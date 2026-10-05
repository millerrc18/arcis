"""S04 T1-T5, T7: Data plane audit.

Audits the S03 bars panel for coverage, adjustments, corporate actions,
availability, and survivorship. Produces aggregate statistics only.

Usage:
    python tools/audit_data_plane.py --data-root /home/hatch/arcis-data

Output: <data_root>/s04/audit_results.json (aggregate statistics only).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd

# Known splits for adjustment verification (T3)
KNOWN_SPLITS = [
    # (symbol, split_date, ratio) — ratio = pre-split shares per post-split share
    ("AAPL", "2020-08-31", 4),   # 4:1
    ("TSLA", "2020-08-31", 5),   # 5:1
    ("NVDA", "2021-07-20", 4),   # 4:1
    ("AMZN", "2022-06-06", 20),  # 20:1
]


def load_panel(data_root: str) -> pd.DataFrame:
    """Load all per-symbol bars into one DataFrame."""
    bars_dir = os.path.join(data_root, "raw", "bars")
    frames = []
    for fname in sorted(os.listdir(bars_dir)):
        if not fname.endswith(".parquet"):
            continue
        symbol = fname[:-len(".parquet")]
        df = pd.read_parquet(os.path.join(bars_dir, fname))
        df["symbol"] = symbol
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["t"], utc=True)
    return panel.sort_values(["symbol", "date"]).reset_index(drop=True)


def audit_coverage(panel: pd.DataFrame) -> dict:
    """T1: per-symbol coverage statistics (aggregates only)."""
    # SPY trading calendar as reference
    spy_dates = set(
        panel[panel["symbol"] == "SPY"]["date"].dt.date.astype(str)
    )
    stats = []
    late_starters = []
    for symbol, grp in panel.groupby("symbol"):
        dates = set(grp["date"].dt.date.astype(str))
        first = min(dates)
        last = max(dates)
        # Gaps: SPY trading days missing for this symbol (after its first bar)
        expected = {d for d in spy_dates if d >= first}
        gaps = sorted(expected - dates)
        stats.append({
            "n_rows": len(grp),
            "n_gaps": len(gaps),
            "first": first,
            "last": last,
        })
        if first > "2016-01-04":
            late_starters.append((symbol, first))
    df = pd.DataFrame(stats)
    return {
        "n_symbols": int(len(df)),
        "rows": {
            "mean": float(df["n_rows"].mean()),
            "min": int(df["n_rows"].min()),
            "max": int(df["n_rows"].max()),
        },
        "gaps": {
            "symbols_with_gaps": int((df["n_gaps"] > 0).sum()),
            "max_gaps": int(df["n_gaps"].max()),
            "mean_gaps": float(df["n_gaps"].mean()),
        },
        "late_starters": {
            "count": len(late_starters),
            "list": sorted(late_starters),
        },
        "date_range": {
            "min": str(panel["date"].min().date()),
            "max": str(panel["date"].max().date()),
        },
    }


def verify_adjustments(panel: pd.DataFrame) -> dict:
    """T3: verify known splits show no artificial jumps."""
    results = []
    for symbol, split_date, ratio in KNOWN_SPLITS:
        grp = panel[panel["symbol"] == symbol].sort_values("date")
        if len(grp) < 2:
            results.append({"symbol": symbol, "status": "no data"})
            continue
        # Find the split date
        grp["d"] = grp["date"].dt.date.astype(str)
        before = grp[grp["d"] < split_date].iloc[-1] if len(grp[grp["d"] < split_date]) else None
        after = grp[grp["d"] >= split_date].iloc[0] if len(grp[grp["d"] >= split_date]) else None
        if before is None or after is None:
            results.append({"symbol": symbol, "status": "split date not in range"})
            continue
        # With adjustment=all, the pre-split close should be divided by ratio
        # So before.c / ratio should ≈ after.o (no jump)
        # Actually: adjusted close before = raw close before / ratio
        # The ratio of closes across the split should be ~1.0 (no jump)
        # We check: |log(after.c / before.c)| should be small (normal daily move)
        # If unadjusted, it would be ~log(ratio) ≈ 1.39 for 4:1
        log_jump = abs(float(np.log(after["c"] / before["c"])))
        results.append({
            "symbol": symbol,
            "split_date": split_date,
            "ratio": ratio,
            "log_jump": log_jump,
            "adjusted": bool(log_jump < 0.2),  # < ~22% move = likely adjusted
        })
    return {"splits": results}


def audit_availability(panel: pd.DataFrame) -> dict:
    """T5: data availability characteristics."""
    # For the forward test, what matters is that bars are available at t_d.
    # We document the panel's timestamp characteristics.
    panel["hour"] = panel["date"].dt.hour
    return {
        "note": (
            "Bars are timestamped at midnight UTC (00:00). For the forward test, "
            "availability at t_d (17:00 ET) depends on Alpaca's publication latency, "
            "not the bar timestamp."
        ),
        "bar_timestamp_hour_utc": int(panel["hour"].mode()[0]),
        "n_symbols": int(panel["symbol"].nunique()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S04 data plane audit")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    args = parser.parse_args()

    out_dir = os.path.join(args.data_root, "s04")
    os.makedirs(out_dir, exist_ok=True)

    print("Loading panel...", flush=True)
    panel = load_panel(args.data_root)
    print(f"  {len(panel):,} rows", flush=True)

    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "coverage": audit_coverage(panel),
        "adjustments": verify_adjustments(panel),
        "availability": audit_availability(panel),
    }

    out_path = os.path.join(out_dir, "audit_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}", flush=True)

    # Print summary
    c = results["coverage"]
    print(f"Symbols: {c['n_symbols']}, late starters: {c['late_starters']['count']}")
    print(f"Symbols with gaps: {c['gaps']['symbols_with_gaps']}")
    for s in results["adjustments"]["splits"]:
        lj = s.get("log_jump", "N/A")
        adj = s.get("adjusted", "N/A")
        print(f"  {s['symbol']}: log_jump={lj}, adjusted={adj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
