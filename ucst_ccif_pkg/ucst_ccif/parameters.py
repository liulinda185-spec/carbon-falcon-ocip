"""
Literature-calibrated parameter ranges for the land-ocean carbon continuum.

All ranges are 95% uncertainty intervals drawn from:
    - Salt-marsh / Spartina alterniflora: Mcleod et al. 2011 (Front Ecol Environ);
      Hawman & Mishra 2026 (Sapelo Island MSH-GCEM dataset)
    - Q10 temperature response: IPCC AR6 WG1 Ch.5; Reichstein et al. 2005 GCB
    - Soil turnover: RothC (Coleman & Jenkinson 2014); CENTURY (Parton et al. 1987);
      Yasso07 (Liski et al. 2005)
    - Blue carbon burial: Chmura et al. 2003; McLeod et al. 2011
    - Riverine C evasion: Raymond et al. 2013 (Nature); Regnier et al. 2013

Units: rates are per-day unless noted; stocks are gC m^-2.
"""

from dataclasses import dataclass, field
import numpy as np


@dataclass
class ParameterSet:
    """A single draw of model parameters."""

    # --- Vegetation partitioning ---
    gpp_to_npp: float = 0.55          # NPP/GPP ratio (Ra ~ 45% of GPP)
    frac_leaf: float = 0.30          # NPP allocated to leaves
    frac_wood: float = 0.10           # NPP allocated to wood/stems
    frac_root: float = 0.60           # NPP allocated to roots (salt-marsh: root-heavy)

    # --- Litter turnover (per day) ---
    leaf_turnover: float = 1.0 / 365.0     # leaves senesce ~annually
    wood_turnover: float = 0.05 / 365.0     # wood slow
    root_turnover: float = 0.25 / 365.0     # roots turnover 0.25/yr

    # --- Litter decomposition partitioning ---
    metabolic_frac: float = 0.50     # fraction of litter going to metabolic pool
    structural_frac: float = 0.50    # rest goes to structural pool

    # --- Soil pool turnover rates (per day) ---
    # RothC: DPM ~0.65/yr, RPM ~0.11/yr, Bio ~0.015/yr, Hum ~0.004/yr, IOM inert
    active_turnover: float = 0.65 / 365.0      # ~0.5 yr residence
    slow_turnover: float = 0.04 / 365.0        # ~20 yr residence
    passive_turnover: float = 0.001 / 365.0    # ~270 yr residence

    # --- Heterotrophic respiration partition from each pool ---
    rh_from_active: float = 0.55     # fraction of active turnover lost as CO2
    rh_from_slow: float = 0.50
    rh_from_passive: float = 0.50

    # --- Temperature / moisture response ---
    q10: float = 1.8                  # temperature sensitivity of respiration
    t_ref: float = 15.0               # reference temperature (deg C)
    moisture_opt: float = 0.60       # optimal soil water content (fraction)

    # --- Erosion / lateral transport ---
    erosion_rate: float = 0.00002     # fraction of SOC eroded per day (small!)
    doc_fraction: float = 0.60       # eroded C as dissolved organic C
    poc_fraction: float = 0.40       # eroded C as particulate organic C
    river_evasion_rate: float = 0.04 # fraction of R_DIC evaded to atm per day
    export_to_coast: float = 0.012   # fraction of river C exported to coast per day
    # ~80-day residence time in the river network (Raymond et al. 2013)

    # --- Coastal / blue carbon ---
    coastal_burial_rate: float = 0.00055  # fraction of coastal pool buried per day
    # ~150-250 gC m^-2 yr^-1 burial = 0.0004-0.0007 d^-1 for a 500 gC m^-2 pool

    # --- Initial stocks (gC m^-2) ---
    init_V_leaf: float = 120.0
    init_V_wood: float = 40.0
    init_V_root: float = 300.0
    init_L_met: float = 80.0
    init_L_struct: float = 150.0
    init_S_active: float = 200.0
    init_S_slow: float = 2000.0
    init_S_passive: float = 3000.0
    init_R_DOC: float = 2.0
    init_R_POC: float = 1.0
    init_R_DIC: float = 5.0
    init_O_coastal: float = 500.0

    # --- Observation noise ---
    obs_sd: float = 0.3              # gC m^-2 d^-1, eddy-covariance NEE noise


# Literature 95% ranges for Monte Carlo sampling.
# Each entry: (low, high) for uniform sampling.
LITERATURE_RANGES: dict[str, tuple] = {
    "gpp_to_npp":        (0.45, 0.65),
    "frac_root":         (0.45, 0.75),
    "q10":               (1.4, 2.5),
    "active_turnover":   (0.4 / 365.0, 1.0 / 365.0),
    "slow_turnover":     (0.02 / 365.0, 0.08 / 365.0),
    "passive_turnover":  (0.0005 / 365.0, 0.002 / 365.0),
    "erosion_rate":      (0.00001, 0.00005),
    "river_evasion_rate":(0.02, 0.08),
    "coastal_burial_rate": (0.0003, 0.0008),
    "init_S_active":     (150.0, 300.0),
    "init_S_slow":       (1500.0, 3000.0),
    "init_S_passive":    (2000.0, 5000.0),
    "init_V_root":       (200.0, 500.0),
    "obs_sd":            (0.2, 0.5),
}


def draw_parameters(rng: np.random.Generator | None = None) -> ParameterSet:
    """Draw one parameter set by uniformly sampling literature ranges."""
    if rng is None:
        rng = np.random.default_rng()
    defaults = ParameterSet()
    overrides = {}
    for key, (lo, hi) in LITERATURE_RANGES.items():
        overrides[key] = rng.uniform(lo, hi)
    return ParameterSet(**{**defaults.__dict__, **overrides})
