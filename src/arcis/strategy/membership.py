"""Point-in-time universe membership from S01 snapshots.

The ranker must use only the membership available at the decision time.
Snapshots live at <data_root>/universe/YYYY-MM-DD.csv (one symbol per line,
header 'symbol').
"""

from __future__ import annotations

import os


def load_membership(data_root: str, as_of: str) -> set[str]:
    """Load the universe snapshot for `as_of` (YYYY-MM-DD).

    Returns the set of symbols. Raises FileNotFoundError if no snapshot
    exists for that date.
    """
    path = os.path.join(data_root, "universe", f"{as_of}.csv")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no universe snapshot for {as_of}: {path}")
    symbols = set()
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue  # header
            symbol = line.strip()
            if symbol:
                symbols.add(symbol)
    return symbols


def is_member(symbol: str, data_root: str, as_of: str) -> bool:
    """True if `symbol` was in the universe snapshot for `as_of`."""
    return symbol in load_membership(data_root, as_of)
