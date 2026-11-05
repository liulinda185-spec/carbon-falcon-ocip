"""
OCIP persistent store — PostgreSQL for multi-user deployments, SQLite for
local development.

Why this shape
--------------
* Every row is scoped by ``(org_id, site_id)``. Nothing is global except the
  reference factor library, so two tenants never see each other's ledgers.
* A ledger upload is stored as an immutable **load**: one record per file with
  its SHA-256, plus the parsed rows. Re-uploading identical bytes returns the
  same ``load_id`` instead of rewriting history — an audit certificate that
  points at a load always points at the same rows.
* An **audit run** stores the eight artifacts as JSON next to the headline
  figures, and the four load ids it consumed. That is the whole audit trail:
  certificate → run → loads → file checksums.

Connection string
-----------------
``postgresql+psycopg://user:pass@host:5432/db?sslmode=require``  (Neon / Supabase / RDS)
``sqlite:///ocip.db``                                            (local only)

The module imports SQLAlchemy at import time; the Streamlit app imports it
lazily so the app still runs when the dependency or the database is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Optional

import pandas as pd
import sqlalchemy as sa

LEDGERS: tuple[str, ...] = ("activity", "flux", "stock", "intervention")

#: Bump when the DDL changes in a way that needs a migration.
SCHEMA_VERSION = "3"

DT = sa.DateTime(timezone=True)


# ---------------------------------------------------------------------------
# value helpers — Postgres JSONB rejects NaN, SQLite stores whatever it likes,
# so normalise once and both behave the same.
# ---------------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalars into JSON-safe Python."""
    if obj is None:
        return None
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if obj is pd.NaT:
        return None
    # numpy scalars and everything else with .item()
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:  # noqa: BLE001
            pass
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Row dicts with cleaned keys and JSON-safe values."""
    out = []
    for raw in df.to_dict("records"):
        out.append({str(k): _jsonable(v) for k, v in raw.items()})
    return out


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    return None if f is None else int(round(f))


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if ts is None or pd.isna(ts):
        return None
    return ts.date()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_type() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON elsewhere."""
    try:  # pragma: no cover - import is dialect-gated
        from sqlalchemy.dialects.postgresql import JSONB

        return sa.JSON().with_variant(JSONB, "postgresql")
    except ImportError:  # pragma: no cover
        return sa.JSON()


def _uuid_type() -> sa.types.TypeEngine:
    """UUID on Postgres, CHAR(32) elsewhere; carried as str in Python."""
    return sa.Uuid(as_uuid=False)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def build_metadata() -> sa.MetaData:
    md = sa.MetaData()

    sa.Table(
        "org", md,
        sa.Column("org_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, default=""),
        sa.Column("created_at", DT, nullable=False),
    )

    sa.Table(
        "site", md,
        sa.Column("org_id", sa.String(64),
                  sa.ForeignKey("org.org_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("site_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200)),
        sa.Column("area_ha", sa.Float),
        sa.Column("grid_region", sa.String(32)),
        sa.Column("updated_at", DT, nullable=False),
    )

    sa.Table(
        "ledger_load", md,
        sa.Column("load_id", _uuid_type(), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("ledger_type", sa.String(16), nullable=False),
        sa.Column("file_name", sa.String(255)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("columns", _json_type(), nullable=False),
        sa.Column("loaded_at", DT, nullable=False),
        sa.Column("loaded_by", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["site.org_id", "site.site_id"],
            ondelete="CASCADE", name="fk_load_site"),
        sa.UniqueConstraint("org_id", "site_id", "ledger_type", "sha256",
                            name="uq_ledger_load_identity"),
    )

    for name, extra in (
        ("activity_row", [
            sa.Column("scope", sa.Integer),
            sa.Column("category", sa.String(64)),
            sa.Column("activity_key", sa.String(128)),
            sa.Column("quantity", sa.Float),
        ]),
        ("flux_row", [
            sa.Column("date", sa.Date),
            sa.Column("nee_daily_total", sa.Float),
            sa.Column("gpp_daily_total", sa.Float),
            sa.Column("er_daily_total", sa.Float),
        ]),
        ("stock_row", [
            sa.Column("area_ha", sa.Float),
            sa.Column("removal_tco2e", sa.Float),
        ]),
        ("intervention_row", [
            sa.Column("scenario", sa.String(128)),
            sa.Column("baseline_removal_tco2e", sa.Float),
            sa.Column("intervention_removal_tco2e", sa.Float),
            sa.Column("active_fraction", sa.Float),
        ]),
    ):
        t = sa.Table(
            name, md,
            sa.Column("load_id", _uuid_type(),
                      sa.ForeignKey("ledger_load.load_id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("row_no", sa.Integer, primary_key=True),
            # denormalised so a Postgres RLS policy can scope the row tables
            # directly, instead of trusting every query to join through the load
            sa.Column("org_id", sa.String(64), nullable=False),
            *extra,
            sa.Column("payload", _json_type(), nullable=False),
        )
        sa.Index(f"ix_{name}_org", t.c.org_id)

    audit = sa.Table(
        "audit_run", md,
        sa.Column("run_id", _uuid_type(), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(200)),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.Column("certificate_status", sa.String(40)),
        sa.Column("emissions_tco2e", sa.Float),
        sa.Column("emissions_u95_tco2e", sa.Float),
        sa.Column("removals_tco2e", sa.Float),
        sa.Column("removals_u95_tco2e", sa.Float),
        sa.Column("residual_ec_tco2e", sa.Float),
        sa.Column("scale_residual_ea_tco2e", sa.Float),
        sa.Column("leakage_ryg", sa.String(16)),
        sa.Column("area_ha", sa.Float),
        sa.Column("claimed_removals_tco2e", sa.Float),
        sa.Column("grid_region", sa.String(32)),
        sa.Column("agent_col", sa.String(128)),
        sa.Column("loads", _json_type(), nullable=False),
        sa.Column("report", _json_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["site.org_id", "site.site_id"],
            ondelete="CASCADE", name="fk_run_site"),
    )
    sa.Index("ix_audit_run_org_site_time", audit.c.org_id, audit.c.site_id,
             audit.c.created_at.desc())

    fb = sa.Table(
        "feedback", md,
        sa.Column("feedback_id", _uuid_type(), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("run_id", _uuid_type(), nullable=True),
        sa.Column("tab", sa.String(64)),
        sa.Column("rating", sa.Integer),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("contact_email", sa.String(256)),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["site.org_id", "site.site_id"],
            ondelete="CASCADE", name="fk_feedback_site"),
    )
    sa.Index("ix_feedback_org_time", fb.c.org_id, fb.c.created_at.desc())

    # Step-level telemetry for a pilot: which actions a tester reached, never
    # what they typed. No IP, no user agent, no free text — `detail` holds only
    # small fixed fields such as {"ledger": "activity", "rows": 365}.
    ev = sa.Table(
        "event", md,
        sa.Column("event_id", _uuid_type(), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("verb", sa.String(48), nullable=False),
        sa.Column("detail", _json_type(), nullable=True),
        sa.Column("at", DT, nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["site.org_id", "site.site_id"],
            ondelete="CASCADE", name="fk_event_site"),
    )
    sa.Index("ix_event_org_time", ev.c.org_id, ev.c.at.desc())

    sa.Table(
        "factor_version", md,
        sa.Column("factor_id", sa.String(80), primary_key=True),
        sa.Column("version", sa.String(40), primary_key=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(48), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("vintage_year", sa.Integer),
        sa.Column("seeded_at", DT, nullable=False),
    )

    return md


METADATA = build_metadata()


@dataclass(frozen=True)
class LoadRef:
    """Result of storing one ledger file."""

    load_id: str
    ledger_type: str
    row_count: int
    sha256: str
    deduplicated: bool


class Store:
    """Thin, explicit data-access layer. No ORM objects, no implicit sessions."""

    def __init__(self, url: str, *, echo: bool = False):
        if not url or "://" not in url:
            raise ValueError(f"invalid database url: {url!r}")
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo, "future": True,
                                  "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update({"pool_size": 5, "max_overflow": 5,
                           "pool_recycle": 1800})
        self.engine = sa.create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            # foreign_keys is per-connection and OFF by default in SQLite; without
            # this the ON DELETE CASCADE on ledger rows would never fire.
            @sa.event.listens_for(self.engine, "connect")
            def _enable_fk(dbapi_conn, _record):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        self._ready = False

    # -- lifecycle ---------------------------------------------------------
    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    def ensure_schema(self) -> None:
        """Create missing tables. Safe to call on every boot."""
        if self._ready:
            return
        METADATA.create_all(self.engine)
        self._ready = True

    def health(self) -> dict[str, Any]:
        probe = ("select sqlite_version()" if self.dialect == "sqlite"
                 else "select version()")
        with self.engine.connect() as conn:
            version = conn.execute(sa.text(probe)).scalar_one()
        return {"dialect": self.dialect, "server": str(version)[:120],
                "schema_version": SCHEMA_VERSION,
                "tables": sorted(METADATA.tables)}

    def dispose(self) -> None:
        self.engine.dispose()

    # -- identity ----------------------------------------------------------
    def upsert_org(self, conn, org_id: str, name: str | None = None) -> None:
        org = METADATA.tables["org"]
        if conn.execute(sa.select(org.c.org_id)
                        .where(org.c.org_id == org_id)).first():
            return
        conn.execute(sa.insert(org).values(
            org_id=org_id, name=name or org_id, created_at=_now()))

    def upsert_site(self, conn, org_id: str, site_id: str, *,
                    area_ha: float | None = None,
                    grid_region: str | None = None,
                    name: str | None = None) -> None:
        site = METADATA.tables["site"]
        row = conn.execute(
            sa.select(site).where(site.c.org_id == org_id,
                                  site.c.site_id == site_id)).mappings().first()
        if row is None:
            conn.execute(sa.insert(site).values(
                org_id=org_id, site_id=site_id, name=name or site_id,
                area_ha=area_ha, grid_region=grid_region, updated_at=_now()))
            return
        patch = {}
        if area_ha is not None:
            patch["area_ha"] = area_ha
        if grid_region is not None:
            patch["grid_region"] = grid_region
        if name is not None:
            patch["name"] = name
        if patch:
            patch["updated_at"] = _now()
            conn.execute(sa.update(site)
                         .where(site.c.org_id == org_id,
                                site.c.site_id == site_id)
                         .values(**patch))

    # -- ledgers -----------------------------------------------------------
    def put_ledger(self, *, org_id: str, site_id: str, ledger: str,
                   df: pd.DataFrame, file_name: str = "upload.csv",
                   loaded_by: str | None = None) -> LoadRef:
        """Store one ledger file. Idempotent on identical bytes."""
        if ledger not in LEDGERS:
            raise ValueError(f"unknown ledger {ledger!r}; expected {LEDGERS}")
        if df is None or len(df) == 0:
            raise ValueError(f"{ledger} ledger is empty")

        df = df.copy()
        df.columns = [str(c) for c in df.columns]
        canonical = df.to_csv(index=False).encode("utf-8")
        sha = hashlib.sha256(canonical).hexdigest()

        with self.engine.begin() as conn:
            self.upsert_org(conn, org_id)
            self.upsert_site(conn, org_id, site_id)

            load_t = METADATA.tables["ledger_load"]
            existing = conn.execute(
                sa.select(load_t.c.load_id, load_t.c.row_count)
                .where(load_t.c.org_id == org_id,
                       load_t.c.site_id == site_id,
                       load_t.c.ledger_type == ledger,
                       load_t.c.sha256 == sha)).first()
            if existing is not None:
                return LoadRef(load_id=str(existing[0]), ledger_type=ledger,
                               row_count=int(existing[1]), sha256=sha,
                               deduplicated=True)

            load_id = str(uuid.uuid4())
            rows = self._rows_for(ledger, df, load_id, org_id)
            table = METADATA.tables[f"{ledger}_row"]
            try:
                with conn.begin_nested():
                    conn.execute(sa.insert(load_t).values(
                        load_id=load_id, org_id=org_id, site_id=site_id,
                        ledger_type=ledger, file_name=file_name, sha256=sha,
                        row_count=len(df), columns=list(df.columns),
                        loaded_at=_now(), loaded_by=loaded_by))
                    for start in range(0, len(rows), 20_000):
                        conn.execute(sa.insert(table), rows[start:start + 20_000])
            except sa.exc.IntegrityError:
                # A concurrent session stored the same bytes between our check
                # and our insert. The unique constraint did its job; adopt the
                # winner's load instead of failing the upload.
                existing = conn.execute(
                    sa.select(load_t.c.load_id, load_t.c.row_count)
                    .where(load_t.c.org_id == org_id,
                           load_t.c.site_id == site_id,
                           load_t.c.ledger_type == ledger,
                           load_t.c.sha256 == sha)).first()
                if existing is None:
                    raise
                return LoadRef(load_id=str(existing[0]), ledger_type=ledger,
                               row_count=int(existing[1]), sha256=sha,
                               deduplicated=True)

        return LoadRef(load_id=load_id, ledger_type=ledger,
                       row_count=len(df), sha256=sha, deduplicated=False)

    @staticmethod
    def _rows_for(ledger: str, df: pd.DataFrame,
                  load_id: str, org_id: str) -> list[dict[str, Any]]:
        recs = _records(df)

        def base(i: int, rec: dict[str, Any]) -> dict[str, Any]:
            return {"load_id": load_id, "row_no": i, "org_id": org_id,
                    "payload": rec}

        if ledger == "activity":
            return [dict(base(i, r),
                         scope=_as_int(r.get("scope")),
                         category=_as_str(r.get("category")),
                         activity_key=_as_str(r.get("activity_key")),
                         quantity=_as_float(r.get("quantity")))
                    for i, r in enumerate(recs)]
        if ledger == "flux":
            return [dict(base(i, r),
                         date=_as_date(r.get("date")),
                         nee_daily_total=_as_float(r.get("NEE_daily_total")),
                         gpp_daily_total=_as_float(r.get("GPP_daily_total")),
                         er_daily_total=_as_float(r.get("ER_daily_total")))
                    for i, r in enumerate(recs)]
        if ledger == "stock":
            return [dict(base(i, r),
                         area_ha=_as_float(r.get("area_ha")),
                         removal_tco2e=_as_float(r.get("removal_tco2e")))
                    for i, r in enumerate(recs)]
        return [dict(base(i, r),
                     scenario=_as_str(r.get("scenario")),
                     baseline_removal_tco2e=_as_float(
                         r.get("baseline_removal_tco2e")),
                     intervention_removal_tco2e=_as_float(
                         r.get("intervention_removal_tco2e")),
                     active_fraction=_as_float(r.get("active_fraction")))
                for i, r in enumerate(recs)]

    def ledger_frame(self, load_id: str) -> pd.DataFrame:
        """Rehydrate a stored ledger exactly as the audit received it."""
        load_t = METADATA.tables["ledger_load"]
        with self.engine.begin() as conn:
            head = conn.execute(
                sa.select(load_t.c.ledger_type).where(
                    load_t.c.load_id == load_id)).scalar_one_or_none()
            if head is None:
                raise KeyError(f"no such load: {load_id}")
            rows = conn.execute(
                sa.select(METADATA.tables[f"{head}_row"].c.payload)
                .where(METADATA.tables[f"{head}_row"].c.load_id == load_id)
                .order_by(METADATA.tables[f"{head}_row"].c.row_no)
            ).scalars().all()
        return pd.DataFrame([json.loads(r) if isinstance(r, str) else r
                             for r in rows])

    # -- audits ------------------------------------------------------------
    def save_audit(self, *, org_id: str, site_id: str, report: Any,
                   loads: Mapping[str, str | None],
                   label: str | None = None,
                   created_by: str | None = None,
                   area_ha: float | None = None,
                   claimed_removals_tco2e: float | None = None,
                   grid_region: str | None = None,
                   agent_col: str | None = None) -> str:
        """Persist one AuditReport plus the load ids it consumed."""
        run_id = str(uuid.uuid4())
        artifacts = report.artifacts() if hasattr(report, "artifacts") else {}
        payload = {
            "certificate_status": getattr(report, "certificate_status", None),
            "artifacts": _jsonable(artifacts),
            "stages": [
                {"stage": s.stage, "name": s.name, "status": s.status,
                 "detail": s.detail}
                for s in getattr(report, "stages", [])
            ],
            "data_gaps": _jsonable(getattr(report, "data_gaps", [])),
            "summary": getattr(report, "summary", lambda: "")(),
        }
        clean_loads = {k: v for k, v in dict(loads).items() if v}

        with self.engine.begin() as conn:
            self.upsert_org(conn, org_id)
            self.upsert_site(conn, org_id, site_id, area_ha=area_ha,
                             grid_region=grid_region)
            conn.execute(sa.insert(METADATA.tables["audit_run"]).values(
                run_id=run_id, org_id=org_id, site_id=site_id,
                label=label, created_at=_now(), created_by=created_by,
                certificate_status=getattr(report, "certificate_status", None),
                emissions_tco2e=_as_float(getattr(report, "emissions_tco2e", None)),
                emissions_u95_tco2e=_as_float(
                    getattr(report, "emissions_u95_tco2e", None)),
                removals_tco2e=_as_float(getattr(report, "removals_tco2e", None)),
                removals_u95_tco2e=_as_float(
                    getattr(report, "removals_u95_tco2e", None)),
                residual_ec_tco2e=_as_float(
                    getattr(report, "residual_eC_tco2e", None)),
                scale_residual_ea_tco2e=_as_float(
                    getattr(report, "scale_residual_eA_tco2e", None)),
                leakage_ryg=getattr(report, "leakage_ryg", None),
                area_ha=area_ha,
                claimed_removals_tco2e=claimed_removals_tco2e,
                grid_region=grid_region, agent_col=agent_col,
                loads=_jsonable(clean_loads), report=payload))
        return run_id

    # -- reads -------------------------------------------------------------
    def _frame(self, stmt) -> pd.DataFrame:
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return pd.DataFrame([dict(r) for r in rows])

    def audit_history(self, *, org_id: str, site_id: str | None = None,
                      limit: int = 200) -> pd.DataFrame:
        raw = METADATA.tables["audit_run"]
        cols = ["run_id", "label", "created_at", "created_by",
                "certificate_status", "emissions_tco2e", "removals_tco2e",
                "residual_ec_tco2e", "leakage_ryg", "area_ha", "grid_region"]
        stmt = sa.select(*[raw.c[c] for c in cols]).where(raw.c.org_id == org_id)
        if site_id:
            stmt = stmt.where(raw.c.site_id == site_id)
        stmt = stmt.order_by(raw.c.created_at.desc()).limit(limit)
        return self._frame(stmt)

    def loads(self, *, org_id: str, site_id: str | None = None,
              limit: int = 500) -> pd.DataFrame:
        load_t = METADATA.tables["ledger_load"]
        cols = ["load_id", "ledger_type", "file_name", "sha256", "row_count",
                "loaded_at", "loaded_by"]
        stmt = sa.select(*[load_t.c[c] for c in cols]).where(
            load_t.c.org_id == org_id)
        if site_id:
            stmt = stmt.where(load_t.c.site_id == site_id)
        stmt = stmt.order_by(load_t.c.loaded_at.desc()).limit(limit)
        return self._frame(stmt)

    def run_report(self, run_id: str) -> dict[str, Any]:
        raw = METADATA.tables["audit_run"]
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(raw.c.report, raw.c.loads, raw.c.created_at,
                          raw.c.certificate_status)
                .where(raw.c.run_id == run_id)).mappings().first()
        if row is None:
            raise KeyError(f"no such run: {run_id}")
        report = row["report"]
        return {"report": json.loads(report) if isinstance(report, str) else report,
                "loads": json.loads(row["loads"]) if isinstance(row["loads"], str)
                else row["loads"],
                "created_at": row["created_at"],
                "certificate_status": row["certificate_status"]}

    # -- feedback ----------------------------------------------------------
    def add_feedback(self, *, org_id: str, site_id: str, comment: str,
                     rating: int | None = None, tab: str | None = None,
                     run_id: str | None = None,
                     contact_email: str | None = None,
                     created_by: str | None = None) -> str:
        """Store one piece of tester feedback. Empty comments are rejected."""
        text = (comment or "").strip()
        if not text:
            raise ValueError("feedback comment is empty")
        feedback_id = str(uuid.uuid4())
        clean_rating = None if rating is None else max(1, min(5, int(rating)))
        with self.engine.begin() as conn:
            self.upsert_org(conn, org_id)
            self.upsert_site(conn, org_id, site_id)
            conn.execute(sa.insert(METADATA.tables["feedback"]).values(
                feedback_id=feedback_id, org_id=org_id, site_id=site_id,
                run_id=run_id, tab=_as_str(tab), rating=clean_rating,
                comment=text, contact_email=_as_str(contact_email),
                created_at=_now(), created_by=created_by))
        return feedback_id

    def feedback(self, *, org_id: str | None = None,
                 site_id: str | None = None, limit: int = 500) -> pd.DataFrame:
        raw = METADATA.tables["feedback"]
        cols = ["feedback_id", "org_id", "site_id", "tab", "rating", "comment",
                "contact_email", "created_at", "created_by"]
        stmt = sa.select(*[raw.c[c] for c in cols])
        if org_id:
            stmt = stmt.where(raw.c.org_id == org_id)
        if site_id:
            stmt = stmt.where(raw.c.site_id == site_id)
        stmt = stmt.order_by(raw.c.created_at.desc()).limit(limit)
        return self._frame(stmt)

    # -- step-level telemetry ----------------------------------------------
    def log_event(self, *, org_id: str, site_id: str, verb: str,
                  detail: Mapping[str, Any] | None = None,
                  created_by: str | None = None) -> str:
        """Record one UI step. Never call this from the public sandbox."""
        name = (verb or "").strip()
        if not name:
            raise ValueError("event verb is empty")
        event_id = str(uuid.uuid4())
        payload = _jsonable(dict(detail)) if detail else None
        with self.engine.begin() as conn:
            self.upsert_org(conn, org_id)
            self.upsert_site(conn, org_id, site_id)
            conn.execute(sa.insert(METADATA.tables["event"]).values(
                event_id=event_id, org_id=org_id, site_id=site_id, verb=name,
                detail=payload, at=_now(), created_by=created_by))
        return event_id

    def events(self, *, org_id: str | None = None, site_id: str | None = None,
               limit: int = 500) -> pd.DataFrame:
        raw = METADATA.tables["event"]
        cols = ["event_id", "org_id", "site_id", "verb", "detail", "at",
                "created_by"]
        stmt = sa.select(*[raw.c[c] for c in cols])
        if org_id:
            stmt = stmt.where(raw.c.org_id == org_id)
        if site_id:
            stmt = stmt.where(raw.c.site_id == site_id)
        stmt = stmt.order_by(raw.c.at.desc()).limit(limit)
        return self._frame(stmt)

    def funnel(self, *, org_id: str) -> pd.DataFrame:
        """Counts per verb for one org — the funnel in a single call."""
        raw = METADATA.tables["event"]
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(raw.c.verb, sa.func.count())
                .where(raw.c.org_id == org_id)
                .group_by(raw.c.verb)).all()
        frame = pd.DataFrame([{"verb": v, "count": int(c)} for v, c in rows])
        if not frame.empty:
            frame = frame.sort_values("count", ascending=False)
        return frame.reset_index(drop=True)

    # -- reference factors -------------------------------------------------
    def seed_factors(self) -> int:
        """Write the emission-factor registry into the DB (idempotent)."""
        rows = factor_rows()
        if not rows:
            return 0
        table = METADATA.tables["factor_version"]
        inserted = 0
        with self.engine.begin() as conn:
            for row in rows:
                exists = conn.execute(
                    sa.select(table.c.factor_id).where(
                        table.c.factor_id == row["factor_id"],
                        table.c.version == row["version"])).first()
                if exists:
                    continue
                conn.execute(sa.insert(table).values(**row, seeded_at=_now()))
                inserted += 1
        return inserted

    def factor_versions(self) -> pd.DataFrame:
        table = METADATA.tables["factor_version"]
        return self._frame(
            sa.select(table.c.factor_id, table.c.version, table.c.value,
                      table.c.unit, table.c.source, table.c.vintage_year)
            .order_by(table.c.factor_id, table.c.version))

    # -- maintenance -------------------------------------------------------
    def digest(self) -> pd.DataFrame:
        """Operator view: one row per organisation.

        This is the only place that reads across tenants, so it exists for the
        person who runs the deployment and must never be wired into the app UI.
        """
        org_t = METADATA.tables["org"]
        with self.engine.connect() as conn:
            orgs = [r[0] for r in conn.execute(sa.select(org_t.c.org_id)).all()]
        rows: list[dict[str, Any]] = []
        for org_id in orgs:
            load_t = METADATA.tables["ledger_load"]
            run_t = METADATA.tables["audit_run"]
            fb_t = METADATA.tables["feedback"]
            ev_t = METADATA.tables["event"]
            with self.engine.connect() as conn:
                loads = int(conn.execute(
                    sa.select(sa.func.count()).select_from(load_t)
                    .where(load_t.c.org_id == org_id)).scalar_one())
                runs = int(conn.execute(
                    sa.select(sa.func.count()).select_from(run_t)
                    .where(run_t.c.org_id == org_id)).scalar_one())
                fbs = int(conn.execute(
                    sa.select(sa.func.count()).select_from(fb_t)
                    .where(fb_t.c.org_id == org_id)).scalar_one())
                evs = int(conn.execute(
                    sa.select(sa.func.count()).select_from(ev_t)
                    .where(ev_t.c.org_id == org_id)).scalar_one())
                rating = conn.execute(
                    sa.select(sa.func.avg(fb_t.c.rating))
                    .where(fb_t.c.org_id == org_id)).scalar_one()
                stamps = [
                    conn.execute(sa.select(sa.func.max(load_t.c.loaded_at))
                                 .where(load_t.c.org_id == org_id)).scalar_one(),
                    conn.execute(sa.select(sa.func.max(run_t.c.created_at))
                                 .where(run_t.c.org_id == org_id)).scalar_one(),
                    conn.execute(sa.select(sa.func.max(fb_t.c.created_at))
                                 .where(fb_t.c.org_id == org_id)).scalar_one(),
                    conn.execute(sa.select(sa.func.max(ev_t.c.at))
                                 .where(ev_t.c.org_id == org_id)).scalar_one(),
                ]
            seen = [s for s in stamps if s is not None]
            rows.append({
                "org_id": org_id,
                "loads": loads,
                "runs": runs,
                "feedback": fbs,
                "events": evs,
                "avg_rating": round(float(rating), 2) if rating is not None else None,
                "last_activity": max(seen) if seen else None,
            })
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values("last_activity", ascending=False,
                                      na_position="last")
        return frame.reset_index(drop=True)

    def counts(self, *, org_id: str, site_id: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in ("ledger_load", "audit_run", "feedback", "event"):
            t = METADATA.tables[name]
            stmt = sa.select(sa.func.count()).select_from(t).where(
                t.c.org_id == org_id)
            if site_id:
                stmt = stmt.where(t.c.site_id == site_id)
            with self.engine.connect() as conn:
                out[name] = int(conn.execute(stmt).scalar_one())
        return out


# ---------------------------------------------------------------------------
# factor registry — mirrors ucst_ccif.emission_factors so the numbers live in
# a table instead of only in code.
# ---------------------------------------------------------------------------
def factor_rows() -> list[dict[str, Any]]:
    from . import emission_factors as ef

    rows: list[dict[str, Any]] = []
    for region, value in ef.GRID_FACTORS_MEE_2022.items():
        rows.append({"factor_id": f"grid_ef:{region}", "version": "MEE-2022",
                     "value": float(value), "unit": "kgCO2/kWh",
                     "source": ef.GRID_SOURCE, "vintage_year": 2022})
    rows.append({"factor_id": "grid_ef:guangdong_epd", "version": "GD-EPD",
                 "value": float(ef.GUANGDONG_EPD_FACTOR), "unit": "kgCO2/kWh",
                 "source": "Guangdong EPD provincial reporting factor",
                 "vintage_year": None})
    for key, fuel in ef.FUELS.items():
        rows.append({"factor_id": f"fuel:{key}", "version": "MEE-AppA",
                     "value": float(fuel.ef_kgCO2_unit),
                     "unit": f"kgCO2/{fuel.unit}",
                     "source": "MEE 发电设施核算指南 App.A", "vintage_year": None})
    rows.append({"factor_id": "scope3:td_loss_rate", "version": "CN-grid",
                 "value": float(ef.TD_LOSS_RATE), "unit": "fraction",
                 "source": "China grid average T&D loss", "vintage_year": None})
    for name, value in ef.TRAVEL_FACTORS.items():
        rows.append({"factor_id": f"scope3:travel:{name}", "version": "DEFRA",
                     "value": float(value), "unit": "kgCO2/passenger-km",
                     "source": "DEFRA / ICAO-style default", "vintage_year": None})
    for name, value in ef.COMMUTE_FACTORS.items():
        rows.append({"factor_id": f"scope3:commute:{name}", "version": "OCIP",
                     "value": float(value), "unit": "kgCO2/km/passenger",
                     "source": "OCIP default", "vintage_year": None})
    for name, value in ef.SPEND_FACTORS.items():
        rows.append({"factor_id": f"scope3:spend:{name}", "version": "OCIP",
                     "value": float(value), "unit": "kgCO2/CNY",
                     "source": "IO-derived rough factor", "vintage_year": None})
    return rows


# ---------------------------------------------------------------------------
# CLI: --ddl (print Postgres DDL), --selftest (round-trip), --digest (usage)
# ---------------------------------------------------------------------------
def render_ddl() -> str:
    """Postgres DDL for the schema, generated from the same metadata."""
    import sqlalchemy.dialects.postgresql  # noqa: F401  (register the dialect)
    from sqlalchemy.schema import CreateIndex, CreateTable

    pg = sa.dialects.postgresql.dialect()
    out = [f"-- OCIP schema v{SCHEMA_VERSION} — generated, do not hand-edit",
           "-- psql -f schema.sql  (or let Store.ensure_schema() create it)", ""]
    for table in METADATA.sorted_tables:
        out.append(str(CreateTable(table).compile(dialect=pg)).strip() + ";")
    for table in METADATA.sorted_tables:
        for index in table.indexes:
            out.append(str(CreateIndex(index).compile(dialect=pg)).strip() + ";")
    return "\n".join(out) + "\n"


def _selftest(url: str) -> int:
    store = Store(url)
    store.ensure_schema()
    health = store.health()
    print(f"connected: {health['dialect']} — {health['server']}")
    print(f"tables: {', '.join(health['tables'])}")

    org, site = "__selftest__", "__selftest__"
    df = pd.DataFrame({"scope": [1, 2], "category": ["fuel", "electricity"],
                       "activity_key": ["diesel_L", "guangdong"],
                       "quantity": [20000.0, 1135589.4]})
    ref = store.put_ledger(org_id=org, site_id=site, ledger="activity",
                           df=df, file_name="selftest.csv")
    print(f"insert load: {ref.load_id} rows={ref.row_count} "
          f"dedup={ref.deduplicated}")
    again = store.put_ledger(org_id=org, site_id=site, ledger="activity",
                             df=df, file_name="selftest.csv")
    assert again.load_id == ref.load_id and again.deduplicated, "idempotency broken"
    print("idempotency: ok")

    back = store.ledger_frame(ref.load_id)
    assert list(back["activity_key"]) == ["diesel_L", "guangdong"], "round-trip broken"
    print("round-trip: ok")

    class _Rep:
        certificate_status = "REVIEW"
        emissions_tco2e = 613.9
        emissions_u95_tco2e = 12.0
        removals_tco2e = None
        removals_u95_tco2e = None
        residual_eC_tco2e = -180.0
        scale_residual_eA_tco2e = None
        leakage_ryg = "amber"
        stages: list = []
        data_gaps = ["selftest"]

        def artifacts(self):
            return {"audit_certificate": "REVIEW"}

        def summary(self):
            return "selftest"

    run = store.save_audit(org_id=org, site_id=site, report=_Rep(),
                           loads={"activity": ref.load_id},
                           label="selftest", created_by="selftest")
    hist = store.audit_history(org_id=org, site_id=site)
    assert run in set(hist["run_id"]), "history broken"
    print(f"audit round-trip: ok ({run})")

    fb_id = store.add_feedback(org_id=org, site_id=site,
                               comment="selftest note", rating=4, tab="selftest",
                               created_by="selftest")
    rows = store.feedback(org_id=org, site_id=site)
    assert fb_id in set(rows["feedback_id"]), "feedback broken"
    print("feedback round-trip: ok")

    ev_id = store.log_event(org_id=org, site_id=site, verb="selftest",
                            detail={"step": 1}, created_by="selftest")
    ev_rows = store.events(org_id=org, site_id=site)
    assert ev_id in set(ev_rows["event_id"]), "event broken"
    assert len(store.funnel(org_id=org)) >= 1, "funnel broken"
    print("event round-trip: ok")
    print("seeded factors:", store.seed_factors())

    # cleanup — leaves the target database exactly as it was
    with store.engine.begin() as conn:
        activity = METADATA.tables["activity_row"]
        conn.execute(sa.delete(activity).where(activity.c.load_id == ref.load_id))
        for name in ("event", "feedback", "audit_run", "ledger_load", "site", "org"):
            t = METADATA.tables[name]
            conn.execute(sa.delete(t).where(t.c.org_id == org))
    print("cleanup: ok")
    store.dispose()
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ucst_ccif.store")
    parser.add_argument("--url", default=os.environ.get("OCIP_DATABASE_URL"),
                        help="SQLAlchemy URL (defaults to $OCIP_DATABASE_URL)")
    parser.add_argument("--ddl", action="store_true",
                        help="print the Postgres DDL and exit")
    parser.add_argument("--selftest", action="store_true",
                        help="round-trip test against a real database")
    parser.add_argument("--digest", action="store_true",
                        help="per-organisation usage table (operator only)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.ddl:
        print(render_ddl())
        return 0
    if args.selftest:
        if not args.url:
            print("--selftest needs --url or OCIP_DATABASE_URL", file=sys.stderr)
            return 2
        return _selftest(args.url)
    if args.digest:
        if not args.url:
            print("--digest needs --url or OCIP_DATABASE_URL", file=sys.stderr)
            return 2
        store = Store(args.url)
        try:
            store.ensure_schema()
            frame = store.digest()
        finally:
            store.dispose()
        if frame.empty:
            print("no organisations yet — nobody has written anything")
            return 0
        print(frame.to_string(index=False))
        stuck = frame[(frame["loads"] > 0) & (frame["runs"] == 0)]
        if not stuck.empty:
            print("\nloaded a ledger but never ran an audit: "
                  + ", ".join(stuck["org_id"].tolist()))
        quiet = frame[frame["feedback"] == 0]
        if not quiet.empty:
            print("no feedback yet from: " + ", ".join(quiet["org_id"].tolist()))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
