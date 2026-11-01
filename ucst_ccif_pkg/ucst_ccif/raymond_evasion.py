"""
Raymond-2013 inland-water CO2 evasion kernel.

Implements gas-transfer based evasion for streams/rivers and lakes:

    F_CO2 (gC m-2 d-1) = k_CO2 * Kh * (pCO2_water - pCO2_atm) * 1000 * 12

    k_CO2 = k600 * (Sc/600)^-0.5
    Sc    = 1911 - 118.11*T + 3.4527*T^2 - 0.04132*T^3   (Wanninkhof 1992)
    Kh    = Henry constant from Weiss (1974) solubility fit (mol L-1 atm-1)

k600 selection:
    - streams/rivers: k600 = 2841.4 * (v * S)^0.353   (Raymond et al. 2012,
      Limnol Oceanogr Fluids Environ 2:41-53 — as used in Raymond et al. 2013 Nature)
      v in m/s, S dimensionless slope.
    - lakes: wind-based / default k600 ~0.7 m d-1 (Cole & Caraco 1998; configurable)

Global context (Raymond et al. 2013, Nature 503:355-359): total inland-water
CO2 evasion ~2.1 Pg C yr-1 [streams+rivers ~1.78, lakes ~0.32, reservoirs
~0.13 — breakdown [待核证]]. Use for L3 budget framing only.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


def schmidt_co2(T: float | np.ndarray) -> float | np.ndarray:
    """Schmidt number of CO2 in water at temperature T (degC)."""
    T = np.asarray(T, dtype=float)
    return 1911.0 - 118.11 * T + 3.4527 * T**2 - 0.04132 * T**3


def henry_co2(T: float | np.ndarray) -> float | np.ndarray:
    """Henry constant Kh (mol L-1 atm-1) from Weiss (1974) fit; T degC."""
    Tk = np.asarray(T, dtype=float) + 273.15
    ln_kh = (-60.2409 + 93.4517 * (100.0 / Tk)
             + 23.3585 * np.log(Tk / 100.0))
    return np.exp(ln_kh)


def k600_streams(v: float | np.ndarray, slope: float | np.ndarray
                 ) -> float | np.ndarray:
    """Raymond et al. 2012 stream k600 (m d-1) from velocity (m/s) & slope."""
    return 2841.4 * (np.asarray(v, dtype=float) * np.asarray(slope, dtype=float)) ** 0.353


def k600_lakes(u10: float | np.ndarray = 3.0) -> float | np.ndarray:
    """Lake k600 (m d-1); default 0.7 m d-1, or wind-based scaling."""
    u = np.asarray(u10, dtype=float)
    return np.where(u <= 0.1, 0.7, 0.728 * np.sqrt(u) - 0.317 * u + 0.0372 * u**2)


@dataclass
class EvasionKernel:
    """Configurable CO2 evasion kernel for one water body."""
    water_type: str = "stream"      # 'stream' | 'lake'
    # stream params
    velocity: float | None = 0.5    # m/s
    slope: float | None = 0.001     # dimensionless
    # lake params
    u10: float | None = 3.0         # m/s wind at 10m
    k600_fixed: float | None = None # override k600 (m d-1)

    def k600(self) -> float:
        if self.k600_fixed is not None:
            return float(self.k600_fixed)
        if self.water_type == "lake":
            return float(k600_lakes(self.u10))
        return float(k600_streams(self.velocity, self.slope))

    def flux_gC_m2_d(self, pco2_water_uatm: float | np.ndarray,
                     T_degC: float | np.ndarray = 20.0,
                     pco2_atm_uatm: float = 420.0) -> float | np.ndarray:
        """CO2 flux (gC m-2 d-1); negative = net uptake, positive = evasion."""
        k600 = self.k600()
        k_co2 = k600 * (schmidt_co2(T_degC) / 600.0) ** -0.5
        kh = henry_co2(T_degC)
        dP = np.asarray(pco2_water_uatm, dtype=float) - pco2_atm_uatm
        # mol m-2 d-1 -> gC m-2 d-1
        return k_co2 * kh * (dP * 1e-6) * 1000.0 * 12.0

    def total_MgC_yr(self, pco2_water_uatm: float | np.ndarray,
                     area_km2: float,
                     T_degC: float | np.ndarray = 20.0,
                     pco2_atm_uatm: float = 420.0) -> float:
        """Annual total evasion (Mg C/yr) over a water surface (km2)."""
        gC_m2_d = self.flux_gC_m2_d(pco2_water_uatm, T_degC, pco2_atm_uatm)
        mean = float(np.mean(np.asarray(gC_m2_d, dtype=float)))
        return mean * area_km2 * 1e6 * 365.0 / 1e6   # gC/yr -> MgC/yr


# Global framing (Raymond et al. 2013 Nature) — breakdown values [待核证]
GLOBAL_EVASION_PG_C_YR = {
    "total_inland_water": 2.1,
    "streams_rivers": 1.78,
    "lakes": 0.32,
    "reservoirs": 0.13,
}
