"""
3-PG-lite: species parameter lookups for GBA subtropical species.

Full 3-PG (Physiological Principles Predicting Growth, Sands & Landsberg
2002) is a forest-stand process model. This module ships the *lookup layer*
only: species-level parameters relevant to GPP/NPP estimation, plus a thin
light-use-efficiency kernel for annual NPP scoping.

Fields (3-PG conventions):
    alpha_C      canopy quantum efficiency (mol C / mol PAR)
    SLA          specific leaf area (m2 kg-1)
    pRx          fraction of NPP to roots
    pRn          fraction of NPP to foliage
    pFs          fraction of NPP to stems
    wood_density kg m-3 (for biomass conversion)
    litter_class RothC DPM:RPM split key (ties the two kernels together)

All numbers are LITERATURE-INFORMED DEFAULTS for scoping — mark clearly in
any report that they require site calibration (allometry, LAI, eddy flux).

Species list covers GBA plantation + native + mangrove candidates.
"""

from __future__ import annotations
from dataclasses import dataclass

# mol C / mol PAR, m2/kg, fractions, kg/m3
# Values are defaults assembled from 3-PG literature & species papers [待核证]
SPECIES_TABLE: dict[str, dict] = {
    # --- GBA plantation species ---
    "Eucalyptus urophylla": {
        "alpha_C": 0.05, "SLA": 6.0, "pRx": 0.25, "pRn": 0.35, "pFs": 0.40,
        "wood_density": 540.0, "litter_class": "broadleaf",
    },
    "Eucalyptus camaldulensis": {
        "alpha_C": 0.055, "SLA": 7.0, "pRx": 0.25, "pRn": 0.35, "pFs": 0.40,
        "wood_density": 500.0, "litter_class": "broadleaf",
    },
    "Acacia mangium": {
        "alpha_C": 0.045, "SLA": 9.0, "pRx": 0.28, "pRn": 0.38, "pFs": 0.34,
        "wood_density": 450.0, "litter_class": "broadleaf",
    },
    "Cunninghamia lanceolata": {
        "alpha_C": 0.042, "SLA": 5.0, "pRx": 0.22, "pRn": 0.30, "pFs": 0.48,
        "wood_density": 310.0, "litter_class": "conifer",
    },
    "Pinus massoniana": {
        "alpha_C": 0.038, "SLA": 4.0, "pRx": 0.22, "pRn": 0.28, "pFs": 0.50,
        "wood_density": 450.0, "litter_class": "conifer",
    },
    # --- Native / secondary forest ---
    "Schima superba": {
        "alpha_C": 0.048, "SLA": 7.5, "pRx": 0.24, "pRn": 0.36, "pFs": 0.40,
        "wood_density": 610.0, "litter_class": "broadleaf",
    },
    "Castanopsis hystrix": {
        "alpha_C": 0.045, "SLA": 6.5, "pRx": 0.24, "pRn": 0.34, "pFs": 0.42,
        "wood_density": 650.0, "litter_class": "broadleaf",
    },
    # --- Mangroves (GBA candidates) ---
    "Kandelia obovata": {
        "alpha_C": 0.040, "SLA": 8.0, "pRx": 0.40, "pRn": 0.35, "pFs": 0.25,
        "wood_density": 700.0, "litter_class": "mangrove",
    },
    "Avicennia marina": {
        "alpha_C": 0.042, "SLA": 8.5, "pRx": 0.42, "pRn": 0.34, "pFs": 0.24,
        "wood_density": 720.0, "litter_class": "mangrove",
    },
    "Sonneratia caseolaris": {
        "alpha_C": 0.046, "SLA": 10.0, "pRx": 0.38, "pRn": 0.36, "pFs": 0.26,
        "wood_density": 480.0, "litter_class": "mangrove",
    },
}


@dataclass
class SpeciesLookup:
    species: str
    params: dict

    def estimate_npp(self, par_mj_m2_yr: float,
                     fapar: float = 0.6) -> float:
        """
        Scoping NPP (tC/ha/yr) from annual PAR (MJ/m2/yr) and FAPAR.

        alpha_C in mol C / mol PAR -> gC conversion:
            NPP = alpha_C * PAR * fapar * (1 - pRx) * 0.012 * 10  (tC/ha)
        Rough scoping only; calibrate with tower/site data.
        """
        alpha = self.params["alpha_C"]
        mol_per_MJ = 2.3          # MJ -> mol PAR (approx, clear sky PAR)
        gpp_gC = alpha * par_mj_m2_yr * mol_per_MJ * fapar * 12.0  # gC/m2/yr
        npp_gC = gpp_gC * (1.0 - self.params["pRx"])               # above+bellow NPP
        return npp_gC * 10.0 / 1e6 * 1e4                            # -> tC/ha/yr


def get_species(name: str) -> SpeciesLookup:
    """Fetch a species parameter set by exact or fuzzy name."""
    if name in SPECIES_TABLE:
        return SpeciesLookup(species=name, params=dict(SPECIES_TABLE[name]))
    low = name.lower()
    hits = [s for s in SPECIES_TABLE if low in s.lower()]
    if len(hits) == 1:
        return SpeciesLookup(species=hits[0], params=dict(SPECIES_TABLE[hits[0]]))
    if len(hits) > 1:
        raise KeyError(f"ambiguous species {name!r}; matches {hits}")
    raise KeyError(f"unknown species {name!r}; available: {list_species()}")


def list_species() -> list[str]:
    return sorted(SPECIES_TABLE)
