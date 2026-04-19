# Pass 1 — Incumbent v1 YAML spec extraction evaluation (#523)

**Branch:** `refactor/incumbent-v1-yaml-spec`
**Date:** 2026-04-19
**Sprint type:** Refactor. Hard rules: no logic changes, no feature additions, byte-identical order stream.

## Scope

Prompt mission: "Extract the incumbent pullback-in-uptrend strategy logic into `src/platform/specs/incumbent_v1.yaml`. Runtime behavior must be byte-identical pre/post. The spec becomes the frozen reference for v0.26.1 walk-forward validation."

Prompt explicitly anticipates a STOP-and-file outcome:

> ## Risk: "can't cleanly separate"
> If Pass 2 reveals cross-dependencies that don't YAML-ify, STOP and file issue with specific coupling. Do NOT force incomplete refactor.

This evaluation inventories the hardcoded logic and flags up-front the cross-dependencies that justify that STOP path. Pass 2 will confirm or refute with a deeper line-by-line read.

## Existing reference: `src/platform/specs/lazy_prices_v1.yaml`

The lazy_prices schema is the shape we're attempting to reuse:

- `spec_version`, `strategy_id`, `display_name`, `derived_from: null`, `description`, `citation`
- `universe.tickers: sp100`
- `entry.kind: event_driven` (with `event_table`, `event_filter`, `signal[] {metric, target, reference, operator, threshold}`, `combinator`)
- `exit.kind: mechanical` (with `timeout_days`, `stop {method, atr_period, multiplier, floor_pct, cap_pct}`, same for `target`)
- `position_sizing {method, pct, max_concurrent}`
- `attribution {benchmark, metrics[]}`
- `llm_enhancement {enabled, model, role, prompt_template, validation}`

Spec-loader in `src/platform/strategy_spec.py`:
- `ALLOWED_ENTRY_KINDS = {"scheduled", "event_driven", "python_plugin"}`
- `ALLOWED_EXIT_KINDS = {"mechanical", "python_plugin"}`
- `REQUIRED_KEYS = ("spec_version", "strategy_id", "display_name", "universe", "entry", "exit", "position_sizing", "attribution")`

## Incumbent pipeline — inventory

The incumbent "pullback-in-uptrend" strategy is not a single function; it is the entire live/shadow scan pipeline. The pipeline is:

```
run_scan(config)                                 # src/services/scan_service.py
  ├─ get_sp100_universe()                        # src/universe/sp100.py
  ├─ fetch_ohlcv(universe)                       # src/data_ingestion/market_data.py
  ├─ fetch_spy_benchmark()                       # src/data_ingestion/market_data.py
  ├─ compute_all_features(ohlcv, spy)            # src/features/engine.py (364 lines)
  │    ├─ compute_features(ticker, ohlcv, spy)   # 7 feature dimensions
  │    ├─ _classify_trend()                      # trend_state enum
  │    ├─ _classify_relative_strength()          # relative_strength_state enum
  │    ├─ get_next_earnings_date() + check_earnings_overlap()
  │    ├─ compute_market_regime(spy, ohlcv)      # src/features/regime.py
  │    ├─ _load_options_metrics()                # DB: options_metrics
  │    ├─ _load_event_proximity()                # src/features/event_proximity.py
  │    ├─ _load_sector_profiles()                # data/reference/sector_profiles.json
  │    └─ classify_setup() + log_setup_signal()  # src/features/setup_classifier.py
  ├─ enrich_features(features, config)           # src/data_enrichment/enricher.py
  ├─ attach_post_scan_features()                 # traffic_light + event_risk + regime_label
  ├─ validate_universe() + validate_features()   # src/data_integrity/
  ├─ rank_universe(features)                     # src/ranking/ranker.py (330 lines)
  │    ├─ _load_thresholds(regime_type)          # bootcamp on/off, regime_adaptive on/off
  │    ├─ _compute_sector_rs()                   # 20/50/30 weighting 1m/3m/6m
  │    ├─ _score_ticker()                        # deterministic multi-branch scoring
  │    │    ├─ trend_state bonus (+30/+20/+5)
  │    │    ├─ two-tier RS (60% market + 40% sector)
  │    │    ├─ pullback depth bands ([-8,-3]=+25, [-12,-8)=+10)
  │    │    ├─ dist_to_sma20 band ([-5,-1]=+10)
  │    │    ├─ volume_ratio_20d band (<0.8=+15)
  │    │    ├─ options signals (iv_rank <25 → +3, >75+pc_vol>1.2 → −3)
  │    │    ├─ _regime_adjustment (6 regime branches + SPY RSI bounds, ±10)
  │    │    └─ cap [0, 100]
  │    ├─ compute_sector_context()               # post-score sector statistics
  │    └─ event_risk_level gate (elevated|imminent → 'earnings_risk_packet')
  ├─ get_top_candidates(ranked, max_packets, max_watchlist)
  │    └─ bootcamp mode override: max_packets=20, max_watchlist=30
  ├─ for each packet_worthy:
  │    ├─ log_attribution_before_llm()           # ranker-only snapshot
  │    ├─ build_packet_from_features(ticker, feat, config)
  │    ├─ enhance_packet_with_llm(packet, feat, config)   # LLM bracket refinement
  │    ├─ log_recommendation()
  │    ├─ log_attribution_after_llm()
  │    └─ open_shadow_trade(rec_id, packet, feat)         # uses packet.entry_zone, stop_invalidation, targets
  └─ check_and_manage_open_trades()              # bracket-based exits + timeout
```

## Hardcoded logic — inventory with file/line anchors

### Entry signal parameters (features/engine.py)

| Element | Value | Location |
|---|---|---|
| SMA periods | 20, 50, 200 | `engine.py:120-122` |
| Pullback lookback window | 50 days (high_50d) | `engine.py:161` |
| ATR period | 14 | `engine.py:165-169` |
| Volume MA period | 20 | `engine.py:173` |
| Return periods for RS (days) | 21, 63, 126 (1m/3m/6m) | `engine.py:143-148` |
| Trend state thresholds | `price > sma50 > sma200 && both slopes positive → strong_uptrend`; `price > sma50 > sma200 → uptrend`; symmetric for downtrends | `engine.py:57-68` |
| RS state thresholds | positive_count==3 → strong_outperformer; ≥2 → outperformer; symmetric for negatives | `engine.py:78-99` |
| Minimum rows for feature eligibility | 200 | `engine.py:239` |

### Ranking weights (ranking/ranker.py)

| Element | Value | Location |
|---|---|---|
| trend_state bonus | strong_uptrend=+30, uptrend=+20, neutral=+5 | `ranker.py:169-176` |
| market_rs bonus | strong_outperformer=25, outperformer=15, else 0 | `ranker.py:180` |
| two-tier RS weights | 60% market + 40% sector | `ranker.py:184` |
| sector_rs band cutoffs | 5.0 → 25, 2.0 → 15, −2.0 → 5, else → 0 | `ranker.py:140-147` |
| sector_rs period weighting | 20% 1m + 50% 3m + 30% 6m | `ranker.py:132-137` |
| pullback_depth bands | [-8,-3] → +25; [-12,-8) → +10 | `ranker.py:191-194` |
| dist_to_sma20 band | [-5,-1] → +10 | `ranker.py:198-199` |
| volume_ratio band | <0.8 → +15 | `ranker.py:202-204` |
| options signals | iv_rank<25 → +3; iv_rank>75 & pc_vol>1.2 → −3 | `ranker.py:207-213` |
| regime_adjustment bounds | ±10, clamped | `ranker.py:102` |
| regime branches | calm_uptrend+healthy=+5; calm_uptrend+narrowing=+2; volatile_uptrend=0; transitional=−3; calm_downtrend=−5; volatile_downtrend=−10 | `ranker.py:80-91` |
| SPY RSI bounds | >75 → −3; <30 → +3 | `ranker.py:94-97` |
| score cap | [0, 100] | `ranker.py:220` |
| REGIME_THRESHOLDS lookup | 7 regimes × {packet_worthy, position_pct} table | `ranker.py:17-25` (module const) |
| bootcamp thresholds | qualification_threshold=40, watchlist_threshold=25, position_pct=1.0 | `ranker.py:38-47` (from config) |
| bootcamp caps | max_packets=20, max_watchlist=30 | `ranker.py:311-315` |
| base thresholds | packet_worthy=70, watchlist=45 | `ranker.py:50-53` (from config with defaults) |
| earnings gate | event_risk_level ∈ {elevated, imminent} → earnings_risk_packet bucket | `ranker.py:282-286` |

### Bracket logic (shadow_trading/executor.py + scan_service.py + config)

| Element | Value | Location |
|---|---|---|
| timeout_days default | 15 | `schema/registry.py:224`, `schemas.py:104`, `services/shadow_service.py:22,55` |
| timeout_days override (pullback) | 7 | `api/cloud_routes/core.py:366` |
| attribution-layer ATR multiples (Phase 1 log only) | stop = entry − 2·atr; target = entry + 1.5·atr | `scan_service.py:156-157` |
| actual bracket prices | from `packet.entry_zone`, `packet.stop_invalidation`, `packet.targets` | `executor.py:478-485` |
| packet prices source | `build_packet_from_features()` → LLM-enhanced by `enhance_packet_with_llm()` | `scan_service.py:168-169` |
| fallback prices (ATR absent) | entry*0.97 stop, entry*1.02 target | `scan_service.py:156-157` (attribution only) |
| volatility-regime brackets (simulation path only) | {low: 2.0/2.0/8d, normal: 2.0/2.0/8d, elevated: 2.5/2.5/7d, extreme: 3.0/3.0/5d} | `simulation/engine.py:90-93` |

### Universe

- `src/universe/sp100.py` — 100 tickers + sector map
- Schema: reference by key — `universe.tickers: sp100` (same shape as lazy_prices)

### Event-risk exclusion

- **Earnings (SD#33)**: `features/earnings.py` (134 lines) + `check_earnings_overlap()` sets `event_risk_level` field on each ticker; ranker gates elevated/imminent into `earnings_risk_packet` quarantine
- **Tariff (SD#42)**: `src/diagnostics/known_events.py` + post-audit ruleset (referenced from v0.26.2 plan, not yet wired into the scan pipeline — scan_service has no tariff gate today)
- **Market-level event_risk_score**: `features/event_risk_score.py` (322 lines) — continuous 0-10 scoring with Telegram alert at threshold 6; set via `attach_post_scan_features` + `market_event_risk` dict

## Proposed spec shape (pre-schema-extension baseline)

If we were to produce an `incumbent_v1.yaml` matching the lazy_prices schema strictly, it would look like:

```yaml
spec_version: 1
strategy_id: incumbent_v1
display_name: Pullback-in-Uptrend (Incumbent)
derived_from: null
description: >
  Live paper-trading strategy — pullback entry on uptrending S&P 100 names
  with ranker-driven conviction scoring, LLM-enhanced packet bracket
  refinement, and mechanical ATR-based brackets.
citation: null

universe:
  tickers: sp100

# NOT IN lazy_prices — needs schema extension:
entry:
  kind: daily_scan    # NEW — not in ALLOWED_ENTRY_KINDS
  # ... complex signal spec with scoring bands, regime adjustments, etc.

exit:
  kind: mechanical
  timeout_days: 15            # default; 7 for pullback override
  stop:
    method: atr_based
    atr_period: 14
    multiplier: 2.0            # from attribution path; LLM may override
  target:
    method: atr_based
    atr_period: 14
    multiplier: 1.5            # from attribution path; LLM may override

position_sizing:
  method: regime_adaptive     # NEW — lazy_prices uses fixed_pct_equity
  # ... regime-keyed pct table

attribution:
  benchmark: SPY_matched_window
  metrics: [raw_sharpe, excess_sharpe, win_rate, profit_factor, max_drawdown]

llm_enhancement:
  enabled: true               # INCUMBENT DIFF — lazy_prices: false
  model: halcyon-v1           # actual model key — currently from config
  role: bracket_refinement    # NEW role type
  prompt_template: incumbent_packet_prompt
  validation: price_bounds_check

frozen_at_commit: <this SHA>
frozen_date: 2026-04-19
```

## Schema extensions required (non-exhaustive)

To represent the incumbent as YAML without losing fidelity, the spec schema and the spec-loader (`src/platform/strategy_spec.py`) need:

1. **New `entry.kind: daily_scan`** — add to `ALLOWED_ENTRY_KINDS`.
2. **New `entry.signal` shape for scoring bands**, not just thresholds — e.g.,
   ```yaml
   signal:
     - metric: pullback_depth_pct
       bands:
         - {range: [-8, -3], score: 25}
         - {range: [-12, -8], score: 10}
   ```
3. **New `ranking` block** with:
   - trend_state bonus table
   - market_rs bonus table
   - two-tier RS weights {market_weight, sector_weight}
   - sector_rs period weighting (1m/3m/6m)
   - sector_rs band cutoffs and scores
   - regime_adjustment table (6 regimes × adjustment value)
   - SPY RSI bounds
   - score cap [0, 100]
4. **New `thresholds` block** with regime_adaptive lookup (7 regimes × {packet_worthy, position_pct}) and bootcamp override
5. **New `position_sizing.method: regime_adaptive`** with regime-keyed pct table (replacing `fixed_pct_equity`)
6. **New `event_risk` block** capturing earnings gate + market-level threshold + tariff rule (SD#42)
7. **New `llm_enhancement.role: bracket_refinement`** with validation spec (vs lazy_prices' `structured_extraction`)
8. **New `attribution` hooks** — log_attribution_before_llm / log_attribution_after_llm
9. **Optional `bootcamp_mode` section** for bootcamp-on overrides
10. **New `options_signals` block** capturing iv_rank + put_call_vol_ratio rules

These extensions are additive to the existing lazy_prices schema, but they introduce a scoring DSL into the spec format — a significant platform evolution, not a simple lift-and-shift.

## Cross-dependencies that don't cleanly YAML-ify

### Blocker 1: `daily_scan` entry kind has no runtime

`src/platform/signal_eval.py:180` currently raises:
```python
if kind == "scheduled":
    raise NotImplementedError("[SIGNAL_EVAL] scheduled-kind find_candidates_for_date not yet implemented")
```

`scheduled` would be the closest analog to `daily_scan`, but it's a tracked open issue (**#494**, flagged as pending in the v0.25.2 parked subphase). The platform's backtest engine cannot instantiate or run an incumbent YAML without this wiring.

### Blocker 2: LLM enhancement is load-bearing for bracket prices

`scan_service.py:169` — `packet = enhance_packet_with_llm(packet, feat, config)` rewrites `packet.entry_zone`, `packet.stop_invalidation`, `packet.targets` before `open_shadow_trade()`. The LLM output is not a pure function of features — it depends on:
- `config['llm']` model name, temperature, repeat_penalty
- Ollama binary, model weights (`halcyon-v1.0.0` GGUF)
- Conviction extraction patterns (5-pattern match, #183)
- Pre-parser rejection of prompt leakage / template stubs / repetition (#384)
- Write-boundary type coercion (#383)

**Byte-identical order stream is mathematically impossible** without LLM determinism controls that don't exist in the current pipeline (Ollama GGUF is deterministic per-seed but prompt context changes per scan). Even at seed=0 temperature=0 the model weights are frozen but the prompt varies with live feature values.

### Blocker 3: Config-driven state (bootcamp, regime_adaptive) changes pipeline behavior

Both bootcamp-on and regime_adaptive-on modes modify `_load_thresholds()` output. Per `docs/decisions/013-strategy-evaluation-apr-19.md` (v0.25.0), `bootcamp.enabled: true` (qualification 40→55 as of Monday). Any YAML that freezes incumbent behavior must either:
- Capture bootcamp state at SHA snapshot time (breaks "v1 is THE strategy" framing)
- Represent bootcamp as a mode switch in YAML (new `bootcamp_mode` section, see extension #9)

The simulation path has its OWN volatility-regime bracket table (`simulation/engine.py:90-93`) distinct from the live path — live doesn't use that table, it comes out of LLM packet enhancement. Inventorying which table is "the" incumbent is itself ambiguous.

### Blocker 4: Attribution Phase 1/2 hooks are runtime-resident

`log_attribution_before_llm()` and `log_attribution_after_llm()` are invoked from `scan_service.py:158, 188`. The YAML spec has no place to express "hook: log_attribution_before_llm" as a declaration, and representing runtime hooks in YAML is a bigger platform feature (observation framework in spec DSL).

### Blocker 5: Data-enrichment step is not described in spec

`enrich_features(features, config)` pulls fundamental/insider/macro data. Lazy-prices skips enrichment entirely — it's event-driven on EDGAR only. Incumbent requires enrichment. YAML would need a `data_enrichment` block listing enrichers (new concept).

### Blocker 6: Post-scan enrichment chain (traffic_light + event_risk + regime_label)

`attach_post_scan_features()` mutates the feature dict after ranking (`scan_service.py:83-85`). Spec YAML has no place for "run this helper after ranking".

### Blocker 7: Setup classifier + log_setup_signal

`src/features/setup_classifier.py` classifies each feature dict into one of 6 setup types and logs to `setup_signals` table. Used by LLM prompt. Deferred circular-import load. Not expressible in YAML.

### Blocker 8: Volatility-regime bracket table is in simulation-only path

`simulation/engine.py:90-93` has a hardcoded `{low, normal, elevated, extreme} × {stop_atr_mult, target_atr_mult, timeout_days}` table. This is for the **backtester**, not the live pipeline. The live pipeline uses LLM packet enhancement. If the YAML should represent "incumbent as simulated" vs "incumbent as live-traded", they are different strategies — YAML must pick one.

## Non-goals (explicit)

Per prompt hard rules:

- ❌ No LLM enhancement rewire — remain a Python function
- ❌ No attribution logging rewire — remain at call sites
- ❌ No bootcamp switch rewire — remain config-driven
- ❌ No new schema operators (`between`, `bands`) added in this sprint
- ❌ No porting incumbent to backtest_engine (would require #494 wiring + major engineering)
- ❌ No byte-identical guarantee spanning LLM randomness

## Decisions required (for Pass 2 confirmation)

1. **Spec-as-reference vs spec-as-runtime**: is the YAML a purely documentary artifact (frozen snapshot + `derived_from: null` declaration) that the runtime does not consume, or does the YAML drive runtime?
   - If spec-as-reference: minimal change; regression test verifies YAML values match Python source; no schema extension needed
   - If spec-as-runtime: major refactor + schema extension + #494 wiring + LLM determinism work
2. **If spec-as-reference**: should the fields we CANNOT capture (LLM role, attribution hooks, enrichment chain, post-scan chain) be omitted silently, or explicitly annotated in the YAML with `reference_only: true` markers?
3. **Schema extension for `daily_scan` kind**: block it to a later sprint, or accept scope creep now?
4. **Bracket source-of-truth tension**: Python attribution fallback (2·ATR / 1.5·ATR) vs LLM-enhanced packet — if spec must pick one, which?

## Recommendation (pending Pass 2)

Pass 1 strongly suggests the **STOP-and-file** path per prompt's Risk section:

> Outcome: PR contains Pass 1 + Pass 2 docs only, closes #523 with "BLOCKED — see issue #NNN," follow-up sprint unwinds coupling before retry.

The incumbent pipeline is not amenable to byte-identical YAML extraction because of LLM-in-the-loop bracket pricing (Blocker 2), missing runtime for `daily_scan` kind (Blocker 1), and the 8 cross-dependencies inventoried above. A minimal "spec-as-reference" interpretation would technically satisfy the sprint if the operator accepts a documentary-only YAML with no runtime wiring — but that departs from the prompt's illustrative "Load via platform spec-loader" regression test.

**Pass 2 will re-read every file end-to-end to confirm these blockers and check for any mitigations (e.g., LLM determinism flags, a secondary non-LLM code path, a narrower scope that yields a byte-identical subset).**
