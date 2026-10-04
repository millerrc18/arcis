#!/usr/bin/env python3
"""S03 T2: Pull daily bars panel for S&P 500 + SPY into the data root.

Writes parquet files under <data_root>/raw/bars/, one per symbol, plus a
manifest. Resumable: skips symbols with a complete manifest entry.

Usage:
    python tools/pull_bars_panel.py --data-root /home/hatch/arcis-data

Requires ALPACA_API_KEY / ALPACA_API_SECRET in the environment.
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CSV = REPO_ROOT / "config" / "sp500.csv"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
START = "2016-01-01T00:00:00Z"


def load_symbols() -> list[str]:
    syms = [line.strip() for line in UNIVERSE_CSV.read_text().splitlines()[1:] if line.strip()]
    if "SPY" not in syms:
        syms.append("SPY")
    return sorted(set(syms))


def fetch_bars(session: requests.Session, symbol: str) -> list[dict]:
    """Fetch all daily bars for one symbol, following pagination."""
    bars: list[dict] = []
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": START,
            "limit": 10000,
            "adjustment": "all",
            "feed": "sip",
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        r = session.get(BARS_URL, params=params, timeout=60)
        r.raise_for_status()
        d = r.json()
        sym_bars = d.get("bars", {}).get(symbol, [])
        bars.extend(sym_bars)
        page_token = d.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.1)
    return bars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    args = ap.parse_args()

    data_root = args.data_root
    # Data-root guard: refuse repo and cloud-sync paths (S01 invariant I-7).
    if REPO_ROOT in data_root.parents or data_root == REPO_ROOT:
        print("REFUSING: data root inside the repo", file=sys.stderr)
        return 1
    for sync in ("Dropbox", "OneDrive", "Google Drive", "iCloud"):
        if sync.lower() in str(data_root).lower():
            print(f"REFUSING: data root looks like a sync folder ({sync})", file=sys.stderr)
            return 1

    bars_dir = data_root / "raw" / "bars"
    bars_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bars_dir / "manifest.json"

    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_API_SECRET", "")
    if not key or not secret:
        print("ALPACA_API_KEY / ALPACA_API_SECRET required", file=sys.stderr)
        return 1
    session = requests.Session()
    session.headers.update({
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    })

    symbols = load_symbols()
    print(f"{len(symbols)} symbols, {len([s for s in symbols if s not in manifest])} to fetch")

    try:
        import pandas as pd
    except ImportError:
        print("pandas required", file=sys.stderr)
        return 1

    for i, sym in enumerate(symbols):
        if sym in manifest and manifest[sym].get("complete"):
            continue
        try:
            bars = fetch_bars(session, sym)
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"[{i+1}/{len(symbols)}] {sym}: ERROR {e}")
            manifest[sym] = {"complete": False, "error": str(e)}
            continue
        if not bars:
            print(f"[{i+1}/{len(symbols)}] {sym}: no bars")
            manifest[sym] = {"complete": True, "rows": 0, "first": None, "last": None}
            continue
        df = pd.DataFrame(bars)
        df["t"] = pd.to_datetime(df["t"])
        out = bars_dir / f"{sym}.parquet"
        df.to_parquet(out, index=False)
        sha = hashlib.sha256(out.read_bytes()).hexdigest()
        manifest[sym] = {
            "complete": True,
            "rows": len(df),
            "first": str(df["t"].min()),
            "last": str(df["t"].max()),
            "sha256": sha,
        }
        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(symbols)}] ...")
            manifest_path.write_text(json.dumps(manifest, indent=1))
        time.sleep(0.3)  # stay well under 200/min

    manifest["_meta"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "start": START,
        "universe": "sp500 + SPY",
        "symbols_total": len(symbols),
        "symbols_complete": sum(
            1 for v in manifest.values()
            if isinstance(v, dict) and v.get("complete")
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"Done. Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
