# Strategy Research Platform — Activation Guide

This guide walks the operator through activating a research strategy on the Strategy Research Platform end-to-end. As of v0.24.0, the platform can:

1. Evaluate a strategy historically via `scripts/run_backtest.py`
2. Persist backtest results + promotion events to SQLite
3. Pass statistical gates (DSR ≥ 0.95 + PBO ≤ 0.5 + OOS efficiency ≥ 0.3)
4. Shadow-trade a promoted strategy on a **second Alpaca paper account**, isolated from swing
5. Halt a strategy cleanly (close positions without touching swing or other research strategies)
6. Surface everything in the `/research-platform` dashboard page

## 1. Write the strategy spec

Create `src/platform/specs/<strategy_id>.yaml` following `docs/specs/strategy-schema.md`. For event-driven strategies like Lazy Prices, declare:

```yaml
strategy_id: my_strategy_v1
display_name: My Strategy
universe:
  tickers: sp100
entry:
  kind: event_driven
  event_table: edgar_filings
  event_filter:
    form_type: [10-K, 10-Q]
    filing_date_within_days: 5
  signal:
    - metric: cosine_similarity
      target: item_1a
      reference: prior_year_same_form
      operator: less_than
      threshold: 0.75
  combinator: any
exit:
  kind: mechanical
  timeout_days: 21
  stop: {method: atr_based, atr_period: 14, multiplier: 3.0, floor_pct: 0.05, cap_pct: 0.12}
  target: {method: atr_based, atr_period: 14, multiplier: 6.0, floor_pct: 0.10, cap_pct: 0.25}
position_sizing:
  method: fixed_pct_equity
  pct: 0.15
attribution:
  benchmark: SPY_matched_window
  metrics: [raw_sharpe, excess_sharpe, win_rate, profit_factor, max_drawdown]
```

For Python-plugin strategies, see `src/platform/strategy_plugin.py` — register a class with `@register_plugin`.

## 2. Register the strategy

```python
from src.platform.promotion import register_strategy
register_strategy(
    strategy_id="my_strategy_v1",
    display_name="My Strategy",
    spec_source="yaml:src/platform/specs/my_strategy_v1.yaml",
    spec_hash="<sha256 of spec>",
    db_path=DB_PATH,
)
```

Initial status: `proposed`.

## 3. Run a backtest

```
python scripts/run_backtest.py \
    --strategy my_strategy_v1 \
    --start 2020-01-01 \
    --end 2024-12-31 \
    --with-walkforward
```

`--with-walkforward` populates `backtest_results.oos_efficiency`. For PBO population, run a parameter-sweep campaign (v0.24.1 driver — tracked separately).

## 4. Auto-promotion to `backtested`

On first successful backtest, `promote(strategy_id, 'backtested', triggered_by='auto_gate')` fires automatically. No gate — automatic transition.

## 5. Manual promotion to `shadow_trading`

Requires **all three rigor gates green**:
- DSR ≥ 0.95
- PBO ≤ 0.50 (requires a param sweep)
- OOS_efficiency ≥ 0.30

If all pass, promote via:

```python
from src.platform.promotion import promote
promote(
    strategy_id="my_strategy_v1",
    target_status="shadow_trading",
    triggered_by="manual",
    justification_note="<at least 40 characters explaining rationale>",
)
```

OR via the dashboard: `POST /api/platform/promotions`.

### Before first shadow_trading promotion — Operator prerequisites

1. Create a **second Alpaca paper account** distinct from swing
2. Set env vars on the NSSM service:
   ```
   nssm set ArcisWatchLoop AppEnvironmentExtra ALPACA_RESEARCH_API_KEY=...
   nssm set ArcisWatchLoop AppEnvironmentExtra ALPACA_RESEARCH_API_SECRET=...
   ```
3. Flip `desks.research.enabled: true` in `config/settings.local.yaml`
4. Restart watch loop → `verify_accounts_distinct()` runs at first ShadowHarness init and fails-fast if mis-configured (catches "both desks share a paper account" bug at startup)

## 6. Watch loop picks up the strategy

`WatchLoop._run_platform_shadow_tick()` dispatches to every active `shadow_trading` strategy at its declared `shadow_cadence_seconds` (default 600s per spec.raw). `ShadowHarness.run_one_tick()` does:
- Reconcile own positions via research Alpaca
- Find candidates via `find_candidates_for_date(spec, db_path, as_of)`
- Pre-trade limits check (`check_pre_trade_limits`)
- Place bracket order via research Alpaca with `desk='research_<strategy_id>'`
- Write to `shadow_trades`

## 7. Promotion to `production`

Requires all `shadow_trading` gates PLUS:
- ≥ 30 shadow trades
- ≥ 60 shadow-trading days
- Two-step 24h delay (token-based via `strategy_registry.notes`)
- Manual justification_note ≥ 40 chars

## 8. Halting a strategy

```python
from src.platform.promotion import demote, pause
demote(strategy_id="my_strategy_v1", reason="<at least 20 chars>")
# OR for emergency pause without position close:
pause(strategy_id="my_strategy_v1")
```

`demote()` moves to `deprecated` AND closes all open positions via research Alpaca.
`pause()` moves to `backtested` WITHOUT closing positions (emergency halt; operator reviews manually).

## 9. Inspect via dashboard

Open `/research-platform` — 4 sections show registry, YAML spec, backtest history, equity curves, promotion events log. The home dashboard's `PlatformStatusWidget` surfaces counts + "awaiting approval" nudge.

## Known limitations (v0.24.0)

- **Historical EDGAR data** — backfill only 2024-present; Lazy Prices validation at scale requires 2019-2023 backfill (issue #469)
- **PBO** — requires a param-sweep driver (v0.24.1)
- **`_find_candidates` scheduled-kind** — currently returns `[]` with warning; v0.24.1 adds day-iteration live path
- **Correlation monitoring** — Tier 7 modules defer to v0.24.1 (only relevant with ≥2 concurrent strategies)
- **Python plugin execution** — interface defined in v0.24.0; backtest_engine + shadow_harness wiring is v0.24.1

## Emergency rollback

If a strategy misbehaves in shadow:
```python
pause(strategy_id="...")           # Stop ticking; positions stay open for review
demote(strategy_id="...", reason="...")  # Stop + close all positions
```

If the NSSM service needs to be halted:
```
nssm stop ArcisWatchLoop
```

Reconcile on restart catches up — `reconcile_paper_trades(desk=...)` is idempotent.
