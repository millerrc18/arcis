# Capability Registry Refresh — Exhaustive Subsystem Inventory

**Date:** 2026-05-21
**Scope:** `C:/arcis/halcyon-lab` — `src/platform/capability_registry/`
**Mode:** Research / analysis only (no code modified)
**Surfaces at:** `GET /api/system/index` (both `src/api/cloud_routes/system_index.py` and `src/api/routes/system_index.py`)

---

## 1. How the registry works (ground truth)

Four import-time decorator registries in `src/platform/capability_registry/registry.py`:

| Decorator | Registry dict | Wraps | Required extra fields (beyond `BaseEntry`) |
|---|---|---|---|
| `@register_action(**meta)` | `ACTIONS` | a kickoff fn (returned unchanged) | `kickoff_endpoint`, `input_schema`, `output_schema`, `estimated_duration` (+ optional `history_endpoint`, `ui_kickoff_available`) |
| `@register_state(**meta)` | `STATES` | becomes `query_function` | `refresh_hint` |
| `@register_system(**meta)` | `SYSTEMS` | becomes `health_check_function` | `expected_runtime` |
| `register_decision(**meta)` (plain call, no decorator) | `DECISIONS` | nothing (a fact) | `decision_text`, `rationale`, `revisit_trigger` |

**`BaseEntry`** (`schemas.py:24`) requires on every entry: `name` (snake/hyphen, ≤128), `description` (≤1024), `category` (≤64), `version`, `maintainer` (`operator`|`ai_session`), `introduced_in` (must start with `v`), `last_reviewed_date` (a `datetime.date`), `deprecated`/`deprecated_replacement` pair. Action `input_schema`/`output_schema` must be valid Draft-7 JSON Schema with top-level `type` (MCP-compatible). Pydantic validates at decoration time, so malformed metadata fails loudly at import.

**Bootstrap** (`bootstrap.py:35`): `CAPABILITY_MODULES` is a hand-maintained 14-entry tuple. `ensure_bootstrapped()` imports each module to fire its decorators. A failed import is logged (`CAPABILITY_REGISTRY_BOOTSTRAP_ERROR`) and skipped — registration is silent-fail by design, which is exactly why drift is invisible.

**The "frozen guard":** `tests/test_capability_registry_integration.py:81` `test_18_capabilities_registered` → `assert total >= 18`. This is a snapshot floor, not a structural rule. It passes forever as long as the original 18 survive; it can never detect a 19th subsystem that was added without a decorator. (Note: the per-entry metadata test `tests/test_capability_registry_metadata.py` validates quality of *registered* entries but likewise never enumerates what *should* exist.)

---

## 2. Currently registered (the live ledger) — 18 total

Confirmed by grepping `@register_action|@register_state|@register_system` + `register_decision(` across `src/`.

| # | Name | Kind | File:line |
|---|---|---|---|
| 1 | `regime_diagnostic` | action | `src/diagnostics/__init__.py:24` |
| 2 | `forensic_trade_audit` | action | `src/diagnostics/__init__.py:76` |
| 3 | `strategy_backtest` | action | `src/platform/__init__.py:18` |
| 4 | `edgar_historical_backfill` | action | `src/data_ingestion/backfill_registration.py:25` |
| 5 | `training_data_audit` | action | `src/training/audit/__init__.py:26` |
| 6 | `shadow_trade_cohort` | state | `src/shadow_trading/state.py:72` |
| 7 | `strategy_registry_state` | state | `src/platform/__init__.py:78` |
| 8 | `training_corpus` | state | `src/services/training_service.py:53` |
| 9 | `bootcamp_mode` | state | `src/services/bootcamp_state.py:37` |
| 10 | `alpaca_account` | state | `src/shadow_trading/alpaca_adapter.py:411` |
| 11 | `ollama_model` | state | `src/llm/ollama_state.py:37` |
| 12 | `watch_loop` | system | `src/startup.py:197` |
| 13 | `reconcile_trades` | system | `src/shadow_trading/reconcile_state.py:47` |
| 14 | `attribution_resolver` | system | `src/attribution/logger.py:340` |
| 15 | `nightly_audit_agent` | system | `src/platform/capability_registry/audit_registration.py:60` |
| 16 | `bootcamp_still_active` | decision | `src/platform/capability_registry/decisions.py:29` |
| 17 | `pullback_strategy_contaminated` | decision | `src/platform/capability_registry/decisions.py:60` |
| 18 | `lazy_prices_deprecated_on_sp100` | decision | `src/platform/capability_registry/decisions.py:89` |
| 19 | `no_new_strategy_specs_until_walkforward_ships` | decision | `src/platform/capability_registry/decisions.py:117` |

> Tally note: the grep yields **19** registrations (5 actions, 6 states, 4 systems, 4 decisions). The "~18" in the prompt/`test_18_capabilities_registered` is the documented Sprint-1B floor; the 19th decision (`no_new_strategy_specs...`) was added later and still passes the `>= 18` assertion. Either way the ledger froze in mid-April: every entry carries `last_reviewed_date = date(2026, 4, 18)`.

---

## 3. Missing capability-hosting subsystems (the drift)

Each row was confirmed by reading the real module. Proposed names follow the existing snake_case convention. Kind chosen per the registry semantics in §1.

### 3a. Data collectors — `src/data_collection/` (largest gap: a whole subsystem family)

24 collector modules exist; **zero** register a SYSTEM. Each is an overnight/enrichment data source with a clear "did it run recently / is the table fresh" health signal (mirrors `reconcile_trades`' MAX(updated_at) proxy).

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| EDGAR filings collector | `src/data_collection/edgar_collector.py` (`collect_new_filings` :274) | SYSTEM | N | `edgar_filings_collector` — pulls new 10-K/10-Q/8-K filings for the universe; health = freshness of `filings` table |
| Filings sentiment | `src/data_collection/filings_sentiment_collector.py` | SYSTEM | N | `filings_sentiment_collector` — NLP sentiment over recent filings |
| Insider transactions | `src/data_collection/insider_collector.py` | SYSTEM | N | `insider_collector` — Form 4 insider buys/sells |
| Press releases | `src/data_collection/press_releases_collector.py` | SYSTEM | N | `press_releases_collector` — company press-release feed |
| Analyst ratings | `src/data_collection/analyst_collector.py` | SYSTEM | N | `analyst_collector` — analyst rating changes / consensus |
| Macro indicators | `src/data_collection/macro_collector.py` | SYSTEM | N | `macro_collector` — macro series ingestion |
| Fed / rates | `src/data_collection/fed_collector.py` | SYSTEM | N | `fed_collector` — Fed calendar + statements |
| Short interest | `src/data_collection/short_interest_collector.py` | SYSTEM | N | `short_interest_collector` — bi-monthly short-interest |
| Short volume (FINRA) | `src/data_collection/short_volume_finra.py` | SYSTEM | N | `short_volume_collector` — daily FINRA short-volume |
| Institutional ownership | `src/data_collection/institutional_ownership_collector.py` | SYSTEM | N | `institutional_ownership_collector` — 13F holdings |
| VIX | `src/data_collection/vix_collector.py` | SYSTEM | N | `vix_collector` — VIX level for regime/governor |
| CBOE | `src/data_collection/cboe_collector.py` | SYSTEM | N | `cboe_collector` — CBOE options/put-call data |
| Options chain | `src/data_collection/options_collector.py` (+ `options_metrics.py`) | SYSTEM | N | `options_collector` — options-chain snapshot + derived metrics |
| Google Trends | `src/data_collection/trends_collector.py` | SYSTEM | N | `trends_collector` — search-interest series |
| Research docs | `src/data_collection/docs_collector.py` / `research_collector.py` / `research_synthesizer.py` | SYSTEM | N | `research_collector` — research-source ingestion + synthesis |
| **Company executives** | `src/data_collection/company_executive_collector.py` | SYSTEM | N | `company_executive_collector` — *paid Finnhub capability, dead-weight per MEMORY (no wired collector yet)* |
| **Price targets** | `src/data_collection/price_target_collector.py` | SYSTEM | N | `price_target_collector` — *paid Finnhub dead-weight capability* |
| **Stock financials** | `src/data_collection/stock_financials_collector.py` | SYSTEM | N | `stock_financials_collector` — *paid Finnhub dead-weight capability* |
| Retention sweep | `src/data_collection/retention.py` | SYSTEM | N | `data_retention_sweep` — prunes stale collected data per retention policy |

> `src/data_ingestion/` (the *other* ingestion package: `finnhub.py`, `market_data.py` with `fetch_ohlcv`/`fetch_spy_benchmark`, `risk_free_rate.py`) hosts the live OHLCV/benchmark/rate fetchers. `market_data` is arguably one more SYSTEM (`market_data_feed`). Only `backfill_registration.py` here is wired today.

### 3b. Watch-loop overnight/daytime scheduler handlers — `src/scheduler/watch_handlers.py`

`ALL_HANDLERS` (`:289`) = 16 module-level handler functions wired onto the `on_tick` event via `WatchLoop._register_default_handlers` (`watch.py:2116`). Each is a discrete scheduled ACTION the platform performs nightly. **None registered.** This is the single most structurally-derivable missing set (see §4, Convention A).

| Handler (`watch_handlers.py`) | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|
| `maybe_morning_vram_handoff` | ACTION | N | `morning_vram_handoff` — 5:15 AM unload Ollama / clear VRAM for pre-market inference |
| `maybe_post_close_capture` | ACTION | N | `post_close_capture` — 5:30 PM post-close snapshot capture |
| `maybe_overnight_training_collection` | ACTION | N | `overnight_training_collection` — 6 PM collect training examples |
| `maybe_evening_vram_handoff` | ACTION | N | `evening_vram_handoff` — 6:50 PM unload Ollama, launch overnight training subprocess |
| `maybe_stress_test` | ACTION | N | `model_stress_test` — 7 PM re-run stress test on model-version change |
| `maybe_data_collection` | ACTION | N | `nightly_data_collection` — 9:30 PM comprehensive data collection (orchestrates §3a) |
| `maybe_news_ingestion` | ACTION | N | `nightly_news_ingestion` — 10 PM full-universe news pull |
| `maybe_enrichment_precache` | ACTION | N | `enrichment_precache` — 11 PM pre-fetch fundamentals/insider/macro |
| `maybe_1min_bar_collection` | ACTION | N | `intraday_bar_collection` — 11:30 PM 1-min OHLCV bars for S&P 100 |
| `maybe_pre_market_refresh` | ACTION | N | `premarket_refresh` — 6 AM pre-market check + brief |
| `maybe_premarket_rolling_features` | ACTION | N | `premarket_rolling_features` — 6:02 AM rolling-feature computation |
| `maybe_premarket_training` | ACTION | N | `premarket_training_gen` — 7 AM generate pre-market training data |
| `maybe_premarket_news_scoring` | ACTION | N | `premarket_news_scoring` — 8:02 AM news relevance scoring |
| `maybe_premarket_candidates` | ACTION | N | `premarket_candidates` — 9:00–9:24 AM build pre-market candidate list |
| `maybe_stats_pulse` | ACTION | N | `trading_stats_pulse` — 3×/day trading-stats Telegram pulse |
| `maybe_walkforward_reconciler` | ACTION | N | `walkforward_reconciler` — hourly market-hours orphan-backtest auto-fire |

> Other `src/scheduler/` modules that are SYSTEMs/ACTIONs in their own right and unregistered: `position_monitor.py` (SYSTEM `position_monitor` — open-position price/exit monitoring), `universe_scanner.py` (SYSTEM/ACTION `universe_scanner` — candidate scan), `sentiment_scanner.py` (`sentiment_scanner`), `scorer.py` (`candidate_scorer`), `premarket.py`, `overnight.py`, `reports.py`, `fundamentals_refresh.py` (`fundamentals_refresh`), `vram_manager.py` (SYSTEM `vram_manager`).

### 3c. Risk governor gates — `src/risk/governor.py`

`RiskGovernor.check_trade` (`:565`) is the last-line trade gate with a layered 8-check (0a–8) defense. Each check is a discrete DECISION point (gate logic the system applies). **None registered as DECISIONs.** The governor itself is also an unregistered SYSTEM.

| Gate (in `check_trade`) | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|
| Governor as a whole | SYSTEM | N | `risk_governor` — deny-by-default last check before any order; enforces 8 layered limits |
| 0a Traffic Light | DECISION | N | `gate_traffic_light` — regime-based position-size multiplier from council |
| 0b Event Risk | DECISION | N | `gate_event_risk` — earnings/macro hard block or size reduction |
| 1 Kill Switch | DECISION | N | `gate_kill_switch` — file-based emergency halt (`data/trading_halted`) |
| 2 Daily Loss | DECISION | N | `gate_daily_loss` — realized-only daily P&L cap |
| 3 Position Size | DECISION | N | `gate_position_size` — single-name concentration cap |
| 4 Max Positions | DECISION | N | `gate_max_positions` — bootcamp-aware portfolio breadth limit (MIN of all configured caps, `_CAP_NAMESPACES`) |
| 5 Sector Concentration | DECISION | N | `gate_sector_concentration` — VIX-adaptive sector cap |
| 6 Correlation | DECISION | N | `gate_correlation` — same-sector count limit |
| 7 Volatility | DECISION | N | `gate_volatility` — VIX circuit breaker |
| 8 Duplicate | DECISION | N | `gate_duplicate_position` — one position per ticker |
| Deterministic audit suppression | DECISION | N | `gate_deterministic_audit` — blocks entries while a critical audit is active |
| Graduated drawdown sizing | DECISION | N | `decision_drawdown_adjusted_risk` — Thorp proportional bet-reduction (`drawdown_adjusted_risk` :338) |

### 3d. Execution / position monitoring / exits — `src/shadow_trading/`

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| Trade executor (entry submit) | `src/shadow_trading/executor.py` (`open_shadow_trade` :557, `open_live_trade` :2386) | ACTION | N | `submit_shadow_trade` — open a bracket/OCO shadow (or live) position through the risk governor |
| Open-trade management / exits | `src/shadow_trading/executor.py` (`check_and_manage_open_trades` :1614) | SYSTEM | N | `position_exit_manager` — monitors open trades, fires bracket exits, retries failed exits |
| Bracket monitor | `src/shadow_trading/bracket_monitor.py` | SYSTEM | N | `bracket_monitor` — watches Alpaca bracket/OCO legs for fills |
| Bracket attach | `src/shadow_trading/bracket_attach.py` | ACTION | N | `attach_bracket` — attach stop/target legs to a filled entry |
| Reconciliation engine | `src/shadow_trading/reconcile.py` / `reconcile_dispatch.py` / `exit_reconciliation.py` | SYSTEM | N | `trade_reconciler` — broker↔journal drift detection + orphan backfill (the *engine*; `reconcile_trades` registers only a freshness health proxy) |
| Exit-reason classification | `src/shadow_trading/exit_reason.py` | DECISION | N | `exit_reason_classifier` — classifies why a position closed (stop/target/manual/abandon) |
| Qty-mismatch handling | `src/shadow_trading/qty_mismatch.py` | DECISION | N | `qty_mismatch_resolution` — reconciles share-count drift between journal and broker |
| Broker exception logger | `src/shadow_trading/broker_exception_logger.py` | SYSTEM | N | `broker_exception_log` — captures Alpaca API exceptions for audit |
| Milestone / loss-streak / sector alerts | `executor.py` (`_check_loss_streak` :2961, `_check_sector_exposure` :3027, `_check_*_milestones`) | DECISION | N | `decision_loss_streak_alert` — surfaces consecutive-loss + concentration warnings |

### 3e. Scan → candidate → LLM packet → scoring pipeline

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| Candidate ranker | `src/ranking/ranker.py` | DECISION | N | `candidate_ranking` — ranks/scans candidates for entry consideration |
| LLM packet writer | `src/llm/packet_writer.py` (+ `src/packets/`) | ACTION | N | `build_decision_packet` — assembles the LLM decision packet for a candidate |
| LLM client / scoring | `src/llm/client.py`, `src/llm/grammar_client.py`, `src/llm/validator.py` | SYSTEM | N | `llm_scorer` — Ollama-backed conviction scoring with grammar-constrained output |
| Council engine | `src/council/engine.py` (`CouncilEngine` :170, `run_council_command` :152) | SYSTEM | N | `council_engine` — multi-agent regime/traffic-light assessment (feeds governor 0a) |
| Council aggregation | `src/council/aggregation.py` / `value_tracker.py` | DECISION | N | `council_aggregation` — combines agent votes into a traffic-light multiplier |
| Watchlist writer | `src/llm/watchlist_writer.py` / `src/packets/watchlist.py` | ACTION | N | `build_watchlist` — generates the daily watchlist packet |
| Postmortem writer | `src/llm/postmortem_writer.py` / `src/evaluation/postmortem.py` | ACTION | N | `trade_postmortem` — LLM postmortem on closed trades |
| EOD recap | `src/packets/eod_recap.py` | ACTION | N | `eod_recap` — end-of-day recap packet |

### 3f. Training pipeline — `src/training/` + `src/services/training_service.py` + `src/platform/`

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| Finetune trainer | `src/training/trainer.py` (`evaluate_on_holdout` :669, `run_promotion_gate_for_version` :1139) | ACTION | N | `run_finetune` — Transformers+PEFT+TRL finetune run (RTX 3090 path) |
| Holdout evaluation | `src/training/trainer.py:669` / `src/training/ab_evaluation.py` | ACTION | N | `evaluate_holdout` — evaluate a candidate model on the holdout set |
| Promotion gate | `src/training/versioning.py` (`promote_evaluation_model` :160), `src/platform/promotion.py` (`promote` :721) | DECISION | N | `model_promotion_gate` — promotes a candidate model when gate criteria pass |
| Rollback | `src/training/versioning.py` (`rollback_model` :217), `src/services/training_service.py` (`rollback_model_service` :202) | ACTION | N | `rollback_model` — revert active model to prior version |
| Canary evaluation | `src/training/canary.py` (`evaluate` :126) / `src/strategy/canary.py` | DECISION | N | `canary_evaluation` — canary-gate a new model before full promotion |
| 50-trade gate | `src/evaluation/gate_evaluator.py` (`evaluate_50_trade_gate` :28) | DECISION | N | `gate_50_trade` — promotion readiness gate on closed-trade count |
| DPO pipeline | `src/training/dpo_pipeline.py` | ACTION | N | `run_dpo` — DPO preference-tuning pipeline |
| Corpus / curriculum builder | `src/training/curriculum.py`, `src/training/data_collector.py`, `src/evaluation/corpus_generator.py` | ACTION | N | `build_training_corpus` — assemble curriculum + corpus from closed trades |
| Ingestion gate | `src/training/ingestion_gate.py` | DECISION | N | `training_ingestion_gate` — decides which examples enter the corpus |
| Quality filter / drift | `src/training/quality_filter.py`, `src/training/quality_drift.py` | DECISION | N | `training_quality_filter` — filters low-quality examples; tracks corpus drift |
| Leakage detector | `src/training/leakage_detector.py` (audit `pass_c_leakage.py`) | DECISION | N | `leakage_detection` — flags lookahead/leakage in training examples |
| Historical scanner / sampler | `src/training/historical_scanner.py`, `src/training/regime_sampler.py` | ACTION | N | `historical_scan_sampler` — backfills historical regime-stratified samples |

### 3g. Evaluation / audit / escalation — `src/evaluation/`

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| Auditor (governor verdict) | `src/evaluation/auditor.py` | SYSTEM | N | `system_auditor` — produces the audit verdict the governor trusts (see hotfix two-layer-staleness note) |
| System validator | `src/evaluation/system_validator.py` | SYSTEM | N | `system_validator` — end-to-end config/wiring validation |
| Model monitor | `src/evaluation/model_monitor.py` | SYSTEM | N | `model_monitor` — tracks live model performance drift |
| Backtester | `src/evaluation/backtester.py` (+ `walkforward.py`, `hshs.py`) | ACTION | N | `run_backtest` — strategy backtest engine (the *engine*; `strategy_backtest` action is the kickoff wrapper) |
| Walk-forward rigor | `src/platform/rigor/walkforward.py`, `cscv.py` (`src/platform/rigor/`) | ACTION/DECISION | N | `walkforward_validation` — OOS efficiency + PBO/CSCV validation (gates promotion per decision #19) |
| Gate evaluator | `src/evaluation/gate_evaluator.py` | DECISION | N | (covered in §3f `gate_50_trade`) |
| Scorecard / CTO report | `src/evaluation/scorecard.py`, `cto_report.py`, `build_score.py` | ACTION | N | `build_scorecard` — periodic system scorecard |
| Change detector | `src/evaluation/change_detector.py` | DECISION | N | `change_detector` — detects regime/behavior change for re-evaluation triggers |
| Monte-carlo simulation | `src/simulation/monte_carlo.py` | ACTION | N | `monte_carlo_sim` — MC simulation of strategy outcomes |

### 3h. Notifications & attribution

| Subsystem | File | Type | Registered? | Proposed name + 1-line metadata |
|---|---|---|---|---|
| Telegram notifier | `src/notifications/telegram.py` (`send_telegram`, `notify_*`) | SYSTEM | N | `telegram_notifier` — outbound Telegram alerts/digests; health = enabled + last-send |
| Telegram commands | `src/notifications/telegram_commands.py` (`run_council_command` :584) | ACTION | N | `telegram_command_handler` — inbound Telegram command dispatch |
| Notification policy / digest | `src/notifications/policy.py`, `digest_queue.py` | DECISION | N | `notification_policy` — decides immediate vs digest vs suppress |
| Platform-events emitter | `src/notifications/platform_events.py` | SYSTEM | N | `platform_event_bus` — structured platform-event emission |
| Attribution engine | `src/attribution/logger.py` (`attribution_resolver` registers a health proxy only) | partially | Y(proxy)/N(engine) | the *resolver* is registered; the attribution *backtest* path (`src/platform/backtest_attribution.py`) is a separate unregistered ACTION `attribution_backtest` |
| SPY benchmark analytics | `src/analytics/spy_benchmark.py` | STATE | N | `spy_benchmark_state` — benchmark return for relative-performance attribution |

---

## 4. Counts

| Bucket | Count |
|---|---|
| **Currently registered (N)** | **19** (5 action, 6 state, 4 system, 4 decision) — documented floor "18" |
| **Missing (M), enumerated above** | **~95** discrete subsystems/gates/handlers (≈19 collectors, 16 scheduler handlers + ~9 other scheduler systems, 13 governor gates+drawdown, ~9 execution/exit, 8 scan/LLM/council, 12 training, 9 evaluation/audit, 6 notifications/attribution) |
| **Total target** | **≈114** capability entries once the ledger reflects reality |

> The exact target depends on granularity decisions (e.g., whether each of the 13 governor gates is its own DECISION or one `risk_governor` SYSTEM + one `gate_check` DECISION). The structurally-unambiguous, must-register sets are: **the 16 `ALL_HANDLERS`**, **the 24 `src/data_collection/*_collector.py` modules**, and **the governor's 8 named checks**. Those three alone move the ledger from 19 → ~67.

---

## 5. Recommended anti-drift coverage-guard conventions

Replace `assert total >= 18` (a frozen snapshot that can never detect a new undecorated feature) with **structural rules that derive the expected set from the code itself**. Each new feature that omits a decorator then fails CI automatically. Proposed in priority order; all three can coexist.

### Convention A (highest value, lowest ambiguity) — **Every `ALL_HANDLERS` watch-loop handler must be a registered ACTION**

The watch loop already keeps a canonical, machine-readable list of every scheduled task: `src.scheduler.watch_handlers.ALL_HANDLERS` (`watch_handlers.py:289`). This is a pre-existing structural registry of "things the platform does on a schedule" — a perfect oracle.

```python
# tests/test_capability_registry_coverage.py
from src.scheduler.watch_handlers import ALL_HANDLERS
from src.platform.capability_registry import ensure_bootstrapped, list_actions

# Mapping convention: handler `maybe_<x>` registers ACTION named `<x>`
def _expected_action_name(handler) -> str:
    n = handler.__name__
    return n[len("maybe_"):] if n.startswith("maybe_") else n

def test_every_watch_handler_is_a_registered_action():
    ensure_bootstrapped()
    registered = {a.name for a in list_actions()}
    expected = {_expected_action_name(h) for h in ALL_HANDLERS}
    missing = expected - registered
    assert not missing, (
        f"Watch-loop handlers without a @register_action: {sorted(missing)}. "
        "Add a @register_action next to the handler (or its _run_* target)."
    )
```

**Derivation:** expected set = `{name(h) for h in ALL_HANDLERS}`. Adding a 17th handler to `ALL_HANDLERS` without a decorator fails CI on the next run. Zero hand-maintained list.

### Convention B — **Every `src/data_collection/*_collector.py` module must register a SYSTEM**

The collector family follows a strict filename convention (`*_collector.py`). Derive the expected SYSTEM set from the filesystem so a new collector cannot be added silently.

```python
import importlib, pkgutil
import src.data_collection as dc
from src.platform.capability_registry import ensure_bootstrapped, list_systems

EXEMPT = {"_finnhub_shared", "errors", "retention", "research_synthesizer"}  # non-collector helpers

def _collector_modules() -> set[str]:
    return {
        name for _, name, _ in pkgutil.iter_modules(dc.__path__)
        if name.endswith("_collector") and name not in EXEMPT
    }

def test_every_collector_module_registers_a_system():
    ensure_bootstrapped()
    registered_owners = {  # convention: SYSTEM whose name == module stem (minus _collector) or category=="data-collection"
        s.name for s in list_systems() if s.category == "data-collection"
    }
    # stronger form: import each module and assert it added >=1 SYSTEM
    missing = []
    for mod in sorted(_collector_modules()):
        before = len(list_systems())
        importlib.import_module(f"src.data_collection.{mod}")
        if len(list_systems()) == before and f"{mod}" not in registered_owners:
            missing.append(mod)
    assert not missing, (
        f"Collector modules with no @register_system: {missing}. "
        "Each collector must register a SYSTEM with category='data-collection'."
    )
```

**Derivation:** expected set = every `src/data_collection/*_collector.py` (minus a small, explicit `EXEMPT` allow-list of shared helpers). Forces all 24 collectors — including the three paid-but-dead-weight Finnhub ones (`company_executive`, `price_target`, `stock_financials`) — onto the ledger, and any future collector too.

### Convention C — **Every governor check name in `check_trade` must be a registered DECISION**

The governor emits a stable, machine-readable `name` for each check it appends to `checks` (e.g. `traffic_light`, `event_risk`, `emergency_halt`, `daily_loss`, …). Derive the expected DECISION set by running `check_trade` against a fixture portfolio and harvesting the emitted check names (or, lower-effort, assert against a small explicitly-maintained `GOVERNOR_GATES` constant defined next to the gate logic so the *gate list lives in the governor module, not the test*).

```python
# Preferred: a constant co-located with the gate logic in src/risk/governor.py
GOVERNOR_GATES = (
    "traffic_light", "event_risk", "deterministic_audit", "emergency_halt",
    "daily_loss", "position_size", "max_positions", "sector_concentration",
    "correlation", "volatility", "duplicate_position",
)

# tests/
from src.risk.governor import GOVERNOR_GATES
from src.platform.capability_registry import ensure_bootstrapped, list_decisions

def test_every_governor_gate_is_a_registered_decision():
    ensure_bootstrapped()
    registered = {d.name for d in list_decisions()}
    missing = {f"gate_{g}" for g in GOVERNOR_GATES} - registered
    assert not missing, f"Governor gates missing a register_decision: {sorted(missing)}"
```

**Derivation:** expected set = `{f"gate_{g}" for g in GOVERNOR_GATES}`, where `GOVERNOR_GATES` is defined *in the governor module beside the checks* — so adding a 9th check forces an edit to that tuple, which forces a matching registration. (If we prefer zero new constants, harvest the names dynamically from a `check_trade` dry-run instead.)

### Why these beat `>= 18`
- They derive the **expected** set from live code structures (a handler list, a filename glob, a gate tuple) rather than asserting a magic number. A new feature that skips its decorator changes the *expected* side but not the *registered* side → diff → CI red.
- They are **localized**: the oracle for each rule lives next to the feature (handler list, collector dir, governor gate tuple), so the rule self-updates as the platform grows.
- Start with **Convention A** (zero ambiguity, zero new constants, immediately catches the 16-handler gap), then **B** (the 24-collector gap), then **C**. Those three convert the worst drift (~67 of the ~95 missing) into CI-enforced coverage.

---

## 6. Caveats / coverage notes

- Subsystem→registry-type assignments for §3 are proposals based on reading each module's purpose; a few are judgment calls (e.g., reconcile *engine* SYSTEM vs the existing `reconcile_trades` health-proxy SYSTEM; ranker as DECISION vs ACTION). The Architect should ratify granularity before mass-registration.
- The "~95 missing / ~114 target" figure is a function of chosen granularity; the **structurally-unambiguous must-register sets** (16 handlers, 24 collectors, 8 governor checks) are firm.
- Not exhaustively line-read: every individual collector's internal health signal, and `src/api/cloud_routes/*` route handlers (these are transport, generally not capabilities). `src/api/routes/system_index.py` (local twin of the cloud endpoint) was confirmed to exist but not line-compared against the cloud version.
- `CAPABILITY_MODULES` in `bootstrap.py` is itself a hand-maintained list — even with Conventions A–C, a registered capability in a module *not* listed in `CAPABILITY_MODULES` won't load. A 4th guard ("every module containing a `@register_*` decorator appears in `CAPABILITY_MODULES`") would close that meta-gap.
