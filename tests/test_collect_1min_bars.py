"""Tests for scripts/collect_1min_bars.py (1-minute OHLCV collector).

Covers:
- schema registration (minute_bars table with composite PK)
- collector idempotency (INSERT OR REPLACE on composite PK)
- yfinance MultiIndex flattening (same defect pattern as SD#41 D2)
- NaN handling for price/volume fields
- empty-response handling (weekends, holidays, delisted tickers)
- rate limiting between tickers
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts.collect_1min_bars import (
    _fetch_minute_bars,
    _previous_trading_day,
    _upsert_bars,
    collect,
)
from src.schema.registry import TABLES
from tests.conftest import init_test_db

ET = ZoneInfo("America/New_York")


# ── Schema registration ─────────────────────────────────────────────────


def test_minute_bars_schema_registered():
    """Table, composite PK, OHLCV columns, and sync flag must all be wired."""
    assert "minute_bars" in TABLES, "minute_bars not registered in TABLES"
    td = TABLES["minute_bars"]
    col_names = {c.name for c in td.columns}
    assert {"ticker", "timestamp", "open", "high", "low", "close",
            "volume", "trade_count"} <= col_names
    assert td.primary_key == ["ticker", "timestamp"], (
        "Composite PK required so same ticker can have many timestamps "
        "without collision."
    )
    assert td.sync_to_postgres is True
    assert td.sync_mode == "incremental"
    assert td.sync_time_column == "timestamp"


# ── Fixtures ────────────────────────────────────────────────────────────


def _minute_frame_multiindex(ticker: str = "AAPL", n: int = 3):
    """Return a yfinance-shaped DataFrame (MultiIndex columns)."""
    idx = pd.date_range("2026-04-14 09:30", periods=n, freq="1min", tz="US/Eastern")
    df = pd.DataFrame(
        {
            "Open":   [100.0 + i * 0.1 for i in range(n)],
            "High":   [100.5 + i * 0.1 for i in range(n)],
            "Low":    [99.5 + i * 0.1 for i in range(n)],
            "Close":  [100.2 + i * 0.1 for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


def _init_minute_bars_schema(db_path: str) -> sqlite3.Connection:
    """Create the minute_bars table via the canonical registry → SQL path."""
    init_test_db(db_path, tables=["minute_bars"])
    return sqlite3.connect(db_path)


# ── Fetch shape + flattening ────────────────────────────────────────────


def test_fetch_minute_bars_flattens_multiindex():
    """yfinance returns tuple-keyed columns for single-ticker downloads.

    The collector must flatten to string columns before building dicts,
    otherwise `row["Open"]` misses and everything becomes None. Same
    defect pattern as SD#41 D2 attribution resolver.
    """
    target = datetime(2026, 4, 14, tzinfo=ET)
    with patch("yfinance.download", return_value=_minute_frame_multiindex("AAPL", 3)):
        bars = _fetch_minute_bars("AAPL", target)
    assert len(bars) == 3
    # Every bar has numeric OHLC values — not None
    for b in bars:
        assert b["open"] is not None
        assert b["high"] is not None
        assert b["low"] is not None
        assert b["close"] is not None
        assert b["volume"] is not None
        assert b["ticker"] == "AAPL"


def test_fetch_minute_bars_handles_nan_values():
    """yfinance intermittently returns NaN for volume on low-liquidity bars.

    `int(NaN)` raises ValueError; the helper must map NaN -> None instead.
    """
    target = datetime(2026, 4, 14, tzinfo=ET)
    df = _minute_frame_multiindex("AAPL", 3)
    # Introduce NaN volume on middle bar
    df.iloc[1, df.columns.get_loc(("Volume", "AAPL"))] = float("nan")
    with patch("yfinance.download", return_value=df):
        bars = _fetch_minute_bars("AAPL", target)
    assert bars[1]["volume"] is None, "NaN must coerce to None, not crash"
    assert bars[0]["volume"] is not None
    assert bars[2]["volume"] is not None


def test_fetch_minute_bars_returns_empty_on_empty_response():
    """Weekends/holidays/delisted -> empty DataFrame -> empty list, no crash."""
    target = datetime(2026, 4, 14, tzinfo=ET)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        bars = _fetch_minute_bars("DELISTED", target)
    assert bars == []


# ── Upsert idempotency ──────────────────────────────────────────────────


def test_upsert_bars_is_idempotent(tmp_path):
    """Running twice with the same bars leaves the row count unchanged.

    Composite PK (ticker, timestamp) + INSERT OR REPLACE => overwrite, not
    duplicate. This is the core guarantee for daily re-collection safety.
    """
    db = str(tmp_path / "minute.db")
    conn = _init_minute_bars_schema(db)
    bars = [
        {"ticker": "AAPL", "timestamp": "2026-04-14T09:30:00-04:00",
         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
         "volume": 1000, "trade_count": None},
        {"ticker": "AAPL", "timestamp": "2026-04-14T09:31:00-04:00",
         "open": 100.5, "high": 101.5, "low": 99.5, "close": 101.0,
         "volume": 1200, "trade_count": None},
    ]
    _upsert_bars(conn, bars)
    _upsert_bars(conn, bars)  # second pass must not duplicate
    conn.commit()
    (n,) = conn.execute("SELECT COUNT(*) FROM minute_bars").fetchone()
    conn.close()
    assert n == 2, f"Expected 2 rows after idempotent re-insert, got {n}"


# ── End-to-end collect() ────────────────────────────────────────────────


def test_collect_dry_run_does_not_write(tmp_path, monkeypatch):
    """`--dry-run` path must fetch but skip DB writes (for pre-flight checks)."""
    db = str(tmp_path / "dry.db")
    _init_minute_bars_schema(db).close()

    monkeypatch.setattr("scripts.collect_1min_bars.DB_PATH", db)
    # Keep the universe tiny so the test runs fast
    monkeypatch.setattr(
        "scripts.collect_1min_bars.get_sp100_universe", lambda: ["AAPL", "MSFT"]
    )

    with patch("yfinance.download",
               return_value=_minute_frame_multiindex("AAPL", 3)):
        result = collect(
            target_dates=[datetime(2026, 4, 14, tzinfo=ET)],
            dry_run=True,
            rate_limit_seconds=0,
        )

    conn = sqlite3.connect(db)
    (n,) = conn.execute("SELECT COUNT(*) FROM minute_bars").fetchone()
    conn.close()
    assert n == 0, "dry_run must skip writes"
    assert result["bars_collected"] == 0
    assert result["tickers"] == 2


def test_collect_rate_limits_between_tickers(tmp_path, monkeypatch):
    """Rate limiter must fire once per ticker-day to stay under yfinance caps."""
    db = str(tmp_path / "rate.db")
    _init_minute_bars_schema(db).close()

    monkeypatch.setattr("scripts.collect_1min_bars.DB_PATH", db)
    monkeypatch.setattr(
        "scripts.collect_1min_bars.get_sp100_universe",
        lambda: ["AAPL", "MSFT", "GOOGL"],
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("scripts.collect_1min_bars.time.sleep",
                        lambda s: sleep_calls.append(s))

    with patch("yfinance.download",
               return_value=_minute_frame_multiindex("AAPL", 2)):
        collect(
            target_dates=[datetime(2026, 4, 14, tzinfo=ET)],
            dry_run=True,
            rate_limit_seconds=0.3,
        )

    # 3 tickers * 1 day = 3 sleep calls
    assert len(sleep_calls) == 3
    assert all(s == 0.3 for s in sleep_calls)


# ── Previous-trading-day walker ─────────────────────────────────────────


def test_previous_trading_day_skips_weekends():
    """Sunday/Monday lookups must roll back to Friday."""
    monday = datetime(2026, 4, 13, tzinfo=ET)  # Monday
    assert _previous_trading_day(monday).weekday() == 4  # Friday

    sunday = datetime(2026, 4, 12, tzinfo=ET)
    assert _previous_trading_day(sunday).weekday() == 4

    tuesday = datetime(2026, 4, 14, tzinfo=ET)
    assert _previous_trading_day(tuesday).weekday() == 0  # Monday
