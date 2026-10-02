"""T5: the Alpaca news client — schema, pagination, chunking, retries,
typed errors, rate limits, and Date header capture."""
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from arcis.recorder.client import (
    AlpacaNewsClient,
    Article,
    NewsPage,
    chunked,
)
from arcis.recorder.config import Config
from arcis.recorder.errors import AuthError, ClientError, RateLimitError

REPO = Path(__file__).resolve().parent.parent
BASE_URL = "https://paper-api.alpaca.markets"


def make_config(**overrides) -> Config:
    doc = {
        "data_root": "/tmp/arcis-test-data",
        "alpaca_base_url": BASE_URL,
        "alpaca_api_key": "k",
        "alpaca_api_secret": "s",
        "universe_name": "sp500",
        "universe_source": "test",
        "symbols": ["AAPL"],
        "rate_limit": {"max_requests_per_minute": 200, "max_requests_per_day": 50000},
        "retry": {"max_attempts": 3, "base_delay_seconds": 0.01, "max_delay_seconds": 0.05},
    }
    doc.update(overrides)
    return Config(**doc)


def article_dict(**overrides) -> dict:
    d = {
        "id": 1,
        "headline": "h",
        "summary": "s",
        "content": None,
        "author": "a",
        "created_at": "2026-10-02T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "url": "https://example.com",
        "source": "TestWire",
        "symbols": ["AAPL"],
        "images": [{"size": "large", "url": "https://example.com/i.jpg"}],
    }
    d.update(overrides)
    return d


def page_dict(articles, token=None) -> dict:
    return {"news": articles, "next_page_token": token}


START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 2, tzinfo=UTC)


# --- schema ---


def test_article_parses_t1_fixture():
    raw = json.loads((REPO / "tests/fixtures/news_page_1.json").read_text())
    page = NewsPage(**raw)
    assert len(page.news) == 3
    assert page.next_page_token is None
    assert all(isinstance(a.id, int) for a in page.news)


def test_article_allows_null_content_and_ignores_unknown_fields():
    a = Article(**article_dict(content=None, future_field="x"))
    assert a.content is None
    assert not hasattr(a, "future_field")


def test_article_defaults_symbols_and_images():
    d = article_dict()
    del d["symbols"]
    del d["images"]
    a = Article(**d)
    assert a.symbols == [] and a.images == []


def test_chunked():
    assert list(chunked([str(i) for i in range(120)], 50)) == [
        [str(i) for i in range(50)],
        [str(i) for i in range(50, 100)],
        [str(i) for i in range(100, 120)],
    ]


# --- behavior (respx) ---


@respx.mock
def test_pagination_follows_next_page_token():
    route = respx.get(f"{BASE_URL}/v1beta1/news").mock(
        side_effect=[
            httpx.Response(200, json=page_dict([article_dict(id=1)], token="tok")),
            httpx.Response(200, json=page_dict([article_dict(id=2)])),
        ]
    )
    client = AlpacaNewsClient(make_config())
    try:
        articles = list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()
    assert [f.article.id for f in articles] == [1, 2]
    assert route.call_count == 2
    assert "page_token=tok" in str(route.calls[1].request.url)


@respx.mock
def test_symbols_chunked_at_50():
    route = respx.get(f"{BASE_URL}/v1beta1/news").mock(
        httpx.Response(200, json=page_dict([]))
    )
    client = AlpacaNewsClient(make_config())
    try:
        list(client.fetch_news([f"S{i}" for i in range(120)], START, END))
    finally:
        client.close()
    assert route.call_count == 3
    counts = []
    for c in route.calls:
        query = str(c.request.url).split("symbols=")[1].split("&")[0]
        counts.append(len(query.split("%2C")))
    assert counts == [50, 50, 20]


@respx.mock
def test_retry_then_success_on_429():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=page_dict([article_dict(id=7)])),
        ]
    )
    client = AlpacaNewsClient(make_config())
    try:
        with patch("arcis.recorder.client.time.sleep"):
            articles = list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()
    assert [f.article.id for f in articles] == [7]


@respx.mock
def test_auth_error_on_401():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(httpx.Response(401, text="unauthorized"))
    client = AlpacaNewsClient(make_config())
    try:
        with pytest.raises(AuthError):
            list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()


@respx.mock
def test_rate_limit_error_after_retries():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(httpx.Response(429, text="slow down"))
    client = AlpacaNewsClient(make_config())
    try:
        with (
            patch("arcis.recorder.client.time.sleep"),
            pytest.raises(RateLimitError),
        ):
            list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()


@respx.mock
def test_client_error_on_500_after_retries():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(httpx.Response(500, text="boom"))
    client = AlpacaNewsClient(make_config())
    try:
        with (
            patch("arcis.recorder.client.time.sleep"),
            pytest.raises(ClientError),
        ):
            list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()


@respx.mock
def test_client_error_on_unexpected_status():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(httpx.Response(418, text="teapot"))
    client = AlpacaNewsClient(make_config())
    try:
        with pytest.raises(ClientError):
            list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()


@respx.mock
def test_date_header_captured():
    respx.get(f"{BASE_URL}/v1beta1/news").mock(
        httpx.Response(200, json=page_dict([]), headers={"Date": "Thu, 02 Oct 2026 12:00:00 GMT"})
    )
    client = AlpacaNewsClient(make_config())
    try:
        list(client.fetch_news(["AAPL"], START, END))
    finally:
        client.close()
    assert client.last_server_date == "Thu, 02 Oct 2026 12:00:00 GMT"


@respx.mock
def test_per_minute_limit_triggers_sleep_between_requests():
    calls = [
        httpx.Response(200, json=page_dict([article_dict(id=1)], token="t")),
        httpx.Response(200, json=page_dict([article_dict(id=2)])),
    ]
    respx.get(f"{BASE_URL}/v1beta1/news").mock(side_effect=calls)
    config = make_config(rate_limit={"max_requests_per_minute": 1, "max_requests_per_day": 50000})
    client = AlpacaNewsClient(config)
    try:
        with patch("arcis.recorder.client.time.sleep") as asleep:
            list(client.fetch_news(["AAPL"], START, END))
        assert asleep.call_count >= 1
    finally:
        client.close()


def test_unparseable_page_raises_client_error():
    with respx.mock:
        respx.get(f"{BASE_URL}/v1beta1/news").mock(httpx.Response(200, text="not json"))
        client = AlpacaNewsClient(make_config())
        try:
            with pytest.raises(ClientError, match="unparseable"):
                list(client.fetch_news(["AAPL"], START, END))
        finally:
            client.close()
