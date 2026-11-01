"""Tests for 3-PG species lookup layer."""
import pytest
from ucst_ccif import get_species, list_species


def test_exact_lookup():
    s = get_species("Kandelia obovata")
    assert s.species == "Kandelia obovata"
    assert 0 < s.params["alpha_C"] < 0.1
    assert s.params["litter_class"] == "mangrove"


def test_fuzzy_lookup():
    s = get_species("eucalyptus urophylla")
    assert s.species == "Eucalyptus urophylla"


def test_npp_estimate_positive_and_scales_with_par():
    s = get_species("Eucalyptus urophylla")
    low = s.estimate_npp(par_mj_m2_yr=3000.0)
    high = s.estimate_npp(par_mj_m2_yr=5000.0)
    assert low > 0 and high > low


def test_unknown_raises():
    with pytest.raises(KeyError):
        get_species("Pinus nonexistent")


def test_species_list_nonempty():
    assert len(list_species()) >= 5
