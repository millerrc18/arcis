"""Markdown report generator for regime diagnostic v1.

Produces a structured diagnostic report with:
- Executive summary (3 paragraphs, leads with decision)
- Methodology (including bootcamp-mode caveat)
- Aggregate stats with bootstrap CI
- A1-A5 results tables
- Power analysis
- Decision recommendation

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations


def _fmt(v: object, decimals: int = 3) -> str:
    """Format a numeric value, handling None."""
    if v is None:
        return "\u2014"
    return f"{float(v):.{decimals}f}"  # type: ignore[arg-type]


def _cell_table(cells: list[dict]) -> str:
    """Render a list of cell results as a markdown table."""
    if not cells:
        return "*No cells to display.*\n"
    lines = [
        "| Cell | n | Mean Excess (%) | 95% CI | p-value "
        "| FDR-adj p | Survives FDR | MDE | Underpowered |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cells:
        if c["status"] == "insufficient_data":
            lines.append(
                f"| {c['label']} | {c['n']} "
                f"| \u2014 | \u2014 | \u2014 | \u2014 | \u2014 | \u2014 "
                f"| insufficient data |"
            )
        else:
            ci = f"[{_fmt(c['ci_lower'])}, {_fmt(c['ci_upper'])}]"
            p_adj = _fmt(c.get("p_adjusted"), 4)
            fdr = "Yes" if c.get("survives_fdr") else "No"
            underpowered = "Yes" if c.get("is_underpowered") else "No"
            lines.append(
                f"| {c['label']} | {c['n']} | {_fmt(c['point_estimate'])} "
                f"| {ci} | {_fmt(c['p_value'], 4)} | {p_adj} | {fdr} "
                f"| {_fmt(c.get('mde'))} | {underpowered} |"
            )
    return "\n".join(lines) + "\n"


def _write_header(results: dict, date_str: str) -> str:
    """Report header with N and decision."""
    decision = results["decision"]
    return (
        f"# Regime Diagnostic v1 \u2014 {date_str}\n\n"
        f"**N = {results['n_total']}** closed trades | "
        f"**Decision: {decision}**\n"
    )


def _write_executive_summary(results: dict) -> str:
    """Executive summary leading with decision."""
    agg = results["aggregate_ci"]
    lines = [
        "## Executive Summary\n",
        f"**Recommendation: {results['decision']}.** "
        f"{results['decision_rationale']}\n",
        f"The incumbent pullback-in-uptrend strategy produced a mean excess "
        f"return of {_fmt(results['mean_excess'])}% vs SPY across "
        f"{results['n_total']} closed trades (95% CI: "
        f"[{_fmt(agg['ci_lower'])}, {_fmt(agg['ci_upper'])}], "
        f"p = {_fmt(agg['p_value'], 4)}).\n",
    ]
    if results.get("quarantine_note"):
        lines.append(
            f"**Quarantine note:** {results['quarantine_note']}\n"
        )
    return "\n".join(lines)


def _write_methodology() -> str:
    """Methodology section with bootcamp-mode caveat."""
    return (
        "## Methodology\n\n"
        "- **Data source:** `shadow_trades` table "
        "(closed trades with exit and P&L)\n"
        "- **Excess return:** `pnl_pct - (spy_return_over_hold * 100)` "
        "(computed by D1 backfill)\n"
        "- **VIX:** ^VIX close on `entry_date - 1` trading day "
        "(yfinance, no look-ahead)\n"
        "- **Bootstrap:** 10,000 resamples, percentile method, 95% CI\n"
        "- **FDR:** Benjamini-Hochberg at q = 0.10\n"
        "- **Power:** Minimum detectable effect at 80% power, "
        "5% significance\n"
        "- **Minimum cell size:** n >= 5 "
        "(cells below this are marked 'insufficient data')\n\n"
        "**Bootcamp-mode caveat:** These trades were generated under "
        "bootcamp-mode relaxed thresholds (e.g., no conviction floors, "
        "no sector caps). Findings about regime contamination or null "
        "hypothesis apply to the bootcamp-mode strategy, not necessarily "
        "to the strict-mode version that would trade real capital. The "
        "diagnostic tests whether the bootcamp-mode strategy has any "
        "alpha signal worth filtering for.\n"
    )


def _write_aggregate_stats(results: dict) -> str:
    """Aggregate statistics table + data quality notes."""
    agg = results["aggregate_ci"]
    lines = [
        "## Aggregate Statistics\n",
        f"| Metric | Value |\n|---|---|\n"
        f"| N (closed trades) | {results['n_total']} |\n"
        f"| Mean excess return | {_fmt(results['mean_excess'])}% |\n"
        f"| 95% CI | [{_fmt(agg['ci_lower'])}, "
        f"{_fmt(agg['ci_upper'])}] |\n"
        f"| p-value (H0: mean = 0) | {_fmt(agg['p_value'], 4)} |\n",
    ]
    vix_flags = results.get("vix_flags", [])
    if vix_flags:
        lines.append("### Data Quality Notes\n")
        lines.append(
            "VIX cross-check: the following trades have `vix_at_entry` "
            "values that differ from yfinance ^VIX by more than "
            "0.5 points:\n"
        )
        lines.append(
            "| Trade ID | Stored | yfinance | Diff |\n|---|---|---|---|\n"
        )
        for f in vix_flags:
            lines.append(
                f"| {f['trade_id'][:8]}... | {_fmt(f['stored'], 1)} "
                f"| {_fmt(f['expected'], 1)} | {_fmt(f['diff'], 1)} |\n"
            )
    return "\n".join(lines)


def _write_a1_vix(a1: dict) -> str:
    """A1: VIX regression section."""
    lines = ["## A1: VIX Regression\n"]
    if a1.get("status") == "computed":
        lines.append(
            f"OLS: `excess_return = {_fmt(a1['slope'])} * vix + "
            f"{_fmt(a1['intercept'])}`\n\n"
            f"| Metric | Value |\n|---|---|\n"
            f"| r | {_fmt(a1['r'])} |\n"
            f"| r-squared | {_fmt(a1['r_squared'], 4)} |\n"
            f"| Slope | {_fmt(a1['slope'])} |\n"
            f"| Slope 95% CI | [{_fmt(a1['slope_ci_lower'])}, "
            f"{_fmt(a1['slope_ci_upper'])}] |\n"
            f"| p-value | {_fmt(a1['p_value'], 4)} |\n"
            f"| VIX range | {_fmt(a1['vix_range'][0], 1)} - "
            f"{_fmt(a1['vix_range'][1], 1)} |\n"
            f"| MDE (slope) | {_fmt(a1['mde_slope'])} %/VIX-point |\n"
            f"| Benchmark | {a1['mde_benchmark']} %/VIX-point |\n"
            f"| Underpowered? | "
            f"{'Yes' if a1['is_underpowered'] else 'No'} |\n"
        )
        if a1["is_underpowered"]:
            lines.append(
                f"\n**Note:** MDE ({_fmt(a1['mde_slope'])} %/VIX-point) "
                f"exceeds benchmark ({a1['mde_benchmark']} %/VIX-point). "
                f"This analysis is underpowered \u2014 its null result "
                f"should be interpreted as 'insufficient evidence', not "
                f"'no relationship'.\n"
            )
    else:
        lines.append("*Insufficient data for VIX regression.*\n")
    lines.append("\n![VIX Regression](a1_vix_regression.png)\n")
    return "\n".join(lines)


def _write_a2_days(a2: dict) -> str:
    """A2: Trade-day clustering section."""
    lines = [
        "## A2: Trade-Day Clustering\n",
        "### Per-Day Results\n",
        _cell_table(a2["per_day"]["cells"]),
    ]
    if a2["bad_runs"]:
        lines.append("### Contiguous Bad Runs (mean excess < -1%)\n")
        for run in a2["bad_runs"]:
            dates = ", ".join(run["dates"])
            lines.append(
                f"- **{dates}** (n={run['n']}, "
                f"mean excess={_fmt(run['mean_excess'])}%)"
            )
            if run["events"]:
                evts = ", ".join(
                    f"{e['event']} ({e['category']})"
                    for e in run["events"]
                )
                lines.append(f"  - Matched events: {evts}")
            else:
                lines.append("  - No matched macro events")
            lines.append(
                f"  - Repeatable category: "
                f"{'Yes' if run['has_repeatable_category'] else 'No'}"
            )
            lines.append("")
    else:
        lines.append(
            "*No contiguous bad runs detected (mean excess < -1%).*\n"
        )
    lines.append("\n![Day Clustering](a2_day_clustering.png)\n")
    lines.append("![Cumulative P&L](a2_cumulative_pnl.png)\n")
    return "\n".join(lines)


def _write_stratified_section(
    label: str, cells: list[dict], plot: str,
) -> str:
    """A3/A4/A5: Generic stratified analysis section."""
    return (
        f"## {label}\n\n"
        f"{_cell_table(cells)}\n"
        f"\n![{label}]({plot})\n"
    )


def _write_power_analysis(results: dict) -> str:
    """Power analysis summary across all cell analyses."""
    a1 = results["a1_vix"]
    lines = ["## Power Analysis\n"]
    all_cells: list[dict] = []
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        all_cells.extend(results[key]["cells"])
    computed = [c for c in all_cells if c["status"] == "computed"]
    if computed:
        lines.append(
            "| Cell | n | MDE (excess-Sharpe) "
            "| Underpowered (MDE > 0.5)? |\n"
            "|---|---|---|---|\n"
        )
        for c in computed:
            up = "Yes" if c.get("is_underpowered") else "No"
            lines.append(
                f"| {c['label']} | {c['n']} "
                f"| {_fmt(c.get('mde'))} | {up} |\n"
            )
    lines.append(
        f"\nVIX regression MDE: {_fmt(a1.get('mde_slope'))} "
        f"%/VIX-point (benchmark: "
        f"{a1.get('mde_benchmark', 0.3)} %/VIX-point, "
        f"underpowered: "
        f"{'Yes' if a1.get('is_underpowered') else 'No'})\n"
    )
    return "\n".join(lines)


def _write_decision(results: dict) -> str:
    """Final decision section."""
    return (
        "## Decision\n\n"
        f"**{results['decision']}**\n\n"
        f"{results['decision_rationale']}\n"
    )


def generate_report(results: dict, date_str: str) -> str:
    """Generate the full markdown diagnostic report.

    Orchestrates section helpers into a single markdown string.
    """
    sections = [
        _write_header(results, date_str),
        _write_executive_summary(results),
        _write_methodology(),
        _write_aggregate_stats(results),
        _write_a1_vix(results["a1_vix"]),
        _write_a2_days(results["a2_days"]),
        _write_stratified_section(
            "A3: Sector Rotation",
            results["a3_sector"]["cells"], "a3_sector.png",
        ),
        _write_stratified_section(
            "A4: Entry Time-of-Day",
            results["a4_hour"]["cells"], "a4_entry_time.png",
        ),
        _write_stratified_section(
            "A5: Holding Period",
            results["a5_holding"]["cells"], "a5_holding_period.png",
        ),
        _write_power_analysis(results),
        _write_decision(results),
    ]
    return "\n".join(sections)
