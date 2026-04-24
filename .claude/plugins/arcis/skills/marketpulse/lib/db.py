"""Data directory, SQLite engine, and DuckDB connection management.

Provides:
- ``MarketPulseConfig`` -- central configuration loaded from env vars.
- Async SQLAlchemy engine + session factory for the SQLite metadata DB.
- DuckDB in-memory connection factory for Parquet analytics queries.
- ``bars_glob()`` helper to build Parquet glob paths for ``read_parquet()``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from sqlalchemy import MetaData


# ---------------------------------------------------------------------------
# ORM base -- shared across all model modules
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all MarketPulse SQLAlchemy models."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MarketPulseConfig:
    """Central configuration for MarketPulse, populated from environment."""

    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "MARKETPULSE_DATA_DIR",
                str(Path.home() / ".marketpulse"),
            )
        )
    )
    concurrency: int = field(
        default_factory=lambda: int(
            os.environ.get("MARKETPULSE_CONCURRENCY", "10")
        )
    )
    rate_limit: int = field(
        default_factory=lambda: int(
            os.environ.get("MARKETPULSE_RATE_LIMIT", "50")
        )
    )
    polygon_api_key: str = field(
        default_factory=lambda: os.environ.get("POLYGON_API_KEY", "")
    )

    # -- derived paths -------------------------------------------------------

    @property
    def db_url(self) -> str:
        """SQLAlchemy connection URL for the async SQLite engine."""
        return f"sqlite+aiosqlite:///{self.data_dir / 'metadata.db'}"

    @property
    def bars_dir(self) -> Path:
        """Root directory for Hive-partitioned Parquet bar data."""
        return self.data_dir / "bars"

    # -- directory bootstrap -------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create the data directory tree if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "custom_lists").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Module-level config singleton
# ---------------------------------------------------------------------------

_config: MarketPulseConfig | None = None


def get_config() -> MarketPulseConfig:
    """Return the global config singleton, creating it on first call."""
    global _config
    if _config is None:
        _config = MarketPulseConfig()
        _config.ensure_dirs()
    return _config


def reset_config() -> None:
    """Reset the global config singleton (useful in tests)."""
    global _config, _engine, _session_factory
    _config = None
    _engine = None
    _session_factory = None


# ---------------------------------------------------------------------------
# SQLite async engine + session
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _enable_wal(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
    """Enable WAL journal mode on every new raw DBAPI connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_engine(config: MarketPulseConfig | None = None) -> AsyncEngine:
    """Return the async SQLAlchemy engine, creating it on first call.

    The engine connects to ``{data_dir}/metadata.db`` with WAL mode
    enabled via an event listener on the underlying sync engine.
    """
    global _engine
    if _engine is None:
        cfg = config or get_config()
        _engine = create_async_engine(cfg.db_url, echo=False)
        event.listens_for(_engine.sync_engine, "connect")(_enable_wal)
    return _engine


def get_session_factory(
    config: MarketPulseConfig | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the engine."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(config)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncSession:
    """Convenience: open a new async session from the global factory."""
    factory = get_session_factory()
    return factory()


async def init_db(metadata: MetaData | None = None) -> None:
    """Create all tables in ``metadata.db``.

    Parameters
    ----------
    metadata:
        Optional SQLAlchemy ``MetaData`` to use.  When *None* the
        module imports ``models`` lazily and uses ``Base.metadata``
        to avoid circular-import issues during startup.
    """
    if metadata is None:
        metadata = Base.metadata
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------

def get_duckdb() -> duckdb.DuckDBPyConnection:
    """Return a fresh in-memory DuckDB connection.

    The connection is in-memory because we only use DuckDB to run
    analytical queries against Parquet files already on disk.
    """
    return duckdb.connect()


def bars_glob(
    ticker: str | None = None,
    timespan: str = "1min",
    year_month: str | None = None,
) -> str:
    """Build a Parquet glob path for ``read_parquet()`` calls.

    The Hive-partitioned layout under ``bars/`` is::

        bars/timespan=1min/ticker=AAPL/2022-06.parquet

    Examples
    --------
    >>> bars_glob("AAPL", "1min")
    '.../bars/timespan=1min/ticker=AAPL/*.parquet'

    >>> bars_glob("AAPL", "1min", "2022-06")
    '.../bars/timespan=1min/ticker=AAPL/2022-06.parquet'

    >>> bars_glob(None, "1min", "2022-06")
    '.../bars/timespan=1min/ticker=*/2022-06.parquet'
    """
    cfg = get_config()
    base = cfg.bars_dir / f"timespan={timespan}"

    if ticker is not None:
        base = base / f"ticker={ticker}"
    else:
        base = base / "ticker=*"

    if year_month is not None:
        return str(base / f"{year_month}.parquet").replace("\\", "/")
    return str(base / "*.parquet").replace("\\", "/")
