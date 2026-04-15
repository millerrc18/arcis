# Sprint: Alpha Attribution Resolver Hardening

**Branch:** `feat/attribution-resolver`
**Priority:** HIGH — GPU priority #1, existential question ("does the LLM add alpha?")
**Estimated time:** 2-3 hours
**Prerequisite:** The resolver (`src/attribution/logger.py::resolve_pending_outcomes`) already exists and is correct. The time window was widened in v0.17.2 from 5min to 7hrs. This sprint hardens it for the 1,825-pair backlog.

---

## Pre-flight

- [ ] Read MASTER.md (root)
- [ ] Read `src/attribution/logger.py` (existing resolver + simulate_mechanical_outcome)
- [ ] Read `src/scheduler/watch.py` lines 1394-1406 (time window trigger)
- [ ] Run existing tests: `python -m pytest tests/ -x -q`

---

## Context

The attribution system has 1,825 logged pairs with `ranker_only_outcome = 'pending'`. The resolver downloads historical price data via yfinance and simulates mechanical bracket outcomes. It works but has never run because the watch loop crashed before its execution window.

**Problem:** Processing 1,825 pairs sequentially, each with a yfinance download, will take ~30-60 minutes and may hit rate limits. No progress logging, no batching, no resume capability.

---

## Task 1: Add batching + throttle to `resolve_pending_outcomes`

Current code processes ALL pending pairs in one call. Change to:

```python
def resolve_pending_outcomes(db_path: str = DB_PATH, batch_size: int = 50) -> int:
```

- Process `batch_size` pairs per call (default 50)
- Add 0.5s sleep between yfinance downloads to avoid rate limiting
- Log progress every 10 pairs: `[ATTRIBUTION] Resolved 10/50 batch (running total: 120)`
- Return count resolved this batch
- The watch loop calls it repeatedly until all are done or time runs out

**Why batch:** If the loop crashes mid-resolve, the next restart picks up where it left off (already-resolved pairs have outcome != 'pending').

---

## Task 2: Handle yfinance edge cases

The current resolver skips pairs where `data.empty`. Add handling for:

- **Multi-level column headers:** yfinance sometimes returns MultiIndex columns. Flatten with `data.columns = data.columns.get_level_values(0)` before processing.
- **Missing OHLCV columns:** Some tickers may return partial data. Check for 'High', 'Low', 'Close' existence before simulation.
- **Rate limit (429):** Catch `HTTPError` and sleep 60 seconds before retrying.
- **Weekend/holiday scan dates:** If `scan_timestamp` is a Friday, start the bracket simulation on Monday. Use `pd.bdate_range` or skip weekend dates.
- **Stale pairs (>30 days old):** For very old pairs, yfinance data is definitely available. Prioritize resolving oldest pairs first (`ORDER BY scan_timestamp ASC`).

---

## Task 3: Add McNemar's test for final comparison

Once enough pairs are resolved, compute the alpha test. Add to `src/attribution/logger.py`:

```python
def compute_alpha_attribution(db_path: str = DB_PATH) -> dict:
    """Compute McNemar's test: does the LLM add alpha vs ranker-only?
    
    Requires ≥50 resolved pairs where the LLM took the trade AND the
    ranker-only outcome is also resolved (concordant/discordant pairs).
    """
```

Returns:
```python
{
    "n_resolved": int,
    "ranker_win_rate": float,
    "llm_win_rate": float,
    "concordant": int,      # both won or both lost
    "discordant_llm_better": int,  # LLM won, ranker lost
    "discordant_ranker_better": int,  # ranker won, LLM lost
    "mcnemar_chi2": float | None,
    "mcnemar_pvalue": float | None,
    "verdict": str,  # "llm_adds_alpha", "no_difference", "insufficient_data"
}
```

McNemar's test formula:
```python
b = discordant_llm_better  
c = discordant_ranker_better
chi2 = (abs(b - c) - 1) ** 2 / (b + c) if (b + c) > 0 else 0
# Compare to chi2 distribution with 1 df: p < 0.05 = significant
```

---

## Task 4: Expose results on attribution dashboard

Update the cloud endpoint `/api/attribution/stats` to include:
- `resolved_count`: number of resolved pairs
- `ranker_win_rate`: from resolved pairs
- `llm_win_rate`: from resolved pairs  
- `mcnemar_result`: output of `compute_alpha_attribution()`
- `resolution_progress`: `f"{resolved}/{total} ({resolved/total*100:.0f}%)"`

---

## Task 5: Add progress logging with Loki ctx tags

```python
logger.info(
    "[ATTRIBUTION] Batch resolved: %d/%d (total: %d/%d)",
    batch_resolved, batch_size, total_resolved, total_pending,
    extra={"ctx": {"event": "attribution_batch", "resolved": total_resolved, "pending": total_pending}}
)
```

---

## Task 6: Tests

4 tests:
1. `test_simulate_mechanical_outcome_win` — price hits target before stop
2. `test_simulate_mechanical_outcome_loss` — price hits stop first
3. `test_simulate_mechanical_outcome_timeout` — neither hit in 7 days
4. `test_resolve_returns_none_on_empty` — no pending pairs returns 0

---

## Constraints

- Do NOT change the pair logging (Phase 1/2) — it works fine
- yfinance downloads must have 0.5s minimum delay between calls
- Batch size default 50 — configurable but not above 200 per call
- The resolver must be idempotent — safe to call multiple times
- No new dependencies
- `resolve_pending_outcomes` must never crash the watch loop

## Commit Message

```
feat(attribution): batch resolver + McNemar's test for alpha attribution

- Batched resolution (50 pairs/call) with 0.5s throttle
- yfinance edge case handling (MultiIndex, missing cols, rate limits)
- McNemar's chi-squared test for LLM vs ranker-only comparison
- Progress logging with Loki ctx tags
- Cloud endpoint updated with resolution progress + test results
- 4 tests (win/loss/timeout simulation, empty pending)
```

---

## Ralph Loop Findings

### Pass 1 — Done flag blocks backlog clearing
The watch loop sets `_attribution_resolution_done = True` after the first successful batch call. With batch_size=50, it resolves 50 of 1,825 and stops. 37 days to clear the backlog.

**Fix:** Change watch.py trigger: only set `_attribution_resolution_done = True` when `resolve_pending_outcomes()` returns 0 (nothing left to resolve). While it returns > 0, keep calling it each watch loop cycle. Add a safety cap: max 5 batch calls per evening (250 pairs/day, clears backlog in 8 days).

```python
# In watch.py attribution block:
if not self._attribution_resolution_done:
    resolved = resolve_pending_outcomes(batch_size=50)
    if resolved == 0:
        self._attribution_resolution_done = True
    self._attribution_batches_today = getattr(self, '_attribution_batches_today', 0) + 1
    if self._attribution_batches_today >= 5:
        self._attribution_resolution_done = True  # cap for today
```

### Pass 2 — Group downloads by ticker to eliminate redundancy
1,825 pairs across ~102 S&P 100 tickers = ~18 pairs per ticker on average. Each pair triggers a separate yfinance download for overlapping date ranges. Massive waste.

**Fix:** Restructure `resolve_pending_outcomes` to:
1. Group all pending pairs by ticker
2. For each ticker, find min(scan_timestamp) and max(scan_timestamp) + 8 days
3. Download OHLCV once for that full date range
4. Simulate all pairs for that ticker from the cached data
5. This reduces ~1,825 downloads to ~102 (one per ticker), completing in ~1 minute vs 15 minutes

```python
# Pseudocode for ticker-grouped resolution
pending_by_ticker = defaultdict(list)
for row in pending:
    pending_by_ticker[row["ticker"]].append(row)

for ticker, pairs in pending_by_ticker.items():
    # Download once for the full date range
    min_date = min(p["scan_timestamp"][:10] for p in pairs)
    max_date = max(p["scan_timestamp"][:10] for p in pairs)
    data = yf.download(ticker, start=min_date, end=max_date + 8d)
    
    # Simulate each pair from the cached data
    for pair in pairs:
        pair_start = pair["scan_timestamp"][:10] + 1 business day
        pair_data = data[pair_start : pair_start + 7 business days]
        outcome = simulate_mechanical_outcome(...)
```

### Pass 3 — Two separate statistical tests, not one McNemar
McNemar's test only applies to "both_taken" pairs (LLM agreed with ranker). These are concordant/discordant pairs where BOTH portfolios had a position.

For "llm_rejected" pairs (ranker would take, LLM passed), the test is different: simple binomial — "what fraction of rejected trades were actually winners?" If the LLM correctly rejects losers, the rejection rate among losers should be higher than among winners.

**Fix:** `compute_alpha_attribution` should return two tests:
1. **McNemar (both_taken pairs):** Does the LLM's conviction filtering improve win rate on trades it DOES take?
2. **Rejection accuracy (llm_rejected pairs):** Does the LLM correctly identify which trades to skip? Metric: `rejected_loser_rate = rejected_losers / total_rejected`. If > 50%, the LLM adds value by filtering.

```python
{
    "mcnemar_test": {  # Only both_taken pairs
        "n_pairs": int,
        "llm_win_rate": float,
        "ranker_win_rate": float,
        "chi2": float,
        "pvalue": float,
        "verdict": "llm_adds_alpha" | "no_difference" | "insufficient"
    },
    "rejection_accuracy": {  # Only llm_rejected pairs  
        "n_rejected": int,
        "would_have_won": int,
        "would_have_lost": int,
        "rejection_accuracy": float,  # would_have_lost / n_rejected
        "verdict": "good_filter" | "destroying_alpha" | "insufficient"
    }
}
```
