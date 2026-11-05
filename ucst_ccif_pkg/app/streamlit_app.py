"""
UCST-CCIF Streamlit MVP — v0.4.0 (6 workspaces)

Workspaces:
  1. Upload & Dictionary — four ledgers (activity / flux / stock / intervention),
     every CSV template carries a "#" comment line with full names + units, and
     each ledger has a column dictionary. Missing ledgers are reported as data
     gaps — never silently estimated.
  2. Audit Report — the S1→S7 pipeline (boundary → factors → conservation →
     scale → additionality → leakage → uncertainty) producing the 8 artifacts
     plus a certificate, an embedded leakage verdict, a time-series scale
     audit εA (Eq.4) and a PDF evidence pack.
  3. Equations (Eq.1–10) — every numbered equation of the anchor manuscript
     rendered with its logic, its software location and its pipeline stage,
     so the audit is traceable back to the math (and the paper).
  4. Model competition (M0–M3, Eq.8–10) — reproduce the paper's §5 nested
     comparison on your own flux ledger: M0/M1/(M2a) out-of-sample metrics,
     predictions and the M3 counterfactual scenario calculator.
  5. Benchmarks — official reference data (CEADs Guangdong / Global Carbon
     Budget / HK EPD / CH4 kernels / CCER mangrove lookup) + NGFS stress lens.
  6. Data & history — optional PostgreSQL persistence (see docs/POSTGRES.md):
     every upload is an immutable, checksum-addressed load; every audit is a
     run pointing at the loads it consumed. Without a database this tab says
     so and nothing is written — and with OCIP_DEMO_MODE=1 it says *demo*,
     because a configured database is then deliberately ignored.

Community-trial affordances: tab 1 can load a session-only sample dataset
(Guangzhou 2023) so a stranger reaches a certificate without owning data; when
a database is linked, uploads stay disabled until the data notice is
acknowledged; and tab 6 stores free-text feedback (or shows a form link when no
database is linked).

Why the old tabs disappeared: uploading the four ledgers already covers
Scope 1-3 (activity ledger, stage S1), biogenic flux (flux ledger, stage S2),
leakage (stage S6) and PDF export (post-audit). Manual input tabs were
duplicate entry points, so they were removed.
"""

from __future__ import annotations
import io
import os
import sys
import pathlib as _pl
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st

# Cloud-deploy safety: make the ucst_ccif package importable regardless of
# whether this app runs from the repo root (Streamlit Cloud) or from inside
# the package folder (local run).
_APP_ROOT = _pl.Path(__file__).resolve().parents[1]   # e.g. .../ucst_ccif_pkg
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

st.set_page_config(page_title="OCIP — Carbon Verification Layer", layout="wide",
                   initial_sidebar_state="expanded")

from ucst_ccif.emission_factors import (
    FUELS, GRID_FACTORS_MEE_2022, GRID_SOURCE,
    TD_LOSS_RATE, TRAVEL_FACTORS, COMMUTE_FACTORS, SPEND_FACTORS,
)
from ucst_ccif.tenancy import mapping_is_enforced as _mapping_is_enforced
from ucst_ccif.tenancy import resolve_org as _resolve_org

# ------------------------------------------------------------------
# Brand & theme
APP_VERSION = "v0.4.0"
APP_TAGLINE = "The independent carbon-verification layer for GBA enterprises & research teams"
GITHUB_URL = "https://github.com/liulinda185-spec/carbon-falcon-ocip"
DOI_URL = "https://zenodo.org/records/23687344"

st.markdown("""
<style>
  /* Hero */
  .ocip-hero { padding: .35rem .9rem .5rem .9rem; border-left: 5px solid #1F497D;
               background: linear-gradient(90deg, #FFFFFF 0%, #F2F5F9 100%);
               border-radius: 10px; margin-bottom: .4rem; }
  .ocip-hero h1 { margin: 0; font-size: 2.0rem; letter-spacing: -.01em;
                  color: #1F497D; }
  .ocip-hero .tagline { color: #47596B; font-size: 1.02rem; margin-top: .1rem; }
  .ocip-hero .badges { margin-top: .3rem; }
  .ocip-badge { display: inline-block; background: #1F497D; color: #fff;
                border-radius: 20px; padding: .1rem .7rem; font-size: .78rem;
                margin-right: .4rem; font-weight: 600; }
  .ocip-badge.gold { background: #C9A227; }
  .ocip-badge.grey { background: #5C6B7A; }
  /* Section labels */
  .ocip-section { color: #1F497D; font-weight: 700; font-size: .95rem;
                  letter-spacing: .04em; margin: .2rem 0 .15rem 0; }
  /* Metrics polish */
  [data-testid="stMetric"] { background: #FFFFFF; border: 1px solid #E3E8EE;
                             border-radius: 10px; padding: .6rem .8rem; }
  [data-testid="stMetricLabel"] { color: #5C6B7A; }
  /* Footer */
  .ocip-footer { color: #8A97A5; font-size: .8rem; margin-top: 1.2rem;
                 border-top: 1px solid #E3E8EE; padding-top: .5rem; }
  /* Sidebar brand */
  .ocip-side-brand { font-size: 1.15rem; font-weight: 800; color: #1F497D; }
  .ocip-side-sub { color: #5C6B7A; font-size: .82rem; }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="ocip-hero">
  <h1>OCIP — Open Carbon Platform</h1>
  <div class="tagline">{APP_TAGLINE}</div>
  <div class="badges">
    <span class="ocip-badge">{APP_VERSION}</span>
    <span class="ocip-badge">113/113 tests</span>
    <span class="ocip-badge gold">Apache-2.0</span>
    <span class="ocip-badge grey">UCST-CCIF engine</span>
    <span class="ocip-badge">10/10 equations mapped</span>
  </div>
</div>
""", unsafe_allow_html=True)
st.caption("One auditable ledger: fossil + biogenic flux · leakage audit built in · "
           "L1 point flux → L5 policy · same factors, same ε_C residual rule at every scale.")

# ------------------------------------------------------------------
# Persistence — optional PostgreSQL (multi-user) or SQLite (local dev).
# Every helper below fails soft: the app must run with no database at all.
# ------------------------------------------------------------------
def _secret(*path, default=None):
    """Read st.secrets[...] without letting a missing secrets.toml crash the app."""
    try:
        node = st.secrets
        for key in path:
            node = node[key]
    except Exception:  # noqa: BLE001
        return default
    return default if node is None else node


@st.cache_resource(show_spinner=False)
def _build_store(url: str):
    from ucst_ccif.store import Store

    store = Store(url)
    store.ensure_schema()   # idempotent: creates only what is missing
    store.seed_factors()    # writes the factor library once
    return store


def _demo_mode() -> bool:
    """Public sandbox: sample data in, nothing written out.

    Set OCIP_DEMO_MODE=1 in the environment or `demo = true` under [ocip] in
    secrets. In this mode a configured database is deliberately ignored, so
    anonymous testers cannot write into the ledger you intend to analyse.
    """
    env = os.environ.get("OCIP_DEMO_MODE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if _telemetry_only():      # the public trial is a sandbox with counting on
        return True
    return bool(_secret("ocip", "demo", default=False))


def _telemetry_only() -> bool:
    """Public trial: events yes, client files never.

    `telemetry_only = true` under [ocip] (or OCIP_TELEMETRY_ONLY=1) makes the
    app read sample data, keep every visitor's uploads in the browser session,
    and write *only* the step events — no ledger rows, no reports, no emails.
    """
    env = os.environ.get("OCIP_TELEMETRY_ONLY", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    return bool(_secret("ocip", "telemetry_only", default=False))


def _store():
    """(Store | None, reason). Never raises."""
    if _demo_mode() and not _telemetry_only():
        return None, "demo sandbox — sample data only, nothing is stored"
    url = (_secret("postgres", "url", default=None)
           or os.environ.get("OCIP_DATABASE_URL"))
    if not url:
        return None, "no connection string configured"
    try:
        return _build_store(url), "ok"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _identity():
    """(email, org_id). st.login when configured, otherwise a dev identity.

    In telemetry-only mode the visitor is deliberately anonymous: no address
    is recorded even if one happens to be available.
    """
    if _telemetry_only():
        return None, "public"
    email = None
    try:
        if st.user.is_logged_in:
            email = getattr(st.user, "email", None)
    except Exception:  # noqa: BLE001
        email = None
    email = email or _secret("ocip", "dev_user", default=None) or "local@dev"
    orgs = _secret("ocip", "orgs", default=None) or {}
    org = _resolve_org(
        email, orgs,
        default_org=str(_secret("ocip", "default_org", default="demo")),
        allow_unknown=bool(_secret("ocip", "allow_unknown", default=False)))
    return email, str(org or _secret("ocip", "default_org", default="demo"))


def _current_site():
    return st.session_state.get("ocip_site") or _secret(
        "ocip", "default_site", default="GBA-DEMO-01")


_EVENT_VERBS = {
    "app_open", "consent_accepted", "sample_loaded", "upload_ok",
    "upload_rejected", "audit_run", "pdf_export", "feedback_view",
}


def _log_event(verb, **detail):
    """One step of the pilot funnel. Silent no-op without a database.

    The public sandbox never reaches the table: demo mode returns no store at
    all. Telemetry must never be able to break an audit, so failures are
    swallowed rather than surfaced.
    """
    store, _ = _store()
    if store is None:
        return
    email, org = _identity()
    try:
        store.log_event(org_id=org, site_id=_current_site(), verb=verb,
                        detail=(detail or None), created_by=email)
    except Exception:  # noqa: BLE001
        pass


def _log_once(key, verb, **detail):
    """Log at most once per browser session."""
    flag = f"ocip_ev_{key}"
    if st.session_state.get(flag):
        return
    st.session_state[flag] = True
    _log_event(verb, **detail)


def _persist_ledger(ledger, df, file_name):
    """Store one uploaded ledger. Silent no-op when no database is linked.

    In demo / public-trial mode this never writes: a visitor's file stays in
    their own session, so the sample data cannot be polluted by strangers.
    """
    store, _ = _store()
    if store is None:
        return
    if _demo_mode():
        # public trial: count the step, keep the file in the visitor's session
        _log_event("upload_ok", ledger=ledger, rows=len(df), stored=False)
        return
    email, org = _identity()
    try:
        ref = store.put_ledger(org_id=org, site_id=_current_site(), ledger=ledger,
                               df=df, file_name=file_name, loaded_by=email)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not persist {ledger} ledger: {exc}")
        return
    st.session_state.setdefault("ocip_loads", {})[ledger] = ref.load_id
    _log_event("upload_ok", ledger=ledger, rows=ref.row_count,
               dedup=bool(ref.deduplicated))
    tag = "re-used" if ref.deduplicated else "saved"
    st.caption(f"Postgres → {tag} load `{ref.load_id[:8]}` · {ref.row_count} rows "
               f"· sha256 {ref.sha256[:8]}…")


def _persist_audit(report, *, area_ha, claimed, agent_col, grid_region):
    store, _ = _store()
    if store is None:
        return
    if _demo_mode():
        _log_event("audit_run",
                   certificate=getattr(report, "certificate_status", None),
                   area_ha=area_ha, grid_region=grid_region, stored=False)
        return
    email, org = _identity()
    try:
        run_id = store.save_audit(
            org_id=org, site_id=_current_site(), report=report,
            loads=st.session_state.get("ocip_loads", {}),
            label=f"audit {datetime.now():%Y-%m-%d %H:%M}",
            created_by=email, area_ha=area_ha,
            claimed_removals_tco2e=claimed, grid_region=grid_region,
            agent_col=agent_col)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Audit ran but was not persisted: {exc}")
        return
    st.session_state["ocip_last_run"] = run_id
    _log_event("audit_run", certificate=getattr(report, "certificate_status", None),
               loads=len(st.session_state.get("ocip_loads", {})),
               area_ha=area_ha, grid_region=grid_region)
    st.caption(f"Postgres → run `{run_id[:8]}` saved with its ledger loads")


def _auth_enabled() -> bool:
    """True when an [auth] block exists — i.e. real sign-in is expected."""
    return bool(_secret("auth", default=None))


def _signed_in() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except Exception:  # noqa: BLE001
        return False


def _invite_list_active() -> bool:
    """An [ocip.orgs] map exists and unknown emails are not waved through.

    Without this, an invite-only pilot is a fiction: any Google account that
    signs in falls back to default_org and can read that org's ledgers.
    """
    return _mapping_is_enforced(
        _secret("ocip", "orgs", default=None),
        allow_unknown=bool(_secret("ocip", "allow_unknown", default=False)))


def _email_allowed(email) -> bool:
    return _resolve_org(email, _secret("ocip", "orgs", default=None) or {},
                        default_org="", allow_unknown=False) is not None


_SAMPLE_DIR = _APP_ROOT / "testdata"

_DATA_NOTICE = (
    "**When a database is linked, this is what gets stored:** the file you upload "
    "row by row, its filename, its SHA-256 checksum, your email, your organisation "
    "and site ID, and the audit report.\n\n"
    "- **Why:** so an audit can be traced back to the exact bytes it read, and so "
    "your runs stay separate from another organisation's.\n"
    "- **Who sees it:** people mapped to your organisation, plus whoever operates "
    "this deployment.\n"
    "- **How long:** until you ask for deletion. Ledger rows are append-only — a "
    "correction arrives as a new file, not an overwrite of the old one.\n"
    "- **Deletion:** ask the operator; the site's loads, runs and feedback are "
    "removed together.\n"
    "- **Steps we count:** while this deployment is used for a pilot, we also record "
    "*which* step you reached (opened, ticked consent, loaded the sample, uploaded, "
    "ran the audit, exported the PDF, opened the feedback box) with the time and "
    "your email — never what you typed. No IP address, no browser fingerprint. This "
    "is how failures in the funnel get found; it is not used to profile you.\n"
    "- **Please don't upload** personal data, or company data you have no "
    "permission to share."
)


_PUBLIC_NOTICE = (
    "**This is a public trial.** Your uploaded files stay in your browser "
    "session: they are never stored, never shown to anyone else, and disappear "
    "when you close the tab.\n\n"
    "- **What we record:** which step you reached — opened the app, loaded the "
    "sample, uploaded, ran the audit, exported the PDF, opened the feedback box "
    "— with a timestamp and a random session label.\n"
    "- **What we never record:** your email, your IP address, your browser "
    "fingerprint, the contents of any file you upload, or any text you type.\n"
    "- **Why:** to find where a first-time visitor gets stuck. Nothing here "
    "identifies you.\n"
    "- **Please don't upload** real company data — use the sample dataset, or "
    "dummy numbers."
)


def _data_notice() -> str:
    """The notice that matches the deployment's actual behaviour."""
    return _PUBLIC_NOTICE if _telemetry_only() else _DATA_NOTICE


def _consent_required() -> bool:
    """Consent matters only when a visitor's own file is actually stored.

    The public trial writes events but never ledgers, so it does not ask.
    """
    store, _ = _store()
    return store is not None and not _demo_mode()


def _sample_frames() -> dict[str, pd.DataFrame]:
    """Guangzhou 2023 daily NEE + demo activity/stock — for a first run."""
    act = pd.DataFrame([
        {"scope": "2", "category": "electricity",
         "activity_key": "guangdong", "quantity": 1135589.4},
        {"scope": "1", "category": "fuel",
         "activity_key": "diesel_L", "quantity": 20000.0},
    ])
    stock = pd.DataFrame([{"area_ha": 100.0, "removal_tco2e": 380.0}])
    flux_path = _SAMPLE_DIR / "gba_flux_guangzhou_2023.csv"
    if not flux_path.exists():
        raise FileNotFoundError(f"sample dataset missing: {flux_path}")
    flux = pd.read_csv(flux_path, comment="#")
    return {"activity": act, "flux": flux, "stock": stock}


# With [auth] configured, an unauthenticated visitor must not reach the data at
# all — st.login() is an explicit action, so without this gate the app would
# quietly fall back to the dev identity and expose that org's ledgers.
if _auth_enabled() and not _signed_in():
    st.markdown("## Sign in to OCIP")
    st.info("This deployment is multi-user — each account is routed to its own "
            "organisation, and ledgers are never shared across tenants.")
    if st.button("Sign in", type="primary"):
        st.login()
    st.stop()


# Signing in is not the same as being invited. With an [ocip.orgs] map in place,
# an account that is not listed is stopped here rather than dropped into
# default_org — the difference between an invite-only pilot and a public one.
if _auth_enabled() and _signed_in() and _invite_list_active():
    _visitor = None
    try:
        _visitor = getattr(st.user, "email", None)
    except Exception:  # noqa: BLE001
        _visitor = None
    if not _email_allowed(_visitor):
        st.markdown("## This pilot is invite-only")
        st.error(f"`{_visitor}` is not on the access list for this deployment.")
        st.caption("Ask the operator to add your address to `[ocip.orgs]` in the "
                   "app's secrets, then reload this page.")
        if st.button("Sign out"):
            st.logout()
        st.stop()


# First step of the funnel: once per browser session, pilot only (in demo mode
# there is no store, so this is a no-op).
_log_once("open", "app_open", page="1. Upload & Dictionary")


# The public sandbox opens with something to audit: a visitor who has no data
# should still reach a certificate before being asked to upload anything.
if _demo_mode() and not st.session_state.get("ocip_demo_seeded"):
    try:
        for _key, _frame in _sample_frames().items():
            st.session_state[f"ocip_{_key}"] = _frame
        st.session_state["ocip_area"] = 100.0
        st.session_state["ocip_demo_seeded"] = True
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------
# Sidebar
with st.sidebar:
    st.markdown('<div class="ocip-side-brand">OCIP</div>', unsafe_allow_html=True)
    st.markdown('<div class="ocip-side-sub">Carbon verification · UCST-CCIF</div>',
                unsafe_allow_html=True)
    st.divider()
    region = st.selectbox("Grid region",
        ["guangdong", "south_region", "national_avg"], index=0,
        help="Grid emission factor used across Scope 2, balance sheet and examples.")
    grid_factor = GRID_FACTORS_MEE_2022[region]
    st.info(f"Grid EF: {grid_factor:.4f} kgCO2/kWh\n({GRID_SOURCE})")
    st.divider()

    _store_obj, _store_reason = _store()
    if _store_obj is not None and _telemetry_only():
        st.info("**Store:** public trial — step counts only, uploaded files are "
                "never saved")
        st.caption("anonymous · org `public` · no email stored")
    elif _store_obj is not None:
        engine = ("PostgreSQL" if _store_obj.dialect == "postgresql"
                  else f"{_store_obj.dialect} (local dev)")
        st.success(f"**Store:** {engine} — persisted")
        st.caption(f"org `{_identity()[1]}` · site-scoped")
    else:
        if _demo_mode():
            st.info("**Store:** demo sandbox — sample data, nothing stored")
        else:
            st.warning("**Store:** session-only — uploads vanish on refresh")
        st.caption(_store_reason)
    st.session_state.setdefault(
        "ocip_site", _secret("ocip", "default_site", default="GBA-DEMO-01"))
    st.text_input("Site ID", key="ocip_site",
                  help="Every ledger load and audit run is filed under this site.")
    st.caption(f"User `{_identity()[0] or 'anonymous'}`")
    if _auth_enabled() and _signed_in():
        if not _invite_list_active():
            st.caption("Note: no `[ocip.orgs]` list — any signed-in account lands "
                       "in `default_org`. Add one before sharing this link.")
        if st.button("Sign out", key="ocip_logout"):
            st.logout()

    st.divider()
    st.caption("**How to use** — 1) upload your four ledgers, 2) run the audit, "
               "3) compare against official benchmarks. Every number is traceable "
               "to a source or a formula in this app.")
    st.caption(f"[GitHub]({GITHUB_URL}) · [Zenodo DOI]({DOI_URL}) · "
               f"[Paper](https://ssrn.com/abstract=7417192) · v{APP_VERSION.lstrip('v')}")

tab_upload, tab_report, tab_eq, tab_model, tab_bench, tab_data = st.tabs([
    "1. Upload & Dictionary",
    "2. Audit Report",
    "3. Equations (Eq.1–10)",
    "4. Model competition (M0–M3)",
    "5. Benchmarks",
    "6. Data & history",
])

# ==================================================================
# 1. UPLOAD & DICTIONARY
# ==================================================================
with tab_upload:
    st.header("Upload the four ledgers")
    st.caption("Every file is **optional** — missing ledgers are reported as data "
               "gaps, never silently estimated. Each CSV template carries a **`#` "
               "comment line** with full column names and units; download a template "
               "to inspect them.")

    # ---- CSV templates (with # comment lines: full name + unit + example) ----
    tmpl = {
        "activity": (
            "# Activity ledger — full names & units\n"
            "# scope: 1=on-site fuel (Scope1) 2=purchased electricity (Scope2) "
            "3=supply chain (Scope3) | "
            "category: electricity/fuel/purchased_goods | "
            "activity_key: specific activity key e.g. guangdong/diesel_L/manufactured_goods | "
            "quantity: amount (unit depends on category: electricity->kWh, fuel->L or m3, "
            "purchased_goods->CNY)\n"
            "scope,category,activity_key,quantity\n"
            "2,electricity,guangdong,1135589.4\n"
            "1,fuel,diesel_L,20000\n"
            "2,purchased_goods,manufactured_goods,2000000\n"),
        "flux": (
            "# Flux ledger — full names & units\n"
            "# date: date (YYYY-MM-DD) | "
            "NEE_daily_total: Net Ecosystem Exchange, g C m-2 day-1, negative = uptake | "
            "GPP_daily_total: Gross Primary Production, g C m-2 day-1 | "
            "ER_daily_total: Ecosystem Respiration, g C m-2 day-1 | "
            "water_level: agent-state management signal (e.g. tidal level), "
            "optional — enables M2a (Eq.2)\n"
            "date,NEE_daily_total,GPP_daily_total,ER_daily_total,wind_speed_mean,temperature_2m_mean,water_level\n"
            "2023-01-01,3.92,2.27,1.29,14.7,14.0,2.1\n"
            "2023-01-02,4.47,1.90,1.14,20.2,15.3,2.4\n"),
        "stock": (
            "# Stock ledger — full names & units\n"
            "# area_ha: project area, hectare | "
            "removal_tco2e: independently observed removal, tonnes CO2 equivalent\n"
            "area_ha,removal_tco2e\n"
            "100.0,420.0\n"),
        "intervention": (
            "# Intervention ledger — full names & units\n"
            "# scenario: scenario name e.g. wetland_restoration | "
            "baseline_removal_tco2e: baseline removal tCO2e (do-nothing control) | "
            "intervention_removal_tco2e: post-intervention removal tCO2e | "
            "active_fraction: share of actively managed intervention, 0-1 dimensionless\n"
            "scenario,baseline_removal_tco2e,intervention_removal_tco2e,active_fraction\n"
            "wetland_restoration,300.0,420.0,0.4\n"),
    }
    t1, t2, t3, t4 = st.columns(4)
    for col, key, label in ((t1, "activity", "Activity ledger"),
                            (t2, "flux", "Flux ledger"),
                            (t3, "stock", "Stock ledger"),
                            (t4, "intervention", "Intervention ledger")):
        with col:
            st.download_button(
                f"{label} template (CSV)", data=tmpl[key],
                file_name=f"ocip_{key}_template.csv", mime="text/csv")

    st.divider()

    # ---- quick start: sample dataset · consent · data notice ----
    q1, q2 = st.columns([1, 2])
    with q1:
        if st.button("Load sample dataset", key="ocip_sample_btn",
                     help="Guangzhou 2023 daily NEE + a demo activity ledger. "
                          "Session-only — never written to the ledger."):
            try:
                frames = _sample_frames()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Sample dataset unavailable: {exc}")
            else:
                for key_name, frame in frames.items():
                    st.session_state[f"ocip_{key_name}"] = frame
                st.session_state["ocip_area"] = 100.0
                _log_event("sample_loaded")
                st.rerun()
        st.caption("Guangzhou 2023 flux + demo activity · session-only")
    with q2:
        if _consent_required():
            st.checkbox("I may share the data I upload, and I accept the data "
                        "notice below.", key="ocip_consent",
                        help="Required before anything is written to the database.")
            if not st.session_state.get("ocip_consent"):
                st.warning("Tick the box above to enable uploads.")
            else:
                _log_once("consent", "consent_accepted")
        else:
            st.caption("No database linked — uploads live in this browser session "
                       "only, and nothing is written.")
        with st.expander("Data notice — what happens to what you upload"):
            st.markdown(_data_notice())

    st.divider()

    # ---- upload + validation (skip # comment lines) ----
    required = {
        "activity": ["scope", "category", "activity_key", "quantity"],
        "flux": ["date", "NEE_daily_total"],
        "stock": ["area_ha", "removal_tco2e"],
        "intervention": ["scenario", "baseline_removal_tco2e",
                         "intervention_removal_tco2e"],
    }
    ledgers = {
        "activity": ("ocip_activity", "Activity ledger (Scope 1-3)"),
        "flux": ("ocip_flux", "Flux ledger (daily NEE)"),
        "stock": ("ocip_stock", "Stock ledger (observed removal)"),
        "intervention": ("ocip_intervention", "Intervention ledger (Eq.3)"),
    }
    c_a, c_f, c_s, c_i = st.columns(4)
    for col, (key, (skey, label)) in zip((c_a, c_f, c_s, c_i), ledgers.items()):
        with col:
            st.markdown(f"**{label}**")
            up = st.file_uploader(f"Upload {key}", type=["csv"], key=f"up_{key}",
                                  disabled=(_consent_required()
                                            and not st.session_state.get("ocip_consent")))
            if up:
                try:
                    df = pd.read_csv(up, comment="#")
                    st.session_state[skey] = df
                    miss = [c for c in required[key] if c not in df.columns]
                    st.dataframe(df.head(3), width="stretch")
                    if miss:
                        st.error(f"Missing columns: {', '.join(miss)}")
                        _log_event("upload_rejected", ledger=key,
                                   missing=len(miss), rows=len(df))
                    else:
                        st.success(f"OK — {len(df)} rows, required columns present")
                        _persist_ledger(key, df, up.name)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not parse CSV: {e}")
                    _log_event("upload_rejected", ledger=key, reason="parse")
                    st.session_state.pop(skey, None)

    # ---- per-ledger column dictionary ----
    st.divider()
    st.markdown('<span class="ocip-section">Column dictionary — full name / unit / role</span>',
                unsafe_allow_html=True)
    dict_rows = [
        ("activity",
         [("scope", "GHG scope", "1 / 2 / 3", "1=on-site fuel 2=purchased electricity 3=supply chain (S1 auto classifies)"),
          ("category", "category", "electricity / fuel / purchased_goods", "picks the emission-factor table"),
          ("activity_key", "activity key", "e.g. guangdong / diesel_L", "maps to a specific factor-library entry"),
          ("quantity", "quantity", "kWh · L · m³ · CNY (depends on category)", "× emission factor → emissions (S1)")]),
        ("flux",
         [("date", "date", "YYYY-MM-DD", "time step (optional, auto-ignored)"),
          ("NEE_daily_total", "Net Ecosystem Exchange", "g C m⁻² day⁻¹", "audit target: site net carbon flux (S2)"),
          ("GPP_daily_total", "Gross Primary Production", "g C m⁻² day⁻¹", "Algebraically derived from NEE — using it as a predictor leaks (S6)"),
          ("ER_daily_total", "Ecosystem Respiration", "g C m⁻² day⁻¹", "Same dependency: NEE = ER − GPP (S6)")]),
        ("stock",
         [("area_ha", "project area", "ha", "scale factor converting gC/m² to tCO₂e (S2/S4)"),
          ("removal_tco2e", "independently observed removal", "tCO₂e", "independent basis for reconciling claimed removals (S3)")]),
        ("intervention",
         [("scenario", "scenario", "text", "e.g. wetland_restoration"),
          ("baseline_removal_tco2e", "baseline removal", "tCO₂e", "do-nothing control (S5, Eq.3 F_p)"),
          ("intervention_removal_tco2e", "post-intervention removal", "tCO₂e", "removal after the intervention (S5, Eq.3)"),
          ("active_fraction", "active intervention share", "0–1 dimensionless", "share of actively managed intervention (optional)")]),
    ]
    for key, label, rows in (
            ("activity", "Activity ledger", dict_rows[0][1]),
            ("flux", "Flux ledger", dict_rows[1][1]),
            ("stock", "Stock ledger", dict_rows[2][1]),
            ("intervention", "Intervention ledger", dict_rows[3][1])):
        with st.expander(f"{label} — column dictionary", expanded=False):
            st.table(pd.DataFrame(rows, columns=["Column", "Full name", "Unit", "Role in the audit"]))

    st.divider()
    area_ha = st.number_input(
        "Project area (ha) — converts daily NEE (gC/m²/d) to tCO₂e",
        0.0, 1e9, 100.0, step=1.0, key="ocip_area_input")
    st.session_state["ocip_area"] = area_ha

    st.info("**Scope 1/2/3 are computed automatically** — provide `category` + "
            "`quantity` in the activity ledger; stage S1 applies the corresponding "
            "emission factors (Scope 1 = on-site fuel, Scope 2 = purchased "
            "electricity, Scope 3 = supply chain). Proceed to **Tab 2 Audit "
            "Report** and run the audit.")

# ==================================================================
# 2. AUDIT REPORT
# ==================================================================
with tab_report:
    st.header("Audit report — 7-step pipeline, 8 artifacts")
    st.caption("Runs S1 (boundary) → S2 (factors) → S3 (conservation, Eq.1) → "
               "S4 (scale, Eq.4–5) → S5 (additionality, Eq.2+3) → S6 (leakage, Eq.7) → "
               "S7 (uncertainty) on the four ledgers uploaded in tab 1. "
               "Full equation logic lives in tab 3.")

    st.markdown("""
    <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:stretch;font-size:0.85rem;margin:6px 0 10px;">
      <div style="flex:2 1 380px;background:#fff;border:1px solid #d8dee4;border-radius:10px;padding:10px;">
        <b>7-step pipeline — run_audit()</b>
        <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S1 Boundary</div><span style="color:#5c6b7a;">→</span>
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S2 Factors</div><span style="color:#5c6b7a;">→</span>
          <div style="border:2px solid #B23A3A;border-radius:6px;padding:4px 6px;background:#FDF3F1;">S3 Conservation</div><span style="color:#5c6b7a;">→</span>
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S4 Scale</div><span style="color:#5c6b7a;">→</span>
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S5 Additionality</div><span style="color:#5c6b7a;">→</span>
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S6 Leakage</div><span style="color:#5c6b7a;">→</span>
          <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 6px;background:#f7f9fb;">S7 Uncertainty</div>
        </div>
        <div style="margin-top:6px;color:#5c6b7a;font-size:0.75rem;">S3: ε_C = independent observation − company claim (negative = over-claim) · S5: active trigger F_a vs passive response F_p · S6: three-step leakage audit</div>
      </div>
      <div style="flex:1 1 220px;background:#eaf6ec;border:1px solid #b7d9bd;border-radius:10px;padding:10px;">
        <b>8 artifacts + certificate</b>
        <div style="margin-top:6px;color:#2c3e50;line-height:1.6;font-size:0.8rem;">
          ① boundary inventory · ② emission interval · ③ removal interval · ④ residual ε_C<br/>
          ⑤ scale residual · ⑥ leakage RYG flag · ⑦ attribution split · ⑧ uncertainty budget
        </div>
        <div style="margin-top:6px;border:1px solid #3a7d44;border-radius:6px;padding:4px 6px;background:#fff;font-weight:600;">PASS / REVIEW / FAIL / INCOMPLETE</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    a1, a2, a3 = st.columns(3)
    with a1:
        claim = st.number_input("Company's claimed removal (tCO₂e/yr)",
                                0.0, 1e9, 420.0, step=10.0,
                                help="Company-claimed removals — S3 reconciles it against independent observation")
    with a2:
        agent_col = st.text_input("Agent-state column (Eq.2, optional)",
                                  placeholder="e.g. water_level / mangrove_age",
                                  help="Column in the flux ledger carrying the management signal; leave empty to skip the attribution split")
    with a3:
        area = st.session_state.get("ocip_area", 100.0)
        st.metric("Area used for gC → tCO₂e", f"{area:,.1f} ha",
                  help="Set in Tab 1")

    if st.button("Run the audit", type="primary"):
        from ucst_ccif import run_audit
        rep = run_audit(
            activity_df=st.session_state.get("ocip_activity"),
            flux_df=st.session_state.get("ocip_flux"),
            stock_df=st.session_state.get("ocip_stock"),
            intervention_df=st.session_state.get("ocip_intervention"),
            area_ha=(area if area > 0 else None),
            grid_region=region,
            claimed_removals_tco2e=(claim if claim > 0 else None),
            agent_col=(agent_col.strip() if agent_col.strip() else None),
        )
        st.session_state["ocip_report"] = rep
        st.session_state["ocip_report_text"] = rep.summary()
        _persist_audit(rep, area_ha=(area if area > 0 else None), claimed=claim,
                       agent_col=(agent_col.strip() or None),
                       grid_region=region)

    rep = st.session_state.get("ocip_report")
    if rep is not None:
        # --- certificate + headline metrics ---
        cert_color = {"PASS": "#1F7A3D", "FAIL": "#B23A3A",
                      "REVIEW": "#C9A227", "INCOMPLETE": "#5C6B7A"}
        cc = next((v for k, v in cert_color.items()
                   if rep.certificate_status.startswith(k)), "#5C6B7A")
        st.markdown(
            f"<div style='border-left:6px solid {cc}; padding:.4rem .9rem; "
            f"background:#F7F9FB; border-radius:8px; margin:.3rem 0'>"
            f"<b style='font-size:1.25rem;color:{cc}'>{rep.certificate_status}</b>"
            f"<div style='color:#47596B'>Audit certificate — the verdict of the "
            f"8-artifact report.</div></div>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Verified emissions",
                  (f"{rep.emissions_tco2e:,.1f} ± {rep.emissions_u95_tco2e:,.1f}"
                   " tCO₂e" if rep.emissions_tco2e is not None else "—"),
                  help="Artifact 1: verified emission interval (S2 + S7)")
        m2.metric("Verified removals",
                  (f"{rep.removals_tco2e:,.1f} ± {rep.removals_u95_tco2e:,.1f}"
                   " tCO₂e" if rep.removals_tco2e is not None else "—"),
                  help="Artifact 2: verified removal interval (S3)")
        m3.metric("Conservation residual ε_C",
                  (f"{rep.residual_eC_tco2e:+,.1f} tCO₂e"
                   if rep.residual_eC_tco2e is not None else "—"),
                  help="Artifact 3: observed − claimed. Negative = over-claim (S3)")
        m4.metric("Leakage flag",
                  {"red": "RED — leaky predictors",
                   "amber": "AMBER", "green": "GREEN — clean",
                   "grey": "no flux data"}.get(rep.leakage_ryg, "—"),
                  help="Artifact 5: RYG status of the flux model (S6, Eq.7)")

        # --- leakage verdict (formerly its own tab) ---
        with st.expander("Leakage verdict (S6)", expanded=True):
            if rep.leakage is not None and rep.leakage.leaky_predictors:
                st.markdown("**Flagged LEAKY predictors (NEE-derived, circular):** "
                            + ", ".join(f"`{p}`" for p in rep.leakage.leaky_predictors))
                st.markdown("These columns are algebraically derived from NEE "
                            "(GPP/ER balance) — any model using them inflates R² "
                            "circularly. Drop them before quoting performance.")
            if rep.leak_free_gain_pct is not None:
                st.info(f"Leakage-free refit (step 3): apparent gain from leaky "
                        f"predictors = **{rep.leak_free_gain_pct:+.1f}%** "
                        f"(Sapelo honest baseline: 36.1%).")
            else:
                st.caption("No flux ledger uploaded — leakage stage reported as a "
                           "data gap, not estimated.")

        # --- scale audit: time-series εA (Eq.4) ---
        with st.expander("Scale audit — εA time series (Eq.4–5)", expanded=True):
            sa = getattr(rep, "scale_audit", None) or {}
            if not sa or sa.get("status") == "not_run":
                st.caption("No usable flux ledger — scale residual reported as a "
                           "data gap, not estimated.")
            else:
                st.markdown("**Aggregation-commutator residual (Eq.4):** integrate "
                            "daily NEE as measured (fine path), subtract the coarse "
                            "path (monthly-mean first, then integrate). Non-zero εA = "
                            "information lost by aggregation.")
                s1, s2, s3 = st.columns(3)
                s1.metric("max |εA|", f"{sa['eps_max_abs_gCm2']:.2f} gC/m²",
                          f"{sa['relative_max_pct']:.1f}% of total |flux|",
                          help="Scale-consistency gate: max |εA| vs pre-specified tolerance")
                s2.metric("final εA", f"{sa['eps_final_gCm2']:+.2f} gC/m²",
                          help="Residual at the end of the record (should return near 0)")
                s3.metric("Status", sa["status"], f"tol {sa['tol_pct']:.0f}%")
                if sa.get("monthly_worst_gCm2"):
                    st.markdown("**Worst day per month (gC/m²)** — where aggregation loses most:")
                    st.bar_chart(pd.Series(sa["monthly_worst_gCm2"]), height=160)
                if rep.scale_residual_eA_tco2e is not None:
                    st.caption(f"max |εA| over project area ≈ "
                               f"{rep.scale_residual_eA_tco2e:+,.1f} tCO₂e.")

        with st.expander("Stage log (S1–S7)", expanded=True):
            _stage_eq = {"1": "—", "2": "—", "3": "Eq. (1)",
                         "4": "Eq. (4)–(5)", "5": "Eq. (2)+(3)",
                         "6": "Eq. (7)", "7": "—"}
            st.dataframe(pd.DataFrame([
                {"Stage": f"S{s.stage}", "Name": s.name, "Status": s.status,
                 "Equation": _stage_eq.get(s.stage, "—"),
                 "Detail": s.detail} for s in rep.stages
            ]), width="stretch")
        if rep.data_gaps:
            with st.expander("Reported data gaps (never silently estimated)",
                             expanded=True):
                for g in rep.data_gaps:
                    st.markdown(f"- {g}")
        with st.expander("Full 8-artifact payload (JSON)"):
            st.json(rep.artifacts())

        # --- PDF evidence pack (formerly its own tab) ---
        st.divider()
        if st.button("Download ISO 14064-3 evidence pack (PDF)"):
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=A4)
            styles = getSampleStyleSheet()
            story = [
                Paragraph("OCIP — Carbon Audit Evidence Pack", styles["Title"]),
                Paragraph(f"Generated: {datetime.now().isoformat(timespec='seconds')}", styles["Normal"]),
                Paragraph(f"Platform: OCIP {APP_VERSION} (UCST-CCIF engine) · {GITHUB_URL}", styles["Normal"]),
                Paragraph(f"Certificate: {rep.certificate_status}", styles["Heading2"]),
                Spacer(1, 6),
                Paragraph(f"Verified emissions: "
                          f"{rep.emissions_tco2e:.1f} ± {rep.emissions_u95_tco2e:.1f} tCO2e"
                          if rep.emissions_tco2e is not None else
                          "Verified emissions: not run", styles["Normal"]),
                Paragraph(f"Verified removals: "
                          f"{rep.removals_tco2e:.1f} ± {rep.removals_u95_tco2e:.1f} tCO2e"
                          if rep.removals_tco2e is not None else
                          "Verified removals: not run", styles["Normal"]),
                Paragraph(f"Conservation residual ε_C: {rep.residual_eC_tco2e:+.1f} tCO2e "
                          "(negative = over-claim)" if rep.residual_eC_tco2e is not None
                          else "ε_C: not run", styles["Normal"]),
                Paragraph(f"Leakage RYG: {rep.leakage_ryg}", styles["Normal"]),
                Spacer(1, 6),
                Paragraph("Stage log:", styles["Heading3"]),
            ]
            for s in rep.stages:
                story.append(Paragraph(
                    f"[{s.status}] S{s.stage} {s.name} — {s.detail}", styles["Normal"]))
            if rep.data_gaps:
                story.append(Spacer(1, 6))
                story.append(Paragraph("Data gaps (do not fill with estimates):",
                                       styles["Heading3"]))
                for g in rep.data_gaps:
                    story.append(Paragraph(f"- {g}", styles["Normal"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(
                "Verification: third-party ISO 14064-3 assurance required before "
                "disclosure.", styles["Normal"]))
            doc.build(story)
            if st.download_button("Download PDF", buf.getvalue(),
                                  file_name="ocip_audit_evidence_pack.pdf",
                                  mime="application/pdf"):
                _log_event("pdf_export", report="evidence_pack")
    else:
        st.info("Upload at least the activity ledger + one removal observation "
                "in tab 1, then press **Run the audit**.")

# ==================================================================
# 3. EQUATIONS — the logic behind every number (Eq.1–10)
# ==================================================================
with tab_eq:
    st.header("UCST-CCIF equations — what each number means")
    st.caption("All ten numbered equations of the anchor manuscript are wired "
               "into the engine (`ucst_ccif` package). Each card below shows the "
               "equation, its one-line logic, where it runs in the pipeline, and "
               "its scientific status per manuscript Table 3. "
               "Paper: [ssrn.com/abstract=7417192](https://ssrn.com/abstract=7417192)")

    st.markdown("""
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:0.82rem;margin:6px 0 10px;">
      <div style="border:2px solid #B23A3A;border-radius:6px;padding:4px 8px;background:#FDF3F1;"><b>S3</b> Eq.(1) Conservation</div><span style="color:#5c6b7a;">→</span>
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>S4</b> Eq.(4)–(5) Scale</div><span style="color:#5c6b7a;">→</span>
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>S5</b> Eq.(2)+(3) Attribution / additionality</div><span style="color:#5c6b7a;">→</span>
      <div style="border:2px solid #B23A3A;border-radius:6px;padding:4px 8px;background:#FDF3F1;"><b>S6</b> Eq.(7) Leakage</div>
      <div style="margin-left:8px;color:#5c6b7a;">Library: Eq.(6) observation operator · CLI/paper scripts: Eq.(8)–(10) M0/M1/M3</div>
    </div>
    """, unsafe_allow_html=True)

    eq_cards = [
        dict(n="Eq. (1)", badge="Core in UI · S3 hard gate",
             title="Stock–flux accounting identity (conservation-constrained)",
             latex=(r"\frac{dC}{dt} = \sum_{j} F_{i\to j} - \sum_{j} F_{j\to i} "
                    r"+ Q_{env} + Q_{agent} + \varepsilon_C \quad,\quad "
                    r"\varepsilon_C = \Delta C_{obs} - \Delta C_{balance}"),
             logic="Carbon-pool change must equal net internal transfers + environmental in/out + agent-mediated in/out; the balance εC is a diagnostic residual, not a free correction term.",
             where="`compartments.step()` computes εC every step; the ledger version lives in `attribution.conservation_reconcile` (observed − claimed, negative = over-claim); stage S3 renders the PASS/FAIL verdict."),
        dict(n="Eq. (2)", badge="Optional in UI · S5b",
             title="Agent-mediated flux (compositional hypothesis)",
             latex=r"F_{agent} = f\big(E,\; z,\; g,\; \theta_{agent}\big)",
             logic="A flux is classified as agent-mediated (intervention test) only if changes in internal state z / management variable g reproducibly alter it; otherwise it counts as environmental flux.",
             where="`models.M2aAgent` (model competition); `attribution.attribution_split` (identifiable only if R² gain ≥ 0.005); filling the Agent-state column in the UI triggers it."),
        dict(n="Eq. (3)", badge="Core in UI · S5",
             title="Dual-force decomposition — active + passive (decomposition hypothesis)",
             latex=r"F_{hybrid} = F_{active} + F_{passive}",
             logic="Hybrid human interventions split into two: active trigger (deliberate human action) and passive response (post-intervention ecological dynamics). Additionality = intervention − baseline.",
             where="`models.m3_counterfactual` (military/restoration/DAC defaults for F_a/F_p); `attribution.additionality_counterfactual`; called directly by the Intervention ledger (Eq.3) in the UI."),
        dict(n="Eq. (4)", badge="Implemented · S4 time-series εA",
             title="Aggregation commutator residual (scale-translation hypothesis)",
             latex=(r"\varepsilon_A(s) = A(s)\big[\, f_s(x_s)\,\big] "
                    r"- f_{s+1}\big[\, A(s)\,x_s \,\big]"),
             logic="The same flux series walks two paths: evolve at fine scale then aggregate, minus aggregate then evolve — the difference is εA; stronger nonlinearity, within-month variance or spikes give larger εA; max|εA| above tolerance relative to total flux fails the scale check.",
             where="`audit_pipeline.time_series_scale_audit` lands this equation in the time dimension (daily integral vs monthly-mean then integrate; Tab 2/S4 shows the series and per-month εA); the stock-vs-flux scalar reconciliation remains as a secondary view. The spatial aggregation operator A(s) is not yet implemented."),
        dict(n="Eq. (5)", badge="Not implemented standalone",
             title="Downscaling operator (scale-translation hypothesis)",
             latex=r"x_{s} = D(s)\, x_{s+1} + \zeta(s)",
             logic="Coarse-scale state is rebuilt down to fine scale; ζ(s) carries fine-scale covariates absent from the coarse state; the residual needs a pre-specified tolerance.",
             where="No standalone downscaling operator yet; the S4 dual-ledger reconciliation partially covers it indirectly."),
        dict(n="Eq. (6)", badge="In library · not in UI",
             title="Observation model (measurement model)",
             latex=r"y^{(k)} = H^{(k)}(x) + b^{(k)} + \eta^{(k)}",
             logic="Observation ≠ truth: H is the observation operator, b the systematic bias, η the random error. Makes multi-source data comparable without assuming any single observation directly represents the full ecosystem state.",
             where="`assimilation.observation_operator()` (H explicit but currently the identity on NEE) + `nudge_update` relaxation assimilation (2σ threshold, absorbed into the least-certain pool)."),
        dict(n="Eq. (7)", badge="Core in UI · S6 hard gate",
             title="Flux partitioning → target leakage (algebraic identity)",
             latex=(r"\mathrm{GPP} - \mathrm{ER} = \mathrm{NEE} \quad\Rightarrow\quad "
                    r"\text{partitioned predictors leak the target}"),
             logic="GPP/ER are algebraic transforms of NEE: any model predicting NEE from GPP/ER/cumulative carbon balance circularly references the target — classify first, then screen for correlation, then refit leakage-free.",
             where="`leakage.py` three-step audit; S6 outputs the RYG flag + the apparent gain % of the leakage-free refit (Sapelo honest baseline: 36.1%)."),
        dict(n="Eq. (8)", badge="Implemented · CLI/paper scripts",
             title="M0 baseline — partitioned baseline model (15 parameters)",
             latex=(r"\mathrm{NEE}_{M0}(t) = \underbrace{\sum_{n=1}^{3}\big[ a_n \sin(n\omega t) + b_n \cos(n\omega t)\big]}_{\text{Fourier seasonal}} "
                    r"+ \sum_{i}\beta_i X_i(t) + c\, K_{hurricane}(t)"),
             logic="Third-order Fourier seasonality + exogenous meteorological predictors + exponentially decaying hurricane kernel; no system-level conservation constraint — the structural null hypothesis.",
             where="`models.M0Baseline` maps term by term; CLI `ucst-ccif compare`; paper scripts `03_Code/LiuYG_03*`. Now runnable in Tab 4."),
        dict(n="Eq. (9)", badge="Implemented · CLI/paper scripts",
             title="M1 conservation-constrained — conservation-integrated (17 parameters)",
             latex=(r"\mathrm{NEE}_{M1}(t) = \mathrm{NEE}_{M0}(t) + c_C\, C_{state}(t) "
                    r"+ c_{\Delta C}\, \Delta C_{state}(t)"),
             logic="Adds a purely exogenous, leakage-free conservation-state term to M0 (meteorological anomaly z-score → cumulative → detrended), testing whether the conservation constraint yields out-of-sample gain.",
             where="`models.M1Conservation` + `compute_conservation_state` (consistent with the manuscript's leakage-independent conservation-state definition); CLI compare — now runnable in Tab 4."),
        dict(n="Eq. (10)", badge="Available via Eq.(3)",
             title="M3 counterfactual scenarios (active + passive)",
             latex=(r"\Delta \mathrm{NEE}_{scenario} = F_{a} + F_{p} "
                    r"\qquad \text{(military / restoration / DAC)}"),
             logic="Dual-force counterfactuals on the calibrated M0 baseline: military damage = hybrid active-passive, ecological restoration = gradual mediated enhancement, DAC = purely exogenous active removal. Default F_a/F_p come from Sapelo Table 10.",
             where="`models.SCENARIO_PARAMS` + `m3_counterfactual` (gC/m²/d → tCO2e/ha/yr factor 13.383); called through the Intervention ledger in the UI — now also in Tab 4."),
    ]
    for e in eq_cards:
        with st.container(border=True):
            st.markdown(
                f"**{e['n']}** — {e['title']} &nbsp; "
                f"<span style='white-space:nowrap;background:#F2F5F9;border:1px solid #D8DEE4;"
                f"border-radius:20px;padding:1px 10px;font-size:0.78rem;color:#47596B'>{e['badge']}</span>",
                unsafe_allow_html=True)
            st.latex(e["latex"])
            st.caption(f"**Logic** {e['logic']}")
            st.caption(f"**Software location** {e['where']}")

    st.divider()
    st.caption("Role & status per manuscript Table 3: Eq.(1)(7) are conservation/"
               "algebraic identities — audit hard gates; Eq.(2)(3)(4)(5)(6) are "
               "composition/scale/measurement hypotheses — optional diagnostics; "
               "Eq.(8)(9)(10) are model specifications. This round: Eq.(4) time-series "
               "εA landed (Tab 2/S4) and the Eq.(8)(9)(10) model competition landed "
               "(Tab 4) — the software now reproduces the paper's §5 core result. "
               "Eq.(5) downscaling operator remains unimplemented.")

# ==================================================================
# 4. MODEL COMPETITION (M0–M3, Eq.8–10) — reproduce the paper
# ==================================================================
with tab_model:
    from ucst_ccif.models import model_competition, SCENARIO_PARAMS, m3_counterfactual
    st.header("M0–M3 model competition — reproduce the paper's core result")
    st.caption("Runs the nested M0 / M1 / (M2a) comparison of manuscript §5 on "
               "your flux ledger: does conservation (Eq.9) or agent feedback "
               "(Eq.2) beat the baseline (Eq.8) **out of sample**? Leakage-free "
               "by construction — GPP/ER columns are never used as predictors. "
               "Paper: [ssrn.com/abstract=7417192](https://ssrn.com/abstract=7417192)")

    st.markdown("""
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:0.82rem;margin:6px 0 10px;">
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>M0</b> Eq.(8) baseline · 15 params</div><span style="color:#5c6b7a;">→</span>
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>M1</b> Eq.(9) conservation state · 17 params</div><span style="color:#5c6b7a;">→</span>
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>M2a</b> Eq.(2) agent feedback · 19 params (§5)</div><span style="color:#5c6b7a;">→</span>
      <div style="border:1px solid #5c6b7a;border-radius:6px;padding:4px 8px;background:#f7f9fb;"><b>M3</b> Eq.(10) counterfactual scenario</div>
      <div style="margin-left:8px;color:#5c6b7a;">Protocol identical to paper §5: calib ≤ cutoff year · valid > cutoff year · leakage-free exogenous predictors</div>
    </div>
    """, unsafe_allow_html=True)

    model_df = st.session_state.get("ocip_model_df")
    up_model = st.file_uploader("Model CSV (date + NEE + meteorology; leave empty "
                                "to reuse the Tab-1 flux ledger)",
                                type=["csv"], key="up_model")
    if up_model is not None:
        try:
            model_df = pd.read_csv(up_model, comment="#")
            st.session_state["ocip_model_df"] = model_df
        except Exception as e:  # noqa: BLE001
            st.error(f"CSV parse failed: {e}")
    if model_df is None:
        model_df = st.session_state.get("ocip_flux")
    if model_df is None:
        st.info("No flux data available. Upload a flux ledger in **Tab 1** "
                "(a CSV with `date` + `NEE_daily_total`, e.g. "
                "`testdata/gba_flux_guangzhou_2023.csv`), or a model CSV "
                "above. The dataset is retained for the session after upload.")
    else:
        src = ("model CSV uploaded here"
               if st.session_state.get("ocip_model_df") is not None
               else "Tab 1 flux ledger")
        st.caption(f"Data source: **{src}** · {len(model_df)} rows × "
                   f"{len(model_df.columns)} columns · loaded")
        num_cols = [c for c in model_df.columns
                    if c != "date" and pd.api.types.is_numeric_dtype(model_df[c])]
        if not num_cols:
            st.error("No numeric columns in the data — cannot model.")
        else:
            target = st.selectbox("Target variable",
                                  list(dict.fromkeys(["NEE_daily_total"] + num_cols)),
                                  key="mc_target")
            # Leakage-free by construction (Eq.7): exclude every NEE/ER/GPP-derived
            # column plus time-structure columns from predictor candidates.
            reserved = {"disturbance", "year", "month"}
            reserved |= {c for c in num_cols
                         if c.upper().startswith(("NEE", "ER_", "GPP"))
                         and c != target}
            exo_candidates = [c for c in num_cols
                              if c not in reserved and c != target]
            exo_default = exo_candidates[:4]
            exo_cols = st.multiselect(
                "Exogenous predictors (leakage-free — NEE/ER/GPP-derived "
                "columns excluded, Eq.7)",
                exo_candidates, default=exo_default, key="mc_exo")
            if not exo_cols:
                st.warning("No exogenous predictors selected — M0/M1 reduce to "
                           "pure Fourier seasonality.")
            dist_options = [None] + [c for c in num_cols
                                     if "disturb" in c.lower()
                                     or "hurricane" in c.lower()]
            disturbance_col = st.selectbox("Disturbance kernel column (optional)",
                                           dist_options, key="mc_dist")
            agent_options = [None] + [c for c in exo_candidates
                                      if c not in set(exo_cols)]
            agent_col = st.selectbox("Agent-state column (management signal — "
                                     "enables M2a, Eq.2)",
                                     agent_options, key="mc_agent")
            if len(agent_options) == 1:
                st.caption("No management-signal column in the data — M2a (Eq.2) "
                           "is skipped. Add a column such as `water_level` or "
                           "`mangrove_age` to enable the agent-feedback model.")
            calib_year = st.number_input("Calibration end year", 2000, 2100, 2020,
                                         key="mc_calib")
            if st.button("Run model competition", type="primary"):
                try:
                    out = model_competition(
                        model_df, target, list(exo_cols),
                        calib_end_year=int(calib_year),
                        agent_col=agent_col or None,
                        disturbance_col=disturbance_col or None)
                    st.session_state["ocip_model_result"] = out
                except Exception as e:  # noqa: BLE001
                    st.error(f"Model competition failed: {e}")

            out = st.session_state.get("ocip_model_result")
            if out is not None:
                res = out["results"]
                rows = [{"Model": n, "n_params": r.n_params,
                         "calib RMSE": round(r.calib_rmse, 4),
                         "valid RMSE": round(r.valid_rmse, 4),
                         "valid R²": round(r.valid_r2, 4),
                         "valid MAE": round(r.valid_mae, 4)}
                        for n, r in res.items()]
                st.markdown("**Out-of-sample metrics** "
                            "(calib ≤ year · valid > year)")
                st.dataframe(pd.DataFrame(rows), width="stretch")

                st.markdown("**Validation RMSE by model**")
                st.bar_chart(pd.DataFrame(
                    {"model": list(res),
                     "valid_rmse": [r.valid_rmse for r in res.values()]}
                ).set_index("model"), height=200)

                st.markdown("**Validation predictions vs observed (last 365 days)**")
                v = out["valid"]
                plot_cols = ["date", "observed"] + [f"pred_{n}" for n in res]
                st.line_chart(v[plot_cols].tail(365).set_index("date"), height=220)

                if "M1" in res and "M0" in res:
                    d1 = (res["M0"].valid_rmse - res["M1"].valid_rmse) \
                        / res["M0"].valid_rmse * 100.0
                    st.caption(f"M1 vs M0: ΔRMSE = {d1:+.1f}% — paper §5 daily: "
                               f"−1.6% (conservation adds no out-of-sample gain).")
                if agent_col and "M2a" in res and "M1" in res:
                    d2 = (res["M1"].valid_rmse - res["M2a"].valid_rmse) \
                        / res["M1"].valid_rmse * 100.0
                    st.caption(f"M2a vs M1: ΔRMSE = {d2:+.1f}% — paper: negligible "
                               f"predictive benefit at daily scale.")

                st.divider()
                st.subheader("M3 — counterfactual human-agency scenarios (Eq.10)")
                st.caption("Active trigger F_a + passive response F_p applied to "
                           "the baseline. Defaults from Sapelo Table 10; override "
                           "with site data. **Illustrative, not a forecast.**")
                scen = st.selectbox("Scenario", list(SCENARIO_PARAMS), key="mc_scen")
                sp = SCENARIO_PARAMS[scen]
                f1, f2, f3 = st.columns(3)
                fa = f1.number_input("F_a (active trigger)", value=sp["F_a"],
                                     step=0.01, format="%.3f", key="mc_fa")
                fp = f2.number_input("F_p (passive response)", value=sp["F_p"],
                                     step=0.01, format="%.3f", key="mc_fp")
                m3_area = f3.number_input("Area (ha)", 0.0, 1e7, 100.0,
                                          step=10.0, key="mc_m3_area")
                base_nee = float(v["observed"].mean())
                m3 = m3_counterfactual(base_nee, scenario=scen, area_ha=m3_area,
                                       F_a=fa, F_p=fp)
                g1, g2, g3, g4 = st.columns(4)
                g1.metric("ΔNEE", f"{m3['delta_nee_gCm2_d']:+.3f} gC/m²/d",
                          help="F_a + F_p (negative = more uptake)")
                g2.metric("Extra removal",
                          f"{m3['extra_removal_tco2e_ha_yr']:+,.1f} tCO₂e/ha/yr",
                          help="Negative = extra emission pressure")
                g3.metric("Active share", f"{m3['active_share_of_change']:.0%}",
                          help="F_a as a share of the total change")
                g4.metric("Total (area)",
                          (f"{m3['extra_removal_tco2e_yr']:+,.1f} tCO₂e/yr"
                           if "extra_removal_tco2e_yr" in m3 else "—"),
                          help="Extra removal × project area")
                st.caption(m3["illustrative_note"])

# ==================================================================
# 5. BENCHMARKS (official reference data + stress lens)
# ==================================================================
with tab_bench:
    st.header("Benchmarks — official reference data")
    st.caption("These numbers are **external standards**, not your data: they give "
               "your audit a frame of reference. Sources: CEADs 2022 (Guangdong) · "
               "Global Carbon Budget 2025 · HK EPD GHG inventory 2023 · IPCC/CCER.")

    # --- A. GBA human sectors (CEADs 2022, Guangdong) ---
    st.markdown('<span class="ocip-section">A. GBA human sectors — Guangdong 2022 (CEADs, Mt CO₂)</span>',
                unsafe_allow_html=True)
    gd_sectors = {
        "Electric power": 379.2, "Cement & minerals": 57.7,
        "Transport & logistics": 46.6, "Iron & steel": 34.7,
        "Urban residential": 26.3, "Nonferrous metals": 14.0,
        "Rural residential": 13.4, "Wholesale & catering": 12.5,
        "Petroleum refining": 8.1,
    }
    st.bar_chart(pd.DataFrame({"Sector": list(gd_sectors),
                               "MtCO2": list(gd_sectors.values())}).set_index("Sector"),
                 height=240)
    g1, g2 = st.columns(2)
    g1.metric("Guangdong total (2022)", "613.9 Mt CO₂",
              help="CEADs Shan et al. provincial sectoral inventory, IPCC Sectoral Approach")
    g2.metric("Power & heat share", "61.8%",
              help="Electric power dominates — the CBAM/ETS hotspot for GBA exporters")

    # --- B. Global (GCB2025, 2024) ---
    st.markdown('<span class="ocip-section">B. Global human emissions — fossil + land-use (GCB2025, 2024)</span>',
                unsafe_allow_html=True)
    fossil = {"Coal": 4.31, "Oil": 3.40, "Gas": 2.19, "Cement": 0.40, "Other": 0.42}
    st.bar_chart(pd.DataFrame({"Fuel": list(fossil),
                               "GtC per yr": list(fossil.values())}).set_index("Fuel"),
                 height=200)
    b1, b2, b3 = st.columns(3)
    b1.metric("Fossil + cement", "10.53 GtC/yr", "≈ 38.6 GtCO₂/yr")
    b2.metric("Land-use change", "1.25 GtC/yr", "≈ 4.6 GtCO₂/yr")
    b3.metric("Atmospheric growth", "+4.9 GtC/yr",
              help="≈ 49% of emissions stay in the atmosphere; the rest goes to sinks")

    # --- C. Nature ledger ---
    st.markdown('<span class="ocip-section">C. Nature ledger — where the rest goes (GCB2025)</span>',
                unsafe_allow_html=True)
    n1, n2, n3 = st.columns(3)
    n1.metric("Ocean sink", "3.1 GtC/yr", "≈ 11.4 GtCO₂/yr")
    n2.metric("Land sink", "2.5 GtC/yr", "≈ 9.2 GtCO₂/yr (incl. blue carbon)")
    n3.metric("Total sinks", "5.6 GtC/yr", "vs 11.8 emitted")

    # --- D. HK sectors (EPD 2023) ---
    st.markdown('<span class="ocip-section">D. Hong Kong sectors — GHG inventory 2023 (EPD, kt CO₂e)</span>',
                unsafe_allow_html=True)
    hk_sectors = {
        "Electricity & energy ind.": 21200, "Transport": 6330,
        "Industrial processes & other": 2920, "Waste": 2410,
        "Other combustion": 1660, "Agriculture": 28,
    }
    st.bar_chart(pd.DataFrame({"Sector": list(hk_sectors),
                               "ktCO2e": list(hk_sectors.values())}).set_index("Sector"),
                 height=200)
    h1, h2, h3 = st.columns(3)
    h1.metric("HK total (2023)", "34.5 Mt CO₂e",
              help="≈ −25% vs 2014 peak; EPD GHG inventory, revised methodology")
    h2.metric("Electricity share", "61.3%",
              help="Power is HK's dominant source — same story as Guangdong, same CBAM lens")
    h3.metric("Per-capita", "4.6 t CO₂e",
              help="Record low since 1990s (7.5M population)")

    # --- E. CH4 kernels (rice + landfill) ---
    st.markdown('<span class="ocip-section">E. CH₄ — rice paddies & landfills (GBA, IPCC/DNDC kernels)</span>',
                unsafe_allow_html=True)
    c_rice, c_land = st.columns(2)
    with c_rice:
        with st.container(border=True):
            from ucst_ccif.dndc_lite import rice_ch4_season, RICE_WATER_REGIMES
            st.markdown("**Rice paddies (DNDC-lite, IPCC scaling)**")
            regime = st.selectbox("Water regime", list(RICE_WATER_REGIMES), key="rice_regime")
            rice_days = st.slider("Season length (days)", 90, 180, 120, key="rice_days")
            rice_ha = st.number_input("Area (ha)", 1.0, 10000.0, 100.0, key="rice_ha")
            try:
                est = rice_ch4_season(regime, rice_days, area_ha=rice_ha)
                st.metric("Seasonal CH₄", f"{est.total_kgCH4:.1f} kg",
                          f"{est.total_tCO2e:.1f} tCO₂e (GWP28)")
            except KeyError as e:
                st.error(str(e))
    with c_land:
        with st.container(border=True):
            from ucst_ccif.landfill import landfill_ch4_tier1
            st.markdown("**Landfills (IPCC 2006/2019 Tier-1)**")
            msw_t = st.number_input("Waste disposed (t/yr)", 0.0, 10_000_000.0,
                                    1_500_000.0, step=50_000.0, key="land_msw")
            lf_type = st.selectbox("Landfill type",
                                   ["managed_anaerobic", "managed_semi_aerobic",
                                    "unmanaged_deep", "unmanaged_shallow",
                                    "uncategorised"], key="land_type")
            lr = landfill_ch4_tier1(msw_t, mcf_key=lf_type)
            st.metric("Landfill CH₄", f"{lr.ch4_t:.1f} t CH₄/yr",
                      f"{lr.co2e_t_ar5:.1f} tCO₂e/yr (AR5 GWP28)")
    st.caption("CH₄ has ~28× GWP of CO₂: the GBA CH₄ wedge is rice + landfills "
               "+ tidal wetlands — OCIP audits all three on one CH₄ ledger.")

    # --- F. CCER mangrove lookup (screening tool) ---
    st.markdown('<span class="ocip-section">F. CCER mangrove restoration — project screening lookup</span>',
                unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("Methodology: **CCER—14—002—V02 mangrove afforestation** "
                    "(2026 revision, "
                    "age-based lookup; baseline = unvegetated tidal flat / retired shrimp pond). "
                    "This is a **pre-screening estimate**, not a credit claim — official "
                    "crediting requires CCER field measurement per the methodology age-based "
                    "tables (App. A, Guangdong region).")
        f1, f2, f3 = st.columns(3)
        f1.metric("Default crediting period", "20–40 yr", help="CCER methodology crediting period")
        f2.metric("GD mangrove C stock", "3.22 Mt C",
                  help="Guangdong province (Kandelia obovata dominant)")
        f3.metric("GD sink potential", "6.6–18.2 tCO₂e/ha/yr",
                  help="55 km² target → 36,171–99,891 tCO₂e/yr")
        proj_area = st.number_input("Your project area (ha)", 0.0, 100000.0,
                                    100.0, key="ccer_area")
        proj_age = st.slider("Mean stand age (yr)", 1, 50, 10, key="ccer_age")
        agb_accum = 0.35 * proj_age + 1.2          # Mg C/ha (above+below, saturating proxy)
        soil_acc = 0.35                             # Mg C/ha/yr burial
        tot_acc = agb_accum + soil_acc * proj_age   # Mg C/ha cumulative
        co2_per_ha = tot_acc * 44.0 / 12.0
        st.metric("Estimated cumulative carbon", f"{co2_per_ha * proj_area:,.0f} tCO₂e",
                  f"{co2_per_ha:.1f} tCO₂e/ha over {proj_age} yr (order-of-magnitude)")

    # --- G. NGFS stress lens (based on your audit) ---
    st.markdown('<span class="ocip-section">G. NGFS Phase V — stress lens on your inventory</span>',
                unsafe_allow_html=True)
    st.caption("Carbon-price & physical-risk lens. Uses your audited emissions when "
               "available, otherwise the demo activity in the activity template.")
    rep_now = st.session_state.get("ocip_report")
    stress_base = (rep_now.emissions_tco2e if rep_now is not None
                   and rep_now.emissions_tco2e is not None else None)
    if stress_base is None:
        # fall back to demo activity ledger (template example), same as S1 would
        demo_act = pd.DataFrame([
            {"scope": "2", "category": "electricity",
             "activity_key": "guangdong", "quantity": 1135589.4},
            {"scope": "1", "category": "fuel",
             "activity_key": "diesel_L", "quantity": 20000},
        ])
        from ucst_ccif.audit_pipeline import _validate_activity
        try:
            stress_base = _validate_activity(demo_act)["tco2e"].sum()
        except Exception:  # noqa: BLE001
            stress_base = None
    if stress_base is not None:
        ngfs = {
            "Orderly": {"carbon_price_2030": 150, "physical_risk": "low"},
            "Disorderly": {"carbon_price_2030": 350, "physical_risk": "medium"},
            "Hot House": {"carbon_price_2030": 15, "physical_risk": "high"},
        }
        sc = st.selectbox("Scenario", list(ngfs.keys()))
        c1, c2 = st.columns(2)
        c1.metric("Carbon price 2030 (US$/tCO2)", ngfs[sc]["carbon_price_2030"])
        c2.metric("Physical risk", ngfs[sc]["physical_risk"])
        st.caption(f"Under {sc.lower()}, a {ngfs[sc]['carbon_price_2030']} $/t price on "
                   f"your {stress_base:.1f} tCO₂e → "
                   f"**US${ngfs[sc]['carbon_price_2030'] * stress_base:,.0f} exposure.**")
    else:
        st.info("Run the audit first (tab 2) to stress-test your verified emissions.")

    # --- H. How to use / data sources ---
    st.markdown('<span class="ocip-section">H. How to use & where the data comes from</span>',
                unsafe_allow_html=True)
    st.markdown(
        "**Verification workflow.** Three rules:\n\n"
        "1. **Upload** — your four ledgers are the only thing the audit consumes. "
        "Missing files are reported as data gaps, never silently estimated.\n"
        "2. **Run** — the 7-step pipeline verifies your numbers against independent "
        "observation and official benchmarks; the certificate is the verdict.\n"
        "3. **Benchmark** — CEADs / GCB / HK EPD / IPCC / CCER are external standards "
        "for comparison, not substitutes for your data.\n\n"
        "Free data sources: FLUXNET (fluxnet.org, CC-BY-4.0) · JapanFlux2024 · "
        "ChinaFLUX/NESDC (Jinfo 2020–2022) · CEADs provincial · HK EPD · ERA5/Open-Meteo · "
        "TROPOMI CH₄ · Sentinel-2/GEDI biomass. Column-level sourcing is "
        "documented in each ledger's column dictionary."
    )

# ==================================================================
# 6. DATA & HISTORY — what the platform remembers
# ==================================================================
with tab_data:
    st.header("Data & history — what the platform remembers")
    st.caption("Every upload becomes an immutable, checksum-addressed **load**; "
               "every audit becomes a **run** pointing at the loads it consumed. "
               "Both are scoped by organisation and site — tenants never see "
               "each other's ledger rows.")

    data_store, data_reason = _store()
    if data_store is None:
        st.warning(f"No database linked — this session is memory-only ({data_reason}).")
        st.markdown(
            "**Link PostgreSQL** by adding the connection string to "
            "`.streamlit/secrets.toml` (local) or the *Secrets* panel of the "
            "deployed app:\n\n"
            "```toml\n"
            "[postgres]\n"
            'url = "postgresql+psycopg://USER:PASS@HOST:5432/ocip?sslmode=require"\n'
            "\n[ocip]\n"
            'default_org  = "cityu"\n'
            'default_site = "GBA-DEMO-01"\n'
            "```\n\n"
            "Reboot the app afterwards. The schema is created on first connect; "
            "`python -m ucst_ccif.store --selftest --url <url>` round-trips it and "
            "cleans up after itself.")

        fb_url = _secret("ocip", "feedback_url", default=None)
        if fb_url:
            st.markdown(f"**Feedback:** [{fb_url}]({fb_url})")
        else:
            st.caption("Feedback channel not configured — set `[ocip].feedback_url` "
                       "in secrets to collect comments without a database.")
    else:
        email, org = _identity()
        site = _current_site()
        history = data_store.audit_history(org_id=org, site_id=site)
        load_rows = data_store.loads(org_id=org, site_id=site)

        c1, c2, c3 = st.columns(3)
        c1.metric("Audit runs", len(history))
        c2.metric("Ledger loads", len(load_rows))
        c3.metric("Latest certificate",
                  history.iloc[0]["certificate_status"] if len(history) else "—")
        st.caption(f"`{data_store.dialect}` · org `{org}` · site `{site}` · "
                   f"user `{email}`")

        with st.expander("Audit history", expanded=True):
            if history.empty:
                st.info("No audit run stored for this organisation/site yet — "
                        "run one in tab 2.")
            else:
                show = history.rename(columns={
                    "run_id": "Run", "label": "Label", "created_at": "When",
                    "created_by": "By", "certificate_status": "Certificate",
                    "emissions_tco2e": "Emissions (tCO2e)",
                    "removals_tco2e": "Removals (tCO2e)",
                    "residual_ec_tco2e": "ε_C (tCO2e)",
                    "leakage_ryg": "Leakage", "area_ha": "Area (ha)",
                    "grid_region": "Grid"})
                st.dataframe(show, width="stretch")
                st.download_button(
                    "Download history (CSV)",
                    show.to_csv(index=False).encode("utf-8"),
                    file_name=f"ocip_audit_history_{site}.csv",
                    mime="text/csv")

        with st.expander("Ledger provenance — which file produced which numbers"):
            if load_rows.empty:
                st.info("No ledger load stored yet — upload a CSV in tab 1.")
            else:
                show = load_rows.rename(columns={
                    "load_id": "Load", "ledger_type": "Ledger",
                    "file_name": "File", "sha256": "SHA-256",
                    "row_count": "Rows", "loaded_at": "Loaded",
                    "loaded_by": "By"})
                st.dataframe(show, width="stretch")
                st.caption("Re-uploading identical bytes returns the same load id, "
                           "so an audit that cites a load always cites the same rows.")
                st.download_button(
                    "Download provenance (CSV)",
                    show.to_csv(index=False).encode("utf-8"),
                    file_name=f"ocip_ledger_loads_{site}.csv",
                    mime="text/csv")

        with st.expander("Stored report (JSON)", expanded=False):
            if history.empty:
                st.caption("Nothing stored yet.")
            else:
                labels = dict(zip(history["run_id"], history["label"]))
                pick = st.selectbox(
                    "Run", history["run_id"].tolist(),
                    format_func=lambda r: f"{r[:8]} · {labels.get(r) or '—'}")
                payload = data_store.run_report(pick)
                st.json(payload["report"])
                loads_used = payload["loads"] or {}
                if loads_used:
                    st.caption("Loads consumed: "
                               + " · ".join(f"{k}={str(v)[:8]}"
                                            for k, v in loads_used.items()))

        with st.expander("Reference factor library (global, not org-scoped)"):
            st.dataframe(data_store.factor_versions(), width="stretch")
            st.caption("Seeded from `ucst_ccif/emission_factors.py` on first boot. "
                       "Update a factor by adding a new version row — never by "
                       "overwriting the old one.")

        st.divider()
        st.markdown('<span class="ocip-section">Feedback — what confused you first?'
                    '</span>', unsafe_allow_html=True)
        _log_once("fbview", "feedback_view", tab="6. Data & history")
        with st.form("ocip_feedback", clear_on_submit=True):
            comment = st.text_area("What was unclear, wrong, or missing?",
                                   key="ocip_fb_comment", height=90,
                                   placeholder="One sentence is enough — e.g. "
                                               "'I did not know which column the "
                                               "flux ledger expected'.")
            rating = st.slider("How useful was this session?", 1, 5, 3,
                               key="ocip_fb_rating")
            contact = st.text_input("Email (optional — only if you want a reply)",
                                    key="ocip_fb_contact")
            sent = st.form_submit_button("Send feedback", type="primary")
        if sent:
            if not comment.strip():
                st.warning("Add a sentence first — a rating alone is not actionable.")
            else:
                try:
                    data_store.add_feedback(
                        org_id=org, site_id=site, comment=comment, rating=rating,
                        tab="6. Data & history",
                        run_id=st.session_state.get("ocip_last_run"),
                        contact_email=(contact.strip() or None), created_by=email)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not store feedback: {exc}")
                else:
                    st.success("Thank you — stored with your organisation and site.")

        st.caption("Need ad-hoc SQL? Use your provider's console (Neon, Supabase) "
                   "with a read-only role. The app exposes no free-form query box, "
                   "so a shared link cannot read another tenant's ledger.")

# ------------------------------------------------------------------
st.markdown(f"""
<div class="ocip-footer">
  OCIP {APP_VERSION} · UCST-CCIF engine · {GITHUB_URL} · DOI {DOI_URL}<br/>
  Every audit output is traceable to source data and equations.
</div>
""", unsafe_allow_html=True)
