"""Cache manager and batch engine for MarketPulse bar data.

Coordinates between the Polygon.io client, Hive-partitioned Parquet
storage, and the SQLite coverage table to provide a write-through
cache with resumable multi-ticker batch pulls.

Classes
-------
- ``CoverageReport`` -- what months are cached vs. missing for a query.
- ``CacheManager``   -- check/fetch/query cached bar data.
- ``BatchEngine``    -- orchestrate multi-ticker pulls with job tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .client import Bar, PolygonClient
from .db import MarketPulseConfig, bars_glob, get_duckdb
from .models import Coverage, FetchJob
from .storage import compute_year_months, write_bars

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timespan mapping: user-facing key -> (Polygon API timespan, multiplier)
# ---------------------------------------------------------------------------

TIMESPAN_MAP: dict[str, tuple[str, int]] = {
    "1min": ("minute", 1),
    "5min": ("minute", 5),
    "15min": ("minute", 15),
    "1hour": ("hour", 1),
    "1day": ("day", 1),
}


# ---------------------------------------------------------------------------
# CoverageReport
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    """Result of a coverage check for a ticker/timespan/date range."""

    ticker: str
    timespan: str
    from_date: date
    to_date: date
    cached: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def fully_cached(self) -> bool:
        """True when every required month is already in the cache."""
        return len(self.missing) == 0


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------

class CacheManager:
    """Coordinates Polygon fetching, Parquet storage, and SQLite coverage.

    Parameters
    ----------
    config:
        MarketPulse configuration (data_dir, bars_dir, etc.).
    client:
        A ``PolygonClient`` instance (caller manages its lifecycle).
    session_factory:
        Async SQLAlchemy session factory for the metadata DB.
    """

    def __init__(
        self,
        config: MarketPulseConfig,
        client: PolygonClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.config = config
        self.client = client
        self.session_factory = session_factory

    # -- coverage check ------------------------------------------------------

    async def check_coverage(
        self,
        ticker: str,
        timespan: str,
        from_date: date,
        to_date: date,
    ) -> CoverageReport:
        """Determine which year-months are cached and which are missing.

        Parameters
        ----------
        ticker:
            Stock symbol.
        timespan:
            User-facing timespan key (e.g. ``"1min"``, ``"1day"``).
        from_date, to_date:
            Inclusive date range.

        Returns
        -------
        CoverageReport
        """
        needed = compute_year_months(from_date, to_date)

        async with self.session_factory() as session:
            stmt = (
                select(Coverage.year_month)
                .where(Coverage.ticker == ticker)
                .where(Coverage.timespan == timespan)
                .where(Coverage.year_month.in_(needed))
            )
            result = await session.execute(stmt)
            cached_set = {row[0] for row in result.fetchall()}

        cached = [ym for ym in needed if ym in cached_set]
        missing = [ym for ym in needed if ym not in cached_set]

        return CoverageReport(
            ticker=ticker,
            timespan=timespan,
            from_date=from_date,
            to_date=to_date,
            cached=cached,
            missing=missing,
        )

    # -- fetch and cache -----------------------------------------------------

    async def fetch_and_cache(
        self,
        ticker: str,
        timespan: str,
        multiplier: int,
        from_date: date,
        to_date: date,
    ) -> int:
        """Fetch missing months from Polygon and write to the Parquet cache.

        Already-cached months are skipped.  For each missing month the
        method fetches bars from the API, writes a Parquet partition file,
        and records a row in the ``coverage`` table.

        Parameters
        ----------
        ticker:
            Stock symbol.
        timespan:
            User-facing timespan key (e.g. ``"1min"``).
        multiplier:
            Multiplier for the Polygon API timespan.
        from_date, to_date:
            Inclusive date range.

        Returns
        -------
        int
            Total number of new bars cached across all missing months.
        """
        report = await self.check_coverage(ticker, timespan, from_date, to_date)

        if report.fully_cached:
            return 0

        # Resolve the Polygon API timespan from the user-facing key
        api_timespan, api_multiplier = TIMESPAN_MAP.get(
            timespan, (timespan, multiplier)
        )

        total_new_bars = 0

        for ym in report.missing:
            year, month = int(ym[:4]), int(ym[5:7])

            # Compute chunk boundaries clipped to the request range
            chunk_start = date(year, month, 1)
            if chunk_start < from_date:
                chunk_start = from_date

            if month == 12:
                next_first = date(year + 1, 1, 1)
            else:
                next_first = date(year, month + 1, 1)
            chunk_end = next_first - timedelta(days=1)
            if chunk_end > to_date:
                chunk_end = to_date

            # Fetch from Polygon
            bars: list[Bar] = await self.client.get_bars(
                ticker, api_timespan, api_multiplier, chunk_start, chunk_end,
            )

            # Convert Bar dataclasses to dicts for storage
            bar_dicts = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "vwap": b.vwap,
                    "num_transactions": b.num_transactions,
                }
                for b in bars
            ]

            # Write Parquet (even if empty -- the file records the fetch)
            if bar_dicts:
                write_bars(
                    ticker,
                    timespan,
                    ym,
                    bar_dicts,
                    bars_dir=self.config.bars_dir,
                )

            # Record coverage
            async with self.session_factory() as session:
                session.add(
                    Coverage(
                        ticker=ticker,
                        timespan=timespan,
                        year_month=ym,
                        bar_count=len(bars),
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

            total_new_bars += len(bars)

        return total_new_bars

    # -- query cached bars via DuckDB ----------------------------------------

    async def get_bars_df(
        self,
        tickers: list[str],
        timespan: str,
        from_date: date,
        to_date: date,
        columns: list[str] | None = None,
        max_rows: int = 10_000,
    ) -> pd.DataFrame:
        """Query cached Parquet bar data via DuckDB.

        Parameters
        ----------
        tickers:
            List of stock symbols.
        timespan:
            User-facing timespan key (e.g. ``"1min"``).
        from_date, to_date:
            Inclusive date range.
        columns:
            Optional list of columns to select.  ``None`` = all columns.
        max_rows:
            Maximum rows to return.  Emits a warning if the result is
            truncated.  Default 10,000.

        Returns
        -------
        pandas.DataFrame
        """
        # Build glob paths for each ticker
        glob_paths = [
            bars_glob(ticker=t, timespan=timespan) for t in tickers
        ]

        col_expr = ", ".join(columns) if columns else "*"

        # Build a UNION of read_parquet() calls
        union_parts = [
            f"SELECT {col_expr} FROM read_parquet('{p}', hive_partitioning=true)"
            for p in glob_paths
        ]
        base_query = " UNION ALL ".join(union_parts)

        # Filter by date range and apply row limit
        query = (
            f"SELECT * FROM ({base_query}) AS bars "
            f"WHERE timestamp >= '{from_date.isoformat()}' "
            f"AND timestamp <= '{to_date.isoformat()} 23:59:59' "
            f"ORDER BY timestamp "
            f"LIMIT {max_rows + 1}"
        )

        con = get_duckdb()
        try:
            df = con.execute(query).fetchdf()
        finally:
            con.close()

        if len(df) > max_rows:
            logger.warning(
                "Result truncated to %d rows (limit=%d). "
                "Narrow your date range or ticker list.",
                max_rows,
                max_rows,
            )
            df = df.head(max_rows)

        return df

    # -- cache status --------------------------------------------------------

    async def get_cache_status(
        self,
        ticker: str | None = None,
    ) -> dict:
        """Return information about what's currently cached.

        Parameters
        ----------
        ticker:
            If given, return detail for that ticker.  Otherwise return
            a summary across all tickers.

        Returns
        -------
        dict
            Keys depend on whether ``ticker`` is specified:

            **Per-ticker** -- ``ticker``, ``timespan_coverage`` (dict of
            timespan -> list of year_months), ``total_bars``.

            **Summary** -- ``total_tickers``, ``total_bars``,
            ``total_partitions``.
        """
        async with self.session_factory() as session:
            if ticker is not None:
                stmt = (
                    select(Coverage)
                    .where(Coverage.ticker == ticker)
                    .order_by(Coverage.timespan, Coverage.year_month)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                timespan_coverage: dict[str, list[str]] = {}
                total_bars = 0
                for row in rows:
                    timespan_coverage.setdefault(row.timespan, []).append(
                        row.year_month
                    )
                    total_bars += row.bar_count

                return {
                    "ticker": ticker,
                    "timespan_coverage": timespan_coverage,
                    "total_bars": total_bars,
                }
            else:
                # Summary across all tickers
                ticker_count_stmt = select(
                    func.count(func.distinct(Coverage.ticker))
                )
                bar_sum_stmt = select(func.coalesce(func.sum(Coverage.bar_count), 0))
                partition_count_stmt = select(func.count(Coverage.ticker))

                ticker_count = (
                    await session.execute(ticker_count_stmt)
                ).scalar() or 0
                bar_sum = (
                    await session.execute(bar_sum_stmt)
                ).scalar() or 0
                partition_count = (
                    await session.execute(partition_count_stmt)
                ).scalar() or 0

                return {
                    "total_tickers": ticker_count,
                    "total_bars": bar_sum,
                    "total_partitions": partition_count,
                }


# ---------------------------------------------------------------------------
# BatchEngine
# ---------------------------------------------------------------------------

class BatchEngine:
    """Orchestrates multi-ticker pulls with job tracking and resumability.

    Parameters
    ----------
    cache_manager:
        A ``CacheManager`` for the actual fetch-and-cache work.
    session_factory:
        Async SQLAlchemy session factory for job tracking rows.
    """

    def __init__(
        self,
        cache_manager: CacheManager,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.cache_manager = cache_manager
        self.session_factory = session_factory

    # -- pull ----------------------------------------------------------------

    async def pull(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "1min",
        job_id: str | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> FetchJob:
        """Fetch bars for a list of tickers with job tracking.

        Parameters
        ----------
        tickers:
            Symbols to fetch.
        from_date, to_date:
            Inclusive date range.
        timespan:
            User-facing timespan key.
        job_id:
            If resuming, the existing job ID to continue.
        on_progress:
            Optional callback ``(current_ticker, completed, total)``.

        Returns
        -------
        FetchJob
            The job row with final status and stats.
        """
        _, api_multiplier = TIMESPAN_MAP.get(timespan, (timespan, 1))
        total = len(tickers)

        async with self.session_factory() as session:
            if job_id is not None:
                result = await session.execute(
                    select(FetchJob).where(FetchJob.id == job_id)
                )
                job = result.scalar_one()
            else:
                job_id = uuid.uuid4().hex[:12]
                job = FetchJob(
                    id=job_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    tickers=json.dumps(tickers),
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                    timespan=timespan,
                    status="pending",
                    total_tickers=total,
                    completed_tickers=0,
                    current_ticker=None,
                    error=None,
                )
                session.add(job)
                await session.commit()

            # Transition to running
            job.status = "running"
            await session.commit()

        completed = 0
        try:
            for ticker in tickers:
                async with self.session_factory() as session:
                    result = await session.execute(
                        select(FetchJob).where(FetchJob.id == job_id)
                    )
                    job = result.scalar_one()
                    job.current_ticker = ticker
                    await session.commit()

                await self.cache_manager.fetch_and_cache(
                    ticker, timespan, api_multiplier, from_date, to_date,
                )

                completed += 1

                async with self.session_factory() as session:
                    result = await session.execute(
                        select(FetchJob).where(FetchJob.id == job_id)
                    )
                    job = result.scalar_one()
                    job.completed_tickers = completed
                    await session.commit()

                if on_progress is not None:
                    on_progress(ticker, completed, total)

            # Mark completed
            async with self.session_factory() as session:
                result = await session.execute(
                    select(FetchJob).where(FetchJob.id == job_id)
                )
                job = result.scalar_one()
                job.status = "completed"
                job.current_ticker = None
                await session.commit()

        except (KeyboardInterrupt, asyncio.CancelledError):
            async with self.session_factory() as session:
                result = await session.execute(
                    select(FetchJob).where(FetchJob.id == job_id)
                )
                job = result.scalar_one()
                job.status = "paused"
                await session.commit()

        except Exception as exc:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(FetchJob).where(FetchJob.id == job_id)
                )
                job = result.scalar_one()
                job.status = "failed"
                job.error = str(exc)
                await session.commit()

        # Return the final job state
        async with self.session_factory() as session:
            result = await session.execute(
                select(FetchJob).where(FetchJob.id == job_id)
            )
            job = result.scalar_one()

        return job

    # -- resume --------------------------------------------------------------

    async def resume(
        self,
        job_id: str,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> FetchJob:
        """Resume a paused or failed job from where it left off.

        Parameters
        ----------
        job_id:
            The job to resume.
        on_progress:
            Optional progress callback.

        Returns
        -------
        FetchJob
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(FetchJob).where(FetchJob.id == job_id)
            )
            job = result.scalar_one()

        all_tickers = json.loads(job.tickers)
        remaining = all_tickers[job.completed_tickers:]

        return await self.pull(
            tickers=remaining,
            from_date=date.fromisoformat(job.from_date),
            to_date=date.fromisoformat(job.to_date),
            timespan=job.timespan,
            job_id=job_id,
            on_progress=on_progress,
        )

    # -- list jobs -----------------------------------------------------------

    async def list_jobs(self) -> list[FetchJob]:
        """Return all FetchJob rows ordered by created_at descending.

        Returns
        -------
        list[FetchJob]
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(FetchJob).order_by(FetchJob.created_at.desc())
            )
            return list(result.scalars().all())
