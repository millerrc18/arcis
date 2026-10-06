"""Point-in-time universe membership from S01 snapshots.

The ranker must use only the membership available at the decision time.
Snapshots live at <data_root>/universe/YYYY-MM-DD.csv (one symbol per line,
header 'symbol'). Parsing and validation reuse the S01 snapshot reader
(arcis.recorder.universe.read_symbols): the header is checked and duplicate
symbols are rejected, instead of reimplementing the reader here.
"""

from __future__ import annotations

from pathlib import Path

from arcis.recorder.universe import read_symbols


def load_membership(data_root: str, as_of: str) -> set[str]:
    """Load the universe snapshot for `as_of` (YYYY-MM-DD).

    Returns the set of symbols. Raises UniverseError if no snapshot exists
    for that date, the header is not 'symbol', or symbols are duplicated.
    """
    path = Path(data_root) / "universe" / f"{as_of}.csv"
    return set(read_symbols(path))


def is_member(symbol: str, data_root: str, as_of: str) -> bool:
    """True if `symbol` was in the universe snapshot for `as_of`."""
    return symbol in load_membership(data_root, as_of)
