"""
Official emission factors for China / GBA.

Sources:
- MEE Announcement 2024 No.33: 2022 provincial grid CO2 factors (published 2024-12-26)
- MEE "企业温室气体排放核算方法与报告指南 发电设施" Appendix A:
  fuel carbon content (CC, tC/TJ) and oxidation rate (OF)
- Guangdong EPD: provincial reporting factor (older vintage, kept for reference)
- IPCC 2006 Vol.2: default NCV and Scope 3 defaults

All factors are versioned with source year. Update when MEE publishes new vintages.
"""

from __future__ import annotations
from dataclasses import dataclass


# --- Grid emission factors (MEE 2022, published Dec 2024) ---
# Unit: kgCO2 per kWh purchased electricity
GRID_FACTORS_MEE_2022: dict[str, float] = {
    "national_avg":   0.5366,
    "south_region":   0.3869,   # Southern China regional grid
    "guangdong":      0.4403,   # Guangdong province (official MEE number)
    "guangxi":        0.4044,
    "hainan":         0.4184,
    "fujian":         0.4092,
}
GRID_SOURCE = "MEE Announcement 2024 No.33, 2022 power CO2 factors"

# Guangdong EPD's own reporting factor (different methodology, older vintage)
GUANGDONG_EPD_FACTOR = 0.6379  # kgCO2/kWh, from 6.379 tCO2/万kWh


# --- Stationary combustion factors (MEE power generation guideline App. A) ---
# EF_CO2 = CC (tC/TJ) * OF * 44/12
@dataclass(frozen=True)
class FuelFactor:
    name: str
    cc_tC_TJ: float       # carbon content
    oxidation: float     # oxidation rate
    ncv_GJ_per_unit: float  # net calorific value
    unit: str            # 'm3', 'L', 'kg', 't'
    note: str = ""

    @property
    def ef_kgCO2_GJ(self) -> float:
        """kgCO2 per GJ. (CC in tC/TJ -> EF in tCO2/TJ = kgCO2/GJ.)"""
        return self.cc_tC_TJ * self.oxidation * 44.0 / 12.0

    @property
    def ef_kgCO2_unit(self) -> float:
        """kg CO2 per activity unit (m3, L, kg)."""
        return self.ef_kgCO2_GJ * self.ncv_GJ_per_unit


FUELS: dict[str, FuelFactor] = {
    "natural_gas_m3": FuelFactor(
        name="Natural gas", cc_tC_TJ=15.32, oxidation=0.99,
        ncv_GJ_per_unit=0.03893, unit="m3",
        note="NCV 38.93 MJ/m3; MEE App.A",
    ),
    "diesel_L": FuelFactor(
        name="Diesel", cc_tC_TJ=20.2, oxidation=0.98,
        ncv_GJ_per_unit=0.0355, unit="L",  # 42.65 GJ/t * 0.832 kg/L
        note="NCV 42.65 GJ/t, density 0.832 kg/L",
    ),
    "petrol_L": FuelFactor(
        name="Petrol", cc_tC_TJ=18.9, oxidation=0.98,
        ncv_GJ_per_unit=0.0310, unit="L",  # 44.8 GJ/t * 0.703 kg/L
        note="NCV 44.8 GJ/t, density 0.703 kg/L",
    ),
    "coal_kg": FuelFactor(
        name="Raw coal", cc_tC_TJ=26.18, oxidation=0.94,
        ncv_GJ_per_unit=0.0209, unit="kg",  # 20.9 GJ/t
        note="Bituminous raw coal, MEE App.A",
    ),
}


# --- Scope 3 factors ---
# Cat 3: T&D losses on purchased electricity (China grid average ~5.5%)
TD_LOSS_RATE = 0.055  # fraction of purchased electricity

# Cat 6: Business travel (DEFRA/ICAO-style defaults, kgCO2 per passenger-km)
TRAVEL_FACTORS: dict[str, float] = {
    "flight_short_haul":   0.15,   # < 3hr, economy
    "flight_long_haul":    0.19,   # > 3hr, economy
    "car_petrol":          0.17,   # per km, average vehicle
    "car_diesel":          0.17,
    "taxi":                0.17,
    "bus":                 0.05,   # per passenger-km
    "rail":                0.035,  # per passenger-km
}

# Cat 7: Commuting (kgCO2 per km, per passenger)
COMMUTE_FACTORS: dict[str, float] = {
    "car":       0.17,
    "bus":       0.05,
    "metro":     0.004,   # Guangzhou/Shenzhen metro
    "motorcycle": 0.10,
    "walk_cycle": 0.0,
}

# Cat 1: Purchased goods spend-based (simplified, kgCO2 per CNY spent)
# Use EXIOBASE/IO-derived rough factors; replace with Climatiq for production
SPEND_FACTORS: dict[str, float] = {
    "raw_materials":     0.0008,   # kgCO2/CNY
    "manufactured_goods": 0.0005,
    "services":          0.0002,
    "logistics":         0.0006,
}
