"""Tests for marketpulse lib.models -- SQLAlchemy metadata tables.

Verifies all four models can be created, inserted, queried, and that
composite-PK uniqueness is enforced for Coverage and IndexMember.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Make ``lib.*`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.db import Base  # noqa: E402
from lib.models import Coverage, FetchJob, IndexMember, Ticker  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine_and_session():
    """Create an in-memory SQLite engine + session, with all tables."""

    async def _build():
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        return engine, factory

    engine, factory = asyncio.run(_build())
    yield engine, factory

    asyncio.run(engine.dispose())


def _run(coro):
    """Shorthand to run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Ticker
# ---------------------------------------------------------------------------

class TestTicker:

    def test_insert_and_query(self, engine_and_session):
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(
                    symbol="AAPL",
                    name="Apple Inc.",
                    sector="Technology",
                    industry="Consumer Electronics",
                    market_cap=3_000_000_000_000.0,
                    sic_code="3571",
                    updated_at="2026-04-24T12:00:00Z",
                ))
                await session.commit()

            async with factory() as session:
                row = await session.get(Ticker, "AAPL")
                assert row is not None
                assert row.symbol == "AAPL"
                assert row.name == "Apple Inc."
                assert row.sector == "Technology"
                assert row.industry == "Consumer Electronics"
                assert row.market_cap == 3_000_000_000_000.0
                assert row.sic_code == "3571"
                assert row.updated_at == "2026-04-24T12:00:00Z"

        _run(_go())

    def test_nullable_fields(self, engine_and_session):
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(symbol="XYZ"))
                await session.commit()

            async with factory() as session:
                row = await session.get(Ticker, "XYZ")
                assert row is not None
                assert row.name is None
                assert row.market_cap is None

        _run(_go())


# ---------------------------------------------------------------------------
# IndexMember
# ---------------------------------------------------------------------------

class TestIndexMember:

    def test_insert_and_query(self, engine_and_session):
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(symbol="AAPL", name="Apple Inc."))
                session.add(IndexMember(
                    index_name="sp500",
                    ticker="AAPL",
                    added_date="2000-01-01",
                    removed_date=None,
                ))
                await session.commit()

            async with factory() as session:
                row = (await session.execute(
                    select(IndexMember).where(IndexMember.ticker == "AAPL")
                )).scalar_one()
                assert row.index_name == "sp500"
                assert row.ticker == "AAPL"
                assert row.added_date == "2000-01-01"
                assert row.removed_date is None

        _run(_go())

    def test_default_added_date(self, engine_and_session):
        """added_date defaults to empty string when not supplied."""
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(symbol="MSFT", name="Microsoft"))
                session.add(IndexMember(index_name="sp500", ticker="MSFT"))
                await session.commit()

            async with factory() as session:
                row = (await session.execute(
                    select(IndexMember).where(IndexMember.ticker == "MSFT")
                )).scalar_one()
                assert row.added_date == ""

        _run(_go())

    def test_composite_pk_uniqueness(self, engine_and_session):
        """Duplicate (index_name, ticker, added_date) must raise."""
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(symbol="GOOG", name="Alphabet"))
                session.add(IndexMember(
                    index_name="sp500", ticker="GOOG", added_date="2014-04-03"
                ))
                await session.commit()

            async with factory() as session:
                session.add(IndexMember(
                    index_name="sp500", ticker="GOOG", added_date="2014-04-03"
                ))
                with pytest.raises(IntegrityError):
                    await session.commit()

        _run(_go())

    def test_same_ticker_different_dates(self, engine_and_session):
        """Same ticker re-added to the same index on a different date is OK."""
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Ticker(symbol="META", name="Meta Platforms"))
                session.add(IndexMember(
                    index_name="sp500", ticker="META", added_date="2013-12-23",
                    removed_date="2022-09-19",
                ))
                session.add(IndexMember(
                    index_name="sp500", ticker="META", added_date="2023-03-20",
                ))
                await session.commit()

            async with factory() as session:
                rows = (await session.execute(
                    select(IndexMember).where(IndexMember.ticker == "META")
                )).scalars().all()
                assert len(rows) == 2

        _run(_go())


# ---------------------------------------------------------------------------
# FetchJob
# ---------------------------------------------------------------------------

class TestFetchJob:

    def test_insert_and_query(self, engine_and_session):
        engine, factory = engine_and_session
        job_id = str(uuid.uuid4())

        async def _go():
            async with factory() as session:
                session.add(FetchJob(
                    id=job_id,
                    created_at="2026-04-24T10:00:00Z",
                    index_name="sp500",
                    tickers=json.dumps(["AAPL", "MSFT", "GOOG"]),
                    from_date="2024-01-01",
                    to_date="2026-04-24",
                    timespan="day",
                    status="pending",
                    total_tickers=3,
                    completed_tickers=0,
                    current_ticker=None,
                    error=None,
                ))
                await session.commit()

            async with factory() as session:
                row = await session.get(FetchJob, job_id)
                assert row is not None
                assert row.status == "pending"
                assert row.total_tickers == 3
                assert row.completed_tickers == 0
                assert json.loads(row.tickers) == ["AAPL", "MSFT", "GOOG"]
                assert row.index_name == "sp500"
                assert row.current_ticker is None
                assert row.error is None

        _run(_go())

    def test_default_completed_tickers(self, engine_and_session):
        engine, factory = engine_and_session
        job_id = str(uuid.uuid4())

        async def _go():
            async with factory() as session:
                session.add(FetchJob(
                    id=job_id,
                    created_at="2026-04-24T10:00:00Z",
                    tickers="[]",
                    from_date="2024-01-01",
                    to_date="2026-04-24",
                    timespan="day",
                    status="pending",
                    total_tickers=0,
                ))
                await session.commit()

            async with factory() as session:
                row = await session.get(FetchJob, job_id)
                assert row.completed_tickers == 0

        _run(_go())


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

class TestCoverage:

    def test_insert_and_query(self, engine_and_session):
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Coverage(
                    ticker="AAPL",
                    timespan="day",
                    year_month="2024-06",
                    bar_count=21,
                    fetched_at="2026-04-24T12:00:00Z",
                ))
                await session.commit()

            async with factory() as session:
                row = (await session.execute(
                    select(Coverage).where(
                        Coverage.ticker == "AAPL",
                        Coverage.timespan == "day",
                        Coverage.year_month == "2024-06",
                    )
                )).scalar_one()
                assert row.bar_count == 21
                assert row.fetched_at == "2026-04-24T12:00:00Z"

        _run(_go())

    def test_composite_pk_uniqueness(self, engine_and_session):
        """Duplicate (ticker, timespan, year_month) must raise."""
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Coverage(
                    ticker="MSFT",
                    timespan="day",
                    year_month="2024-01",
                    bar_count=22,
                    fetched_at="2026-04-24T12:00:00Z",
                ))
                await session.commit()

            async with factory() as session:
                session.add(Coverage(
                    ticker="MSFT",
                    timespan="day",
                    year_month="2024-01",
                    bar_count=99,
                    fetched_at="2026-04-24T13:00:00Z",
                ))
                with pytest.raises(IntegrityError):
                    await session.commit()

        _run(_go())

    def test_different_timespan_same_month(self, engine_and_session):
        """Same ticker+month but different timespan should be allowed."""
        engine, factory = engine_and_session

        async def _go():
            async with factory() as session:
                session.add(Coverage(
                    ticker="GOOG", timespan="day", year_month="2024-03",
                    bar_count=21, fetched_at="2026-04-24T12:00:00Z",
                ))
                session.add(Coverage(
                    ticker="GOOG", timespan="1min", year_month="2024-03",
                    bar_count=8400, fetched_at="2026-04-24T12:00:00Z",
                ))
                await session.commit()

            async with factory() as session:
                rows = (await session.execute(
                    select(Coverage).where(Coverage.ticker == "GOOG")
                )).scalars().all()
                assert len(rows) == 2

        _run(_go())
