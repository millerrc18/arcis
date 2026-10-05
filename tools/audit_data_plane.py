"""S04 T1-T5, T7: Data plane audit.

Audits the S03 bars panel for coverage, adjustments, corporate actions,
availability, and survivorship. Produces aggregate statistics only.

Usage:
    python tools/audit_data_plane.py --data-root <DATA_ROOT>

Output: <data_root>/s04/audit_results.json (aggregate statistics only).

The pure-logic functions (compute_log_jump, is_adjusted, find_gaps,
is_late_starter) have no pandas dependency and are imported by
tests/test_data_plane.py. Pandas is imported lazily inside the
DataFrame-based functions so the module imports cleanly in CI.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# Known splits for adjustment verification (T3)
KNOWN_SPLITS = [
    # (symbol, split_date, ratio) — ratio = pre-split shares per post-split share
    ("AAPL", "2020-08-31", 4),   # 4:1
    ("TSLA", "2020-08-31", 5),   # 5:1
    ("NVDA", "2021-07-20", 4),   # 4:1
    ("AMZN", "2022-06-06", 20),  # 20:1
]

# Cutoff fallback for "late starter" when SPY's first date is unavailable
# (e.g., in unit tests). In audit_coverage, the cutoff is SPY's first date.
COVERAGE_CUTOFF = "2016-01-04"

# Threshold for "adjusted": |log jump| below this means no artificial split jump
ADJUSTMENT_THRESHOLD = 0.2


# ---------------------------------------------------------------------------
# Pure-logic functions (no pandas). Tested directly by tests/test_data_plane.py.
# ---------------------------------------------------------------------------

def compute_log_jump(before_close: float, after_close: float) -> float:
    """Absolute log price jump across a corporate-action date.

    An unadjusted 4:1 split shows |log| ≈ 1.39; an adjusted one shows a
    normal daily move (< 0.2).
    """
    return abs(math.log(after_close / before_close))


def is_adjusted(log_jump: float, threshold: float = ADJUSTMENT_THRESHOLD) -> bool:
    """True if the log jump is small enough to indicate adjustment."""
    return log_jump < threshold


def find_gaps(expected_dates: set[str], actual_dates: set[str]) -> list[str]:
    """Sorted list of expected dates missing from actual dates."""
    return sorted(expected_dates - actual_dates)


def is_late_starter(first_date: str, cutoff: str = COVERAGE_CUTOFF) -> bool:
    """True if the symbol's first bar is after the coverage cutoff."""
    return first_date > cutoff


def spy_covers_panel(spy_dates: set[str], panel_min: str, panel_max: str) -> bool:
    """True if SPY's date range covers the panel's full range.

    If SPY starts after panel_min or ends before panel_max, coverage
    gaps would be invisible — fail closed.
    """
    if not spy_dates:
        return False
    return min(spy_dates) <= panel_min and max(spy_dates) >= panel_max


def spy_missing_days(spy_dates: set[str],
                     constituent_dates: set[str]) -> list[str]:
    """Sorted dates where constituents traded but SPY has no bar.

    If non-empty, the SPY reference calendar is incomplete: those days
    are invisible to per-symbol gap detection. Fail closed.
    """
    return sorted(constituent_dates - spy_dates)


def adjustments_failed(results: list[dict]) -> bool:
    """True if any split check failed: missing data or unadjusted.

    Each result dict has either a 'status' key (error) or an 'adjusted'
    key (bool). Any error status or adjusted=False means failure.
    An empty results list is also a failure (nothing was checked) —
    fail closed if KNOWN_SPLITS is ever emptied.
    """
    if not results:
        return True
    for r in results:
        if "status" in r:
            return True
        if not r.get("adjusted", False):
            return True
    return False


# ---------------------------------------------------------------------------
# DataFrame-based functions (pandas imported lazily).
# ---------------------------------------------------------------------------

def _guard_data_root(data_root: str) -> None:
    """Refuse repo and cloud-sync paths (S01 invariant I-7).

    Resolve first so relative paths cannot bypass the check.
    Raises SystemExit(2) on violation.
    """
    resolved = Path(data_root).resolve()
    repo = Path(__file__).resolve().parent.parent
    if repo in resolved.parents or resolved == repo:
        print("REFUSING: data root inside the repo", file=sys.stderr)
        raise SystemExit(2)
    for sync in ("Dropbox", "OneDrive", "Google Drive", "iCloud"):
        if sync.lower() in str(resolved).lower():
            print(f"REFUSING: data root looks like a sync folder ({sync})",
                  file=sys.stderr)
            raise SystemExit(2)


def load_panel(data_root: str) -> pd.DataFrame:
    """Load all per-symbol bars into one DataFrame."""
    import pandas as pd

    bars_dir = os.path.join(data_root, "raw", "bars")
    if not os.path.isdir(bars_dir):
        print(f"ERROR: bars directory not found: {bars_dir}", file=sys.stderr)
        raise SystemExit(1)
    frames = []
    for fname in sorted(os.listdir(bars_dir)):
        if not fname.endswith(".parquet"):
            continue
        symbol = fname[:-len(".parquet")]
        df = pd.read_parquet(os.path.join(bars_dir, fname))
        df["symbol"] = symbol
        frames.append(df)
    if not frames:
        print("ERROR: no parquet files found", file=sys.stderr)
        raise SystemExit(1)
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["t"], utc=True)
    return panel.sort_values(["symbol", "date"]).reset_index(drop=True)


def _validate_spy(panel: pd.DataFrame) -> set[str]:
    """Validate SPY exists and covers the panel's full date range.

    SPY is the reference calendar for coverage. If SPY is missing, or if
    SPY's range doesn't cover the panel's range (start or end), exit
    non-zero — coverage gaps would be invisible.
    """
    spy = panel[panel["symbol"] == "SPY"]
    if len(spy) == 0:
        print("ERROR: SPY not in panel; cannot build reference calendar",
              file=sys.stderr)
        raise SystemExit(1)
    spy_dates = set(spy["date"].dt.date.astype(str))
    panel_min = panel["date"].min().date().isoformat()
    panel_max = panel["date"].max().date().isoformat()
    if not spy_covers_panel(spy_dates, panel_min, panel_max):
        # Fail closed: days outside SPY's range would be invisible in coverage.
        print(f"ERROR: SPY range [{min(spy_dates)}, {max(spy_dates)}] does not "
              f"cover panel range [{panel_min}, {panel_max}]; "
              f"coverage would hide missing days", file=sys.stderr)
        raise SystemExit(1)
    return spy_dates


def _collect_constituent_dates(panel: pd.DataFrame) -> dict[str, set[str]]:
    """Map each constituent symbol to its set of bar dates (excl. SPY)."""
    groups = {}
    for symbol, grp in panel.groupby("symbol"):
        if symbol == "SPY":
            continue
        groups[symbol] = set(grp["date"].dt.date.astype(str))
    return groups


def _check_spy_completeness(spy_dates: set[str],
                            groups: dict[str, set[str]]) -> None:
    """Exit 1 if any constituent traded on a day SPY has no bar."""
    all_dates: set[str] = set()
    for dates in groups.values():
        all_dates |= dates
    missing = spy_missing_days(spy_dates, all_dates)
    if missing:
        print(f"ERROR: {len(missing)} days have constituent bars but no SPY "
              f"bar (e.g. {missing[:5]}); SPY calendar incomplete",
              file=sys.stderr)
        raise SystemExit(1)


def _symbol_stats(symbol: str, dates: set[str], n_rows: int,
                  spy_dates: set[str], cutoff: str) -> tuple[dict, bool]:
    """Per-symbol stats dict and late-starter flag."""
    first = min(dates)
    expected = {d for d in spy_dates if d >= first}
    gaps = find_gaps(expected, dates)
    return ({
        "n_rows": n_rows,
        "n_gaps": len(gaps),
        "first": first,
        "last": max(dates),
    }, is_late_starter(first, cutoff))


def audit_coverage(panel: pd.DataFrame) -> dict[str, Any]:
    """T1: per-symbol coverage statistics (aggregates only).

    The late-starter cutoff is SPY's first date (not hardcoded): a
    constituent starting after SPY started is a late starter.
    Fails closed if any constituent traded on a day SPY has no bar —
    those days would be invisible to gap detection.
    """
    import pandas as pd

    spy_dates = _validate_spy(panel)
    cutoff = min(spy_dates)  # SPY's first date, not a hardcoded constant
    groups = _collect_constituent_dates(panel)
    _check_spy_completeness(spy_dates, groups)

    stats = []
    late_starters = []
    for symbol, dates in groups.items():
        n_rows = int((panel["symbol"] == symbol).sum())
        stat, late = _symbol_stats(symbol, dates, n_rows, spy_dates, cutoff)
        stats.append(stat)
        if late:
            late_starters.append((symbol, stat["first"]))
    df = pd.DataFrame(stats)
    n_constituents = len(df)  # Excludes SPY
    return {
        "n_symbols": int(n_constituents),
        "n_symbols_incl_spy": int(n_constituents + 1),
        "rows": {
            "mean": float(df["n_rows"].mean()),
            "min": int(df["n_rows"].min()),
            "max": int(df["n_rows"].max()),
        },
        "gaps": {
            "symbols_with_gaps": int((df["n_gaps"] > 0).sum()),
            "max_gaps": int(df["n_gaps"].max()),
            "mean_gaps": float(df["n_gaps"].mean()),
        },
        "late_starters": {
            "count": len(late_starters),
            "list": sorted(late_starters),
        },
        "full_history": {
            "count": int(n_constituents - len(late_starters)),
            "pct": float((n_constituents - len(late_starters))
                         / n_constituents * 100),
        },
        "date_range": {
            "min": str(panel["date"].min().date()),
            "max": str(panel["date"].max().date()),
        },
    }


def verify_adjustments(panel: pd.DataFrame) -> dict[str, Any]:
    """T3: verify known splits show no artificial jumps.

    Sets failed=True if any symbol is missing OR if any split appears
    unadjusted (adjusted=False). main() exits non-zero on failed.
    The failed determination uses adjustments_failed() so the logic
    is unit-testable.
    """
    results = []
    for symbol, split_date, ratio in KNOWN_SPLITS:
        grp = panel[panel["symbol"] == symbol].sort_values("date")
        if len(grp) < 2:
            results.append({"symbol": symbol, "status": "no data"})
            print(f"ERROR: {symbol} has no data", file=sys.stderr)
            continue
        grp = grp.copy()
        grp["d"] = grp["date"].dt.date.astype(str)
        before_rows = grp[grp["d"] < split_date]
        after_rows = grp[grp["d"] >= split_date]
        if len(before_rows) == 0 or len(after_rows) == 0:
            results.append({"symbol": symbol,
                            "status": "split date not in range"})
            print(f"ERROR: {symbol} split date {split_date} not in range",
                  file=sys.stderr)
            continue
        before = before_rows.iloc[-1]
        after = after_rows.iloc[0]
        log_jump = compute_log_jump(float(before["c"]), float(after["c"]))
        adjusted = is_adjusted(log_jump)
        if not adjusted:
            # Fail closed: an unadjusted split is a data defect, not a warning.
            print(f"ERROR: {symbol} split on {split_date} appears unadjusted "
                  f"(log_jump={log_jump:.3f})", file=sys.stderr)
        results.append({
            "symbol": symbol,
            "split_date": split_date,
            "ratio": ratio,
            "log_jump": log_jump,
            "adjusted": adjusted,
        })
    return {"splits": results, "failed": adjustments_failed(results)}


def audit_availability(panel: pd.DataFrame) -> dict[str, Any]:
    """T5: data availability characteristics.

    Shows the full distribution of bar timestamp hours, not just the mode,
    to reveal DST splits or mixed conventions.
    """
    hours = panel["date"].dt.hour
    dist = hours.value_counts().sort_index().to_dict()
    dist = {int(k): int(v) for k, v in dist.items()}
    return {
        "note": (
            "Bar timestamps reflect the market date. For the forward test, "
            "availability at t_d (17:00 ET) depends on Alpaca's publication "
            "latency, not the bar timestamp. Verify latency before the "
            "12-month look."
        ),
        "bar_timestamp_hour_utc_dist": dist,
        "bar_timestamp_hour_utc_mode": int(hours.mode()[0]),
        "n_symbols": int(panel["symbol"].nunique()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S04 data plane audit")
    parser.add_argument("--data-root", required=True,
                        help="Path to data root (fail-closed: no default)")
    args = parser.parse_args()

    _guard_data_root(args.data_root)

    out_dir = os.path.join(args.data_root, "s04")
    os.makedirs(out_dir, exist_ok=True)

    print("Loading panel...", flush=True)
    panel = load_panel(args.data_root)
    print(f"  {len(panel):,} rows", flush=True)

    adjustments = verify_adjustments(panel)
    if adjustments["failed"]:
        print("ERROR: adjustment verification failed", file=sys.stderr)
        return 1

    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "coverage": audit_coverage(panel),
        "adjustments": adjustments,
        "availability": audit_availability(panel),
    }

    out_path = os.path.join(out_dir, "audit_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}", flush=True)

    # Print summary
    c = results["coverage"]
    print(f"Constituents: {c['n_symbols']}, late starters: "
          f"{c['late_starters']['count']}")
    print(f"Full history: {c['full_history']['count']} "
          f"({c['full_history']['pct']:.1f}%)")
    print(f"Symbols with gaps: {c['gaps']['symbols_with_gaps']}")
    for s in results["adjustments"]["splits"]:
        print(f"  {s['symbol']}: log_jump={s['log_jump']:.4f}, "
              f"adjusted={s['adjusted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
