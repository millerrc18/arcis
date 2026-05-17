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
    """Create a temporary SQLite database with collector schemas."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db
    init_test_db(path, [
        "edgar_filings", "insider_transactions", "short_interest",
        "analyst_estimates", "fed_communications",
    ])
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
        from src.data_collection.edgar_collector import parse_sections

        text = """Item 1. Business This is the business section.
        Item 7. Management's Discussion This is the MD&A section.
        Item 8. Financial Statements These are the financials."""

        sections = parse_sections(text, "10-K")
        assert "item_1" in sections
        assert "item_7" in sections
        assert "item_8" in sections

    def test_parse_10q_sections(self):
        from src.data_collection.edgar_collector import parse_sections

        text = """Item 2. Management's Discussion This is the MD&A for Q2.
        Item 3. Quantitative and qualitative disclosures."""

        sections = parse_sections(text, "10-Q")
        assert "item_2" in sections

    def test_parse_10k_uppercase_headers(self):
        """Pre-2020 filings often use all-caps headers."""
        from src.data_collection.edgar_collector import parse_sections

        text = """ITEM 1. BUSINESS This is the business description.
        ITEM 1A. RISK FACTORS These are the risk factors.
        ITEM 1B. UNRESOLVED STAFF COMMENTS None.
        ITEM 2. PROPERTIES We own stuff."""

        sections = parse_sections(text, "10-K")
        assert "item_1a" in sections
        assert "risk factors" in sections["item_1a"].lower()

    def test_parse_10k_hyphen_separator(self):
        """Some filings use hyphen separators (observed in COST, LMT)."""
        from src.data_collection.edgar_collector import parse_sections

        text = """Item 1 - Business Our company does things.
        Item 1A - Risk Factors We face risks.
        Item 2 - Properties We have offices."""

        sections = parse_sections(text, "10-K")
        assert "item_1a" in sections

    def test_parse_10k_amendment_form_type(self):
        """10-K/A amendments should also parse sections."""
        from src.data_collection.edgar_collector import parse_sections

        text = """Item 7. Management's Discussion This is the MD&A for the amendment.
        Item 8. Financial Statements Amended financials."""

        sections = parse_sections(text, "10-K/A")
        assert "item_7" in sections
        assert len(sections["item_7"]) > 10

    def test_parse_empty_text(self):
        from src.data_collection.edgar_collector import parse_sections
        assert parse_sections("", "10-K") == {}
        assert parse_sections(None, "10-K") == {}

    def test_collect_creates_table(self, tmp_db):
        """Verify edgar_filings table exists (created by fixture from registry)."""
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
        """Verify insider_transactions table exists (created by fixture from registry)."""
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = [t[0] for t in tables]
        assert "insider_transactions" in names

    def test_collect_no_api_key(self, tmp_db):
        from src.data_collection.insider_collector import collect_insider_transactions
        from src.data_collection.errors import CollectorConfigError

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value=None):
            with pytest.raises(CollectorConfigError, match="FINNHUB_API_KEY"):
                collect_insider_transactions(["AAPL"], db_path=tmp_db)

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
        from src.data_collection.errors import CollectorPartialFailureError

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value="test-key"), \
             patch("src.data_collection.insider_collector.requests.get", side_effect=Exception("API down")), \
             patch("src.data_collection.insider_collector.time.sleep"):
            # 1/1 tickers failing = 100% > 50% threshold → raises
            with pytest.raises(CollectorPartialFailureError):
                collect_insider_transactions(["AAPL"], db_path=tmp_db)


# ── Short Interest Deduplication ────────────────────────────────────

class TestShortInterest:
    def test_collect_creates_table(self, tmp_db):
        """Verify short_interest table exists (created by fixture from registry)."""
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
        from src.data_collection.errors import CollectorConfigError

        with patch("src.data_collection.short_interest_collector._get_finnhub_key", return_value=None):
            with pytest.raises(CollectorConfigError, match="FINNHUB_API_KEY"):
                collect_short_interest(["AAPL"], db_path=tmp_db)


# ── Analyst Estimates ───────────────────────────────────────────────

class TestAnalystEstimates:
    def test_collect_creates_table(self, tmp_db):
        """Verify analyst_estimates table exists (created by fixture from registry)."""
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
             patch("src.data_collection.analyst_collector.finnhub_plan_supports", return_value=True), \
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

    def test_collect_skips_price_target_when_plan_does_not_support_it(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates

        rec_data = [{"buy": 20, "hold": 5, "sell": 1, "strongBuy": 10, "strongSell": 0}]

        # T26 (Sprint 5 Wave C7b.6): collect_analyst_estimates now has TWO
        # plan-gate checks — recommendation_trends (top-level, gates the
        # whole collection) and price_target (per-ticker, gates only the
        # price-target endpoint). To test "recommendation_trends runs but
        # price_target is skipped", differentiate the mock by feature.
        def _plan_supports(feature, *_, **__):
            return feature == "recommendation_trends"

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.analyst_collector.finnhub_plan_supports", side_effect=_plan_supports), \
             patch("src.data_collection.analyst_collector.requests.get") as mock_get, \
             patch("src.data_collection.analyst_collector.time.sleep"):
            mock_resp_rec = MagicMock()
            mock_resp_rec.json.return_value = rec_data
            mock_resp_rec.raise_for_status.return_value = None
            mock_get.return_value = mock_resp_rec

            result = collect_analyst_estimates(["AAPL"], batch_size=5, db_path=tmp_db)

        assert result["tickers_processed"] == 1
        assert result["estimates_stored"] == 1
        assert mock_get.call_count == 1

    def test_no_api_key(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates
        from src.data_collection.errors import CollectorConfigError

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value=None):
            with pytest.raises(CollectorConfigError, match="FINNHUB_API_KEY"):
                collect_analyst_estimates(["AAPL"], db_path=tmp_db)


# ── Fed Communications ──────────────────────────────────────────────

class TestFedCommunications:
    def test_collect_creates_table(self, tmp_db):
        """Verify fed_communications table exists (created by fixture from registry)."""
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

    def test_parse_href_date_old_8digit_format(self):
        from src.data_collection.fed_collector import _parse_href_date
        assert _parse_href_date("/path/fomcminutes20260128.htm") == "2026-01-28"

    def test_parse_href_date_year_mmdd_format(self):
        from src.data_collection.fed_collector import _parse_href_date
        assert _parse_href_date("/monetarypolicy/2026/0128.htm") == "2026-01-28"

    def test_parse_href_date_invalid_returns_none(self):
        from src.data_collection.fed_collector import _parse_href_date
        assert _parse_href_date("/no-date-here.htm") is None

    def test_parse_href_date_invalid_month_rejected(self):
        from src.data_collection.fed_collector import _parse_href_date
        assert _parse_href_date("/path/20269999.htm") is None

    def test_parse_href_date_does_not_match_within_long_digit_run(self):
        from src.data_collection.fed_collector import _parse_href_date
        assert _parse_href_date("/asset/123456789012.css") is None


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
        from src.data_collection.errors import CollectorConfigError

        with patch("src.data_collection.macro_collector._get_fred_api_key", return_value=None):
            with pytest.raises(CollectorConfigError, match="FRED_API_KEY"):
                collect_macro_snapshots(db_path=tmp_db)


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
        from src.data_collection.errors import CollectorPartialFailureError

        with patch("src.data_collection.insider_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.insider_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.insider_collector.time.sleep"):
            # 1/1 tickers failing = 100% error rate → raises
            with pytest.raises(CollectorPartialFailureError):
                collect_insider_transactions(["AAPL"], db_path=tmp_db)

    def test_short_interest_network_failure(self, tmp_db):
        from src.data_collection.short_interest_collector import collect_short_interest
        from src.data_collection.errors import CollectorPartialFailureError

        with patch("src.data_collection.short_interest_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.short_interest_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.short_interest_collector.time.sleep"):
            with pytest.raises(CollectorPartialFailureError):
                collect_short_interest(["AAPL"], db_path=tmp_db)

    def test_analyst_network_failure(self, tmp_db):
        from src.data_collection.analyst_collector import collect_analyst_estimates
        from src.data_collection.errors import CollectorPartialFailureError

        with patch("src.data_collection.analyst_collector._get_finnhub_key", return_value="key"), \
             patch("src.data_collection.analyst_collector.requests.get",
                   side_effect=Exception("Network down")), \
             patch("src.data_collection.analyst_collector.time.sleep"):
            with pytest.raises(CollectorPartialFailureError):
                collect_analyst_estimates(["AAPL"], batch_size=5, db_path=tmp_db)

    def test_fed_network_failure(self, tmp_db):
        from src.data_collection.fed_collector import collect_fed_communications

        with patch("src.data_collection.fed_collector.requests.get",
                   side_effect=Exception("Network down")):
            result = collect_fed_communications(db_path=tmp_db)

        assert isinstance(result, dict)


# ── Training Data Collector: pnl type safety (#195) ───────────────

class TestTrainingDataCollectorPnlTypeSafety:
    """Verify numeric fields from SQLite are cast before comparison (#195)."""

    def test_pnl_dollars_as_string_does_not_raise(self, tmp_db):
        """SQLite may return pnl_dollars as a string — must not TypeError."""
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "r1", "AAPL", "closed", "50.25", "3.2",
             "target_1_hit", "5", "60.0", "10.0",
             "2026-01-05T16:00:00", "2026-01-01", "2026-01-05"),
        )
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, ticker, enriched_prompt, created_at) "
            "VALUES (?,?,?,?)",
            ("r1", "AAPL", "Test prompt content", "2026-01-01"),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock analysis output"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert isinstance(count, int)
        assert count >= 1  # String pnl_dollars="50.25" should produce a training example

    def test_negative_string_pnl_does_not_raise(self, tmp_db):
        """Negative string pnl like '-150.50' must not crash or mis-classify."""
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t2", "r2", "PFE", "closed", "-150.50", "-8.1",
             "stop_hit", "12", "5.0", "160.0",
             "2026-01-15T16:00:00", "2026-01-03", "2026-01-15"),
        )
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, ticker, enriched_prompt, created_at) "
            "VALUES (?,?,?,?)",
            ("r2", "PFE", "Test prompt content", "2026-01-03"),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock loss analysis") as mock_gen, \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert count >= 1

    def test_none_pnl_defaults_to_zero(self, tmp_db):
        """None pnl_dollars must default to 0 without crashing."""
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t3", "r3", "MSFT", "closed", None, None,
             "timeout", None, None, None,
             "2026-02-01T16:00:00", "2026-01-20", "2026-02-01"),
        )
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, ticker, enriched_prompt, created_at) "
            "VALUES (?,?,?,?)",
            ("r3", "MSFT", "Test prompt content", "2026-01-20"),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock timeout analysis"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert isinstance(count, int)

    def test_build_outcome_text_with_string_values(self):
        """_build_outcome_text must handle all-string numeric fields."""
        from src.training.data_collector import _build_outcome_text

        trade = {
            "exit_reason": "target_1_hit",
            "pnl_dollars": "125.50",
            "pnl_pct": "4.2",
            "duration_days": "7",
            "max_favorable_excursion": "150.00",
            "max_adverse_excursion": "30.00",
        }
        result = _build_outcome_text(trade)
        assert "$125.50" in result
        assert "4.2%" in result
        assert "7 days" in result

    def test_build_outcome_text_with_none_values(self):
        """_build_outcome_text must handle None values without crashing."""
        from src.training.data_collector import _build_outcome_text

        trade = {
            "exit_reason": "timeout",
            "pnl_dollars": None,
            "pnl_pct": None,
            "duration_days": None,
            "max_favorable_excursion": None,
            "max_adverse_excursion": None,
        }
        result = _build_outcome_text(trade)
        assert "$0.00" in result
        assert "0 days" in result

    def test_closed_trade_without_recommendation_row_still_collects(self, tmp_db):
        """Closed trades should remain collectible even if recommendations row is missing.

        Fixture includes setup_type/regime_at_entry/vix_at_entry so the
        shadow_trades fallback emits a real feature snapshot rather than skipping.
        """
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at, "
            "setup_type, regime_at_entry, vix_at_entry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t_missing_rec", "r_missing", "AAPL", "closed", "50.25", "3.2",
             "target_1_hit", "5", "60.0", "10.0",
             "2026-01-05T16:00:00", "2026-01-01", "2026-01-05",
             "pullback", "neutral_chop", 18.4),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock analysis output"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert count >= 1

    def test_closed_trade_without_recommendation_id_uses_trade_fallback_key(self, tmp_db):
        """Null recommendation_id should use a stable trade-based dedupe key.

        Fixture includes setup_type/regime_at_entry/vix_at_entry so the
        shadow_trades fallback emits a real feature snapshot rather than skipping.
        """
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at, "
            "setup_type, regime_at_entry, vix_at_entry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t_null_rec_id", None, "MSFT", "closed", "22.0", "1.1",
             "target_1_hit", "3", "30.0", "9.0",
             "2026-01-10T16:00:00", "2026-01-08", "2026-01-10",
             "pullback", "low_vol_grind", 14.2),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock analysis output"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            first_count = collect_training_examples_from_closed_trades(db_path=tmp_db)
            second_count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert first_count >= 1
        assert second_count == 0, "Fallback dedupe key should prevent duplicate inserts"

    def test_closed_trade_without_recommendation_uses_shadow_trade_fallback(self, tmp_db):
        """When the recommendation row is missing, _build_feature_input_from_trade
        must emit a snapshot derived from shadow_trades columns — not the
        all-N/A degenerate snapshot that _build_feature_input(trade) would produce.
        """
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at, "
            "setup_type, setup_confidence, regime_at_entry, vix_at_entry, "
            "ranking_at_entry, realized_sector, "
            "entry_price, actual_entry_price, stop_price, target_1, target_2) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t_fallback_path", None, "NVDA", "closed", "180.0", "4.5",
             "target_1_hit", "4", "210.0", "20.0",
             "2026-02-12T16:00:00", "2026-02-08", "2026-02-12",
             "pullback", 0.78, "strong_bull", 16.5,
             3, "Information Technology",
             420.5, 422.10, 405.0, 445.0, 470.0),
        )
        conn.commit()
        conn.close()

        captured_inputs = []

        def _capture(prompt, feature_input, purpose=None):
            captured_inputs.append((purpose, feature_input))
            return "Mock analysis output"

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   side_effect=_capture), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert count >= 1
        assert captured_inputs, "generate_training_example was never called"

        # The Stage 1 snapshot must reflect shadow_trades values, not N/A defaults.
        stage1 = next((fi for purpose, fi in captured_inputs if purpose == "backfill_blinded"), None)
        assert stage1 is not None, "No Stage 1 backfill_blinded call captured"
        assert "Ticker: NVDA" in stage1
        assert "Setup: pullback" in stage1
        assert "Market Regime at Entry: strong_bull" in stage1
        assert "VIX at Entry: 16.50" in stage1
        assert "Sector: Information Technology" in stage1
        assert "Stop: $405.00" in stage1
        assert "Target 1: $445.00" in stage1
        assert "shadow_trades fallback" in stage1
        # No N/A leakage on the populated fields
        assert "Setup: n/a" not in stage1
        assert "Market Regime at Entry: n/a" not in stage1

    def test_closed_trade_with_no_feature_data_anywhere_is_skipped(self, tmp_db, caplog):
        """A trade with no recommendation row AND no shadow_trades context
        (setup_type, regime_at_entry, vix_at_entry all NULL) must be SKIPPED
        — never written as a degenerate all-N/A training example."""
        import logging
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t_no_data_anywhere", None, "GOOG", "closed", "12.0", "0.5",
             "target_1_hit", "2", "15.0", "5.0",
             "2026-03-01T16:00:00", "2026-02-27", "2026-03-01"),
        )
        conn.commit()
        conn.close()

        gen_mock = MagicMock(return_value="Should never run")

        with caplog.at_level(logging.WARNING, logger="src.training.data_collector"), \
             patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example", gen_mock), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert count == 0, "Trade with no feature data must not produce a training example"
        gen_mock.assert_not_called()  # LLM call must be skipped before generation

        # No row should have been written either.
        with sqlite3.connect(tmp_db) as conn2:
            te_count = conn2.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
        assert te_count == 0

        # Skip warning must mention the trade.
        skip_msg = " ".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
        assert "no feature data available for training" in skip_msg
        assert "GOOG" in skip_msg or "t_no_data_anywhere" in skip_msg


# ── Outcome Classification & Prompt Selection ─────────────────────

class TestOutcomeClassification:
    def test_classify_win(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 100, "exit_reason": "target_1_hit"}
        assert _classify_outcome(trade) == "WIN"

    def test_classify_loss(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": -50, "exit_reason": "stop_hit"}
        assert _classify_outcome(trade) == "LOSS"

    def test_classify_timeout(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 10, "exit_reason": "timeout"}
        assert _classify_outcome(trade) == "TIMEOUT"

    def test_classify_timeout_with_loss(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": -5, "exit_reason": "timeout"}
        assert _classify_outcome(trade) == "TIMEOUT"

    def test_classify_no_exit_reason_positive(self):
        from src.training.data_collector import _classify_outcome
        trade = {"status": "closed", "pnl_dollars": 50, "exit_reason": ""}
        assert _classify_outcome(trade) == "WIN"


class TestOutcomePromptSelection:
    def test_win_selects_winner_prompt(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import WINNER_SYSTEM_PROMPT
        assert _get_outcome_prompt("WIN") == WINNER_SYSTEM_PROMPT

    def test_loss_selects_loser_prompt(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import LOSER_SYSTEM_PROMPT
        assert _get_outcome_prompt("LOSS") == LOSER_SYSTEM_PROMPT

    def test_timeout_selects_timeout_prompt(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import TIMEOUT_SYSTEM_PROMPT
        assert _get_outcome_prompt("TIMEOUT") == TIMEOUT_SYSTEM_PROMPT

    def test_unknown_defaults_to_winner(self):
        from src.training.data_collector import _get_outcome_prompt
        from src.training.outcome_prompts import WINNER_SYSTEM_PROMPT
        assert _get_outcome_prompt("UNKNOWN") == WINNER_SYSTEM_PROMPT


# ── #615: structured CollectionResult distinguishes failure modes ──

class TestCollectionResult:
    """Verify the detailed collector exposes attempted/rejected/skipped counts
    so overnight summaries can distinguish 'no work' from '100% failed'."""

    def test_detailed_collector_returns_collection_result(self, tmp_db):
        from src.training.data_collector import (
            CollectionResult,
            collect_training_examples_from_closed_trades_detailed,
        )
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            result = collect_training_examples_from_closed_trades_detailed(db_path=tmp_db)

        assert isinstance(result, CollectionResult)
        assert result.count == 0
        assert result.attempted == 0
        assert result.rejected == 0
        assert result.skipped_no_features == 0
        assert result.halted is False
        assert result.is_silent_failure is False, "Empty DB is 'no work', not failure"

    def test_detailed_collector_distinguishes_failure_from_no_work(self, tmp_db):
        """When attempted>0 but count==0, is_silent_failure must be True.

        Pre-#615 callers couldn't tell 'ran but every LLM call returned None'
        from 'nothing to do' — both produced examples=0.
        """
        from src.training.data_collector import (
            collect_training_examples_from_closed_trades_detailed,
        )
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, recommendation_id, ticker, status, pnl_dollars, "
            "pnl_pct, exit_reason, duration_days, max_favorable_excursion, "
            "max_adverse_excursion, actual_exit_time, created_at, updated_at, "
            "setup_type, regime_at_entry, vix_at_entry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t_apifail", None, "AAPL", "closed", "50.25", "3.2",
             "target_1_hit", "5", "60.0", "10.0",
             "2026-01-05T16:00:00", "2026-01-01", "2026-01-05",
             "pullback", "neutral_chop", 18.4),
        )
        conn.commit()
        conn.close()

        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value=None), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            result = collect_training_examples_from_closed_trades_detailed(db_path=tmp_db)

        assert result.count == 0
        assert result.stage1_failures >= 1
        assert result.is_silent_failure is True, (
            "attempted>0 + count==0 must be flagged as silent failure"
        )

    def test_legacy_int_returning_function_still_works(self, tmp_db):
        """The plain int-returning entrypoint must remain backward compatible."""
        from src.training.data_collector import collect_training_examples_from_closed_trades
        from tests.conftest import init_test_db

        init_test_db(tmp_db, ["shadow_trades", "recommendations", "training_examples"])
        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        assert isinstance(count, int)
        assert count == 0


# ── #616: prompts forbid markdown structural headings ──

class TestPromptForbidsMarkdownHeadings:
    """Sonnet's default analysis style emits **Heading**: structural headers
    that the post-#334 markdown_bold validator rejects. Prompts must explicitly
    forbid this format to keep the producer + validator in sync."""

    def test_quality_enhancement_prompt_forbids_markdown_headings(self):
        from src.llm.prompts import QUALITY_ENHANCEMENT_PROMPT
        text = QUALITY_ENHANCEMENT_PROMPT.lower()
        assert "markdown" in text and ("heading" in text or "**" in text), (
            "QUALITY_ENHANCEMENT_PROMPT must explicitly forbid markdown headings"
        )

    def test_winner_prompt_forbids_markdown_headings(self):
        from src.training.outcome_prompts import WINNER_SYSTEM_PROMPT
        assert "markdown" in WINNER_SYSTEM_PROMPT.lower() or "**" in WINNER_SYSTEM_PROMPT

    def test_loser_prompt_forbids_markdown_headings(self):
        from src.training.outcome_prompts import LOSER_SYSTEM_PROMPT
        assert "markdown" in LOSER_SYSTEM_PROMPT.lower() or "**" in LOSER_SYSTEM_PROMPT

    def test_timeout_prompt_forbids_markdown_headings(self):
        from src.training.outcome_prompts import TIMEOUT_SYSTEM_PROMPT
        assert "markdown" in TIMEOUT_SYSTEM_PROMPT.lower() or "**" in TIMEOUT_SYSTEM_PROMPT

    def test_pass_prompt_forbids_markdown_headings(self):
        from src.training.outcome_prompts import PASS_SYSTEM_PROMPT
        assert "markdown" in PASS_SYSTEM_PROMPT.lower() or "**" in PASS_SYSTEM_PROMPT
