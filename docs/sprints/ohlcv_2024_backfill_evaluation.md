# 2024 OHLCV backfill Pass 1 — Evaluation

**Branch:** `feat/backfill-2024-ohlcv`
**Issue:** #570
**Date:** 2026-04-20
**Prerequisites:** Sprint C.1 merged (`90f5806`), Sprint F parked at `53dee07` on `feat/port-ranker-to-spec`

-----

## TL;DR

- **Universe:** 102 S&P 100 tickers from `get_sp100_universe()` + `^VIX` + `SPY` = 104 tickers
- **Date range (PROPOSED — wider than prompt suggests):** `2023-01-01` → `2024-12-31` (24 months). **Reason:** SMA200 / 6-month RS calculations require ~200 trading days of lookback before the earliest fuzz date (2024-01-16). Full 2024 alone gives zero lookback → every fuzz date except late-2024 would fail feature computation. Flagged for operator review in Section 9.
- **Fetch pattern:** reuse existing `src/simulation/cache.py::fetch_cached_ohlcv(ticker, start, end)` — per-ticker save, parquet-per-range cache, no new abstractions (anti-goal respected).
- **Output:** 104 parquet files at `data/simulation_cache/<safe_ticker>_2023-01-01_2024-12-31.parquet`.
- **Runtime estimate:** 3-5 minutes (serial fetch, 0.5s spacing, ~104 tickers).
- **Failure tolerance:** ≤5% (5 tickers). Delisted / symbol-changed tickers logged + skipped.
- **Overwrite policy:** existing partials (8 ranged parquets for NKE/PG/^VIX) have different cache keys and remain untouched. New full-range parquets sit alongside them.

-----

## 1 — Ticker universe

### 1.1 Source of truth

`src/universe/sp100.py::get_sp100_universe()` — 102 hardcoded ticker strings, alphabetically sorted. Last verified 2025-03-24 per module docstring.

Full list (counted 102):

```
AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY
BRK.B C CAT CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR ETN
EXC F FDX GD GE GILD GM GOOG GOOGL GS HD HON IBM INTC INTU JNJ JPM KHC KO LIN
LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA
ORCL PEP PFE PG PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TXN UNH UNP
UPS USB V VZ WFC WMT XOM
```

**Note on count:** 102 > 100. S&P 100 includes GOOG and GOOGL as separate entries (Class A and Class C Alphabet shares). This is standard and matches the universe used by `rank_universe` and `compute_all_features`. Not a bug.

### 1.2 yfinance symbol mapping

`src/universe/sp100.py:15-17`:

```python
YFINANCE_TICKER_MAP = {
    "BRK.B": "BRK-B",
}
```

Single translation: Berkshire Class B uses `BRK-B` on yfinance instead of canonical `BRK.B`. The `to_yfinance_ticker()` helper in the same module handles this automatically — `fetch_cached_ohlcv` already calls it at line 52.

### 1.3 Additional tickers for Sprint F

Sprint F's byte-identity fuzz requires:

- **`^VIX`** — used by `compute_market_regime` (regime.py:107) for volatility classification. Required.
- **`SPY`** — used by `_classify_relative_strength` (engine.py:78-99) and all RS calculations. Required.

Both extend the fetch list. Existing `warm_cache` in cache.py (line 82-86) already fetches SPY + ^VIX alongside the universe — same pattern here.

**Final fetch list: 102 S&P 100 + `SPY` + `^VIX` = 104 tickers.**

### 1.4 Known-stale candidates (Pass 2 verifies)

The last-verified date on the universe list is 2025-03-24. A year has passed. Typical S&P 100 rebalance frequency: ~2-4 changes per year. Possible stale candidates (to check in Pass 2):

- `PYPL` — was removed from S&P 500 in 2025 per public reporting (affects S&P 100 membership if it was there)
- `F` / `GM` — cyclical auto stocks, historically volatile membership
- `KHC` — mid-cap now, sometimes drops out

Pass 2 will test-fetch 3-5 sentinel tickers against yfinance to catch symbol changes / delistings before the full run.

-----

## 2 — Existing fetch infrastructure

### 2.1 `src/simulation/cache.py::fetch_cached_ohlcv`

Core function (simulation/cache.py:40-61):

```python
def fetch_cached_ohlcv(ticker: str, start: str, end: str,
                        cache_dir: Path = CACHE_DIR) -> pd.DataFrame | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_ticker = ticker.replace(".", "_").replace("/", "_")
    cache_key = f"{safe_ticker}_{start}_{end}.parquet"
    cache_path = cache_dir / cache_key
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    try:
        data = yf.download(to_yfinance_ticker(ticker), start=start, end=end,
                           progress=False, auto_adjust=True)
        if data is not None and not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            data.to_parquet(cache_path)
            return data
    except Exception as e:
        logger.warning("[SIM-CACHE] Failed to fetch %s: %s", ticker, e)
    return None
```

**Key behaviors:**

- Safe-ticker conversion: `BRK.B` → `BRK_B` (filesystem-safe).
- **Per-call save at line 57** — if the script crashes mid-loop, all completed tickers are already persisted. No end-of-run flush. Satisfies the prompt's anti-crash-loss guardrail.
- MultiIndex column flattening at line 55-56 — yfinance sometimes returns OHLCV as `(OHLCV_column, ticker)` tuples; this flattens to single-level `{Open, High, Low, Close, Volume}`.
- `auto_adjust=True` — returns split-and-dividend-adjusted closes. Matches what `compute_features` expects.
- Cache key format: `{safe_ticker}_{start}_{end}.parquet`. Different date ranges produce different files → no conflict with existing 8 partial parquets in `data/simulation_cache/`.
- Returns `None` on any failure; never raises.

### 2.2 Why not use `warm_cache`

`warm_cache` (cache.py:64-87) iterates over a `scenarios` dict (from `simulation_engine.py`). Overkill for this sprint — we have a single date range, not 13 scenarios. A tight one-off script is simpler and keeps the scope focused.

### 2.3 Script location

**New:** `scripts/backfill_2024_ohlcv.py` — throwaway backfill script. Pattern-matches the existing `scripts/render_migrate.py` / `scripts/post_close_check.py` cadence of one-off maintenance scripts at the repo root's scripts/ directory.

Will be committed (not deleted post-execution) for reproducibility if the backfill needs to be re-run later.

-----

## 3 — Date range decision

### 3.1 Requirement from Sprint F fuzz dates

Sprint F's 10-date fuzz plus primary (`docs/sprints/sprint_F_evaluation.md` §4.3, which is currently on `feat/port-ranker-to-spec` but its date list is:

| # | Date | Day |
|---|---|---|
| — | 2024-03-26 | Tue (primary) |
| 1 | 2024-01-16 | Tue |
| 2 | 2024-02-20 | Tue |
| 3 | 2024-03-26 | Tue |
| 4 | 2024-04-23 | Tue |
| 5 | 2024-05-21 | Tue |
| 6 | 2024-06-25 | Tue |
| 7 | 2024-07-23 | Tue |
| 8 | 2024-09-10 | Tue |
| 9 | 2024-10-22 | Tue |
| 10 | 2024-11-19 | Tue |

Earliest fuzz date: **2024-01-16**.

### 3.2 Feature-computation lookback requirement

`compute_features` (engine.py:102-201) requires, for each ticker:

- **SMA200** (engine.py:122): 200 rolling days of closes.
- **SMA50** (engine.py:121): 50 rolling days.
- **RS 6m** (engine.py:147): 126 trading days of returns.
- **Pullback depth from 50-day high** (engine.py:161): 50 trading days.
- **ATR 14** (engine.py:169): 14 trading days of true range.

Bottleneck: **SMA200 requires 200 trading days before the fuzz date**.

200 trading days ≈ 282 calendar days (accounting for weekends + 10 market holidays).

For earliest fuzz date `2024-01-16`:
- 282 days back = `2023-04-09`

### 3.3 Proposed range: `2023-01-01` → `2024-12-31`

**Why 2023-01-01 (not 2023-04-09):**

1. Safety buffer — a few weeks of extra data costs nothing and protects against holidays / data gaps.
2. Round date — simpler cache key, simpler script.
3. SMA200 lookback for the 2024-01-16 fuzz date gets ~260 trading days — well over the 200 required.
4. Future Sprint F alternate dates in early January 2024 (if the 2024-01-16 candidate count is low) still have adequate lookback.

**Why 2024-12-31 (not just 2024-11-19):**

- Matches the prompt's "full calendar year" recommendation for 2024.
- Gives Sprint F flexibility to pick alternate fuzz dates later in Q4 if needed.
- Costs nothing marginal.

### 3.4 Cache-key implications

Cache key format: `{safe_ticker}_2023-01-01_2024-12-31.parquet`.

Example files after backfill:
- `data/simulation_cache/AAPL_2023-01-01_2024-12-31.parquet`
- `data/simulation_cache/BRK_B_2023-01-01_2024-12-31.parquet` (safe-ticker conversion)
- ... 102 more

Existing 8 partial parquets (NKE/PG/^VIX scenario-specific ranges) have DIFFERENT cache keys (`NKE_2024-04-26_2024-08-24.parquet` etc.) — they are preserved, not overwritten. Sprint F should use the full-range parquets; the partials remain for the existing `simulation_engine.py` scenarios.

### 3.5 Data volume estimate

- 104 tickers × ~252 trading days × 2 years = ~52,000 bars
- Parquet per ticker ≈ 15-30 KB (compressed, 6 columns × ~500 rows)
- Total disk: ~2-3 MB

Trivial. No concerns.

-----

## 4 — Batch plan

### 4.1 Constraints

- yfinance rate limit: undocumented but community consensus is ~2 req/sec sustained.
- No new fetch abstraction (anti-goal): must reuse `fetch_cached_ohlcv` as-is → single-ticker calls.
- Per-call save (already handled by `fetch_cached_ohlcv` line 57).

### 4.2 Proposed strategy

Serial loop over 104 tickers with 0.5-second sleep between fetches:

```python
import time
from src.simulation.cache import fetch_cached_ohlcv
from src.universe.sp100 import get_sp100_universe

START = "2023-01-01"
END = "2024-12-31"
EXTRA = ["SPY", "^VIX"]

universe = get_sp100_universe() + EXTRA
failures = []
for i, t in enumerate(universe, 1):
    result = fetch_cached_ohlcv(t, START, END)
    if result is None:
        failures.append(t)
    if i % 10 == 0:
        print(f"  Progress: {i}/{len(universe)} ({len(failures)} failures so far)")
    time.sleep(0.5)
```

### 4.3 Runtime estimate

- Fetch latency: 0.5-1.5s per ticker (yfinance HTTPS round trip + parsing)
- Sleep between fetches: 0.5s
- Total per ticker: ~1.5s average
- **104 tickers × 1.5s ≈ 156 seconds (~2.6 minutes)**

Under the 10-minute guardrail. Under the 5-minute sprint-prompt target.

### 4.4 Failure handling

Per-ticker try is already in `fetch_cached_ohlcv` — returns `None` on any exception (catches `yfinance.YFRateLimitError`, `yfinance.YFPricesMissingError`, network errors, delisting → empty DataFrame).

Script-level failure handling:
- Accumulate failed tickers in a list.
- Print running-tally progress every 10 tickers.
- At end, print summary + `data/simulation_cache/` file count.
- If `len(failures) / len(universe) > 0.05` (5%): raise SystemExit with non-zero code — operator investigates before declaring sprint done.

-----

## 5 — Overwrite / idempotency policy

### 5.1 Existing partials

Found in `data/simulation_cache/` (8 files):

| Ticker | Range | Source |
|---|---|---|
| NKE | 2024-04-26 → 2024-08-24 | simulation_engine.py scenario |
| NKE | 2024-07-26 → 2024-09-06 | simulation_engine.py scenario |
| PG | 2024-05-07 → 2024-09-04 | simulation_engine.py scenario |
| PG | 2024-08-06 → 2024-09-17 | simulation_engine.py scenario |
| ^VIX | 2024-01-01 → 2024-01-11 | simulation_engine.py scenario |
| ^VIX | 2024-07-01 → 2024-07-11 | simulation_engine.py scenario |
| ^VIX | 2024-07-19 → 2024-07-27 | simulation_engine.py scenario |
| ^VIX | 2024-07-30 → 2024-08-07 | simulation_engine.py scenario |

### 5.2 Behavior after backfill

- Each file above has a DIFFERENT cache key than this sprint's output (`{ticker}_2023-01-01_2024-12-31.parquet`).
- **No overwrites.** Partial scenario parquets remain untouched. `simulation_engine.py` continues to work with its scenario-specific ranges.
- New full-range parquets sit alongside them.

### 5.3 Re-run idempotency

If the script is re-run after partial completion (e.g., after a crash), `fetch_cached_ohlcv` at line 48 checks `cache_path.exists()` and returns the cached file without re-hitting yfinance. Only missing tickers get re-fetched. **Re-run is safe and efficient.**

If a ticker's parquet is known-bad and needs re-fetching: delete `data/simulation_cache/<ticker>_2023-01-01_2024-12-31.parquet` before re-running.

-----

## 6 — Validation / spot-checks (Pass 3)

After execution, verify:

1. **Count:** `ls data/simulation_cache/ | grep '_2023-01-01_2024-12-31\.parquet' | wc -l` — expect 104 minus failures.
2. **Per-ticker trading-day count:** for 3 random non-failed tickers, open parquet and assert `len(df) >= 490` (~2 years × 252 TD = 504; tolerance for holidays).
3. **OHLCV schema check:** assert columns `{Open, High, Low, Close, Volume}` present + all non-null on 5 sample rows.
4. **Date span check:** `df.index.min() <= 2023-01-10` and `df.index.max() >= 2024-12-20` (slack for first/last trading days).
5. **Sprint F date coverage:** for each of the 10 fuzz dates + 1 primary, confirm AAPL has a row on or near that date (±1 trading day for holidays).

These are manual queries in Pass 3, not unit tests (no new test file — scope exclusion in the sprint prompt).

-----

## 7 — Watch loop coexistence

### 7.1 Risk

`CLAUDE.md` notes that external writes to `data/simulation_cache/` can contend with the watch loop's reads. The prompt directs: "Stop watch loop before execution — data/simulation_cache/ writes could contend with watch loop reads. Restart after merge."

### 7.2 Pre-Pass-3 checklist (operator action)

Before running the backfill script:

```bash
# Check if watch loop is running
powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe' and CommandLine like '%watch%'\" | Select-Object ProcessId, CreationDate | Format-List"
```

If a PID shows:

```bash
taskkill /PID <pid> /F /T
rm data/watch.lock  # only if no watch process is running
```

### 7.3 Post-merge restart (operator action)

After the PR merges:

```bash
python -m src.main startup
```

-----

## 8 — Success criteria

Pass 3 is complete when ALL of:

- [ ] Backfill script `scripts/backfill_2024_ohlcv.py` runs to completion
- [ ] `data/simulation_cache/` has ≥99 parquet files with the `_2023-01-01_2024-12-31.parquet` suffix (≤5 ticker failures allowed)
- [ ] Failure list is logged with per-ticker reason (delisted / symbol-change / rate-limit / other)
- [ ] 3 spot-checked parquets pass column + row-count checks from §6
- [ ] AAPL parquet has a row within ±1 trading day of all 11 fuzz/primary dates
- [ ] Runtime recorded (expect <5 min)
- [ ] CHANGELOG updated (Unreleased entry)
- [ ] Watch loop not running during execution (per §7)

-----

## 9 — Open questions for operator before Pass 2

**1. Date range approval.** Prompt suggests `2024-01-01 → 2024-12-31`. Pass 1 proposes **`2023-01-01 → 2024-12-31`** due to SMA200 lookback (§3.2). Without the 2023 buffer, the earliest 7 of 11 Sprint F fuzz dates (2024-01-16 through 2024-06-25) cannot compute SMA200 and will fail feature computation — which would fail byte-identity fuzz for reasons unrelated to the port.

**Decision needed:** approve wider range (24 months) OR narrower range with accepted reduction in fuzz-date coverage.

**2. Universe-freshness verification scope.** Pass 1 flagged PYPL, F, GM, KHC as possibly-stale S&P 100 members (universe last verified 2025-03-24, a year ago). Pass 2 will test-fetch 3-5 sentinel tickers. Options:

- (a) Accept the hardcoded list as-is, flag any fetch failures as "may be delisted / not on S&P 100 in 2024" in the post-run log (Pass 1 recommendation).
- (b) Pass 2 cross-references current S&P 100 membership from an external source and updates `get_sp100_universe()` before fetching. **Out of scope per anti-goals** ("No expansion beyond S&P 100 — scope is tight"), but mentioning for completeness.

**Decision needed:** confirm (a) OR override.

**3. `SPY` inclusion.** Prompt scope says "S&P 100 universe + ^VIX" but `SPY` is required for RS calculations (§1.3). Pass 1 includes `SPY` on grounds of functional necessity — rank_universe fails without it. **Decision needed:** confirm SPY is in scope (Pass 1 recommendation) OR explicitly exclude.

-----

## 10 — Pass 2 handoff

Pass 2 will (conditional on §9 decisions):

1. Test-fetch 3 sentinel tickers (AAPL, GOOGL, MSFT) against yfinance for the 2023-01 sample date range — verify yfinance returns data, verify schema, verify column names.
2. Spot-check the 3-5 possibly-stale tickers from §1.4 — do they return data for 2024-12? If any returns empty, note as expected failure in Pass 3 log.
3. Confirm runtime estimate (§4.3) with a 5-ticker miniature run.
4. Finalize failure-rate tolerance per universe size (if e.g. 3 tickers confirmed-delisted in §2, tolerance adjusts from 5/104 to 2/104 of the remaining).
5. Write `docs/sprints/ohlcv_2024_backfill_research.md` with empirical evidence.

-----

## 11 — What Pass 1 deliberately did not do

- No yfinance calls from Pass 1 (research only — Pass 2 does the sentinel fetches).
- No scripts written (Pass 3 creates `scripts/backfill_2024_ohlcv.py`).
- No changes to `src/universe/sp100.py` (universe list stays as-is — refresh is a separate maintenance task).
- No changes to `src/simulation/cache.py` (reuses existing function per anti-goal).
- No watch loop actions taken (operator does this at Pass 3 start).
- No CHANGELOG edits (Pass 3 commits them alongside the script + run output).

-----

## 12 — Anti-goals compliance

- ✓ No schema changes.
- ✓ No new fetch abstractions — reuses `fetch_cached_ohlcv`.
- ✓ No retry logic for delisted tickers — log + skip via existing `fetch_cached_ohlcv` return-`None` pattern.
- ✓ No expansion beyond S&P 100 (+ mandatory `SPY`/`^VIX` market context — §1.3 justifies).
- ✓ No fetching pre-2023-01-01 data. **Deviation:** fetches 2023 (not just 2024) for SMA200 lookback — flagged for operator approval in §9.
