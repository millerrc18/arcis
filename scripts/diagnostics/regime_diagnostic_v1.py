"""Regime Diagnostic v1 -- CLI entry point.

Runs the full diagnostic pipeline: load trades, backfill VIX,
compute dimensions, run A1-A5 analyses, generate plots and report.

Usage:
    python scripts/diagnostics/regime_diagnostic_v1.py
    python scripts/diagnostics/regime_diagnostic_v1.py --exclude-quarantined
    python scripts/diagnostics/regime_diagnostic_v1.py --bootstrap-n 5000

Called by: operator (CLI)
Calls: src.diagnostics.*
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from src.diagnostics.dimensions import build_analysis_df  # noqa: E402
from src.diagnostics.bootstrap import bootstrap_ci  # noqa: E402
from src.diagnostics.analyses import (  # noqa: E402
    vix_regression,
    day_clustering,
    sector_rotation,
    entry_time_analysis,
    holding_period,
)
from src.diagnostics.plots import (  # noqa: E402
    plot_vix_regression,
    plot_day_clustering,
    plot_cumulative_pnl,
    plot_sector,
    plot_entry_time,
    plot_holding_period,
)
from src.diagnostics.report import generate_report  # noqa: E402


def _decide(results: dict) -> tuple[str, str]:
    """Determine CONTAMINATED / UNIFORMLY_NULL / PENDING."""
    fdr_survivors = []
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        for cell in results[key]["cells"]:
            if cell.get("survives_fdr"):
                fdr_survivors.append(cell)

    repeatable_runs = [
        r for r in results["a2_days"]["bad_runs"]
        if r["has_repeatable_category"]
    ]

    a1 = results["a1_vix"]
    vix_promising = (
        a1.get("status") == "computed"
        and a1.get("p_value", 1.0) < 0.05
    )
    vix_underpowered = a1.get("is_underpowered", True)

    if fdr_survivors or repeatable_runs:
        parts = []
        if fdr_survivors:
            labels = [c["label"] for c in fdr_survivors]
            parts.append(
                f"Cell(s) {', '.join(labels)} survive FDR correction "
                f"(q=0.10), indicating non-uniform excess return."
            )
        if repeatable_runs:
            for run in repeatable_runs:
                events = [e["event"] for e in run["events"]]
                parts.append(
                    f"Bad run {', '.join(run['dates'])} maps to "
                    f"repeatable event(s): {', '.join(events)}."
                )
        return "CONTAMINATED", " ".join(parts)

    if vix_promising and vix_underpowered:
        return "PENDING", (
            f"VIX regression shows a nominal relationship "
            f"(p={a1['p_value']:.4f}) but the analysis is underpowered "
            f"(MDE={a1['mde_slope']:.3f} %/VIX-point exceeds benchmark "
            f"{a1['mde_benchmark']}). Re-run at N>=150 with broader "
            f"VIX range."
        )

    all_underpowered = True
    any_computed = False
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        for cell in results[key]["cells"]:
            if cell["status"] == "computed":
                any_computed = True
                if not cell.get("is_underpowered", True):
                    all_underpowered = False

    if all_underpowered and any_computed:
        return "PENDING", (
            "All cell-level analyses are underpowered (MDE > 0.5 "
            "excess-Sharpe). Cannot distinguish between genuine null "
            "and insufficient sample size. Re-run at N>=150."
        )

    return "UNIFORMLY_NULL", (
        "No subsample cut (sector, time-of-day, day-cluster, holding "
        "period) shows excess return distinguishable from zero after "
        "FDR correction. The aggregate null is evenly distributed."
    )


def main() -> None:
    today = date.today().isoformat()
    default_db = "C:/arcis/data/ai_research_desk.sqlite3"

    parser = argparse.ArgumentParser(
        description="Regime Diagnostic v1"
    )
    parser.add_argument("--db", default=default_db)
    parser.add_argument("--output",
                        default=f"docs/diagnostics/regime-{today}.md")
    parser.add_argument("--plot-dir",
                        default=f"docs/diagnostics/regime-{today}/")
    parser.add_argument("--bootstrap-n", type=int, default=10_000)
    parser.add_argument("--exclude-quarantined", action="store_true")
    args = parser.parse_args()

    plot_dir = Path(args.plot_dir)
    plot_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[diagnostic] Loading trades from {args.db}")
    print(f"[diagnostic] Exclude quarantined: {args.exclude_quarantined}")

    df, vix_flags = build_analysis_df(
        args.db, exclude_quarantined=args.exclude_quarantined,
    )
    n_total = len(df)
    print(f"[diagnostic] Loaded {n_total} closed trades")
    if vix_flags:
        print(f"[diagnostic] VIX cross-check: {len(vix_flags)} discrepancies")

    mean_excess = float(df["excess_return"].mean())
    aggregate_ci = bootstrap_ci(
        df["excess_return"].values, n_resamples=args.bootstrap_n,
    )

    bn = args.bootstrap_n
    print("[diagnostic] Running A1: VIX regression...")
    a1 = vix_regression(df, n_resamples=bn)
    print("[diagnostic] Running A2: Day clustering...")
    a2 = day_clustering(df, n_resamples=bn)
    print("[diagnostic] Running A3: Sector rotation...")
    a3 = sector_rotation(df, n_resamples=bn)
    print("[diagnostic] Running A4: Entry time-of-day...")
    a4 = entry_time_analysis(df, n_resamples=bn)
    print("[diagnostic] Running A5: Holding period...")
    a5 = holding_period(df, n_resamples=bn)

    results: dict = {
        "n_total": n_total,
        "mean_excess": mean_excess,
        "aggregate_ci": aggregate_ci,
        "vix_flags": vix_flags,
        "a1_vix": a1,
        "a2_days": a2,
        "a3_sector": a3,
        "a4_hour": a4,
        "a5_holding": a5,
    }

    # Quarantine sensitivity note
    if not args.exclude_quarantined:
        q_count = (
            int(df["quarantined"].sum())
            if "quarantined" in df.columns else 0
        )
        if q_count > 0:
            results["quarantine_note"] = (
                f"{q_count} of {n_total} trades are quarantined "
                f"(April 10 cascade). Re-run with "
                f"--exclude-quarantined for sensitivity."
            )
    else:
        results["quarantine_note"] = (
            "Analysis excludes quarantined trades per "
            "--exclude-quarantined flag."
        )

    decision, rationale = _decide(results)
    results["decision"] = decision
    results["decision_rationale"] = rationale

    print(f"[diagnostic] Decision: {decision}")
    print("[diagnostic] Generating plots...")

    plot_vix_regression(df, a1, plot_dir)
    plot_day_clustering(df, a2, plot_dir)
    plot_cumulative_pnl(df, plot_dir)
    plot_sector(a3, plot_dir)
    plot_entry_time(a4, plot_dir)
    plot_holding_period(a5, plot_dir)

    print("[diagnostic] Generating report...")
    md = generate_report(results, today)
    output_path.write_text(md, encoding="utf-8")

    print(f"[diagnostic] Report: {output_path}")
    print(f"[diagnostic] Plots:  {plot_dir}")
    print(f"\n{'=' * 60}")
    print(f"DECISION: {decision}")
    print(f"{'=' * 60}")
    print(f"{rationale}")


if __name__ == "__main__":
    main()
