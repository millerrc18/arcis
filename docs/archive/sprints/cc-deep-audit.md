# CC Exploratory Audit: Deep Codebase Review

> **Executor:** Claude Code
> **Goal:** Deep exploratory audit of the ENTIRE codebase. Find every bug, edge case, logic error, race condition, UX gap, missing feature, architectural inconsistency, and improvement opportunity. Open a GitHub Issue for EVERY finding — the more the better, as long as each is genuine and value-added. Do NOT fix anything.
> **Repo:** millerrc18/halcyon-lab
> **Read first:** AGENTS.md, docs/conventions.md
> **Prior audit:** Issues #80-#98 already filed. Do NOT duplicate those. Read them first so you know what's already been found.

---

## Context

Arcis is an autonomous AI equity trading system that runs 24/7 on a Windows machine. It paper trades S&P 100 stocks via Alpaca, uses a fine-tuned Qwen3 8B LLM via Ollama, has a 5-agent AI council, 12 overnight data collectors, a React dashboard on Render, and a training pipeline that improves itself. The system went live March 27, 2026 and has been in rapid development (Sprints 1-6). It's now in "lockdown" — meant to run autonomously with minimal human intervention.

The operator (Ryan) works a full-time job during market hours and cannot intervene. Everything must work unattended. Reliability is paramount.

---

## Audit Methodology

For each category below, READ the actual source code (not just grep). Trace execution paths. Think about what happens at 3 AM when nobody is watching. Think about what happens after 1,000 trades instead of 5. Think about what happens when APIs are down, the network drops, the disk fills up, or the model produces garbage.

**For every finding, open a GitHub Issue with:**
- Clear title: `[category] Specific description`
- Labels: `bug`, `tech-debt`, `security`, `performance`, `reliability`, `ux`, `feature-request`, `documentation`, `test-gap`
- Body: file path, line numbers, what's wrong, WHY it matters, and suggested fix
- Priority estimate: P0 (broken now), P1 (will break soon), P2 (should fix), P3 (nice to have)

---

## 1. TRADING LOGIC (highest stakes — real money at risk)

Read these files end-to-end:
- `src/shadow_trading/executor.py` — trade opening and closing
- `src/shadow_trading/bracket_monitor.py` — bracket health verification
- `src/shadow_trading/reconcile.py` — Alpaca reconciliation
- `src/shadow_trading/alpaca_adapter.py` — broker API interface
- `src/risk/governor.py` — risk checks
- `src/features/traffic_light.py` — regime overlay

Look for:
- Race conditions between scan opening a trade and bracket monitor closing one
- What happens if Alpaca API is down during a scan? Does the system retry? Silently skip? Leave orphan records?
- What happens if a bracket order partially fills? (entry fills, stop/target don't)
- What happens if the same ticker qualifies in consecutive scans? Duplicate position check robust?
- Is the kill switch (halt-trading) truly atomic? Can a trade slip through during halt?
- What if current_price is 0 or None in features? Does the governor catch it?
- What if Alpaca returns a different ticker format (BRK.B vs BRK/B)?
- Timeout logic: what happens on day 7/10 exactly? Is it inclusive/exclusive? Timezone-correct?
- Position sizing: with 0.5x bootcamp TL floor and 0.1x event risk, does the final allocation ever hit $0?
- What happens to GTC orders over a weekend or holiday? Do they expire?

---

## 2. WATCH LOOP RESILIENCE (runs 24/7 unattended)

Read: `src/scheduler/watch.py` (the entire file — it's the system heartbeat)

Look for:
- What happens if ANY single function throws an unhandled exception? Does the whole loop crash, or does it recover?
- Is there a top-level try/except around the main loop? What does it catch?
- What happens if SQLite is locked (another process has it open)?
- What happens if Ollama is not running / crashes mid-inference?
- What happens if the Render Postgres connection drops mid-sync?
- What happens if the system clock jumps (NTP correction, DST change)?
- Memory leaks: does anything accumulate without bound over days/weeks?
- What happens on market holidays? Does the system know about them?
- What if a scan takes longer than the scan interval? Can scans overlap?
- Is the overnight → market transition clean? Any state that doesn't reset?
- What happens if the computer sleeps mid-scan? (This already happened once)
- Does the watch loop log a heartbeat so you can tell it's alive vs stuck?

---

## 3. DATA PIPELINE INTEGRITY

Read:
- `src/data_collection/*.py` (all 12+ collectors)
- `src/data_enrichment/*.py` (fundamentals, insiders, news, macro)
- `src/sync/render_sync.py`

Look for:
- What happens if yfinance returns NaN or None for prices? Does it propagate to features?
- What happens if Finnhub rate-limits you? (60 calls/min)
- What happens if SEC EDGAR returns 429 or 503?
- Are there any collectors that overwrite historical data instead of appending?
- Is there timezone handling for all date comparisons? (market data is ET, UTC in DB?)
- What happens if two sync cycles overlap? (sync_interval=120s but sync takes 130s)
- Are there any tables that grow without bound and never get pruned?
- What happens if Render Postgres has a schema mismatch with local SQLite?
- Does the sync handle NULL values correctly across SQLite ↔ Postgres?

---

## 4. LLM PIPELINE

Read:
- `src/llm/client.py` — Ollama client
- `src/llm/packet_writer.py` — prompt construction + response parsing
- `src/llm/validator.py` — LLM output validation
- `src/llm/grammar_client.py` — GBNF constrained decoding

Look for:
- What happens if Ollama returns empty string? Partial JSON? Timeout?
- What's the timeout for LLM inference? Is it appropriate for 8B model on RTX 3060?
- Does the prompt ever exceed context window (8192 tokens for Qwen3)?
- If the LLM hallucinates a ticker that's not in S&P 100, is it caught?
- If conviction score is outside 1-10 range, what happens?
- What does "template fallback" mean exactly? Is the fallback output useful or just noise?
- XML parsing: what happens with malformed XML tags? Unclosed tags? Extra whitespace?
- Is there prompt injection risk from feature data? (e.g., news headlines with instructions)

---

## 5. TRAINING PIPELINE

Read:
- `src/training/trainer.py` — fine-tuning orchestration
- `src/training/data_collector.py` — training data from closed trades
- `src/training/quality_filter.py` — quality scoring
- `src/training/leakage_detector.py` — TF-IDF leakage test
- `src/training/curriculum.py` — difficulty classification
- `src/training/canary.py` — model degradation monitoring
- `src/scheduler/scorer.py` — between-scan quality scoring

Look for:
- Is the self-blinding actually architectural? Or can outcome data leak through feature fields?
- Does the training data collector handle partial closes (stop hit at partial fill)?
- What happens if training runs while the watch loop is doing inference? GPU contention?
- Is the VRAM handoff between inference and training actually implemented?
- What if there are <10 training examples? Does the trainer handle edge cases?
- Quality scorer (GuardedScorer): what if Ollama returns garbage scores? Are they validated?
- Does the leakage detector work correctly with <50 examples per class?
- Is the canary set actually never used in training? Where is that enforced?

---

## 6. COUNCIL SYSTEM

Read:
- `src/council/engine.py` — session orchestration
- `src/council/protocol.py` — Anthropic API calls
- `src/council/aggregation.py` — vote aggregation
- `src/council/parsing.py` — response parsing
- `src/council/value_tracker.py` — attribution tracking

Look for:
- What happens if the Anthropic API returns 429 (rate limited)?
- What if one agent's response is malformed but others are fine?
- What if all 5 agents agree but the aggregation logic has an off-by-one?
- Is the council result actually used for anything, or just informational?
- What happens if a council session costs >$1? Is there a cost cap?
- Does the rate limiter actually prevent runaway API costs?
- What if the council runs during a scan? Any concurrency issues?

---

## 7. FRONTEND / DASHBOARD

Read all files in `frontend/src/pages/` and `frontend/src/components/`

Look for:
- API calls that will 404 in cloud mode (Codex found some, but look for more)
- Missing error handling: what shows when an API call fails?
- Loading states: do pages show spinners or just blank?
- Stale data: are refetch intervals appropriate? Any that never refresh?
- Mobile breakpoints: anything that's broken on 375px width?
- Accessibility: any color-only indicators without text/icon alternatives?
- Are there any pages that make N+1 API calls (one per trade/row)?
- What happens when there are 0 trades? 0 scans? 0 council sessions? Empty state handling?
- Auth: what happens if AuthGate token expires mid-session?

---

## 8. CONFIGURATION & ENVIRONMENT

Read:
- `src/config.py`
- `config/settings.example.yaml`
- `.env.example`
- `src/config_overrides.py`

Look for:
- Config keys referenced in code but not in settings.example.yaml
- Default values that are dangerous (e.g., max_positions defaulting to something too high)
- Config override whitelist: is it complete? Any dangerous keys that can be overridden from dashboard?
- What happens if settings.yaml doesn't exist? Does the system fail gracefully?
- What happens if .env has a typo in a key name? Silent failure?
- Are there any circular dependencies between config and other modules?

---

## 9. ERROR HANDLING & OBSERVABILITY

Across the entire codebase:
- Find every bare `except:` or `except Exception: pass` (Codex found some in council/context.py, but there may be more)
- Find every place where an error is caught but not logged
- Find every place where a function returns None on error but the caller doesn't check for None
- Are Telegram notifications sent for all critical failures? What failures are silent?
- Is there a dead man's switch? (If the watch loop crashes at 2 AM, does anyone know?)
- What's the logging level? Are there important events at DEBUG that should be INFO?

---

## 10. EDGE CASES & RACE CONDITIONS

Think about temporal edge cases:
- Market open (9:30 AM) — what happens if a scan is running at exactly 9:30?
- Market close (4:00 PM) — what if a trade is mid-execution at close?
- Midnight UTC — any date-boundary issues?
- Saturday retrain — what if the watch loop is also running?
- First of the month — any monthly logic that hasn't been tested?
- What happens after the 50th closed trade? Does the Phase 1 gate evaluation trigger automatically?
- What happens if all 50 positions are open and none close for weeks?

---

## 11. SCALABILITY

Think about what breaks at 10x scale:
- 500 training examples → 5,000: does quality scoring take too long?
- 23 open positions → 50: does the bracket monitor slow down?
- 100 scan_metrics rows → 10,000: any queries that will be slow without indexes?
- 972 training examples → 10,000: does the leakage detector still work?
- 1 model version → 10: does versioning handle history correctly?
- 12 collectors × 365 days: how much data accumulates? Any pruning?

---

## 12. DOCUMENTATION GAPS

- Are there any modules where the docstring says something different from what the code does?
- Are there any "Called by" lists that are incomplete?
- Are there any outdated comments that reference Halcyon Lab instead of Arcis?
- Are there decision documents (docs/decisions/) that should exist but don't?
- Is there any tribal knowledge that's only in Claude conversation history, not in docs?

---

## Output Requirements

1. Open a GitHub Issue for EVERY finding (use the GitHub API)
2. Group trivially related findings (e.g., "5 files missing None check for the same function" = 1 issue)
3. Tag issues with milestone "Phase 1: 50 Closed Trades" if they could affect trading reliability
4. At the end, create a summary issue titled "CC Deep Audit Summary — [DATE]" with:
   - Total issues opened
   - Breakdown by label and priority
   - Top 5 most critical findings
   - Top 5 highest-ROI improvements
   - Overall assessment and recommendations

## Existing Issues (DO NOT DUPLICATE)

Already filed: #80-#98. Read them before starting. If you find something that overlaps, reference the existing issue instead of creating a new one.
