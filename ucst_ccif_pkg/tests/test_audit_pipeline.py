"""Tests for the S1..S7 OCIP audit pipeline (MVP v0.3)."""

import numpy as np
import pandas as pd
import pytest

from ucst_ccif.audit_pipeline import (
    run_audit, AuditReport, StageStatus, time_series_scale_audit,
)


def _activity_500t() -> pd.DataFrame:
    # electricity only: quantity x GD grid factor = 500 tCO2e exactly
    qty_kwh = 500.0 * 1000.0 / 0.4403
    return pd.DataFrame([
        {"scope": "2", "category": "electricity", "activity_key": "guangdong",
         "quantity": qty_kwh},
    ])


def _flux_365d(mean_nee_gCm2_d=-4.0, n=365, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    nee = mean_nee_gCm2_d + rng.normal(0, 1.2, n)
    wind = rng.normal(4, 1.5, n)
    return pd.DataFrame({"date": dates, "NEE_daily_total": nee,
                         "wind_speed_mean": wind})


def _stock_removal(tco2e: float, area_ha: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame([{"area_ha": area_ha, "removal_tco2e": tco2e}])


def _intervention() -> pd.DataFrame:
    return pd.DataFrame([
        {"scenario": "wetland_restoration", "baseline_removal_tco2e": 300.0,
         "intervention_removal_tco2e": 420.0},
    ])


class TestAuditPipeline:
    def test_full_audit_emission_verified(self):
        rep = run_audit(activity_df=_activity_500t())
        assert isinstance(rep, AuditReport)
        assert rep.emissions_tco2e is not None
        assert rep.emissions_tco2e == pytest.approx(500.0, rel=1e-6)
        assert rep.emissions_u95_tco2e == pytest.approx(50.0, rel=1e-6)
        assert rep.uncertainty_budget["emissions_u95_rel"] == pytest.approx(0.10)
        assert rep.certificate_status.startswith("INCOMPLETE")  # no flux ledger

    def test_missing_flux_is_a_reported_gap(self):
        rep = run_audit(activity_df=_activity_500t())
        assert any("flux ledger" in g for g in rep.data_gaps)

    def test_conservation_balanced(self):
        rep = run_audit(
            activity_df=_activity_500t(),
            stock_df=_stock_removal(420.0),
            claimed_removals_tco2e=420.0,
        )
        assert rep.residual_eC_tco2e == pytest.approx(0.0)
        assert rep.residual_eC_status == "balanced"
        assert rep.certificate_status.startswith("PASS")

    def test_overclaim_detected_and_fails_certificate(self):
        # company claims 600 t removal; independent observation supports 420 t
        rep = run_audit(
            activity_df=_activity_500t(),
            stock_df=_stock_removal(420.0),
            claimed_removals_tco2e=600.0,
        )
        assert rep.residual_eC_tco2e == pytest.approx(-180.0)
        assert rep.residual_eC_status == "over-claimed"
        assert rep.certificate_status.startswith("FAIL")

    def test_flux_based_removal_and_scale_reconciliation(self):
        area = 100.0
        # choose flux mean so integral = 420 tCO2e
        mean_nee = -420.0 / (365.0 * area * 1e4 * (44.0 / 12.0) / 1e6)
        flux = _flux_365d(mean_nee_gCm2_d=mean_nee)
        rep = run_audit(
            activity_df=_activity_500t(),
            flux_df=flux,
            stock_df=_stock_removal(420.0, area_ha=area),
            claimed_removals_tco2e=420.0,
            area_ha=area,
        )
        assert rep.removals_tco2e == pytest.approx(420.0, rel=0.05)
        assert rep.scale_residual_status in ("balanced", "flagged")
        assert rep.leakage_ryg in ("green", "grey")

    def test_intervention_additionality_recorded(self):
        rep = run_audit(
            activity_df=_activity_500t(),
            stock_df=_stock_removal(420.0),
            intervention_df=_intervention(),
            claimed_removals_tco2e=420.0,
        )
        assert rep.additionality["rows"][0]["extra_tco2e"] == pytest.approx(120.0)

    def test_agent_attribution_runs_when_column_provided(self):
        rng = np.random.default_rng(5)
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="D")
        temp = rng.normal(22, 3, n)
        agent = np.linspace(0, 1, n) + rng.normal(0, 0.05, n)
        nee = 0.3 * temp + 1.5 * agent + rng.normal(0, 0.3, n)
        flux = pd.DataFrame({"date": dates, "NEE_daily_total": nee,
                             "temperature_2m_mean": temp,
                             "agent_state": agent})
        rep = run_audit(flux_df=flux, area_ha=10.0, agent_col="agent_state")
        assert rep.attribution.get("agent_col") == "agent_state"

    def test_eight_artifacts_present(self):
        rep = run_audit(
            activity_df=_activity_500t(),
            stock_df=_stock_removal(420.0),
            claimed_removals_tco2e=420.0,
        )
        art = rep.artifacts()
        assert set(art.keys()) == {
            "verified_emission_interval", "verified_removal_interval",
            "conservation_residual_eC", "scale_residual_eA",
            "leakage_ryg", "attribution_decomposition",
            "uncertainty_budget", "audit_certificate",
        }
        assert art["verified_emission_interval"] == pytest.approx([450.0, 550.0])

    def test_summary_renders(self):
        rep = run_audit(activity_df=_activity_500t())
        text = rep.summary()
        assert "OCIP AUDIT REPORT" in text
        assert "Data gaps" in text


class TestScaleAudit:
    """Eq.(4) time-series aggregation-commutator residual (S4)."""

    def _flux(self, values, start="2023-01-01"):
        return pd.DataFrame({
            "date": pd.date_range(start, periods=len(values), freq="D"),
            "NEE_daily_total": values,
        })

    def test_constant_flux_has_zero_aggregation_error(self):
        n = 120
        sa = time_series_scale_audit(self._flux([-4.0] * n))
        assert sa["status"] == "balanced"
        assert sa["eps_max_abs_gCm2"] == pytest.approx(0.0)
        assert sa["n_days"] == n

    def test_spike_flux_flags_aggregation_loss(self):
        n = 120
        vals = [0.0] * n
        vals[10] = 1000.0  # single-day transient the monthly mean smooths away
        sa = time_series_scale_audit(self._flux(vals))
        assert sa["status"] == "flagged"
        assert sa["eps_max_abs_gCm2"] > 0.0
        assert sa["relative_max_pct"] > sa["tol_pct"]
        assert sa["monthly_worst_gCm2"]

    def test_short_series_is_not_run(self):
        sa = time_series_scale_audit(self._flux([-4.0] * 10))
        assert sa["status"] == "not_run"

    def test_scale_audit_populated_in_run_audit(self):
        rep = run_audit(flux_df=self._flux([-4.0] * 120), area_ha=10.0)
        assert rep.scale_audit["status"] == "balanced"
        assert rep.scale_residual_status in ("balanced", "flagged")
        assert rep.scale_residual_eA_tco2e == pytest.approx(0.0)
