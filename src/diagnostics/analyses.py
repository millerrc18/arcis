"""Five diagnostic analyses for regime diagnostic v1.

A1: Continuous VIX regression (excess_return ~ vix_at_entry)
A2: Trade-day clustering (per-calendar-day + contiguous-run detection)
A3: Sector rotation (4-bucket stratification)
A4: Entry time-of-day (4-bucket stratification)
A5: Holding period outcomes (3-bucket stratification)

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: diagnostics.bootstrap, diagnostics.fdr, diagnostics.power,
       diagnostics.known_events
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from src.diagnostics.bootstrap import bootstrap_ci
from src.diagnostics.fdr import benjamini_hochberg
from src.diagnostics.known_events import KNOWN_EVENTS, EVENT_CATEGORIES
from src.diagnostics.power import cell_mde, regression_slope_mde

MIN_CELL_SIZE = 5
MDE_BENCHMARK_BPS_PER_VIX = 0.3  # % per VIX point


def _cell_stats(
    data: np.ndarray,
    label: str,
    n_resamples: int = 10_000,
) -> dict:
    """Compute stats for a single stratification cell.

    Returns insufficient_data if n < MIN_CELL_SIZE.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)
    result: dict = {"label": label, "n": n}

    if n < MIN_CELL_SIZE:
        result["status"] = "insufficient_data"
        result["point_estimate"] = None
        result["ci_lower"] = None
        result["ci_upper"] = None
        result["p_value"] = None
        result["mde"] = None
        return result

    boot = bootstrap_ci(data, n_resamples=n_resamples)
    std = float(np.std(data, ddof=1))
    mde = cell_mde(n=n, std=std)

    result["status"] = "computed"
    result["point_estimate"] = boot["point_estimate"]
    result["ci_lower"] = boot["ci_lower"]
    result["ci_upper"] = boot["ci_upper"]
    result["p_value"] = boot["p_value"]
    result["std"] = std
    result["mde"] = mde
    result["is_underpowered"] = mde > 0.5
    return result


def _stratified_analysis(
    df: pd.DataFrame,
    group_col: str,
    value_col: str = "excess_return",
    n_resamples: int = 10_000,
) -> dict:
    """Run cell-level analysis for a stratification dimension."""
    cells = []
    p_values = []
    for label, group in sorted(df.groupby(group_col)):
        cell = _cell_stats(
            group[value_col].values, label=str(label),
            n_resamples=n_resamples,
        )
        cells.append(cell)
        if cell["p_value"] is not None:
            p_values.append(cell["p_value"])

    # FDR correction across computed cells
    if len(p_values) >= 2:
        adjusted, survived = benjamini_hochberg(
            np.array(p_values), q=0.10,
        )
        idx = 0
        for cell in cells:
            if cell["p_value"] is not None:
                cell["p_adjusted"] = float(adjusted[idx])
                cell["survives_fdr"] = survived[idx]
                idx += 1
    elif len(p_values) == 1:
        cells_with_p = [c for c in cells if c["p_value"] is not None]
        cells_with_p[0]["p_adjusted"] = cells_with_p[0]["p_value"]
        cells_with_p[0]["survives_fdr"] = cells_with_p[0]["p_value"] <= 0.10

    return {"cells": cells, "n_computed": len(p_values)}


def vix_regression(
    df: pd.DataFrame, n_resamples: int = 10_000,
) -> dict:
    """A1: OLS regression of excess_return on vix_at_entry."""
    valid = df.dropna(subset=["vix_at_entry", "excess_return"])
    x = valid["vix_at_entry"].values
    y = valid["excess_return"].values
    n = len(x)

    if n < MIN_CELL_SIZE:
        return {"status": "insufficient_data", "n": n}

    slope, intercept, r, p_value, se = stats.linregress(x, y)

    # Bootstrap CI on slope
    rng = np.random.default_rng(42)
    boot_slopes = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.choice(n, size=n, replace=True)
        s, _, _, _, _ = stats.linregress(x[idx], y[idx])
        boot_slopes[i] = s
    slope_ci_lower = float(np.percentile(boot_slopes, 2.5))
    slope_ci_upper = float(np.percentile(boot_slopes, 97.5))

    # Power analysis for slope
    x_std = float(np.std(x, ddof=1))
    y_std = float(np.std(y, ddof=1))
    mde = regression_slope_mde(n=n, x_std=x_std, y_std=y_std)

    return {
        "status": "computed",
        "n": n,
        "r": float(r),
        "r_squared": float(r ** 2),
        "slope": float(slope),
        "intercept": float(intercept),
        "p_value": float(p_value),
        "se": float(se),
        "slope_ci_lower": slope_ci_lower,
        "slope_ci_upper": slope_ci_upper,
        "mde_slope": mde,
        "mde_benchmark": MDE_BENCHMARK_BPS_PER_VIX,
        "is_underpowered": mde > MDE_BENCHMARK_BPS_PER_VIX,
        "vix_range": (float(np.min(x)), float(np.max(x))),
        "vix_std": x_std,
    }


def day_clustering(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A2: Per-calendar-day analysis + contiguous-run detection."""
    per_day = _stratified_analysis(df, "entry_date", n_resamples=n_resamples)

    day_means = []
    for label, group in sorted(df.groupby("entry_date")):
        day_means.append({
            "date": str(label),
            "n": len(group),
            "mean_excess": float(group["excess_return"].mean()),
        })

    bad_runs = _detect_bad_runs(df, day_means)

    return {
        "per_day": per_day,
        "day_means": day_means,
        "bad_runs": bad_runs,
    }


def _detect_bad_runs(df: pd.DataFrame, day_means: list[dict]) -> list[dict]:
    """Detect contiguous 2-3 day runs with mean excess < -1%."""
    bad_runs = []
    for i in range(len(day_means)):
        for run_len in (2, 3):
            if i + run_len > len(day_means):
                break
            run = day_means[i : i + run_len]
            total_n = sum(d["n"] for d in run)
            if total_n < MIN_CELL_SIZE:
                continue
            combined_excess = []
            for d in run:
                date_trades = df[df["entry_date"] == d["date"]]
                combined_excess.extend(
                    date_trades["excess_return"].tolist()
                )
            run_mean = float(np.mean(combined_excess))
            if run_mean < -1.0:
                dates = [d["date"] for d in run]
                events = _match_events(dates)
                bad_runs.append({
                    "dates": dates,
                    "n": total_n,
                    "mean_excess": run_mean,
                    "events": events,
                    "has_repeatable_category": len(events) > 0,
                })
    return bad_runs


def _match_events(dates: list[str]) -> list[dict]:
    """Match dates to known macro events."""
    events = []
    for d in dates:
        if d in KNOWN_EVENTS:
            evt = KNOWN_EVENTS[d]
            cat = EVENT_CATEGORIES.get(evt, "Unknown")
            events.append({"date": d, "event": evt, "category": cat})
    return events


def sector_rotation(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A3: Per-sector-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "sector_bucket", n_resamples=n_resamples)


def entry_time_analysis(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A4: Per-hour-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "hour_bucket", n_resamples=n_resamples)


def holding_period(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A5: Per-holding-period-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "duration_bucket", n_resamples=n_resamples)
