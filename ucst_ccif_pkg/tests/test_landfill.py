"""Tests for the landfill methane Tier-1 kernel (IPCC 2006/2019)."""

import pytest
from ucst_ccif.landfill import (
    LANDFILL_MCF, landfill_ch4_tier1,
    DOC_DEFAULT, DOC_F_DEFAULT, F_DEFAULT, OX_DEFAULT,
    GWP_CH4_AR5, GWP_CH4_AR6,
)


def test_managed_anaerobic_reference():
    # 100,000 t MSW, managed anaerobic landfill
    r = landfill_ch4_tier1(100_000.0, mcf_key="managed_anaerobic")
    expected = (100_000.0 * DOC_DEFAULT * DOC_F_DEFAULT * F_DEFAULT
                * (16.0 / 12.0) * (1.0 - OX_DEFAULT) * 1.0)
    assert r.ch4_t == pytest.approx(expected, rel=1e-9)
    assert r.mcf == 1.0
    assert r.co2e_t_ar5 == pytest.approx(expected * GWP_CH4_AR5)
    assert r.co2e_t_ar6 == pytest.approx(expected * GWP_CH4_AR6)


def test_semi_aerobic_half():
    r = landfill_ch4_tier1(50_000.0, mcf_key="managed_semi_aerobic")
    r_ana = landfill_ch4_tier1(50_000.0, mcf_key="managed_anaerobic")
    # semi-aerobic produces half the methane of anaerobic (IPCC design intent)
    assert r.ch4_t == pytest.approx(r_ana.ch4_t / 2.0)


def test_zero_waste():
    r = landfill_ch4_tier1(0.0)
    assert r.ch4_t == 0.0
    assert r.ch4_t_per_msw == 0.0


def test_unknown_type_raises():
    with pytest.raises(KeyError):
        landfill_ch4_tier1(1_000.0, mcf_key="nope")


def test_negative_raises():
    with pytest.raises(ValueError):
        landfill_ch4_tier1(-1.0)


def test_all_types_covered():
    for key in LANDFILL_MCF:
        r = landfill_ch4_tier1(10_000.0, mcf_key=key)
        assert r.ch4_t >= 0.0
