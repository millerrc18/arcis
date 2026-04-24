"""Tests for marketpulse lib.cache -- CacheManager and BatchEngine.

Uses asyncio.run() for async tests.  PolygonClient is fully mocked so
no network calls are made.  A temporary directory is used for both
Parquet storage and the SQLite metadata database.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Make ``lib`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.cache import BatchEngine, CacheManager, CoverageReport, TIMESPAN_MAP  # noqa: E402
from lib.client import Bar, PolygonClient  # noqa: E402
from lib.db import (  # noqa: E402
    Base,
    MarketPulseConfig,
    get_engine,
    get_session_factory,
    init_db,
    reset_config,
)
from lib.models import Coverage, FetchJob  # noqa: E402
from lib.storage import partition_path, read_bars  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_bars(n: int = 3, month: int = 6) -> list[Bar]:
    """Return a list of Bar dataclass instances for testing."""
    return [
        Bar(
            timestamp=datetime(2022, month, 1, 9, 30 + i, 0, tzinfo=timezone.utc),
            open=150.0 + i,
            high=151.5 + i,
            low=149.0 + i,
            close=150.5 + i,
            volume=1000.0 + i * 100,
            vwap=150.25 + i,
            num_transactions=42 + i,
        )
        for i in range(n)
    ]


def _mock_client() -> PolygonClient:
    """Return a mock PolygonClient with a default get_bars that returns
    sample bars."""
    client = MagicMock(spec=PolygonClient)
    client.get_bars = AsyncMock(return_value=_sample_bars(3))
    return client


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


@pytest.fixture
def config(tmp_path: Path) -> MarketPulseConfig:
    cfg = MarketPulseConfig(data_dir=tmp_path)
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def mock_client() -> PolygonClient:
    return _mock_client()


def _setup_db_and_cache(config, mock_client):
    """Synchronous helper to create engine + session factory + init db and
    return (cache_manager, session_factory)."""

    async def _init():
        engine = get_engine(config)
        sf = get_session_factory(config)
        await init_db(Base.metadata)
        cm = CacheManager(config, mock_client, sf)
        return cm, sf

    return asyncio.run(_init())


# ---------------------------------------------------------------------------
# CoverageReport dataclass
# ---------------------------------------------------------------------------


class TestCoverageReport:
    def test_fully_cached_true_when_no_missing(self):
        report = CoverageReport(
            ticker="AAPL",
            timespan="1min",
            from_date=date(2022, 6, 1),
            to_date=date(2022, 6, 30),
            cached=["2022-06"],
            missing=[],
        )
        assert report.fully_cached is True

    def test_fully_cached_false_when_missing(self):
        report = CoverageReport(
            ticker="AAPL",
            timespan="1min",
            from_date=date(2022, 6, 1),
            to_date=date(2022, 7, 31),
            cached=["2022-06"],
            missing=["2022-07"],
        )
        assert report.fully_cached is False


# ---------------------------------------------------------------------------
# CacheManager.check_coverage
# ---------------------------------------------------------------------------


class TestCheckCoverage:
    def test_all_missing_when_empty_db(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _run():
            return await cm.check_coverage(
                "AAPL", "1min", date(2022, 6, 1), date(2022, 8, 31)
            )

        report = asyncio.run(_run())

        assert report.ticker == "AAPL"
        assert report.timespan == "1min"
        assert report.missing == ["2022-06", "2022-07", "2022-08"]
        assert report.cached == []
        assert report.fully_cached is False

    def test_correct_cached_missing_split(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        # Manually insert a coverage row for 2022-06
        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.check_coverage(
                "AAPL", "1min", date(2022, 6, 1), date(2022, 8, 31)
            )

        report = asyncio.run(_run())

        assert report.cached == ["2022-06"]
        assert report.missing == ["2022-07", "2022-08"]
        assert report.fully_cached is False

    def test_fully_cached_when_all_present(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.check_coverage(
                "AAPL", "1min", date(2022, 6, 1), date(2022, 6, 30)
            )

        report = asyncio.run(_run())

        assert report.cached == ["2022-06"]
        assert report.missing == []
        assert report.fully_cached is True


# ---------------------------------------------------------------------------
# CacheManager.fetch_and_cache
# ---------------------------------------------------------------------------


class TestFetchAndCache:
    def test_writes_parquet_and_coverage(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _run():
            return await cm.fetch_and_cache(
                "AAPL", "1min", 1, date(2022, 6, 1), date(2022, 6, 30)
            )

        total = asyncio.run(_run())

        # Should have cached 3 bars (our mock returns 3)
        assert total == 3

        # Parquet file should exist
        pq_path = partition_path(
            "AAPL", "1min", "2022-06", bars_dir=config.bars_dir
        )
        assert pq_path.exists()

        # Coverage row should exist
        async def _check():
            async with sf() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(Coverage).where(
                        Coverage.ticker == "AAPL",
                        Coverage.timespan == "1min",
                        Coverage.year_month == "2022-06",
                    )
                )
                row = result.scalar_one()
                assert row.bar_count == 3

        asyncio.run(_check())

    def test_skips_cached_months(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        # Pre-seed 2022-06 as cached
        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.fetch_and_cache(
                "AAPL", "1min", 1, date(2022, 6, 1), date(2022, 7, 31)
            )

        total = asyncio.run(_run())

        # Only 2022-07 was missing, so client.get_bars should be called once
        assert mock_client.get_bars.call_count == 1
        assert total == 3  # 3 bars for the one missing month

    def test_fully_cached_returns_zero(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        # Pre-seed 2022-06 as cached
        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.fetch_and_cache(
                "AAPL", "1min", 1, date(2022, 6, 1), date(2022, 6, 30)
            )

        total = asyncio.run(_run())

        assert total == 0
        # Client should not have been called at all
        mock_client.get_bars.assert_not_called()

    def test_multi_month_fetch(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _run():
            return await cm.fetch_and_cache(
                "AAPL", "1min", 1, date(2022, 6, 1), date(2022, 8, 31)
            )

        total = asyncio.run(_run())

        # 3 months * 3 bars each
        assert total == 9
        assert mock_client.get_bars.call_count == 3

    def test_bars_readable_after_cache(self, config, mock_client):
        """Verify that Parquet files written by fetch_and_cache are valid."""
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _run():
            await cm.fetch_and_cache(
                "AAPL", "1min", 1, date(2022, 6, 1), date(2022, 6, 30)
            )

        asyncio.run(_run())

        df = read_bars("AAPL", "1min", "2022-06", bars_dir=config.bars_dir)
        assert len(df) == 3
        assert "open" in df.columns
        assert "timestamp" in df.columns


# ---------------------------------------------------------------------------
# CacheManager.get_cache_status
# ---------------------------------------------------------------------------


class TestGetCacheStatus:
    def test_summary_empty(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _run():
            return await cm.get_cache_status()

        status = asyncio.run(_run())
        assert status["total_tickers"] == 0
        assert status["total_bars"] == 0
        assert status["total_partitions"] == 0

    def test_summary_with_data(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                session.add(
                    Coverage(
                        ticker="MSFT",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=200,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.get_cache_status()

        status = asyncio.run(_run())
        assert status["total_tickers"] == 2
        assert status["total_bars"] == 300
        assert status["total_partitions"] == 2

    def test_per_ticker_status(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)

        async def _seed():
            async with sf() as session:
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1min",
                        year_month="2022-06",
                        bar_count=100,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                session.add(
                    Coverage(
                        ticker="AAPL",
                        timespan="1day",
                        year_month="2022-06",
                        bar_count=20,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        async def _run():
            return await cm.get_cache_status(ticker="AAPL")

        status = asyncio.run(_run())
        assert status["ticker"] == "AAPL"
        assert status["total_bars"] == 120
        assert "1min" in status["timespan_coverage"]
        assert "1day" in status["timespan_coverage"]
        assert "2022-06" in status["timespan_coverage"]["1min"]


# ---------------------------------------------------------------------------
# BatchEngine.pull
# ---------------------------------------------------------------------------


class TestBatchEnginePull:
    def test_creates_job_and_completes(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        async def _run():
            return await engine.pull(
                ["AAPL", "MSFT"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
            )

        job = asyncio.run(_run())

        assert job.status == "completed"
        assert job.total_tickers == 2
        assert job.completed_tickers == 2
        assert job.current_ticker is None
        assert job.error is None

        # Tickers stored as JSON
        tickers = json.loads(job.tickers)
        assert tickers == ["AAPL", "MSFT"]

    def test_progress_callback(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        progress_calls = []

        def on_progress(ticker, completed, total):
            progress_calls.append((ticker, completed, total))

        async def _run():
            return await engine.pull(
                ["AAPL", "MSFT", "GOOG"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
                on_progress=on_progress,
            )

        asyncio.run(_run())

        assert len(progress_calls) == 3
        assert progress_calls[0] == ("AAPL", 1, 3)
        assert progress_calls[1] == ("MSFT", 2, 3)
        assert progress_calls[2] == ("GOOG", 3, 3)

    def test_failed_status_on_exception(self, config, mock_client):
        # Make client raise on the second ticker
        call_count = 0

        async def _flaky_get_bars(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("API exploded")
            return _sample_bars(2)

        mock_client.get_bars = AsyncMock(side_effect=_flaky_get_bars)

        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        async def _run():
            return await engine.pull(
                ["AAPL", "MSFT"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
            )

        job = asyncio.run(_run())

        assert job.status == "failed"
        assert "API exploded" in job.error
        assert job.completed_tickers == 1

    def test_job_persisted_in_db(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        async def _run():
            job = await engine.pull(
                ["AAPL"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
            )
            return job.id

        job_id = asyncio.run(_run())

        # Verify we can load the job back from the DB
        async def _check():
            from sqlalchemy import select

            async with sf() as session:
                result = await session.execute(
                    select(FetchJob).where(FetchJob.id == job_id)
                )
                job = result.scalar_one()
                assert job.status == "completed"

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# BatchEngine.resume
# ---------------------------------------------------------------------------


class TestBatchEngineResume:
    def test_resume_skips_completed_tickers(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        # Create a "paused" job manually with 1 of 3 tickers completed
        job_id = "test-resume-01"

        async def _seed():
            async with sf() as session:
                session.add(
                    FetchJob(
                        id=job_id,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        tickers=json.dumps(["AAPL", "MSFT", "GOOG"]),
                        from_date="2022-06-01",
                        to_date="2022-06-30",
                        timespan="1min",
                        status="paused",
                        total_tickers=3,
                        completed_tickers=1,
                        current_ticker="MSFT",
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        progress_calls = []

        def on_progress(ticker, completed, total):
            progress_calls.append(ticker)

        async def _run():
            return await engine.resume(job_id, on_progress=on_progress)

        job = asyncio.run(_run())

        assert job.status == "completed"
        # Only MSFT and GOOG should have been processed (AAPL was skipped)
        assert progress_calls == ["MSFT", "GOOG"]


# ---------------------------------------------------------------------------
# BatchEngine.list_jobs
# ---------------------------------------------------------------------------


class TestBatchEngineListJobs:
    def test_list_returns_all_jobs(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        async def _run():
            await engine.pull(
                ["AAPL"], date(2022, 6, 1), date(2022, 6, 30), timespan="1min"
            )
            await engine.pull(
                ["MSFT"], date(2022, 7, 1), date(2022, 7, 31), timespan="1min"
            )
            return await engine.list_jobs()

        jobs = asyncio.run(_run())

        assert len(jobs) == 2
        # Ordered by created_at desc, so second job first
        assert all(j.status == "completed" for j in jobs)


# ---------------------------------------------------------------------------
# Job status transitions
# ---------------------------------------------------------------------------


class TestJobStatusTransitions:
    def test_pending_to_running_to_completed(self, config, mock_client):
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        # Track job statuses during execution
        statuses_seen = []

        original_fetch = cm.fetch_and_cache

        async def _spying_fetch(*args, **kwargs):
            # Check job status mid-flight
            from sqlalchemy import select

            async with sf() as session:
                result = await session.execute(select(FetchJob))
                job = result.scalar_one()
                statuses_seen.append(job.status)
            return await original_fetch(*args, **kwargs)

        cm.fetch_and_cache = _spying_fetch

        async def _run():
            return await engine.pull(
                ["AAPL"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
            )

        job = asyncio.run(_run())

        # During execution the status should have been "running"
        assert "running" in statuses_seen
        assert job.status == "completed"

    def test_running_to_failed(self, config, mock_client):
        mock_client.get_bars = AsyncMock(
            side_effect=RuntimeError("network failure")
        )
        cm, sf = _setup_db_and_cache(config, mock_client)
        engine = BatchEngine(cm, sf)

        async def _run():
            return await engine.pull(
                ["AAPL"],
                date(2022, 6, 1),
                date(2022, 6, 30),
                timespan="1min",
            )

        job = asyncio.run(_run())

        assert job.status == "failed"
        assert "network failure" in job.error


# ---------------------------------------------------------------------------
# TIMESPAN_MAP sanity
# ---------------------------------------------------------------------------


class TestTimespanMap:
    def test_known_mappings(self):
        assert TIMESPAN_MAP["1min"] == ("minute", 1)
        assert TIMESPAN_MAP["5min"] == ("minute", 5)
        assert TIMESPAN_MAP["15min"] == ("minute", 15)
        assert TIMESPAN_MAP["1hour"] == ("hour", 1)
        assert TIMESPAN_MAP["1day"] == ("day", 1)
