"""Shared pytest fixtures for MarketPulse tests.

Provides:
- ``tmp_data_dir``       -- temp directory standing in for ~/.marketpulse/
- ``test_config``        -- MarketPulseConfig pointed at the temp dir
- ``mock_polygon_client``-- mock PolygonClient returning fixture bars
- ``db_session``         -- async SQLite session with tables created
- ``load_fixture()``     -- helper to load JSON from fixtures/polygon_responses/
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Make ``lib`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.client import Bar, PolygonClient  # noqa: E402
from lib.db import (  # noqa: E402
    Base,
    MarketPulseConfig,
    get_engine,
    get_session_factory,
    init_db,
    reset_config,
)

# ---------------------------------------------------------------------------
# Fixture data directory
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "polygon_responses"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file from ``tests/fixtures/polygon_responses/{name}.json``.

    Parameters
    ----------
    name:
        Filename without the ``.json`` extension (e.g. ``"ticker_details_aapl"``).

    Returns
    -------
    dict
        Parsed JSON content.
    """
    path = _FIXTURES_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Sample bar helper
# ---------------------------------------------------------------------------

def _sample_bars(n: int = 5, month: int = 1, year: int = 2022) -> list[Bar]:
    """Return *n* Bar dataclass instances for testing.

    Each bar is timestamped on day 3 of the given month/year at
    09:30 + i minutes, providing stable fixture data.
    """
    return [
        Bar(
            timestamp=datetime(year, month, 3, 9, 30 + i, 0, tzinfo=timezone.utc),
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path: Path):
    """Create a temporary data directory for ``~/.marketpulse/``.

    Sets the ``MARKETPULSE_DATA_DIR`` environment variable, resets
    the global config singleton, and cleans up after the test.
    """
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    os.environ.setdefault("POLYGON_API_KEY", "test-key-fixture")
    yield tmp_path
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)


@pytest.fixture
def test_config(tmp_data_dir: Path) -> MarketPulseConfig:
    """Return a ``MarketPulseConfig`` pointed at the temp data directory.

    Also ensures subdirectories (bars/, custom_lists/) exist.
    """
    cfg = MarketPulseConfig(
        data_dir=tmp_data_dir,
        polygon_api_key="test-key-fixture",
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def mock_polygon_client() -> PolygonClient:
    """Return a mock ``PolygonClient`` whose ``get_bars()`` returns sample bars.

    The default implementation returns 5 bars.  Tests can override
    ``mock_polygon_client.get_bars`` with a custom ``AsyncMock`` or
    side_effect for more specific behaviour.
    """
    client = MagicMock(spec=PolygonClient)
    client.get_bars = AsyncMock(return_value=_sample_bars(5))
    return client


@pytest.fixture
def db_session(test_config: MarketPulseConfig):
    """Create a file-based SQLite database in the temp dir, run ``init_db()``,
    and yield an async session factory.

    After the test, the engine is disposed of.
    """

    async def _setup():
        engine = get_engine(test_config)
        sf = get_session_factory(test_config)
        await init_db(Base.metadata)
        return engine, sf

    engine, sf = asyncio.run(_setup())

    yield sf

    asyncio.run(engine.dispose())
