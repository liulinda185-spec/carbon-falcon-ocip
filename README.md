# UCST-CCIF — Carbon Falcon / OCIP

**Conservation-Constrained Carbon Flux Integrated Framework** — auditable, cross-scale carbon accounting from enterprise Scope 1 to coastal blue carbon.

## Try it now — no install, no sign-in

**[▶ Open the public trial →](https://carbon-falcon-8dubwckd7mfseynb7azamc.streamlit.app/)**

A carbon-verification layer for GBA enterprises. Sample ledgers are preloaded —
you reach an audited certificate in about three minutes. The certificate is
*earned*: if a removal claim exceeds what the independent flux record supports,
the verdict is **FAIL — over-claim detected**, not a softer note. No sign-in,
uploaded files are never stored; only anonymous step counts are collected.

## What it does

- **Audit pipeline (v0.4.0)** — the OCIP "four ledgers → 7 steps → 8 artifacts" loop:
  - `ucst_ccif.audit_pipeline.run_audit` — stages S1 boundary / S2 factors / S3 conservation / S4 scale / S5 additionality / S6 leakage / S7 uncertainty, tolerant of missing ledgers (reported as data gaps, never silently estimated), emitting an 8-artifact `AuditReport` with a PASS / REVIEW / FAIL / INCOMPLETE certificate.
  - `ucst_ccif.audit_pipeline.time_series_scale_audit` — Eq.(4) aggregation-commutator residual εA in the time dimension (daily integral vs monthly-mean-then-integrate).
  - `ucst_ccif.attribution` — Eq.1 conservation reconciliation (claim vs independent observation → ε_C, over-claim detection), Eq.3 additionality counterfactual (active trigger F_a vs passive response F_p), Eq.2 attribution split.
  - `ucst_ccif.leakage` — three-step detector that flags predictors algebraically derived from NEE (GPP, ER, cumulative balance) before they fake model performance; `refit_without_leakage` quantifies the apparent gain (Sapelo 36.1% signature).
  - `ucst_ccif.models` — nested M0 / M1 / M2a comparison (Eq.8–10) with out-of-sample validation, and `m3_counterfactual` (military / restoration / DAC scenario engine, Eq.3 / Eq.10).
- **Continuum model** (`ucst_ccif.compartments`): 12-pool daily land–river–coastal carbon model with Q10 temperature response, moisture constraints, and a mass-balance residual ε_C.
- **Monte Carlo uncertainty** (`ucst_ccif.uncertainty`): parameter ensemble with 90% confidence intervals.
- **MVP integration kernels**: `rothc_lite`, `bluecarbon_lookups`, `dndc_lite`, `threepg_lookups`, `raymond_evasion`, `netcdf_priors`.
- **CLI**: `ucst-ccif run | audit | compare | rothc | blue | rice | evasion | priors | version`.

## Streamlit app (5 workspaces, v0.4.0, English UI)

1. **Upload & Dictionary** — four ledgers (activity / flux / stock / intervention) with CSV templates that carry `#` comment lines (full names + units), per-ledger column dictionaries, and area input.
2. **Audit Report** — S1–S7 pipeline, 8 artifacts, certificate, leakage RYG flag, time-series scale audit εA (Eq.4–5), PDF evidence pack.
3. **Equations (Eq.1–10)** — every numbered equation of the anchor manuscript (SSRN 7417192) rendered with its logic, software location and pipeline stage.
4. **Model competition (M0–M3, Eq.8–10)** — reproduce the paper's §5 nested comparison on your own flux ledger: out-of-sample metrics, predictions, M3 counterfactual scenario calculator.
5. **Benchmarks** — official reference data (CEADs Guangdong, Global Carbon Budget, HK EPD, CH₄ kernels, CCER mangrove screening) + NGFS stress lens.

Run locally: `streamlit run app/streamlit_app.py` (from `ucst_ccif_pkg/`).

## Install

```bash
pip install -e ".[dev]"      # for development
pip install -e ".[app]"       # for the Streamlit MVP
pip install -e ".[data]"      # for NetCDF prior pulls (xarray + netCDF4)
```

## Quick start

```python
from ucst_ccif import CarbonContinuumModel, ParameterSet, MonteCarloEnsemble
import numpy as np

T = 365
gpp = np.clip(3.5 + 2.5*np.sin(2*np.pi*np.arange(T)/365), 0.2, 7.0)
T_air = np.full(T, 20.0)
swc = np.full(T, 0.55)
rain = np.zeros(T)

model = CarbonContinuumModel(ParameterSet())
state = model.run(gpp, T_air, swc, rain)
print(f"Annual NEE: {state.nee.mean()*365:.1f} gC m-2 yr-1")
```

## How the audit works (S1–S7 → 8 artifacts)

Four ledgers in → a 7-step falsification pipeline → eight audited outputs plus a certificate.

- S1 boundary inventory (activity × emission factors) → S2 factors (NEE = GPP − ER) → S3 conservation ε_C = observed − claimed (Eq.1) → S4 scale (Eq.4–5) → S5 additionality F_a vs F_p (Eq.2–3) → S6 leakage three-step audit (Eq.7) → S7 Monte Carlo uncertainty.

**Worked example** — a company books 420 tCO₂e removed but claims 600: S3 computes ε_C = 420 − 600 = **−180 t** ⇒ certificate **FAIL — over-claim detected**. Negative ε_C always means the books claim more than the independent record supports.

## Tests

```bash
pytest tests/ -v
```

118 tests pass, including attribution, audit-pipeline (scale audit), leakage-refit,
event-tracker, tenant-isolation and M0–M3 competition suites.

## Paper

Liu, Y. & Cui, W. *Integrating Ecological Carbon Fluxes Across Scales: A Conservation-Constrained, Falsification-Based Modelling Framework based on Unified Complex System Theory (UCST)*. SSRN 7417192 — https://ssrn.com/abstract=7417192

## License

Apache License 2.0 — see [LICENSE](LICENSE). Part of the UCST-CCIF Open Carbon Platform (OCIP) project, GBA-first, going global.
