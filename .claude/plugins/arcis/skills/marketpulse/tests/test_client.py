"""Tests for the Polygon.io API client (lib.client).

Uses plain asyncio.run() for async tests to avoid pytest-asyncio version
quirks.  Imports client.py via sys.path manipulation so we don't need
__init__.py files all the way up the tree.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Make ``lib.client`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.client import (  # noqa: E402
    Bar,
    PolygonAPIError,
    PolygonClient,
    PolygonRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "polygon_responses"


def _load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / name) as f:
        return json.load(f)


def _make_response(status_code: int = 200, json_data: dict | None = None,
                   headers: dict | None = None, text: str = "") -> httpx.Response:
    """Build a fake httpx.Response."""
    if json_data is not None:
        content = json.dumps(json_data).encode()
    else:
        content = text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
    )


def _client() -> PolygonClient:
    """Create a PolygonClient with mocked internals ready for testing."""
    c = PolygonClient(api_key="test-key", rate_limit=100)
    c._http = AsyncMock(spec=httpx.AsyncClient)
    c._limiter = MagicMock()
    return c


# ---------------------------------------------------------------------------
# get_bars -- happy path
# ---------------------------------------------------------------------------


def test_get_bars_parses_fixture():
    """get_bars() should parse the fixture JSON into Bar objects with correct
    field mapping and UTC timestamp conversion."""
    fixture = _load_fixture("aggs_aapl_2022_01_03.json")
    response = _make_response(json_data=fixture)

    client = _client()
    client._http.request = AsyncMock(return_value=response)

    async def _run():
        return await client.get_bars("AAPL", "minute", 1,
                                     date(2022, 1, 3), date(2022, 1, 3))

    bars = asyncio.run(_run())

    assert len(bars) == 10

    # Check the first bar in detail
    first = bars[0]
    assert isinstance(first, Bar)
    assert first.timestamp == datetime.fromtimestamp(
        1641220200000 / 1000.0, tz=timezone.utc
    )
    assert first.timestamp.tzinfo == timezone.utc
    assert first.open == 182.63
    assert first.high == 182.88
    assert first.low == 182.01
    assert first.close == 182.21
    assert first.volume == 2345678.0
    assert first.vwap == 182.0123
    assert first.num_transactions == 15432

    # Check the last bar
    last = bars[-1]
    assert last.timestamp == datetime.fromtimestamp(
        1641220740000 / 1000.0, tz=timezone.utc
    )
    assert last.close == 182.44


# ---------------------------------------------------------------------------
# get_bars -- empty results (non-trading day)
# ---------------------------------------------------------------------------


def test_get_bars_empty_results():
    """get_bars() should return an empty list when results are absent."""
    response = _make_response(json_data={
        "ticker": "AAPL",
        "queryCount": 0,
        "resultsCount": 0,
        "adjusted": True,
        "results": [],
        "status": "OK",
        "request_id": "empty_test",
    })

    client = _client()
    client._http.request = AsyncMock(return_value=response)

    async def _run():
        return await client.get_bars("AAPL", "minute", 1,
                                     date(2022, 1, 1), date(2022, 1, 1))

    bars = asyncio.run(_run())
    assert bars == []


def test_get_bars_no_results_key():
    """get_bars() should return empty list when 'results' key is missing."""
    response = _make_response(json_data={
        "ticker": "AAPL",
        "status": "OK",
        "request_id": "no_results_key",
    })

    client = _client()
    client._http.request = AsyncMock(return_value=response)

    async def _run():
        return await client.get_bars("AAPL", "minute", 1,
                                     date(2022, 12, 25), date(2022, 12, 25))

    bars = asyncio.run(_run())
    assert bars == []


# ---------------------------------------------------------------------------
# Retry on 429
# ---------------------------------------------------------------------------


def test_retry_on_429():
    """_request should retry on 429 and succeed when the server finally
    returns 200.  Verify that 3 calls are made (429 -> 429 -> 200)."""
    fixture = _load_fixture("aggs_aapl_2022_01_03.json")

    resp_429 = _make_response(status_code=429, text="rate limited")
    resp_200 = _make_response(json_data=fixture)

    client = _client()
    client._http.request = AsyncMock(side_effect=[resp_429, resp_429, resp_200])

    async def _run():
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            bars = await client.get_bars("AAPL", "minute", 1,
                                         date(2022, 1, 3), date(2022, 1, 3))
            return bars, mock_sleep

    bars, mock_sleep = asyncio.run(_run())

    assert len(bars) == 10
    assert client._http.request.call_count == 3
    # asyncio.sleep should have been called twice (once per 429)
    assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# Retry on 500
# ---------------------------------------------------------------------------


def test_retry_on_500():
    """_request should retry on 500 and succeed on subsequent 200."""
    fixture = _load_fixture("aggs_aapl_2022_01_03.json")

    resp_500 = _make_response(status_code=500, text="internal error")
    resp_200 = _make_response(json_data=fixture)

    client = _client()
    client._http.request = AsyncMock(side_effect=[resp_500, resp_200])

    async def _run():
        with patch("asyncio.sleep", new_callable=AsyncMock):
            return await client.get_bars("AAPL", "minute", 1,
                                         date(2022, 1, 3), date(2022, 1, 3))

    bars = asyncio.run(_run())

    assert len(bars) == 10
    assert client._http.request.call_count == 2


# ---------------------------------------------------------------------------
# PolygonAPIError on 401
# ---------------------------------------------------------------------------


def test_401_raises_api_error():
    """A 401 response should raise PolygonAPIError immediately (no retry)."""
    resp_401 = _make_response(status_code=401, text="unauthorized")

    client = _client()
    client._http.request = AsyncMock(return_value=resp_401)

    async def _run():
        await client.get_bars("AAPL", "minute", 1,
                              date(2022, 1, 3), date(2022, 1, 3))

    with pytest.raises(PolygonAPIError) as exc_info:
        asyncio.run(_run())

    assert exc_info.value.status_code == 401
    # Should NOT have retried -- only 1 call
    assert client._http.request.call_count == 1


# ---------------------------------------------------------------------------
# get_bars_chunked -- multi-month chunking
# ---------------------------------------------------------------------------


def test_get_bars_chunked_multi_month():
    """get_bars_chunked() should call get_bars() once per month chunk."""
    client = _client()

    call_count = 0

    async def fake_get_bars(ticker, timespan, multiplier, from_date, to_date):
        nonlocal call_count
        call_count += 1
        return [
            Bar(
                timestamp=datetime(from_date.year, from_date.month, 1,
                                   tzinfo=timezone.utc),
                open=100.0, high=101.0, low=99.0, close=100.5,
                volume=1000.0, vwap=100.2, num_transactions=50,
            )
        ]

    client.get_bars = fake_get_bars  # type: ignore[assignment]

    async def _run():
        return await client.get_bars_chunked(
            "AAPL", "minute", 1,
            date(2022, 1, 15), date(2022, 4, 10),
        )

    bars = asyncio.run(_run())

    # Jan, Feb, Mar, Apr => 4 month chunks => 4 calls
    assert call_count == 4
    assert len(bars) == 4


def test_get_bars_chunked_single_month():
    """get_bars_chunked() with a range inside a single month makes 1 call."""
    client = _client()

    call_count = 0

    async def fake_get_bars(ticker, timespan, multiplier, from_date, to_date):
        nonlocal call_count
        call_count += 1
        return []

    client.get_bars = fake_get_bars  # type: ignore[assignment]

    async def _run():
        return await client.get_bars_chunked(
            "AAPL", "minute", 1,
            date(2022, 3, 5), date(2022, 3, 25),
        )

    bars = asyncio.run(_run())
    assert call_count == 1
    assert bars == []


# ---------------------------------------------------------------------------
# Rate limiter is used
# ---------------------------------------------------------------------------


def test_rate_limiter_is_called():
    """Every _request call should acquire a rate-limit token."""
    fixture = _load_fixture("aggs_aapl_2022_01_03.json")
    response = _make_response(json_data=fixture)

    client = _client()
    client._http.request = AsyncMock(return_value=response)

    async def _run():
        await client.get_bars("AAPL", "minute", 1,
                              date(2022, 1, 3), date(2022, 1, 3))

    asyncio.run(_run())

    # _acquire_rate_limit calls self._limiter.try_acquire("polygon")
    client._limiter.try_acquire.assert_called_with("polygon")
    assert client._limiter.try_acquire.call_count >= 1


# ---------------------------------------------------------------------------
# PolygonRateLimitError when retries exhausted
# ---------------------------------------------------------------------------


def test_429_exhausted_raises_rate_limit_error():
    """When 429 responses exhaust all retries, PolygonRateLimitError is raised."""
    resp_429 = _make_response(status_code=429, text="rate limited")

    client = _client()
    # MAX_RETRIES + 1 = 6 calls, all returning 429
    client._http.request = AsyncMock(return_value=resp_429)

    async def _run():
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await client.get_bars("AAPL", "minute", 1,
                                  date(2022, 1, 3), date(2022, 1, 3))

    with pytest.raises(PolygonRateLimitError):
        asyncio.run(_run())
