"""Tests for LLM writer modules:
- src/llm/postmortem_writer.py
- src/llm/watchlist_writer.py
"""

from unittest.mock import patch, MagicMock

import pytest

from src.llm.postmortem_writer import enhance_postmortem_with_llm
from src.llm.watchlist_writer import generate_watchlist_narrative


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> dict:
    base = {
        "ticker": "AAPL",
        "entry_price": 150.0,
        "exit_price": 155.0,
        "entry_date": "2025-06-01",
        "exit_date": "2025-06-05",
        "exit_reason": "target_hit",
        "pnl": 50.0,
        "pnl_pct": 3.3,
        "duration_days": 4,
        "mfe": 6.0,
        "mae": -2.0,
        "stop_price": 147.0,
        "target_1": 155.0,
        "target_2": 160.0,
        "atr_at_entry": 3.0,
        "thesis_text": "Pullback in strong uptrend.",
    }
    base.update(overrides)
    return base


def _make_candidate(ticker: str, score: float = 80.0) -> dict:
    return {
        "ticker": ticker,
        "score": score,
        "features": {
            "trend_state": "strong_uptrend",
            "relative_strength_state": "leading",
        },
    }


RULE_BASED = "Rule-based postmortem: trade hit target."


# ---------------------------------------------------------------------------
# enhance_postmortem_with_llm
# ---------------------------------------------------------------------------

class TestEnhancePostmortemWithLlm:
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": False}})
    def test_llm_disabled_returns_fallback(self, mock_cfg):
        result = enhance_postmortem_with_llm(_make_trade(), RULE_BASED)
        assert result == RULE_BASED

    @patch("src.llm.postmortem_writer.generate", return_value=None)
    @patch("src.llm.postmortem_writer.is_llm_available", return_value=False)
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": True}})
    def test_llm_unavailable_returns_fallback(self, mock_cfg, mock_avail, mock_gen):
        result = enhance_postmortem_with_llm(_make_trade(), RULE_BASED)
        assert result == RULE_BASED
        mock_gen.assert_not_called()

    @patch("src.llm.postmortem_writer.generate", return_value="LLM-enhanced analysis of AAPL trade.")
    @patch("src.llm.postmortem_writer.is_llm_available", return_value=True)
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": True}})
    def test_llm_available_returns_enhanced(self, mock_cfg, mock_avail, mock_gen):
        result = enhance_postmortem_with_llm(_make_trade(), RULE_BASED)
        assert result == "LLM-enhanced analysis of AAPL trade."
        mock_gen.assert_called_once()

    @patch("src.llm.postmortem_writer.generate", return_value=None)
    @patch("src.llm.postmortem_writer.is_llm_available", return_value=True)
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": True}})
    def test_llm_generation_fails_returns_fallback(self, mock_cfg, mock_avail, mock_gen):
        result = enhance_postmortem_with_llm(_make_trade(), RULE_BASED)
        assert result == RULE_BASED

    @patch("src.llm.postmortem_writer.generate", return_value="Enhanced text")
    @patch("src.llm.postmortem_writer.is_llm_available", return_value=True)
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": True}})
    def test_prompt_contains_ticker(self, mock_cfg, mock_avail, mock_gen):
        enhance_postmortem_with_llm(_make_trade(ticker="GOOG"), RULE_BASED)
        call_args = mock_gen.call_args
        prompt = call_args[0][0]  # first positional arg
        assert "GOOG" in prompt

    @patch("src.llm.postmortem_writer.generate", return_value="Enhanced text")
    @patch("src.llm.postmortem_writer.is_llm_available", return_value=True)
    @patch("src.llm.postmortem_writer.load_config", return_value={"llm": {"enabled": True}})
    def test_prompt_contains_pnl(self, mock_cfg, mock_avail, mock_gen):
        enhance_postmortem_with_llm(_make_trade(pnl=-20.0, pnl_pct=-1.5), RULE_BASED)
        prompt = mock_gen.call_args[0][0]
        assert "-20.00" in prompt
        assert "-1.5%" in prompt


# ---------------------------------------------------------------------------
# generate_watchlist_narrative
# ---------------------------------------------------------------------------

class TestGenerateWatchlistNarrative:
    def test_llm_disabled_returns_none(self):
        config = {"llm": {"enabled": False}}
        result = generate_watchlist_narrative([], [], config)
        assert result is None

    @patch("src.llm.watchlist_writer.is_llm_available", return_value=False)
    def test_llm_unavailable_returns_none(self, mock_avail):
        config = {"llm": {"enabled": True}}
        result = generate_watchlist_narrative([], [], config)
        assert result is None

    @patch("src.llm.watchlist_writer.generate", return_value="Market narrative text.")
    @patch("src.llm.watchlist_writer.is_llm_available", return_value=True)
    def test_llm_available_returns_narrative(self, mock_avail, mock_gen):
        config = {"llm": {"enabled": True}}
        pw = [_make_candidate("AAPL", 90)]
        wl = [_make_candidate("MSFT", 75)]
        result = generate_watchlist_narrative(pw, wl, config)
        assert result == "Market narrative text."
        mock_gen.assert_called_once()

    @patch("src.llm.watchlist_writer.generate", return_value=None)
    @patch("src.llm.watchlist_writer.is_llm_available", return_value=True)
    def test_llm_generation_fails_returns_none(self, mock_avail, mock_gen):
        config = {"llm": {"enabled": True}}
        result = generate_watchlist_narrative([], [], config)
        assert result is None

    @patch("src.llm.watchlist_writer.generate", return_value="Narrative")
    @patch("src.llm.watchlist_writer.is_llm_available", return_value=True)
    def test_prompt_includes_tickers(self, mock_avail, mock_gen):
        config = {"llm": {"enabled": True}}
        pw = [_make_candidate("GOOG", 88)]
        wl = [_make_candidate("TSLA", 70)]
        generate_watchlist_narrative(pw, wl, config)
        prompt = mock_gen.call_args[0][0]
        assert "GOOG" in prompt
        assert "TSLA" in prompt

    @patch("src.llm.watchlist_writer.generate", return_value="Narrative")
    @patch("src.llm.watchlist_writer.is_llm_available", return_value=True)
    def test_empty_lists_still_generates(self, mock_avail, mock_gen):
        config = {"llm": {"enabled": True}}
        result = generate_watchlist_narrative([], [], config)
        assert result == "Narrative"
        prompt = mock_gen.call_args[0][0]
        assert "None" in prompt  # The "None" placeholder for empty lists
