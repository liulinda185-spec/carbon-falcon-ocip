"""Tests for the RothC-lite kernel: mass conservation, units, date inputs."""
import numpy as np
import pandas as pd
from ucst_ccif import run_rothc, run_rothc_dataframe


def _series(n=36, c_in=2.0, T=20.0, smd=30.0, tsd=100.0, cover=1.0):
    return dict(
        c_inputs=np.full(n, c_in), T=np.full(n, T),
        smd=np.full(n, smd), tsd=np.full(n, tsd),
        cover=cover,
    )


def test_mass_balance_exact():
    n = 36
    r = run_rothc(**_series(n))
    # per-step: inputs == dStock(active pools) + CO2 (IOM inert)
    stocks_before = np.zeros(n)
    stocks_before[0] = 0.0
    d_stock = np.diff([0.0] + [r.stocks["DPM"][i] + r.stocks["RPM"][i]
                               + r.stocks["BIO"][i] + r.stocks["HUM"][i]
                               for i in range(n)])
    budget = r.c_inputs - (d_stock + r.co2_flux)
    assert np.allclose(budget, 0.0, atol=1e-9), f"max residual {np.abs(budget).max():.2e}"


def test_no_inputs_pools_decrease_and_respire():
    n = 60
    init = {"DPM": 10.0, "RPM": 30.0, "BIO": 5.0, "HUM": 50.0}
    r = run_rothc(c_inputs=np.zeros(n), T=np.full(n, 20.0),
                  smd=np.full(n, 30.0), tsd=np.full(n, 100.0), init=init)
    for k in r.stocks:
        assert r.stocks[k][-1] <= r.stocks[k][0] + 1e-9, f"{k} grew without inputs"
    assert r.co2_flux.sum() > 0


def test_temperature_factor_monotonic():
    from ucst_ccif import temperature_factor
    cold = temperature_factor(5.0)
    warm = temperature_factor(30.0)
    assert warm > cold > 0


def test_dataframe_input_with_dates():
    n = 24
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="MS"),
        "c_inputs": np.full(n, 1.5),
        "T": np.full(n, 22.0),
        "smd": np.full(n, 25.0),
        "tsd": np.full(n, 100.0),
    })
    r = run_rothc_dataframe(df)
    assert r.dates is not None and len(r.dates) == n
    assert r.total_soc[-1] > 0


def test_clay_split_changes_bio_hum_ratio():
    r_low = run_rothc(**_series(n=120, c_in=2.0), clay_pct=5.0)
    r_high = run_rothc(**_series(n=120, c_in=2.0), clay_pct=60.0)
    bio_hum_low = r_low.stocks["BIO"][-1] / max(r_low.stocks["HUM"][-1], 1e-9)
    bio_hum_high = r_high.stocks["BIO"][-1] / max(r_high.stocks["HUM"][-1], 1e-9)
    # RothC x = 1.67*(1.85+1.60*exp(-0.0786*clay)) falls with clay, so
    # more clay -> proportionally MORE HUM relative to BIO (lower BIO:HUM)
    assert bio_hum_high < bio_hum_low
