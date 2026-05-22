# Capability Registry Refresh — Implementation Plan

- **tasks:**

  ### 1
  - **id:** 1
  - **name:** Foundations: freshness + IO-schema helpers + GOVERNOR_GATES tuple + watch-handler CLI dispatcher
  - **description:** Create shared helpers, the governor gate oracle, and the REAL CLI kickoff dispatcher (DA-3). (a) src/data_collection/_capability_health.py exporting table_freshness_health(table, ts_col, stale_after_minutes, cadence_label) -> {status, detail, last_updated_at?} mirroring reconcile_state — lazy-imports connect_db/DB_PATH inside, catches connect failure AND DBOperationalError, returns ok/degraded/down, NEVER raises (degrade-not-raise). (b) src/platform/capability_registry/_io_schemas.py exporting simple_io_schema(properties=None, required=None) returning MCP-valid Draft-7 {type:object, properties, required, additionalProperties:False}. (c) Add module-level tuple GOVERNOR_GATES = ('traffic_light','event_risk','deterministic_audit','emergency_halt','daily_loss','position_size','max_positions','sector_concentration','correlation','volatility_halt','duplicate') to src/risk/governor.py beside check_trade (names == emitted check 'name' values, verified governor.py:628-820). (d) scripts/run_watch_handler.py: import-light CLI dispatcher — imports ALL_HANDLERS from src.scheduler.watch_handlers at top, defers WatchLoop import into main(); supports --list (print 16 handler __name__s), --handler <name> [--at ISO] [--force] (construct WatchLoop, set overnight=True if --force, call fn(watch, now)). This is the genuine kickoff_endpoint for Task 3's ACTIONs and resolves F-min-1.
  - **files_in_scope:**
    - src/data_collection/_capability_health.py
    - src/platform/capability_registry/_io_schemas.py
    - src/risk/governor.py
    - scripts/run_watch_handler.py
  - **files_read_only:**
    - src/shadow_trading/reconcile_state.py
    - src/platform/capability_registry/schemas.py
    - src/scheduler/watch_handlers.py
    - src/scheduler/watch.py
  - **depends_on:**
  - **test_strategy:** Unit test table_freshness_health against tmp SQLite (empty table -> degraded; one fresh row -> ok; missing table -> down; unconstructable DB path -> down, no raise). Unit test simple_io_schema passes Draft7Validator.check_schema and has type=object. Assert GOVERNOR_GATES is an 11-tuple with the exact emitted names. Smoke test scripts/run_watch_handler.py: `--list` prints exactly the 16 ALL_HANDLERS names; dispatching one handler with `--force --at 2026-05-21T19:00:00` returns 0 without raising (bare env).
  - **scope_fence:** Do NOT register any capability here. Do NOT modify check_trade logic — only ADD the GOVERNOR_GATES tuple. Do NOT touch bootstrap.py. Do NOT add helpers to schemas.py. Do NOT import WatchLoop at module top in run_watch_handler.py — defer into main() so --list works without the heavy loop.
  - **estimated_complexity:** medium

  ### 2
  - **id:** 2
  - **name:** Collectors -> 18 SYSTEMS + Convention B guard
  - **description:** Create src/data_collection/capability_registration.py registering all 18 *_collector.py modules as SYSTEMs via a metadata-table loop (§2.2), using the FUNCTIONAL register_system(...)(fn) form. SYSTEM name MUST equal the module stem (vix_collector -> SYSTEM vix_collector); category MUST be 'data-collection'; each health fn delegates to table_freshness_health with that collector's owned table + ts column (read each collector to find its table; vix->vix_term_structure/collected_at). maintainer=ai_session, introduced_in='v0.36.0', last_reviewed_date=date(2026,5,21). Add 'src.data_collection.capability_registration' to CAPABILITY_MODULES. Add Convention B to the new coverage test: glob *_collector.py via pkgutil, EXEMPT=empty set with a documented contract docstring (add a stem here ONLY if it hosts no real collector; each entry needs a reason), assert each stem has a matching category=='data-collection' SYSTEM.
  - **files_in_scope:**
    - src/data_collection/capability_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/data_collection/_capability_health.py
    - src/data_collection/vix_collector.py
    - src/data_collection/__init__.py
    - src/shadow_trading/reconcile_state.py
  - **depends_on:**
    - 1
  - **test_strategy:** Convention B test (every collector stem -> SYSTEM). Health-executes: all 18 health fns return {status in ok/degraded/down} against tmp SQLite seeded with each owned table from src.schema.registry.TABLES, AND against a bare env (missing tables -> down, no raise). Assert bootstrap loads capability_registration with zero error.
  - **scope_fence:** Do NOT add @register_system decorators inside individual collector modules — register en-bloc only. Do NOT register short_volume_finra/options_metrics/retention/research_synthesizer (not *_collector.py). Do NOT implement Conventions A/C/D/E here. Owned-table names are code constants — do not parameterize from user input.
  - **estimated_complexity:** medium

  ### 3
  - **id:** 3
  - **name:** Watch handlers -> 16 ACTIONS (real kickoff + real input_schema) + Convention A guard
  - **description:** Create src/scheduler/handler_registration.py importing ALL_HANDLERS from src.scheduler.watch_handlers and registering each as an ACTION via a per-handler metadata table. ACTION name MUST equal the maybe_-stripped handler __name__ (maybe_stress_test->stress_test, maybe_1min_bar_collection->1min_bar_collection) so Convention A passes — DO NOT use inventory §3b cosmetic names. category='scheduler'; kickoff_endpoint='python scripts/run_watch_handler.py --handler <handler_name>' (the REAL dispatcher from Task 1, DA-3); input_schema=simple_io_schema({'at':{type:string,format:date-time}, 'force':{type:boolean}}, []) — a NON-EMPTY schema reflecting the dispatcher's real trigger params; output_schema=simple_io_schema(); estimated_duration per handler; maintainer=ai_session, introduced_in='v0.36.0', last_reviewed_date=date(2026,5,21). Anchor fn returns static dict. Add module to CAPABILITY_MODULES. Add Convention A to coverage test WITH the no-collision and plain-maybe_-fn assertions.
  - **files_in_scope:**
    - src/scheduler/handler_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/scheduler/watch_handlers.py
    - src/platform/capability_registry/_io_schemas.py
    - scripts/run_watch_handler.py
    - src/diagnostics/__init__.py
  - **depends_on:**
    - 1
  - **test_strategy:** Convention A test: every ALL_HANDLERS handler -> ACTION with stripped name; assert len({stripped})==len(ALL_HANDLERS) (no collisions); assert each handler is a plain maybe_-prefixed function. Assert all 16 ACTIONs have valid Draft-7 input/output schemas with the {at,force} properties. Assert kickoff_endpoint passes the .py/scripts CLI check in the metadata test.
  - **scope_fence:** Do NOT import src.scheduler.watch (heavy WatchLoop) — import only ALL_HANDLERS from watch_handlers. Do NOT add decorators inside watch_handlers.py. Do NOT rename handlers. Do NOT use empty {type:object} schemas — use the real {at,force} schema. Do NOT implement B/C/D/E here.
  - **estimated_complexity:** medium

  ### 4
  - **id:** 4
  - **name:** Governor gates -> 11 DECISIONS + risk_governor SYSTEM + drawdown DECISION + Convention C (definition-enumeration)
  - **description:** Create src/risk/gate_decisions.py importing GOVERNOR_GATES and loop-registering 11 DECISIONs named gate_<g> (functional register_decision form) with hand-authored decision_text/rationale/revisit_trigger per gate in a _GATE_META dict (category='risk-governor', maintainer=operator, introduced_in='v0.14.0', last_reviewed_date=date(2026,5,21)). Add the F-min-2 completeness assert at module top: assert set(_GATE_META)==set(GOVERNOR_GATES) with a precise missing/extra message (fails before the loop, not a bare KeyError). Also register risk_governor SYSTEM (health = governor enabled + config sane; lazy-import config; degrade-not-raise -> {status:degraded} on unavailable config) and decision_drawdown_adjusted_risk DECISION (Thorp bet reduction, governor.py:338). Add 'src.risk.gate_decisions' to CAPABILITY_MODULES. Add Convention C (definition-enumeration: {gate_<g> for g in GOVERNOR_GATES} subset of decisions — NO check_trade dry-run, DA-4) + the C-companion static source-scan test (test_governor_gates_tuple_matches_source: regex the "name":"..." literals in governor.py, minus {input_surface, governor_disabled}, assert == set(GOVERNOR_GATES)).
  - **files_in_scope:**
    - src/risk/gate_decisions.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/risk/governor.py
    - src/platform/capability_registry/decisions.py
  - **depends_on:**
    - 1
  - **test_strategy:** Convention C test ({gate_<g>} subset of decisions). C-companion #1: in-module assert set(_GATE_META)==set(GOVERNOR_GATES) (import succeeds). C-companion #2: static source-scan asserts GOVERNOR_GATES == the gate-name literals in governor.py minus framework checks (robust to short-circuit — NO dry-run of check_trade). risk_governor health fn executes -> valid status dict in a bare env (no raise). Assert no name collision with the existing 4 decisions.
  - **scope_fence:** Register gate DECISIONs in gate_decisions.py only — NOT in decisions.py (keep structural gates separate from strategic facts). Do NOT modify check_trade logic. Do NOT harvest gate names from a check_trade dry-run — it short-circuits (governor.py:613/680) so no fixture emits all 11; enumerate definitions instead. gate names MUST be gate_volatility_halt and gate_duplicate (emitted names), NOT gate_volatility/gate_duplicate_position. Do NOT implement A/B/D/E here.
  - **estimated_complexity:** medium

  ### 5
  - **id:** 5
  - **name:** Execution / exits family registrations (keep 3)
  - **description:** Co-locate registrations for the trimmed keep-set (exactly 3, DA-1): submit_shadow_trade (ACTION, anchor near executor.open_shadow_trade:557, kickoff = real route or CLI, real input_schema), position_exit_manager (SYSTEM, health = open-trade freshness via MAX(updated_at) on active shadow_trades — reuse table_freshness pattern, degrade-not-raise), trade_reconciler (SYSTEM engine, distinct name from existing reconcile_trades proxy; health = reconcile freshness). Use a thin src/shadow_trading/capability_registration.py if executor.py top-level import is heavy; otherwise co-locate. Add host to CAPABILITY_MODULES. DEFER exit_reason_classifier, decision_trade_alerts, bracket_monitor to backlog AND seed them into Convention E's EXEMPT_MODULES (with reasons) in the coverage test.
  - **files_in_scope:**
    - src/shadow_trading/capability_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/shadow_trading/executor.py
    - src/shadow_trading/reconcile_state.py
    - src/data_collection/_capability_health.py
    - src/shadow_trading/state.py
  - **depends_on:**
    - 1
  - **test_strategy:** Add these SYSTEM health fns + ACTION schema to the coverage health-executes test (bare env, no raise). Assert names don't collide with reconcile_trades/alpaca_account/shadow_trade_cohort. Assert ACTION schema valid Draft-7. Add the 3 deferred modules to EXEMPT_MODULES so Convention E (Task 10) stays green.
  - **scope_fence:** Do NOT re-register reconcile_trades (engine gets the distinct name trade_reconciler). Do NOT register exit_reason_classifier/decision_trade_alerts/bracket_monitor/qty_mismatch/broker_exception (deferred — EXEMPT them). Do NOT modify executor trading logic. Keep anchor import-light; defer heavy imports into health/anchor bodies. Keep-set is exactly 3.
  - **estimated_complexity:** medium

  ### 6
  - **id:** 6
  - **name:** Scan / LLM / council family registrations (keep 3)
  - **description:** Co-locate trimmed keep-set (exactly 3, DA-1): llm_scorer (SYSTEM, src/llm — health = Ollama reachable/last-score; lazy import; degrade-not-raise -> {status:down,'Ollama unreachable'} when no Ollama), council_engine (SYSTEM, src/council — health = last council run; lazy import; degrade on missing), build_decision_packet (ACTION, src/llm/packet_writer.py — real route/CLI kickoff + input_schema). Use thin */capability_registration.py hosts (council/engine.py and llm/client.py have heavy import graphs). Add hosts to CAPABILITY_MODULES. DEFER candidate_ranking, build_watchlist, trade_postmortem, council_aggregation, eod_recap to backlog AND seed into Convention E EXEMPT_MODULES.
  - **files_in_scope:**
    - src/llm/capability_registration.py
    - src/council/capability_registration.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/council/engine.py
    - src/llm/packet_writer.py
    - src/llm/client.py
    - src/platform/capability_registry/_io_schemas.py
  - **depends_on:**
    - 1
  - **test_strategy:** Add SYSTEM health (llm_scorer, council_engine) + ACTION schema (build_decision_packet) to coverage health-executes test — MUST return a status dict in a bare env (no Ollama, no .env) without raising. Assert bootstrap clean (no import cycle from council/llm). Add deferred modules to EXEMPT_MODULES.
  - **scope_fence:** Both new capability_registration.py hosts must be added to CAPABILITY_MODULES (this task edits bootstrap.py too — coordinate with Integrator). Do NOT register candidate_ranking/build_watchlist/trade_postmortem/council_aggregation/eod_recap (deferred — EXEMPT them). Do NOT import heavy engine classes at module top — lazy import inside health fns. Keep-set is exactly 3. Do NOT implement guards here.
  - **estimated_complexity:** medium

  ### 7
  - **id:** 7
  - **name:** Training pipeline family registrations (keep 3)
  - **description:** Co-locate trimmed keep-set (exactly 3, DA-1): run_finetune (ACTION, src/training/trainer.py — real route/CLI kickoff + input_schema), model_promotion_gate (DECISION — grouped: folds 50-trade gate + canary + promotion criteria into one), training_quality_filter (DECISION — grouped: quality + drift + leakage + ingestion). Co-locate in a thin src/training/capability_registration.py (training graph is heavy). Add to CAPABILITY_MODULES. DEFER evaluate_holdout, rollback_model, build_training_corpus, run_dpo to backlog AND seed into Convention E EXEMPT_MODULES.
  - **files_in_scope:**
    - src/training/capability_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/training/trainer.py
    - src/training/versioning.py
    - src/evaluation/gate_evaluator.py
    - src/services/training_service.py
  - **depends_on:**
    - 1
  - **test_strategy:** Add ACTION schema (run_finetune) + 2 DECISION entries to coverage. Assert no collision with existing training_corpus state / training_data_audit action. Assert bootstrap clean (training graph can be heavy — verify no cycle). Add the 4 deferred modules to EXEMPT_MODULES.
  - **scope_fence:** Do NOT re-register training_corpus (existing state) or training_data_audit (existing action). Do NOT register evaluate_holdout/rollback_model/build_training_corpus/run_dpo (deferred — EXEMPT them). model_promotion_gate and training_quality_filter are each ONE grouped decision — do not split. Keep anchors import-light. Keep-set is exactly 3.
  - **estimated_complexity:** medium

  ### 8
  - **id:** 8
  - **name:** Evaluation / audit family registrations (keep 3)
  - **description:** Co-locate trimmed keep-set (exactly 3, DA-1): system_auditor (SYSTEM, src/evaluation/auditor.py — health = last audit_reports freshness via table_freshness_health; note two-layer-staleness in description; degrade-not-raise), model_monitor (SYSTEM, src/evaluation/model_monitor.py — health = last drift-check freshness; degrade-not-raise), run_backtest (ACTION engine, distinct from existing strategy_backtest wrapper — real route/CLI kickoff + input_schema). Co-locate or thin src/evaluation/capability_registration.py. Add to CAPABILITY_MODULES. DEFER system_validator, walkforward_validation, build_scorecard, change_detector, monte_carlo_sim to backlog AND seed into Convention E EXEMPT_MODULES.
  - **files_in_scope:**
    - src/evaluation/capability_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/evaluation/auditor.py
    - src/evaluation/model_monitor.py
    - src/data_collection/_capability_health.py
    - src/platform/__init__.py
  - **depends_on:**
    - 1
  - **test_strategy:** Add SYSTEM health (system_auditor, model_monitor) + ACTION schema (run_backtest) to coverage health-executes test (bare env, no raise). Assert run_backtest does not collide with strategy_backtest. Assert bootstrap clean. Add the deferred modules to EXEMPT_MODULES.
  - **scope_fence:** Do NOT re-register strategy_backtest (existing) or nightly_audit_agent (existing). Do NOT register system_validator/walkforward_validation/build_scorecard/change_detector/monte_carlo_sim (deferred — EXEMPT them). Keep import-light; lazy-import audit/monitor internals inside health fns. Keep-set is exactly 3.
  - **estimated_complexity:** medium

  ### 9
  - **id:** 9
  - **name:** Notifications / attribution family registrations (keep 2)
  - **description:** Co-locate trimmed keep-set (exactly 2, DA-1): telegram_notifier (SYSTEM, src/notifications/telegram.py — health = token-configured + last-send; degrade-not-raise -> {status:degraded,'not configured'} when no token, NEVER raise on missing .env), spy_benchmark_state (STATE, src/analytics/spy_benchmark.py — query returns {value:{...}}, refresh_hint; degrade to {value:None} on missing source). Add host(s) to CAPABILITY_MODULES. DEFER telegram_command_handler, notification_policy, platform_event_bus, attribution_backtest to backlog AND seed into Convention E EXEMPT_MODULES.
  - **files_in_scope:**
    - src/notifications/capability_registration.py
    - src/platform/capability_registry/bootstrap.py
    - tests/test_capability_registry_coverage.py
  - **files_read_only:**
    - src/notifications/telegram.py
    - src/analytics/spy_benchmark.py
    - src/notifications/policy.py
    - src/attribution/logger.py
  - **depends_on:**
    - 1
  - **test_strategy:** Add SYSTEM health (telegram_notifier) + STATE query (spy_benchmark_state) to coverage health/query-executes test — MUST return a dict in a bare env (no .env, no Telegram token) without raising. Assert spy_benchmark_state query returns dict with value key. Assert no collision with attribution_resolver (existing system). Add deferred modules to EXEMPT_MODULES.
  - **scope_fence:** Do NOT re-register attribution_resolver (existing proxy). Do NOT register telegram_command_handler/notification_policy/platform_event_bus/attribution_backtest (deferred — EXEMPT them). Do NOT register route handlers in src/api/. Keep-set is exactly 2 (this family is the -1 that lands the total at 80).
  - **estimated_complexity:** medium

  ### 10
  - **id:** 10
  - **name:** Capstone: Convention D + Convention E + floor raise (>=80) + metadata extension + last_reviewed verify + backlog
  - **description:** (a) Add Convention D to coverage test: rglob src/*.py with encoding='utf-8', regex catching BOTH @register_* AND functional register_*( forms (the en-bloc loop modules use the functional form), map to dotted module, exclude registry.py/schemas.py/__init__.py but REQUIRE decisions.py + audit_registration + all new *capability_registration*/gate_decisions/handler_registration modules, assert subset of CAPABILITY_MODULES; add the D self-test proving the regex catches the functional form. (b) Add Convention E (DA-2): walk CAPABILITY_PACKAGES (shadow_trading, llm, council, training, evaluation, notifications, ranking, analytics), assert every business-logic module either registers (directly or via a sibling capability_registration.py) OR is in EXEMPT_MODULES; assemble the full EXEMPT_MODULES manifest from the deferred sets seeded by Tasks 5-9 plus pure helpers. (c) In tests/test_capability_registry_integration.py raise BOTH `>= 18` assertions (lines ~88 AND ~128) -> `>= 80` and update messages. (d) Extend tests/test_capability_registry_metadata.py: assert every collector SYSTEM has category=='data-collection'. (e) Verify all newly-added entries carry last_reviewed_date=date(2026,5,21); leave the existing 19 untouched. (f) Run full suite; confirm zero CAPABILITY_REGISTRY_BOOTSTRAP_ERROR and total == 80. (g) Write docs/audits/2026-05-21-capability-registry/deferred_backlog.md recording the deferred set (exit_reason_classifier, decision_trade_alerts, bracket_monitor, candidate_ranking, build_watchlist, trade_postmortem, council_aggregation, eod_recap, evaluate_holdout, rollback_model, build_training_corpus, run_dpo, system_validator, walkforward_validation, build_scorecard, change_detector, monte_carlo_sim, telegram_command_handler, notification_policy, platform_event_bus, attribution_backtest) with one-line metadata each.
  - **files_in_scope:**
    - tests/test_capability_registry_coverage.py
    - tests/test_capability_registry_integration.py
    - tests/test_capability_registry_metadata.py
    - docs/audits/2026-05-21-capability-registry/deferred_backlog.md
  - **files_read_only:**
    - src/platform/capability_registry/bootstrap.py
    - src/platform/capability_registry/registry.py
  - **depends_on:**
    - 2
    - 3
    - 4
    - 5
    - 6
    - 7
    - 8
    - 9
  - **test_strategy:** Convention D passes (all registering modules, decorator AND functional, listed) + D self-test green. Convention E passes (every capability-package module registers or is EXEMPT). Full coverage suite (A/B/C/C-companions/D/E + health-executes bare-env) green. BOTH integration floors >=80 green. Metadata test green over 80 entries. Endpoint round-trip 200. Zero bootstrap errors. Assert all_entries() total == 80 exactly.
  - **scope_fence:** Do NOT modify the 19 existing entries' metadata (keep last_reviewed_date=2026-04-18). Do NOT add new capability registrations here — capstone is guards + floor + verification + backlog only. Do NOT weaken any guard to make it pass; fix the missing registration (or add a justified EXEMPT_MODULES entry with a reason) in the owning family task instead. Both integration-test floor assertions (line ~88 AND line ~128) must be raised — do not miss the second one.
  - **estimated_complexity:** medium
- **execution_order:**
  - [1]
  - [2, 3, 4]
  - [5, 6, 7, 8, 9]
  - [10]
- **notes:** Batch 1 (foundations) lands first — helpers + GOVERNOR_GATES + the real run_watch_handler.py dispatcher (DA-3) unblock everyone. Batches 2/3/4 each pair a firm structural registration set (18 collectors / 16 handlers / 11 gates) with its guard (B/A/C) so each is independently reviewable; mutually independent, run in parallel. Batches 5-9 are independent heterogeneous families with TRIMMED keep-sets summing to exactly 14 (T5=3, T6=3, T7=3, T8=3, T9=2) so the grand total is 19+47+14=80 (DA-1). Each of 5-9 also seeds its deferred modules into Convention E's EXEMPT_MODULES. Task 10 is the capstone gate: Convention D (broadened regex catches the functional register_x( form used by the en-bloc loops — DA-minor) + Convention E (per-package presence guard closing the heterogeneous drift surface — DA-2) + both floor-raises (>=80) depend on ALL registrations existing, so it lands last. CRITICAL sequencing invariant: no guard (A/B/C/D/E) is ever merged before its target registrations; D and E in particular would red-CI every prior PR if landed early, hence depends_on=[2..9]. If any guard fails, fix the missing registration (or add a justified EXEMPT entry) in the owning family task; never weaken the guard. CONCURRENT-EDIT HOTSPOTS: bootstrap.py (CAPABILITY_MODULES tuple) and tests/test_capability_registry_coverage.py are touched by tasks 2-10; the Integrator must merge family batches sequentially or assign clearly-delimited append sections to avoid conflicts.
- **_concurrent_edit_note:** bootstrap.py and tests/test_capability_registry_coverage.py are append-only hotspots across tasks 2-10 (each family appends to CAPABILITY_MODULES, to the health-executes test, and to Convention E's EXEMPT_MODULES). Recommend the Integrator merges family batches sequentially, or each task appends to a distinct, clearly-delimited section. Task 1's scripts/run_watch_handler.py is a new file with no concurrent contention.