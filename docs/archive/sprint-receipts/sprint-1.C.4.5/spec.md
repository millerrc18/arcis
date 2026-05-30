# Sprint 1.C Phase 4.5 — Corpus Generator + Backtester Fetch-Period Bugs

**Tracker:** task #104
**Status:** Stage 1 walkforward structural blocker. Found pre-flight by operator running §B2 admissibility gates #8 + #9 on 2026-04-29.
**Branch:** `fix/104-corpus-backtester-fetch-period`
**Base:** `sprint/1.C.4.5/base` (off `origin/main` @ `5ae190a`)

## Pre-fix evidence (operator console output, 2026-04-29)

```
mille@SWIFT-PC C:\arcis\halcyon-lab>scripts\smoke_gate_8_dry_run.bat
2026-04-29 10:44:26,180 INFO [__main__] [CORPUS] stage1-smoke: enumerating decision points (window=2024-01-01..2024-01-31, folds=None, max=100)
2026-04-29 10:44:27,609 INFO [__main__] [CORPUS] 100 decision points enumerated
2026-04-29 10:44:27,824 INFO [src.evaluation.corpus_generator] [CORPUS] stage1-smoke: 0 entries, 0 parse-failures (0.00%), admissibility=PASS
2026-04-29 10:44:27,825 INFO [__main__] [CORPUS] Wrote corpus to data\corpus\stage1-smoke

mille@SWIFT-PC C:\arcis\halcyon-lab> scripts\smoke_gate_9_fold1.bat
2026-04-29 10:44:49,460 INFO [__main__] [CORPUS] stage1-fold1: enumerating decision points (window=2023-09-01..2026-04-28, folds=[1], max=None)
2026-04-29 10:44:50,914 INFO [__main__] [CORPUS] 8476 decision points enumerated
2026-04-29 10:44:50,915 INFO [__main__] [CORPUS] Computing features for 83 unique dates
2026-04-29 10:44:54,255 ERROR [yfinance]
1 Failed download:
2026-04-29 10:44:54,256 ERROR [yfinance] ['ATVI']: YFPricesMissingError('possibly delisted; no price data found  (period=3y) (Yahoo error = "No data found, symbol may be delisted")')
2026-04-29 10:44:54,430 WARNING [src.data_ingestion.market_data] No data for ATVI
2026-04-29 10:44:56,425 INFO [src.evaluation.corpus_generator] [CORPUS] stage1-fold1: 0 entries, 0 parse-failures (0.00%), admissibility=PASS
2026-04-29 10:44:56,426 INFO [__main__] [CORPUS] Wrote corpus to data\corpus\stage1-fold1
```

Manifest: `total_decision_points=0`, admissibility=PASS (vacuous — 0/0 = 0%).

## Bug A — Corpus dry-run skips feature computation

**File:** `scripts/generate_llm_corpus.py:232-235`

```python
features_by_date: dict[str, dict[str, dict]] = {}
if not args.dry_run and decision_points:  # BUG
    logger.info("[CORPUS] Computing features for %d unique dates", ...)
    features_by_date = _compute_features_for_window(decision_points)
```

But `src/evaluation/corpus_generator.py:_generate_one_entry` always needs `feat` — even the dry-run path calls `_build_feature_prompt(feat, ticker)` to compute `prompt_sha256`. Every dry-run entry hits `feat is None` and is silently skipped.

**Fix:** drop the `not args.dry_run` guard. The "dry" in dry-run means "no LLM call" (per `_dry_run_entry` placeholder), not "no feature pipeline".

## Bug B — Corpus fetch period too narrow for early folds

**File:** `scripts/generate_llm_corpus.py:193-194`

```python
ohlcv = fetch_ohlcv(universe, period="3y")
spy = fetch_spy_benchmark(period="3y")
```

`period="3y"` returns yfinance data from `today - 3y` (today=2026-04-29 → 2023-04-29 onward). Fold 1 test_start = 2023-09-01, but `slice_to_date` enforces a 200-trading-day minimum (`if len(sliced) < 200: continue`). For as_of=2023-09-01 the slice returns ~88 trading days — every ticker filtered out → empty `ohlcv_dict` → `compute_all_features` returns `{}` → 0 features by date.

## Bug C — Backtester fetch period anchored to wrong end

**File:** `src/evaluation/backtester.py:111-126`

```python
if test_start and test_end:
    start_date = datetime.fromisoformat(test_start)
    end_date = datetime.fromisoformat(test_end)
else:
    end_date = datetime.now() - timedelta(days=20)
    start_date = end_date - timedelta(days=months * 30)

window_days = max((end_date - start_date).days, 1)
fetch_period_days = window_days + 60  # BUG
ohlcv = fetch_ohlcv(universe, period=f"{fetch_period_days}d")
spy = fetch_spy_benchmark(period=f"{fetch_period_days}d")
```

yfinance `period=` always fetches BACK from today. For fold-1 (test_start=2023-09-01, test_end=2024-01-01, today=2026-04-29):
- `window_days` = 122
- `fetch_period_days` = 182d
- yfinance returns data from **2025-10-29 → 2026-04-29** (last 182 days)
- Test span **2023-09-01 → 2024-01-01** is 789 days BEFORE the fetched window
- Every `slice_to_date(date_str_in_test_span)` returns 0 rows
- Result: fold 1-7 silently produce 0 trades; only fold 8 has data

Introduced by PR #831's review fix that added `test_start`/`test_end` parameters but didn't update the period calc.

## Methodology constraints

1. **PIT cleanliness is enforced at SLICE time, not fetch time.** `slice_to_date` strictly truncates `df.index <= cutoff`. Fetching wider data is methodologically FINE.
2. **Pre-reg addendum 1 §A1 makes NO commitments about fetch period.** This fix does NOT require pre-reg amendment.
3. **Cost calibration (Wave C #79) and risk-free rate (Wave C #80)** wiring in backtester must continue to work post-fix.
4. **Per pre-reg §5.3** operator must be present for the official Stage 1 backtest. **DO NOT RUN walkforward in this PR.** Only fix blockers and run smokes.

## Proposed fix shape

Two reasonable paths — architect/developer picks:

**Path 1** — Add date-bounded params to `fetch_ohlcv` (more robust, future-proof):
```python
def fetch_ohlcv(tickers, period="1y", start=None, end=None) -> dict[str, pd.DataFrame]:
    if start or end:
        raw = yf.download(download_tickers, start=start, end=end, ...)
    else:
        raw = yf.download(download_tickers, period=period, ...)
```

**Path 2** — Compute `fetch_period_days` correctly (smaller diff):
```python
fetch_period_days = (today - earliest_as_of).days + 280  # 200 trading days + buffer
```

## Sibling-search (REQUIRED — operator's strict rigor rule)

After fix, GREP for these patterns:

1. `fetch_ohlcv\(.*period=` — every caller
2. `slice_to_date` — every caller (verify fetch covers slice range)
3. `fetch_period_days` — every site
4. `period=f"{.*}d"` and `period="\dy"` — dynamic + hardcoded

Known callers (most are fine — live use):
- `src/services/mr_scan_service.py:53` (period="1y", live scan — OK)
- `src/risk/price_utils.py:35` (period="5d", live)
- `src/shadow_trading/reconcile.py:156, 174` (period="5d", live)
- `src/evaluation/backtester.py:125` (THE BUG)
- `scripts/generate_llm_corpus.py:193` (THE BUG)

Document each callsite's correctness in PR description with reasoning.

## Regression tests (MANDATORY)

1. **`tests/evaluation/test_corpus_generator.py`** — `test_dry_run_writes_entries_for_past_window`: call `generate_corpus(corpus_id='test', decision_points=[(d, 'AAPL'), ...], features_by_date={d: {'AAPL': {...}}}, dry_run=True, ...)` for past dates. Assert manifest's `total_decision_points > 0`. Tests Bug A.

2. **`tests/test_backtester.py`** — `test_backtest_model_produces_trades_for_old_test_window`: mock `fetch_ohlcv` to return realistic 5y of synthetic ohlcv covering 2021-01 through 2026-04. Call `backtest_model(test_start='2023-09-01', test_end='2024-01-01')`. Assert `len(result['trades']) > 0`. Without Bug C fix, this test should fail. Tests Bug C.

3. **`tests/evaluation/test_walkforward.py`** — Add or augment a smoke test that exercises all 8 folds against a synthetic fixture and asserts each non-underpowered fold has trades.

CLAUDE.md baseline: 3682 tests. Post-fix should be ≥3685.

## Scope fence

Allowed files:
- `scripts/generate_llm_corpus.py`
- `src/evaluation/backtester.py`
- `src/data_ingestion/market_data.py` (only if Path 1 chosen)
- `tests/evaluation/test_corpus_generator.py`
- `tests/test_backtester.py`
- `tests/evaluation/test_walkforward.py` (if test 3 added there)
- `CHANGELOG.md`
- `.claude/agent-scope.json`

If sibling-search finds another bug, surface to PM (do NOT bundle).

## Receipts required

- Pre-fix smoke output (above)
- Post-fix dry-run smoke output (should show 100 decision_points, 0 parse-failures since dry-run uses placeholder)
- Sibling-search results (every fetch_ohlcv callsite + correctness reasoning)
- `python -m pytest tests/ -q --timeout=60` output (≥3685)
- `python -m pytest tests/test_repo_structure.py -v` output (per CLAUDE.md disclosure rule)
- Mini-replication of Bug C: a one-liner showing `fetch_period_days=182, fetch_starts_at=2025-10-29, test_span=2023-09-01..2024-01-01` proving fetch window is 789 days after test span pre-fix

## Branch + PR conventions

- Branch: `fix/104-corpus-backtester-fetch-period`
- PR title: `fix(#104): corpus dry-run + backtester fetch-period anchor (Stage 1 blocker)`
- Link: task #104, ref pre-reg addendum 1 §A1

## Worktree discipline

Use `isolation: "worktree"` per CLAUDE.md parallel-agent rule. `.env` is gitignored — won't carry into worktree (memory: feedback_worktree_env_drift). Use hermetic test fixtures, no env-var deps.

## Done definition

- [ ] All 3 bugs fixed
- [ ] Path 1 vs Path 2 architectural choice documented
- [ ] Sibling-search documented in PR body
- [ ] 3 regression tests added
- [ ] Test baseline preserved (≥3685)
- [ ] CHANGELOG.md updated under [Unreleased]
- [ ] Pre-fix and post-fix smoke outputs in PR body
- [ ] PR pushed, CI green
- [ ] **DO NOT MERGE** — operator review pending
