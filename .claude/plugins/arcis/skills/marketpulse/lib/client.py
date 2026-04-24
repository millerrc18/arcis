"""Polygon.io REST API client with rate limiting, retry, and month chunking.

Provides async methods to fetch aggregated bar data and ticker reference
information from the Polygon.io API.  All HTTP requests are rate-limited
via ``pyrate-limiter`` and retried on transient failures (429 / 5xx) with
exponential backoff + jitter.

Usage::

    async with PolygonClient(api_key="...") as client:
        bars = await client.get_bars_chunked("AAPL", "minute", 1,
                                             date(2022, 1, 1),
                                             date(2022, 6, 30))
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Self

import httpx
from pyrate_limiter import Duration, Limiter, Rate

from .storage import compute_year_months

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"

# Maximum number of retry attempts on transient errors.
MAX_RETRIES = 5
BASE_DELAY = 1.0
MAX_DELAY = 60.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """A single OHLCV bar from Polygon aggregates."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    num_transactions: int


@dataclass
class TickerInfo:
    """Reference information for a stock ticker."""

    symbol: str
    name: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    sic_code: str | None = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PolygonAPIError(Exception):
    """Raised on non-retryable API errors (400, 401, 403, 404)."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Polygon API error {status_code}: {message}")


class PolygonRateLimitError(PolygonAPIError):
    """Raised when retries are exhausted after repeated 429 responses."""

    def __init__(self, message: str = "Rate limit retries exhausted") -> None:
        super().__init__(429, message)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class PolygonClient:
    """Async Polygon.io REST client with rate limiting and retry.

    Parameters
    ----------
    api_key:
        Polygon.io API key.
    rate_limit:
        Maximum requests per second.  Falls back to the
        ``MARKETPULSE_RATE_LIMIT`` environment variable, then 50.
    """

    def __init__(
        self,
        api_key: str,
        rate_limit: int | None = None,
    ) -> None:
        self.api_key = api_key

        if rate_limit is None:
            rate_limit = int(os.environ.get("MARKETPULSE_RATE_LIMIT", "50"))
        self.rate_limit = rate_limit

        self._limiter = Limiter(Rate(rate_limit, Duration.SECOND))
        self._http: httpx.AsyncClient | None = None

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> Self:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            params={"apiKey": self.api_key},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- internal helpers ----------------------------------------------------

    def _acquire_rate_limit(self) -> None:
        """Block until a rate-limit token is available (sync -- fast)."""
        self._limiter.try_acquire("polygon")

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:  # noqa: ANN003
        """Make an HTTP request with rate limiting and retry."""
        if self._http is None:
            raise RuntimeError(
                "PolygonClient must be used as an async context manager"
            )

        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            self._acquire_rate_limit()

            resp = await self._http.request(method, path, **kwargs)

            # Success
            if resp.status_code == 200:
                return resp

            # Non-retryable client errors
            if resp.status_code in (400, 401, 403, 404):
                body = resp.text
                raise PolygonAPIError(resp.status_code, body)

            # Retryable: 429 or 5xx
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = PolygonAPIError(resp.status_code, resp.text)

                if attempt < MAX_RETRIES:
                    # Calculate delay
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after is not None:
                            delay = float(retry_after)
                        else:
                            delay = min(
                                BASE_DELAY * (2 ** attempt) + random.random(),
                                MAX_DELAY,
                            )
                    else:
                        delay = min(
                            BASE_DELAY * (2 ** attempt) + random.random(),
                            MAX_DELAY,
                        )

                    logger.warning(
                        "Polygon API %s on %s (attempt %d/%d), "
                        "retrying in %.1fs",
                        resp.status_code,
                        path,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )

                    import asyncio
                    await asyncio.sleep(delay)
                    continue

                # Retries exhausted
                if resp.status_code == 429:
                    raise PolygonRateLimitError()
                raise last_exc

            # Unexpected status code -- treat as non-retryable
            raise PolygonAPIError(resp.status_code, resp.text)

        # Should not reach here, but just in case
        raise last_exc or RuntimeError("Unexpected retry loop exit")  # pragma: no cover

    # -- public API ----------------------------------------------------------

    async def get_bars(
        self,
        ticker: str,
        timespan: str,
        multiplier: int,
        from_date: date,
        to_date: date,
    ) -> list[Bar]:
        """Fetch aggregated bars for a single date range.

        Parameters
        ----------
        ticker:
            Stock symbol (e.g. ``"AAPL"``).
        timespan:
            Size of the time window: ``minute``, ``hour``, ``day``, etc.
        multiplier:
            Multiplier for ``timespan`` (e.g. 1 for 1-minute bars).
        from_date, to_date:
            Inclusive date range (ISO format strings sent to Polygon).

        Returns
        -------
        list[Bar]
            Parsed bar data.  Empty list for non-trading days.
        """
        path = (
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}"
            f"/{from_date.isoformat()}/{to_date.isoformat()}"
        )
        resp = await self._request(
            "GET",
            path,
            params={"adjusted": "true", "sort": "asc", "limit": "50000"},
        )
        data = resp.json()

        results = data.get("results")
        if not results:
            return []

        bars: list[Bar] = []
        for r in results:
            bars.append(
                Bar(
                    timestamp=datetime.fromtimestamp(
                        r["t"] / 1000.0, tz=timezone.utc
                    ),
                    open=float(r["o"]),
                    high=float(r["h"]),
                    low=float(r["l"]),
                    close=float(r["c"]),
                    volume=float(r["v"]),
                    vwap=float(r["vw"]),
                    num_transactions=int(r["n"]),
                )
            )
        return bars

    async def get_bars_chunked(
        self,
        ticker: str,
        timespan: str,
        multiplier: int,
        from_date: date,
        to_date: date,
    ) -> list[Bar]:
        """Fetch bars by chunking the date range into calendar months.

        This is the primary entry point for fetching bar data.  Callers
        do not need to worry about date-range chunking.

        Parameters
        ----------
        ticker, timespan, multiplier:
            Same as :meth:`get_bars`.
        from_date, to_date:
            The full date range to fetch.

        Returns
        -------
        list[Bar]
            Concatenated bars from all monthly chunks.
        """
        year_months = compute_year_months(from_date, to_date)
        all_bars: list[Bar] = []

        for ym in year_months:
            year, month = int(ym[:4]), int(ym[5:7])

            # Chunk start: max(from_date, first-of-month)
            chunk_start = date(year, month, 1)
            if chunk_start < from_date:
                chunk_start = from_date

            # Chunk end: min(to_date, last-of-month)
            if month == 12:
                next_month_first = date(year + 1, 1, 1)
            else:
                next_month_first = date(year, month + 1, 1)
            chunk_end = date(
                next_month_first.year,
                next_month_first.month,
                next_month_first.day,
            )
            # last day of month
            from datetime import timedelta
            chunk_end = chunk_end - timedelta(days=1)
            if chunk_end > to_date:
                chunk_end = to_date

            chunk_bars = await self.get_bars(
                ticker, timespan, multiplier, chunk_start, chunk_end
            )
            all_bars.extend(chunk_bars)

        return all_bars

    async def get_ticker_details(self, ticker: str) -> TickerInfo:
        """Fetch reference data for a single ticker.

        Parameters
        ----------
        ticker:
            Stock symbol.

        Returns
        -------
        TickerInfo
        """
        resp = await self._request("GET", f"/v3/reference/tickers/{ticker}")
        data = resp.json()
        result = data.get("results", {})

        return TickerInfo(
            symbol=result.get("ticker", ticker),
            name=result.get("name", ""),
            sector=result.get("sector"),
            industry=result.get("industry"),
            market_cap=result.get("market_cap"),
            sic_code=result.get("sic_code"),
        )

    async def search_tickers(
        self, query: str, limit: int = 20
    ) -> list[TickerInfo]:
        """Search for tickers by name or symbol prefix.

        Parameters
        ----------
        query:
            Search string.
        limit:
            Maximum number of results.

        Returns
        -------
        list[TickerInfo]
        """
        resp = await self._request(
            "GET",
            "/v3/reference/tickers",
            params={"search": query, "active": "true", "limit": str(limit)},
        )
        data = resp.json()
        results = data.get("results", [])

        return [
            TickerInfo(
                symbol=r.get("ticker", ""),
                name=r.get("name", ""),
                sector=r.get("sector"),
                industry=r.get("industry"),
                market_cap=r.get("market_cap"),
                sic_code=r.get("sic_code"),
            )
            for r in results
        ]
