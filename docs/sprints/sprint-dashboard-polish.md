# Sprint: Dashboard Polish — Audit Banner Redesign + Build Score Fix + Roadmap Update

> **Priority:** HIGH — Dashboard shows misleading data (Build Score 0.0, stale RED audit banner, outdated roadmap)
> **Scope:** 3 frontend fixes + 1 backend fix. No new features — polish only.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after. Run `cd frontend && npm run build` after all frontend changes.**

---

## Pre-Flight

1. Read `SYSTEM_STATE.md` — especially Strategy Decisions (24 confirmed), Phase Gates, Revenue Milestones, GPU Utilization Framework, Exit Management Framework, CC Sprint Queue
2. Read `docs/research/deep-research/SYNTHESIS-framework-update-roadmap-changes.md` — the approved roadmap changes
3. Read `frontend/src/pages/Dashboard.jsx` — current audit banner implementation
4. Read `frontend/src/pages/Roadmap.jsx` — current roadmap content
5. Read `src/api/cloud_routes/analytics.py` — build-score endpoint
6. Run `python -m pytest tests/ -x -q` — record baseline

---

## Task 1: Redesign Audit Banner (Dashboard.jsx)

The current red audit banner dumps raw auditor text with no design consideration. It's ugly, rarely aligned to actual system state, and shows truncated JSON.

**Replace with a compact status chip:**

- **Collapsed (default):** Show a single-line status chip at the top of Dashboard:
  - `🟢 System OK` — if audit overall_assessment is "green" or "healthy"
  - `🟡 3 warnings` — if audit has warnings but no critical issues
  - `🔴 2 critical issues` — if audit has critical findings
  - `⚪ Audit stale (>24h)` — if the latest audit is more than 24 hours old
  - `⚪ No audit data` — if audit_reports table is empty (post-recovery state)

- **Expanded (on click):** Clicking the chip expands to show the audit summary text in a clean card below the chip. NOT the raw JSON dump — extract `overall_assessment` and `summary` fields only. Include a "Collapse" button to close.

- **NEVER show raw JSON, truncated text, or code fences in the banner.**

- Style: Use Arcis Palette H variables. The chip should be subtle — not a screaming red wall.

**File:** `frontend/src/pages/Dashboard.jsx`

---

## Task 2: Fix Build Score Display

Build Score shows 0.0 with all 6 components at 0. This happens when `build_score_history` is empty (post-recovery).

**Fix two things:**

### 2A: Dashboard display when no data
If `/api/build-score` returns all zeros or empty data, show "Not yet computed — run CTO Report to generate" instead of 0.0 with zero-filled progress bars.

**File:** `frontend/src/pages/Dashboard.jsx`

### 2B: Ensure Build Score computes on CTO Report action
Verify that the "Generate CTO Report" button (which submits a `cto-report` command via the command queue) also triggers a build score computation. If the build score computation is a separate scheduled task, add a note in the UI: "Build Score updates daily at 4:30 PM ET."

**File:** `src/api/cloud_routes/analytics.py` (verify), `frontend/src/pages/Dashboard.jsx` (display)

---

## Task 3: Update Roadmap Page with Approved Deep Research Changes

The Roadmap page (`frontend/src/pages/Roadmap.jsx`) is hardcoded and out of date. Update it with ALL approved changes from the deep research synthesis (April 2, 2026).

Read `SYSTEM_STATE.md` for the authoritative state. Key updates:

### Strategy Decisions (16 → 24):
Add these 8 new decisions to the roadmap display:
- #17: Alpha attribution experiment (parallel ranker-only shadow portfolio)
- #18: Mechanical brackets optimal through 200 trades, then phased LLM management
- #19: Options moved to Phase 2 at $15-25K (vertical spreads only — was Phase 3-4 at $50K)
- #20: Collective2 account for independently verified track record
- #21: Training data expand from 7→11 XML sections with random source subsetting
- #22: 4-tier multi-cadence scanning (15min position / 30min price / 60min sentiment / daily fundamentals)
- #23: Outcome-conditioned training prompts (3-5x data yield per closed trade)
- #24: 8 new outcome metadata columns in shadow_trades

### Phase Gate Changes:
- Phase 1→2 now requires: 50 trades **+ alpha attribution running (≥50 paired trades) + stress test completed (2008/2020/2022) + ≥100 mean reversion paper trades**
- Phase 2→3 now includes: **options paper-trading at $15-25K**

### Strategy #2 Timing:
- Mean Reversion moved from "Phase 2" to **"Paper-trading NOW (Phase 1)"**

### New Sections to Add:
1. **Revenue Milestones** timeline:
   - Month 0: Personal trading + capital injections ($1K/mo)
   - Month 3: Open Collective2 (~$99/mo) — track record clock starts
   - Month 6: Phase 1 gate → go live ($5-10K)
   - Month 12: Signal marketplace revenue + RIA outreach
   - Month 18: Wyoming LLC + Section 475(f)
   - Month 24: Fund formation at $1-2M AUM
   - Month 36: Fund self-sustaining at $2M+ AUM

2. **Exit Management Framework** (4 phases):
   - Phase 1 (now→50 trades): Pure mechanical brackets
   - Phase 2 (50→200): Mechanical + rule-based (time-based stop tightening, signal exit)
   - Phase 3 (200→500): Evaluate LLM pilot (days 5-7 only)
   - Phase 4 (500+): Full active if validated

3. **GPU Utilization Targets**:
   - Market hours: 30-40% (inference + alpha backtest)
   - Post-close: 40-60% (stress testing + Monte Carlo)
   - Overnight: 50-70% (continuous eval + parameter backtesting)
   - Weekend: 70-80% (retrain + exhaustive backtest)

**File:** `frontend/src/pages/Roadmap.jsx`

---

## Task 4: Update SYSTEM_STATE.md

After all changes, update:
- Note this sprint was completed
- Dashboard page descriptions updated if any layout changed

---

## Acceptance Criteria

### Audit Banner
- [ ] Default state is a compact single-line status chip (not a red wall of text)
- [ ] Chip shows correct status: green/yellow/red/stale/empty
- [ ] Clicking expands to show clean audit summary (not raw JSON)
- [ ] Clicking again collapses back to chip
- [ ] When audit_reports is empty, shows "No audit data" (not an error)
- [ ] No raw JSON, code fences, or truncated text ever visible

### Build Score
- [ ] When build_score_history is empty, shows "Not yet computed" instead of 0.0
- [ ] After CTO Report runs, Build Score populates with real values
- [ ] All 6 component bars show real values (not all zeros)

### Roadmap
- [ ] Strategy Decisions shows 24 items (was 16)
- [ ] Phase 1→2 gate shows all 4 requirements (50 trades + alpha attribution + stress test + 100 MR paper)
- [ ] Strategy #2 shows "Paper-trading NOW" not "Phase 2"
- [ ] Options shows "Phase 2 at $15-25K" not "Phase 3-4 at $50K"
- [ ] Revenue Milestones section renders with timeline
- [ ] Exit Management Framework section renders with 4 phases
- [ ] GPU Utilization section renders with targets

### Zero Regressions
- [ ] All Python tests pass
- [ ] `npm run build` succeeds
- [ ] All other dashboard pages still load correctly
