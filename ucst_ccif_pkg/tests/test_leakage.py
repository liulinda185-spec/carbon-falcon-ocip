"""Tests for the leakage audit."""
import numpy as np
import pandas as pd
from ucst_ccif import audit_leakage, split_predictors


def test_flags_gpp_as_leaky():
    rng = np.random.default_rng(0)
    n = 200
    nee = rng.normal(0, 1, n)
    gpp = -nee + rng.normal(0, 0.1, n)  # deterministic transform
    wind = rng.normal(2, 0.5, n)         # independent
    df = pd.DataFrame({"NEE": nee, "GPP": gpp, "wind": wind})
    rep = audit_leakage(df, "NEE", ["GPP", "wind"])
    assert "GPP" in rep.leaky_predictors
    assert "wind" not in rep.leaky_predictors
    leaky, exo = split_predictors(rep)
    assert "GPP" in leaky
    assert "wind" in exo
