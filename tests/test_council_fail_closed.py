"""Tests for #612 — council fail-closed on Anthropic outage.

Pre-#612, two layers of silent-fail composed into a phantom-success state:
  1. claude_client.py:104  swallows ALL exceptions returning None
  2. aggregation.py:141    falls back to using all-failed assessments

Result: a billing outage produced a synthesized "5-0 neutral consensus" that
drove risk-knob clipping for two trading days (4/21–4/22). Risk parameters
were modified by a fake council vote during an external service outage.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ── claude_client typed exceptions ──

class TestClaudeAuthErrorRaisesForUnrecoverable:
    """Auth/billing failures should raise ClaudeAuthError so callers can
    fail-closed (halt batch, alert operator) instead of silently retrying.

    Transient errors (rate limit, 5xx, network) should still return None
    so the caller can move on to the next item.
    """

    def test_credit_balance_too_low_raises_typed_exception(self):
        from src.training.claude_client import (
            ClaudeAuthError,
            generate_training_example,
        )

        # Build a mock that raises an exception whose str() contains the marker.
        class _FakeBadRequest(Exception):
            pass

        with patch("src.training.claude_client._get_anthropic_client") as gc:
            gc.return_value.messages.create.side_effect = _FakeBadRequest(
                "Error code: 400 - {'error': {'message': 'Your credit_balance_too_low'}}"
            )
            with pytest.raises(ClaudeAuthError):
                generate_training_example("system", "user", purpose="test")

    def test_authentication_error_raises_typed_exception(self):
        from src.training.claude_client import (
            ClaudeAuthError,
            generate_training_example,
        )

        class _FakeAuth(Exception):
            pass

        with patch("src.training.claude_client._get_anthropic_client") as gc:
            gc.return_value.messages.create.side_effect = _FakeAuth(
                "Error code: 401 - {'error': {'type': 'authentication_error'}}"
            )
            with pytest.raises(ClaudeAuthError):
                generate_training_example("system", "user", purpose="test")

    def test_other_errors_still_return_none_for_backward_compat(self):
        from src.training.claude_client import generate_training_example

        with patch("src.training.claude_client._get_anthropic_client") as gc:
            gc.return_value.messages.create.side_effect = TimeoutError("transient")
            result = generate_training_example("system", "user", purpose="test")
        assert result is None  # transient → soft failure, caller continues


# ── aggregation refuses to synthesize from all-failed assessments ──

class TestAggregationFailClosed:
    """When all council agents fail, aggregation must NOT silently fall back
    to using the failed-stub assessments — that produced the 4/21 fake 5-0
    neutral consensus that drove real risk-knob adjustments.
    """

    def test_aggregate_raises_when_all_assessments_parse_failed(self):
        from src.council.aggregation import aggregate_votes
        from src.council.errors import CouncilUnavailableError

        all_failed = [
            {"agent": "tactical_operator", "_parse_failed": True, "direction": None},
            {"agent": "risk_governor", "_parse_failed": True, "direction": None},
            {"agent": "macro_strategist", "_parse_failed": True, "direction": None},
            {"agent": "ranker", "_parse_failed": True, "direction": None},
            {"agent": "validator", "_parse_failed": True, "direction": None},
        ]
        with pytest.raises(CouncilUnavailableError):
            aggregate_votes(all_failed)

    def test_aggregate_succeeds_with_at_least_one_valid_vote(self, tmp_path):
        from src.council.aggregation import aggregate_votes
        from tests.conftest import init_test_db

        # aggregate_votes touches the DB for dynamic weights — give it a clean one.
        db = str(tmp_path / "agg.sqlite3")
        init_test_db(db, ["agent_calibration"])

        votes = [
            {"agent": "tactical_operator", "_parse_failed": True, "direction": None},
            {"agent": "risk_governor", "direction": "bullish", "confidence": 0.7,
             "position_sizing_multiplier": 1.0, "cash_reserve_target_pct": 0.1,
             "scan_aggressiveness": "normal"},
        ]
        result = aggregate_votes(votes, db_path=db)
        # Exactly one valid vote → its direction wins; consensus reached.
        assert result.get("direction") == "bullish"


# ── data_collector halts cleanly on ClaudeAuthError ──

class TestDataCollectorHaltsOnClaudeAuthError:
    """When generate_training_example raises ClaudeAuthError, the collector
    must halt the batch (don't retry every trade) and surface it via
    CollectionResult.halted=True with halt_reason='claude_auth_error'.
    Pre-#612 fix: the auth failure went up as None, every trade was retried."""

    def test_collector_halts_on_claude_auth_error(self, tmp_path):
        import sqlite3
        from unittest.mock import patch
        from src.training.claude_client import ClaudeAuthError
        from src.training.data_collector import (
            collect_training_examples_from_closed_trades_detailed,
        )
        from tests.conftest import init_test_db

        db = str(tmp_path / "collector.sqlite3")
        init_test_db(db, ["shadow_trades", "recommendations", "training_examples"])

        # Insert 5 closed trades — pre-fix would have made 5 wasted LLM calls;
        # post-fix should halt after the first auth failure.
        conn = sqlite3.connect(db)
        for i in range(5):
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
                "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
                "max_adverse_excursion, actual_exit_time, created_at, updated_at, "
                "setup_type, regime_at_entry, vix_at_entry) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"t{i}", None, f"TIC{i}", "closed", "10.0", "1.0",
                 "target_1_hit", "5", "20.0", "5.0",
                 f"2026-01-0{i+1}T16:00:00", f"2026-01-0{i+1}", f"2026-01-0{i+1}",
                 "pullback", "neutral_chop", 16.0),
            )
        conn.commit()
        conn.close()

        call_count = {"n": 0}

        def _fail_with_auth(*_args, **_kwargs):
            call_count["n"] += 1
            raise ClaudeAuthError("credit_balance_too_low: out of credits")

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   side_effect=_fail_with_auth), \
             patch("src.training.data_collector.DB_PATH", db):
            result = collect_training_examples_from_closed_trades_detailed(db_path=db)

        # Halted on the first auth failure — should NOT have retried the other 4.
        assert call_count["n"] == 1, "Must halt on first auth error, not retry"
        assert result.halted is True
        assert result.halt_reason == "claude_auth_error"
        assert result.stage1_failures == 1
        assert result.count == 0
        assert result.is_silent_failure is True
