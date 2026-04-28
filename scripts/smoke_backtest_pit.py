"""Smoke backtest for the PIT SP100 universe.

Purpose:
    Operator-runnable script that exercises the full point-in-time universe
    pipeline against the regenerated `data/reference/sp100_history.json` and
    asserts that historically-correct tickers appear at expected dates. Acts
    as a fast pre-flight check before committing to a real multi-week backtest.

Why this is NOT a unit test:
    - Reads the actual production JSON (not a synthetic fixture). If a future
      `_CURATED_CHANGES` edit silently regresses a corp-action, this script
      surfaces it immediately at the command line.
    - Exercises the full lookup chain (`pit.get_sp100_at` -> `load_sp100_membership_table`
      -> JSON file -> ticker list) in operator-realistic conditions.
    - Failures here mean either the data is wrong or the loader contract changed
      — both block any real backtest from being trusted.

Usage:
    python scripts/smoke_backtest_pit.py
    python scripts/smoke_backtest_pit.py --verbose

Exit codes:
    0 — all assertions pass
    1 — at least one assertion failed (failed checks are printed to stderr)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from src.universe.pit import ...` works
# when the script is invoked directly from the repo root (the canonical operator pattern).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.universe.pit import (  # noqa: E402
    UniverseDataMissing,
    get_all_historical_tickers,
    get_data_range,
    get_sp100_at,
    load_sp100_membership_table,
)
from scripts.build_sp100_history import _CURATED_CHANGES  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
# Operator-authored smoke-check spec (three layers + negative tests + today)
# ════════════════════════════════════════════════════════════════════════════

# Layer 1 — spot-checks for the three known corporate actions fixed in Sprint 1.A.x.
# These regression-lock the specific bugs we just fixed.
SPOT_CHECKS = [
    # (date_str, ticker, should_be_present, rationale)
    # ── Tier A (Sprint 1.A.x) ────────────────────────────────────────────
    ("2015-06-01", "PCLN", True,  "Booking Holdings was PCLN until 2018-02-27"),
    ("2015-06-01", "BKNG", False, "BKNG didn't exist as a ticker pre-2018-02-27"),
    ("2018-06-01", "BKNG", True,  "Post-rename, BKNG should be present"),
    ("2018-06-01", "PCLN", False, "Post-rename, PCLN should be gone"),
    ("2015-06-01", "KRFT", True,  "Kraft Foods was KRFT until 2015-07-06"),
    ("2015-06-01", "KHC",  False, "KHC didn't exist pre-merger"),
    ("2019-06-01", "UTX",  True,  "United Technologies was UTX until 2020-04-03"),
    ("2019-06-01", "RTN",  True,  "Raytheon was RTN until 2020-04-03"),
    ("2019-06-01", "RTX",  False, "RTX didn't exist pre-merger"),
    ("2021-06-01", "RTX",  True,  "Post-merger, RTX should be present"),
    # ── Tier B (Sprint 1.A.x.1) ──────────────────────────────────────────
    ("2018-06-01", "CELG", True,  "Celgene was SP100 until BMS acquisition 2019-11-20"),
    ("2024-06-01", "CELG", False, "Post-acquisition, CELG should be gone"),
    ("2018-06-01", "S",    True,  "Sprint Corp was SP100 until T-Mobile merger 2020-04-01"),
    ("2024-06-01", "S",    False, "Post-merger, S should be gone"),
    ("2020-06-01", "FB",   True,  "Facebook was FB until 2022-06-09"),
    ("2020-06-01", "META", False, "META didn't exist as ticker pre-rename"),
    ("2024-06-01", "META", True,  "Post-rename, META should be present"),
    ("2024-06-01", "FB",   False, "Post-rename, FB should be gone"),
]

# Layer 2 — structural invariants that catch the CLASS of bug.
# Bound widened from (99, 105) to (99, 110) in Sprint 1.A.x.1 to absorb Tier B
# re-additions (CELG, S re-added on backwards-walk push pre-2019 snapshots to ~107).
# 110 cap still catches gross parse errors while accommodating legitimate corp-action
# accumulation. The historical-ticker spot-checks (Layer 1 + L3) remain the strong
# correctness signal; this size band is the structural sanity net.
SNAPSHOT_SIZE_RANGE = (99, 110)
MAX_DELTA_BETWEEN_ADJACENT_SNAPSHOTS = 8  # alarm if a snapshot replaces >8 tickers vs predecessor

# Negative tests — out-of-range as_of must raise UniverseDataMissing.
NEGATIVE_TESTS = [
    ("2010-01-01", "before earliest snapshot"),
    ("2099-01-01", "after latest snapshot"),
]

# Today-size sanity bound.
TODAY_SIZE_RANGE = (99, 105)


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _summary_print(label: str, verbose: bool, **kwargs) -> None:
    """Verbose-mode pretty-printer; no-op when not verbose."""
    if not verbose:
        return
    print(f"  {label}")
    for k, v in kwargs.items():
        print(f"    {k}: {v}")


def run_smoke_checks(verbose: bool = False) -> list[str]:
    """Run the operator-defined smoke assertions.

    Returns a list of failure messages — empty list means all assertions passed.

    The assertion logic is operator-authored (TODO below) — this function is the
    scaffolding around it. Each check should:
      1. Compute or look up an expected value
      2. Read from `pit.get_sp100_at()` or `pit.get_all_historical_tickers()`
      3. Append a descriptive failure string to `failures` if mismatched
    """
    failures: list[str] = []

    earliest, latest = get_data_range()
    print(f"PIT coverage: {earliest} -> {latest}")

    latest_str = latest.isoformat()  # get_sp100_at takes ISO strings, not date objects

    if verbose:
        all_tickers = get_all_historical_tickers()
        _summary_print(
            "Universe stats",
            verbose,
            historical_total=len(all_tickers),
            today_count=len(get_sp100_at(latest_str)),
        )

    # ────────────────────────────────────────────────────────────────────────
    # Layer 1 — corp-action spot-checks (regression-lock the specific bugs we fixed)
    # ────────────────────────────────────────────────────────────────────────
    for date_str, ticker, should_be_present, rationale in SPOT_CHECKS:
        try:
            universe = get_sp100_at(date_str)
        except UniverseDataMissing as exc:
            failures.append(f"L1 {date_str} {ticker}: get_sp100_at raised UniverseDataMissing ({exc})")
            continue
        present = ticker in universe
        if present != should_be_present:
            failures.append(
                f"L1 {date_str} {ticker}: expected present={should_be_present}, got={present} ({rationale})"
            )
    _summary_print("Layer 1 spot-checks", verbose, count=len(SPOT_CHECKS), failed=sum(1 for f in failures if f.startswith("L1 ")))

    # ────────────────────────────────────────────────────────────────────────
    # Layer 2 — structural invariants (every snapshot in the JSON)
    # ────────────────────────────────────────────────────────────────────────
    table = load_sp100_membership_table()
    snapshot_dates = sorted(table.keys())

    # 2a. snapshot_size_in_range — every snapshot must be within bounds
    lo, hi = SNAPSHOT_SIZE_RANGE
    for snap_date in snapshot_dates:
        n = len(table[snap_date])
        if not (lo <= n <= hi):
            failures.append(f"L2 size: snapshot {snap_date} has {n} tickers (outside [{lo}, {hi}])")

    # 2b. max_delta_between_adjacent_snapshots — alarm on >N ticker churn between adjacent dates
    max_delta = MAX_DELTA_BETWEEN_ADJACENT_SNAPSHOTS
    largest_observed_delta = 0
    largest_observed_pair: tuple[str, str] | None = None
    for prev_date, curr_date in zip(snapshot_dates[:-1], snapshot_dates[1:]):
        prev_set = set(table[prev_date])
        curr_set = set(table[curr_date])
        delta = len(prev_set.symmetric_difference(curr_set))
        if delta > largest_observed_delta:
            largest_observed_delta = delta
            largest_observed_pair = (prev_date, curr_date)
        if delta > max_delta:
            failures.append(
                f"L2 delta: {prev_date} -> {curr_date} has {delta} ticker swaps (cap {max_delta})"
            )
    _summary_print(
        "Layer 2 structural",
        verbose,
        snapshots=len(snapshot_dates),
        max_delta_observed=largest_observed_delta,
        max_delta_pair=largest_observed_pair,
    )

    # ────────────────────────────────────────────────────────────────────────
    # Layer 3 — rename/merger consistency (cross-source check vs _CURATED_CHANGES)
    # For every rename event, verify the new ticker doesn't appear before the
    # rename date AND the old ticker doesn't appear at/after the rename date.
    # Catches incomplete or wrong rename records.
    # ────────────────────────────────────────────────────────────────────────
    for record in _CURATED_CHANGES:
        evt = record.get("type")
        if evt == "rename":
            rename_date = record["date"]
            old_t = record["from"]
            new_t = record["to"]
            for snap_date, tickers in table.items():
                if snap_date < rename_date and new_t in tickers:
                    failures.append(
                        f"L3 rename {old_t}->{new_t}@{rename_date}: {new_t} appears in pre-rename snapshot {snap_date}"
                    )
                if snap_date >= rename_date and old_t in tickers:
                    failures.append(
                        f"L3 rename {old_t}->{new_t}@{rename_date}: {old_t} appears in post-rename snapshot {snap_date}"
                    )
        elif evt == "merger":
            merger_date = record["date"]
            old_tickers = record["from"]  # list
            new_t = record["to"]
            for snap_date, tickers in table.items():
                if snap_date < merger_date and new_t in tickers:
                    failures.append(
                        f"L3 merger {'+'.join(old_tickers)}->{new_t}@{merger_date}: {new_t} appears in pre-merger snapshot {snap_date}"
                    )
                if snap_date >= merger_date:
                    for old_t in old_tickers:
                        if old_t in tickers:
                            failures.append(
                                f"L3 merger {'+'.join(old_tickers)}->{new_t}@{merger_date}: {old_t} appears in post-merger snapshot {snap_date}"
                            )

    # ────────────────────────────────────────────────────────────────────────
    # Negative tests — out-of-range as_of must raise UniverseDataMissing
    # ────────────────────────────────────────────────────────────────────────
    for date_str, rationale in NEGATIVE_TESTS:
        try:
            get_sp100_at(date_str)
            failures.append(f"NEG {date_str} ({rationale}): expected UniverseDataMissing, got success")
        except UniverseDataMissing:
            pass  # expected
        except Exception as exc:
            failures.append(f"NEG {date_str} ({rationale}): expected UniverseDataMissing, got {type(exc).__name__}: {exc}")

    # ────────────────────────────────────────────────────────────────────────
    # Today-size sanity — current snapshot should be in expected range
    # ────────────────────────────────────────────────────────────────────────
    today = get_sp100_at(latest_str)
    today_lo, today_hi = TODAY_SIZE_RANGE
    if not (today_lo <= len(today) <= today_hi):
        failures.append(f"TODAY: snapshot {latest} has {len(today)} tickers (outside [{today_lo}, {today_hi}])")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print universe stats alongside pass/fail counts",
    )
    args = parser.parse_args(argv)

    try:
        failures = run_smoke_checks(verbose=args.verbose)
    except UniverseDataMissing as exc:
        print(
            f"FATAL: PIT data unavailable — {exc}\n"
            f"Run `python scripts/build_sp100_history.py` to regenerate, then re-run this script.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"FATAL: unexpected error — {exc}", file=sys.stderr)
        return 1

    if failures:
        print(f"\nFAIL: {len(failures)} smoke assertion(s) failed:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\nOK — all smoke assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
