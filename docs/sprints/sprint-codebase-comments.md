# Sprint: Codebase Documentation — Inline Comments for AI Agent Context

> **Priority:** MEDIUM — quality-of-life for all future CC sprints
> **Estimated time:** 4-6 hours CC time
> **Why this matters:** AI agents (CC, Codex) are the sole developers. They lose context between sessions. Comments in the code ARE the context. A well-commented file means CC can understand WHY a decision was made without reading 60 research docs. Every comment is an investment that pays off on every future sprint.

> ⚠️ **Rules:**
> - Do NOT change any logic, behavior, or formatting. Comments ONLY.
> - Do NOT refactor, rename, or reorganize anything.
> - Run `python -m pytest tests/ -x -q` before AND after. Pass count must not change.
> - If a file is over 400 lines, do NOT add so many comments that it exceeds the guardrail.

---

## What Good Comments Look Like

**BAD (what the code does — reader can see that):**
```python
# Get the account info
account = get_account_info()

# Check if VIX is above 35
if vix > 35:
```

**GOOD (why the code does it — reader can't see that):**
```python
# Alpaca paper account — used for Phase 1 bootcamp tracking (not live capital)
account = get_account_info()

# VIX > 35 = extreme fear. Strategy Decision #6: halt all new entries.
# Historically, VIX > 60 is a 100% reliable buy signal, but 35-60 is
# a regime where pullback setups have negative expectancy.
if vix > 35:
```

**Comment priorities (in order):**
1. **WHY** decisions were made — link to strategy decisions, research docs, or incidents
2. **GOTCHAS** that would bite a future agent — "don't use time.sleep() here because..."
3. **BUSINESS LOGIC** explanations — "bootcamp phase uses 50 max positions because..."
4. **MAGIC NUMBERS** — "2.0 ATR multiplier per Strategy Decision #18, optimal through 200 trades"
5. **DATA FLOW** — "this value comes from X, feeds into Y, consumed by Z"

---

## Phase 1: Critical Path Files (do these first)

These are the files CC modifies most often and where context loss causes the most bugs.

### 1.1 `src/scheduler/watch.py` (~3,080 lines)
The main loop. Every scan, trade, and overnight task flows through here.
- Comment each numbered section (0, 0.5, 1, 1.5, 2, 2.5, 3...) explaining WHAT triggers it and WHY at that time
- Comment the timing constants (why 15 min for position monitor, why 30 min for scans, why 60 min for sentiment)
- Comment the daily reset block — what state gets cleared and why
- Comment the overnight collector list — what each one does and which API it calls
- Comment the sleep recovery detection — why it matters (computer sleep during market hours killed scans)
- Comment the backoff/retry mechanism — what triggers escalation
- Comment `_get_live_stats()` — where each stat comes from and what "N/A" means

### 1.2 `src/shadow_trading/executor.py` (~1,436 lines)
The trade execution engine. Wrong behavior here = lost money.
- Comment `open_shadow_trade()` — the full decision chain (qualify → governor → bracket → log)
- Comment paper vs live dispatch — when each fires and why they have different risk params
- Comment the ATR-based stop/target calculation — reference Strategy Decision #18
- Comment `check_and_manage_open_trades()` — each exit path (stop, target, timeout, MR RSI exit)
- Comment the MR exit dispatcher — why it runs BEFORE bracket logic (strategy-aware exits)
- Comment the dual execution block — paper always fires, live only if enabled + governor passes
- Comment why `_parse_price()` exists (LLM outputs prices in various formats)
- Comment the attribution logging points — Phase 1 (before LLM) and Phase 2 (after)

### 1.3 `src/shadow_trading/alpaca_adapter.py` (~549 lines)
The broker interface. Alpaca API quirks live here.
- Comment each function's retry behavior and failure mode
- Comment `place_bracket_order()` — GTC semantics, what happens if partial fill
- Comment paper vs live client initialization — different base URLs, different keys
- Comment notional ordering (fractional shares) vs share ordering — when each is used
- Comment `_serialize_order()` — why it exists (Alpaca Order objects aren't JSON serializable)

### 1.4 `src/schema/registry.py` (~1,386 lines)
49 tables. Every column should say WHY it exists.
- Add a one-line comment above each `TableDef` explaining what it tracks and who writes to it
- For columns with non-obvious purposes (like `drawdown_from_mfe`), add inline comments
- Comment the sync configuration (sync_to_postgres, sync_mode, sync_time_column) — when and why

### 1.5 `src/features/regime.py` + `src/features/engine.py` + `src/features/setup_classifier.py`
The feature pipeline determines what the model sees.
- Comment the traffic light logic — what each regime label means for trading
- Comment the scoring weights — why pullback_depth is weighted higher than volume
- Comment each technical indicator — what it measures and what good/bad values look like
- Comment the 7 signal dimensions — reference Alternative Data research doc

---

## Phase 2: AI/Training Pipeline

### 2.1 `src/training/data_collector.py`
- Comment the self-blinding architecture — why outcome data is NEVER in the prompt
- Comment the outcome-conditioned template block — why output_text is empty (batch later)
- Comment the quality gate (halt_batch) — when and why training halts

### 2.2 `src/training/trainer.py` (~794 lines)
- Comment the curriculum stages (structure → evidence → decision)
- Comment the learning rate schedule (3e-4 → 2e-4 → 1e-4)
- Comment the champion-challenger evaluation — what triggers a rollback
- Comment the VRAM handoff — why training and inference can't run simultaneously on 12GB

### 2.3 `src/training/outcome_prompts.py`
- Comment WHY each prompt template is worded the way it is (reference Prompt Engineering research)
- Comment the self-blinding guarantee — the template shapes analysis FOCUS, not CONCLUSION
- Comment the contrastive pair generation — these become DPO training pairs

### 2.4 `src/llm/packet_writer.py`
- Comment the LLM prompt construction — what XML tags the model expects
- Comment `_parse_llm_response()` — each fallback pattern and when it activates
- Comment the conviction extraction — the 5 patterns and their priority order
- Comment the prose fallback — when no XML tags are found at all

---

## Phase 3: Risk & Evaluation

### 3.1 `src/risk/governor.py`
- Comment each of the 8 checks with its threshold and WHY that threshold
- Comment the kill switch mechanism — file-based persistence across restarts
- Comment the graduated drawdown — Ed Thorp's protocol, linear 100%→0% from 0%→20% DD

### 3.2 `src/council/engine.py` (~554 lines)
- Comment the Modified Delphi protocol — why 3 rounds, what changes between rounds
- Comment each agent role and what perspective it brings
- Comment the consensus calculation — how votes translate to traffic light
- Comment the anti-sycophancy interventions — what prevents agents from just agreeing

### 3.3 `src/evaluation/build_score.py` + `src/evaluation/hshs_live.py`
- Comment the 6 build score components and their geometric mean
- Comment HSHS (Health Score) — 5 dimensions, phase weighting
- Comment the float() casts — WHY they're there (SQLite TEXT column incident #181)

---

## Phase 4: API Routes & Infrastructure

### 4.1 All files in `src/api/routes/` (14 files, mostly 0% comments)
- Add a comment block at the top of each route file listing the endpoints it serves
- Comment any route that does something non-obvious (e.g., `/actions/cto-report` submits `cto-report` command, not `scan`)
- Comment auth handling — when Bearer token is required vs optional

### 4.2 `src/sync/render_sync.py` (~737 lines)
- Comment the sync architecture — pull-based, local SQLite → Render Postgres
- Comment `ON CONFLICT DO NOTHING` — why it's there (incident #185)
- Comment per-table reconnection — why each table retries independently
- Comment the sync_interval and batch size choices

### 4.3 `src/notifications/telegram.py` (~1,494 lines)
- Comment which notifications are gated behind `trade_id` and why
- Comment the 32 notification functions — group by category
- Comment rate limiting and message formatting

---

## Phase 5: Scripts

### 5.1 All files in `scripts/` (35 files)
- Each script should have a module docstring explaining:
  - When to run it (daily? weekly? one-time?)
  - What it reads and writes
  - Any prerequisites (env vars, running services)
- Comment any non-obvious shell commands or SQL queries

---

## Verification

After ALL commenting is complete:
- `python -m pytest tests/ -x -q` — pass count UNCHANGED
- `cd frontend && npm run build` — still succeeds
- `python -m src.main watch --help` — still works
- `wc -l src/scheduler/watch.py` — should not exceed ~3,300 (was 3,080, comments add ~7%)
- Spot check: open 5 random files and verify comments explain WHY, not WHAT

---

## Commit

```bash
git add src/ scripts/
git commit -m "docs: comprehensive inline comments across 200+ Python files

Added WHY-focused comments to every Python module in src/ and scripts/.
Priority: business logic rationale, strategy decision references, gotchas,
magic number explanations, data flow documentation.

Key files commented:
- watch.py: 27 event blocks, timing rationale, recovery logic
- executor.py: trade lifecycle, risk params, dual execution, attribution
- alpaca_adapter.py: API quirks, retry behavior, order types
- registry.py: 49 table purposes, column rationale, sync config
- governor.py: 8 check thresholds with strategy decision references
- council/engine.py: Modified Delphi protocol, anti-sycophancy
- trainer.py: curriculum stages, VRAM handoff, champion-challenger

Zero logic changes. Zero behavior changes. Test count unchanged."
```
