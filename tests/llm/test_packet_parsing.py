"""Tests for B4 (Key Risk / llm_conviction_reason) and B8 (Expected Holding Period /
llm_timeout_days) LLM packet parsing.

Covers: positive parse, missing-field NULL fallback, boundary truncation (B4),
out-of-range / non-integer validation (B8), regression that existing Conviction:
integer parsing still works.
"""

import logging
import pytest

from src.llm.packet_writer import _parse_llm_response


def _make_response(conviction=7, key_risk="Earnings gap could reverse the move.",
                   holding_period="14 days", include_key_risk=True,
                   include_holding_period=True):
    """Build a minimal well-formed LLM response for testing."""
    metadata_lines = [f"Conviction: {conviction}", "Direction: LONG",
                      "Time Horizon: 5-10 trading days"]
    if include_key_risk:
        metadata_lines.append(f"Key Risk: {key_risk}")
    if include_holding_period:
        metadata_lines.append(f"Expected Holding Period: {holding_period}")
    metadata = "\n".join(metadata_lines)
    return (
        "<why_now>The setup is constructive with price pulling back to the 50-day MA "
        "on contracting volume.</why_now>\n"
        "<analysis>Paragraph one of analysis.\n\nParagraph two of analysis.</analysis>\n"
        f"<metadata>\n{metadata}\n</metadata>"
    )


class TestB4KeyRiskParsing:
    def test_positive_key_risk_extracted(self):
        """B4 positive: Key Risk line present → conviction_reason populated."""
        response = _make_response(key_risk="Earnings in 3 days could gap against position.",
                                  include_holding_period=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert conviction_reason == "Earnings in 3 days could gap against position."

    def test_missing_key_risk_falls_back_to_none(self):
        """B4 negative: No Key Risk line → conviction_reason is None, conviction still parses."""
        response = _make_response(conviction=7, include_key_risk=False, include_holding_period=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert conviction_reason is None
        assert conviction == 7

    def test_key_risk_truncation_at_4000_chars(self):
        """B4 boundary: Key Risk > 4000 chars → truncated with marker."""
        long_risk = "X" * 4500
        response = _make_response(key_risk=long_risk, include_holding_period=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert conviction_reason is not None
        assert len(conviction_reason) > 4000
        assert "... [truncated, original 4500 chars]" in conviction_reason
        assert conviction_reason.startswith("X" * 4000)

    def test_existing_conviction_integer_parsing_unchanged(self):
        """Regression: existing Conviction: N parsing still works after B4+B8 changes."""
        response = _make_response(conviction=8, include_key_risk=False, include_holding_period=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert conviction == 8
        assert why_now is not None
        assert deeper_analysis is not None


class TestB8HoldingPeriodParsing:
    def test_positive_holding_period_extracted(self):
        """B8 positive: Expected Holding Period: 14 days → timeout_days=14."""
        response = _make_response(holding_period="14 days", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days == 14

    def test_missing_holding_period_falls_back_to_none(self):
        """B8 negative: No Expected Holding Period line → timeout_days is None."""
        response = _make_response(include_key_risk=False, include_holding_period=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days is None

    def test_holding_period_lower_bound_valid(self):
        """B8 boundary: value=1 is valid lower bound."""
        response = _make_response(holding_period="1 days", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days == 1

    def test_holding_period_upper_bound_valid(self):
        """B8 boundary: value=60 is valid upper bound."""
        response = _make_response(holding_period="60 days", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days == 60

    def test_holding_period_out_of_range_low(self):
        """B8 validation: value=0 (below 1) → NULL with warning."""
        response = _make_response(holding_period="0 days", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days is None

    def test_holding_period_out_of_range_high(self):
        """B8 validation: value=90 (above 60) → NULL with warning."""
        response = _make_response(holding_period="90 days", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days is None

    def test_holding_period_non_integer_falls_back_to_none(self):
        """B8 validation: '2 weeks' (non-integer) → NULL with warning."""
        response = _make_response(holding_period="2 weeks", include_key_risk=False)
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert timeout_days is None

    def test_holding_period_out_of_range_logs_warning(self, caplog):
        """B8 validation: out-of-range emits [LLM_TIMEOUT_INVALID] warning."""
        response = _make_response(holding_period="90 days", include_key_risk=False)
        with caplog.at_level(logging.WARNING, logger="src.llm.packet_writer"):
            _parse_llm_response(response)
        assert any("[LLM_TIMEOUT_INVALID]" in rec.message for rec in caplog.records)

    def test_holding_period_non_integer_logs_warning(self, caplog):
        """B8 validation: non-integer emits [LLM_TIMEOUT_INVALID] warning."""
        response = _make_response(holding_period="2 weeks", include_key_risk=False)
        with caplog.at_level(logging.WARNING, logger="src.llm.packet_writer"):
            _parse_llm_response(response)
        assert any("[LLM_TIMEOUT_INVALID]" in rec.message for rec in caplog.records)


class TestBothFieldsTogether:
    def test_both_fields_parsed_together(self):
        """Integration: both Key Risk and Expected Holding Period present → both parsed."""
        response = _make_response(
            conviction=9,
            key_risk="Fed pivot could kill the rally.",
            holding_period="21 days",
        )
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)
        assert conviction == 9
        assert conviction_reason == "Fed pivot could kill the rally."
        assert timeout_days == 21

    def test_parse_failure_returns_five_tuple_with_nones(self):
        """Parser always returns 5-tuple even on degenerate input."""
        result = _parse_llm_response("garbage input that cannot be parsed at all")
        assert len(result) == 5
        conviction, why_now, deeper_analysis, conviction_reason, timeout_days = result
        assert conviction_reason is None
        assert timeout_days is None
