"""Tier-1 observability quick wins (#613, #614, #618, #623).

Each test is a regression guard. The corresponding production fix lives in
the same commit. See plan: docs/superpowers/plans/2026-04-23-triage-tiers-1-through-4.md
"""

from __future__ import annotations

import pathlib

import pytest


# ── #614 — activity_log event constants must have writers ──

class TestActivityLogConstantsHaveWriters:
    """Defined-but-unused constants in activity_logger.py mean the dashboard
    activity feed shows ~2-4 events/day instead of the actual ~hundreds.
    Pre-fix audit: SCAN_COMPLETE, TRADE_OPENED, TRADE_CLOSED, RISK_ALERT,
    SYSTEM_EVENT — all defined, none written."""

    SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

    def _writers_for(self, symbol: str) -> int:
        import re
        # Match log_activity(<whitespace/newline>SYMBOL — handles multi-line calls.
        pattern = re.compile(r"log_activity\(\s*" + re.escape(symbol) + r"\b")
        count = 0
        for path in self.SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                count += 1
        return count

    def test_scan_complete_has_writer(self):
        assert self._writers_for("SCAN_COMPLETE") >= 1

    def test_trade_opened_has_writer(self):
        assert self._writers_for("TRADE_OPENED") >= 1

    def test_trade_closed_has_writer(self):
        assert self._writers_for("TRADE_CLOSED") >= 1

    def test_risk_alert_has_writer(self):
        assert self._writers_for("RISK_ALERT") >= 1

    def test_system_event_has_writer(self):
        # Already added by deploy_info.py in #630 fix
        assert self._writers_for("SYSTEM_EVENT") >= 1


# ── #618 — sleep-recovery threshold must include jitter buffer ──

class TestSleepRecoveryThreshold:
    """Pre-fix: `if elapsed > 30` matched the 30-min scan_interval, firing
    on every cycle (~31 min elapsed due to jitter). 12 false Telegram
    alerts/day. The new helper compares against 1.5×scan_interval."""

    def test_typical_jitter_does_not_trigger(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        assert _is_likely_sleep_gap(elapsed_min=30.0, scan_interval_min=30) is False
        assert _is_likely_sleep_gap(elapsed_min=31.0, scan_interval_min=30) is False
        assert _is_likely_sleep_gap(elapsed_min=44.0, scan_interval_min=30) is False

    def test_genuine_sleep_gap_triggers(self):
        from src.scheduler.watch import _is_likely_sleep_gap
        # 1.5x threshold: 30*1.5 = 45, so anything >45 fires
        assert _is_likely_sleep_gap(elapsed_min=46.0, scan_interval_min=30) is True
        assert _is_likely_sleep_gap(elapsed_min=120.0, scan_interval_min=30) is True

    def test_uses_configurable_scan_interval(self):
        """A different scan_interval shifts the threshold proportionally."""
        from src.scheduler.watch import _is_likely_sleep_gap
        # 60-min interval → threshold 90
        assert _is_likely_sleep_gap(elapsed_min=80.0, scan_interval_min=60) is False
        assert _is_likely_sleep_gap(elapsed_min=95.0, scan_interval_min=60) is True


# ── #623 — _is_collector_error must not match `errors: 0` substring ──

class TestCollectorErrorClassification:
    """Pre-fix: `'error' in str(result).lower()` matched `'errors': 0` in
    successful return dicts → 8 false ERROR rows / 3-day window."""

    def test_success_with_errors_zero_is_not_error(self):
        from src.scheduler.overnight import _is_collector_error
        result = {"tickers_processed": 20, "estimates_stored": 20, "errors": 0}
        assert _is_collector_error(result) is False

    def test_dict_with_explicit_error_key_is_error(self):
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"error": "API key missing"}) is True

    def test_string_starting_with_error_is_error(self):
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error("Error: network down") is True

    def test_string_containing_error_substring_is_not_error(self):
        from src.scheduler.overnight import _is_collector_error
        # The substring "error" embedded inside a longer message shouldn't trip
        assert _is_collector_error("collected 20 tickers (no errors)") is False

    def test_partial_failure_with_zero_processed_is_error(self):
        """All-failed batch (errors > 0 AND tickers_processed == 0) is an error."""
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"tickers_processed": 0, "errors": 5}) is True

    def test_partial_failure_with_some_processed_is_not_error(self):
        """Partial success (some succeed, some fail) is not a full failure."""
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"tickers_processed": 15, "errors": 5}) is False

    # ── kin #23 / DD-15 r3 — dual-mode: CollectorResult-aware ──
    # PR-D migrates collectors dict -> CollectorResult one batch at a time.
    # A CollectorResult is NOT a dict, so the dict-only classifier fell through
    # to "not an error", SILENTLY REVERSING the #623 fix for every migrated
    # collector (a genuinely FAILED collector stopped being flagged).

    def test_failed_collectorresult_is_error(self):
        """#623-REVERSAL GUARD: a CollectorResult.failed() MUST be flagged.

        VERIFY-BY-MUTATION (per feedback_vacuous_test_pattern): delete the
        ``isinstance(result, CollectorResult)`` branch in _is_collector_error
        and this assertion flips to False — a failed collector silently stops
        being an error, exactly the kin #23 regression. Proven non-vacuous by
        running this test against the pre-edit (dict-only) classifier: it FAILS.
        """
        from src.data_collection.result import CollectorResult
        from src.scheduler.overnight import _is_collector_error
        failed = CollectorResult.failed("macro", errors=["FRED 500"])
        assert _is_collector_error(failed) is True

    def test_healthy_collectorresult_is_not_error(self):
        """An 'ok' CollectorResult is healthy and must NOT be flagged."""
        from src.data_collection.result import CollectorResult
        from src.scheduler.overnight import _is_collector_error
        ok = CollectorResult.ok_from_count("macro", 31)
        assert _is_collector_error(ok) is False

    def test_partial_collectorresult_is_not_error(self):
        """A 'partial' CollectorResult is above-threshold usable (is_healthy)."""
        from src.data_collection.result import CollectorResult
        from src.scheduler.overnight import _is_collector_error
        partial = CollectorResult.partial("trends", 18, errors=["2 tickers 429"])
        assert _is_collector_error(partial) is False

    def test_legacy_dict_path_still_works_alongside_collectorresult(self):
        """Dual-mode: legacy dict classification is unchanged by the new branch."""
        from src.scheduler.overnight import _is_collector_error
        assert _is_collector_error({"error": "API key missing"}) is True
        assert _is_collector_error({"tickers_processed": 20, "errors": 0}) is False


# ── #613 — production-side guard against test pollution of activity_log ──

class TestActivityLogTestPollutionGuard:
    """Pre-fix: tests calling _global_halt without monkeypatching DB_PATH
    wrote 540 fake kill_switch_halt rows into prod ai_research_desk.sqlite3.

    The production-side guard skips the activity_log write when running
    under pytest (PYTEST_CURRENT_TEST env var set), so future tests that
    forget to monkeypatch don't pollute prod."""

    def test_log_activity_skips_writes_under_pytest(self, tmp_path):
        """With PYTEST_CURRENT_TEST set (always true in pytest), log_activity
        must NOT write to the DB when the safety guard is active."""
        import os
        from src.utils import activity_logger
        # PYTEST_CURRENT_TEST is auto-set by pytest itself.
        assert os.environ.get("PYTEST_CURRENT_TEST"), (
            "this test must run under pytest"
        )
        # Point at tmp DB to be safe even if guard fails.
        bad_db = str(tmp_path / "should_stay_empty.sqlite3")
        # Initialize schema so insert would succeed if guard were missing.
        from tests.conftest import init_test_db
        init_test_db(bad_db, ["activity_log"])
        # Call should be a no-op due to guard.
        activity_logger.log_activity("system_event", "test_pollution_check", db_path=bad_db)
        # Verify no row was written.
        import sqlite3
        with sqlite3.connect(bad_db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        assert n == 0, "log_activity wrote under pytest — guard missing or broken"
