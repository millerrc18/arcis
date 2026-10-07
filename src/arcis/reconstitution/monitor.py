"""Russell reconstitution monitor for the December 2026 event.

FTSE Russell moved to semi-annual reconstitution in 2026. The December 2026
event (effective Dec 11) is the first December recon in 30+ years — no
crowding history, no backtestable precedent.

This module polls FTSE Russell's published preliminary lists and identifies
long-side candidates:
- Russell 1000 → Russell 2000 downward movers (become top-weight small caps)
- S&P 500 → S&P 400 downward deletions (where applicable)

Key dates for December 2026:
- Rank day: Oct 30, 2026
- Preliminary lists: Nov 13, Nov 20, Nov 27, Dec 4, Dec 11
- Effective: after close Dec 11, 2026
"""

from __future__ import annotations

from dataclasses import dataclass, field

# FTSE Russell reconstitution document URL patterns
# Preliminary lists are published at lseg.com/ftse-russell
LSEG_BASE = "https://www.lseg.com"

# December 2026 schedule (from FTSE Russell announcements)
DEC_2026_SCHEDULE = {
    "rank_day": "2026-10-30",
    "preliminary_dates": [
        "2026-11-13",
        "2026-11-20",
        "2026-11-27",
        "2026-12-04",
        "2026-12-11",
    ],
    "effective_date": "2026-12-11",
}

USER_AGENT = "ARCIS Research contact@arcis.local"


@dataclass
class ReconCandidate:
    """A stock identified as a potential long-side recon play."""

    ticker: str
    company: str
    from_index: str  # e.g., "Russell 1000"
    to_index: str  # e.g., "Russell 2000"
    event_type: str  # "downward_migration", "deletion_rebound", "addition"
    preliminary_date: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class ReconEvent:
    """A reconstitution event with its candidate list."""

    name: str  # e.g., "December 2026 Russell Reconstitution"
    effective_date: str
    preliminary_lists: list[str] = field(default_factory=list)
    candidates: list[ReconCandidate] = field(default_factory=list)
    status: str = "upcoming"  # upcoming, preliminary, effective, complete


def classify_migration(
    from_index: str, to_index: str
) -> str | None:
    """Classify an index migration by direction.

    Returns event_type or None if not a tradeable long-side event.
    """
    # Downward migrations: becoming a bigger fish in a smaller pond
    if from_index == "Russell 1000" and to_index == "Russell 2000":
        return "downward_migration"
    if from_index == "S&P 500" and to_index == "S&P 400":
        return "downward_migration"
    # Deletions: must have explicit from_index (not empty/missing due to parse error)
    # and explicit to_index of "none" (not empty string from missing data)
    if from_index and to_index == "none":
        return "deletion_rebound"
    return None


def is_long_side_candidate(candidate: ReconCandidate) -> bool:
    """Filter for long-side candidates per the research thesis.

    Long-side events:
    - Downward migrations (R1000→R2000, SP500→SP400): become top-weight
      in smaller index, attract new buyers
    - Deletion rebounds: forced selling creates temporary dislocation

    Excluded:
    - Upward migrations (already crowded, negative announcement returns)
    - Straight additions (Greenwood & Sammon: effect decayed to ~0)
    """
    return candidate.event_type in ("downward_migration", "deletion_rebound")


# ---------------------------------------------------------------------------
# Checklist for December 2026 live trade
# ---------------------------------------------------------------------------

DEC_2026_CHECKLIST = [
    "Preliminary lists downloaded and parsed (Nov 13+) ",
    "Long-side candidates identified (R1000→R2000, SP500→SP400)",
    "Liquidity filter: ADV > $5M, spread < 50bp",
    "Position sizing: max 10% per name, max 30% total recon book",
    "Entry timing: after close Dec 11 (effective date), not before",
    "Exit plan: 2-6 week hold, take profit at +5%, stop at -3%",
    "Kill criterion defined: if basket is negative after 3 weeks, close all",
]


def get_checklist_status() -> dict[str, bool]:
    """Return checklist with all items unchecked (to be filled as we progress)."""
    return {item: False for item in DEC_2026_CHECKLIST}
