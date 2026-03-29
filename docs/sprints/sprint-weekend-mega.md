# Sprint: Weekend Mega Sprint — Post-First-Trading-Week
# All research integrated, all gaps closed, all infrastructure hardened

> **CONTEXT:** The system ran its first full trading week (March 31 – April 4, 2026).
> NO changes were made during the week except critical fixes.
> This sprint integrates all 46+ research findings, closes every gap identified
> during the week, and prepares the system for Phase 1 steady-state operation.
>
> **CONSTRAINT:** Fire remaining 18 deep research prompts BEFORE this sprint.
> Wait for all research to return. This sprint incorporates ALL findings.
>
> **SCOPE:** This is the largest sprint Halcyon Lab has ever executed.
> Estimated: 15-20 parts, 2000+ lines of changes across 30+ files.
> Plan for a full CC session (proto branch, thorough testing, merge).

---

# ══════════════════════════════════════════════════════════════
# PHASE A: MERGE & STABILIZE (do first, before any new work)
# ══════════════════════════════════════════════════════════════

## A1. Merge CC's cleanup sprint (compatible changes only)

CC completed a cleanup sprint on proto/upbeat-edison with 9 files changed.
The following changes are COMPATIBLE with our v2 council deployment on main:

**MERGE these:**
- `src/scheduler/watch.py` — RotatingFileHandler (10MB × 7) to logs/halcyon.log
- `frontend/src/pages/Council.jsx` — dissent detection fix (removed devils_advocate)
- `AGENTS.md` — counts updated (141 files, 1064 tests, 54 CLI, 35 tables)
- `docs/architecture.md` — synced tables, DB schema, API routes updated
- `docs/roadmap.md` — reliability sprint + file logging in completed items
- `config/settings.example.yaml` — execution config section added
- `tests/test_auditor.py` — bootcamp mode fix (supplies 50+ trades)

**DO NOT MERGE these (incompatible with v2 council on main):**
- `tests/test_council.py` — CC fixed for v1 agents, will FAIL against v2
- `tests/test_council_agents.py` — CC fixed for v1 data functions

**Procedure:**
```bash
git fetch origin
git cherry-pick <compatible-commit-hashes>  # Or manually apply diffs
# OR: checkout individual files from CC's branch
git checkout origin/proto/upbeat-edison -- src/scheduler/watch.py
git checkout origin/proto/upbeat-edison -- config/settings.example.yaml
git checkout origin/proto/upbeat-edison -- tests/test_auditor.py
# etc. — but NOT tests/test_council*.py
```

## A2. Rewrite council tests for v2

The council v2 is deployed on main with new agent names and schema.
Tests must be rewritten from scratch for the v2 API.

**Read these files IN FULL before writing tests:**
```bash
cat src/council/agents.py     # 5 new agents, gather functions return strings
cat src/council/protocol.py   # aggregate_votes, apply_rate_limiters, _parse_agent_response
cat src/council/engine.py     # run_session with custom_question, result_json
cat src/council/value_tracker.py  # log_parameter_change, compute_attribution
```

**Required test file: `tests/test_council_v2.py`**

Test categories (minimum 30 tests):

```
# agents.py tests
- AGENT_NAMES has exactly 5 entries
- AGENT_DATA_FUNCTIONS has exactly 5 entries matching AGENT_NAMES
- Each gather function returns non-empty string on populated DB
- Each gather function returns fallback string on empty DB
- Each gather function never raises exceptions (even with corrupt data)
- _query_db helper works correctly

# protocol.py tests
- _parse_agent_response: valid JSON → correct fields populated
- _parse_agent_response: code-fenced JSON → strips fences and parses
- _parse_agent_response: JSON embedded in prose → extracted via find/rfind
- _parse_agent_response: old schema (position 1-10 int) → auto-converted to direction/float
- _parse_agent_response: garbage input → _default_response with _parse_failed=True
- _parse_agent_response: missing direction field → default to neutral
- _parse_agent_response: confidence > 1.0 → clamped to 1.0
- _parse_agent_response: confidence as int 8 → converted to 0.8
- _default_response: all required fields present including backward-compat
- aggregate_votes: 5 bullish → consensus_reached=True, round2_needed=False, consensus_type="5-0"
- aggregate_votes: 3 bullish 2 bearish → consensus_reached=True, consensus_type="3-2"
- aggregate_votes: 2-2-1 split → consensus_reached=False, round2_needed=True
- aggregate_votes: all neutral → direction="neutral"
- aggregate_votes: domain weights affect score (tactical_operator weighted higher in daily)
- apply_rate_limiters: small change → not clipped
- apply_rate_limiters: >25% daily change → clipped to 25%
- apply_rate_limiters: hard bounds enforced (0.25 min, 1.5 max for sizing)
- tally_votes: returns backward-compat format with _v2 key
- build_shared_context: returns non-empty string on populated DB

# engine.py tests
- init_council_tables: creates all 6 tables (sessions, votes, calibrations, debug_log, parameter_log, parameter_state)
- init_council_tables: adds v2 columns to existing tables (safe ALTER)
- _store_votes: populates both old (position/confidence/vote) and new (direction/confidence_float/assessment_json) columns
- _estimate_session_cost: correct math for 1 and 2 rounds

# value_tracker.py tests
- log_parameter_change: stores entry and closes previous window
- log_parameter_change: updates council_parameter_state
- get_current_parameters: returns defaults on empty DB
- compute_attribution: sizing multiplier counterfactual correct (reduced sizing + loss = positive value)
- compute_attribution: skips non-attributable parameters
- get_rolling_value_summary: counts consecutive negative weeks correctly
- get_rolling_value_summary: authority_status transitions (full → alert at 8, reduced at 12)
```

## A3. Render sync for new tables

Cloud dashboard is BLIND to everything we built. Read `src/sync/render_sync.py` in full.

**Add to sync list:**
- `traffic_light_state`
- `council_calibrations`
- `council_debug_log`
- `council_parameter_log`
- `council_parameter_state`
- `validation_results`

**Add to Render Postgres migration (`scripts/render_migrate.py`):**
- CREATE TABLE statements for all 6 new tables
- ALTER TABLE statements for new columns on existing tables

**New columns to sync:**
- `shadow_trades.signal_price`, `shadow_trades.implementation_shortfall_bps`
- `council_sessions.result_json`
- `council_votes.direction`, `council_votes.confidence_float`, `council_votes.assessment_json`

---

# ══════════════════════════════════════════════════════════════
# PHASE B: P0 RESEARCH-INFORMED CHANGES
# ══════════════════════════════════════════════════════════════

## B1. Strategy-specific holding period timeouts

**Research:** `docs/research/Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md`
**Finding:** Pullback alpha concentrates in days 1-5 (80-85% of edge). Current 15-day timeout is too long.

**Changes:**

1. Add strategy-specific timeout config to `config/settings.example.yaml`:
```yaml
shadow_trading:
  timeout_days:
    pullback: 7          # was 15 — research: 80% of edge in days 1-5
    mean_reversion: 5    # Phase 2 — RSI(2) literature
    pead: 10             # Phase 3 — ML-enhanced composite
    default: 10          # fallback for unclassified
```

2. Modify `src/shadow_trading/executor.py` `check_and_manage_open_trades()`:
   - Read strategy type from trade record (setup_type or similar field)
   - Look up strategy-specific timeout from config
   - Apply per-strategy timeout instead of global timeout_days

3. Add safe ALTER to shadow_trades for strategy_type if not present:
```sql
ALTER TABLE shadow_trades ADD COLUMN strategy_type TEXT DEFAULT 'pullback';
```

4. Store strategy_type when opening trades in `open_shadow_trade()`.

## B2. Alpaca bracket order redundancy

**Research:** `docs/research/Alpaca_Bracket_Order_Failure_Modes_and_Mitigations.md`
**Finding:** 9 failure modes including 17+ hours unprotected daily, stock split breaks, partial fill deadlocks.

**Changes:**

1. Create `src/shadow_trading/bracket_monitor.py`:
   - Runs every 5 minutes during market hours (via watch.py scheduler)
   - For each open position:
     a. Query Alpaca for bracket order status
     b. Verify stop and target legs are still active
     c. If any leg is missing/canceled → re-submit bracket or alert
     d. Log status to new `bracket_health` table

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

3. Extended hours protection:
   - Add pre-market check (9:00 AM) that verifies all brackets are active
   - Add post-close check (4:30 PM) that logs which positions are unprotected overnight
   - Telegram alert if any bracket is missing

4. Stock split detection:
   - Query Alpaca for corporate actions on held tickers
   - If split detected, cancel and re-submit brackets with adjusted prices
   - Telegram alert on split detection

5. Wire into watch.py scan cycle.

---

# ══════════════════════════════════════════════════════════════
# PHASE C: P1 INFRASTRUCTURE IMPROVEMENTS
# ══════════════════════════════════════════════════════════════

## C1. GBNF grammar enforcement for XML compliance

**Research:** `docs/research/XML_Compliance_via_GBNF_Grammar_Enforcement.md`
**Finding:** Ollama cannot enforce XML. llama-cpp-python with GBNF grammar = 100% structural correctness.

**Changes:**

1. Create `config/trade_commentary.gbnf` with the structural envelope grammar
   from the research doc (constrains tags, prose is free).

2. Create `src/llm/grammar_client.py`:
   - Alternative to the Ollama client for grammar-constrained generation
   - Uses llama-cpp-python with the GBNF grammar
   - Falls back to Ollama if llama-cpp-python not installed
   - Config flag: `llm.use_grammar_enforcement: true`

3. Modify `src/llm/packet_writer.py`:
   - If grammar enforcement enabled, use grammar_client instead of Ollama
   - Template fallback still available as safety net
   - Log whether grammar or fallback was used

4. Add to config:
```yaml
llm:
  use_grammar_enforcement: false  # Enable after testing
  grammar_file: "config/trade_commentary.gbnf"
```

5. Install llama-cpp-python in requirements (optional dependency).

## C2. Training pipeline upgrade (Unsloth + TRL 0.29.1)

**Research:** `docs/research/Fine-Tuning_Qwen3_8B_RTX_3060_March_2026_Guide.md`
**Finding:** Unsloth now fits Qwen3 8B on RTX 3060. TRL 0.29.1 has Dr. GRPO built in.

**Changes:**

1. Update `requirements-training.txt`:
   - `unsloth>=2024.12` (replaces BitsAndBytes for training)
   - `trl>=0.29.1` (was 0.24)

2. Modify `src/training/trainer.py`:
   - Add Unsloth training path alongside existing BitsAndBytes path
   - Config flag: `training.use_unsloth: true`
   - If Unsloth available, use FastLanguageModel for 60% VRAM savings
   - If not, fall back to existing BitsAndBytes path

3. Update Dr. GRPO config for TRL 0.29.1 API changes.

4. Document the upgrade in `docs/guides/training_setup.md`.

## C3. Prompt caching on council sessions

**Research:** `docs/research/Claude_API_Cost_Optimization__Prompt_Caching_Batch_API_Haiku.md`
**Finding:** Council agents share 10K+ system prompt. Agents 2-5 get 90% off with caching.

**Changes:**

1. Modify `src/training/claude_client.py`:
   - Add `cache_control` parameter support
   - For council calls: first agent writes cache, agents 2-5 read cache
   - Requires sequential (not parallel) agent execution for Round 1

2. Modify `src/council/protocol.py` `run_round_1()`:
   - First agent call includes `cache_control: {"type": "ephemeral"}` on system prompt
   - Wait for first response before launching agents 2-5
   - Log cache hit/miss status

3. Estimated savings: $3/month on council sessions.

## C4. Data quality ingestion gates

**Research:** `docs/research/Bulletproof_Data_Quality_for_Small-Scale_Financial_ML.md`
**Finding:** 78% format contamination persisted because zero quality gates existed. $0 fix.

**Changes:**

1. Create `src/training/ingestion_gate.py` (~50 lines):
   - XML structure validation (required tags present and ordered)
   - Content length checks (why_now ≥ 50 chars, analysis ≥ 100 chars)
   - Metadata field validation (conviction 1-10, direction valid)
   - Duplicate detection (TF-IDF similarity > 0.9 with existing examples)
   - Returns (is_valid, rejection_reason)

2. Wire into training example creation in `src/training/generator.py`.

3. Add pipeline halt: if format compliance < 90% in a batch → stop + Telegram alert.

4. Add Pandera schema for training_examples table validation.

---

# ══════════════════════════════════════════════════════════════
# PHASE D: FEATURES & UI
# ══════════════════════════════════════════════════════════════

## D1. Notes page (cloud dashboard)

Still not built. Add to Render dashboard:
- `user_notes` table (note_id, title, content, tags, pinned, created_at, updated_at)
- CRUD API endpoints in cloud_app.py
- Notes.jsx React page with auto-save, tags, pinning, search
- Route + navigation entry
- Render sync (bidirectional — notes created on cloud should sync back)

## D2. Council dashboard update for v2

Council.jsx needs visual update for v2 agents and schema:
- 5 new agent cards with new names/emojis/colors
- Direction-based display (bullish/neutral/bearish) not position
- Confidence as percentage (0-100%) not integer (1-10)
- Consensus badge (5-0, 4-1, 3-2, No Consensus)
- Parameter adjustments table (before/after/rate-limited)
- Strategic question input field
- Value attribution section (when data available)
- Calibration scorecard (when predictions verified)
- Session history with expandable details
- Remove all Round 3 references

## D3. HSHS dashboard page

The Health page exists but needs HSHS visualization:
- Fetch from `/api/health/hshs`
- 5-dimension radar chart (Recharts RadarChart)
- Composite score prominently displayed
- Phase-dependent weights shown
- Trend over time (if historical HSHS data stored)

---

# ══════════════════════════════════════════════════════════════
# PHASE E: INTEGRATE REMAINING RESEARCH
# ══════════════════════════════════════════════════════════════

## E1. Save all remaining research documents to repo and Notion

When the remaining 18 prompts return, save each to:
- `docs/research/` in the repo
- Appropriate Notion category with executive summary

## E2. Update roadmap with findings

Each research document may produce new roadmap items.
Add to `docs/roadmap-additions-2026-03-28.md` with priority levels.

## E3. Integrate conviction calibration framework

**Research:** `docs/research/LLM_Conviction_Score_Calibration_for_Trading.md`

At Phase 1 (5-50 trades): placeholder calibration.
At 50-trade gate: implement Platt scaling on conviction scores.
Add calibration tracking to the CTO report.

## E4. Integrate numerical hallucination prevention

**Research:** `docs/research/Numerical_Hallucination_Prevention_in_Small_Financial_LMs.md`

Verify that the feature engine pre-computes all derived quantities.
Add regex-based post-processing to packet_writer for number validation.
Document the "never let the model compute" principle in AGENTS.md.

## E5. Integrate multi-LoRA serving architecture (document only)

**Research:** `docs/research/Multi-LoRA_Serving_on_Consumer_GPUs.md`

Document the Phase 2 serving architecture in docs/architecture.md:
- llama-server with pre-loaded adapters (not Ollama)
- Per-request adapter selection via API
- KV cache invalidation strategy
- Dual-GPU planning for RTX 3090 upgrade

---

# ══════════════════════════════════════════════════════════════
# PHASE F: DOCUMENTATION & FINAL VERIFICATION
# ══════════════════════════════════════════════════════════════

## F1. AGENTS.md — exact counts

Re-run all count commands and update line 1.

## F2. docs/architecture.md — comprehensive update

Must reflect: council v2, value tracker, all new tables, all new columns,
all new API endpoints, data flow changes, deleted modules.

## F3. CHANGELOG.md

Add entry for this mega sprint.

## F4. docs/roadmap.md

Integrate all research-informed roadmap items.

## F5. Final test run

```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
```

ALL tests pass. Frontend builds. Zero orphaned imports. Zero old agent names.

---

# ══════════════════════════════════════════════════════════════
# TRADING WEEK OBSERVATIONS LOG
# ══════════════════════════════════════════════════════════════

> **Fill this section during the trading week (March 31 – April 4).**
> Document every observation, issue, or question that arises.
> These feed directly into this sprint's priorities.

### Monday March 31
- [ ] Watch loop started cleanly? (Y/N)
- [ ] First scan completed? Results?
- [ ] Traffic Light regime status?
- [ ] Council daily session ran? Direction?
- [ ] Any Telegram alerts?
- [ ] NKE earnings — did PEAD enrichment fire?
- [ ] Issues observed:

### Tuesday April 1
- [ ] Observations:

### Wednesday April 2
- [ ] Observations:

### Thursday April 3
- [ ] NFP preview — council assessment?
- [ ] Observations:

### Friday April 4
- [ ] NFP impact — did Traffic Light respond?
- [ ] Weekly council session ran?
- [ ] Saturday retrain scheduled?
- [ ] Issues observed:

### Sunday April 5 — First Sunday Ritual
- [ ] Export 20 training examples
- [ ] Export halcyon.log (now with file rotation!)
- [ ] Dashboard screenshots
- [ ] Research digest from collector #13
- [ ] Monday action items prepared

---

# Sprint Documentation Checklist (docs/sprint-checklist.md)

### Tier 1 (MANDATORY):
- [ ] AGENTS.md counts match code
- [ ] CHANGELOG.md — mega sprint entry
- [ ] docs/architecture.md — comprehensive update
- [ ] docs/roadmap.md — all research items integrated
- [ ] All tests pass (including new council v2 tests)
- [ ] Frontend builds
- [ ] Render sync verified
- [ ] No orphaned imports
- [ ] No old agent names in active code

### Tier 2:
- [ ] All research docs in Notion with executive summaries
- [ ] config/settings.example.yaml — all new keys documented
- [ ] frontend/src/api.js — all new endpoints
- [ ] Notes page functional on cloud dashboard
- [ ] HSHS radar chart on Health page
