"""Matplotlib plot generation for regime diagnostic v1.

Generates 6 PNG plots saved to the plot directory:
1. VIX regression scatter with CI band
2. Per-calendar-day excess return bars
3. Per-sector excess-Sharpe bars
4. Per-hour-bucket excess-Sharpe bars
5. Per-holding-period excess-Sharpe bars
6. Cumulative P&L curve with day annotations

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: matplotlib
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py (smoke test)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_vix_regression(
    df: pd.DataFrame, result: dict, plot_dir: Path,
) -> Path:
    """A1: Scatter of excess_return vs vix_at_entry with regression line."""
    fig, ax = plt.subplots(figsize=(8, 5))
    valid = df.dropna(subset=["vix_at_entry", "excess_return"])
    ax.scatter(valid["vix_at_entry"], valid["excess_return"],
               alpha=0.6, s=40, c="#3B82F6", edgecolors="white", linewidths=0.5)
    if result.get("status") == "computed":
        x_range = np.linspace(float(valid["vix_at_entry"].min()) - 0.5,
                              float(valid["vix_at_entry"].max()) + 0.5, 100)
        y_hat = result["slope"] * x_range + result["intercept"]
        ax.plot(x_range, y_hat, color="#EF4444", linewidth=2,
                label=f"slope={result['slope']:.3f} (p={result['p_value']:.3f})")
        ax.fill_between(x_range,
                        result["slope_ci_lower"] * x_range + result["intercept"],
                        result["slope_ci_upper"] * x_range + result["intercept"],
                        alpha=0.15, color="#EF4444")
        ax.legend(fontsize=9)
    ax.set_xlabel("VIX at Entry (prior day close)")
    ax.set_ylabel("Excess Return vs SPY (%)")
    ax.set_title("A1: Excess Return vs VIX at Entry")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    path = plot_dir / "a1_vix_regression.png"
    _save(fig, path)
    return path


def plot_day_clustering(
    df: pd.DataFrame, result: dict, plot_dir: Path,
) -> Path:
    """A2: Per-calendar-day mean excess return bars."""
    day_means = result["day_means"]
    dates = [d["date"][5:] for d in day_means]
    means = [d["mean_excess"] for d in day_means]
    ns = [d["n"] for d in day_means]
    colors = ["#EF4444" if m < -1.0 else "#3B82F6" for m in means]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(dates, means, color=colors, edgecolor="white", linewidth=0.5)
    for bar, n in zip(bars, ns):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"n={n}", ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Entry Date")
    ax.set_ylabel("Mean Excess Return (%)")
    ax.set_title("A2: Per-Day Mean Excess Return")
    plt.xticks(rotation=45, ha="right")
    path = plot_dir / "a2_day_clustering.png"
    _save(fig, path)
    return path


def plot_cumulative_pnl(df: pd.DataFrame, plot_dir: Path) -> Path:
    """A2 companion: Cumulative excess P&L curve."""
    sorted_df = df.sort_values("actual_entry_time")
    cum_excess = sorted_df["excess_return"].cumsum()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(cum_excess)), cum_excess.values,
            color="#3B82F6", linewidth=1.5)
    ax.fill_between(range(len(cum_excess)), 0, cum_excess.values,
                    alpha=0.1, color="#3B82F6")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Trade # (chronological)")
    ax.set_ylabel("Cumulative Excess Return (%)")
    ax.set_title("Cumulative Excess Return vs SPY")
    path = plot_dir / "a2_cumulative_pnl.png"
    _save(fig, path)
    return path


def _bar_chart_with_ci(
    result: dict, title: str, filename: str, plot_dir: Path,
) -> Path:
    """Generic bar chart for stratified analyses (A3, A4, A5)."""
    cells = result["cells"]
    computed = [c for c in cells if c["status"] == "computed"]
    if not computed:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.text(0.5, 0.5, "No cells with n >= 5", ha="center",
                va="center", transform=ax.transAxes, fontsize=14)
        ax.set_title(title)
        path = plot_dir / filename
        _save(fig, path)
        return path

    labels = [c["label"] for c in computed]
    means = [c["point_estimate"] for c in computed]
    ci_low = [c["ci_lower"] for c in computed]
    ci_high = [c["ci_upper"] for c in computed]
    ns = [c["n"] for c in computed]
    errors_low = [m - lo for m, lo in zip(means, ci_low)]
    errors_high = [hi - m for m, hi in zip(means, ci_high)]

    colors = []
    for c in computed:
        if c.get("survives_fdr"):
            colors.append("#10B981")
        elif c["p_value"] < 0.05:
            colors.append("#F59E0B")
        else:
            colors.append("#6B7280")

    fig, ax = plt.subplots(figsize=(8, 5))
    x = range(len(labels))
    ax.bar(x, means, color=colors, edgecolor="white", linewidth=0.5)
    ax.errorbar(x, means, yerr=[errors_low, errors_high],
                fmt="none", color="black", capsize=4, linewidth=1)
    for i, n in enumerate(ns):
        y_pos = means[i] + errors_high[i]
        ax.text(i, y_pos, f"n={n}", ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Mean Excess Return (%) with 95% CI")
    ax.set_title(title)
    path = plot_dir / filename
    _save(fig, path)
    return path


def plot_sector(result: dict, plot_dir: Path) -> Path:
    """A3: Per-sector excess-Sharpe bars with CIs."""
    return _bar_chart_with_ci(
        result, "A3: Excess Return by Sector", "a3_sector.png", plot_dir,
    )


def plot_entry_time(result: dict, plot_dir: Path) -> Path:
    """A4: Per-hour-bucket bars with CIs."""
    return _bar_chart_with_ci(
        result, "A4: Excess Return by Entry Time", "a4_entry_time.png", plot_dir,
    )


def plot_holding_period(result: dict, plot_dir: Path) -> Path:
    """A5: Per-holding-period bars with CIs."""
    return _bar_chart_with_ci(
        result, "A5: Excess Return by Holding Period",
        "a5_holding_period.png", plot_dir,
    )
