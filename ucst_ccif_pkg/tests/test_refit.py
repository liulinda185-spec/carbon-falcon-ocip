"""Tests for leakage step 3: leakage-free refit."""

import numpy as np
import pandas as pd
import pytest

from ucst_ccif.leakage import refit_without_leakage, RefitReport


def _leaky_df(n=200, seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-01", periods=n, freq="D")
    wind = rng.normal(4, 1.5, n)
    noise = rng.normal(0, 0.4, n)
    nee = 0.8 * wind + 0.3 * np.sin(2 * np.pi * np.arange(n) / 30.0) + noise
    # near-deterministic leak: a column that almost *is* the target
    leaked = 0.9 * nee + rng.normal(0, 0.06, n)
    return pd.DataFrame({
        "date": dates,
        "NEE_daily_total": nee,
        "nee_balance": leaked,       # name matches LEAKY_PATTERNS
        "wind_speed_mean": wind,
    })


class TestRefitWithoutLeakage:
    def test_leaky_model_looks_better(self):
        df = _leaky_df()
        rep = refit_without_leakage(
            df, "NEE_daily_total",
            ["nee_balance", "wind_speed_mean"])
        assert isinstance(rep, RefitReport)
        assert rep.leaky_rmse < rep.clean_rmse
        # the leaky predictor produces an apparent improvement of >50%
        assert rep.apparent_gain_pct > 50.0
        assert rep.leaky_predictors == ["nee_balance"]
        assert rep.clean_predictors == ["wind_speed_mean"]
        assert rep.n_samples >= 150

    def test_refit_uses_exo_only_override(self):
        df = _leaky_df()
        rep = refit_without_leakage(
            df, "NEE_daily_total",
            ["nee_balance", "wind_speed_mean"],
            exo_only=["wind_speed_mean", "nee_balance"])
        # user forced to keep the leaky column: clean == leaky model
        assert rep.clean_predictors == ["wind_speed_mean", "nee_balance"]
        assert rep.apparent_gain_pct == pytest.approx(0.0, abs=1e-6)

    def test_no_exogenous_predictor_returns_nan_report(self):
        df = _leaky_df()
        rep = refit_without_leakage(df, "NEE_daily_total", ["nee_balance"])
        assert rep.clean_predictors == []
        assert np.isnan(rep.clean_rmse)

    def test_too_few_rows_raises(self):
        df = _leaky_df(n=12)
        with pytest.raises(ValueError):
            refit_without_leakage(df, "NEE_daily_total",
                                  ["nee_balance", "wind_speed_mean"])
