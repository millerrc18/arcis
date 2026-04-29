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


class TestEnrichFeaturesAsOfRouting:
    """Tests for the as_of parameter routing in enrich_features (#854).

    Verifies that:
    - Default (as_of=None) routes news fetch to fetch_recent_news (runtime)
    - as_of='YYYY-MM-DD' routes to fetch_historical_news (TEMPORAL COMPLIANCE)
    - The same feat dict shape is produced either way

    This locks the routing contract that Sprint 1.C Phase 4 corpus
    generation depends on.
    """

    @staticmethod
    def _stub_news() -> dict:
        return {
            "headline_count": 0,
            "headlines": [],
            "summary": "stub for routing test",
            "news_sentiment": "neutral",
            "last_news_date": None,
        }

    def test_default_routes_to_fetch_recent_news(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True, "finnhub_api_key": "stub-key"}}

        with (
            patch("src.data_enrichment.enricher._rate_limit"),
            patch("src.data_enrichment.macro.fetch_macro_context", return_value={}),
            patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
            patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None),
            patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()) as recent,
            patch("src.data_enrichment.news.fetch_historical_news") as historical,
        ):
            result = enrich_features(features, config)  # no as_of

        assert recent.called, "Runtime path should call fetch_recent_news"
        assert not historical.called, "Runtime path must NOT call fetch_historical_news"
        assert "news_summary" in result["AAPL"]

    def test_as_of_routes_to_fetch_historical_news(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True, "finnhub_api_key": "stub-key"}}

        with (
            patch("src.data_enrichment.enricher._rate_limit"),
            patch("src.data_enrichment.macro.fetch_macro_context", return_value={}),
            patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
            patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None),
            patch("src.data_enrichment.news.fetch_recent_news") as recent,
            patch(
                "src.data_enrichment.news.fetch_historical_news",
                return_value=self._stub_news(),
            ) as historical,
        ):
            result = enrich_features(features, config, as_of="2024-06-15")

        assert historical.called, "Backtest path should call fetch_historical_news"
        assert not recent.called, "Backtest path must NOT call fetch_recent_news"
        # Confirm as_of was passed through
        kwargs = historical.call_args.kwargs
        assert kwargs.get("as_of_date") == "2024-06-15"
        assert "news_summary" in result["AAPL"]

    def test_as_of_does_not_break_other_sections(self):
        """Backtest path is additive — non-news sections still populate."""
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        with (
            patch("src.data_enrichment.enricher._rate_limit"),
            patch("src.data_enrichment.macro.fetch_macro_context", return_value={"fed_stance": "neutral"}),
            patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
            patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None),
            patch("src.data_enrichment.news.fetch_historical_news", return_value=self._stub_news()),
        ):
            result = enrich_features(features, config, as_of="2024-06-15")

        assert "macro_summary" in result["AAPL"]
        assert "fundamental_summary" in result["AAPL"]
        assert "insider_summary" in result["AAPL"]
        assert "news_summary" in result["AAPL"]


class TestMacroAsOfRouting:
    """Tests for the as_of parameter on fetch_macro_context (#855).

    Verifies that:
    - Default (as_of=None) preserves current FRED 'now' behavior
    - as_of='YYYY-MM-DD' passes observation_end=as_of to FRED API calls
      (FRED supports PIT lookups natively via observation_end)
    - Cache keys differ between as_of=None and as_of=set so PIT data
      and "now" data don't collide on disk
    - enrich_features routes its as_of value through to fetch_macro_context

    This locks the FRED PIT-routing contract that Sprint 1.C Phase 4
    corpus generation depends on for Section 7 of the LLM prompt.
    """

    def test_default_as_of_uses_current_fred_behavior(self):
        """Without as_of, _fetch_series should NOT pass observation_end."""
        from src.data_enrichment.macro import _fetch_series

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"observations": [{"value": "5.25"}]}
        mock_resp.raise_for_status.return_value = None

        with patch("src.data_enrichment.macro.requests.get", return_value=mock_resp) as get:
            result = _fetch_series("FEDFUNDS", "stub-key")

        assert result == 5.25
        kwargs = get.call_args.kwargs
        params = kwargs.get("params", {})
        assert "observation_end" not in params, (
            "Runtime path must NOT send observation_end to FRED"
        )

    def test_as_of_passes_observation_end_to_fred(self):
        """When as_of is set, _fetch_series should pass observation_end to FRED."""
        from src.data_enrichment.macro import _fetch_series

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"observations": [{"value": "2.50"}]}
        mock_resp.raise_for_status.return_value = None

        with patch("src.data_enrichment.macro.requests.get", return_value=mock_resp) as get:
            result = _fetch_series("FEDFUNDS", "stub-key", as_of="2024-06-15")

        assert result == 2.50
        kwargs = get.call_args.kwargs
        params = kwargs.get("params", {})
        assert params.get("observation_end") == "2024-06-15", (
            "Backtest path must send observation_end=as_of to FRED for PIT lookup"
        )

    def test_fetch_macro_context_propagates_as_of(self):
        """fetch_macro_context should forward as_of to every _fetch_series call."""
        from src.data_enrichment.macro import fetch_macro_context

        with (
            patch("src.data_enrichment.macro._load_cached", return_value=None),
            patch("src.data_enrichment.macro._save_cache"),
            patch("src.data_enrichment.macro._fetch_series", return_value=4.0) as series,
            patch("src.data_enrichment.macro._fetch_cpi_yoy", return_value=2.5) as cpi,
            patch("src.data_enrichment.macro.time.sleep"),
        ):
            result = fetch_macro_context(fred_api_key="stub-key", as_of="2024-06-15")

        assert isinstance(result, dict)
        assert result.get("fed_funds_rate") == 4.0
        # Every _fetch_series call should have received as_of
        for call in series.call_args_list:
            assert call.kwargs.get("as_of") == "2024-06-15", (
                f"_fetch_series called without as_of: {call}"
            )
        # CPI YoY helper should also receive as_of
        cpi_kwargs = cpi.call_args.kwargs
        assert cpi_kwargs.get("as_of") == "2024-06-15"

    def test_cache_key_differs_between_as_of_modes(self):
        """Cache key for as_of=None must differ from as_of='YYYY-MM-DD' so
        PIT data and 'now' data don't collide on disk."""
        from src.data_enrichment.macro import _get_cache_path

        path_now = _get_cache_path()
        path_pit = _get_cache_path(as_of="2024-06-15")

        assert path_now != path_pit, (
            "PIT cache path must differ from runtime cache path"
        )
        assert "2024-06-15" in str(path_pit), (
            "PIT cache filename should encode as_of for traceability"
        )

    def test_enricher_passes_as_of_to_macro(self):
        """enrich_features must route its as_of through to fetch_macro_context."""
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        with (
            patch("src.data_enrichment.enricher._rate_limit"),
            patch(
                "src.data_enrichment.macro.fetch_macro_context",
                return_value={"fed_stance": "neutral"},
            ) as macro,
            patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
            patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None),
            patch("src.data_enrichment.news.fetch_historical_news", return_value={
                "headline_count": 0, "headlines": [], "summary": "stub",
                "news_sentiment": "neutral", "last_news_date": None,
            }),
        ):
            enrich_features(features, config, as_of="2024-06-15")

        assert macro.called
        kwargs = macro.call_args.kwargs
        assert kwargs.get("as_of") == "2024-06-15", (
            "enrich_features must forward as_of to fetch_macro_context"
        )

    def test_enricher_default_does_not_pass_as_of_to_macro(self):
        """Without as_of, fetch_macro_context should be called with as_of=None."""
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True, "finnhub_api_key": "stub"}}

        with (
            patch("src.data_enrichment.enricher._rate_limit"),
            patch(
                "src.data_enrichment.macro.fetch_macro_context",
                return_value={"fed_stance": "neutral"},
            ) as macro,
            patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
            patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None),
            patch("src.data_enrichment.news.fetch_recent_news", return_value={
                "headline_count": 0, "headlines": [], "summary": "stub",
                "news_sentiment": "neutral", "last_news_date": None,
            }),
        ):
            enrich_features(features, config)  # no as_of

        assert macro.called
        kwargs = macro.call_args.kwargs
        # Either explicit None, or omitted entirely (function default is None)
        assert kwargs.get("as_of") is None
