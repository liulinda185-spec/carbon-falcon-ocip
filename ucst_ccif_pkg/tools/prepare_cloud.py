"""Prepare a Cloud deployment: normalise the URL, verify it, emit Secrets.

Neon hands you `postgresql://…`, but SQLAlchemy needs the driver tag
`postgresql+psycopg://…`. That single mismatch is the most common first-deploy
failure, so this script fixes it and then proves the database works before you
paste anything into the Cloud dashboard.

    python tools/prepare_cloud.py --url "postgresql://user:pass@host/db" --mode public
    python tools/prepare_cloud.py --url "…" --mode pilot
    python tools/prepare_cloud.py --url "…" --skip-check      # print TOML only

The printed TOML contains the password. It goes into the Streamlit Secrets
panel, never into the repository.
"""

from __future__ import annotations

import argparse
import sys

DRIVER_SCHEME = "postgresql+psycopg"


def normalize_url(raw: str) -> str:
    """`postgres://` and `postgresql://` -> `postgresql+psycopg://`.

    Surrounding quotes are stripped (Neon's console puts them around the string),
    and an already-normalised URL is returned unchanged.
    """
    text = (raw or "").strip().strip("'\"")
    if text.startswith(f"{DRIVER_SCHEME}://"):
        return text
    for scheme in ("postgres://", "postgresql://"):
        if text.startswith(scheme):
            return f"{DRIVER_SCHEME}://{text[len(scheme):]}"
    return text


def secrets_block(url: str, mode: str) -> str:
    """The exact TOML to paste into the app's Secrets panel."""
    if mode == "public":
        body = f"""[postgres]
url = "{url}"

[ocip]
telemetry_only  = true
default_site    = "PUBLIC-WEB"
feedback_url    = "https://forms.gle/REPLACE_ME"

[server]
maxUploadSize = 50
"""
        note = ("Public trial: sample data preloaded, visitor uploads never stored, "
                "anonymous step events only. Use a SEPARATE database from the pilot.")
    else:
        body = f"""[postgres]
url = "{url}"

[ocip]
default_org     = "cityu"
default_site    = "GBA-DEMO-01"
dev_user        = "liulinda@cityu"
feedback_url    = "https://forms.gle/REPLACE_ME"

[ocip.orgs]
"someone@company.com.hk" = "company-a"

[auth]
redirect_uri        = "https://YOUR-APP.streamlit.app/oauth2callback"
cookie_secret       = "REPLACE_WITH_A_LONG_RANDOM_STRING"
client_id           = "REPLACE_ME.apps.googleusercontent.com"
client_secret       = "REPLACE_ME"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
"""
        note = ("Pilot: real sign-in, real storage. Fill [ocip.orgs] with the exact "
                "addresses you invited; without that map, anyone who signs in is refused.")
    return ("--- paste this into the app's Secrets panel ---\n" + body
            + "\n# " + note + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/prepare_cloud.py")
    parser.add_argument("--url", required=True,
                        help="Neon / Postgres URL, quoted is fine")
    parser.add_argument("--mode", choices=("public", "pilot"), default="public")
    parser.add_argument("--skip-check", action="store_true",
                        help="print the TOML without touching the database")
    args = parser.parse_args(argv)

    url = normalize_url(args.url)
    print(f"driver: {url.split('://', 1)[0]}://")
    if not url.startswith(f"{DRIVER_SCHEME}://") and not url.startswith("sqlite"):
        print("WARNING: this does not look like a postgresql+psycopg URL", file=sys.stderr)
        return 2

    if not args.skip_check:
        from ucst_ccif.store import _selftest   # the same check the CLI runs

        code = _selftest(url)
        if code != 0:
            print("verification FAILED — do not deploy against this URL",
                  file=sys.stderr)
            return code

    print(secrets_block(url, args.mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
