"""
Attribution & conservation-reconciliation layer (Eq. 1-3 of the manuscript).

Answers the OCIP core question: *"a company claims X t emitted and Y t removed
(湿地 / 光伏 / 草坪) — does the ledger actually balance?"*

  1. `conservation_reconcile` — Eq. (1): reconcile claimed removals against
     independently observed removals. The residual e_C = observed − claimed
     flags over-claiming before any certificate is issued.
  2. `additionality_counterfactual` — Eq. (3): split an intervention into
     active trigger (F_a) and passive response (F_p); extra removal =
     intervention − baseline. This is the CCER / CRCF additionality gate.
  3. `attribution_split` — Eq. (2): intervention test. Holding environmental
     drivers fixed, does the agent state produce a reproducible flux change?

Units are kept in tCO2e for the enterprise ledger and gC m-2 d-1 for the
ecological ledger; every conversion uses C -> CO2 factor 44.0/12.0.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np
import pandas as pd

# C -> CO2 mass ratio (IPCC).
C_TO_CO2 = 44.0 / 12.0
# Default tolerance for "balanced" status, in % of the observed side.
DEFAULT_TOLERANCE_PCT = 5.0


# --------------------------------------------------------------------------
# 1. Conservation reconciliation  (Eq. 1 residual)
# --------------------------------------------------------------------------
@dataclass
class ReconciliationReport:
    """Outcome of the conservation reconciliation gate."""
    emissions_tco2e: float            # verified/claimed emissions
    claimed_removals_tco2e: float     # what the company claims it removed
    observed_removals_tco2e: float    # what independent observation supports
    net_claimed_tco2e: float          # emissions - claimed removals
    net_observed_tco2e: float         # emissions - observed removals
    residual_tco2e: float             # observed - claimed (positive = over-claim)
    tolerance_pct: float
    status: str                       # "balanced" | "over-claimed" | "conservative"

    def summary(self) -> str:
        return (
            f"=== Conservation reconciliation (Eq.1) ===\n"
            f"Emissions            : {self.emissions_tco2e:,.1f} tCO2e\n"
            f"Claimed removals     : {self.claimed_removals_tco2e:,.1f} tCO2e\n"
            f"Observed removals    : {self.observed_removals_tco2e:,.1f} tCO2e\n"
            f"Residual (obs-claim) : {self.residual_tco2e:+,.1f} tCO2e\n"
            f"Status               : {self.status}"
        )


def conservation_reconcile(
    emissions_tco2e: float,
    claimed_removals_tco2e: float,
    observed_removals_tco2e: float,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> ReconciliationReport:
    """
    Reconcile a claimed carbon ledger against observations.

    The residual is defined as *observed minus claimed*: a negative residual
    means the company claims more removal than any observable carbon pool or
    flux supports -> over-claiming. A positive residual means the claim is
    conservative (independent observation supports more removal than claimed).

    Tolerance is expressed as a percentage of max(observed, small floor).
    """
    claimed = float(claimed_removals_tco2e)
    observed = float(observed_removals_tco2e)
    emissions = float(emissions_tco2e)
    residual = observed - claimed
    floor = max(abs(observed), 1e-6)
    tol = tolerance_pct / 100.0 * floor
    if abs(residual) <= tol:
        status = "balanced"
    elif residual < -tol:
        status = "over-claimed"      # claim > observation
    else:
        status = "conservative"      # claim < observation
    return ReconciliationReport(
        emissions_tco2e=emissions,
        claimed_removals_tco2e=claimed,
        observed_removals_tco2e=observed,
        net_claimed_tco2e=emissions - claimed,
        net_observed_tco2e=emissions - observed,
        residual_tco2e=residual,
        tolerance_pct=tolerance_pct,
        status=status,
    )


# --------------------------------------------------------------------------
# 2. Additionality counterfactual  (Eq. 3: F_hybrid = F_a + F_p)
# --------------------------------------------------------------------------
@dataclass
class AdditionalityReport:
    """Active-passive decomposition of an intervention (Eq. 3)."""
    scenario: str
    baseline_removal_tco2e: float      # would have happened anyway (F_p, passive)
    intervention_removal_tco2e: float  # total removal with the intervention
    active_trigger_tco2e: float        # F_a (intentional human action)
    passive_response_tco2e: float      # F_p (secondary ecosystem evolution)
    extra_removal_tco2e: float         # intervention - baseline = additionality
    additionality_ratio: float         # extra / intervention

    def summary(self) -> str:
        return (
            f"=== Additionality counterfactual (Eq.3) — {self.scenario} ===\n"
            f"Baseline (no action)      : {self.baseline_removal_tco2e:,.2f} tCO2e\n"
            f"With intervention         : {self.intervention_removal_tco2e:,.2f} tCO2e\n"
            f"Active trigger F_a        : {self.active_trigger_tco2e:+,.2f} tCO2e\n"
            f"Passive response F_p      : {self.passive_response_tco2e:+,.2f} tCO2e\n"
            f"Extra (additionality)     : {self.extra_removal_tco2e:+,.2f} tCO2e\n"
            f"Additionality ratio       : {self.additionality_ratio:.1%}"
        )


def additionality_counterfactual(
    baseline_removal_tco2e: float,
    intervention_removal_tco2e: float,
    scenario: str = "intervention",
    active_fraction: float | None = None,
) -> AdditionalityReport:
    """
    Decompose an intervention into active trigger and passive response.

    Extra removal = intervention − baseline. If `active_fraction` is given,
    the active trigger is that fraction of the total change; otherwise the
    whole change is attributed to the active trigger and the passive
    response is the baseline itself (conservative default).
    """
    baseline = float(baseline_removal_tco2e)
    intervention = float(intervention_removal_tco2e)
    extra = intervention - baseline
    if active_fraction is None:
        active = extra
        passive = float(intervention) if intervention != baseline else 0.0
    else:
        active = extra * float(active_fraction)
        passive = extra - active
    ratio = extra / intervention if intervention != 0 else 0.0
    return AdditionalityReport(
        scenario=scenario,
        baseline_removal_tco2e=baseline,
        intervention_removal_tco2e=intervention,
        active_trigger_tco2e=active,
        passive_response_tco2e=passive,
        extra_removal_tco2e=extra,
        additionality_ratio=ratio,
    )


# --------------------------------------------------------------------------
# 3. Attribution split  (Eq. 2: intervention test)
# --------------------------------------------------------------------------
@dataclass
class AttributionReport:
    """Environment-driven vs agent-driven contribution to a flux."""
    env_r2: float                       # R2 of environmental predictors alone
    agent_r2_gain: float                # R2 gain when agent state is added
    agent_effect_tco2e: float | None    # annualised agent-driven flux, if area given
    agent_identifiable: bool            # |gain| above identifiability floor
    summary_text: str

    def summary(self) -> str:
        return self.summary_text


def attribution_split(
    df: pd.DataFrame,
    target_col: str,
    env_cols: Sequence[str],
    agent_col: str,
    area_ha: float | None = None,
    identifiability_floor: float = 0.005,
) -> AttributionReport:
    """
    Operational attribution test (Eq. 2).

    Fit: flux ~ environmental drivers (env-only), then add the agent state.
    If adding the agent state does not change the flux (R2 gain below the
    identifiability floor), the process is classified *environmental* for
    this model — no agency is claimed without a reproducible effect.
    """
    df = df.copy()
    y = np.asarray(df[target_col].values, dtype=float)
    env = np.column_stack([np.asarray(df[c].values, dtype=float) for c in env_cols])
    agent = np.asarray(df[agent_col].values, dtype=float)

    def _r2(X: np.ndarray) -> float:
        X = np.column_stack([X, np.ones(len(X))])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            return 0.0
        pred = X @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    env_r2 = _r2(env)
    both_r2 = _r2(np.column_stack([env, agent]))
    gain = both_r2 - env_r2
    identifiable = gain >= identifiability_floor

    agent_effect = None
    if area_ha is not None:
        # Annualised agent-driven flux in tCO2e (linear approx: gain * mean |y|).
        mean_abs = float(np.mean(np.abs(y)))
        agent_effect = gain * mean_abs * 365.0 * area_ha * 1e4 * C_TO_CO2 / 1e6

    lines = [
        f"=== Attribution split (Eq.2) — target {target_col} ===",
        f"Environmental R2           : {env_r2:.3f}",
        f"Agent-state R2 gain        : {gain:+.3f}",
        f"Agent identifiable (>=.005) : {identifiable}",
    ]
    if agent_effect is not None:
        lines.append(f"Agent-driven flux (est.)    : {agent_effect:+,.2f} tCO2e/yr")
    return AttributionReport(
        env_r2=env_r2,
        agent_r2_gain=gain,
        agent_effect_tco2e=agent_effect,
        agent_identifiable=identifiable,
        summary_text="\n".join(lines),
    )
