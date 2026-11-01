"""
UCST-CCIF: Conservation-Constrained Carbon Flux Integrated Framework.

Units: stocks gC m^-2, fluxes gC m^-2 d^-1, daily timestep.
NEE < 0 = net sink, NEE > 0 = net source.
"""

from .compartments import CarbonContinuumModel, CompartmentState
from .parameters import ParameterSet, LITERATURE_RANGES, draw_parameters
from .uncertainty import MonteCarloEnsemble
from .assimilation import observation_operator, nudge_update
from .leakage import (
    audit_leakage, LeakageReport, split_predictors,
    refit_without_leakage, RefitReport,
)
from .models import (
    M0Baseline, M1Conservation, M2aAgent, compare_m0_m1,
    compare_m0_m1_m2a, m3_counterfactual, SCENARIO_PARAMS,
    compute_conservation_state, compute_agent_state, ModelResult,
)
from .attribution import (
    conservation_reconcile, additionality_counterfactual, attribution_split,
    ReconciliationReport, AdditionalityReport, AttributionReport,
    C_TO_CO2, DEFAULT_TOLERANCE_PCT,
)
from .audit_pipeline import (
    run_audit, AuditReport, StageStatus,
    DEFAULT_U95_EMISSIONS, DEFAULT_U95_REMOVALS,
)
from .rothc_lite import (
    run_rothc, run_rothc_dataframe, temperature_factor,
    moisture_factor, DPM_RPM_SPLITS, RothCResult,
)
from .bluecarbon_lookups import (
    blue_carbon_estimate, list_ecosystems, list_regions,
    GWP_CH4_AR6, BlueCarbonEstimate,
)
from .dndc_lite import (
    rice_ch4_season, RICE_WATER_REGIMES,
    ORGANIC_AMENDMENT_SF, RiceCH4Estimate,
)
from .threepg_lookups import (
    get_species, list_species, SpeciesLookup, SPECIES_TABLE,
)
from .raymond_evasion import (
    EvasionKernel, k600_streams, k600_lakes,
    henry_co2, schmidt_co2, GLOBAL_EVASION_PG_C_YR,
)
from .netcdf_priors import (
    PriorClient, PRIOR_SOURCES, list_sources, PriorSource,
)

__version__ = "0.3.0"
__all__ = [
    "CarbonContinuumModel", "CompartmentState",
    "ParameterSet", "LITERATURE_RANGES", "draw_parameters",
    "MonteCarloEnsemble",
    "observation_operator", "nudge_update",
    "audit_leakage", "LeakageReport", "split_predictors",
    "refit_without_leakage", "RefitReport",
    "M0Baseline", "M1Conservation", "M2aAgent", "compare_m0_m1",
    "compare_m0_m1_m2a", "m3_counterfactual", "SCENARIO_PARAMS",
    "compute_conservation_state", "compute_agent_state", "ModelResult",
    # MVP v0.3 audit layer
    "conservation_reconcile", "additionality_counterfactual",
    "attribution_split", "ReconciliationReport", "AdditionalityReport",
    "AttributionReport", "C_TO_CO2", "DEFAULT_TOLERANCE_PCT",
    "run_audit", "AuditReport", "StageStatus",
    "DEFAULT_U95_EMISSIONS", "DEFAULT_U95_REMOVALS",
    # MVP integration kernels
    "run_rothc", "run_rothc_dataframe", "temperature_factor",
    "moisture_factor", "DPM_RPM_SPLITS", "RothCResult",
    "blue_carbon_estimate", "list_ecosystems", "list_regions",
    "GWP_CH4_AR6", "BlueCarbonEstimate",
    "rice_ch4_season", "RICE_WATER_REGIMES",
    "ORGANIC_AMENDMENT_SF", "RiceCH4Estimate",
    "get_species", "list_species", "SpeciesLookup", "SPECIES_TABLE",
    "EvasionKernel", "k600_streams", "k600_lakes",
    "henry_co2", "schmidt_co2", "GLOBAL_EVASION_PG_C_YR",
    "PriorClient", "PRIOR_SOURCES", "list_sources", "PriorSource",
]
