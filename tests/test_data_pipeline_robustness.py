"""Tests for Sprint 8 Task 4: data pipeline robustness fixes.

Covers: retention pruning (#123), NaN price rejection (#125),
accession number normalization (#126), rate limiter enforcement (#133).
"""

import math
import os
import sqlite3
import tempfile
import time

import pytest


# ── Helpers ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with required schemas."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db
    init_test_db(path, ["edgar_filings", "scan_metrics"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


# ── #123: Retention prunes old rows ─────────────────────────────────

class TestRetention:
    def test_prunes_old_rows(self, tmp_db):
        """Retention deletes rows older than the configured threshold."""
        from src.data_collection.retention import run_retention, RETENTION_RULES

        from tests.conftest import init_test_db as _init_db
        _init_db(tmp_db, ["activity_log"])
        with sqlite3.connect(tmp_db) as conn:
            # Insert old row (60 days ago — exceeds 30-day rule)
            conn.execute(
                "INSERT INTO activity_log (event_type, created_at, detail) VALUES (?, ?, ?)",
                ("test", "2020-01-01T00:00:00", "old"),
            )
            # Insert recent row
            conn.execute(
                "INSERT INTO activity_log (event_type, created_at, detail) VALUES (?, ?, ?)",
                ("test", "2099-01-01T00:00:00", "recent"),
            )

        result = run_retention(db_path=tmp_db)
        assert result.get("activity_log", 0) == 1

        with sqlite3.connect(tmp_db) as conn:
            remaining = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        assert remaining == 1

    def test_skips_missing_tables(self, tmp_db):
        """Retention does not crash when a table does not exist."""
        from src.data_collection.retention import run_retention

        result = run_retention(db_path=tmp_db)
        assert isinstance(result, dict)

    def test_never_prunes_protected_tables(self, tmp_db):
        """Tables like shadow_trades are never listed in RETENTION_RULES."""
        from src.data_collection.retention import RETENTION_RULES

        protected = ["shadow_trades", "training_examples", "recommendations",
                      "council_sessions"]
        for table in protected:
            assert table not in RETENTION_RULES


# ── #125: NaN price rejected ────────────────────────────────────────

class TestNaNPriceRejection:
    def test_nan_underlying_price_skipped(self, tmp_db):
        """Options collector skips tickers with NaN underlying price."""
        from unittest.mock import patch, MagicMock
        import pandas as pd

        # Mock yfinance to return NaN close price
        mock_ticker = MagicMock()
        mock_ticker.options = ["2025-06-20"]
        hist_df = pd.DataFrame({"Close": [float("nan")]})
        mock_ticker.history.return_value = hist_df

        with patch("src.data_collection.options_collector.yf") as mock_yf, \
             patch("src.data_collection.options_collector.to_yfinance_ticker", return_value="TEST"):
            mock_yf.Ticker.return_value = mock_ticker
            from src.data_collection.options_collector import collect_options_chains
            result = collect_options_chains(["TEST"], db_path=tmp_db)

        # Ticker should be skipped, not collected. Non-vacuity (DD-15 r3):
        # primary_count==0 + errors==0 asserts the NaN guard early-continued
        # (a SUCCESSFUL count-0 'ok' run, not a 'failed' run); would fail if the
        # collector stopped skipping NaN underlying prices.
        assert result.primary_count == 0
        assert result.metadata["errors"] == 0

    def test_zero_underlying_price_skipped(self, tmp_db):
        """Options collector skips tickers with zero underlying price."""
        from unittest.mock import patch, MagicMock
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker.options = ["2025-06-20"]
        hist_df = pd.DataFrame({"Close": [0.0]})
        mock_ticker.history.return_value = hist_df

        with patch("src.data_collection.options_collector.yf") as mock_yf, \
             patch("src.data_collection.options_collector.to_yfinance_ticker", return_value="TEST"):
            mock_yf.Ticker.return_value = mock_ticker
            from src.data_collection.options_collector import collect_options_chains
            result = collect_options_chains(["TEST"], db_path=tmp_db)

        assert result.primary_count == 0


# ── #126: Accession number normalized ────────────────────────────────

class TestAccessionNormalization:
    def test_dashes_added_to_flat_accession(self):
        """Flat 18-digit accession gets normalized to dashed format."""
        from src.data_collection.edgar_collector import _normalize_accession

        assert _normalize_accession("000119312521123456") == "0001193125-21-123456"

    def test_already_dashed_preserved(self):
        """Already-dashed accession is returned unchanged."""
        from src.data_collection.edgar_collector import _normalize_accession

        assert _normalize_accession("0001193125-21-123456") == "0001193125-21-123456"

    def test_unusual_length_preserved(self):
        """Non-standard accession is returned as-is."""
        from src.data_collection.edgar_collector import _normalize_accession

        assert _normalize_accession("short") == "short"


# ── #128: CBOE regex returns None on failure ─────────────────────────

class TestCboeRegexFallback:
    def test_parse_returns_none_on_no_match(self):
        """_parse_cboe_page returns None when no ratios match."""
        from src.data_collection.cboe_collector import _parse_cboe_page

        result = _parse_cboe_page("<html><body>No data here</body></html>")
        assert result is None

    def test_parse_returns_dict_on_match(self):
        """_parse_cboe_page returns dict when at least one ratio matches."""
        from src.data_collection.cboe_collector import _parse_cboe_page

        html = '<div>equity put/call ratio 0.85</div>'
        result = _parse_cboe_page(html)
        assert result is not None
        assert result["equity_pc_ratio"] == 0.85

    def test_collect_returns_collector_result_with_stored_row(self):
        """PR-D T22 (Shape A): collect_cboe_ratios returns a CollectorResult.

        Non-vacuity: with all three tiers' ratios populated, a successful run
        stores exactly one cboe_ratios row, so primary_count == 1 and the
        narrowed metadata ratios_present == 3 (three non-NULL ratio fields). If
        the INSERT path broke, the DB-row count assertion would fail; if the
        ratio-presence narrowing broke, ratios_present would not be 3.
        """
        from unittest.mock import patch

        from src.data_collection.cboe_collector import collect_cboe_ratios
        from src.data_collection.result import CollectorResult

        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        from tests.conftest import init_test_db
        init_test_db(path, ["cboe_ratios"])
        try:
            with patch(
                "src.data_collection.cboe_collector._fetch_cboe_pc_ratio",
                return_value={
                    "equity_pc_ratio": 0.85,
                    "index_pc_ratio": 1.20,
                    "total_pc_ratio": 0.95,
                },
            ):
                result = collect_cboe_ratios(db_path=path)

            assert isinstance(result, CollectorResult)
            assert result.is_healthy
            assert result.primary_count == 1
            assert result.metadata["ratios_present"] == 3

            with sqlite3.connect(path) as conn:
                stored = conn.execute(
                    "SELECT COUNT(*) FROM cboe_ratios"
                ).fetchone()[0]
            assert stored == 1
        finally:
            try:
                os.unlink(path)
            except PermissionError:
                pass

    def test_collect_raises_when_all_tiers_fail(self):
        """DD-14 preserved: when every fallback tier returns NULL ratios,
        collect_cboe_ratios RAISES CollectorPartialFailureError (it must NOT
        return a CollectorResult or insert an all-NULL row)."""
        from unittest.mock import patch

        from src.data_collection.cboe_collector import collect_cboe_ratios
        from src.data_collection.errors import CollectorPartialFailureError

        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        from tests.conftest import init_test_db
        init_test_db(path, ["cboe_ratios"])
        try:
            with patch(
                "src.data_collection.cboe_collector._fetch_cboe_pc_ratio",
                return_value={
                    "equity_pc_ratio": None,
                    "index_pc_ratio": None,
                    "total_pc_ratio": None,
                },
            ):
                with pytest.raises(CollectorPartialFailureError):
                    collect_cboe_ratios(db_path=path)

            with sqlite3.connect(path) as conn:
                stored = conn.execute(
                    "SELECT COUNT(*) FROM cboe_ratios"
                ).fetchone()[0]
            assert stored == 0
        finally:
            try:
                os.unlink(path)
            except PermissionError:
                pass


# ── #129: Short interest uses cursor.rowcount ────────────────────────

class TestShortInterestRowCount:
    def test_no_total_changes_reference(self):
        """Verify conn.total_changes is no longer used."""
        import inspect
        from src.data_collection.short_interest_collector import collect_short_interest

        source = inspect.getsource(collect_short_interest)
        assert "total_changes" not in source
        assert "rowcount" in source


# ── #133: Rate limiter enforces interval ─────────────────────────────

class TestRateLimiter:
    def test_rate_limiter_enforces_interval(self):
        """Rate limiter sleeps to enforce minimum interval."""
        from src.data_enrichment.enricher import _rate_limit, _last_request_time

        # Clear state
        _last_request_time.clear()

        # First call should not sleep
        t0 = time.time()
        _rate_limit("test_api", min_interval=0.2)
        t1 = time.time()
        assert t1 - t0 < 0.15  # Should be near-instant

        # Second call should sleep ~0.2s
        _rate_limit("test_api", min_interval=0.2)
        t2 = time.time()
        assert t2 - t1 >= 0.15  # Should have slept

    def test_rate_limiter_uses_defaults(self):
        """Rate limiter uses default intervals from _RATE_LIMITS."""
        from src.data_enrichment.enricher import _RATE_LIMITS

        assert _RATE_LIMITS["finnhub"] == 1.0
        assert _RATE_LIMITS["sec"] == 0.1


# ── #127: EDGAR NLP column check ─────────────────────────────────────

class TestEdgarNlpColumns:
    def test_ensure_nlp_columns_adds_missing(self, tmp_db):
        """_ensure_nlp_columns adds sentiment columns if they're absent."""
        from src.data_collection.edgar_collector import _ensure_nlp_columns

        with sqlite3.connect(tmp_db) as conn:
            result = _ensure_nlp_columns(conn)
        assert result is True

        # Verify columns exist now
        with sqlite3.connect(tmp_db) as conn:
            cols = {c[1] for c in conn.execute("PRAGMA table_info(edgar_filings)").fetchall()}
        assert "sentiment_polarity" in cols
        assert "cautionary_phrases" in cols


# ── kin #23 / DD-15 r3: dual-mode collect-pipeline failure detection ──
#
# The manual collect-data pipelines (CLI cmd_collect_data + dashboard route
# _run_collect_data) tally failed_collectors. Pre-PR-D the test was
# `isinstance(result, dict) and "error" in result`; a CollectorResult.failed()
# is NOT a dict, so a migrated collector that genuinely failed would be counted
# as a success — the same silent-reversal class as the #623 overnight guard.
# Both consumers now route through _collector_result_is_failed (dual-mode).

class TestCollectPipelineDualModeFailureDetection:
    """VERIFY-BY-MUTATION (feedback_vacuous_test_pattern): drop the
    ``isinstance(result, CollectorResult)`` branch from either helper and the
    failed-CollectorResult assertions flip to False (a failed collector stops
    being counted) — proving these tests exercise the dual-mode branch, not
    just the legacy dict path."""

    def test_cli_helper_flags_failed_collectorresult(self):
        from src.cli.commands_data import _collector_result_is_failed
        from src.data_collection.result import CollectorResult
        assert _collector_result_is_failed(
            CollectorResult.failed("macro", errors=["FRED 500"])
        ) is True

    def test_cli_helper_passes_healthy_collectorresult(self):
        from src.cli.commands_data import _collector_result_is_failed
        from src.data_collection.result import CollectorResult
        assert _collector_result_is_failed(
            CollectorResult.ok_from_count("macro", 31)
        ) is False
        assert _collector_result_is_failed(
            CollectorResult.partial("trends", 18, errors=["429"])
        ) is False

    def test_cli_helper_legacy_dict_path(self):
        from src.cli.commands_data import _collector_result_is_failed
        assert _collector_result_is_failed({"error": "boom"}) is True
        assert _collector_result_is_failed({"series_collected": 31}) is False
        assert _collector_result_is_failed("skipped (not settlement date)") is False

    def test_route_helper_flags_failed_collectorresult(self):
        from src.api.routes.actions import _collector_result_is_failed
        from src.data_collection.result import CollectorResult
        assert _collector_result_is_failed(
            CollectorResult.failed("macro", errors=["FRED 500"])
        ) is True

    def test_route_helper_passes_healthy_collectorresult(self):
        from src.api.routes.actions import _collector_result_is_failed
        from src.data_collection.result import CollectorResult
        assert _collector_result_is_failed(
            CollectorResult.ok_from_count("macro", 31)
        ) is False

    def test_route_helper_legacy_dict_path(self):
        from src.api.routes.actions import _collector_result_is_failed
        assert _collector_result_is_failed({"error": "boom"}) is True
        assert _collector_result_is_failed({"status": "skipped"}) is False
