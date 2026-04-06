"""Tests for LLM conviction extraction stages (#309, #312)."""

import pytest
from unittest.mock import patch


class TestConvictionExtraction:
    """Test the conviction extraction cascade in _parse_llm_response."""

    def _parse(self, response):
        from src.llm.packet_writer import _parse_llm_response
        conviction, why_now, analysis = _parse_llm_response(response)
        return conviction

    def test_stage1_xml_metadata(self):
        resp = (
            "<why_now>Technical setup looks strong.</why_now>"
            "<analysis>Detailed analysis paragraph one.\n\nParagraph two with more details.</analysis>"
            "<metadata>Conviction: 8\nDirection: LONG\nTime Horizon: 5 days\nKey Risk: earnings</metadata>"
        )
        assert self._parse(resp) == 8

    def test_stage6_catchall_prose(self):
        """Stage 6 catch-all: extract conviction from unstructured prose."""
        resp = (
            "<why_now>Looks good.</why_now>"
            "<analysis>" + "This is a long analysis. " * 20 + "</analysis>\n"
            "Overall my conviction for this trade is 7 based on the setup."
        )
        assert self._parse(resp) == 7

    def test_stage6_catchall_various_formats(self):
        """Stage 6 handles 'conviction of 9' and similar patterns."""
        resp = (
            "<why_now>Test.</why_now>"
            "<analysis>" + "Analysis paragraph. " * 15 + "</analysis>\n"
            "I give this a conviction of 9."
        )
        assert self._parse(resp) == 9

    def test_all_stages_fail_returns_none(self):
        """When no conviction pattern is found, returns None."""
        resp = (
            "<why_now>Test setup.</why_now>"
            "<analysis>" + "Long analysis content. " * 15 + "</analysis>\n"
            "No rating provided anywhere in this response."
        )
        assert self._parse(resp) is None

    def test_stage6_ignores_out_of_range(self):
        """Stage 6 only matches values 1-10."""
        resp = (
            "<why_now>Test.</why_now>"
            "<analysis>" + "Analysis. " * 20 + "</analysis>\n"
            "Conviction level is 15 which is very high."
        )
        # 15 is outside 1-10, should not match stage 6
        assert self._parse(resp) is None
