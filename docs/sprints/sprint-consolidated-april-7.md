# Consolidated Sprint Package -- April 7, 2026 (v2)

> **5 sprints in execution order.** Ralph Looped 6x total (3 by author, 3 additional on v2).
>
> Sprint 1 and 2 can run in parallel (zero file overlap verified -- see note in Pass 6).
> Sprint 3 and 4 can run in parallel after 1+2 merge.
> Sprint 5 runs last -- full codebase refactor baseline.

---

## MANDATORY CC RULES -- APPLY TO ALL 5 SPRINTS

These rules are non-negotiable. Violating any of them is a sprint failure.

### Rule 1: Read Before Write
Before modifying ANY file, read the ENTIRE file. Not grep, not head/tail -- the full file. If the file is over 500 lines, read it in 500-line chunks until you have seen every line. You cannot fix what you have not read.

### Rule 2: Validate Every Character
After every file modification, re-read the modified file and verify:
- No stubs, TODOs, placeholder data, or pass statements in new code
- No commented-out code left behind
- No print() statements (use logger)
- No hardcoded paths, keys, or credentials
- All imports resolve (run python -c "import src.MODULE" for each touched module)
- All string literals are correct (no typos in table names, column names, status values)

### Rule 3: Document Every Assumption
If at ANY point during execution you are unsure about what a function does, what format data is in, whether a table/column exists, or what the caller expects -- you MUST: (a) investigate until you know, or (b) document the assumption explicitly in your commit message AND in the PR description under a section called "## Assumptions Made". Never silently guess.

### Rule 4: Test Before AND After
Before any changes: python -m pytest tests/ -x -q (record exact pass/fail count)
After all changes: python -m pytest tests/ -x -q (must match or exceed)
Frontend: cd frontend && npm run build && cd ..
If pass count drops or new failures appear, FIX THEM before committing.

### Rule 5: Atomic Commits
One logical change per commit. Never combine a bug fix with a feature addition. Every commit message must reference the issue number or task number.

### Rule 6: PR Description Template
Every PR must include: Summary, Files Changed (every file with 1-line description), Assumptions Made (list every assumption or "None -- all behavior verified against code"), Test Results (before/after counts + new tests), and Validation Checklist (read every file, imports verified, no stubs, frontend builds, MASTER.md updated).

---

## Sprint 1: Production Hotfixes (#318-321)

> **Priority:** CRITICAL -- live-money bugs
> **Branch:** fix/production-hotfixes-april
> **Tag:** v0.14.3
> **Closes:** #318, #319, #320, #321
> **Files touched:** src/llm/packet_writer.py, src/shadow_trading/executor.py, src/shadow_trading/alpaca_adapter.py, src/shadow_trading/reconcile.py, src/cli/commands.py, src/journal/store.py, + new/extended test files

### Pre-Flight

git checkout main && git pull origin main
git checkout -b fix/production-hotfixes-april
python -m pytest tests/ -x -q   # Record exact pass count
cd frontend && npm run build && cd ..

### Task 1: Fix LLM conviction parsing regression (#318)

**Root cause hypothesis:** The conviction parse cascade in _parse_llm_response() (line 252 of src/llm/packet_writer.py) has 5 strategies. The LIKELY bug path is: when parse fails entirely (why_now=None), the template fallback at line 490 returns the original packet WITHOUT setting packet.llm_conviction. Conviction stays None from packet construction, bypasses the default-to-5 logic at line 495, and leaks into the executor.

**Investigation steps (CC must do ALL of these):**

1. Read src/llm/packet_writer.py in full (535 lines).
2. Read _parse_llm_response (line 252-401). Document exactly what the 5 parse strategies look for. Verify this list matches the ACTUAL code. If it differs, document what the code actually does.
3. Read enhance_packet_with_llm (line ~440-535). Trace the exact flow:
   - Line 488: conviction, why_now, deeper_analysis = _parse_llm_response(response)
   - Line 490: if why_now is None or deeper_analysis is None -> return packet
   - Line 495: if conviction is None -> conviction = 5
   - Line 519: packet.llm_conviction = conviction
   KEY: When the template fallback fires at line 490, the function returns BEFORE reaching line 495 or 519. The packet llm_conviction is never set. Verify this is the actual code path.
4. Pull 5 recent raw LLM responses to verify what the model actually outputs:
   SELECT ticker, raw_llm_response FROM recommendations WHERE raw_llm_response IS NOT NULL ORDER BY created_at DESC LIMIT 5;
   If the column name is not raw_llm_response, check the schema registry. Document what format the model produces.

**Fix:**
1. In the template fallback path (line 490), before return packet, add: packet.llm_conviction = 5 with a warning log.
2. If model output format does not match any of the 5 strategies: add a 6th strategy. Include test with real v1 response as fixture.
3. Add defensive guard in open_shadow_trade (executor.py, ~line 200 inside function body): if conviction is None, default to 5 with warning log.
4. Verify open_live_trade (executor.py line 1222-1224) already rejects None. Confirm and document.

**Tests:** Parse with actual v1 format, template fallback sets conviction=5, open_shadow_trade handles None.

### Task 2: Fix paper positions flipped to short (#319)

**Root cause hypothesis:** Entry hardcodes direction="long" (line 353) and OrderSide.BUY (alpaca_adapter line 285). Short positions likely from reconciliation.

**Investigation steps (CC must do ALL):**
1. Read executor.py in full (1,775 lines). Search for OrderSide.SELL, side.*sell, "short", negative quantity. Document every occurrence.
2. Read alpaca_adapter.py in full (631 lines). Verify place_bracket_order (line ~258) and place_paper_entry (line ~178) ALWAYS use OrderSide.BUY.
3. Read reconcile.py in full (490 lines). Check reconcile_paper_trades -- does it insert new trade rows? Does it check position side?
4. Query actual short positions:
   SELECT trade_id, ticker, direction, planned_shares, status, source, created_at FROM shadow_trades WHERE direction != 'long' OR planned_shares < 0;
   Document findings in PR.

**Fix:**
1. Add validation in insert_shadow_trade (journal/store.py line 147): raise ValueError if direction != "long".
2. If reconciliation is the source: add guard skipping negative-qty positions.
3. Fix existing erroneous rows ONLY after investigation confirms they are erroneous. Document evidence.

### Task 3: Fix executor cross-broker mismatch (#320)

1. Read check_and_manage_open_trades (executor.py line 641-1139). Verify source_filter SQL WHERE clause.
2. Read _submit_exit_order (line 115-133). Does it know paper vs live? Does it route to correct broker?
3. Read position_monitor.py (72 lines). Verify source_filter="paper" and source_filter="live" calls.
4. Fix: if _submit_exit_order always uses paper, add source awareness via broker_factory for live trades.

### Task 4: Fix UnicodeEncodeError in reconcile-live CLI (#321)

1. Read cmd_reconcile_live (commands.py line 403-420). Check if uses safe_print or raw print().
2. Replace raw print() with safe_print (defined at commands.py line 78).
3. Verify safe_print handles emoji with errors="replace".

### Post-Flight

python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
git tag -a v0.14.3 -m "v0.14.3 -- 4 production hotfixes (#318-321)"
git push origin fix/production-hotfixes-april && git push origin v0.14.3

Documentation: MASTER.md (close #318-321, 7->3 open), RELEASES.md, CHANGELOG.md

---

## Sprint 2: Attribution Pipeline Wiring

> **Priority:** HIGH -- existential validation has zero data flowing
> **Branch:** feat/attribution-wiring
> **Files touched:** src/services/scan_service.py, src/attribution/logger.py, src/shadow_trading/executor.py (line ~1093, NOT line ~140 which Sprint 1 owns), src/api/ routes, tests/test_attribution.py

### Pre-Flight

git checkout main && git pull origin main
git checkout -b feat/attribution-wiring
python -m pytest tests/ -x -q
Confirm attribution_trades has 0 rows.

### Context: Read ALL before writing code
1. src/attribution/logger.py (243 lines) -- all functions exist but none are called
2. src/services/scan_service.py (259 lines) -- candidate loop at line 168
3. src/shadow_trading/executor.py (1,775 lines) -- trade closure at line ~1060-1095
4. src/schema/registry.py -- attribution_trades table (16 columns)
5. frontend/src/pages/Attribution.jsx (157 lines)
6. tests/test_attribution.py
7. src/scheduler/watch.py line 1388-1395 -- resolve_pending_outcomes already scheduled

### Task 1: Wire Phase 1+2 into scan_service.py

Insertion point: inside for candidate in packet_worthy_raw: loop (line 168).

Current flow: line 176 build_packet, line 177 enhance_packet_with_llm, line 184 log_recommendation, line 198 open_shadow_trade.

Add BEFORE line 176: log_attribution_before_llm(ticker, ranker_score, entry_price, stop_price, target_price). Wrapped in try/except -- attribution must NEVER block trades.

Add AFTER line 177: log_attribution_after_llm(attribution_id, llm_action, conviction). Determine action: "taken" if conviction > 0, "conviction_none" if None, "rejected" otherwise.

Add AFTER line 184: update attribution row with rec_id.

ASSUMPTION CHECK: The feat dict must contain current_price, stop_invalidation, target_1. CC MUST read build_packet_from_features in src/packets/template.py to verify these key names. If different, use actual names and document in PR.

### Task 2: Wire trade closure into attribution

Insertion point: executor.py line ~1093, after actions.append(action).

Add link_trade_outcome(recommendation_id=rec_id, outcome="win"/"loss"/"timeout", pnl_pct=pnl_pct).

New function in src/attribution/logger.py:
def link_trade_outcome(recommendation_id, outcome, pnl_pct, db_path=DB_PATH):
    UPDATE attribution_trades SET llm_portfolio_outcome=?, llm_portfolio_pnl_pct=? WHERE recommendation_id=?

Also wire for MR closures (executor.py line 757-775). CC must verify rec_id is in scope.

### Task 3: Verify watch loop resolution (lines 1385-1400)
### Task 4: Verify API endpoints and Attribution.jsx
### Task 5: Tests -- full pipeline mock, failure isolation, link_trade_outcome, resolve_pending

Post-flight: verify attribution wiring with grep. Push branch.
Documentation: MASTER.md attribution -> LIVE, note data collection start date.

---

## Sprint 3: Simulation Engine Promotion

> **Branch:** refactor/simulation-promotion

Read FIRST: scripts/simulation_engine.py (706), src/simulation/ (153), tests, Simulation.jsx (350), watch.py line 3251-3277.

Extract core engine into src/simulation/engine.py (under 400 lines -- split into regimes.py + validation.py if needed). Script becomes thin CLI wrapper. Update watch.py stub. Backward compat: scripts/simulation_engine.py --dry-run must still work.

---

## Sprint 4: Mean Reversion End-to-End Integration

> **Branch:** feat/mr-integration

Read FIRST: mean_reversion.py (194), executor.py MR exit (749-800), scan_service.py, prompts.py, setup_classifier.py (line 214), config strategies.mean_reversion.

Task 1: Create src/services/mr_scan_service.py (NOT in watch.py). Function run_mr_scan(config, dry_run) that calls scan_for_mr_candidates, builds MR packets, opens MR trades. Respect paper_only, max_positions.

Task 2: Wire into watch.py via _safe_run after main scan.

Task 3: MR trade opening -- add strategy_type="mean_reversion" to shadow_trades row. MR trades do NOT use bracket orders. CC must choose: add param to open_shadow_trade or create new function. Document why.

Task 4: MR-specific LLM prompts in prompts.py. Wire via setup_type check. ASSUMPTION TO VERIFY: does features dict contain setup_type when reaching packet_writer? Trace through engine.py -> setup_classifier -> scan_service.

Task 5: Verify training data_collector preserves strategy_type.
Task 6: Tests -- new test_mr_scan_service.py, MR trade opening, MR prompt routing.

---

## Sprint 5: Codebase Refactor Baseline

> **Branch:** refactor/codebase-baseline
> **Tag:** v0.15.1

### Pre-Flight: Capture exact baseline to docs/audits/refactor-baseline-2026-04.md

### Task 1: Extract overnight functions from watch.py -> src/scheduler/overnight.py (~630 lines)

Functions (verified line numbers):
_run_post_close_capture (2062-2129, 67 lines)
_run_overnight_training_collection (2131-2165, 34)
_run_news_ingestion (2167-2198, 31)
_run_enrichment_precache (2200-2230, 30)
_run_pre_market_refresh (2232-2258, 26)
_run_data_collection (2260-2468, 208)
_run_evening_handoff (2479-2510, 31)
_run_morning_handoff (2512-2550, 38)
_run_premarket_rolling_features (3203-3208, 5)
_run_premarket_training (3210-3219, 9)
_run_premarket_news_scoring (3221-3226, 5)
_run_premarket_candidates (3228-3233, 5)
_run_stress_test (3235-3249, 14)
_run_simulation_engine (3251-3277, 26)
_run_research_synthesis (3279-3313, 34)
_save_daily_metric_snapshot (3315-3382, 67)

Extraction rules: self.config -> config parameter. Return bool for done-flag handling. Move imports. Call pattern: self._safe_run(name, lambda: overnight.func(self.config)). ZERO behavior change.

### Task 2: Extract reporting from watch.py -> src/scheduler/reports.py (~628 lines)

Functions (verified):
_run_saturday_reports (1942-2020, 78)
_send_premarket_brief (2641-2764, 123)
_send_eod_report (2766-2878, 112)
_send_data_asset_report (2880-2931, 51)
_check_vix_regime_alert (2933-2988, 55)
_send_weekly_digest (2990-3150, 160)
_check_earnings_proximity (3152-3201, 49)

Expected watch.py after Tasks 1+2: ~3,382 - 630 - 628 = ~2,124 lines

### Task 3: Split telegram.py (1,563 lines, 55 functions) into 4 files

telegram_core.py (~200 lines): _get_telegram_config (85), is_telegram_enabled (100), send_telegram (106), poll_commands (717), handle_command (922), all _cmd_* functions

telegram_trades.py (~200 lines): notify_trade_opened (144), notify_trade_closed (177), notify_milestone (530), notify_streak_alert (536), notify_exposure_alert (679), notify_position_earnings_warning (693)

telegram_system.py (~250 lines): notify_startup_complete (242), notify_system_event (234), notify_scan_complete (191), notify_risk_alert (207), notify_overnight_complete (222), notify_model_event (301), notify_vram_handoff (354), notify_validation_summary (1448), notify_collection_failure (661), notify_action_required (772), check_action_reminders (783)

telegram_reports.py (~300 lines): notify_daily_summary (287), notify_watchlist (312), notify_scan_result (329), notify_premarket_complete (340), notify_premarket_brief (406), notify_first_scan_summary (436), notify_eod_report (463), notify_data_asset_report (490), notify_regime_alert (511), notify_weekly_digest (552), notify_retrain_report (609), notify_scoring_summary (380), notify_schedule_health (390), notify_overnight_training_complete (366), notify_earnings_warning (213), notify_research_papers (634), notify_research_digest (649)

Update __init__.py to re-export all public functions for backward compat. Grep codebase for all telegram imports. Delete original ONLY after all imports resolve.

### Task 4: Update known_violations.json from actual state
### Task 5: Measure improvement -- append before/after table to baseline doc

### Post-Flight
All tests pass. Frontend builds. Import walker finds no broken modules. Tag v0.15.1.

---

## Execution Order

Phase 1 (parallel): Sprint 1 + Sprint 2
Phase 2 (merge): v0.14.3 + v0.15.0
Phase 3 (parallel): Sprint 3 + Sprint 4
Phase 4 (merge): features consolidated
Phase 5 (sequential): Sprint 5 -> v0.15.1

File overlap note: Sprints 1 and 2 both touch executor.py but 950 lines apart (Sprint 1: ~line 140, Sprint 2: ~line 1093). Safe but CC should be aware.

---

## Ralph Loop Verification

### Author Pass 4 (v2 iteration 1):
- Added 6 mandatory CC rules with PR template requiring Assumptions section
- Sprint 1 Task 1: identified actual bug path (template fallback at line 490)
- Sprint 2: exact insertion points in scan_service.py line 168 candidate loop
- Sprint 4: creates mr_scan_service.py instead of adding to watch.py
- Sprint 5: verified line numbers for every extraction target

### Author Pass 5 (v2 iteration 2):
- Sprint 1 Task 2: added DB query to investigate short positions before fixing
- Sprint 2 Task 1: ASSUMPTION CHECK for feat dict key names
- Sprint 4 Task 4: assumption verification for setup_type in features dict
- Sprint 5 Task 3: __init__.py re-export + grep verification command

### Author Pass 6 (v2 iteration 3):
- File overlap: Sprints 1+2 both touch executor.py, 950 lines apart (safe)
- Sprint 5 Task 1: self.config -> config parameter conversion documented
- Sprint 5: expected watch.py size = 3,382 - 630 - 628 = 2,124
- Sprint 5: post-flight import walker to catch broken modules
- All sprints: read ENTIRE file as hard requirement
