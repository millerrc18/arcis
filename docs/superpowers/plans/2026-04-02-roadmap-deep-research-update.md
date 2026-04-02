# Roadmap Deep Research Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the Roadmap dashboard page to reflect all strategy decisions and framework changes approved in the April 2 deep research synthesis.

**Architecture:** Pure frontend data change — modify `ROADMAP_DATA` in `Roadmap.jsx` to add 8 new Phase 1 items, 3 new gate metrics, updated Phase 2 options timing, and 3 new info sections (Revenue Milestones, Exit Management, GPU Utilization). No backend changes needed.

**Tech Stack:** React 19, Tailwind 4, lucide-react icons

**Source docs:**
- `docs/research/deep-research/SYNTHESIS-framework-update-roadmap-changes.md`
- `SYSTEM_STATE.md` (lines 283-450)

---

## File Structure

### Modified files:
```
frontend/src/pages/Roadmap.jsx    — ROADMAP_DATA updates + 3 new info sections
```

No new files needed. All changes are data + minor JSX additions within the existing component.

---

### Task 1: Update ROADMAP_DATA header + Phase 1 gate metrics

**Files:**
- Modify: `frontend/src/pages/Roadmap.jsx:24-35`

- [ ] **Step 1: Update lastUpdated date**

In `ROADMAP_DATA`, change line 24:

```javascript
lastUpdated: '2026-04-02',
```

- [ ] **Step 2: Update Phase 1 gate label and add 3 new metrics**

Replace the Phase 1 gate object (lines 28-35) with:

```javascript
gate: { label: '50+ trades, positive expectancy, alpha attribution, stress test, mean reversion data', metrics: [
  { key: 'trades_closed', label: 'Closed trades', target: 50, op: '>=', fmt: '' },
  { key: 'win_rate', label: 'Win rate', target: 0.45, op: '>=', fmt: 'pct' },
  { key: 'profit_factor', label: 'Profit factor', target: 1.3, op: '>=' },
  { key: 'expectancy_dollars', label: 'Expectancy', target: 0, op: '>', fmt: 'dollar' },
  { key: 'max_drawdown_pct', label: 'Max drawdown', target: 12, op: '<=', fmt: 'pctVal' },
  { key: 'sharpe_ratio', label: 'Per-trade Sharpe', target: 0.15, op: '>=' },
  { key: 'alpha_paired_trades', label: 'Alpha paired trades', target: 50, op: '>=' },
  { key: 'stress_test_completed', label: 'Stress tests (08/20/22)', target: 3, op: '>=' },
  { key: 'mr_paper_trades', label: 'Mean reversion paper', target: 100, op: '>=' },
]},
```

- [ ] **Step 3: Run build to verify no syntax errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Roadmap.jsx
git commit -m "feat(roadmap): update Phase 1 gate with alpha attribution, stress test, mean reversion requirements"
```

---

### Task 2: Add 8 new Phase 1 items (Weeks 8-12 subphase)

**Files:**
- Modify: `frontend/src/pages/Roadmap.jsx:61-69` (Weeks 8-12 subphase items array)

- [ ] **Step 1: Add new items to the Weeks 8-12 subphase**

After the existing last item in the `Weeks 8–12: Risk & NLP` subphase (`Score + retrain halcyon-v1`, line 68), add these 8 items:

```javascript
{ l: 'Alpha attribution experiment', s: 'pending', c: 'validation', d: 'Parallel ranker-only shadow portfolio to measure model value-add vs. systematic scoring alone. Requires ≥50 paired trades.', r: 'Deep Research Synthesis: "single most informative test"' },
{ l: 'Paper-trade mean reversion (Strategy #2)', s: 'pending', c: 'strategy', d: 'Connors RSI(2) mean reversion on S&P 100. Moved from Phase 2 to NOW. ≥100 paper trades needed for gate.', r: 'Deep Research: moved from Phase 2 to Phase 1' },
{ l: 'Open Collective2 account', s: 'pending', c: 'ops', d: 'Verified track record platform (~$99/mo). Track record clock starts immediately. Required for external credibility.', r: 'Revenue Sequencing: Month 3 milestone' },
{ l: '8 outcome metadata columns', s: 'pending', c: 'data', d: 'Add to shadow_trades: hold_period_return, benchmark_return, alpha_vs_spy, max_drawdown_during_trade, exit_efficiency, entry_timing_score, thesis_accuracy, sector_at_exit.', r: 'Deep Research: flywheel optimization' },
{ l: 'Stress test suite (2008/2020/2022)', s: 'pending', c: 'validation', d: 'Walk-forward backtest through GFC, COVID crash, and 2022 bear market. Must complete before Phase 2 gate.', r: 'Deep Research: Phase 1→2 gate addition' },
{ l: '4-tier multi-cadence scanning', s: 'pending', c: 'strategy', d: '15min position monitoring, 30min price alerts, 60min sentiment updates, daily fundamental refresh.', r: 'Deep Research: scanning intervals study' },
{ l: 'Outcome-conditioned training prompts', s: 'pending', c: 'ai', d: 'Generate 3-5 training examples per trade instead of 1. Prompt variations: "given it went up 5%..." and "given it hit stop...".', r: 'Deep Research: 3-5x data yield per trade' },
{ l: 'Expand training XML 7→11 sections', s: 'pending', c: 'ai', d: 'Add 4 sections: options flow, sector relative, event calendar proximity, cross-asset correlation. Random source subsetting for robustness.', r: 'Deep Research: horizontal training data study' },
```

- [ ] **Step 2: Run build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Roadmap.jsx
git commit -m "feat(roadmap): add 8 new Phase 1 items from deep research synthesis"
```

---

### Task 3: Update Phase 2 — options timing + new gate

**Files:**
- Modify: `frontend/src/pages/Roadmap.jsx:72-104` (Phase 2 definition)

- [ ] **Step 1: Update Phase 2 gate to include options paper-trading**

Replace the Phase 2 gate label (line 74):

```javascript
gate: { label: '100+ trades, PSR >90%, paper-live concordance, options paper at $15-25K', metrics: [
```

Add to the Phase 2 gate metrics array (after `calmar`):

```javascript
{ key: 'options_paper_trades', label: 'Options paper trades', target: 50, op: '>=' },
```

- [ ] **Step 2: Update the Phase 3 options item to reflect new timing**

In Phase 3 (line 124), find the "Options data collection" item and update:

```javascript
{ l: 'Options paper-trading ($15-25K vertical spreads)', s: 'pending', c: 'strategy', d: 'Vertical spreads only at $15-25K capital. Moved from Phase 3-4 at $50K. Conservative defined-risk positions.', r: 'Deep Research: options moved to Phase 2 at lower capital tier' },
```

- [ ] **Step 3: Run build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Roadmap.jsx
git commit -m "feat(roadmap): move options to Phase 2 at $15-25K, update gate"
```

---

### Task 4: Add Revenue Milestones section

**Files:**
- Modify: `frontend/src/pages/Roadmap.jsx` — add `REVENUE_MILESTONES` data array and render section

- [ ] **Step 1: Add revenue milestones data**

After the `ROADMAP_DATA` object (after line 186), add:

```javascript
const REVENUE_MILESTONES = [
  { month: '0', label: 'Now', stream: 'Personal trading + $1K/mo capital injections', color: 'var(--arcis-teal-light)' },
  { month: '3', label: 'Month 3', stream: 'Open Collective2 (~$99/mo). Track record clock starts.', color: 'var(--arcis-teal-light)' },
  { month: '6', label: 'Month 6', stream: 'Phase 1 gate → go live ($5-10K). Verifiable live returns.', color: 'var(--chart-4)' },
  { month: '12', label: 'Month 12', stream: 'Signal marketplace + RIA outreach. First external revenue.', color: 'var(--chart-4)' },
  { month: '18', label: 'Month 18', stream: 'Wyoming LLC + Section 475(f) election. Legal entity.', color: 'var(--chart-1)' },
  { month: '24', label: 'Month 24', stream: 'Fund formation at $1-2M AUM. Mgmt + performance fees.', color: 'var(--chart-7)' },
  { month: '36', label: 'Month 36', stream: 'Fund self-sustaining at $2M+ AUM (1.5% + 17.5%). Day job optional.', color: 'var(--chart-7)' },
]
```

- [ ] **Step 2: Add Revenue Milestones JSX section**

In the render, between the `<RevenueProjection />` card and the two-column grid (around line 362), add:

```jsx
<div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)' }}>
  <div className="flex items-center gap-2 mb-3">
    <DollarSign size={16} style={{ color: 'var(--arcis-text-secondary)' }} />
    <h2 className="text-sm font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Revenue milestones</h2>
  </div>
  <div className="space-y-2">
    {REVENUE_MILESTONES.map((m, i) => (
      <div key={i} className="flex items-center gap-3 text-xs">
        <span className="shrink-0" style={{ width: 60, color: m.color, fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{m.label}</span>
        <div className="flex-1 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: m.color }} />
          <span style={{ color: 'var(--arcis-text-secondary)' }}>{m.stream}</span>
        </div>
      </div>
    ))}
  </div>
</div>
```

- [ ] **Step 3: Run build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Roadmap.jsx
git commit -m "feat(roadmap): add revenue milestones timeline (month 0→36)"
```

---

### Task 5: Add Exit Management Framework section

**Files:**
- Modify: `frontend/src/pages/Roadmap.jsx` — add `EXIT_FRAMEWORK` data and render section

- [ ] **Step 1: Add exit framework data**

After `REVENUE_MILESTONES`, add:

```javascript
const EXIT_FRAMEWORK = [
  { phase: 'Phase 1', trades: '13→50', strategy: 'Pure mechanical brackets', detail: 'Fix live stop to 2.0x ATR. MFE/MAE logging for every trade.', color: 'var(--arcis-teal-light)' },
  { phase: 'Phase 2', trades: '50→200', strategy: 'Mechanical + rule-based', detail: 'Time-based stop tightening (2.0x→1.5x by day 5). Signal exit: close > 5-day SMA.', color: 'var(--chart-4)' },
  { phase: 'Phase 3', trades: '200→500', strategy: 'Evaluate LLM pilot', detail: 'Thesis invalidation detection on days 5-7 only. A/B test vs mechanical.', color: 'var(--chart-1)' },
  { phase: 'Phase 4', trades: '500+', strategy: 'Full active (if validated)', detail: 'Separate exit-specialist LoRA. Daily conviction updates. Full LLM exit management.', color: 'var(--chart-7)' },
]

const GPU_TARGETS = [
  { block: 'Market hours', time: '9:30-4:00', current: '4.4%', target: '30-40%', activities: 'Inference + alpha backtest + eval warmup' },
  { block: 'Post-close', time: '4:00-7:00', current: '~5%', target: '40-60%', activities: 'Stress testing + Monte Carlo + outcome training gen' },
  { block: 'Overnight', time: '7:00-5:15', current: '~10%', target: '50-70%', activities: 'Continuous eval + parameter backtesting + scenario gen' },
  { block: 'Weekend', time: 'Sat-Sun', current: 'Training only', target: '70-80%', activities: 'Full retrain + exhaustive backtest + stress suite' },
]
```

- [ ] **Step 2: Add Exit Management + GPU Utilization JSX sections**

After the Revenue Milestones section, before the two-column hardware/costs grid, add:

```jsx
<div className="grid grid-cols-2 gap-4">
  <div className="rounded-lg p-4" style={{ border: '1px solid var(--arcis-border)' }}>
    <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--arcis-text-primary)' }}>Exit management framework</h2>
    <div className="space-y-2">
      {EXIT_FRAMEWORK.map((e, i) => (
        <div key={i} className="rounded p-2" style={{ background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-bg-surface)' }}>
          <div className="flex items-center justify-between mb-1">
            <span style={{ color: e.color, fontSize: 11, fontWeight: 500 }}>{e.phase} ({e.trades})</span>
          </div>
          <div className="text-xs font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{e.strategy}</div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>{e.detail}</div>
        </div>
      ))}
    </div>
  </div>

  <div className="rounded-lg p-4" style={{ border: '1px solid var(--arcis-border)' }}>
    <div className="flex items-center gap-2 mb-3">
      <Cpu size={16} style={{ color: 'var(--arcis-text-secondary)' }} />
      <h2 className="text-sm font-medium" style={{ color: 'var(--arcis-text-primary)' }}>GPU utilization targets</h2>
    </div>
    <div className="space-y-2">
      {GPU_TARGETS.map((g, i) => (
        <div key={i} className="rounded p-2" style={{ background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-bg-surface)' }}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{g.block}</span>
            <span style={{ fontSize: 10, color: 'var(--arcis-text-muted)' }}>{g.time}</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span style={{ color: 'var(--arcis-text-muted)' }}>{g.current}</span>
            <span style={{ color: 'var(--arcis-text-muted)' }}>→</span>
            <span style={{ color: 'var(--arcis-teal-light)', fontWeight: 500 }}>{g.target}</span>
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>{g.activities}</div>
        </div>
      ))}
    </div>
  </div>
</div>
```

- [ ] **Step 3: Run build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Roadmap.jsx
git commit -m "feat(roadmap): add exit management framework + GPU utilization targets"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run npm build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 2: Run Python tests**

Run: `python -m pytest tests/ -q --tb=no`
Expected: >= 1,230 passed (frontend changes don't affect Python tests)

- [ ] **Step 3: Visual check — count new items**

Verify in the ROADMAP_DATA:
- Phase 1 gate metrics: 9 (was 6, +3 new)
- Phase 1 Weeks 8-12 items: 15 (was 7, +8 new)
- Revenue milestones: 7 entries
- Exit framework: 4 phases
- GPU targets: 4 time blocks

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(roadmap): deep research synthesis — 8 new items, 3 gates, revenue/exit/GPU sections

Updates approved April 2 from deep research synthesis:
- Phase 1 gate: +alpha attribution, stress test, mean reversion requirements
- 8 new Phase 1 items: alpha experiment, mean reversion, Collective2, metadata,
  stress tests, multi-cadence scanning, outcome training, expanded XML
- Options moved from Phase 3-4 ($50K) to Phase 2 ($15-25K vertical spreads)
- Revenue milestones timeline (month 0→36)
- Exit management framework (4 phases: mechanical → LLM)
- GPU utilization targets (4.4% → 30-80% across time blocks)"
```

---

## Acceptance Criteria

- [ ] `lastUpdated` is `'2026-04-02'`
- [ ] Phase 1 gate has 9 metrics (6 original + alpha, stress, MR)
- [ ] Phase 1 has 8 new items in Weeks 8-12 subphase
- [ ] Phase 2 gate mentions options paper-trading
- [ ] Phase 3 options item updated to $15-25K vertical spreads
- [ ] Revenue Milestones section renders 7 entries
- [ ] Exit Management section renders 4 phases
- [ ] GPU Utilization section renders 4 time blocks
- [ ] `npm run build` succeeds
- [ ] All existing Python tests still pass
