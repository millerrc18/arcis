"""W21 pre-overnight check regression-locks for short_volume_finra.

Two bugs caught by manual pre-flight on 2026-05-18 (before tonight's
first scheduled overnight run), fixed in v0.36.20:

1. `collect_finra_short_volume()` originally called
   `get_sp100_at(target_date)` passing a `date` object. `get_sp100_at()`
   expects an ISO-format string (uses `date.fromisoformat()` internally).
   Would have TypeErrored at the first overnight run.

2. Even with the ISO-fix, `get_sp100_at()` raised `UniverseDataMissing`
   because `data/reference/sp100_history.json` was 3 weeks stale
   (latest=2026-04-28) and the collector pulls T+1 data.

The fix: use `get_sp100_universe()` (current membership) for a DAILY
data collector. PIT (`get_sp100_at()`) is for backtesting historical
signals, not for filtering today's tickers.

Pre-flight result post-fix:
    {'tickers_collected': 101, 'rows_inserted': 101,
     'target_date': '2026-05-15', 'source': 'finra'}
"""

import os
import re


_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "data_collection", "short_volume_finra.py",
)


def _load_source() -> str:
    with open(_PATH, encoding="utf-8") as f:
        return f.read()


def test_uses_current_sp100_universe_not_pit():
    """Daily data collector must use current SP100, not point-in-time."""
    source = _load_source()
    assert "get_sp100_universe" in source, (
        "short_volume_finra must use get_sp100_universe() (current membership) — "
        "PIT get_sp100_at() raises UniverseDataMissing when data is stale, "
        "killing the overnight run."
    )
    # The pre-fix call as ACTIVE code (not in a comment / docstring) should be gone.
    # Look for lines where the call appears outside of a leading '#' comment marker
    # and outside of triple-quoted blocks.
    in_triple_quote = False
    bad_lines: list[int] = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        # Count triple-quote toggles
        triple_count = stripped.count('"""') + stripped.count("'''")
        # Skip lines starting with '#' (pure comments)
        if stripped.startswith("#"):
            # Update triple-quote state even for comment lines
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        # If we're inside a docstring/triple-quote, skip
        if in_triple_quote:
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        # Update triple-quote state
        if triple_count % 2 == 1:
            in_triple_quote = not in_triple_quote
            continue  # this line started/ended a docstring; skip its content
        if "get_sp100_at(target_date)" in stripped:
            bad_lines.append(i)
    assert not bad_lines, (
        "Pre-fix `get_sp100_at(target_date)` ACTIVE CODE found at "
        f"line(s) {bad_lines}. It's OK in docstrings/comments documenting "
        "the bug history, but not as live code."
    )


def test_no_pit_imports():
    """Imports section should not reference PIT functions."""
    source = _load_source()
    # The import line should now reference sp100, not pit
    assert "from src.universe.sp100 import get_sp100_universe" in source
    assert "from src.universe.pit import" not in source
