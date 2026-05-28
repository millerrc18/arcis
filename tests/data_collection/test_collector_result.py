"""Tests for the CollectorResult frozen dataclass (Phase 5 PR-D T18, #72).

Canonical context: docs/audits/2026-05-27-phase-5-unified/master-spec.md §5.1,
design-decisions.md DD-12/DD-13/DD-14/DD-15.

Q5 verify-by-mutation: each test pins one production invariant of
src/data_collection/result.py and is constructed to FAIL if the dataclass
logic were wrong (e.g. the is_healthy tests fail if is_healthy returns the
wrong bool; the frozen test fails if mutation is silently permitted; the
aggregate tests fail if per-ticker lists were not merged).

The truthiness tests pin DD-15 r3: CollectorResult MUST be truthy so the
not-yet-flipped `_safe_run` (`if result:`) keeps working before T19.
"""

import dataclasses

import pytest

from src.data_collection.result import CollectorResult, aggregate_results


# ── construction + frozen-ness (DD-13) ───────────────────────────────────


def test_collector_result_fields_assigned():
    """Pins the 5-field contract: every constructor arg lands on the instance."""
    r = CollectorResult(
        collector_name="macro",
        status="ok",
        primary_count=30,
        errors=["x"],
        metadata={"notable_changes": 2},
    )
    assert r.collector_name == "macro"
    assert r.status == "ok"
    assert r.primary_count == 30
    assert r.errors == ["x"]
    assert r.metadata == {"notable_changes": 2}


def test_collector_result_default_errors_and_metadata():
    """Pins the default_factory contract: errors/metadata default to empty
    containers, and each instance gets its OWN container (no shared mutable
    default — would fail if `field(default_factory=...)` were a bare `= []`)."""
    a = CollectorResult(collector_name="a", status="ok", primary_count=1)
    b = CollectorResult(collector_name="b", status="ok", primary_count=2)
    assert a.errors == []
    assert a.metadata == {}
    a.errors.append("leak")  # mutate a's list (the list itself is not frozen)
    assert b.errors == [], "default_factory must give each instance its own list"


def test_collector_result_is_frozen_on_status():
    """Pins frozen-ness: reassigning a field raises FrozenInstanceError.

    Fails if the dataclass were declared without frozen=True (assignment
    would silently succeed)."""
    r = CollectorResult(collector_name="macro", status="ok", primary_count=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.status = "failed"  # type: ignore[misc]


def test_collector_result_is_frozen_on_primary_count():
    """Second frozen-ness probe on a different field — guards against a
    partially-frozen impl."""
    r = CollectorResult(collector_name="macro", status="ok", primary_count=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.primary_count = 99  # type: ignore[misc]


# ── truthiness (DD-15 r3 — must not break unflipped _safe_run) ────────────


def test_ok_result_is_truthy():
    """DD-15 r3: an ok result must be truthy so `if result:` in the
    not-yet-flipped _safe_run keeps treating success as success.

    Fails if someone added a __bool__/__len__ that made an ok result falsy."""
    r = CollectorResult.ok_from_count("macro", 5)
    assert bool(r) is True


def test_failed_result_is_still_truthy():
    """DD-15 r3 (the subtle one): even a FAILED result is object-truthy.

    Before T19, _safe_run does `if result:` and must NOT treat a failed
    CollectorResult as falsy (that would change failure-handling behavior
    mid-migration). Health is expressed via .is_healthy, NOT object bool.
    Fails if a __bool__ returning self.is_healthy were added."""
    r = CollectorResult.failed("macro", ["boom"])
    assert bool(r) is True


# ── is_healthy property ───────────────────────────────────────────────────


def test_is_healthy_true_for_ok():
    """ok status is healthy. Fails if is_healthy excluded 'ok'."""
    assert CollectorResult.ok_from_count("macro", 10).is_healthy is True


def test_is_healthy_true_for_partial():
    """partial (above-threshold) status is healthy — partial data is still
    usable. Fails if is_healthy treated 'partial' as unhealthy."""
    r = CollectorResult.partial("analyst", 8, errors=["t1 failed"])
    assert r.is_healthy is True


def test_is_healthy_false_for_failed():
    """failed status is NOT healthy. Fails if is_healthy returned True for
    'failed' (the core regression this test guards)."""
    assert CollectorResult.failed("macro", ["boom"]).is_healthy is False


def test_is_healthy_returns_bool_not_truthy():
    """is_healthy must be a real bool (True/False), not a truthy/falsy proxy
    — _capability_health routing branches on it. Fails if it returned a
    string status or an int count."""
    assert CollectorResult.ok_from_count("macro", 1).is_healthy is True
    assert CollectorResult.failed("macro", []).is_healthy is False


# ── classmethod: ok_from_count ────────────────────────────────────────────


def test_ok_from_count_sets_status_and_count():
    """ok_from_count → status='ok', primary_count=count, errors empty.
    Fails if it set the wrong status or dropped the count."""
    r = CollectorResult.ok_from_count("macro", 30)
    assert r.collector_name == "macro"
    assert r.status == "ok"
    assert r.primary_count == 30
    assert r.errors == []


def test_ok_from_count_captures_metadata_kwargs():
    """ok_from_count forwards **metadata into the metadata dict (Shape A:
    notable_changes count). Fails if metadata kwargs were dropped."""
    r = CollectorResult.ok_from_count("macro", 30, notable_changes=2)
    assert r.metadata == {"notable_changes": 2}


# ── classmethod: partial ──────────────────────────────────────────────────


def test_partial_sets_status_and_errors():
    """partial → status='partial', keeps count + error list.
    Fails if partial mis-set status or discarded the errors."""
    r = CollectorResult.partial("options", 12, errors=["AAPL failed", "MSFT failed"])
    assert r.status == "partial"
    assert r.primary_count == 12
    assert r.errors == ["AAPL failed", "MSFT failed"]


def test_partial_captures_metadata_kwargs():
    """partial forwards **metadata (Shape C: contracts_stored).
    Fails if metadata kwargs were dropped on the partial path."""
    r = CollectorResult.partial("options", 12, errors=["e"], contracts_stored=480)
    assert r.metadata == {"contracts_stored": 480}


# ── classmethod: failed ───────────────────────────────────────────────────


def test_failed_sets_status_zero_count_and_errors():
    """failed → status='failed', primary_count=0, keeps errors.
    Fails if failed produced a non-zero count or dropped errors."""
    r = CollectorResult.failed("macro", ["FRED_API_KEY missing"])
    assert r.status == "failed"
    assert r.primary_count == 0
    assert r.errors == ["FRED_API_KEY missing"]


# ── aggregate_results (Shape F: press_releases per-ticker lists) ──────────


def test_aggregate_results_sums_primary_counts():
    """aggregate_results sums primary_count across per-ticker results
    (Shape F: each ticker is its own collect call). Fails if counts were
    not summed (e.g. last-wins or first-wins)."""
    parts = [
        CollectorResult.ok_from_count("press_releases", 3),
        CollectorResult.ok_from_count("press_releases", 5),
        CollectorResult.ok_from_count("press_releases", 2),
    ]
    agg = aggregate_results("press_releases", parts)
    assert agg.primary_count == 10


def test_aggregate_results_concatenates_errors():
    """aggregate_results merges all per-ticker error lists into one.
    Fails if errors from non-first results were dropped."""
    parts = [
        CollectorResult.ok_from_count("press_releases", 3),
        CollectorResult.partial("press_releases", 1, errors=["TSLA fetch failed"]),
        CollectorResult.partial("press_releases", 0, errors=["NVDA fetch failed"]),
    ]
    agg = aggregate_results("press_releases", parts)
    assert agg.errors == ["TSLA fetch failed", "NVDA fetch failed"]


def test_aggregate_results_partial_when_any_error():
    """An aggregate with some successes AND some errors is 'partial'.
    Fails if the aggregate were marked 'ok' despite per-ticker errors."""
    parts = [
        CollectorResult.ok_from_count("press_releases", 3),
        CollectorResult.partial("press_releases", 0, errors=["TSLA fetch failed"]),
    ]
    agg = aggregate_results("press_releases", parts)
    assert agg.status == "partial"


def test_aggregate_results_ok_when_no_errors():
    """All-clean aggregate is 'ok'. Fails if a clean merge were mislabeled."""
    parts = [
        CollectorResult.ok_from_count("press_releases", 3),
        CollectorResult.ok_from_count("press_releases", 4),
    ]
    agg = aggregate_results("press_releases", parts)
    assert agg.status == "ok"


def test_aggregate_results_failed_when_all_failed():
    """When every part failed (zero successes, only errors), the aggregate is
    'failed' and not healthy. Fails if an all-failed merge stayed 'partial'."""
    parts = [
        CollectorResult.failed("press_releases", ["AAPL fetch failed"]),
        CollectorResult.failed("press_releases", ["MSFT fetch failed"]),
    ]
    agg = aggregate_results("press_releases", parts)
    assert agg.status == "failed"
    assert agg.is_healthy is False


def test_aggregate_results_empty_is_ok_zero():
    """Aggregating no results (no tickers in scope) yields ok / count 0 —
    an empty universe is not a failure. Fails if empty raised or returned
    'failed'."""
    agg = aggregate_results("press_releases", [])
    assert agg.status == "ok"
    assert agg.primary_count == 0
    assert agg.is_healthy is True


def test_aggregate_results_returns_collector_result():
    """aggregate_results returns a CollectorResult (frozen) carrying the
    supplied name. Fails if it returned a dict or the wrong name."""
    agg = aggregate_results("press_releases", [CollectorResult.ok_from_count("x", 1)])
    assert isinstance(agg, CollectorResult)
    assert agg.collector_name == "press_releases"
    with pytest.raises(dataclasses.FrozenInstanceError):
        agg.primary_count = 0  # type: ignore[misc]
