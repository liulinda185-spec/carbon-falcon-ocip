"""Headless boot tests for the Streamlit app.

These catch the failure mode that matters most here: adding a database must
never break the app when the database is absent.
"""

from __future__ import annotations

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

APP = pathlib.Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def _run(**kwargs) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    return at


def test_app_boots_without_a_database(monkeypatch):
    monkeypatch.delenv("OCIP_DATABASE_URL", raising=False)
    at = _run()
    assert not at.exception, [str(e.value) for e in at.exception]
    # the degraded path must say so rather than pretend persistence works
    warnings = " ".join(w.value for w in at.warning)
    assert "session-only" in warnings


def test_app_boots_and_stores_with_sqlite(monkeypatch, tmp_path):
    db = tmp_path / "app.db"
    monkeypatch.setenv("OCIP_DATABASE_URL", f"sqlite:///{db}")
    at = _run()
    assert not at.exception, [str(e.value) for e in at.exception]

    from ucst_ccif.store import Store

    store = Store(f"sqlite:///{db}")
    # the app seeds the reference factor library on first boot
    assert len(store.factor_versions()) > 0
    # and reports the linked state in the sidebar
    successes = " ".join(s.value for s in at.success)
    assert "persisted" in successes
    store.dispose()


ACTIVITY_CSV = (
    "# Activity ledger — full names & units\n"
    "scope,category,activity_key,quantity\n"
    "2,electricity,guangdong,1135589.4\n"
    "1,fuel,diesel_L,20000\n"
)


def test_upload_then_audit_is_persisted(monkeypatch, tmp_path):
    """End to end through the real widgets: upload → run → rows in the store."""
    db = tmp_path / "e2e.db"
    monkeypatch.setenv("OCIP_DATABASE_URL", f"sqlite:///{db}")

    at = _run()
    # a linked database requires an explicit acknowledgement of the data notice
    at.checkbox(key="ocip_consent").check()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    at.file_uploader(key="up_activity").set_value(
        ("activity.csv", ACTIVITY_CSV.encode("utf-8"), "text/csv"))
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    run_buttons = [b for b in at.button if b.label == "Run the audit"]
    assert run_buttons, "audit button not found"
    run_buttons[0].click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    from ucst_ccif.store import Store

    store = Store(f"sqlite:///{db}")
    loads = store.loads(org_id="demo", site_id="GBA-DEMO-01")
    assert len(loads) == 1
    assert loads.iloc[0]["ledger_type"] == "activity"
    assert loads.iloc[0]["row_count"] == 2

    runs = store.audit_history(org_id="demo", site_id="GBA-DEMO-01")
    assert len(runs) == 1
    assert runs.iloc[0]["certificate_status"]

    payload = store.run_report(runs.iloc[0]["run_id"])
    assert payload["loads"]["activity"] == loads.iloc[0]["load_id"]

    # tab 6 counters reflect the stored rows
    labels = {m.label: m.value for m in at.metric}
    assert labels["Audit runs"] == "1"
    assert labels["Ledger loads"] == "1"

    # the step-level funnel recorded the same session
    verbs = set(store.events(org_id="demo")["verb"])
    assert "app_open" in verbs
    assert "audit_run" in verbs
    store.dispose()


def test_demo_mode_ignores_a_configured_database(monkeypatch, tmp_path):
    """The public sandbox must be unable to write, even with a URL present."""
    db = tmp_path / "demo.db"
    monkeypatch.setenv("OCIP_DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("OCIP_DEMO_MODE", "1")

    at = _run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert "demo sandbox" in " ".join(i.value for i in at.info).lower()

    # sample data is preloaded, so a visitor reaches a certificate immediately
    run_buttons = [b for b in at.button if b.label == "Run the audit"]
    assert run_buttons, "audit button not found"
    run_buttons[0].click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert any(m.label.startswith("Verified") for m in at.metric)

    assert not db.exists(), "demo mode opened the database"


def test_public_trial_counts_steps_but_stores_no_files(monkeypatch, tmp_path):
    """Share-one-link mode: events land, ledgers never do, nobody is identified."""
    db = tmp_path / "public.db"
    monkeypatch.setenv("OCIP_DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("OCIP_TELEMETRY_ONLY", "1")

    at = _run()
    assert not at.exception, [str(e.value) for e in at.exception]
    infos = " ".join(i.value for i in at.info).lower()
    assert "public trial" in infos

    run_buttons = [b for b in at.button if b.label == "Run the audit"]
    assert run_buttons, "audit button not found"
    run_buttons[0].click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert any(m.label.startswith("Verified") for m in at.metric)

    from ucst_ccif.store import Store

    store = Store(f"sqlite:///{db}")
    counts = store.counts(org_id="public")
    assert counts["event"] >= 2, "steps were not recorded"
    assert counts["ledger_load"] == 0, "a public trial stored a ledger"
    assert counts["audit_run"] == 0, "a public trial stored an audit"
    ev = store.events(org_id="public")
    assert set(ev["created_by"].dropna()) == set(), "an email was recorded"
    assert store.feedback(org_id="public").empty
    store.dispose()


def test_feedback_is_stored(monkeypatch, tmp_path):
    db = tmp_path / "fb.db"
    monkeypatch.setenv("OCIP_DATABASE_URL", f"sqlite:///{db}")

    at = _run()
    at.text_area(key="ocip_fb_comment").set_value(
        "I did not know which column the flux ledger expected.")
    send = [b for b in at.button if b.label == "Send feedback"]
    assert send, "feedback submit button not found"
    # set_value and click must land in the same run: a form only ships its
    # widget values to the server when it is submitted
    send[0].click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    from ucst_ccif.store import Store

    store = Store(f"sqlite:///{db}")
    rows = store.feedback(org_id="demo")
    assert len(rows) == 1
    assert "flux ledger" in rows.iloc[0]["comment"]
    assert rows.iloc[0]["site_id"] == "GBA-DEMO-01"
    store.dispose()
