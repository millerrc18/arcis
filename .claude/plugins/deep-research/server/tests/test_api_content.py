"""Tests for content extraction API module — fallback chain, response parsing."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from server.apis.content import (
    read_url,
    _read_firecrawl,
    _read_jina,
    _read_trafilatura,
    _read_raw_http,
)


class TestFirecrawl:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await _read_firecrawl("https://example.com")
            assert result is None

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "markdown": "# Test Content\n\nSome text here.",
                "metadata": {"title": "Test Page", "description": "A test"},
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"FIRECRAWL_API_KEY": "test-key"}):
            with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
                result = await _read_firecrawl("https://example.com")

        assert result is not None
        assert result["api_used"] == "firecrawl"
        assert "Test Content" in result["content"]
        assert result["title"] == "Test Page"

    @pytest.mark.asyncio
    async def test_content_truncation(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "markdown": "x" * 10000,
                "metadata": {},
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"FIRECRAWL_API_KEY": "key"}):
            with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
                result = await _read_firecrawl("https://example.com", max_length=100)

        assert len(result["content"]) == 100
        assert result["truncated"] is True


class TestJina:
    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "# Extracted Content\n\nSome long article text here that is useful."

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
            result = await _read_jina("https://example.com")

        assert result is not None
        assert result["api_used"] == "jina"
        assert "Extracted Content" in result["content"]

    @pytest.mark.asyncio
    async def test_short_content_returns_none(self):
        """Content shorter than 50 chars should be rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "tiny"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
            result = await _read_jina("https://example.com")

        assert result is None


class TestRawHttp:
    @pytest.mark.asyncio
    async def test_strips_html_tags(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "<html><head><title>Test</title></head><body><p>This is a paragraph with enough content to pass the length check easily.</p></body></html>"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
            result = await _read_raw_http("https://example.com")

        assert result is not None
        assert "<p>" not in result["content"]
        assert "paragraph" in result["content"]

    @pytest.mark.asyncio
    async def test_strips_script_tags(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = '<html><body><script>alert("xss")</script><p>Real content here that is long enough to pass validation checks.</p></body></html>'

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.content.httpx.AsyncClient", return_value=mock_client):
            result = await _read_raw_http("https://example.com")

        assert "alert" not in result["content"]


class TestReadUrlFallback:
    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        with patch("server.apis.content._read_firecrawl", return_value=None):
            with patch("server.apis.content._read_jina", return_value=None):
                with patch("server.apis.content._read_trafilatura", return_value=None):
                    with patch("server.apis.content._read_raw_http", return_value=None):
                        result = await read_url("https://example.com")
                        assert result["content"] == ""
                        assert "error" in result

    @pytest.mark.asyncio
    async def test_fallback_to_jina(self):
        jina_result = {
            "content": "Jina content that is long enough to pass",
            "title": "",
            "description": "",
            "full_length": 42,
            "truncated": False,
            "api_used": "jina",
        }
        with patch("server.apis.content._read_firecrawl", return_value=None):
            with patch("server.apis.content._read_jina", return_value=jina_result):
                result = await read_url("https://example.com")
                assert result["api_used"] == "jina"

    @pytest.mark.asyncio
    async def test_start_index_offset(self):
        firecrawl_result = {
            "content": "0123456789ABCDEFGHIJ",
            "title": "T",
            "description": "",
            "full_length": 20,
            "truncated": False,
            "api_used": "firecrawl",
        }
        with patch("server.apis.content._read_firecrawl", return_value=firecrawl_result):
            result = await read_url("https://example.com", max_length=5, start_index=10)
            assert result["content"] == "ABCDE"
            assert result["start_index"] == 10
