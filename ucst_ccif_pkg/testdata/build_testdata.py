"""
Build the OCIP GBA test-data pack from REAL online sources.

Sources
-------
1. Open-Meteo Archive API (ERA5 reanalysis) — GBA meteorology, free, no key
   https://open-meteo.com/en/docs/historical-weather-api
2. Global Carbon Budget 2025 gridded fossil CO2 (0.1 deg, kg CO2 yr-1 cell-1)
   https://zenodo.org/records/xxxx (see README) — file already in project folder
3. CEADs China provincial sectoral CO2 inventory 2022 — Guangdong sheet
   https://www.ceads.net.cn — xlsx already in project folder
4. NOAA GML Mauna Loa CO2 monthly means (2023, approx values for demo)

Generated (written to ./testdata/):
  gba_meteo_shenzhen_bay_2023.csv     real ERA5 meteorology (daily)
  gba_meteo_guangzhou_2023.csv        real ERA5 meteorology (daily)
  gba_flux_shenzhen_bay_2023.csv      real meteo-forced CarbonContinuumModel flux
                                       (NEE/GPP/ER model-synthesised, meteorology real)
  gba_grid_fossil_co2_2022.csv        real GCB2025 grid cells (GBA box, non-zero)
  ceads_guangdong_2022_by_sector.csv  real CEADs Guangdong 2022 sector totals
  README.md                           provenance + licences + how to use in app
Run:  python build_testdata.py   (idempotent, overwrites the CSVs)
"""
from __future__ import annotations
import json, math, pathlib, urllib.request
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE

ROOT = HERE.parent  # ucst_ccif_pkg
import sys
sys.path.insert(0, str(ROOT))

from ucst_ccif import CarbonContinuumModel, ParameterSet  # noqa: E402

# ------------------------------------------------------------------
# 1. Open-Meteo ERA5 meteorology — two GBA sites
API = "https://archive-api.open-meteo.com/v1/archive"
SITES = {
    "shenzhen_bay": (22.51, 113.95),   # Deep Bay / Shenzhen Bay wetland zone
    "guangzhou":    (23.13, 113.26),   # Pearl River inner GBA
}
VARS = ("temperature_2m_mean,wind_speed_10m_mean,precipitation_sum,"
        "relative_humidity_2m_mean,shortwave_radiation_sum")
START, END = "2023-01-01", "2023-12-31"


def fetch_meteo(lat: float, lon: float) -> pd.DataFrame:
    url = (f"{API}?latitude={lat}&longitude={lon}"
           f"&start_date={START}&end_date={END}"
           f"&daily={VARS}&timezone=Asia%2FShanghai")
    with urllib.request.urlopen(url, timeout=60) as r:
        j = json.load(r)
    d = j["daily"]
    df = pd.DataFrame({
        "date": d["time"],
        "temperature_2m_mean": d["temperature_2m_mean"],
        "wind_speed_10m_mean": d["wind_speed_10m_mean"],
        "precipitation_sum": d["precipitation_sum"],
        "relative_humidity_2m_mean": d["relative_humidity_2m_mean"],
        "shortwave_radiation_sum": d["shortwave_radiation_sum"],
    })
    return df


# ------------------------------------------------------------------
# NOAA GML Mauna Loa CO2, 2023 — monthly means (approx, for demo exogenous column)
# Exact values: https://gml.noaa.gov/ccgg/trends/data.html
ML2023_APPROX = np.array([421.9, 422.2, 423.1, 423.6, 424.2, 424.8,
                          425.3, 425.2, 424.7, 424.0, 422.9, 421.9])


def add_co2_monthly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    mon = pd.to_datetime(df["date"]).dt.month.values
    df["co2_mole_fraction_mean"] = ML2023_APPROX[mon - 1]
    return df


# ------------------------------------------------------------------
# 2. Model-synthesised wetland flux, forced by REAL meteorology
def build_flux(df_meteo: pd.DataFrame) -> pd.DataFrame:
    df = df_meteo.copy()
    T = len(df)
    doy = np.arange(T)
    T_air = df["temperature_2m_mean"].values.astype(float)
    T_air = np.nan_to_num(T_air, nan=T_air[~np.isnan(T_air)].mean())
    sw = df["shortwave_radiation_sum"].values.astype(float)
    sw = np.nan_to_num(sw, nan=0.0)
    sw_mean = max(sw.mean(), 1e-6)
    rain = df["precipitation_sum"].values.astype(float)
    rain = np.nan_to_num(rain, nan=0.0)
    # soil water: simple bucket from rain (0.25–0.85)
    swc = np.full(T, 0.55)
    for i in range(1, T):
        swc[i] = np.clip(swc[i-1] + 0.02 * rain[i] - 0.02, 0.25, 0.85)

    # GPP: synthesised from real radiation + temperature (documented in README)
    gpp = np.clip((1.2 + 2.6 * sw / sw_mean) * (1.0 + 0.04 * (T_air - 22.0)),
                  0.3, 9.0)

    m = CarbonContinuumModel(ParameterSet())
    s = m.run(gpp, T_air, swc, rain)

    er = s.ra + s.rh                      # model respiration (gC m-2 d-1)
    ustar = 0.10 * df["wind_speed_10m_mean"].values  # approx log-layer estimate
    out = pd.DataFrame({
        "date": df["date"],
        "NEE_daily_total": np.round(s.nee, 4),          # target (model)
        "GPP_daily_total": np.round(gpp, 4),            # LEAKY by name+identity
        "ER_daily_total": np.round(er, 4),              # LEAKY by name+identity
        "wind_speed_mean": df["wind_speed_10m_mean"],
        "ustar_mean": np.round(ustar, 4),
        "co2_mole_fraction_mean": add_co2_monthly(df)["co2_mole_fraction_mean"],
        "temperature_2m_mean": df["temperature_2m_mean"],
        "precipitation_sum": df["precipitation_sum"],
    })
    return out


# ------------------------------------------------------------------
# 3. GCB2025 gridded fossil CO2 — extract GBA box
def build_gba_grid() -> pd.DataFrame:
    import h5py
    nc = ROOT / ".." / "Fossil_carbon_emissions_gridded_GCB2025_2015-2024.nc"
    f = h5py.File(str(nc.resolve()), "r")
    lat = f["lat"][:]; lon = f["lon"][:]; co2 = f["TOTAL/CO2"][:]
    f.close()
    m = (lat >= 21.0) & (lat <= 24.0)
    n = (lon >= 111.0) & (lon <= 116.0)
    ii, jj = np.nonzero(np.outer(m, n) & (co2 > 0))
    rows = []
    for i, j in zip(ii, jj):
        rows.append({"lat": round(float(lat[i]), 2),
                     "lon": round(float(lon[j]), 2),
                     "kgCO2_yr": round(float(co2[i, j]), 0),
                     "tCO2_yr": round(float(co2[i, j]) / 1000.0, 1)})
    df = pd.DataFrame(rows).sort_values("tCO2_yr", ascending=False)
    df["gba_region"] = "GBA box 21–24N / 111–116E (0.1 deg cell)"
    return df


# ------------------------------------------------------------------
# 4. CEADs Guangdong 2022 — aggregate fuels per sector row
def build_ceads_gd() -> pd.DataFrame:
    import openpyxl
    xls = ROOT / ".." / "中国省级分部门碳排放清单（2022）.xlsx"
    wb = openpyxl.load_workbook(str(xls.resolve()), read_only=True)
    ws = wb["Guangdong2022"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [str(c).strip() for c in rows[0]]
    fuel_cols = [i for i, h in enumerate(header) if h not in ("Emission_Inventory", "")]
    out = []
    for r in rows[3:]:
        if r[0] is None:
            continue
        sector = str(r[0]).strip()
        if sector in ("unit", ""):
            continue
        tot = sum(float(r[i]) for i in fuel_cols if isinstance(r[i], (int, float)))
        out.append({"sector": sector, "MtCO2_2022": round(tot, 4),
                    "tCO2_2022": round(tot * 1e6, 0)})
    df = pd.DataFrame(out).sort_values("MtCO2_2022", ascending=False)
    df.insert(0, "note",
              "CEADs Guangdong 2022, fuel-summed rows (raw_coal … other fuels); "
              "units Mt CO2; sector labels as in source sheet")
    return df


# ------------------------------------------------------------------
def main() -> None:
    print("== 1. Meteorology (Open-Meteo / ERA5 reanalysis) ==")
    for site, (lat, lon) in SITES.items():
        met = fetch_meteo(lat, lon)
        met.to_csv(OUT / f"gba_meteo_{site}_2023.csv", index=False)
        print(f"  {site}: {len(met)} days, "
              f"T {met['temperature_2m_mean'].mean():.1f} C, "
              f"wind {met['wind_speed_10m_mean'].mean():.2f} m/s")

    print("== 2. Wetland flux (real meteo forcing + model NEE/GPP/ER) ==")
    for site in SITES:
        met = pd.read_csv(OUT / f"gba_meteo_{site}_2023.csv")
        flx = build_flux(met)
        flx.to_csv(OUT / f"gba_flux_{site}_2023.csv", index=False)
        print(f"  {site}: NEE annual {flx['NEE_daily_total'].mean()*365:+.1f} gC/m2/yr, "
              f"rows {len(flx)}")

    print("== 3. GCB2025 gridded fossil CO2 — GBA box ==")
    g = build_gba_grid()
    g.to_csv(OUT / "gba_grid_fossil_co2_2022.csv", index=False)
    print(f"  {len(g)} non-zero cells; top cell "
          f"({g['lat'].iloc[0]},{g['lon'].iloc[0]}) {g['tCO2_yr'].iloc[0]:,.0f} tCO2/yr; "
          f"box sum {g['tCO2_yr'].sum():,.0f} tCO2/yr")

    print("== 4. CEADs Guangdong 2022 sector totals ==")
    c = build_ceads_gd()
    c.to_csv(OUT / "ceads_guangdong_2022_by_sector.csv", index=False)
    print(f"  {len(c)} sectors; top: {c['sector'].iloc[0]} "
          f"{c['MtCO2_2022'].iloc[0]:.1f} Mt; total {c['MtCO2_2022'].sum():.1f} Mt")

    print("== 5. Verify leakage engine on the flux files ==")
    from ucst_ccif import audit_leakage
    for site in SITES:
        df = pd.read_csv(OUT / f"gba_flux_{site}_2023.csv")
        rep = audit_leakage(df, "NEE_daily_total",
                            [c for c in df.columns if c != "date" and c != "NEE_daily_total"])
        leaky = sorted(k for k, v in rep.classified.items() if v == "leaky")
        print(f"  {site}: LEAKY -> {leaky}")
    print("DONE.")


if __name__ == "__main__":
    main()
