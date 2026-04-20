"""One-off backfill: 2023-01-01 to 2024-12-31 daily OHLCV for the S&P 100
universe + SPY + ^VIX.

Issue #570. Unblocks Sprint F (#564) byte-identity fuzz across 10 fuzz dates
spanning 2024. The 24-month range provides SMA200 lookback (200 trading days)
before the earliest fuzz date (2024-01-16). SPY is included on functional-
necessity grounds — rank_universe fails without it (RS calculations). ^VIX
is required by compute_market_regime for vix_proxy.

Reuses src/simulation/cache.py::fetch_cached_ohlcv — per-call parquet save
(crash-safe), cache-hit skip on re-run, safe-ticker filename handling.

Usage: python scripts/backfill_2024_ohlcv.py
Runtime: ~1-3 minutes depending on cache hit rate and network.
"""

import logging
import sys
import time
from pathlib import Path

# allow direct script execution from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.simulation.cache import fetch_cached_ohlcv
from src.universe.sp100 import get_sp100_universe

logging.basicConfig(level=logging.INFO, format="%(message)s")

START = "2023-01-01"
END = "2024-12-31"
EXTRA = ["SPY", "^VIX"]
SLEEP_BETWEEN = 0.5  # seconds between fetches
FAILURE_TOLERANCE = 0.05  # >5% failure rate to exit 1


def main() -> int:
    universe = get_sp100_universe() + EXTRA
    print(f"Backfill: {len(universe)} tickers | {START} to {END}")
    print(f"Output:   data/simulation_cache/<safe_ticker>_{START}_{END}.parquet")
    print()

    t0 = time.monotonic()
    failures: list[str] = []

    for i, ticker in enumerate(universe, 1):
        result = fetch_cached_ohlcv(ticker, START, END)
        status = "OK" if result is not None else "FAILED"
        if result is None:
            failures.append(ticker)
        if status == "FAILED" or i % 10 == 0 or i == len(universe):
            print(
                f"  [{i:3d}/{len(universe)}] {ticker:8s} {status:6s} "
                f"(failures so far: {len(failures)})"
            )
        time.sleep(SLEEP_BETWEEN)

    dt = time.monotonic() - t0
    print()
    print("=== Summary ===")
    print(f"  Total:     {len(universe)}")
    print(f"  Succeeded: {len(universe) - len(failures)}")
    print(f"  Failed:    {len(failures)}")
    if failures:
        print(f"  Failed tickers: {failures}")
    print(f"  Runtime:   {dt:.1f}s")

    fail_rate = len(failures) / len(universe)
    if fail_rate > FAILURE_TOLERANCE:
        print(
            f"\n  FAILURE RATE {fail_rate:.1%} EXCEEDS "
            f"{FAILURE_TOLERANCE:.0%} TOLERANCE — investigate before declaring sprint complete."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
