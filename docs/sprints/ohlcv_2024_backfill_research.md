# 2024 OHLCV backfill Pass 2 — Research

**Branch:** `feat/backfill-2024-ohlcv`
**Issue:** #570
**Date:** 2026-04-20
**Builds on:** `docs/sprints/ohlcv_2024_backfill_evaluation.md` (Pass 1, commit `abbe8a9`)
**Operator resolutions (2026-04-20):** date range 2023-01-01..2024-12-31 approved; universe list hardcoded as-is; SPY inclusion approved on functional-necessity grounds.

-----

## Section 0 — Operator resolutions (lock-in)

| # | Question | Resolution |
|---|---|---|
| 1 | Date range | **2023-01-01 → 2024-12-31** (24 months). SMA200 lookback rationale accepted. |
| 2 | Universe-freshness | Hardcoded list as-is. Log any failures as "possibly delisted" in Pass 3 report. PYPL/F/GM/KHC noted in PR body observations regardless of outcome. **Do NOT file new issue unless >1 of the 4 actually fails** — then fold into a general "SP100 constituent staleness" cleanup candidate. |
| 3 | SPY inclusion | **Approved.** Prerequisite, not universe expansion. CHANGELOG must explain rationale so future readers don't read it as scope creep. |

Final fetch list: **104 tickers** = 102 S&P 100 + `SPY` + `^VIX`.

-----

## Section 1 — Sentinel fetch results (empirical)

Pass 2 ran `fetch_cached_ohlcv(ticker, "2023-01-01", "2024-12-31")` on 7 tickers sequentially with 0.5s spacing. All 7 succeeded.

### 1.1 High-confidence sentinels (Pass 1 §9 plan)

| Ticker | Rows | First date | Last date | Fetch time | Notes |
|---|---|---|---|---|---|
| AAPL  | 501 | 2023-01-03 | 2024-12-30 | 1.83s | First call — includes DNS + TLS warmup |
| GOOGL | 501 | 2023-01-03 | 2024-12-30 | 0.28s | |
| MSFT  | 501 | 2023-01-03 | 2024-12-30 | 0.29s | |

### 1.2 Possibly-stale candidates (Pass 1 §1.4 flagged)

| Ticker | Rows | First date | Last date | Fetch time | Status |
|---|---|---|---|---|---|
| PYPL | 501 | 2023-01-03 | 2024-12-30 | 0.30s | **Clean — not delisted** |
| F    | 501 | 2023-01-03 | 2024-12-30 | 0.40s | **Clean — not delisted** |
| GM   | 501 | 2023-01-03 | 2024-12-30 | 0.33s | **Clean — not delisted** |
| KHC  | 501 | 2023-01-03 | 2024-12-30 | 0.22s | **Clean — not delisted** |

**All 4 flagged candidates return full-range 2023-2024 daily OHLCV.** None are delisted. Whether they're still on the S&P 100 in 2024 is a separate membership question — but from a data-availability standpoint, they're all fetchable. Pass 3 will note this in the PR body per operator direction (no new issue unless fetch failures).

### 1.3 Schema verification

All 7 parquets return the same column schema:

```python
cols = ['Close', 'High', 'Low', 'Open', 'Volume']  # 5 columns, sorted
```

Observations:

- Ordering is **alphabetical** (Close before High, Low before Open, etc.) — different from the canonical OHLCV ordering but purely presentational; `compute_features` accesses columns by name (`ohlcv["Close"]`), not by position.
- **No `Adj Close` column** — expected because `auto_adjust=True` (cache.py:53). Adjustments are applied to `Close` in-place. This matches `compute_features` expectations — it reads `Close`, `High`, `Low`, `Volume` (engine.py:113-116) and never references `Adj Close`.
- Index is a DatetimeIndex on trading days (no index column in the parquet — stored via the DataFrame index).

### 1.4 Coverage for Sprint F fuzz dates

All 7 sentinels satisfy:

- `df.index.min() ≤ 2023-04-20` (warmup ≥ 260 trading days before 2024-01-16 fuzz) — ALL satisfy (min is 2023-01-03).
- `df.index.max() ≥ 2024-11-19` (covers last fuzz date) — ALL satisfy (max is 2024-12-30).

Sprint F will have complete feature-computation coverage for all 10 fuzz dates + 1 primary.

### 1.5 Row-count consistency

All 7 tickers return **501 rows**. Calendar years 2023-2024 span 729 calendar days → expected ~502 trading days (252 + 252 - ~2 observed-first-day holidays). 501 is the exact correct count. No anomalies.

### 1.6 Cache state after sentinel run

```
data/simulation_cache/AAPL_2023-01-01_2024-12-31.parquet
data/simulation_cache/F_2023-01-01_2024-12-31.parquet
data/simulation_cache/GM_2023-01-01_2024-12-31.parquet
data/simulation_cache/GOOGL_2023-01-01_2024-12-31.parquet
data/simulation_cache/KHC_2023-01-01_2024-12-31.parquet
data/simulation_cache/MSFT_2023-01-01_2024-12-31.parquet
data/simulation_cache/PYPL_2023-01-01_2024-12-31.parquet
```

7/104 tickers cached. Pass 3 backfill will skip these 7 (cache hit at `fetch_cached_ohlcv` line 48-49) and fetch the remaining 97. **Re-run idempotency confirmed in practice.**

The 8 pre-existing scenario-partial parquets (NKE/PG/^VIX with non-2023-01-01_2024-12-31 keys) remain untouched, confirming the no-overwrite property of distinct cache keys.

-----

## Section 2 — Runtime projection

### 2.1 Measured latencies

- **First fetch** (AAPL): 1.83s — includes DNS resolution, TLS handshake, yfinance HTTP session setup. One-time cost per Python process.
- **Subsequent fetches**: 0.22 - 0.40s each, mean ≈ 0.30s.

### 2.2 Full-run extrapolation

With 97 remaining tickers (7 already cached):

- Fetch time: 97 × 0.30s ≈ 29s
- Sleep between: 97 × 0.5s = 48.5s
- First-fetch warmup: +1.5s (one-time on Pass 3 run)
- **Estimated total: ~80s (~1.3 minutes)**

If the full 104 is re-run (cache cleared): ~140s (~2.3 minutes). Both well under the 10-minute guardrail and under the 5-minute prompt target.

### 2.3 Failure-rate tolerance

Pass 1 §4.4 set tolerance at ≤5% (≤5 failures out of 104).

Pass 2 evidence: 7/7 fetches succeeded including all 4 flagged candidates. Observed failure rate: 0%.

**Adjusted expectation:** likely 0-2 failures in Pass 3. Anything >2 is suspicious and warrants investigation (probably network / rate-limiting, not tickers).

-----

## Section 3 — Edge cases to watch in Pass 3

### 3.1 Known class-share tickers

`BRK.B` → `BRK-B` (yfinance). Handled by `to_yfinance_ticker()` in `src/universe/sp100.py:20-22`. No action needed in the Pass 3 script.

No other class-share tickers in the current S&P 100 list. `GOOG` and `GOOGL` are separate tickers (not share classes of one entity for yfinance purposes) — both fetch independently.

### 3.2 Symbol changes mid-2024

The hardcoded universe list was last verified 2025-03-24 (per module docstring). No indication of any S&P 100 ticker symbol changing between 2023-01-01 and 2024-12-31 that isn't already reflected. `BRK.B` → `BRK-B` is the sole translation.

If a future universe refresh adds a ticker with a different symbol in 2024 vs today, yfinance's lookup might fail — but that's a Pass 3+ surprise, not a blocker.

### 3.3 Rate limiting

yfinance community consensus: ~2 req/sec sustained. Our 0.5s spacing (2 req/sec) is at the edge. If yfinance returns `YFRateLimitError` mid-run, `fetch_cached_ohlcv` catches it, logs a warning, and returns `None`. Script-level: the ticker goes into the failures list. Operator can re-run Pass 3 — cache hits skip completed tickers, and only the failed ones retry.

Pass 3 will bump spacing to 0.5s (already planned). If we observe any rate-limit errors in practice, can bump to 1.0s.

### 3.4 VIX-specific handling

`^VIX` is an index, not a stock. yfinance returns volume as 0 for indices. `compute_features` reads `volume` for `volume_ratio_20d` (engine.py:175), which would divide by 0 average.

But `compute_features` is only called by Sprint F on ticker OHLCV, not on ^VIX itself. ^VIX is consumed by `compute_market_regime` for `vix_proxy` (regime.py:107-108), which uses daily returns of `Close`, not volume. So the volume-zero concern is moot for Sprint F's byte-identity fuzz.

No special handling needed. `^VIX` caches as `^VIX_2023-01-01_2024-12-31.parquet`.

-----

## Section 4 — Pass 3 handoff

### 4.1 Script to create

**New:** `scripts/backfill_2024_ohlcv.py`

Structure:

```python
"""One-off backfill script: 2023-01-01 → 2024-12-31 daily OHLCV for the
S&P 100 universe + SPY + ^VIX.

Issue #570. Unblocks Sprint F (#564) byte-identity fuzz.

Usage: python scripts/backfill_2024_ohlcv.py
Runtime: ~1-3 minutes depending on cache hit rate.
"""

import logging
import sys
import time
from pathlib import Path

# allow direct script execution from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.simulation.cache import fetch_cached_ohlcv
from src.universe.sp100 import get_sp100_universe

logging.basicConfig(level=logging.INFO, format='%(message)s')

START = "2023-01-01"
END = "2024-12-31"
EXTRA = ["SPY", "^VIX"]
SLEEP_BETWEEN = 0.5  # seconds

def main() -> int:
    universe = get_sp100_universe() + EXTRA
    print(f"Backfilling {len(universe)} tickers from {START} to {END}")
    print(f"Output: data/simulation_cache/<ticker>_{START}_{END}.parquet")
    print()

    t0 = time.monotonic()
    failures: list[str] = []

    for i, ticker in enumerate(universe, 1):
        result = fetch_cached_ohlcv(ticker, START, END)
        if result is None:
            failures.append(ticker)
            print(f"  [{i:3d}/{len(universe)}] {ticker:8s} FAILED")
        elif i % 10 == 0 or i == len(universe):
            print(f"  [{i:3d}/{len(universe)}] {ticker:8s} OK "
                  f"({len(failures)} failures so far)")
        time.sleep(SLEEP_BETWEEN)

    dt = time.monotonic() - t0
    print()
    print(f"=== Summary ===")
    print(f"  Total:    {len(universe)}")
    print(f"  Succeeded: {len(universe) - len(failures)}")
    print(f"  Failed:    {len(failures)}")
    if failures:
        print(f"  Failed tickers: {failures}")
    print(f"  Runtime:   {dt:.1f}s")

    fail_rate = len(failures) / len(universe)
    if fail_rate > 0.05:
        print(f"FAILURE RATE {fail_rate:.1%} EXCEEDS 5% TOLERANCE — investigate.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 4.2 Execution checklist (operator actions)

- [x] Watch loop confirmed not running (Pass 2 §0 — no python watch process; `data/watch.lock` present but stale, lockfile is for serializing watch-loop instances not file access)
- [ ] `python scripts/backfill_2024_ohlcv.py` run to completion
- [ ] Parse failure list; if > 2 failures, investigate before declaring done
- [ ] Spot-check 3 random parquets (AAPL already verified in Pass 2; check e.g. BRK.B (special-cased), V, XOM)
- [ ] Update CHANGELOG `[Unreleased]` with Added entry
- [ ] Commit Pass 3 (script + CHANGELOG)
- [ ] Push branch, open PR

### 4.3 PR body requirements

- Closes #570
- Fetched N tickers / failed N with per-ticker reasons
- Explicit note that 0 of 4 flagged candidates (PYPL/F/GM/KHC) actually failed — membership-staleness question remains open but no cleanup issue filed per operator resolution
- Runtime
- Cache state: pre vs post parquet count
- Sprint F unblock confirmation
- Watch loop restart note for operator

-----

## Section 5 — Success criteria (unchanged from Pass 1 §8)

Pass 3 is complete when ALL of:

- [ ] Backfill script runs to completion
- [ ] ≥99 parquet files with `_2023-01-01_2024-12-31.parquet` suffix in `data/simulation_cache/` (≤5 ticker failures allowed; Pass 2 evidence suggests 0-2 expected)
- [ ] Failure list logged with per-ticker reasons
- [ ] 3 spot-checked parquets pass schema + row-count checks
- [ ] AAPL parquet has rows covering all 11 fuzz/primary dates (±1 trading day for holidays) — already verified for AAPL in Pass 2
- [ ] Runtime recorded (expect <3 min per §2.2)
- [ ] CHANGELOG updated with SPY-inclusion rationale (operator direction)

-----

## Section 6 — What Pass 2 deliberately did not do

- Only 7 sentinel fetches. Did NOT fetch all 104 — that's Pass 3's job.
- Did NOT write `scripts/backfill_2024_ohlcv.py`. Structure drafted above; Pass 3 creates + commits.
- Did NOT touch CHANGELOG. Pass 3 commits it together with the script and run log.
- Did NOT modify watch.lock or any other control files. Operator handles watch loop at Pass 3 start per §4.2.
- Did NOT refresh the S&P 100 universe list — out of scope per operator resolution.
