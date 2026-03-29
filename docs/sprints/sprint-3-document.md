# Sprint 3: Document & Verify — Clean Codebase for Monday
# CC solo execution. Fresh session. Fire after Sprint 2 merges.

> **SYSTEM CONTEXT:** Halcyon Lab is an autonomous AI-powered equity trading system.
> S&P 100 universe, pullback-in-strong-trend strategy, Alpaca bracket orders.
> Qwen3 8B (Q8_0 GGUF) via Ollama on RTX 3060 12GB, Windows 11.
> React dashboard on Render (halcyonlab.app). ~25 open positions.
> $100K paper + $100 live. Phase 1 (bootcamp), targeting 50-trade gate.
> 58 research documents in docs/research/. 16 strategy decisions confirmed.
>
> **WHAT JUST HAPPENED:**
> - Sprint 1: Stabilized — council v2 tests, Render sync, file logging, GTC brackets,
>   holding period timeouts, verify_counts.py, schema_report.py, audit fixes (#30-33, #37)
> - Hotfix: Safety — 3 critical (#40 validator, #41 journal-before-broker, #42 fail-open),
>   4 high (#44 council columns, #45 close-without-exit, #46 phantom trades, #48 Telegram)
> - Sprint 2: Built — event calendar scoring, bracket monitor, GBNF grammar, data quality
>   gates, Notes page, Council.jsx v2, HSHS radar, prompt caching, docstrings, audit fixes (#47, #51, #52)
>
> **THIS SPRINT:** 10 tasks. Documentation, decision records, and final verification.
> The goal: go into Monday with every doc matching code, every decision formally recorded,
> and a clean final gate with zero orphans, zero stale references, zero test failures.
>
> **RULES:**
> - ≤10 tasks. Do not expand scope.
> - This is a documentation sprint. The only CODE changes are #49 and #50 fixes.
> - All tests must pass at the end
> - Frontend must build
> - Run `python scripts/verify_counts.py` at the end
> - Update AGENTS.md counts, CHANGELOG.md

---

## Pre-read (mandatory, IN FULL):
```
cat AGENTS.md
cat CHANGELOG.md
cat docs/architecture.md
cat docs/roadmap.md
cat docs/roadmap-additions-2026-03-28.md
cat docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md
cat src/main.py
cat tests/test_features.py
```

Also scan the full module list to understand current codebase:
```
find src -name "*.py" ! -path "*__pycache__*" ! -name "*backup*" | sort
find tests -name "*.py" | sort
```

**Run before starting:** `python -m pytest tests/ -x -q`

---

## Task 1: ADR (Architecture Decision Records) directory

Create `docs/decisions/` with one file per major decision. Each file follows this template:

```markdown
# ADR-NNN: Title

**Date:** YYYY-MM-DD
**Status:** Active | Superseded | Tabled
**Context:** 2-3 sentences on what problem we faced.
**Decision:** 1-2 sentences on what we decided.
**Consequences:** 2-3 sentences on what this means going forward.
**Research:** Link to supporting research document(s) if applicable.
```

Create these 11 files:
```
docs/decisions/001-strategy-2-mean-reversion.md
docs/decisions/002-strategy-3-evolved-pead.md
docs/decisions/003-rl-method-dr-grpo.md
docs/decisions/004-traffic-light-regime-overlay.md
docs/decisions/005-council-vote-first-protocol.md
docs/decisions/006-holding-period-optimization.md
docs/decisions/007-event-calendar-risk-scoring.md
docs/decisions/008-xml-gbnf-grammar-enforcement.md
docs/decisions/009-volatility-adaptive-phase-2.md
docs/decisions/010-risk-budgeting-equal-weight.md
docs/decisions/011-tax-strategy-tabled.md
```

**Source data:** Read `docs/roadmap-additions-2026-03-28.md` for all [DECISION] tags with dates, rationale, and research references.

---

## Task 2: docs/architecture.md comprehensive rewrite

This file is stale. Rewrite it to reflect the ACTUAL current system.

**Must include:**

1. **System overview** — one paragraph describing Halcyon Lab
2. **Module inventory** — every Python file in src/ with one-line description. Group by directory (api/, council/, data_collection/, data_enrichment/, evaluation/, features/, llm/, notifications/, packets/, ranking/, risk/, scheduler/, services/, shadow_trading/, sync/, training/)
3. **Database schema** — run `python scripts/schema_report.py` and include the output. Every table, every column, every index.
4. **API endpoints** — every route in cloud_app.py and routes/*.py with method, path, description
5. **Data flow** — how a scan cycle works end-to-end: universe → features → enrichment → Traffic Light → event risk → ranking → LLM → governor → executor → journal
6. **Council flow** — Round 1 → aggregate → conditional Round 2 → parameter application → value tracking
7. **New since last update:** Traffic Light, PEAD enrichment, IS tracking, HSHS, council v2, value tracker, event calendar scoring, bracket monitor, GBNF grammar, data quality gates, Notes page
8. **Deleted modules:** overnight.py (consolidated into watch.py), broker.py (unused), v1 backup files

**Do NOT copy-paste from this sprint doc.** Read the actual code and describe what it does.

---

## Task 3: docs/roadmap.md with all confirmed decisions

Consolidate ALL [DECISION] tags from `docs/roadmap-additions-2026-03-28.md` into a single clean roadmap document. Structure:

```markdown
# Halcyon Lab Roadmap

## Phase 1: Bootcamp (Current)
- What's deployed and running
- What's remaining (50-trade gate)

## Phase 2: After 50-Trade Gate
- Strategy #2: Mean Reversion
- Universe expansion
- Volatility-adaptive sizing
- FinBERT NLP
- Conviction calibration
- etc.

## Phase 3+: Scale
- Strategy #3: Evolved PEAD
- GRPO training
- Fund formation path

## Confirmed Decisions
(table of all 16 decisions with dates)

## Tabled / Deferred
(items explicitly not doing now, with reasons)
```

---

## Task 4: CHANGELOG mega sprint entry

Add one comprehensive entry covering all weekend sprints:

```markdown
## [Unreleased] - 2026-04-05/06

### Weekend Mega Sprint (4 sprints: Stabilize + Hotfix + Build + Document)

#### Critical Safety Fixes
- Fixed: safety checks fail closed on errors, not open (#42)
- Fixed: journal closes after broker confirmation, not before (#41)
- Fixed: LLM validator accepts real TradePacket schema (#40)
- Fixed: paper trades logged as "failed" on submission failure (#46)
- Fixed: /shadow/close requires broker exit for live trades (#45)
- Fixed: council agents query correct column names (#44)
- Fixed: Telegram trade notification uses correct fields (#48)

#### New Features
- Event calendar 0-10 continuous risk scoring
- Bracket order health monitor (every 5 min + pre-market + post-close)
- GBNF grammar enforcement for XML compliance (off by default)
- Data quality ingestion gates with pipeline halt
- Notes page on cloud dashboard
- Council.jsx v2 visual update
- HSHS radar chart on Health page
- Prompt caching on council sessions

#### Infrastructure
- RotatingFileHandler (logs/halcyon.log, 10MB × 7)
- scripts/verify_counts.py — automated AGENTS.md verification
- scripts/schema_report.py — canonical database schema doc
- Strategy-specific holding period timeouts (pullback 15→7 days)
- Render sync for 6 new tables + 6 new columns
- Module ownership docstrings across all src/ files
- Ollama daily VRAM restart
- SQLite connection leak fixed (#52)
- Kill-switch path made configurable (#47)

#### Documentation
- 11 Architecture Decision Records (docs/decisions/)
- docs/architecture.md comprehensive rewrite
- docs/roadmap.md consolidated from all decision sources
- Import dependency graph (docs/dependency-graph.md)
- 58 research documents in library
```

---

## Task 5: Import dependency graph

Write a script or use `pydeps` to trace all `from src.X import Y` statements across the codebase.

Generate `docs/dependency-graph.md`:
```markdown
# Import Dependency Graph

## src/services/scan_service.py
Imports from:
- src.features.engine
- src.features.traffic_light
- src.features.event_risk_score
- src.data_enrichment.earnings_signals
- src.ranking.ranker
- src.llm.packet_writer
- src.risk.governor
- src.shadow_trading.executor

Imported by:
- src.scheduler.watch

## src/council/engine.py
Imports from:
- src.council.protocol
- src.council.value_tracker
...
```

Also flag any circular dependencies (A imports B which imports A).

If `pydeps` is available, also generate a visual graph. Otherwise the markdown list is sufficient.

---

## Task 6: Integrate remaining research into Framework v2.1

Read `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`.

Check if the v2.1 changes table includes ALL findings from the 58 research documents:
- Comprehensive compendium (10 domains): SQLite 10-20 years, Render $13/mo, Ollama daily restart, 15 pre-commitment rules, MinBTL formula
- Fund formation: $50K-$75K startup, 12-24 month track record, tabled
- Feature importance: section ablation, 35 min/month
- Risk budgeting: 1/N until 200 trades
- SEC EDGAR XBRL: companyfacts.zip

If anything is missing from the Framework, add it to the v2→v2.1 changes table.

---

## Task 7: Trading week observation log

Create `docs/observation-log-template.md`:

```markdown
# Trading Week Observation Log

## Monday
- [ ] Watch loop started cleanly? (Y/N, timestamp)
- [ ] First scan completed? (candidates found, fallback rate)
- [ ] Traffic Light regime? (GREEN/YELLOW/RED, score)
- [ ] Event risk score? (score, components)
- [ ] Council daily session? (direction, consensus type, cost)
- [ ] Bracket health check? (all intact Y/N)
- [ ] Telegram alerts? (list any)
- [ ] Trades opened? (tickers, sizes)
- [ ] Trades closed? (tickers, P&L)
- [ ] Issues observed:

## Tuesday
(same template)

## Wednesday
(same template)

## Thursday
(same template)

## Friday
(same template)

## Saturday — Retrain Day
- [ ] Weekly retrain triggered?
- [ ] Training data count + quality scores
- [ ] Model version updated?

## Sunday — Review Ritual
- [ ] Export 20 recent training examples
- [ ] Export halcyon.log
- [ ] Dashboard screenshots
- [ ] Research digest reviewed
- [ ] Monday action items:
```

---

## Task 8: Full dry-run scan end-to-end verification

```bash
python -m src.main scan --dry-run --verbose 2>&1 | tee /tmp/full_scan.log
```

**Verify in output (check each one):**
- [ ] Universe loads (90+ tickers)
- [ ] Features computed
- [ ] PEAD earnings enrichment runs (conditional on proximity)
- [ ] Traffic Light computed (score, multiplier, regime)
- [ ] Event risk score computed (score, components, multiplier)
- [ ] Ranking produces candidates
- [ ] LLM commentary generated (check fallback rate)
- [ ] Signal prices captured
- [ ] Governor checks pass
- [ ] No crashes, no unhandled exceptions

If any step fails, fix it before proceeding.

---

## Task 9: Final audit — zero orphans, zero old names + fixes (#49, #50)

```bash
# Orphaned imports (must be empty)
grep -rn "from src.scheduler.overnight\|from src.shadow_trading.broker\|protocol_v2\|agents_v2" src/ tests/ --include="*.py" | grep -v backup | grep -v __pycache__

# Old agent names in active code (must be empty except schema column refs)
grep -rn "risk_officer\|alpha_strategist\|data_scientist\|regime_analyst\|devils_advocate" src/ frontend/src/ tests/ --include="*.py" --include="*.jsx" | grep -v backup | grep -v __pycache__ | grep -v node_modules | grep -v "is_devils_advocate\|# "

# Bare except:pass in safety code (must be empty)
grep -rn "except.*:$" src/risk/ src/shadow_trading/ --include="*.py" -A1 | grep "pass$"
```

**All must return empty.** If not, fix the offending lines.

**Fix #49:** `tests/test_features.py` — Feature-engine test fixtures that depend on the current date fail on weekends/holidays. Fix by using fixed dates or mocking `datetime.now()`:
```python
# Instead of: pd.date_range(end=pd.Timestamp.now(), periods=60, freq='B')
# Use: pd.date_range(end=pd.Timestamp('2026-03-20'), periods=60, freq='B')
```

**Fix #50:** `src/main.py` exceeds its own 1000-line guardrail. Extract command functions into `src/cli/commands.py`:
- Move `cmd_scan`, `cmd_council`, `cmd_train_pipeline`, and other large command functions
- Import them back into main.py
- main.py becomes just argparse setup + function routing
- Target: main.py under 500 lines

---

## Task 10: Final gate

```bash
# All tests pass
python -m pytest tests/ -v --tb=short

# Frontend builds clean
cd frontend && npm run build && cd ..

# Counts match AGENTS.md
python scripts/verify_counts.py

# Schema doc generated
python scripts/schema_report.py

# No orphaned imports
grep -rn "from src.scheduler.overnight\|protocol_v2\|agents_v2" src/ tests/ --include="*.py" | grep -v backup | grep -v __pycache__
# Must be empty
```

**ALL pass. Commit everything. Push. System is clean for Monday.**

---

# Sprint Documentation Checklist (docs/sprint-checklist.md)

### Tier 1 (MANDATORY):
- [ ] AGENTS.md counts match code (verify_counts.py passes)
- [ ] CHANGELOG.md — mega sprint entry
- [ ] docs/architecture.md — comprehensive rewrite matches actual code
- [ ] docs/roadmap.md — all 16 decisions consolidated
- [ ] docs/decisions/ — 11 ADR files created
- [ ] docs/dependency-graph.md — import graph generated
- [ ] docs/observation-log-template.md — trading week template
- [ ] All tests pass
- [ ] Frontend builds
- [ ] Full dry-run scan completes without errors
- [ ] Zero orphaned imports
- [ ] Zero old agent names in active code
- [ ] main.py under guardrail (after #50 fix)
