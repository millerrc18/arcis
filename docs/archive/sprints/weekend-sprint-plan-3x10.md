# Weekend Sprint Plan — 3 Sprints to Clean Codebase
# Saturday AM → Saturday PM → Sunday Morning
# Go into next week completely clean and ready to test

---

# ══════════════════════════════════════════════════════════════
# SPRINT 1: STABILIZE (Saturday Morning — Ryan + Claude together)
# ══════════════════════════════════════════════════════════════
# Max 10 tasks. All about making what exists work correctly.

## Pre-read:
```
cat src/council/agents.py src/council/protocol.py src/council/engine.py src/council/value_tracker.py
cat tests/test_council.py tests/test_council_agents.py
cat src/sync/render_sync.py scripts/render_migrate.py
cat src/shadow_trading/executor.py  # bracket order TIF
```

## Task 1: Verify bracket orders use GTC
**WHY:** If brackets use time_in_force="day", stops expire at 4 PM daily. Positions unprotected overnight.
```python
# Run on your machine:
from src.shadow_trading.alpaca_adapter import get_api
api = get_api()
for o in api.list_orders(status="open"):
    print(f"{o.symbol}: tif={o.time_in_force}")
```
If ANY say "day" → change to "gtc" in executor.py bracket submission and re-submit all open orders.

## Task 2: Merge CC's compatible cleanup changes
Cherry-pick or checkout these files from CC's cleanup branch:
- `src/scheduler/watch.py` (RotatingFileHandler)
- `config/settings.example.yaml` (execution config)
- `tests/test_auditor.py` (bootcamp fix)
- `frontend/src/pages/Council.jsx` (dissent detection)
- `AGENTS.md`, `docs/architecture.md`, `docs/roadmap.md` (doc updates)

**DO NOT merge** `tests/test_council.py` or `tests/test_council_agents.py` (written for v1).

## Task 3: Rewrite council tests for v2 (collaborative)
Ryan and Claude write these together because the v2 schema is complex.
Target: 30+ tests covering agents, protocol, engine, and value_tracker.
See mega sprint section A2 for full test specification.

## Task 4: Render sync for new tables
Add 6 tables + 6 columns to sync pipeline. Update Render Postgres migration.

## Task 5: Audit quick-fixes (GitHub Issues #30, #31, #32, #33, #37)
- #30: Bare except in system.py → add logging
- #31: broadcast_sync swallows exceptions → add logging
- #32: Wrong type annotation on activity_feed → fix
- #33: Delete v1 backup files (3 files, ~1,154 lines dead code)
- #37: Dead code in edgar_collector.py → delete

## Task 6: Strategy-specific holding period timeouts
Change timeout_days from flat 15 to strategy-specific:
```yaml
timeout_days:
  pullback: 7    # research: 80% of edge in days 1-5
  default: 10
```
Add strategy_type column to shadow_trades. Store on trade open. Read on timeout check.

## Task 7: Create `scripts/verify_counts.py`
Automated AGENTS.md verification. Counts Python files, tests, CLI commands, DB tables,
API routes, notifications, research docs. Compares to AGENTS.md line 1.
Exits non-zero if any count is wrong. Run after every sprint.
```bash
python scripts/verify_counts.py  # PASS or FAIL with diff
```

## Task 8: Create `scripts/schema_report.py`
Single source of truth for database schema. Introspects the live SQLite database,
lists all tables with columns, types, indexes, and row counts.
Outputs to `docs/schema.md`. Run weekly or after any sprint that adds tables.
```bash
python scripts/schema_report.py  # generates docs/schema.md
```

## Task 9: All tests pass + frontend builds
```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
python scripts/verify_counts.py  # new script from Task 7
```

## Task 10: Commit, push, verify on live system
```bash
python -m src.main council  # council v2 end-to-end
python -m src.main scan --dry-run --verbose  # full pipeline with all new features
```

---

# ══════════════════════════════════════════════════════════════
# SPRINT 2: BUILD (Saturday Afternoon — CC solo execution)
# ══════════════════════════════════════════════════════════════
# Max 10 tasks. New features that research says we need.

## Pre-read:
```
cat docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md
cat docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md
cat docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md
cat docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md
cat docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md
cat src/services/scan_service.py
cat src/risk/governor.py
cat src/shadow_trading/executor.py
cat src/training/claude_client.py
```

## Task 1: Event calendar 0-10 continuous risk scoring
Create `src/features/event_risk_score.py`:
- Query earnings_calendar, economic_calendar for upcoming events
- Additive scoring: earnings(0-4) + FOMC(0-2) + NFP(0-1) + CPI(0-1) + OpEx(0-1) + month-end(0-1)
- Score 0-3: full sizing (1.0×), Score 4-7: linear reduction to 0.25 floor, Score 8+: hard block
- Wire into scan_service.py alongside Traffic Light
- Wire into governor as additional sizing multiplier (stacks with Traffic Light)
- Telegram alert at score ≥6

## Task 2: Bracket order health monitor
Create `src/shadow_trading/bracket_monitor.py`:
- Runs every 5 minutes during market hours (APScheduler in watch.py)
- For each open position: verify stop and target legs are active on Alpaca
- If any leg missing/canceled → alert via Telegram
- Pre-market check (9:00 AM): all brackets active
- Post-close check (4:30 PM): log unprotected positions
- Create `bracket_health` table for audit trail

## Task 3: GBNF grammar enforcement for XML
Create `config/trade_commentary.gbnf` (structural envelope grammar from research)
Create `src/llm/grammar_client.py`:
- Uses llama-cpp-python with GBNF grammar
- Falls back to Ollama if llama-cpp-python not installed
- Config flag: `llm.use_grammar_enforcement: false` (off by default, enable after testing)
Wire into packet_writer.py as alternative generation path.

## Task 4: Data quality ingestion gates
Create `src/training/ingestion_gate.py` (~50 lines):
- XML structure validation (tags present and ordered)
- Content length checks (why_now ≥50 chars, analysis ≥100 chars)
- Metadata field validation (conviction 1-10, direction valid)
- Duplicate detection (TF-IDF similarity >0.9)
- Pipeline halt: format compliance <90% → stop + Telegram alert
Wire into training example creation.

## Task 5: Notes page (cloud dashboard)
- `user_notes` table (CREATE TABLE IF NOT EXISTS)
- CRUD API endpoints in cloud_app.py (GET, POST, PUT, DELETE)
- Notes.jsx React page (auto-save, tags, pinning, search, monospace textarea)
- Route in App.jsx, navigation in Layout.jsx
- api.js exports: fetchNotes, createNote, updateNote, deleteNote

## Task 6: Council.jsx v2 visual update
- 5 agent cards with new names/emojis (tactical⚡, strategic🏗️, red_team🔴, innovation💡, macro🌍)
- Direction-based display (bullish/neutral/bearish with green/gray/red)
- Confidence as percentage (0-100%)
- Consensus badge (5-0, 4-1, 3-2, No Consensus)
- Remove all Round 3 and devils_advocate references
- Strategic question input field

## Task 7: HSHS radar chart on Health page
- Fetch from `/api/health/hshs`
- Recharts RadarChart with 5 dimensions
- Composite score prominently displayed
- Phase-dependent weights shown

## Task 8: Prompt caching on council sessions
Modify `src/training/claude_client.py`:
- Add cache_control parameter for council purpose
- First agent writes cache, agents 2-5 read cache
- Sequential execution for Round 1 (not parallel)
- Log cache hit/miss status

## Task 9: Module ownership docstrings + audit quick-fixes (#47, #51, #52)
For every file in src/ that doesn't have it, add a 3-line header:
```python
"""Module description.

Called by: scan_service.py, watch.py
Calls: governor.py, executor.py
"""
```

Also fix these three audit issues while touching each file:
- **#52** `src/data_enrichment/earnings_signals.py`: SQLite connection leak — use `with sqlite3.connect()` context manager
- **#47** `src/risk/governor.py`: Kill-switch ambient file path — make configurable or use DB flag instead of hardcoded path
- **#51** `src/data_collection/research_collector.py`: Delete dead stub `crawl_sec_regulatory()` and unused import

## Task 10: All tests pass + frontend builds + verify_counts
```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
python scripts/verify_counts.py
```

---

# ══════════════════════════════════════════════════════════════
# SPRINT 3: DOCUMENT & VERIFY (Sunday Morning — CC solo)
# ══════════════════════════════════════════════════════════════
# Max 10 tasks. Documentation, decision records, final verification.

## Task 1: ADR (Architecture Decision Records) directory
Create `docs/decisions/` with numbered files:
```
001-strategy-2-mean-reversion.md
002-strategy-3-evolved-pead.md
003-rl-method-dr-grpo.md
004-traffic-light-regime-overlay.md
005-council-vote-first-protocol.md
006-holding-period-optimization.md
007-event-calendar-risk-scoring.md
008-xml-gbnf-grammar-enforcement.md
009-volatility-adaptive-phase-2.md
010-risk-budgeting-equal-weight.md
011-tax-strategy-tabled.md
```
Each file: 10-20 lines with Context, Decision, Consequences, Date, Status.

## Task 2: docs/architecture.md comprehensive rewrite
Must reflect ALL modules, tables, columns, endpoints, data flows.
Use `scripts/schema_report.py` output as the canonical DB reference.
Include module dependency notes from the ownership docstrings.

## Task 3: docs/roadmap.md with all confirmed decisions
Consolidate all [DECISION] tags from roadmap-additions into a single clean roadmap.
Phase 1 (current), Phase 2 (after 50-trade gate), Phase 3+.

## Task 4: CHANGELOG mega sprint entry
One comprehensive entry covering all 3 weekend sprints.

## Task 5: Import dependency graph
Run `pydeps` or write a simple script that traces `from src.X import Y` across all files.
Generate `docs/dependency-graph.md` showing which modules depend on which.
Flag any circular dependencies.

## Task 6: Integrate remaining research into Framework v2.1
Check if any of the 10 remaining research prompts have returned.
If so: save to repo, add to Notion, update Framework, add roadmap items.

## Task 7: Trading week observation log
Finalize the daily checklist template in the mega sprint doc.
Ensure it covers: watch loop status, scan results, Traffic Light,
council sessions, Telegram alerts, PEAD enrichment, bracket health.

## Task 8: Full dry-run scan end-to-end verification
```bash
python -m src.main scan --dry-run --verbose 2>&1 | tee /tmp/full_scan.log
```
Verify: universe loads, features compute, enrichment runs (including PEAD),
Traffic Light computes, event risk scores, ranking, LLM commentary,
signal prices captured. No crashes, no unhandled exceptions.

## Task 9: Final audit — zero orphans, zero old names, audit fixes (#49, #50)
```bash
# Orphaned imports
grep -rn "from src.scheduler.overnight\|from src.shadow_trading.broker\|protocol_v2\|agents_v2" src/ tests/ --include="*.py" | grep -v backup | grep -v __pycache__

# Old agent names in active code
grep -rn "risk_officer\|alpha_strategist\|data_scientist\|regime_analyst\|devils_advocate" src/ frontend/src/ tests/ --include="*.py" --include="*.jsx" | grep -v backup | grep -v __pycache__ | grep -v node_modules | grep -v "is_devils_advocate\|# "

# Bare except:pass in safety code
grep -rn "except.*:$" src/risk/ src/shadow_trading/ --include="*.py" -A1 | grep "pass$"
```
All must return empty.

Also fix these two audit issues:
- **#49** `tests/test_features.py`: Feature-engine test fixtures are date-sensitive on weekends — use fixed dates or mock `datetime.now()` instead of relying on current calendar day
- **#50** `src/main.py`: Exceeds its own 1000-line guardrail — extract the largest command functions (cmd_scan, cmd_council, etc.) into a `src/cli/` module or split into `src/main_commands.py`

## Task 10: Final gate
```bash
python -m pytest tests/ -v --tb=short   # ALL pass
cd frontend && npm run build && cd ..   # builds clean
python scripts/verify_counts.py         # counts match AGENTS.md
python scripts/schema_report.py         # schema doc generated
```
Commit everything. Push. System is clean for Monday.

---

# Summary

| Sprint | When | Who | Focus | Tasks |
|---|---|---|---|---|
| 1 | Sat AM | CC (running) | Stabilize | GTC brackets, merge cleanup, council tests, Render sync, audit fixes (#30-33,#37), timeouts, tooling scripts |
| **Hotfix** | **After S1** | **CC solo** | **Safety** | **#40 (validator), #41 (journal before broker), #42 (fail-open), #44 (council columns), #45 (close without exit), #46 (phantom trades), #48 (Telegram fields)** |
| 2 | Sat PM | CC solo | Build | Event scoring, bracket monitor, GBNF, data gates, Notes, Council.jsx, HSHS, caching, docstrings + #47,#51,#52 |
| 3 | Sun AM | CC solo | Document | ADRs, architecture.md, roadmap, CHANGELOG, dependency graph, research integration, final verification + #49,#50 |
| *Tech Debt* | *Next weekend* | *CC solo* | *Refactor* | *#26-29 (cloud_app.py split), #34-36 (council functions), #38 (fed_collector), #39 (value_tracker)* |

**End state:** Every test passes, every doc matches code, every decision is recorded,
every module says what calls it, every table is documented, the database schema has
a single source of truth, and AGENTS.md is verified by a script not a human.
