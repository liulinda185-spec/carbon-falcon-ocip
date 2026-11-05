# UCST-CCIF

**Conservation-Constrained Carbon Flux Integrated Framework** — auditable, cross-scale carbon accounting from enterprise Scope 1 to coastal blue carbon.

## Try it now — no install, no sign-in

**[▶ Open the public trial →](https://carbon-falcon-8dubwckd7mfseynb7azamc.streamlit.app/)**

A carbon-verification layer for GBA enterprises. Sample data is preloaded — you
reach an audited certificate in about three minutes. The certificate is *earned*:
if a removal claim exceeds what the independent flux record supports, the verdict
is **FAIL — over-claim detected**, not a softer note. No sign-in, no data leaves
your browser; only anonymous step counts are collected.

## What it does

- **Continuum model** (`ucst_ccif.compartments`): 12-pool daily land–river–coastal carbon model with Q10 temperature response, moisture constraints, and a mass-balance residual ε_C that flags bookkeeping gaps.
- **Leakage audit** (`ucst_ccif.leakage`): three-step detector that flags predictors algebraically derived from NEE (GPP, ER, cumulative balance) before they fake model performance.
- **Nested M0–M3 comparison** (`ucst_ccif.models`): scipy-optimized models where each added layer must justify itself out-of-sample.
- **Monte Carlo uncertainty** (`ucst_ccif.uncertainty`): parameter ensemble with 90% confidence intervals.
- **MVP integration kernels (v0.2.0)**:
  - `rothc_lite` — RothC 4-pool soil-C kernel (monthly, date-stamped inputs)
  - `bluecarbon_lookups` — InVEST-style mangrove/saltmarsh/seagrass stocks, burial, CH4
  - `dndc_lite` — rice CH4 Tier-1 (IPCC scaling factors, water-regime management table)
  - `threepg_lookups` — GBA subtropical species parameters + light NPP scoping
  - `raymond_evasion` — inland-water CO2 evasion (gas-transfer, Raymond-2013)
  - `netcdf_priors` — read-only prior registry/client for CAMS, FLUXCOM, SoilGrids, NASA CMS mangrove, SOCAT, CEADs
- **CLI**: `ucst-ccif run | audit | compare | rothc | blue | rice | evasion | priors | version`.
- **Audit pipeline (v0.3.0)** — the OCIP "four ledgers → 7 steps → 8 artifacts" loop:
  - `ucst_ccif.attribution` — Eq.1 conservation reconciliation (claim vs independent observation → ε_C, over-claim detection), Eq.3 additionality counterfactual (active trigger F_a vs passive response F_p), Eq.2 attribution split (agent identifiable only when the flux changes reproducibly).
  - `ucst_ccif.audit_pipeline.run_audit` — stages S1 boundary / S2 factors / S3 conservation / S4 scale / S5 additionality / S6 leakage / S7 uncertainty, tolerant of missing ledgers (reported as data gaps, never silently estimated), emitting an 8-artifact `AuditReport`.
  - `ucst_ccif.leakage.refit_without_leakage` — step 3 of the leakage protocol: drop leaky predictors and refit, quantifying the apparent gain (the Sapelo 36.1% signature).
  - `ucst_ccif.models` — `M2aAgent` (M1 + exogenous agent-state feedback, Eq.2) and `m3_counterfactual` (military / restoration / DAC scenario engine, Eq.3).

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

## Streamlit MVP

```bash
streamlit run app/streamlit_app.py
```

Workspaces (v0.3.0, reorganized): **① Upload & Dictionary** — the four ledgers
(activity / flux / stock / intervention) with CSV templates that carry `#` comment
lines (full names + units), per-ledger column dictionaries, and area input;
**② Audit Report** — runs the S1–S7 pipeline and shows the 8 artifacts (verified
emission & removal intervals, ε_C residual, scale residual, leakage RYG flag +
flagged predictors, attribution decomposition, uncertainty budget, certificate)
plus a PDF evidence pack; **③ Benchmarks** — official reference data (CEADs
Guangdong, Global Carbon Budget, HK EPD, CH₄ kernels, CCER mangrove screening)
and an NGFS stress lens. The old manual Scope 1–3 / Biogenic / standalone
Leakage / PDF tabs were removed: the four-ledger upload already covers them
(Scope 1–3 via the activity ledger in S1, biogenic flux via the flux ledger in
S2, leakage in S6, PDF export post-audit).

## Persistence (multi-user)

The app runs with no database. Point it at PostgreSQL and it becomes
multi-tenant: uploads become immutable checksum-addressed *loads*, audits become
*runs* that cite the loads they consumed, and the emission factors live in a
versioned table instead of only in code.

```bash
pip install -e ".[app]"
export OCIP_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/ocip?sslmode=require"
python -m ucst_ccif.store --selftest --url "$OCIP_DATABASE_URL"   # round-trips, then cleans up
streamlit run app/streamlit_app.py
```

Schema, roles, secrets, sign-in and the current limitations are documented in
[`docs/POSTGRES.md`](docs/POSTGRES.md). `sql/schema.sql` is generated from
`ucst_ccif/store.py` (`python -m ucst_ccif.store --ddl`), so the two cannot
drift.

### Running it for other people

Two deployments from one repository:

- **Public sandbox** — `OCIP_DEMO_MODE=1`. Sample data is preloaded so a
  visitor reaches a certificate without owning data, and a configured database
  is ignored: nothing is written.
- **Invited pilot** — `[auth]` plus a Postgres URL. Each account maps to an
  organisation; uploads stay disabled until the data notice is acknowledged;
  tab 6 stores feedback.

The pilot also writes a step-level `event` row (`app_open`, `consent_accepted`,
`sample_loaded`, `upload_ok`, `upload_rejected`, `audit_run`, `pdf_export`,
`feedback_view`) so you can see where a tester stopped. It holds no IP, no
user agent and no typed text, and the sandbox writes none of it. Read the funnel
with `Store.funnel(org_id=...)` or the third query in
[`docs/LAUNCH.md`](docs/LAUNCH.md).

Step-by-step for Neon, Streamlit Cloud, Google sign-in, the data notice and the
feedback loop: [`docs/LAUNCH.md`](docs/LAUNCH.md). Notice template:
[`docs/DATA_NOTICE.md`](docs/DATA_NOTICE.md).

## How the audit works (S1–S7 → 8 artifacts)

Four ledgers in → a 7-step falsification pipeline → eight audited outputs plus a certificate.

```mermaid
flowchart TB
    classDef in fill:#e8f1f8,stroke:#2f6f9f,color:#123f5f;
    classDef step fill:#ffffff,stroke:#5c6b7a,color:#2c3e50;
    classDef out fill:#eaf6ec,stroke:#3a7d44,color:#1d4a26;

    subgraph LEDG["📥 四账上传（工作区 1 · Upload & Dictionary）"]
        A["活动账 Activity<br/>scope · category · activity_key · quantity"]
        F["通量账 Flux<br/>date · NEE_daily_total"]
        S["碳库账 Stock<br/>area_ha · removal_tco2e"]
        I["干预账 Intervention<br/>scenario · baseline · intervention"]
    end

    subgraph PIPE["⚙️ 7 步审计流水线 run_audit()"]
        S1["S1 边界簿记<br/>活动 × 排放因子（Eq.8–10）"]
        S2["S2 采集因子<br/>NEE = GPP − ER（Eq.6）"]
        S3["S3 守恒核销<br/>ε_C = 独立观测 − 企业声称（Eq.1）"]
        S4["S4 尺度核销<br/>跨尺度质量守恒（Eq.4–5）"]
        S5["S5 归因额外性<br/>主动触发 F_a vs 被动响应 F_p（Eq.2–3）"]
        S6["S6 泄漏审计<br/>三步：代数派生 → 泄漏版重拟合 → 去泄漏重拟合（Eq.7）"]
        S7["S7 不确定性<br/>Monte Carlo · 90% CI"]
    end

    subgraph OUT["📤 8 件输出 + 审计证书"]
        O1["① 边界清单"] O2["② 排放区间"] O3["③ 移除区间"] O4["④ 残差 ε_C"]
        O5["⑤ 尺度残差"] O6["⑥ 泄漏 RYG 旗标"] O7["⑦ 归因分解"] O8["⑧ 不确定性预算"]
        C["🏅 证书：PASS / REVIEW / FAIL / INCOMPLETE"]
    end

    A & F & S & I --> S1
    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    S7 --> O1 & O2 & O3 & O4 & O5 & O6 & O7 & O8
    O1 & O2 & O3 & O4 & O5 & O6 & O7 & O8 --> C

    class A,F,S,I in
    class S1,S2,S3,S4,S5,S6,S7 step
    class O1,O2,O3,O4,O5,O6,O7,O8,C out
```

**Worked example** — a company books 420 tCO₂e removed but claims 600: S3 computes
ε_C = independent observation − claimed = 420 − 600 = **−180 t** ⇒ certificate **FAIL — over-claim detected**.
Negative ε_C always means the books claim more than the independent record supports.

## Deploy it publicly (free)

The live public trial above already runs on Streamlit Community Cloud. To redeploy
or build your own:

1. **Streamlit Community Cloud** (easiest, free):
   - Go to <https://share.streamlit.io> → **Sign in with GitHub**
   - **Deploy an app** → pick `liulinda185-spec/carbon-falcon-ocip`
   - Main file: `ucst_ccif_pkg/app/streamlit_app.py` → **Deploy**
   - Paste the Secrets TOML (see [`docs/LAUNCH.md`](docs/LAUNCH.md)) — a public
     trial uses `[ocip].telemetry_only = true` and stores nothing of the visitor's.
2. **Your own server** (most control): install `.[app]`, then
   `streamlit run app/streamlit_app.py --server.port 80`.

## Tests

```bash
pytest tests/ -v
```

118 tests pass, including the attribution, audit-pipeline, leakage-refit,
event-tracker, tenant isolation, and sample-verdict suites.

## Zenodo DOI

To mint a DOI for this release (v0.3.0):
1. Tag and push: `git tag v0.3.0 && git push origin v0.3.0`
2. Go to [zenodo.org](https://zenodo.org), sign in with GitHub.
3. Enable the `liulinda185-spec/Carbon-Falcon` repository in Zenodo (one-time grant).
4. Publish a new GitHub release for tag `v0.3.0` — Zenodo archives it and mints the DOI.
5. Backfill the DOI into `pyproject.toml` and this README.

## Citation

Liu, Y. & Cui, W. (2026). *Integrating Ecological Carbon Fluxes Across Scales: A Conservation-Constrained, Falsification-Based Modelling Framework based on Unified Complex System Theory (UCST)*. Ecological Modelling.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Part of the UCST-CCIF Open Carbon Platform (OCIP) project, GBA-first.
