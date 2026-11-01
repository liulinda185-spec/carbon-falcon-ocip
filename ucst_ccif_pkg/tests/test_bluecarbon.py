"""Tests for blue-carbon lookup tables."""
import pytest
from ucst_ccif import blue_carbon_estimate, list_ecosystems, list_regions
from ucst_ccif.bluecarbon_lookups import GWP_CH4_AR6


def test_lookup_positive_and_consistent():
    est = blue_carbon_estimate("mangrove", "subtropical")
    assert est.stock_MgC_ha == pytest.approx(
        est.agb_MgC_ha + est.bgb_MgC_ha + est.soil_MgC_ha)
    assert est.stock_MgC_ha > 100
    assert est.sequestration_gC_m2_yr > 50
    assert est.burial_MgC_ha_yr > 0


def test_region_ordering():
    trop = blue_carbon_estimate("mangrove", "tropical").stock_MgC_ha
    temp = blue_carbon_estimate("mangrove", "temperate").stock_MgC_ha
    assert trop > temp


def test_ecosystem_and_region_lists():
    assert set(list_ecosystems()) == {"mangrove", "saltmarsh", "seagrass"}
    assert "subtropical" in list_regions()


def test_ch4_co2e_conversion():
    est = blue_carbon_estimate("saltmarsh", "subtropical")
    assert est.ch4_co2e_gCO2e_m2_yr == pytest.approx(
        est.ch4_gCH4_m2_yr * GWP_CH4_AR6)


def test_area_scaling():
    est = blue_carbon_estimate("seagrass", "subtropical", area_ha=100.0)
    assert est.total_stock_MgC == pytest.approx(est.stock_MgC_ha * 100.0)
    assert est.annual_burial_MgC == pytest.approx(est.burial_MgC_ha_yr * 100.0)


def test_unknown_ecosystem_raises():
    with pytest.raises(KeyError):
        blue_carbon_estimate("peatland")
