"""Tests for the self-blinding training data pipeline."""

import pytest
from unittest.mock import patch, MagicMock

from src.llm.prompts import BLINDED_ANALYSIS_PROMPT, QUALITY_ENHANCEMENT_PROMPT


class TestBlindedPromptContent:
    """Verify that blinded prompts do NOT contain outcome information."""

    def test_blinded_prompt_has_no_outcome_text(self):
        prompt = BLINDED_ANALYSIS_PROMPT.format(date="2025-01-15")
        assert "ACTUAL OUTCOME" not in prompt
        assert "P&L" not in prompt
        assert "Exit Reason" not in prompt
        assert "MFE" not in prompt
        assert "MAE" not in prompt
        assert "winner" not in prompt.lower()
        assert "loser" not in prompt.lower()

    def test_blinded_prompt_has_uncertainty_language(self):
        prompt = BLINDED_ANALYSIS_PROMPT.format(date="2025-01-15")
        assert "do NOT know" in prompt
        assert "genuine uncertainty" in prompt

    def test_enhancement_prompt_has_no_outcome_text(self):
        assert "ACTUAL OUTCOME" not in QUALITY_ENHANCEMENT_PROMPT
        assert "P&L" not in QUALITY_ENHANCEMENT_PROMPT
        assert "winner" not in QUALITY_ENHANCEMENT_PROMPT.lower()
        assert "loser" not in QUALITY_ENHANCEMENT_PROMPT.lower()

    def test_enhancement_prompt_preserves_structure(self):
        assert "WITHOUT changing" in QUALITY_ENHANCEMENT_PROMPT
        assert "directional thesis" in QUALITY_ENHANCEMENT_PROMPT
        assert "conviction level" in QUALITY_ENHANCEMENT_PROMPT


class TestSelfBlindingDataCollector:
    """Test the self-blinding pipeline in data_collector."""

    @patch("src.training.data_collector.generate_training_example")
    @patch("src.training.data_collector.load_config")
    @patch("src.training.data_collector.init_training_tables")
    @patch("sqlite3.connect")
    def test_stage1_receives_no_outcome(self, mock_conn, mock_init, mock_config, mock_gen):
        """Verify Stage 1 Claude call does NOT include outcome data."""
        mock_config.return_value = {"training": {"enabled": True}}

        # Mock a closed trade row
        mock_row = {
            "ticker": "AAPL", "recommendation_id": "rec-1",
            "enriched_prompt": "=== TECHNICAL DATA ===\nTicker: AAPL\nScore: 85/100",
            "created_at": "2025-01-15T10:00:00",
            "pnl_dollars": 150.0, "exit_reason": "target_1_hit",
            "pnl_pct": 3.5, "duration_days": 5,
            "max_favorable_excursion": 200, "max_adverse_excursion": -50,
        }

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.row_factory = None
        ctx.execute = MagicMock()
        ctx.execute.return_value.fetchall = MagicMock(return_value=[mock_row])
        ctx.commit = MagicMock()
        mock_conn.return_value = ctx

        # Track what prompts are sent to Claude
        calls = []
        def capture_call(system, user, **kwargs):
            calls.append({"system": system, "user": user})
            return "<why_now>Test</why_now><analysis>Test analysis</analysis><metadata>Conviction: 7</metadata>"
        mock_gen.side_effect = capture_call

        from src.training.data_collector import collect_training_examples_from_closed_trades
        collect_training_examples_from_closed_trades()

        # Stage 1 call should NOT contain outcome data
        assert len(calls) >= 1
        stage1_user = calls[0]["user"]
        assert "ACTUAL OUTCOME" not in stage1_user
        assert "pnl" not in stage1_user.lower()
        assert "exit_reason" not in stage1_user.lower()

        # Stage 1 system prompt should be the blinded prompt
        stage1_system = calls[0]["system"]
        assert "do NOT know" in stage1_system

    @patch("src.training.data_collector.generate_training_example")
    @patch("src.training.data_collector.load_config")
    @patch("src.training.data_collector.init_training_tables")
    @patch("sqlite3.connect")
    def test_stage2_receives_no_outcome(self, mock_conn, mock_init, mock_config, mock_gen):
        """Verify Stage 2 Claude call does NOT include outcome data."""
        mock_config.return_value = {"training": {"enabled": True}}

        mock_row = {
            "ticker": "AAPL", "recommendation_id": "rec-1",
            "enriched_prompt": "=== TECHNICAL DATA ===\nTicker: AAPL\nScore: 85/100",
            "created_at": "2025-01-15T10:00:00",
            "pnl_dollars": 150.0, "exit_reason": "target_1_hit",
            "pnl_pct": 3.5, "duration_days": 5,
            "max_favorable_excursion": 200, "max_adverse_excursion": -50,
        }

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.row_factory = None
        ctx.execute = MagicMock()
        ctx.execute.return_value.fetchall = MagicMock(return_value=[mock_row])
        ctx.commit = MagicMock()
        mock_conn.return_value = ctx

        calls = []
        def capture_call(system, user, **kwargs):
            calls.append({"system": system, "user": user})
            return "<why_now>Test</why_now><analysis>Test</analysis><metadata>Conviction: 7</metadata>"
        mock_gen.side_effect = capture_call

        from src.training.data_collector import collect_training_examples_from_closed_trades
        collect_training_examples_from_closed_trades()

        # If Stage 2 was called (should be calls[1])
        if len(calls) >= 2:
            stage2_user = calls[1]["user"]
            assert "ACTUAL OUTCOME" not in stage2_user
            assert "pnl" not in stage2_user.lower()
            assert "target_1_hit" not in stage2_user

    @patch("src.training.data_collector.generate_training_example")
    @patch("src.training.data_collector.load_config")
    @patch("src.training.data_collector.init_training_tables")
    @patch("sqlite3.connect")
    def test_stage1_failure_skips_example(self, mock_conn, mock_init, mock_config, mock_gen):
        """Stage 1 failure should skip the example entirely, not fall back."""
        mock_config.return_value = {"training": {"enabled": True}}

        mock_row = {
            "ticker": "AAPL", "recommendation_id": "rec-1",
            "enriched_prompt": "features",
            "created_at": "2025-01-15T10:00:00",
            "pnl_dollars": 150.0, "exit_reason": "target_1_hit",
            "pnl_pct": 3.5, "duration_days": 5,
            "max_favorable_excursion": 200, "max_adverse_excursion": -50,
        }

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.row_factory = None
        ctx.execute = MagicMock()
        ctx.execute.return_value.fetchall = MagicMock(return_value=[mock_row])
        ctx.commit = MagicMock()
        mock_conn.return_value = ctx

        # Stage 1 returns None (failure)
        mock_gen.return_value = None

        from src.training.data_collector import collect_training_examples_from_closed_trades
        count = collect_training_examples_from_closed_trades()
        assert count == 0

    @patch("src.training.data_collector.generate_training_example")
    @patch("src.training.data_collector.load_config")
    @patch("src.training.data_collector.init_training_tables")
    @patch("sqlite3.connect")
    def test_stage2_failure_uses_stage1(self, mock_conn, mock_init, mock_config, mock_gen):
        """Stage 2 failure should fall back to Stage 1 output."""
        mock_config.return_value = {"training": {"enabled": True}}

        mock_row = {
            "ticker": "AAPL", "recommendation_id": "rec-1",
            "enriched_prompt": "features",
            "created_at": "2025-01-15T10:00:00",
            "pnl_dollars": 150.0, "exit_reason": "target_1_hit",
            "pnl_pct": 3.5, "duration_days": 5,
            "max_favorable_excursion": 200, "max_adverse_excursion": -50,
        }

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.row_factory = None
        ctx.execute = MagicMock()
        ctx.execute.return_value.fetchall = MagicMock(return_value=[mock_row])
        ctx.commit = MagicMock()
        mock_conn.return_value = ctx

        # Stage 1 succeeds, Stage 2 fails
        call_count = [0]
        valid_stage1 = (
            "<why_now>AAPL is pulling back within an intact uptrend, and the current setup still "
            "offers a favorable entry against clear invalidation.</why_now>"
            "<analysis>The broader tape remains constructive, price is resting near support, and "
            "recent participation suggests buyers are still defending the trend. The setup has enough "
            "room to work over the next week without requiring an immediate breakout, which keeps the "
            "risk-reward profile acceptable for a swing entry.</analysis>"
            "<metadata>Conviction: 7\nDirection: LONG\nTime Horizon: 5-10 trading days\n"
            "Key Risk: Market breadth weakens and the pullback deepens into a true trend break.</metadata>"
        )

        def side_effect(system, user, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return valid_stage1
            return None  # Stage 2 fails
        mock_gen.side_effect = side_effect

        from src.training.data_collector import collect_training_examples_from_closed_trades
        count = collect_training_examples_from_closed_trades()
        assert count == 1

        # Verify the stored output is Stage 1 (check the INSERT call)
        insert_calls = [c for c in ctx.execute.call_args_list if "INSERT" in str(c)]
        if insert_calls:
            args = insert_calls[-1][0][1]
            output_text = args[-1]  # Last argument is output_text
            assert output_text == valid_stage1
