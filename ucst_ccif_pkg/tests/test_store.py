"""Tests for the persistent store layer.

The suite runs on SQLite because that is the dialect available on this
machine; the Postgres path is covered by compiling the same metadata with the
Postgres dialect (see ``test_postgres_ddl_compiles``) and by
``python -m ucst_ccif.store --selftest --url <postgres-url>`` against a real
server.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from ucst_ccif.store import METADATA, Store, render_ddl


@pytest.fixture()
def store(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 'ocip.db'}")
    s.ensure_schema()
    yield s
    s.dispose()


ACTIVITY = pd.DataFrame({
    "scope": [1, 2, 3],
    "category": ["fuel", "electricity", "purchased_goods"],
    "activity_key": ["diesel_L", "guangdong", "manufactured_goods"],
    "quantity": [20000.0, 1135589.4, 2000000.0],
})

FLUX = pd.DataFrame({
    "date": ["2023-01-01", "2023-01-02", "2023-01-03"],
    "NEE_daily_total": [3.92, 4.47, -0.12],
    "GPP_daily_total": [2.27, 1.90, 0.98],
    "ER_daily_total": [1.29, 1.14, 0.86],
    "water_level": [2.1, 2.4, None],
})


STOCK = pd.DataFrame({"area_ha": [100.0], "removal_tco2e": [420.0]})

INTERVENTION = pd.DataFrame({
    "scenario": ["wetland_restoration"],
    "baseline_removal_tco2e": [300.0],
    "intervention_removal_tco2e": [420.0],
    "active_fraction": [0.4],
})

FRAMES = {"activity": ACTIVITY, "flux": FLUX, "stock": STOCK,
          "intervention": INTERVENTION}


class _StubReport:
    """Minimal stand-in for ucst_ccif.audit_pipeline.AuditReport."""

    certificate_status = "REVIEW"
    emissions_tco2e = 613.9
    emissions_u95_tco2e = 31.0
    removals_tco2e = None
    removals_u95_tco2e = None
    residual_eC_tco2e = -180.0
    scale_residual_eA_tco2e = None
    leakage_ryg = "amber"
    stages: list = []
    data_gaps = ["stock ledger missing"]

    def artifacts(self):
        return {"audit_certificate": "REVIEW", "conservation_residual_eC": -180.0}

    def summary(self):
        return "stub report"


def test_every_ledger_round_trips(store):
    for ledger, df in FRAMES.items():
        ref = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger=ledger,
                               df=df, file_name=f"{ledger}.csv")
        back = store.ledger_frame(ref.load_id)
        assert len(back) == len(df), ledger
        assert list(back.columns) == list(df.columns), ledger


def test_identical_file_is_deduplicated(store):
    ref = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="activity",
                           df=ACTIVITY, file_name="a.csv")
    again = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="activity",
                             df=ACTIVITY, file_name="a-renamed.csv")
    assert again.load_id == ref.load_id
    assert again.deduplicated is True
    assert len(store.loads(org_id="cityu", site_id="SZ-01")) == 1


def test_changed_bytes_create_a_new_load(store):
    ref = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="activity",
                           df=ACTIVITY, file_name="a.csv")
    changed = ACTIVITY.copy()
    changed.loc[0, "quantity"] = 21000.0
    other = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="activity",
                             df=changed, file_name="a.csv")
    assert other.load_id != ref.load_id
    assert other.deduplicated is False


def test_audit_run_is_traceable_to_its_load(store):
    ref = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="activity",
                           df=ACTIVITY, file_name="a.csv")
    run = store.save_audit(org_id="cityu", site_id="SZ-01", report=_StubReport(),
                           loads={"activity": ref.load_id}, label="q1",
                           created_by="liulinda@cityu")
    payload = store.run_report(run)
    assert payload["certificate_status"] == "REVIEW"
    assert payload["loads"]["activity"] == ref.load_id
    assert payload["report"]["artifacts"]["audit_certificate"] == "REVIEW"

    hist = store.audit_history(org_id="cityu", site_id="SZ-01")
    assert len(hist) == 1
    assert hist.iloc[0]["run_id"] == run
    assert hist.iloc[0]["residual_ec_tco2e"] == pytest.approx(-180.0)


def test_orgs_are_isolated(store):
    df = ACTIVITY.copy()
    store.put_ledger(org_id="org-a", site_id="S", ledger="activity", df=df)
    store.put_ledger(org_id="org-b", site_id="S", ledger="activity", df=df)

    assert len(store.loads(org_id="org-a", site_id="S")) == 1
    assert len(store.loads(org_id="org-b", site_id="S")) == 1
    assert store.counts(org_id="org-c")["ledger_load"] == 0

    store.save_audit(org_id="org-a", site_id="S", report=_StubReport(),
                     loads={}, label="a")
    store.save_audit(org_id="org-b", site_id="S", report=_StubReport(),
                     loads={}, label="b")
    assert len(store.audit_history(org_id="org-a", site_id="S")) == 1
    assert len(store.audit_history(org_id="org-b", site_id="S")) == 1


def test_nan_and_nat_become_null_not_literal(store):
    """Postgres JSONB rejects NaN/Infinity; the bytes we write must be clean.

    Checked on the stored text rather than on a rehydrated DataFrame, because
    pandas turns None back into NaN in a float column.
    """
    df = FLUX.copy()
    df.loc[2, "water_level"] = float("nan")
    ref = store.put_ledger(org_id="cityu", site_id="SZ-01", ledger="flux", df=df)
    with store.engine.connect() as conn:
        raw = "".join(
            conn.exec_driver_sql("select payload from flux_row").scalars().all())
    assert "NaN" not in raw
    assert "Infinity" not in raw
    assert "null" in raw, "missing value should be stored as JSON null"


def test_factor_library_seeds_once(store):
    first = store.seed_factors()
    assert first > 0
    assert store.seed_factors() == 0, "second seed must be a no-op"
    assert len(store.factor_versions()) == first
    factors = store.factor_versions()
    assert (factors["factor_id"] == "grid_ef:guangdong").any()
    guangdong = factors.loc[factors["factor_id"] == "grid_ef:guangdong",
                            "value"].iloc[0]
    assert guangdong == pytest.approx(0.4403)


def test_unknown_ledger_and_missing_rows_are_rejected(store):
    with pytest.raises(ValueError):
        store.put_ledger(org_id="o", site_id="s", ledger="nope", df=ACTIVITY)
    with pytest.raises(ValueError):
        store.put_ledger(org_id="o", site_id="s", ledger="activity",
                         df=ACTIVITY.iloc[0:0])


def test_postgres_ddl_compiles():
    ddl = render_ddl()
    assert "CREATE TABLE ledger_load" in ddl
    assert "JSONB" in ddl
    assert "load_id UUID NOT NULL" in ddl
    assert "CONSTRAINT fk_load_site" in ddl
    assert "ix_audit_run_org_site_time" in ddl
    # the SQLite UUID fallback must not leak into the Postgres script
    assert not re.search(r"\bCHAR\(32\)", ddl)
    assert "CREATE TABLE feedback" in ddl
    assert "CONSTRAINT fk_feedback_site" in ddl
    assert "CREATE TABLE event" in ddl
    assert "CONSTRAINT fk_event_site" in ddl


def test_schema_has_no_global_tables_except_reference_data():
    """Every tenant-owned table must carry org_id; factors are the only exception."""
    exempt = {"org", "site", "factor_version"}
    for name, table in METADATA.tables.items():
        if name in exempt:
            continue
        assert "org_id" in table.c, f"{name} is not tenant-scoped"


def test_feedback_round_trip_and_isolation(store):
    fid = store.add_feedback(org_id="a", site_id="s1", comment="first look",
                             rating=4, tab="6. Data & history", created_by="t@x")
    store.add_feedback(org_id="b", site_id="s2", comment="second look")
    a = store.feedback(org_id="a")
    assert list(a["feedback_id"]) == [fid]
    assert a.iloc[0]["rating"] == 4
    assert a.iloc[0]["site_id"] == "s1"
    b = store.feedback(org_id="b")
    assert set(b["comment"]) == {"second look"}
    # ratings are clamped into 1..5 even if a caller passes nonsense
    store.add_feedback(org_id="a", site_id="s1", comment="clamped", rating=99)
    assert store.feedback(org_id="a")["rating"].max() == 5


def test_feedback_rejects_an_empty_comment(store):
    with pytest.raises(ValueError):
        store.add_feedback(org_id="a", site_id="s1", comment="   ")


def test_events_round_trip_and_isolation(store):
    eid = store.log_event(org_id="a", site_id="s1", verb="app_open",
                          detail={"page": "tab1"}, created_by="t@x")
    store.log_event(org_id="b", site_id="s2", verb="app_open")
    ev = store.events(org_id="a")
    assert list(ev["event_id"]) == [eid]
    assert ev.iloc[0]["detail"] == {"page": "tab1"}
    funnel = store.funnel(org_id="a")
    assert list(funnel["verb"]) == ["app_open"]
    assert store.counts(org_id="a")["event"] == 1


def test_event_rejects_an_empty_verb(store):
    with pytest.raises(ValueError):
        store.log_event(org_id="a", site_id="s1", verb="   ")


def test_digest_reports_one_row_per_org(store):
    store.add_feedback(org_id="a", site_id="s1", comment="looks right", rating=5)
    store.add_feedback(org_id="b", site_id="s2", comment="confused")
    d = store.digest()
    assert set(d["org_id"]) == {"a", "b"}
    row_a = d[d["org_id"] == "a"].iloc[0]
    assert row_a["feedback"] == 1
    assert row_a["avg_rating"] == 5.0
    assert row_a["last_activity"] is not None
    row_b = d[d["org_id"] == "b"].iloc[0]
    assert row_b["loads"] == 0 and row_b["runs"] == 0
    assert row_b["avg_rating"] != row_b["avg_rating"]  # NaN: no rating given


def test_digest_counts_events(store):
    store.log_event(org_id="a", site_id="s1", verb="app_open")
    store.log_event(org_id="a", site_id="s1", verb="audit_run")
    d = store.digest()
    assert d[d["org_id"] == "a"].iloc[0]["events"] == 2
