# PostgreSQL for the multi-user OCIP platform

The Streamlit app started life with no database: four CSVs in `st.session_state`,
an audit, a PDF. That is still how it behaves when nothing is configured. This
document describes the persistent layer that turns it into a multi-tenant
platform, and the exact steps to switch it on.

Wire-up lives in two places:

| Where | What it does |
|---|---|
| `ucst_ccif/store.py` | schema + all SQL (SQLAlchemy Core, no ORM) |
| `app/streamlit_app.py` | sidebar status, upload hook, audit hook, tab 6 |

---

## 1. What the database holds

```
org ──< site ──< ledger_load ──< activity_row / flux_row / stock_row / intervention_row
         │           │
         │           └──< audit_run  (loads JSON: which four loads produced it)
         ├──< feedback              (free text + rating; optional run_id)
         └──< event                 (verb + small fixed detail dict; pilot only)
factor_version                     (global reference data, not tenant-scoped)
```

- **`ledger_load`** — one row per uploaded file: SHA-256, column list, row count,
  who loaded it, when. Re-uploading identical bytes returns the *same* `load_id`,
  so a certificate that cites a load always cites the same rows. Corrections
  arrive as a **new** load; the old one is never rewritten.
- **`audit_run`** — certificate status, the headline figures, the full report
  JSON (artifacts + stage log + data gaps), and the load ids it consumed.
  That is the audit trail: certificate → run → loads → file checksums.
- **`feedback`** — free text, a 1–5 rating and an optional reply address from
  whoever tested the platform, scoped to org/site and optionally pointing at the
  run they were looking at. Read it with `Store.feedback(org_id=...)`; there is
  no triage UI.
- **`event`** — one row per step of the pilot funnel: `verb` (`app_open`,
  `consent_accepted`, `sample_loaded`, `upload_ok`, `upload_rejected`,
  `audit_run`, `pdf_export`, `feedback_view`), the org/site, the email, a
  timestamp, and a small fixed `detail` dict (`{"ledger": "activity", "rows":
  365}`). No IP address, no user agent, no free text. Written **only** when a
  real database is linked: demo mode returns no store, so the public sandbox
  records nothing. Read it with `Store.events(org_id=...)` and
  `Store.funnel(org_id=...)`; `digest()` counts them per org.
- **`factor_version`** — the emission factors from
  `ucst_ccif/emission_factors.py`, keyed by `(factor_id, version)`. A new MEE
  vintage is a new version row, not an edit.
- Every tenant-owned table carries `org_id`; the four row tables carry it too,
  so a future row-level-security policy can scope them without a join.

Nothing from tab 4 (model competition) is stored, and the PDF is generated per
request from the stored report.

---

## 2. Provision a database

Any Postgres 13+ works. Three common choices:

**Neon** (free tier, scales to zero)

1. Create a project → copy the connection string.
2. Use the **direct** endpoint (no `-pooler`) for a long-lived Streamlit process,
   and keep `sslmode=require`.
3. Cold starts after idle can take a second; the engine uses `pool_pre_ping`, so
   the first query after a nap reconnects instead of erroring.

**Supabase** — Project → Settings → Database → connection string, session mode,
port 5432.

**Your own server**

```bash
createdb ocip
```

---

## 3. Apply the schema

Two options, same result:

```bash
# A. let the app do it — Store.ensure_schema() runs on first boot, idempotent
# B. run the generated DDL yourself (this file is generated from the same metadata)
psql "postgresql://USER:PASS@HOST:5432/ocip" -f sql/schema.sql
```

`sql/schema.sql` is generated, never hand-edited:

```bash
python -m ucst_ccif.store --ddl > sql/schema.sql
```

Note the two URL forms — `psql` wants libpq, SQLAlchemy wants the driver tag:

```
postgresql://user:pass@host:5432/ocip?sslmode=require           # psql / libpq
postgresql+psycopg://user:pass@host:5432/ocip?sslmode=require   # the app
```

---

## 4. Roles

Run the app as a role that can write, and let analysts read from a separate
role. Do not run the app as the database owner.

```sql
create role ocip_app login password 'REPLACE_ME';
grant connect on database ocip to ocip_app;
grant usage on schema public to ocip_app;
grant select, insert, update, delete on all tables in schema public to ocip_app;

create role ocip_read login password 'REPLACE_ME_TOO';
grant connect on database ocip to ocip_read;
grant usage on schema public to ocip_read;
grant select on all tables in schema public to ocip_read;
```

There are no sequences to grant: ids are UUIDs generated in Python, which also
keeps the schema portable to SQLite for local development.

---

## 5. Secrets

Copy `secrets.toml.example` to `.streamlit/secrets.toml` and fill it in. On
Streamlit Community Cloud, paste the same TOML into the app's **Secrets** panel.

```toml
[postgres]
url = "postgresql+psycopg://ocip_app:PASS@HOST:5432/ocip?sslmode=require"

[ocip]
default_org  = "cityu"
default_site = "GBA-DEMO-01"
dev_user     = "liulinda@cityu"

[ocip.orgs]
"liulinda@cityu.edu.hk" = "cityu"
```

`.streamlit/` is git-ignored, so the real file cannot be committed by accident.

For local experiments, `OCIP_DATABASE_URL` in the environment overrides the
secret — that is how the test suite points the app at a temporary SQLite file.

---

## 6. Identity and tenancy

- **With `[auth]` configured**: the app shows a sign-in gate (top of
  `streamlit_app.py`) and does not render any tab until `st.user.is_logged_in`
  is true. `st.login()` redirects to your OIDC provider; `[ocip.orgs]` maps the
  returned email to a tenant, and unmatched users fall back to `default_org`.
- **Without `[auth]`**: everyone who opens the app is `dev_user` in
  `default_org`. That is fine on a laptop, and wrong on a public URL. The
  sidebar says which mode you are in; take it seriously before sharing a link.
- **With `[auth]` and an `[ocip.orgs]` map**: an account that is not listed is
  stopped at an invite-only screen rather than joining `default_org`. The rule
  lives in `ucst_ccif/tenancy.py` (`resolve_org`) so it is unit-tested;
  `allow_unknown = true` opts back into open registration.
- **Demo mode** (`OCIP_DEMO_MODE=1`, or `demo = true` under `[ocip]`): the app
  preloads the Guangzhou 2023 sample, and a configured database is deliberately
  ignored — the sidebar says *demo sandbox*, and nothing is written. Use this
  for the public link; use `[auth]` + a database for the invited pilot.
- **Consent**: when a database is linked, the four uploaders stay disabled until
  the data-notice checkbox in tab 1 is ticked. Nothing is persisted before that.

Minimal Google OIDC configuration:

```toml
[auth]
redirect_uri = "https://YOUR-APP.streamlit.app/oauth2callback"
cookie_secret = "a long random string"
client_id = "....apps.googleusercontent.com"
client_secret = "...."
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

For local development the redirect URI is
`http://localhost:8501/oauth2callback`, and it must be registered with the
provider as well. Streamlit's auth extra (`authlib`) is already in
`requirements.txt`.

---

## 7. Verify before trusting it

The store ships with a self-test that round-trips a real database and then
removes every row it created:

```bash
python -m ucst_ccif.store --selftest --url "postgresql+psycopg://ocip_app:PASS@HOST:5432/ocip?sslmode=require"
```

Expected: `connected: postgresql — PostgreSQL 16.x` (17.x on a newer Neon project
— both fine), then
`idempotency: ok`, `round-trip: ok`, `audit round-trip: ok`,
`feedback round-trip: ok`, `event round-trip: ok`, `cleanup: ok`.
It also seeds the factor library (global rows, intentionally left behind).

The same check runs against SQLite, which is what the automated tests use:

```bash
python -m pytest tests/test_store.py tests/test_app_smoke.py -q
```

**Honest status:** this layer was developed and tested against SQLite on the
author's machine; the Postgres path was verified by compiling the exact DDL and
statements with the Postgres dialect, not by executing them on a server. Run
the self-test above against your instance before the first real upload — it
takes seconds and exercises the same code paths the app uses.

---

## 8. Behaviour you can rely on

| Situation | What happens |
|---|---|
| Same file uploaded twice | same `load_id`, `deduplicated=True`, no new rows |
| Two sessions upload the same file at once | one wins the unique constraint, the other adopts its load |
| Edited file re-uploaded | new `load_id`; earlier runs keep pointing at the earlier load |
| Missing ledger | audit reports a data gap; nothing is estimated |
| Database unreachable | app still runs, sidebar says session-only, nothing is written |
| Audit computed but insert fails | warning shown; prior runs untouched |
| Demo mode with a database configured | database ignored, nothing written |

---

## 9. What is not done yet

Stated plainly so it is not mistaken for finished:

1. **Row-level security is not wired.** Every table has `org_id`, but the app
   does not `SET LOCAL ocip.org_id` inside its transactions, so enabling a
   policy today would block the app's own queries. To enable RLS, add the GUC
   per transaction in `Store`, then `enable row level security` + policies.
2. **No migration tool.** Schema v1 is created idempotently; later changes need
   explicit `ALTER` scripts (or introduce Alembic). No version table is
   recorded beyond the `SCHEMA_VERSION` constant.
3. **No deletion or retention policy.** Ledger rows are append-only by design;
   deleting a site cascades through its loads and runs, but there is no UI for
   it and no archival job.
4. **Org-wide visibility.** Any user mapped to an org sees every site in that
   org. Per-site permissions would need a membership table and a filter in
   `audit_history` / `loads`.
5. **The PDF is not archived.** It is regenerated on demand from the stored
   report, which is usually what you want — but a byte-identical evidence pack
   would need object storage.
6. **Concurrent-write handling is defensive, not load-tested.** The savepoint
   path exists for the duplicate-upload race; it has not been exercised under
   real concurrency.
7. **Feedback has no triage UI.** It is stored and exportable
   (`Store.feedback()`), but nothing summarises it, and there is no notification
   when it arrives — that has to be a habit, not a feature, for now.
8. **No alerting.** `python -m ucst_ccif.store --digest` is a pull: one row per
   org with loads, runs, feedback and last activity. Nothing emails you when a
   firm uploads, and the public sandbox writes nothing at all, so it produces no
   usage data by design.
