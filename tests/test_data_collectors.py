"""Tests for new data collectors: EDGAR, insider, short interest, analyst, Fed, trends."""

import json
import sqlite3
import tempfile
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


# ── EDGAR CIK Lookup ────────────────────────────────────────────────

class TestEdgarCikLookup:
    def test_cik_cache_populated_from_sec(self, tmp_db):
        from src.data_collection.edgar_collector import _load_cik_lookup, _cik_cache
        _cik_cache.clear()

        mock_data = {
            "0": {"cik_str": 320193, "ticker": "AAPL"},
            "1": {"cik_str": 1018724, "ticker": "AMZN"},
        }
        with patch("src.data_collection.edgar_collector.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            result = _load_cik_lookup()

        assert "AAPL" in result
        assert result["AAPL"] == "0000320193"
        assert "AMZN" in result
        _cik_cache.clear()

    def test_get_cik_handles_missing_ticker(self):
        from src.data_collection.edgar_collector import _get_cik, _cik_cache
        _cik_cache.clear()

        with patch("src.data_collection.edgar_collector._load_cik_lookup", return_value={}):
            assert _get_cik("FAKE") is None
        _cik_cache.clear()


# ── EDGAR Filing Parser ─────────────────────────────────────────────

class TestEdgarFilingParser:
    def test_parse_10k_sections(self):
        from src.data_collection.edgar_collector import _parse_sections

        text = """Item 1. Business This is the business section.
        Item 7. Management's Discussion This is the MD&A section.
        Item 8. Financial Statements These are the financials."""

        sections = _parse_sections(text, "10-K")
        assert "item_1" in sections
        assert "item_7" in sections
        assert "item_8" in sections

    def test_parse_10q_sections(self):
        from src.data_collection.edgar_collector import _parse_sections

        text = """Item 2. Management's Discussion This is the MD&A for Q2.
        Item 3. Quantitative and qualitative disclosures."""

        sections = _parse_sections(text, "10-Q")
        assert "item_2" in sections

    def test_parse_empty_text(self):
        from src.data_collection.edgar_collector import _parse_sections
        assert _parse_sections("", "10-K") == {}
        assert _parse_sections(None, "10-K") == {}

    def test_collect_creates_table(self, tmp_db):
        from src.data_collection.edgar_collector import _init_table
        _init_table(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "edgar_filings" in names

    def test_collect_handles_no_cik(self, tmp_db):
        from src.data_collection.edgar_collector import collect_new_filings, _cik_cache
        _cik_cache.clear()

        with patch("src.data_collection.edgar_collector._load_cik_lookup", return_value={}):
            result = collect_new_filings(["FAKE"], db_path=tmp_db)

        assert result["tickers_processed"] == 0
        assert result["filings_stored"] == 0
        _cik_cache.clear()


# ── Insider Transaction Normalization ───────────────────────────────

class TestInsiderTransactions:
    def test_collect_creates_table(self, tmp_db):
        from src.data_collection.insider_collector import _init_table
        _init_table(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "insider_transactions" in names

    def test_collect_no_api_key(self, tmp_db):
        from src.data_collection.insider_collector import collect_insider_transactions

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value=None):
            result = collect_insider_transactions(["AAPL"], db_path=tmp_db)

        assert result["tickers_processed"] == 0
        assert "error" in result

    def test_collect_stores_transactions(self, tmp_db):
        from src.data_collection.insider_collector import collect_insider_transactions

        mock_data = {
            "data": [
                {
                    "name": "Tim Cook",
                    "position": "CEO",
                    "transactionCode": "S",
                    "transactionDate": "2026-03-20",
                    "filingDate": "2026-03-22",
                    "change": -50000,
                    "transactionPrice": 180.0,
                    "share": 1000000,
                },
            ],
        }
        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value="test-key"), \
             patch("src.data_collection.insider_collector.requests.get") as mock_get, \
             patch("src.data_collection.insider_collector.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            result = collect_insider_transactions(["AAPL"], db_path=tmp_db)

        assert result["tickers_processed"] == 1
        assert result["transactions_stored"] == 1

        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT * FROM insider_transactions").fetchone()
        assert row is not None

    def test_collect_handles_api_failure(self, tmp_db):
        from src.data_collection.insider_collector import collect_insider_transactions

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value="test-key"), \
             patch("src.data_collection.insider_collector.requests.get", side_effect=Exception("API down")), \
             patch("src.data_collection.insider_collector.time.sleep"):
            result = collect_insider_transactions(["AAPL"], db_path=tmp_db)

        # Should not crash — graceful failure
        assert result["tickers_processed"] == 0


# ── Short Interest Deduplication ────────────────────────────────────

class TestShortInterest:
    def test_collect_creates_table(self, tmp_db):
        from src.data_collection.short_interest_collector import _init_table
        _init_table(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "short_interest" in names

    def test_deduplication_by_settlement_date(self, tmp_db):
        from src.data_collection.short_interest_collector import collect_short_interest

        mock_data = {
            "data": [
                {"settlementDate": "2026-03-15", "shortInterest": 5000000,
                 "avgDailyShareTradeVolume": 1000000, "shortInterestPercentFloat": 2.5},
            ],
        }
        with patch("src.data_collection.short_interest_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.short_interest_collector.requests.get") as mock_get, \
             patch("src.data_collection.short_interest_collector.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            # First collection
            collect_short_interest(["AAPL"], db_path=tmp_db)
            # Second collection (should be deduplicated)
            collect_short_interest(["AAPL"], db_path=tmp_db)

        with sqlite3.connect(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]
        assert count == 1  # Deduplication via UNIQUE constraint

    def test_no_api_key(self, tmp_db):
        from src.data_collection.short_interest_collector import collect_short_interest

        with patch("src.data_collection.short_interest_collector._get_finnhub_key", return_value=None):
            result = collect_short_interest(["AAPL"], db_path=tmp_db)

        assert "error" in result


# ── Analyst Estimates ───────────────────────────────────────────────

class TestAnalystEstimates:
    def test_collect_creates_table(self, tmp_db):
        from src.data_collection.analyst_collector import _init_table
        _init_table(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "analyst_estimates" in names

    def test_collect_stores_estimates(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates

        rec_data = [{"buy": 20, "hold": 5, "sell": 1, "strongBuy": 10, "strongSell": 0}]
        pt_data = {"targetHigh": 250.0, "targetLow": 150.0, "targetMean": 200.0,
                   "targetMedian": 195.0, "lastUpdated": "2026-03-20"}

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.analyst_collector.requests.get") as mock_get, \
             patch("src.data_collection.analyst_collector.time.sleep"):
            mock_resp_rec = MagicMock()
            mock_resp_rec.json.return_value = rec_data
            mock_resp_rec.raise_for_status.return_value = None

            mock_resp_pt = MagicMock()
            mock_resp_pt.json.return_value = pt_data
            mock_resp_pt.raise_for_status.return_value = None

            mock_get.side_effect = [mock_resp_rec, mock_resp_pt]

            result = collect_analyst_estimates(["AAPL"], batch_size=5, db_path=tmp_db)

        assert result["tickers_processed"] == 1
        assert result["estimates_stored"] == 1

    def test_no_api_key(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value=None):
            result = collect_analyst_estimates(["AAPL"], db_path=tmp_db)

        assert "error" in result


# ── Fed Communications ──────────────────────────────────────────────

class TestFedCommunications:
    def test_collect_creates_table(self, tmp_db):
        from src.data_collection.fed_collector import _init_table
        _init_table(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "fed_communications" in names

    def test_collect_handles_fetch_failure(self, tmp_db):
        from src.data_collection.fed_collector import collect_fed_communications

        with patch("src.data_collection.fed_collector._fetch_page", return_value=None):
            result = collect_fed_communications(db_path=tmp_db)

        # Should not crash — graceful failure
        assert isinstance(result, dict)
        assert "statements" in result
        assert "minutes" in result
        assert "beige_book" in result
        assert "speeches" in result


# ── FRED Expanded Series ────────────────────────────────────────────

class TestFredExpanded:
    def test_fred_series_count(self):
        from src.data_collection.macro_collector import FRED_SERIES
        # Original 19 + 14 new = 33 total (ICSA already existed in original)
        assert len(FRED_SERIES) >= 33

    def test_new_series_present(self):
        from src.data_collection.macro_collector import FRED_SERIES
        new_series = [
            "HOUST", "PERMIT", "CSUSHPISA",
            "CCSA", "JTSJOL",
            "BOPGSTB", "IPMAN", "DGORDER",
            "UMCSENT", "PCE", "RSAFS",
            "WALCL", "RRPONTSYD", "M2SL",
        ]
        for series_id in new_series:
            assert series_id in FRED_SERIES, f"Missing: {series_id}"

    def test_collect_no_api_key(self, tmp_db):
        from src.data_collection.macro_collector import collect_macro_snapshots

        with patch("src.data_collection.macro_collector._get_fred_api_key", return_value=None):
            result = collect_macro_snapshots(db_path=tmp_db)

        assert result["series_collected"] == 0
        assert "error" in result


# ── Google Trends Market-Wide Mode ──────────────────────────────────

class TestGoogleTrendsMarketWide:
    def test_sentiment_terms_defined(self):
        from src.data_collection.trends_collector import MARKET_SENTIMENT_TERMS
        assert len(MARKET_SENTIMENT_TERMS) == 8
        assert "stock market crash" in MARKET_SENTIMENT_TERMS
        assert "recession" in MARKET_SENTIMENT_TERMS

    def test_collect_pytrends_not_installed(self, tmp_db):
        from src.data_collection.trends_collector import collect_google_trends

        with patch.dict("sys.modules", {"pytrends": None, "pytrends.request": None}):
            # Force reimport to pick up the missing module
            import importlib
            import src.data_collection.trends_collector as tc
            importlib.reload(tc)
            result = tc.collect_google_trends(tickers=["AAPL"], db_path=tmp_db)

        assert result["terms_collected"] == 0

    def test_accepts_tickers_param_for_backwards_compat(self, tmp_db):
        """The function signature still accepts tickers but ignores them."""
        from src.data_collection.trends_collector import collect_google_trends

        # Mock the pytrends import inside the function to simulate not installed
        with patch.dict("sys.modules", {"pytrends": None, "pytrends.request": None}):
            import importlib
            import src.data_collection.trends_collector as tc
            importlib.reload(tc)
            # Should not crash when tickers is passed
            result = tc.collect_google_trends(tickers=["AAPL", "MSFT"], db_path=tmp_db)
        assert "terms_collected" in result or "error" in result


# ── Collector Failure Handling (Graceful) ───────────────────────────

class TestCollectorFailureHandling:
    """Verify that each collector fails gracefully and never crashes the pipeline."""

    def test_edgar_network_failure(self, tmp_db):
        from src.data_collection.edgar_collector import collect_new_filings, _cik_cache
        _cik_cache.clear()

        with patch("src.data_collection.edgar_collector._load_cik_lookup",
                   side_effect=Exception("Network down")):
            result = collect_new_filings(["AAPL"], db_path=tmp_db)

        assert isinstance(result, dict)
        _cik_cache.clear()

    def test_insider_network_failure(self, tmp_db):
        from src.data_collection.insider_collector import collect_insider_transactions

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.insider_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.insider_collector.time.sleep"):
            result = collect_insider_transactions(["AAPL"], db_path=tmp_db)

        assert isinstance(result, dict)

    def test_short_interest_network_failure(self, tmp_db):
        from src.data_collection.short_interest_collector import collect_short_interest

        with patch("src.data_collection.short_interest_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.short_interest_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.short_interest_collector.time.sleep"):
            result = collect_short_interest(["AAPL"], db_path=tmp_db)

        assert isinstance(result, dict)

    def test_analyst_network_failure(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.analyst_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.analyst_collector.time.sleep"):
            result = collect_analyst_estimates(["AAPL"], batch_size=5, db_path=tmp_db)

        assert isinstance(result, dict)

    def test_fed_network_failure(self, tmp_db):
        from src.data_collection.fed_collector import collect_fed_communications

        with patch("src.data_collection.fed_collector.requests.get",
                   side_effect=Exception("Network down")):
            result = collect_fed_communications(db_path=tmp_db)

        assert isinstance(result, dict)


# ── Render Sync Tables Config ───────────────────────────────────────

class TestRenderSyncNewTables:
    def test_new_tables_in_sync_config(self):
        from src.sync.render_sync import SYNC_TABLES
        new_tables = [
            "insider_transactions",
            "short_interest",
            "analyst_estimates",
            "fed_communications",
            "edgar_filings",
        ]
        for table in new_tables:
            assert table in SYNC_TABLES, f"Missing from SYNC_TABLES: {table}"
            assert SYNC_TABLES[table]["mode"] == "incremental"
            assert SYNC_TABLES[table]["time_col"] == "collected_at"
            assert SYNC_TABLES[table]["pk"] == "id"
