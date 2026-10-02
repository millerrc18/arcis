#!/usr/bin/env python3
"""Live smoke test for the news recorder (T9).

Modes:
  full:        real poll against Alpaca paper into a temp data root; verifies
               articles are stored, manifests verify clean, heartbeat written.
  fingerprint: fetches live articles, verifies version-hash stability and
               that the tamper-evident index round-trips (rebuild is clean,
               and a tampered article is detected).

Usage:
  ALPACA_API_KEY=... ALPACA_API_SECRET=... uv run python tools/smoke.py --mode full
  ALPACA_API_KEY=... ALPACA_API_SECRET=... uv run python tools/smoke.py --mode fingerprint

Reads the universe from config/sp500.csv (first N symbols only, to stay fast).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arcis.recorder.client import AlpacaNewsClient
from arcis.recorder.config import Config
from arcis.recorder.runner import poll, read_heartbeat
from arcis.recorder.store import NewsStore, canonical_json
from arcis.recorder.universe import build_universe
from arcis.recorder.versioning import VersionIndex, version_hash

REPO = Path(__file__).resolve().parent.parent
SYMBOLS = ["AAPL", "MSFT", "NVDA"]


def make_config(data_root: Path) -> Config:
    import os

    return Config(
        data_root=data_root,
        alpaca_base_url="https://data.alpaca.markets",
        alpaca_api_key=os.environ["ALPACA_API_KEY"],
        alpaca_api_secret=os.environ["ALPACA_API_SECRET"],
        universe_name="sp500",
        universe_source="smoke",
        symbols=SYMBOLS,
        rate_limit={"max_requests_per_minute": 200, "max_requests_per_day": 50000},
        retry={"max_attempts": 3, "base_delay_seconds": 1.0, "max_delay_seconds": 10.0},
    )


def write_snapshot(config: Config, day) -> None:
    # Build a minimal vendored CSV with just our symbols for the smoke test.
    tmp_config = Path(tempfile.mkdtemp()) / "config"
    tmp_config.mkdir()
    (tmp_config / "sp500.csv").write_text("symbol\n" + "".join(s + "\n" for s in SYMBOLS))
    build_universe(config, day, tmp_config)


def smoke_full() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / "data"
        config = make_config(data_root)
        write_snapshot(config, datetime.now(UTC).date())
        summary = poll(config)
        print(json.dumps(summary, indent=2))
        assert summary["pairs_stored"] > 0, "expected at least one article stored"
        assert summary["server_date"], "expected a Date header"
        hb = read_heartbeat(data_root)
        assert hb and hb["pairs_stored"] == summary["pairs_stored"]
        store = NewsStore(data_root)
        errors = store.verify()
        assert not errors, f"verify failed: {errors}"
        print("full smoke: OK")


def smoke_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / "data"
        config = make_config(data_root)
        client = AlpacaNewsClient(config)
        try:
            end = datetime.now(UTC)
            start = end - timedelta(hours=24)
            fetched_list = list(client.fetch_news(SYMBOLS, start, end, max_pages=2))
        finally:
            client.close()
        assert fetched_list, "expected at least one live article"
        print(f"fetched {len(fetched_list)} articles")
        # Version hashes are stable across recomputation.
        for f in fetched_list[:5]:
            assert version_hash(f.raw) == version_hash(json.loads(canonical_json(f.raw)))
        # Index round-trips: store -> index -> rebuild is clean.
        store = NewsStore(data_root)
        index = VersionIndex(data_root)
        for f in fetched_list:
            for symbol in f.article.symbols:
                if symbol in SYMBOLS and store.append(symbol, f):
                    index.append(symbol, f.article.id, version_hash(f.raw))
        assert index.rebuild() == [], "rebuild should be clean"
        # Tampering is detected.
        first_symbol = fetched_list[0].article.symbols[0]
        if first_symbol in SYMBOLS:
            # Find the actual file (article date may differ from today).
            candidates = list((data_root / "articles" / first_symbol).glob("*.jsonl"))
            assert candidates, "expected an article file"
            path = candidates[0]
            lines = path.read_text().splitlines()
            tampered = dict(json.loads(lines[0]), headline="tampered")
            path.write_text(canonical_json(tampered) + "\n" + "\n".join(lines[1:]) + "\n")
            errors = index.rebuild()
            assert any("version hash mismatch" in e for e in errors), "tamper not detected"
            print("tamper detection: OK")
        print("fingerprint smoke: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "fingerprint"], required=True)
    args = parser.parse_args()
    if "ALPACA_API_KEY" not in __import__("os").environ:
        print("error: ALPACA_API_KEY is not set", file=sys.stderr)
        return 1
    try:
        if args.mode == "full":
            smoke_full()
        else:
            smoke_fingerprint()
    except Exception as e:  # noqa: BLE001 — CLI boundary: report and exit non-zero
        print(f"smoke failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
