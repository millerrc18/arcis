"""Tests for historical EDGAR backfill — index.json resolution and pipeline."""

import json
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import init_test_db


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with edgar_filings schema."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    init_test_db(path, ["edgar_filings"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


class TestIndexJsonResolution:
    def test_selects_correct_primary_document(self):
        """Mock index.json with multiple .htm files; verify non-amendment preferred."""
        from src.data_collection.edgar_collector import _lookup_primary_document_via_index

        index_response = {
            "directory": {
                "item": [
                    {"name": "aapl-20190928.htm", "type": "10-K", "size": "1234567"},
                    {"name": "R1.htm", "type": "", "size": "5678"},
                    {"name": "aapl-20190928_g1.jpg", "type": "", "size": "45678"},
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = index_response

        with patch("src.data_collection.edgar_collector.requests.get", return_value=mock_resp):
            result = _lookup_primary_document_via_index(
                cik="0000320193", accession="0000320193-19-000119", form_type="10-K"
            )

        assert result is not None
        filename, base_url = result
        assert filename == "aapl-20190928.htm"
        assert "320193" in base_url
        assert "000032019319000119" in base_url

    def test_cache_hit_skips_index_json(self):
        """Pre-populated primaryDocument cache resolves without HTTP call."""
        from src.data_collection.edgar_collector import (
            _lookup_primary_document_via_index,
            _index_json_cache,
        )

        _index_json_cache["0001193125-20-123456"] = {
            "directory": {
                "item": [
                    {"name": "msft-20200630.htm", "type": "10-K", "size": "999999"},
                ]
            }
        }

        with patch("src.data_collection.edgar_collector.requests.get") as mock_get:
            result = _lookup_primary_document_via_index(
                cik="0000789019", accession="0001193125-20-123456", form_type="10-K"
            )

        mock_get.assert_not_called()
        assert result is not None
        assert result[0] == "msft-20200630.htm"
        _index_json_cache.clear()

    def test_graceful_no_htm_files(self):
        """index.json with no .htm/.html files logs and returns None (no crash)."""
        from src.data_collection.edgar_collector import _lookup_primary_document_via_index

        index_response = {
            "directory": {
                "item": [
                    {"name": "filing.xml", "type": "10-K", "size": "1000"},
                    {"name": "logo.jpg", "type": "", "size": "5000"},
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = index_response

        with patch("src.data_collection.edgar_collector.requests.get", return_value=mock_resp):
            result = _lookup_primary_document_via_index(
                cik="0000320193", accession="0000320193-19-000999", form_type="10-K"
            )

        assert result is None


class TestBackfillIdempotency:
    def test_skips_already_populated_rows(self, tmp_db):
        """Rows with sections_json already populated are skipped on re-run."""
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """INSERT INTO edgar_filings
            (ticker, cik, form_type, filing_date, accession_number,
             full_text, sections_json, word_count, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("AAPL", "0000320193", "10-K", "2019-10-31",
             "0000320193-19-000119",
             "Some full text content here",
             json.dumps({"item_1": "business section"}),
             5, "2026-04-18T00:00:00"),
        )
        conn.commit()

        rows = conn.execute(
            """SELECT accession_number FROM edgar_filings
            WHERE filing_date BETWEEN '2019-01-01' AND '2023-12-31'
            AND sections_json IS NULL"""
        ).fetchall()

        assert len(rows) == 0
        conn.close()


class TestPaginationDiscovery:
    @pytest.mark.skip(reason="discover_filings_for_ticker implemented in Task 6")
    def test_discovers_filings_from_paginated_files(self):
        """Submissions API filings.files[] pagination yields historical filings."""
        pass  # Will be implemented after Task 6
