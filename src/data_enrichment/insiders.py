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

from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/insiders")


def _get_cache_path(ticker: str, as_of_date: str | None = None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{as_of_date}" if as_of_date else ""
    return CACHE_DIR / f"{ticker}_insiders{suffix}.pkl"


def _load_cached(ticker: str, cache_hours: int = 24, as_of_date: str | None = None) -> dict | None:
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


def _fetch_from_finnhub(
    ticker: str,
    api_key: str,
    lookback_days: int = 90,
    as_of: str | None = None,
    warnings: list[str] | None = None,
) -> dict | None:
    """Fetch insider transactions from Finnhub API.

    When ``as_of`` is None: uses lookback_days from "now" (runtime path).
    When ``as_of`` is set: uses [as_of - lookback_days, as_of] window
    (TEMPORAL COMPLIANCE for backtest / training-corpus paths).

    ``warnings`` (#99): Optional list mutated in place when the Finnhub
    request fails or as_of is unparseable. Categories: ``insiders_invalid_as_of``,
    ``insiders_fetch_failed``.
    """
    url = "https://finnhub.io/api/v1/stock/insider-transactions"
    params: dict[str, str] = {"symbol": ticker}
    headers = {"X-Finnhub-Token": api_key}

    # Compute window. When as_of is set, pass from/to to Finnhub so the API
    # itself bounds the response and the client-side filter aligns with PIT.
    if as_of is not None:
        try:
            end_dt = datetime.strptime(as_of, "%Y-%m-%d")
        except (ValueError, TypeError):
            if warnings is not None:
                warnings.append(f"insiders_invalid_as_of:{ticker}:{as_of}")
            return None
        start_dt = end_dt - timedelta(days=lookback_days)
        params["from"] = start_dt.strftime("%Y-%m-%d")
        params["to"] = end_dt.strftime("%Y-%m-%d")
        cutoff = start_dt
    else:
        end_dt = datetime.now()
        cutoff = end_dt - timedelta(days=lookback_days)

    resp = retry_with_backoff(
        lambda: requests.get(url, params=params, headers=headers, timeout=15),
        max_retries=3, base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        logger.debug("Finnhub request failed for %s after retries", ticker)
        if warnings is not None:
            anchor = as_of if as_of is not None else "runtime"
            warnings.append(f"insiders_fetch_failed:{ticker}:{anchor}")
        return None
    try:
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug("Finnhub request failed for %s: %s", ticker, e)
        if warnings is not None:
            anchor = as_of if as_of is not None else "runtime"
            warnings.append(f"insiders_fetch_failed:{ticker}:{anchor}")
        return None

    transactions = data.get("data", [])
    if not transactions:
        return None

    recent = []
    for tx in transactions:
        tx_date_str = tx.get("transactionDate", "")
        try:
            tx_date = datetime.strptime(tx_date_str, "%Y-%m-%d")
            if tx_date < cutoff:
                continue
            # When as_of is set, also exclude post-as_of transactions
            # (defense-in-depth — Finnhub honors `to` but we double-check).
            if as_of is not None and tx_date > end_dt:
                continue
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
    as_of: str | None = None,
    warnings: list[str] | None = None,
) -> dict | None:
    """Fetch recent insider trading activity.

    Returns dict with insider buys/sells, net shares, sentiment, and notable transactions.
    Returns None if data is unavailable.

    Args:
        ticker: Stock symbol.
        lookback_days: Window length in days.
        finnhub_api_key: Finnhub API key (falls back to ``FINNHUB_API_KEY`` env).
        cache_hours: Cache TTL.
        as_of: Optional ISO date string (``YYYY-MM-DD``). When set, the lookup
            uses ``[as_of - lookback_days, as_of]`` and the cache key is
            namespaced by ``as_of`` so PIT and "now" data don't collide
            (#857 — Sprint 1.C Phase 2 PIT fix). When None (the runtime
            default), behavior is unchanged.
        warnings: Optional list to collect coverage/PIT warnings (#99).
            Mutated in place. Categories emitted: ``insiders_no_api_key``,
            ``insiders_invalid_as_of``, ``insiders_fetch_failed``.

    Coverage limit: Finnhub free-tier insider history goes back ~2-3 years.
    Stage 1 OOS window starts 2023-09 (pre-reg addendum 1 §A4) which is
    inside coverage; earliest folds may be sparse.
    """
    # Check cache (PIT-aware: as_of-keyed when set so backfills don't collide
    # with runtime cache).
    cached = _load_cached(ticker, cache_hours, as_of_date=as_of)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    result = None

    # Try Finnhub (.env fallback when caller doesn't provide key)
    finnhub_api_key = finnhub_api_key or os.environ.get("FINNHUB_API_KEY")
    if finnhub_api_key:
        result = _fetch_from_finnhub(
            ticker, finnhub_api_key, lookback_days, as_of=as_of, warnings=warnings,
        )
        time.sleep(1.0)  # Rate limit
    else:
        if warnings is not None:
            anchor = as_of if as_of is not None else "runtime"
            warnings.append(f"insiders_no_api_key:{ticker}:{anchor}")

    if result is not None:
        _save_cache(ticker, result, as_of_date=as_of)
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
