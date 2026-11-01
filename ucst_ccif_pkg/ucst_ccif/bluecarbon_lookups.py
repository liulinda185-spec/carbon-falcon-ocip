"""
InVEST-style blue-carbon lookup tables + calculators (no InVEST runtime needed).

Ecosystems: mangrove, saltmarsh, seagrass.
Stocks in Mg C/ha (aboveground + belowground + soil to 1 m).
Sequestration = sediment accretion rates in g C m-2 yr-1.

Documented sources (all literature defaults — calibrate for GBA sites):
    - Burial / accretion rates : McLeod et al. 2011, Front Ecol Environ 9:552-560
                                 (mangrove ~226, saltmarsh ~218, seagrass ~138 g C m-2 yr-1)
    - Mangrove biomass C      : Donato et al. 2011, Nat Geosci 4:293-297 (Indo-Pacific)
    - Saltmarsh soil C        : Chmura et al. 2003, Glob Biogeochem Cycles 17:1095
    - Seagrass C              : Fourqurean et al. 2012, Nat Geosci 5:505-509
    - Coastal CH4 (CO2e)      : IPCC 2013 Wetlands Supplement Ch.4 [待核证 values]

All values are DEFAULT lookups for MVP scoping; site measurement always wins.
"""

from __future__ import annotations
from dataclasses import dataclass

# GWP for CO2e conversion (IPCC AR6, biogenic CH4, 100-yr)
GWP_CH4_AR6 = 27.0

# --------------------------------------------------------------------------
# C stocks by ecosystem x region (Mg C/ha, top 1 m soil unless noted)
# --------------------------------------------------------------------------
STOCK_TABLES: dict[str, dict[str, dict[str, float]]] = {
    "mangrove": {
        "tropical":   {"agb": 160.0, "bgb": 90.0,  "soil_1m": 620.0},  # Donato 2011 / [待核证 site]
        "subtropical": {"agb": 90.0,  "bgb": 60.0,  "soil_1m": 500.0},  # GBA default [待核证]
        "temperate":  {"agb": 40.0,  "bgb": 30.0,  "soil_1m": 300.0},
    },
    "saltmarsh": {
        "tropical":   {"agb": 10.0,  "bgb": 40.0,  "soil_1m": 250.0},
        "subtropical": {"agb": 10.0,  "bgb": 45.0,  "soil_1m": 255.0},  # Chmura 2003 median ~255
        "temperate":  {"agb": 8.0,   "bgb": 35.0,  "soil_1m": 260.0},
    },
    "seagrass": {
        "tropical":   {"agb": 2.5,   "bgb": 3.0,   "soil_1m": 420.0},  # Fourqurean 2012 soil
        "subtropical": {"agb": 2.5,   "bgb": 3.0,   "soil_1m": 300.0},
        "temperate":  {"agb": 2.0,   "bgb": 3.0,   "soil_1m": 150.0},
    },
}

# Sequestration / sediment accretion (g C m-2 yr-1)
SEQUESTRATION_G_C_M2_YR: dict[str, dict[str, float]] = {
    "mangrove":  {"tropical": 226.0, "subtropical": 210.0, "temperate": 150.0},
    "saltmarsh": {"tropical": 218.0, "subtropical": 215.0, "temperate": 210.0},
    "seagrass":  {"tropical": 138.0, "subtropical": 120.0, "temperate": 100.0},
}

# CH4 emission (g CH4 m-2 yr-1) — IPCC 2013 Wetlands Supplement defaults [待核证]
CH4_G_M2_YR: dict[str, float] = {
    "mangrove":  0.29,   # low (aerobic root zone oxidation)
    "saltmarsh": 0.90,   # variable, higher in brackish/oligohaline [待核证]
    "seagrass":  0.01,   # near-zero, typically net sink of CH4 [待核证]
}


@dataclass
class BlueCarbonEstimate:
    ecosystem: str
    region: str
    stock_MgC_ha: float
    agb_MgC_ha: float
    bgb_MgC_ha: float
    soil_MgC_ha: float
    sequestration_gC_m2_yr: float
    ch4_gCH4_m2_yr: float
    ch4_co2e_gCO2e_m2_yr: float
    # per-ha yearly carbon gain from burial (Mg C ha-1 yr-1)
    burial_MgC_ha_yr: float


def blue_carbon_estimate(ecosystem: str, region: str = "subtropical",
                         area_ha: float | None = None) -> BlueCarbonEstimate:
    """
    Look up blue-carbon stocks and annual sequestration for one ecosystem.

    area_ha: optional project area; if given, returns totals in the estimate
    fields scaled to area (see .annual_burial_MgC and .total_stock_MgC).
    """
    eco = ecosystem.lower()
    reg = region.lower()
    if eco not in STOCK_TABLES:
        raise KeyError(f"unknown ecosystem {ecosystem!r}; choose from "
                       f"{sorted(STOCK_TABLES)}")
    if reg not in STOCK_TABLES[eco]:
        raise KeyError(f"unknown region {region!r}; choose from "
                       f"{sorted(STOCK_TABLES[eco])}")

    s = STOCK_TABLES[eco][reg]
    seq = SEQUESTRATION_G_C_M2_YR[eco][reg]
    ch4 = CH4_G_M2_YR[eco]
    stock = s["agb"] + s["bgb"] + s["soil_1m"]
    burial_MgC_ha_yr = seq * 10.0 / 1e6 * 1e4  # g/m2 -> Mg/ha: /1e6 *1e4

    est = BlueCarbonEstimate(
        ecosystem=eco, region=reg,
        stock_MgC_ha=stock,
        agb_MgC_ha=s["agb"], bgb_MgC_ha=s["bgb"], soil_MgC_ha=s["soil_1m"],
        sequestration_gC_m2_yr=seq,
        ch4_gCH4_m2_yr=ch4,
        ch4_co2e_gCO2e_m2_yr=ch4 * GWP_CH4_AR6,
        burial_MgC_ha_yr=burial_MgC_ha_yr,
    )
    if area_ha is not None:
        est.total_stock_MgC = est.stock_MgC_ha * area_ha          # noqa
        est.annual_burial_MgC = est.burial_MgC_ha_yr * area_ha    # noqa
        est.annual_ch4_co2e_tCO2e = est.ch4_co2e_gCO2e_m2_yr * area_ha * 1e4 / 1e6  # noqa
    return est


def list_ecosystems() -> list[str]:
    return sorted(STOCK_TABLES)


def list_regions() -> list[str]:
    return sorted({r for t in STOCK_TABLES.values() for r in t})
