"""
Nested M0-M3 carbon-flux model comparison (UCST-CCIF).

Ported from LiuYG_03_leakage_free_model_comparison.py.

M0: baseline (Fourier seasonal + exogenous meteorology + disturbance kernel)
M1: M0 + conservation-state term
M2: M1 + state-dependent agent feedback
M3: counterfactual human-agency scenario engine (post-calibration)

Each model must justify itself out-of-sample. Calibration fit alone is
NOT evidence for retaining added complexity.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.signal import detrend


def fourier_seasonal(doy: np.ndarray, params: np.ndarray) -> np.ndarray:
    """3rd-order Fourier seasonal term. params = [a0,a1,b1,a2,b2,a3,b3]."""
    a0, a1, b1, a2, b2, a3, b3 = params[:7]
    t = 2 * np.pi * doy / 365.25
    return (a0 + a1*np.sin(t) + b1*np.cos(t)
            + a2*np.sin(2*t) + b2*np.cos(2*t)
            + a3*np.sin(3*t) + b3*np.cos(3*t))


@dataclass
class ModelResult:
    name: str
    params: np.ndarray
    calib_rmse: float
    valid_rmse: float
    valid_r2: float
    valid_mae: float
    n_params: int
    valid_predictions: np.ndarray = None


class M0Baseline:
    """
    M0: compartmentalized baseline.
    Fourier seasonal + exogenous predictors + disturbance kernel.
    No conservation state, no agent feedback.
    """
    name = "M0"

    def __init__(self, exo_cols: list[str], disturbance_col: str = "disturbance"):
        self.exo_cols = exo_cols
        self.disturbance_col = disturbance_col
        self.n_exo = len(exo_cols)
        self.n_params = 7 + self.n_exo + 1  # Fourier + exo + disturbance

    def predict(self, params: np.ndarray, df: pd.DataFrame) -> np.ndarray:
        seasonal = fourier_seasonal(df["doy"].values, params)
        exo_sum = np.zeros(len(df))
        for i, col in enumerate(self.exo_cols):
            exo_sum += params[7 + i] * df[col].values
        c_dist = params[7 + self.n_exo]
        return seasonal + exo_sum + c_dist * df[self.disturbance_col].values

    def residuals(self, params: np.ndarray, df: pd.DataFrame, target: str) -> np.ndarray:
        return self.predict(params, df) - df[target].values


class M1Conservation(M0Baseline):
    """
    M1: M0 + conservation-state term (cumulative exogenous anomaly, detrended).
    Uses leakage-free exogenous conservation state only.
    """
    name = "M1"

    def __init__(self, exo_cols: list[str], disturbance_col: str = "disturbance"):
        super().__init__(exo_cols, disturbance_col)
        self.n_params = 7 + self.n_exo + 1 + 2  # + C_state, dC_state

    def predict(self, params: np.ndarray, df: pd.DataFrame) -> np.ndarray:
        base = super().predict(params[: 7 + self.n_exo + 1], df)
        c_C = params[7 + self.n_exo + 1]
        c_dC = params[7 + self.n_exo + 2]
        return base + c_C * df["C_state"].values + c_dC * df["dC_state"].values


def _sanitize_model_frame(df: pd.DataFrame, keep_cols: list[str],
                          min_rows: int = 30) -> tuple[pd.DataFrame, int]:
    """
    Coerce model columns to numeric and drop rows with missing/infinite values.

    Returns the cleaned frame and the number of rows dropped, with an explicit
    error (instead of an opaque scipy 'infs or NaNs' crash) when too little
    usable data remains.
    """
    df = df.copy()
    for c in keep_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    before = len(df)
    df = df.dropna(subset=keep_cols)
    dropped = before - len(df)
    if len(df) < min_rows:
        raise ValueError(
            f"after removing {dropped} rows with missing/infinite values in "
            f"{keep_cols}, only {len(df)} rows remain (need >= {min_rows}). "
            f"Pick columns without large gaps, or fill/clean the data first.")
    return df, dropped


def compute_conservation_state(df: pd.DataFrame, exo_cols: list[str]) -> pd.DataFrame:
    """
    Compute leakage-free conservation state from exogenous anomalies.
    This is the M1_exo construction: z-scored anomalies, cumulative, detrended.
    """
    df = df.copy()
    z_cols = []
    for col in exo_cols:
        seasonal = df.groupby("month")[col].transform("mean")
        anom = (df[col] - seasonal).fillna(0.0)
        std = anom.std()
        df[f"_{col}_z"] = anom / std if (std == std and std > 1e-12) else 0.0
        z_cols.append(f"_{col}_z")
    df["_env_anomaly"] = df[z_cols].mean(axis=1)
    cum = np.cumsum(df["_env_anomaly"].values)
    df["C_state"] = detrend(cum)
    df["dC_state"] = np.diff(df["C_state"], prepend=df["C_state"].iloc[0])
    return df


def fit_model(model, calib: pd.DataFrame, valid: pd.DataFrame,
              target: str, init: np.ndarray,
              bounds: tuple[np.ndarray, np.ndarray]) -> ModelResult:
    """Fit a model with scipy least_squares and report out-of-sample metrics."""
    fit = least_squares(model.residuals, init, args=(calib, target),
                        bounds=bounds, max_nfev=10000)
    params = fit.x
    calib_rmse = float(np.sqrt(np.mean(model.residuals(params, calib, target) ** 2)))

    v_pred = model.predict(params, valid)
    v_obs = valid[target].values
    valid_rmse = float(np.sqrt(np.mean((v_pred - v_obs) ** 2)))
    valid_mae = float(np.mean(np.abs(v_pred - v_obs)))
    ss_res = float(np.sum((v_obs - v_pred) ** 2))
    ss_tot = float(np.sum((v_obs - np.mean(v_obs)) ** 2))
    valid_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return ModelResult(
        name=model.name, params=params,
        calib_rmse=calib_rmse, valid_rmse=valid_rmse,
        valid_r2=valid_r2, valid_mae=valid_mae,
        n_params=len(init), valid_predictions=v_pred,
    )


def compare_m0_m1(df: pd.DataFrame, target: str,
                  exo_cols: list[str],
                  calib_end_year: int = 2020,
                  disturbance_col: str = "disturbance") -> dict[str, ModelResult]:
    """
    Run the full M0 vs M1_exo comparison.

    df must have columns: date, doy, month, year, target, exo_cols, disturbance_col.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["doy"] = df["date"].dt.dayofyear
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    needed = [target] + list(exo_cols) + [disturbance_col]
    df, _ = _sanitize_model_frame(df, needed)
    df = compute_conservation_state(df, exo_cols)

    calib = df[df["year"] <= calib_end_year].copy()
    valid = df[df["year"] > calib_end_year].copy()

    # M0 init/bounds
    n_exo = len(exo_cols)
    m0_init = [0, -0.8, -0.3, 0.2, 0.1, 0.05, 0.0]
    m0_init += [0.01] * n_exo + [0.1]
    m0_lo = [-3, -3, -3, -2, -2, -1, -1] + [-5]*n_exo + [-3]
    m0_hi = [3, 3, 3, 2, 2, 1, 1] + [5]*n_exo + [3]

    m0 = M0Baseline(exo_cols, disturbance_col)
    r0 = fit_model(m0, calib, valid, target,
                   np.array(m0_init), (np.array(m0_lo), np.array(m0_hi)))

    # M1 init/bounds (M0 params + 2 conservation terms)
    m1_init = list(r0.params) + [0.001, 0.1]
    m1_lo = list(m0_lo) + [-0.01, -5]
    m1_hi = list(m0_hi) + [0.01, 5]
    m1 = M1Conservation(exo_cols, disturbance_col)
    r1 = fit_model(m1, calib, valid, target,
                   np.array(m1_init), (np.array(m1_lo), np.array(m1_hi)))

    return {"M0": r0, "M1": r1}


class M2aAgent(M1Conservation):
    """
    M2a: M1 + exogenous agent-state feedback Omega(t).

    The agent state is an external management signal (e.g. intervention
    intensity, water management, species-mix change) built WITHOUT any
    GPP/ER terms — it stays leakage-free by construction. Added complexity
    is only justified if it survives the out-of-sample test vs M1.
    """
    name = "M2a"

    def __init__(self, exo_cols: list[str],
                 disturbance_col: str = "disturbance",
                 agent_col: str = "agent_state"):
        super().__init__(exo_cols, disturbance_col)
        self.agent_col = agent_col
        self.n_params = 7 + self.n_exo + 1 + 2 + 2  # + c_Omega, c_dOmega

    def predict(self, params: np.ndarray, df: pd.DataFrame) -> np.ndarray:
        base = super().predict(params[: 7 + self.n_exo + 1 + 2], df)
        c_om = params[7 + self.n_exo + 1 + 2]
        c_dom = params[7 + self.n_exo + 1 + 3]
        return (base + c_om * df[self.agent_col].values
                + c_dom * df["d" + self.agent_col].values)


def compute_agent_state(df: pd.DataFrame, agent_col: str) -> pd.DataFrame:
    """
    Build a leakage-free agent state (z-scored anomaly, cumulative, detrended)
    from an exogenous management signal, mirroring compute_conservation_state.
    """
    df = df.copy()
    seasonal = df.groupby("month")[agent_col].transform("mean")
    anom = (df[agent_col] - seasonal).fillna(0.0)
    std = anom.std()
    df[agent_col] = anom / std if (std == std and std > 1e-12) else 0.0
    cum = np.cumsum(df[agent_col].values)
    df[agent_col] = detrend(cum)
    df["d" + agent_col] = np.diff(df[agent_col], prepend=df[agent_col].iloc[0])
    return df


def compare_m0_m1_m2a(df: pd.DataFrame, target: str,
                      exo_cols: list[str], agent_col: str,
                      calib_end_year: int = 2020,
                      disturbance_col: str = "disturbance") -> dict[str, ModelResult]:
    """
    M0 vs M1_exo vs M2a on the same calibration/validation split.

    The M2a gain over M1 (agent R2 gain) answers Eq. 2: does an exogenous
    management state move the flux AFTER conservation is accounted for?
    """
    res = compare_m0_m1(df, target, exo_cols, calib_end_year, disturbance_col)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["doy"] = df["date"].dt.dayofyear
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    df, _ = _sanitize_model_frame(
        df, [target] + list(exo_cols) + [disturbance_col, agent_col])
    df = compute_conservation_state(df, exo_cols)
    df = compute_agent_state(df, agent_col)

    calib = df[df["year"] <= calib_end_year].copy()
    valid = df[df["year"] > calib_end_year].copy()
    n_exo = len(exo_cols)

    m0_lo = [-3, -3, -3, -2, -2, -1, -1] + [-5]*n_exo + [-3]
    m0_hi = [3, 3, 3, 2, 2, 1, 1] + [5]*n_exo + [3]
    m1_lo = m0_lo + [-0.01, -5]
    m1_hi = m0_hi + [0.01, 5]
    m2_lo = m1_lo + [-0.01, -5]
    m2_hi = m1_hi + [0.01, 5]

    m2_init = list(res["M1"].params) + [0.001, 0.1]
    m2 = M2aAgent(exo_cols, disturbance_col, agent_col)
    r2 = fit_model(m2, calib, valid, target,
                   np.array(m2_init),
                   (np.array(m2_lo, dtype=float), np.array(m2_hi, dtype=float)))
    res["M2a"] = r2
    return res


# --------------------------------------------------------------------------
# M3: counterfactual human-agency scenarios (Eq. 3, post-calibration)
# --------------------------------------------------------------------------
# Illustrative scenario parameters (Sapelo Island, manuscript Table 10).
# F_a = active trigger of human action; F_p = passive ecosystem response.
# Units: gC m-2 d-1 of NEE change per unit intervention. NOT forecasts —
# they are audit scenario defaults the user can override.
SCENARIO_PARAMS: dict[str, dict[str, float]] = {
    # e.g. military hard-engineered land use: net emission pressure
    "military":    {"F_a": +0.956, "F_p": +0.327},
    # restoration planting: active uptake + passive regrowth follows
    "restoration": {"F_a": -0.105, "F_p": -0.277},
    # DAC / engineered removal: purely exogenous, no passive term
    "dac":         {"F_a": -0.274, "F_p": 0.000},
}

# tCO2e per ha per year for 1 gC m-2 d-1 of sustained NEE change.
_GCM2D_TO_TCO2E_HA_YR = 365.0 * 1e4 * 44.0 / 12.0 / 1e6  # = 13.383


def m3_counterfactual(baseline_nee_gCm2_d: float,
                      scenario: str = "restoration",
                      area_ha: float | None = None,
                      F_a: float | None = None,
                      F_p: float | None = None) -> dict:
    """
    Counterfactual agency test (Eq. 3): split an intervention into active
    trigger (F_a) and passive response (F_p), and report the extra removal
    against the no-action baseline.

    Returns a dict with delta-NEE, extra removal (tCO2e), the active/passive
    decomposition and an additionality ratio. `F_a`/`F_p` override the
    illustrative defaults; `area_ha` switches output to total tCO2e/yr.
    """
    if scenario not in SCENARIO_PARAMS and (F_a is None or F_p is None):
        raise ValueError(
            f"unknown scenario {scenario!r}; known: {sorted(SCENARIO_PARAMS)} "
            f"or pass F_a/F_p explicitly")
    fa = float(F_a) if F_a is not None else SCENARIO_PARAMS[scenario]["F_a"]
    fp = float(F_p) if F_p is not None else SCENARIO_PARAMS[scenario]["F_p"]

    delta_nee = fa + fp                       # gC m-2 d-1 (negative = more uptake)
    per_ha = -delta_nee * _GCM2D_TO_TCO2E_HA_YR  # tCO2e/ha/yr extra removal
    total = per_ha * area_ha if area_ha else None
    denom = fa + fp
    active_share = fa / denom if denom != 0 else float("nan")

    out = {
        "scenario": scenario,
        "baseline_nee_gCm2_d": float(baseline_nee_gCm2_d),
        "delta_nee_gCm2_d": delta_nee,
        "F_a_active_trigger": fa,
        "F_p_passive_response": fp,
        "extra_removal_tco2e_ha_yr": per_ha,
        "active_share_of_change": active_share,
        "illustrative_note": "scenario defaults from Sapelo Table 10; "
                             "override F_a/F_p with site data",
    }
    if total is not None:
        out["extra_removal_tco2e_yr"] = total
    return out


def model_competition(
    df: pd.DataFrame,
    target: str,
    exo_cols: list[str],
    calib_end_year: int = 2020,
    agent_col: str | None = None,
    disturbance_col: str | None = None,
) -> dict:
    """
    Full M0 vs M1 vs (optional) M2a competition with validation frames.

    Reproduces manuscript §5 nested comparison on a user flux ledger:
      M0  : Eq.(8) Fourier seasonal + exogenous predictors + disturbance kernel
      M1  : Eq.(9) + leakage-free conservation state
      M2a : Eq.(2) + exogenous agent-state feedback (only if agent_col given)

    Returns {"results": {name: ModelResult}, "calib": df, "valid": df},
    with per-model out-of-sample predictions attached to `valid` for plotting.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["doy"] = df["date"].dt.dayofyear
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year

    if disturbance_col is None:
        disturbance_col = "disturbance"
        if disturbance_col not in df.columns:
            df[disturbance_col] = 0.0
    elif disturbance_col not in df.columns:
        raise ValueError(f"disturbance column {disturbance_col!r} not in data")

    keep = [target] + list(exo_cols) + [disturbance_col]
    if agent_col:
        if agent_col not in df.columns:
            raise ValueError(f"agent column {agent_col!r} not in data")
        keep.append(agent_col)
    df, _ = _sanitize_model_frame(df, keep)

    df = compute_conservation_state(df, exo_cols)
    if agent_col:
        df = compute_agent_state(df, agent_col)

    calib = df[df["year"] <= calib_end_year].copy()
    valid = df[df["year"] > calib_end_year].copy()
    if len(calib) < 30 or len(valid) < 10:
        raise ValueError(
            f"need >= 30 calibration and >= 10 validation days "
            f"(calib <= {calib_end_year}: {len(calib)} d, valid: {len(valid)} d)")

    if agent_col:
        results = compare_m0_m1_m2a(df, target, exo_cols, agent_col,
                                    calib_end_year, disturbance_col)
    else:
        results = compare_m0_m1(df, target, exo_cols,
                                calib_end_year, disturbance_col)

    valid_out = valid.copy()
    valid_out["observed"] = valid_out[target]
    for name, r in results.items():
        valid_out[f"pred_{name}"] = r.valid_predictions
    return {"results": results, "calib": calib, "valid": valid_out}
