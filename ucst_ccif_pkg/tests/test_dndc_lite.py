"""Tests for DNDC-lite rice CH4 Tier-1 calculator."""
import pytest
from ucst_ccif import rice_ch4_season, RICE_WATER_REGIMES
from ucst_ccif.dndc_lite import GWP_CH4_AR6


def test_regime_ordering():
    cf = rice_ch4_season("continuously_flooded", 100).adjusted_kgCH4_ha
    ifa = rice_ch4_season("intermittently_flooded_single", 100).adjusted_kgCH4_ha
    ifm = rice_ch4_season("intermittently_flooded_multiple", 100).adjusted_kgCH4_ha
    assert cf > ifa > ifm


def test_no_amendment_default_factors_one():
    est = rice_ch4_season("continuously_flooded", 100)
    assert est.sfw == 1.0 and est.sfp == 1.0 and est.sfo == 1.0
    assert est.adjusted_kgCH4_ha == pytest.approx(
        est.baseline_kgCH4_ha)


def test_amendment_scales_emission():
    base = rice_ch4_season("continuously_flooded", 100).adjusted_kgCH4_ha
    amended = rice_ch4_season("continuously_flooded", 100,
                              organic_amendment="composted_organic").adjusted_kgCH4_ha
    assert amended < base


def test_co2e_conversion():
    est = rice_ch4_season("continuously_flooded", 100)
    assert est.co2e_tCO2e_ha == pytest.approx(
        est.adjusted_kgCH4_ha * GWP_CH4_AR6 / 1000.0)


def test_area_scaling():
    est = rice_ch4_season("rainfed_regular", 90, area_ha=50.0)
    assert est.total_kgCH4 == pytest.approx(est.adjusted_kgCH4_ha * 50.0)
    assert est.total_tCO2e == pytest.approx(est.co2e_tCO2e_ha * 50.0)


def test_invalid_inputs_raise():
    with pytest.raises(KeyError):
        rice_ch4_season("unknown_regime", 90)
    with pytest.raises(ValueError):
        rice_ch4_season("continuously_flooded", 90, cultivar_factor=3.0)
