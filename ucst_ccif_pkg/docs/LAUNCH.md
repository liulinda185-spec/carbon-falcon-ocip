# Launching the OCIP community trial

Two deployments from one repository. Keep them apart — that is the whole point.

| | Public sandbox | Invited pilot |
|---|---|---|
| Secret `[ocip] demo = true` | yes | no |
| Database | none | Neon Postgres |
| Sign-in | none | Google OIDC |
| Data written | nothing, ever | per organisation |
| Who gets the link | anyone you announce to | firms you invite |

The sandbox exists so strangers can judge the tool without handing you data,
and so their clicks can never land in the database you intend to analyse.

---

## 1 · Neon database (~10 min)

1. Sign up at neon.tech, create a project. Pick the region closest to Hong
   Kong — AWS **ap-southeast-1 (Singapore)**.
2. Neon creates a database (usually named `neondb`) and gives you a connection
   string ending in `?sslmode=require`.
3. Convert it to the form the app wants — one substitution:

   ```
   postgresql://USER:PASS@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   postgresql+psycopg://USER:PASS@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

4. Verify before trusting it — this creates the schema, round-trips a load, an
   audit and a feedback row, then deletes everything it wrote:

   ```bash
   python -m ucst_ccif.store --selftest --url "postgresql+psycopg://..."
   ```

   Expect `connected: postgresql — PostgreSQL 16.x` (17.x on a newer Neon project;
   either is fine), then `idempotency: ok`,
   `round-trip: ok`, `audit round-trip: ok`, `feedback round-trip: ok`,
   `cleanup: ok`. Only the 28 factor rows stay behind, on purpose.

5. Optional but worth it: create a read-only role for analysts
   (`sql/schema.sql` and `docs/POSTGRES.md` §4 have the exact grants).

Neon's free tier suspends an idle database; the first query after a nap takes
a second or two. The engine uses `pool_pre_ping`, so it reconnects instead of
erroring.

---

## 2 · Streamlit Community Cloud (~15 min)

1. Go to share.streamlit.io, sign in with GitHub, grant access to
   `liulinda185-spec/carbon-falcon-ocip`.
2. **New app** → repository `liulinda185-spec/carbon-falcon-ocip`, branch
   `main`, main file path `ucst_ccif_pkg/app/streamlit_app.py`.
3. Under **Advanced settings**, choose Python 3.12 if offered (3.13 also works
   — the code is pure Python with no compiled dependencies).
4. Dependencies come from the **repository-root `requirements.txt`**, which now
   carries `sqlalchemy`, `psycopg[binary]` and `authlib`. The package folder has
   its own copy for local installs; if you add a dependency, add it to both.
5. Optional but recommended: let the helper turn Neon's URL into a working one,
   verify it, and print the TOML for you —

   ```bash
   python tools/prepare_cloud.py --url "postgresql://user:pass@host/db?sslmode=require" --mode public
   ```

   It rewrites the scheme to `postgresql+psycopg://`, runs the full selftest
   against the real database (`event round-trip: ok` and `cleanup: ok` included),
   and only then prints the Secrets block. `--mode pilot` prints the version with
   `[auth]` and `[ocip.orgs]`. If the check fails, do not deploy.
6. Paste the secrets. Sandbox app:

   ```toml
   [ocip]
   demo = true
   default_org  = "demo"
   default_site = "GBA-DEMO-01"
   dev_user     = "visitor@demo"
   feedback_url = "https://forms.gle/…"    # optional, shown when no DB is linked
   ```

   Pilot app — same repository, different Secrets, note `demo` is absent:

   ```toml
   [postgres]
   url = "postgresql+psycopg://ocip_app:PASS@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

   [ocip]
   default_org  = "cityu"
   default_site = "GBA-DEMO-01"
   dev_user     = "liulinda@cityu"
   feedback_url = "https://forms.gle/…"

   [ocip.orgs]
   "someone@company.com.hk" = "company-a"

   [auth]
   redirect_uri = "https://YOUR-PILOT-APP.streamlit.app/oauth2callback"
   cookie_secret = "a long random string"
   client_id = "….apps.googleusercontent.com"
   client_secret = "…"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

   **Public trial app — one link for everyone, funnel counted, files never
   stored.** This is the configuration for "share it widely and still see where
   people stop". No `[auth]`, no `[ocip.orgs]`, and a *separate* database so a
   public app can never touch pilot data:

   ```toml
   [postgres]
   url = "postgresql+psycopg://ocip_public:PASS@ep-yyy.ap-southeast-1.aws.neon.tech/ocip_public?sslmode=require"

   [ocip]
   telemetry_only = true
   default_site   = "PUBLIC-WEB"
   feedback_url   = "https://forms.gle/…"
   ```

   Behaviour in that mode: the sample dataset is preloaded, uploaded files stay
   in the visitor's browser (never written, never shown to anyone else), no
   email / IP / user agent is recorded, and only the eight step events land in
   `event` under org `public`. Consent is not asked because nothing of theirs is
   stored; the notice shown in tab 1 changes to match (`_data_notice()`).

7. Deploy. First boot creates the schema and seeds the 28 factor rows.

Free-tier apps sleep when idle; the first visitor after a quiet spell waits
~30 seconds. That is a real cost for a launch post — publish when you are
awake to answer the first questions.

---

## 3 · Google sign-in (~15 min)

1. console.cloud.google.com → **New project** (`ocip-pilot`).
2. **APIs & Services → OAuth consent screen**: External. While testing, keep it
   in *Testing* and add your own address plus each pilot contact as a test user;
   publish it only when you are ready for strangers.
3. **Credentials → Create credentials → OAuth client ID → Web application**.
   Authorised redirect URIs — both, exactly:

   ```
   https://YOUR-PILOT-APP.streamlit.app/oauth2callback
   http://localhost:8501/oauth2callback
   ```

   No trailing slash. A mismatch surfaces as `redirect_uri_mismatch` after the
   user has already signed in — the ugliest failure mode to debug in front of a
   client.
4. Copy client id and secret into `[auth]`. Generate `cookie_secret` with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

With `[auth]` present the app stops at a sign-in screen; without it every
visitor inherits `dev_user`, which is why the sandbox app must **not** carry an
`[auth]` block and the pilot app **must**.

**`[ocip.orgs]` is not optional.** The moment someone can sign in, the question
becomes *who is allowed to*. With the map present, an account that is not listed
is stopped at a "This pilot is invite-only" screen; without it, any Google
account that signs in lands in `default_org` and can read that organisation's
ledgers. So: add each firm's address to the map, reboot the app from
*Manage app → Reboot*, then send the link. To add a firm later, add one line and
reboot — nobody has to re-deploy. If you ever genuinely want open registration,
set `allow_unknown = true` and accept that it is a public deployment.

---

## 4 · The legal line (~1 h, plus institutional review)

Start from `docs/DATA_NOTICE.md` — it is a template with the bracketed fields
marked. Three decisions only you can make:

- **Operator**: your name and department, or a lab/project name that outlives
  your degree.
- **Research use, (a) or (b)**: audit-for-the-client only, or aggregate findings
  may appear in publications. If (b), the CityU ethics approval must exist
  before the first external upload, and the notice must cite its reference.
- **Retention and deletion contact**: who answers a deletion request, and
  within how many working days.

Then put the same text in three places so nobody can claim they never saw it:
the in-app expander (it reads `_DATA_NOTICE` in `streamlit_app.py`, so edit it
there too), the repo (`docs/DATA_NOTICE.md`), and the announcement post itself.

Hong Kong PDPO (Cap. 486) governs the email addresses you hold; it is the
reason the sign-in address is the only personal data worth collecting, and why
the app asks you not to upload personal data at all.

---

## 5 · A feedback channel you will actually read (~10 min)

Three options, in increasing effort:

1. **Form only** — create a Google Form / Tally, put the URL in
   `[ocip].feedback_url`. The app shows it when no database is linked. Zero
   code, works today.
2. **Form + in-app** — with a database, tab 6 stores free text, rating, and an
   optional reply address. Export with:

   ```python
   from ucst_ccif.store import Store
   s = Store("postgresql+psycopg://...")
   s.feedback(org_id="cityu").to_csv("feedback.csv", index=False)
   ```

3. **In-app only** — a dedicated inbox address monitored weekly; set a
   recurring 15-minute calendar block, or the loop dies in a fortnight.

Whatever you pick, name one person. "The team will look at it" is how feedback
graveyards start.

### Where the data actually lives — three doors

There is no admin screen, by design: the database is the record, and you read it
with tools that cannot accidentally expose one tenant to another.

1. **Neon console (the authoritative copy).** Project → **SQL Editor**. Paste and
   run:

   ```sql
   select org_id, count(*) as loads, max(loaded_at) as last_load
   from ledger_load group by org_id order by last_load desc;

   select org_id, rating, left(comment, 60) as comment, created_at
   from feedback order by created_at desc limit 20;

   -- the funnel: which steps each tester actually reached
   select org_id, verb, count(*) as n, max(at) as last_at
   from event group by 1, 2 order by 1, 3 desc;
   ```

   The third query is the one rows cannot answer: it shows people who opened the
   app and stopped, or uploaded and never ran the audit — the middle of the
   funnel. `event` is written only when a database is linked; the public sandbox
   records nothing at all.

   Neon also has a *Tables* view if you prefer clicking to typing. This is your
   account only — no tester sees it.

2. **Your laptop, via the CLI.** Same data, shaped for reading:

   ```bash
   python -m ucst_ccif.store --digest --url "$PILOT_URL"
   ```

   ```
      org_id  loads  runs  feedback  events  avg_rating              last_activity
   company-c      0     0         1       4         2.0  2026-11-05 09:11:27
   company-b      1     0         1       9         3.0  2026-11-05 09:11:27
   company-a      1     1         0      12         NaN  2026-11-05 09:11:27

   loaded a ledger but never ran an audit: company-b
   no feedback yet from: company-a
   ```

   Keep the exported CSV on your laptop: it contains tester email addresses, so
   it must never be committed.

3. **Streamlit Cloud logs (crashes and restarts).** Your app → *Manage app →
   Logs*. Check after every deploy and after every announcement wave; this is
   where a `KeyError` shows up as a trace, not as silence.

Read the digest as a funnel, not a scoreboard. `loads` without `runs` is the most
valuable signal you have: someone got far enough to upload and then stopped —
that is a specific bug to ask about, not a vague opinion. `feedback = 0` from an
active org means your ask was too weak or the form too far away. Duplicate loads
for the same org (visible in `Store.loads()` as repeated `sha256` prefixes) means
they did not believe the first upload took.

Limits worth writing down:

- **The sandbox is invisible by design.** It writes nothing, so there is no
  sandbox funnel to analyse — only the Cloud logs (Manage app → Logs), which
  show errors and restarts, not who did what. If you later want sandbox numbers,
  that is a deliberate new decision about collecting analytics, not a setting.
- **Nothing alerts you.** `--digest` is a pull; there is no email when a firm
  uploads. Until you build that, put a recurring 15-minute calendar block on it —
  a weekly digest nobody opens is worse than no digest.
- **Browser analytics are off** (`gatherUsageStats = false` in both
  `config.toml` files, which is also the honest choice for a data tool), so
  Streamlit's own view counts are not a substitute for the table above.

---

## 6 · Pre-flight checks before you announce

Run these in order; each one catches a different class of mistake.

```bash
# 1. schema + round-trip against the real database
python -m ucst_ccif.store --selftest --url "$PILOT_URL"

# 2. local run, demo mode — must show "demo sandbox", must not touch the DB
OCIP_DEMO_MODE=1 streamlit run app/streamlit_app.py

# 3. local run, pilot mode — must show "PostgreSQL — persisted"
OCIP_DATABASE_URL="$PILOT_URL" streamlit run app/streamlit_app.py
```

In the deployed apps:

- sandbox: open in a private window → sample data already loaded → **Run the
  audit** produces a certificate without uploading anything.
- pilot: sign in as yourself → sidebar shows your org → **Load sample dataset**
  → **Run the audit** → tab 6 counts 1 load and 1 run.
- pilot: sign in as an unmapped colleague → with `[ocip.orgs]` present they get
  the *invite-only* screen; without it they land in `default_org`. The first is
  what you want.
- settings page of the Cloud app → Secrets show the values you expect (never
  paste a connection string into the repo itself).

---

## 7 · Sharing it, in four stages

Do not announce a link you have not walked through yourself. Each stage unlocks
the next one, and each one changes what the next stage should say.

**Stage 1 — sandbox only.** Deploy the demo app (it needs nothing but the repo),
open it in a private window, run the sample audit, submit one piece of feedback
to yourself. Then send it to **one** person — a Sustainability Club colleague, a
friend in an ESG role. Ask them one question: *where did you stop and why?* You
are testing whether a stranger can reach a certificate without being taught.

**Stage 2 — the pilot, with three firms.** Now do Neon + Google + `[ocip.orgs]`
(§1–§3). Add three addresses you can actually phone. Never send the pilot link
before the map exists, or strangers become members of `default_org`.

**Stage 3 — the invitation, one firm at a time.** Short, specific, and honest
about what you want from them:

> Subject: a 10-minute check of a carbon-audit tool (no data leaves your side)
>
> I've built an open tool that recomputes a firm's carbon position from its own
> ledgers and shows every number back to a source or a formula. It keeps your
> uploads under your organisation only, and I can delete them on request.
>
> Could you try it with one real (or anonymised) activity ledger and tell me the
> first place it confused you? Two links: the demo has sample data and needs no
> sign-in — [sandbox link]; the working version takes your own files — [pilot
> link], sign in with this Google address and you'll be routed to your own space.
>
> If it is useful, I'd like to hear what your reporting actually needs. If it
> isn't, that answer is just as valuable.

**Stage 4 — public, once you have two real stories.** Then:

1. CityU Sustainability Club and your own network.
2. Two or three GBA chambers / green-finance groups where you already have a
   name attached.
3. One LinkedIn post with the certificate screenshot and the sentence that makes
   the tool unusual: *this number is traceable to a file with a SHA-256
   checksum, not to a spreadsheet someone edited.*
4. Zenodo DOI and the SSRN paper as the citable handles, so a sceptical reader
   can check the method before touching the app.

Post the **sandbox** link in public, never the pilot link. The pilot is a
relationship, not a URL.

Ask each tester for exactly one thing: upload one real dataset and tell you the
first place it confused them. One dataset from ten firms beats a hundred
curiosity clicks.

Keep the invitation honest about state: the Postgres path has been verified
against SQLite locally and, once you run step 1, against your own Neon
database — not against a fleet of concurrent users. Say so; the people worth
having will trust you more for it.
