"""
Monte Carlo uncertainty wrapper: sample parameters from literature ranges,
run the model ensemble, report mean and 95% CI for NEE and stocks.

This implements the UCST-CCIF "parameter uncertainty" category
(manuscript Section 2.7).
"""

import numpy as np
from .compartments import CarbonContinuumModel, CompartmentState
from .parameters import draw_parameters, ParameterSet


class MonteCarloEnsemble:
    """Run N ensemble members with sampled parameters."""

    def __init__(self, n_members: int = 200, seed: int = 42):
        self.n = n_members
        self.rng = np.random.default_rng(seed)
        self.results: list[CompartmentState] = []

    def run(self, gpp_series: np.ndarray, T_air: np.ndarray,
            swc: np.ndarray, rain: np.ndarray) -> dict:
        """
        Run ensemble. Returns dict with:
            nee_mean, nee_p5, nee_p95   : NEE trajectory CI
            stock_mean, stock_p5/p95    : per-compartment stock CI
            params_used                 : list of ParameterSet
        """
        nee_ens = np.zeros((self.n, len(gpp_series)))
        eps_ens = np.zeros((self.n, len(gpp_series)))
        coastal_burial = np.zeros(self.n)
        params_used: list[ParameterSet] = []

        for i in range(self.n):
            p = draw_parameters(self.rng)
            model = CarbonContinuumModel(p)
            state = model.run(gpp_series, T_air, swc, rain)
            nee_ens[i, :] = state.nee
            eps_ens[i, :] = state.eps_C
            coastal_burial[i] = state.coastal_burial_cum
            params_used.append(p)

        return dict(
            nee_mean=nee_ens.mean(axis=0),
            nee_p5=np.percentile(nee_ens, 5, axis=0),
            nee_p95=np.percentile(nee_ens, 95, axis=0),
            eps_mean=eps_ens.mean(axis=0),
            eps_p5=np.percentile(eps_ens, 5, axis=0),
            eps_p95=np.percentile(eps_ens, 95, axis=0),
            coastal_burial_mean=coastal_burial.mean(),
            coastal_burial_p5=np.percentile(coastal_burial, 5),
            coastal_burial_p95=np.percentile(coastal_burial, 95),
            params_used=params_used,
        )
