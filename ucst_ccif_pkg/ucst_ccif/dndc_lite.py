"""
DNDC-lite: rice CH4 management table (Tier-1 IPCC scaling-factor approach).

Implements the IPCC method (2006 GL Vol.4 Ch.5 Eq. 5.1; 2013 Wetlands
Supplement Ch.3; 2019 Refinement):

    CH4_season = sum_t( EF_water[t] ) * SFw * SFp * SFo

    EF_water  : baseline daily emission factor by water regime
                (kg CH4 ha-1 d-1), Tier-1 defaults below
    SFw       : water management before/at cultivation (pre-season flood)
    SFp       : cultivar factor (0.35 - 1.29; default 1.0)
    SFo       : organic amendment factor (default 1.0 = no amendment)

Baseline EFs (Asia, without organic amendments) [2006 GL Table 5.11;
2019 Refinement updates the numbers — re-verify before regulatory use]:
    continuously flooded                1.91
    intermittently flooded, single aeration   0.91
    intermittently flooded, multiple aeration 0.58
    rainfed, regular water              1.21
    rainfed, drought-prone              0.66
    deepwater                           1.45

This is a *management table + calculator*, NOT the full DNDC process model.
It gives GBA rice-paddy CH4 estimates for scoping and MRV Tier-1 reporting.
"""

from __future__ import annotations
from dataclasses import dataclass

# kg CH4 ha-1 d-1 (Tier-1 Asia defaults, no organic amendment)
RICE_WATER_REGIMES: dict[str, float] = {
    "continuously_flooded":            1.91,
    "intermittently_flooded_single":   0.91,
    "intermittently_flooded_multiple": 0.58,
    "rainfed_regular":                 1.21,
    "rainfed_drought_prone":           0.66,
    "deepwater":                       1.45,
}

# SFw: pre-season water management (before cultivation) — default 1.0
# (flooded <30 days before cultivation = 1.0)
PRE_SEASON_FLOOD_SF = {"none": 1.0, "flooded_lt_30d": 1.0, "flooded_gt_30d": 1.9}

# SFp: cultivar factor range (IPCC default 1.0)
CULTIVAR_FACTOR_RANGE = (0.35, 1.29)

# SFo: organic amendment factors (relative to 1.0 = no amendment)
# Values per 2006 GL Table 5.13 [待核证 before use]
ORGANIC_AMENDMENT_SF = {
    "none":                                  1.0,
    "straw_incorporated_gt_30d_before":      0.29,   # [待核证]
    "straw_incorporated_lt_30d_before":      1.0,    # [待核证]
    "farmyard_manure":                       1.0,    # [待核证]
    "composted_organic":                     0.68,   # [待核证]
}

GWP_CH4_AR6 = 27.0


@dataclass
class RiceCH4Estimate:
    water_regime: str
    days: int
    baseline_kgCH4_ha: float
    sfw: float
    sfp: float
    sfo: float
    adjusted_kgCH4_ha: float
    co2e_tCO2e_ha: float
    area_ha: float = 1.0

    @property
    def total_kgCH4(self) -> float:
        return self.adjusted_kgCH4_ha * self.area_ha

    @property
    def total_tCO2e(self) -> float:
        return self.co2e_tCO2e_ha * self.area_ha


def rice_ch4_season(
    water_regime: str,
    days: int,
    area_ha: float = 1.0,
    organic_amendment: str = "none",
    cultivar_factor: float = 1.0,
    pre_season_flood: str = "none",
    gwp_ch4: float = GWP_CH4_AR6,
) -> RiceCH4Estimate:
    """
    Compute one rice-growing-season CH4 emission (Tier-1).

    Parameters
    ----------
    water_regime   : key of RICE_WATER_REGIMES
    days           : length of the flooded season (d)
    area_ha        : paddy area
    organic_amendment : key of ORGANIC_AMENDMENT_SF
    cultivar_factor : SFp (default 1.0)
    pre_season_flood : key of PRE_SEASON_FLOOD_SF
    gwp_ch4        : GWP100 for CH4 (AR6 biogenic default 27.0)

    Returns
    -------
    RiceCH4Estimate
    """
    if water_regime not in RICE_WATER_REGIMES:
        raise KeyError(f"unknown water regime {water_regime!r}; choose from "
                       f"{sorted(RICE_WATER_REGIMES)}")
    if organic_amendment not in ORGANIC_AMENDMENT_SF:
        raise KeyError(f"unknown amendment {organic_amendment!r}; choose from "
                       f"{sorted(ORGANIC_AMENDMENT_SF)}")
    if pre_season_flood not in PRE_SEASON_FLOOD_SF:
        raise KeyError(f"unknown pre-season flood {pre_season_flood!r}; choose "
                       f"from {sorted(PRE_SEASON_FLOOD_SF)}")
    if not (CULTIVAR_FACTOR_RANGE[0] <= cultivar_factor <= CULTIVAR_FACTOR_RANGE[1]):
        raise ValueError(f"cultivar_factor {cultivar_factor} outside IPCC range "
                         f"{CULTIVAR_FACTOR_RANGE}")

    ef = RICE_WATER_REGIMES[water_regime]
    sfw = PRE_SEASON_FLOOD_SF[pre_season_flood]
    sfp = float(cultivar_factor)
    sfo = ORGANIC_AMENDMENT_SF[organic_amendment]

    baseline = ef * days
    adjusted = baseline * sfw * sfp * sfo
    return RiceCH4Estimate(
        water_regime=water_regime, days=days,
        baseline_kgCH4_ha=baseline, sfw=sfw, sfp=sfp, sfo=sfo,
        adjusted_kgCH4_ha=adjusted,
        co2e_tCO2e_ha=adjusted * gwp_ch4 / 1000.0,
        area_ha=area_ha,
    )
