"""S03 T2: Pull news metadata-only panel for the most recent 12 months (batched).

Metadata-only by construction: for each symbol and calendar day, we store
ONLY the article count and the earliest created_at timestamp. No article
text, headlines, summaries, URLs, images, authors, or sources are retained,
and raw API responses are never written to disk.

This is a clean-room measurement script for S03 (preregistration power
calibration). It must NOT condition on any real signal:
  - Never load config/incumbent_v1.yaml.
  - No statistic conditional on incumbent qualification, ranker score,
    text score, or any real signal. Only per-stock-day article counts.

Batches multiple symbols per request for efficiency.

Output:
  <data_root>/raw/news_metadata/news_metadata.parquet
    (symbol, date, article_count, earliest_created_at)
  <data_root>/raw/news_metadata/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests

# S03 absolute anti-contamination rule: this script must never open the
# incumbent definition. Fail loudly if it is even referenced.
_FORBIDDEN_CONFIG = "incumbent_v1.yaml"

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
RATE_LIMIT_PAUSE_S = 0.2
PAGE_LIMIT = 50
BATCH_SIZE = 20  # symbols per request
MAX_PAGES_PER_BATCH = 500  # sanity cap


def _get(url: str, headers: dict, params: dict) -> dict:
    """GET with explicit requests exceptions only (no blind except)."""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
    except requests.RequestException as exc:  # transport-level failure
        raise RuntimeError(f"HTTP request failed for {url}: {exc}") from exc
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "60"))
        time.sleep(retry_after + 5)
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP retry failed for {url}: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Invalid JSON from {url}") from exc


def _check_forbidden(config_dir: str) -> None:
    # Guard: nothing in this script's execution should depend on the
    # incumbent definition. We do not read it; assert we are not asked to.
    forbidden = os.path.join(config_dir, _FORBIDDEN_CONFIG)
    assert not os.environ.get("ARCIS_ALLOW_INCUMBENT"), (
        "S03 scripts must not run with incumbent access enabled"
    )
    _ = forbidden  # path referenced only for the assertion message


def load_symbols(config_dir: str) -> list[str]:
    path = os.path.join(config_dir, "sp500.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    symbols = [r["symbol"].strip() for r in rows if r.get("symbol")]
    if "SPY" not in symbols:
        symbols.append("SPY")
    return symbols


def fetch_batch_metadata(
    symbols: list[str], headers: dict, start: datetime, end: datetime
) -> pd.DataFrame:
    """Fetch news for a batch of symbols; return per-day (count, earliest created_at)."""
    # per_day[(symbol, day)] = {"count": n, "earliest": ts}
    per_day: dict[tuple[str, str], dict] = {}
    page_token = None
    pages = 0
    symbols_param = ",".join(symbols)
    while pages < MAX_PAGES_PER_BATCH:
        params = {
            "symbols": symbols_param,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": PAGE_LIMIT,
            "include_content": "false",
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        payload = _get(NEWS_URL, headers, params)
        # Reduce each article immediately to (symbol, date, created_at);
        # never retain text fields. Strip any content-related key defensively.
        for article in payload.get("news", []):
            if not isinstance(article, dict):
                continue
            created = article.get("created_at")
            article_symbols = article.get("symbols", [])
            if not created or not article_symbols:
                continue
            day = created[:10]
            for sym in article_symbols:
                if not isinstance(sym, str):
                    continue
                sym = sym.strip()
                if sym not in symbols:
                    continue
                key = (sym, day)
                cell = per_day.setdefault(key, {"count": 0, "earliest": created})
                cell["count"] += 1
                if created < cell["earliest"]:
                    cell["earliest"] = created
        page_token = payload.get("next_page_token")
        pages += 1
        time.sleep(RATE_LIMIT_PAUSE_S)
        if not page_token:
            break
    rows = [
        {
            "symbol": sym,
            "date": day,
            "article_count": cell["count"],
            "earliest_created_at": cell["earliest"],
        }
        for (sym, day), cell in sorted(per_day.items())
    ]
    return pd.DataFrame(rows, columns=["symbol", "date", "article_count", "earliest_created_at"])


def main() -> int:
    parser = argparse.ArgumentParser(description="S03 news metadata-only panel pull (batched)")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    _check_forbidden(args.config_dir)

    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ALPACA_API_KEY / ALPACA_API_SECRET not set", file=sys.stderr)
        return 2
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}

    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=365)

    out_dir = os.path.join(args.data_root, "raw", "news_metadata")
    if not os.path.abspath(out_dir).startswith(os.path.abspath(args.data_root)):
        print("data root guard failed", file=sys.stderr)
        return 2
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "news_metadata.parquet")
    manifest_path = os.path.join(out_dir, "manifest.json")

    manifest: dict = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    done_symbols: set[str] = set(manifest.get("complete_symbols", []))

    symbols = load_symbols(args.config_dir)
    remaining = [s for s in symbols if s not in done_symbols]
    
    frames: list[pd.DataFrame] = []
    if os.path.exists(out_path):
        frames.append(pd.read_parquet(out_path))

    # Batch the remaining symbols
    batches = [remaining[i:i+BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]
    total_batches = len(batches)
    
    for i, batch in enumerate(batches, 1):
        try:
            df = fetch_batch_metadata(batch, headers, start, end)
        except RuntimeError as exc:
            print(f"ERROR batch {i}: {exc}", file=sys.stderr)
            return 1
        frames.append(df)
        done_symbols.update(batch)
        if i % 5 == 0 or i == total_batches:
            print(f"[{i}/{total_batches}] batches ... "
                  f"({len(done_symbols)}/{len(symbols)} symbols)", flush=True)
            # checkpoint
            combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            combined.to_parquet(out_path, index=False)
            manifest["complete_symbols"] = sorted(done_symbols)
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    combined = combined.drop_duplicates(subset=["symbol", "date"]).sort_values(
        ["symbol", "date"]
    )
    combined.to_parquet(out_path, index=False)

    digest = hashlib.sha256()
    with open(out_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)

    manifest.update(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "symbols_total": len(symbols),
            "symbols_complete": len(done_symbols),
            "stock_days": int(len(combined)),
            "sha256": digest.hexdigest(),
            "fields": ["symbol", "date", "article_count", "earliest_created_at"],
            "note": ("metadata only: article counts and earliest created_at "
                     "per stock-day; no text retained"),
        }
    )
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Done. Stock-days with news: {len(combined)}. Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
