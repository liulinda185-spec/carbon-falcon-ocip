"""Tests for M2a agent model and M3 counterfactual scenarios."""

import numpy as np
import pandas as pd
import pytest

from ucst_ccif.models import (
    M2aAgent, M1Conservation, compute_conservation_state,
    compute_agent_state, compare_m0_m1_m2a, m3_counterfactual,
    SCENARIO_PARAMS, model_competition,
)


def _make_2yr_df(seed=2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-01", periods=365 * 3, freq="D")  # 2019-2021
    doy = dates.dayofyear.values
    t = 2 * np.pi * doy / 365.25
    exo = rng.normal(0, 0.6, len(dates))
    disturbance = (rng.random(len(dates)) < 0.03).astype(float)
    nee = (1.0 + 1.5 * np.sin(t) + 0.5 * np.cos(2 * t)
           + 0.4 * exo + 0.5 * disturbance + rng.normal(0, 0.3, len(dates)))
    agent = np.linspace(0, 0.5, len(dates)) + rng.normal(0, 0.02, len(dates))
    return pd.DataFrame({
        "date": dates,
        "year": dates.year,
        "month": dates.month,
        "doy": doy,
        "NEE_daily_total": nee,
        "exo1": exo,
        "disturbance": disturbance,
        "agent_state": agent,
    })


class TestM2aAgent:
    def test_parameter_count(self):
        m1 = M1Conservation(["exo1"], "disturbance")
        m2 = M2aAgent(["exo1"], "disturbance", "agent_state")
        assert m2.n_params == m1.n_params + 2

    def test_predict_shape(self):
        df = _make_2yr_df()
        df = compute_conservation_state(df, ["exo1"])
        df = compute_agent_state(df, "agent_state")
        m2 = M2aAgent(["exo1"], "disturbance", "agent_state")
        params = np.zeros(m2.n_params)
        out = m2.predict(params, df)
        assert out.shape == (len(df),)
        assert np.all(np.isfinite(out))

    def test_compare_m0_m1_m2a_runs(self):
        df = _make_2yr_df()
        res = compare_m0_m1_m2a(
            df, "NEE_daily_total", ["exo1"], "agent_state",
            calib_end_year=2020)
        assert set(res.keys()) == {"M0", "M1", "M2a"}
        # M2a nested on M1: same params plus two agent terms
        assert res["M2a"].n_params == res["M1"].n_params + 2
        for r in res.values():
            assert np.isfinite(r.valid_rmse)


class TestM3Counterfactual:
    def test_restoration_extra_removal(self):
        out = m3_counterfactual(-0.382, scenario="restoration")
        assert out["delta_nee_gCm2_d"] == pytest.approx(
            SCENARIO_PARAMS["restoration"]["F_a"]
            + SCENARIO_PARAMS["restoration"]["F_p"])
        assert out["extra_removal_tco2e_ha_yr"] > 0.0
        assert "extra_removal_tco2e_yr" not in out  # no area given

    def test_military_is_net_emission_pressure(self):
        out = m3_counterfactual(-0.382, scenario="military")
        assert out["delta_nee_gCm2_d"] > 0.0
        assert out["extra_removal_tco2e_ha_yr"] < 0.0  # negative = extra emission

    def test_area_scales_to_total(self):
        out = m3_counterfactual(-0.382, scenario="restoration", area_ha=50.0)
        assert out["extra_removal_tco2e_yr"] == pytest.approx(
            out["extra_removal_tco2e_ha_yr"] * 50.0)

    def test_override_fa_fp(self):
        out = m3_counterfactual(-0.382, F_a=-0.5, F_p=-0.2)
        assert out["delta_nee_gCm2_d"] == pytest.approx(-0.7)
        assert out["scenario"] == "restoration"  # default label, overridden params

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            m3_counterfactual(-0.382, scenario="teleport")


class TestModelCompetition:
    """M0–M3 competition entry point used by the Streamlit Tab 4."""

    def test_runs_m0_m1_with_validation_frames(self):
        df = _make_2yr_df()
        out = model_competition(df, "NEE_daily_total", ["exo1"],
                                calib_end_year=2020)
        assert set(out["results"].keys()) == {"M0", "M1"}
        assert out["results"]["M1"].n_params == \
            out["results"]["M0"].n_params + 2
        assert "pred_M0" in out["valid"].columns
        assert "pred_M1" in out["valid"].columns
        assert "observed" in out["valid"].columns
        assert len(out["valid"]) == len(out["valid"]["pred_M0"])
        assert out["calib"]["year"].max() <= 2020
        assert out["valid"]["year"].min() > 2020

    def test_runs_m2a_when_agent_column_given(self):
        df = _make_2yr_df()
        out = model_competition(df, "NEE_daily_total", ["exo1"],
                                calib_end_year=2020, agent_col="agent_state")
        assert set(out["results"].keys()) == {"M0", "M1", "M2a"}
        assert "pred_M2a" in out["valid"].columns

    def test_auto_zero_disturbance_when_missing(self):
        df = _make_2yr_df().drop(columns=["disturbance"])
        out = model_competition(df, "NEE_daily_total", ["exo1"],
                                calib_end_year=2020)
        assert set(out["results"].keys()) == {"M0", "M1"}

    def test_runs_with_nan_exogenous(self):
        df = _make_2yr_df()
        df.loc[df.index[::50], "exo1"] = np.nan
        out = model_competition(df, "NEE_daily_total", ["exo1"],
                                calib_end_year=2020)
        assert "M0" in out["results"]
        assert out["valid"]["pred_M0"].notna().all()

    def test_runs_with_nan_agent_column(self):
        df = _make_2yr_df()
        df.loc[df.index[::40], "agent_state"] = np.nan
        out = model_competition(df, "NEE_daily_total", ["exo1"],
                                calib_end_year=2020, agent_col="agent_state")
        assert set(out["results"].keys()) == {"M0", "M1", "M2a"}
        assert out["valid"]["pred_M2a"].notna().all()

    def test_too_short_data_raises(self):
        df = _make_2yr_df().head(40)
        with pytest.raises(ValueError):
            model_competition(df, "NEE_daily_total", ["exo1"],
                              calib_end_year=2020)
