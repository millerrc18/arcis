"""Tests for marketpulse lib.storage -- Parquet read/write/delete/listing.

All storage functions are synchronous, so no async wrappers needed.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# ---------------------------------------------------------------------------
# Make ``lib.storage`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.db import MarketPulseConfig, reset_config  # noqa: E402
from lib.storage import (  # noqa: E402
    BAR_SCHEMA,
    compute_year_months,
    delete_bars,
    list_partitions,
    partition_path,
    read_bars,
    write_bars,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_config(tmp_path: Path):
    """Reset the global config singleton and point at a temp dir."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    yield
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)


def _sample_bars() -> list[dict]:
    """Return a small list of bar dicts for testing."""
    return [
        {
            "timestamp": datetime(2022, 6, 1, 9, 30, 0),
            "open": 150.0,
            "high": 151.5,
            "low": 149.0,
            "close": 150.5,
            "volume": 1000.0,
            "vwap": 150.25,
            "num_transactions": 42,
        },
        {
            "timestamp": datetime(2022, 6, 1, 9, 31, 0),
            "open": 150.5,
            "high": 152.0,
            "low": 150.0,
            "close": 151.0,
            "volume": 1500.0,
            "vwap": 151.0,
            "num_transactions": 55,
        },
    ]


# ---------------------------------------------------------------------------
# partition_path
# ---------------------------------------------------------------------------

class TestPartitionPath:
    def test_default_bars_dir(self, tmp_path: Path):
        p = partition_path("AAPL", "1min", "2022-06")
        assert str(p).endswith("2022-06.parquet")
        assert "timespan=1min" in str(p)
        assert "ticker=AAPL" in str(p)

    def test_custom_bars_dir(self, tmp_path: Path):
        custom = tmp_path / "custom_bars"
        p = partition_path("MSFT", "day", "2023-01", bars_dir=custom)
        expected = custom / "timespan=day" / "ticker=MSFT" / "2023-01.parquet"
        assert p == expected


# ---------------------------------------------------------------------------
# write_bars + read_bars roundtrip
# ---------------------------------------------------------------------------

class TestWriteReadBars:
    def test_roundtrip_from_dicts(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        bars = _sample_bars()

        path = write_bars("AAPL", "1min", "2022-06", bars, bars_dir=bars_dir)

        # File exists at the right location
        assert path.exists()
        assert "timespan=1min" in str(path)
        assert "ticker=AAPL" in str(path)
        assert path.name == "2022-06.parquet"

        # Read back
        df = read_bars("AAPL", "1min", "2022-06", bars_dir=bars_dir)
        assert len(df) == 2
        assert list(df.columns) == [f.name for f in BAR_SCHEMA]
        assert df["open"].iloc[0] == 150.0
        assert df["close"].iloc[1] == 151.0
        assert df["num_transactions"].iloc[0] == 42

    def test_roundtrip_from_dataframe(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        df_in = pd.DataFrame(_sample_bars())

        write_bars("TSLA", "day", "2023-03", df_in, bars_dir=bars_dir)
        df_out = read_bars("TSLA", "day", "2023-03", bars_dir=bars_dir)

        assert len(df_out) == 2
        pd.testing.assert_series_equal(
            df_out["volume"].reset_index(drop=True),
            df_in["volume"].reset_index(drop=True),
            check_names=False,
        )

    def test_overwrite_existing(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        bars1 = _sample_bars()
        bars2 = [bars1[0]]  # only one row

        write_bars("AAPL", "1min", "2022-06", bars1, bars_dir=bars_dir)
        write_bars("AAPL", "1min", "2022-06", bars2, bars_dir=bars_dir)

        df = read_bars("AAPL", "1min", "2022-06", bars_dir=bars_dir)
        assert len(df) == 1

    def test_read_nonexistent_returns_empty(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        df = read_bars("NOPE", "1min", "2099-01", bars_dir=bars_dir)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == [f.name for f in BAR_SCHEMA]

    def test_schema_columns_not_partition_keys(self, tmp_path: Path):
        """Partition keys (ticker, timespan, year_month) must NOT appear as columns."""
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)

        df = read_bars("AAPL", "1min", "2022-06", bars_dir=bars_dir)
        assert "ticker" not in df.columns
        assert "timespan" not in df.columns
        assert "year_month" not in df.columns


# ---------------------------------------------------------------------------
# Atomic write safety
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_no_partial_file_on_failure(self, tmp_path: Path):
        """If writing fails, no .parquet file should remain."""
        bars_dir = tmp_path / "bars"

        with patch("lib.storage.pq.write_table", side_effect=IOError("disk full")):
            with pytest.raises(IOError, match="disk full"):
                write_bars("FAIL", "1min", "2022-01", _sample_bars(), bars_dir=bars_dir)

        target = partition_path("FAIL", "1min", "2022-01", bars_dir=bars_dir)
        assert not target.exists()
        # Also verify no .tmp files are left behind
        if target.parent.exists():
            tmp_files = list(target.parent.glob("*.tmp"))
            assert len(tmp_files) == 0

    def test_temp_file_cleaned_up_on_success(self, tmp_path: Path):
        """After a successful write, only the final .parquet should exist."""
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)

        pq_dir = partition_path("AAPL", "1min", "2022-06", bars_dir=bars_dir).parent
        assert len(list(pq_dir.glob("*.tmp"))) == 0
        assert len(list(pq_dir.glob("*.parquet"))) == 1


# ---------------------------------------------------------------------------
# delete_bars
# ---------------------------------------------------------------------------

class TestDeleteBars:
    def test_delete_existing(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)

        assert delete_bars("AAPL", "1min", "2022-06", bars_dir=bars_dir) is True
        assert not partition_path("AAPL", "1min", "2022-06", bars_dir=bars_dir).exists()

    def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        assert delete_bars("NOPE", "1min", "2099-01", bars_dir=bars_dir) is False


# ---------------------------------------------------------------------------
# list_partitions
# ---------------------------------------------------------------------------

class TestListPartitions:
    def test_list_all(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("AAPL", "1min", "2022-07", _sample_bars(), bars_dir=bars_dir)
        write_bars("MSFT", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("AAPL", "day", "2022-06", _sample_bars(), bars_dir=bars_dir)

        result = list_partitions(bars_dir=bars_dir)
        assert len(result) == 4
        # All are (ticker, timespan, year_month)
        assert ("AAPL", "1min", "2022-06") in result
        assert ("AAPL", "1min", "2022-07") in result
        assert ("MSFT", "1min", "2022-06") in result
        assert ("AAPL", "day", "2022-06") in result

    def test_filter_by_ticker(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("MSFT", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)

        result = list_partitions(ticker="AAPL", bars_dir=bars_dir)
        assert len(result) == 1
        assert result[0] == ("AAPL", "1min", "2022-06")

    def test_filter_by_timespan(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("AAPL", "day", "2022-06", _sample_bars(), bars_dir=bars_dir)

        result = list_partitions(timespan="day", bars_dir=bars_dir)
        assert len(result) == 1
        assert result[0] == ("AAPL", "day", "2022-06")

    def test_filter_both(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        write_bars("AAPL", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("AAPL", "day", "2022-06", _sample_bars(), bars_dir=bars_dir)
        write_bars("MSFT", "1min", "2022-06", _sample_bars(), bars_dir=bars_dir)

        result = list_partitions(ticker="AAPL", timespan="1min", bars_dir=bars_dir)
        assert len(result) == 1
        assert result[0] == ("AAPL", "1min", "2022-06")

    def test_empty_tree(self, tmp_path: Path):
        bars_dir = tmp_path / "bars"
        result = list_partitions(bars_dir=bars_dir)
        assert result == []


# ---------------------------------------------------------------------------
# compute_year_months
# ---------------------------------------------------------------------------

class TestComputeYearMonths:
    def test_same_month(self):
        result = compute_year_months(date(2022, 6, 1), date(2022, 6, 30))
        assert result == ["2022-06"]

    def test_single_day(self):
        result = compute_year_months(date(2022, 6, 15), date(2022, 6, 15))
        assert result == ["2022-06"]

    def test_multi_month(self):
        result = compute_year_months(date(2022, 1, 15), date(2022, 3, 10))
        assert result == ["2022-01", "2022-02", "2022-03"]

    def test_cross_year(self):
        result = compute_year_months(date(2021, 11, 1), date(2022, 2, 28))
        assert result == ["2021-11", "2021-12", "2022-01", "2022-02"]

    def test_full_year(self):
        result = compute_year_months(date(2022, 1, 1), date(2022, 12, 31))
        assert len(result) == 12
        assert result[0] == "2022-01"
        assert result[-1] == "2022-12"

    def test_reversed_dates_returns_empty(self):
        result = compute_year_months(date(2022, 6, 1), date(2022, 1, 1))
        assert result == []

    def test_multi_year(self):
        result = compute_year_months(date(2020, 12, 1), date(2022, 1, 31))
        assert result == [
            "2020-12",
            "2021-01", "2021-02", "2021-03", "2021-04",
            "2021-05", "2021-06", "2021-07", "2021-08",
            "2021-09", "2021-10", "2021-11", "2021-12",
            "2022-01",
        ]
