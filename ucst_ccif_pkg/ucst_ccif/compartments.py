"""
Core carbon continuum model: 7 active compartments + coastal burial sink.

Compartment structure (RothC-inspired, extended to land-ocean continuum):

    Atmosphere
        ↑ GPP (observed/modelled)
    [V_leaf, V_wood, V_root]        Vegetation biomass
        ↓ litterfall
    [L_met, L_struct]               Litter pools
        ↓ decomposition
    [S_active, S_slow, S_passive]    Soil organic matter
        ↓ erosion                       ↓ heterotrophic respiration (CO2)
    [R_DOC, R_POC, R_DIC]           River / inland water
        ↓ evasion to atm               ↓ export to coast
    [O_coastal]                     Coastal marine pool
        ↓ burial
    [O_burial]                      Long-term geological sink (accumulator)

The conservation residual eps_C = dTotalStock/dt - (inputs - outputs) is
computed at every timestep and surfaced as a diagnostic. Non-zero eps_C flags
unresolved processes, measurement error, or boundary mis-specification — this
is the core UCST-CCIF audit feature (Eq. 1 in the manuscript).
"""

from dataclasses import dataclass, field
import numpy as np
from .parameters import ParameterSet


# Ordering of state vector
STATE_KEYS = [
    "V_leaf", "V_wood", "V_root",
    "L_met", "L_struct",
    "S_active", "S_slow", "S_passive",
    "R_DOC", "R_POC", "R_DIC",
    "O_coastal",
]
# O_burial is a cumulative accumulator, not a dynamic pool.

N_STATE = len(STATE_KEYS)


@dataclass
class CompartmentState:
    """Time-series state of all compartments."""
    t: np.ndarray                       # (T,) days
    stocks: dict[str, np.ndarray] = field(default_factory=dict)
    # Flux diagnostics
    gpp: np.ndarray = None              # gross primary production (gC m^-2 d^-1)
    npp: np.ndarray = None
    rh: np.ndarray = None               # heterotrophic respiration
    ra: np.ndarray = None               # autotrophic respiration
    river_evasion: np.ndarray = None
    coastal_burial: np.ndarray = None
    nee: np.ndarray = None              # net ecosystem exchange (atmospheric)
    eps_C: np.ndarray = None            # conservation residual
    total_stock: np.ndarray = None
    coastal_burial_cum: float = 0.0


def q10_response(T_air: np.ndarray, q10: float, t_ref: float) -> np.ndarray:
    """Temperature multiplier for respiratory flux."""
    return q10 ** ((T_air - t_ref) / 10.0)


def moisture_modifier(swc: np.ndarray, opt: float) -> np.ndarray:
    """Reduce respiration when soil is too dry or too wet."""
    # Symmetric penalty around optimum: min(1, swc/opt, opt/swc clipped)
    dry_pen = np.clip(swc / opt, 0.0, 1.0)
    wet_pen = np.clip((1.0 - swc) / (1.0 - opt), 0.0, 1.0)
    return np.minimum(dry_pen, wet_pen)


class CarbonContinuumModel:
    """
    Daily-timestep land-ocean carbon continuum model.

    Usage:
        model = CarbonContinuumModel(params)
        state = model.run(gpp_forced, T_air, swc, rain)
    """

    def __init__(self, params: ParameterSet):
        self.p = params

    def initial_state(self) -> np.ndarray:
        p = self.p
        return np.array([
            p.init_V_leaf, p.init_V_wood, p.init_V_root,
            p.init_L_met, p.init_L_struct,
            p.init_S_active, p.init_S_slow, p.init_S_passive,
            p.init_R_DOC, p.init_R_POC, p.init_R_DIC,
            p.init_O_coastal,
        ])

    def step(self, x: np.ndarray, gpp: float, T_air: float,
             swc: float, rain: float) -> tuple[np.ndarray, dict]:
        """
        Advance one day.

        Parameters
        ----------
        x : (N_STATE,) current stocks [gC m^-2]
        gpp : daily GPP [gC m^-2 d^-1] (observed or from empirical model)
        T_air : air temperature [deg C]
        swc : soil water content [fraction 0-1]
        rain : daily precipitation [mm]

        Returns
        -------
        x_new : updated stocks
        diag  : dict of diagnosed fluxes
        """
        p = self.p
        (V_leaf, V_wood, V_root,
         L_met, L_struct,
         S_active, S_slow, S_passive,
         R_DOC, R_POC, R_DIC,
         O_coastal) = x

        # --- Environmental modifiers ---
        fT = q10_response(np.array([T_air]), p.q10, p.t_ref)[0]
        fW = moisture_modifier(np.array([swc]), p.moisture_opt)[0]

        # --- Vegetation: NPP partitioning ---
        npp = gpp * p.gpp_to_npp
        ra = gpp - npp  # autotrophic respiration (to atmosphere)

        dV_leaf = p.frac_leaf * npp - p.leaf_turnover * V_leaf
        dV_wood = p.frac_wood * npp - p.wood_turnover * V_wood
        dV_root = p.frac_root * npp - p.root_turnover * V_root

        # --- Litterfall into litter pools ---
        litter_leaf = p.leaf_turnover * V_leaf
        litter_root = p.root_turnover * V_root
        litter_wood = p.wood_turnover * V_wood
        litter_total = litter_leaf + litter_root + litter_wood

        to_met = p.metabolic_frac * litter_total
        to_struct = p.structural_frac * litter_total

        # --- Litter decomposition to soil pools ---
        # Metabolic litter decomposes fast -> active pool + Rh
        L_met_decay = p.active_turnover * L_met * fT * fW
        L_struct_decay = p.slow_turnover * L_struct * fT * fW

        dL_met = to_met - L_met_decay
        dL_struct = to_struct - L_struct_decay

        # --- Soil pools: turnover + Rh + inter-pool transfer (RothC-style) ---
        # When a pool decomposes, rh_from_* fraction leaves as CO2;
        # the rest is transferred to the next slower pool.
        dec_active = p.active_turnover * S_active * fT * fW
        dec_slow = p.slow_turnover * S_slow * fT * fW
        dec_passive = p.passive_turnover * S_passive * fT * fW

        Rh_active = dec_active * p.rh_from_active
        Rh_slow = dec_slow * p.rh_from_slow
        Rh_passive = dec_passive * p.rh_from_passive
        rh_total = Rh_active + Rh_slow + Rh_passive

        # Decomposition products (non-Rh) cascade forward: active->slow->passive
        transfer_active = dec_active * (1.0 - p.rh_from_active)
        transfer_slow = dec_slow * (1.0 - p.rh_from_slow)
        transfer_passive = dec_passive * (1.0 - p.rh_from_passive)

        # Litter decomposition feeds soil pools
        dS_active = (L_met_decay * 0.6 + L_struct_decay * 0.3
                     - dec_active)
        dS_slow = (L_struct_decay * 0.5 + transfer_active
                   - dec_slow)
        dS_passive = (L_met_decay * 0.1 + L_struct_decay * 0.1
                      + transfer_slow - dec_passive)

        # --- Erosion to river ---
        eroded = p.erosion_rate * (S_active + S_slow) * (1.0 + rain / 10.0)
        eroded = max(eroded, 0.0)
        to_DOC = eroded * p.doc_fraction
        to_POC = eroded * p.poc_fraction

        # --- River processing ---
        river_evasion = p.river_evasion_rate * R_DIC * fT
        river_export_DOC = p.export_to_coast * R_DOC
        river_export_POC = p.export_to_coast * R_POC
        river_export_DIC = p.export_to_coast * R_DIC * 0.3  # some DIC exported

        dR_DOC = to_DOC - river_export_DOC - 0.01 * R_DOC  # small mineralization
        dR_POC = to_POC - river_export_POC - 0.005 * R_POC
        dR_DIC = (0.01 * R_DOC + 0.005 * R_POC   # mineralization to DIC
                  - river_evasion - river_export_DIC)

        # --- Coastal ---
        coastal_in = river_export_DOC + river_export_POC + river_export_DIC
        coastal_burial = p.coastal_burial_rate * O_coastal * fW
        coastal_outgas = 0.01 * O_coastal * fT  # some outgassing
        dO_coastal = coastal_in - coastal_burial - coastal_outgas

        # --- Assemble ---
        dx = np.array([
            dV_leaf, dV_wood, dV_root,
            dL_met, dL_struct,
            dS_active, dS_slow, dS_passive,
            dR_DOC, dR_POC, dR_DIC,
            dO_coastal,
        ])
        x_new = np.maximum(0.0, x + dx)

        # --- Conservation residual (Eq. 1 in manuscript) ---
        # eps_C = dTotalStock/dt - (external_in - external_out)
        # Note: coastal_burial IS an external output from the active surface
        # system (it enters long-term geological storage outside the L2/L3 boundary).
        d_total = x_new.sum() - x.sum()
        external_in = gpp
        external_out = (ra + rh_total + river_evasion
                        + coastal_outgas + coastal_burial)
        eps_C = d_total - (external_in - external_out)

        # --- Net ecosystem exchange (atmospheric CO2 flux) ---
        # NEE = Ra + Rh + river_evasion + coastal_outgas - GPP
        nee = ra + rh_total + river_evasion + coastal_outgas - gpp

        diag = dict(
            gpp=gpp, npp=npp, ra=ra, rh=rh_total,
            river_evasion=river_evasion,
            coastal_burial=coastal_burial,
            nee=nee, eps_C=eps_C,
        )
        return x_new, diag

    def run(self, gpp_series: np.ndarray, T_air: np.ndarray,
            swc: np.ndarray, rain: np.ndarray,
            x0: np.ndarray | None = None) -> CompartmentState:
        """Run the model forward over a time series."""
        T = len(gpp_series)
        if x0 is None:
            x0 = self.initial_state()

        stocks = {k: np.zeros(T) for k in STATE_KEYS}
        diags = {k: np.zeros(T) for k in
                 ["gpp", "npp", "ra", "rh", "river_evasion",
                  "coastal_burial", "nee", "eps_C"]}

        x = x0.copy()
        coastal_burial_cum = 0.0
        for k in range(T):
            x, d = self.step(x, gpp_series[k], T_air[k], swc[k], rain[k])
            for i, key in enumerate(STATE_KEYS):
                stocks[key][k] = x[i]
            for key in diags:
                diags[key][k] = d[key]
            coastal_burial_cum += d["coastal_burial"]

        t = np.arange(T, dtype=float)
        total_stock = np.sum([stocks[k] for k in STATE_KEYS], axis=0)

        return CompartmentState(
            t=t, stocks=stocks,
            gpp=diags["gpp"], npp=diags["npp"], ra=diags["ra"], rh=diags["rh"],
            river_evasion=diags["river_evasion"],
            coastal_burial=diags["coastal_burial"],
            nee=diags["nee"], eps_C=diags["eps_C"],
            total_stock=total_stock,
            coastal_burial_cum=coastal_burial_cum,
        )
