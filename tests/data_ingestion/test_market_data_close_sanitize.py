"""Regression test for OHLCV trailing-zero-close sanitizer (root cause of #52).

Background:
yfinance batch downloads occasionally return per-ticker DataFrames where the
trailing row has Close == 0 or Close == NaN, while Open/High/Low/Volume are
populated. `df.dropna(how="all")` does NOT remove such rows. Downstream,
`engine._compute_price_features` reads `current_price = float(close.iloc[-1])`,
which propagates the zero/NaN as `current_price=0`, triggering
`template.py:177`'s #621 packet refusal.

Until 2026-05-08, that refusal then crashed `enhance_packet_with_llm` with
`'NoneType' object has no attribute 'llm_conviction_parse_failed'` because two
callers (mr_scan_service, scan_service) lacked the matching None-skip guard.
PR #1036 fixed the symptom (caller-side guard); this test locks the upstream
sanitizer fix that prevents the bad data from propagating in the first place.

Affected tickers in production logs:
- 2026-05-08: AMZN (1×), BAC (4×)
- 2026-05-07: AVGO (5×)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from src.data_ingestion.market_data import _trim_invalid_trailing_close


def _make_df(rows: list[tuple]) -> pd.DataFrame:
    """Construct a yfinance-shaped DataFrame from (Open,High,Low,Close,Volume) tuples."""
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"])


def test_trim_drops_single_trailing_zero_close():
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (100.5, 102.0, 100.0, 101.5, 1_200_000),
        (101.5, 102.0, 101.0, 0.0, 0),  # yfinance batch glitch
    ])
    out = _trim_invalid_trailing_close(df, "AMZN")
    assert len(out) == 2
    assert out["Close"].iloc[-1] == 101.5


def test_trim_drops_single_trailing_nan_close():
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (100.5, 102.0, 100.0, 101.5, 1_200_000),
        (101.5, 102.0, 101.0, np.nan, 0),
    ])
    out = _trim_invalid_trailing_close(df, "BAC")
    assert len(out) == 2
    assert out["Close"].iloc[-1] == 101.5


def test_trim_drops_multiple_trailing_invalid_rows():
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (100.5, 102.0, 100.0, 101.5, 1_200_000),
        (101.5, 102.0, 101.0, 0.0, 0),
        (101.5, 102.0, 101.0, np.nan, 0),
        (101.5, 102.0, 101.0, -0.01, 0),  # negative is also invalid
    ])
    out = _trim_invalid_trailing_close(df, "AVGO")
    assert len(out) == 2
    assert out["Close"].iloc[-1] == 101.5


def test_trim_preserves_valid_data_unchanged():
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (100.5, 102.0, 100.0, 101.5, 1_200_000),
        (101.5, 102.0, 101.0, 102.0, 1_100_000),
    ])
    out = _trim_invalid_trailing_close(df, "MSFT")
    assert len(out) == 3
    assert out.equals(df)


def test_trim_keeps_interior_zero_close_unchanged():
    """Only TRAILING zero closes are trimmed. An interior zero (e.g., a
    historical data anomaly far in the past) is left alone — we never
    re-write history, only sanitize the most recent reading."""
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (100.5, 102.0, 100.0, 0.0, 0),  # interior zero — should be preserved
        (101.5, 102.0, 101.0, 102.0, 1_100_000),
    ])
    out = _trim_invalid_trailing_close(df, "INTERIOR_TEST")
    assert len(out) == 3
    assert out["Close"].iloc[1] == 0.0  # interior zero preserved


def test_trim_returns_empty_when_all_rows_invalid():
    df = _make_df([
        (100.0, 101.0, 99.0, 0.0, 0),
        (100.5, 102.0, 100.0, np.nan, 0),
    ])
    out = _trim_invalid_trailing_close(df, "ALL_INVALID")
    assert out.empty


def test_trim_handles_empty_df():
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    out = _trim_invalid_trailing_close(df, "EMPTY")
    assert out.empty


def test_trim_handles_missing_close_column():
    """Defensive: if the DataFrame lacks a Close column entirely, return as-is
    rather than crash."""
    df = pd.DataFrame([(100.0, 1_000_000)], columns=["Open", "Volume"])
    out = _trim_invalid_trailing_close(df, "NO_CLOSE_COL")
    assert len(out) == 1


def test_trim_logs_warning_when_rows_trimmed(caplog):
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (101.5, 102.0, 101.0, 0.0, 0),
    ])
    with caplog.at_level(logging.WARNING, logger="src.data_ingestion.market_data"):
        _trim_invalid_trailing_close(df, "BAC")
    assert any(
        "BAC" in r.message and "trimmed 1 trailing" in r.message
        for r in caplog.records
    ), f"expected trim-warning log; got: {[r.message for r in caplog.records]}"


def test_trim_no_warning_when_data_clean(caplog):
    df = _make_df([
        (100.0, 101.0, 99.0, 100.5, 1_000_000),
        (101.5, 102.0, 101.0, 102.0, 1_100_000),
    ])
    with caplog.at_level(logging.WARNING, logger="src.data_ingestion.market_data"):
        _trim_invalid_trailing_close(df, "MSFT")
    assert not any("trimmed" in r.message for r in caplog.records)
