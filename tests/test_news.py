"""Tests for news enrichment module."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


def test_format_news_summary_with_data():
    from src.data_enrichment.news import format_news_summary

    data = {
        "headline_count": 3,
        "headlines": [
            {"headline": "NVIDIA Reports Record Revenue", "source": "Reuters", "datetime": "2026-03-20T14:30:00"},
            {"headline": "AI Chip Demand Drives Growth", "source": "Bloomberg", "datetime": "2026-03-19T10:00:00"},
            {"headline": "NVDA Price Target Raised", "source": "MarketWatch", "datetime": "2026-03-18T09:00:00"},
        ],
        "summary": "3 articles. Sentiment: positive.",
        "news_sentiment": "positive",
        "last_news_date": "2026-03-20",
    }

    result = format_news_summary(data)
    assert "3 articles" in result
    assert "Positive" in result
    assert "NVIDIA Reports Record Revenue" in result
    assert "Reuters" in result


def test_format_news_summary_none():
    from src.data_enrichment.news import format_news_summary
    assert format_news_summary(None) == "No recent news"


def test_format_news_summary_empty():
    from src.data_enrichment.news import format_news_summary
    data = {"headline_count": 0, "headlines": [], "news_sentiment": "no_news"}
    assert format_news_summary(data) == "No recent news"


def test_format_news_summary_limits_to_3():
    from src.data_enrichment.news import format_news_summary

    data = {
        "headline_count": 5,
        "headlines": [
            {"headline": f"Headline {i}", "source": "Source", "datetime": f"2026-03-{20-i}T10:00:00"}
            for i in range(5)
        ],
        "news_sentiment": "neutral",
    }

    result = format_news_summary(data)
    # Should only have 3 headlines in output
    assert result.count(' - "Headline') == 3


def test_sentiment_classification():
    from src.data_enrichment.news import _classify_sentiment

    # Positive
    label, pos, neg, neu = _classify_sentiment([
        {"headline": "Record revenue beats expectations"},
        {"headline": "Analyst upgrade surge"},
        {"headline": "Standard quarterly update"},
    ])
    assert label == "positive"
    assert pos == 2

    # Negative
    label, pos, neg, neu = _classify_sentiment([
        {"headline": "Company cuts guidance"},
        {"headline": "Layoffs announced decline"},
    ])
    assert label == "negative"

    # No news
    label, _, _, _ = _classify_sentiment([])
    assert label == "no_news"


def test_historical_news_date_bounds():
    """Historical news should only return articles before as_of_date.

    fetch_historical_news checks an on-disk cache before falling through to
    the no-API-key guard. A stale cache file from a prior run would return
    data even without an API key, masking the behavior we want to verify.
    Patch _load_cached to None and strip any FINNHUB_API_KEY from the env
    so we genuinely exercise the "no API key → None" branch.
    """
    import os
    from src.data_enrichment.news import fetch_historical_news

    with patch("src.data_enrichment.news._load_cached", return_value=None), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FINNHUB_API_KEY", None)
        result = fetch_historical_news("AAPL", "2026-01-15")
    assert result is None


@patch("src.data_enrichment.news.requests.get")
def test_fetch_recent_news_api_failure(mock_get):
    import requests as req_lib
    from src.data_enrichment.news import fetch_recent_news

    mock_get.side_effect = req_lib.RequestException("Connection error")
    result = fetch_recent_news("AAPL", finnhub_api_key="test_key", cache_hours=0)
    assert result is None


@patch("src.data_enrichment.news.requests.get")
def test_fetch_recent_news_empty_response(mock_get):
    from src.data_enrichment.news import fetch_recent_news

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = fetch_recent_news("AAPL", finnhub_api_key="test_key", cache_hours=0)
    assert result is not None
    assert result["headline_count"] == 0
    assert result["news_sentiment"] == "no_news"


@patch("src.data_enrichment.news.requests.get")
def test_fetch_news_sentiment_success(mock_get):
    from src.data_enrichment.news import fetch_news_sentiment

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "companyNewsScore": 0.74,
        "sectorAverageNewsScore": 0.51,
        "sectorAverageBullishPercent": 0.42,
        "buzz": {"articlesInLastWeek": 12},
        "sentiment": {"bullishPercent": 0.71, "bearishPercent": 0.09},
    }
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = fetch_news_sentiment("AAPL", finnhub_api_key="test_key", cache_hours=0)
    assert result is not None
    assert result["news_sentiment"] == "positive"
    assert result["articles_in_last_week"] == 12
    assert "Finnhub sentiment: positive" in result["summary"]


@patch("src.data_enrichment.news.requests.get")
def test_fetch_news_sentiment_handles_403(mock_get):
    from src.data_enrichment.news import fetch_news_sentiment

    warnings = []
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_get.return_value = mock_resp

    result = fetch_news_sentiment(
        "AAPL",
        finnhub_api_key="test_key",
        cache_hours=0,
        warnings=warnings,
    )
    assert result is None
    assert warnings == ["news_sentiment_unavailable:AAPL:runtime"]
