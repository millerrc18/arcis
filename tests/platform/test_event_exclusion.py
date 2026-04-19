"""Event exclusion filter unit tests for v0.26.2-scoped schema extension.

Verifies the `entry.event_exclusion.categories` hook in
`backtest_engine._run_event_driven` — matches via `is_known_event(entry_iso,
category=C)` and skips the trade when any listed category matches.

Rather than fake up the full OHLCV + EDGAR DB, these tests exercise the
underlying `is_known_event` predicate with known v0.25.1-backfilled
Trade Policy dates and then verify the same call shape the engine uses.
"""

from src.diagnostics.known_events import is_known_event


def test_is_known_event_matches_trade_policy_date():
    # 2022-03-08 is SANCTIONS_ESCALATION -> Trade Policy per v0.25.1 backfill
    assert is_known_event("2022-03-08", category="Trade Policy") is True


def test_is_known_event_next_day_does_not_match():
    assert is_known_event("2022-03-09", category="Trade Policy") is False


def test_is_known_event_requires_exact_category_match():
    # 2022-03-08 is Trade Policy, not Monetary Policy
    assert is_known_event("2022-03-08", category="Monetary Policy") is False


def test_is_known_event_no_category_filter_returns_true_for_any_known():
    assert is_known_event("2022-03-08") is True


def test_is_known_event_unknown_date_returns_false():
    assert is_known_event("2020-01-02", category="Trade Policy") is False


def test_event_exclusion_any_category_match_triggers():
    """Replicates the engine's any(...) call pattern."""
    entry_iso = "2023-12-18"  # TRADE_DISRUPTION -> Trade Policy
    cats = ["Fed", "Trade Policy", "Earnings"]
    assert any(is_known_event(entry_iso, category=c) for c in cats) is True


def test_event_exclusion_no_categories_match():
    entry_iso = "2023-01-03"  # not in KNOWN_EVENTS
    cats = ["Trade Policy"]
    assert any(is_known_event(entry_iso, category=c) for c in cats) is False


def test_all_2019_2024_trade_policy_dates_match():
    """Guardrail: v0.25.1 backfill labels 9 dates. If this count drifts,
    the sprint's outcome hypothesis (5-6 trades after filter) shifts."""
    expected = {
        "2019-10-11", "2019-12-12",  # tariffs
        "2022-02-24", "2022-03-08",  # sanctions
        "2022-07-27", "2022-08-09",  # industrial policy
        "2022-10-07",                 # export controls
        "2023-12-18",                 # trade disruption
        "2024-05-14",                 # tariff escalation
    }
    for d in expected:
        assert is_known_event(d, category="Trade Policy") is True, d
