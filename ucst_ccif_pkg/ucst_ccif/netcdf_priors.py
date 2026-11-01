"""
Read-only NetCDF / tabular prior pullers (CAMS, FLUXCOM, SoilGrids, NASA CMS
mangrove, SOCAT, CEADs).

Design contract (from the Integration roadmap):
    - OCIP consumes gridded outputs as PRIORS, never re-runs the parent model.
    - Every fetch is READ-ONLY: no writes to source systems, no licensing
      obligations beyond each source's terms (check per source before
      redistribution of derived products).

Dependencies: xarray + netCDF4 are REQUIRED to actually read NetCDF files.
They are optional extras in pyproject (`pip install -e ".[data]"`).
If missing, `PriorClient.fetch()` raises ImportError with an install hint;
`list_sources()` and the offline `demo_grid()` still work.

For each source the registry records: name, provider, URL, format, licence,
variables, coverage, and an ETL hint (what to subset / which file to grab).
All URLs are the official portals; verify current endpoints at fetch time.
"""

from __future__ import annotations
from dataclasses import dataclass, field

try:
    import xarray as xr  # noqa: F401
    _HAS_XARRAY = True
except Exception:  # pragma: no cover
    xr = None
    _HAS_XARRAY = False

try:
    import requests  # noqa: F401
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None
    _HAS_REQUESTS = False


@dataclass(frozen=True)
class PriorSource:
    name: str
    provider: str
    url: str
    file_format: str
    licence: str
    variables: str
    coverage: str
    etl_hint: str


PRIOR_SOURCES: list[PriorSource] = [
    PriorSource(
        name="CAMS", provider="Copernicus/ECMWF",
        url="https://ads.atmosphere.copernicus.eu/",
        file_format="NetCDF/GRIB (xds)",
        licence="CAMS licence (free for non-commercial; redistribute w/ attribution)",
        variables="CO2, CH4 fluxes & mixing ratios (global inversion)",
        coverage="Global, ~0.1-1 deg, daily-monthly",
        etl_hint="Use ADS API (variables 'carbon_dioxide','methane'); subset GBA bbox; cache NetCDF; regrid to OCIP grid.",
    ),
    PriorSource(
        name="FLUXCOM", provider="ICOS/Max Planck",
        url="https://www.fluxcom.org/",
        file_format="NetCDF",
        licence="CC-BY-4.0 (FLUXCOM-X)",
        variables="GPP, NEE, TER (upscaled from FLUXNET)",
        coverage="Global 0.05-0.5 deg, 2001-2021 (FLUXCOM-X)",
        etl_hint="Download GPP/NEE monthly NetCDF; clip GBA bbox; use as M0 upscaled reference & benchmark for tower sites.",
    ),
    PriorSource(
        name="SoilGrids", provider="ISRIC",
        url="https://files.isric.org/soilgrids/latest/data/",
        file_format="NetCDF (COG)", licence="CC-BY-4.0",
        variables="SOC stock 0-30cm, 30-100cm (tC/ha)",
        coverage="Global, 250 m",
        etl_hint="Grab 'ocs_0-30cm_mean' NetCDF/COG variants; reproject to GBA; use as RothC/SOC prior & verification of soil pools.",
    ),
    PriorSource(
        name="NASA_CMS_Mangrove", provider="NASA CMS / JPL",
        url="https://data.nasa.gov/",
        file_format="NetCDF/GeoTIFF",
        licence="NASA open data (public domain)",
        variables="Mangrove canopy height, AGB, C stock",
        coverage="Global mangroves, ~30 m (2000 & 2016 vintages)",
        etl_hint="Search CMS 'Global Mangrove' biomass; clip GBA mangrove belt (Qi'ao, Shenzhen, Zhanjiang); cross-check against blue-carbon lookups.",
    ),
    PriorSource(
        name="SOCAT", provider="SOCAT (international)",
        url="https://www.socat.info/",
        file_format="NetCDF/CSV",
        licence="SOCAT data use agreement (open, attribution required)",
        variables="Surface fCO2, SST, SSS (quality-flagged)",
        coverage="Global coastal & open ocean, 1957-present",
        etl_hint="Pull GBA coastal bbox; compute air-sea CO2 flux with your EvasionKernel (open-water branch); flag 'WOCE' quality tiers.",
    ),
    PriorSource(
        name="CEADs", provider="Tsinghua University",
        url="https://www.ceads.net/",
        file_format="Excel/CSV (provincial & city)",
        licence="Free registration, research use; commercial requires license",
        variables="CO2 emission inventories by sector (fossil, process)",
        coverage="China provinces + 400+ cities, 1997-2021+",
        etl_hint="Not NetCDF: read via pandas read_excel. Download Guangdong + PRD city sheets; map sectors to GHG Protocol/GB/T 4754; use as L4 baseline & normalization tests.",
    ),
]

PRIOR_BY_NAME: dict[str, PriorSource] = {s.name: s for s in PRIOR_SOURCES}


def list_sources() -> list[str]:
    return [s.name for s in PRIOR_SOURCES]


class PriorClient:
    """Read-only client for the MVP prior sources.

    Real NetCDF pulls require `pip install "ucst-ccif[data]"`
    (xarray + netCDF4). Tabular sources (CEADs) only need pandas.
    """

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = cache_dir

    def fetch(self, name: str, **kwargs):
        """Fetch a prior for source `name`.

        Raises
        ------
        KeyError   : unknown source name
        ImportError: xarray/requests missing for NetCDF sources
        """
        src = PRIOR_BY_NAME.get(name)
        if src is None:
            raise KeyError(f"unknown prior source {name!r}; available: "
                           f"{list_sources()}")
        if src.file_format.startswith("NetCDF") and not _HAS_XARRAY:
            raise ImportError(
                f"{name} is a NetCDF source; install optional deps with "
                f"`python -m pip install -e \".[data]\"` (xarray + netCDF4).")
        if not _HAS_REQUESTS:
            raise ImportError("`requests` required for network fetches; "
                              "install with `pip install requests`.")
        # Actual download logic is source-specific ETL; for MVP this raises
        # NotImplementedError with the ETL hint so each source is wired
        # incrementally without silently fabricating data.
        raise NotImplementedError(
            f"ETL for {name} not wired yet. Source: {src.url} | {src.etl_hint}")

    def demo_grid(self, nx: int = 10, ny: int = 10, nt: int = 12) -> dict:
        """Offline synthetic grid (pure numpy, no xarray needed).

        Returns a dict mimicking a small 3-D prior field so the ingestion
        interface can be tested before real data arrives. Clearly demo data.
        """
        import numpy as np
        rng = np.random.default_rng(0)
        return {
            "lon": np.linspace(112.5, 114.5, nx),
            "lat": np.linspace(22.0, 23.5, ny),
            "time": np.arange(nt),
            "values": rng.normal(loc=0.5, scale=0.2, size=(nt, ny, nx)),
        }
