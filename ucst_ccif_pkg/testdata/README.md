# OCIP — GBA Test-Data Pack

Test data for the OCIP Streamlit app, built from **real online sources** for the
Pearl River Delta / Greater Bay Area. One script reproduces everything:

```
python testdata/build_testdata.py
```

---

## Files

| File | Content | Source (real, online) | Licence | Use in app |
|---|---|---|---|---|
| `gba_meteo_shenzhen_bay_2023.csv` | daily T, wind, rain, RH, shortwave radiation — Shenzhen Bay / Deep Bay (22.51°N, 113.95°E), 365 days 2023 | Open-Meteo Archive API → **ERA5 reanalysis** (ECMWF) | CC-BY-4.0 (Open-Meteo terms; ERA5 licence) | tab 4 (Biogenic) forcing context; tab 9 worked example |
| `gba_meteo_guangzhou_2023.csv` | same, Guangzhou (23.13°N, 113.26°E) | Open-Meteo / ERA5 | same | same |
| `gba_flux_shenzhen_bay_2023.csv` | **upload-ready Leakage file** (tab 5): `date, NEE_daily_total, GPP_daily_total, ER_daily_total, wind_speed_mean, ustar_mean, co2_mole_fraction_mean, temperature_2m_mean, precipitation_sum` | meteorology: ERA5 (real); **NEE/GPP/ER: CarbonContinuumModel, forced by the real meteorology** (see caveats); CO₂: NOAA GML Mauna Loa 2023 monthly means (approx) | real parts CC-BY-4.0; model output Apache-2.0 (this repo) | **tab 5 → upload** — expects GPP/ER flagged LEAKY, weather exogenous; 365 rows ≥ 30 |
| `gba_flux_guangzhou_2023.csv` | same for Guangzhou | same | same | same |
| `gba_grid_fossil_co2_2022.csv` | 1,457 non-zero 0.1° grid cells in the GBA box (21–24°N, 111–116°E): annual fossil CO₂ per cell (kg & t yr⁻¹) | **Global Carbon Budget 2025** gridded fossil emissions (`Fossil_carbon_emissions_gridded_GCB2025_2015-2024.nc`, in project folder) | GCB data policy (open, cite Friedlingstein et al. 2025) | tab 8 (Anthropogenic) — spatial truth for the GBA: box sum ≈ 447 Mt CO₂/yr (2022, GCB2015–24 mean file) |
| `ceads_guangdong_2022_by_sector.csv` | Guangdong 2022 CO₂ by sector, fuel-summed rows (48 rows incl. `TotalEmissions`) | **CEADs** `中国省级分部门碳排放清单（2022）.xlsx` (project folder), sheet `Guangdong2022` | CEADs open data (CC BY-NC, cite Shan et al.) | tab 8 — sector ledger; note the **口径 caveat** below |

---

## Caveats — read before quoting any number

1. **Flux files are model output, not tower data.** `NEE/GPP/ER` are synthesised
   by `CarbonContinuumModel` driven by *real* ERA5 meteorology (radiation, T, rain)
   for the site. They are for testing the **pipeline** (upload, column
   auto-classification, correlation screen, honest-R² refit) — not for scientific
   claims. Annual NEE ≈ −233 / −222 g C m⁻² yr⁻¹ (net sink, plausible for
   subtropical wetland; app demo uses −155.6).
2. **`ustar_mean` is an estimate** (`u* ≈ 0.10 × u10`, log-layer rule of thumb).
   A real tower supplies u* directly (EddyPro/ONEFlux).
3. **`co2_mole_fraction_mean` uses NOAA GML Mauna Loa monthly means (approx,
   2023)** — a global background value, not a GBA in-situ measurement.
   Exact monthly values: https://gml.noaa.gov/ccgg/trends/data.html
4. **CEADs 口径 vs the app's built-in number.** The app's Anthropogenic tab cites
   **613.9 Mt CO₂** (2022, sector-final accounting, IPCC Sectoral Approach, Shan
   et al.). The local CEADs workbook's `TotalEmissions` row sums **≈1,239 Mt**
   because it totals *raw fuel columns* (energy-conversion double counting:
   upstream fuel for power + downstream use). Use the CSV for **structure and
   relative sector mix**, and the app's built-in 613.9 Mt for the headline.
5. **GCB grid cell values are annual fossil CO₂ (kg yr⁻¹ cell⁻¹)** from the
   2015–2024 mean field; box sum ≈ 447 Mt CO₂/yr sits below Guangdong's ~614 Mt
   because the box excludes the non-Pearl-River parts of Guangdong.
6. Open-Meteo/ERA5 is a **reanalysis**, not an in-situ station record. For
   verification-grade meteorology prefer tower or HKO data.

---

## The real GBA flux gap (and where the next data comes from)

There is **no open, publicly downloadable eddy-flux tower in the GBA core**
(Shenzhen Bay / Mai Po / Deep Bay) yet — that is the MOU/ChinaFLUX step in the
roadmap. The nearest open mainland flux data:

- **NESDC / ChinaFLUX — Jinfo Mountain station** (Chongqing, subtropical forest),
  2020–2022 half-hourly flux
  - DOI `10.12199/nesdc.jfk.202601` · CSTR `15732.11.nesdc.jfk.202601`
  - https://www.nesdc.org.cn/sdo/detail?id=6acd9bff7e28175caefb7513
  - Licence **CC BY-NC 4.0**, protected until **2026-12-15**, download via CERN
    account login
- **JapanFlux2024** (Kyushu/Okinawa, subtropical) — CC-BY-4.0, ready now:
  https://japanflux.org
- **FLUXNET2015 / FLUXNET Data System** — global tier-1 sites, CC-BY-4.0:
  https://fluxnet.org

When a real GBA wetland tower comes online (or a partner MOU lands), replace the
flux files with the tower CSVs — the app's Leakage tab will take them unchanged
(one target column + ≥1 predictor, ≥30 rows).

---

## How to verify the pack

```bash
cd ucst_ccif_pkg
python testdata/build_testdata.py      # regenerates everything + runs the leakage check
python -m pytest -q                    # 43/43 core-engine tests
```

The builder's last step runs `audit_leakage` on both flux files — expected:
`GPP_daily_total` and `ER_daily_total` flagged **LEAKY**, weather exogenous.
