"""Tests for academic API module — Semantic Scholar, OpenAlex, arXiv, PubMed."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from server.apis.academic import (
    search_academic,
    _search_semantic_scholar,
    _search_openalex,
    resolve_doi,
)


class TestSemanticScholar:
    @pytest.mark.asyncio
    async def test_successful_search(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "total": 100,
            "data": [
                {
                    "paperId": "abc123",
                    "title": "Test Paper on Machine Learning",
                    "url": "https://www.semanticscholar.org/paper/abc123",
                    "abstract": "This paper presents a novel approach...",
                    "year": 2024,
                    "citationCount": 42,
                    "authors": [{"name": "John Doe"}],
                    "venue": "NeurIPS",
                    "externalIds": {"DOI": "10.1234/test"},
                    "tldr": {"text": "A novel ML approach"},
                },
            ],
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.academic.httpx.AsyncClient", return_value=mock_client):
            result = await _search_semantic_scholar("machine learning")

        assert result is not None
        assert result["api_used"] == "semantic_scholar"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Test Paper on Machine Learning"
        assert result["results"][0]["citation_count"] == 42
        assert result["results"][0]["source_type"] == "academic"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"total": 0, "data": []}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("server.apis.academic.httpx.AsyncClient", return_value=mock_client):
            result = await _search_semantic_scholar("nonexistent topic xyz123")

        assert result is not None
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("server.apis.academic.httpx.AsyncClient", return_value=mock_client):
            result = await _search_semantic_scholar("test")

        assert result is None


class TestOpenAlex:
    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))

        with patch("server.apis.academic.httpx.AsyncClient", return_value=mock_client):
            result = await _search_openalex("test")

        assert result is None


class TestAcademicFallbackChain:
    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        with patch("server.apis.academic._search_semantic_scholar", return_value=None):
            with patch("server.apis.academic._search_openalex", return_value=None):
                with patch("server.apis.academic._search_arxiv", return_value=None):
                    with patch("server.apis.academic._search_pubmed", return_value=None):
                        result = await search_academic("test")
                        assert result["results"] == []
                        assert "error" in result

    @pytest.mark.asyncio
    async def test_first_succeeds(self):
        ss_result = {
            "results": [{"title": "Paper", "url": "https://s2.com/p/1", "snippet": "abs"}],
            "total_count": 1,
            "api_used": "semantic_scholar",
        }
        with patch("server.apis.academic._search_semantic_scholar", return_value=ss_result):
            with patch("server.apis.academic._search_openalex") as mock_oa:
                result = await search_academic("test")
                assert result["api_used"] == "semantic_scholar"
                mock_oa.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_openalex(self):
        oa_result = {
            "results": [{"title": "OA Paper", "url": "https://oa.org/1"}],
            "total_count": 1,
            "api_used": "openalex",
        }
        with patch("server.apis.academic._search_semantic_scholar", return_value=None):
            with patch("server.apis.academic._search_openalex", return_value=oa_result):
                result = await search_academic("test")
                assert result["api_used"] == "openalex"


class TestResolveDoi:
    @pytest.mark.asyncio
    async def test_successful_resolve(self):
        cr_response = MagicMock()
        cr_response.status_code = 200
        cr_response.raise_for_status = MagicMock()
        cr_response.json.return_value = {
            "message": {
                "title": ["Test Paper"],
                "author": [{"given": "J", "family": "Doe"}],
                "container-title": ["Nature"],
                "published-print": {"date-parts": [[2024, 1, 15]]},
                "is-referenced-by-count": 50,
                "URL": "https://doi.org/10.1234/test",
            }
        }

        up_response = MagicMock()
        up_response.status_code = 200
        up_response.raise_for_status = MagicMock()
        up_response.json.return_value = {
            "best_oa_location": {"url_for_pdf": "https://arxiv.org/pdf/2024.12345"}
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Return different responses for different URLs
        async def mock_get(url, **kwargs):
            if "crossref" in url:
                return cr_response
            elif "unpaywall" in url:
                return up_response
            return MagicMock()

        mock_client.get = mock_get

        with patch("server.apis.academic.httpx.AsyncClient", return_value=mock_client):
            result = await resolve_doi("10.1234/test")

        assert "metadata" in result
        assert result["open_access_url"] == "https://arxiv.org/pdf/2024.12345"
