"""Tests for search API module — fallback chain, request construction, response parsing."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from server.apis.search import (
    search_web,
    _search_tavily,
    _search_exa,
    _search_serper,
    _search_brave,
)


# ── Tavily ────────────────────────────────────────────────────────────


class TestTavily:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await _search_tavily("test query")
            assert result is None

    @pytest.mark.asyncio
    async def test_successful_search(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://example.com",
                    "content": "Some content here",
                    "score": 0.95,
                    "published_date": "2024-06-15",
                }
            ],
            "answer": "Summary answer",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            with patch("server.apis.search.httpx.AsyncClient", return_value=mock_client):
                result = await _search_tavily("test query")

        assert result is not None
        assert result["api_used"] == "tavily"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Test Result"
        assert result["results"][0]["url"] == "https://example.com"
        assert result["results"][0]["source_type"] == "web"

    @pytest.mark.asyncio
    async def test_rate_limit_returns_none(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            with patch("server.apis.search.httpx.AsyncClient", return_value=mock_client):
                result = await _search_tavily("test query")

        assert result is None

    @pytest.mark.asyncio
    async def test_snippets_detail_level(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [{"title": "T", "url": "https://a.com", "content": "x" * 1000}],
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "key"}):
            with patch("server.apis.search.httpx.AsyncClient", return_value=mock_client):
                result = await _search_tavily("q", detail_level="snippets")

        assert len(result["results"][0]["snippet"]) <= 500


# ── Exa ───────────────────────────────────────────────────────────────


class TestExa:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await _search_exa("test query")
            assert result is None


# ── Serper ────────────────────────────────────────────────────────────


class TestSerper:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await _search_serper("test query")
            assert result is None


# ── Brave ─────────────────────────────────────────────────────────────


class TestBrave:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await _search_brave("test query")
            assert result is None


# ── Fallback Chain ────────────────────────────────────────────────────


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        """When no API keys are set, search_web returns an error dict."""
        with patch.dict("os.environ", {}, clear=True):
            result = await search_web("test query")
            assert result["results"] == []
            assert result["api_used"] == "none"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_first_succeeds(self):
        """When Tavily succeeds, don't try other APIs."""
        tavily_result = {
            "results": [{"title": "T", "url": "https://a.com", "content": "c"}],
            "total_count": 1,
            "api_used": "tavily",
        }

        with patch("server.apis.search._search_tavily", return_value=tavily_result) as mock_tavily:
            with patch("server.apis.search._search_exa") as mock_exa:
                result = await search_web("test")
                assert result["api_used"] == "tavily"
                mock_exa.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_second(self):
        """When Tavily fails, try Exa."""
        exa_result = {
            "results": [{"title": "T", "url": "https://a.com", "text": "c"}],
            "total_count": 1,
            "api_used": "exa",
        }

        with patch("server.apis.search._search_tavily", return_value=None):
            with patch("server.apis.search._search_exa", return_value=exa_result):
                result = await search_web("test")
                assert result["api_used"] == "exa"

    @pytest.mark.asyncio
    async def test_max_results_clamped(self):
        """max_results above 20 should be clamped internally by the tool layer."""
        # This tests the search function's behavior — it should pass through
        # whatever max_results it gets (clamping happens in the MCP tool layer)
        with patch("server.apis.search._search_tavily", return_value=None):
            with patch("server.apis.search._search_exa", return_value=None):
                with patch("server.apis.search._search_serper", return_value=None):
                    with patch("server.apis.search._search_brave", return_value=None):
                        result = await search_web("test", max_results=100)
                        assert result["api_used"] == "none"
