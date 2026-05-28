"""Normalized collector outcome — the CollectorResult frozen dataclass.

Called by: data_collection.* (collectors), scheduler.watch (_safe_run — flips in T19)
Calls: none
Owns tables: none
Config keys: none
Tests: tests/data_collection/test_collector_result.py

Phase 5 PR-D / #72. Canonical context:
docs/audits/2026-05-27-phase-5-unified/master-spec.md §5.1 + design-decisions
DD-12/DD-13/DD-14/DD-15.

Pre-Phase-5 the 22 collectors returned 8 distinct dict shapes that _safe_run
(watch.py) discarded after a bare truthiness check. CollectorResult normalizes
those outputs into one frozen value object so _safe_run can route status to
_capability_health once T19 flips the consumer.

DD-12: this is a SEPARATE module from errors.py — result is data, not an
exception. CollectorPartialFailureError stays in errors.py and continues to
raise for the >50% mass-failure escalation path (DD-14); CollectorResult never
replaces that exception.

DD-15 r3 (truthiness): a CollectorResult is object-truthy for EVERY status,
including 'failed'. The Big Bang migrates collectors first and flips _safe_run
LAST (T19); until then _safe_run does `if result:` and must keep seeing a
truthy object. Health is expressed via the .is_healthy property, never via
object bool — so we deliberately do NOT define __bool__/__len__.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "partial", "failed"]


@dataclass(frozen=True)
class CollectorResult:
    """One collector run's normalized outcome (frozen — DD-13).

    Fields:
      collector_name: the collector that produced this result.
      status: "ok" | "partial" | "failed".
      primary_count: the collector's natural unit (series_collected,
        tickers_processed, rows_stored, ...).
      errors: per-item failure messages (empty on a clean run).
      metadata: secondary integer counts (e.g. notable_changes,
        contracts_stored) — the spec's dict[str, int] supplementary bucket.

    Construct via the classmethods (ok_from_count / partial / failed) rather
    than the raw constructor to avoid bool-trap status strings.
    """

    collector_name: str
    status: Status
    primary_count: int
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, int] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        """True when the run is usable: 'ok' or (above-threshold) 'partial'.

        'failed' is the only unhealthy status. _safe_run branches on this
        (not on object truthiness — see module docstring / DD-15 r3) to set
        _capability_health.
        """
        return self.status in ("ok", "partial")

    @classmethod
    def ok_from_count(cls, name: str, count: int, **metadata: int) -> CollectorResult:
        """A fully-successful run of ``count`` primary items."""
        return cls(
            collector_name=name,
            status="ok",
            primary_count=count,
            metadata=dict(metadata),
        )

    @classmethod
    def partial(
        cls, name: str, count: int, errors: list[str], **metadata: int
    ) -> CollectorResult:
        """A run that collected ``count`` items but hit some item failures."""
        return cls(
            collector_name=name,
            status="partial",
            primary_count=count,
            errors=list(errors),
            metadata=dict(metadata),
        )

    @classmethod
    def failed(cls, name: str, errors: list[str]) -> CollectorResult:
        """A run that produced no usable data (primary_count forced to 0)."""
        return cls(
            collector_name=name,
            status="failed",
            primary_count=0,
            errors=list(errors),
        )


def aggregate_results(
    name: str, results: list[CollectorResult]
) -> CollectorResult:
    """Merge per-ticker CollectorResults into one (Shape F: press_releases).

    press_releases collects one ticker at a time, so the loop produces a list
    of CollectorResults. This sums primary_count, concatenates errors, merges
    metadata, and derives an overall status:
      - all parts failed (no successes, only errors) -> 'failed'
      - any errors present                           -> 'partial'
      - otherwise                                    -> 'ok'

    An empty list (no tickers in scope) aggregates to ok / count 0 — an empty
    universe is not a failure.
    """
    total = sum(r.primary_count for r in results)
    errors: list[str] = []
    metadata: dict[str, int] = {}
    for r in results:
        errors.extend(r.errors)
        metadata.update(r.metadata)

    all_failed = bool(results) and all(r.status == "failed" for r in results)
    if all_failed:
        status: Status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "ok"

    return CollectorResult(
        collector_name=name,
        status=status,
        primary_count=total,
        errors=errors,
        metadata=metadata,
    )
