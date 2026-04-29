"""Attribution Readout v1 -- read-only diagnostic of attribution_trades.

Produces a descriptive markdown report on selection alpha (LLM-taken vs
LLM-rejected ranker-only counterfactuals). Read-only via mode=ro URI.
Usage: python scripts/diagnostics/attribution_readout.py [--db PATH --out PATH]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from scipy import stats

DEFAULT_ARCHIVE = Path("C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3")
DEFAULT_OUTPUT = Path("audits/attribution-readout-2026-04-28.md")

NUMERICAL_FILTER = (
    "ranker_only_outcome IN ('win','loss','timeout') "
    "AND ranker_only_pnl_pct IS NOT NULL "
    "AND COALESCE(resolution_version, '') != 'v1_multiindex_bug'"
)


def connect_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)


def _fmt(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6f}" if abs(v) < 0.01 else f"{v:.4f}"
    return str(v)


def table_md(headers: list[str], rows: list[list]) -> str:
    head = "| " + " | ".join(str(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    if not rows:
        return "\n".join([head, sep, "| _(empty)_ |" + " |".join([""] * len(headers))])
    body = "\n".join("| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows)
    return "\n".join([head, sep, body])


def section_1_coverage(con: sqlite3.Connection) -> str:
    row = con.execute("""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT attribution_id) AS distinct_ids,
               SUM(CASE WHEN ranker_only_outcome IN ('win','loss','timeout') THEN 1 ELSE 0 END) AS resolved,
               SUM(CASE WHEN ranker_only_outcome = 'pending' OR ranker_only_outcome IS NULL THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN ranker_only_outcome IN ('win','loss','timeout') AND ranker_only_pnl_pct IS NULL THEN 1 ELSE 0 END) AS null_pnl_resolved,
               SUM(CASE WHEN resolution_version = 'v1_multiindex_bug' THEN 1 ELSE 0 END) AS bug_tagged,
               SUM(CASE WHEN resolution_version IS NULL THEN 1 ELSE 0 END) AS null_resolution,
               SUM(CASE WHEN llm_action='taken' AND llm_conviction IS NULL THEN 1 ELSE 0 END) AS null_conv_taken,
               MIN(scan_timestamp) AS dmin,
               MAX(scan_timestamp) AS dmax
        FROM attribution_trades
    """).fetchone()
    total, did, res, pen, npr, bug, nrv, nct, dmin, dmax = row
    receipts = [
        ["total_rows", total], ["distinct_attribution_id", did],
        ["resolved (outcome win/loss/timeout)", res],
        ["pending (outcome='pending' or NULL)", pen],
        ["resolution_rate", f"{res/total:.4f}" if total else "—"],
        ["null_pnl_pct in resolved rows", npr],
        ["resolution_version='v1_multiindex_bug'", bug],
        ["resolution_version IS NULL", nrv],
        ["null_conviction in llm_action='taken'", nct],
        ["scan_timestamp earliest", dmin], ["scan_timestamp latest", dmax],
    ]
    action_dist = list(con.execute(
        "SELECT COALESCE(llm_action,'(NULL)'), COUNT(*) FROM attribution_trades "
        "GROUP BY llm_action ORDER BY COUNT(*) DESC"
    ))
    return "\n".join([
        "## 1. Sample size & coverage\n",
        table_md(["metric", "value"], receipts),
        "\n### llm_action distribution (raw)\n",
        table_md(["llm_action", "n"], [list(r) for r in action_dist]),
    ])


def section_2_outcome_by_action(con: sqlite3.Connection) -> str:
    rows = list(con.execute(f"""
        SELECT llm_action, ranker_only_outcome, COUNT(*),
               AVG(ranker_only_pnl_pct), MIN(ranker_only_pnl_pct), MAX(ranker_only_pnl_pct)
        FROM attribution_trades
        WHERE {NUMERICAL_FILTER}
        GROUP BY llm_action, ranker_only_outcome
        ORDER BY llm_action, ranker_only_outcome
    """))
    return "\n".join([
        "## 2. Outcome breakdown by LLM action\n",
        "_Filter: resolved (win/loss/timeout), pnl_pct present, not `v1_multiindex_bug`._\n",
        table_md(
            ["llm_action", "ranker_only_outcome", "n", "avg pnl_pct", "min", "max"],
            [list(r) for r in rows],
        ),
    ])


def _band(c) -> str:
    """Bucket a conviction value on the canonical 1-10 scale (#847).

    Earlier versions banded 0-49 / 50-69 / 70-84 / 85+, modeled on the
    ranker_score scale (0-100). But llm_conviction is parsed on a 1-10
    scale by src/llm/packet_writer.py:451 (clamped via max(1, min(10, .))),
    so all real values trivially fell into the 0-49 bucket — making the
    band table appear fully degenerate when it was actually a scale
    mismatch. The 1-10 band cuts mirror the LLM's prompt vocabulary
    (low / medium / high / very-high conviction).
    """
    if c is None:
        return "null"
    if c <= 3:
        return "1-3 (low)"
    if c <= 6:
        return "4-6 (medium)"
    if c <= 8:
        return "7-8 (high)"
    return "9-10 (very high)"


def section_3_conviction_bands(con: sqlite3.Connection) -> str:
    rows = list(con.execute(f"""
        SELECT llm_conviction, ranker_only_outcome, ranker_only_pnl_pct
        FROM attribution_trades
        WHERE llm_action='taken' AND {NUMERICAL_FILTER}
    """))
    bands: dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "pnls": []})
    for c, outcome, pnl in rows:
        b = bands[_band(c)]
        b["n"] += 1
        b["wins"] += int(outcome == "win")
        b["pnls"].append(pnl)
    body = []
    for label in ["null", "1-3 (low)", "4-6 (medium)", "7-8 (high)", "9-10 (very high)"]:
        b = bands.get(label, {"n": 0, "wins": 0, "pnls": []})
        avg_pnl = mean(b["pnls"]) if b["pnls"] else None
        body.append([label, b["n"], b["wins"], avg_pnl])
    # Caveat — conviction=5 is the parser's parse-failure fallback (set
    # in src/llm/packet_writer.py:692,701,710 when the LLM response can't
    # be parsed). Any concentration in the 4-6 band may include real medium
    # AND parse-failure pollution. Disambiguating requires a separate
    # parse_failed column or NULL-on-failure semantics — see follow-up.
    return "\n".join([
        "## 3. Conviction-banded analysis (LLM `taken` only)\n",
        "_Filter: resolved + pnl_pct present + not `v1_multiindex_bug` + llm_action='taken'._\n",
        "_Scale: 1-10 (per `src/llm/packet_writer.py` clamp). Caveat: conviction=5 is the parser's parse-failure fallback — the 4-6 band conflates real medium conviction with parse-failure pollution._\n",
        table_md(["band", "n", "ranker-only wins", "avg ranker-only pnl_pct"], body),
    ])


def _selection_alpha(con: sqlite3.Connection, where_extra: str = "") -> dict:
    sql = (f"SELECT llm_action, ranker_only_pnl_pct FROM attribution_trades "
           f"WHERE {NUMERICAL_FILTER} AND llm_action IN ('taken','rejected') {where_extra}")
    pnls: dict[str, list[float]] = defaultdict(list)
    for action, pnl in con.execute(sql):
        pnls[action].append(pnl)
    taken, rejected = pnls["taken"], pnls["rejected"]
    out = {
        "n_taken": len(taken),
        "n_rejected": len(rejected),
        "mean_taken": mean(taken) if taken else None,
        "mean_rejected": mean(rejected) if rejected else None,
        "delta": None,
        "t_stat": None,
        "p_value": None,
        "test": "Welch two-sample t-test (two-sided)",
    }
    if taken and rejected:
        out["delta"] = out["mean_taken"] - out["mean_rejected"]
        t_stat, p_value = stats.ttest_ind(taken, rejected, equal_var=False)
        out["t_stat"], out["p_value"] = float(t_stat), float(p_value)
    else:
        out["test"] = "skipped — one or both groups empty"
    return out


def section_4_selection_alpha(con: sqlite3.Connection) -> str:
    res = _selection_alpha(con)
    return "\n".join([
        "## 4. Selection alpha test\n",
        "_Compare ranker_only_pnl_pct of llm_action='taken' vs 'rejected'._\n",
        table_md(["metric", "value"], [[k, v] for k, v in res.items()]),
        "\nTest: Welch's two-sample t-test (unequal variances), two-sided.",
        "Interpretation guide (operator-side, NOT a verdict from this script):",
        "p < 0.05 with positive `delta` indicates the LLM-taken trades had",
        "statistically different ranker-only outcomes than the rejected",
        "counterfactuals. The numbers are descriptive — drawing a conclusion",
        "is the operator's call.",
    ])


def section_5_time_split(con: sqlite3.Connection) -> str:
    date_min, date_max = con.execute(
        "SELECT MIN(scan_timestamp), MAX(scan_timestamp) FROM attribution_trades"
    ).fetchone()
    midpoint = datetime.fromisoformat(date_min) + (
        datetime.fromisoformat(date_max) - datetime.fromisoformat(date_min)) / 2
    midpoint_iso = midpoint.isoformat()
    half1 = _selection_alpha(con, f"AND scan_timestamp < '{midpoint_iso}'")
    half2 = _selection_alpha(con, f"AND scan_timestamp >= '{midpoint_iso}'")
    keys = ["n_taken", "n_rejected", "mean_taken", "mean_rejected",
            "delta", "t_stat", "p_value", "test"]
    body = [[k, half1.get(k), half2.get(k)] for k in keys]
    return "\n".join([
        "## 5. Time-stratified replication\n",
        f"Midpoint: `{midpoint_iso}`",
        f"- First half:  `[{date_min}, {midpoint_iso})`",
        f"- Second half: `[{midpoint_iso}, {date_max}]`\n",
        table_md(["metric", "first half", "second half"], body),
        "\nIf the overall §4 result is driven by a single regime, one half will",
        "carry the signal while the other is flat or reversed. Reporting the",
        "two halves independently exposes that failure mode.",
    ])


NOTES = [
    "## Notes & caveats",
    "- Numerical aggregates exclude `resolution_version='v1_multiindex_bug'` and rows with `ranker_only_pnl_pct IS NULL`.",
    "- This archive (2026-04-24) predates the `quarantined` column added 2026-04-27 (audit-2026-04-27 §F-1, T1.05). No quarantine filter applied.",
    "- `resolution_version IS NULL` rows are kept (legacy pre-tagging). Count surfaced in §1 as a data-quality flag.",
    "- §4 / §5 use only `llm_action IN ('taken','rejected')`. Other values (`buy`, `skip`, `pending`) appear in §1/§2 but are excluded from the t-test by design.",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Attribution readout (read-only).")
    parser.add_argument("--db", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2
    con = connect_ro(args.db)
    sections = [
        "# Attribution readout — bootcamp archive 2026-04-24",
        f"_Generated 2026-04-28. Read-only diagnostic. DB: `{args.db}`._",
        "",
        section_1_coverage(con),
        section_2_outcome_by_action(con),
        section_3_conviction_bands(con),
        section_4_selection_alpha(con),
        section_5_time_split(con),
        "",
        "\n".join(NOTES),
    ]
    md = "\n\n".join(sections) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    sys.stdout.write(md)
    print(f"\n[wrote {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
