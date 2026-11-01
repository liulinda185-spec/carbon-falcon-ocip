# OCIP MVP Integration Guide — 0–6 months kernels

How the six MVP kernels from the *Integration roadmap* are implemented in
`ucst_ccif_pkg` (v0.2.0), how to wire real data, and what to calibrate next.

Status: **implemented & tested** — 37/37 pytest green, CLI smoke-tested.
All literature values are DEFAULTS for scoping; every item marked `[待核证]`
must be re-verified against primary sources before any client-facing use.

---

## 1. Architecture — where each kernel lives

```
ucst_ccif_pkg/ucst_ccif/
  compartments.py          (existing) 12-pool continuum, M0-M3, leakage audit
  rothc_lite.py            NEW  RothC 4-pool soil C (monthly, date-stamped)
  bluecarbon_lookups.py    NEW  InVEST-style blue-C stocks/sequestration/CH4
  dndc_lite.py             NEW  rice CH4 Tier-1 management table
  threepg_lookups.py       NEW  3-PG species params + light NPP kernel
  raymond_evasion.py       NEW  inland-water CO2 evasion (gas-transfer)
  netcdf_priors.py         NEW  read-only prior registry + client (CAMS/
                                FLUXCOM/SoilGrids/CMS/SOCAT/CEADs)
  cli.py                   extended  rothc|blue|rice|evasion|priors
tests/                    +5 new test files (16 new tests)
```

Design contract: these are **cheap lookup kernels + prior consumers**. OCIP
does NOT re-run JULES/ORCHIDEE/DNDC-full/3-PG-full; it embeds the thin
version and pulls gridded outputs as read-only priors.

## 2. Kernel-by-kernel

### 2.1 RothC-lite (`rothc_lite.py`)
- Pools DPM/RPM/BIO/HUM + inert IOM; monthly timestep; RothC rate modifiers
  a(T), b(SMD/TSMD), c(cover); clay split x = 1.67(1.85+1.60e^-0.0786·clay).
- Inputs: `c_inputs` (tC/ha/mo), T, smd, tsd, cover, clay_pct — via arrays or a
  **date-stamped DataFrame** (`run_rothc_dataframe`).
- Conservation: exact by construction (test `test_mass_balance_exact`).
- Next step: replace default DPM:RPM splits with GBA crop/forest values;
  drive `smd/tsd` from ERA5/Open-Meteo soil moisture when wiring weather.

### 2.2 Blue-carbon lookups (`bluecarbon_lookups.py`)
- Mangrove / saltmarsh / seagrass × tropical / subtropical / temperate:
  AGB+BGB+soil(1m) stocks, burial (McLeod 2011 ~226/218/138 gC/m2/yr),
  CH4 (2013 Wetlands Supplement `[待核证]`).
- API: `blue_carbon_estimate(eco, region, area_ha)` → stocks, burial,
  CH4 CO2e (GWP_CH4_AR6 = 27.0).
- Next step: replace defaults with GBA site data (Qi'ao/Shenzhen-Zhongshan/
  Zhanjiang) once tower or soil-core campaigns exist; cross-check against
  NASA CMS mangrove priors (see 2.6).

### 2.3 DNDC-lite rice CH4 (`dndc_lite.py`)
- IPCC Tier-1 scaling factors: CH4_season = ΣEF_water × SFw × SFp × SFo.
- Water regimes (Asia defaults): continuously flooded 1.91, IF-single 0.91,
  IF-multiple 0.58, rainfed 1.21/0.66, deepwater 1.45 kg CH4/ha/d.
- Next step: re-verify against 2019 Refinement tables; calibrate cultivar SFp
  for GBA indica/hybrid varieties; hook GBA rice calendars (two crops/yr).

### 2.4 3-PG lookups (`threepg_lookups.py`)
- Species table (10 GBA species incl. mangroves) with alpha_C, SLA,
  allocation fractions, wood density, and the RothC `litter_class` tie-in.
- Thin NPP scoping: `estimate_npp(PAR, fAPAR)`.
- Next step: calibrate alpha_C per species with tower/site data; this is a
  LOOKUP layer, not full 3-PG (full 3-PG is research-grade, not for MVP).

### 2.5 Raymond-2013 evasion (`raymond_evasion.py`)
- k600: streams/rivers `2841.4·(v·S)^0.353` (Raymond et al. 2012), lakes
  wind/default 0.7 m/d (Cole & Caraco 1998); Sc & Henry (Wanninkhof 1992 /
  Weiss 1974); flux gC/m2/d, totals MgC/yr.
- Global framing: ~2.1 PgC/yr inland-water evasion `[待核证 breakdown]`.
- Next step: tune k600 with Pearl River reach data; default stream params give
  high k for steep fast reaches — use GBA lowland values (v≈0.3, S≈1e-4).

### 2.6 Prior registry (`netcdf_priors.py`)
- `PRIOR_SOURCES` registry for CAMS, FLUXCOM-X, SoilGrids, NASA CMS mangrove,
  SOCAT, CEADs: URL, licence, variables, ETL hint.
- `PriorClient`: `list_sources()`, `fetch(name)` (raises ImportError if
  xarray missing; NotImplementedError with ETL hint until wired), offline
  `demo_grid()` for interface testing.
- Install real NetCDF stack: `python -m pip install -e ".[data]"`.

## 3. What to wire next (data acquisition)

| Kernel | Source | Action | Licence |
|---|---|---|---|
| RothC drivers | Open-Meteo / ERA5 | soil moisture → SMD/TSMD | free (C3S) |
| Blue-C priors | NASA CMS mangrove | clip GBA bbox | public domain |
| Rice CH4 | MEE/GBA rice stats | season length, water regime maps | — |
| Evasion | SOCAT + PRD gauge | coastal fCO2, river v/S | SOCAT agreement |
| GPP/NEE prior | FLUXCOM-X | monthly GPP/NEE NetCDF | CC-BY-4.0 |
| CO2/CH4 prior | CAMS ADS API | GBA subset | CAMS licence |
| L4 baseline | CEADs | Guangdong + PRD city sheets | registration |

Priority order: CAMS + FLUXCOM (priors for the M0-M3 engine) → Open-Meteo
(weather drivers) → NASA CMS (blue-C cross-check) → SOCAT (evasion).

## 4. Known gaps / `[待核证]`

- 2019 Refinement rice CH4 EF updates; 2013 Wetlands Supplement coastal CH4
  values; Raymond 2013 breakdown; cultivar SFp for GBA varieties; species
  alpha_C; IPCC-compliant tC/ha vs gC/m2 harmonisation in reports.
- NetCDF ETL bodies (per-source `fetch`) are stubs by design — wire one
  source at a time with tests; never fabricate data in the ETL.

## 5. Build order & effort (part-time, single dev)

1. Weather driver (Open-Meteo → SMD/TSMD) + RothC report page — 3-5 d
2. CAMS + FLUXCOM NetCDF pull + cache + regrid — 3-5 d
3. Blue-C page wired to NASA CMS priors + site override — 2-3 d
4. Rice CH4 page with GBA calendar — 2-3 d
5. Evasion kernel report (Pearl River + PRD reservoirs) — 2-3 d
6. Streamlit MVP tabs integration + PDF export update — 3-4 d

Total ≈ 15-23 dev-days to a demonstrable GBA demo covering all six kernels.
