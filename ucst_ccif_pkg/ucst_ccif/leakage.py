"""
Three-step target-leakage audit for carbon-flux models.

Ported from LiuYG_03_leakage_free_model_comparison.py.
Implements the protocol in Section 5.1 of the manuscript:

  1. Predictor classification: flag predictors algebraically derived from NEE.
  2. Correlation screening: |r| > 0.5 investigate, |r| > 0.8 near-deterministic.
  3. Leakage-free refit: drop leaky predictors, refit, compare.

This is a first-class audit feature in the product, not an afterthought.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np
import pandas as pd


# Predictor names that are algebraically derived from NEE via flux partitioning.
# GPP and ER are deterministic transforms of NEE: GPP - ER = NEE.
LEAKY_PATTERNS: tuple[str, ...] = (
    "gpp", "GPP", "er_", "ER_", "_er", "ecosystem_resp",
    "nee_balance", "carbon_balance", "cumulative_balance",
    "npp_balance", "lateral_flux",
)


@dataclass
class LeakageReport:
    """Result of a leakage audit."""
    classified: dict[str, str] = field(default_factory=dict)
    correlations: dict[str, float] = field(default_factory=dict)
    leaky_predictors: list[str] = field(default_factory=list)
    near_deterministic: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["=== UCST-CCIF Leakage Audit ==="]
        lines.append(f"Predictors classified: {len(self.classified)}")
        lines.append(f"Leaky (NEE-derived):  {len(self.leaky_predictors)} -> {self.leaky_predictors}")
        lines.append(f"Near-deterministic (|r|>0.8): {self.near_deterministic}")
        lines.append("")
        lines.append("Per-predictor correlations with target:")
        for k, v in sorted(self.correlations.items(), key=lambda x: -abs(x[1])):
            flag = "  <-- LEAKY" if k in self.leaky_predictors else ""
            lines.append(f"  {k:30s} r={v:+.3f}{flag}")
        return "\n".join(lines)


def classify_predictor(col: str) -> str:
    """
    Classify a column as 'leaky' if its name matches flux-partitioning patterns.
    This is a heuristic; the user should confirm with the data dictionary.
    """
    for pat in LEAKY_PATTERNS:
        if pat in col:
            return "leaky"
    return "exogenous"


def audit_leakage(df: pd.DataFrame,
                  target_col: str,
                  predictor_cols: Sequence[str]) -> LeakageReport:
    """
    Run the 3-step leakage audit.

    Parameters
    ----------
    df : DataFrame with target and predictor columns
    target_col : name of the target variable (e.g. 'NEE_daily_total')
    predictor_cols : list of predictor column names

    Returns
    -------
    LeakageReport with classification, correlations, and flags.
    """
    report = LeakageReport()
    try:
        y = np.asarray(df[target_col].values, dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"target column {target_col!r} is not numeric: {e}"
        ) from e

    for col in predictor_cols:
        if col not in df.columns:
            continue
        report.classified[col] = classify_predictor(col)
        try:
            x = np.asarray(df[col].values, dtype=float)
        except (TypeError, ValueError):
            continue  # non-numeric column (e.g. date) is not a predictor
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 10:
            report.correlations[col] = float("nan")
            continue
        r = np.corrcoef(x[mask], y[mask])[0, 1]
        report.correlations[col] = float(r)

        if report.classified[col] == "leaky":
            report.leaky_predictors.append(col)
        if abs(r) > 0.8:
            report.near_deterministic.append(col)

    return report


def split_predictors(report: LeakageReport) -> tuple[list[str], list[str]]:
    """Return (leaky_cols, exogenous_cols) from a report."""
    leaky = [c for c, cls in report.classified.items() if cls == "leaky"]
    exogenous = [c for c, cls in report.classified.items() if cls == "exogenous"]
    return leaky, exogenous


# --------------------------------------------------------------------------
# Step 3: leakage-free refit (the honest-baseline comparison)
# --------------------------------------------------------------------------
@dataclass
class RefitReport:
    """Comparison of the model with leaky predictors vs the leakage-free refit."""
    leaky_rmse: float          # out-of-sample RMSE using ALL predictors
    clean_rmse: float          # out-of-sample RMSE using exogenous predictors only
    apparent_gain_pct: float   # (1 - leaky/clean)*100; positive = leaky looks better
    leaky_predictors: list[str]
    clean_predictors: list[str]
    n_samples: int
    test_fraction: float

    def summary(self) -> str:
        return (
            f"=== Leakage-free refit (step 3) ===\n"
            f"RMSE with leaky predictors : {self.leaky_rmse:.4f}\n"
            f"RMSE leakage-free refit    : {self.clean_rmse:.4f}\n"
            f"Apparent gain from leakage : {self.apparent_gain_pct:+.1f}%\n"
            f"(positive = the leaky model only *looks* better; "
            f"Sapelo honest baseline: 36.1% apparent gain)\n"
            f"Clean predictors retained : {self.clean_predictors}"
        )


def _ols_rmse(df: pd.DataFrame, target: str, cols: list[str],
              test_fraction: float) -> tuple[float, int]:
    """Linear OLS (with intercept), time-ordered train/test split."""
    data = df.dropna(subset=[target] + cols).copy()
    n = len(data)
    n_test = max(5, int(n * test_fraction))
    n_train = n - n_test
    if n_train < 10 or n_test < 2:
        raise ValueError(
            f"not enough rows for refit: {n} rows "
            f"(need >= 12 with {test_fraction:.0%} test split)")
    X = np.column_stack([data[c].values for c in cols])
    X = np.column_stack([X, np.ones(n)])
    y = data[target].values
    X_tr, X_te, y_tr, y_te = X[:n_train], X[n_train:], y[:n_train], y[n_train:]
    beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
    pred = X_te @ beta
    rmse = float(np.sqrt(np.mean((pred - y_te) ** 2)))
    return rmse, n


def refit_without_leakage(
    df: pd.DataFrame,
    target_col: str,
    predictor_cols: Sequence[str],
    exo_only: Sequence[str] | None = None,
    test_fraction: float = 0.25,
) -> RefitReport:
    """
    Step 3 of the leakage protocol: drop the leaky predictors, refit the model,
    and compare out-of-sample RMSE. A large apparent gain (clean RMSE above
    leaky RMSE) is the signature of target leakage — the quoted R2/RMSE was
    partly explaining the target with itself.

    `exo_only` overrides the automatic classification (use it when the
    name-based heuristic needs a manual correction).
    """
    leaky_cols = [c for c in predictor_cols if classify_predictor(c) == "leaky"]
    if exo_only is not None:
        clean_cols = [c for c in exo_only if c in df.columns]
    else:
        clean_cols = [c for c in predictor_cols if c not in leaky_cols]
    if not clean_cols:
        return RefitReport(
            leaky_rmse=float("nan"), clean_rmse=float("nan"),
            apparent_gain_pct=float("nan"),
            leaky_predictors=leaky_cols, clean_predictors=[],
            n_samples=0, test_fraction=test_fraction)

    leaky_rmse, n1 = _ols_rmse(df, target_col, list(predictor_cols), test_fraction)
    clean_rmse, n2 = _ols_rmse(df, target_col, clean_cols, test_fraction)
    apparent_gain = (1.0 - leaky_rmse / clean_rmse) * 100.0 \
        if clean_rmse > 0 else float("nan")
    return RefitReport(
        leaky_rmse=leaky_rmse, clean_rmse=clean_rmse,
        apparent_gain_pct=apparent_gain,
        leaky_predictors=leaky_cols, clean_predictors=clean_cols,
        n_samples=min(n1, n2), test_fraction=test_fraction)
