"""Insider trading data fetcher.

Called by: data_enrichment/enricher.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_enrichment.py

Primary source: Finnhub API (free tier: 60 calls/min).
Fallback: SEC EDGAR Form 4 data.
"""

import logging
import os
import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/insiders")


def _get_cache_path(ticker: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{ticker}_insiders.pkl"


def _load_cached(ticker: str, cache_hours: int = 24) -> dict | None:
    path = _get_cache_path(ticker)
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


def _save_cache(ticker: str, data: dict) -> None:
    data["_cached_at"] = datetime.now()
    path = _get_cache_path(ticker)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _fetch_from_finnhub(ticker: str, api_key: str, lookback_days: int = 90) -> dict | None:
    """Fetch insider transactions from Finnhub API."""
    url = "https://finnhub.io/api/v1/stock/insider-transactions"
    params = {"symbol": ticker}
    headers = {"X-Finnhub-Token": api_key}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug("Finnhub request failed for %s: %s", ticker, e)
        return None

    transactions = data.get("data", [])
    if not transactions:
        return None

    cutoff = datetime.now() - timedelta(days=lookback_days)
    recent = []
    for tx in transactions:
        tx_date_str = tx.get("transactionDate", "")
        try:
            tx_date = datetime.strptime(tx_date_str, "%Y-%m-%d")
            if tx_date >= cutoff:
                recent.append(tx)
        except (ValueError, TypeError):
            continue

    if not recent:
        return {
            "insider_buys_90d": 0,
            "insider_sells_90d": 0,
            "insider_net_shares": 0,
            "insider_net_value": 0,
            "insider_sentiment": "no_activity",
            "notable_transactions": [],
            "last_transaction_date": None,
        }

    buys = [t for t in recent if t.get("transactionType") in ("P - Purchase", "P")]
    sells = [t for t in recent if t.get("transactionType") in ("S - Sale", "S")]

    buy_count = len(buys)
    sell_count = len(sells)

    buy_shares = sum(abs(t.get("share", 0) or 0) for t in buys)
    sell_shares = sum(abs(t.get("share", 0) or 0) for t in sells)
    net_shares = buy_shares - sell_shares

    buy_value = sum(abs(t.get("transactionPrice", 0) or 0) * abs(t.get("share", 0) or 0) for t in buys)
    sell_value = sum(abs(t.get("transactionPrice", 0) or 0) * abs(t.get("share", 0) or 0) for t in sells)
    net_value = buy_value - sell_value

    # Classify sentiment
    if buy_count > sell_count and net_value > 0:
        sentiment = "net_buying"
    elif sell_count > buy_count and net_value < 0:
        sentiment = "net_selling"
    elif buy_count == 0 and sell_count == 0:
        sentiment = "no_activity"
    else:
        sentiment = "neutral"

    # Notable transactions (top 5 by value)
    all_txs = []
    for t in recent:
        name = t.get("name", "Insider")
        shares = abs(t.get("share", 0) or 0)
        price = t.get("transactionPrice", 0) or 0
        value = shares * price
        date = t.get("transactionDate", "")
        tx_type = "bought" if t.get("transactionType", "").startswith("P") else "sold"
        all_txs.append({
            "text": f"{name} {tx_type} {shares:,.0f} shares (${value:,.0f}) on {date}",
            "value": value,
        })

    all_txs.sort(key=lambda x: -x["value"])
    notable = [t["text"] for t in all_txs[:5]]

    # Last transaction date
    dates = [t.get("transactionDate", "") for t in recent]
    dates.sort(reverse=True)
    last_date = dates[0] if dates else None

    return {
        "insider_buys_90d": buy_count,
        "insider_sells_90d": sell_count,
        "insider_net_shares": int(net_shares),
        "insider_net_value": round(net_value, 2),
        "insider_sentiment": sentiment,
        "notable_transactions": notable,
        "last_transaction_date": last_date,
    }


def fetch_insider_activity(
    ticker: str,
    lookback_days: int = 90,
    finnhub_api_key: str | None = None,
    cache_hours: int = 24,
) -> dict | None:
    """Fetch recent insider trading activity.

    Returns dict with insider buys/sells, net shares, sentiment, and notable transactions.
    Returns None if data is unavailable.
    """
    # Check cache
    cached = _load_cached(ticker, cache_hours)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    result = None

    # Try Finnhub (.env fallback when caller doesn't provide key)
    finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
    if finnhub_api_key:
        result = _fetch_from_finnhub(ticker, finnhub_api_key, lookback_days)
        time.sleep(1.0)  # Rate limit

    if result is not None:
        _save_cache(ticker, result)
        return result

    return None


def format_insider_summary(data: dict | None) -> str:
    """Format insider data into a concise text block."""
    if not data:
        return "No insider data available"

    sentiment = data.get("insider_sentiment", "no_activity")

    if sentiment == "no_activity":
        return "Insider activity (90d): No transactions recorded"

    buys = data.get("insider_buys_90d", 0)
    sells = data.get("insider_sells_90d", 0)
    net_value = data.get("insider_net_value", 0)

    sentiment_label = {
        "net_buying": "Net buying",
        "net_selling": "Net selling",
        "neutral": "Mixed",
    }.get(sentiment, sentiment)

    parts = [f"Insider activity (90d): {sentiment_label}"]
    parts.append(f"{sells} sells vs {buys} buys")
    parts.append(f"net {_format_value(net_value)}")

    notable = data.get("notable_transactions", [])
    if notable:
        parts.append(f"Notable: {notable[0]}")

    return " — ".join(parts[:2]) + ", " + ", ".join(parts[2:])


def _format_value(value: float) -> str:
    """Format dollar value compactly."""
    abs_val = abs(value)
    sign = "+" if value >= 0 else "-"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.0f}K"
    else:
        return f"{sign}${abs_val:.0f}"
