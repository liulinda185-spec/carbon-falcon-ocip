"""Tests for the attribution / conservation-reconciliation layer (Eq.1-3)."""

import numpy as np
import pandas as pd
import pytest

from ucst_ccif.attribution import (
    conservation_reconcile,
    additionality_counterfactual,
    attribution_split,
    C_TO_CO2,
)


class TestConservationReconcile:
    def test_balanced_within_tolerance(self):
        rep = conservation_reconcile(
            emissions_tco2e=500.0,
            claimed_removals_tco2e=420.0,
            observed_removals_tco2e=425.0,   # within 5%
        )
        assert rep.status == "balanced"
        assert rep.residual_tco2e == pytest.approx(5.0)
        assert rep.net_claimed_tco2e == pytest.approx(80.0)

    def test_overclaim_detected(self):
        # company claims 600 t removal, observation supports only 420 t
        rep = conservation_reconcile(
            emissions_tco2e=500.0,
            claimed_removals_tco2e=600.0,
            observed_removals_tco2e=420.0,
        )
        assert rep.status == "over-claimed"
        assert rep.residual_tco2e == pytest.approx(-180.0)
        assert rep.net_claimed_tco2e == pytest.approx(-100.0)  # books a surplus

    def test_conservative_when_claim_below_observation(self):
        rep = conservation_reconcile(500.0, 300.0, 420.0)
        assert rep.status == "conservative"
        assert rep.residual_tco2e == pytest.approx(120.0)

    def test_strict_tolerance_flags_claim(self):
        rep = conservation_reconcile(500.0, 420.0, 400.0, tolerance_pct=1.0)
        assert rep.status == "over-claimed"  # 5% gap is beyond 1% tolerance


class TestAdditionalityCounterfactual:
    def test_extra_removal_is_intervention_minus_baseline(self):
        rep = additionality_counterfactual(300.0, 420.0)
        assert rep.extra_removal_tco2e == pytest.approx(120.0)
        assert rep.additionality_ratio == pytest.approx(120.0 / 420.0)
        assert rep.active_trigger_tco2e == pytest.approx(120.0)

    def test_no_additionality_when_unchanged(self):
        rep = additionality_counterfactual(420.0, 420.0)
        assert rep.extra_removal_tco2e == pytest.approx(0.0)
        assert rep.additionality_ratio == pytest.approx(0.0)

    def test_active_fraction_splits_trigger_and_passive(self):
        rep = additionality_counterfactual(300.0, 420.0, active_fraction=0.4)
        assert rep.active_trigger_tco2e == pytest.approx(120.0 * 0.4)
        assert rep.passive_response_tco2e == pytest.approx(120.0 * 0.6)


class TestAttributionSplit:
    def _make_df(self, seed=7):
        rng = np.random.default_rng(seed)
        n = 180
        temp = rng.normal(22, 3, n)
        wind = rng.normal(4, 1.5, n)
        agent = np.linspace(0, 1, n) + rng.normal(0, 0.05, n)
        nee = 0.3 * temp - 0.4 * wind + 1.2 * agent + rng.normal(0, 0.3, n)
        return pd.DataFrame({"temp": temp, "wind": wind,
                             "agent_state": agent, "NEE": nee})

    def test_agent_effect_identifiable(self):
        df = self._make_df()
        rep = attribution_split(df, "NEE", ["temp", "wind"], "agent_state")
        assert rep.env_r2 >= 0.0
        assert rep.agent_r2_gain > 0.05
        assert rep.agent_identifiable is True

    def test_no_agent_effect_when_irrelevant(self):
        rng = np.random.default_rng(1)
        n = 180
        temp = rng.normal(22, 3, n)
        noise_agent = rng.normal(0, 0.01, n)  # unrelated to NEE
        nee = 0.3 * temp + rng.normal(0, 0.5, n)
        df = pd.DataFrame({"temp": temp, "agent_state": noise_agent, "NEE": nee})
        rep = attribution_split(df, "NEE", ["temp"], "agent_state")
        assert rep.agent_identifiable is False
        assert rep.agent_r2_gain < 0.005

    def test_area_converts_to_tco2e(self):
        df = self._make_df()
        rep = attribution_split(df, "NEE", ["temp", "wind"], "agent_state",
                                area_ha=10.0)
        assert rep.agent_effect_tco2e is not None
        # sign follows the agent term (positive agent -> positive NEE -> source)
        assert rep.agent_effect_tco2e > 0.0


def test_conversion_constant():
    assert C_TO_CO2 == pytest.approx(44.0 / 12.0)
