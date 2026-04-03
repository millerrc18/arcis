# Arcis Master Implementation Plan — Sprints A through 7

> **Date:** April 3, 2026 (verified against PR history — all tasks still pending)
> **Scope:** 7 sprints covering dashboard polish, documentation consolidation, and all 5 strategic priorities from deep research synthesis
> **How to use:** Each sprint section is a self-contained CC prompt. Fire them in order. Copy the sprint section + its acceptance criteria into CC.
> **Dependencies:** Sprint 2 (Bug Bash: #182, #183, #184) must complete first.
> **New files:** Sprints 4-7 reference `src/` files that don't exist yet — they are TO BE CREATED by the sprint (e.g., `src/features/mean_reversion.py`, `src/scheduler/position_monitor.py`, `src/training/outcome_prompts.py`). This is intentional.

---

## Sprint Sequence

| Sprint | Name | Est. Hours | Status |
|---|---|---|---|
| **A** | Dashboard Polish + Documentation Consolidation | 4-6 | READY TO FIRE |
| **3** | Alpha Attribution Experiment | 4-6 | Blocked on Sprint 2 (#183 conviction parsing) |
| **4** | Mean Reversion Paper Trading | 4-6 | No hard blockers |
| **5** | Multi-Cadence Scanning | 6-8 | Depends on Sprint 4 (MR RSI exit) |
| **6** | Outcome-Conditioned Training Pipeline | 3-4 | Benefits from Sprint 3 (PASS examples) |
| **7** | Historical Stress Testing | 2-3 | Uses Sprint 3 backtester extensions |

---

## Research Traceability

Every sprint deliverable traces to a specific research document. CC should read the linked research when it needs deeper context on WHY a decision was made.

### Source Research Documents

| ID | Document | Path | Lines | Key Findings |
|---|---|---|---|---|
| **R1** | Horizontal Training Data | `docs/research/deep-research/horizontal-training-data-RESULTS.md` | 228 | Only 7-8 orthogonal dimensions for S&P 100. 11-section hard cap. Random source subsetting. |
| **R2** | Scanning Intervals | `docs/research/deep-research/scanning-intervals-RESULTS.md` | 240 | 4-tier cadence. Split position monitoring from scanning. 60% API reduction. FMP 250/day binding. |
| **R3** | Full Strategy (9-part) | `docs/research/deep-research/full-strategy-RESULTS.md` | 984 | Alpha attribution experiment. Mechanical brackets through 200 trades. Options at $15-25K. Revenue sequencing. GPU priority stack. Flywheel friction audit. |
| **R4** | Framework Synthesis | `docs/research/deep-research/SYNTHESIS-framework-update-roadmap-changes.md` | 237 | 8 approved strategy decisions (#17-24). Phase gate changes. Exit management framework. GPU targets. |
| **R5** | Red Team Interview | `docs/research/deep-research/red-team-interview.md` | 208 | 7 interview scenarios. Known gaps list. "Does the LLM add alpha?" surfaced as existential question. |

### Sprint-to-Research Mapping

| Sprint | Task | Research Source | What to Read |
|---|---|---|---|
| **A** | Audit banner redesign | — | No research dependency (UX fix) |
| **A** | Build score / CTO report | — | No research dependency (bug fix) |
| **A** | MASTER.md creation | R4 | Section 5 (strategy decisions), Section 6 (phase gates), Section 7 (frameworks) |
| **3** | Alpha attribution experiment design | R3 Part 0 | "Deliverable 1: Alpha Attribution Experiment Design" — McNemar's test, 200+ paired trades, decomposition framework |
| **3** | Parallel shadow portfolio | R3 Part 0 | "The Parallel Shadow Portfolio" — matched pairs vs independent, 3 trade categories |
| **3** | Statistical power requirements | R3 Part 0 | Power table: 200 trades for 10% detection at 80% power. 50 trades = only 28% power. |
| **3** | Historical backtest | R3 Part 7 | "Deliverable 23: GPU Activity Priority Stack" — alpha attribution backtest is #1 priority |
| **4** | RSI(2) mean reversion scanner | R3 Part 2 | "Should paper-trading of strategy #2 start in Phase 1? YES, unambiguously." + 130-390 examples in 6 months |
| **4** | Strategy-aware exit dispatcher | R3 Part 1 | "Deliverable 5: Phased Recommendation" — mechanical brackets Phase 1-2, LLM pilot Phase 3 |
| **4** | RSI exit threshold (>70) | R4 Strategy #2 | Mean Reversion / Connors RSI(2), ρ=−0.35 |
| **5** | 4-tier multi-cadence | R2 | Full document — information half-life table, polling schedule, dual-cadence architecture |
| **5** | Staleness detection | R2 Section 4 | "Staleness Tolerance Matrix" — acceptable/warning/critical per dimension |
| **5** | Position monitor split | R2 Section 7 | "Open Position Monitoring vs. Universe Scanning" — different cadences for different jobs |
| **6** | Outcome-conditioned prompts | R3 Part 6 | "Deliverable 20: Friction Audit" — 5 categories of signal waste, 3-5x yield target |
| **6** | Contrastive examples (DPO pairs) | R3 Part 6 | "Link 2: Outcomes → Training Data" — outcome-type-blind generation identified as HIGH friction |
| **6** | 8 metadata columns | R3 Part 6 | "Fix: Add 8 columns to shadow_trades" — regime_at_entry/exit, vix, time_to_target, etc. |
| **7** | Stress testing (2008/2020/2022) | R3 Part 7 | "Deliverable 23" — historical stress testing is #2 GPU priority, answers allocator's #1 question |
| **7** | VIX-regime stop validation | R3 Part 1 | "Deliverable 3: Optimal Mechanical Exit Parameters" — ATR multipliers by regime |
| **7** | Extended backtester metrics | R3 Part 2 | "Deliverable 8: The Options Case" + Part 1 evidence table for calmar, monthly returns |

### Additional Research (reference only, not sprint-blocking)

| Topic | Document | Path |
|---|---|---|
| Training data architecture (11 sections) | Horizontal Training Data (prompt) | `docs/research/deep-research/horizontal-training-data-DRAFT.md` |
| Position management literature | Full Strategy prompt Part 1 | `docs/research/deep-research/full-strategy.md` |
| Options minimum capital derivation | Full Strategy Results Part 2.3 | `docs/research/deep-research/full-strategy-RESULTS.md` |
| Revenue stream ranking | Full Strategy Results Part 3 | `docs/research/deep-research/full-strategy-RESULTS.md` |
| Insurgent advantage analysis | Full Strategy Results Part 8 | `docs/research/deep-research/full-strategy-RESULTS.md` |
| Self-blinding pipeline | Research corpus | `docs/research/Prompt_Engineering_for_Outcome-Conditioned_Training_Data_Generation_...md` |
| Quality rubric (6 dimensions) | Research corpus | `docs/research/Gold-Standard_Rubric_for_Scoring_Equity_Trade_Commentary_...md` |
| Model degradation prevention | Research corpus | `docs/research/Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining_...md` |

---

# SPRINT A: Dashboard Polish + Documentation Consolidation

> **Priority:** HIGH — Dashboard shows misleading data + agents waste 34K tokens reading 5 overlapping docs
> **Scope:** 4 frontend fixes + 2 backend fixes + full documentation restructure
> **Note:** Roadmap page already updated (529 lines) — do NOT touch `Roadmap.jsx`.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after. Run `cd frontend && npm run build` after all frontend changes.**

## Pre-Flight (Sprint A)

1. Read `SYSTEM_STATE.md` — current state
2. Read `AGENTS.md` — architecture overview, data sources, CLI commands
3. Read `CLAUDE.md` — CC rules (this stays as-is, 104 lines)
4. Read `docs/conventions.md` — module docstring format, adding features/collectors
5. Read `docs/sprint-checklist.md` — post-sprint documentation requirements
6. Read `frontend/src/pages/Dashboard.jsx` — audit banner (lines 15-28, 224-232), build score (BuildScoreCard ~line 38)
7. Read `frontend/src/components/ActivityFeed.jsx` — event type switch (lines 40-78), normalizer (line 82)
8. Read `src/api/cloud_routes/training.py` lines 261-275 — audit latest endpoint (NOT in core.py)
9. Read `src/api/cloud_routes/core.py` lines 357-395 — action button command mappings
10. Read `src/commands/executor.py` — COMMAND_HANDLERS dict (note: `cto-report` is MISSING)
11. Read `src/evaluation/build_score.py` — `persist_build_score()` (line 368)
12. Run `python -m pytest tests/ -x -q` — record baseline

---

## Task A1: Redesign Audit Banner

**File:** `frontend/src/pages/Dashboard.jsx`

The current red audit banner dumps raw auditor text. Replace with a compact expandable chip.

### Current implementation:
- `parseAuditSummary()` (lines 15-28) — improve, don't rewrite
- Banner at lines 224-232 shows when `auditAssessment !== 'green'`
- API: `GET /api/audit/latest` in `src/api/cloud_routes/training.py:261`

### Collapsed state (default):
Single-line chip, right-aligned near "HALT TRADING":

| Condition | Chip |
|---|---|
| `overall_assessment === 'green'` or `'healthy'` | `🟢 System OK` — subtle green |
| `overall_assessment === 'yellow'` or `'warning'` | `🟡 Warnings` — amber |
| `overall_assessment === 'red'` or `'critical'` | `🔴 Issues found` — red (NOT a screaming wall) |
| No audit data (`{audit: null}`) | `⚪ No audit` — muted |
| `created_at` >24 hours old | `⚪ Stale (>24h)` — muted, OVERRIDES assessment |

Staleness check:
```javascript
const auditCreatedAt = auditData?.created_at || auditData?.audit_date
const isStale = auditCreatedAt && 
  (Date.now() - new Date(auditCreatedAt).getTime()) > 24 * 60 * 60 * 1000
```

### Expanded state (on click):
Card below chip: assessment icon, clean summary (max 300 chars), "Last audit: 2 hours ago" relative timestamp, "Collapse" link.

### Design:
- Chip: `inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium cursor-pointer`
- Card: `rounded-lg border p-4 mt-2` with Arcis palette
- `useState` toggle — collapsed by default
- NEVER show raw JSON, code fences, or truncated garbage

---

## Task A2: Fix Build Score Empty State + CTO Report Button

### A2a: Frontend empty state
**File:** `frontend/src/pages/Dashboard.jsx`

BuildScoreCard (~line 38) shows 0.0 when `build_score_history` is empty. When API returns all zeros:
```jsx
if (!data || (data.build_score === 0 && (!data.components || Object.values(data.components).every(v => v === 0)))) {
  return (
    <div className="card p-4 text-center">
      <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>Build Score not yet computed</span>
      <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>Click "Generate CTO Report" or wait for 4:30 PM ET</p>
    </div>
  )
}
```

### A2b: Add `cto-report` command handler
**File:** `src/commands/executor.py`

"Generate CTO Report" maps to `_submit_command("scan")` — WRONG. Add handler:
```python
def _handle_cto_report(payload: dict, config: dict) -> dict:
    """Generate CTO report and compute build score."""
    from src.evaluation.build_score import persist_build_score
    result = persist_build_score()
    return {"build_score": result.get("build_score", 0), "components": result.get("components", {}), "status": "completed"}
```
Add to COMMAND_HANDLERS: `"cto-report": _handle_cto_report,`

### A2c: Fix action endpoint mappings
**File:** `src/api/cloud_routes/core.py`

```python
# FROM (both wrong — submit scan instead of cto-report):
def action_cto_report(): return _submit_command("scan")
def action_score(): return _submit_command("scan")

# TO:
def action_cto_report(): return _submit_command("cto-report")
def action_score(): return _submit_command("cto-report")
```

---

## Task A3: Fix Activity Feed "task: ?" Entries

**File:** `frontend/src/components/ActivityFeed.jsx`

Fix overnight_task case (lines 61-62):
```javascript
case 'overnight_task': {
  if (d.task) {
    const parts = [`${d.task.replace(/_/g, ' ')}: ${d.status || 'complete'}`]
    if (d.articles_cached) parts.push(`(${d.articles_cached} articles)`)
    if (d.tickers_enriched) parts.push(`(${d.tickers_enriched} tickers)`)
    return parts.join(' ')
  }
  return evt.detail ? String(evt.detail).slice(0, 120) : 'Overnight task completed'
}
```

Fix default case (lines 74-77):
```javascript
default: {
  const detail = evt.detail || ''
  if (detail && !detail.startsWith('{')) return detail.slice(0, 120)
  const eventName = (evt.type || evt.event || 'system').replace(/_/g, ' ')
  const summary = d.detail || d.message || d.status || ''
  return summary ? `${eventName}: ${String(summary).slice(0, 80)}` : eventName
}
```

---

## Task A4: Create MASTER.md

Create `MASTER.md` in repo root. This consolidates 5 docs / 34K tokens into ~1,000 lines / ~5K tokens. Inverted pyramid structure — most critical info first.

### Sources to absorb:
- `SYSTEM_STATE.md` (509 lines) — all content
- `AGENTS.md` (280 lines) — architecture, data sources, CLI, scope
- `docs/conventions.md` (122 lines) — module patterns, adding features/collectors
- `docs/sprint-checklist.md` (45 lines) — post-sprint requirements
- `docs/schema-governance.md` (375 lines) — condensed schema rules

### Section outline:

**Section 1: System Identity (~30 lines)**
- What Arcis is, repo URL, dashboard URL, license, owner
- Single-paragraph system description

**Section 2: Current State — Volatile (~80 lines)**
- Phase progress, trade count, open issues table
- What's deployed, active sprint, known blockers
- Last audit results

**Section 3: Architecture Overview (~100 lines)**
- System flow: Universe → Features → Ranking → LLM → Trade
- Component table: module, purpose, key entry point file
- Data sources table (7 enrichment + 12 collection)
- Infrastructure: SQLite, Render Postgres, Ollama, Alpaca

**Section 4: Schema Summary (~60 lines)**
Table of all tables with purpose and key columns (NOT full DDL):
```markdown
| Table | Purpose | Key Columns | Sync |
|---|---|---|---|
| shadow_trades | Trade ledger | trade_id, ticker, status, pnl_dollars | incremental |
...
```
Note: "Full DDL in `src/schema/registry.py` — the single source of truth."

**Section 5: Strategy Decisions (~40 lines)**
All 24 decisions, numbered — copy from SYSTEM_STATE.md.

**Section 6: Phase Gates (~20 lines)**
Gate table — copy from SYSTEM_STATE.md.

**Section 7: Frameworks (~80 lines)**
- GPU Utilization (4 time blocks)
- Exit Management (4 phases)
- Scanning Cadence (4 tiers)
- Training Data (11 sections, random subsetting)

**Section 8: Revenue & Business (~30 lines)**
Revenue milestones (month 0→36), fund path, hardware path.

**Section 9: Conventions & Rules (~100 lines)**
Absorb from conventions.md, sprint-checklist.md, CLAUDE.md:
- Module docstring format (5-field header)
- Adding features / collectors / endpoints (step-by-step)
- Sprint checklist (required/optional docs)
- Schema rules (registry is source of truth, never DDL outside registry)
- Codebase guardrails (no file >400 lines, no function >60 lines, ≤10 tasks/sprint)
- PR review rules

**Section 10: Key Principles (~40 lines)**
- Training data quality is #1 competitive advantage
- Self-blinding is architectural, not instructional
- Quality > quantity (LIMA, AlpaGasus)
- Dashboard is the control plane
- Never refactor and add features in same sprint
- The data asset is the most valuable component

**Section 11: Sprint Queue (~40 lines)**
Current queue with status.

**Section 12: Reference Pointers (~30 lines)**
```markdown
| Topic | Document |
|---|---|
| Full table DDL | `src/schema/registry.py` |
| Deep research results | `docs/research/deep-research/` |
| Implementation plan | `docs/sprints/implementation-plan-sprints-3-7.md` |
...
```

**Section 13: Brand (~15 lines)**
Name, palette, typography, voice.

---

## Task A5: Archive Original Documents

**Note:** `docs/archive/` already exists with 49 files from PR #179 (old sprints, audits, quality docs). We're adding `governance/` and `reference/` subdirectories for the main docs being absorbed into MASTER.md.

```bash
mkdir -p docs/archive/governance docs/archive/reference

# Governance (absorbed into MASTER.md)
mv SYSTEM_STATE.md docs/archive/governance/
mv AGENTS.md docs/archive/governance/
mv docs/conventions.md docs/archive/governance/
mv docs/sprint-checklist.md docs/archive/governance/
mv docs/schema-governance.md docs/archive/governance/

# Reference (superseded by source of truth)
mv docs/architecture.md docs/archive/reference/
mv docs/database-schema.md docs/archive/reference/
mv docs/dependency-graph.md docs/archive/reference/
mv docs/roadmap.md docs/archive/reference/
mv docs/roadmap-complete.md docs/archive/reference/
mv docs/diagrams.md docs/archive/reference/
```

Create `docs/archive/README.md` explaining what was moved and why.

---

## Task A6: Update All References

- **CLAUDE.md:** Change `AGENTS.md` → `MASTER.md`
- **src/api/routes/docs.py:** Serve MASTER.md instead of archived files
- **README.md:** Point documentation section to MASTER.md
- **docs/sprints/TEMPLATE.md:** Reference MASTER.md Section 9 for sprint checklist
- **scripts/verify_docs.py:** Currently reads `SYSTEM_STATE.md` for count validation — **MUST update** to read `MASTER.md` Section 2 instead, or it will crash after the archive. The script defines `STATE_FILE = ROOT / "SYSTEM_STATE.md"` — change to `ROOT / "MASTER.md"` and update the regex patterns to match the new format.
- Check for any other stale references: `grep -rn "SYSTEM_STATE.md\|AGENTS.md\|architecture.md\|sprint-checklist" scripts/ .github/ .husky/ 2>/dev/null`

---

## Task A7: Update MASTER.md Volatile Section + Verify

After all changes, update Section 2 with current numbers. Run:
- `python -m pytest tests/ -x -q`
- `cd frontend && npm run build`
- `python scripts/verify_docs.py` (update if needed)
- Verify dashboard Docs page loads MASTER.md

---

## Task A8: Watch Loop Console Output Improvements

**File:** `src/scheduler/watch.py` — `_print_banner()` (line 356) and main loop (line ~1475)

The startup banner is the operator's primary window into system health. It prints once at startup and then never again — even during 6+ hour market sessions. Three improvements:

### A8a: Enrich the startup banner

Current banner shows basic config. Add live system state below it:

```
=============================================
 ARCIS - WATCH MODE
=============================================
 Time: 2026-04-03 09:25:00 ET
 LLM: connected (halcyon-v1.0.0)
 Shadow Trading: enabled | Live: enabled (1% risk)
 Bootcamp: Phase 1 — 13/50 trades (26%)
 Training: 972 examples (last retrain: Mar 29)

 Portfolio:
   Open positions: 25 paper / 4 live
   Account equity: $102,340 | Buying power: $5,253
   Today P&L: +$127.50 (+0.12%)
   Open P&L: -$340.20 (-0.33%)

 Schedule:
   Morning watchlist: 8:00 ET
   Market scans: every 30 min (9:30-16:00 ET)
   EOD recap: 16:00 ET
   Overnight: enabled

 System:
   Open issues: 7 (2 critical: #182, #183)
   Last audit: green (2h ago)
   DB: SQLite (WAL mode) | Render sync: active
   GPU: ~4.4% utilization (target: 30-40%)

 Press Ctrl+C to stop.
=============================================
```

Implementation: After the existing banner print, query:
- `get_open_shadow_trades()` → count paper vs live
- `get_account_info()` from alpaca_adapter → equity, buying power
- Open P&L from shadow_trades where status='open' → sum pnl
- Phase progress from `_compute_phase_progress()`
- Open issues count from a simple SELECT on known bug tables (or hardcode for now)
- Last audit assessment + age from `audit_reports`

Wrap in a helper `_get_live_stats()` that returns a dict. If any query fails, show "N/A" — never crash the banner.

### A8b: Periodic status heartbeat

Add a `_last_status_print` timestamp and reprint a condensed status block every **60 minutes** during market hours. Not the full banner — a compact 4-line summary:

```
─── ARCIS STATUS (10:30 ET) ──────────────────
 Phase 1: 13/50 | 25 open | Equity: $102,340 | Today: +$127.50
 Last scan: 10:00 (3 packets, 1 trade) | Next: 10:30
 GPU: 4.4% | Audit: green | Sync: OK
──────────────────────────────────────────────
```

Implementation in main loop (near `time.sleep(60)`):
```python
# Periodic status heartbeat (every 60 min during market hours)
if (self._is_market_hours(now) 
    and (not self._last_status_print 
         or (now - self._last_status_print).total_seconds() > 3600)):
    self._print_status_heartbeat()
    self._last_status_print = now
```

### A8c: Improve scan cycle output

Current: `[WATCH] 10:05 ET -- market open, scanning...` then individual trade lines.

Add a scan summary line AFTER the scan completes:
```
[WATCH] 10:05 ET — Scan complete: 100 tickers → 8 qualified → 3 packets → 1 trade (CAT $731.86)
```

This is a one-line change after the existing `broadcast_sync("scan_complete", ...)` call. Use the metrics already computed in `_record_scan_metrics()`.

### A8d: Banner reprint on significant events

Reprint the full banner (not just heartbeat) on:
- New day (midnight reset) — already prints `[WATCH] New day: ...` 
- First scan of the day (9:30 AM)
- After training completes
- After model version changes

Add `self._reprint_banner_on_next_cycle = False` flag. Set it to `True` on these events. Check in main loop before the sleep.

---

## Acceptance Criteria (Sprint A)

### Dashboard
- [ ] Audit: compact chip, not red wall. 🟢/🟡/🔴/⚪ states. Staleness detection. Click expands.
- [ ] Build Score: empty state shows "Not yet computed" (not 0.0)
- [ ] CTO Report button submits `cto-report` (not `scan`). Handler calls `persist_build_score()`.
- [ ] Score button submits `cto-report` (not `scan`). Scan button still works.
- [ ] Activity feed: no "task: ?" entries. Default case is human-readable.

### Documentation
- [ ] `MASTER.md` exists, ~800-1,000 lines, 13 sections populated with real data
- [ ] 11 docs archived to `docs/archive/` (not deleted)
- [ ] `CLAUDE.md` → MASTER.md reference. `docs.py` serves MASTER.md. `README.md` updated.
- [ ] `docs/archive/README.md` exists
- [ ] No broken references in src/ or frontend/

### Watch Loop Console
- [ ] Startup banner shows portfolio stats (open positions, equity, buying power, today P&L)
- [ ] Startup banner shows phase progress (13/50) and open issues count
- [ ] Status heartbeat prints every 60 min during market hours (compact 4-line block)
- [ ] Scan complete line shows full pipeline summary (tickers → qualified → packets → trades)
- [ ] Full banner reprints on new day, first scan, and post-training
- [ ] All queries wrapped in try/except — banner never crashes on data fetch failure

### Zero Regressions
- [ ] All tests pass, `npm run build` succeeds, all 16 dashboard pages load

---

# SPRINT 3: Alpha Attribution Experiment

> **Priority:** EXISTENTIAL — answers "does the LLM add alpha?"
> **Estimated CC time:** 4-6 hours
> **Dependencies:** Bug Bash (#183 conviction parsing fixed)
> **Files touched:** ~6 new + 3 modified

## Why Sprint 3 Is Existential

Every downstream decision — GRPO, training data, hardware, fund narrative — depends on whether the LLM adds alpha over the deterministic ranker. Research says 200+ paired trades needed (6-8 months). Start the clock NOW.

## Architecture

Simulation ledger, NOT a second Alpaca account. Tracks what the ranker alone WOULD have done:

```
Scan → Rank → packet_worthy candidates
               ├── LLM Portfolio (existing): enhance + trade
               └── Ranker-Only Simulation (NEW): log + simulate mechanically
```

## Implementation

### Task 3.1: Schema — `attribution_trades` table
New table in registry:

| Column | Type | Purpose |
|---|---|---|
| `attribution_id` | TEXT PK | UUID |
| `recommendation_id` | TEXT FK | Links to recommendations |
| `ticker` | TEXT | |
| `scan_timestamp` | TEXT | When ranker qualified |
| `ranker_score` | REAL | Deterministic score (0-100) |
| `llm_conviction` | INTEGER | NULL if LLM skipped/failed |
| `llm_action` | TEXT | `taken`, `rejected`, `parse_failed`, `conviction_none` |
| `ranker_only_entry` | REAL | Price at qualification |
| `ranker_only_stop` | REAL | Mechanical stop |
| `ranker_only_target` | REAL | Mechanical target |
| `ranker_only_outcome` | TEXT | `win`, `loss`, `timeout`, `pending` |
| `ranker_only_pnl_pct` | REAL | Simulated P&L |
| `llm_portfolio_outcome` | TEXT | What LLM portfolio did |
| `llm_portfolio_pnl_pct` | REAL | Actual P&L (NULL if not taken) |
| `pair_type` | TEXT | `both_taken`, `llm_rejected`, `llm_upgraded` |
| `created_at` | TEXT | |

### Task 3.2: Two-phase attribution logging in watch.py
**Phase 1 (BEFORE LLM, after ranking):** Create row for every packet_worthy candidate. `llm_action = "pending"`.
**Phase 2 (AFTER LLM):** Update row with `llm_action`, `llm_conviction`.

This captures `llm_rejected` trades — the most informative category.

### Task 3.3: Mechanical outcome simulator
Post-close job (4:30 PM): for each `pending` attribution row, fetch historical OHLCV from entry date, simulate bracket:
```python
def simulate_mechanical_outcome(entry_price, stop_price, target_price, timeout_days, ohlcv):
    for day_idx, row in enumerate(ohlcv.itertuples()):
        if row.Low <= stop_price: return "loss", stop_price, day_idx + 1
        if row.High >= target_price: return "win", target_price, day_idx + 1
    return "timeout", ohlcv.iloc[-1]["Close"], timeout_days
```

### Task 3.4: Historical backtest script
`scripts/alpha_attribution_backtest.py` — uses existing backtester. For each historical date: run ranker → record qualified → compute outcomes → compare to LLM decisions. 1-2 days GPU time.

### Task 3.5: Dashboard — Attribution page
New page: paired trade count, win rate comparison, McNemar's p-value, category breakdown (`both_taken`, `llm_rejected`, `llm_upgraded`), "Is LLM adding alpha?" verdict.

### Task 3.6: Tests + MASTER.md update

## Acceptance Criteria (Sprint 3)
- [ ] `attribution_trades` table created via schema registry
- [ ] Every packet_worthy candidate logged BEFORE LLM processing
- [ ] LLM action (taken/rejected/parse_failed/conviction_none) recorded
- [ ] Mechanical outcome simulator runs post-close
- [ ] Historical backtest script produces attribution results
- [ ] Dashboard Attribution page renders with paired trade stats
- [ ] All tests pass, `npm run build` succeeds

---

# SPRINT 4: Mean Reversion Paper Trading

> **Priority:** HIGH — bear market insurance + 2-3x data generation
> **Estimated CC time:** 4-6 hours
> **Dependencies:** None hard. Sprint 2 (#182 reconciliation) is a soft dependency.

## Architecture

Second strategy within the SAME watch loop. `strategy_type` column in `shadow_trades` differentiates.

```
Watch Loop → Pullback Scanner (existing) → LLM → trade (strategy_type="pullback")
           → MR Scanner (NEW) → no LLM → trade (strategy_type="mean_reversion")
```

## Implementation

### Task 4.1: Mean Reversion Feature Engine
New: `src/features/mean_reversion.py`
- RSI(2) computation (Connors variant)
- Distance from 200 EMA
- 3-day cumulative return
- Bollinger Band position
- Volume spike detection

### Task 4.2: Shared RSI utility
Extract to `src/features/indicators.py`:
```python
def compute_rsi(close: pd.Series, period: int = 14) -> float:
```
Update both existing callers in `regime.py` and `setup_classifier.py`.

### Task 4.3: Strategy config
```yaml
strategies:
  pullback:
    enabled: true
  mean_reversion:
    enabled: true
    paper_only: true   # NEVER live until Phase 2 gate
    rsi_period: 2
    rsi_entry_threshold: 10
    rsi_exit_threshold: 70
    require_above_200ema: true
    max_positions: 5
    holding_period: 5
    stop_atr_multiple: 2.5
```

### Task 4.4: Strategy-aware exit dispatcher
In `check_and_manage_open_trades()` (executor.py line 418), add BEFORE bracket/timeout logic:
```python
if trade.get("strategy_type") == "mean_reversion":
    mr_exit = _check_mean_reversion_exit(trade, db_path)
    if mr_exit:
        actions.append(mr_exit)
        continue  # Skip bracket logic
```

`_check_mean_reversion_exit()` needs:
1. Fetch last 10 days OHLCV via new `_get_recent_ohlcv_safe(ticker, days=10)`
2. Compute RSI(2) from close prices using shared `compute_rsi()`
3. If RSI(2) > 70: sell via Alpaca, close shadow trade with `exit_reason="rsi_exit"`
4. Also check stop (2.5× ATR) and timeout (5 days) as fallbacks

### Task 4.5: `paper_only` enforcement
In `open_shadow_trade()`:
```python
strategy_cfg = config.get("strategies", {}).get(strategy_type, {})
if strategy_cfg.get("paper_only", False):
    trade_data["source"] = "paper"
```
In `_run_scan()` live trade block: skip live execution for paper_only strategies.

### Task 4.6: Dashboard strategy filter
Add `strategy_type` filter to Shadow Ledger and Performance pages.

### Task 4.7: Tests + MASTER.md update

## Acceptance Criteria (Sprint 4)
- [ ] RSI(2) scanner identifies MR candidates
- [ ] MR trades tagged `strategy_type="mean_reversion"` in shadow_trades
- [ ] RSI(2) > 70 exit fires correctly (not bracket-based)
- [ ] `paper_only` enforced — no live MR trades regardless of config
- [ ] `compute_rsi()` shared utility used by all callers
- [ ] Strategy filter works on Shadow Ledger and Performance pages
- [ ] All tests pass, `npm run build` succeeds

---

# SPRINT 5: Multi-Cadence Scanning

> **Priority:** HIGH — biggest architectural improvement to scan pipeline
> **Estimated CC time:** 6-8 hours (pure refactor — largest sprint)
> **Dependencies:** Sprint 4 (MR RSI exit used by position monitor)

## Architecture

Replace monolithic 30-min `_run_scan()` with 4 tiers:

| Tier | Interval | What | API Budget |
|---|---|---|---|
| Position Monitor | 15 min | Held tickers: price, stop/target proximity, MR RSI check, reconciliation | ~50 yfinance |
| Price/Technical | 30 min | Full universe: OHLCV, features, ranking, LLM packets, trades | ~100 yfinance + LLM |
| Sentiment/Regime | 60 min | VIX, news, options flow, sector rotation | ~200 Finnhub |
| Fundamentals | Daily 7:30 AM | FRED macro, SEC filings, FMP estimates, insider txns | ~200 FMP + FRED |

## Implementation

### Task 5.1: Extract scan components from watch.py (3,031 lines)
**Refactor by extraction, not rewrite.** Create:
- `src/scheduler/position_monitor.py` — Tier 1
- `src/scheduler/universe_scanner.py` — Tier 2
- `src/scheduler/sentiment_scanner.py` — Tier 3
- `src/scheduler/fundamentals_refresh.py` — Tier 4

`watch.py` stays as orchestrator.

### Task 5.2: Timing orchestrator
Sequential execution — Tier 1 first (fast, <30s), then Tier 2, then Tier 3:
```python
def _tick(self, now):
    if self._should_monitor_positions(now):   # every 15 min
        self._run_position_monitor()
    if self._should_scan_universe(now):        # every 30 min
        self._run_universe_scan()
    if self._should_refresh_sentiment(now):    # every 60 min
        self._run_sentiment_refresh()
```

### Task 5.3: Staleness detection
New: `src/data_enrichment/staleness.py`

| Dimension | Acceptable | Warning | Critical |
|---|---|---|---|
| Price | <35 min | 35-60 min | >60 min |
| VIX | <65 min | 65-120 min | >120 min |
| News | <2 hrs | 2-4 hrs | >4 hrs |
| Fundamentals | <26 hrs | 26-48 hrs | >48 hrs |

Per-ticker tracking in `data_freshness` table: `(source, ticker, last_fetched_at)`.

### Task 5.4: Tests + MASTER.md update

## Acceptance Criteria (Sprint 5)
- [ ] 4 extracted modules exist and are called from watch.py
- [ ] Tiers fire at correct intervals (15/30/60/daily)
- [ ] Position monitor handles both pullback (bracket) and MR (RSI) exits
- [ ] Staleness detected per-ticker-per-source
- [ ] watch.py line count reduced by ≥30%
- [ ] No behavior changes — same scan results as before extraction
- [ ] All tests pass, `npm run build` succeeds

---

# SPRINT 6: Outcome-Conditioned Training Pipeline

> **Priority:** MEDIUM-HIGH — 3-5x data yield per closed trade
> **Estimated CC time:** 3-4 hours
> **Dependencies:** Sprint 3 (PASS examples from attribution ledger)

## Architecture

Currently: 1 training example per closed trade. After: 3-5 examples per trade.

```
Closed Trade → classify outcome (WIN/LOSS/TIMEOUT)
  ├── Primary: outcome-conditioned prompt (different template per type)
  ├── Contrastive: opposite-decision prompt (natural DPO pair)
  └── Management: during-hold analysis (WIN/LOSS only)

PASS decisions (from attribution_trades where llm_action="rejected"):
  └── PASS prompt: "justify why this qualified setup should NOT be traded"
```

## Implementation

### Task 6.1: Outcome classifier
New: `src/training/outcome_prompts.py`
```python
def classify_outcome(trade: dict) -> str:
    if trade.get("exit_reason") in ("timeout", "reconciled_stale"): return "TIMEOUT"
    return "WIN" if trade.get("pnl_dollars", 0) > 0 else "LOSS"
```

### Task 6.2: Outcome-conditioned prompt templates
4 system prompts (all maintain self-blinding — outcome type determines WHICH template, not WHAT it says):
- `WINNER_SYSTEM_PROMPT` — emphasize thesis validation
- `LOSER_SYSTEM_PROMPT` — emphasize risk weighting
- `TIMEOUT_SYSTEM_PROMPT` — emphasize signal decay
- `PASS_SYSTEM_PROMPT` — justify the skip decision

### Task 6.3: Contrastive example generator
For each trade, generate opposite-stance example using same features:
- WIN → "why I would PASS" example
- LOSS → "why I would BUY" example
Both maintain self-blinding. Creates natural DPO pairs.

### Task 6.4: Update `collect_training_examples_from_closed_trades()`
In `src/training/data_collector.py`, modify collection loop to generate 3-5 examples.

### Task 6.5: Add 8 outcome metadata columns to shadow_trades
Via schema registry (Strategy Decision #24):
- `regime_at_entry TEXT`, `regime_at_exit TEXT`
- `vix_at_entry REAL`, `vix_at_exit REAL`
- `time_to_target_days INTEGER`, `drawdown_from_mfe REAL`
- `concurrent_positions INTEGER`, `ranking_at_entry INTEGER`

Populate in `open_shadow_trade()` and `close_shadow_trade()`.

### Task 6.6: Tests + MASTER.md update

## Acceptance Criteria (Sprint 6)
- [ ] 3-5 examples generated per closed trade (up from 1)
- [ ] Outcome classifier correctly maps exit_reason → WIN/LOSS/TIMEOUT
- [ ] Self-blinding maintained — TF-IDF leakage detector passes
- [ ] Contrastive examples have opposite stance from primary
- [ ] 8 metadata columns added and populated
- [ ] All tests pass

---

# SPRINT 7: Historical Stress Testing

> **Priority:** MEDIUM — answers the allocator's #1 due diligence question
> **Estimated CC time:** 2-3 hours
> **Dependencies:** Sprint 3 (uses same backtester infrastructure)

## Architecture

Extend `src/evaluation/backtester.py` (210 lines) to replay through 3 crisis periods. No LLM — pure ranker + mechanical brackets.

## Implementation

### Task 7.1: Stress test script
New: `scripts/stress_test.py`
3 scenarios:
```python
SCENARIOS = {
    "2008_financial_crisis": {"start": "2008-09-01", "end": "2009-03-31"},
    "2020_covid_crash":      {"start": "2020-02-01", "end": "2020-04-30"},
    "2022_bear_market":      {"start": "2022-01-01", "end": "2022-10-31"},
}
```

For each trading day: fetch historical OHLCV → compute features → run ranker → simulate brackets → track equity curve.

### Task 7.2: Survivorship bias mitigation
Filter universe to tickers with available data for test period:
```python
def get_stress_test_universe(scenario):
    valid = [t for t in get_sp100_universe() if yf.download(t, start=start, end=start) is not None]
    logger.warning("[STRESS] Excluded %d tickers (no data)", len(get_sp100_universe()) - len(valid))
    return valid
```
Report explicitly notes survivorship bias limitation.

### Task 7.3: Extended backtester metrics
Add to return dict: `max_drawdown_pct`, `max_drawdown_duration_days`, `calmar_ratio`, `monthly_returns`, `trade_gap_days`, `regime_breakdown`, `equity_curve`.

### Task 7.4: VIX-regime stop validation
Stress test validates ATR multipliers by regime: at 3.0× ATR in Crisis, what % of stops triggered? Recommendation for adjustment if needed.

### Task 7.5: Dashboard — Stress Test Results page
Equity curves overlaid on S&P 500 drawdown, max DD per scenario, trade frequency, regime performance.

### Task 7.6: Scheduled overnight execution
Runs Sunday nights after retrain. Re-runs on model version change. Results in `stress_test_results` table.

### Task 7.7: Tests + MASTER.md update

## Acceptance Criteria (Sprint 7)
- [ ] All 3 scenarios produce results (equity curve, max DD, trade count)
- [ ] Survivorship bias noted in output
- [ ] Extended metrics (calmar, monthly returns, regime breakdown) populated
- [ ] VIX-regime stop analysis complete
- [ ] Dashboard page renders stress test results
- [ ] All tests pass, `npm run build` succeeds

---

# Gap Analysis Addendum

12 gaps found across 3 iterations of codebase analysis. All addressed in sprint specs above.

| # | Gap | Sprint | Fix |
|---|---|---|---|
| 1 | No mechanical outcome simulator | 3 | Price-based simulator using historical OHLCV |
| 2 | Attribution rows must precede LLM | 3 | Two-phase logging (before/after LLM) |
| 3 | RSI exit incompatible with bracket reconciliation | 4 | Strategy-aware exit dispatcher |
| 4 | RSI computation hardcoded period=14 | 4 | Shared `compute_rsi()` with configurable period |
| 5 | `paper_only` not enforced | 4 | Check in executor + skip live block |
| 6 | Trade manager needs OHLCV history for MR | 4 | `_get_recent_ohlcv_safe()` helper |
| 7 | No concurrency model for simultaneous tiers | 5 | Sequential: Tier 1 → 2 → 3 within tick |
| 8 | Staleness per-source not per-ticker | 5 | Per-ticker tracking in `data_freshness` table |
| 9 | `outcome_type` classifier missing | 6 | `classify_outcome()` maps exit_reason |
| 10 | Contrastive examples must maintain self-blinding | 6 | Same features, different instruction only |
| 11 | Survivorship bias in stress testing | 7 | Filter to available tickers, note limitation |
| 12 | Backtester missing key metrics | 7 | Add calmar, monthly returns, regime breakdown |

---

# Dependency Graph

```
Bug Bash (#2) ──┬── Sprint A (Dashboard + Docs)
                │
                ├── Sprint 3 (Alpha Attribution) ───── Sprint 7 (Stress Testing)
                │       │                              (extends backtester)
                │       │ PASS examples feed ──────────┘
                │
                ├── Sprint 4 (Mean Reversion) ──────── Sprint 5 (Multi-Cadence)
                │   (RSI exit logic)                   (position monitor uses it)
                │
                └── Sprint 6 (Training Pipeline)
                    (benefits from #3 PASS data + #4 MR trades)
```

**Parallel:** Sprints A, 3, 4, and 6 have no mutual dependencies — can run simultaneously.

---

# Risk Register

| Risk | Sprint | Severity | Mitigation |
|---|---|---|---|
| watch.py extraction breaks scan flow | 5 | HIGH | Extract one module at a time, test after each |
| RSI(2) exit whipsaws | 4 | MEDIUM | Configurable threshold + min 2-day hold |
| Attribution simulator disagrees with Alpaca fills | 3 | MEDIUM | Conservative 5bps slippage, flag >10bps |
| Survivorship bias invalidates stress results | 7 | MEDIUM | Report notes limitation prominently |
| Contrastive training introduces directional bias | 6 | LOW | TF-IDF leakage detector after each batch |
| Tier 1+2 sequential adds 30s latency | 5 | LOW | Acceptable for 2-15 day strategy |

---

# Timeline

| Week | Sprint | Deliverable |
|---|---|---|
| Week 0 | **A** Dashboard + Docs | Audit chip, build score, MASTER.md, archive |
| Week 1 | **3** Alpha Attribution | Attribution table, mechanical simulator, dashboard page |
| Week 1-2 | **4** Mean Reversion | RSI(2) scanner, strategy-aware exits, paper trading live |
| Week 2-3 | **5** Multi-Cadence | watch.py extraction, 4-tier scheduling, staleness |
| Week 3 | **6** Training Pipeline | Outcome-conditioned prompts, contrastive pairs, metadata |
| Week 3-4 | **7** Stress Testing | 2008/2020/2022 replay, stress dashboard page |
