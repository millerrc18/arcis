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
    def test_discovers_filings_from_paginated_files(self):
        """Submissions API filings.files[] pagination yields historical filings."""
        # Simulate the main submissions response with a files[] reference
        main_response = {
            "cik": "320193",
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "filingDate": ["2024-11-01"],
                    "accessionNumber": ["0000320193-24-000123"],
                    "primaryDocDescription": ["10-K"],
                    "primaryDocument": ["aapl-20240928.htm"],
                },
                "files": [
                    {"name": "CIK0000320193-submissions-001.json"}
                ],
            },
        }

        # Simulate the paginated file with older filings
        paginated_response = {
            "form": ["10-K", "10-Q", "8-K"],
            "filingDate": ["2019-10-31", "2019-07-31", "2019-08-01"],
            "accessionNumber": [
                "0000320193-19-000119",
                "0000320193-19-000076",
                "0000320193-19-000080",
            ],
            "primaryDocDescription": ["10-K", "10-Q", "8-K"],
            "primaryDocument": [
                "aapl-20190928.htm",
                "aapl-20190629.htm",
                "some-8k.htm",
            ],
        }

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "submissions-001" in url:
                resp.json.return_value = paginated_response
            else:
                resp.json.return_value = main_response
            resp.raise_for_status.return_value = None
            return resp

        with patch("scripts.backfill_edgar_historical.requests.get", side_effect=mock_get):
            from scripts.backfill_edgar_historical import discover_filings_for_ticker

            filings, doc_cache = discover_filings_for_ticker(
                cik="0000320193",
                ticker="AAPL",
                form_types=["10-K", "10-Q"],
                start_date="2019-01-01",
                end_date="2023-12-31",
            )

        # Should find the 10-K and 10-Q from 2019 (8-K filtered out)
        assert len(filings) == 2
        forms = {f["form_type"] for f in filings}
        assert forms == {"10-K", "10-Q"}

        # primaryDocument should be cached from paginated response
        assert "0000320193-19-000119" in doc_cache
        assert doc_cache["0000320193-19-000119"] == "aapl-20190928.htm"
