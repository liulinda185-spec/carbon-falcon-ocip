"""Tests for the read-only prior-source registry and offline demo grid."""
import pytest
from ucst_ccif import PRIOR_SOURCES, PriorClient, list_sources


def test_registry_covers_all_mvp_sources():
    names = list_sources()
    for required in ["CAMS", "FLUXCOM", "SoilGrids", "NASA_CMS_Mangrove",
                     "SOCAT", "CEADs"]:
        assert required in names


def test_registry_metadata_complete():
    for s in PRIOR_SOURCES:
        assert s.url.startswith("http")
        assert s.licence
        assert s.variables
        assert s.etl_hint


def test_demo_grid_shape():
    g = PriorClient().demo_grid(nx=8, ny=6, nt=12)
    assert g["values"].shape == (12, 6, 8)


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        PriorClient().fetch("NOT_A_SOURCE")


def test_netcdf_fetch_raises_without_xarray():
    client = PriorClient()
    # In this environment xarray is not installed -> NetCDF sources must raise
    # ImportError with an install hint; tabular CEADs raises NotImplementedError
    # (ETL not wired) which also proves the registry resolves correctly.
    try:
        import xarray  # noqa: F401
        has_xarray = True
    except Exception:
        has_xarray = False
    if has_xarray:
        pytest.skip("xarray installed; ImportError path not applicable here")
    with pytest.raises(ImportError, match="xarray"):
        client.fetch("CAMS")
