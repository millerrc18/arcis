"""Parquet storage layer with Hive-style partitioning and atomic writes.

Provides read/write/delete operations for bar data stored as Parquet files
in a Hive-partitioned directory tree::

    bars/timespan=1min/ticker=AAPL/2022-06.parquet

Partition metadata (ticker, timespan, year_month) is encoded in the
directory path, NOT as columns inside the Parquet file.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .db import get_config

# ---------------------------------------------------------------------------
# Parquet schema -- columns stored INSIDE each file
# ---------------------------------------------------------------------------

BAR_SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("us")),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64()),
    ("vwap", pa.float64()),
    ("num_transactions", pa.int32()),
])


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def partition_path(
    ticker: str,
    timespan: str,
    year_month: str,
    *,
    bars_dir: Path | None = None,
) -> Path:
    """Return the full Path to a Parquet partition file.

    Parameters
    ----------
    ticker:
        Stock symbol (e.g. ``"AAPL"``).
    timespan:
        Aggregation window (e.g. ``"1min"``, ``"day"``).
    year_month:
        ``"YYYY-MM"`` string.
    bars_dir:
        Override for the bars root directory.  Defaults to
        ``get_config().bars_dir``.
    """
    root = bars_dir or get_config().bars_dir
    return root / f"timespan={timespan}" / f"ticker={ticker}" / f"{year_month}.parquet"


# ---------------------------------------------------------------------------
# Write (atomic)
# ---------------------------------------------------------------------------

def write_bars(
    ticker: str,
    timespan: str,
    year_month: str,
    bars: list[dict] | pd.DataFrame,
    *,
    bars_dir: Path | None = None,
) -> Path:
    """Write bar data to a Parquet partition file using atomic rename.

    Parameters
    ----------
    ticker, timespan, year_month:
        Partition keys (encoded in the path, NOT in columns).
    bars:
        Either a list of bar dicts or a ``pandas.DataFrame``.
    bars_dir:
        Override for the bars root directory.

    Returns
    -------
    Path
        The final partition file path.
    """
    target = partition_path(ticker, timespan, year_month, bars_dir=bars_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Normalise to DataFrame
    if isinstance(bars, list):
        df = pd.DataFrame(bars)
    else:
        df = bars.copy()

    # Ensure timestamp column is datetime
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Convert to Arrow table with our fixed schema
    table = pa.Table.from_pandas(df, schema=BAR_SCHEMA, preserve_index=False)

    # Atomic write: write to temp file, then rename
    tmp_path = target.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        pq.write_table(table, tmp_path)
        # On Windows, os.replace handles cross-device and overwrite atomically
        os.replace(str(tmp_path), str(target))
    except BaseException:
        # Clean up temp file on any failure
        tmp_path.unlink(missing_ok=True)
        raise

    return target


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_bars(
    ticker: str,
    timespan: str,
    year_month: str,
    *,
    bars_dir: Path | None = None,
) -> pd.DataFrame:
    """Read a single Parquet partition file and return a DataFrame.

    Returns an empty DataFrame (with the correct columns) if the
    partition file does not exist.
    """
    path = partition_path(ticker, timespan, year_month, bars_dir=bars_dir)
    if not path.exists():
        return pd.DataFrame(columns=[f.name for f in BAR_SCHEMA])
    table = pq.read_table(path, schema=BAR_SCHEMA)
    return table.to_pandas()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_bars(
    ticker: str,
    timespan: str,
    year_month: str,
    *,
    bars_dir: Path | None = None,
) -> bool:
    """Remove a single partition file.  Returns True if a file was deleted."""
    path = partition_path(ticker, timespan, year_month, bars_dir=bars_dir)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def list_partitions(
    ticker: str | None = None,
    timespan: str | None = None,
    *,
    bars_dir: Path | None = None,
) -> list[tuple[str, str, str]]:
    """Walk the partition tree and return matching (ticker, timespan, year_month) tuples.

    Parameters
    ----------
    ticker:
        Filter to a specific ticker.  ``None`` = all tickers.
    timespan:
        Filter to a specific timespan.  ``None`` = all timespans.
    bars_dir:
        Override for the bars root directory.

    Returns
    -------
    list[tuple[str, str, str]]
        Sorted list of ``(ticker, timespan, year_month)`` tuples.
    """
    root = bars_dir or get_config().bars_dir

    if not root.exists():
        return []

    results: list[tuple[str, str, str]] = []

    # Walk: bars / timespan=X / ticker=Y / YYYY-MM.parquet
    timespan_pattern = f"timespan={timespan}" if timespan else "timespan=*"
    ticker_pattern = f"ticker={ticker}" if ticker else "ticker=*"

    for ts_dir in sorted(root.glob(timespan_pattern)):
        ts_name = ts_dir.name.split("=", 1)[1]  # strip "timespan="
        for tk_dir in sorted(ts_dir.glob(ticker_pattern)):
            tk_name = tk_dir.name.split("=", 1)[1]  # strip "ticker="
            for pq_file in sorted(tk_dir.glob("*.parquet")):
                ym = pq_file.stem  # "2022-06"
                results.append((tk_name, ts_name, ym))

    return results


# ---------------------------------------------------------------------------
# Date-range utilities
# ---------------------------------------------------------------------------

def compute_year_months(from_date: date, to_date: date) -> list[str]:
    """Return the list of ``"YYYY-MM"`` strings covering a date range.

    Both endpoints are inclusive: the month containing ``from_date`` and
    the month containing ``to_date`` are both included.

    Examples
    --------
    >>> compute_year_months(date(2022, 1, 15), date(2022, 3, 10))
    ['2022-01', '2022-02', '2022-03']
    """
    if from_date > to_date:
        return []

    result: list[str] = []
    year, month = from_date.year, from_date.month

    while (year, month) <= (to_date.year, to_date.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1

    return result
