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

        # Ticker should be skipped, not collected
        assert result["tickers_collected"] == 0
        assert result["errors"] == 0

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

        assert result["tickers_collected"] == 0


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
