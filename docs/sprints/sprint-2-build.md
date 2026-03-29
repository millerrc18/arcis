# Sprint 2: Build — New Features from Research
# CC solo execution. Fresh session. Fire after Hotfix sprint merges.

> **SYSTEM CONTEXT:** Halcyon Lab is an autonomous AI-powered equity trading system.
> S&P 100 universe, pullback-in-strong-trend strategy, Alpaca bracket orders.
> Qwen3 8B (Q8_0 GGUF) via Ollama on RTX 3060 12GB, Windows 11.
> React dashboard on Render (halcyonlab.app). ~25 open positions.
> $100K paper + $100 live. Phase 1 (bootcamp), targeting 50-trade gate.
>
> **WHAT JUST HAPPENED:**
> - Sprint 1 merged: council v2 tests rewritten, Render sync wired, file logging added,
>   GTC brackets verified, holding period timeouts (15→7), verify_counts.py + schema_report.py created,
>   audit quick-fixes (#30-33, #37) applied
> - Hotfix sprint merged: 3 critical safety fixes (#40 validator, #41 journal-before-broker,
>   #42 fail-open), 4 high fixes (#44 council columns, #45 close-without-exit, #46 phantom trades,
>   #48 Telegram fields)
>
> **THIS SPRINT:** 10 tasks. New features informed by 58 research documents.
> No refactoring. Build new capabilities, wire them in, test them.
>
> **RULES:**
> - ≤10 tasks. Do not expand scope.
> - Every new module gets a 3-line ownership docstring (what, called-by, calls)
> - All tests must pass at the end
> - Frontend must build
> - Run `python scripts/verify_counts.py` at the end
> - Update AGENTS.md counts, CHANGELOG.md, docs/architecture.md

---

## Pre-read (mandatory, IN FULL):
```
cat AGENTS.md
cat src/services/scan_service.py
cat src/risk/governor.py
cat src/shadow_trading/executor.py
cat src/features/traffic_light.py
cat src/data_enrichment/earnings_signals.py
cat src/training/claude_client.py
cat src/llm/client.py
cat src/llm/packet_writer.py
cat src/training/generator.py
cat src/api/cloud_app.py
cat src/scheduler/watch.py
cat src/council/agents.py
cat frontend/src/pages/Council.jsx
cat frontend/src/pages/Health.jsx
cat frontend/src/App.jsx
cat frontend/src/api.js
cat config/settings.example.yaml
cat docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md
cat docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md
cat docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md
cat docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md
cat docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md
```

**Run before starting:** `python -m pytest tests/ -x -q`

---

## Task 1: Event calendar 0-10 continuous risk scoring

**Research:** `docs/research/Event_Calendar_Integration_for_SP100_Pullback_Trading.md`

Create `src/features/event_risk_score.py`:

```python
"""Event calendar risk scoring — continuous 0-10 additive system.

Called by: scan_service.py
Calls: sqlite3 (earnings_calendar, economic_calendar tables)
"""
```

**Implementation:**
1. Query `earnings_calendar` for each ticker's next earnings date. Score based on proximity:
   - ≤2 days: +4 points
   - 3-5 days: +2 points
   - >5 days: +0 points

2. Query `economic_calendar` for upcoming FOMC, NFP, CPI dates:
   - FOMC within 2 days: +2 points
   - NFP within 1 day: +1 point
   - CPI within 1 day: +1 point

3. Check calendar for OpEx (3rd Friday), month-end, quarter-end:
   - OpEx day: +1 point
   - Month-end (last 2 trading days): +1 point

4. Return: `{"total_score": int, "components": dict, "sizing_multiplier": float}`
   - Score 0-3: sizing_multiplier = 1.0 (full)
   - Score 4-7: sizing_multiplier = linear interpolation from 1.0 down to 0.25
   - Score 8+: sizing_multiplier = 0.0 (hard block, no new entries)

5. Wire into `scan_service.py`:
   - Compute ONCE per scan (like Traffic Light — not per ticker for the market-wide events)
   - Per-ticker earnings proximity IS per ticker
   - Pass to governor as additional sizing multiplier (stacks multiplicatively with Traffic Light)

6. Telegram alert when total_score ≥ 6: "⚠️ Elevated event risk: {score}/10 — {components}"

7. Add to `config/settings.example.yaml`:
```yaml
event_risk:
  enabled: true
  block_threshold: 8      # hard block above this score
  alert_threshold: 6      # Telegram alert above this
  sizing_floor: 0.25      # minimum sizing multiplier
```

**Tests:** Score computation for known dates, sizing multiplier boundaries, hard block at 8+.

---

## Task 2: Bracket order health monitor

**Research:** `docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md`

Create `src/shadow_trading/bracket_monitor.py`:

```python
"""Bracket order health monitoring — verifies stop/target legs are active.

Called by: watch.py (APScheduler, every 5 minutes during market hours)
Calls: alpaca_adapter.py, telegram.py, sqlite3
"""
```

**Implementation:**
1. For each open trade in `shadow_trades` where `alpaca_order_id IS NOT NULL`:
   - Query Alpaca for the order and its legs
   - Verify stop leg status = "new" or "held" (active)
   - Verify target leg status = "new" or "held" (active)
   - If any leg is missing, canceled, or expired → Telegram alert

2. Create `bracket_health` table:
```sql
CREATE TABLE IF NOT EXISTS bracket_health (
    check_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    stop_leg_status TEXT,
    target_leg_status TEXT,
    bracket_intact INTEGER DEFAULT 1,
    action_taken TEXT,
    checked_at TEXT NOT NULL
);
```

3. Schedule in watch.py:
   - Every 5 minutes during market hours (9:30 AM - 4:00 PM ET)
   - Pre-market check at 9:00 AM (verify all brackets before open)
   - Post-close check at 4:30 PM (log which positions are unprotected overnight)

4. Telegram notifications:
   - "🔴 BRACKET ALERT: {ticker} stop leg {status} — position may be unprotected"
   - "✅ Pre-market bracket check: {n}/{total} positions protected"

**Tests:** Mock Alpaca API responses for intact vs broken brackets, verify alerts fire.

---

## Task 3: GBNF grammar enforcement for XML

**Research:** `docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md`

1. Create `config/trade_commentary.gbnf`:
```
root ::= ws why-now-block ws analysis-block ws metadata-block ws

why-now-block  ::= "<why_now>" ws prose ws "</why_now>"
analysis-block ::= "<analysis>" ws prose ws "</analysis>"
metadata-block ::= "<metadata>" ws metadata-lines ws "</metadata>"

metadata-lines ::= conviction-line ws direction-line ws horizon-line ws risk-line

conviction-line ::= "Conviction: " digit
direction-line  ::= "Direction: " ("LONG" | "SHORT" | "NEUTRAL")
horizon-line    ::= "Time Horizon: " prose-line
risk-line       ::= "Key Risk: " prose-line

digit      ::= [1-9] | "10"
prose      ::= prose-char+
prose-char ::= [^<]
prose-line ::= [^\n]+
ws         ::= [ \t\n\r]*
```

2. Create `src/llm/grammar_client.py`:
```python
"""Grammar-constrained LLM client using llama-cpp-python with GBNF.

Called by: packet_writer.py
Calls: llama_cpp (optional dependency)
"""
```
   - Try to import llama_cpp; if unavailable, log warning and return None
   - Load GGUF model and grammar on first call, cache for subsequent calls
   - `generate_with_grammar(prompt, max_tokens=2048, temperature=0.7) -> str`
   - Unload Ollama model first if running (keep_alive=0)

3. Wire into `src/llm/packet_writer.py`:
   - Add config flag check: `settings.get("llm", {}).get("use_grammar_enforcement", False)`
   - If enabled and grammar_client available: use grammar_client
   - Else: fall back to existing Ollama path
   - Log which path was used

4. Add to `config/settings.example.yaml`:
```yaml
llm:
  use_grammar_enforcement: false  # Enable after testing llama-cpp-python
  grammar_file: "config/trade_commentary.gbnf"
```

**Tests:** Grammar file parses without error, config flag routing works, fallback to Ollama when llama-cpp not installed.

---

## Task 4: Data quality ingestion gates

**Research:** `docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md`

Create `src/training/ingestion_gate.py`:

```python
"""Training data ingestion validation — prevents format contamination.

Called by: generator.py, any training example creation path
Calls: sqlite3 (training_examples for duplicate detection)
"""
```

**Implementation (~50 lines):**
1. `validate_training_example(text: str, db_path: str) -> tuple[bool, str]`
2. Checks:
   - XML structure: `<why_now>`, `<analysis>`, `<metadata>` tags present and in order
   - Content length: why_now ≥ 50 chars, analysis ≥ 100 chars
   - Metadata: Conviction is integer 1-10, Direction is valid
   - No markdown formatting inside XML (no `**bold**`, no `### headers`)
   - No code fences wrapping the XML
   - Duplicate detection: TF-IDF cosine similarity > 0.9 with existing examples → reject
3. Returns `(True, "")` or `(False, "rejection_reason")`

4. Wire into training example creation:
   - Before inserting into `training_examples` table, call `validate_training_example()`
   - If invalid, log the rejection reason, do NOT insert
   - Track rejection rate per batch

5. Pipeline halt: if format compliance < 90% in a batch of 10+ examples → Telegram alert
   "🛑 TRAINING HALT: {compliance}% format compliance ({rejected}/{total} rejected). Top reason: {reason}"

**Tests:** Valid example passes, missing tags rejected, bad conviction rejected, duplicate detected.

---

## Task 5: Notes page (cloud dashboard)

1. Add `user_notes` table in `watch.py` `_ensure_all_tables()`:
```sql
CREATE TABLE IF NOT EXISTS user_notes (
    note_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

2. Add CRUD endpoints in `src/api/cloud_app.py`:
   - `GET /api/notes` — list all, sorted by pinned then updated_at desc
   - `POST /api/notes` — create new note
   - `PUT /api/notes/{note_id}` — update title/content/tags/pinned
   - `DELETE /api/notes/{note_id}` — delete

3. Create `frontend/src/pages/Notes.jsx`:
   - List view with search/filter
   - Click to edit (auto-save on blur or after 2s debounce)
   - Tag management (comma-separated)
   - Pin/unpin toggle
   - Monospace textarea for content

4. Add route in `App.jsx`, navigation in sidebar/layout.

5. Add to `frontend/src/api.js`: fetchNotes, createNote, updateNote, deleteNote

6. Add `user_notes` to Render sync table list.

**Tests:** CRUD endpoints return correct status codes, note creation with tags works.

---

## Task 6: Council.jsx v2 visual update

Read `src/council/agents.py` and `src/council/engine.py` to understand the v2 schema.

Update `frontend/src/pages/Council.jsx`:
1. Agent cards with new names and emojis:
   - tactical_operator → ⚡ Tactical
   - strategic_architect → 🏗️ Strategic
   - red_team → 🔴 Red Team
   - innovation_engine → 💡 Innovation
   - macro_navigator → 🌍 Macro

2. Direction-based display:
   - bullish → green badge
   - neutral → gray badge
   - bearish → red badge

3. Confidence as percentage (0-100%), not integer (1-10)

4. Consensus badge: "5-0 Unanimous", "4-1 Strong", "3-2 Majority", "No Consensus"

5. Remove ALL references to: round3, devils_advocate, position (use direction), old agent names

6. Add strategic question input: text field + "Ask Council" button that POSTs to `/api/council/strategic`

7. Parameter adjustments section: table showing previous → recommended → applied for each parameter

**Tests:** `npm run build` succeeds. No old agent names in JSX.

---

## Task 7: HSHS radar chart on Health page

Update `frontend/src/pages/Health.jsx`:
1. Fetch from `GET /api/health/hshs`
2. Add Recharts `RadarChart` with 5 dimensions:
   - Performance, Model Quality, Data Asset, Flywheel Velocity, Defensibility
3. Composite score prominently displayed (large number with color: green >70, yellow >50, red <50)
4. Show current phase weights below the chart
5. If HSHS endpoint returns no data, show placeholder "Collecting data..."

**Tests:** `npm run build` succeeds.

---

## Task 8: Prompt caching on council sessions

**Research:** `docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md`

Read `src/training/claude_client.py` (or wherever the Anthropic API calls live for council).

Modify council API calls:
1. The 5 agent system prompts in `src/council/agents.py` are 10K+ tokens each (well above 2,048 minimum)
2. For Round 1 calls, the FIRST agent request adds `cache_control: {"type": "ephemeral"}` on the system message
3. Wait for first response before launching agents 2-5
4. Agents 2-5 share the cached system prompt (90% off input tokens)
5. Log cache hits/misses: `logger.info("[COUNCIL] Agent %s: cache_%s", agent_name, "hit" if cached else "miss")`

**Note:** Each agent has a DIFFERENT system prompt, so caching only helps if there's a shared prefix. Check if the agents share a common preamble. If not, caching won't help here — document this finding and skip.

**Tests:** Council session runs without error, cost is logged.

---

## Task 9: Module ownership docstrings + audit quick-fixes (#47, #51, #52)

For every file in `src/` that doesn't already have it, add a 3-line header docstring:
```python
"""Module description.

Called by: scan_service.py, watch.py
Calls: governor.py, executor.py
"""
```

Trace the actual imports to determine the correct "Called by" and "Calls" for each module.

Also fix these three audit issues:
- **#52** `src/data_enrichment/earnings_signals.py`: SQLite connection opened without context manager. Wrap in `with sqlite3.connect(db_path) as conn:` to prevent leaks.
- **#47** `src/risk/governor.py`: Kill-switch uses hardcoded ambient file path. Change to configurable path from settings, or use a DB flag in a `system_flags` table.
- **#51** `src/data_collection/research_collector.py`: Delete dead stub function `crawl_sec_regulatory()` (lines 313-321) and any unused imports.

---

## Task 10: All tests pass + frontend builds + verify_counts

```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
python scripts/verify_counts.py
```

**ALL tests pass. Frontend builds clean. Counts match AGENTS.md.**

---

# Sprint Documentation Checklist (docs/sprint-checklist.md)

### Tier 1 (MANDATORY):
- [ ] AGENTS.md counts match code (run verify_counts.py)
- [ ] CHANGELOG.md — Sprint 2 entry
- [ ] docs/architecture.md — new modules added (event_risk_score, bracket_monitor, grammar_client, ingestion_gate, Notes page)
- [ ] config/settings.example.yaml — all new keys documented
- [ ] All tests pass
- [ ] Frontend builds
- [ ] No bare except:pass in new code
