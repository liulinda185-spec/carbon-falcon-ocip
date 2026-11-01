"""Tests for the continuum model: mass balance, units, basic runs."""
import numpy as np
from ucst_ccif import CarbonContinuumModel, ParameterSet


def _forcing(T=60):
    doy = np.arange(T)
    gpp = np.clip(3.5 + 2.5 * np.sin(2*np.pi*(doy-105)/365.25), 0.2, 7.0)
    T_air = 18.0 + 12.0 * np.sin(2*np.pi*(doy-200)/365.25)
    swc = np.full(T, 0.55)
    rain = np.zeros(T)
    return gpp, T_air, swc, rain


def test_runs_and_returns_state():
    p = ParameterSet()
    m = CarbonContinuumModel(p)
    gpp, T, swc, rain = _forcing()
    s = m.run(gpp, T, swc, rain)
    assert s.nee.shape == (60,)
    assert s.total_stock[-1] > 0


def test_mass_balance_residual_small():
    p = ParameterSet()
    m = CarbonContinuumModel(p)
    gpp, T, swc, rain = _forcing(120)
    s = m.run(gpp, T, swc, rain)
    # eps_C should be small relative to NEE magnitude
    assert np.mean(np.abs(s.eps_C)) < 0.2


def test_no_negative_stocks():
    p = ParameterSet()
    m = CarbonContinuumModel(p)
    gpp, T, swc, rain = _forcing(120)
    s = m.run(gpp, T, swc, rain)
    for k, v in s.stocks.items():
        assert np.all(v >= 0), f"{k} has negative stock"
