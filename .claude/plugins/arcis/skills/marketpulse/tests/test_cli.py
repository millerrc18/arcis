"""Tests for marketpulse lib.cli -- Typer CLI commands.

Uses Typer's CliRunner to invoke commands in-process.  The Polygon
client is fully mocked, and a temporary directory is used for both
Parquet storage and the SQLite metadata database.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Make ``lib`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from typer.testing import CliRunner

from lib.cli import app
from lib.client import Bar, PolygonClient
from lib.db import (
    Base,
    MarketPulseConfig,
    get_engine,
    get_session_factory,
    init_db,
    reset_config,
)
from lib.models import Coverage, FetchJob

runner = CliRunner()


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


def _init_db_sync(tmp_path: Path):
    """Set up config, engine, session factory, and create tables."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    os.environ["POLYGON_API_KEY"] = "test-key-12345"

    async def _setup():
        from lib.db import get_config
        cfg = get_config()
        cfg.ensure_dirs()
        get_engine(cfg)
        get_session_factory(cfg)
        await init_db(Base.metadata)

    asyncio.run(_setup())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_env(tmp_path: Path):
    """Reset config and point at a temp dir for each test."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    os.environ["POLYGON_API_KEY"] = "test-key-12345"
    yield
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)
    os.environ.pop("POLYGON_API_KEY", None)


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------


class TestApiKeyValidation:
    def test_pull_errors_without_api_key(self, tmp_path):
        os.environ.pop("POLYGON_API_KEY", None)
        result = runner.invoke(app, [
            "pull", "AAPL", "--from", "2022-06-01", "--to", "2022-06-30",
        ])
        assert result.exit_code != 0
        assert "POLYGON_API_KEY" in result.output

    def test_cache_status_errors_without_api_key(self):
        os.environ.pop("POLYGON_API_KEY", None)
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code != 0
        assert "POLYGON_API_KEY" in result.output

    def test_jobs_list_errors_without_api_key(self):
        os.environ.pop("POLYGON_API_KEY", None)
        result = runner.invoke(app, ["jobs", "list"])
        assert result.exit_code != 0
        assert "POLYGON_API_KEY" in result.output


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------


class TestDateValidation:
    def test_invalid_from_date(self):
        result = runner.invoke(app, [
            "pull", "AAPL", "--from", "not-a-date", "--to", "2022-06-30",
        ])
        assert result.exit_code != 0
        assert "YYYY-MM-DD" in result.output

    def test_invalid_to_date(self):
        result = runner.invoke(app, [
            "pull", "AAPL", "--from", "2022-06-01", "--to", "garbage",
        ])
        assert result.exit_code != 0
        assert "YYYY-MM-DD" in result.output

    def test_from_after_to_date(self):
        result = runner.invoke(app, [
            "pull", "AAPL", "--from", "2022-07-01", "--to", "2022-06-01",
        ])
        assert result.exit_code != 0
        assert "before" in result.output.lower()


# ---------------------------------------------------------------------------
# Timespan validation
# ---------------------------------------------------------------------------


class TestTimespanValidation:
    def test_invalid_timespan(self):
        result = runner.invoke(app, [
            "pull", "AAPL",
            "--from", "2022-06-01", "--to", "2022-06-30",
            "--timespan", "3sec",
        ])
        assert result.exit_code != 0
        assert "Invalid timespan" in result.output


# ---------------------------------------------------------------------------
# Index name handling
# ---------------------------------------------------------------------------


class TestIndexNames:
    def test_index_resolves_dow30(self, tmp_path):
        """Passing an index name like DOW30 resolves and shows 'Resolved DOW30'."""
        _init_db_sync(tmp_path)

        mock_client_instance = MagicMock(spec=PolygonClient)
        mock_client_instance.get_bars = AsyncMock(return_value=_sample_bars(1))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("lib.cli.PolygonClient", return_value=mock_client_instance):
            result = runner.invoke(app, [
                "pull", "DOW30", "--from", "2022-06-01", "--to", "2022-06-30",
            ])

        assert result.exit_code == 0, f"Output: {result.output}"
        assert "Resolved" in result.output
        assert "DOW30" in result.output

    def test_all_known_indices_resolve(self, tmp_path):
        """SP100, SP500, DOW30, NDX100 resolve; RUT2000 shows no-tickers error."""
        _init_db_sync(tmp_path)

        mock_client_instance = MagicMock(spec=PolygonClient)
        mock_client_instance.get_bars = AsyncMock(return_value=_sample_bars(1))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        for idx in ("SP100", "SP500", "DOW30", "NDX100"):
            with patch("lib.cli.PolygonClient", return_value=mock_client_instance):
                result = runner.invoke(app, [
                    "pull", idx, "--from", "2022-06-01", "--to", "2022-06-30",
                ])
            assert "Resolved" in result.output, f"Failed for {idx}: {result.output}"
            assert idx in result.output, f"Index name not in output for {idx}"

        # RUT2000 has empty constituents -- should error
        result = runner.invoke(app, [
            "pull", "RUT2000", "--from", "2022-06-01", "--to", "2022-06-30",
        ])
        assert result.exit_code != 0, f"RUT2000 should fail: {result.output}"
        assert "no tickers" in result.output.lower()


# ---------------------------------------------------------------------------
# pull command with mocked client
# ---------------------------------------------------------------------------


class TestPullCommand:
    def test_pull_success(self, tmp_path):
        """Pull with mocked client completes and shows summary."""
        _init_db_sync(tmp_path)

        mock_client_instance = MagicMock(spec=PolygonClient)
        mock_client_instance.get_bars = AsyncMock(return_value=_sample_bars(3))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("lib.cli.PolygonClient", return_value=mock_client_instance):
            result = runner.invoke(app, [
                "pull", "AAPL",
                "--from", "2022-06-01", "--to", "2022-06-30",
                "--timespan", "1min",
            ])

        assert result.exit_code == 0, f"Output: {result.output}"
        assert "completed" in result.output.lower()

    def test_pull_multiple_tickers(self, tmp_path):
        """Pull multiple tickers shows correct progress."""
        _init_db_sync(tmp_path)

        mock_client_instance = MagicMock(spec=PolygonClient)
        mock_client_instance.get_bars = AsyncMock(return_value=_sample_bars(2))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("lib.cli.PolygonClient", return_value=mock_client_instance):
            result = runner.invoke(app, [
                "pull", "AAPL,MSFT,GOOG",
                "--from", "2022-06-01", "--to", "2022-06-30",
            ])

        assert result.exit_code == 0, f"Output: {result.output}"
        # The job should show 3/3 tickers
        assert "3/3" in result.output or "completed" in result.output.lower()

    def test_pull_default_timespan(self, tmp_path):
        """Default timespan is 1min."""
        _init_db_sync(tmp_path)

        mock_client_instance = MagicMock(spec=PolygonClient)
        mock_client_instance.get_bars = AsyncMock(return_value=_sample_bars(1))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("lib.cli.PolygonClient", return_value=mock_client_instance):
            result = runner.invoke(app, [
                "pull", "AAPL",
                "--from", "2022-06-01", "--to", "2022-06-30",
            ])

        assert result.exit_code == 0, f"Output: {result.output}"
        assert "1min" in result.output


# ---------------------------------------------------------------------------
# cache-status command
# ---------------------------------------------------------------------------


class TestCacheStatusCommand:
    def test_cache_status_empty(self, tmp_path):
        """Cache status with no data shows zeros."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0, f"Output: {result.output}"
        # Should show a table with "0" values
        assert "0" in result.output

    def test_cache_status_with_data(self, tmp_path):
        """Cache status after seeding coverage rows."""
        _init_db_sync(tmp_path)

        async def _seed():
            sf = get_session_factory()
            async with sf() as session:
                session.add(Coverage(
                    ticker="AAPL", timespan="1min", year_month="2022-06",
                    bar_count=500,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                ))
                session.add(Coverage(
                    ticker="MSFT", timespan="1min", year_month="2022-06",
                    bar_count=450,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                ))
                await session.commit()

        asyncio.run(_seed())

        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "2" in result.output  # 2 tickers
        assert "950" in result.output  # total bars

    def test_cache_status_per_ticker(self, tmp_path):
        """Cache status for a specific ticker shows coverage detail."""
        _init_db_sync(tmp_path)

        async def _seed():
            sf = get_session_factory()
            async with sf() as session:
                session.add(Coverage(
                    ticker="AAPL", timespan="1min", year_month="2022-06",
                    bar_count=500,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                ))
                session.add(Coverage(
                    ticker="AAPL", timespan="1min", year_month="2022-07",
                    bar_count=520,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                ))
                await session.commit()

        asyncio.run(_seed())

        result = runner.invoke(app, ["cache-status", "AAPL"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "AAPL" in result.output
        assert "2022-06" in result.output
        assert "2022-07" in result.output

    def test_cache_status_unknown_ticker(self, tmp_path):
        """Cache status for an unknown ticker says no data."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["cache-status", "ZZZZ"])
        assert result.exit_code == 0
        assert "no cached data" in result.output.lower()


# ---------------------------------------------------------------------------
# jobs commands
# ---------------------------------------------------------------------------


class TestJobsCommands:
    def test_jobs_list_empty(self, tmp_path):
        """Jobs list with no jobs."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["jobs", "list"])
        assert result.exit_code == 0
        assert "no fetch jobs" in result.output.lower()

    def test_jobs_list_shows_jobs(self, tmp_path):
        """Jobs list shows jobs created by pull."""
        _init_db_sync(tmp_path)

        # Seed a job row
        async def _seed():
            sf = get_session_factory()
            async with sf() as session:
                session.add(FetchJob(
                    id="test-job-001",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    tickers=json.dumps(["AAPL", "MSFT"]),
                    from_date="2022-06-01",
                    to_date="2022-06-30",
                    timespan="1min",
                    status="completed",
                    total_tickers=2,
                    completed_tickers=2,
                ))
                await session.commit()

        asyncio.run(_seed())

        result = runner.invoke(app, ["jobs", "list"])
        assert result.exit_code == 0
        assert "test-job-001" in result.output
        assert "completed" in result.output.lower()

    def test_jobs_status_found(self, tmp_path):
        """Jobs status shows details for a specific job."""
        _init_db_sync(tmp_path)

        async def _seed():
            sf = get_session_factory()
            async with sf() as session:
                session.add(FetchJob(
                    id="detail-job-001",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    tickers=json.dumps(["AAPL", "MSFT", "GOOG"]),
                    from_date="2022-06-01",
                    to_date="2022-06-30",
                    timespan="1min",
                    status="paused",
                    total_tickers=3,
                    completed_tickers=1,
                    current_ticker="MSFT",
                ))
                await session.commit()

        asyncio.run(_seed())

        result = runner.invoke(app, ["jobs", "status", "detail-job-001"])
        assert result.exit_code == 0
        assert "detail-job-001" in result.output
        assert "paused" in result.output.lower()
        assert "AAPL" in result.output
        assert "MSFT" in result.output

    def test_jobs_status_not_found(self, tmp_path):
        """Jobs status for nonexistent job gives error."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["jobs", "status", "no-such-job"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_jobs_resume_not_found(self, tmp_path):
        """Resume nonexistent job gives error."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["jobs", "resume", "no-such-job"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_jobs_resume_wrong_status(self, tmp_path):
        """Resume a completed job gives error."""
        _init_db_sync(tmp_path)

        async def _seed():
            sf = get_session_factory()
            async with sf() as session:
                session.add(FetchJob(
                    id="done-job-001",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    tickers=json.dumps(["AAPL"]),
                    from_date="2022-06-01",
                    to_date="2022-06-30",
                    timespan="1min",
                    status="completed",
                    total_tickers=1,
                    completed_tickers=1,
                ))
                await session.commit()

        asyncio.run(_seed())

        result = runner.invoke(app, ["jobs", "resume", "done-job-001"])
        assert result.exit_code != 0
        assert "paused or failed" in result.output.lower()


# ---------------------------------------------------------------------------
# No args shows help
# ---------------------------------------------------------------------------


class TestIndicesSubcommands:
    """Tests for the indices list/create/refresh subcommands."""

    def test_indices_list_shows_table(self, tmp_path):
        """indices list shows a table with all built-in index names."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["indices", "list"])
        assert result.exit_code == 0, f"Output: {result.output}"
        output = result.output
        # All 5 built-in indices should appear
        for name in ["DOW30", "SP100", "SP500", "NDX100", "RUT2000"]:
            assert name in output, f"{name} not found in output: {output}"

    def test_indices_create_success(self, tmp_path):
        """indices create makes a custom list and shows success."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["indices", "create", "my-test-list", "AAPL,MSFT,GOOG"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "Created custom list" in result.output
        assert "3 tickers" in result.output

    def test_indices_create_empty_tickers(self, tmp_path):
        """indices create with empty tickers should fail."""
        _init_db_sync(tmp_path)
        result = runner.invoke(app, ["indices", "create", "empty-list", ""])
        assert result.exit_code != 0

    def test_indices_list_includes_custom(self, tmp_path):
        """After creating a custom list, indices list includes it."""
        _init_db_sync(tmp_path)
        # Create first
        runner.invoke(app, ["indices", "create", "my-watchlist", "TSLA,NVDA"])
        # Then list
        result = runner.invoke(app, ["indices", "list"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "my-watchlist" in result.output


# ---------------------------------------------------------------------------
# No args shows help
# ---------------------------------------------------------------------------


class TestHelpOutput:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # Typer with no_args_is_help=True exits with code 0 or 2 depending
        # on Click version; either is acceptable as long as help is shown.
        assert result.exit_code in (0, 2)
        output_lower = result.output.lower()
        assert "pull" in output_lower
        assert "cache-status" in output_lower
        assert "jobs" in output_lower
