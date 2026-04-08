"""Tests for XML-tagged output format parsing and 11-section prompt structure."""

import pytest
from src.llm.packet_writer import _parse_llm_response, _build_feature_prompt, _interpret_skew


class TestXMLParsing:
    """Test XML parser extracts why_now, analysis, metadata correctly."""

    def test_full_xml_response(self):
        response = """
<why_now>
AAPL is pulling back 3.2% from its 50-day high into a rising 50-day MA, with RSI at 58 — a textbook continuation setup.
</why_now>

<analysis>
The thesis here is simple: Apple's trend structure remains intact with the 50-day MA rising at 0.8% slope, and this pullback offers a defined-risk entry into what has been the market's most reliable large-cap name.

Relative strength confirms the setup. AAPL has outperformed SPY by 4.2% over the past 3 months, with the RS line making new highs even as price consolidates. This divergence typically resolves higher.

Volume is contracting into the pullback — the 20-day volume ratio sits at 0.78x, suggesting sellers are exhausted rather than aggressive. The ATR(14) at $2.85 gives us a tight 1.5% risk from entry to stop.

The risk here is a broader market regime shift. SPY's RSI at 52 and breadth at 58% above the 50-day MA are acceptable but not strong. A VIX spike above 20 would invalidate this as a low-volatility continuation trade.
</analysis>

<metadata>
Conviction: 7
Direction: LONG
Time Horizon: 5-10 trading days
Key Risk: Broad market regime deterioration with VIX above 20
</metadata>
"""
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction == 7
        assert "AAPL is pulling back" in why_now
        assert "thesis here is simple" in analysis
        assert "broader market regime" in analysis

    def test_conviction_parsing_from_metadata(self):
        response = "<why_now>Test</why_now><analysis>Test analysis</analysis><metadata>Conviction: 9\nDirection: LONG</metadata>"
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction == 9
        assert why_now == "Test"
        assert analysis == "Test analysis"

    def test_conviction_clamping(self):
        response = "<why_now>Test</why_now><analysis>Test</analysis><metadata>Conviction: 15</metadata>"
        conviction, _, _ = _parse_llm_response(response)
        assert conviction == 10

        response2 = "<why_now>Test</why_now><analysis>Test</analysis><metadata>Conviction: 0</metadata>"
        conviction2, _, _ = _parse_llm_response(response2)
        # 0 doesn't match \d+ as 0 is clamped to 1 by max(1, min(10, 0))
        # Actually 0 matches \d+ but max(1, min(10, 0)) = max(1, 0) = 1
        assert conviction2 == 1


class TestPlainTextFallback:
    """Test backward compatibility with plain-text format."""

    def test_plain_text_parsing(self):
        response = """CONVICTION: 8 Strong trend with insider buying convergence

WHY NOW:
MSFT is pulling back into the 50-day MA with relative strength intact.

DEEPER ANALYSIS:
The setup offers a clean risk/reward with defined stop below the rising 50-day.

Additional analysis paragraph here.
"""
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction == 8
        assert "MSFT is pulling back" in why_now
        assert "clean risk/reward" in analysis

    def test_plain_text_no_conviction(self):
        response = """WHY NOW:
Some reason.

DEEPER ANALYSIS:
Some analysis.
"""
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction is None
        assert why_now is not None
        assert analysis is not None


class TestMalformedXML:
    """Test handling of malformed or partial XML."""

    def test_missing_analysis_tag(self):
        response = "<why_now>Test why now</why_now>"
        conviction, why_now, analysis = _parse_llm_response(response)
        # why_now found but analysis is None → returns None, None
        assert why_now is None
        assert analysis is None

    def test_empty_tags(self):
        response = "<why_now></why_now><analysis></analysis>"
        conviction, why_now, analysis = _parse_llm_response(response)
        # Empty strings are falsy → returns None, None
        assert why_now is None
        assert analysis is None

    def test_missing_metadata(self):
        response = "<why_now>Test</why_now><analysis>Analysis text</analysis>"
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction is None
        assert why_now == "Test"
        assert analysis == "Analysis text"

    def test_mixed_format_xml_and_plain(self):
        """XML tags take precedence over plain text markers."""
        response = """<why_now>XML why now</why_now>

WHY NOW:
Plain text why now

<analysis>XML analysis</analysis>

DEEPER ANALYSIS:
Plain text analysis
"""
        conviction, why_now, analysis = _parse_llm_response(response)
        assert why_now == "XML why now"
        assert analysis == "XML analysis"

    def test_no_format_at_all(self):
        response = "Just some random text without any format markers."
        conviction, why_now, analysis = _parse_llm_response(response)
        assert conviction is None
        assert why_now is None
        assert analysis is None


class TestElevenSections:
    def test_all_section_headers_present(self):
        """Verify all 11 === SECTION === headers appear in prompt."""
        features = {"price": 150.0, "atr": 3.5, "trend": "up", "spy_trend": "up", "vix": 18.0, "sector": "Technology", "sector_etf": "XLK"}
        prompt = _build_feature_prompt(features, "AAPL")
        for header in ["=== TECHNICAL DATA ===", "=== MARKET REGIME ===", "=== SECTOR RELATIVE ===",
                        "=== FUNDAMENTAL SNAPSHOT ===", "=== INSIDER ACTIVITY ===", "=== RECENT NEWS ===",
                        "=== MACRO CONTEXT ===", "=== OPTIONS FLOW ===", "=== EVENT CALENDAR ===",
                        "=== EARNINGS SIGNALS ===", "=== CROSS-ASSET CONTEXT ==="]:
            assert header in prompt, f"Missing: {header}"

    def test_no_subsection_numbering(self):
        from src.llm.packet_writer import _build_feature_prompt
        prompt = _build_feature_prompt({}, "TEST")
        assert "7.5" not in prompt
        assert "7.6" not in prompt
        assert "7.7" not in prompt

    def test_missing_data_graceful(self):
        from src.llm.packet_writer import _build_feature_prompt
        prompt = _build_feature_prompt({}, "TEST")
        assert "=== CROSS-ASSET CONTEXT ===" in prompt

    def test_skew_interpretation_bearish(self):
        assert "bearish" in _interpret_skew({"iv_skew_25d": 0.1}).lower()

    def test_skew_interpretation_bullish(self):
        assert "bullish" in _interpret_skew({"iv_skew_25d": -0.05}).lower()

    def test_skew_interpretation_normal(self):
        assert "Normal" in _interpret_skew({"iv_skew_25d": 0.02})

    def test_skew_interpretation_none(self):
        assert _interpret_skew({}) == "n/a"


class TestRandomSourceSubsetting:
    def test_subsetting_drops_some_sections(self):
        features = {"price": 150.0, "atr": 3.5, "trend": "up", "spy_trend": "up", "vix": 18.0}
        full = _build_feature_prompt(features, "TEST", subsetting=False)
        # Run 50 times — at least one should drop a section
        shorter_found = False
        for _ in range(50):
            p = _build_feature_prompt(features, "TEST", subsetting=True)
            if len(p) < len(full):
                shorter_found = True
                break
        assert shorter_found, "Subsetting should sometimes drop sections"

    def test_core_sections_never_dropped(self):
        features = {"price": 150.0, "atr": 3.5, "trend": "up", "spy_trend": "up", "vix": 18.0}
        for _ in range(50):
            prompt = _build_feature_prompt(features, "TEST", subsetting=True)
            assert "=== TECHNICAL DATA ===" in prompt
            assert "=== MARKET REGIME ===" in prompt
            assert "=== MACRO CONTEXT ===" in prompt
            assert "=== EVENT CALENDAR ===" in prompt
