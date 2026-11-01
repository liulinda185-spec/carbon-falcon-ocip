"""
Simple observation operator and data-assimilation nudge.

For MVP: instead of a full Ensemble Kalman Filter (which needs DART or
filterpy), we use a relaxation-to-observation nudging scheme:
    whenever observed NEE diverges from modelled NEE by > 2*sigma_obs,
    adjust the most uncertain pool (S_active) by a fraction of the residual.

This is a deliberate, documented simplification. It is NOT a substitute for
a proper EnKF — but it is auditable and sufficient for the first version.
Upgrade to filterpy.EnKF once two validation sites are online.
"""

import numpy as np
from .compartments import STATE_KEYS


def observation_operator(state: dict) -> float:
    """
    Map model state to observed NEE (the quantity measured by eddy covariance).

    In this simple model, the diagnosed NEE from step() IS the observation.
    This function exists so the observation operator H is explicit, as
    required by UCST-CCIF Eq. (6): y = H(x) + b + eta.
    """
    return state["nee"]


def nudge_update(x: np.ndarray,
                 modelled_nee: float,
                 observed_nee: float,
                 sigma_obs: float = 0.3,
                 relaxation: float = 0.5) -> tuple[np.ndarray, float]:
    """
    Relaxation-to-observation nudge.

    Parameters
    ----------
    x : state vector (13 stocks)
    modelled_nee, observed_nee : gC m^-2 d^-1
    sigma_obs : observation noise (gC m^-2 d^-1)
    relaxation : fraction of residual absorbed into soil pool (0-1)

    Returns
    -------
    x_new : adjusted state
    nudge_applied : magnitude of adjustment (gC m^-2)
    """
    residual = observed_nee - modelled_nee  # +ve means model under-predicts source
    if abs(residual) < 2.0 * sigma_obs:
        return x, 0.0

    # Absorb residual into S_active (index 5) — the most uncertain pool.
    # Positive residual (model says sink, observation says source) ->
    # reduce S_active (respiration too low means soil C is overestimated).
    idx_S_active = STATE_KEYS.index("S_active")
    adjustment = -relaxation * residual  # gC m^-2 d^-1 transferred
    x_new = x.copy()
    x_new[idx_S_active] = max(0.0, x_new[idx_S_active] + adjustment)
    return x_new, adjustment
