# Changelog

## [Unreleased]

- **docs(operator-guide): T9 — Sprint 2 closeout / methodology gate runbook.** Adds §10 "Daily methodology-gate workflow" to `docs/operator-guide.md` covering: (a) what the daily 16:35 ET sweep does — `watch.py` fires `run_daily_gate_for_all_active_strategies`, iterates `shadow_trading`/`backtested` strategies, persists `triggered_by='gate_proposal'` rows with `from_status==to_status`, logs `[METHODOLOGY_GATE]` + sends Telegram when enabled; (b) how to read the digest — Telegram message format, `logs/arcis.log` search pattern, `strategy_promotion_events` SQL query; (c) how to interpret evidence JSON — complete field-by-field reference for `decision`, `threshold_used`, `votes` flat dict (`cpcv`/`block_bootstrap`/`mc_perm`/`psr_dsr`/`white_rc`, each `true|false|null`), `details.{n_pass,n_fail,n_abstentions,instrumentation_excluded_count}`, `walkforward_status` (`no_data_yet|pass|fail|inconclusive`), no `pbo` in votes, no top-level `tally`; (d) running confirm-promotion end-to-end — cross-links §3 CLI syntax, emphasizes Critical-1 thin-wrapper design (no synthetic-outcome bypass), staleness guard, reject-not-overridable; (e) troubleshooting defer outcomes — abstention-cause table for `mc_perm`/`psr_dsr`/`white_rc`/all-abstain/null-entry-time, diagnostic SQL, general formula; (f) bootstrap-window `walkforward_status='no_data_yet'` — first-30-days walkforward sequencing, correct interpretation, `scripts/smoke_gate_9_fold1.bat` reference; (g) feature-flag + STRICT_GATE 2×2 matrix — all four combinations documented, production default (`METHODOLOGY_GATE_ENABLED=true`, `STRICT_GATE=false`), emergency-disable pattern; (h) Sprint 2 limitations §1.3.1 — long-only MC permutation degeneracy, trainer/kpi 3-of-5 ceiling, watch.py daily orchestrator as promote-capable path, regression-lock reference; (i) production-gate asymmetry §1.2 — `backtested→shadow_trading` checks walkforward+DSR+PBO, `shadow_trading→production` checks DSR only (PBO/oos_efficiency Sprint-4 placeholders), locked by integration test. Also updates §0.2, §0.4, §8 Glossary ("Promotion gate"), §9 Roadmap pointer to reflect gate is now live. Section placed as new §10 (insertion before existing §10 Update Protocol, which becomes §11). Cross-links to existing §3 T5 confirm-promotion CLI content — no duplication. PR #982. **Sprint 2 closeout summary:** the methodology gate end-to-end is now LIVE in production. T1 (#961) documented the new triggered_by sentinels; T2 (#976) wired `_evaluate_strategy_methodology_gate` at 7+1 AND-compose sites in platform.promotion; T3 (#975) fixed three pre-existing bugs in the trainer call sites + locked the Choice A long-only regression; T4 (#977) wired the daily 16:35 ET firing into watch.py; T5 (#978) shipped the operator confirm-promotion CLI (Critical-1: thin `promote()` wrapper, no synthetic-outcome bypass); T6 (#979) added the analytics aggregation function; T7 (#980) surfaced the gate-proposal KPI in the dashboard read API; T8 (#981) locked the 15 critical+major safety properties via cross-cutting integration tests. The Choice A degeneracy is documented + ceiling-locked at 3-of-5 via the trainer path; the production-gate asymmetry (DSR-only vs walkforward+DSR+PBO) is documented + locked. Feature flag `METHODOLOGY_GATE_ENABLED` retained for short-circuit; `STRICT_GATE` env var documented in the runbook 2×2 matrix.

- **test: T8 — cross-cutting integration tests for methodology gate (15 named locks).** Sprint 2 T8 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §6 + plan §T8. New `tests/test_methodology_gate_integration.py` (~930 lines, 18 tests) locks the 15 critical+major safety properties spanning `src/platform/promotion.py` + `src/scheduler/watch.py` + `src/cli/promotion_cmd.py` + `src/methods/promotion_gate.py` + `src/training/trainer.py` + `src/analytics/instrumentation_filter.py`. Each test name corresponds 1:1 to a critical or major review finding from spec v5. The 15 named locks: `test_operator_confirm_calls_promote_not_synthetic_outcome` (Critical-1), `test_reject_outcome_not_overridable_via_cli` (Decision 4), `test_and_composition_with_walkforward_blocks_methodology_only_pass`, `test_methodology_gate_and_composed_at_walkforward_pass_path` (DA major fix 1), `test_partial_instrumentation_excluded_from_gate_input`, `test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key`, `test_feature_flag_disabled_short_circuits_persistence`, `test_gate_proposal_row_has_from_status_eq_to_status`, `test_operator_confirm_row_has_real_transition` (Major 4), `test_methodology_gate_evidence_schema_matches_decide_function` (DA major fix 2), `test_production_gate_methodology_compose_with_dsr_only` (DA major fix 5), `test_walkforward_status_populated_for_all_four_states` (DA major fix 4, parametrized + `no_data_yet` companion), `test_walkforward_outcome_state_still_populated_for_backwards_compat` (DA major fix 4), `test_cli_confirm_promotion_re_fire_includes_methodology_gate` (Minor 1 / T5-T2 ordering ratchet), `test_trainer_promotion_gate_currently_cannot_promote_long_only` (Choice A regression-lock per spec §1.3.1). All hermetic — sqlite tmp_path + schema-registry init via `create_all_tables()` (or `init_training_tables` + `initialize_database` for the trainer-path test); FRED mocked via the `_mock_fred` autouse fixture pattern locked by PR #975. **PM-rescue note:** dispatched developer agent hit a 500 API error after 26 tool uses with the file fully written (928 lines, all 15 names present). 17/18 tests passed on first run; PM fixed 1 test that referenced a non-existent `strategy_versions` table (canonical name is `model_versions` per `src/schema/registry.py:430`) by replacing the manual setup with the T3 canonical pattern (`init_training_tables` + `model_versions` insert + FRED mock + `tmp_path` fixture). Also relaxed an over-specified mc_perm-vote assertion to a weaker n_pass≤3 ceiling check that matches the spec §1.3.1 invariant. Test runtime: 11.91s. NO modifications to any file under `src/`. PR #981.

- **feat(api): T7 — surface methodology gate-proposal KPI in dashboard route.** Sprint 2 T7 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §4 + plan §T7. New endpoint `GET /api/kpis/gate-proposals` in `src/api/cloud_routes/kpis.py` (NOT `src/api/dashboard_routes.py` — the plan path was incorrect; PM caught the drift via Glob and corrected during dispatch). Implementation choice **A** (sub-route, not response-extension): cleaner separation of concerns, does not change the existing `/kpis` contract, easier to evolve independently. Calls `src.analytics.kpis_compute.get_gate_proposal_counts(DB_PATH)` (T6 deliverable) — module imported via `from src.analytics import kpis_compute as _analytics_kpis` so test patches at `src.analytics.kpis_compute.get_gate_proposal_counts` work as expected. Catches `sqlite3.OperationalError` (fresh-deployment / table-not-yet-created path) and returns canonical zero shape with WARNING log so the dashboard does not show an error card before the first daily watch.py run lands a row. Auth via the existing `verify_auth` placeholder dep (overridden by cloud_app at mount time — same pattern as walkforward.py / broker_exceptions.py). 6 hermetic tests in `tests/test_dashboard_gate_kpi_route.py`: `test_route_returns_200_when_table_empty` (canonical zero shape), `test_route_response_matches_kpis_compute_output` (route passes through compute output cleanly), `test_route_excludes_operator_confirm_rows` (T6 compute call exercised against a real seeded sqlite to verify the operator_confirm exclusion filter; route data path is mock-passthrough since route shape/auth are covered independently by tests 1+2+4+5), `test_route_requires_auth` + `test_route_rejects_wrong_token` (401 without Bearer / with wrong Bearer), `test_route_handles_missing_table_gracefully` (200 + zero shape on `OperationalError`). NO frontend changes; pure read-side endpoint. NO modifications to `src/api/cloud_routes/kpis_compute.py` (T3-modified compute module — distinct from the T6 analytics module). PM-rescue note: dispatched developer agent stalled (watchdog timeout) after adding only the import line to kpis.py + completing the test file; PM completed the route implementation, fixed the import to use module-level binding so `patch("src.analytics.kpis_compute.get_gate_proposal_counts")` works, ran tests (6/6 pass in 1.00s), commit + push.

- **feat(analytics): T6 — KPI compute for methodology gate proposals (counts by decision over 1d/7d/30d).** New `src/analytics/kpis_compute.py` module with `get_gate_proposal_counts(db_path)` — reads `strategy_promotion_events` filtered by `triggered_by='gate_proposal'` and returns decision counts (`promote`, `reject`, `defer`, `unknown`) bucketed by 1d/7d/30d rolling UTC windows. `operator_confirm` rows are excluded (they are real promotion transitions, not gate-proposal observations). Malformed/NULL `gate_result_json` rows land in `unknown` bucket rather than raising. Decision extracted from `gate_result_json['methodology_gate']['decision']`. 6 hermetic tests in `tests/test_kpis_compute_gate.py`. Sprint 2 T6.

- **feat(cli): T5 — confirm-promotion command (thin promote() wrapper).** Sprint 2 T5 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/spec.md §4.4`. New `src/cli/promotion_cmd.py` module with `cmd_confirm_promotion(args)` command and `build_confirm_promotion_parser()`. Wired into `src/main.py` as the `confirm-promotion` subcommand. Critical-1 design constraint enforced: the CLI delegates entirely to `platform.promotion.promote(triggered_by='operator_confirm', ...)` — it does NOT call `_apply_gate_outcome` with a synthetic outcome, does NOT write `strategy_promotion_events` rows directly, and does NOT bypass `promote()`'s server-side re-fire of `check_promotion_gate`. Pre-checks added for operator ergonomics only: (1) client-side justification length guard (`len(justification.strip()) >= 40`, exit 4 if violated, server-side enforcement at `promote()` lines 402-407 remains authoritative); (2) load latest `triggered_by='gate_proposal'` row — exit 4 if missing or older than 24h (Decision 14 stale-proposal guard); (3) Decision 4 reject guard — CLI refuses if gate_proposal has `decision='reject'`, with error message citing "reject is not overridable"; (4) display proposal evidence (decision/votes/walkforward_status/threshold_used) and y/N prompt (skipped with `--yes`); (5) on `promote()` `ValueError` (gate re-fire rejection, data drift): exit non-zero, print reason, NO event_id; (6) on success: print event_id + final_status, exit 0. Sibling-search finding: `_apply_gate_outcome` has ZERO callers in `src/` (grep confirms) — the CLI does not join any such path. 10 new tests in `tests/test_cli_confirm_promotion.py` (all hermetic, mock FRED via autouse fixture): `test_operator_confirm_calls_promote_not_synthetic_outcome` (Critical-1 lock — asserts `promote` called with `triggered_by='operator_confirm'` + namespace guard); `test_apply_gate_outcome_not_imported_in_promotion_cmd` (structural namespace guard); `test_reject_outcome_not_overridable_via_cli` (Decision 4); `test_stale_proposal_rejected_by_cli` (Decision 14, 25h-old row); `test_short_justification_rejected_client_side` (client-side length check, 8-char input); `test_no_gate_proposal_exits_4`; `test_promote_re_fires_gate_server_side` (promote() raises ValueError, CLI exits non-zero, no event_id); `test_operator_confirm_row_has_real_transition` (Major 4, backtested→shadow_trading shows real status delta); `test_successful_confirm_prints_event_id`; `test_cli_confirm_promotion_re_fire_includes_methodology_gate` (Minor 1 / T5-T2 ordering ratchet — patches `_evaluate_strategy_methodology_gate` and asserts it fires during CLI's promote() path). `docs/operator-guide.md` updated: §3 Common Commands gains `confirm-promotion` usage; §7 Maintenance Tasks gains the daily confirmation workflow. `config/known_violations.json` not updated (promotion_cmd.py is 165 lines, below the 200-line guardrail). PR #978.

- **feat(scheduler): T4 — wire daily 16:35 ET methodology gate firing into watch.py.** Sprint 2 T4 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §4.2. Adds `self._strategy_gate_done = False` flag in `WatchLoop.__init__` (immediately after `_postclose_reconcile_done`) and in `_reset_daily_state` so the gate fires once per trading day and auto-resets at midnight. New daily-loop slot in `_run_sync_body` IMMEDIATELY after the post-close-reconcile block: slot guard `hour==16 and now.minute>=35 and not self._strategy_gate_done`. Late-imports `run_daily_gate_for_all_active_strategies` inside the method body (critical: top-level import would create a circular-import risk — promotion.py → src.config → triggered at watch.py module load). Wraps the call in `self._safe_run("strategy methodology gate", lambda: ...)` per CLAUDE.md `_safe_run` discipline; sets `_strategy_gate_done=True` ONLY on success (conditional done-flag). Passes `db_path=DB_PATH, notify=self._notify_gate_proposal`. Adds `_notify_gate_proposal(strategy_id, evidence)` helper (stub per spec §4.2): logs `[METHODOLOGY_GATE] proposal for <id>: decision=<decision>` and sends a Telegram message when `is_telegram_enabled()`. Sibling-search for the `_safe_run(...); _done = True` antipattern (unconditional set) across all 22+ existing `_safe_run` call sites in watch.py: confirmed ALL existing sites use the correct `if self._safe_run(...): self._done = True` pattern — no antipatterns present. `config/known_violations.json` updated: `watch.py` line count 2085→2262 (within tolerance band; +177L from new slot + helper + comments); `_run_sync_body` 619→652 lines (still within tolerance band). 8 new tests in `tests/test_watch_strategy_gate.py`: `test_watch_loop_fires_at_16_35_ET`, `test_watch_loop_fires_at_16_35_ET_via_safe_run`, `test_watch_loop_idempotent_within_day`, `test_watch_loop_resets_flag_at_day_roll`, `test_late_import_avoids_circular`, `test_strategy_gate_done_initialized_in_init`, `test_notify_gate_proposal_helper_exists`, `test_notify_gate_proposal_does_not_raise`.

- **feat(promotion): T2 — wire methodology gate into platform.promotion (AND-compose at 7+1 sites; walkforward_status; production-gate asymmetry).** Sprint 2 T2 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/spec.md`. Adds `_evaluate_strategy_methodology_gate(strategy_id, db_path) -> tuple[bool, dict]` helper that loads per-strategy shadow_trades, applies `is_fully_instrumented` + `actual_entry_time IS NOT NULL` filter, builds MethodInputs (returns + dates + directions; long-only `[+1]*N`), calls `methods.promotion_gate.promotion_gate()`. Evidence schema matches `_decide` per spec §3.2 — vote keys flat `bool|None` (`cpcv`, `block_bootstrap`, `mc_perm`, `psr_dsr`, `white_rc`); per-vote `details[name]` separate; counts at `details.{n_pass, n_fail, n_abstentions}`; no `pbo` in vote map; no top-level `tally`. AND-composes at all SEVEN return sites of `_evaluate_shadow_trading_gate` including the wf-PASS-PBO-PASS success branch at line 298 (DA major fix 1; was missing in v4 plan) — locked by `test_methodology_gate_and_composed_at_walkforward_pass_path`. AND-composes at the ONE return site of `_evaluate_production_gate` (DSR-only per Sprint-4 placeholders for PBO/oos_efficiency; DA major fix 5). New `walkforward_status` evidence key inside `_evaluate_walkforward_gate` ALONGSIDE existing `walkforward_outcome_state` (backwards-compat); values `'no_data_yet' | 'pass' | 'fail' | 'inconclusive'` (DA major fix 4). New top-level `run_daily_gate_for_all_active_strategies(db_path, notify=None)` orchestrator iterating `get_strategies_by_status(['shadow_trading','backtested'])` and persisting `triggered_by='gate_proposal'` rows with `from_status==to_status`, `justification_note=None`. `METHODOLOGY_GATE_ENABLED=false` short-circuits to `(True, {'decision':'skipped'})` with NO persistence. 4-of-4 fallback when `len(active_research_strategies) < 2` with `threshold_used='4_of_4_no_white_rc'`. **Pre-merge schema verification per Performance reviewer REJECT on initial commit:** reviewer flagged a perceived "missing `strategy_id = ?` filter" in the shadow_trades SELECT, asserting the query loads cross-strategy returns. Schema verification (`src/schema/registry.py:196-275`) shows `shadow_trades` has NO `strategy_id` column — adding the predicate would raise `no such column: strategy_id`. The system is single-strategy today (every shadow_trade belongs to the one active "pullback" strategy by definition); the helper's `strategy_id` parameter is kept for forward-compat with future multi-strategy schema (T-FOLLOWUP). Added explanatory in-code comment so future readers understand the parameter is intentionally not in the SQL. Added `ORDER BY actual_entry_time ASC` so the dates list passed to promotion_gate is monotonic. Reviewer's HIGH dead-code finding (active_strategies fetch with `candidate_pool=None` in both branches) deferred to follow-up task — non-blocking; semantically correct given current single-strategy world (White RC abstains either way). 13 new tests in `tests/test_promotion_methodology_gate.py` (15 pass with 2 parametrize variants in 9.79s, hermetic). Disclosed in `config/known_violations.json`: promotion.py 527→811 lines (T2 integration; real split deferred to Sprint 3 via sibling `promotion_gate_wiring.py`); `_evaluate_strategy_methodology_gate` 129 lines (NEW); `_evaluate_shadow_trading_gate` 69→101 lines (AND-compose at 7 sites); plus `enricher.py::enrich_features` 137→204 entry refresh (pre-existing growth, surfaced by T2's repo-structure disclosure run). Three deferred follow-ups: (a) candidate_pool wiring from active_research_strategies so White RC can vote (currently abstains; tracked); (b) reduce N+1 in orchestrator (5-6 SQLite connection opens per strategy); (c) replace 7-site AND-compose pattern with single-return refactor of `_evaluate_shadow_trading_gate` to eliminate maintainer-forgets-AND-compose hazard. Scope-fenced: NO modifications to methods/promotion_gate.py, methods/promotion_gate_helpers.py, analytics/instrumentation_filter.py, trainer.py, watch.py, any CLI module; `promote()` unchanged; `walkforward_outcome_state` column kept. PR #976.

- **fix(trainer): T3 — input-quality fix for promotion_gate call sites + Choice A regression-lock.** Fixes three pre-existing bugs in the methodology gate call paths per Phase 4 deep_report finding 5 (v5 spec). **Bug A** (`trainer.py:1039`): `promotion_gate(returns, n_trials=n_trials)` was missing `dates=` and `directions=` kwargs, causing MC permutation and White RC votes to abstain unconditionally (`passed=None`) instead of running. Both methods require real directions/dates per the Sprint-0 Wave-5b abstention semantics. **Bug B** (`trainer.py:975-976`): `rf_placeholder = 0.0001` was pre-subtracted from `pnl_pct/100` before the call. Once `dates` flows and `_adjust_returns_via_fred` runs, FRED rf would be subtracted again → double-count. Pre-subtraction dropped; raw `pnl_pct/100` now returned. **Bug C** (`kpis_compute.py:376`): same missing-kwargs pattern mirrored in the KPI strip endpoint. **SQL filter** (`trainer.py:967-972`): SELECT now fetches `actual_entry_time` alongside `pnl_pct` and adds `AND actual_entry_time IS NOT NULL` guard — prevents `None[:10]` TypeError and ensures the length invariant `len(returns)==len(dates)==len(directions)` holds at the boundary. `_resolve_returns_for_gate` refactored to return a 3-tuple `(returns, dates, directions)` where `returns` are raw (no rf pre-subtraction), `dates` are `date.fromisoformat(actual_entry_time[:10])`, and `directions` are `[+1]*N` (semantically honest encoding for the long-only system per `registry.py:202`). Empty result returns `([], [], [])`. **Choice A regression-lock** (spec §1.3.1): `test_trainer_promotion_gate_currently_cannot_promote_long_only` locks the documented degeneracy — under a long-only system `directions=[+1]*N`, MC permutation shuffling is identity, p-value is always 1.0, and the vote always fails. The maximum achievable vote tally via trainer.py / kpis_compute.py call sites is 3-of-5 (ceiling: cannot promote until T4 wires a real `candidate_pool`). **DA major fix 6** (sibling): `cmd_run_promotion_gate` in `cli/commands.py` is transitively fixed; 2 explicit regression tests verify the CLI path also passes dates+directions and produces reject/defer (not promote). 11 new tests in `tests/test_trainer_dates_directions_fix.py` and `tests/test_cmd_run_promotion_gate_post_fix.py`. **Pre-merge review fix:** both new tests were hitting FRED's live API (violating CLAUDE.md "Mock all external APIs in tests"); added `_mock_fred` autouse fixture to each file returning constant `0.0001` rf-rate, plus varied seeded returns (cycles `2.x`-`3.x` instead of identical `3.0`/`3.5`) so the rf-mock doesn't produce zero-variance signed returns that would crash before reaching the MC-perm degeneracy check. `config/known_violations.json` updated: `trainer.py` line count 1176→1192, `run_promotion_gate_for_version` 66→73 lines (backward-compat unpack branch added for legacy mock compatibility with `tests/training/test_promotion_gate_wiring.py`).

- **docs(operator-guide): NEW §0 System Overview (5-min new-operator onboarding) + refresh corpus + Ollama runbook.** Major refresh of `docs/operator-guide.md`. NEW §0 "System Overview" makes the guide self-contained for a new operator: §0.1 What ARCIS is + naming; §0.2 strategic goal (3-stage validation ladder per MASTER.md SD#43); §0.3 system anatomy diagram (operator-machine + cloud + sync); §0.4 trade lifecycle (pre-market → intraday → post-close → methodology gate → overnight); §0.5 data lifecycle (trade outcomes → instrumentation filter → ladder; LLM corpus → training → model versions); §0.6 key invariants (schema-as-SOT, risk governor, PIT, training data quality, test floor, worktree isolation, outcome_stats_filter_sql) with where-enforced and why-it-matters columns; §0.7 what the operator actually does (recurring tasks in frequency order); §0.8 where-to-look-first symptom→section table; §0.9 mental model in one paragraph. Plus the corpus + Ollama runbook refresh from earlier in this PR. Updates: §3 corpus generation (NUM_PARALLEL=2 default + watchdog prereq + OLLAMA_NUM_PARALLEL env match); §4 file paths (new logs/ollama-watchdog.log, logs/ollama-daemon.{err,out}, logs/corpus-stage1-001.{out,err}, scripts/ollama_watchdog.ps1, entries.jsonl.bak.<N> backup convention); §5 NEW troubleshooting "Ollama crashes / corpus producing template fallbacks" with VRAM math (9.12 GiB resident at NUM_PARALLEL=2; 1.7 GiB cushion vs 0.4 GiB at NUM_PARALLEL=4), audit script, and trim recovery; §5 NEW "Long-running process won't survive my SSH session closing" with Win32_Process.Create pattern; §6 NEW recovery "CHANGELOG.md conflict during sequential PR merges" (standard keep-both-in-order resolution); §7 refreshed corpus regen (NUM_PARALLEL=2, watchdog prereq, fallback audit); §7 NEW maintenance "Ollama watchdog" (start/stop/verify/circuit-breaker semantics + config overrides); §7 NEW "SSH-safe process launch" (Win32_Process.Create canonical pattern + recipes for corpus + watchdog); §8 glossary entries for Watchdog, Template-fallback entry, WMI launch / Session 0. No code changes.

- **schema(registry): document two new triggered_by sentinels for methodology gate wiring.** Updated `triggered_by` ColumnDef description in `strategy_promotion_events` to enumerate all four valid values: `'manual'`, `'auto_gate'`, `'gate_proposal'`, `'operator_confirm'` — with inline semantics for each. `'gate_proposal'` rows have `from_status==to_status` (informational, no transition); `'operator_confirm'` is a real transition via the confirm-promotion CLI. Description-string-only change; no schema migration, no new tables or columns. Sprint 2 T1 deliverable per `docs/audits/2026-05-05-methodology-gate-wiring/plan.md`. 1 new regression-lock test: `test_strategy_promotion_events_triggered_by_documents_all_sentinels`.

- **chore(ops): Ollama watchdog wrapper — auto-restart on death, capture stderr.** New `scripts/ollama_watchdog.ps1` + `scripts/start_ollama_watchdog.bat` close two diagnostic + reliability gaps surfaced by the 2026-05-06 corpus crash investigation. (1) Polls `http://127.0.0.1:11434/api/tags` every 30s; on failure, kills any orphan `ollama*` processes and restarts via `Start-Process -RedirectStandardError logs/ollama-daemon.err -RedirectStandardOutput logs/ollama-daemon.out`. The earlier headless-launch pattern (`Start-Process -WindowStyle Hidden`) discarded stderr entirely, so when the runner subprocess crashed (suspected CUDA OOM) we had no diagnostic; the watchdog now captures it. (2) Circuit breaker: 3 restarts in any rolling 10-minute window pauses the watchdog for 5 minutes — prevents tight crash loops from masking driver/hardware issues, with the last 10 lines of `ollama-daemon.err` logged at the breaker trip. The packet_writer fallback bug (silent template-substitution writes to entries.jsonl with `model_version="arcis:v1.0.0"` indistinguishable from real LLM entries — 5,012 historical pollutants found, ~16% of the corpus, 33 of them from the most recent crash) is tracked as a separate follow-up — needs either skip-write or distinct `model_version="template_fallback"` tagging. Companion entries.jsonl trim (drop short-response template-prefix matches) was a manual ops action, not part of this PR.

- **test(bracket_orders): assert OrderRequest take_profit + stop_loss kwargs are populated.** PR #942 Wave 6 investigation flagged that `test_market_bracket_order_params` only inspected `qty`/`symbol` on the submitted OrderRequest — a future regression dropping `stop_loss=` or `take_profit=` would silently pass the suite. Closes that gap by adding 5 new assertions in `TestBracketOrderKwargs` covering both market-entry and limit-entry bracket paths: `test_market_bracket_order_passes_take_profit_kwarg`, `test_market_bracket_order_passes_stop_loss_kwarg`, `test_bracket_order_request_has_both_kwargs_required`, `test_limit_bracket_order_passes_take_profit_kwarg`, `test_limit_bracket_order_passes_stop_loss_kwarg`. Each asserts the exact dict payload (`{"limit_price": <price>}` / `{"stop_price": <price>}`) on the request object. Sibling-search finding: `test_broker_interface.py::test_place_live_bracket_submits_alpaca_bracket_request` already has equivalent kwarg locks for the live-bracket path (lines 341–342); `test_bracket_safety.py` has GTC but no kwarg-presence lock; IB bracket tests use a different API surface (IB child orders, no `take_profit`/`stop_loss` fields). No production code changed. PR #946.

- **Wave 7 — reconcile_live_trades empty-fetch guard (mirror Wave 6 to live path).** Closes the same anti-pattern in `reconcile_live_trades()` that Wave 6 (PR #942) closed for `reconcile_paper_trades()`. If the live broker returns 0 positions while local has `>=_TRANSIENT_EMPTY_FETCH_THRESHOLD` (3) active live trades, all live trades would have been mass-marked stale. Currently moot (live trading is paper-only post-bootcamp) but hardened before any live-money flip (trading-safety class). Changes: (1) `live_fetch_ok` flag initialized `True`; set `False` when both broker-factory and `get_live_positions()` direct fallback both raise (now caught by inner try/except, was previously propagating); (2) transient-empty guard: if live broker returns 0 positions while local has `>=3` active live trades, `live_fetch_ok = False`; (3) stale *detection* suppressed when `live_fetch_ok = False` (mirror of Wave 6 paper approach — empty stale list rather than skip in closing loop); (4) IB-parity warning "Skipping stale closure for N live-broker trades — live fetch failed this cycle"; (5) `error` field populated in result dict on exception. Reuses existing `_TRANSIENT_EMPTY_FETCH_THRESHOLD = 3` module constant (no duplicate). 5 new tests in `tests/shadow_trading/test_reconcile_live_empty_fetch.py`: `test_live_fetch_exception_skips_stale_marking`, `test_live_empty_with_3plus_active_skips_stale_marking`, `test_live_empty_with_2_active_proceeds_normally` (boundary lock), `test_live_empty_with_exactly_3_active_skips_stale_marking` (N=3 boundary), `test_live_returns_real_positions_normal_path`. Sibling-search: no other reconcile-class function in `src/` has the try/except → empty-list anti-pattern on a positions fetch.

- **test(static): enforce outcome_stats_filter_sql on shadow_trades aggregations.** Adds `tests/test_outcome_stats_filter_coverage.py` — a pure static-analysis test (no production code changes) that walks all `*.py` files in `src/` and fails if any `.execute()` call queries `FROM shadow_trades` with an outcome-stat aggregation (`SUM`/`AVG` on `pnl_dollars` or `pnl_pct`, or `SUM(CASE WHEN pnl_dollars ...)`) without also calling `outcome_stats_filter_sql()`. Motivated by three incomplete post-merge sweeps of Wave 4 H5 (PR #933) and today's issue #482 sibling-search finding 4+ missing sites in `src/scheduler/reports.py`. Uses paren-depth tracking to isolate each `.execute()` call from its neighbours (preventing cross-query false positives), excludes active-only queries (`status='open'`/`_a_frag`) where `reconciled_stale` cannot appear, and provides an explicit allow-list for 11 legitimate exemptions (drawdown calc, equity curve, loss-limit guards, intraday P&L displays) with issue-cited rationale. Supports `# outcome-stats-filter: exempt-<reason>` inline comment for ad-hoc suppression. 5 tests: `test_all_shadow_trades_outcome_aggregations_use_filter` (main enforcement), `test_scanner_catches_regression_fixture` (anti-vacuity), `test_active_only_queries_not_flagged`, `test_exempt_marker_suppresses_detection`, `test_allowlist_entries_reference_real_from_lines` (stale-allowlist guard). Branch: `test/outcome-stats-filter-coverage-enforcement`. Closes #13. Sibling-search per `feedback_review_sibling_search` found additional hardcoded `WHERE status = 'closed'` sites in `src/scheduler/watch.py` (lines 556, 1550) — logged as follow-up for #482.

- **fix(bracket_monitor): support OCO order_class — recognize parent-as-limit topology.** bracket_monitor was false-alerting `alerted_target_leg` every ~5 minutes for 4 live paper positions (BK, C, COP, TGT) since 2026-05-05T13:10 ET. Root cause: `_classify_legs()` only understood the BRACKET topology (parent=entry-order, both stop+limit in `parent.legs`). Alpaca had transitioned those positions to OCO protection orders where the parent IS the take-profit LIMIT order and `parent.legs` contains only the STOP. New `_is_oco_topology()` helper detects OCO via explicit `order_class='oco'` field (plus structural fallback: parent has `limit_price`, no LIMIT-type child in legs). `_classify_legs()` now branches on topology: OCO reads `target_status` from the parent's own status and `stop_status` from the single leg; BRACKET path unchanged. The verdict (`bracket_intact=1`) now fires correctly for both shapes when the operational invariant holds (working stop + working take-profit). 4 new tests: `test_oco_with_held_stop_classified_healthy`, `test_oco_with_canceled_stop_classified_broken`, `test_bracket_with_both_legs_active_classified_healthy` (regression-lock), `test_classifier_returns_unified_shape_for_both_classes`. Sibling-search findings: `executor.py:1862-1863` reads `order_status["legs"]` for IB fill detection (not topology classification, no same-bug); cloud_routes have no `legs`/`order_class` reads. PR #944 closes Telegram spam incident.

- **hotfix(reconcile): Wave 5 orphan-guard row-factory portability (`_row[0]` -> `_row['actual_exit_time']`).** `src/shadow_trading/reconcile.py:664` used positional index `_row[0]` to access `actual_exit_time` from the stale-rows query result. This works for `sqlite3.Row` and tuple rows but raises `KeyError: 0` on dict-row-factory connections. Fixed to `_row['actual_exit_time']` (named-key access, works for all Mapping-like row factories). Also updated `test_exit_reason_writer_coverage.py::TestReconcileRoutesThroughCoerce` fixture `fetchall_side_effect` to account for the extra Wave 5 orphan-guard fetchall call (call-count offset fix for `test_reconcile_overshoot_detected_routes_through_coerce` and `test_reconcile_qty_mismatch_routes_through_coerce`). 3 new regression-lock tests in `tests/shadow_trading/test_wave5_guard_row_factory.py` (sqlite3.Row factory, dict row factory, invalid ISO gracefully). Sibling-search: one `_row[0]` occurrence in `reconcile.py` (the fixed line), all other `row[0]` in `src/` are `fetchone()` patterns (not stale-row iteration).

- **Wave 6 — Alpaca empty-fetch guard (root-cause closure for 2026-05-04 mass-misclassification).** On 2026-05-04, a transient Alpaca API response returned 0 positions, causing `reconcile_paper_trades()` to mark 13 real broker positions (AVGO, BK, BMY, C, CAT, COP, EMR, GS, KO, PEP, SPG, TGT, TXN) as `reconciled_stale` in a single cycle. Root cause: no guard for the empty-broker-response case, unlike the IB-side which had `ib_fetch_ok` + transient-empty guard since the 2026-04-13 outage. Wave 5 (PR #937) added an anti-re-backfill guard that contained the cycle but did not fix the root cause. Wave 6 closes it: (1) `alpaca_fetch_ok` flag initialized `True`; set `False` on exception (exception path no longer early-returns — function continues and safely skips stale closure); (2) `alpaca_trade_count` + transient guard: if Alpaca returns 0 positions while local has `>=_TRANSIENT_EMPTY_FETCH_THRESHOLD` (3) active alpaca trades, `alpaca_fetch_ok` is set `False` ("treat as unreachable for this cycle"); (3) stale loop respects `alpaca_fetch_ok` — `if not alpaca_fetch_ok: continue` before the `ticker not in alpaca_tickers` check; (4) `_TRANSIENT_EMPTY_FETCH_THRESHOLD = 3` module-level constant for future tuning; (5) `_alpaca_fetch_error` plumbing so the return dict's `error` field is populated on exception. 4 new tests in `tests/shadow_trading/test_reconcile_paper_empty_fetch.py`: exception-skips-stale, empty-3plus-skips-stale, empty-2-proceeds-normally (threshold lock), happy-path-normal. PR #942. Closes #32.

- **Wave 4 H1 — Auto-clear stale own-host sync_state lock.** New helper `release_stale_in_flight_for_host()` in `src/sync/render_sync.py` runs at `RenderSyncThread.run()` startup (PID-lock invariant guarantees safety, no time cutoff). Closes the cycle-skipping pathology after watch-loop crash/restart — operator no longer needs manual SQL fix to release a stuck `sync_state` row. 3 new tests in `tests/test_render_sync.py`. PR #930. Closes #8.

- **Wave 4 H2 — scan_metrics.id UNIQUE constraint fix.** Dropped manual `id` from the INSERT in `src/scheduler/watch.py::_record_scan_metrics` — SQLite ROWID auto-generates the id since `scan_metrics.id` is INTEGER PRIMARY KEY in the registry. Closes the `UNIQUE constraint failed: scan_metrics.id` crash on watch-loop restart caused by `_scan_number` resetting to 0 and colliding with existing rows. 3 new tests in `tests/scheduler/test_scan_metrics_writer.py`. PR #931. Closes #11.

- **Wave 4 H3 — live_prices sync_mode latest_only → incremental + watermark migration CLI.** Single-line flip in `src/schema/registry.py:2491` (`sync_mode='latest_only'` → `'incremental'`) plus new `reset-live-prices-watermark` CLI command in `src/cli/commands.py` (registered through `src/main.py`) for clean transition (caps first-cycle backlog to ~24h via watermark reset). After this change, all open-trade ticker rows propagate per sync cycle (previously only the global-max-`as_of` row, dropping 14 of 15 tickers). 3 new tests + assertion flip in `tests/test_live_prices.py`. **Operator post-merge action**: run `python -m src.main reset-live-prices-watermark` once before next watch-loop restart. PR #932. Closes #12.

- **Wave 4 H4 — coerce_exit_reason bypass fix at 3 sites + `retry_exit` vocabulary add.** Wrapped `executor.py:120` (`quarantine_trade`), `:1489` (skip_reason from `_sync_exit_qty`), `:1516` (retry handler success path) with `coerce_exit_reason()`. Added `'retry_exit'` to `CONTROLLED_VOCAB` (real fill, real P&L — NOT added to `EXCLUDED_FROM_OUTCOME_STATS`). `quarantine_trade()` signature gained optional `ticker: str = ''` kwarg with sibling-search audit of all callers (zero in `src/` beyond the definition itself — kwarg is forward-compatible). 10 new tests across `tests/shadow_trading/test_exit_reason_taxonomy.py`, `test_exit_reason_writes_route_through_coerce.py`, `test_executor_retry_exit_path.py`. PR #929. Closes #17.

- **Wave 4 H5 — outcome_stats_filter_sql() expanded across sibling sites in 12 src/ files.** Closes the reconciled_stale-pollution sibling class systematically: `hshs_live.py` (5 sites), bootcamp counters (5 — `auditor.py`/`build_score.py`/`gate_evaluator.py`/`api/routes/health.py:68+:189`), `telegram_commands.py` (3), `scheduler/reports.py` (5), `cost_model/calibration.py` (1), `council/agent_data.py` (4), `email/digest_builder.py` (4), plus reviewer-found follow-ups in `evaluation/change_detector.py` (1, CUSUM drift detection) and `evaluation/model_monitor.py` (1, JOIN context — uses `outcome_stats_filter_sql().replace('exit_reason', 'st.exit_reason')`). Reclassified do-NOT-filter sites per M11 design decision: `agent_data.py:224` (recent-losses display already filters via `pnl_pct < 0`) and `digest_builder.py:219`/`:290` (open-trade counters where reconciled_stale rows are legitimate during their lifecycle). New shared helper `tests/_helpers/seed_closed_trades.py` seeds N normal + M reconciled_stale + K reconciled rows for consistent filter tests. ~76 new tests across 11 test files (10 site test files + 2 reviewer-followup tests in change_detector + model_monitor). Reviewer flagged Task #13 (static-analysis CI guardrail) urgency — this was the third round of incomplete sweeps in this bug class (#919 → #920 → #933). PR #933. Closes #14.

- **Wave 4 H7 — post-bootcamp graduation override (sticky).** New `live_trading.post_bootcamp` config key (default `false`, documented in `config/settings.example.yaml`) decouples the auditor's `bootcamp_mode` from the runtime `closed_count`. Once the operator declares Stage 1 baseline signed and sets `post_bootcamp: true` in `settings.local.yaml`, `bootcamp_mode` never auto-flips back — even when filtering changes the closed-trade count (e.g., when H5 drops the bootcamp counter from 50 to 6 honest strategy outcomes by excluding reconciled_stale rows). Without this override, H5's data-integrity fix would silently regress ordinary CRITICAL audit flags into "alert" downgrades, the exact safety-net behavior the operator graduated past when the Stage 1 baseline was signed at `d651160`. Categories already in `_NEVER_DOWNGRADE` (`risk_governor_breach`, `emergency_halt_bypass`) continue to halt regardless of this flag. 2 new tests in `tests/test_auditor.py::TestEscalation`. **Operator post-merge action**: add `live_trading.post_bootcamp: true` to `settings.local.yaml` (one-time edit; sticky thereafter). PR #934.

- **T-DOCS sweep — Sprint 1.A documentation refresh.** MASTER.md sprint-queue marked Wave 2+3 ✅ COMPLETE (#911/#918/#921/#922/#923 merged); current-state metrics refreshed (corpus 18,185/67,681 ≈26.9%, watch loop paused, model arcis:v1.0.0). dashboard-data-map.md updated with #918/#919/#920 changes (live_prices as_of sync, outcome_stats_filter_sql helper). dashboard-gap-list-2026-04-29.md marked 5 fixed gaps as ✅ closed with PR refs and 5 in-flight gaps mapped to Wave 4 H1–H5. methodology-toolkit.md gained a `subtract_trading_days` reference (helper + calendar source + use cases + why). CLAUDE.md Analytics & Methodology section now flags `subtract_trading_days` as canonical for fetch anchors / lookback windows (cites #888 / #106 incident).

- **feat(#106 follow-up): wire subtract_trading_days into src/evaluation/backtester.py fetch anchor** — replaces 365-calendar-day buffer with 200-trading-day pre-reg-aligned anchor; B.3 from PR #911 plan. Mirrors #922 (corpus generator wiring at the same call-site shape).

- **feat(#106 follow-up): wire subtract_trading_days into scripts/generate_llm_corpus.py::_compute_features_for_window fetch anchor (replaces 365-calendar-day buffer with 200-trading-day pre-reg-aligned anchor; B.2 from PR #911 plan).**

- **fix(#919 follow-up): apply reconciled_stale exclusion to ALL remaining shadow_trades outcome aggregations** — #919 patched 4 sites; review caught 2 more in analytics.py (cto_report, strategy_detail); operator's second-round review caught 3 more in trades.py; comprehensive sibling-sweep found 2 more in cloud trades.py + 1 in cloud training.py + 2 in local routes/. **9 routes patched total in this PR.** Cloud routes: (1) `analytics.py::cto_report` — headline_kpis + 6 sub-aggregations (by_score_band, by_sector, by_regime, execution_analysis, fund_metrics monthly_batting_avg, by_broker); (2) `analytics.py::strategy_detail`; (3) `trades.py::shadow_open` (line 166 SUM, hygiene only — reconciled_stale rows have pnl=0 so SUM unaffected, but filter prevents inclusion in any future trade-count alongside); (4) `trades.py::shadow_metrics` (305) — desk-filtered metrics tile; (5) `trades.py::live_summary` (442) — live-trading summary; (6) `trades.py::shadow_account` (477) — account-level desk-filtered; (7) `trades.py::projections_live` (598) — projections route win_rate / sharpe / drawdown / profit_factor; (8) `training.py::training_status` — per-model-version metrics (uses `st.exit_reason` alias-prefix via .replace on the helper output to handle the JOIN context). Local routes (parity with cloud per #919's pattern): (9) `routes/live.py::live_summary` and (10) `routes/projections.py::projections_live`. For `cto_report` specifically: builds `closed_recent_for_stats = [t for t in closed_recent if not t.get('exit_reason') or t['exit_reason'] not in EXCLUDED_FROM_OUTCOME_STATS]` and routes ALL outcome aggregations through it — the by_exit_reason histogram (line 457) intentionally STAYS on the unfiltered `closed_recent` so reconciled_stale appears as informational signal in the histogram tile. All other sites use SQL-level `outcome_stats_filter_sql()` appended to existing WHERE clauses (no histogram concern). Sibling-sweep also confirmed `attribution_stats` reads from a different table (`attribution_trades`) — not affected. No new tests: the primitives (constant + SQL fragment + in-memory filter) are already locked by 6 tests in `tests/shadow_trading/test_exit_reason_taxonomy.py` from #919; new sites are 1-line applications. Filed as Wave-2-class follow-up (task #13): a static-analysis test (`test_no_unfiltered_win_rate_aggregation_on_shadow_trades`) that parses cloud_routes/* + routes/* and asserts every shadow_trades aggregation goes through `outcome_stats_filter_sql()` — closes the recurring "still leaking across sites" class permanently. After Render redeploy: every dashboard win_rate / profit_factor / expectancy / drawdown figure reflects the same outcome-eligible trade set.

- **fix(dashboard): exclude `reconciled_stale` exit_reason from win-rate and outcome stats** — Operator dashboard showed 28.6% win rate when post-audit history should be 100%. Root cause: local SQLite shadow_trades contained 16 rows with `exit_reason='reconciled_stale'` (set by `src/shadow_trading/reconcile.py:349` when a tracked position no longer exists on the broker side). 15 were a single bulk-close at `2026-05-03T21:44:16` after a watch-loop crash with `pnl_dollars=0.0`; one (ETN) was an earlier reconciliation where `_estimate_exit_pnl` happened to return non-zero. All 16 are bookkeeping artifacts, not real trade outcomes. Including them in win-rate aggregation produced 6 real wins / (6+15 zero-pnl) = 28.6%. Excluding `reconciled_stale` → 5 real wins / 5 closed = 100% ✓ matches operator expectation. New `EXCLUDED_FROM_OUTCOME_STATS = frozenset({"reconciled_stale"})` constant in `src/shadow_trading/exit_reason.py`, plus `outcome_stats_filter_sql()` helper that returns `AND (exit_reason IS NULL OR exit_reason NOT IN ('reconciled_stale'))` for use in win-rate / profit-factor / avg-winner queries. Applied at four sites: `src/api/cloud_routes/analytics.py::health_hshs`, `health_score`, `src/api/cloud_routes/kpis_compute.py::_fetch_closed_trades_from_postgres` (cloud KPI tile), and `src/journal/store.py::get_closed_shadow_trades` (local KPI tile — keeps cloud + local consistent). The recent-outcomes breakdown at `analytics.py:415-431` intentionally NOT filtered (surfaces exit_reason histogram for informational signal). 6 new regression tests in `tests/shadow_trading/test_exit_reason_taxonomy.py` lock the constant, SQL fragment shape, and end-to-end filter behavior against in-memory SQLite (including the ETN non-zero-pnl case). After merge: cloud route changes go live on Render auto-deploy; dashboard tile updates on next sync cycle. Follow-ups deferred: (a) auto-clear stale RenderSyncThread sync_state lock on watch-loop startup so a crash doesn't permanently block sync (caused tonight's manual SQL fix), (b) consider whether `timeout`/`mr_timeout` should also be excluded per methodology call.

- **fix(#910 follow-up): live_prices.sync_time_column was None, blocking latest_only sync** — `src/schema/registry.py` `live_prices` TableDef shipped with `sync_mode="latest_only"` but `sync_time_column=None`, causing `RenderSyncThread` to build SQL with literal `MAX(None)` → `sqlite3.OperationalError: live_prices: no such column: None` every sync cycle. Effect: even when `_refresh_live_prices()` writes rows to local SQLite, the latest_only sync never propagates them to Postgres → `/api/shadow/open` returns `current_price_est=None`. Fix: `sync_time_column="as_of"` (matches the existing alpaca timestamp column already in the schema). Test additions: `tests/test_live_prices.py::test_live_prices_sync_config` extended with explicit `sync_time_column == "as_of"` and `sync_conflict_col == "ticker"` assertions. Existing `tests/test_schema.py::test_every_sync_table_has_time_column` was already structurally correct and would have caught this in CI — verified locally that reverting the fix produces the expected `AssertionError: live_prices has sync_mode=latest_only but no sync_time_column`. The #910 CI evidently did not run `test_schema.py`; reviewer ran a partial subset (`tests/test_live_prices.py + tests/test_watch_resilience.py`). Discovered while diagnosing why the live_prices Postgres tile remained empty after a watch-loop restart and `render_migrate.py` had successfully created the table.

- **fix(#72 follow-up #85): split RenderSyncThread.run() into helpers (≤60 lines per guardrail)** — `run()` was 63 lines (62 per AST measure), violating the 60-line guardrail. Extracted four private helpers: `_log_cycle_outcome(summary)` (logging block), `_dispatch_pulled_commands(summary)` (commands callback), `_handle_cycle_exception(exc)` (error path + telegram notification), and `_run_one_cycle()` (lock acquisition + run_sync_cycle invocation + counter increment). Outer `run()` is now 8 lines. All log message strings, lock semantics, reconcile-gate predicate, and exception-swallow pattern preserved exactly. 10 new unit tests in `TestRenderSyncThreadHelpers` cover `_log_cycle_outcome` quiet-cycle / heartbeat / error conditions, `_dispatch_pulled_commands` callback semantics, and `_handle_cycle_exception` telegram-swallow behavior. Removed stale `run` entry from `config/known_violations.json`.

- **fix(#58/#815): clean up docstring drift for src/api/routes/system.py** — Issue #815 reported that 4+ module docstrings referenced `api.routes.system` but the file did not exist, causing `AttributeError: module 'src.api.routes' has no attribute 'system'` in 3 simulation-engine tests. Investigation confirmed the file now exists (723 lines, grandfathered in `known_violations.json`) and all 3 symptom tests pass on current `main`. The remaining docstring drift: (1) `src/api/routes/system.py` declared `Tests: none` despite being imported and exercised by `tests/test_local_api_routes.py`, `tests/test_tier_1_5_hygiene.py`, and `tests/evaluation/test_sharpe_canonical_routing.py` — updated to list all three; (2) `src/evaluation/corpus.py` was missing the required `Config keys:` header, causing a new violation in `tests/test_repo_structure.py::test_all_modules_have_standard_docstring` — `Config keys: none` added. All 4+ `Called by:` references in `canonical_sharpe.py`, `config/__init__.py`, `cto_report.py`, `system_validator.py` are valid and unchanged. Sibling search across `src/api/routes/` found no other broken module references.

- **feat(#106): add subtract_trading_days(anchor, n) NYSE-calendar-aware helper** — `src/scheduler/holidays.py` gains the public `subtract_trading_days(anchor: date, n: int) -> date` function. Uses the existing `_NYSE` calendar instance (pandas_market_calendars) with a `ceil(n * 1.6) + 10` calendar-day look-back window to enumerate valid trading days and index `-(n+1)` from the end, honoring weekends, full holidays, and half-days (which still count as trading days). If anchor is a non-trading day (weekend/holiday), it rounds back to the prior trading day then steps back N. Raises `ValueError` for n < 0. Returns `date` (not `pd.Timestamp`). 7 new tests in `tests/scheduler/test_holidays.py` lock the behavior: one-step weekday, holiday crossing (MLK Day), weekend crossing, 200-day anchor (hardcoded 2025-07-16 locks calendar arithmetic), n=0 semantics, ValueError on negative, and Saturday anchor round-back. B.2 will wire this into corpus + backtester fetch anchors.

- **fix(dashboard): scan_metrics avg_conviction/duration_seconds + live_prices table for accurate shadow/open P&L** — Two related dashboard tile fixes. **Bug 1 (scan_metrics writer):** `src/scheduler/watch.py::_record_scan_metrics` was inserting hardcoded `0.0, 0.0` for `avg_conviction` and `duration_seconds` columns at line 934 — the function signature accepted `conviction_parsed`/`conviction_total` but only used them in the log line, never threading them into the table row. Fix: added `avg_conviction: float = 0.0, duration_seconds: float = 0.0` to the signature, threaded through all 3 callsites (aborted scan, empty scan, success path), measured `duration_seconds = time.time() - scan_started_at` from a marker captured at scan-cycle start. `avg_conviction` uses `result.conviction_parsed/result.conviction_total` as a parse-rate proxy; TODO note left to wire real per-packet conviction list when `universe_scanner.ScanResult` exposes it. **Bug 2 (live_prices):** `/api/shadow/open` was using `setup_signals.theoretical_entry` as a "current price" proxy — but that's the SCAN-COMPUTED ideal entry, not a market quote, and goes stale when the watch loop is stopped. New `live_prices` table (PK=ticker, columns: price, bid, ask, as_of, source) with `sync_to_postgres=True, sync_mode=latest_only, sync_reconcile=True`. New `_refresh_live_prices()` method on `WatchLoop` queries open `shadow_trades` for the active ticker set and UPSERTs current Alpaca quotes (bid-ask midpoint via `StockLatestQuoteRequest`) once per scan cycle. New `fetch_latest_quotes(tickers)` helper in `src/shadow_trading/alpaca_adapter.py` wraps the Alpaca data API call. `/api/shadow/open` route SQL changed from `setup_signals.theoretical_entry` proxy to `live_prices.price` direct read; new `current_price_as_of` field returned for frontend staleness detection. Schema table count: 69 → 70. **Operator action sequence after merge:** `python scripts/render_migrate.py` with `DATABASE_URL` to create `live_prices` on cloud Postgres, then trigger Render redeploy of halcyon-api, then restart watch loop with `OLLAMA_NUM_PARALLEL=5; python -m src.main startup` so the new writer runs alongside the corpus job. New regression tests in `tests/test_live_prices.py` (table + writer + route) and `tests/test_watch_resilience.py` (scan_metrics writer instrumentation). PM-rescued from a stalled background agent (aa2ab37ec6dfedf0e) that completed all substantive work but exited at turn-limit before committing/pushing.
- **hotfix: /api/system/index HTTP 500 on Render — broaden exception fallback so non-sqlite3.Error exceptions degrade gracefully** — Two exception-handling gaps caused the endpoint to propagate HTTP 500 instead of falling back to the cloud or offline payload: (1) `_open_sqlite()` was guarded by `except sqlite3.Error` + `except TypeError`, missing `OSError`/`FileNotFoundError`/`PermissionError` raised on Render's Linux runtime when `DB_PATH` is a Windows path; (2) `_build_live_payload()` had no try/except, so a freshly-created empty SQLite file (where `operator_view_state` doesn't exist) propagated `sqlite3.OperationalError: no such table` as 500. Both gaps consolidated to `except Exception` with type-name + message logged at WARNING, consistent with the docstring contract: "raised exceptions become {'status': 'unavailable'} — one bad query cannot cascade-break the index." Sibling `mark_reviewed` narrow catches also broadened (OSError on path open should give 503, not crash). 3 new regression tests in `tests/api/test_system_index.py`. Operator must trigger Render redeploy of halcyon-api after merge.
- **hotfix: add `requests` to cloud deps + soft-import in risk_free_rate (production /api/kpis 500 fix)** — `requests>=2.31,<3.0` added to `requirements-cloud.txt`; same comment style as the prior `jsonschema` and `numpy` retroactive-add entries explains the transitive dependency path. `src/data_ingestion/risk_free_rate.py` changed from a hard module-level `import requests` to a soft import (`try/except ImportError → requests=None`) with a guard in `_fetch_dtb3_observations` that raises `ImportError` when `requests is None`. This ensures (a) the module loads even if `requests` is stripped from the cloud environment, and (b) the existing broad `except Exception` in `kpis_compute._compute_per_trade_rf` catches the `ImportError` and falls back to the placeholder rf rate rather than crashing the route handler. Root cause: Render production log showed `ModuleNotFoundError: No module named 'requests'` at `risk_free_rate.py:32` on every `/api/kpis` call — the module-level import fired when `_compute_per_trade_rf` ran `from src.data_ingestion.risk_free_rate import get_rf_rate`, before any try/except branch could fire. **Operator must trigger a Render redeploy of halcyon-api after merge for the fix to take effect.** 3 new regression tests in `tests/api/test_kpis.py::TestRequestsLazyImportFallback` lock the soft-import behavior, the fallback-on-None path, and the ImportError raise from `_fetch_dtb3_observations`.

- **hotfix target: v0.32.1 — Telegram telemetry, Finnhub plan gating, and Render dashboard fallback recovery** (#903) — Fixes the Telegram schedule-health placeholders by wiring live GPU / scan-delay / VRAM-handoff metrics, and corrects EOD win/loss reporting so `rejected` trades no longer count as realized losses. Adds a plan-aware Finnhub toggle via `FINNHUB_PLAN` / `data_enrichment.finnhub_plan` (`auto`, `free`, `fundamental-1`), enabling runtime premium `news-sentiment` use while safely suppressing unsupported `price-target` calls. Restores Render `/api/system/index` in cloud mode with Postgres-backed fallbacks, adds explicit dashboard empty/error states for System Index and Scan Metrics, and bumps the service-worker cache key to move clients off stale bundles. Regression coverage added for the cloud fallback, schedule health computation, Finnhub sentiment gating, and scan-service hermeticity.
- **corpus generator: periodic progress + completion summary** (Stage 1 launch QoL) — `src/evaluation/corpus_generator.py::_stream_entries` now emits a single-line progress heartbeat every 100 entries OR every 10 minutes (whichever fires first), plus a startup banner and a final completion summary. The progress line includes: entries-written / total, percent-complete, recent rate (sec/entry), ETA in human + ISO form, parse-failure count + rate, and top-3 coverage warnings. Designed for the ~12.5-day Stage 1 corpus run — the operator can `tail -f` the log and see live progress without grepping JSONL line counts. Both the sequential (`num_parallel=1`) and parallel branches emit identically. The closure-captured counter reads are race-free because `_stream_entries` increments them on the main thread only; worker threads return entries and the main thread serializes the writes (#108 Lever 1 design). Cadence constants `_PROGRESS_EVERY_N=100` / `_PROGRESS_EVERY_SEC=600` are module-private — tunable in code if needed but defaults are good for the Stage 1 run length. 36/36 tests pass post-change.
- **#108 Lever 1: parallelize Ollama calls in corpus generator** — Cuts Stage 1 corpus generation from ~30 days (sequential) to ~12.5 days (N=4) with **zero pre-reg amendment** (model unchanged, prompt unchanged, prompt_sha256 unchanged, parser unchanged — only dispatch order differs). `scripts/generate_llm_corpus.py` gains `--num-parallel N` CLI flag (default 4). `src/evaluation/corpus_generator.py::_stream_entries` replaces sequential for-loop with `concurrent.futures.ThreadPoolExecutor`; JSONL writes serialized via `threading.Lock` so resume order is preserved (writes occur in submission order). `src/llm/client.py::generate` gains `batch_mode: bool = False` kwarg that gates the 2s post-call cooldown — corpus runner sets it True; live-scan path leaves it False to preserve #388 Ollama-overload protection. Threaded through `enhance_packet_with_llm` in `packet_writer.py`. Watch-loop coexistence: the `--num-parallel` flag enables the operator to run the watch loop alongside the walkforward; recommendation in CLI `--help` is to set `OLLAMA_NUM_PARALLEL=5` so live scans get a dedicated slot (corpus N=4 + scan N=1 fits in 12 GB VRAM). Per-future error handling: failures log at WARNING with type-name + message and continue (retry on next `--resume`). 6 new regression tests in `tests/evaluation/test_corpus_generator.py::TestParallelEquivalence` + `tests/llm/test_packet_writer.py::TestBatchMode` lock parallel-vs-sequential equivalence + concurrent-coexistence + batch_mode sleep gating. PM-rescued from a stalled background agent (a02396161a95a3aef) that completed the substantive code + tests but terminated mid-final-step due to an upstream auth error before committing.
- **dashboard cloud fallbacks** (`ccc78fd`, direct-to-main) — Disables same-origin WebSocket attempts in cloud mode (was hammering `wss://halcyonlab.app/ws/live` with failures). Hardens `KPIStrip.jsx` so partial / bad `/api/kpis` payloads no longer crash the dashboard — shows explicit "KPI data unavailable" instead of blank loader. `/api/preflight/latest` returns empty-state instead of 500 when `preflight_runs` is missing in Render Postgres (the table from #87 hadn't been migrated yet). Sets cloud CORS defaults for `halcyonlab.app`. Applies the real cloud auth override to `kpis` and `preflight` routes. Direct-to-main commit by Codex, no PR — emergency dashboard recovery.
- **#87 cloud Postgres equivalents for broker_exceptions / preflight / kpis** (#84 follow-up — closes Tier 1 dashboard staleness for these three routes) — `src/api/cloud_routes/broker_exceptions.py`, `preflight.py`, and `kpis_compute.py` now return correct data when running against Render Postgres (previously some queries assumed SQLite-only behavior or read tables that didn't replicate). New table `preflight_runs` added to `src/schema/registry.py` (`sync_mode=latest_only`, `sync_to_postgres=True`) so the cloud route reads the most-recent pre-flight run instead of returning `overall_status='unknown'` indefinitely. 6 new regression tests across the three test files exercise the routes against an in-memory Postgres-shape connection. Total schema table count: 68 → 69. PM-rescued from a stalled background agent (a9ee1efdf9f20877d) that completed the substantive code + tests but exited before committing while investigating whether `render_migrate.py` should be run inside the worktree (correct call: operator runs it with their actual `DATABASE_URL`). 133 tests pass across the three modified test files.
- **TradePacket: add `llm_conviction_parse_failed` + `parser_strategy_succeeded` fields** (Sprint 1.C Phase 4.5 hotfix) — Both `enhance_packet_with_llm` (in `src/llm/packet_writer.py`) and downstream callers were setting these as attributes on packet, but the Pydantic fields had never been declared. `TradePacket.model_config = ConfigDict(validate_assignment=True)` rejects undeclared assignment with `ValidationError(no_such_attribute)`, crashing gate #9 first-fold smoke at line 723 (`packet.llm_conviction_parse_failed = False`) the moment a real LLM call ran. Bug originally introduced by #850 (parse-failed flag) and extended by #98 (parser strategy) — both PRs' unit tests used `SimpleNamespace` mocks that bypass `validate_assignment` entirely, so the schema gap stayed hidden until the smoke ran end-to-end against a real `TradePacket` instance. 3 new regression tests in `tests/test_llm_pipeline_hardening.py::TestTradePacketLLMFields` lock both fields against future drift. No PIT or methodology change.
- **slice_to_date: empty-SPY guard with clear error message** (Sprint 1.C Phase 4.5 hotfix) — When `fetch_spy_benchmark` hits a yfinance timeout it returns an empty DataFrame whose index is `RangeIndex` (Int64), not `DatetimeIndex`. The naive `spy_full.index <= cutoff` comparison then raised `TypeError: '<=' not supported between instances of 'numpy.ndarray' and 'Timestamp'` — obscuring the real cause (failed network fetch). `src/training/historical_data.py::slice_to_date` now detects the empty case up front and raises `ValueError` with the as_of date and a yfinance-timeout hint, so callers get an actionable error and can retry the fetch. Reproduces gate #9 first-fold smoke crash on 2026-04-29 when 18 tickers + SPY timed out simultaneously. 2 new regression tests in `tests/test_backfill.py::TestSliceToDate` (clear error + message-content assertions). No PIT semantic change.
- **#104 follow-up: bump fetch-buffer 280→365 calendar days** (Sprint 1.C Phase 4.5 hotfix) — The 280-day buffer landed in PR #888 was at the edge: 280 calendar days ≈ 200 weekdays, but US market holidays (~9 in any rolling 9-month span) drop the realised trading-day count to ~192 — below `slice_to_date`'s 200-row gate. Smoke gate #8 reproduced this at `as_of=2024-01-02`: 201 business days but only ~193 trading days after holidays, so every ticker was filtered out and `total_decision_points` stayed at 0. Bumped to 365 calendar days (~250 trading days post-holidays) for both `scripts/generate_llm_corpus.py::_compute_features_for_window` and `src/evaluation/backtester.py::backtest_model`. PIT cleanliness unchanged — `slice_to_date`'s `df.index <= cutoff` is still the binding contract.
- **#99 enrichment-pit-warnings collection channel** (Sprint 1.C Phase 4 follow-up) — wires the `enrichment_pit_warnings` field on `CorpusEntry` and `coverage_limit_hits` on `CorpusManifest` to a real signal source. Each fetcher in `src/data_enrichment/` (`fetch_recent_news`, `fetch_historical_news`, `fetch_macro_context`, `fetch_fundamental_snapshot`, `fetch_insider_activity`, `compute_earnings_signals`) now accepts an optional `warnings: list[str] | None = None` kwarg and appends prefixed strings (`<source>_<category>:<scope>:<as_of>`) when it hits a coverage gap, missing API key, invalid as_of, fetch failure, or no-data fallback. `enrich_features` gains `warnings_out: list[str] | None = None` that forwards to every fetcher. `corpus_generator._generate_one_entry` collects per-decision warnings into the `CorpusEntry`; `_build_and_write_manifest` aggregates by prefix into `coverage_limit_hits` (e.g. `{"news_coverage_gap": 12, "macro_no_api_key": 3}`). 33 new tests in `tests/data_enrichment/test_warnings.py`. Backward-compat: callers that don't pass the new kwargs see no behavior change.
- **#98 parser_strategy_succeeded instrumentation** (Sprint 1.C Phase 4 follow-up) — `src/llm/packet_writer.py` adds `_detect_conviction_strategy(response)` mirroring the 8-strategy cascade in `_parse_llm_response` (which keeps its 5-tuple return shape stable for dozens of existing callers). `enhance_packet_with_llm` sets `packet.parser_strategy_succeeded` to the strategy identifier (or `None` if all 8 miss). 8 stable identifiers form the dataset contract: `metadata_block`, `plain_conviction`, `conviction_tag`, `conviction_score`, `markdown_bold`, `catchall`, `confidence_label`, `bare_score`. `src/evaluation/corpus_generator.py::_packet_to_entry` reads via `_strategy_label(packet)` (defensive `isinstance` check). 18 new tests in `tests/llm/test_packet_writer.py`. Closes the Phase 4 follow-up tracker. PM-rescued from a stalled background agent that completed all substantive work but exited without committing/pushing.
- **#104 corpus dry-run + backtester fetch-period anchor (Sprint 1.C Phase 4.5 — Stage 1 blocker)** — Three fetch-period bugs that together rendered the corpus generator + walkforward backtester unable to produce data for any fold older than the most recent. Surfaced by operator running §B2 admissibility gates #8 + #9 (`stage1-fold1` returned `total_decision_points=0`).
  - **Bug A (`scripts/generate_llm_corpus.py:233`)** — `if not args.dry_run and decision_points:` skipped feature computation under `--dry-run`, but `corpus_generator._generate_one_entry` always calls `_build_feature_prompt(feat, ticker)` for prompt_sha256. Without features every dry-run entry was silently skipped → 0 entries written. Fix: dropped the `not args.dry_run` guard.
  - **Bug B (`scripts/generate_llm_corpus.py:193-194`)** — `fetch_ohlcv(period="3y")` anchors to today (yfinance semantics), so for fold 1 (test_start=2023-09-01) the slice returned ~88 trading days — below `slice_to_date`'s 200-row gate, every ticker filtered out. Fix: anchored to `(earliest_as_of - 280 calendar days)` through `latest_as_of`.
  - **Bug C (`src/evaluation/backtester.py:119-126`)** — `fetch_period_days = window_days + 60` with `period=f"{N}d"` returned data from `today - N days` through today. For an old fold (test span 2023-09-01..2024-01-01, today=2026-04-29) the fetched window starts 667 days AFTER the test span; every `slice_to_date` returned 0 rows; folds 1-7 silently produced 0 trades (only fold 8 overlapped the recent fetch). Fix: anchored to `(test_start - 280 days)` through `test_end`.
  - **Architectural choice — Path 1 (date-bounded fetch_ohlcv)**: `src/data_ingestion/market_data.py::fetch_ohlcv` + `fetch_spy_benchmark` gain `start=` / `end=` keyword args. When provided, yfinance uses date boundaries; otherwise legacy `period=` semantics apply (live callers `mr_scan_service`, `price_utils`, `reconcile`, `executor._get_recent_ohlcv_safe` are unchanged). Refactored helpers `_build_yf_download_kwargs`, `_fetch_single`, `_extract_batch_frames` keep `fetch_ohlcv` body under the 60-line guardrail.
  - **PIT preserved**: `slice_to_date`'s `df.index <= cutoff` is still the binding contract; fetching wider data is methodologically fine per pre-reg addendum 1 §A1. The 200-trading-day gate in `slice_to_date` is unchanged.
  - **3 regression-locks added** (each fails pre-fix and passes post-fix): `tests/test_backtester.py::test_backtest_model_produces_trades_for_old_test_window`; `tests/evaluation/test_corpus_generator.py::TestDryRunWithPastDates::test_dry_run_writes_entries_for_past_window`; `tests/evaluation/test_walkforward.py::test_all_folds_produce_trades` (8-fold integration smoke). `tracker:104`.
- **#858 Option A options-metrics PIT loader** (Sprint 1.C pre-Stage-1 robustness — closes Section 8 PIT gap surfaced by audit #879) — `src/features/engine_helpers.py::_load_options_metrics` accepts `as_of: str | None = None`. When set, query filters `collected_date <= as_of` and selects per-ticker latest snapshot (replaces the global `MAX(collected_at)` subquery that excluded tickers with stale data even at runtime). SELECT now covers all 6 prompt-side fields including the previously-dropped `iv_percentile` + `atm_iv_30d`; the schema column `iv_skew` is aliased to `iv_skew_25d` so `src/llm/packet_writer.py::_interpret_skew` and Section 8 prompt template populate (these have rendered 'n/a' since v0.0). `compute_all_features` propagates as_of through `load_shared_enrichments` to the loader. 7 new tests in `TestLoadOptionsMetricsPIT` mirroring the #856 PIT-discrimination shape. PR #882.
- **#82 deterministic-ranker shadow portfolio** (Sprint 1.C Phase 5) — `src/evaluation/backtester.py::backtest_model` gains optional `shadow: bool = False`; `src/evaluation/walkforward.py::run_walkforward` gains `with_shadow: bool = False`. Implements pre-reg §6 secondary diagnostic + addendum §A1.6. When `shadow=True` with `corpus_id`: every parse_failed=0 entry produces a trade regardless of `llm_action` (strips LLM filter). Without corpus: every ranker candidate becomes a trade. §A1.6 fair-comparison enforced via `load_entries_by_decision(parse_clean_only=True)` upstream. `with_shadow=True` returns `{primary, shadow, delta, corpus_id, manifest_admissibility}`; `False` (default) preserves flat shape exactly (regression-lock for #81). CLI `--with-shadow` flag. 11 new tests in `tests/evaluation/test_shadow.py`. `walkforward.py` 367→427 lines added to `config/known_violations.json`. PR #881.
- **#860 earnings tables PIT discipline audit** — `docs/research/earnings-tables-pit-audit.md`. Mixed: `analyst_estimates` PIT-correct cross-day; `earnings_calendar` PIT-broken (UPSERT overwrite) AND empty in prod. Schema gap (no UNIQUE for ON CONFLICT). PM-rescue from terminated agent. 4 options documented (PM lean B). Addendum-2 required. PR #880.
- **#858 Section 8 options-flow source audit** — `docs/research/section-8-options-source-audit.md`. **MAJOR FINDING**: §A2.2 placeholder treatment WRONG — live producer exists (`options_metrics.py` → `options_metrics` table) but loader is PIT-broken + has `iv_skew_25d` field-name mismatch + drops 2 schema columns. PM-rescue from terminated agent. PM lean Option A (fix loader). Addendum-2 required. PR #879.
- **chore: bump arcis agent maxTurns to 100** across all 18 agents. Resolves silent-termination class. PR #878.
- **#96.2 LLM-scoring corpus generator** (Phase 4 sub-task 2) — `corpus_generator.py` + `scripts/generate_llm_corpus.py`. Streams `CorpusEntry` to `entries.jsonl` + `manifest.json`. CLI: `--corpus-id`, `--window-start/--window-end`, `--model-version`, `--dry-run`, `--max-decisions`, `--folds`, `--resume`. `model_version=None` raises ValueError per §A1.1. Two follow-ups deferred (#98, #99). 11 new tests. PR #876.
- **#96.3 + #96.4 backtester + walkforward consume corpus** (Phase 4 sub-tasks 3+4 bundled) — `backtest_model` + `run_walkforward` accept `corpus_id`. Backtester loads via `load_entries_by_decision(parse_clean_only=True)` per §A1.4. Walkforward's `_gate_corpus_or_raise` fires §A3 admissibility gate before any fold runs. Result dict gains corpus provenance. 18 new tests. PR #877.
- **#96.1 corpus data model + reader** (Sprint 1.C Phase 4 foundation) — `src/evaluation/corpus.py`. Defines `CorpusEntry` (per-decision artifact per pre-reg addendum 1 §A3.1: as_of, ticker, model_version, prompt_sha256, response, llm_action, llm_conviction, parse_failed, parser_strategy_succeeded, prompt_section_omitted, enrichment_pit_warnings, generated_at) + `CorpusManifest` (reproducibility receipts per §A3.2: corpus_id, code_sha, walkforward window, totals, parse_failure_rate, section_pit_status, coverage_limit_hits, admissibility) + `compute_admissibility()` encoding §A1.4 5% parse-failure ceiling + §A2.1 broken-section gate. JSONL storage at `data/corpus/<corpus_id>/{entries.jsonl, manifest.json}` (overridable via `ARCIS_CORPUS_ROOT`). `load_entries_by_decision(parse_clean_only=True)` default enforces §A1.4 row exclusion at read time so primary-metric path can't accidentally include parse-failed rows. 25 new tests in `tests/evaluation/test_corpus.py` including a cross-module drift check against `src/attribution/logger.py::_CANONICAL_LLM_ACTIONS`. Foundation for #96.2 (generator) + #96.3 (backtester wiring) + #96.4 (walkforward integration).
- **#856 fundamentals PIT routing** (Sprint 1.C Phase 2 follow-up #3 — audit's #1 high-severity finding) — `fetch_fundamental_snapshot` + `_get_latest_value` + `_get_ttm_value` accept `as_of`. When set: filter entries by `filed <= as_of` BEFORE sorting, then sort by `filed` desc (period-end secondary). Closes the audit's "sort by `end` not `filed`" bug — XBRL filings filed AFTER as_of were leaking into historical decision points. Cache key encodes as_of. 10 new tests in `TestFundamentalsAsOfRouting` including the synthetic Q3-vs-Q4 bug case (Q4 with end=2024-12-31, filed=2025-02-15 is correctly excluded at as_of=2024-12-31). PM-rebased after agent's PR #867 was auto-closed when its base was deleted on the #865 squash.
- **#857 insiders PIT routing** (Sprint 1.C Phase 2 follow-up #4) — `fetch_insider_activity` accepts `as_of`. When set: computes window=[as_of-lookback_days, as_of] and passes Finnhub `from`/`to` for TEMPORAL COMPLIANCE. Cache key encodes as_of. 4 new tests in `TestInsidersAsOfRouting`. PM-rebased after agent's PR #866 was auto-closed when its base was deleted on the #865 squash.
- **#854 news PIT routing** (Sprint 1.C Phase 2 follow-up #1) — `src/data_enrichment/enricher.py::enrich_features` gains an `as_of: str | None = None` parameter. When set, news fetch routes to `fetch_historical_news(as_of_date=...)` (already implemented at `news.py:200`, just not previously wired). When None (runtime default), behavior unchanged. Establishes the `as_of` plumbing pattern that #855/#856/#857/#859 follow. PR #865.
- **#855 macro PIT routing** (Sprint 1.C Phase 2 follow-up #2 — Section 7) — `fetch_macro_context` + `_fetch_series` + `_fetch_cpi_yoy` accept `as_of`. FRED API receives `observation_end=as_of`. Cache key encodes as_of; PIT entries skip freshness. Section 11 cross-asset bundling found no live producer (filed as #870). PR #869.
- **#859 earnings-signals PIT plumbing** (Sprint 1.C Phase 2 follow-up #5) — `compute_earnings_signals` accepts `as_of`. `earnings_calendar` lookup binds `date(?)`; `analyst_estimates` queries gain `AND collected_at <= ?` filter; proximity uses `as_of` not `datetime.now(ET)`. 11 new tests in `TestEarningsSignalsAsOfRouting`. Depends on #860 (table-level audit) for full PIT correctness.
- **#850 parse-failed flag** (Sprint 1.C Phase 1d) — additive `parse_failed INTEGER DEFAULT 0` column on `attribution_trades`. `src/llm/packet_writer.py` sets `packet.llm_conviction_parse_failed = True` at the 4 conviction-fallback sites + `False` on successful parse. `src/attribution/logger.py::log_attribution_after_llm` accepts `parse_failed: bool = False`, persisted as 0/1. `scan_service.py` + `universe_scanner.py` (both Phase 2 + rejected-overwrite call sites) pass the flag via `getattr(packet, 'llm_conviction_parse_failed', False)`. `scripts/diagnostics/attribution_readout.py` v2 — §3 conviction-band table + §4 selection-alpha t-test now filter `AND COALESCE(parse_failed, 0) = 0` for parse-clean reads; pollution count surfaced separately. 4 new tests in `TestParseFailed`. PR #863. PM-rescued from a stalled background agent that had completed the work but timed out on full test sweep.
- **#95 pre-reg addendum 1** (Sprint 1.C Phase 3) — `docs/research/pre-registration-stage1-addendum-1.md`. Locks the LLM-scoring methodology before Phase 4 corpus generation begins (per pre-reg §5.3 forbidding amendments after results are visible). Six §A1 commitments: model=arcis:v1.0.0, temp=0, prompt format frozen at v0.32.0, parse_failed=1 rows excluded from primary metric, "taken" semantic = canonical+rec_id+parse_failed=0, deterministic-ranker shadow uses same row filter for fair comparison. §A2 PIT compliance: 6 PIT-fix trackers (#854-#859 bundle) MUST close before Stage 1 begins; sectors+options+earnings_calendar+yfinance-auto-adjust accepted as documented impurities per operator's PR #853 review. §A3 corpus contract: per-decision artifact requirements (model_version, prompt_sha256, parse_failed, parser_strategy_succeeded, prompt_section_omitted, enrichment_pit_warnings) + reproducibility manifest + regeneration policy. §A4 confirms original §3.3 OOS window unchanged (2023-09 onward, 8 folds — already inside Finnhub coverage limits). PR #864.
- 8 PIT follow-ups #854-#861 filed (Sprint 1.C Phase 2 fix sequencing) — not yet started.

_Next minor cut (v0.33.0) will land when #850 + #95 + at least one PIT follow-up close. Patch cuts (v0.32.x) reserved for hotfixes._

## [v0.32.0] - 2026-04-29 — Sprint 1.C Phase 1 + Phase 2: attribution discipline + LLM-prompt PIT audit

### Release summary

Sprint 1.C kicked off with operator option C ("wire LLM-scoring into backtester first, then build deterministic-ranker shadow"). Phase 1 closed three measurement-quality bugs in attribution data surfaced by the §4 attribution_readout in PR #845. Phase 2 audited all 11 sections of the LLM prompt assembly path against PIT semantics — the binding finding that gates Phase 4 corpus generation. Pre-reg §3.1 Stage 1 start date may need revision from 2014 to ~2022 due to insider/news Finnhub coverage limits surfaced by the audit.

### Added

- **Attribution canonical action validator** (`src/attribution/logger.py`) — `_CANONICAL_LLM_ACTIONS` frozenset + `ValueError` on non-canonical input. Caller-side bugs surface immediately at write time. (#846 / PR #849)
- **`scripts/diagnostics/attribution_readout.py` band correctness** — bands rescaled from 0-49/50-69/70-84/85+ (modeled on ranker_score 0-100) to 1-3/4-6/7-8/9-10 matching the canonical 1-10 conviction scale. Surfaced 7-8 band as the cleanest signal currently available (avg pnl 1.56% on n=32, not contaminated by conviction=5 parse-failures). (#847 / PR #851)
- **Coverage-drop postmortem** — `audits/attribution-coverage-drop-postmortem-2026-04-29.md`. The audit's "117 H1 vs 3 H2" headline reframed: not a coverage break but a model-version transition (`halcyon-v1.0.0` → `arcis:v1.0.0`) on Apr 13 compounded with parse-failure pollution. (#848 / PR #852)
- **LLM-prompt PIT-cleanliness audit** — `docs/research/llm-prompt-pit-audit.md`. 11 prompt sections traced against PIT semantics. Sections 1-2 clean; 4/5/7/10/11 PIT-broken (HIGH severity); 6 wireable; 3 needs operator policy; 8/9 unclear. Six operator decisions surfaced. (#94 / PR #853)
- **8 PIT follow-up trackers filed** (#854-#861) for the must-fix sections + sub-investigations + sector-PIT-policy doc.
- **#850 follow-up tracker filed** for conviction=5 parse-failure pollution (gates Phase 4 corpus generation).

### Fixed

- **`src/services/scan_service.py:305`** wrote non-canonical `"buy"`/`"skip"` labels for 227 rows (80 + 147) silently excluded from §4 t-test. Canonicalized to mirror `universe_scanner.py:248-253` semantics: `taken` if rec_id+conviction, `conviction_none` if rec_id+no-conviction, `rejected` otherwise. (#846 / PR #849)

### Decisions

- **Sprint 1.C option C locked in** — wire LLM-scoring into backtester first, then build deterministic-ranker shadow. Pre-computed corpus strategy chosen over live-LLM-call.
- **Phase 1d added** — #850 parse-failure flag (option B: schema add, non-destructive) added as Phase 1d after #847 surfaced the parse-failure pollution. In flight at v0.32.0 cut.
- **Pre-reg §3.1 revision likely** — Stage 1 start date may need to advance from 2014 to ~2022 per audit findings (Finnhub coverage limits on Sections 5+6). Phase 3 addendum will lock the final decision.

## [v0.31.0] - 2026-04-28 — Sprint 1.B Wave A/B/C: walk-forward harness + methodology wiring

### Release summary

Sprint 1.B closed the gap between the methodology toolkit shelf (built across PR-690 / Track 1.5) and production wiring. Walk-forward harness, cost-model calibration, FRED-backed risk-free rate, promotion-gate post-train flow, subgroup-analysis harness all wired. Pre-registration document drafted (Stage 1 walk-forward validation discipline). Pre-push hook (#59) closed the stale-base hazard class after 5 incidents in 5 days.

### Added

- **Walk-forward harness** (`src/evaluation/walkforward.py`) — anchored expanding × 8 folds × 21-day embargo. Underpowered-fold flag (<15 trades) excludes from primary aggregate per pre-reg §3.5. (#78 / PR #831)
- **Cost-model calibration wiring** — backtester reads `data/calibration/cost_model.json`; per-trade `median_round_trip_cost_bps` deducted at entry. Falls back to zero cost with warning if absent. (#79 / PR #834)
- **FRED-backed risk-free rate** — `src/data_ingestion/risk_free_rate.py` wired into backtester via per-trade `get_rf_rate()` lookup. Replaces placeholder `rf=0.0001`. (#80 / PR #835)
- **Promotion-gate post-train flow** — `src/methods/promotion_gate.py` wired into training/post-train; ≥4-of-5 voting gate now runs on every promotion candidate. (#49 Sprint 1.B Wave B / PR #836)
- **Subgroup-analysis harness** (`src/evaluation/subgroup_analysis.py`) — pre-reg §6 exploratory subgroups (regime/year/sector/LLM-conviction) with per-partition metrics (trade_count, mean_return, win_rate, Sharpe via canonical raw_sharpe, max_drawdown_pct). 24 tests. (#81 / PR #845)
- **Pre-registration document** (`docs/research/pre-registration-stage1.md`) — binding methodology contract per §5.3 (forbids post-hoc fixes once Stage 1 begins). (#63 / PR #822)
- **Pre-push git hook** (`scripts/hooks/pre-push`) — refuses pushes from branches behind origin/main. Closes stale-base hazard class (5 incidents: #769, #816, #829, #840, #841). Bypass: `git push --no-verify`. (#59 / PR #842)
- **Backtester import smoke test** + **kill_switch test isolation** + **scan_metrics UNIQUE constraint** (#52, #62, #64 — bundled patches).

### Fixed

- **`src/evaluation/backtester.py` silent except** narrowed to `(ConnectionError, TimeoutError)` (#67 / PR #830).
- **`backtester.slice_to_date` import** restored (closes 0-trades mystery, #64 / PR #823).
- **Validator hardcoded snapshot-size cap** replaced with data-driven `max_observed × 1.05` (#65 / PR #837).
- **`diagnostic_runs` stale-job watchdog** at watch-loop startup (#56 / Tier 1.D / PR #840).
- **`docs/methodology-toolkit.md`** conflict markers shipped to main by #835 squash-merge — hotfix (PR #839).

### Decisions

- **Pre-registration § committed**: §1 deterministic-ranker shadow as secondary diagnostic; §3.5 underpowered-fold filter <15 trades; §6 four exploratory subgroups; §8.1 exploratory not pass/fail.
- **Per-trade allocation_pct=0.05** anchors the backtester equity curve; subgroup harness mirrors this for max-drawdown computation.

## [v0.30.0] - 2026-04-28 — Reconcile track + dashboard sprint (Tier 1.A-1.F)

### Release summary

Two parallel tracks closed: (1) Render Postgres delete-replication reconcile track (#68-#74) addressing 623,360 ghost rows accumulated across 25 tables from prior SQLite-archive cycles, and (2) dashboard sprint resolving operator's 2026-04-27 audit Tier 1.A-1.F findings (old-data display, empty registries, API failures + CORS, stuck training audit, "Clear stale" 404, "outcome data pending migration"). One-time manual reconcile (Pass 1 + 2 + 3) executed with operator approval.

### Added

- **Delete-replication reconcile module** (`src/sync/reconcile.py`) — `is_eligible()`, `topo_sort_reconcile_tables()`, `assert_no_ghost_rows()`, `reconcile_all()`. Snapshot-Postgres-first (race-window discipline). (#68-#74 series)
- **`TableDef.sync_reconcile: bool`** registry-driven allowlist (33 tables flagged). Pass 1+2+3 reconciled tables + "Clean (no diff)" eligibles. (#73 / PR #829)
- **Periodic reconcile in `RenderSyncThread`** — `_maybe_run_reconcile()` helper with `reconcile_every_n_cycles=30` default; integrated into `run_sync_cycle` end-of-cycle. (#72 / PR #832)
- **`src/schema/sync_config._topo_sort_tables()`** — Kahn's BFS with cycle detection via `len(result) != len(names)`; dual-source FK lookup (TableDef.foreign_keys or fallback to TABLES registry). (#76 / PR #826)
- **Dashboard cloud routes wired** — kpis, broker_exceptions, preflight orphan route imports added to `src/api/cloud_app.py`. CORS env-var documented. (Tier 1.C / PR #833)
- **Dashboard `/api/commands/expire-stale`** + **COALESCE outcome query** — closes Tier 1.E ("Clear stale" 404) + Tier 1.F (training outcome data pending migration). (PR #827)
- **Dashboard registry imports** in `cloud_app.py` to populate runtime registries on startup. (Tier 1.D / PR #816)

### Fixed

- **One-time manual reconcile** — 623,360 ghost rows deleted across 25 tables in three passes, with per-table verification protocol (BEFORE snapshot → execute → AFTER snapshot → verify Postgres delta == expected, SQLite unchanged, no remaining ghosts). pg_dump backups taken before each pass.
- **FK violation on `council_sessions`** during reconcile resolved by reordering deletes (children first).
- **Group B (~938K rows in `mode=latest_only` tables)** identified and **deferred to #75** for reconcile.py extension.
- **`fix(p0)` connect_db imports** missing across multiple sites (#767, #783 / PR #793).

### Deferred / follow-ups

- **#75** — extend reconcile.py to handle `mode=latest_only` + composite-key delete-replication (Group B cleanup).
- **#85** — split `RenderSyncThread.run()` (60-line cap follow-up).
- **#86** — integration test for periodic reconcile gating.
- **#87** — Cloud Postgres equivalents for broker_exceptions / preflight / kpis (currently SQLite-only via `connect_db()` — won't work on Render cloud).

## [v0.29.0] - 2026-04-27 — Sprint 1.A.x: point-in-time SP100 universe discipline

### Release summary

The single biggest training-data quality lift since v0.27.1. Migrated backtest, simulation, and training-backfill sites from "current S&P 100 membership" to point-in-time-correct historical universe lookups. Wikipedia-sourced JSON membership table with curated corp-action history (Tier A: PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal). Tier B (CELG, S, FB→META) added immediately after Tier A. T10 survivorship migration enforced by lint test.

### Added

- **`data/reference/sp100_history.json`** — Wikipedia-scraped historical SP100 membership snapshots back to ~2015. Loaded by `src/universe/pit.py::load_sp100_membership_table()`. (Sprint 1.A.0 / PR #802)
- **`src/universe/pit.py`** — canonical PIT lookup module: `get_sp100_at(as_of, membership_table=None)`, `get_data_range()`, `get_all_historical_tickers()`. `UniverseDataMissing` raised for out-of-range or missing JSON. (Sprint 1.A.0 / PR #802)
- **`scripts/build_sp100_history.py`** — regenerates the JSON via Wikipedia scraper + curated changes. (Sprint 1.A.0 / PR #802)
- **T10 survivorship migration** — backtest/sim/training-backfill sites now use `get_sp100_at(<as_of>)`; text-masking sites use `get_all_historical_tickers()`. Live-runtime callers (scheduler/services/cli/api/llm/platform/commands/training-bootstrap) intentionally retain `get_sp100_universe()`. (Sprint 1.A.1 / PR #813)
- **Tier A corp-action handling** — PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal in `_CURATED_CHANGES`. (#803 / PR #818)
- **Tier B corp-action handling** — CELG, S, FB→META. (#803 follow-up / PR #821)
- **`tests/test_pit_universe_discipline.py`** — allowlist + lint test enforcing T10 migration.
- **Smoke backtest tool** (`scripts/smoke_backtest.py`) — operator-runnable PIT validation.
- **Test baseline** lifted from 3671 → 3682 (T10 regression-locks +11). CI floor bumped in `CLAUDE.md`.

### Fixed

- **Render Postgres compat** — `ARCIS_DB_PATH` made optional when `DATABASE_URL` is set (#768 / PR #782).
- **Schema-verify infinite loop** at watch-loop startup (#766 hotfix).
- **`src/api/cloud_app.py`** missing registry-populating imports (#807 / PR #816).

## [v0.28.0] - 2026-04-26 — Sprint 0 wave-system + 0.B-0.D consolidation

### Release summary

Post-Track-1.5 + post-PR-690 sweep. 14 wave-style PRs (Sprint 0 Wave 1a-5c) closed dashboard cockpit, status-constants, exit vocabulary lifecycle, watch-loop discipline, schema floor, local-auth surface, FRED rf wiring v2, walkforward KPIs SE, Sharpe consolidation, promotion-gate methodology, live-order verification, PIT features. Followed by Sprint 0.B-0.D triage closing ~30 silent-failure / code-hygiene / connect-db / size / method-violation findings from Round-7/7b technical audit. PM-autonomous parallel agent dispatch with worktree isolation discipline (formalized in this release after #690 N3 stash-pop incidents).

### Added

- **14 Sprint 0 Wave-X parallel-dispatch PRs** (#700-#724): frontend cockpit, status constants, shadow-trade lifecycle bugs, DB-stub paths, schema floor, watch-loop discipline, exit-vocabulary lifecycle, local-auth surface, docs+MIME+API-secret, FRED-rf-v2, Sharpe consolidation eval, promotion-gate methodology, live-order verification, PIT features. Each carried strict-rigor receipts; 5/5 stash-pop class incidents documented + recovered via `git fsck --lost-found`.
- **Worktree-per-agent dispatch pattern formalized** — `CLAUDE.md` "Parallel Agent Dispatch — Worktree Discipline" section + recovery patterns + `.env`/untracked-files limitations doc. Closes #699. (PR #734)
- **Sprint 0.B-0.D batches**: silent-failure cleanup (B2.1), code-hygiene (B2.2), connect-db wiring (B2.3 + C.1), size refactors (B2.4 + C.2 alpaca-split), method-violation fixes (B2.5), test-triage (B2.6 + C.3 + D.2), schema-infra (C.6 sync_state in-flight), code-bugs (C.5), process+versioning audit trail (C.4), connect_db hotfixes (#793).
- **`src/version.py`** — single source of truth for app version; `get_app_version()` cleanup. (#660 closure / Sprint 0.C C.4)

### Fixed

- **Render-sync `mode=full` tables** — never strip `id` column (closes #797 / PR #800).
- **PR #690 in-PR review-finding sweep continuation** — additional N3 / O-tier findings landed via the wave system.
- **Coding-skill discipline** — Planner maxTurns 6→12 + stale-base check before PR-create (#53 follow-up / PR #817). Lessons-learned baked into anti-fallacy playbook (#749).

### Decisions

- **`feedback_strict_rigor_no_handwave.md`** — operator stated "rather take a full day than hand wave" (2026-04-26). Encoded as PM memory.
- **`feedback_autopilot_origin_check.md`** — every wakeup: `git fetch origin` + `gh pr list` BEFORE dispatching, to avoid racing operator on parallel work.
- **`feedback_worktree_env_drift.md`** — agent worktrees don't carry `.env`; tests with env-var-driven deps may pass in worktree but break post-merge.

## [v0.27.1] - 2026-04-26 — PR #690 review-finding sweep + Sprint 0 Wave 1a kickoff

### Release summary

PR #690 (Track 1.5 instrumentation) merged with 27 review findings landed as in-PR fixes (5 Blockers + 8 Important + 14 Observations). Sprint 0 Wave 1a kicked off post-merge to clear the dashboard cockpit issues that survived the PR-690 sweep — F-AUTH (Rules of Hooks compliance) + F-CHANGELOG (this entry; WhatsNewPanel was still advertising v0.25.0 as latest).

### Fixed

- **F-CHANGELOG (Sprint 0 Wave 1a / PR #690 review B3):** `frontend/src/components/system/WhatsNewPanel.jsx` was still listing v0.25.0 (2026-04-18) as the most recent entry, missing the entire Track 1.5 + Round 10 + PR #690 review-sweep work. RECENT_ENTRIES refreshed to mirror the canonical CHANGELOG (this file). Regression test added: `frontend/src/components/system/WhatsNewPanel.test.jsx` asserts the top entry is current and that the rendered date reflects the latest release. `src/version.py` bumped from v0.27.0 → v0.27.1.

- **PR #690 in-PR review-finding sweep** (full list in PR #690 commit history, summarized):
  - **B1–B5 Blockers:** exit_reconciliation direction-aware semantics + named tolerance constant (O2/O3); analytics monitor route raises 500 instead of silent empty array (O8); replaced `setdefault(key, dict.get(key))` no-op with explicit assignment (O10); publicized `compute_timeout_status` + `shadow_trades.quarantined NOT NULL` migration + integration negative-path tests (O4/O7/O9); 3 services routed `[BROKER_EXCEPTION]` → `log_and_persist` (O1-redo).
  - **I1–I8 Important:** wired FRED DTB3 rf adapter into kpis + stage1 baseline (I1); promotion-gate exception logging + distinct caption (I2); Lo (2002) autocorrelation-corrected Sharpe SE (I3); split `n_spy` and `n_total` in KPI response (I4); regenerated sprint_F engine fixtures + dropped `--ignore` (I5); labeled TradeHistory rolling Sharpe as diagnostic + used Alpaca equity for projections drawdown baseline (O11/I6); Round-8.F backtick template-literal stripping anti-regression test (I7); KPI threshold pinning (I8) with decision-matrix thresholds aligned to audit-spec §3.1 (B3-A).
  - **O1–O14 Observations:** packet_writer Key Risk regex semantics + truncation marker budget (O13); _find_latest_transcript sorts by mtime not lexicographic (O6); replaced projections.py non-canonical Sharpe with `canonical_sharpe.raw_sharpe` (B5); MR_VIX_LOOKUP_FAILED warning instead of bare pass on VIX swallow (O5); route-parity value-validation tests for kpis + projections (O14); 7 test failures from post-rewrite sweep resolved.

### Decisions

- **Decision 6 — KPI traffic-light thresholds anchored to audit-spec §3.1.** Pinning tests added in `tests/api/test_kpis.py` so Stage-1/Stage-2 boundaries cannot drift silently. Rationale + thresholds documented in PR #690 B3-A commit.

## [v0.27.0] - 2026-04-25 — Track 1.5 instrumentation gap closure (post-audit, PM-autonomous dispatch)

### Release summary

Post-audit instrumentation-gap-closure track dispatched autonomously by the PM after the 2026-04-27 Trading-Readiness Audit (v0.26.0 / v0.27.0) completed. 14 rounds + 4 plugin/infra fixes across ~16 commits. All Critical + Important findings from both audit passes cleared. ~250 new tests added.

Full design decisions, hard truths, and deferred items: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

### Added

- **Track 1.5 instrumentation deliverables (B1–B9):**
  - B1: `signal_exit_price` + `exit_slippage_bps` persisted at close (`executor.py` update path)
  - B2.A: `broker_exceptions` schema table + 4 silent-swallow upgraded to writes
  - B2.B: Structured logging for 15 broker partial-swallow sites in `executor.py`
  - B2.C: Bounded retry + qty-mismatch detection (CVS regression closure)
  - B3: `exit_reason` canonical taxonomy + nightly reconciliation script
  - B4 + B8: `key_risk_assessment` + LLM-set `expected_holding_period_days` persisted at open
  - B5 + B8: Schema + executor open-path stamping for `instrumentation_version` INTEGER sentinel + `timeout_days`; `INSTRUMENTATION_VERSION_CURRENT = 3` constant; `filter_to_version` helper (`src/analytics/instrumentation.py`)
  - B6: End-to-end integration test for full instrumentation pipeline
  - B9: `llm_timeout_days` surfaced in dashboard trade ledgers

- **5-KPI hero strip** (`frontend/src/components/dashboard/KPIStrip.jsx` + `src/api/cloud_routes/kpis.py`): rf-adjusted excess Sharpe, SPY-relative Sharpe + p-value + CI, win rate, Stage-1/2 traffic light, promotion-gate vote count. Replaces Dashboard hero MetricCards.

- **`broker_exceptions` panel** (`frontend/src/components/dashboard/BrokerExceptionsPanel.jsx` + `/api/broker-exceptions` endpoint): live-trade observability for all broker partial-swallows and exception writes. Critical gap from Round 7b G1 finding.

- **Preflight gate UI echo** (Round 8 / S4): `scripts/preflight_monday.py` output now written back to Dashboard via a preflight result card. Prior state: output written to disk only, never read back.

- **Vitest infra** (`frontend/src/` test harness) + `arcis-pulse` keyframe animation (B9 cleanup).

- **`docs/instrumentation_versions.md`** (NEW): v0/v1/v2/v3 version-to-feature matrix per B5 design. Rationale for the INTEGER sentinel, analytics filter rules, cross-references to B5 design doc + executor stamping point + `filter_to_version` helper.

- **3 new sprints queued** (post-Track-1.5): (1) v0.26.3 `sections_json` widening, (2) System Index visibility audit, (3) Council impact analysis. Cohort 3 strategy redesign (T2.14b/T2.14c/T2.16b) also queued as Sprint 4.

### Changed

- **Dashboard hero replaced with canonical KPIStrip** (R1 resolved): three incompatible Sharpe formulas across four surfaces collapsed to a single canonical strip. Dashboard hero and CTOReport previously used uncanonical `mean/stdev`; only TradeHistory attribution panel used T1.03. Now the strip is the single source of truth.

- **Win-rate silent fallback removed** (R2 fixed): `Dashboard.jsx:469` previously fell back to Alpaca account API value when `shadow_service` returned null — different denominator, no quarantine filter, misleading number. Fallback removed; null → `"—"` displayed.

- **P&L source labels added** (R3 fixed): Shadow Equity and cumulative P&L chart now carry explicit source annotations so operator can see when values come from different count bases.

### Fixed

- **5 Critical findings from Round 7 technical audit** (Round 8.A):
  - C1 Monitoring history shape mismatch — backend `{snapshots: [...]}` vs frontend array expectation
  - C2/C3/C4 Local-route parity — `/ib-shadow/*`, `/strategy-detail/{type}`, `/system/index` mirrored to local FastAPI
  - C5 `RevenueProjection` live route added

- **3 deferred audit items closed in Round 8.F** (cosmetic + Important-tier findings): SPY data source label, double-prefix bug, and remaining Important catch-all items from Round 7 + 7b.

### Decisions

- **Fix-everything-technically-before-trading principle** adopted as SD#46 (2026-04-25). Supersedes Mon $100 deploy from SD#41 REVISED until Cohort 3 redesign produces a strategy with positive expected alpha. Full reasoning in `track-1.5-DECISIONS.md` Decision 1. Memory artifact: `feedback_fix_before_trade.md`.

- **5-KPI strip layout approved** with documented color rules per §3.1 Decision Matrix thresholds.

- **Mon $100 live deploy DEFERRED** until post-Cohort-3 strategy redesign. Mon AM preflight still runs as system-health check, not deploy gate. Next deploy decision happens after Cohort 3 redesign (T2.14b/T2.14c/T2.16b) produces a strategy with reason to believe in its alpha signal.

Full reasoning for all decisions: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

## [v0.26.0] - 2026-04-23 — v0.26.0 chain complete + triage bundle + overshoot root cause

### Release summary

Tag cut pre-Friday bootcamp archive (SD#42) to anchor code state for the DB cutover. Scope since v0.25.0 is too large for a patch release — this is a minor bump.

**Trading safety (critical):**
- Exit-overshoot cancel-race fix (#608/#609/#610, PR #636): `_handle_pre_exit_cancel` routes to `_close_from_broker_fill` when cancel races a fill instead of submitting another SELL. Addresses C 4/21 + AMD 4/22 root cause that survived #595.
- CVS retry loop + phantom exits (PR #595): D2 reconcile 3rd branch + D3 executor qty sync + _strip_enum enum.value normalization.
- Council fail-closed (#612, PR #636): ClaudeAuthError + CouncilUnavailableError replace silent fake 5-0 consensus from failed stubs.

**Training data:**
- Silent-failure detection (#615, PR #636): CollectionResult dataclass + Telegram alert when is_silent_failure=True. Closes 11-day blind-spot pattern 4/13-4/23.
- Missing recommendation fallback (PR #606): LEFT JOIN + COALESCE + _build_feature_input_from_trade fallback builder + skip-instead-of-degenerate-example guard.

**v0.26.0 chain (closes #530):**
- Sprint F (PR #585): spec-driven ranker + features/enrichment port with 20 byte-identity fixtures
- Sprint G/H (commit 413fd39): spec-driven packet builder + scan plumbing

**Triage bundle (PR #636 — 29 issues closed across 4 tiers):**
- Tier 3 dep-health 13-pack: #527, #544-546, #572, #587-590, #599-601, #605, #608-610, #612, #615, #616, #630
- Tier 1 observability: #613, #614, #618, #623
- Tier 2 safety one-liners: #438, #440
- Tier 4 scoped feature work: #576, #598, #622, #624

**Dashboard (PR #637, #638):**
- src/version.py single source of truth (#631-15)
- Trade open/close websocket refresh events
- 10 other UX polish items from #631


### Fixed (Sprint fix/paper-exit-qty-asymmetry — CVS retry loop + phantom exits)

Closes #591 (D2 reconcile 3rd branch) and #592 (D3 paper exit qty sync).

Three interlocking bugs surfaced by the 2026-04-21 investigation
(`docs/audit/root_cause_investigation_2026-04-21.md`) collapsed into a
single root cause: `_strip_enum` at `src/shadow_trading/alpaca_adapter.py:38`
returned UPPERCASE names instead of lowercase values from alpaca-py's
regular-Enum `OrderStatus`. Downstream executor checks at
`executor.py:1375` and `:1383` compare against lowercase sets and
silently missed every filled bracket leg. Fallback stop/target/timeout
path then dispatched `_submit_exit_order(planned_shares)` against a
position already closed server-side → phantom sell-to-open → overshoot.

CVS on 2026-04-21 added a second failure mode: a partial fill left
4 residual shares against `planned_shares=130`. Reconcile's stuck-trade
resolution only had two branches (qty<=0 or qty>0); missing branch for
`0 < qty < planned` reverted to `open` every cycle → 17+ failed sell
attempts before operator manual quarantine.

- **D2 fix (`src/shadow_trading/reconcile.py:655-700`):** added the
  `0 < alpaca_qty < planned_shares` branch. Marks
  `status='needs_manual_review'`, `exit_reason='qty_mismatch_partial_fill'`.
  Distinct reason separates qty-mismatch residuals from directional
  overshoots for cleanup tooling.
- **D3 fix (`src/shadow_trading/executor.py`):** new helper
  `_sync_exit_qty(ticker, requested_shares, broker_positions)` reuses
  the `get_all_positions` result already fetched at `:1174` (now a
  `dict[str, float]` keyed by ticker) to clip or skip exits against
  actual broker qty. Threads `broker_positions` through `_retry_exit`.
  Phantom exits (`broker_qty <= 0`) are marked `exit_pending` with
  `position_already_closed` for reconcile to finalize — no sell ever
  submitted against a closed position.
- **Upstream fix (`src/shadow_trading/alpaca_adapter.py:38-70`):**
  `_strip_enum` now returns `val.value` for `enum.Enum` instances.
  Callsite audit documented in commit 6 message — no other callers
  needed changes beyond the existing `.lower()` patterns they already
  applied (`bracket_monitor.py:75`, `_is_filled_status`, `_is_pending_status`).
- **9 new tests + 3 test updates** covering partial-fill mismatch,
  phantom-exit prevention, race with reconcile, `_strip_enum`
  normalization, and bracket leg-fill detection case-insensitivity.
  Three existing tests (`test_retry_exit_called_for_exit_failed`,
  `test_bad_timestamp_forces_timeout`, `test_exception_marks_exit_failed_not_open`)
  updated to mock broker positions so they exercise their intended paths
  rather than hitting D3's new skip branch.
- **`scripts/cleanup_overshoot_zombies_2026_04_21.py`** for operator to
  run post-deploy to close the 13 accumulated zombies (dry-run default;
  `--apply` required; idempotent; read-only Alpaca calls).

Sprint artifacts:
- Pass 1 evaluation: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md`
- Pass 2 research: `docs/sprints/fix_paper_exit_qty_asymmetry_research.md`

Pre-existing failures on main, NOT introduced or fixed by this sprint:
2 Sprint F byte-identity tests; `ranker.py` > 400 lines (not in
`config/known_violations.json`).

### Added (Cleanup Sprint 3 — 4 strategic-sprint spec drafts)

Four draftable-tonight specs surfaced by the 2026-04-20 audit's
"Strategic" items 1–4, landed in `docs/sprints/future/`. Zero code
changes; future-CC can Ralph-Loop each spec into its own sprint.

- **`docs/sprints/future/eval_harness_spec.md`** — wire the existing
  canary / A/B / quality-drift / leakage-detector infrastructure into
  a nightly harness that gates model promotions (300-prompt canary,
  6-dim rubric judge, composite gate, `eval_results` table). 2–3
  sprints to deliver; dependencies none.
- **`docs/sprints/future/second_strategy_evaluation_spec.md`** —
  pivoted from the prompt's 4-candidate selection to "implement the
  already-selected Strategy 2 (mean reversion) and Strategy 3
  (evolved PEAD)" because existing decision docs
  (`Strategy_2_Selection__Mean_Reversion_Wins.md`, ADR-002) already
  made the selection. Track A: Strategy 2 implementation audit.
  Track B: Strategy 3 ground-up build (4-way PEAD composite).
- **`docs/sprints/future/training_curriculum_gate_spec.md`** —
  10-criteria pre-training gate blocking training runs with
  unbalanced outcome mix (40/25/5/15) or ratio drift from the 62/38
  curated/generated target. Chains with the eval harness spec
  (post-training gate) without circular dependency. 1–2 sprints.
- **`docs/sprints/future/containerization_spec.md`** — move training
  subsystem to WSL2 (alone first, Docker later) to eliminate cp1252
  issues that cost three subsystems tonight. Watch loop stays
  Windows-native per NSSM integration. 1–2 sprints.

Pass-1 evaluation + Pass-2 research docs in
`docs/sprints/cleanup_sprint_3_evaluation.md` and
`cleanup_sprint_3_research.md` record the scope pivots for Spec 1
(infra exists, not greenfield) and Spec 2 (decisions already made).

---

### Added (Cleanup Sprint 2 — Track A DB reconciliation script)

`scripts/reconcile_2026_04_20.py` — one-shot DB reconciliation for the
19 broken-state shadow_trades rows + 1 stale model_versions row
surfaced by the 2026-04-20 live-state analysis. Author-only in this
PR; the operator runs it after Alpaca fills confirm zero-short state.

- 12 trades (9 CLOSE_AT_OPEN incl GS + 3 NEEDS_OPERATOR_JUDGMENT) →
  `status='closed'`, `exit_reason='manual_reconcile'`.
- 7 trades (4 stale exit_failed + 3 open-row phantoms) →
  `status='exit_abandoned'`, `exit_reason='phantom_row_cleanup'`.
- TGT #12 broker-tag corrected `ib → alpaca` (position was on Alpaca).
- `model_versions.arcis:v1.0.0` → `status='active'` after three-way
  reconciliation (Ollama + config agree it is operational).

Safeguards: kill-switch pre-flight (exit 2), Alpaca pre-flight for
zero shorts (exit 3), single atomic transaction, post-update count
verification with rollback (exit 4), idempotent re-runs skip resolved
rows. Structured audit log appended to
`docs/audit/reconcile_2026_04_20_execution.log`. 5 regression tests
(`tests/scripts/test_reconcile_2026_04_20.py`).

### Changed (Cleanup Sprint 2 — `bootcamp.max_packets_per_scan` 20 → 8)

`config/settings.local.yaml:103` (gitignored — operator-local value).
Post-reconciliation BP (~$100-200K) comfortably fits 8 × ~$15.5K = $124K.
20-cap produced 11 BP-rejections 2026-04-20 because 20 × $15.5K =
$310K exceeded the $6,982 BP. Matches `settings.example.yaml:455`
default. **Operator must manually verify their local
`config/settings.local.yaml` contains `max_packets_per_scan: 8`** —
gitignored file cannot be committed.

### Fixed (Cleanup Sprint 2 — 7 medium-risk code fixes: L, K, C2-partial, H4, H5, H7, L5)

Seven independent code fixes from the 2026-04-20 post-market audit.
Kill-switch engaged throughout; no order submissions, no live-state
mutations. See `docs/sprints/cleanup_sprint_2_evaluation.md` (Pass-1)
and `cleanup_sprint_2_research.md` (Pass-2) for per-item rationale.

- **L — `_scan_cycle_committed` reset on every scan entry.**
  The module-level BP-committed counter persisted across scan cycles
  because `reset_scan_cycle_committed()` was called only from
  `src/services/scan_service.py:37`. The production watch path
  (`src/scheduler/universe_scanner.py`) and the MR path
  (`src/services/mr_scan_service.py`) skipped the reset, producing
  `committed $37,942` persistence across 11 scans today. Fix: add
  `reset_scan_cycle_committed()` at the top of both scan entries.
  4 regression tests including a static guard that fails CI if any
  scan-entry module loses the reset call.
- **K — pre-LLM BP check in scan entry paths.**
  New helpers `_check_paper_buying_power_allocation(allocation)` and
  `_record_bp_rejection_pre_llm(packet)` in executor.py. Wired at
  `universe_scanner.py:202`, `scan_service.py:169`, and
  `mr_scan_service.py:117` — before `enhance_packet_with_llm`. Saves
  ~17s of Ollama compute per un-fundable ticker (11 AVGO retries
  today = ~3 min wasted). Fail-closed on account-fetch errors. Does
  not increment `_scan_cycle_committed` (authoritative gate stays at
  `executor.py:598`). 7 regression tests.
- **C2-partial — cancel dangling orders before orphan backfill.**
  `reconcile.py:498` orphan-backfill loop now calls
  `cancel_orders_for_ticker` before `insert_shadow_trade`, matching
  the existing stale-close path at `:546` (fix #356). Prevents
  stale bracket legs from firing a duplicate sell after backfill
  (the exit-overshoot pattern behind today's 12 shorts). 2
  regression tests.
- **H4 — governor-disabled critical alert.**
  `risk/governor.py` — when `enabled=False`, `check_trade` now fires
  one `logger.critical` + one Telegram alert per process lifetime
  (module-level sentinel prevents per-check spam). Alert message
  names the config key to edit (`risk_governor.enabled`). Prevents a
  silent governance bypass from a config flip. 5 regression tests.
- **H5 — traffic-light credit classifier `int+str` TypeError.**
  `macro_snapshots.value` is stored as SQLite TEXT (SQLite type
  affinity allows str INSERTs into REAL columns). `sum(values)` of
  str raised `TypeError` (26 warnings today, silently disabling the
  credit-spread regime input). Fix: parse each value via `float()`
  with try/except skip; require 20 parseable values post-filter.
  5 regression tests.
- **H7 — bare `sqlite3.connect()` → `connect_db()` in reconcile.py.**
  7 call sites swapped. Promotes `busy_timeout` from the 5-second
  default to the canonical 30 seconds and adds `row_factory=Row`.
  Matches CLAUDE.md rule for all SQLite connections. connect_db does
  **not** apply `PRAGMA foreign_keys` or WAL (Pass-2 research
  correction) — FK enforcement remains a separate follow-up. 4
  regression tests including an integration test that a second
  writer waits rather than failing immediately.
- **L5 — EOD report format-string `Unknown format code 'f'` crash.**
  `reports.py:399-407` now casts `pnl_dollars` and `pnl_pct` to
  `float()` before passing into `notify_eod_report`'s `{:+.2f}`
  f-strings. Fixes the 4 EOD failures observed on 04-14/04-15/04-16/04-17.
  3 regression tests. Upstream writer storing TEXT remains a separate
  data-layer bug.

### Deferred to dedicated sprints

- **H8** — `activity_log.id` needs `PRIMARY KEY AUTOINCREMENT` —
  schema migration tracked in issue #580.
- **AAPL 24-day stop=0/target=0** — backfill-default root cause
  investigation tracked in issue #581.
- **Model registry archaeology** — `arcis:v1.0.0` rollback audit
  tracked in issue #582.

---

### Fixed (Cleanup Sprint 1 — critical-path code fixes: C3, H6, H3.b)

Three independent zero-live-state fixes surfaced by the 2026-04-20 log
audit (see `docs/sprints/cleanup_sprint_1_evaluation.md` and
`cleanup_sprint_1_research.md`). Kill-switch stayed engaged throughout;
no trading-path, governor, or model-registry changes.

- **C3 — reconcile dispatch `db_path=None` TypeError.**
  `src/scheduler/watch.py:694` calls `reconcile_all_paper_trades()` with
  no `db_path` kwarg; the `None` default propagated through
  `get_strategies_by_status` to `sqlite3.connect(None)` and raised
  TypeError. Intra-day reconciliation failed 13× today and has been
  silently failing every 30-min scan cycle. Added None-guards at both
  call sites (`src/shadow_trading/reconcile_dispatch.py`,
  `src/platform/promotion.py:489`) that resolve `None` to the config
  `DB_PATH`. 5 regression tests in
  `tests/shadow_trading/test_reconcile_dispatch_db_path.py`.
- **H6 — cp1252 Unicode crash in overnight reconciliation log.**
  Windows StreamHandler could not encode `❌` (U+274C) when emitted via
  `logger.info("[WATCH] %s", msg)` on line 67 (source on line 65);
  10 logger crashes today. Replaced `❌`/`✅`/`—` in logger/print/msg
  paths with `[FAIL]`/`[OK]`/`--`. Preserved emojis in Telegram-only
  paths (Telegram renders UTF-8 natively). Preserved em dashes in
  docstrings and comments (never reach an emittable stream). 5
  regression tests in `tests/scheduler/test_overnight_encoding.py`
  including a cp1252 round-trip and a static scan that fails if any
  logger/print/msg line contains cp1252-incompatible bytes.
- **H3.b — `trl` version pin.** Pinned `trl>=0.12,<0.25` in
  `requirements-training.txt`. Unbounded upper resolved to trl 1.1.0
  which ships `chat_templates/gptoss.jinja` read via `Path.read_text()`
  without an explicit encoding; on Windows that raised
  UnicodeDecodeError, killing `SFTTrainer` import and silently breaking
  overnight fine-tune for approximately one week. Pin is compatible
  with co-pinned `transformers>=4.46` and `accelerate>=1.0`.

Operator follow-up (not in sprint scope):
- Add `PYTHONUTF8=1` to the watch-loop NSSM service environment.
- `pip install -r requirements-training.txt` on the training host to
  downgrade `trl` to the 0.12–0.24 window.
- Investigate what caused remote `main` to be fast-forwarded to this
  sprint's tip without a PR (see `audit/2026-04-21` branch for the
  automated audit commit preserved from the incident).

---

### Added (2024 OHLCV backfill for Sprint F byte-identity fuzz)

Closes #570. Unblocks Sprint F (#564) byte-identity fuzz. Populates
`data/simulation_cache/` with 2023-01-01..2024-12-31 daily OHLCV for
the S&P 100 universe + SPY + ^VIX = **104 tickers, 501 trading days
each**. All 11 Sprint F fuzz/primary dates (2024-01-16 through
2024-11-19, primary 2024-03-26) have exact-match data.

**Date range is 24 months, not calendar-year 2024**, because
`compute_features` requires SMA200 (200 trading days) and RS-6m
(126 trading days) of lookback before the earliest fuzz date. A
calendar-year-2024 fetch would have broken feature computation on
the first 7 of 11 fuzz dates — confusing `SMA200 NaN` failures
attributable to data setup rather than the port. The extra 6 months
of 2023 data costs ~2 MB and ~1 minute of runtime.

**SPY is included** (not just "S&P 100 universe + ^VIX"): `rank_universe`
uses SPY for `_classify_relative_strength` (the 1m/3m/6m RS calculations
that feed `relative_strength_state`). SPY is a functional prerequisite
for the scan pipeline, not universe expansion. `^VIX` is required by
`compute_market_regime` for the `vix_proxy` volatility classification.

**New script:** `scripts/backfill_2024_ohlcv.py` (throwaway; kept
committed for re-runnability). Reuses `src/simulation/cache.py::fetch_cached_ohlcv`
— no new fetch abstractions (prompt anti-goal). Per-call parquet save
(crash-safe), cache-hit skip on re-run (idempotent).

**Results:**
- 104 of 104 tickers succeeded (0 failures)
- Runtime 83.1 seconds (under the 3-minute Pass 1 estimate)
- 4 Pass-1-flagged tickers (PYPL, F, GM, KHC) all fetched cleanly —
  none are delisted; S&P 100 membership-staleness remains an open
  observation but no new issue filed per operator direction (only
  file if >1 actually fails, which they didn't)
- 8 pre-existing scenario-partial parquets (different cache keys)
  preserved untouched as designed
- BRK.B → `BRK_B_...` filename translation verified via
  `to_yfinance_ticker()`; hyphen/dot handling clean

**Re-run:** `python scripts/backfill_2024_ohlcv.py` is idempotent —
skips cached files, re-fetches only missing ones. If any parquet is
known-bad, delete it before re-running.

---

### Fixed (Sprint C.1 — schema refinement: scoring shape gaps)

Closes #569, #567, #568 — slot 6-a in the #530 Sprint chain (chain count
revised 8→9; F/G/H shift to slots 7/8/9). Sprint F Pass 1 (see
`docs/sprints/sprint_F_evaluation.md` on `feat/port-ranker-to-spec`,
parked at `53dee07`) surfaced 9 schema shape gaps blocking byte-identity
port of the ranker; Sprint C.1 closes them before Sprint F resumes.

**9 items:**

1. **Categorical bands** — `ranking.bands` accepts `category: <str>` as
   an alternative to `range: [lo, hi]`. Mutual exclusion. Covers
   `trend_state` / `relative_strength_state` in `_score_ticker`.
2. **Compound AND conditions** — band entries may use `conditions:
   [{metric, operator, threshold}, ...]` instead of a top-level metric.
   Covers `iv_rank > 75 AND pc_vol > 1.2`. Operator enum
   `{>, >=, <, <=, ==, !=}`.
3. **Weighted blend groups** — bands accept optional `weight: float
   [0,1]` + `blend_group: <str>` for weighted sums across tagged bands.
   Covers the 0.6/0.4 market-vs-sector RS blend. Weights within a group
   should sum to 1.0 (warn if not).
4. **`ranking.adjustments` block** — new block with same grammar as
   `ranking.bands` plus `clamp: [lo, hi]`. Covers `_regime_adjustment`
   (ranker.py:72-102).
5. **`ranking.derived_metrics` block** — declarative feature derivations.
   Ops: `subtract`, `weighted_sum`. DAG cycle check. Covers
   `_compute_sector_rs` (ranker.py:105-147).
6. **#567 — `packet_worthy` → `min_score` hard-rename.** Schema validator
   previously asserted bool; runtime stored int threshold. Field is now
   `min_score: int` in `[0, 100]`. No legacy alias.
7. **#568 — `KNOWN_POST_SCAN_HELPERS` contents + strict flip.** Set
   aligned to runtime dispatch names `{traffic_light, event_risk}`;
   `post_scan.chain` flipped to `strict=True`.
8. **`KNOWN_SCORING_METRICS` registry.** 10-metric seed for
   `_validate_bands` / `_validate_band_condition`. Effective set at
   validation = seed ∪ derived-metric names from Item 5.
9. **Event-risk casing docstring (Item 9).** Schema comment codifies the
   lowercase_with_underscores convention. No runtime edits — Option 9A
   per operator resolution 2026-04-20.

**Registry additions:**

- `KNOWN_REGIME_LABELS` — 5-label set from `compute_market_regime()`
  (regime.py:161-170). Intentionally separate from `KNOWN_REGIME_KEYS`
  (7-label, threshold dispatch). Documented with comment explaining
  the split.
- `KNOWN_SCORING_METRICS` — 10-metric seed from `_score_ticker` +
  `_regime_adjustment`. Additions require a refinement sprint
  (C.1-style) — silent edits risk schema/runtime scoring drift.
- `ALLOWED_BAND_OPERATORS`, `ALLOWED_DERIVED_OPS` — operator enums.

**Structure:**

- Ranking validators extracted to `src/platform/_strategy_spec_ranking.py`
  (341 LOC) to keep `strategy_spec.py` focused and under guardrail. Main
  module re-exports the constants for public API stability.
- `strategy_spec.py`: 393 → 388 lines (under 650 guardrail).
- `tests/platform/specs/test_schema_c1_refinements.py`: 28 tests covering
  all 9 items + backward compat + registry seeds.

**Known Sprint F divergence (operator resolution 2026-04-20):** the
sector_rs None-fallback in `_score_ticker:182-187` (market gets weight
1.0 when sector data absent) is NOT expressible in pure weighted-blend
schema. Sprint F will observe byte-identity fuzz failure → STOP → file
issue for a follow-on sprint (C.2-style) if the fallback matters.

**Follow-up candidates for Sprint F or C.2:** symmetric categorical-value
validation for non-regime metrics (`trend_state`, `relative_strength_state`,
`market_breadth_label`) — each ~10 LOC. Deferred because immediate scope
is `regime_label` per operator. Sprint F may surface additional gaps
that get bundled.

**Sprint F unblocks:** once #569 merges AND #570 (2024 OHLCV data gap)
resolves, `feat/port-ranker-to-spec` (parked at `53dee07`) resumes as
Sprint F at slot 7 of 9.

---

### Added (Sprint E — hooks, enrichment, post-scan, event-risk, bootcamp schema)

Closes #551 — fifth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549, D #550 merged earlier). **Sprint E
completes the v0.26.0 schema surface**; the next two sprints (F, G) port
the runtime (`compute_all_features`, `rank_universe`, bracket engine) to
consume the declared spec instead of hardcoded logic.

`src/platform/strategy_spec.py::validate_spec` now validates five
additive optional top-level blocks:

```yaml
hooks:                           # attribution logger refs (strict)
  attribution:
    - log_before_llm
    - log_after_llm

enrichment:                      # ordered enricher chain (warn)
  chain:
    - technicals
    - insider
    - macro
    - news
    - sector

post_scan:                       # ordered post-ranking helpers (warn)
  chain:
    - classifier
    - filter_duplicates

event_risk:                      # category-based quarantine gate (warn)
  quarantine_categories:
    - earnings_imminent
    - fomc

bootcamp:                        # strategy-level bootcamp overrides (strict)
  qualification_threshold: 55
  watchlist_threshold: 30
  max_positions: 20
  traffic_light_floor: 0.5
```

Per-block policy — strict-vs-warn chosen by registry maturity
(documented in `docs/sprints/schema_final_blocks_evaluation.md §2`):

| Block | Policy | Registry source | Reason |
|-------|--------|-----------------|--------|
| `hooks.attribution` | **strict** | `src/attribution/logger.py` (2 stable functions) | Typo silently disables attribution — 2-year-old code, capability-registry-registered. |
| `enrichment.chain` | warn | no formal registry yet | Sprint prompt names aspirational; Sprint F wires the registry. |
| `post_scan.chain` | warn | no registry exists | Same; runtime binding deferred. |
| `event_risk.quarantine_categories` | warn | fragmented (`MACRO_EVENT_TYPES` + `KNOWN_EVENTS` labels) | 20-seed-entry union of current category sources; sprint-prompt earnings names aren't in code yet. |
| `bootcamp` | **strict** | `config/settings.example.yaml:435-457` | 4 keys load-bearing at 7 runtime sites; typo silently reverts to hardcoded default. |

Validation rules (strict blocks):

- **`hooks.attribution`** — list of string refs; each must be in
  `KNOWN_ATTRIBUTION_HOOKS = {log_before_llm, log_after_llm}`.
- **`bootcamp`** — dict; allowed keys are
  `{qualification_threshold, watchlist_threshold, max_positions,
  traffic_light_floor}`. Per-key type check: thresholds are int in
  `[0, 100]`, `max_positions` is a positive int (bool excluded),
  `traffic_light_floor` is a number in `[0.0, 1.0]`.

Validation rules (warn blocks): unknown refs emit
`logger.warning("[PLATFORM] %s[%d]: unknown ref %r (known: ...)")` but
do not block the spec load. Matches the Sprint C/D precedent
(ranking.bands overlap, regime-key unknowns).

Added constants and helpers in `strategy_spec.py`:

- `KNOWN_ATTRIBUTION_HOOKS`, `KNOWN_ENRICHERS`,
  `KNOWN_POST_SCAN_HELPERS`, `KNOWN_EVENT_RISK_CATEGORIES` (20 entries),
  `KNOWN_BOOTCAMP_KEYS` (all module-level frozensets).
- `_LIST_BLOCKS` dispatch tuple — single loop handles the 4
  list-of-refs blocks (hooks, enrichment, post_scan, event_risk).
- `_validate_known_ref_list(items, known, path, errors, *, strict)` —
  shared helper factoring the common shape out of four dispatch sites.
- `_validate_bootcamp_overrides(block, errors)` + `_BOOTCAMP_RULES`
  table-driven per-key type checks.

Guardrails:

- **Schema-only.** `StrategySpec` dataclass unchanged; new blocks land
  in `.raw`. Downstream consumers pick them up from `.raw` without
  modification. Reproducibility hash at `backtest_engine.py:187`
  captures the new blocks (intentional; same precedent as Sprint C/D).
- **Zero top-level key collision.** `{hooks, enrichment, post_scan,
  event_risk, bootcamp}` appear in neither `lazy_prices_v1.yaml` nor
  `post_audit_ruleset_v1.yaml`; existing `attribution` top-level key
  is in a separate namespace from `hooks.attribution`.
- **File-size budget preserved.** `strategy_spec.py` grew from 298 to
  393 lines — under the 400-line cap set by the sprint prompt.

Tests — `tests/platform/specs/test_schema_final_blocks.py` (25 tests):

- 2 tests per block × 5 blocks = 10 (prompt minimum).
- +5 combined / backward-compat (all-5-simultaneously, lazy_prices_v1,
  post_audit_ruleset_v1, none-declared, non-dict outer ignored).
- +5 edge cases (empty list, not-a-list, non-string entry, bootcamp
  not-a-dict, all-outer-dicts-empty).
- +5 bootcamp-specific (threshold range, bool-is-int trap, floor
  range, floor valid, watchlist valid).

Platform test count: 447 → 470 (23 new + 2 new skipped = 25 additive).

Documentation:

- `docs/sprints/schema_final_blocks_evaluation.md` — Pass 1 per-block
  registry-source discovery, strict-vs-warn decision matrix, test plan.
- `docs/sprints/schema_final_blocks_research.md` — Pass 2 verification
  of the 7 Pass-1 assumptions (attribution module location, bootcamp
  consumers, top-level key collisions, spec.raw consumers, event-risk
  seed byte-match, file-size budget, test count floor).

Next: Sprint F (ranker port — `compute_all_features` + `rank_universe`
consume spec instead of hardcoded logic).

### Added (Sprint D — multi-target brackets + regime-adaptive sizing schema)

Closes #550 — fourth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates two additive
schema blocks — a list-form `exit.targets[]` alternative to the legacy
singular `exit.target`, and a `position_sizing.method: regime_adaptive`
option alongside the existing `fixed_pct_equity`.

Accepted shapes:

```yaml
exit:
  kind: mechanical
  timeout_days: 21
  stop:
    atr_multiple: 2.0                # required when using targets[]
  targets:                           # list-form; alternative to exit.target
    - name: target_1
      atr_multiple: 1.5
    - name: target_2
      atr_multiple: 3.0

position_sizing:
  method: regime_adaptive
  regimes:
    BULL_LOW_VOL:     {packet_worthy: true,  position_pct: 0.05}
    CRISIS:           {packet_worthy: false, position_pct: 0.0}
```

Validation rules:

- **Brackets XOR.** When `exit.kind == "mechanical"`, exactly one of
  `exit.target` (legacy singular) or `exit.targets` (new plural) is
  required. Both is rejected; neither is rejected. `exit.kind ==
  "python_plugin"` passes through without either (plugin owns brackets).
- **`exit.targets[]` interior.** Non-empty list; each entry has a
  non-empty string `name` (unique across the list) plus a numeric
  `atr_multiple > 0`. Bool values rejected (isinstance-True-is-int trap).
- **`exit.stop.atr_multiple`.** Required when `exit.targets` is used;
  legacy `exit.target` path leaves `exit.stop` uninspected (rich
  `{method, atr_period, multiplier, floor_pct, cap_pct}` shape passes
  through unchanged).
- **`position_sizing.method`.** Restricted to `fixed_pct_equity` or
  `regime_adaptive`. `fixed_pct_equity` interior (`pct`,
  `max_concurrent`) passes through unvalidated.
- **`regime_adaptive.regimes`.** Non-empty dict. Each entry requires
  `packet_worthy: bool` + `position_pct: float` in [0.0, 1.0]. Unknown
  regime keys warn via `logger.warning` but do not reject — the known
  set is the incumbent 7-label `classify_regime`/`REGIME_THRESHOLDS`
  codomain (`BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`,
  `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS`).

**Schema-only sprint — no runtime consumption.** Sprints F (ranker
port) and G (exit/bracket port) consume these blocks. `strategy_spec.py`
grew from 195 → 298 lines (under the 300-line C+D combined budget). New
tests: `tests/platform/specs/test_schema_brackets_sizing.py` (29 tests)
cover every rejection path, unknown-regime-key warn semantics, duplicate
target names, bool/negative/zero `atr_multiple`, and backward compat on
both shipping specs (`lazy_prices_v1` + `post_audit_ruleset_v1`).

**Backward compat.** Zero production YAML changes — both
`src/platform/specs/*.yaml` use the legacy `exit.target` +
`fixed_pct_equity` shapes (2/2 each, grep-verified in Pass 2). Three
test-helper fixtures that used bare `exit: {kind: mechanical}` without
targets were updated to `exit: {kind: python_plugin}` (tests don't
exercise brackets); commented inline.

**Housekeeping.** `config/known_violations.json` grandfathers
`src/platform/signal_eval.py` (450 lines) — grew past the 400-line cap
in Sprint B (#556) but wasn't added to the oversized list at merge;
surfaced by `tests/test_repo_structure.py::test_no_file_over_400_lines`
after pulling main into the sprint branch.

### Added (Sprint C — scoring-DSL schema block)

Closes #549 — third of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494 and B #493 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates an optional
`ranking.bands` block — a declarative scoring DSL that the Sprint F ranker
port will consume in place of the hardcoded bands in
`src/ranking/ranker.py::_score_ticker`.

Accepted shape:

```yaml
ranking:
  bands:
    - metric: pullback_depth_pct   # non-empty str
      range: [-8, -3]              # 2-element numeric list, lower < upper
      score: 25                    # int or float
```

Validation rules:

- `ranking` is an optional top-level key; specs without it load unchanged
  (`lazy_prices_v1` and `post_audit_ruleset_v1` regression-tested).
- `ranking.bands` is optional inside `ranking`; other sub-keys (e.g.
  hypothetical `ranking.weights`) pass through unchecked.
- Each band must provide a non-empty string `metric`, a 2-element numeric
  `range` with `range[0] < range[1]`, and a numeric `score`. Bool values
  are explicitly rejected (Python's `isinstance(True, int)` trap).
- Multiple bands per metric are allowed. Overlapping ranges on the same
  metric emit a `[PLATFORM] ranking.bands overlap: ...` warning via
  `logger.warning` — the spec still validates successfully. `validate_spec`'s
  `(ok, errors)` return signature is preserved; no callers break.

**Schema-only sprint — no runtime consumption.** Sprint F ports the ranker
to consume this block. `strategy_spec.py` grew from 131 → 195 lines (under
the 250-line sprint cap). New tests:
`tests/platform/specs/test_schema_scoring_dsl.py` (23 tests) cover every
rejection path, overlap-warn semantics, backward compat on both shipping
specs, and the `ranking.weights` pass-through case.

### Validated (v0.25.6 — lazy_prices_v1 walk-forward rerun on real EDGAR)

Closes #547. First walk-forward rerun after three upstream capabilities landed
(v0.25.4 VIX enrichment #535, v0.25.4 INCONCLUSIVE_DURATION sub-state #538,
v0.25.5 sections_json parser backfill #537). Spec, seed, and universe
unchanged from the v0.25.3 baseline (`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`).

**Run identity**

- `run_id`: `7a8a96b6-3d3d-4cc3-9e6f-34573547cc72`
- `spec_hash`: `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` (identical to v0.25.3)
- `code_git_sha`: `638ef96912fa6338d88fd380b6d2328377a06d83`
- `random_seed`: `42`
- Exit code: 3 (INCONCLUSIVE)

**Outcome delta (v0.25.3 → v0.25.6)**

| metric | v0.25.3 | v0.25.6 |
|---|---|---|
| outcome_state | INCONCLUSIVE | INCONCLUSIVE |
| Windows (PASS/FAIL/INC_DATA/INC_POWER/INC_DURATION) | 0/0/5/0/— | 0/0/4/0/**1** |
| vix_tier_coverage | 0 | **3** |
| OOS trades with vix_at_entry non-NULL | 0/20 | 21/21 |
| Total OOS trades | 20 | 21 |
| Pooled Sharpe | 3.5280 | 3.8976 |
| Pooled MDE | 10.5448 | 10.2932 |

**Confirmations closed**

- **#535 (VIX enrichment):** `vix_at_entry` populated on 100% of OOS trades
  across 3 tiers (low/medium/high). `lookup_vix_at_entry` wired end-to-end
  via `_build_trade()`. Closes v0.25.3 §Follow-ups #1.
- **#538 (window-duration sub-state):** Window 4 (273 days < 365 threshold)
  correctly flips to `INCONCLUSIVE_DURATION` regardless of trade count.
  Persisted `n_windows_inconclusive_duration = 1`. Closes v0.25.3 §Follow-ups #3.

**Parser backfill impact observation**

v0.25.5's lift from 28% → 71% useful `sections_json` coverage produced **+1
new OOS trade** (PG 2024-08-06 in Window 4). Windows 0-3 trade counts
identical to v0.25.3. Pre-registered rule R3 predicted 2-6× lift; observed
delta is well below that. Candidate reasons (not in scope): #552 fetcher issue
still produces `'{}'` on 1,424 rows; prior-year reference filings pre-2019
are not in the corpus; 8-K filings (69% of the v0.25.5 backlog) don't trigger
`lazy_prices` signals. Captured, not interpreted — the framework reports the
number it got.

**Framework-bug triggers**

Inert. All triggers are PASS-conditional; outcome was INCONCLUSIVE. No
framework-bug issue filed.

**Minor follow-up flagged (not filed)**

`scripts/backtest/run_walkforward.py::main()` JSON summary omits
`n_windows_inconclusive_duration` — the persisted DB row carries it but the
CLI stdout doesn't. One-line fix in the `summary` dict. Not bundled into this
PR per the sprint's anti-goal (no spec/runner modification during validation).

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.6_evaluation.md` (commit `638ef96`)
- Pass 2 raw capture: `docs/sprints/lazy_prices_v1_rerun_raw.md` (commit `2ca4b36`)
- Pass 3 validation: `docs/validation/lazy-prices-v1-walkforward-real-rerun-2026-04-20.md` (this PR)
### Fixed (Sprint B — python_plugin find_candidates_for_date wiring)

Closes #493, #548 — second of 8 prerequisite sprints in the #530 Sprint
chain (Sprint A, #494 scheduled-kind, merged earlier in this chain).

`src/platform/signal_eval.py::find_candidates_for_date` previously raised
`NotImplementedError` for `entry.kind: python_plugin`, blocking any strategy
declaring itself via the `StrategyPlugin` ABC from running through the live
scan pipeline. The new `_find_candidates_python_plugin` branch:

- resolves universe via `_resolve_universe`; applies `spec.universe.sector_filter`
  (identical plumbing to Sprint A's scheduled path);
- applies `entry.event_exclusion.categories` on the as_of date — short-circuits
  BEFORE dispatching to the plugin, so the plugin isn't needlessly invoked on
  excluded days;
- looks up the plugin via `plugin_registry.get_plugin(entry.plugin_ref or spec.strategy_id)`.
  `entry.plugin_ref` is a new **optional** dict key (NO schema change — not
  validated in `strategy_spec.py`); when absent, the plugin key defaults to
  the spec's own `strategy_id`;
- passes `{"db_path": live_db, "strategy_id": spec.strategy_id}` as the plugin
  `context` arg per the existing `StrategyPlugin.find_candidates` signature;
- translates returned `Candidate` dataclass objects into the shadow_harness
  dict shape, augmenting metadata with `strategy_spec_hash`, `trigger`
  (`"python_plugin"`), `signal_direction`, `plugin_ref`. Plugin-supplied
  metadata keys are preserved;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`.

Error handling (no new exception classes per sprint guardrail):

- Missing plugin → `KeyError` with `plugin_ref` + hint to check `@register_plugin`.
- Plugin's `find_candidates` raises → `RuntimeError` wrapping original via
  `raise ... from exc`; plugin name in the message.
- Plugin returns non-list → `TypeError` with the actual type.
- Plugin returns non-`Candidate` items → `TypeError` per-item with the actual
  type. All three are caught by `shadow_harness._find_candidates`' broad
  `except Exception`; tick degrades to 0 candidates.

New tests in `tests/platform/test_signal_eval_python_plugin.py` (13 tests)
cover: dispatch on spec.strategy_id, `entry.plugin_ref` override, missing
plugin / raising plugin / bad return type / wrong item type, dedup, sector
filter narrowing the universe received by the plugin, event_exclusion
short-circuit (plugin NOT called), empty universe short-circuit (plugin NOT
called), plugin context delivery, walk-forward path still raises
`NotImplementedError` (backtest_engine untouched), scheduled + event_driven
branches still dispatch correctly.

`backtest_engine._run_backtest` still raises `NotImplementedError` for
`python_plugin` kind — historical replay for plugin strategies is explicitly
out of this sprint's scope (tracked in the #530 chain). Walk-forward runner,
which routes scheduled/event_driven/python_plugin through `run_backtest`,
is untouched.

`src/platform/signal_eval.py` grew from 399 → 450 lines; at the sprint's
450-line cap.

### Executed (v0.25.5 — sections_json parser backfill for EDGAR)

Closes #537. Runs the existing section parser over the 3,743 `edgar_filings`
rows that had `full_text` populated by the 2026-04-19 fulltext backfill but
`sections_json` still NULL. Pure execution sprint — no parser logic changes,
no schema changes.

**Coverage delta**

- Useful (`sections_json` non-empty): 1,518 / 5,393 = 28.1% → 3,837 / 5,393 = **71.1%**
- Attempted (`sections_json IS NOT NULL`): 28.1% → **97.6%**

Remaining 132 NULL rows are all `full_text IS NULL` (ineligible).

**Execution**

3,743 rows processed in 6.1 s total wall-clock (plan budgeted 2 h). Batch
commits every 100 rows, zero exceptions, zero baseline drift against a
5-row spot-check of pre-parsed rows.

- 2,319 rows produced non-empty `sections_json`
- 1,424 rows produced `'{}'` (mark-attempted semantic — see #552)
- 0 exceptions

**Code changes**

- `_parse_sections` → public `parse_sections` in
  `src/data_collection/edgar_collector.py`. Callsites updated in
  `scripts/backfill_edgar_historical.py` and `tests/test_data_collectors.py`.
  No behavioral change.
- New `scripts/backfill_sections_json.py` (205 lines, all functions ≤ 48 lines,
  well under the 60-line guardrail). Flags: `--dry-run`, `--limit`,
  `--batch-size`, `--db-path`. Built-in `capture_baseline`/`verify_baseline`
  defense-in-depth against WHERE-clause drift.
- Storage semantic: empty parser dict stored as `'{}'` literal JSON, NOT NULL.
  One-way divergence from `edgar_collector.py:351` (inline collector path).
  Chosen for idempotency on re-run and diagnostic value for #552.

**Follow-up filed (#552)**

1,424 of the 3,743 rows (~38%) produced empty `sections_json`. Diagnosed
via spot-inspection: `_lookup_primary_document` is resolving some filings
to iXBRL / SGML submission-header documents instead of the narrative HTML.
Parser correctly returns `{}` on these — no narrative sections exist to
extract. Filed as **#552** for a later sprint; out of scope for v0.25.5.

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.5_evaluation.md` (commit `c495530`)
- Pass 2 research: `docs/sprints/v0.25.5_research.md` (commit `6a8f290`)
- Pass 3 validation: `docs/sprints/v0.25.5_validation.md` (this PR)
### Fixed (Sprint A — scheduled-kind find_candidates_for_date wiring)

Closes #494 — first of 8 prerequisite sprints in the #530 Sprint A chain
unblocking v0.26.0 incumbent YAML extraction (#523).

`src/platform/signal_eval.py::find_candidates_for_date` previously warned
and returned `[]` for `entry.kind: scheduled`, blocking any scheduled
strategy spec from running through the live scan pipeline. The new
`_find_candidates_scheduled` branch:

- resolves the universe via `_resolve_universe` (honors string aliases like
  `"sp100"`, unlike `backtest_engine._run_scheduled` which short-circuits on
  non-list inputs);
- applies `spec.universe.sector_filter` (v0.26.2-scoped) via `SECTOR_MAP`;
- fires when `_matches_scheduled_trigger(as_of, entry)` is True
  (shared with the backtest path — no behavior fork);
- applies `entry.event_exclusion.categories` (v0.26.2-scoped) on the as_of
  date via `is_excluded_event_date`;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`;
- emits one candidate dict per qualifying ticker with
  `metadata.trigger == "scheduled"`.

`entry.signal` is intentionally ignored for the scheduled MVP path —
scheduled specs express timing via `day_of_week` today. A cron/interval DSL
is tracked for a later sprint in the #530 chain.

New tests in `tests/platform/test_signal_eval_scheduled.py` (10 tests)
cover: trigger-match emission on a fixed historical Monday (2023-11-06),
empty-filter path returning full universe, sector_filter + event_exclusion
composition, day_of_week mismatch, dedup against open positions, unknown
operator regression guard (no exception), unknown-kind ValueError, and
walk-forward-path-untouched confirmation. Two stale assertions in
`tests/platform/test_find_candidates.py` (which pinned the previous
warn-and-return-`[]` contract) were updated to the new behavior.

`src/platform/signal_eval.py` grew from 370 → 399 lines; under the sprint's
400-line file-size budget. `backtest_engine._run_scheduled` (walk-forward
path) is untouched — Pass 2 research
`docs/sprints/scheduled_kind_wiring_research.md` §3 confirms the two paths
are independent siblings sharing only the stateless `_matches_scheduled_trigger`
helper.

### Added (v0.25.4 Part A — VIX enrichment in walk-forward trades)

Closes #535 (and the umbrella #542). Plugs the gap diagnosed in
`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md` where 20/20
OOS trades carried `vix_at_entry = NULL` because `BacktestTrade` had no such
field. The runner's `getattr(t, "vix_at_entry", None)` always returned None
and downstream tier bucketing degenerated to `vix_tier_coverage = 0`.

- New module `src/platform/vix_lookup.py` (~70 lines) with single function
  `lookup_vix_at_entry(entry_iso) -> float | None` that delegates to
  `fetch_cached_ohlcv("^VIX", ...)` and returns the most-recent Close on or
  before `entry_iso`. Returns None on cache miss, empty frame, or no eligible
  bar (graceful degradation, never raises).
- Add `vix_at_entry: float | None = None` field to `BacktestTrade` dataclass.
  Defaulted so existing constructors stay backwards-compatible.
- Wire `lookup_vix_at_entry` into `_build_trade()` — single call site reached
  by both `_run_scheduled` and `_run_event_driven` paths.

The runner picks up the new field automatically; `_assign_vix_tier` correctly
buckets into `low` (<15), `medium` (15–25), `high` (>25). Pass 1 source
decision: yfinance `^VIX` over FRED VIXCLS / `vix_term_structure` table /
non-existent `daily_bars` — the only source with full 2019-2024 daily
coverage (verified 12/12 month-starts in Pass 2) plus already wired through
the existing OHLCV cache path.

11 new tests in `tests/platform/rigor/test_vix_enrichment.py` cover helper
behavior + `BacktestTrade` shape + `_build_trade` integration via mocked
OHLCV/VIX path + end-to-end persistence through `walkforward_runner`.

### Added (v0.25.4 Part B — Window-duration surfacing)

Closes #538 (and the umbrella #542). Adds an `INCONCLUSIVE_WINDOW_DURATION`
sub-state so operators can distinguish "strategy didn't signal"
(`INCONCLUSIVE_DATA`) from "the OOS window was too short to deliver
meaningful coverage" (the new sub-state).

- New constant `WINDOW_INCONCLUSIVE_DURATION` in `walkforward_outcome.py`.
- New `n_windows_inconclusive_duration` field on `OutcomeResult` and matching
  `INTEGER DEFAULT 0` column on `walkforward_results`.
- New per-run config knob `min_window_duration_days: int = 365` on
  `WalkForwardConfig` + module-level `MIN_WINDOW_DURATION_DAYS = 365`. Round-
  trips through `as_json_dict()`. Override-able for power-testing or backport.
- `count_power_states` extended with `windows` + `min_window_duration_days`
  kwargs (both default-no-op so legacy callers stay unchanged). Per-window
  precedence: DURATION > DATA > POWER > PASS > FAIL.
- Run-level reducer: `INCONCLUSIVE_WINDOW_DURATION` ≥ inconclusive_window_threshold
  → outcome `INCONCLUSIVE / duration_inconclusive`, prepended ahead of the
  existing `coverage_inconclusive` and `power_inconclusive` checks.
- `cloud_routes/walkforward.py` SELECT extended to surface the new counter
  to API consumers. Dashboard chip surfacing is a follow-up; backwards-compat
  preserved (existing UI ignores the new column).

Pass 1 chose Option 1 (sub-state) over Option 2 (new `walkforward_windows`
table) because: (a) the `walkforward_windows` table doesn't exist — Option 2
would require creating it, vs Option 1's +1 INTEGER column; (b) sub-state
surfaces the distinction in every consumer (validation docs, promotion gate,
JSON outputs) for free; (c) Option 2 would require every consumer to apply
the threshold itself — drift waiting to happen.

Threshold = 365 days. v0.25.3 default windows are four 15-month (~456-day)
windows + one 9-month (273-day) tail window — the threshold cleanly flags
the tail without affecting the standard four. 1 calendar year is the minimum
needed to span ~1 cycle of seasonal effects.

15 new tests in `tests/platform/rigor/test_window_duration.py` cover reducer
+ classifier + config + persistence + a v0.25.3 retrofit asserting the new
sub-state fires on Window 4 while leaving the run-level outcome's
`coverage_inconclusive` reason intact (1 short window < threshold of 2).

### Added (v0.26.2-scoped — Schema extension: sector_filter + event_exclusion)

Closes #539. Two additive optional fields on the strategy spec, both read-only
filters applied at candidate-selection time (pre-ranking). Minimal and
declarative per the v0.26.2-preflight (PR #536) Path B scope.

- **`universe.sector_filter: list[str]`** — if present, filters the candidate
  ticker set to those whose `SECTOR_MAP[ticker]` (GICS name) matches any
  listed value. Applied in `src/platform/signal_eval.py:_query_event_rows`
  between universe resolution and the SQL `IN(...)` clause.
- **`entry.event_exclusion.categories: list[str]`** — if present, skips any
  entry whose resolved entry date (`filing_date + next trading day`) matches
  a v0.25.1 `KNOWN_EVENTS` row whose category is in the listed set.
  Applied in `src/platform/backtest_engine.py:_run_event_driven`.

Both fields are optional and validated in
`src/platform/strategy_spec.py:validate_spec`. Type rules: non-empty
`list[str]`; nested `entry.event_exclusion` must be a dict if present.

Preserves the v0.25.3 framework baseline and does not modify
`lazy_prices_v1.yaml`. Regression test
`test_lazy_prices_still_loads_without_new_fields` confirms.

### Added (v0.26.2-scoped — post_audit_ruleset_v1.yaml)

First non-null `derived_from` strategy on main. `source_type =
forensic_audit_ruleset`, source date range 2026-04-01 → 2026-04-18,
`source_trade_ids` key intentionally omitted per Pass 2 finding (the R8
firewall at `walkforward_firewall.py:129-135` accepts key-absence but
rejects `null`).

- `universe.sector_filter: [Consumer Staples, Utilities, Health Care]`
  (28 tickers, 28% of current S&P 100 by GICS membership)
- `entry.event_exclusion.categories: [Trade Policy]` (excludes entries on
  any of the 9 2019-2024 Trade Policy dates from v0.25.1 backfill)
- Otherwise mirrors `lazy_prices_v1.yaml` — same cosine-similarity signals
  on 10-K/10-Q sections, same ATR-based brackets, same fixed-pct sizing

### Validated (v0.26.2-scoped — Walk-forward run on real EDGAR data)

First walk-forward run of a non-null-`derived_from` spec.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches Pass 1
  hypothesis; trade count collapses to 3 (all Consumer Staples, windows
  0/2/3 one each; windows 1/4 empty).
- **Run:** `run_id=f266e097-0e19-4360-ac4a-ca1c388dda02`,
  `spec_hash=463853b5...`, `code_git_sha=6b887927...`, `seed=42`.
- **Pooled Sharpe:** +1.019 (vs v0.25.3 baseline +3.528)
- **Pooled MDE:** 47.197 (vs 10.545 baseline; ~4.5× scales as 1/√N)
- **Heavy-tail flag:** 0 (N=1 windows degenerate to MDE=inf before the
  bootstrap heuristic activates — correct behavior)
- **R8(a) persisted:** `derived_from_source_type=forensic_audit_ruleset`,
  `derived_from_source_run_id=april-2026-forensic-audit`
- **R8(b):** overlap-assertion trivially cleared (2026-04 vs 2019-2024)
- **Filter bypass trigger (new):** did NOT fire — 3 trades ≤ 20 baseline

**Schema + filters both VALIDATED.** No framework-bug investigation filed.

Per-trade ledger:
- Window 0: PM (Consumer Staples) 2020-02-10, 13d, -5.79% (stop)
- Window 2: COST (Consumer Staples) 2021-10-07, 20d, +12.84% (timeout)
- Window 3: MO (Consumer Staples) 2023-02-28, 17d, -5.00% (stop)

Validation doc:
`docs/validation/post-audit-v1-scoped-walkforward-2026-04-20.md`.
Cycle summary: `docs/validation/v0.26-cycle-summary.md`. Ralph Loop:
`docs/sprints/post_audit_v1_scoped_{evaluation,research}.md`.

**Morning-only filter (the third forensic-audit refinement)** remains
deferred to #540. Pending intraday OHLCV data layer.

**Secondary finding (non-blocking):** `vix_at_entry` / `vix_tier` NULL
on 3/3 OOS trades. Same upstream data-enrichment gap documented in the
v0.25.3 validation doc. Primary `min_trades_per_window=10` gate already
binding.
### Blocked (v0.26.0 — Incumbent YAML extraction)

Closes #523 as **BLOCKED**. See #530 for prerequisite dependency chain.

- **Pass 1 + Pass 2 findings:** 7 of 8 pre-registered blockers hold. Incumbent cannot cleanly extract to YAML without schema extensions + close of #494 + scan pipeline refactor.
- **Deliverable:** `docs/sprints/incumbent_v1_yaml_evaluation.md` (309 lines) + `docs/sprints/incumbent_v1_yaml_research.md` (261 lines).
- **Docs-only ship** per prompt's explicit STOP path.

### Added (v0.26.2-preflight — post-audit ruleset feasibility diagnostic)

Closes #533. Pass 1 only — docs-only sprint, no implementation, no spec,
no schema changes.

- **Outcome: Path B (partial block, scoped sprint).** v0.26.2 does NOT
  inherit the full #530 dependency chain. Walk-forward is insulated
  from the `signal_eval.py:180` `NotImplementedError` (#494 / #530
  Sprint A) because it runs through `backtest_engine._run_scheduled`,
  not the live-flow candidate resolver.
- **Per-filter verdict:** Defensive (hard-filter, disjoint from #530),
  Tariff (schema-only, uses v0.25.1 `is_known_event` substrate),
  Morning-only (deferred to #540 behind intraday OHLCV data layer).
- **R8(a) finding:** `source_trade_ids: null` fails
  `validate_derived_from` at `walkforward_firewall.py:129-135` —
  recommend omitting the key entirely.
- **Deliverable:** `docs/sprints/post_audit_v1_preflight.md` (343 lines).

### Validated (v0.25.3 — Walk-forward framework end-to-end on real EDGAR data)

Closes #532. First real-data run of the walk-forward v1 framework (shipped
in v0.25.0 / PR #520) against `src/platform/specs/lazy_prices_v1.yaml`
using the operator's local EDGAR corpus.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches the Pass 1
  pre-registered hypothesis (NOT PASS expected; forensic audit established
  lazy-prices underpowered at 2019-2024 trade density).
- **Run:** `run_id=88fd926e-1789-46f0-aee4-501addbb7256`,
  `spec_hash=ea78fed3...`, `code_git_sha=0f5e7178...`, `random_seed=42`.
- **Windows:** 5/5 `INCONCLUSIVE_DATA`. 20 OOS trades across 2019-2024
  (4/7/4/4/1 per window). Zero purged, zero embargoed.
- **Heavy-tail override:** fired on 4/5 windows, correctly driving MDE
  values to capture small-N pathology (Window 0: 4-trade, Sharpe −142,
  MDE 8.37e15). Not a bug — truthful reflection of small-N instability.
- **R8(a):** `derived_from: null` correctly propagated through to
  `walkforward_results.derived_from_source_type = NULL`.
- **Framework-bug trigger:** did NOT fire (would have required
  `outcome_state = PASS`).
- **Synthetic vs real comparison:** outcome state, reason, window-state
  distribution, heavy-tail count, and pooled MDE all match the synthetic
  INCONCLUSIVE baseline (`docs/validation/lazy-prices-v1-walkforward-2026-04-19.md`).
- **Validation doc:**
  `docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`
- **Ralph Loop docs:**
  `docs/sprints/lazy_prices_v1_real_evaluation.md` (Pass 1),
  `docs/sprints/lazy_prices_v1_real_raw.md` (Pass 2).

**Secondary finding (non-blocking for this sprint):**
`vix_at_entry` and `vix_tier` are NULL for 20/20 OOS trades, driving
`vix_tier_coverage = 0`. Data-enrichment gap upstream of the framework;
filed as follow-up in the validation doc. Does not affect this run's
INCONCLUSIVE verdict (primary `min_trades_per_window = 10` gate already
binding).

### Changed (v0.25.2 — Roadmap completeness audit)

Closes #526. Additions-only sprint — no new code, `frontend/src/pages/Roadmap.jsx`
data extensions only.

- **New Phase 1 subphase "Parked / deferred"** — 15 items captured that memory
  and open GitHub issues reference but that were missing from the roadmap UI:
  1 surprise-shipped (HSHS dashboard, flipped to `done` with reference to
  `Health.jsx:247-289`) + 14 pending items across issue-referenced tech debt
  (#367 WatchLoop, #432 position-cap consolidation, #451 residual shorts,
  #478 SQLite repository pattern, #479 executor.py mega-functions, #480
  shadow_trading test suite, #491/#492 Tier 7 correlation work, #493/#494
  v0.24.1 wiring gaps, #497 forensic refactor) and memory-only deferred items
  (AI Council 5→7 expansion, Alpaca MCP integration, IB log-only broker).
- **Phase 2 Month 3** — 1 item appended: UPS purchase (CyberPower
  CP1500PFCLCD) — complements the existing Dedicated Arcis machine row that
  only mentions UPS in its specs blurb.
- **Phase 3 new subphase "Second strategy candidate (v0.27.x)"** — 1 item:
  second-strategy candidate spec gated on v0.26 cycle outcome.
- **Phase 5 Fund formation** — 3 items appended: CPCV upgrade, live
  walk-forward (rolling OOS extension), and v1.0.0 release gate
  (fund-formation readiness) with explicit prerequisite list.
- **Skipped** — "Research Analyst setup" per guardrail #3 (don't invent items
  when memory is vague). Roadmap.jsx:161 already explicitly supersedes the
  concept: "Supersedes the stale 'Research Analyst desk (relaxed thresholds)'
  concept — platform evaluates genuinely uncorrelated strategies, not relaxed
  variants of swing."
- **Ralph Loop docs** — `docs/sprints/roadmap_completeness_evaluation.md`
  (Pass 1) + `docs/sprints/roadmap_completeness_research.md` (Pass 2).

Total Roadmap.jsx delta: +20 items across 4 insertion sites (1 new Phase 1
subphase with 15 items, 1 Phase 2 append, 1 new Phase 3 subphase with 1 item,
3 Phase 5 appends). Zero existing items modified. No MASTER.md changes.

### Added (v0.25.1 — known_events 2019-2024 backfill + is_known_event helper)

Load-bearing prerequisite for v0.26.2's post-audit ruleset tariff-exclusion
rule. Before this sprint, `src/diagnostics/known_events.py` only carried
March-April 2026 forward-planning dates, meaning any tariff-exclusion rule
applied to walk-forward v1 OOS windows (2019-01-01 → 2024-09-30 per
`walkforward_config.py` R1) would match zero historical dates and be
effectively a no-op.

- **9 new events** added to `KNOWN_EVENTS` covering the 2019-09-30 →
  2024-09-30 window, each verified against a primary source
  (treasury.gov/OFAC, USTR, White House EO, BIS, DOD, Maersk). See
  `docs/sprints/known_events_and_drift_repair_research.md` §1.1 for
  per-event market-move verdict and source URL.
- **5 new category labels** — `SANCTIONS_INITIAL`, `SANCTIONS_ESCALATION`,
  `EXPORT_CONTROLS`, `INDUSTRIAL_POLICY`, `TRADE_DISRUPTION` — all roll
  up to existing `"Trade Policy"` category for consumer uniformity
  (`src/diagnostics/analyses.py:_match_events` unchanged).
- **`EVENT_METADATA: dict[str, EventMeta]`** — new parallel dict keyed on
  the same dates as `KNOWN_EVENTS`. Carries per-event description,
  affected-sector list (empty = broad-market), primary-source URL, and
  market-impact note. Invariant enforced by test:
  `set(KNOWN_EVENTS) == set(EVENT_METADATA)`.
- **`is_known_event(date_str, category=None)`** helper — returns True
  iff the date is keyed in `KNOWN_EVENTS` and (if category given) the
  category matches. Pure function, no side effects.
- **Backward compatibility** — `KNOWN_EVENTS` and `EVENT_CATEGORIES`
  dict shapes unchanged; existing consumer at `analyses.py:210-213`
  reads the same API.
- **Coverage floor** — regression test requires ≥ 8 events in the
  2019-09-30 → 2024-09-30 window; hard fails if count drops.
- **File size** — `known_events.py` at 327 lines, within the 400-line
  guardrail; no split required.
- **13 new tests** in `tests/diagnostics/test_known_events.py` covering
  schema invariants, category closure, coverage floor, metadata parity,
  primary-source format, helper lookup, and new-label category routing.

### Fixed (v0.25.1 — MASTER.md Section 2 + CLAUDE.md drift repair)

Today's 11-PR session shipped without mid-sprint `MASTER.md` updates;
`scripts/verify_docs.py` was failing with 5/5 warnings. Repaired:

- `Tests` row: 2,141 → 2,507 (+366 tests across platform-foundation/rigor/
  safety/shadow sprints + dashboard v1 + walk-forward v1 + training-data
  audit + hygiene bundle + known_events backfill). Test files: 181 → 227.
- `Python files` row: 214 → 303 (+89 modules across the same sprint
  cluster).
- `Dashboard pages` row: 25 → 28 (Walkforward Results added v0.25.0).
- `Research docs` row: 107 → 92 (-15; doc pruning since last update).
- `Schema tables` row: 61 → 67 registry, 58 synced to Postgres (9
  local-only enumerated in the annotation).
- `Closed trades` row: 85 → 88 (live count per latest shadow-status).
- `GitHub issues` row: 0 → 40 (actual open issue count via `gh issue list`).
- `Training data` row reformatted to concise
  `1,782 examples total; 76 quarantined (75 format_drift + 1 v1_citation);
  1,706 clean corpus` per updated-prompt copy.
- Component rows in §2 updated to match: `Dashboard (Arcis)`
  (26 → 28 pages), `Schema registry` (63 → 67 tables), `Render sync`
  (44/51 → 58/67 tables).
- **Four new Deployed Components rows** added: WalkforwardResults
  dashboard page (v0.25.0), Walk-forward v1 promotion gate (v0.25.0,
  soft migration live), Capability registry + `/api/system/index`
  (v0.25.0), Training audit pipeline + quarantine (v0.26.0 — 1,706
  clean / 76 quarantined).
- `CLAUDE.md` line 14 table count: 64 → 67. Authoritative-count
  one-liner preserved.
- `scripts/verify_docs.py` now exits 0 with 5/5 passes.

**Deferred follow-up:** `frontend/public/architecture.html` (880 lines,
zero `walkforward` references after PR #520) is stale but outside the
`verify_docs.py` check set. Issue to file for a subsequent sprint.

### Changed (v0.25.1 — RELEASES.md session addendum + Roadmap.jsx retroactive updates)

- `RELEASES.md` v1.0.0 criteria table: Phase 1 gate trade count
  `18 trades (36%)` → `88 trades (target reached — validate
  WR/Sharpe/PF/DD next)`. Count only; WR/Sharpe/PF/DD gate metrics
  not yet computed (next validation sprint).
- `RELEASES.md` — added "v0.25.0 Session addendum (2026-04-19)"
  entry documenting PRs #506, #509, #512-#519, #521 with the
  patch-level rationale for each. Not tagged as its own release
  because it's the same opening-bell session as v0.25.0 (walk-forward
  v1 already tagged) and v0.26.0 (training-data audit still
  [Unreleased]).
- `frontend/src/pages/Roadmap.jsx`:
  - `lastUpdated`: 2026-04-17 → 2026-04-19.
  - **Weeks 8-12 subphase:** 4 items flipped `pending` → `done`
    (Earnings 7-day exclusion SD#33, 3-regime classifier v2 SD#35,
    Monthly retraining cadence SD#34, TCA logging SD#38). Each item's
    `d` field updated with shipping evidence.
  - **Strategy Research Platform subphase:** 13 items flipped
    `pending` → `done` (backtest harness, strategy spec YAML + plugin,
    DSR gate, CSCV/PBO + walk-forward, survivorship bias / point-in-time
    universe, Task 0 EDGAR fetch, per-desk Alpaca clients, shadow-trading
    harness, promotion pipeline, correlation monitoring, hard exposure
    limits, defensive dashboard desk filter, Strategy Research dashboard
    page). Lazy Prices strategy flipped `pending` → `in-progress`
    (spec + synthetic smoke done; real-data walk-forward pending).
  - **New subphase `'v0.25.0 — Rigor + hygiene bundle (April 19, 2026)'`**
    with 11 `done` entries (capability registry v1, training-data audit,
    walk-forward framework, command-queue TTL, DB busy_timeout, SQLite
    TEXT coercion, composite PK fix, command-execution hygiene,
    dependency hygiene, GitHub Actions disabled, SD#42 strategy
    evaluation).
- Frontend build verified after edits (`npm run build` ✓ 526ms,
  2,765 modules transformed).

### Chore (v0.25.1 — grandfathered violations from 2026-04-19 merges)

`config/known_violations.json` — added 1 file + 4 functions that
slipped past `test_repo_structure.py` because GitHub Actions was
disabled mid-session. All pre-existing, not caused by this sprint:

- `src/platform/promotion.py` (525 lines) — PR #520 walk-forward
  gate evaluator.
- `src/platform/promotion.py:_evaluate_shadow_trading_gate` (69 lines)
  — same PR.
- `src/platform/rigor/walkforward_runner.py:persist_run_result` (93)
  — PR #520.
- `src/platform/rigor/walkforward_runner.py:run_walkforward` (103) —
  PR #520.
- `src/sync/render_sync.py:run_sync_cycle` (68 lines) — PR #516
  (expire_stale_commands + heartbeat additions).

Follow-up issue to file: "split platform/promotion.py + rigor/
walkforward_runner.py + sync/render_sync.py:run_sync_cycle for a
dedicated cleanup sprint".

### Fixed (v0.25.1 — test_render_sync mock for expire_stale_commands)

`tests/test_render_sync.py::test_healthy_connection_reused_without_reconnect`
patched `pull_commands` but not the new `expire_stale_commands` orphan-
sweep (added in PR #516 same day). The sweep opens its own psycopg2
connection, breaking the test's `connect.call_count == 1` assertion.
Added `patch("src.sync.render_sync.expire_stale_commands", return_value=0)`
to the mock stack. Test-only change; runtime behavior unaffected.

### Changed (2026-04-19 — GitHub Actions disabled)

- Deleted `.github/workflows/ci.yml` and `.github/workflows/daily-repo-audit.yml` to conserve Actions spend until walk-forward validation proves live edge (per April 2026 pivot).
- Added `scripts/run_ci_locally.ps1` — runs the same checks (repo structure guardrails, full pytest with `-x --timeout=60`, test count floor, frontend build, doc drift). Flags: `-SkipFrontend`, `-SkipSlow`.
- Re-enable path: restore workflows from git history after walk-forward v1 real-data run shows excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (SD#25).

### Added (v0.25.0 — Walk-Forward Validation Framework v1)

Load-bearing multi-year infrastructure. Every future strategy must pass
walk-forward v1 before promotion to `shadow_trading` or real capital.
Closes three regime traps identified in the April 18 forensic audit:
regime-averaged false positives, underpowered Sharpe reporting, and
bootcamp-derivation circularity.

- **Three-state outcome framework** (PASS / FAIL / INCONCLUSIVE) — never
  collapsed to boolean anywhere in the stack. Schema enforces
  `outcome_state` NOT NULL; `check_promotion_gate` evidence carries
  `walkforward_outcome_state` + `walkforward_reason` fields end-to-end.
- **R1 — Five non-overlapping OOS windows** 2019-01-01 → 2024-09-30,
  each with a 2-calendar-year IS flank
  (`src/platform/rigor/walkforward_config.py`).
- **R2 — Purge + embargo** (`walkforward_purging.py`) runs at every
  IS/OOS boundary to prevent leakage.
- **R3 — Point-in-time S&P 100 universe** — no survivorship bias.
  `data/reference/sp100_historical.csv` sourced from S&P DJI press
  releases + Wikipedia index-change tables. Resolver in
  `walkforward_universe.py`.
- **R4 — Transaction costs** (0.5 bp per side, 1.0 bp round-trip)
  applied uniformly in `walkforward_costs.py`.
- **R5 — Determinism** via `WalkForwardConfig.random_seed`; spec hash
  + git SHA recorded per run.
- **R6 — MDE gate** using annualized-scale Lo (2002) formula with
  Newey-West N_effective correction; heavy-tail bootstrap SE override
  at `bootstrap_SE > 1.5 × parametric_SE` (10k resamples).
- **R7 — Full reproducibility columns** on every `walkforward_results`
  row: spec_hash, code_git_sha, random_seed, config_json.
- **R8 — Strategy identity firewall** (`walkforward_firewall.py`):
  (a) `derived_from` required field on every spec, (b) overlap
  assertion before any window runs, (c) no inherited credit,
  (d) bootcamp forced False, (e) PR body declaration (honor-system).
  Non-blocking runtime heuristic emits WARNING when spec first-commit
  is within 30 days of a matching forensic audit AND derived_from=null.
- **Schema** — `walkforward_results`, `walkforward_trades`, and
  `sp100_historical_constituents` added to `src/schema/registry.py`.
  Table count 64 → 67.
- **CLI wrapper** `scripts/backtest/run_walkforward.py` — exit codes
  0/1/2/3 map PASS/FAIL/args-error/INCONCLUSIVE so CI can distinguish
  underpowered from failed.
- **Lazy Prices v1** spec updated with `derived_from: null`
  (literature-derived from Cohen-Malloy-Nguyen 2020 JF).
- **Dashboard** `/walkforward-results` React page with three-state
  color coding (PASS green, FAIL red, INCONCLUSIVE amber) +
  INCONCLUSIVE_POWER / INSUFFICIENT_DATA sub-badges +
  per-window/per-trade drill-down.
- **Backend route** `src/api/cloud_routes/walkforward.py` — runs list,
  run detail, window aggregation, trade drill-down.
- **Promotion gate** `check_promotion_gate` — walk-forward v1 takes
  precedence when a row exists; three-state result preserved in
  evidence dict. Soft migration: legacy DSR + PBO + OOS_efficiency path
  still runs when no walkforward_results row exists.
- **Synthetic smoke test** — `scripts/backtest/lazy_prices_smoke_test.py`
  exercises all three outcome paths. Cloud fallback: report marked
  SYNTHETIC FALLBACK when real EDGAR data not accessible. Operator
  re-runs locally after PR review.
- **131 new tests** across 9 new test modules in
  `tests/platform/rigor/`, `tests/scripts/`, `tests/api/`, and
  `tests/platform/test_promotion_walkforward.py`.

### Added (v0.26.0 — Training Data v1-Citation Audit)

- `src/training/audit/` package — three-pass audit for the 1,782-row
  `training_examples` corpus:
  - Pass A (`pass_a_citation.py`) — quarantines rows whose narrative
    cites the v1-buggy outcome and contradicts the v2-corrected
    outcome. Ground truth lives in `attribution_trades`
    (`ranker_only_outcome_v1 != ranker_only_outcome`). Lexicon-based
    win/loss direction classifier with word-boundary regex
    (`successful` fires; `unsuccessful` does not).
  - Pass B (`pass_b_format.py`) — XML tag integrity on `output_text`
    (`<why_now>`, `<analysis>` at 95% prevalence) + plain-text label
    schema on `input_text` (`Ticker:`, `Current Price:`, `Trend State:`
    — all 100% prevalence per commit-12 calibration).
  - Pass C (`pass_c_leakage.py`) — TF-IDF + LogReg probe with
    StratifiedKFold CV + balanced-accuracy scoring on the labeled
    subset (`blinded_win/loss`, `outcome_win/loss`). Masks ticker +
    company names. Report-only; never auto-quarantines in v1.
- `@register_action(name="training_data_audit", ...)` — capability
  registered at import time per Sprint 1B. Appears in
  `/api/system/index` and as a third kickoff button on `/diagnostics`.
- `POST /api/diagnostic-runs/training-audit` + 409 CONFLICT dedup
  (same pattern as regime + forensic).
- `run-training-audit` command dispatched through
  `src/commands/diagnostic_handlers.py` →
  `dashboard_runner.run_diagnostic` →
  `scripts/audits/training_data_v1_audit.py`.
- Frontend: third `<div>` in `DiagnosticKickoffButtons.jsx`
  (grid-cols-3); `DiagnosticRunTable.parseDecision()` recognizes
  `{quarantined_total, total_audited}` summary_json shape.
- Schema: `training_examples.quarantined INTEGER DEFAULT 0` +
  `training_examples.quarantine_reason TEXT` columns (additive via
  registry). `diagnostic_runs.diagnostic_type` description widened
  to `'regime' | 'forensic' | 'training_audit'`.
- Fixed quarantine-reason taxonomy (`src/training/audit/taxonomy.py`):
  `v1_attribution_contradicts_narrative` |
  `format_drift_missing_section` | `format_drift_deprecated_marker` |
  `format_drift_malformed` | `leakage_ngram_suspect`. Free-form
  strings are not accepted (R3).

### Audit results (2026-04-19 production run)

- Total audited: 1,782; quarantined 76 (4.3%); clean corpus 1,706.
- Pass A: 1 quarantine (CSCO, `blinded_win`, narrative cited v1="loss"
  contradicting v2="win"); 7 preserved outcome-neutral.
- Pass B: 75 missing `<why_now>` or `<analysis>` XML tags.
- Pass C: balanced accuracy 0.500, majority baseline 0.721 — NOT
  LEAKING. Probe confirms the narrative does not encode the outcome
  beyond class-imbalance baseline.
- Full report: `docs/audits/training-audit-2026-04-19.md`.

### Tests added (v0.26.0)

- `tests/training/test_pass_a.py` (14 tests)
- `tests/training/test_pass_b.py` (12 tests)
- `tests/training/test_pass_c.py` (7 tests)
- `tests/training/test_audit_integration.py` (12 tests)
- `tests/audits/test_training_audit_cli.py` (6 tests)
- `tests/test_diagnostic_handlers.py` (+3 tests)
- `tests/api/test_diagnostic_routes.py` (+5 tests)
- `tests/test_schema.py` (+2 tests)

### Added (v0.25.0 — Capability Registry, Sprint 1B)

- `src/platform/capability_registry/` — four in-process registries
  (ACTIONS, STATES, SYSTEMS, DECISIONS) populated at import time via
  decorators, mirroring `src/platform/plugin_registry.py:19`. Pydantic
  v2 validation rejects partial metadata at decorator time; deprecated
  entries must specify `deprecated_replacement`. ActionEntry
  input/output schemas validated as Draft-7 JSON Schema (MCP-compatible).
- `GET /api/system/index` + `POST /api/system/index/{name}/mark-reviewed`
  (`src/api/cloud_routes/system_index.py`). State queries and system
  health checks run in a shared ThreadPoolExecutor with a 2s per-call
  timeout. One bad query cannot cascade-break the endpoint (R5).
- `operator_view_state` table (`src/schema/registry.py`) tracks per-
  operator last-viewed baseline + delta for each entry, plus local
  Mark Reviewed override. `sync_to_postgres=False` — local state only
  until v1.1's source-file automation.
- 18 retroactive capability registrations across the platform:
  - Actions: `regime_diagnostic`, `forensic_trade_audit`,
    `strategy_backtest`, `edgar_historical_backfill`
  - States: `shadow_trade_cohort`, `strategy_registry_state`,
    `training_corpus`, `bootcamp_mode`, `alpaca_account`, `ollama_model`
  - Systems: `watch_loop`, `reconcile_trades`, `attribution_resolver`,
    `nightly_audit_agent`
  - Decisions: `bootcamp_still_active`, `pullback_strategy_contaminated`,
    `lazy_prices_deprecated_on_sp100`,
    `no_new_strategy_specs_until_walkforward_ships`
- Dashboard panels: `QuickStatsPanel`, `SystemIndexPanel`,
  `WhatsNewPanel`, `CapabilityDetailModal` (with Mark Reviewed flow).
  Wired into `frontend/src/pages/Dashboard.jsx`; 60s refetch interval.
  No new npm deps.
- CI enforcement: `tests/test_capability_registry_metadata.py` (10
  tests) + `tests/test_capability_registry_integration.py` (5 tests).
  Stale entries (>180d) emit warnings, not failures.
- `jsonschema>=4.0` promoted from transitive to first-class dependency.
- `docs/capability_registry.md` spec + how-to.
- Ralph Loop artifacts: Pass 1 evaluation + Pass 2 research findings
  committed as `docs/sprints/capability_registry_v1_evaluation.md` and
  `docs/sprints/capability_registry_v1_research_findings.md`.

### Tests (Sprint 1B totals)

- 15 schema tests (`tests/platform/test_capability_registry_schemas.py`)
- 14 registry mechanics tests (`tests/platform/test_capability_registry.py`)
- 10 CI metadata tests (`tests/test_capability_registry_metadata.py`)
- 12 API endpoint tests (`tests/api/test_system_index.py`)
- 5 integration tests (`tests/test_capability_registry_integration.py`)
- 56 new tests total, all green.

### Added (v0.25.0 — Diagnostic Dashboard)

- New `/diagnostics` dashboard page with kickoff buttons for regime and forensic diagnostic runs, inline markdown report rendering (react-markdown + remark-gfm), and inline base64 plot display. Polls 5s while active, 30s otherwise.
- `diagnostic_runs` + `diagnostic_run_plots` tables (schema registry `src/schema/registry.py`) — sibling layout with base64-encoded PNGs so plots reach the Render dashboard through existing table-only sync.
- Six new REST endpoints under `/api/diagnostic-runs/*` (cloud): POST regime/forensic (202 with queued run_id), GET list (filterable by type+status), GET single, GET report markdown, GET plots.
- Two new executor handlers in `src/commands/executor.py`: `run-regime-diagnostic`, `run-forensic-audit`. Both delegate to the new `src/diagnostics/dashboard_runner.py` orchestration helper (subprocess, report parse, plot encode, SQLite transaction).
- `src/diagnostics/summary_extractor.py` — regex parser for `## Executive Summary` sections of both report formats, with raw-text fallback when fields can't be extracted.
- Deps: `react-markdown@^9`, `remark-gfm@^4` (operator-approved).
- 26 new tests: 6 summary-extractor, 3 dashboard_runner, 6 handler, 9 API route, 2 end-to-end smoke.

### Refactor (post-Sprint-3 tech debt — closes #471)

- Extract 4 Sprint-2-grandfathered size-guardrail violations into named helpers with zero behavior change:
  - `src/platform/backtest_engine.py` (432 → 396 lines): split `_inject_cosine_scores` into new `src/platform/backtest_attribution.py` module. Pattern mirrors Sprint 1's `signal_eval.py` extraction.
  - `src/platform/promotion.py::check_promotion_gate` (97 → 25 lines): dispatcher delegates to `_evaluate_shadow_trading_gate` / `_evaluate_production_gate` per-target helpers.
  - `src/platform/rigor/walkforward.py::run_walkforward` (83 → 58 lines): extract `_run_one_fold(strategy_spec, fold_spec)` + `_compute_efficiency` helper.
  - `src/platform/features/cosine_similarity.py::_parse_section_from_fulltext` (68 → 32 lines): extract `_is_substantive_match(body)` predicate + `_SECTION_PATTERNS` module-level dict.
- `config/known_violations.json` — 4 entries removed. No new grandfatherings added.

### Added (post-Sprint-3 feature completion — closes #475)

- `backtest_results` schema — 2 new NULL-defaulting columns: `pbo` (Probability of Backtest Overfitting from CSCV) and `oos_efficiency` (walk-forward OOS_SR / IS_SR). Populated by Sprint 4's param-sweep driver (PBO) and by new `--with-walkforward` CLI flag (OOS efficiency).
- `scripts/run_backtest.py --with-walkforward` — invokes `run_walkforward` against the strategy spec + date range and persists `oos_efficiency` to the `backtest_results` row.
- `src/platform/promotion.py::_evaluate_shadow_trading_gate` now enforces the full three-gate check per spec line 1127-1135:
  - DSR ≥ 0.95 (was already live via Task 5-carryover)
  - **PBO ≤ 0.50** (new — fails with clear message if NULL)
  - **OOS_efficiency ≥ 0.30** (new — fails with clear message if NULL)
  Evidence dict now carries all three values; historical gate decisions are fully reproducible from `strategy_promotion_events.gate_result_json`.

### Tests

- 5 new tests in `tests/platform/test_promotion.py` covering each new failure mode (PBO NULL, OOS NULL, PBO over threshold, OOS under threshold) plus the all-pass case.
- `--with-cscv` CLI flag deferred to Sprint 4's param-sweep driver where it semantically belongs (a single-config backtest can't produce meaningful PBO).

### Fixed

- deps: add missing `beautifulsoup4` to `requirements.txt` — `fed_collector` and clean-deploy importability depended on a transitive install; now declared as a first-class dependency. (#455)
- deps: add missing `numpy` and `scipy` to `requirements.txt` — analytics modules (evaluation, features/regime, simulation/monte_carlo) import both but neither was declared; clean deploys crashed on first analytics import. (#460)
- deps: add missing `pyarrow` to `requirements.txt` — `src/simulation/cache.py` uses `pd.read_parquet` / `to_parquet`; pandas requires pyarrow for parquet IO. Simulation cache crashed on clean deploy. (#462)

## v0.24.0 (Strategy Research Platform — Final)

Final release of the Strategy Research Platform (v0.24.0 arc). Merges Sprint 4 continuation: visibility layer + functional signal integration.

### Added
- **`_find_candidates` integration** (highest-value task): `src/platform/signal_eval.py::find_candidates_for_date` — event-driven single-date candidate generation reusing backtest_engine._run_event_driven. ShadowHarness._find_candidates now calls it. Platform is functional — any promoted strategy with event-driven entry can generate real research-desk trades. Dedup against open shadow_trades for the strategy's desk.
- **`/api/platform/*` endpoints** (Task 12b): 5 GET (strategies, detail, backtest-results, backtest-trades, promotion-events) + 3 POST (backtests async kickoff, promotions with 40-char justification + two-step 24h delay for production, demotions with 20-char reason).
- **`/research-platform` dashboard page** (Task 12a): 4 sections — strategy registry table with status badges, expandable detail with YAML spec + backtest history grid + promotion events log, equity curve modal using BacktestEquityChart (Recharts LineChart). Empty state renders cleanly.
- **`PlatformStatusWidget` on home dashboard** (Task 12d): compact status card with strategy counts per state, "ready for approval" nudge, last backtest timestamp. Returns null when no strategies exist.
- **Telegram platform events** (Task 12e): `notify_backtest_complete`, `notify_shadow_gate_ready` (dedup per strategy within 24h), `notify_strategy_promoted`, `notify_strategy_demoted`. All prefixed `[RESEARCH]`. Send failures logged, never raised.
- **Python plugin strategy interface** (Task 2): `src/platform/strategy_plugin.py` (StrategyPlugin ABC + Candidate dataclass) + `src/platform/plugin_registry.py` (register/get/list). Interface-only; plugin execution wiring is v0.24.1.
- **`docs/platform/activation-guide.md`** (Task 13): operator walkthrough from YAML spec to production promotion.

### Deferred to v0.24.1
- **Tier 7 correlation monitoring**: `correlation.py` (Spearman/Pearson/exceedance), `factor_decomp.py` (Carhart 4 + QMJ), `change_detection.py` (PELT), `alerting.py` (tiered). Only relevant once ≥2 concurrent strategies run concurrently. Filed as separate issues.
- **Python plugin execution wiring**: interface defined in v0.24.0 but backtest_engine + shadow_harness python_plugin path is v0.24.1 scope.
- **Historical EDGAR backfill 2019-2023** (issue #469): blocks first Lazy Prices promotion.
- **Scheduled-kind `find_candidates_for_date`**: event-driven path lives; scheduled returns [] with warning.

### Tests
- 22 new tests across Sprint 4 continuation.
- Full suite post-v0.24.0: ~2,141 passed + ~5 skipped + 1 pre-existing failure (`test_open_trades_excluded`).

### Non-negotiable gates — all green
- `_find_candidates` returns non-empty list when signal criteria met (test_find_candidates_returns_nonempty_on_signal_match)
- ShadowHarness.run_one_tick places bracket order via research client on real candidate (test_harness_run_one_tick_places_order_when_candidate_passes_limits)
- POST /api/platform/promotions rejects justification_note < 40 chars (test_promotion_rejects_short_justification)
- POST /api/platform/demotions rejects reason < 20 chars (test_demotion_rejects_short_reason)
- /research-platform renders empty state + populated state cleanly
- npm run build succeeds with no new warnings

## v0.24.0-alpha4 (Sprint 4 Tier 5 — Live Deployment Foundation)

### Added
- **Task 7a** — `src/shadow_trading/alpaca_clients.py`: per-desk `TradingClient` factory via `get_client(desk)`. Cached with double-checked locking. `verify_accounts_distinct()` raises if swing and research resolve to the same Alpaca account_number — catches silent cross-contamination at startup. Config via `desks.{desk}.alpaca_key_env` in `config/settings.example.yaml` (operator populates `settings.local.yaml` with real credentials).
- **Task 7b** — 17 public API functions in `src/shadow_trading/alpaca_adapter.py` accept `desk: str = "swing"` kwarg. `_get_trading_client(desk=...)` and `_get_data_client(desk=...)` dispatch to `alpaca_clients.get_client(desk)` when `desk != "swing"`. `place_live_entry` raises `ValueError` if `desk != "swing"` (live trading is swing-only compliance guardrail).
- **Task 7c (CRITICAL)** — `reconcile_paper_trades(desk=...)` and `reconcile_live_trades(desk=...)` filter `shadow_trades` by desk and route Alpaca queries through the per-desk client. Fixes the silent-404 risk when reconcile polls research positions on the swing Alpaca account. `reconcile_live_trades` raises `ValueError` on research desks.
- **Task 7d** — New `src/shadow_trading/reconcile_dispatch.py` with `reconcile_all_paper_trades()` — single source of truth for the "swing + every active research desk" loop. Used by `overnight.py`, `position_monitor.py`, `watch.py`. Per-desk failure isolation. `cli/commands.py:408` passes `desk="swing"` explicitly.
- **Task 7e** — `src/platform/shadow_harness.py` with `ShadowHarness` class. Per-strategy instance. `__init__` invokes `verify_accounts_distinct`. `run_one_tick(as_of)` does reconcile → candidates → pre-trade-limits → bracket placement → `shadow_trades` write with `desk='research_<strategy_id>'`. `halt()` closes only this strategy's positions. `get_open_positions()` filters by desk. `_find_candidates` is an MVP placeholder (v0.24.1 follow-up).
- **Task 7f** — `ShadowHarness._is_within_hard_limits` delegates to Sprint 3's `check_pre_trade_limits`. NAV from research Alpaca (fallback $100K). Positions desk-filtered. Blocked candidates skip `place_bracket_order`.
- **Task 9** — `WatchLoop._run_platform_shadow_tick` dispatches every strategy in `shadow_trading` state on its own `shadow_cadence_seconds` (default 600s). Interval-gating pattern (not inline). Failure isolation — one strategy's crash does not kill swing. `_last_platform_tick` dict in `__init__`; cleared on `_reset_daily_state`. Outer loop calls `_safe_run("platform shadow tick", ...)` once per cycle.
- **Task CC** — `src/platform/cost_calibration.py` with `calibrate_from_swing_history()`. Computes median `entry_slippage_bps` / `exit_slippage_bps` from closed swing trades. Falls back to hardcoded 3 bps when sample < 10. Non-negotiable gate: calibrated value within 30% of the hardcoded default.

### Tests
- 35 new tests across 7 test files. Non-negotiable gates all pass:
  - `test_harness_reconcile_uses_research_client`
  - `test_harness_bracket_monitor_uses_research_client`
  - `test_verify_accounts_distinct_raises_on_same_account`
  - `test_harness_halt_closes_only_this_strategy_positions`
- Full suite post-Sprint-4-Tier-5: ~2,095 passed + ~4 skipped. Pre-existing failures unchanged.

### Platform stays inert at merge
- Zero strategies in `shadow_trading` state at merge time. No live behavior change until the operator promotes a strategy.
- `SELECT COUNT(*) FROM shadow_trades WHERE desk != 'swing'` returns 0 before and after merge.
- `_find_candidates` stub logs `[HARNESS <id>] _find_candidates: returning []` — platform is correctly inert.

### Deferred to `v0.24.0-alpha5` / `v0.24.1`
- Tier 6 (dashboard `/research-platform` page, action buttons, PlatformStatusWidget, Telegram events) — visibility layer; not load-bearing
- Tier 7 (correlation measurement, Carhart+QMJ factor decomp, PELT change detection, tiered alerting) — only relevant once ≥2 research strategies run concurrently
- Tier 8 (Python plugin strategy interface, final docs sweep + activation-guide.md) — CUT-CANDIDATE per spec
- `_find_candidates` full integration (expose `signal_eval.find_candidates_for_date`) — required before any real shadow trades can be placed

### Operator prerequisites before activating any research strategy
1. Create a SECOND Alpaca paper account with distinct credentials
2. Export `ALPACA_RESEARCH_API_KEY` / `ALPACA_RESEARCH_API_SECRET` in the NSSM service env (via `nssm set ArcisWatchLoop AppEnvironmentExtra ALPACA_RESEARCH_API_KEY=... ALPACA_RESEARCH_API_SECRET=...`)
3. Flip `desks.research.enabled: true` in `config/settings.local.yaml`
4. Restart watch loop → `verify_accounts_distinct()` runs at first ShadowHarness init and fails-fast if mis-configured
5. Wait for `_find_candidates` full integration in v0.24.1 before promoting any strategy to `shadow_trading`

## v0.24.0-alpha3 (Sprint 3 of 4 — Defensive Dashboard + Hard Exposure Limits)

### Added
- **Task 12c — Defensive desk filtering.** `/api/shadow/*` endpoints (`open`, `closed`, `sharpe-attribution`, `metrics`, `account`) accept optional `?desk=` query param: absent/`swing` → swing-only (backward compat), `all` → aggregate, `research_*` → SQL LIKE wildcard, exact match otherwise. `Dashboard.jsx` gets a desk-filter dropdown populated at render time from the new `GET /api/shadow/desks` endpoint (returns distinct desks currently in `shadow_trades`).
- **Task 11b.1 — Correlation schema.** Two new tables registered: `correlation_matrices` (long-form daily Spearman/Pearson/neg_exceedance snapshots) and `factor_loadings` (rolling Carhart 4 + QMJ regression outputs). Both `sync_to_postgres=True`, `sync_mode='incremental'`. No writes this sprint — Sprint 4 correlation monitor populates.
- **Task 11b.4 — Hard exposure limits.** New `src/platform/risk/exposure_limits.py` with `check_pre_trade_limits(ticker, shares, price, positions, nav, db_path) -> (allowed, reason)`. HARD_LIMITS: 6% single-name / 25% sector / 1.5× gross / 8% book drawdown circuit breaker. Book drawdown computed live from `shadow_trades` cumulative pnl_pct — no persistent breach flag needed; "no auto-reset" enforced by the math itself. SOFT_LIMITS stubbed for Sprint 4 (correlation + factor + vol ratio). `get_soft_limit_breaches()` returns empty until Sprint 4 wires correlation data.

### Tests
- 37 new tests across `tests/platform/risk/test_exposure_limits.py` (13), `tests/test_correlation_schema.py` (9), `tests/test_shadow_desk_filter.py` (15). Non-negotiable gates all pass: single-name / sector / drawdown blocks, 4 desk-param semantics on `/api/shadow/sharpe-attribution`, correlation tables sync-to-postgres incremental.

### Notes
- `check_pre_trade_limits` is NOT yet wired into `src/shadow_trading/executor.py` — that's Sprint 4 (per spec line 230). This sprint ships the pure function + tests; integration path follows.
- Sector-concentration test uses NVDA instead of GOOGL because Alphabet was reclassified from Technology to Communication Services in GICS September 2018.
- Two post-sprint follow-ups tracked as GitHub issues: #475 (wire PBO + OOS_efficiency into `check_promotion_gate` evidence) and the existing #471 (v0.24.2 refactor sprint for 4 grandfathered violations).

## v0.24.0-alpha2 (Sprint 2 of 4 — CSCV + Walk-Forward + Promotion Pipeline)

### Added
- `src/platform/rigor/cscv.py` — Combinatorially Symmetric Cross-Validation / Probability of Backtest Overfitting (S=16 default; Bailey-Borwein-López de Prado-Zhu 2014).
- `src/platform/rigor/walkforward.py` — rolling walk-forward (Pardo 2008; default 3y train / 1y test; OOS_efficiency = OOS_SR / IS_SR; flags overfit if < 0.30).
- `src/platform/rigor/trials.py` — global trials registry with N_eff counter + empirical V[SR] estimator (fallback to 0.02/250 when <20 trials).
- `src/platform/promotion.py` — 5-state lifecycle (proposed → backtested → shadow_trading → production, plus deprecated) with DSR + PBO + OOS_efficiency gates, promote/demote/pause, ≥40-char justification enforcement on manual promotions, ≥20-char reason enforcement on demotion.
- Three new SQLite tables: `strategy_registry`, `strategy_promotion_events`, `trials_registry`.
- Three new `shadow_trades` columns: `desk` (default 'swing'), `research_thesis`, `strategy_spec_hash` + `idx_shadow_trades_desk` index. Migration backfills all 85 existing rows to `desk='swing'` via DEFAULT.

### Fixed (v0.24.0-alpha2.1 hotfix — commits 6055952 + bbf0a71 + 86a46fc)
- `src/platform/signal_eval.py` — `_query_event_rows` rejected the spec's `universe.tickers: "sp100"` string alias; `_resolve_universe` now dispatches string aliases via `_UNIVERSE_ALIASES`. Fixes Lazy Prices returning 0 trades on the production DB (H2).
- `src/platform/features/cosine_similarity.py` — `cosine_similarity_yoy` now falls back to parsing sections from `full_text` when `sections_json` is NULL (the EDGAR backfill populated `full_text` but never derived sections). Fixes cosine=None for every event (H1).
- `src/platform/signal_eval.py` — `_evaluate_event_signal` was hardcoded to AND logic; now honors `combinator` parameter so `combinator: any` fires on OR logic as spec declares. Fixes SBUX-style suppression when one-of-two filters passes (H4).
- `src/config/__init__.py` — DB_PATH was relative (`"ai_research_desk.sqlite3"`); now anchored to `Path(__file__).resolve().parent.parent.parent / "ai_research_desk.sqlite3"` with optional `ARCIS_DB_PATH` env override. Prevents CWD-dependent DB resolution that masked the H1/H2/H4 bugs during Sprint 1 review.
- `src/platform/promotion.py::check_promotion_gate` — now reads real N_eff + V from `trials_registry` rather than the stored (null-fallback-computed) `deflated_sharpe` column. Adds `RuntimeError` guard if V is None so null fallback can't silently fire in production.

### Tests
- 55+ new tests across `tests/platform/rigor/` + `tests/platform/` + `tests/test_schema_desk_columns.py` + `tests/test_config_db_path.py`. Non-negotiable gates pass: PBO rejects overfit (PBO>0.8), PBO accepts stable (<0.2), walk-forward OOS efficiency computed + flags overfit, shadow_trades 85-row backfill, justification-note enforcement, trials_sr_variance plumbing (no null fallback), trials_registry counts every backtest.

### Known issues
- EDGAR data is 2024-only (collector wired late 2025). Lazy Prices e2e test pins on `n_trades >= 1` rather than `>= 50`. Historical 2019-2023 backfill tracked in GitHub issue #469 (v0.24.x; blocks first Lazy Prices promotion to shadow_trading but non-blocking for Sprints 3/4).
- DSR paper-example test split into two V-values (V=0.5/250 for DSR=0.9004, V=0.046/250 for SR*₀_ann=0.5429) because the paper's two claimed outputs are mutually inconsistent under any single V (documented in `src/platform/rigor/dsr.py` docstring; source PDF password-protected — v0.25 followup).

## [Unreleased] → v0.24.0-alpha1 (Sprint 1 of 4 — Platform Foundation + DSR Gate)

### Added

- `src/platform/` package: strategy spec loader (Task 1), OHLCV data adapter (Task 3), basic metrics + survivorship haircut (Task 5a), Deflated Sharpe Ratio (Task 5b), strategy-agnostic backtest engine + signal_eval (Task 4), backtest CLI + SQLite persistence (Task 6), Lazy Prices feature providers (Task 11).
- First YAML strategy spec: `lazy_prices_v1` (Cohen-Malloy-Nguyen 2020) at `src/platform/specs/lazy_prices_v1.yaml`.
- Two new SQLite tables via schema registry: `backtest_results`, `backtest_trades` (registry now at 56 tables total).
- `scripts/run_backtest.py` CLI runner — invocable as `python scripts/run_backtest.py --strategy lazy_prices_v1 --start YYYY-MM-DD --end YYYY-MM-DD --output-format pretty`.
- `scripts/backfill_edgar_fulltext.py` backfill script (operator runs ~20-37 min SEC fetch; do not automate).

### Fixed

- `src/data_collection/edgar_collector.py::_fetch_filing_text` — corrected URL base to `www.sec.gov/Archives/...` (was `data.sec.gov/Archives/...` which 404s), replaced directory-scraping regex with submissions-API `primaryDocument` lookup. Root cause of 0/3362 EDGAR coverage (Task 0).

### Tests

- 44 new tests across 7 new test files (`test_dsr.py`, `test_backtest_engine.py`, `test_backtest_persistence.py`, `test_data_loader.py`, `test_lazy_prices.py`, `test_metrics.py`, `test_strategy_spec.py`). DSR paper-example reproduction gate PASSES. Two hand-computed backtest validation tests PASS (scheduled + event-driven modes).

### Notes

- `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf` is password-protected; the DSR paper example was split into two independent assertions (one using V=0.5/250 for DSR=0.9004; one using V=0.046/250 for SR*_0_ann=0.5429) because the paper's stated outputs are mutually inconsistent under any single V. See `src/platform/rigor/dsr.py` module docstring and Plan Issue B.
- `src/data_collection/edgar_collector.py` now 413 lines (exceeded 400-line guardrail; Task 0 repair added ~27 lines). `_fetch_filing_text` is 68 lines (exceeded 60-line cap). Both are NEW violations introduced by Sprint 1 Task 0 — grandfathering or a follow-up split is needed before merging to main.

## [v0.23.4] - 2026-04-16 — Telegram Refresh: richer trade pings + periodic stats pulses

Long overdue operator-experience pass on the notification layer. The
`notify_trade_opened` / `notify_trade_closed` pings now carry sector,
regime, VIX, conviction, R:R, MFE/MAE, excess vs SPY, and slippage —
everything an operator needs to evaluate a fill without opening the
dashboard. Three new stats pulses (7:45, 12:00, 16:05 ET) give
trade-count + win rate + PnL + excess-Sharpe across today / 7d / 30d /
all-time, so performance is visible throughout the day. Coverage gaps
from today's new work (1-min bar collection, attribution resolver,
stress test) are filled with dedicated notifications.

### Added

- **`notify_trading_stats_update(stats, label)`** — formatted 4-window
  summary sent 3× per weekday (pre-market, midday, post-close). Silent
  on empty DB.
- **`src/journal/stats.py`** — `compute_window_stats` / `compute_all_window_stats`
  helpers that aggregate closed `shadow_trades` (excluding open +
  quarantined) across `today` / `7d` / `30d` / `all_time`. Excess-Sharpe
  shown only once ≥10 closed trades in a window.
- **`notify_1min_bar_collection`** — nightly confirmation from the
  Phase B overnight handler (bars, tickers, empty %, storage MB).
- **`notify_attribution_resolve_complete`** — resolved count + pending
  remaining, posted after the 4:30 PM ET resolver job.
- **`notify_stress_test_complete`** — scenario pass/fail summary, posted
  after the model-version-triggered 7 PM re-run.
- **`maybe_stats_pulse`** — new DAYTIME handler registered via
  `_register_default_handlers` alongside the 14 overnight handlers. Three
  done-flags (`_stats_{premarket,midday,postclose}_done`) reset daily.

### Changed

- **`notify_trade_opened`** — extended with optional `sector`,
  `regime_at_entry`, `vix_at_entry`, `concurrent_positions`,
  `llm_conviction` kwargs. Existing callers unchanged (all kwargs
  default to None; rendering is graceful when fields missing).
  `scan_service.py` caller now passes the enriched fields it already
  has from the feature row + current open-position count.
- **`notify_trade_closed`** — extended with optional `sector`, regime
  transition, `mfe_pct`, `mae_pct`, `excess_return`,
  `spy_return_over_hold`, `drawdown_from_mfe`, `entry_slippage_bps`,
  `exit_slippage_bps`. `executor.py` caller passes the full
  `shadow_trades` row so all fields render. Extracted
  `_format_closed_extras` helper to keep `notify_trade_closed`
  under the 60-line cap.
- **`src/scheduler/watch_handlers.py`** — added `DAYTIME_HANDLERS` list
  + `ALL_HANDLERS = OVERNIGHT_HANDLERS + DAYTIME_HANDLERS`.
  `_register_default_handlers` now registers all 15.
- **`src/scheduler/overnight.py`** — `run_1min_bar_collection` fires
  the new notification; new `run_attribution_resolution_and_notify`
  wrapper calls the resolver + posts the summary. `run_stress_test`
  now posts the pass/fail summary at the end.
- **`src/scheduler/watch.py`** — attribution-resolve branch delegates
  to `run_attribution_resolution_and_notify`; new stats-pulse done-flags
  initialized in `__init__` and reset in `_reset_daily_state`.

### Added (tests)

- **`tests/test_journal_stats.py`** — 9 tests covering empty DB,
  open-trade exclusion, quarantined exclusion, window boundaries
  (today / 7d / 30d / all_time), win rate math, excess-Sharpe minimum
  threshold, NULL excess_return handling, + 2 smoke tests for the
  notification formatter.
- **`tests/test_watch_handlers.py`** +6 `maybe_stats_pulse` tests: skip
  on weekend, fire at 7:45 / 12:00 / 16:05, idempotent per window,
  no-op between windows.

### Verified

- 85 tests pass across the relevant suites (registry, handlers, bootstrap,
  resilience, import, journal stats, repo structure).
- Frontend builds clean.
- `notify_trade_closed` now 37 lines — helper extraction brings it well
  under the 60-line cap.

## [v0.23.3] - 2026-04-16 — Hotfix: resolve_pending_outcomes future-window filter

Fourth bug from the Task 1 operational sweep — the `reresolve_attribution.py`
hotfix correctly skipped future-window rows during the *reset* step, but
the downstream `resolve_pending_outcomes()` function itself had no date
filter, so it still picked up every `pending` row including those whose
7-day outcome window is in the future. Each one caused a noisy
`YFPricesMissingError` in the logs and wasted ~0.5s on a dead yfinance call.

Observed on 2026-04-16 running `scripts/reresolve_attribution.py`: 180
fresh `pending` rows from today generated ~180 sequential yfinance error
logs. No data corruption — rows stay `pending` — but the watch loop's
nightly 4:30 PM ET resolution job would have reproduced the same error
storm indefinitely until all rows aged past their 8-day window.

### Fixed

- **`src/attribution/logger.py::resolve_pending_outcomes`** — added
  `AND DATE(scan_timestamp, '+8 days') <= DATE('now')` to the SELECT so
  rows whose outcome window is still in the future are skipped. Matches
  the same filter already present in `scripts/reresolve_attribution.py`.

### Added

- **`tests/attribution/test_resolver.py::test_resolve_pending_outcomes_skips_future_window_rows`**
  — regression test seeding 3 rows (old-resolvable / fresh-future /
  boundary-edge at exactly 8 days ago) and asserting the SELECT filter
  passes only the 2 elapsed-window rows to `_resolve_one_row`. Uses
  `patch()` on `_resolve_one_row` so no yfinance calls are made — the
  test isolates the SELECT filter contract.

### Authority

Error storm observed live during the `scripts/reresolve_attribution.py`
run on 2026-04-16; root-caused as a 4th operational bug that slipped
past the Task 1 audit.

## [v0.23.2] - 2026-04-16 — Asyncio Refactor Phase B (overnight extraction) + Phase C (tests)

First wave of `_run_sync_body` decomposition: the 14 overnight-schedule
tasks now live in a new module and run via the handler dispatch path.
Zero behavior change — done-flag semantics preserved, handler firing
times match the pre-refactor `elif` chain. `_run_sync_body` shrank from
740 → 631 lines; watch.py dropped from 2,041 → 1,941 lines (below the
pre-refactor baseline of 2,039).

### Added

- **`src/scheduler/watch_handlers.py`** (229 lines) — 14 module-level
  `maybe_<name>(watch, now)` handlers extracted from the
  `elif self.overnight and not self._is_market_open(now):` branch of
  `_run_sync_body`. Each checks its time window + done-flag and calls
  `watch._safe_run(...)`. `OVERNIGHT_HANDLERS` list exports them in
  registration order.
- **`HandlerRegistryMixin._dispatch_sync`** — sync-context dispatch so
  the `_run_sync_body` worker thread can fire handlers without crossing
  event-loop boundaries. Coroutine handlers get wrapped in `asyncio.run`;
  sync handlers run inline. Same exception contract as `_dispatch`.
- **`WatchLoop._register_default_handlers`** — single entry point called
  once at startup (between `_check_row_counts()` and the IB cold-storage
  banner) that `functools.partial(handler, self)`-binds each handler in
  `OVERNIGHT_HANDLERS` and registers on `on_tick`.
- **`tests/test_watch_handlers.py`** (25 tests) — per-handler unit tests
  (time window, done-flag respect, weekday gating, chained calls) plus
  integration tests: `_register_default_handlers` binds all 14 in the
  correct order, `_dispatch_sync` fires each handler at the right tick,
  and double-dispatch at the same tick is idempotent.
- **`tests/test_watch_handler_registry.py`** gains 4 `_dispatch_sync`
  tests (sync-handler inline execution, async-handler asyncio.run wrap,
  exception swallowing, registration-order preservation).

### Changed

- **`src/scheduler/watch.py::_run_sync_body`** now calls
  `self._dispatch_sync("on_tick", now)` once per tick, right after the
  midnight daily-state reset. The entire `elif self.overnight and not
  self._is_market_open(now):` branch (lines 1502-1627, 116 lines) is
  removed — its work is now done by the 14 registered handlers. The
  "overnight mode" heartbeat log line is omitted (the watchdog file
  heartbeat already covers the liveness signal).
- **`config/known_violations.json`** — `_run_sync_body` grandfather
  entry updated from 740 → 631 lines to reflect the size reduction.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged.
- 16 handler-registry tests pass (12 Phase A + 4 new `_dispatch_sync`).
- 25 watch_handlers tests pass.
- 15 `test_repo_structure` tests pass.
- Frontend builds clean in 603ms.
- `WatchLoop(...).run()` signature preserved — NSSM / `src/cli/commands.py`
  callers unchanged.

### Not in this branch (queued for follow-up Phase B-continuation)

~20 remaining inline blocks in `_run_sync_body` — market-hours scans
(Tier 1-4), EOD recap cluster, digest schedule (4 windows),
Ollama/council/fundamentals, Saturday/Sunday reports, IB health
check, Telegram polling, earnings warning, action reminders. The
pattern is proven; extracting them is mechanical.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md` Phase B (14 of 30+
extractions) + Phase C (mock-clock integration test for the extracted
subset).

## [v0.23.1] - 2026-04-16 — Asyncio Handler Refactor Phase A

Structural refactor of `src/scheduler/watch.py` — introduces an asyncio
event loop + handler registry without changing any observable behavior.
Foundation for Phase 6 intraday streaming (TradingStream, StockDataStream).

### Added

- **`src/scheduler/handler_registry.py`** (new, 69 lines) — `HandlerRegistryMixin`
  providing `run()` / `run_async()` / `on(event)` / `_dispatch(event, ...)`.
  Sync handlers are wrapped in `asyncio.to_thread` so they never block
  the event loop; coroutine handlers are awaited directly. Handler
  exceptions are logged and swallowed to match the `_safe_run` contract.
- **`tests/test_watch_handler_registry.py`** (new, 12 tests) — unit
  coverage for the registry: empty-start, decorator/direct-call
  registration, registration-order preservation, sync + async handler
  dispatch, exception isolation, unknown-event no-op, args/kwargs
  passthrough, `run()`→`run_async()`→`_run_sync_body()` delegation.
- **`docs/research/async-watch-loop-handler-pattern.md`** — handler
  pattern documentation as a public API for future developers, with
  canonical event names (`on_tick`, `on_fill`, `on_minute_bar`, etc.)
  and the Phase B / C / Phase 6 roadmap.

### Changed

- **`src/scheduler/watch.py::WatchLoop`** now inherits
  `HandlerRegistryMixin`. The pre-refactor `run()` method is renamed to
  `_run_sync_body()` and unchanged — Phase B will carve its 740 lines
  of time-window `if/elif` blocks into `_maybe_*` handlers registered
  on `on_tick`. Net +2 lines on `watch.py` (2,039 → 2,041) — the
  mixin keeps infrastructure out of the already-bloated host file.
- **`config/known_violations.json`** — grandfather entry updated from
  `run` (454 lines) to `_run_sync_body` (740 lines) to reflect the
  rename. Pre-existing debt carried forward, not worsened.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged (zero behavior
  change).
- 12 new registry tests pass.
- 15 `test_repo_structure.py` tests pass (docstring, importability,
  60-line cap, 400-line cap, no-legacy-alpaca-SDK).
- NSSM / `src/cli/commands.py` callers unchanged — `WatchLoop(...).run()`
  signature preserved.

### Not in this sprint (explicit out-of-scope per spec)

- Phase B — extracting the 30+ time-window blocks from `_run_sync_body`
  into `_maybe_*` handlers registered on `on_tick`. Queued as
  `refactor/asyncio-phase-b-handler-extraction`.
- Phase C — mock-clock integration test that advances a WatchLoop
  through 24h and asserts every existing task fires at the right ET
  time. Queued as `refactor/asyncio-phase-c-mock-clock-integration`.
- Converting existing `_run_*` methods to `async def`. They stay sync,
  wrapped via `asyncio.to_thread` at dispatch time.
- Any streaming subscription (`TradingStream`, `StockDataStream`) —
  that is Phase 6.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md`, drafted on
`docs/asyncio-refactor-spec` branch. This sprint executes Task 1 of
the spec's 5-task plan; Tasks 2-5 (extraction, dispatch switch, mock-clock
tests, docs) are follow-up branches.

## [v0.23.0] - 2026-04-16 — 1-Minute Bar Collection (Phase 6 Foundation)

Lays the data foundation for Phase 6 intraday-desk feasibility work per
`docs/research/deep-research/intraday-desk-feasibility-prompt.md`.
yfinance only exposes ~7 trading days of 1-minute history, so we begin
storing bars now to study historical microstructure when the time comes.

### Added

- **`minute_bars` table** (schema registry) — composite PK `(ticker, timestamp)`;
  OHLCV (REAL) + volume/trade_count (INTEGER); synced to Postgres
  incrementally via `sync_time_column="timestamp"`. ~2.3 MB/day / ~600 MB/yr.
- **`scripts/collect_1min_bars.py`** — yfinance-backed nightly collector
  for S&P 100. Rate-limited at 0.3s/ticker (≈31s wall time). CLI flags:
  `--date YYYY-MM-DD`, `--days N` (backfill up to 7d), `--dry-run`.
  Idempotent via `INSERT OR REPLACE` on the composite PK. Flattens
  yfinance MultiIndex columns (same fix pattern as SD#41 D2) and coerces
  NaN prices/volumes to NULL.
- **Overnight schedule wire-up** (`src/scheduler/watch.py`) — new
  `_1min_bar_collection_done` flag, reset daily, fires at hour 23 minute
  ≥30 ET (after enrichment precache, before the midnight flag reset).
  7-days/week like the other network-only collectors; empty weekend
  responses handled gracefully.
- **`tests/test_collect_1min_bars.py`** — 8 tests covering schema
  registration, MultiIndex flatten, NaN coercion, empty-response path,
  idempotent upsert, dry-run semantics, rate-limiting, and the
  previous-trading-day walker.

### Changed

- **`src/sync/render_sync.py`** — added `open`, `high`, `low`, `close`
  to `_REAL_COLUMNS` and `volume`, `trade_count` to `_INTEGER_COLUMNS`
  so `minute_bars` rows coerce cleanly on the Postgres side.

### Authority

Phase 1 decision #3 of `docs/research/deep-research/intraday-desk-feasibility-report.md` — begin storing 1-min bars now.

## [v0.22.1] - 2026-04-16 — alpaca-py Canonicalization (audit + guardrail)

Verification sprint — the `alpaca-py` migration was already complete; this
sprint documents the audit, tightens the version pin, and adds a CI
guardrail to prevent accidental reintroduction of the deprecated
`alpaca_trade_api` SDK. No runtime behavior changes.

### Changed

- **`requirements.txt`** — floor raised `alpaca-py>=0.30` → `alpaca-py>=0.43`
  to match the locally-installed/tested version and narrow the window
  for CI/dev drift.

### Added

- **`tests/test_repo_structure.py::test_no_legacy_alpaca_trade_api_imports`**
  — AST-walking guardrail over `src/` and `tests/` that fails if any
  `import alpaca_trade_api` or `from alpaca_trade_api ...` appears.
- **`docs/research/alpaca-py-current-best-practices-audit.md`** — per-call-site
  audit of `alpaca_adapter.py` (10 imports) and `executor.py` (3 imports)
  against the modern SDK idioms. Verdict: zero bugs; two improvements
  flagged as follow-up tickets (typed `APIError` handling, `client_order_id`
  for idempotency).
- **`docs/research/alpaca-py-intraday-streaming-gap.md`** — Phase 6 pre-work
  mapping `TradingStream` / `StockDataStream` integration points into the
  post-asyncio-refactor watch loop. No code; reference doc for the
  Phase 6 sprint.

### Verified

- Zero `alpaca_trade_api` references across `src/`, `tests/`, and all
  `requirements*.txt`.
- Zero streaming usage (`TradingStream` / `StockDataStream`) in `src/`
  — Phase 6 surface is intentionally empty.
- Installed `alpaca.__version__ == 0.43.2`.

### Authority

`docs/sprints/sprint-alpaca-py-migration.md`, drafted on the
`docs/alpaca-py-migration-spec` branch.

## [v0.22.0] - 2026-04-16 — Attribution Resolver MultiIndex Fix + Doc Sweep (SD#41 REVISED / D2 follow-up)

Ships the D2 follow-up fix (yfinance MultiIndex bug that corrupted 1,600
attribution resolutions) plus a comprehensive documentation sweep to
reflect the 4 merges from 2026-04-16 (v0.18.0 IB cold storage, v0.19.0
SPY excess instrumentation, v0.20.0 regime/sector diagnostic, v0.21.0
earnings filter hard block).

### Fixed — Part 1: Attribution resolver

- **`src/attribution/logger.py::resolve_pending_outcomes`** — flatten
  yfinance MultiIndex columns before building the OHLCV dict list.
  Before: `bar.get("Low", ...)` missed the tuple-keyed column, returned
  default `0`, and tripped the stop-first branch on day 1 of every
  resolution. After: `data.columns = data.columns.get_level_values(0)`
  normalizes to string keys so `bar.get("Low")` resolves correctly.
  `simulate_mechanical_outcome` itself is unchanged (kept pure-logic).

### Added — Part 1

- **3 new columns on `attribution_trades`:**
  - `resolution_version` (TEXT, indexed) — version tag for resolution
    logic. `'v1_multiindex_bug'` marks the buggy pre-fix rows;
    `'v2_fixed'` marks post-fix re-resolutions.
  - `ranker_only_outcome_v1` (TEXT) — archive of pre-fix outcome.
  - `ranker_only_pnl_pct_v1` (TEXT) — archive of pre-fix pnl_pct.
- **`scripts/reresolve_attribution.py`** — idempotent re-resolution
  script. Snapshots v1 values, resets bug-tagged rows to 'pending',
  calls the fixed resolver, tags newly-resolved rows as 'v2_fixed'.
  `--dry-run` flag snapshots only (no writes beyond the archive).
- **`tests/attribution/test_resolver.py`** — 6 regression tests covering
  the simulator (flat columns, timeout, loss) and the resolver
  data-shape contract (MultiIndex flatten, empty yfinance response,
  flat-columns compat).

### Re-resolution

1,600 `v1_multiindex_bug` rows were re-resolved under `v2_fixed`. V1
values preserved in archive columns for forensic comparison. The stop-
distance fingerprint that was universal in v1 is now absent in v2 (aside
from a small legitimate-stop minority). Outcome distribution shows real
`win` / `loss` / `timeout` spread, consistent with bull-market yfinance
paths over 7-day windows.

### Changed — Part 2: Doc Sweep

- **`MASTER.md` Section 1**: release line now v0.22.0; tech-stack trading
  line notes IB dormant per SD#41.
- **`MASTER.md` Section 2**: closed-trade count 18 → 85; test count 1,801
  → 1,852; dashboard pages 24 → 25; research docs 91 → 107; sprint docs
  43 → 57; PEAD entry removed (SD#3 eliminated); new "Attribution
  resolver FIXED" line.
- **`MASTER.md` Section 2 (new subsections)**: Forensic Analysis Status
  (D1/D2/D3 progress, Stage 1/2 OOS gates) and Permanent Methodology
  Guardrails (SD#41 REVISED).
- **`MASTER.md` Section 2 Diagnostic D2 Status**: CLOSED — citation
  freeze LIFTED for `resolution_version='v2_fixed'` rows.
- **`MASTER.md` Section 5**: heading "40 confirmed" → "41 confirmed";
  SD#3 marked ELIMINATED (PEAD dead); SD#17 marked COMPROMISED and then
  FIXED v0.22.0; SD#36 phase gate redefined; new SD#41 REVISED entry
  supersedes prior SD#41 trade-lifecycle synthesis.
- **`MASTER.md` Section 6**: Phase 1→2 gate redefined — excess-Sharpe
  ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (raw Sharpe gate deprecated).
- **`MASTER.md` Section 8**: Revenue milestones shifted 6-12 months per
  SD#41 REVISED. Intraday desk feasibility research flagged.
- **`MASTER.md` Section 11**: Active Queue rewritten as SD#41 REVISED
  diagnostic-first plan. Prior queue moved to "Completed Sprints
  (historical)" subsection. New Research Queue subsection added.
- **`frontend/src/pages/Roadmap.jsx`** — Phase 1 gate metrics use
  excess-Sharpe + t-stat; IB activation row updated to reference cold
  storage + new gate.
- **`README.md`** — version badge v0.22.0; phase badge "diagnostic";
  test-count badge 1,852; Current Status reflects 85 closed + D1/D2/D3
  status + new Phase 1→2 gate.
- **`RELEASES.md`** — v0.22.0 entry with before/after + re-resolution
  stats.

### Authority

- Sprint spec: `docs/sprints/sprint-attribution-resolver-fix.md` (Part 1)
  + inlined doc sweep (Part 2 per user request)
- D2 audit: `docs/research/attribution-resolver-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.20.0] - 2026-04-16 — Regime & Sector Classifier Diagnostic (SD#41 REVISED / Sprint D3)

Closes the regime-NULL and sector-coverage gaps flagged in the forensic
report. No production code change — the enrichment bypass that caused
the 67% NULL `market_regime` was already fixed on 2026-04-14; this
sprint verifies coverage, adds regression tests so it can't silently
regress, backfills `realized_sector` to 100%, and clears up the label
vocabulary confusion between the regime classifier and the traffic
light.

### Diagnosed

- **`recommendations.market_regime` NULL anomaly** — classified as
  hypothesis (c) schema-recent scanner bypass. Per-day NULL rate cuts
  over cleanly at 2026-04-09 (100% -> 0%), matching the
  `attach_post_scan_features` deployment. 1,076 pre-2026-04-09 rows
  left as `NULL` accurately; they legitimately predate the fix.
- **Label-vocabulary confusion** — the codebase carries three distinct
  label systems: 5-state `compute_market_regime` (stored in
  `recommendations.market_regime`), 7-state `classify_regime`
  (canonical going forward), 3-state `traffic_light` (stored in
  `shadow_trades.regime_at_entry` despite the misleading column name).
  All three mapped in `docs/research/regime-classifier-audit.md`.
- **`recommendations.sector_context` 100% NULL** — documented as
  deprecated. Use `shadow_trades.realized_sector` or ticker-lookup via
  `data/reference/sp100-gics-lookup.csv` instead.

### Added

- **`tests/features/test_enrichment_coverage.py`** — 4 regression tests
  that grep the three scanner files for the `attach_post_scan_features`
  literal, plus a behavior test asserting `classify_regime` returns a
  label from the canonical 7-state set for representative inputs.
- **`docs/research/regime-classifier-audit.md`** — 243-line audit
  with label-source map, per-day cut-over evidence, sector backfill
  status, canonical vocabulary policy, and regression-protection summary.

### Changed

- **`data/shadow_trades.realized_sector` coverage now 100%** (226/226
  rows, zero NULL). D1 had backfilled the 85 closed rows; this sprint
  extended the backfill to the remaining 143 open/failed/pending rows
  (all S&P 100 tickers; GICS lookup had no gaps).

### Unchanged production code

No `src/` changes. The `attach_post_scan_features` call is present in
all three scanner paths in current main (`scheduler/universe_scanner.py`,
`services/scan_service.py`, `services/mr_scan_service.py`) and the bug
described in `src/features/enrichment.py:8-14` was remediated
2026-04-14.

### Deferred (out of scope)

- Regime classifier v2 / 7-state DB migration (SD#35, separate sprint).
- Renaming `shadow_trades.regime_at_entry` to `traffic_light_at_entry`
  (schema rename; requires data migration plan).
- Retroactively filling the 1,076 pre-2026-04-09 NULL rows (they
  accurately signal "enrichment not yet deployed").

### Authority

- Sprint spec: `docs/sprints/sprint-D3-regime-sector-diagnostic.md`
- Audit doc: `docs/research/regime-classifier-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.21.0] - 2026-04-16 — Earnings Filter Hard Block (SD#33 / Sprint H1)

Narrow scoring fix so trades are hard-blocked when earnings are scheduled
within ~7 trading days, regardless of the market-wide event risk score.
The earnings pipeline (scraper, lookup, scoring hook, risk governor, executor
tagging, dashboard field) was already fully built; the gap was a scoring-scale
mismatch. One-line threshold-override in `compute_event_risk_score` closes it.

### Fixed

- **`src/features/event_risk_score.py::compute_event_risk_score`** — earnings
  within 10 calendar days (~7 trading days, bounded by two weekends) now set
  `earnings_proximity = block_threshold` and floor `total_score` at
  `block_threshold`, guaranteeing `sizing_multiplier = 0.0` and triggering
  the existing `risk/governor.py:430` "Event risk hard block" reject path.
- `components["earnings_forces_block"]` (bool) is always present for
  downstream consumers, not just when earnings exist.

### The bug

Earnings <=2 days out added only +4 on a scale where hard-block threshold is
8. On calm market days (total_score < 4 before earnings), an earnings-imminent
ticker never crossed the threshold, and gap risk was unpriced. Per forensic
analysis, a non-trivial share of closed trades likely caught earnings
surprises mid-hold. Gap risk cannot be managed by stops, vol targeting, or
exits — only by not being in the position when earnings prints.

### Added

- **`tests/features/test_event_risk_earnings.py`** — 9 regression tests
  (core scenarios + parametric boundary at days_until=0/10/11 +
  earnings_forces_block key consistency when no earnings).
- **`tests/features/__init__.py`** — new test subdir.

### Changed

- **`tests/test_event_risk_score.py::test_compute_event_risk_score_adds_earnings_and_blocks`**
  updated to the new contract: `earnings_proximity = block_threshold` rather
  than the previous sliding +4/+2 schedule.

### Unchanged infrastructure (confirmed working — no rebuild)

- Nightly earnings scraper (`scripts/fetch_earnings_calendar.py`)
- Earnings lookup with yfinance fallback (`src/features/earnings.py`)
- Risk governor hard-block path (`src/risk/governor.py:430`)
- Executor earnings_adjacent flag (`src/shadow_trading/executor.py:570, 1934`)
- Schema `shadow_trades.earnings_adjacent` (INTEGER, default 0)

### Authority

- Sprint spec: `docs/sprints/sprint-H1-earnings-filter.md`
- Strategy Decision #33: MASTER.md Section 5, entry 33 (earnings 7-day
  exclusion zone; entry-exclusion layer now IMPLEMENTED, force-exit and
  post-earnings cooldown layers deferred)

## [v0.19.0] - 2026-04-16 — SPY-Matched Excess Instrumentation (SD#41 REVISED / Sprint D1)

Foundational alpha-vs-beta measurement. Every Sharpe metric can now
answer "real alpha, or just SPY drift?" Adds three columns to
`shadow_trades`, a SPY-benchmark utility, an idempotent backfill, a
dedicated API endpoint, and a Trade History lead panel. Redefines the
IB live-trading gate from raw Sharpe (trivially passed by bull-market
beta) to excess-return Sharpe.

### Added

- **3 columns on `shadow_trades`** (via `src/schema/registry.py`):
  - `spy_return_over_hold` (REAL) — SPY total return over the exact
    entry-to-exit date range, close-to-close, auto-adjusted
  - `excess_return` (REAL) — `pnl_pct - (spy_return * 100)`; positive
    means beat SPY over the same period
  - `realized_sector` (TEXT) — GICS sector from
    `data/reference/sp100-gics-lookup.csv`
- **`src/analytics/spy_benchmark.py`** — SPY return fetch via
  yfinance with fail-open semantics (`spy_return_over_range`,
  `excess_return`, `get_sector`)
- **`data/reference/sp100-gics-lookup.csv`** — 102 tickers mapped to
  11 GICS sectors; zero "Unknown" entries
- **`scripts/backfill_spy_excess.py`** — idempotent backfill for
  existing closed trades; `--dry-run` and `--force` flags
- **`/api/shadow/sharpe-attribution`** — primary metric endpoint
  with raw + excess Sharpe, 95% CIs, t-statistic, hit rate, and a
  verdict interpretation key (alpha_significant / alpha_suggestive /
  negative_alpha_* / alpha_not_demonstrated)
- **Trade History "Primary Metric" panel** — excess-Sharpe leads
  above the Today/Yesterday/7d/30d recency cards; raw Sharpe visible
  but demoted to footnote
- **`tests/analytics/test_spy_benchmark.py`** — 7 regression tests
  (pure-logic + mocked yfinance + sector lookup)

### Changed

- **IB live trading gate redefined:** excess-return Sharpe >= 0.5 at
  t >= 2.0 over 150 OOS trades. (Was raw Sharpe >= 1.0, trivially
  passed by SPY beta during a bull run.)
- **`src/journal/store.py::close_shadow_trade`** now centrally writes
  the three SPY fields on every exit (covers 5 executor call sites +
  3 reconcile call sites in one place). Fail-open: SPY yfinance
  exceptions never block trade close.
- **`src/sync/render_sync.py::_REAL_COLUMNS`** adds the two new REAL
  columns so the Postgres sync coerces them to float, not TEXT.

### Backfill

Live DB: 85/85 closed trades backfilled with SPY-matched excess
data, zero "Unknown" sectors. Second run of the backfill script
confirms idempotency (`updated=0, skipped_existing=85`).

### Rationale

Forensic analysis of 78 closed trades showed per-trade Sharpe 3.38
was mostly SPY beta during a bull run. Excess vs SPY = +0.039%,
t = 0.098 over 75 matched periods. Without this instrumentation we
cannot distinguish alpha from beta — every optimization decision
becomes directional noise chasing.

### Authority

- `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
- Sprint spec: `docs/sprints/sprint-D1-spy-excess-instrumentation.md`
- Methodology: `docs/research/sharpe-attribution-methodology.md` (new)

## [v0.18.0] - 2026-04-16 — IB Cold Storage (SD#41)

Disable Interactive Brokers integration through Phase 1 while preserving
every line of IB code for fast reactivation. The entire change is gated by
a single `trading.ib_enabled` flag. Default Alpaca-only operation; flipping
the flag to `true` and restarting the watch loop restores prior behavior.

### Added

- **Top-level `trading.ib_enabled` flag** (default `false`) in
  `config/settings.example.yaml` and `config/settings.local.yaml`. Cross-cutting
  feature flag, distinct from `live_trading.broker` (which selects between
  brokers but no longer overrides the gate).
- **3 regression tests** (`tests/test_ib_cold_storage.py`) covering the
  fallback path, the explicit-opt-in escape hatch, and the default-config
  invariant.
- **Settings page Broker Status panel** — shows "Alpaca · Active" and
  "IB · Dormant (SD#41)" with a one-line note about reactivation.

### Changed

- **`broker_factory.get_live_broker`** falls back to Alpaca with a `[BROKER]`
  warning when `broker=ib` but `trading.ib_enabled=false`. IB
  instantiation code path is preserved verbatim, just gated.
- **`executor._select_paper_broker`** skips IB paper-routing entirely when
  cold-stored, so high-score paper trades stay on Alpaca.
- **`executor.open_shadow_trade` / `place_paper_exit`** skip IB shadow-log
  writes (entry + exit call sites) when cold-stored.
- **`reconcile.reconcile_paper_trades`** defers the IB position fetch when
  cold-stored. Tracked IB-broker positions (TGT, etc.) get a single
  `[RECONCILE]` info log per cycle indicating brackets resolve naturally.
- **`scheduler.watch.WatchLoop.run`** logs `[WATCH] IB integration dormant
  per SD#41. Alpaca-only mode.` once at startup, and short-circuits the
  IB Gateway health-check loop.
- **6 existing IB tests** now opt-in to the IB code path via
  `trading.ib_enabled=true` in their config dicts.

### Preserved (not deleted)

- `src/trading/ib_broker.py`, `src/trading/ib_shadow.py`
- `src/api/cloud_routes/ib_shadow.py`, `src/api/routes/ib_status.py`
- `ib_shadow_log` database table (queryable, just stops growing)
- `ib_async` dependency in `requirements.txt`
- All `live_trading.ib.*` config keys (host, port, paper_routing, shadow_mode)
- IBShadow.jsx component file (no route changes)

### Authority

- `docs/research/SD-41-defer-ib-integration.md`
- Sprint spec: `docs/sprints/sprint-ib-cold-storage.md`

## [v0.17.2] - 2026-04-15 — Hotfix: Grafana Cloud Loki MVP (SD#40) + NSSM service installer

Centralized log aggregation and 24/7 Windows service management, plus a
fix for the startup hang when Render Postgres is unreachable.

### Added

- **Grafana Cloud Loki integration** (SD#40). Raw HTTP handler
  `src/observability/loki_handler.py` ships logs to Grafana Cloud with zero
  new dependencies — uses `requests` only. QueueHandler+QueueListener
  non-blocking dispatch so the trading thread never waits on HTTP.
- **DedupFilter** attached to the Loki handler. Suppresses duplicate log
  messages within a 60s window to keep noisy repeats (e.g. `[SCHEMA]
  Created/verified 53 tables`) from consuming Grafana Cloud quota. File
  and console logging are unaffected.
- **Structured `ctx` → Loki labels.** `event` and `ticker` from the existing
  `extra={"ctx": {...}}` dict are promoted to Loki stream labels; all other
  ctx data rides along in the log-line text via `StructuredFormatter`.
- **New `ctx` tags** on two previously unstructured log lines:
  `shadow_trading.executor` trade-open (`event=trade_open`) and
  `shadow_trading.reconcile` stale-close (`event=stale_close`).
- **Cloud-side shipping.** `src/api/cloud_app.py` wires the Loki handler at
  startup using env vars (`GRAFANA_LOKI_TOKEN`, `GRAFANA_LOKI_URL`,
  `GRAFANA_LOKI_USER`) so the Render-deployed FastAPI also ships logs.
- **NSSM Windows service installer** at `scripts/install_service.ps1` —
  install / uninstall / restart / status commands. Configures AppDirectory,
  log rotation, AppExit Restart, and a 10s `AppRestartDelay` so the PID
  lockfile atexit hook can release before the next watch-loop launch.
- **Config scaffolding.** `config/settings.example.yaml` gains an
  `observability.grafana` section; `.env.example` gains a
  `GRAFANA_LOKI_TOKEN` placeholder.
- **5 new tests** in `tests/test_loki_handler.py` — disabled config,
  missing observability section, missing env-var token, DedupFilter
  suppression, DedupFilter window expiry. No network calls.

### Fixed

- **Startup hang on unreachable Render Postgres.** `psycopg2.connect()` had
  no `connect_timeout`, so libpq retried SYN indefinitely when the Render
  DB was paused. `create_all_tables` / `ensure_columns` gain an optional
  `connect_timeout` kwarg (default `None` preserves manual-migration
  behavior); the three startup-path call sites now pass
  `connect_timeout=5` so an unreachable DB becomes a warning instead of a
  hang.
- **Stale test baselines.** `tests/test_coerce_to_schema.py` targeted
  `planned_shares` (which flipped INTEGER→REAL in v0.17.1 for fractional
  shares) — retargeted onto the still-INTEGER `duration_days`.
  `tests/test_executor_event_risk_resolve.py` filtered caplog at ERROR
  but the function logs at WARNING — lifted to WARNING across three tests.

## [v0.17.1] - 2026-04-13 — Hotfix: test baseline + fractional shares

Post-v0.17.0 hotfix clearing 12 of 19 pre-existing test failures on main and
a latent fractional-shares source bug. Net: test baseline moves from 1738/1757
passing to 1750/1757 passing (7 structural/environment failures remain, tracked
as separate issues for targeted cleanup sprints).

### Schema

- **fix:** `training_examples` gains `updated_at` (TEXT) column. `GuardedScorer`
  issued `UPDATE training_examples SET quality_score_auto = ?, updated_at = ?`
  but the column was never defined in `src/schema/registry.py` — every
  between-scan rescore raised `sqlite3.OperationalError`. Column added,
  migration applied via `validate-schema --fix`. Fixes `test_scorer.py` × 3.
- **fix:** `shadow_trades.planned_shares` and `.actual_shares` changed from
  INTEGER to REAL. Alpaca fractional share counts (e.g. 0.30) were silently
  truncated to 0, then the positive-shares guard in `journal.store` rejected
  the backfill.

### Source

- **fix:** `BrokerPosition.quantity`, `BrokerOrder.quantity`, and
  `BrokerOrder.filled_qty` changed from `int` to `float` in
  `trading.broker_interface`. `alpaca_broker.py` stops wrapping share counts in
  `int(float(...))` — fractional quantities now survive the reconcile path
  end-to-end. Fixes `test_reconcile.py` × 2 (`backfills_orphaned`,
  `ignores_paper_trades`).

### Tests

- **fix:** `test_env_secrets.py::test_env_var_referenced_in_source` (× 6
  parametrized) rewrote from `subprocess.run(["grep", ...])` to pure Python
  `pathlib.rglob + read_text`. Windows subprocess can't pass the embedded
  double-quote in the search pattern, giving false negatives that bash
  execution didn't show.
- **fix:** `test_watch_resilience.py::test_heartbeat_command_callable` —
  import path updated from `src.notifications.telegram` to
  `src.notifications.telegram_commands` after the notifications split.
- **fix:** `test_ingestion.py` × 2 — replaced live `yfinance.download()` calls
  with `patch` + deterministic OHLCV stubs. Complies with CLAUDE.md's
  no-network-in-tests rule.
- **fix:** `test_news.py::test_historical_news_date_bounds` — patches
  `_load_cached` to None and strips `FINNHUB_API_KEY` from the env so the test
  actually exercises the "no API key" branch rather than returning stale cache
  data from a previous run.
- **fix:** `test_render_sync.py::test_healthy_connection_reused_without_reconnect`
  — patches `create_all_tables` and `ensure_columns` so schema-helper internal
  `psycopg2.connect` calls don't inflate the expected count from 1 → 3.

### API

- **chore:** Bump `app.version` in `src.api.app` and `src.api.cloud_app` from
  `1.0.0` to `0.17.1` to match release tagging.

### Deferred (tracked as issues)

- `test_vram_manager::test_handoff_to_training_unload_fails` — needs
  `_wait_for_vram_clear` mock to exercise the no-nvidia-smi unload-failure
  branch correctly.
- `test_repo_structure.py` × 2 — 2 files over 400-line limit
  (`src/api/cloud_routes/trades.py` 427, `src/email/digest_builder.py` 405)
  and 15 functions over 60-line limit — refactor per the lint contract.

## [v0.17.0] - 2026-04-12 — IB Integration Complete + Dashboard Overhaul + Training Backfill

Consolidates seven IB integration sprints (IB-1 through IB-7), four dashboard
sprints (DB-1, DB-2a, DB-2b, DB-3), one final cleanup sprint (DB-FINAL),
a capital-velocity instrumentation drop, and a 703-row regime-diverse training
backfill into a single tagged release. Sub-sections below keep the sprint-level
notes that previously lived under `[Unreleased]` so the ship history stays
traceable.

### DB-FINAL — Dashboard cleanup

- **fix:** `shadow_trades` gains `time_to_mfe_days` (INTEGER) and `mfe_timestamp`
  (TEXT) columns. Executor's `check_and_manage_open_trades` now updates both on
  every MFE high; flat and adverse cycles preserve the peak. 3 new tests cover
  the rise/flat/close paths (Strategy Decision #32 instrumentation).
- **fix:** Attribution logger warnings are visible (`logger.warning` instead of
  `logger.debug` in `scheduler/universe_scanner.py`) and a defensive
  `_parse_price` check skips attribution entirely when entry/stop/target parse
  to 0/None rather than writing corrupt zero-priced ranker-only pairs.
  `attribution_trades` already carries `sync_to_postgres=True`; integration test
  added.
- **feat:** Mobile sidebar collapse in `Layout.jsx` (hamburger + overlay backdrop,
  status bar hidden below md breakpoint), `min-h-[44px]` touch targets on nav
  links, `p-3 md:p-6 lg:p-8` main-content padding.
- **fix:** `Architecture.jsx` and `DBSchema.jsx` set `nodesDraggable={false}` +
  `nodesConnectable={false}`, `<MiniMap>` removed (bottom-right glitch).
  Architecture subtitle no longer advertises drag.
- **chore:** ~15 `data-testid` attributes on Health (hshs-radar, hshs-composite,
  build-score-card, ib-status-card, model-history), Validation
  (validation-category-{name}), Monitoring (resource-chart, ollama-status,
  disk-status, log-table) for the upcoming System Health consolidation.
- **refactor:** `space-y-4 md:space-y-6` roots across 14 dashboard pages.

### DB-3 — Responsive + polish

- **feat:** Architecture diagram shows IB Gateway infrastructure node + a
  `broker_router` → (`live_alpaca` | `live_ib`) execution split reflecting the
  score-gated dual-broker routing.
- **feat:** Simulation page gains a regime dropdown that highlights one equity
  curve and dims the rest (opacity 0.15).
- **feat:** `scripts/stress_test.py` adds 4 historical scenarios — 2018 Q4
  selloff, 2011 debt ceiling, 2015 China deval, 2024 yen unwind.
- **feat:** IB section on Settings page (shadow_mode, paper_routing, routing
  threshold, Gateway port, client_id).
- **feat:** New `/velocity` dashboard page renders hold-period distribution,
  time-to-MFE scatter (falls back to duration until the new column fills),
  MFE capture efficiency. Gated behind a 50-trade banner until statistically
  useful.

### DB-2b — Feature additions

- **feat:** `IB Shadow` → `Broker Comparison`; nav item moved from System to
  Trading. CTO report exposes a by-broker breakdown (win rate, avg/total P&L).
- **feat:** Logs page "Export errors" downloads ERROR+CRITICAL+WARNING entries
  (last 24h) as markdown; "Clear stale" resolves pending/claimed commands
  older than 1 hour.
- **feat:** `get_training_status` returns `outcome_counts` + `source_counts`
  so the Outcome Distribution card renders real data.
- **feat:** 9 additional IB research + ops docs indexed on the Docs page.
- **feat:** `run_data_collection` emits a per-collector success/failure line
  after the 12-step block.

### DB-2a — Bug fixes

- **fix:** Packets page strips everything before the first recognized XML tag
  so the analysis pane shows LLM output only.
- **fix:** `/live/trades` + `/api/live/trades` enrich open rows with
  `current_price` + unrealized `pnl_dollars` / `pnl_pct` (graceful fallback when
  `setup_signals` is missing).
- **feat:** `OpenPositionCard` — rich per-position monitor card (stop/entry/target
  progress gauge, MFE/MAE, bracket status, conviction, days held/timeout).
  Shadow Ledger open tab uses a card grid.
- **feat:** Ledger source toggle (All / Paper / Live) + broker filter (Alpaca /
  IB) + broker column on closed-trades table.
- **feat:** Strategy page Drawdown chart is now a ComposedChart with green/red
  per-trade bars overlaid on the drawdown area.
- **fix:** Stress Test groups runs by scenario; only the latest per scenario
  renders, rest collapse into a "Previous Runs" archive.
- **fix:** Monitoring page crash — `Array.isArray(history) ? history : []`.

### DB-1 — Data integrity + quarantine sync

- **fix:** `scripts/sync_quarantine_to_postgres.py` one-time migration pushes
  locally-quarantined `shadow_trades.quarantined=1` rows to Render Postgres.
  The incremental sync uses `updated_at > last_synced_at` as its cursor — prior
  quarantine UPDATEs didn't touch the column, so ~17 issues were served
  compromised rows even though `COALESCE(quarantined, 0) = 0` was correctly
  applied in every cloud route.
- **fix:** `scripts/quarantine_april10.py` bumps `updated_at` on every UPDATE so
  future runs sync automatically.
- **fix:** `scripts/backfill_model_version.py` backfills
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance attribution.
- **fix:** `get_active_model_name()` falls back to Ollama `/api/ps` then
  `llm.model` when `model_versions` has no active row; new
  `src.llm.client.get_loaded_model_name` helper.
- **fix:** Header version resolves from `ARCIS_VERSION` env →  `VERSION` file →
  `git describe --tags --abbrev=0` → hardcoded fallback (`lru_cache`'d).
- **fix:** DB Schema page renders live table count + cluster-config domain
  count instead of hardcoded "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` + `strategies.pullback.timeout_days`
  resolve to actual keys; Min Conviction Score renders "Disabled" at 0/null;
  System Health shows "CLOUD (local status unavailable)" on cloud mode.
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with one deployed model. Data growth and
  recent-volume signals scale by a spin factor.
- **fix:** `council/value_tracker.py` track-record join adds
  `COALESCE(st.quarantined, 0) = 0`.
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  Advisory-only mode logs recommendations but does NOT rewrite live config.
  Session meta carries `advisory_only` for the dashboard.

### Training backfill

- **data:** 703 regime-diverse training examples imported — broadens v2 dataset
  from 1,019 to 1,722 examples spanning every market regime in the backfill
  sample. Conviction recalibrated (range 1-8, down from 5-9). Leakage check
  passed (59.8%). Halcyon-v2.0.0 retrain pipeline in progress.

## [Unreleased] — Dashboard Data Integrity (Sprint DB-1)

### Data fixes
- **fix:** `scripts/sync_quarantine_to_postgres.py` — one-time migration that pushes
  locally-quarantined `shadow_trades.quarantined=1` flags to Render Postgres. The
  normal sync is incremental on `updated_at`; quarantine UPDATEs run by
  `scripts/quarantine_april10.py` never touched that column, so 17+ issues across
  the dashboard were reading compromised rows despite every cloud route filtering
  on `COALESCE(quarantined, 0) = 0`. The filter was correct; the data wasn't.
- **fix:** `scripts/quarantine_april10.py` now also bumps `updated_at` on every
  UPDATE so future runs sync automatically without a dedicated migration.
- **fix:** `scripts/backfill_model_version.py` — one-time backfill of
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance dashboard attribution.

### Detection + display
- **fix:** `get_active_model_name()` now falls back to Ollama (`/api/ps`) then the
  config `llm.model` value when `model_versions` is empty. Cloud deployments with
  an unpopulated table no longer report a misleading "base".
- **feat:** `src.llm.client.get_loaded_model_name()` — non-recursive helper used by
  the versioning fallback.
- **fix:** Header bar version string is now resolved from `ARCIS_VERSION` env var
  → `VERSION` file → `git describe --tags --abbrev=0` → hardcoded fallback, with
  `lru_cache` so each request is cheap.
- **fix:** DB Schema page reads the live table count from `/system/table-counts`
  and the domain count from the cluster config instead of hardcoding
  "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` and
  `strategies.pullback.timeout_days` now resolve to actual config keys; Min
  Conviction Score renders a "Disabled" pill when the value is 0 or null.
- **fix:** System Health indicators display "CLOUD" (title: "local status
  unavailable") instead of "Off" when running against the cloud API, which
  cannot reach local services like Ollama.

### Metrics
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with only one deployed model. Data growth
  and recent volume are scaled by a spin factor that's zero until the first
  cycle, so mere data accumulation no longer inflates the score.
- **fix:** Council agent track-record query in `value_tracker.py` now applies
  `COALESCE(st.quarantined, 0) = 0` to the `shadow_trades` join.

### Safety
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  While false, the council logs recommended parameter changes for counterfactual
  attribution but does NOT rewrite live config. Enforces the FINSABER Phase 1
  authority boundary. Session result JSON now carries
  `session_meta.advisory_only` so the dashboard can label sessions as advisory.

### Tests
- **test:** `test_versioning.py` — new `monkeypatch`-based test for the Ollama
  fallback path of `get_active_model_name`.

## [Unreleased] — IB Integration Validation (Sprint IB-7)

### Integration Tests (16 tests)
- **test:** End-to-end IB + Alpaca trade lifecycle with broker field tracking
- **test:** Cross-broker position counting — governor, reconciler, executor all agree
- **test:** Config progression matrix — shadow → routing → live transitions
- **test:** Failure/recovery simulation — fallback, resume, mixed broker state
- **test:** Multi-broker API responses — schema columns, status mapping

### Operational Tooling
- **feat:** `scripts/validate_ib_integration.py` — data completeness checker across
  shadow_trades, ib_shadow_log, daily_ib_health, schema columns
- **docs:** `docs/operations/ib-smoke-test.md` — 6-phase manual validation checklist
  (shadow mode → dual routing → bracket monitoring → failure recovery → dashboard → scripts)

## [Unreleased] — IB Paper Trading Activation (Sprint IB-6)

### Validation & Monitoring
- **feat:** `scripts/validate_ib_gateway.py` — validates paper account setup, qualifies 10
  S&P 100 contracts, checks buying power, tests market data. REFUSES port 4001 (live).
- **feat:** `daily_ib_health` schema table — tracks uptime_pct, trade_count, error_count,
  reconnect_count. 30-day gate: >95% market-hours uptime.
- **feat:** IB Gateway status card on Health page — connection status, shadow mode, trade
  count, uptime, last connection timestamp
- **feat:** IB section in EOD digest — connection uptime %, IB vs Alpaca routing breakdown,
  errors/fallbacks (conditional on shadow_mode or paper_routing enabled)

### Operations
- **docs:** `docs/operations/ib-gateway-setup.md` — IBC config, Windows hardening, TDR fix,
  Java heap, Sunday 2FA procedure, troubleshooting

### Tests
- 5 tests: validation script live port refusal, daily_ib_health schema + SQLite creation,
  digest section conditional logic

## [Unreleased] — IB Production Hardening (Sprint IB-5)

### Connection Resilience
- **fix:** `_ensure_connected()` with exponential backoff (3 retries: 1s, 2s, 4s)
- **feat:** `_verify_bracket_integrity()` checks all positions have active stops after reconnect
- **feat:** Connect/disconnect pattern — fresh connection each poll cycle, rebuild state from server

### Order Safety
- **fix:** `outsideRth=True` on ALL orders — protective orders execute outside regular hours
- **fix:** `ocaType=3` on bracket children — block/overfill protection prevents dual fills
- **feat:** `permId` stored for cross-session tracking (survives Gateway restarts)
- **feat:** Partial fill detection with warning log

### Status Normalization
- **feat:** `IB_STATUS_MAP` normalizes IB statuses (PreSubmitted→pending, Inactive→rejected, etc.)
- **feat:** `_handle_ib_error()` classifies common IB error codes (110, 135, 200, 201, 202)

### Schema
- **schema:** Added `ib_perm_id` column to `shadow_trades` for cross-session order tracking
- **schema:** Added `perm_id` field to `BrokerOrder` dataclass

### Tests
- **test:** 16 tests for reconnection, bracket verification, status mapping, partial fills,
  outsideRth/ocaType, error codes, permId

## [Unreleased] — IB Dual-Execution Routing (Sprint IB-4)

### Score-Based Paper Broker Routing

- **feat:** `_select_paper_broker()` routes paper trades to IB when score >= threshold
  (default 80) and `live_trading.ib.paper_routing: true`. Falls back to Alpaca with
  warning if IB Gateway is down.
- **feat:** `open_shadow_trade()` uses the router — IB paper bracket orders placed via
  broker abstraction, Alpaca path unchanged for below-threshold trades.
- **feat:** `reconcile_paper_trades()` checks correct broker per trade — IB trades
  validate against IB positions, Alpaca trades against Alpaca positions.
- **config:** `live_trading.ib.paper_routing` (bool) + `paper_routing_threshold` (int)
- **test:** 12 tests — routing logic, fallback, cross-broker counting, Alpaca regression

## [Unreleased] — IB Shadow Dashboard + API Routes

### IB Shadow Dashboard

- **schema:** Enabled Postgres sync for `ib_shadow_log` (incremental, keyed on `shadow_id`)
- **feat:** 3 cloud API routes (`/api/ib-shadow/summary`, `/api/ib-shadow/log`, `/api/ib-shadow/health`)
- **feat:** IB Shadow dashboard page with KPI cards (shadow count, gateway uptime, contract valid, BP acceptance), trade log table, and error log
- **feat:** Navigation entry in System section (GitCompare icon)
- **feat:** Empty state with setup instructions when no shadow data exists

## [Unreleased] — IB Structural Fixes (Sprint IB-2)

### Critical Runtime Bug Fixes

- **fix:** `get_live_broker()` called without config arg — TypeError on live path
- **fix:** `get_positions()` → `get_all_positions()` + `p["symbol"]` → `p.ticker`
- **fix:** IB bracket child order IDs now stored (enables bracket health monitoring)
- **fix:** Bracket exit monitoring routes through broker factory for live trades
- **fix:** `_retry_exit` cancel uses broker factory for live/IB trades
- **fix:** Risk governor uses IB account equity when `broker=ib`
- **fix:** Live reconciler cancels IB orders before closing stale trades
- **fix:** IB `get_position` fetches current price via market data snapshot
- **fix:** Startup check validates `ib_async` availability when IB configured

### Schema

- Added `ib_child_order_ids` column to `shadow_trades`
- Added `broker_order_id` alias column (prep for `alpaca_order_id` migration)

## [Unreleased] — IB Test Coverage + Shadow Mode (#368)

### IB Broker Unit Tests (24 tests)

- **test:** Full unit test coverage for all 10 `BrokerAdapter` methods on `IBBroker`
  via mock factories (no ib_async dependency required). Covers happy paths (10),
  error handling (8), and edge cases (6) — connection lifecycle, bracket orders,
  market orders, exits, cancellations, positions, price snapshots.
- **test:** Mock factory helpers in `tests/conftest_ib.py` for all 6 ib_async
  object types (AccountValue, Trade, Position, Order, Stock, Ticker).

### IB Shadow Mode

- **feat:** `IBShadowLogger` class (`src/trading/ib_shadow.py`) — validates IB
  Gateway connectivity, contract validity, and buying power for each Alpaca
  trade WITHOUT submitting orders. Stores comparison data in `ib_shadow_log`.
- **schema:** Added `ib_shadow_log` table (17 columns, sync_to_postgres=False).
- **feat:** Executor hooks in `open_shadow_trade()` and `open_live_trade()` —
  non-blocking, wrapped in try/except, only fires when `ib.shadow_mode: true`.
- **test:** 6 shadow logger tests + 2 executor integration tests.

## [v0.16.12] - 2026-04-11

### Trading safety + security batch (#361, #363, #369, #370, #380)

**Trading safety (#369, #370):**
- **fix:** Replaced 6 `except Exception: pass` blocks in `executor.py` with
  `logger.warning()` — critical trading notifications (buying-power crisis,
  unprotected positions, exit circuit breaker) were silently swallowed
- **fix:** Added argument validation to `test_retry_exit_called_for_exit_failed`
  (`assert_called_once_with` instead of `assert_called_once`)
- **fix:** Added explicit assertion to `test_missing_table_does_not_raise`

**Security (#361, #363, #380):**
- **fix:** Added column allowlist in `attribution/logger.py` — dynamic SQL
  SET clause now validates columns against `_ALLOWED_ATTRIBUTION_COLUMNS`
- **fix:** Replaced `.format()` SQL in `value_tracker.py` with parameterized
  `?` placeholders for the `IN` clause
- **fix:** Replaced raw `str(exc)` in 5 command executor error responses with
  generic error categories — full details logged server-side only

## [v0.16.11] - 2026-04-11

### Fix: Test regressions — buying power mock + training gate assertion (#239, #371, #372)

- **fix:** Added `get_account_info` mock to `TestPaperSourceTagging` and
  `TestDualExecution` — tests failed because `_check_paper_buying_power()`
  returns $1 with placeholder API keys (#371, #239)
- **fix:** Updated `test_markdown_bold_heading_rejected` to use a standalone
  bold heading line (`**Market context:**\n`) instead of inline bold-then-text.
  The regex was intentionally narrowed in #334 to allow inline emphasis; the
  test wasn't updated (#372)
- **fix:** Fixed `test_daily_loss_guard_halts_trading` — the daily loss guard
  queries the DB directly, not `get_open_shadow_trades`. Test now inserts a
  losing live trade into tmp_db so the guard finds it.
- **fix:** Fixed `test_generate_create_sql_basic` — SQLite generator inlines
  `PRIMARY KEY` on single INTEGER columns (ROWID alias). Test was asserting
  the separate `PRIMARY KEY (id)` constraint form.

## [v0.16.10] - 2026-04-11

### P2 batch: research feeds, CBOE scraper, buying power race condition (#389-392)

- **fix:** Research feeds (#389): Removed dead Anthropic `/feed.xml` (404) and
  OpenAI `/blog/rss/` (403) URLs. Replaced Anthropic with `/research/rss.xml`.
  Added `Accept` header to SSRN request. Increased arXiv timeout to 60s.
- **fix:** CBOE scraper (#390): Demoted regex-failure log from `warning` to
  `debug` — the SPY proxy and FRED fallbacks already produce reliable data.
  The regex breaks every time CBOE changes their HTML.
- **note:** NULL ids (#391): Investigated and confirmed already resolved —
  SQLite `INTEGER PRIMARY KEY` auto-assigns ROWIDs. Current state: 459K rows,
  0 NULL ids. The auto-repair messages in logs were from a one-time migration.
- **fix:** Buying power race condition (#392): Added per-scan-cycle committed
  capital tracker in executor. Previously N trades each passed the buying power
  check individually but together exhausted capital. Now
  `_scan_cycle_committed` subtracts capital from earlier orders in the same
  batch before checking. Reset at scan start via `reset_scan_cycle_committed()`.

## [v0.16.9] - 2026-04-11

### Root cause gap closures for #383, #386, #388

- **fix:** Added `_coerce_to_schema` to `update_recommendation()` — was unprotected
- **fix:** Refactored direct SQL UPDATE in `executor.py:650` to use
  `update_shadow_trade()` — was bypassing the coercion write boundary
- **fix:** Council dynamic weights: aggregate net PnL per day before joining
  to votes, preventing many-to-many inflation where 1 vote × 5 trades = 5
  data points. Added `session_type` filter to the query.
- **fix:** Applied circuit breaker to `generate_structured()` — was unprotected
  against Ollama outages, burning 180s timeouts independently of `generate()`

## [v0.16.8] - 2026-04-11

### Hotfix: Ollama timeout resilience — circuit breaker + auto-restart (#388)

- **fix:** Added consecutive failure tracking (circuit breaker) to `generate()` —
  after 3 failures, skips immediately instead of burning 180s timeouts per call.
  Previously 15 consecutive timeouts wasted 45 minutes on Apr 10 evening.
- **fix:** Auto-restart mechanism: when circuit breaker trips, attempts to restart
  Ollama via `ollama serve` before giving up
- **fix:** 2-second cooldown between inference calls to prevent Ollama overload
  during batch processing (10-20 tickers per scan cycle)

## [v0.16.7] - 2026-04-11

### Hotfix: Training pipeline — em-dash SyntaxError + GGUF fallback + Modelfile path (#387)

- **fix:** Replaced Unicode em-dash with ASCII `--` in `training_data/train.py:78`
  — Windows cp1252 subprocess could not parse the UTF-8 character, blocking
  the entire training script from loading
- **fix:** Added CPU-based GGUF conversion fallback via llama.cpp when Unsloth
  GPU export fails due to insufficient VRAM (RTX 3060 12GB)
- **fix:** Modelfile path now uses `.as_posix()` for forward slashes — was
  writing Windows backslashes into the `FROM` directive

## [v0.16.6] - 2026-04-11

### Hotfix: Council dynamic weights query — fix broken join (#386)

- **fix:** Replaced broken `JOIN shadow_trades st ON cs.session_id = st.session_id`
  (column never existed) with date-based join `ON date(cs.created_at) = date(st.created_at)`.
  Council sessions are market-level, not per-trade — votes are matched to trades
  opened on the same day.
- **fix:** Added `float()` cast on `pnl_dollars` comparison (defense-in-depth for #383)

## [v0.16.5] - 2026-04-11

### Hotfix: Auto-fix Postgres schema drift during startup (#385)

- **fix:** Startup sequence now runs `create_all_tables()` + `ensure_columns()`
  against Render Postgres automatically, matching the SQLite auto-fix pattern.
  Previously only warned about drift (filed 8 times as #184, #285, #307, #331,
  #332, #338). Missing tables and columns are now created on every startup.

## [v0.16.4] - 2026-04-11

### Hotfix: LLM output quality — repeat penalty + output validation (#384)

- **fix:** Added `repeat_penalty: 1.15` to Ollama API calls in `src/llm/client.py`
  to suppress degenerate repetition loops (52 debug log files showed `===` or
  data fields repeated 10-82 times)
- **fix:** Added `_validate_llm_output()` pre-parser in `src/llm/packet_writer.py`
  that rejects responses containing prompt leakage (37% of debug logs), template
  stubs (10%), and repetition loops (14%) before they reach the XML parser
- **test:** 10 tests for `_validate_llm_output` covering all rejection categories

## [v0.16.3] - 2026-04-11

### Hotfix: Write-boundary type coercion for shadow_trades (#383)

- **fix:** Added `_coerce_to_schema()` to `src/journal/store.py` — coerces dict
  values to match schema registry column types (REAL→float, INTEGER→int) before
  INSERT/UPDATE. Applied to `insert_shadow_trade()`, `update_shadow_trade()`,
  and `log_recommendation()`. This is the systemic root cause behind 10+ prior
  issues where `pnl_dollars`, `entry_price`, `price_at_recommendation` etc.
  were stored as strings, causing TypeErrors in 8+ downstream subsystems.
- **test:** 13 tests for `_coerce_to_schema` covering string→float, None
  preservation, unknown tables/columns, invalid values, and multi-column
  coercion.

## [Unreleased] — Manual Backfill Pipeline

### Historical Backfill: Manual Generation Workflow

**New modules:**
- `src/training/regime_sampler.py` — regime-targeted date selection, stratified sampling, FRED macro formatting, and dataset balancing helpers (moved from backfill.py)
- `scripts/export_backfill_prompts.py` — exports regime-targeted prompt files with real FRED macro context for manual generation via Claude/ChatGPT
- `scripts/import_backfill_results.py` — validates XML, pairs with sealed outcomes, inserts into training_examples (idempotent)
- `scripts/backfill_progress.py` — visual per-regime progress tracker

**Enhancements:**
- `src/training/historical_data.py` — FRED historical series fetch (`fetch_fred_history`) + point-in-time lookup (`get_fred_value_as_of`)
- `src/training/historical_scanner.py` — FRED macro enrichment in scan pipeline, PASS example generation (score 45-69), `generate_backfill_example()` handles outcome=None
- `src/llm/prompts.py` — `PASS_ANALYSIS_PROMPT` for below-threshold setups (conviction 1-4, NEUTRAL direction)

**Refactors:**
- `src/training/backfill.py` — 445→343 lines; `_balance_dataset`, `_deduplicate_candidates`, `_cap_and_diversify` moved to `regime_sampler.py`

**Tests:** 16 new tests (6 FRED history + 10 regime sampler); all 40 pass

## [v0.16.2] - 2026-04-11

### Hotfix: MR scan broken import (#382)

- **fix:** Corrected import path `src.journal.recommendation_logger` →
  `src.journal.store` — the `recommendation_logger` module never existed;
  `log_recommendation()` lives in `store.py`. Mean-reversion scanning has been
  fully disabled since April 9.

## [v0.16.1] - 2026-04-10

### Hotfix: pandas 3.0 import deadlock on Windows

- **fix:** Pin `pandas>=2.2,<3.0` in requirements.txt — pandas 3.0.1 C extensions
  deadlock on import under Python 3.13 + Windows (DLL loading hang in
  `pandas._libs.pandas_parser`)
- **fix:** Recreate venv with pandas 2.2.3 to restore `startup` / watch loop

## [v0.16.0] - 2026-04-10

### Trade Reconciliation Hardening & Data Quarantine

**Security (#348, #349):**
- **fix:** Local API binds to 127.0.0.1 (was 0.0.0.0)
- **fix:** Cloud API raises RuntimeError when API_SECRET is empty

**Order Submission (#352, #353, #359, #360):**
- **feat:** Post-submission order verification via `verify_order_accepted()`
- **fix:** Typed exception handling — ConnectionError/TimeoutError, APIError, Exception
- **feat:** Entry retry with ghost position check on network errors
- **feat:** exit_order_id stored immediately after exit submission

**Reconciler (#354, #356, #357, #358):**
- **fix:** Backfilled orphans get 5% stop/target defaults (was zero)
- **feat:** `cancel_orders_for_ticker()` called before closing stale positions
- **fix:** Alpaca position check before entry prevents duplicate ghost positions
- **feat:** Telegram alert after 3+ consecutive buying power failures
- **feat:** `submission_uncertain` trades resolved by reconciler

**Status Model (#355):**
- **feat:** TERMINAL_STATUSES / ACTIVE_STATUSES constants in models.py
- **fix:** Buying power rejections use status='rejected' (was 'failed')

**Data Quarantine:**
- **feat:** `quarantined` column added to shadow_trades
- 77 compromised records flagged (42 rejected, 34 stale, 1 orphan WMT)
- 18 verified trades preserved ($603.96 P&L, 83.3% win rate)
- All shadow_trades queries filtered on quarantine column
- **fix:** TEXT-to-REAL type casting in shadow_service (TypeError)

**Infrastructure (#328, #350, #351):**
- **fix:** latest_collection date format truncated to date-only
- **fix:** Watch loop done-flags moved inside try blocks
- **test:** Executor entry path coverage added

## [v0.15.3] - 2026-04-08

### Production Sweep — 14 issues closed in 3 phases

**Phase 1 — CRITICAL (v0.15.1):**
- **fix:** Stop-price > 0 guard before bracket order placements (#326)
- **fix:** Fractional share tolerance — alpaca adapter returns float qty (#325)
- **fix:** Conviction extraction stages 7-8 + parse rate logging (#329)
- **fix:** safe_numeric for quality_score_auto, int() cast on config thresholds (#330)
- **fix:** Overnight training script import path verified (#335)

**Phase 2 — HIGH (v0.15.2):**
- **fix:** Postgres create_all_tables + ensure_columns at sync startup (#331)
- **fix:** macro_snapshots sync_conflict_col for duplicate key prevention (#332)
- **fix:** DDL guardrail verified clean (#327)
- **fix:** Data collection stats COALESCE for column compatibility (#328)

**Phase 3 — MEDIUM (v0.15.3):**
- **fix:** NULL PK inline PRIMARY KEY root cause verified (#302)
- **fix:** Research source caching + 30s timeout + retry with backoff (#303)
- **fix:** VRAM handoff 3-retry logic with Telegram alert (#304, #333)
- **fix:** Ingestion gate narrowed for inline bold emphasis (#334)

## [Unreleased — pending v0.15.0]

### Gap Assessment (merged 2026-04-07)
- **feat:** Embedding-based semantic leakage detection — Ollama + LogisticRegression classifier (#295)
- **feat:** Dynamic Bayesian agent weighting for AI Council — Beta posterior, feature flag, 12-week window (#296)
- **feat:** Two-tier relative strength — 60% vs SPY + 40% vs sector ETF, 11 sector ETFs mapped (#297)
- **test:** 7 ranker tests (two-tier RS, pullback bounds, volume weight, backward compat, score cap)
- **test:** 6 council aggregation tests (dynamic weights, floor enforcement, normalization, fallback)
- **test:** 6 embedding leakage tests (mock Ollama, graceful fallback, threshold, class balance)

### Pending merge
- feat/simulation-engine: 13-scenario engine, Monte Carlo, TL validation, dashboard page
- feat/model-performance: per-model metrics, regression alerts, dashboard page
- feat/ui-bloomberg: Bloomberg Terminal aesthetic on all 18 pages

## [v0.14.2] - 2026-04-06

### Hotfix merge sprint — 6 critical production bugs + codex fixes + dependencies

**Critical fixes (PR #313):**
- **fix:** Shadow trade exit cascade — `exit_failed` status + circuit breaker + `cancel-all-pending` CLI (#310)
- **fix:** Type-safety gaps — `safe_numeric` utility for traffic_light, VIX alerts, EOD report (#311)
- **fix:** LLM conviction parsing — Stage 6 catch-all regex + debug file logging (#309, #312)
- **fix:** Risk governor TypeError — `safe_numeric` coercion at `check_trade` entry (#308)
- **fix:** Postgres schema drift — startup drift check + broker column (#307)

**Codex fixes (PR #305):**
- **fix:** Ingestion gate markdown detection narrowed to line-leading headings (#299)
- **fix:** Type-safety in notifications/digests (#300)
- **fix:** Fundamentals refresh import drift (#301)

**Other:**
- **feat:** Structured logging with `|ctx:{}` for AI agent review (#314)
- **fix:** load_dotenv() in config loader — .env works from any entry point (#317)
- **build:** 9 Dependabot PRs (CI actions, npm bumps, yfinance range)
- **chore:** 33+ stale branches deleted

## [v0.14.1] - 2026-04-05

### Log Audit Hotfix (14 production issues)

Full audit of 15K-line arcis.log identified and fixed 14 issues across 8 modules.

**Critical:**
- #279: Bracket monitor strips Alpaca enum prefix from leg statuses + adds `accepted` to ACTIVE_LEG_STATUSES (was reporting 0/N protected)
- #280: Earnings signals column names corrected to schema registry (actual/estimate/metric)

**High:**
- #281: Overnight training script imports fixed (was referencing wrong module paths)
- #282: Position monitor casts timeout_days from SQLite TEXT to int
- #283: Regime refresh passes ohlcv_data argument to sentiment_scanner
- #284: HSHS performance sub-score casts SQLite TEXT to float before abs()
- #285: Training data_collector casts to float before %.2f format string

**Medium:**
- #286: Postgres sync null ID guard + duplicate primary key handling
- Stress test VIX symbol handling fixed
- EOD recap format string type safety

**Audit report:** `docs/audits/log-audit-2026-04-04.md`

---

## [v0.14.0] - 2026-04-05

### Interactive Brokers Integration — Broker Abstraction Layer

5 new files, 19 new tests. Multi-broker architecture deployed.

**New modules:**
- `src/trading/broker_interface.py` — Abstract BrokerAdapter (10 methods) + normalized dataclasses
- `src/trading/broker_factory.py` — Singleton factory, config-driven routing (`"ib" | "alpaca"`)
- `src/trading/ib_broker.py` — IB adapter via ib_async, lazy connection, GTC bracket orders
- `src/trading/alpaca_broker.py` — Thin wrapper over existing alpaca_adapter.py
- `tests/test_broker_interface.py` — 19 tests (interface compliance, factory routing, dataclasses)

**Architecture changes:**
- Live trading routes through broker factory: `get_live_broker(config)` instead of direct Alpaca
- Schema: `broker` column added to `shadow_trades` (default "alpaca")
- Config: `settings.example.yaml` updated with IB settings (host, port, client_id)
- Paper trading unchanged (Alpaca direct, no abstraction needed)

---

## [v0.13.0] - 2026-04-04

### Gap Analysis Rectification — 23 Issues Resolved in 3 Tiers

19 files changed, +414 -157. 0 open issues.

**Tier 1 — CRITICAL (6 issues, money at risk + training data):**
- #272: Live trading now enforces RiskGovernor + LLM validator (was bypassed entirely)
- #274: Bracket fallback places standalone stop-loss (was naked market entry)
- #275: Daily loss guard uses today's realized P&L (was all-time unrealized)
- #277: Feature sanitization BEFORE LLM generation (self-blinding leak fixed)
- #273: Empty-output templates excluded from training dataset
- #278: Partial fills tracked correctly (was recording as full close)

**Tier 2 — HIGH (7 issues, reliability):**
- #271: MR exit passes all required args to close_shadow_trade
- #276: Duplicate position check + insert in same transaction (race fixed)
- #267: Traffic light defaults to 0.5 (conservative) when missing
- #257: _safe_run only sets done-flag on success (failed tasks retry)
- #259: pull_commands only claims successfully inserted commands
- #269: _notify_exit_trade call sites pass all required params
- #264: open_shadow_trade returns None consistently on failure

**Tier 3 — MEDIUM (9 issues, polish):**
- #256: Options metrics query column names fixed
- #260: options_chains retention rule added (30 days)
- #261: Options flow in training documented as future enhancement
- #262: earnings_signals logs errors instead of swallowing
- #263: Duplicate bracket order log removed
- #265: Stub endpoints return not_implemented status
- #266: shadow_account queries unified
- #268: Dead canary_score import removed
- #270: NYSE 2026 holiday calendar added

---

## [v0.12.0] - 2026-04-04

### Codebase Documentation + Issue Resolution + Gap Analysis

116 files changed, +3,757 lines. 0 pre-existing issues remaining.

**Issue resolution (11 closed: #222, #239, #247-#255):**
- #248: Bracket monitor false alarms — Alpaca enum prefix stripped
- #249: System validator reads env vars, not YAML
- #250: Dark mode chart visibility — CSS variables defined
- #251: Packet commentary — raw template headers stripped
- #253: Open positions unrealized P&L computed
- #254: Max consecutive losses wired from cto_report
- #247: Metric cards centered
- #252: Stress test Run button via command queue
- #255: React Flow diagram polish
- #239: Daily audit baseline updated
- #222: Telegram pairing documented

**Codebase documentation:**
- WHY-focused inline comments on all 200+ Python files
- 30 closed issues cross-referenced in code at fix locations
- Strategy decisions (#1-#24) cited at implementation points

**Gap analysis (15 new issues filed: #256-#270):**
- Options pipeline dead (#256), _safe_run done-flags (#257), busy_timeout bypass (#258)
- pull_commands claim bug (#259), options_chains unbounded growth (#260)
- Unused options flow (#261), earnings_signals swallowing (#262), duplicate log (#263)
- open_shadow_trade return type (#264), stub endpoints (#265), wrong columns (#266)
- Traffic light default (#267), broken import (#268), missing params (#269), no holidays (#270)

---

## [Unreleased] - 2026-04-03

### Bug Fixes (PRs #200, #201, #204)

- Cast `pnl_dollars` to float before comparison in shadow trade close logic (#195, PR #200)
- Fix exit order cancel race condition — cancel completes before status update (#196, PR #201)
- Harden VRAM handoff escalation — retry with exponential backoff (#198, PR #201)
- Add Postgres sync reconnection on transient connection drops (#199, PR #201)
- Fix 8 RCCA bugs from 4/3 log audit: SQLite TEXT→numeric casts (4 bugs), VIX `.item()`, regime missing arg, Telegram undefined var, Postgres duplicate keys (PR #204)

### Sprint Gap Closures (PR #204)

- Wire `resolve_pending_outcomes()` into 4:30 PM post-close job (S3)
- Add `tests/test_attribution.py` — 12 tests covering all 5 attribution functions (S3)
- Add `strategy_type` dropdown filter on Shadow Ledger + API response (S4)
- Extract universe scanner from `watch.py` into stateless `universe_scanner.py` (S5)
- VIX-regime ATR-based brackets in stress test (2.0x/2.5x/3.0x by regime) (S7)
- Schedule stress test Sunday 9 PM + re-run on model version change (S7)

### Halcyon-Audit Plugin (PR #204)

- 8 domain agents + 1 synthesis agent for automated codebase auditing
- `/audit` skill with scheduling, quality gate, baseline management
- Idempotent GitHub issue filing with severity/domain labels

### Local API Parity (PR #202)

- 22 missing routes added to local FastAPI server to match cloud endpoints

### Sprints A through 7: Dashboard, Attribution, MR, Multi-Cadence, Training, Stress Testing

**Sprint A — Dashboard Polish + Documentation Consolidation:**
- Redesigned audit banner as compact expandable chip (green/yellow/red/stale states)
- Fixed build score empty state (shows "not yet computed" instead of 0.0)
- Added `cto-report` command handler; fixed action endpoint mappings
- Fixed activity feed "task: ?" entries for overnight_task and default cases
- Created MASTER.md (822 lines, 13 sections) consolidating 5 governance docs
- Archived 11 docs to docs/archive/governance/ and docs/archive/reference/
- Enriched watch loop: startup banner with portfolio stats, 60-min heartbeat, scan summary line

**Sprint 3 — Alpha Attribution Experiment:**
- Added `attribution_trades` table (49 tables total in registry)
- Two-phase attribution logging in watch.py (before/after LLM)
- Mechanical outcome simulator for post-close evaluation
- Historical backtest script (`scripts/alpha_attribution_backtest.py`)
- Dashboard Attribution page with win rate comparison and statistical power

**Sprint 4 — Mean Reversion Paper Trading:**
- Mean reversion feature engine (RSI(2), 200 EMA, Bollinger, volume spike)
- Shared `compute_rsi()` utility in `src/features/indicators.py`
- Strategy config with `paper_only` enforcement
- Strategy-aware exit dispatcher (RSI(2) > 70 exit, ATR stop, MR timeout)

**Sprint 5 — Multi-Cadence Scanning:**
- Extracted 4 modules: position_monitor (15 min), universe_scanner (30 min), sentiment_scanner (60 min), fundamentals_refresh (daily)
- 4-tier timing orchestrator wired into watch.py main loop
- Staleness detection with per-ticker per-source tracking (`data_freshness` table)

**Sprint 6 — Outcome-Conditioned Training Pipeline:**
- Outcome classifier (WIN/LOSS/TIMEOUT from exit_reason + P&L)
- 4 outcome-conditioned + 2 contrastive prompt templates (all self-blinding)
- Data collector now generates 3-5 examples per closed trade (up from 1)
- 8 outcome metadata columns added to shadow_trades

**Sprint 7 — Historical Stress Testing:**
- Stress test script for 2008, 2020, 2022 crisis periods
- Survivorship bias mitigation (filter + note limitation)
- Extended backtester metrics (calmar, monthly returns, drawdown duration)
- Dashboard StressTest page with equity curves
- Results stored in `stress_test_results` table

## [Previous] - 2026-03-31

### Sprint 8: Comprehensive Cleanup — All Remaining Issues

**Training Pipeline Safety (Task 1):**
- Sanitize feature snapshots: remove outcome-correlated fields before storage (#110)
- Exclude canary example IDs from exported training data (#111)
- Leakage detector returns INSUFFICIENT_DATA when <30 examples per class (#113)
- Temporal split applied BEFORE quality filter to prevent future leakage (#114)
- Dynamic gradient accumulation prevents crash on small datasets (#115)
- Partial close detection: label as PARTIAL and exclude from training (#116)

**Council Fixes (Task 2):**
- Exponential backoff retry on Anthropic rate limit errors (#117)
- Filter unparseable votes from consensus tally (#118)
- Dynamic majority threshold (len//2+1) instead of hardcoded 3 (#119)
- Cost cap check before Round 2 with configurable max_session_cost (#120)
- Type-validate confidence values — non-numeric defaults to 0.5 (#121)
- Auto-create value tracker tables on first access (#122)

**LLM Pipeline Hardening (Task 3):**
- Configurable LLM timeout via llm.inference_timeout_seconds (#153)
- Context window overflow protection with enrichment truncation (#154)
- Prompt injection sanitization for news/filing enrichment data (#156)
- Universe lookup failure rejects trade (fail closed) (#162)
- Grammar client VRAM leak fix on model version change (#163)
- Daily packets list capped at 200 and cleared after EOD digest (#164)
- VRAM threshold increased from 500MB to 1500MB (#166)
- Empty string LLM responses treated as failure (#167)
- Conviction None defaults to 5 with warning (#168)
- Out-of-range conviction logged as hallucination before clamping (#169)

**Data Pipeline Robustness (Task 4):**
- Nightly retention policy: prunes old rows from 7 tables (#123)
- Options collector validates underlying_price (reject NaN/None/0) (#125)
- EDGAR accession numbers normalized to dashed format (#126)
- EDGAR NLP UPDATE checks columns exist via PRAGMA (#127)
- CBOE collector returns None on regex failure (#128)
- Short interest collector uses cursor.rowcount (#129)
- Sync timezone handling verified (#131)
- Enricher rate limiting: Finnhub 1s, SEC 0.1s intervals (#133)

**Trading Logic Fixes (Task 5):**
- Atomic duplicate position check with BEGIN IMMEDIATE (#99)
- Alpaca API failure counter with Telegram alert at >50% failure rate (#102)
- Partial fill detection on bracket legs (#104)
- Backfilled positions flagged with zero stop/target (#107)
- Stale record closure attempts yfinance P&L, falls back to reconciled_stale (#108)
- Daily loss limit uses realized (closed) trades only (#109)
- Traffic light persistence debounce (5-minute cooldown) (#144)
- Sector exposure uses current market price (#145)

**Frontend Bug Fixes (Task 6):**
- Verified all fetchApi() calls match backend routes, added getBuildScore (#81, #134)
- Per-page ErrorBoundary wrapping all routes (#135)
- ShadowLedger reads starting capital from API (#138)
- CTOReport uses optional chaining on all data fields (#139)
- Council page invalidates queries after askStrategic mutation (#140)
- Training page derives outcome types dynamically (#142)

**Frontend Security & UX (Task 7):**
- AuthGate hashes password with SHA-256, 24h expiry (#137)
- Docs page sanitizes HTML to prevent XSS (#136)
- .env.example clarifies VITE_API_SECRET is dashboard-only (#148)
- formatTimestamp utility with Intl.DateTimeFormat (#141)
- Text labels alongside color-coded status indicators (#143)

**Sprint 6 Visibility (Task 8):**
- All 6 Sprint 6 tasks were already implemented; refactored Training.jsx (450→315 lines)

**Config, Performance & Tech Debt (Task 9):**
- Central DB_PATH constant in src/config (#83)
- Added missing env vars to .env.example (#84)
- Added 10+ minimal import tests for untested modules (#85)
- Updated AGENTS.md route count (55→124) (#86)
- Added indexes on shadow_trades.status and recommendations.created_at (#92, #97)
- Replaced all var(--slate-*) with var(--arcis-*) (#93)
- Moved config_overrides.py to src/config/overrides.py (#95)
- Added comprehensive comments to settings.example.yaml (#98)
- Research collector logs fallback to keyword scoring (#146)
- NYSE holiday awareness for 2026 (#149)
- Sleep/crash recovery detection with gap alerting (#152)
- reload_config() clears cache on demand (#165)

**Tests:** +78 new tests (1225 total, up from 1147) across 16 new test files
**Files:** 173 Python modules, 101 test files

**Issues closed:** #81, #83, #84, #85, #86, #92, #93, #95, #97, #98, #99, #102, #104, #107, #108, #109, #110, #111, #113, #114, #115, #116, #117, #118, #119, #120, #121, #122, #123, #125, #126, #127, #128, #129, #131, #133, #134, #135, #136, #137, #138, #139, #140, #141, #142, #143, #144, #145, #146, #148, #149, #152, #153, #154, #156, #162, #163, #164, #165, #166, #167, #168, #169

---

### Sprint 7: Reliability & Critical Bug Fixes

**P0 fixes (trading risk / system crash):**
- Watch loop crash protection: top-level exception handler with Telegram CRITICAL alert, graceful SIGTERM handling, exponential backoff (10s/30s/60s cap) replacing fixed 5-min cooldown, hourly instability alerts (#159, #155, #157)
- Bracket orders changed from DAY to GTC time-in-force — positions now protected overnight/weekends (#101)
- Exit-failed recovery: failed exits marked `exit_failed` and retried next scan cycle with Telegram alert (#100)
- Timestamp parse failure now defaults to days_open=999 (force timeout) instead of 0 (disable timeout) (#105)
- Stop-loss vs take-profit bracket leg identification in exit_reason field (#103)
- Traffic Light API: replaced UNKNOWN stub with live DB query (#89)
- Render sync crash detection: Telegram alert on error, mutex to prevent overlapping cycles (#161, #130)
- load_dotenv added to watch.py for standalone execution (#90)

**P1 fixes (will cause problems soon):**
- Heartbeat: writes timestamp to data/watchdog.txt every 60s, /heartbeat Telegram command (#150)
- Scan overlap prevention: _scan_in_progress flag prevents concurrent scans (#151)
- SQLite busy_timeout: new `src/utils/db.py` helper with PRAGMA busy_timeout=5000; migrated executor, bracket_monitor, reconcile (#160)
- Missing API key alerts: one-time Telegram alert per missing key (FINNHUB, FRED) (#124)

**Cosmetic:**
- Renamed "HALCYON LAB" to "ARCIS" in watch banner and startup notification (#94)
- Updated build_score.py docstring from "Halcyon Lab" to "Arcis" (#96)
- Replaced hardcoded Render URL with RENDER_API_URL env var (#91)

**Tests:** +18 new tests (1168 total) across 3 new test files: test_watch_resilience.py, test_bracket_safety.py, test_db_util.py

**Issues closed:** #89, #90, #91, #94, #96, #100, #101, #103, #105, #124, #130, #150, #151, #155, #157, #159, #160, #161

### Automated Daily Reconciliation (#170)

#### Paper Trade Reconciliation
- Added: `reconcile_paper_trades()` in `src/shadow_trading/reconcile.py` — compares Alpaca paper positions with local `shadow_trades` (source='paper')
- Added: Orphaned position backfill with `order_type='reconciled'`, stale trade detection (alert-only, no auto-close), qty discrepancy reporting
- Added: `_run_postclose_reconciliation()` in watch loop — runs daily at 4:30 PM ET postclose, sends Telegram summary
- Added: 4 tests in `tests/test_reconcile.py` (all-matched, orphaned backfill, stale no-auto-close, qty discrepancy)

---

### Sprint 6: Data Pipeline Visibility

#### API Wiring (Task 1)
- Added: `getDataCollectionStats`, `getTrainingHistory`, `getScanMetrics` methods to frontend api.js

#### Data Collectors Grid (Task 2)
- Added: 12-card collector grid on Training page with freshness indicators (green/yellow/red)
- Added: row counts, relative dates ("2h ago", "yesterday"), and ticker coverage per collector
- Added: responsive grid (3 cols desktop, 2 tablet, 1 mobile)

#### Training Pipeline Status (Task 3)
- Added: pipeline status section on Training page with active model card and status badge
- Added: format compliance display (XML vs plain_text counts)
- Added: leakage test indicator with OK/Marginal/Leaking thresholds
- Added: quadrant distribution 2x2 grid (good/bad process x good/bad outcome)

#### Model History (Task 4)
- Added: model history timeline on Health page with version, status badge, example count, holdout score
- Added: graceful single-model state ("First model — no comparisons yet")

#### Scan Metrics Trend (Task 5)
- Added: scan metrics section on Dashboard with today's summary (scans, packets, LLM success rate)
- Added: 7-day trend sparkline using Recharts LineChart
- Added: LLM success rate color coding (green >90%, yellow 70-90%, red <70%)

#### Card Contrast Fix (Task 6)
- Added: `.arcis-card` CSS class in index.css (elevated bg, border, shadow, hover state)
- Changed: all card elements across Dashboard, Health, Training, Settings, CTOReport to use `.arcis-card`
- Changed: MetricCard component migrated from inline styles to `.arcis-card`
- Changed: Dashboard cards migrated from `--slate-*` to `--arcis-*` design tokens
- Added: light mode shadow variant for `.arcis-card`

#### .env Secret Migration (Task 7)
- Added: `os.environ.get()` with YAML fallback to 10 modules (telegram, claude_client, 3 Finnhub collectors, macro collector, email notifier, insiders enrichment, news enrichment)
- Added: `TELEGRAM_CHAT_ID` to `.env.example`
- Added: `tests/test_env_secrets.py` with 11 tests covering env precedence, YAML fallback, missing keys, and placeholder detection
- Pattern: `.env` (via `load_dotenv`) takes precedence; YAML config is backward-compatible fallback

#### Documentation (Task 8)
- Updated: CHANGELOG.md with Sprint 6 entry
- Updated: AGENTS.md counts
- Verified: test baseline maintained, frontend builds successfully

---

### Sprint 5: Dashboard Polish & UX

#### Shadow Ledger (Task 1)
- Added: summary row (total positions, unrealized P&L, avg days held)
- Added: P&L values with colorblind-accessible arrows (▲/▼) + `financial-data` class
- Added: alternating row shading via `var(--arcis-bg-elevated)`
- Added: mobile-responsive columns (hide IS bps, strategy on <768px)
- Added: default sort by P&L% descending (best performers at top)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Validation Page (Task 2)
- Added: `validate-system` command to executor (command queue integration)
- Added: error state display when watch loop offline
- Enhanced: fallback from direct API to command queue for validation runs

#### Training Page (Task 3)
- Added: hero section with large total examples count, weekly count, avg quality
- Added: outcome distribution horizontal stacked bar (WIN/LOSS/TIMEOUT/PASS)
- Added: v2 spec targets vs actual comparison grid
- Added: source breakdown bar chart (historical_backfill, blinded_win, etc.)
- Added: ticker coverage progress bar and regime coverage display
- Added: recent examples table (last 10 with ticker, source, outcome, quality, date)
- Added: graceful handling when outcome_type data pending migration

#### CTO Report (Task 4)
- Added: Phase 1 gate progress bar (X/50 trades)
- Added: minimum-data notices ("Requires N+ closed trades" instead of N/A)
- Added: early win rate callout (100% on <10 trades note)
- Changed: fund metrics only shown when 20+ trades available
- Changed: confidence calibration section shows data requirements when <10 trades

#### Docs Page (Task 5)
- Added: sticky mobile back button ("← Back to documents") always visible on mobile
- Added: two-column desktop layout (300px sidebar + content viewer)
- Added: single-column mobile navigation (list → detail → back)
- Added: document viewer max-width 720px for comfortable reading
- Added: file icon indicators and sidebar card styling

#### Notes Page (Task 6)
- Added: tag filter pills at top for quick category filtering
- Added: pinned-first + reverse chronological default sort
- Added: relative date formatting (e.g., "2h ago", "Mar 15")
- Added: empty state with icon ("No notes yet — add your first note above")
- Changed: textarea placeholder to "Add a note..." for cleaner UX

#### Logs Page (Task 7)
- Added: expandable log rows (click to show details_json as formatted JSON)
- Added: "Run Command" dropdown with common commands (scan, council, collect-data, validate)
- Added: command auto-refresh at 10s (faster than logs at 30s)
- Added: empty state messages for both logs and commands
- Added: CRITICAL level background highlighting (red tint)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Settings Page (Task 8)
- Added: section icons (Settings2, Shield, Brain, Clock) from lucide-react
- Added: setting descriptions below each label
- Added: "Saved ✓" animation feedback on setting changes
- Added: reset confirmation dialog (two-step: click → confirm)
- Added: system health items in card-style background tiles
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Backend
- Added: `validate-system` command handler in executor.py
- Test count: 1,110 (unchanged)

### Sprint 4E: Post-Review Cleanup & Production Hardening

#### Database Schema
- Added: `strategy_type` column to shadow_trades (DEFAULT 'pullback')
- Added: `outcome_type` and `regime` columns to training_examples
- Added: `level` column to activity_log (DEFAULT 'INFO')
- Added: `build_score_history` CREATE TABLE to create_missing_tables.py
- Added: scripts/migrate_production_db.py (safe, idempotent migration)
- Backfilled: outcome_type on 969/972 training examples from trade outcomes

#### Watch Loop Fixes
- Fixed: Traffic Light now computed during watch loop scans (was only in scan_service)
- Fixed: VIX read from vix_term_structure DB table instead of relying on vix_proxy feature
- Fixed: scan_metrics now recorded for every scan cycle (success, empty, or failed)
- Fixed: Council failure sends Telegram notification (was silent on error)

#### Robustness
- Fixed: weekly_review.py checks column existence via PRAGMA before querying
- Added: schema health section to weekly review (expected vs actual columns)
- Updated: README.md rewritten for Arcis (75 lines, private-repo focused)

#### Tests
- Added: tests/test_db_migration.py (4 tests: idempotent, adds columns, preserves data, creates tables)
- Added: test_vix_30_6_produces_red_vix_component in test_traffic_light.py
- Test count: 1,105 -> 1,110

### Sprint 4C: Dashboard as Control Plane

#### Command Queue System
- Added: pull-based command queue pattern (pending_commands, command_results, config_overrides, log_entries tables)
- Added: bidirectional sync — cloud pulls commands to local, local pushes results to cloud
- Added: command executor with 10 command types (scan, council, collect-data, halt-trading, etc.)
- Added: 5-minute command expiry, 10/min rate limiting, 10KB result truncation
- Added: DBLogHandler that writes WARNING+ to log_entries table (last 500 entries)

#### Config Override System
- Added: dashboard-editable settings with whitelisted keys only
- Added: config overrides merge with YAML defaults (overrides win for whitelisted keys)
- Added: blocked prefixes for API keys, DB paths, and secrets (never editable remotely)
- Added: "Reset to YAML" to clear all dashboard overrides

#### Cloud API Overhaul
- Changed: all stub action endpoints now submit commands via queue instead of returning "must be done locally"
- Added: POST /api/commands/submit, GET /api/commands/{id}/status, GET /api/commands/recent
- Added: GET /api/logs/recent with level and source filtering
- Added: DELETE /api/settings/overrides to clear all overrides
- Changed: POST /api/settings now submits config_change commands via queue

#### Frontend
- Added: editable Settings page with toggle/number inputs and source badges (yaml default vs dashboard override)
- Added: Logs page with filterable log table and recent commands history
- Added: command pending indicator on Dashboard (blue pulsing badge)
- Added: 14th dashboard page (Logs) to navigation

#### Documentation
- Added: ADR 012 — Pull-based command queue architecture decision
- Updated: AGENTS.md counts (169 Python files, 77 test files, 40 DB tables, 55 API routes)
- Added: 15 tests in test_command_queue.py (submission, expiry, whitelist, rate limiting, round-trip)

## [Unreleased] - 2026-03-27/29

### Weekend Mega Sprint (4 sprints: Stabilize + Hotfix + Build + Document)

#### Critical Safety Fixes
- Fixed: safety checks fail closed on errors, not open (#42)
- Fixed: journal closes after broker confirmation, not before (#41)
- Fixed: LLM validator accepts the real `TradePacket` schema (#40)
- Fixed: paper trades are logged as `failed` on submission failure instead of phantom opens (#46)
- Fixed: `/shadow/close` now requires broker exit semantics for Alpaca-backed trades (#45)
- Fixed: council data gatherers query the correct live column names (#44)
- Fixed: Telegram trade notifications use the real packet fields and source labels (#48)
- Fixed: kill-switch tests and training-ingestion tests now run deterministically against the hardened runtime behavior

#### New Features
- Added: event calendar 0-10 continuous risk scoring with sizing multipliers and Telegram alerts
- Added: bracket order health monitor with intraday, pre-market, and post-close verification
- Added: optional GBNF grammar enforcement path for XML commentary generation
- Added: data quality ingestion gates with duplicate detection and batch halt alerts
- Added: Notes page plus cloud CRUD API for pinned, tagged operator notes
- Added: Council.jsx v2 with new agent identities, consensus labels, strategic prompt input, and parameter adjustment history
- Added: HSHS radar chart and live phase-weight display on the Health page

#### Infrastructure
- Added: `scripts/verify_counts.py` for AGENTS.md count verification
- Added: `scripts/schema_report.py` for canonical SQLite schema reporting
- Added: `scripts/generate_dependency_graph.py` and generated `docs/dependency-graph.md`
- Added: `scripts/render_architecture_doc.py` to regenerate the architecture inventory from live code
- Added: strategy-specific pullback timeout support (15 -> 7 days)
- Added: Render sync coverage for the new notes data path
- Added: `bracket_health` and `user_notes` tables to the working schema
- Fixed: SQLite connection handling in earnings enrichment (#52)
- Fixed: kill-switch path handling so safety remains configurable without leaking ambient state into tests (#47)
- Removed: stale council v1 compatibility wrappers from active code paths

#### Documentation
- Added: 11 architecture decision records under `docs/decisions/`
- Rewrote: `docs/architecture.md` from the live module, route, and schema inventories
- Rewrote: `docs/roadmap.md` to consolidate the confirmed March 28-29, 2026 decisions
- Added: `docs/observation-log-template.md` for the Monday-through-Sunday operating rhythm
- Updated: Framework v2.1 research integration notes for risk budgeting, EDGAR fundamentals, operating cadence, and fund-path deferrals
- Documented: council prompt caching was evaluated and intentionally not enabled because the current agent prompts do not share a reusable long prefix

---

## 2026-03-28 — Reliability Sprint + Research-Informed Features

### Critical Safety Fixes
- Risk governor REJECTS trades on exception (was: approve anyway)
- Drawdown returns 15% conservative estimate on error (was: 0%)
- `train-pipeline` CLI runs full 5-step pipeline (was: empty stub)
- LLM validator REJECTS trades on exception (was: continue)
- Bracket order checks child/leg statuses (was: parent only)

### Wiring & Integration
- `data_integrity.py` → scan pipeline (feature validation pre-ranking)
- `canary.py` → trainer (post-retrain evaluation gate)
- `metrics.py` → CTO report (shared calculations)
- All 12 Telegram notifications wired into watch.py
- 44+ bare `except: pass` → logged at WARNING+
- `overnight.py` consolidated (deleted), `broker.py` deleted

### New Features
- **Traffic Light regime:** VIX(20/30) + 200-DMA(3%) + credit spread(0.5σ/1.5σ) → sizing multiplier. 5-day persistence filter.
- **PEAD enrichment:** 5 earnings signals in pullback prompt (conditional on proximity ≤30 days)
- **Implementation Shortfall:** Signal price capture, IS computation on fill, rolling 20-trade alert
- **HSHS live:** 5-dimension health score from database, wired into CTO report + council + API
- **System validator:** 50+ checks, Validation dashboard page
- Independent live trade monitoring (source_filter parameter)

### Research & Architecture
- 6 new research documents (35 total), all strategy decisions confirmed
- Master blueprint v2, Halcyon Framework v2 updated
- Council redesign architecture finalized (vote-first, value tracking)
- 24 deep research prompts generated

---

## 2026-03-27 — Test Gap Closure (Priority 1 — Critical Money Path)

### New Test Files (6)
- **test_statistics.py** (56 tests) — All 11 statistical functions: Sharpe, PSR, bootstrap CI, profit factor, max drawdown, Sortino, Calmar, win rate test, expectancy test, MinTRL
- **test_gate_evaluator.py** (32 tests) — Gate decision logic (PROCEED/EXTEND/REVISION/ROOT CAUSE), metric thresholds, statistical outputs, format_gate_report, boundary conditions
- **test_change_detector.py** (12 tests) — CUSUM symmetric filter, threshold sensitivity, drift detection, performance drift with real SQLite
- **test_llm_validator.py** (18 tests) — All 6 validation checks: ticker universe, entry price deviation, stop below entry, stop distance bounds, position size cap, conviction range
- **test_filing_nlp.py** (17 tests) — Loughran-McDonald sentiment scoring, cautionary phrase detection, filing delta computation, tech-fundamental divergence
- **test_broker.py** (11 tests) — Broker abstraction, AlpacaAdapter methods, factory function, abstract interface

### Full Test Gap Closure (Priority 2-3)
- **test_backtester.py** (7 tests) — Walk-forward backtest with mocked market data, compare_models winner selection
- **test_services.py** (39 tests) — All 7 service modules: scan, shadow, system, training, review, recap, watchlist
- **test_docs_collector.py** (12 tests) — File scanning, title extraction, category assignment, table population
- **test_data_integrity.py** (21 tests) — Feature validation, trade entry validation, universe validation
- **test_activity_logger.py** (8 tests) — Activity log insertion, metadata, missing table handling
- **test_packet_builders.py** (16 tests) — Template packet builder, watchlist builder, EOD recap builder
- **test_llm_writers.py** (10 tests) — Postmortem writer, watchlist narrative generator
- **test_local_api_routes.py** (24 tests) — Packets, training, scan, review route endpoints
- **test_websocket.py** (7 tests) — ConnectionManager connect/disconnect/broadcast

### Coverage Impact
- Tests: 1,035 (up from 657 baseline, +378 new tests)
- All critical money-path, service layer, utility, and API route modules now tested
- Test files: 69 (up from 52)

---

## 2026-03-27 — Dashboard Hardening + Email Digests

### Error Visibility (Part A)
- Every `except Exception` block in cloud_app.py now has `logger.error()` with endpoint name and exc_info
- Every error response now includes an `"error"` key with the exception message
- New `/api/diagnostics` endpoint tests all 23 dashboard tables and reports pass/fail per table

### Test Coverage (Part B)
- Added 29 new cloud API tests covering all previously untested endpoints
- Coverage: activity feed, live trades/summary, council session detail, health score dimensions, settings, market overview, data asset growth, journal, signal zoo, macro dashboard, research papers/digest, training quality, scan metrics, projections, diagnostics, reconcile, CTO report shape
- Total cloud API tests: 67 (up from 38)

### Email Digests (Part C)
- New `src/email/digest_builder.py` — 4 fund-manager-style digests: pre-market (7:30), midday (12:00), EOD (4:15), evening (8:00)
- New `email_mode: digest` — sends exactly 4 emails per day at configured times
- Digest schedule wired into watch.py main tick loop with daily flag resets
- Per-trade and per-scan emails suppressed in digest mode
- Risk alerts still send immediately regardless of mode
- 15 new tests for all 4 digest builders (empty DB, populated, format)

### Telegram (Part D)
- Trade open/close and risk alerts remain immediate
- Per-scan email spam suppressed in digest mode (Telegram notifications unchanged)

---

## 2026-03-27 — Live Trade Reconciliation

### New Features
- **`reconcile-live` CLI Command** — Detects orphaned Alpaca positions (on broker but not in DB) and stale DB records (in DB but not on broker); backfills or marks closed with `--dry-run` option
- **Live Ledger Reconcile Button** — Disabled button with tooltip showing CLI command for local execution

### Fixes
- **Fractional Shares** — `get_live_positions()`, `get_all_positions()`, `get_position()` in alpaca_adapter now use `float(qty)` instead of `int(qty)` to support fractional share positions

### Backend
- New `POST /api/live/reconcile` endpoint (returns cloud_mode error — local CLI only)
- New `src/shadow_trading/reconcile.py` module with `reconcile_live_trades()` function

### Tests
- 5 new tests: dry-run safety, orphan backfill, stale marking, no-discrepancy, paper-trade isolation

---

## 2026-03-27 — Dashboard Polish Sprint

### New Features
- **Research Docs on Cloud** — 35+ markdown docs served via `research_docs` Postgres table with category sidebar and search
- **Council Session Detail View** — Expandable session rows with full agent vote cards, vote distribution chart, dissent highlighting
- **Activity Feed Cloud Polling** — Polling fallback for cloud mode (60s) with event-type icons
- **Live Trade Ledger** — New page for $100 Alpaca live account with equity curve, open/closed tables, header metrics
- **Shadow Ledger Enhancements** — Metrics strip (equity, PF, DD), expandable trade detail rows, 4 viz tabs (equity curve, distribution, sector heatmap, calendar)
- **Hardware Roadmap** — Phase 2 and Phase 4 build specs with costs and unlock descriptions
- **Monthly Cost Timeline** — Visual bar chart of per-phase monthly costs

### Fixes
- **Audit Banner** — Parses raw JSON/code fences from audit summary, shows clean text
- **Shadow Equity** — Uses `shadow/account` endpoint (starting_capital + closed_pnl) instead of potentially wrong `alpaca_equity`
- **KPI Thresholds** — Sharpe/Win Rate show with >= 2 trades (was >= 5)
- **Confidence Calibration** — Shows "< X/50 trades" instead of "--"
- **Rubric Score** — Shows "Not scored yet" with tooltip instead of "n/a"
- **Health Score Dimensions** — All 5 dimensions (Performance, Model Quality, Data Asset, Flywheel, Defensibility) now computed from real data with metric breakdowns
- **Review Tab Removed** — Replaced with Live Ledger in sidebar navigation

### Backend
- 8 new cloud API endpoints: `/api/council/session/{id}`, `/api/activity/feed`, `/api/live/trades`, `/api/live/summary`, `/api/settings` (GET/POST), updated `/api/docs`, `/api/health/score`
- `research_docs` table added to sync pipeline
- Research synthesis wired to Sunday 6 PM schedule
- Daily metric snapshots at 4 PM EOD (not just Saturday)
- Nightly Telegram notification for new research papers

### Components
- New `Tooltip.jsx` — Hover tooltip with 300ms delay
- New `LiveLedger.jsx` — Full live trading ledger page
- Updated `ActivityFeed.jsx` — Cloud polling fallback + event icons
- Updated `Council.jsx` — Expandable session rows
- Updated `ShadowLedger.jsx` — Enhanced with viz tabs + trade expansion

### Roadmap
- Updated to 6 phases (added Phase 6 — Multi-Desk Expansion)
- Phase costs updated: $64 → $125 → $155 → $220 → $500+
- Hardware roadmap section added
