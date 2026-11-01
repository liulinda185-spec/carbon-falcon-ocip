"""
Landfill methane Tier-1 kernel (IPCC 2006 / 2019 Guidelines, Vol.5 Ch.3).

CH4_t = MSW_T * DOC * DOC_F * F * (16/12) * (1 - OX) * MCF

Defaults follow the 2006 IPCC Guidelines and 2019 Refinement:
- DOC   : degradable organic carbon, Mg C / Mg MSW (mixed waste, developing regions ~0.126)
- DOC_F : fraction of DOC actually decomposed (0.5 for bulk disposal)
- F     : fraction of CH4 in landfill gas (default 0.5)
- OX    : soil oxidation factor (default 0.1)
- MCF   : methane correction factor by landfill management type
"""

from __future__ import annotations
from dataclasses import dataclass

# ---- IPCC defaults ---------------------------------------------------------
DOC_DEFAULT = 0.126       # Mg C / Mg MSW — mixed municipal waste (developing regions)
DOC_F_DEFAULT = 0.5       # fraction of DOC decomposed
F_DEFAULT = 0.5           # fraction of CH4 in landfill gas
OX_DEFAULT = 0.1          # oxidation factor
GWP_CH4_AR5 = 28          # AR5 GWP100 (100-yr, no climate feedback)
GWP_CH4_AR6 = 29.8        # AR6 GWP100 incl. climate-carbon feedback

# IPCC 2006/2019 Vol.5 Table 3.1 MCF values
LANDFILL_MCF: dict[str, float] = {
    "managed_anaerobic": 1.0,      # managed sanitary landfill, anaerobic
    "managed_semi_aerobic": 0.5,   # managed, semi-aerobic design
    "unmanaged_deep": 0.8,         # unmanaged, depth > 5 m
    "unmanaged_shallow": 0.4,      # unmanaged, depth < 5 m
    "uncategorised": 0.6,
}


@dataclass
class LandfillCH4Result:
    msw_t: float
    doc: float
    doc_f: float
    mcf: float
    f: float
    ox: float
    ch4_t: float
    co2e_t_ar5: float
    co2e_t_ar6: float

    @property
    def ch4_t_per_msw(self) -> float:
        return self.ch4_t / self.msw_t if self.msw_t > 0 else 0.0

    def summary(self) -> str:
        return (
            f"Landfill CH4 (Tier-1 IPCC): {self.ch4_t:.1f} t CH4/yr "
            f"({self.ch4_t_per_msw:.4f} t CH4 per t MSW)\n"
            f"  = {self.co2e_t_ar5:.1f} tCO2e/yr (AR5 GWP28) / "
            f"{self.co2e_t_ar6:.1f} tCO2e/yr (AR6 GWP29.8)\n"
            f"  (DOC {self.doc:.3f} x DOC_F {self.doc_f:.2f} x F {self.f:.2f} "
            f"x MCF {self.mcf:.2f}, 1-OX {1 - self.ox:.2f})"
        )


def landfill_ch4_tier1(
    msw_t: float,
    mcf_key: str = "managed_anaerobic",
    doc: float | None = None,
    doc_f: float | None = None,
    f: float | None = None,
    ox: float | None = None,
) -> LandfillCH4Result:
    """
    Estimate annual landfill CH4 (t/yr) from disposed waste mass (t/yr).

    Parameters
    ----------
    msw_t : annual municipal solid waste disposed at the landfill (t/yr)
    mcf_key : one of LANDFILL_MCF keys
    doc, doc_f, f, ox : optional overrides of IPCC defaults
    """
    if msw_t < 0:
        raise ValueError("msw_t must be non-negative")
    if mcf_key not in LANDFILL_MCF:
        raise KeyError(
            f"unknown landfill type {mcf_key!r}; choose from {sorted(LANDFILL_MCF)}"
        )
    doc = DOC_DEFAULT if doc is None else doc
    doc_f = DOC_F_DEFAULT if doc_f is None else doc_f
    f = F_DEFAULT if f is None else f
    ox = OX_DEFAULT if ox is None else ox
    mcf = LANDFILL_MCF[mcf_key]

    ch4_t = msw_t * doc * doc_f * f * (16.0 / 12.0) * (1.0 - ox) * mcf
    return LandfillCH4Result(
        msw_t=msw_t, doc=doc, doc_f=doc_f, mcf=mcf, f=f, ox=ox,
        ch4_t=ch4_t,
        co2e_t_ar5=ch4_t * GWP_CH4_AR5,
        co2e_t_ar6=ch4_t * GWP_CH4_AR6,
    )
