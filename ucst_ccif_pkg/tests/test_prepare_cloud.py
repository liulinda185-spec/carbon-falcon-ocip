"""The deploy helper must not mangle a Neon URL — this is the usual first failure."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from prepare_cloud import normalize_url, secrets_block  # noqa: E402


def test_neon_scheme_gains_the_psycopg_driver():
    out = normalize_url("postgresql://u:p@ep-x.ap-southeast-1.aws.neon.tech/db")
    assert out.startswith("postgresql+psycopg://")
    assert "?sslmode=require" not in out  # nothing invented


def test_short_scheme_and_quotes_are_handled():
    out = normalize_url('"postgres://u:p@h:5432/db?sslmode=require"')
    assert out == "postgresql+psycopg://u:p@h:5432/db?sslmode=require"


def test_normalised_url_is_untouched():
    url = "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_url(url) == url


def test_public_secrets_never_ask_for_sign_in():
    block = secrets_block("postgresql+psycopg://u:p@h/db", "public")
    assert "telemetry_only  = true" in block
    assert "[auth]" not in block
    assert "[ocip.orgs]" not in block


def test_pilot_secrets_carry_auth_and_the_mapping():
    block = secrets_block("postgresql+psycopg://u:p@h/db", "pilot")
    assert "[auth]" in block
    assert "[ocip.orgs]" in block
    assert "telemetry_only" not in block
