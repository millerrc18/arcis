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
import os
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


def _guard_data_root(data_root: Path) -> bool:
    """Refuse repo and cloud-sync paths (S01 invariant I-7).

    Returns True if the path is acceptable. Resolve first so relative
    paths cannot bypass the check.
    """
    data_root = data_root.resolve()
    repo_resolved = REPO_ROOT.resolve()
    if repo_resolved in data_root.parents or data_root == repo_resolved:
        print("REFUSING: data root inside the repo", file=sys.stderr)
        return False
    for sync in ("Dropbox", "OneDrive", "Google Drive", "iCloud"):
        if sync.lower() in str(data_root).lower():
            print(f"REFUSING: data root looks like a sync folder ({sync})",
                  file=sys.stderr)
            return False
    return True


def _fetch_one(
    session: requests.Session, sym: str, i: int, n: int,
    bars_dir: Path, manifest: dict,
) -> bool:
    """Fetch and store bars for one symbol. Returns True on success."""
    try:
        bars = fetch_bars(session, sym)
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[{i+1}/{n}] {sym}: ERROR {e}")
        manifest[sym] = {"complete": False, "error": str(e)}
        return False
    if not bars:
        print(f"[{i+1}/{n}] {sym}: no bars")
        manifest[sym] = {"complete": False, "rows": 0,
                         "error": "no bars returned"}
        return False
    import pandas as pd
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"])
    out = bars_dir / f"{sym}.parquet"
    df.to_parquet(out, index=False)
    manifest[sym] = {
        "complete": True,
        "rows": len(df),
        "first": str(df["t"].min()),
        "last": str(df["t"].max()),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    return True


def _report_coverage(manifest: dict, manifest_path: Path) -> None:
    """Write manifest meta and print late-starter coverage report."""
    manifest["_meta"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "start": START,
        "universe": "sp500 + SPY",
        "symbols_total": len([k for k in manifest if k != "_meta"]),
        "symbols_complete": sum(
            1 for v in manifest.values()
            if isinstance(v, dict) and v.get("complete")
        ),
        "symbols_failed": sum(
            1 for v in manifest.values()
            if isinstance(v, dict) and not v.get("complete")
        ),
    }
    late_starters = []
    for sym, entry in manifest.items():
        if sym == "_meta" or not isinstance(entry, dict):
            continue
        if not entry.get("complete"):
            continue
        first = entry.get("first", "")
        if first and first[:4] > "2016":
            late_starters.append((sym, first[:10], entry.get("rows", 0)))
    if late_starters:
        print(f"\nLate starters ({len(late_starters)} symbols, first bar after 2016):")
        for sym, first, rows in sorted(late_starters)[:20]:
            print(f"  {sym}: first={first}, rows={rows}")
        if len(late_starters) > 20:
            print(f"  ... and {len(late_starters) - 20} more")
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"Done. Manifest: {manifest_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    args = ap.parse_args()
    if not _guard_data_root(args.data_root):
        return 1
    data_root = args.data_root.resolve()
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
    try:
        import pandas  # noqa: F401
    except ImportError:
        print("pandas required", file=sys.stderr)
        return 1
    symbols = load_symbols()
    todo = [s for s in symbols if not manifest.get(s, {}).get("complete")]
    print(f"{len(symbols)} symbols, {len(todo)} to fetch")
    errors = 0
    for i, sym in enumerate(symbols):
        if sym in manifest and manifest[sym].get("complete"):
            continue
        if not _fetch_one(session, sym, i, len(symbols), bars_dir, manifest):
            errors += 1
        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(symbols)}] ...")
            manifest_path.write_text(json.dumps(manifest, indent=1))
        time.sleep(0.3)  # stay well under 200/min
    _report_coverage(manifest, manifest_path)
    if errors:
        print(f"{errors} symbols failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
