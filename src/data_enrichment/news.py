"""News data fetcher using Finnhub Company News API.

Called by: data_enrichment/enricher.py, scheduler/premarket.py, scheduler/watch.py, training/historical_scanner.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_news.py

Primary source: Finnhub API (free tier: 60 calls/min, shared with insider fetcher).
Returns headlines and simple sentiment -- NOT full article text.
"""

import logging
import os
import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/news")

# Sentiment keyword lists
POSITIVE_KEYWORDS = {"beat", "record", "surge", "growth", "upgrade", "raises",
                     "outperform", "bullish", "strong", "soars", "rally", "profit"}
NEGATIVE_KEYWORDS = {"miss", "decline", "downgrade", "cuts", "layoffs", "warning",
                     "bearish", "weak", "plunge", "loss", "recall", "investigation"}


def _get_cache_path(ticker: str, as_of_date: str | None = None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{as_of_date}" if as_of_date else ""
    return CACHE_DIR / f"{ticker}_news{suffix}.pkl"


def _load_cached(ticker: str, cache_hours: int = 6, as_of_date: str | None = None) -> dict | None:
    path = _get_cache_path(ticker, as_of_date)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if datetime.now() - data.get("_cached_at", datetime.min) < timedelta(hours=cache_hours):
            return data
    except Exception:
        pass
    return None


def _save_cache(ticker: str, data: dict, as_of_date: str | None = None) -> None:
    data["_cached_at"] = datetime.now()
    path = _get_cache_path(ticker, as_of_date)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _get_sentiment_cache_path(ticker: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{ticker}_news_sentiment.pkl"


def _load_sentiment_cached(ticker: str, cache_hours: int = 6) -> dict | None:
    path = _get_sentiment_cache_path(ticker)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if datetime.now() - data.get("_cached_at", datetime.min) < timedelta(hours=cache_hours):
            return data
    except Exception:
        pass
    return None


def _save_sentiment_cache(ticker: str, data: dict) -> None:
    data["_cached_at"] = datetime.now()
    path = _get_sentiment_cache_path(ticker)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _classify_sentiment(headlines: list[dict]) -> tuple[str, int, int, int]:
    """Classify overall sentiment from headlines. Returns (label, pos, neg, neutral)."""
    pos = 0
    neg = 0
    neutral = 0
    for h in headlines:
        text = h.get("headline", "").lower()
        words = set(text.split())
        has_pos = bool(words & POSITIVE_KEYWORDS)
        has_neg = bool(words & NEGATIVE_KEYWORDS)
        if has_pos and not has_neg:
            pos += 1
        elif has_neg and not has_pos:
            neg += 1
        else:
            neutral += 1

    total = pos + neg + neutral
    if total == 0:
        return "no_news", 0, 0, 0
    if pos > neg and pos > neutral:
        return "positive", pos, neg, neutral
    if neg > pos and neg > neutral:
        return "negative", pos, neg, neutral
    if pos > 0 and neg > 0:
        return "mixed", pos, neg, neutral
    return "neutral", pos, neg, neutral


def fetch_recent_news(ticker: str, lookback_days: int = 7,
                      finnhub_api_key: str | None = None,
                      cache_hours: int = 6,
                      warnings: list[str] | None = None) -> dict | None:
    """Fetch recent news headlines for a ticker from Finnhub.

    Uses Finnhub Company News API (free tier: 60 calls/min).
    Returns only headlines and timestamps — NOT full article text.

    Args:
        ticker: Stock symbol.
        lookback_days: Window length in days.
        finnhub_api_key: Finnhub API key (falls back to FINNHUB_API_KEY env).
        cache_hours: Cache TTL.
        warnings: Optional list to collect coverage/PIT warnings (#99).
            Mutated in place — caller owns the list. Categories emitted:
            ``news_no_api_key``, ``news_coverage_gap``, ``news_fetch_failed``.

    Returns:
        {
            "headline_count": 5,
            "headlines": [
                {"headline": "...", "source": "Reuters", "datetime": "2026-03-20T14:30:00", "category": "company"},
                ...
            ],
            "summary": "5 articles in last 7 days. Sentiment: positive (3 pos, 1 neg, 1 neutral).",
            "news_sentiment": "positive",
            "last_news_date": "2026-03-20",
        }
    """
    cached = _load_cached(ticker, cache_hours)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
    if not finnhub_api_key:
        if warnings is not None:
            warnings.append(f"news_no_api_key:{ticker}:runtime")
        return None

    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": ticker,
        "from": start_date.strftime("%Y-%m-%d"),
        "to": end_date.strftime("%Y-%m-%d"),
    }
    headers = {"X-Finnhub-Token": finnhub_api_key}

    resp = retry_with_backoff(
        lambda: requests.get(url, params=params, headers=headers, timeout=15),
        max_retries=3, base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        logger.debug("Finnhub news request failed for %s after retries", ticker)
        if warnings is not None:
            warnings.append(f"news_fetch_failed:{ticker}:runtime")
        return None
    try:
        resp.raise_for_status()
        articles = resp.json()
    except Exception as e:
        logger.debug("Finnhub news request failed for %s: %s", ticker, e)
        if warnings is not None:
            warnings.append(f"news_fetch_failed:{ticker}:runtime")
        return None

    # Rate limit -- shared with insider fetcher (Finnhub 60/min)
    time.sleep(1.0)

    if not articles:
        if warnings is not None:
            warnings.append(f"news_coverage_gap:{ticker}:runtime")
        result = {
            "headline_count": 0,
            "headlines": [],
            "summary": f"No articles in last {lookback_days} days.",
            "news_sentiment": "no_news",
            "last_news_date": None,
        }
        _save_cache(ticker, result)
        return result

    # Sort by datetime descending, limit to 5 most recent
    articles.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    articles = articles[:5]

    headlines = []
    for a in articles:
        ts = a.get("datetime", 0)
        dt_str = datetime.fromtimestamp(ts).isoformat() if ts else ""
        headlines.append({
            "headline": a.get("headline", ""),
            "source": a.get("source", "Unknown"),
            "datetime": dt_str,
            "category": a.get("category", ""),
        })

    sentiment_label, pos, neg, neutral = _classify_sentiment(headlines)
    count = len(headlines)

    last_date = headlines[0]["datetime"][:10] if headlines else None

    summary = (
        f"{count} articles in last {lookback_days} days. "
        f"Sentiment: {sentiment_label} ({pos} pos, {neg} neg, {neutral} neutral)."
    )

    result = {
        "headline_count": count,
        "headlines": headlines,
        "summary": summary,
        "news_sentiment": sentiment_label,
        "last_news_date": last_date,
    }

    _save_cache(ticker, result)
    return result


def fetch_historical_news(ticker: str, as_of_date: str, lookback_days: int = 7,
                          finnhub_api_key: str | None = None,
                          cache_hours: int = 24,
                          warnings: list[str] | None = None) -> dict | None:
    """Fetch news headlines available on a specific historical date.

    TEMPORAL COMPLIANCE: Only returns news published BEFORE as_of_date.
    For backfill use — ensures training data has point-in-time news context.

    Args:
        ticker: Stock symbol.
        as_of_date: ISO ``YYYY-MM-DD`` historical anchor.
        lookback_days: Window length in days.
        finnhub_api_key: Finnhub API key.
        cache_hours: Cache TTL.
        warnings: Optional list to collect coverage/PIT warnings (#99).
            Mutated in place. Categories emitted: ``news_no_api_key``,
            ``news_invalid_as_of``, ``news_coverage_gap``, ``news_fetch_failed``.
    """
    cached = _load_cached(ticker, cache_hours, as_of_date=as_of_date)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
    if not finnhub_api_key:
        if warnings is not None:
            warnings.append(f"news_no_api_key:{ticker}:{as_of_date}")
        return None

    try:
        end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        if warnings is not None:
            warnings.append(f"news_invalid_as_of:{ticker}:{as_of_date}")
        return None

    start_dt = end_dt - timedelta(days=lookback_days)

    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": ticker,
        "from": start_dt.strftime("%Y-%m-%d"),
        "to": end_dt.strftime("%Y-%m-%d"),
    }
    headers = {"X-Finnhub-Token": finnhub_api_key}

    resp = retry_with_backoff(
        lambda: requests.get(url, params=params, headers=headers, timeout=15),
        max_retries=3, base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        logger.debug("Finnhub historical news request failed for %s on %s after retries",
                     ticker, as_of_date)
        if warnings is not None:
            warnings.append(f"news_fetch_failed:{ticker}:{as_of_date}")
        return None
    try:
        resp.raise_for_status()
        articles = resp.json()
    except Exception as e:
        logger.debug("Finnhub historical news request failed for %s on %s: %s",
                     ticker, as_of_date, e)
        if warnings is not None:
            warnings.append(f"news_fetch_failed:{ticker}:{as_of_date}")
        return None

    time.sleep(1.0)

    if not articles:
        if warnings is not None:
            warnings.append(f"news_coverage_gap:{ticker}:{as_of_date}")
        result = {
            "headline_count": 0,
            "headlines": [],
            "summary": f"No articles in {lookback_days} days before {as_of_date}.",
            "news_sentiment": "no_news",
            "last_news_date": None,
        }
        _save_cache(ticker, result, as_of_date=as_of_date)
        return result

    # TEMPORAL COMPLIANCE: filter to only articles published before as_of_date
    end_ts = end_dt.timestamp()
    articles = [a for a in articles if a.get("datetime", 0) <= end_ts]

    articles.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    articles = articles[:5]

    headlines = []
    for a in articles:
        ts = a.get("datetime", 0)
        dt_str = datetime.fromtimestamp(ts).isoformat() if ts else ""
        headlines.append({
            "headline": a.get("headline", ""),
            "source": a.get("source", "Unknown"),
            "datetime": dt_str,
            "category": a.get("category", ""),
        })

    sentiment_label, pos, neg, neutral = _classify_sentiment(headlines)
    count = len(headlines)
    last_date = headlines[0]["datetime"][:10] if headlines else None

    summary = (
        f"{count} articles in {lookback_days} days before {as_of_date}. "
        f"Sentiment: {sentiment_label} ({pos} pos, {neg} neg, {neutral} neutral)."
    )

    result = {
        "headline_count": count,
        "headlines": headlines,
        "summary": summary,
        "news_sentiment": sentiment_label,
        "last_news_date": last_date,
    }

    _save_cache(ticker, result, as_of_date=as_of_date)
    return result


def _build_premium_sentiment_result(data: dict) -> dict:
    """Extract and classify Finnhub premium sentiment API response into a result dict."""
    sentiment = data.get("sentiment") or {}
    bullish_pct = float(sentiment.get("bullishPercent", 0) or 0)
    bearish_pct = float(sentiment.get("bearishPercent", 0) or 0)
    company_score = float(data.get("companyNewsScore", 0) or 0)
    buzz = (data.get("buzz") or {}).get("articlesInLastWeek", 0) or 0

    if bullish_pct >= 0.67 and company_score >= 0.6:
        label = "positive"
    elif bearish_pct >= 0.67 and company_score <= 0.4:
        label = "negative"
    elif bullish_pct > 0 and bearish_pct > 0:
        label = "mixed"
    else:
        label = "neutral"

    return {
        "news_sentiment": label,
        "company_news_score": company_score,
        "bullish_percent": bullish_pct,
        "bearish_percent": bearish_pct,
        "articles_in_last_week": int(buzz),
        "sector_average_news_score": float(data.get("sectorAverageNewsScore", 0) or 0),
        "sector_average_bullish_percent": float(data.get("sectorAverageBullishPercent", 0) or 0),
        "summary": (
            f"Finnhub sentiment: {label} "
            f"(score {company_score:.2f}, bullish {bullish_pct:.0%}, "
            f"bearish {bearish_pct:.0%}, {int(buzz)} articles/week)."
        ),
    }


def fetch_news_sentiment(
    ticker: str,
    finnhub_api_key: str | None = None,
    cache_hours: int = 6,
    warnings: list[str] | None = None,
) -> dict | None:
    """Fetch Finnhub's premium news sentiment for runtime enrichment.

    Runtime only: the endpoint does not expose an as-of parameter, so callers
    must not use it for historical / PIT backfill paths.
    """
    cached = _load_sentiment_cached(ticker, cache_hours)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
    if not finnhub_api_key:
        return None

    url = "https://finnhub.io/api/v1/news-sentiment"
    headers = {"X-Finnhub-Token": finnhub_api_key}

    resp = retry_with_backoff(
        lambda: requests.get(url, params={"symbol": ticker}, headers=headers, timeout=15),
        max_retries=2,
        base_delay=1.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        if warnings is not None:
            warnings.append(f"news_sentiment_fetch_failed:{ticker}:runtime")
        return None

    try:
        if resp.status_code == 403:
            if warnings is not None:
                warnings.append(f"news_sentiment_unavailable:{ticker}:runtime")
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("Finnhub news sentiment request failed for %s: %s", ticker, exc)
        if warnings is not None:
            warnings.append(f"news_sentiment_fetch_failed:{ticker}:runtime")
        return None

    result = _build_premium_sentiment_result(data)
    _save_sentiment_cache(ticker, result)
    return result


def format_news_summary(data: dict | None) -> str:
    """Format news data into a concise text block for the LLM prompt.

    Returns string like:
    'Recent news (7d): 5 articles. Sentiment: Positive.
     - "NVIDIA Reports Record Q4 Revenue" (Reuters, Mar 20)
     - "AI Chip Demand Drives Growth" (Bloomberg, Mar 19)
     - "NVDA Price Target Raised" (MarketWatch, Mar 18)'

    Limit to 3 most recent headlines. Returns 'No recent news' if None.
    """
    if not data:
        return "No recent news"

    if data.get("headline_count", 0) == 0:
        return "No recent news"

    sentiment = data.get("news_sentiment", "neutral").capitalize()
    count = data["headline_count"]

    parts = [f"Recent news: {count} articles. Sentiment: {sentiment}."]

    headlines = data.get("headlines", [])[:3]
    for h in headlines:
        headline_text = h.get("headline", "")
        source = h.get("source", "")
        dt_str = h.get("datetime", "")
        # Format date as "Mar 20"
        date_short = ""
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str)
                date_short = dt.strftime("%b %d")
            except (ValueError, TypeError):
                pass
        if headline_text:
            line = f' - "{headline_text}"'
            if source or date_short:
                line += f" ({', '.join(filter(None, [source, date_short]))})"
            parts.append(line)

    return "\n".join(parts)
