"""Tests for the Raymond-2013 inland-water evasion kernel."""
import numpy as np
import pytest
from ucst_ccif import EvasionKernel, k600_streams, k600_lakes
from ucst_ccif.raymond_evasion import schmidt_co2, henry_co2


def test_flux_positive_when_supersaturated():
    k = EvasionKernel(water_type="stream", velocity=0.5, slope=0.001)
    flux = k.flux_gC_m2_d(pco2_water_uatm=2000.0)
    assert flux > 0


def test_equilibrium_zero_flux():
    k = EvasionKernel(water_type="lake")
    flux = k.flux_gC_m2_d(pco2_water_uatm=420.0, pco2_atm_uatm=420.0)
    assert abs(flux) < 1e-9


def test_flux_increases_with_pco2():
    k = EvasionKernel(water_type="stream", velocity=0.5, slope=0.001)
    low = k.flux_gC_m2_d(800.0)
    high = k.flux_gC_m2_d(4000.0)
    assert high > low


def test_k600_stream_exceeds_lake_default():
    ks = k600_streams(0.5, 0.001)
    kl = k600_lakes(3.0)
    assert ks > kl > 0


def test_schmidt_and_henry_positive():
    assert schmidt_co2(20.0) > 0
    assert henry_co2(20.0) > 0
    # Henry constant decreases with temperature (CO2 less soluble when warm)
    assert henry_co2(30.0) < henry_co2(10.0)


def test_total_evasion_area_scaling():
    k = EvasionKernel(water_type="lake", k600_fixed=1.0)
    a = k.total_MgC_yr(2000.0, area_km2=10.0)
    b = k.total_MgC_yr(2000.0, area_km2=100.0)
    assert b == pytest.approx(a * 10.0)
    assert a > 0
