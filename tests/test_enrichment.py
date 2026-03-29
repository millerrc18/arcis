"""Tests for data enrichment: fundamentals, insiders, macro formatters and enricher."""

from unittest.mock import patch, MagicMock

import pytest


class TestFundamentalSummaryFormatter:
    def test_format_with_full_data(self):
        from src.data_enrichment.fundamentals import format_fundamental_summary
        data = {
            "revenue_ttm": 394_328_000_000,
            "revenue_yoy_growth": 0.08,
            "net_income_ttm": 93_736_000_000,
            "gross_margin": 0.462,
            "operating_margin": 0.317,
            "eps_diluted_ttm": 6.42,
            "pe_ratio": None,
            "last_filing_date": "2025-11-01",
            "last_filing_type": "10-Q",
            "data_as_of_quarter": "2025-09-30",
        }
        result = format_fundamental_summary(data, price=183.0)
        assert "Revenue" in result
        assert "$394.3B" in result
        assert "+8.0% YoY" in result
        assert "EPS" in result
        assert "P/E" in result

    def test_format_with_none(self):
        from src.data_enrichment.fundamentals import format_fundamental_summary
        assert format_fundamental_summary(None) == "No fundamental data available"

    def test_format_with_empty_data(self):
        from src.data_enrichment.fundamentals import format_fundamental_summary
        data = {
            "revenue_ttm": None,
            "revenue_yoy_growth": None,
            "net_income_ttm": None,
            "gross_margin": None,
            "operating_margin": None,
            "eps_diluted_ttm": None,
            "pe_ratio": None,
            "last_filing_date": None,
            "last_filing_type": None,
            "data_as_of_quarter": None,
        }
        result = format_fundamental_summary(data)
        assert result == "No fundamental data available"

    def test_pe_computed_from_price(self):
        from src.data_enrichment.fundamentals import format_fundamental_summary
        data = {"eps_diluted_ttm": 10.0}
        result = format_fundamental_summary(data, price=200.0)
        assert "P/E: 20.0" in result


class TestFormatDollars:
    def test_billions(self):
        from src.data_enrichment.fundamentals import _format_dollars
        assert _format_dollars(1_500_000_000) == "$1.5B"

    def test_millions(self):
        from src.data_enrichment.fundamentals import _format_dollars
        assert _format_dollars(250_000_000) == "$250.0M"

    def test_trillions(self):
        from src.data_enrichment.fundamentals import _format_dollars
        assert _format_dollars(2_500_000_000_000) == "$2.5T"

    def test_negative(self):
        from src.data_enrichment.fundamentals import _format_dollars
        assert _format_dollars(-500_000_000) == "-$500.0M"


class TestInsiderSummaryFormatter:
    def test_format_with_net_selling(self):
        from src.data_enrichment.insiders import format_insider_summary
        data = {
            "insider_buys_90d": 3,
            "insider_sells_90d": 7,
            "insider_net_shares": -45000,
            "insider_net_value": -2340000,
            "insider_sentiment": "net_selling",
            "notable_transactions": [
                "CFO sold 15,000 shares ($780,000) on 2025-12-15",
            ],
            "last_transaction_date": "2025-12-15",
        }
        result = format_insider_summary(data)
        assert "Net selling" in result
        assert "7 sells vs 3 buys" in result

    def test_format_with_none(self):
        from src.data_enrichment.insiders import format_insider_summary
        assert format_insider_summary(None) == "No insider data available"

    def test_format_no_activity(self):
        from src.data_enrichment.insiders import format_insider_summary
        data = {"insider_sentiment": "no_activity"}
        result = format_insider_summary(data)
        assert "No transactions" in result


class TestMacroSummaryFormatter:
    def test_format_with_full_data(self):
        from src.data_enrichment.macro import format_macro_summary
        data = {
            "fed_funds_rate": 4.50,
            "fed_stance": "restrictive",
            "yield_curve_10y2y": 0.35,
            "yield_curve_signal": "normal",
            "cpi_yoy": 2.8,
            "unemployment_rate": 4.1,
            "economic_regime": "late_cycle",
            "last_fomc_action": "hold",
            "last_fomc_date": "2026-03-19",
        }
        result = format_macro_summary(data)
        assert "Restrictive" in result
        assert "4.50%" in result
        assert "Normal" in result
        assert "2.8%" in result
        assert "4.1%" in result

    def test_format_with_defaults(self):
        from src.data_enrichment.macro import format_macro_summary
        data = {
            "fed_funds_rate": None,
            "fed_stance": "unknown",
            "yield_curve_10y2y": None,
            "yield_curve_signal": "unknown",
            "cpi_yoy": None,
            "unemployment_rate": None,
            "economic_regime": "mid_cycle",
            "last_fomc_action": "unknown",
            "last_fomc_date": None,
        }
        result = format_macro_summary(data)
        assert "Mid Cycle" in result


class TestMacroClassifications:
    def test_fed_stance(self):
        from src.data_enrichment.macro import _classify_fed_stance
        assert _classify_fed_stance(5.0) == "restrictive"
        assert _classify_fed_stance(3.0) == "neutral"
        assert _classify_fed_stance(1.0) == "accommodative"
        assert _classify_fed_stance(None) == "unknown"

    def test_yield_curve(self):
        from src.data_enrichment.macro import _classify_yield_curve
        assert _classify_yield_curve(-0.5) == "inverted"
        assert _classify_yield_curve(0.3) == "flat"
        assert _classify_yield_curve(1.0) == "normal"
        assert _classify_yield_curve(2.0) == "steep"
        assert _classify_yield_curve(None) == "unknown"


class TestEnricherHandlesFailures:
    def test_enricher_returns_features_on_failure(self):
        """Enricher should never crash — returns features unchanged on error."""
        from src.data_enrichment.enricher import enrich_features

        features = {
            "AAPL": {"current_price": 185.0, "ticker": "AAPL"},
            "MSFT": {"current_price": 420.0, "ticker": "MSFT"},
        }
        config = {"data_enrichment": {"enabled": True}}

        # Mock all external API calls to fail
        with patch("src.data_enrichment.macro.fetch_macro_context", side_effect=Exception("API down")):
            result = enrich_features(features, config)

        # Should still have the original features
        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"]["current_price"] == 185.0

    def test_enricher_disabled(self):
        from src.data_enrichment.enricher import enrich_features
        features = {"AAPL": {"current_price": 185.0}}
        config = {"data_enrichment": {"enabled": False}}
        result = enrich_features(features, config)
        assert result == features

    def test_enricher_no_config(self):
        from src.data_enrichment.enricher import enrich_features
        features = {"AAPL": {"current_price": 185.0}}
        config = {}
        # enabled defaults to True, but should handle missing API keys gracefully
        result = enrich_features(features, config)
        assert "AAPL" in result
        assert "macro_summary" in result["AAPL"]
