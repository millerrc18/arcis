"""Tests for the FINRA short-volume collector.

TDD — these tests are written BEFORE the implementation.
All HTTP is mocked; no network calls are made from pytest.

Tests:
1. URL template is pinned to FINRA CDN with correct date format.
2. Pipe-delimited parser correctly filters to SP100 universe.
3. short_ratio is computed as short_volume / total_volume.
4. Zero total_volume yields None short_ratio without ZeroDivisionError.
5. Double-run with same date is idempotent (no IntegrityError).
6. HTTP 404 raises CollectorConfigError after retry.
7. Schema registry has short_volume_daily table with correct PK.
8. overnight.py wires collect_finra_short_volume.
9. short_interest_collector.py carries the DEPRECATED v0.36.13 marker.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Repo root: two levels up from tests/data_collection/
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANNED_RESPONSE = (
    "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
    "20260516|AAPL|1000|50|5000|Q\n"
    "20260516|MSFT|2000|0|10000|Q\n"
    "20260516|FOO|99|0|999|Q\n"
)

CANNED_RESPONSE_WITH_ZERO_VOL = (
    "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
    "20260516|AAPL|1000|50|0|Q\n"
    "20260516|MSFT|2000|0|10000|Q\n"
)


def _init_test_db(db_path: str) -> None:
    from tests.conftest import init_test_db
    init_test_db(db_path)


def _make_mock_response(text: str, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    mock.raise_for_status = MagicMock(
        side_effect=None if status_code == 200 else Exception(f"HTTP {status_code}")
    )
    return mock


# ---------------------------------------------------------------------------
# Test 1: URL format pinned
# ---------------------------------------------------------------------------

def test_url_format_pinned():
    """The FINRA CDN URL template and date format must appear in the source."""
    source_path = _REPO_ROOT / "src" / "data_collection" / "short_volume_finra.py"
    with open(source_path) as f:
        source = f.read()
    assert "https://cdn.finra.org/equity/regsho/daily/CNMSshvol" in source
    assert "%Y%m%d" in source


# ---------------------------------------------------------------------------
# Test 2: Parser filters to SP100
# ---------------------------------------------------------------------------

def test_parser_pipe_delimited(tmp_path):
    """Pipe-delimited FINRA data is parsed and filtered to SP100 only."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    mock_resp = _make_mock_response(CANNED_RESPONSE)

    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=mock_resp), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        result = collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)

    assert result.primary_count == 2, (
        f"FOO should be filtered out; expected 2, got {result.primary_count}"
    )
    assert result.metadata["rows_inserted"] >= 2, (
        f"expected >= 2 rows inserted, got {result.metadata['rows_inserted']}"
    )
    # target_date/source were string fields on the legacy dict — now persisted
    # to short_volume_daily, not carried in the (dict[str,int]) result. Assert
    # the persisted source instead, and the collector identity.
    assert result.collector_name == "short_volume_finra"
    with sqlite3.connect(db_path) as conn:
        src = conn.execute(
            "SELECT source FROM short_volume_daily WHERE ticker = ? AND trade_date = ?",
            ("AAPL", "2026-05-16"),
        ).fetchone()
    assert src is not None and src[0] == "finra"


# ---------------------------------------------------------------------------
# Test 3: short_ratio computed correctly
# ---------------------------------------------------------------------------

def test_short_ratio_computed(tmp_path):
    """AAPL short_ratio == 1000/5000 == 0.2 after insertion."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    mock_resp = _make_mock_response(CANNED_RESPONSE)

    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=mock_resp), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT short_ratio FROM short_volume_daily WHERE ticker = ? AND trade_date = ?",
            ("AAPL", "2026-05-16"),
        ).fetchone()

    assert row is not None, "AAPL row must exist in short_volume_daily"
    assert abs(row[0] - 0.2) < 1e-9, f"expected short_ratio=0.2, got {row[0]}"


# ---------------------------------------------------------------------------
# Test 4: Zero total_volume yields None short_ratio
# ---------------------------------------------------------------------------

def test_zero_total_volume_no_division(tmp_path):
    """A row with total_volume=0 stores short_ratio=None without ZeroDivisionError."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    mock_resp = _make_mock_response(CANNED_RESPONSE_WITH_ZERO_VOL)

    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=mock_resp), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        result = collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT short_ratio FROM short_volume_daily WHERE ticker = ? AND trade_date = ?",
            ("AAPL", "2026-05-16"),
        ).fetchone()

    assert row is not None, "AAPL row must exist even when total_volume=0"
    assert row[0] is None, f"short_ratio must be None when total_volume=0, got {row[0]}"


# ---------------------------------------------------------------------------
# Test 5: Double-run idempotent
# ---------------------------------------------------------------------------

def test_db_upsert_idempotent(tmp_path):
    """Running the collector twice with the same target_date inserts no duplicate rows."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    mock_resp = _make_mock_response(CANNED_RESPONSE)

    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=mock_resp), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL", "MSFT"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)
        # Second run — must not raise IntegrityError
        collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM short_volume_daily WHERE trade_date = ?",
            ("2026-05-16",),
        ).fetchone()[0]

    assert count == 2, (
        f"idempotent run must produce exactly 2 rows (AAPL+MSFT), got {count}"
    )


# ---------------------------------------------------------------------------
# Test 6: HTTP 404 raises CollectorConfigError
# ---------------------------------------------------------------------------

def test_http_404_raises_collector_error(tmp_path):
    """A persistent HTTP 4xx raises CollectorConfigError, not a silent dict."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    from src.data_collection.errors import CollectorConfigError

    # retry_with_backoff returns None on exhaustion — simulate None return which
    # the collector must treat as a permanent HTTP failure
    with patch("src.data_collection.short_volume_finra.retry_with_backoff", return_value=None), \
         patch("src.data_collection.short_volume_finra.get_sp100_universe", return_value=["AAPL"]):
        from src.data_collection.short_volume_finra import collect_finra_short_volume
        with pytest.raises(CollectorConfigError):
            collect_finra_short_volume(target_date=date(2026, 5, 16), db_path=db_path)


# ---------------------------------------------------------------------------
# Test 7: Schema registry has the new table
# ---------------------------------------------------------------------------

def test_schema_registry_has_short_volume_daily():
    """TABLES must contain short_volume_daily with composite PK (ticker, trade_date)."""
    from src.schema.registry import TABLES

    assert "short_volume_daily" in TABLES, (
        "short_volume_daily must be registered in TABLES"
    )
    td = TABLES["short_volume_daily"]
    assert td.primary_key == ["ticker", "trade_date"], (
        f"expected primary_key=['ticker', 'trade_date'], got {td.primary_key!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: overnight.py wires the new collector
# ---------------------------------------------------------------------------

def test_overnight_wires_finra_collector():
    """overnight.py must import and call collect_finra_short_volume."""
    overnight_path = _REPO_ROOT / "src" / "scheduler" / "overnight.py"
    with open(overnight_path) as f:
        source = f.read()
    assert "collect_finra_short_volume" in source, (
        "overnight.py must import/call collect_finra_short_volume"
    )


# ---------------------------------------------------------------------------
# Test 9: short_interest_collector.py is marked deprecated
# ---------------------------------------------------------------------------

def test_short_interest_collector_deprecated():
    """short_interest_collector.py must carry the DEPRECATED v0.36.13 marker."""
    collector_path = (
        _REPO_ROOT / "src" / "data_collection" / "short_interest_collector.py"
    )
    with open(collector_path) as f:
        source = f.read()
    assert "DEPRECATED v0.36.13" in source, (
        "short_interest_collector.py must contain 'DEPRECATED v0.36.13' marker"
    )
