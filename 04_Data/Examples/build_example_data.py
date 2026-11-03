# -*- coding: utf-8 -*-
"""
Build a complete, self-consistent example dataset for the OCIP / Carbon Falcon
app (v0.4.0, 5 workspaces). Run:  python build_example_data.py

Outputs in this folder:
  ocip_example_activity.csv      -> Tab 1 Activity ledger  (Scope 1-3, S1)
  ocip_example_flux.csv          -> Tab 1 Flux ledger + Tab 4 Model competition
                                   (2019-2024, satisfies NEE = ER - GPP, has a
                                    storm pulse in Aug 2021, no missing values)
  ocip_example_stock.csv         -> Tab 1 Stock ledger     (S3/S4 cross-check;
                                   removal = 2023 flux integral, so the
                                   scale audit balances)
  ocip_example_intervention.csv  -> Tab 1 Intervention ledger (S5, Eq.3)

Calibration-cutoff hint for Tab 4: keep the default 2020 (calib 2019-2020,
out-of-sample validation 2021-2024), matching paper Section 5.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(42)
C_TO_CO2 = 44.0 / 12.0
M2_PER_HA = 1e4
G_TO_T = 1e-6


def build_flux() -> pd.DataFrame:
    dates = pd.date_range("2019-01-01", "2024-12-31", freq="D")
    n = len(dates)
    doy = dates.dayofyear.to_numpy()
    year = dates.year.to_numpy()

    # --- meteorology (Guangzhou-flavoured) -----------------------------------
    temp = 16 + 10 * np.sin(2 * np.pi * (doy - 100) / 365) + rng.normal(0, 2.5, n)
    temp = np.clip(temp, 4, 33)
    wind = 14 + 4 * np.sin(2 * np.pi * (doy - 40) / 365) + rng.normal(0, 4, n)
    wind = np.clip(wind, 2, 35)
    ustar = wind / 10 + rng.normal(0, 0.15, n)
    ustar = np.clip(ustar, 0.2, 4.0)
    co2 = 409 + (year - 2019) * 2.6 + rng.normal(0, 0.8, n)      # 409 -> ~422 ppm
    precip = np.clip(rng.gamma(1.4, 4.0, n)
                     * (0.7 + 0.6 * np.sin(2 * np.pi * (doy - 150) / 365)), 0, 60)

    # --- fluxes: ER temperature-driven; NEE seasonal uptake; GPP closes the
    #     identity  NEE = ER - GPP  (Eq.7 leakage-free bookkeeping) ----------
    ER = 1.1 + 0.55 * np.clip(temp - 8, 0, None) + rng.normal(0, 0.25, n)
    NEE = -1.2 - 0.6 * np.sin(2 * np.pi * (doy - 95) / 365) + rng.normal(0, 0.4, n)
    storm = (dates >= "2021-08-01") & (dates <= "2021-08-07")
    NEE[storm] += 5.2
    ER[storm] += 5.8
    GPP = ER - NEE

    # --- agent-state management signal (Eq.2 / M2a): tidal water level ------
    # Simulated independently of NEE by construction -> leakage-free agent
    # feedback. Seasonal tide + a wetland-restoration gate from 2022 (i.e. it
    # only varies inside the out-of-sample window 2021-2024), matching the
    # paper's "agent feedback adds no daily-scale gain" conclusion.
    base_tide = 1.5 + 0.5 * np.sin(2 * np.pi * (doy - 120) / 365)
    gate = (dates >= "2022-01-01").astype(float)
    water = np.clip(base_tide + 0.9 * gate + rng.normal(0, 0.15, n), 0.2, 3.5)

    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "NEE_daily_total": np.round(NEE, 4),
        "GPP_daily_total": np.round(GPP, 4),
        "ER_daily_total": np.round(ER, 4),
        "wind_speed_mean": np.round(wind, 2),
        "ustar_mean": np.round(ustar, 2),
        "co2_mole_fraction_mean": np.round(co2, 1),
        "temperature_2m_mean": np.round(temp, 1),
        "precipitation_sum": np.round(precip, 1),
        "water_level": np.round(water, 2),
    })


def flux_to_tco2e(df: pd.DataFrame, area_ha: float,
                  year: int) -> float:
    """Integrate one calendar year of daily NEE (gC m-2 d-1) to tCO2e."""
    sub = df[df["date"].str.startswith(str(year))]
    gcm2 = float(sub["NEE_daily_total"].sum())          # g C per m2
    return abs(gcm2) * M2_PER_HA * area_ha * C_TO_CO2 * G_TO_T


def main() -> None:
    os.makedirs(HERE, exist_ok=True)
    flux = build_flux()
    flux.to_csv(os.path.join(HERE, "ocip_example_flux.csv"),
                index=False, lineterminator="\n")

    # stock removal := observed removal = 2023 flux integral (scale audit balances)
    removal = flux_to_tco2e(flux, area_ha=100.0, year=2023)
    stock = pd.DataFrame({"area_ha": [100.0],
                          "removal_tco2e": [round(removal, 1)]})
    stock.to_csv(os.path.join(HERE, "ocip_example_stock.csv"),
                 index=False, lineterminator="\n")

    activity = pd.DataFrame({
        "scope": [2, 1, 2, 3],
        "category": ["electricity", "fuel", "purchased_goods", "purchased_goods"],
        "activity_key": ["guangdong", "diesel_L", "manufactured_goods",
                         "manufactured_goods"],
        "quantity": [1135589.4, 20000.0, 2000000.0, 1500000.0],
    })
    activity.to_csv(os.path.join(HERE, "ocip_example_activity.csv"),
                    index=False, lineterminator="\n")

    intervention = pd.DataFrame({
        "scenario": ["wetland_restoration"],
        "baseline_removal_tco2e": [300.0],
        "intervention_removal_tco2e": [420.0],
        "active_fraction": [0.4],
    })
    intervention.to_csv(os.path.join(HERE, "ocip_example_intervention.csv"),
                        index=False, lineterminator="\n")

    print(f"flux rows: {len(flux)}  ({flux['date'].min()} .. {flux['date'].max()})")
    print(f"2023 flux integral: {removal:.1f} tCO2e (stock ledger mirrors this)")
    print(f"NaN anywhere in flux: {int(flux.isna().sum().sum())}")


if __name__ == "__main__":
    main()
