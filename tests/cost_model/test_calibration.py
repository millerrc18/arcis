"""Tests for cost_model.calibration.

Uses in-memory SQLite fixtures — no prod DB access.
"""

import json
import sqlite3
import statistics
from pathlib import Path

import pytest

from src.cost_model.calibration import calibrate, get_calibrated_cost_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS shadow_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL,
    entry_price REAL,
    actual_entry_price REAL,
    actual_exit_price REAL,
    planned_shares REAL,
    actual_shares REAL,
    signal_entry_price REAL,
    signal_exit_price REAL,
    fill_entry_price REAL,
    fill_exit_price REAL
)
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _insert_closed(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, status,
                entry_price, actual_entry_price, actual_exit_price,
                planned_shares, actual_shares,
                signal_entry_price, signal_exit_price,
                fill_entry_price, fill_exit_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["trade_id"],
                row["ticker"],
                row.get("status", "closed"),
                row.get("entry_price"),
                row.get("actual_entry_price"),
                row.get("actual_exit_price"),
                row.get("planned_shares"),
                row.get("actual_shares"),
                row.get("signal_entry_price"),
                row.get("signal_exit_price"),
                row.get("fill_entry_price"),
                row.get("fill_exit_price"),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ten_closed_trades_conn():
    """10 closed trades with deterministic slippage values."""
    conn = _make_conn()
    # Each trade: signal_entry=100, fill_entry=100+i*0.01 → entry slip varies
    # signal_exit=110, fill_exit=110-i*0.01 → exit slip varies
    # actual_shares=100 for all
    rows = []
    for i in range(10):
        entry_signal = 100.0
        entry_fill = 100.0 + (i + 1) * 0.01  # 100.01 … 100.10
        exit_signal = 110.0
        exit_fill = 110.0 - (i + 1) * 0.01   # 109.99 … 109.90
        rows.append(
            {
                "trade_id": f"T{i:03d}",
                "ticker": "AAPL" if i < 5 else "MSFT",
                "status": "closed",
                "entry_price": entry_signal,
                "actual_entry_price": entry_fill,
                "actual_exit_price": exit_fill,
                "planned_shares": 100.0,
                "actual_shares": 100.0,
                "signal_entry_price": entry_signal,
                "signal_exit_price": exit_signal,
                "fill_entry_price": entry_fill,
                "fill_exit_price": exit_fill,
            }
        )
    _insert_closed(conn, rows)
    return conn


@pytest.fixture()
def mixed_status_conn():
    """5 closed + 5 open trades — only closed should be used."""
    conn = _make_conn()
    rows = []
    for i in range(5):
        rows.append(
            {
                "trade_id": f"C{i:03d}",
                "ticker": "TSLA",
                "status": "closed",
                "entry_price": 200.0,
                "actual_entry_price": 200.10,
                "actual_exit_price": 210.0,
                "planned_shares": 50.0,
                "actual_shares": 50.0,
                "signal_entry_price": 200.0,
                "signal_exit_price": 210.0,
                "fill_entry_price": 200.10,
                "fill_exit_price": 209.90,
            }
        )
    for i in range(5):
        rows.append(
            {
                "trade_id": f"O{i:03d}",
                "ticker": "NVDA",
                "status": "open",
                "entry_price": 300.0,
                "actual_entry_price": 300.05,
                "actual_exit_price": None,
                "planned_shares": 30.0,
                "actual_shares": 30.0,
                "signal_entry_price": 300.0,
                "signal_exit_price": None,
                "fill_entry_price": 300.05,
                "fill_exit_price": None,
            }
        )
    _insert_closed(conn, rows)
    return conn


@pytest.fixture()
def empty_conn():
    return _make_conn()


# ---------------------------------------------------------------------------
# Tests — calibrate()
# ---------------------------------------------------------------------------

class TestCalibrateWithTenTrades:
    def test_returns_dict(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        assert isinstance(result, dict)

    def test_count_is_ten(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        assert result["total_count"] == 10

    def test_median_entry_slippage_bps(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        # entry slippage bps = (fill - signal) / signal * 10000
        # fills: 100.01..100.10, signal=100.0
        # slips: 1,2,3,4,5,6,7,8,9,10 bps
        expected_median = statistics.median([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        assert abs(result["median_entry_slippage_bps"] - expected_median) < 0.5

    def test_p95_entry_slippage_bps(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        # p95 of [1..10] ≈ 9.55 (sorted[9] = 10, percentile computation)
        assert result["p95_entry_slippage_bps"] >= 9.0

    def test_median_exit_slippage_bps(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        # exit slippage = (signal - fill) / signal * 10000 (positive = adverse for sells)
        # fills: 109.99..109.90, signal=110.0
        # slips: 0.91..9.09 bps ≈ 1..9
        assert "median_exit_slippage_bps" in result
        assert result["median_exit_slippage_bps"] >= 0

    def test_count_by_ticker(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        assert result["count_by_ticker"]["AAPL"] == 5
        assert result["count_by_ticker"]["MSFT"] == 5

    def test_last_calibrated_at_present(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        assert "last_calibrated_at" in result
        assert result["last_calibrated_at"]  # non-empty

    def test_json_written(self, ten_closed_trades_conn, tmp_path):
        out = tmp_path / "cal.json"
        calibrate(ten_closed_trades_conn, output_path=str(out))
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded["total_count"] == 10

    def test_round_trip_cost_bps_present(self, ten_closed_trades_conn, tmp_path):
        result = calibrate(ten_closed_trades_conn, output_path=str(tmp_path / "cal.json"))
        assert "median_round_trip_cost_bps" in result
        assert result["median_round_trip_cost_bps"] >= 0


class TestCalibrateEmpty:
    def test_empty_returns_dict(self, empty_conn, tmp_path):
        result = calibrate(empty_conn, output_path=str(tmp_path / "cal.json"))
        assert isinstance(result, dict)

    def test_empty_total_count_zero(self, empty_conn, tmp_path):
        result = calibrate(empty_conn, output_path=str(tmp_path / "cal.json"))
        assert result["total_count"] == 0

    def test_empty_json_written(self, empty_conn, tmp_path):
        out = tmp_path / "cal.json"
        calibrate(empty_conn, output_path=str(out))
        assert out.exists()

    def test_empty_slippage_fields_none(self, empty_conn, tmp_path):
        result = calibrate(empty_conn, output_path=str(tmp_path / "cal.json"))
        assert result["median_entry_slippage_bps"] is None
        assert result["p95_entry_slippage_bps"] is None


class TestCalibrateOnlyClosedUsed:
    def test_count_excludes_open(self, mixed_status_conn, tmp_path):
        result = calibrate(mixed_status_conn, output_path=str(tmp_path / "cal.json"))
        assert result["total_count"] == 5

    def test_count_by_ticker_excludes_open(self, mixed_status_conn, tmp_path):
        result = calibrate(mixed_status_conn, output_path=str(tmp_path / "cal.json"))
        assert "NVDA" not in result["count_by_ticker"]
        assert result["count_by_ticker"].get("TSLA") == 5


# ---------------------------------------------------------------------------
# Tests — get_calibrated_cost_model()
# ---------------------------------------------------------------------------

class TestGetCalibratedCostModel:
    def test_reads_back_written_json(self, ten_closed_trades_conn, tmp_path):
        out = tmp_path / "cal.json"
        calibrate(ten_closed_trades_conn, output_path=str(out))
        model = get_calibrated_cost_model(calibration_path=str(out))
        assert model["total_count"] == 10

    def test_missing_file_returns_none(self, tmp_path):
        model = get_calibrated_cost_model(calibration_path=str(tmp_path / "nonexistent.json"))
        assert model is None

    def test_count_by_ticker_preserved(self, ten_closed_trades_conn, tmp_path):
        out = tmp_path / "cal.json"
        calibrate(ten_closed_trades_conn, output_path=str(out))
        model = get_calibrated_cost_model(calibration_path=str(out))
        assert model["count_by_ticker"]["AAPL"] == 5
