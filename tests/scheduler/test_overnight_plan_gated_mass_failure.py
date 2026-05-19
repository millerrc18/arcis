"""Regression-lock for v0.36.26 — silent-success pattern on plan-gated batch collectors.

Background
----------

Pre-v0.36.26 the three plan-gated batch wrappers in
`src/scheduler/overnight.py` (institutional_ownership / filings_sentiment /
press_releases at lines ~750-794) counted `tickers_with_data = N` after
looping over `universe`. When N=0 the result `{"tickers_with_data": 0}`
didn't trigger `_is_collector_error`, so the scheduler reported
`[COLLECT] X: success` even when ALL S&P 100 calls had returned None.

Two real-world manifestations (both silently broken for 6 days):

  1. institutional_ownership called `/stock/institutional-ownership` which
     returns 302→404. Every per-ticker call swallowed the JSON parse error
     and returned None. tickers_with_data=0/100 was logged as success.

  2. filings_sentiment called `/stock/filings-sentiment` which returns body
     `{}`. Same all-None pattern.

CLAUDE.md "Data Collection Rules" already requires:
  "Surface mass failures — if >50% of items in a batch fail, raise
   CollectorPartialFailureError."

But the wrappers didn't enforce it.

Fix (v0.36.26)
--------------

Each plan-gated wrapper now:

1. Checks `finnhub_plan_supports(capability)` BEFORE the loop. If gate is
   closed → result is the string `"skipped: plan-gated"` (caught by the
   existing logging branch at overnight.py:828, logs "[COLLECT] X: skipped").
   No loop = no wasted API calls.

2. If gate is open: runs the loop counting both `tickers_with_data` and
   `tickers_attempted`. Result dict carries both.

3. After the loop, if `tickers_attempted >= 10` and `tickers_with_data == 0`,
   raises `CollectorPartialFailureError`. The surrounding try/except stores
   `{"error": ...}` so `_is_collector_error` correctly classifies it and
   the scheduler logs "[COLLECT] X: FAILED".

The `>=10` floor prevents false-positives on small test universes; the
`== 0` floor (rather than CLAUDE.md's <50%) suits the sparse-data
collectors (filings, press_releases) where many tickers legitimately have
no new data on a given night. 0/100 is unambiguous mass failure regardless
of expected density.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ── Helper: build a fake universe of 100 tickers ────────────────────────


@pytest.fixture
def fake_universe():
    return [f"T{i:03d}" for i in range(100)]


# ── plan-gate closed → "skipped: plan-gated" (no loop, no errors) ───────


def test_plan_gated_off_skips_loop_for_institutional_ownership(fake_universe):
    """Gate closed → result is a 'skipped: plan-gated' string, no per-ticker calls."""
    from src.scheduler import overnight as overnight_mod

    with patch("src.universe.sp100.get_sp100_universe", return_value=fake_universe), \
         patch(
            "src.data_enrichment.finnhub_plan.finnhub_plan_supports",
            side_effect=lambda capability, *a, **k: capability != "institutional_ownership",
         ), \
         patch(
            "src.data_collection.institutional_ownership_collector.collect_institutional_ownership",
         ) as mock_collect:
        result = overnight_mod._run_plan_gated_collector(
            name="institutional_ownership",
            capability="institutional_ownership",
            collector_fn=mock_collect,
            universe=fake_universe,
        )

    assert isinstance(result, str), f"Expected string result, got {type(result).__name__}: {result!r}"
    assert "skipped" in result.lower()
    assert mock_collect.call_count == 0, (
        f"Plan-gated wrapper called collector {mock_collect.call_count} times — "
        "expected 0 (gate closed should short-circuit before the loop)"
    )


# ── plan-gate open + all-None → CollectorPartialFailureError ─────────────


def test_plan_gated_open_all_none_raises_mass_failure(fake_universe):
    """Gate open + 0/100 tickers with data → CollectorPartialFailureError."""
    from src.scheduler import overnight as overnight_mod
    from src.data_collection.errors import CollectorPartialFailureError

    mock_collect = MagicMock(return_value=None)  # every call returns None

    with patch(
        "src.data_enrichment.finnhub_plan.finnhub_plan_supports",
        return_value=True,
    ):
        with pytest.raises(CollectorPartialFailureError) as exc_info:
            overnight_mod._run_plan_gated_collector(
                name="institutional_ownership",
                capability="institutional_ownership",
                collector_fn=mock_collect,
                universe=fake_universe,
            )

    assert exc_info.value.errors == 100
    assert exc_info.value.total == 100
    assert "0/100" in str(exc_info.value) or "0 of 100" in str(exc_info.value)
    assert mock_collect.call_count == 100, (
        "Gate open path should call the collector once per ticker"
    )


# ── plan-gate open + some success → result dict, no raise ────────────────


def test_plan_gated_open_partial_success_does_not_raise(fake_universe):
    """Gate open + 30/100 tickers with data → result dict, no raise."""
    from src.scheduler import overnight as overnight_mod

    # Return non-None for first 30 tickers
    call_count = [0]
    def collector_side_effect(ticker, *a, **kw):
        call_count[0] += 1
        return {"some": "data"} if call_count[0] <= 30 else None

    mock_collect = MagicMock(side_effect=collector_side_effect)

    with patch(
        "src.data_enrichment.finnhub_plan.finnhub_plan_supports",
        return_value=True,
    ):
        result = overnight_mod._run_plan_gated_collector(
            name="press_releases",
            capability="press_releases",
            collector_fn=mock_collect,
            universe=fake_universe,
        )

    assert isinstance(result, dict)
    assert result["tickers_with_data"] == 30
    assert result["tickers_attempted"] == 100
    assert mock_collect.call_count == 100


# ── small universe (<10) → no mass-failure raise even if all-None ───────


def test_small_universe_does_not_trigger_mass_failure_raise():
    """Universe < 10 tickers → don't raise on all-None (could be test setup)."""
    from src.scheduler import overnight as overnight_mod

    mock_collect = MagicMock(return_value=None)
    small_universe = ["AAPL", "MSFT", "GOOGL"]  # 3 tickers

    with patch(
        "src.data_enrichment.finnhub_plan.finnhub_plan_supports",
        return_value=True,
    ):
        # Should NOT raise, just return the count
        result = overnight_mod._run_plan_gated_collector(
            name="filings_sentiment",
            capability="filings_sentiment",
            collector_fn=mock_collect,
            universe=small_universe,
        )

    assert isinstance(result, dict)
    assert result["tickers_with_data"] == 0
    assert result["tickers_attempted"] == 3


# ── plan-gate open + exactly 1 success → no raise (any data == not mass-failure) ──


def test_one_success_in_universe_does_not_raise(fake_universe):
    """1/100 success → not a mass failure. Sparse-data collectors are valid."""
    from src.scheduler import overnight as overnight_mod

    call_count = [0]
    def collector_side_effect(ticker, *a, **kw):
        call_count[0] += 1
        return {"data": "row"} if call_count[0] == 50 else None  # only the 50th succeeds

    mock_collect = MagicMock(side_effect=collector_side_effect)

    with patch(
        "src.data_enrichment.finnhub_plan.finnhub_plan_supports",
        return_value=True,
    ):
        result = overnight_mod._run_plan_gated_collector(
            name="press_releases",
            capability="press_releases",
            collector_fn=mock_collect,
            universe=fake_universe,
        )

    assert isinstance(result, dict)
    assert result["tickers_with_data"] == 1
    assert result["tickers_attempted"] == 100


# ── _is_collector_error correctly classifies the new shapes ─────────────


def test_is_collector_error_skipped_string_is_not_error():
    """`results[name] = 'skipped: plan-gated'` is NOT classified as error."""
    from src.scheduler.overnight import _is_collector_error
    assert _is_collector_error("skipped: plan-gated") is False


def test_is_collector_error_success_dict_is_not_error():
    """`{'tickers_with_data': 30, 'tickers_attempted': 100}` is NOT classified as error."""
    from src.scheduler.overnight import _is_collector_error
    assert _is_collector_error({"tickers_with_data": 30, "tickers_attempted": 100}) is False


def test_is_collector_error_error_key_dict_is_error():
    """`{'error': '...'}` IS classified as error (covers the raise path)."""
    from src.scheduler.overnight import _is_collector_error
    assert _is_collector_error({"error": "boom"}) is True
