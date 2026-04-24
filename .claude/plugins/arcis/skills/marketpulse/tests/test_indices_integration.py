"""Integration tests for index-based pull pipeline.

Tests the full flow: resolve an index name to tickers, then run a
mock pull through BatchEngine and verify job completion.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Make ``lib`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.indices import IndexManager
from lib.db import (
    Base,
    MarketPulseConfig,
    get_config,
    get_session_factory,
    init_db,
    reset_config,
)
from lib.cache import CacheManager, BatchEngine
from lib.client import Bar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_config(tmp_path, monkeypatch):
    """Reset config singleton and point data dir at tmp."""
    reset_config()
    monkeypatch.setenv("MARKETPULSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    yield
    reset_config()


@pytest.fixture
def test_config(tmp_path):
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    config = get_config()
    config.ensure_dirs()
    return config


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIndexBasedPull:
    """Full pipeline: resolve index -> pull bars -> verify job."""

    @pytest.mark.asyncio
    async def test_dow30_resolve_and_pull(self, test_config):
        """DOW30 resolves to 30 tickers and a mock pull completes for all."""
        idx_mgr = IndexManager(test_config)
        tickers = idx_mgr.get_tickers("DOW30")
        assert len(tickers) == 30

        sf = get_session_factory(test_config)
        await init_db(Base.metadata)

        # Mock Polygon client
        mock_client = AsyncMock()
        mock_client.get_bars = AsyncMock(return_value=[
            Bar(
                timestamp=datetime(2022, 1, 3, 14, 30, tzinfo=timezone.utc),
                open=100.0, high=101.0, low=99.0, close=100.5,
                volume=1000, vwap=100.25, num_transactions=50,
            )
        ])

        cm = CacheManager(test_config, mock_client, sf)
        engine = BatchEngine(cm, sf)

        job = await engine.pull(
            tickers=tickers,
            from_date=date(2022, 1, 3),
            to_date=date(2022, 1, 3),
            timespan="1day",
        )

        assert job.status == "completed"
        assert job.completed_tickers == 30
        assert job.total_tickers == 30

    @pytest.mark.asyncio
    async def test_sp100_resolve_count(self, test_config):
        """SP100 resolves to approximately 101 tickers."""
        idx_mgr = IndexManager(test_config)
        tickers = idx_mgr.get_tickers("SP100")
        assert len(tickers) >= 100
        assert len(tickers) <= 105

    @pytest.mark.asyncio
    async def test_custom_list_pull(self, test_config):
        """Custom list can be created and used in a pull."""
        idx_mgr = IndexManager(test_config)
        idx_mgr.create_custom_list("test-trio", ["AAPL", "MSFT", "GOOG"])

        tickers = idx_mgr.get_tickers("test-trio")
        assert tickers == ["AAPL", "MSFT", "GOOG"]

        sf = get_session_factory(test_config)
        await init_db(Base.metadata)

        mock_client = AsyncMock()
        mock_client.get_bars = AsyncMock(return_value=[])

        cm = CacheManager(test_config, mock_client, sf)
        engine = BatchEngine(cm, sf)

        job = await engine.pull(
            tickers=tickers,
            from_date=date(2022, 1, 3),
            to_date=date(2022, 1, 3),
            timespan="1day",
        )

        assert job.status == "completed"
        assert job.completed_tickers == 3

    @pytest.mark.asyncio
    async def test_rut2000_resolves_empty(self, test_config):
        """RUT2000 has no tickers, so resolving it returns empty list."""
        idx_mgr = IndexManager(test_config)
        tickers = idx_mgr.get_tickers("RUT2000")
        assert tickers == []
