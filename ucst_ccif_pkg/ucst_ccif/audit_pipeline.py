"""
OCIP audit pipeline — stages S1..S7 (MVP v0.3).

Turns the four ledgers (activity / flux / stock / intervention) plus the
factor library into one auditable report. Every stage is optional-input
tolerant: a missing ledger is *reported* as a data gap, never silently
filled with an estimate.

Stage map (matches the OCIP 7-step flow):
    S1  boundary & bookkeeping  (column validation, unit sanity)
    S2  ingest & factors        (activity x factor library -> emissions)
    S3  conservation            (Eq.1: emissions vs observed removals -> e_C)
    S4  scale reconciliation    (Eq.4-5: time-series commutator εA + stock/flux cross-check)
    S5  attribution & additionality (Eq.2-3: passive vs active)
    S6  leakage audit           (Eq.7 + 3-step screen incl. no-leak refit)
    S7  uncertainty & report    (intervals, RYG statuses, certificate)

Output (8 artifacts):
    1. verified emission interval       5. leakage RYG flag
    2. verified removal interval        6. attribution decomposition
    3. conservation residual e_C        7. uncertainty budget
    4. scale residual e_A               8. audit certificate
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence
import numpy as np
import pandas as pd

from .attribution import (
    C_TO_CO2,
    conservation_reconcile,
    additionality_counterfactual,
    attribution_split,
)
from .leakage import audit_leakage, refit_without_leakage, LeakageReport
from .emission_factors import (
    FUELS, GRID_FACTORS_MEE_2022, TD_LOSS_RATE,
    TRAVEL_FACTORS, COMMUTE_FACTORS, SPEND_FACTORS,
)

# Default uncertainty budget (relative u95, configurable per user).
DEFAULT_U95_EMISSIONS = 0.10   # activity x factor
DEFAULT_U95_REMOVALS = 0.15    # eddy-covariance / biometric

ACTIVITY_REQUIRED_COLS = ["scope", "category", "activity_key", "quantity"]
FLUX_REQUIRED_COLS = ["date", "NEE_daily_total"]
STOCK_REQUIRED_COLS = ["area_ha", "removal_tco2e"]
INTERVENTION_REQUIRED_COLS = ["scenario", "baseline_removal_tco2e",
                              "intervention_removal_tco2e"]


@dataclass
class StageStatus:
    stage: str
    name: str
    status: str          # "passed" | "flagged" | "not_run" | "warning"
    detail: str = ""


@dataclass
class AuditReport:
    """Full output of `run_audit` — the eight auditable artifacts."""
    # 1. verified emission interval
    emissions_tco2e: float | None = None
    emissions_u95_tco2e: float | None = None
    # 2. verified removal interval
    removals_tco2e: float | None = None
    removals_u95_tco2e: float | None = None
    # 3. conservation residual (Eq.1)
    residual_eC_tco2e: float | None = None
    residual_eC_status: str = "not_run"
    # 4. scale residual (Eq.4-5)
    scale_residual_eA_tco2e: float | None = None
    scale_residual_status: str = "not_run"
    scale_audit: Dict[str, Any] = field(default_factory=dict)  # time-series εA
    # 5. leakage RYG
    leakage_ryg: str = "grey"            # green | amber | red | grey(no data)
    leakage: LeakageReport | None = None
    leak_free_gain_pct: float | None = None
    # 6. attribution decomposition
    attribution: Dict[str, Any] = field(default_factory=dict)
    additionality: Dict[str, Any] = field(default_factory=dict)
    # 7. uncertainty budget
    uncertainty_budget: Dict[str, float] = field(default_factory=dict)
    # 8. certificate
    stages: list[StageStatus] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    certificate_status: str = "incomplete"

    # ---- eight-artifact accessors ----
    def artifacts(self) -> Dict[str, Any]:
        return {
            "verified_emission_interval": (
                None if self.emissions_tco2e is None else
                [self.emissions_tco2e - self.emissions_u95_tco2e,
                 self.emissions_tco2e + self.emissions_u95_tco2e]),
            "verified_removal_interval": (
                None if self.removals_tco2e is None else
                [self.removals_tco2e - self.removals_u95_tco2e,
                 self.removals_tco2e + self.removals_u95_tco2e]),
            "conservation_residual_eC": self.residual_eC_tco2e,
            "scale_residual_eA": self.scale_residual_eA_tco2e,
            "leakage_ryg": self.leakage_ryg,
            "attribution_decomposition": self.attribution,
            "uncertainty_budget": self.uncertainty_budget,
            "audit_certificate": self.certificate_status,
        }

    def summary(self) -> str:
        lines = ["=" * 62, "OCIP AUDIT REPORT — 8 artifacts", "=" * 62]
        art = self.artifacts()
        for k, v in art.items():
            lines.append(f"  {k:<28} : {v}")
        lines.append("-" * 62)
        lines.append("Stage log:")
        for s in self.stages:
            lines.append(f"  [{s.status:>7}] S{s.stage} {s.name} — {s.detail}")
        if self.data_gaps:
            lines.append("Data gaps (do not fill with estimates):")
            for g in self.data_gaps:
                lines.append(f"  - {g}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Stage helpers
# --------------------------------------------------------------------------
def _check_columns(df: Optional[pd.DataFrame], name: str,
                   required: Sequence[str]) -> list[str]:
    if df is None:
        return [f"{name}: no data uploaded"]
    missing = [c for c in required if c not in df.columns]
    return [] if not missing else [f"{name}: missing columns {missing}"]


def _validate_activity(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise the activity ledger into tCO2e per row using the factor lib."""
    rows = []
    for _, r in df.iterrows():
        scope = str(r.get("scope", "")).strip()
        cat = str(r.get("category", "")).strip()
        key = str(r.get("activity_key", "")).strip()
        qty = float(r.get("quantity", 0.0) or 0.0)
        t = 0.0
        src = ""
        if cat == "fuel" and key in FUELS:
            t = FUELS[key].ef_kgCO2_unit * qty / 1000.0
            src = "MEE App.A"
        elif cat == "electricity" and key in GRID_FACTORS_MEE_2022:
            t = GRID_FACTORS_MEE_2022[key] * qty / 1000.0
            src = "MEE 2024 No.33"
        elif cat == "purchased_goods" and key in SPEND_FACTORS:
            t = SPEND_FACTORS[key] * qty / 1000.0
            src = "IO rough (EXIOBASE for prod.)"
        elif cat == "travel" and key in TRAVEL_FACTORS:
            t = TRAVEL_FACTORS[key] * qty / 1000.0
            src = "DEFRA/ICAO-style default"
        elif cat == "commute" and key in COMMUTE_FACTORS:
            t = COMMUTE_FACTORS[key] * qty * 2 * 230 / 1_000_000.0
            src = "metro-style default (230 d/yr)"
        rows.append({"scope": scope, "category": cat, "activity_key": key,
                     "quantity": qty, "tco2e": t, "source": src})
    return pd.DataFrame(rows)


def _flux_to_tco2e(flux_df: pd.DataFrame, area_ha: float) -> float:
    """Annualise daily NEE (gC m-2 d-1) into tCO2e for the given area."""
    nee = pd.to_numeric(flux_df["NEE_daily_total"], errors="coerce").dropna()
    if len(nee) == 0:
        return 0.0
    mean_nee = float(nee.mean())
    # negative NEE = sink -> positive removal
    return -mean_nee * 365.0 * area_ha * 1e4 * C_TO_CO2 / 1e6


def time_series_scale_audit(
    flux_df: pd.DataFrame,
    date_col: str = "date",
    flux_col: str = "NEE_daily_total",
    tol_pct: float = 5.0,
    min_days: int = 30,
) -> Dict[str, Any]:
    """
    Eq.(4) aggregation-commutator residual, landed in the time dimension.

    Two paths over the same daily flux series:
      fine   : evolve at fine scale first (daily integral), then aggregate;
      coarse : aggregate first (monthly mean), then evolve at coarse scale.
    For stationary linear series the two coincide; sub-month variance,
    sign changes and transient spikes make them differ. The residual
    eps_A(t) = C_fine(t) - C_coarse(t) is computed per day; max |eps_A|
    relative to the total |flux| is compared against the pre-specified
    tolerance (default 5%) — this is the scale-consistency gate of Eq.(4).

    Returns a dict with the residual summary and per-month worst residuals
    (used to surface *where* aggregation loses most information).
    """
    df = flux_df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col, flux_col]).sort_values(date_col)
    if len(df) < min_days:
        return {"status": "not_run",
                "reason": f"need >= {min_days} daily records, got {len(df)}"}
    y = pd.to_numeric(df[flux_col], errors="coerce").fillna(0.0).values
    c_fine = np.cumsum(y)
    ym = df.assign(_ym=df[date_col].dt.to_period("M"))
    monthly_mean = ym.groupby("_ym")[flux_col].transform("mean")
    c_coarse = np.cumsum(
        pd.to_numeric(monthly_mean, errors="coerce").fillna(0.0).values)
    eps = c_fine - c_coarse
    total_abs = float(np.sum(np.abs(y)))
    max_abs = float(np.max(np.abs(eps)))
    rel_pct = max_abs / total_abs * 100.0 if total_abs > 0 else 0.0
    status = "balanced" if rel_pct <= tol_pct else "flagged"
    ym = ym.assign(_eps=eps)
    monthly_worst: Dict[str, float] = {}
    for period, sub in ym.groupby("_ym"):
        idx = int(np.argmax(np.abs(sub["_eps"].values)))
        monthly_worst[str(period)] = float(sub["_eps"].values[idx])
    return {
        "status": status,
        "tol_pct": tol_pct,
        "n_days": int(len(df)),
        "eps_final_gCm2": float(eps[-1]),
        "eps_max_abs_gCm2": max_abs,
        "eps_mean_abs_gCm2": float(np.mean(np.abs(eps))),
        "relative_max_pct": rel_pct,
        "total_abs_flux_gCm2": total_abs,
        "monthly_worst_gCm2": monthly_worst,
    }


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------
def run_audit(
    activity_df: Optional[pd.DataFrame] = None,
    flux_df: Optional[pd.DataFrame] = None,
    stock_df: Optional[pd.DataFrame] = None,
    intervention_df: Optional[pd.DataFrame] = None,
    area_ha: float | None = None,
    grid_region: str = "guangdong",
    agent_col: str | None = None,
    claimed_removals_tco2e: float | None = None,
    u95_emissions: float = DEFAULT_U95_EMISSIONS,
    u95_removals: float = DEFAULT_U95_REMOVALS,
) -> AuditReport:
    """Run the S1..S7 pipeline on the four ledgers.

    activity_df columns : scope, category, activity_key, quantity
                          (categories: fuel | electricity | purchased_goods |
                           travel | commute)
    flux_df columns     : date, NEE_daily_total[, GPP_daily_total, ER_daily_total,
                          meteo columns...]
    stock_df columns    : area_ha, removal_tco2e  (independent observation)
    intervention_df cols: scenario, baseline_removal_tco2e,
                          intervention_removal_tco2e[, active_fraction]

    `claimed_removals_tco2e` is the company's own removal claim — it is
    compared against the *observed* removal (stock ledger or flux) in S3.
    When the claim is not supplied it is inferred from the observation and
    the conservation gate reports "no discriminating power".

    Returns an :class:`AuditReport` with the eight artifacts. Missing inputs
    are recorded as data gaps — the certificate never claims completeness.
    """
    rep = AuditReport()
    gaps: list[str] = []
    stages: list[StageStatus] = []

    # ---- S1 boundary & bookkeeping ----
    s1_gaps = (
        _check_columns(activity_df, "activity ledger", ACTIVITY_REQUIRED_COLS)
        + _check_columns(flux_df, "flux ledger", FLUX_REQUIRED_COLS)
        + _check_columns(stock_df, "stock ledger", STOCK_REQUIRED_COLS)
        + _check_columns(intervention_df, "intervention ledger",
                         INTERVENTION_REQUIRED_COLS)
    )
    gaps.extend(s1_gaps)
    stages.append(StageStatus(
        "1", "Boundary & bookkeeping",
        "warning" if s1_gaps else "passed",
        "; ".join(s1_gaps) if s1_gaps else "all four ledgers recognised"))

    # ---- S2 ingest & factors ----
    emissions = None
    if activity_df is not None and len(activity_df):
        norm = _validate_activity(activity_df)
        emissions = float(norm["tco2e"].sum())
        unknown = norm[norm["tco2e"] == 0.0]
        if len(unknown):
            gaps.append(f"activity ledger: {len(unknown)} row(s) with unknown "
                        f"category/key (not counted)")
        stages.append(StageStatus("2", "Ingest & factors", "passed",
                                  f"{emissions:,.1f} tCO2e from "
                                  f"{len(norm)} activity row(s)"))
    else:
        stages.append(StageStatus("2", "Ingest & factors", "not_run",
                                  "no activity ledger"))

    # ---- S7 uncertainty (budget assembled early, reported late) ----
    budget: Dict[str, float] = {}
    if emissions is not None:
        budget["emissions_u95_rel"] = u95_emissions
        budget["emissions_u95_tco2e"] = emissions * u95_emissions
    if flux_df is not None or stock_df is not None:
        budget["removals_u95_rel"] = u95_removals

    # ---- S3 conservation (Eq.1) ----
    observed_removals = None
    if stock_df is not None and len(stock_df) and "removal_tco2e" in stock_df.columns:
        observed_removals = float(pd.to_numeric(
            stock_df["removal_tco2e"], errors="coerce").sum())
    elif flux_df is not None and area_ha:
        observed_removals = _flux_to_tco2e(flux_df, area_ha)

    if emissions is not None and observed_removals is not None:
        claimed = (float(claimed_removals_tco2e)
                   if claimed_removals_tco2e is not None else observed_removals)
        rec = conservation_reconcile(emissions, claimed, observed_removals)
        rep.residual_eC_tco2e = rec.residual_tco2e
        rep.residual_eC_status = rec.status
        rep.removals_tco2e = observed_removals
        rep.removals_u95_tco2e = observed_removals * u95_removals
        detail = (f"e_C = {rec.residual_tco2e:+,.1f} tCO2e "
                  f"(claim {claimed:,.1f} vs obs {observed_removals:,.1f})")
        if claimed_removals_tco2e is None:
            detail += " | claim inferred from obs — no discriminating power"
        stages.append(StageStatus("3", "Conservation (Eq.1)", rec.status, detail))
    else:
        stages.append(StageStatus("3", "Conservation (Eq.1)", "not_run",
                                  "need emissions + observed removals"))
        if flux_df is not None and not area_ha:
            gaps.append("flux ledger uploaded but area_ha not given "
                        "(required for gC -> tCO2e)")

    # ---- S4 scale reconciliation (Eq.4-5): time-series commutator εA ----
    # Primary: aggregation-commutator residual in the time dimension
    # (fine daily integral vs aggregate-then-integrate). If a stock ledger is
    # also present, the cross-ledger scalar check is kept as a secondary view.
    if flux_df is not None:
        sa = time_series_scale_audit(flux_df)
        rep.scale_audit = sa
        if sa["status"] == "not_run":
            detail = sa.get("reason", "insufficient flux records")
            if stock_df is not None and "removal_tco2e" in stock_df.columns and area_ha:
                stock_rem = float(pd.to_numeric(
                    stock_df["removal_tco2e"], errors="coerce").sum())
                flux_rem = _flux_to_tco2e(flux_df, area_ha)
                rep.scale_residual_eA_tco2e = stock_rem - flux_rem
                rep.scale_residual_status = (
                    "balanced"
                    if abs(rep.scale_residual_eA_tco2e) <= 0.05 * max(stock_rem, 1e-6)
                    else "flagged")
                detail += f" | stock {stock_rem:,.1f} vs flux {flux_rem:,.1f} tCO2e"
            stages.append(StageStatus("4", "Scale reconciliation (Eq.4-5)",
                                      rep.scale_residual_status, detail))
        else:
            eps_tco2e = None
            if area_ha:
                eps_tco2e = (sa["eps_max_abs_gCm2"] * area_ha * 1e4
                             * C_TO_CO2 / 1e6)
            rep.scale_residual_eA_tco2e = eps_tco2e
            rep.scale_residual_status = sa["status"]
            detail = (f"max|εA| = {sa['eps_max_abs_gCm2']:.2f} gC/m² "
                      f"({sa['relative_max_pct']:.1f}% of total |flux|, "
                      f"tol {sa['tol_pct']:.0f}%)")
            if eps_tco2e is not None:
                detail += f" → {eps_tco2e:+,.1f} tCO2e"
            if stock_df is not None and "removal_tco2e" in stock_df.columns and area_ha:
                stock_rem = float(pd.to_numeric(
                    stock_df["removal_tco2e"], errors="coerce").sum())
                flux_rem = _flux_to_tco2e(flux_df, area_ha)
                cross = stock_rem - flux_rem
                cross_flag = ("ok" if abs(cross) <= 0.05 * max(stock_rem, 1e-6)
                              else "cross-ledger flag")
                detail += f" | stock vs flux: {cross:+,.1f} tCO2e ({cross_flag})"
            stages.append(StageStatus("4", "Scale reconciliation (Eq.4-5)",
                                      sa["status"], detail))
    else:
        stages.append(StageStatus("4", "Scale reconciliation (Eq.4-5)", "not_run",
                                  "no flux ledger"))

    # ---- S5 attribution & additionality (Eq.2-3) ----
    if intervention_df is not None and len(intervention_df):
        add_rows = []
        for _, r in intervention_df.iterrows():
            add = additionality_counterfactual(
                float(r["baseline_removal_tco2e"]),
                float(r["intervention_removal_tco2e"]),
                scenario=str(r.get("scenario", "intervention")),
                active_fraction=(None if "active_fraction" not in r
                                else r["active_fraction"]))
            add_rows.append({"scenario": add.scenario,
                             "extra_tco2e": add.extra_removal_tco2e,
                             "ratio": add.additionality_ratio})
        rep.additionality = {"rows": add_rows}
        stages.append(StageStatus("5", "Attribution & additionality (Eq.2-3)",
                                  "passed",
                                  f"{len(add_rows)} intervention(s) split"))
    else:
        stages.append(StageStatus("5", "Attribution & additionality", "not_run",
                                  "no intervention ledger"))

    if flux_df is not None and agent_col and agent_col in flux_df.columns:
        try:
            att = attribution_split(
                flux_df,
                target_col="NEE_daily_total",
                env_cols=[c for c in flux_df.columns
                          if c not in ("date", "NEE_daily_total",
                                       "GPP_daily_total", "ER_daily_total",
                                       agent_col)][:4],
                agent_col=agent_col,
                area_ha=area_ha,
            )
            rep.attribution = {"env_r2": att.env_r2,
                               "agent_r2_gain": att.agent_r2_gain,
                               "agent_identifiable": att.agent_identifiable,
                               "agent_col": agent_col}
        except Exception as e:  # noqa: BLE001 — attribution is best-effort
            stages.append(StageStatus("5b", "Attribution split (Eq.2)",
                                      "warning", f"could not split: {e}"))
    elif flux_df is not None and agent_col:
        gaps.append(f"agent state column {agent_col!r} not found in flux ledger "
                    f"(attribution split skipped)")

    # ---- S6 leakage audit (Eq.7 + 3-step) ----
    if flux_df is not None and "NEE_daily_total" in flux_df.columns:
        preds = [c for c in flux_df.columns if c != "date"
                 and c != "NEE_daily_total"]
        leaky_names = [c for c in preds
                       if any(k in c.lower() for k in
                              ("gpp", "er_", "_er", "ecosystem_resp",
                               "nee_balance", "carbon_balance",
                               "cumulative_balance", "npp_balance",
                               "lateral_flux"))]
        if len(preds) >= 1:
            leak_rep = audit_leakage(flux_df, "NEE_daily_total", preds)
            rep.leakage = leak_rep
            n_leaky = sum(1 for v in leak_rep.classified.values()
                          if v == "leaky")
            rep.leakage_ryg = "red" if n_leaky > 0 else "green"
            # third step: no-leak refit
            exo = [c for c in preds
                   if leak_rep.classified.get(c, "exogenous") != "leaky"]
            if len(exo) >= 1:
                try:
                    refit = refit_without_leakage(
                        flux_df, "NEE_daily_total", preds, exo_only=exo)
                    rep.leak_free_gain_pct = refit.apparent_gain_pct
                except Exception:  # noqa: BLE001
                    rep.leak_free_gain_pct = None
            stages.append(StageStatus(
                "6", "Leakage audit (Eq.7)", rep.leakage_ryg,
                f"{n_leaky} leaky predictor(s) flagged"))
        else:
            stages.append(StageStatus("6", "Leakage audit", "not_run",
                                      "no predictor columns in flux ledger"))
    else:
        stages.append(StageStatus("6", "Leakage audit", "not_run",
                                  "no flux ledger"))

    # ---- S7 assemble ----
    rep.emissions_tco2e = emissions
    rep.emissions_u95_tco2e = (emissions * u95_emissions
                               if emissions is not None else None)
    rep.uncertainty_budget = budget
    rep.stages = stages
    rep.data_gaps = gaps

    # ---- certificate ----
    # Missing activity ledger blocks the audit itself; a missing flux ledger
    # only skips the S4 cross-check. If S3 never ran (no observed removals),
    # no conservation verdict exists -> the certificate stays INCOMPLETE.
    critical_missing = [g for g in gaps if "activity ledger" in g]
    if rep.residual_eC_status == "over-claimed":
        rep.certificate_status = "FAIL — over-claim detected (claim > observation)"
    elif rep.leakage_ryg == "red":
        rep.certificate_status = "REVIEW — target leakage in flux model"
    elif rep.scale_residual_status == "flagged":
        rep.certificate_status = "REVIEW — scale reconciliation flagged"
    elif critical_missing or rep.residual_eC_status == "not_run":
        rep.certificate_status = "INCOMPLETE — core ledger(s) missing"
    else:
        rep.certificate_status = "PASS — ledger consistent within tolerance"
    return rep
