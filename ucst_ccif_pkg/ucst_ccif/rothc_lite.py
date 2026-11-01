"""
RothC-lite: a 4-pool Rothamsted Carbon Model kernel (Python, monthly timestep).

Pools (classic RothC, Coleman & Jenkinson 2014):
    DPM  Decomposable Plant Material   (k = 10.0 yr^-1)
    RPM  Resistant Plant Material      (k = 0.3  yr^-1)
    BIO  Microbial Biomass             (k = 0.66 yr^-1)
    HUM  Humified Organic Matter       (k = 0.02 yr^-1)
    IOM  Inert Organic Matter          (no decomposition)

Rate-modifying factors (RothC manual):
    a(T) = 47.91 / (1 + exp(106.06 / (T + 18.27)))          temperature
    b     = 1 - 1.858 * SMD/TSMD  (SMD<TSMD), else 0.2      moisture
    c     = 1.0 with vegetation cover, 0.6 bare soil         soil cover

Clay modifier for the BIO/HUM split:
    x = 1.67 * (1.85 + 1.60 * exp(-0.0786 * %clay))

Decomposition products of a pool decay of magnitude D:
    CO2  = D * (1 - 0.46)                          (0.54 respired)
    BIO  = D * 0.46 * x / (1 + x)                  (from DPM/RPM and BIO/HUM decay)
    HUM  = D * 0.46 * 1  / (1 + x)
    (for BIO and HUM decay the 0.46 goes to BIO+HUM; CO2 fraction 0.54)

Units: stocks and inputs in tC/ha, monthly rates. CO2 output in tC/ha/month.
Mass is conserved by construction: C_inputs = dStock + respired_CO2 (checked in tests).

"Date-stamped inputs" contract: callers pass either parallel arrays or a
pandas DataFrame with columns: date (or month/year), c_inputs (tC/ha/mo),
T (monthly mean degC), smd (soil moisture deficit mm), tsd (total SMD mm),
cover (1.0 or 0.6), optionally clay_pct for the split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

POOL_NAMES = ["DPM", "RPM", "BIO", "HUM"]
DEFAULT_RATES_YR = {"DPM": 10.0, "RPM": 0.3, "BIO": 0.66, "HUM": 0.02}

# Default DPM:RPM split of plant C inputs (RothC manual):
#   crops / improved grassland ~1.44 ; trees (broadleaf) ~0.25-0.67
DPM_RPM_SPLITS = {
    "crop":        1.44,
    "grass":       1.44,
    "broadleaf":   0.67,
    "conifer":     0.25,
    "mangrove":    0.67,   # woody, recalcitrant litter -> more RPM (default; calibrate)
    "saltmarsh":   1.10,   # herbaceous -> mostly DPM (default; calibrate)
}


def temperature_factor(T: float | np.ndarray) -> float | np.ndarray:
    """RothC temperature modifier a(T) (monthly mean degC)."""
    return 47.91 / (1.0 + np.exp(106.06 / (np.asarray(T, dtype=float) + 18.27)))


def moisture_factor(smd: float | np.ndarray, tsd: float | np.ndarray) -> float | np.ndarray:
    """RothC moisture modifier b from soil moisture deficit (mm)."""
    smd = np.asarray(smd, dtype=float)
    tsd = np.asarray(tsd, dtype=float)
    # RothC: b = 1 - 1.858*(SMD/TSMD) while SMD < TSMD, else 0.2
    b = np.where(smd < tsd, 1.0 - 1.858 * smd / np.maximum(tsd, 1e-9), 0.2)
    return np.clip(b, 0.0, 1.0)


def clay_split_factor(clay_pct: float) -> float:
    """RothC x factor controlling BIO:HUM split (clay_pct 0-100)."""
    return 1.67 * (1.85 + 1.60 * np.exp(-0.0786 * clay_pct))


@dataclass
class RothCResult:
    """Monthly pool stocks (tC/ha) and fluxes."""
    dates: np.ndarray | None
    stocks: dict[str, np.ndarray]      # DPM, RPM, BIO, HUM (IOM separate/constant)
    iom: float
    co2_flux: np.ndarray               # tC/ha/month respired
    c_inputs: np.ndarray               # tC/ha/month
    total_soc: np.ndarray              # DPM+RPM+BIO+HUM+IOM
    # mass-balance residual per step: inputs - (dStock + CO2)
    residual: np.ndarray


def run_rothc(
    c_inputs: np.ndarray,
    T: np.ndarray,
    smd: np.ndarray,
    tsd: np.ndarray,
    cover: np.ndarray | float = 1.0,
    clay_pct: float = 20.0,
    iom: float = 2.0,
    init: dict[str, float] | None = None,
    dpm_rpm: float | str = "crop",
    dates: np.ndarray | None = None,
) -> RothCResult:
    """
    Run RothC-lite over a monthly series.

    Parameters
    ----------
    c_inputs : monthly plant C inputs, tC/ha
    T        : monthly mean air temperature, degC
    smd      : soil moisture deficit, mm
    tsd      : total soil moisture deficit at field capacity, mm
    cover    : 1.0 vegetated / 0.6 bare (scalar or per-month)
    clay_pct : soil clay content % (drives BIO:HUM split)
    iom      : inert organic matter stock, tC/ha (constant)
    init     : initial DPM/RPM/BIO/HUM stocks (default 0)
    dpm_rpm  : split key or direct ratio
    dates    : optional date array for the record

    Returns
    -------
    RothCResult
    """
    n = len(c_inputs)
    c_in = np.asarray(c_inputs, dtype=float).reshape(n)
    T = np.asarray(T, dtype=float).reshape(n)
    smd = np.asarray(smd, dtype=float).reshape(n)
    tsd = np.asarray(tsd, dtype=float).reshape(n)
    cover = np.broadcast_to(np.asarray(cover, dtype=float).reshape(-1)[:1] if np.ndim(cover) == 0 else np.asarray(cover, dtype=float), (n,))

    if isinstance(dpm_rpm, str):
        ratio = DPM_RPM_SPLITS.get(dpm_rpm, 1.44)
    else:
        ratio = float(dpm_rpm)

    rates = {k: v / 12.0 for k, v in DEFAULT_RATES_YR.items()}   # per month
    x = clay_split_factor(clay_pct)
    bio_frac = 0.46 * x / (1.0 + x)
    hum_frac = 0.46 * 1.0 / (1.0 + x)

    init = init or {}
    stocks = {k: float(init.get(k, 0.0)) for k in POOL_NAMES}

    series = {k: np.zeros(n) for k in POOL_NAMES}
    co2 = np.zeros(n)
    resid = np.zeros(n)

    a = temperature_factor(T)
    b = moisture_factor(smd, tsd)
    c = cover

    for t in range(n):
        mod = a[t] * b[t] * c[t]
        # plant input split
        dpm_in = c_in[t] * ratio / (1.0 + ratio)
        rpm_in = c_in[t] * 1.0 / (1.0 + ratio)

        before = sum(stocks.values())
        # --- decompose each pool ---
        co2_t = 0.0
        for pool in POOL_NAMES:
            # a pool cannot decompose more than it holds (clip keeps stocks >= 0
            # and preserves exact mass balance: removed C == CO2 + BIO/HUM transfer)
            decay = min(stocks[pool] * rates[pool] * mod, stocks[pool])
            co2_t += decay * (1.0 - 0.46)
            # BIO+HUM receive the 0.46 fraction (split via x)
            stocks["BIO"] += decay * bio_frac
            stocks["HUM"] += decay * hum_frac
            stocks[pool] -= decay
        # add fresh inputs
        stocks["DPM"] += dpm_in
        stocks["RPM"] += rpm_in

        for k in POOL_NAMES:
            series[k][t] = stocks[k]
        co2[t] = co2_t
        after = sum(stocks.values()) + co2_t + iom
        resid[t] = (before + c_in[t]) - after

    total_soc = sum(series[k] for k in POOL_NAMES) + iom
    return RothCResult(
        dates=dates, stocks=series, iom=float(iom),
        co2_flux=co2, c_inputs=c_in,
        total_soc=total_soc, residual=resid,
    )


def run_rothc_dataframe(df: pd.DataFrame, **kwargs) -> RothCResult:
    """
    Run RothC-lite from a date-stamped DataFrame.

    Required columns: c_inputs, T, smd, tsd  (optional: cover, clay_pct).
    Any 'date'/'month'+'year' columns are used for the record.
    """
    cols = ["c_inputs", "T", "smd", "tsd"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    dates = None
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"]).to_numpy()
    elif "month" in df.columns and "year" in df.columns:
        dates = pd.to_datetime(
            dict(year=df["year"], month=df["month"], day=1)).to_numpy()

    cover = df["cover"].to_numpy() if "cover" in df.columns else 1.0
    clay = df["clay_pct"].iloc[0] if "clay_pct" in df.columns else 20.0
    return run_rothc(
        df["c_inputs"].to_numpy(), df["T"].to_numpy(),
        df["smd"].to_numpy(), df["tsd"].to_numpy(),
        cover=cover, clay_pct=float(clay), dates=dates, **kwargs)
