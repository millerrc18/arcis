"""Stage-1 honest baseline recompute (T1.02).

Audit spec §9 item 9: Stage-1 baseline Sharpe MUST be recomputed and reported
honestly — that is, with (a) quarantined rows excluded (T1.01 / T1.05),
(b) only fully-instrumented trades counted (T1.08), (c) the canonical
single-source-of-truth Sharpe formulas (T1.03), and (d) a 95% bootstrap CI +
power assessment so the operator knows whether the number is statistically
reliable. The output is a sign-off-pending memo at
audits/2026-04-27/stage1_baseline_memo.md.

The script ITSELF is read-only on the DB. The operator commits the memo with
`git commit -s` after reviewing it.

Three Sharpe figures (per §F-2 / T1.03):
  raw_sharpe                — pnl_pct series (no benchmark)
  spy_relative_sharpe       — pnl_pct minus per-period SPY return (in pct)
  rf_adjusted_excess_sharpe — pnl_pct minus per-period rf rate (constant for
                              now; T2.10 will swap in FRED 3-month T-bill)

Bootstrap: existing IID bootstrap from src/diagnostics/bootstrap.py — block
bootstrap (T2.02) is the Track-2 follow-up; the memo flags this dependency.

Constant rf rate (DA-9 fix): see RF_PERIOD_CONSTANT and RF_PERIOD_WINDOW
below — these are documented in the memo too.

Called by: operator (CLI). Not imported by other modules.
Calls: src.utils.db, src.analytics.canonical_sharpe, src.analytics.instrumentation_filter,
       src.diagnostics.bootstrap.
Owns tables: none.
Config keys: none.
Tests: tests/scripts/test_stage1_baseline.py.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from src.analytics.canonical_sharpe import (
    raw_sharpe,
    rf_adjusted_excess_sharpe,
    spy_relative_sharpe,
)
from src.analytics.instrumentation_filter import (
    UNDERPOWERED_MESSAGE,
    PowerAssessment,
    assess_statistical_power,
    filter_fully_instrumented,
)
from src.diagnostics.bootstrap import bootstrap_ci
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

# Methodology version hash (T1.03 commit). When T2.02 lands and this module
# starts using block bootstrap, append/replace with the T2.02 commit.
CANONICAL_SHARPE_SHA = "1928710"

# Constant rf rate placeholder (DA-9 fix). Per-period (daily) Treasury bill
# yield approximation. Annualized ~2.52% / 252 ~= 0.01% per trading day.
# Replaced by FRED 3-month T-bill DTB3 series once T2.10 lands.
RF_PERIOD_CONSTANT = 0.0001
RF_PERIOD_WINDOW = "2026-04-23 (single trading day approximation)"

# Memo template path (audit spec §9 item 9).
MEMO_DIR = Path("audits/2026-04-27")
MEMO_PATH = MEMO_DIR / "stage1_baseline_memo.md"


def fetch_closed_shadow_trades(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all rows from shadow_trades where status='closed'.

    Quarantined-vs-clean split happens downstream in compute_baseline so
    that the memo can report the exclusion count.
    """
    return conn.execute(
        """
        SELECT trade_id, recommendation_id, status,
               actual_entry_time, actual_exit_time,
               pnl_pct, spy_return_over_hold, excess_return,
               quarantined
        FROM shadow_trades
        WHERE status = 'closed'
        """
    ).fetchall()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def compute_baseline(conn: sqlite3.Connection) -> dict:
    """Compute the three Sharpe figures + bootstrap CIs + power assessment.

    Returns a dict with the structure consumed by build_memo().
    """
    rows = fetch_closed_shadow_trades(conn)
    n_total = len(rows)
    n_quarantined = sum(1 for r in rows if (r["quarantined"] or 0) == 1)

    # Drop quarantined first, then drop partial-instrumentation.
    non_quarantined = [
        _row_to_dict(r) for r in rows if (r["quarantined"] or 0) == 0
    ]
    instrumented = filter_fully_instrumented(non_quarantined)
    n_fully_instrumented = len(instrumented)

    # Per-period series: pnl_pct is in percent units; spy_return_over_hold is
    # a fraction (per src.analytics.spy_benchmark contract). Multiply SPY by
    # 100 so it lines up unit-wise with pnl_pct before subtracting.
    pnl_pcts = [float(r["pnl_pct"]) for r in instrumented]
    spy_pcts = [float(r["spy_return_over_hold"]) * 100.0 for r in instrumented]

    raw_sr = raw_sharpe(pnl_pcts)
    spy_rel_sr = spy_relative_sharpe(pnl_pcts, spy_pcts)
    rf_sr = rf_adjusted_excess_sharpe(pnl_pcts, RF_PERIOD_CONSTANT)

    # IID bootstrap on the per-period diff series (proxy for Sharpe CI).
    if n_fully_instrumented >= 2:
        raw_ci = bootstrap_ci(pnl_pcts)
        spy_ci = bootstrap_ci(
            [r - s for r, s in zip(pnl_pcts, spy_pcts)]
        )
        rf_ci = bootstrap_ci(
            [r - RF_PERIOD_CONSTANT for r in pnl_pcts]
        )
    else:
        empty_ci = {
            "point_estimate": None,
            "ci_lower": None,
            "ci_upper": None,
            "p_value": None,
        }
        raw_ci = dict(empty_ci)
        spy_ci = dict(empty_ci)
        rf_ci = dict(empty_ci)

    power = assess_statistical_power(n_fully_instrumented)

    return {
        "n_total": n_total,
        "n_quarantined": n_quarantined,
        "n_fully_instrumented": n_fully_instrumented,
        "raw_sharpe": raw_sr,
        "spy_relative_sharpe": spy_rel_sr,
        "rf_adjusted_excess_sharpe": rf_sr,
        "raw_sharpe_ci": raw_ci,
        "spy_relative_sharpe_ci": spy_ci,
        "rf_adjusted_excess_sharpe_ci": rf_ci,
        "power": power,
    }


def _format_sharpe(value: float | None) -> str:
    return "undefined (n<2 or zero variance)" if value is None else f"{value:.4f}"


def _format_ci(ci: dict) -> str:
    if ci.get("ci_lower") is None:
        return "[undefined, undefined] (insufficient sample)"
    return (
        f"[{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}] "
        f"(point={ci['point_estimate']:.4f}, p={ci['p_value']:.4f})"
    )


def build_memo(result: dict) -> str:
    """Render the Stage-1 baseline memo per audit-spec §9 item 9.

    Output is markdown, one section per required content item. The memo is
    NOT signed off here — operator commits with `git commit -s`.
    """
    power: PowerAssessment = result["power"]
    n = result["n_fully_instrumented"]

    underpowered_block = ""
    if n < power.mintrl_required:
        underpowered_block = f"\n> {UNDERPOWERED_MESSAGE}\n"

    lines = [
        "# Stage-1 Baseline Recompute Memo",
        "",
        f"**Date:** 2026-04-27",
        f"**Audit spec:** §9 item 9 (honest Stage-1 Sharpe)",
        f"**Generator:** scripts/stage1_baseline_recompute.py (T1.02)",
        "",
        "## Trade Counts",
        "",
        f"- N total closed shadow_trades in window: **{result['n_total']}**",
        f"- N quarantined (excluded; pre-#651 cascade per T1.01): **{result['n_quarantined']}**",
        f"- N fully-instrumented (per T1.08 four-column predicate): **{result['n_fully_instrumented']}**",
        "",
        "## Three Sharpe Figures (canonical, T1.03 / §F-2)",
        "",
        "All Sharpe values are annualized (sqrt(252)), sample stdev (ddof=1).",
        "",
        f"### 1. raw_sharpe (no benchmark)",
        "",
        f"- Point estimate: **{_format_sharpe(result['raw_sharpe'])}**",
        f"- 95% bootstrap CI (IID, n_resamples=10000) on per-period mean return:",
        f"  {_format_ci(result['raw_sharpe_ci'])}",
        "",
        f"### 2. spy_relative_sharpe (vs SPY total return)",
        "",
        f"- Point estimate: **{_format_sharpe(result['spy_relative_sharpe'])}**",
        f"- 95% bootstrap CI (IID) on per-period (pnl_pct - spy_pct) diff series:",
        f"  {_format_ci(result['spy_relative_sharpe_ci'])}",
        f"- Per-period SPY return is `spy_return_over_hold` from the row "
        f"(src.analytics.spy_benchmark; close-to-close auto-adjusted).",
        "",
        f"### 3. rf_adjusted_excess_sharpe (canonical, vs FRED 3-month T-bill)",
        "",
        f"- Point estimate: **{_format_sharpe(result['rf_adjusted_excess_sharpe'])}**",
        f"- 95% bootstrap CI (IID) on per-period (pnl_pct - rf) diff series:",
        f"  {_format_ci(result['rf_adjusted_excess_sharpe_ci'])}",
        f"- **Inline rf constant (DA-9 fix; pending T2.10 FRED integration):**",
        f"  - rf_period (per-period, daily): `{RF_PERIOD_CONSTANT}`",
        f"  - Window: `{RF_PERIOD_WINDOW}`",
        f"  - Source: placeholder constant — T2.10 will swap in the FRED 3-month "
        f"T-bill (DTB3) series with proper per-day interpolation. Until then, "
        f"this single-day approximation is the documented assumption.",
        "",
        "## Bootstrap Methodology",
        "",
        f"- Engine: `src.diagnostics.bootstrap.bootstrap_ci` (IID percentile bootstrap, "
        f"10,000 resamples, seed=42).",
        f"- **Caveat:** IID bootstrap assumes per-period returns are independent. For "
        f"trades with overlapping holding periods this assumption is violated; the "
        f"reported CIs are therefore optimistic. Block bootstrap (T2.02) is the "
        f"Track-2 follow-up that addresses this.",
        "",
        "## Power Assessment (T1.08, Bailey-LdP MinTRL)",
        "",
        f"- N (fully-instrumented): **{n}**",
        f"- MinTRL (target Sharpe = 0, alpha = 0.05): **{power.mintrl_required:.4f}**",
        f"- Verdict: **{power.status.upper()}**",
        f"- Detail: {power.message}",
        underpowered_block,
        "",
        "## Methodology Version Hashes",
        "",
        f"- Canonical Sharpe module SHA (T1.03): `{CANONICAL_SHARPE_SHA}`",
        f"- Block-bootstrap (T2.02) SHA: *pending — Track 2 dependency*",
        f"- FRED rf-rate series version (T2.10): *pending — Track 2 dependency*",
        "",
        "## Pre-#651 Row Exclusion",
        "",
        f"- Quarantined rows excluded (pre-#651 cascade, T1.01): **{result['n_quarantined']}**",
        f"- Cutoff: `2026-04-22T20:00:00-04:00` (per scripts/quarantine_pre_651.py).",
        "",
        "## Stage-2 Promotion Bootstrap CI (placeholder)",
        "",
        "*This section is reserved for the block-bootstrap CI numbers produced once "
        "T2.02 (block bootstrap) lands. Until then, the IID figures above are the "
        "best-available estimate and should NOT be used as a Stage-2 promotion gate.*",
        "",
        "## Sign-off",
        "",
        "Sign-off is NOT performed by the script. Operator must review this memo "
        "and commit with `git commit -s` to attach a Signed-off-by trailer.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage-1 honest baseline recompute. Reads closed shadow_trades, "
                    "drops quarantined + partial-instrumentation rows, computes three "
                    "Sharpe figures with bootstrap CIs + Bailey-LdP MinTRL power "
                    "assessment, writes memo to audits/2026-04-27/stage1_baseline_memo.md."
    )
    parser.add_argument(
        "--db", default=None,
        help="Override DB path (default: src.config.DB_PATH).",
    )
    parser.add_argument(
        "--out", default=str(MEMO_PATH),
        help=f"Output memo path (default: {MEMO_PATH}).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect_db(args.db) if args.db else connect_db()

    try:
        result = compute_baseline(conn)
        memo = build_memo(result)
    finally:
        conn.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(memo, encoding="utf-8")

    logger.info("[stage1_baseline] N total=%d, quarantined=%d, instrumented=%d",
                result["n_total"], result["n_quarantined"],
                result["n_fully_instrumented"])
    logger.info("[stage1_baseline] Memo written to %s", out_path)
    logger.info("[stage1_baseline] Sign off with: git commit -s %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
