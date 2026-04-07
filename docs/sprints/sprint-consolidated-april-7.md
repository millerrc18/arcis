# Consolidated Sprint Package -- April 7, 2026 (v2)

> **5 sprints in execution order.** Ralph Looped 6x total (3 by author, 3 additional on v2).
>
> Sprint 1 and 2 can run in parallel (zero file overlap verified).
> Sprint 3 and 4 can run in parallel after 1+2 merge.
> Sprint 5 runs last -- full codebase refactor baseline.

---

## MANDATORY CC RULES -- APPLY TO ALL 5 SPRINTS

These rules are non-negotiable. Violating any of them is a sprint failure.

### Rule 1: Read Before Write
Before modifying ANY file, read the ENTIRE file. Not grep, not head/tail -- the full file. If the file is over 500 lines, read it in 500-line chunks until you have seen every line. You cannot fix what you have not read.

### Rule 2: Validate Every Character
After every file modification, re-read the modified file and verify:
- No stubs, TODOs, placeholder data, or `pass` statements in new code
- No commented-out code left behind
- No `print()` statements (use `logger`)
- No hardcoded paths, keys, or credentials
- All imports resolve (run `python -c "import src.MODULE"` for each touched module)
- All string literals are correct (no typos in table names, column names, status values)

### Rule 3: Document Every Assumption
If at ANY point during execution you are unsure about what a function does, what format data is in, whether a table/column exists, or what the caller expects -- you MUST: (a) investigate until you know, or (b) document the assumption explicitly in your commit message AND in the PR description under a section called `## Assumptions Made`. Never silently guess.

### Rule 4: Test Before AND After
```bash
python -m pytest tests/ -x -q 2>&1 | tail -5  # BEFORE: Record exact count
cd frontend && npm run build 2>&1 | tail -3 && cd ..
# ... make changes ...
python -m pytest tests/ -x -q 2>&1 | tail -5  # AFTER: Must match or exceed
cd frontend && npm run build 2>&1 | tail -3 && cd ..
```

### Rule 5: Atomic Commits
One logical change per commit. Every commit message must reference the issue or task number.

### Rule 6: PR Description Template
Every PR must include:
```
## Summary
[2-3 sentences]
## Files Changed
[Every file with 1-line description]
## Assumptions Made
[Every assumption, or "None -- all behavior verified against code"]
## Test Results
- Before: X passed, Y failed
- After: X passed, Y failed
- New tests added: Z
## Validation Checklist
- [ ] Read every modified file in full after changes
- [ ] All imports verified
- [ ] No stubs, TODOs, or placeholder data
- [ ] Frontend builds cleanly
- [ ] MASTER.md updated
```

---

## Sprint 1: Production Hotfixes (#318-321)

> **Priority:** CRITICAL -- live-money bugs
> **Branch:** `fix/production-hotfixes-april`
> **Tag:** v0.14.3
> **Closes:** #318, #319, #320, #321
> **Files:** `src/llm/packet_writer.py`, `src/shadow_trading/executor.py`, `src/shadow_trading/alpaca_adapter.py`, `src/shadow_trading/reconcile.py`, `src/cli/commands.py`, `src/journal/store.py`

### Pre-Flight
```bash
git checkout main && git pull origin main
git checkout -b fix/production-hotfixes-april
python -m pytest tests/ -x -q   # Record: ____
cd frontend && npm run build && cd ..
```

### Task 1: Fix LLM conviction parsing regression (#318)

**Root cause hypothesis:** When LLM parse fails entirely (why_now=None), the template fallback at packet_writer.py line 490 returns the original packet WITHOUT setting `packet.llm_conviction`. Conviction stays None, bypasses the default-to-5 at line 495, and leaks into the executor.

**Investigation (do ALL):**
1. Read `src/llm/packet_writer.py` in full (535 lines)
2. Read `_parse_llm_response` (line 252-401). Document all 5 parse strategies
3. Read `enhance_packet_with_llm` (line ~440-535). Trace: line 488 calls parse, line 490 returns early if why_now=None (BEFORE line 495 default and line 519 assignment). VERIFY this is the actual path
4. Pull 5 recent raw responses: `SELECT ticker, raw_llm_response FROM recommendations WHERE raw_llm_response IS NOT NULL ORDER BY created_at DESC LIMIT 5`

**Fix:**
1. Line 490 template fallback: add `packet.llm_conviction = 5` before `return packet`
2. If model format doesnt match any strategy: add 6th with real v1 fixture
3. Executor defense in `open_shadow_trade` (~line 170): guard conviction=None
4. Verify `open_live_trade` (line 1222-1224) already rejects None

**Tests:** parse with v1 format, template fallback sets conviction=5, executor handles None

### Task 2: Fix paper positions flipped to short (#319)

**Investigation (do ALL):**
1. Read executor.py in full (1775 lines). Search for OrderSide.SELL, "sell", "short", negative qty
2. Read alpaca_adapter.py in full (631 lines). Verify BUY on entries
3. Read reconcile.py in full (490 lines). Check if backfill creates rows with negative qty
4. Query DB: `SELECT trade_id, ticker, direction, planned_shares, status, source FROM shadow_trades WHERE direction != 'long' OR planned_shares < 0 OR direction IS NULL`

**Fix:**
1. Assert direction="long" in `insert_shadow_trade` (journal/store.py line 147)
2. Guard reconciliation against negative qty
3. Fix erroneous rows only after investigation confirms source

**Tests:** insert rejects direction != "long", reconciliation skips negative qty

### Task 3: Fix executor cross-broker mismatch (#320)

**Investigation:**
1. Read `check_and_manage_open_trades` (executor.py line 641-1139). Verify source_filter SQL
2. Read `_submit_exit_order` (line 115-133). Does it know paper vs live?
3. Read position_monitor.py (72 lines). Verify source_filter params

**Fix:** If _submit_exit_order ignores trade source, add routing via broker_factory for live, direct adapter for paper

### Task 4: Fix UnicodeEncodeError (#321)

1. Read cmd_reconcile_live (commands.py line 403-420). Replace print() with safe_print
2. Check emoji at line ~1028. Route through safe_print

### Post-Flight
```bash
python -m pytest tests/ -x -q && cd frontend && npm run build && cd ..
git tag -a v0.14.3 -m "v0.14.3 -- 4 production hotfixes (#318-321)"
git push origin fix/production-hotfixes-april && git push origin v0.14.3
```
Documentation: MASTER.md (close #318-321, 7->3 issues), RELEASES.md, CHANGELOG.md

---

## Sprint 2: Attribution Pipeline Wiring

> **Priority:** HIGH -- existential validation has zero data
> **Branch:** `feat/attribution-wiring`
> **Files:** `src/services/scan_service.py`, `src/attribution/logger.py`, `src/shadow_trading/executor.py` (line ~1093 ONLY), API routes, tests
> **Note:** Sprint 1 owns executor.py line ~140. Sprint 2 owns line ~1093. 950 lines apart.

### Pre-Flight
```bash
git checkout main && git pull origin main
git checkout -b feat/attribution-wiring
python -m pytest tests/ -x -q
python3 -c "import sqlite3; from src.config import DB_PATH; c=sqlite3.connect(DB_PATH); print(f'attribution rows: {c.execute(\"SELECT COUNT(*) FROM attribution_trades\").fetchone()[0]}')"
```

### Read FIRST: logger.py (243 lines), scan_service.py (259 lines), executor.py trade closure (~1060-1095), Attribution.jsx (157 lines), test_attribution.py, watch.py 1388-1395

### Task 1: Wire Phase 1+2 into scan_service.py

Insert into `for candidate in packet_worthy_raw:` loop (line 168):
- BEFORE line 176: `log_attribution_before_llm(ticker, score, entry, stop, target)`
- AFTER line 177: `log_attribution_after_llm(attribution_id, action, conviction)`
- AFTER line 184: update attribution with rec_id

**ASSUMPTION CHECK:** Verify feat dict keys `current_price`, `stop_invalidation`, `target_1` exist by reading `src/packets/template.py`. Use actual names if different. Document.

All calls wrapped in try/except. Attribution NEVER blocks trade execution.

### Task 2: Wire trade closure

Add `link_trade_outcome(recommendation_id, outcome, pnl_pct)` call at executor.py ~line 1093 after `actions.append(action)`. Also wire at MR closure (line ~757-775). Create `link_trade_outcome()` in logger.py.

### Task 3: Verify watch loop resolution (lines 1388-1395)
### Task 4: Verify/create API endpoint + dashboard
### Task 5: Tests (pipeline mock, failure isolation, link_trade_outcome, resolve)

### Post-Flight
```bash
python -m pytest tests/ -x -q && cd frontend && npm run build && cd ..
python3 -c "s=open('src/services/scan_service.py').read(); assert 'log_attribution_before' in s; assert 'log_attribution_after' in s; print('OK')"
git push origin feat/attribution-wiring
```
Documentation: MASTER.md (attribution LIVE), data collection start date noted

---

## Sprint 3: Simulation Engine Promotion

> **Branch:** `refactor/simulation-promotion`

### Read FIRST: scripts/simulation_engine.py (706), src/simulation/ (153), tests, Simulation.jsx (350), watch.py 3251-3277

### Tasks:
1. Read and document current state before any code
2. Extract core engine into src/simulation/engine.py (under 400 lines; split into regimes.py + validation.py if needed)
3. Script becomes thin wrapper importing from module
4. Update watch.py _run_simulation_engine to import from module
5. Backward compat: `python scripts/simulation_engine.py --dry-run` still works
6. All existing tests pass + new module import test

---

## Sprint 4: Mean Reversion End-to-End Integration

> **Branch:** `feat/mr-integration`

### Read FIRST: mean_reversion.py (194), executor.py MR exit (749-800), scan_service.py (259), prompts.py (233), setup_classifier.py (325 line 214), config strategies.mean_reversion

### Tasks:
1. Create `src/services/mr_scan_service.py` (do NOT add to watch.py). `run_mr_scan(config, dry_run)` calls scan_for_mr_candidates, builds packets, opens trades. Respects paper_only and max_positions
2. Wire into watch.py after main scan via _safe_run
3. MR trade opening: add strategy_type to open_shadow_trade OR create open_mr_shadow_trade (CC chooses, documents why). MR uses simple market order, no brackets. strategy_type="mean_reversion" in DB row
4. MR LLM prompts: add get_mr_system_prompt() to prompts.py. Wire via setup_type check. VERIFY setup_type reaches packet_writer by tracing engine -> classifier -> scan_service -> packet_writer
5. Training data: verify data_collector preserves strategy_type from shadow_trades
6. Tests: test_mr_scan_service.py (new), opening sets strategy_type, exit fires, prompt routing

---

## Sprint 5: Codebase Refactor Baseline

> **Branch:** `refactor/codebase-baseline`
> **Tag:** v0.15.1

### Pre-Flight: Capture exact baseline to docs/audits/refactor-baseline-2026-04.md

### Task 1: Extract overnight functions from watch.py (~630 lines -> src/scheduler/overnight.py)

| Function | Lines | Size |
|----------|-------|------|
| _run_post_close_capture | 2062-2129 | 67 |
| _run_overnight_training_collection | 2131-2165 | 34 |
| _run_news_ingestion | 2167-2198 | 31 |
| _run_enrichment_precache | 2200-2230 | 30 |
| _run_pre_market_refresh | 2232-2258 | 26 |
| _run_data_collection | 2260-2468 | 208 |
| _run_evening_handoff | 2479-2510 | 31 |
| _run_morning_handoff | 2512-2550 | 38 |
| _run_premarket_rolling_features | 3203-3208 | 5 |
| _run_premarket_training | 3210-3219 | 9 |
| _run_premarket_news_scoring | 3221-3226 | 5 |
| _run_premarket_candidates | 3228-3233 | 5 |
| _run_stress_test | 3235-3249 | 14 |
| _run_simulation_engine | 3251-3277 | 26 |
| _run_research_synthesis | 3279-3313 | 34 |
| _save_daily_metric_snapshot | 3315-3382 | 67 |

Rules: self.config -> config param, return bool, watch.py sets done-flag. ZERO behavior change.

### Task 2: Extract reporting from watch.py (~628 lines -> src/scheduler/reports.py)

| Function | Lines | Size |
|----------|-------|------|
| _run_saturday_reports | 1942-2020 | 78 |
| _send_premarket_brief | 2641-2764 | 123 |
| _send_eod_report | 2766-2878 | 112 |
| _send_data_asset_report | 2880-2931 | 51 |
| _check_vix_regime_alert | 2933-2988 | 55 |
| _send_weekly_digest | 2990-3150 | 160 |
| _check_earnings_proximity | 3152-3201 | 49 |

Expected watch.py after: ~3382 - 630 - 628 = ~2124 lines

### Task 3: Split telegram.py (1563 lines, 55 functions) into 4 files

**telegram_core.py** (~200 lines): _get_telegram_config(85), is_telegram_enabled(100), send_telegram(106), poll_commands(717), handle_command(922), all _cmd_* functions

**telegram_trades.py** (~200 lines): notify_trade_opened(144), notify_trade_closed(177), notify_milestone(530), notify_streak_alert(536), notify_exposure_alert(679), notify_position_earnings_warning(693)

**telegram_system.py** (~250 lines): notify_startup_complete(242), notify_system_event(234), notify_scan_complete(191), notify_risk_alert(207), notify_overnight_complete(222), notify_model_event(301), notify_vram_handoff(354), notify_validation_summary(1448), notify_collection_failure(661), notify_action_required(772), check_action_reminders(783)

**telegram_reports.py** (~300 lines): notify_daily_summary(287), notify_watchlist(312), notify_scan_result(329), notify_premarket_complete(340), notify_premarket_brief(406), notify_first_scan_summary(436), notify_eod_report(463), notify_data_asset_report(490), notify_regime_alert(511), notify_weekly_digest(552), notify_retrain_report(609), notify_scoring_summary(380), notify_schedule_health(390), notify_overnight_training_complete(366), notify_earnings_warning(213), notify_research_papers(634), notify_research_digest(649)

Update __init__.py to re-export all public functions. Grep all import sites:
```bash
grep -rn "from src.notifications.telegram import" src/ tests/ | grep -v __pycache__ | grep -v telegram_
```
Delete original only after all imports verified.

### Task 4: Update known_violations.json from actual state
### Task 5: Measure improvement, append to baseline doc

### Post-Flight
```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
python3 -c "
import importlib, pkgutil
for _,m,_ in pkgutil.walk_packages(['src'],prefix='src.'):
    try: importlib.import_module(m)
    except Exception as e: print(f'BROKEN: {m}: {e}'); exit(1)
print('All modules OK')
"
git tag -a v0.15.1 -m "v0.15.1 -- codebase refactor baseline"
git push origin refactor/codebase-baseline && git push origin v0.15.1
```

---

## Execution Order

```
Phase 1 (parallel):  Sprint 1 (fix/) + Sprint 2 (feat/attribution)
Phase 2 (merge):     v0.14.3 + v0.15.0
Phase 3 (parallel):  Sprint 3 (refactor/sim) + Sprint 4 (feat/mr)
Phase 4 (merge):     all features consolidated
Phase 5 (last):      Sprint 5 (refactor/baseline) -> v0.15.1
```

---

## Ralph Loop Verification

### Pass 4 (v2 iteration 1):
- Added 6 mandatory CC rules + PR template with Assumptions section
- Sprint 1 Task 1: identified actual bug path (line 490 returns before line 495)
- Sprint 2: exact insertion points with code snippets
- Sprint 4: mr_scan_service.py instead of bloating watch.py
- Sprint 5: verified line numbers for all 23 extraction targets

### Pass 5 (v2 iteration 2):
- Sprint 1 Task 2: DB query to investigate shorts before fixing
- Sprint 2: ASSUMPTION CHECK for feat dict keys
- Sprint 4: VERIFY setup_type reaches packet_writer
- Sprint 5: __init__.py re-export + grep verification command

### Pass 6 (v2 iteration 3):
- Executor.py overlap verified: Sprint 1 at ~140, Sprint 2 at ~1093 (safe)
- Sprint 5: self.config -> config parameter conversion documented
- Sprint 5: expected watch.py = 3382 - 630 - 628 = 2124 lines
- Sprint 5: post-flight module import walker added
- All sprints: read ENTIRE file before modifications (hard requirement)
