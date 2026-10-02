"""Alpaca news client: chunked, paginated, retried, rate-limited.

- Symbols are chunked at 50 per request.
- next_page_token is followed until exhausted or max_pages.
- 429/5xx and network errors retry with exponential backoff (manual;
  tenacity is not a dependency). Retry-After is honored when present.
- Client-side enforcement of max_requests_per_minute (sliding window) and
  max_requests_per_day from the config.
- Every response's Date header is captured for T8's clock checks.
- Typed errors: AuthError (401/403), RateLimitError (429 after retries),
  ClientError (anything else).
"""
from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Iterator
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from arcis.recorder.config import Config
from arcis.recorder.errors import AuthError, ClientError, RateLimitError

NEWS_PATH = "/v1beta1/news"
CHUNK_SIZE = 50
PAGE_SIZE = 50
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ArticleImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    size: str
    url: str


class Article(BaseModel):
    """Exactly the fields observed in the T1 preflight. Unknown fields are
    ignored so additive vendor changes don't break the recorder; missing
    required fields fail closed."""

    model_config = ConfigDict(extra="ignore")

    id: int
    headline: str
    summary: str
    content: str | None
    author: str
    created_at: str
    updated_at: str
    url: str
    source: str
    symbols: list[str] = []
    images: list[ArticleImage] = []


class NewsPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    news: list[Article]
    next_page_token: str | None = None


def chunked(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class AlpacaNewsClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        # trust_env=False: some environments ship a no_proxy that httpx
        # cannot parse (bracketed IPv6 wildcards); read the proxy explicitly.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        self.client = httpx.Client(
            base_url=str(config.alpaca_base_url),
            headers={
                "APCA-API-KEY-ID": config.alpaca_api_key.get_secret_value(),
                "APCA-API-SECRET-KEY": config.alpaca_api_secret.get_secret_value(),
            },
            timeout=30.0,
            trust_env=False,
            proxy=proxy,
        )
        self.server_dates: list[str] = []
        self._minute_window: deque[float] = deque()
        self._day_count = 0
        self._day: str | None = None

    @property
    def last_server_date(self) -> str | None:
        return self.server_dates[-1] if self.server_dates else None

    def close(self) -> None:
        self.client.close()

    def _enforce_rate_limit(self) -> None:
        now = time.monotonic()
        today = datetime.now().date().isoformat()
        if self._day != today:
            self._day = today
            self._day_count = 0
        if self._day_count >= self.config.rate_limit.max_requests_per_day:
            raise RateLimitError("daily request budget exhausted")
        window = 60.0
        max_per_minute = self.config.rate_limit.max_requests_per_minute
        while self._minute_window and self._minute_window[0] <= now - window:
            self._minute_window.popleft()
        if len(self._minute_window) >= max_per_minute:
            time.sleep(self._minute_window[0] + window - now)
            now = time.monotonic()
            while self._minute_window and self._minute_window[0] <= now - window:
                self._minute_window.popleft()
        self._minute_window.append(now)
        self._day_count += 1

    def _get_page(self, params: dict[str, str]) -> NewsPage:
        retry = self.config.retry
        delay = retry.base_delay_seconds
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(1, retry.max_attempts + 1):
            self._enforce_rate_limit()
            try:
                response = self.client.get(NEWS_PATH, params=params)
            except httpx.TransportError as e:
                last_error, last_status = e, None
            else:
                if date := response.headers.get("date"):
                    self.server_dates.append(date)
                last_status = response.status_code
                if last_status == 200:
                    try:
                        return NewsPage(**response.json())
                    except (ValueError, ValidationError) as e:
                        raise ClientError(f"unparseable news page: {e}") from e
                if last_status in (401, 403):
                    raise AuthError(f"alpaca rejected the credentials (HTTP {last_status})")
                if last_status in RETRYABLE_STATUS:
                    last_error = ClientError(f"HTTP {last_status} from {NEWS_PATH}")
                    if attempt == retry.max_attempts:
                        break
                    retry_after = response.headers.get("retry-after")
                    time.sleep(float(retry_after) if retry_after else delay)
                    delay = min(delay * 2, retry.max_delay_seconds)
                    continue
                raise ClientError(
                    f"unexpected HTTP {last_status} from {NEWS_PATH}: {response.text[:200]}"
                )
            if attempt == retry.max_attempts:
                break
            time.sleep(delay)
            delay = min(delay * 2, retry.max_delay_seconds)
        if last_status == 429:
            raise RateLimitError(f"rate limited after {retry.max_attempts} attempts")
        raise ClientError(f"failed after {retry.max_attempts} attempts: {last_error}")

    def fetch_news(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        max_pages: int = 50,
    ) -> Iterator[Article]:
        """Yield articles for the symbols in [start, end), oldest first."""
        for chunk in chunked(symbols, CHUNK_SIZE):
            params = {
                "symbols": ",".join(chunk),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": str(PAGE_SIZE),
                "sort": "asc",
            }
            page_token: str | None = None
            for _ in range(max_pages):
                if page_token:
                    params["page_token"] = page_token
                elif "page_token" in params:
                    del params["page_token"]
                page = self._get_page(params)
                yield from page.news
                page_token = page.next_page_token
                if not page_token:
                    break
