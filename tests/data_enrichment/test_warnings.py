"""Tests for the enrichment-pit-warnings collection channel (#99).

Each fetcher in src/data_enrichment/ accepts an optional `warnings` list
parameter. When supplied, the fetcher appends prefixed warning strings to
the list (mutating in place) whenever it encounters a coverage limit, a
PIT compromise, or a stale-data fallback. enricher.enrich_features
propagates the warnings up via a `warnings_out` parameter.

Warning message format: `<source>_<category>:<ticker_or_scope>:<as_of>`
e.g. `news_no_api_key:AAPL:2024-06-15`

This test module exists in tests/data_enrichment/ (a new test directory)
per the dispatch's coordinated scope-fence with parallel agent #98 — it
must NOT touch tests/evaluation/test_corpus_generator.py (that file is
in #104's scope).
"""
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# news.py — fetch_recent_news + fetch_historical_news
# ---------------------------------------------------------------------------


class TestNewsWarnings:
    def test_fetch_recent_news_no_api_key_emits_warning(self, monkeypatch):
        from src.data_enrichment.news import fetch_recent_news

        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None):
            result = fetch_recent_news("AAPL", finnhub_api_key=None, warnings=warnings)

        assert result is None
        assert any(w.startswith("news_no_api_key:") for w in warnings), (
            f"Expected news_no_api_key warning, got: {warnings}"
        )
        assert "AAPL" in warnings[0]

    def test_fetch_recent_news_no_warnings_on_success(self):
        from src.data_enrichment.news import fetch_recent_news

        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None), \
             patch("src.data_enrichment.news.requests.get") as mock_get, \
             patch("src.data_enrichment.news.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=[
                {"headline": "Test", "source": "Reuters", "datetime": 1700000000, "category": "company"},
            ])
            mock_get.return_value = mock_resp
            result = fetch_recent_news("AAPL", finnhub_api_key="stub-key", warnings=warnings)

        assert result is not None
        assert warnings == []

    def test_fetch_recent_news_coverage_gap_emits_warning(self):
        """When Finnhub returns zero articles, emit a coverage_gap warning."""
        from src.data_enrichment.news import fetch_recent_news

        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None), \
             patch("src.data_enrichment.news.requests.get") as mock_get, \
             patch("src.data_enrichment.news.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=[])
            mock_get.return_value = mock_resp
            result = fetch_recent_news("AAPL", finnhub_api_key="stub-key", warnings=warnings)

        assert result is not None
        assert result["headline_count"] == 0
        assert any(w.startswith("news_coverage_gap:") for w in warnings), (
            f"Expected news_coverage_gap warning, got: {warnings}"
        )

    def test_fetch_recent_news_api_failure_emits_warning(self):
        from src.data_enrichment.news import fetch_recent_news

        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None), \
             patch("src.data_enrichment.news.requests.get") as mock_get:
            import requests as req_lib
            mock_get.side_effect = req_lib.RequestException("boom")
            result = fetch_recent_news("AAPL", finnhub_api_key="stub-key", warnings=warnings)

        assert result is None
        assert any(w.startswith("news_fetch_failed:") for w in warnings), (
            f"Expected news_fetch_failed warning, got: {warnings}"
        )

    def test_fetch_historical_news_invalid_as_of_emits_warning(self):
        from src.data_enrichment.news import fetch_historical_news

        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None):
            result = fetch_historical_news(
                "AAPL", as_of_date="not-a-date", finnhub_api_key="stub-key",
                warnings=warnings,
            )
        assert result is None
        assert any(w.startswith("news_invalid_as_of:") for w in warnings), (
            f"Expected news_invalid_as_of warning, got: {warnings}"
        )

    def test_fetch_historical_news_coverage_gap_emits_warning(self):
        """Empty Finnhub response in historical mode emits coverage_gap."""
        from src.data_enrichment.news import fetch_historical_news

        warnings: list[str] = []
        with patch("src.data_enrichment.news._load_cached", return_value=None), \
             patch("src.data_enrichment.news.requests.get") as mock_get, \
             patch("src.data_enrichment.news.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=[])
            mock_get.return_value = mock_resp
            result = fetch_historical_news(
                "AAPL", as_of_date="2024-06-15",
                finnhub_api_key="stub-key", warnings=warnings,
            )
        assert result is not None
        assert any(w.startswith("news_coverage_gap:") for w in warnings)

    def test_fetch_recent_news_warnings_param_is_optional(self, monkeypatch):
        """Backward compat: callers that don't pass warnings still work."""
        from src.data_enrichment.news import fetch_recent_news

        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        with patch("src.data_enrichment.news._load_cached", return_value=None):
            result = fetch_recent_news("AAPL", finnhub_api_key=None)
        assert result is None


# ---------------------------------------------------------------------------
# macro.py — fetch_macro_context
# ---------------------------------------------------------------------------


class TestMacroWarnings:
    def test_fetch_macro_context_no_api_key_emits_warning(self):
        from src.data_enrichment.macro import fetch_macro_context

        warnings: list[str] = []
        # Bypass the on-disk cache so the no-api-key branch actually runs
        # — without this patch a stale cache shadows the no-key path.
        with patch("src.data_enrichment.macro._load_cached", return_value=None):
            result = fetch_macro_context(fred_api_key=None, warnings=warnings)
        assert isinstance(result, dict)
        assert any(w.startswith("macro_no_api_key:") for w in warnings), (
            f"Expected macro_no_api_key warning, got: {warnings}"
        )

    def test_fetch_macro_context_series_unavailable_emits_warning(self):
        """If a FRED series returns None, emit per-series unavailable warning."""
        from src.data_enrichment.macro import fetch_macro_context

        warnings: list[str] = []
        with patch("src.data_enrichment.macro._load_cached", return_value=None), \
             patch("src.data_enrichment.macro._save_cache"), \
             patch("src.data_enrichment.macro._fetch_series", return_value=None), \
             patch("src.data_enrichment.macro._fetch_cpi_yoy", return_value=None), \
             patch("src.data_enrichment.macro.time.sleep"):
            result = fetch_macro_context(fred_api_key="stub-key", warnings=warnings)

        assert isinstance(result, dict)
        assert any(w.startswith("macro_series_unavailable:") for w in warnings), (
            f"Expected macro_series_unavailable warning, got: {warnings}"
        )

    def test_fetch_macro_context_fetch_failed_emits_warning(self):
        from src.data_enrichment.macro import fetch_macro_context

        warnings: list[str] = []
        with patch("src.data_enrichment.macro._load_cached", return_value=None), \
             patch("src.data_enrichment.macro._fetch_series", side_effect=Exception("boom")), \
             patch("src.data_enrichment.macro.time.sleep"):
            result = fetch_macro_context(fred_api_key="stub-key", warnings=warnings)

        assert isinstance(result, dict)
        assert any(w.startswith("macro_fetch_failed:") for w in warnings), (
            f"Expected macro_fetch_failed warning, got: {warnings}"
        )

    def test_fetch_macro_context_no_warnings_on_success(self):
        from src.data_enrichment.macro import fetch_macro_context

        warnings: list[str] = []
        with patch("src.data_enrichment.macro._load_cached", return_value=None), \
             patch("src.data_enrichment.macro._save_cache"), \
             patch("src.data_enrichment.macro._fetch_series", return_value=4.0), \
             patch("src.data_enrichment.macro._fetch_cpi_yoy", return_value=2.5), \
             patch("src.data_enrichment.macro.time.sleep"):
            result = fetch_macro_context(fred_api_key="stub-key", warnings=warnings)

        assert isinstance(result, dict)
        assert warnings == []

    def test_fetch_macro_context_warnings_param_is_optional(self):
        from src.data_enrichment.macro import fetch_macro_context
        result = fetch_macro_context(fred_api_key=None)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# fundamentals.py — fetch_fundamental_snapshot
# ---------------------------------------------------------------------------


class TestFundamentalsWarnings:
    def test_fetch_fundamental_snapshot_no_cik_emits_warning(self):
        from src.data_enrichment.fundamentals import fetch_fundamental_snapshot

        warnings: list[str] = []
        with patch("src.data_enrichment.fundamentals._load_cached", return_value=None), \
             patch("src.data_enrichment.fundamentals._get_cik", return_value=None):
            result = fetch_fundamental_snapshot("ZZZZ", warnings=warnings)
        assert result is None
        assert any(w.startswith("fundamentals_no_cik:") for w in warnings), (
            f"Expected fundamentals_no_cik warning, got: {warnings}"
        )

    def test_fetch_fundamental_snapshot_fetch_failed_emits_warning(self):
        from src.data_enrichment.fundamentals import fetch_fundamental_snapshot

        warnings: list[str] = []
        with patch("src.data_enrichment.fundamentals._load_cached", return_value=None), \
             patch("src.data_enrichment.fundamentals._get_cik", return_value="0000320193"), \
             patch("src.data_enrichment.fundamentals._fetch_concept", side_effect=Exception("boom")):
            result = fetch_fundamental_snapshot("AAPL", warnings=warnings)
        assert result is None
        assert any(w.startswith("fundamentals_fetch_failed:") for w in warnings), (
            f"Expected fundamentals_fetch_failed warning, got: {warnings}"
        )

    def test_fetch_fundamental_snapshot_no_data_emits_warning(self):
        """When XBRL concepts return empty, emit fundamentals_no_data warning."""
        from src.data_enrichment.fundamentals import fetch_fundamental_snapshot

        warnings: list[str] = []
        with patch("src.data_enrichment.fundamentals._load_cached", return_value=None), \
             patch("src.data_enrichment.fundamentals._get_cik", return_value="0000320193"), \
             patch("src.data_enrichment.fundamentals._fetch_concept", return_value=None), \
             patch("src.data_enrichment.fundamentals.time.sleep"):
            result = fetch_fundamental_snapshot("AAPL", warnings=warnings)
        assert any(w.startswith("fundamentals_no_data:") for w in warnings), (
            f"Expected fundamentals_no_data warning, got: {warnings}"
        )

    def test_fetch_fundamental_snapshot_warnings_param_is_optional(self):
        from src.data_enrichment.fundamentals import fetch_fundamental_snapshot
        with patch("src.data_enrichment.fundamentals._load_cached", return_value=None), \
             patch("src.data_enrichment.fundamentals._get_cik", return_value=None):
            result = fetch_fundamental_snapshot("ZZZZ")
        assert result is None


# ---------------------------------------------------------------------------
# insiders.py — fetch_insider_activity
# ---------------------------------------------------------------------------


class TestInsidersWarnings:
    def test_fetch_insider_activity_no_api_key_emits_warning(self, monkeypatch):
        from src.data_enrichment.insiders import fetch_insider_activity

        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        warnings: list[str] = []
        with patch("src.data_enrichment.insiders._load_cached", return_value=None):
            result = fetch_insider_activity("AAPL", finnhub_api_key=None, warnings=warnings)
        assert result is None
        assert any(w.startswith("insiders_no_api_key:") for w in warnings), (
            f"Expected insiders_no_api_key warning, got: {warnings}"
        )

    def test_fetch_insider_activity_invalid_as_of_emits_warning(self):
        from src.data_enrichment.insiders import fetch_insider_activity

        warnings: list[str] = []
        with patch("src.data_enrichment.insiders._load_cached", return_value=None):
            result = fetch_insider_activity(
                "AAPL", finnhub_api_key="stub-key",
                as_of="not-a-date", warnings=warnings,
            )
        assert result is None
        assert any(w.startswith("insiders_invalid_as_of:") for w in warnings), (
            f"Expected insiders_invalid_as_of warning, got: {warnings}"
        )

    def test_fetch_insider_activity_fetch_failed_emits_warning(self):
        from src.data_enrichment.insiders import fetch_insider_activity

        warnings: list[str] = []
        with patch("src.data_enrichment.insiders._load_cached", return_value=None), \
             patch("src.data_enrichment.insiders.requests.get") as mock_get, \
             patch("src.data_enrichment.insiders.time.sleep"):
            import requests as req_lib
            mock_get.side_effect = req_lib.RequestException("boom")
            result = fetch_insider_activity(
                "AAPL", finnhub_api_key="stub-key", warnings=warnings,
            )
        assert result is None
        assert any(w.startswith("insiders_fetch_failed:") for w in warnings), (
            f"Expected insiders_fetch_failed warning, got: {warnings}"
        )

    def test_fetch_insider_activity_warnings_param_is_optional(self, monkeypatch):
        from src.data_enrichment.insiders import fetch_insider_activity

        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        with patch("src.data_enrichment.insiders._load_cached", return_value=None):
            result = fetch_insider_activity("AAPL", finnhub_api_key=None)
        assert result is None


# ---------------------------------------------------------------------------
# earnings_signals.py — compute_earnings_signals
# ---------------------------------------------------------------------------


class TestEarningsSignalsWarnings:
    def test_compute_earnings_signals_invalid_as_of_emits_warning(self, tmp_path):
        from src.data_enrichment.earnings_signals import compute_earnings_signals
        from tests.conftest import init_test_db

        db = str(tmp_path / "earnings_test.sqlite3")
        init_test_db(db, ["earnings_calendar", "analyst_estimates"])
        warnings: list[str] = []
        result = compute_earnings_signals(
            "AAPL", db_path=db, as_of="not-a-date", warnings=warnings,
        )
        assert isinstance(result, dict)
        assert any(w.startswith("earnings_signal_invalid_as_of:") for w in warnings), (
            f"Expected earnings_signal_invalid_as_of warning, got: {warnings}"
        )

    def test_compute_earnings_signals_db_error_emits_warning(self):
        from src.data_enrichment.earnings_signals import compute_earnings_signals

        warnings: list[str] = []
        result = compute_earnings_signals(
            "AAPL",
            db_path="/path/that/definitely/does/not/exist.sqlite3",
            warnings=warnings,
        )
        assert isinstance(result, dict)
        assert any(w.startswith("earnings_signal_db_error:") for w in warnings), (
            f"Expected earnings_signal_db_error warning, got: {warnings}"
        )

    def test_compute_earnings_signals_warnings_param_is_optional(self, tmp_path):
        from src.data_enrichment.earnings_signals import compute_earnings_signals
        from tests.conftest import init_test_db

        db = str(tmp_path / "earnings_test.sqlite3")
        init_test_db(db, ["earnings_calendar", "analyst_estimates"])
        result = compute_earnings_signals("AAPL", db_path=db)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# enricher.py - enrich_features propagates warnings via warnings_out
# ---------------------------------------------------------------------------


class TestEnrichFeaturesWarningsPropagation:
    @staticmethod
    def _stub_news() -> dict:
        return {
            "headline_count": 0,
            "headlines": [],
            "summary": "stub",
            "news_sentiment": "neutral",
            "last_news_date": None,
        }

    def test_enrich_features_accepts_warnings_out_param(self):
        import inspect
        from src.data_enrichment.enricher import enrich_features

        sig = inspect.signature(enrich_features)
        assert "warnings_out" in sig.parameters
        assert sig.parameters["warnings_out"].default is None

    def test_enrich_features_collects_news_warnings(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True, "finnhub_api_key": "stub-key"}}

        def stub_news_with_warning(*args, **kwargs):
            w = kwargs.get("warnings")
            if w is not None:
                w.append("news_coverage_gap:AAPL:runtime")
            return self._stub_news()

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context", return_value={}), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None), \
             patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None), \
             patch("src.data_enrichment.news.fetch_recent_news", side_effect=stub_news_with_warning):
            warnings = []
            enrich_features(features, config, warnings_out=warnings)

        assert any("news_coverage_gap" in w for w in warnings)

    def test_enrich_features_collects_macro_warnings(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        def stub_macro_with_warning(*args, **kwargs):
            w = kwargs.get("warnings")
            if w is not None:
                w.append("macro_no_api_key:global:runtime")
            return {"fed_stance": "unknown"}

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context",
                   side_effect=stub_macro_with_warning), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None), \
             patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None), \
             patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()):
            warnings = []
            enrich_features(features, config, warnings_out=warnings)

        assert any("macro_no_api_key" in w for w in warnings)

    def test_enrich_features_collects_fundamentals_warnings(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        def stub_fund_with_warning(*args, **kwargs):
            w = kwargs.get("warnings")
            if w is not None:
                w.append("fundamentals_no_cik:AAPL:runtime")
            return None

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context", return_value={}), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot",
                   side_effect=stub_fund_with_warning), \
             patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None), \
             patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()):
            warnings = []
            enrich_features(features, config, warnings_out=warnings)

        assert any("fundamentals_no_cik" in w for w in warnings)

    def test_enrich_features_collects_insider_warnings(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        def stub_insider_with_warning(*args, **kwargs):
            w = kwargs.get("warnings")
            if w is not None:
                w.append("insiders_no_api_key:AAPL:runtime")
            return None

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context", return_value={}), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None), \
             patch("src.data_enrichment.insiders.fetch_insider_activity",
                   side_effect=stub_insider_with_warning), \
             patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()):
            warnings = []
            enrich_features(features, config, warnings_out=warnings)

        assert any("insiders_no_api_key" in w for w in warnings)

    def test_enrich_features_collects_earnings_warnings(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True}}

        def stub_earnings_with_warning(*args, **kwargs):
            w = kwargs.get("warnings")
            if w is not None:
                w.append("earnings_signal_db_error:AAPL:runtime")
            return {"include_in_prompt": False}

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context", return_value={}), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None), \
             patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None), \
             patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()), \
             patch("src.data_enrichment.earnings_signals.compute_earnings_signals",
                   side_effect=stub_earnings_with_warning):
            warnings = []
            enrich_features(features, config, warnings_out=warnings)

        assert any("earnings_signal_db_error" in w for w in warnings)

    def test_enrich_features_no_warnings_when_warnings_out_is_none(self):
        from src.data_enrichment.enricher import enrich_features

        features = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        config = {"data_enrichment": {"enabled": True, "finnhub_api_key": "stub-key"}}

        with patch("src.data_enrichment.enricher._rate_limit"), \
             patch("src.data_enrichment.macro.fetch_macro_context", return_value={}), \
             patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None), \
             patch("src.data_enrichment.insiders.fetch_insider_activity", return_value=None), \
             patch("src.data_enrichment.news.fetch_recent_news", return_value=self._stub_news()):
            result = enrich_features(features, config)
        assert "AAPL" in result


# ---------------------------------------------------------------------------
# corpus_generator.py - _packet_to_entry / _dry_run_entry / manifest
# ---------------------------------------------------------------------------


class TestCorpusGeneratorWarningsAggregation:
    def test_generate_one_entry_passes_warnings_to_corpus_entry(self, tmp_path, monkeypatch):
        from src.evaluation import corpus_generator

        def stub_enrich(features, config, **kwargs):
            warnings_out = kwargs.get("warnings_out")
            if warnings_out is not None:
                warnings_out.append("news_coverage_gap:AAPL:2024-06-15")
            return features

        monkeypatch.setattr(corpus_generator, "enrich_features", stub_enrich)

        features_for_date = {"AAPL": {"current_price": 185.0, "ticker": "AAPL"}}
        entry = corpus_generator._generate_one_entry(
            as_of="2024-06-15",
            ticker="AAPL",
            features_for_date=features_for_date,
            model_version="arcis:test",
            config={"data_enrichment": {"enabled": True}},
            dry_run=True,
        )
        assert entry is not None
        assert "news_coverage_gap:AAPL:2024-06-15" in entry.enrichment_pit_warnings

    def test_build_and_write_manifest_aggregates_warning_prefixes(self, tmp_path, monkeypatch):
        from src.evaluation import corpus_generator

        monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(tmp_path))

        call_count = {"n": 0}

        def stub_enrich(features, config, **kwargs):
            warnings_out = kwargs.get("warnings_out")
            if warnings_out is not None:
                call_count["n"] += 1
                if call_count["n"] <= 2:
                    warnings_out.append(
                        "news_coverage_gap:AAPL:2024-06-{:02d}".format(call_count["n"])
                    )
                else:
                    warnings_out.append("macro_no_api_key:global:2024-06-17")
            return features

        monkeypatch.setattr(corpus_generator, "enrich_features", stub_enrich)

        features_by_date = {
            "2024-06-15": {"AAPL": {"current_price": 100.0, "ticker": "AAPL"}},
            "2024-06-16": {"AAPL": {"current_price": 101.0, "ticker": "AAPL"}},
            "2024-06-17": {"AAPL": {"current_price": 102.0, "ticker": "AAPL"}},
        }
        decision_points = [
            ("2024-06-15", "AAPL"),
            ("2024-06-16", "AAPL"),
            ("2024-06-17", "AAPL"),
        ]

        corpus_path = corpus_generator.generate_corpus(
            corpus_id="test-warnings-aggregation",
            decision_points=decision_points,
            features_by_date=features_by_date,
            model_version="arcis:test",
            config={"data_enrichment": {"enabled": True}},
            code_sha="0" * 40,
            window_start="2024-06-15",
            window_end="2024-06-17",
            dry_run=True,
        )
        manifest_path = corpus_path / "manifest.json"
        assert manifest_path.exists()
        from src.evaluation.corpus import CorpusManifest

        manifest = CorpusManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        assert manifest.coverage_limit_hits.get("news_coverage_gap") == 2
        assert manifest.coverage_limit_hits.get("macro_no_api_key") == 1

    def test_module_docstring_no_longer_references_warnings_tracker(self):
        from src.evaluation import corpus_generator
        doc = corpus_generator.__doc__ or ""
        # The original phrase about the follow-up tracker - should be gone
        assert "stored as ``()`` because individual" not in doc, (
            "Module docstring still references the old enrichment_pit_warnings tracker"
        )
