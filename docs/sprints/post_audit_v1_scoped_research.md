# Pass 2 — v0.26.2-scoped research & verification (#539)

**Branch:** `feat/post-audit-ruleset-v1-scoped`
**Date:** 2026-04-19
**Predecessor:** `docs/sprints/post_audit_v1_scoped_evaluation.md` (Pass 1)

## Objective

Verify four Pass 1 claims by reading code + running probes. Amend Pass 1 if findings change the implementation plan.

## 1. R8 firewall behavior — empirically verified

Ran `validate_derived_from()` against 4 spec shapes:

| Test | Shape | Result |
|---|---|---|
| 1 | full dict, `source_trade_ids` omitted | ✓ ACCEPTED |
| 2 | full dict, `source_trade_ids: None` | ✗ rejected (`R8ViolationError`) |
| 3 | `derived_from: None` (lazy_prices case) | ✓ ACCEPTED |
| 4 | full dict, `source_trade_ids: []` (empty list) | ✓ ACCEPTED |

Reading at `src/platform/rigor/walkforward_firewall.py:129-135`:

```python
if "source_trade_ids" in df:
    sti = df["source_trade_ids"]
    if not isinstance(sti, list) or not all(isinstance(x, str) for x in sti):
        raise R8ViolationError(...)
```

Key-membership check via `in` — omission (key-absence) passes silently; `None` value is not a list and fails the `isinstance` check.

**Plan confirmed:** omit the key entirely in `post_audit_ruleset_v1.yaml`. Do not emit `source_trade_ids: null`.

## 2. SECTOR_MAP coverage for Defensive sectors

Ran `Counter(SECTOR_MAP.values())` on current `src/universe/sectors.py`:

| GICS Sector | Ticker count |
|---|---|
| Financials | 18 |
| Technology | 16 |
| Health Care | **14** |
| Industrials | 14 |
| Communication Services | 10 |
| Consumer Discretionary | 10 |
| Consumer Staples | **10** |
| Utilities | **4** |
| Energy | 3 |
| Real Estate | 2 |
| Materials | 1 |

Defensive universe = `{Consumer Staples ∪ Utilities ∪ Health Care}` = **28 tickers** (28% of S&P 100 current membership).

Defensive tickers: `ABBV, ABT, AMGN, BMY, CL, COST, CVS, DHR, DUK, EXC, GILD, JNJ, KHC, KO, LLY, MDLZ, MDT, MO, MRK, NEE, PEP, PFE, PG, PM, SO, TMO, UNH, WMT`.

**Plan impact:** v0.25.3 baseline had 20 trades across 5 windows on the full S&P 100. A 28% subset gives an upper-bound estimate of ~5-6 trades across 5 windows — even more marginal than Pass 1 predicted 4-5. INCONCLUSIVE_DATA highly likely on all 5 windows.

**Note:** `SECTOR_MAP` is a static current-membership map, not point-in-time. `walkforward_universe.resolve_universe_size()` uses `sp100_historical_constituents` for point-in-time universe resolution. The sector filter is applied AFTER event-row query, so the interaction is:
1. Event rows fetched for all tickers in spec.universe.tickers (static list)
2. Sector filter removes rows whose `SECTOR_MAP[ticker]` is not in allowed sectors

This is not point-in-time sector mapping — if a ticker's sector changed historically, we use its current GICS. Acceptable for MVP; flagged as out-of-scope for this sprint.

## 3. Integration points — confirmed

### Sector filter → `_query_event_rows` (signal_eval.py:108-145)

Current code:
```python
def _query_event_rows(spec: StrategySpec, cfg) -> list[dict]:
    tickers = _resolve_universe(spec.universe.get("tickers", []))
    if not tickers:
        return []
    ...
    sql = f"SELECT * FROM {table} WHERE ticker IN ({placeholders_t}) AND form_type IN (...) AND filing_date BETWEEN ? AND ?"
```

Insertion between lines 118 and 119:

```python
tickers = _resolve_universe(spec.universe.get("tickers", []))
sector_filter = spec.universe.get("sector_filter")
if sector_filter:
    from src.universe.sectors import SECTOR_MAP
    tickers = [t for t in tickers if SECTOR_MAP.get(t) in sector_filter]
if not tickers:
    return []
```

Filter narrows the ticker list BEFORE the SQL `IN (...)` clause — efficient (smaller SQL, smaller result set).

### Event exclusion → `_run_event_driven` (backtest_engine.py:327-347)

Current code:
```python
filing_date = row["filing_date"]
...
after = df[df.index > pd.Timestamp(filing_date)]
if after.empty:
    continue
first_bar = after.iloc[0]
entry_ts = after.index[0]
entry_iso = entry_ts.strftime("%Y-%m-%d")
history_df = df[df.index < entry_ts]
trade = _build_trade(cfg, ticker, entry_iso, entry_price, spec.exit, history_df, metadata=...)
```

Insertion between computing `entry_iso` and calling `_build_trade`:

```python
# Event-exclusion filter (post-audit ruleset v1 schema extension)
exclude_cats = (spec.entry.get("event_exclusion") or {}).get("categories", [])
if exclude_cats:
    from src.diagnostics.known_events import is_known_event
    if any(is_known_event(entry_iso, category=c) for c in exclude_cats):
        continue
```

Clean drop-in; no refactor of surrounding code. Keeps `_build_trade` pure.

## 4. `is_known_event` date semantics

Reading at `src/diagnostics/known_events.py:302-319`:

```python
def is_known_event(date_str: str, category: str | None = None) -> bool:
    label = KNOWN_EVENTS.get(date_str)
    if label is None:
        return False
    if category is None:
        return True
    return EVENT_CATEGORIES.get(label) == category
```

- Date format: ISO-8601 `YYYY-MM-DD` string
- Returns False for unknown dates (safe default — never over-excludes)
- Category filter matches exactly against `EVENT_CATEGORIES[label]`

The `entry_iso` value in `_run_event_driven` is `entry_ts.strftime("%Y-%m-%d")` — same format. Drop-in compatible.

Trade Policy dates in `KNOWN_EVENTS` (v0.25.1 backfill, 2019-2024 window):
- 2019-10-11 (TARIFF_PAUSE)
- 2019-12-12 (TARIFF_ANNOUNCEMENT)
- 2022-02-24 (SANCTIONS_INITIAL)
- 2022-03-08 (SANCTIONS_ESCALATION)
- 2022-07-27 (INDUSTRIAL_POLICY)
- 2022-08-09 (INDUSTRIAL_POLICY)
- 2022-10-07 (EXPORT_CONTROLS)
- 2023-12-18 (TRADE_DISRUPTION)
- 2024-05-14 (TARIFF_ESCALATION)

Any of these hit as an entry date → trade skipped. Expected to eliminate 0-1 trades total in a post-audit run (one of the v0.25.3 baseline filings could land on one of these; most don't).

## 5. `_query_event_rows` empty-result behavior

Pass 1 flagged: confirm `_run_event_driven` doesn't crash if `_query_event_rows` returns `[]` after sector filter narrows to zero.

Reading at `backtest_engine.py:298-352`:

```python
def _run_event_driven(cfg: BacktestConfig) -> list[BacktestTrade]:
    spec = cfg.strategy
    signal = spec.entry.get("signal", [])
    combinator = spec.entry.get("combinator", "all")
    rows = _query_event_rows(spec, cfg)
    ...
    trades: list[BacktestTrade] = []
    for row in rows:
        ...
    return trades
```

If `rows == []`, the for-loop skips entirely and returns `trades = []`. Clean.

Downstream `run_backtest` handles zero-trades case correctly — no division by zero in metrics (confirmed during v0.25.3 read of the walk-forward runner, which tolerates 1-trade windows via `mde_value = inf`).

## 6. Delta from Pass 1

Pass 1 plan stands. No changes to:
- Schema shape (2 optional fields)
- Integration points (both confirmed with exact line numbers)
- Test plan (4 test files, 11 tests total)
- Outcome hypothesis (INCONCLUSIVE_DATA on all 5 windows; <20 trades total)

Amendment: trade-count estimate tightened from "4-5" (Pass 1) to "5-6" (Pass 2) based on 28-ticker Defensive universe × 20 baseline ≈ 5.6. Still well below `min_trades_per_window=10` on any window.

## 7. Pass 3 implementation checklist

Order of operations:

1. **Schema validators** in `strategy_spec.py:validate_spec()` — add `_validate_sector_filter(...)` and `_validate_event_exclusion(...)`
2. **Sector filter** in `signal_eval.py:_query_event_rows()` — insert filter between `tickers = _resolve_universe(...)` and the early-return on empty
3. **Event exclusion** in `backtest_engine.py:_run_event_driven()` — insert check between computing `entry_iso` and calling `_build_trade`
4. **Spec file** `src/platform/specs/post_audit_ruleset_v1.yaml` — derived from lazy_prices_v1.yaml with 2 new fields and the R8(a) forensic-audit block
5. **Tests** — 4 new test files per Pass 1 plan
6. **Walk-forward run** — `python -m scripts.backtest.run_walkforward --strategy post_audit_ruleset_v1 --json`
7. **Validation doc** — `docs/validation/post-audit-v1-scoped-walkforward-2026-04-20.md`
8. **Cycle summary** — `docs/validation/v0.26-cycle-summary.md`
9. **CHANGELOG + MASTER.md + RELEASES.md** entries
10. **Local CI green** — `scripts/run_ci_locally.ps1`
