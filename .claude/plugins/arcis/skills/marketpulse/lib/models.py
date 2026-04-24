"""SQLAlchemy ORM models for MarketPulse metadata tables.

Tables
------
- ``tickers``       -- reference data for each stock symbol
- ``index_members`` -- index constituent tracking (S&P 500, etc.)
- ``fetch_jobs``    -- batch job tracking for resumability
- ``coverage``      -- which ticker/month/timespan combos are cached
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Ticker(Base):
    """Reference data for a single stock symbol."""

    __tablename__ = "tickers"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    sic_code: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)


class IndexMember(Base):
    """Tracks which tickers belong to which index over time."""

    __tablename__ = "index_members"

    index_name: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.symbol"), primary_key=True
    )
    added_date: Mapped[str] = mapped_column(
        String, primary_key=True, default=""
    )
    removed_date: Mapped[str | None] = mapped_column(String, nullable=True)


class FetchJob(Base):
    """Batch job tracking for resumable multi-ticker fetches."""

    __tablename__ = "fetch_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    index_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tickers: Mapped[str] = mapped_column(String)  # JSON array
    from_date: Mapped[str] = mapped_column(String)
    to_date: Mapped[str] = mapped_column(String)
    timespan: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # pending/running/paused/completed/failed
    total_tickers: Mapped[int] = mapped_column(Integer)
    completed_tickers: Mapped[int] = mapped_column(Integer, default=0)
    current_ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Coverage(Base):
    """Tracks which ticker/timespan/month combos have cached bar data."""

    __tablename__ = "coverage"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    timespan: Mapped[str] = mapped_column(String, primary_key=True)
    year_month: Mapped[str] = mapped_column(String, primary_key=True)  # "YYYY-MM"
    bar_count: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[str] = mapped_column(String)
