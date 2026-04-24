"""End-to-end integration tests for the MarketPulse pipeline.

Tests exercise the full stack -- config, database, CacheManager,
BatchEngine, Parquet storage, and DuckDB queries -- with only the
HTTP layer mocked out via a fake PolygonClient.

Uses ``asyncio.run()`` for async operations (no pytest-asyncio needed).
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

from lib.cache import BatchEngine, CacheManager  # noqa: E402
from lib.client import Bar, PolygonClient  # noqa: E402
from lib.db import (  # noqa: E402
    Base,
    MarketPulseConfig,
    get_engine,
    get_session_factory,
    init_db,
    reset_config,
    bars_glob,
    get_duckdb,
)
from lib.models import Coverage, FetchJob  # noqa: E402
from lib.storage import partition_path, read_bars  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(ticker: str, n: int = 5, month: int = 1, year: int = 2022) -> list[Bar]:
    """Generate *n* deterministic Bar instances for the given ticker/month.

    The ticker name is hashed into the price to make bars distinguishable
    between tickers.
    """
    seed = sum(ord(c) for c in ticker)
    return [
        Bar(
            timestamp=datetime(year, month, 3, 9, 30 + i, 0, tzinfo=timezone.utc),
            open=100.0 + seed + i,
            high=101.5 + seed + i,
            low=99.0 + seed + i,
            close=100.5 + seed + i,
            volume=1000.0 + i * 100,
            vwap=100.25 + seed + i,
            num_transactions=42 + i,
        )
        for i in range(n)
    ]


def _mock_client_for_tickers(*tickers: str, bars_per_month: int = 5) -> PolygonClient:
    """Return a mock PolygonClient that returns bars keyed by ticker.

    Each call to ``get_bars(ticker, ...)`` returns ``bars_per_month``
    bars seeded from the ticker name.
    """
    client = MagicMock(spec=PolygonClient)

    async def _get_bars(ticker, timespan, multiplier, from_date, to_date):
        return _make_bars(ticker, n=bars_per_month, month=from_date.month, year=from_date.year)

    client.get_bars = AsyncMock(side_effect=_get_bars)
    return client


def _full_stack(config, client):
    """Initialise config -> db -> CacheManager -> BatchEngine.

    Returns (cache_manager, batch_engine, session_factory).
    """

    async def _init():
        engine = get_engine(config)
        sf = get_session_factory(config)
        await init_db(Base.metadata)
        cm = CacheManager(config, client, sf)
        be = BatchEngine(cm, sf)
        return cm, be, sf

    return asyncio.run(_init())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_env(tmp_path: Path):
    """Reset global singletons and point MARKETPULSE_DATA_DIR at tmp_path."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    os.environ.setdefault("POLYGON_API_KEY", "test-key-integration")
    yield
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)


@pytest.fixture
def config(tmp_path: Path) -> MarketPulseConfig:
    cfg = MarketPulseConfig(data_dir=tmp_path, polygon_api_key="test-key-integration")
    cfg.ensure_dirs()
    return cfg


# ===========================================================================
# Step 1: End-to-end pull and query
# ===========================================================================


class TestEndToEndPullAndQuery:
    """Full pipeline: pull tickers, verify storage, test cache, query bars."""

    def test_pull_two_tickers_creates_parquet_and_coverage(self, config):
        """Pull AAPL + MSFT for Jan 2022 and verify artefacts."""
        client = _mock_client_for_tickers("AAPL", "MSFT", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _run():
            return await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        job = asyncio.run(_run())

        # -- FetchJob assertions --
        assert job.status == "completed"
        assert job.total_tickers == 2
        assert job.completed_tickers == 2
        assert job.error is None

        # -- Parquet files written at correct partition paths --
        aapl_pq = partition_path("AAPL", "1min", "2022-01", bars_dir=config.bars_dir)
        msft_pq = partition_path("MSFT", "1min", "2022-01", bars_dir=config.bars_dir)
        assert aapl_pq.exists(), f"AAPL parquet missing at {aapl_pq}"
        assert msft_pq.exists(), f"MSFT parquet missing at {msft_pq}"

        # -- Coverage rows in SQLite --
        async def _check_coverage():
            from sqlalchemy import select

            async with sf() as session:
                result = await session.execute(
                    select(Coverage).order_by(Coverage.ticker)
                )
                rows = result.scalars().all()
                return rows

        rows = asyncio.run(_check_coverage())
        assert len(rows) == 2
        tickers_in_db = {r.ticker for r in rows}
        assert tickers_in_db == {"AAPL", "MSFT"}
        for row in rows:
            assert row.timespan == "1min"
            assert row.year_month == "2022-01"
            assert row.bar_count == 5

    def test_second_pull_fully_cached_no_api_calls(self, config):
        """Pulling the same tickers again should make zero API calls."""
        client = _mock_client_for_tickers("AAPL", "MSFT", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _first_pull():
            await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        asyncio.run(_first_pull())

        # Record the call count after the first pull
        calls_after_first = client.get_bars.call_count
        assert calls_after_first == 2  # one per ticker

        async def _second_pull():
            return await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        job2 = asyncio.run(_second_pull())

        # No additional API calls should have been made
        assert client.get_bars.call_count == calls_after_first
        assert job2.status == "completed"
        assert job2.completed_tickers == 2

    def test_query_bars_via_duckdb(self, config):
        """Data written by the pipeline should be queryable via DuckDB."""
        client = _mock_client_for_tickers("AAPL", "MSFT", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _pull():
            await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        asyncio.run(_pull())

        # Query via DuckDB using the same glob helper the app uses
        aapl_glob = bars_glob(ticker="AAPL", timespan="1min")
        msft_glob = bars_glob(ticker="MSFT", timespan="1min")

        con = get_duckdb()
        try:
            df_aapl = con.execute(
                f"SELECT * FROM read_parquet('{aapl_glob}', hive_partitioning=true)"
            ).fetchdf()
            df_msft = con.execute(
                f"SELECT * FROM read_parquet('{msft_glob}', hive_partitioning=true)"
            ).fetchdf()
        finally:
            con.close()

        assert len(df_aapl) == 5
        assert len(df_msft) == 5

        # Verify the AAPL and MSFT bars have different price data
        # (seeded from ticker name hash)
        assert df_aapl["open"].iloc[0] != df_msft["open"].iloc[0]

        # Verify expected columns
        expected_cols = {"timestamp", "open", "high", "low", "close", "volume", "vwap", "num_transactions"}
        assert expected_cols.issubset(set(df_aapl.columns))

    def test_query_bars_via_cache_manager(self, config):
        """CacheManager.get_bars_df should return the same data via DuckDB."""
        client = _mock_client_for_tickers("AAPL", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _pull_and_query():
            await be.pull(
                ["AAPL"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )
            return await cm.get_bars_df(
                ["AAPL"],
                "1min",
                date(2022, 1, 1),
                date(2022, 1, 31),
            )

        df = asyncio.run(_pull_and_query())

        assert len(df) == 5
        assert "open" in df.columns
        assert "timestamp" in df.columns

    def test_cache_status_summary(self, config):
        """cache-status returns correct summary after pulling data."""
        client = _mock_client_for_tickers("AAPL", "MSFT", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _pull_and_status():
            await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )
            return await cm.get_cache_status()

        status = asyncio.run(_pull_and_status())

        assert status["total_tickers"] == 2
        assert status["total_bars"] == 10  # 5 per ticker
        assert status["total_partitions"] == 2

    def test_cache_status_per_ticker(self, config):
        """cache-status for a specific ticker returns detail."""
        client = _mock_client_for_tickers("AAPL", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _pull_and_status():
            await be.pull(
                ["AAPL"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )
            return await cm.get_cache_status(ticker="AAPL")

        status = asyncio.run(_pull_and_status())

        assert status["ticker"] == "AAPL"
        assert status["total_bars"] == 5
        assert "1min" in status["timespan_coverage"]
        assert "2022-01" in status["timespan_coverage"]["1min"]


# ===========================================================================
# Step 2: Resume after failure
# ===========================================================================


class TestResumeAfterFailure:
    """Simulate a failure mid-batch and verify resume processes only remaining tickers."""

    def test_fail_on_second_ticker_then_resume(self, config):
        """Pull 3 tickers; ticker 2 fails.  Resume should process remaining."""
        call_log: list[str] = []

        # -- Phase 1: client that fails on ticker 2 (MSFT) --
        async def _failing_get_bars(ticker, timespan, multiplier, from_date, to_date):
            call_log.append(ticker)
            if ticker == "MSFT":
                raise RuntimeError("Simulated API failure on MSFT")
            return _make_bars(ticker, n=5, month=from_date.month, year=from_date.year)

        client = MagicMock(spec=PolygonClient)
        client.get_bars = AsyncMock(side_effect=_failing_get_bars)

        cm, be, sf = _full_stack(config, client)

        async def _pull():
            return await be.pull(
                ["AAPL", "MSFT", "GOOG"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        job = asyncio.run(_pull())

        # After failure: AAPL completed, MSFT failed
        assert job.status == "failed"
        assert "Simulated API failure on MSFT" in job.error
        # AAPL was completed before MSFT failed
        assert job.completed_tickers == 1
        job_id = job.id

        # Verify AAPL parquet exists, MSFT and GOOG do not
        assert partition_path("AAPL", "1min", "2022-01", bars_dir=config.bars_dir).exists()
        assert not partition_path("MSFT", "1min", "2022-01", bars_dir=config.bars_dir).exists()
        assert not partition_path("GOOG", "1min", "2022-01", bars_dir=config.bars_dir).exists()

        # -- Phase 2: fix the mock and resume --
        call_log.clear()

        async def _good_get_bars(ticker, timespan, multiplier, from_date, to_date):
            call_log.append(ticker)
            return _make_bars(ticker, n=5, month=from_date.month, year=from_date.year)

        client.get_bars = AsyncMock(side_effect=_good_get_bars)
        # Rebuild CacheManager with the fixed client
        cm_fixed = CacheManager(config, client, sf)
        be_fixed = BatchEngine(cm_fixed, sf)

        progress_tickers: list[str] = []

        def on_progress(ticker, completed, total):
            progress_tickers.append(ticker)

        async def _resume():
            return await be_fixed.resume(job_id, on_progress=on_progress)

        resumed_job = asyncio.run(_resume())

        # Resume should pick up from where it left off
        assert resumed_job.status == "completed"
        # Note: the error field retains the original failure message as a
        # historical record -- the pull() method does not clear it on success.

        # Both MSFT and GOOG should have been fetched during resume
        assert "MSFT" in call_log
        assert "GOOG" in call_log
        # AAPL should NOT have been re-fetched (already cached)
        # Note: AAPL is not in the resume list since completed_tickers=1
        # means the resume starts from index 1 (MSFT).
        assert "AAPL" not in call_log

        # Progress should have reported MSFT and GOOG
        assert "MSFT" in progress_tickers
        assert "GOOG" in progress_tickers

        # All three parquet files should now exist
        assert partition_path("AAPL", "1min", "2022-01", bars_dir=config.bars_dir).exists()
        assert partition_path("MSFT", "1min", "2022-01", bars_dir=config.bars_dir).exists()
        assert partition_path("GOOG", "1min", "2022-01", bars_dir=config.bars_dir).exists()

    def test_resume_idempotent_when_already_completed(self, config):
        """Resuming a completed job should be a no-op."""
        client = _mock_client_for_tickers("AAPL", bars_per_month=5)
        cm, be, sf = _full_stack(config, client)

        async def _pull():
            return await be.pull(
                ["AAPL"],
                date(2022, 1, 3),
                date(2022, 1, 31),
                timespan="1min",
            )

        job = asyncio.run(_pull())
        assert job.status == "completed"
        job_id = job.id

        # Record API call count
        calls_after = client.get_bars.call_count

        async def _resume():
            return await be.resume(job_id)

        resumed = asyncio.run(_resume())

        # No additional API calls (all tickers already completed/cached)
        assert client.get_bars.call_count == calls_after
        assert resumed.status == "completed"

    def test_multi_month_pull_and_resume(self, config):
        """Pull across 2 months, fail, and resume correctly."""
        call_log: list[tuple[str, str]] = []

        call_count = 0

        async def _get_bars(ticker, timespan, multiplier, from_date, to_date):
            nonlocal call_count
            call_count += 1
            call_log.append((ticker, f"{from_date.year}-{from_date.month:02d}"))
            # Fail on MSFT (second ticker), second month
            if ticker == "MSFT" and from_date.month == 2:
                raise RuntimeError("Simulated failure MSFT Feb")
            return _make_bars(ticker, n=3, month=from_date.month, year=from_date.year)

        client = MagicMock(spec=PolygonClient)
        client.get_bars = AsyncMock(side_effect=_get_bars)

        cm, be, sf = _full_stack(config, client)

        async def _pull():
            return await be.pull(
                ["AAPL", "MSFT"],
                date(2022, 1, 3),
                date(2022, 2, 28),
                timespan="1min",
            )

        job = asyncio.run(_pull())

        # AAPL should be fully complete (both months).
        # MSFT should have failed on month 2.
        assert job.status == "failed"
        assert job.completed_tickers == 1  # AAPL done, MSFT failed

        # AAPL parquet for both months should exist
        assert partition_path("AAPL", "1min", "2022-01", bars_dir=config.bars_dir).exists()
        assert partition_path("AAPL", "1min", "2022-02", bars_dir=config.bars_dir).exists()

        # MSFT Jan should exist (fetched before Feb failure)
        assert partition_path("MSFT", "1min", "2022-01", bars_dir=config.bars_dir).exists()

        # Fix mock and resume
        call_log.clear()
        call_count = 0

        async def _good_get_bars(ticker, timespan, multiplier, from_date, to_date):
            nonlocal call_count
            call_count += 1
            call_log.append((ticker, f"{from_date.year}-{from_date.month:02d}"))
            return _make_bars(ticker, n=3, month=from_date.month, year=from_date.year)

        client.get_bars = AsyncMock(side_effect=_good_get_bars)
        cm_fixed = CacheManager(config, client, sf)
        be_fixed = BatchEngine(cm_fixed, sf)

        async def _resume():
            return await be_fixed.resume(job.id)

        resumed = asyncio.run(_resume())
        assert resumed.status == "completed"

        # Resume should only fetch MSFT Feb (Jan was already cached)
        msft_calls = [(t, m) for t, m in call_log if t == "MSFT"]
        assert len(msft_calls) == 1
        assert msft_calls[0] == ("MSFT", "2022-02")

        # AAPL should not have been re-fetched at all
        aapl_calls = [(t, m) for t, m in call_log if t == "AAPL"]
        assert len(aapl_calls) == 0

        # All parquet files should exist
        assert partition_path("MSFT", "1min", "2022-02", bars_dir=config.bars_dir).exists()
