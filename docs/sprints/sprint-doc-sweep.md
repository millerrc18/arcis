# Sprint: Comprehensive Documentation & Roadmap Sweep

**Authority:** Post-forensic-analysis housekeeping
**Effort:** 3-4 hours CC time
**Branch:** `docs/post-forensic-sweep`
**Tag on merge:** none (docs-only)
**Priority:** HIGH — stale docs create false confidence and misaligned expectations

---

## Goal

MASTER.md, dashboard roadmap page, and supporting docs are severely stale after
the forensic analysis pivot and 4 sprint merges on 2026-04-16. This sprint
updates every stale section to reflect the current system state. No code changes
beyond frontend JSX for dashboard pages.

---

## Current Counts (verified 2026-04-16)

Use these as the source of truth:

| Metric | Old (stale) | Current |
|---|---|---|
| Latest release | v0.17.2 | v0.21.0 (v0.18.0 + v0.19.0 + v0.21.0 all on 2026-04-16) |
| Closed trades | 18 (+ 77 quarantined) | 85 (verify via DB query, may have grown) |
| Tests | 1,801 across 148 files | **Query: `pytest --collect-only -q 2>&1 \| tail -1`** |
| Python files | 225 | 225 (verify: `find src/ -name "*.py" -not -path "*__pycache__*" \| wc -l`) |
| Test files | 148 | 154 (verify: `find tests/ -name "*.py" -not -path "*__pycache__*" \| wc -l`) |
| Dashboard pages | 24 | 25 (verify: `find frontend/src/pages -name "*.jsx" \| wc -l`) |
| Research docs | 91 | 106 (verify: `find docs/research -name "*.md" -o -name "*.pdf" \| wc -l`) |
| Sprint docs | 43 | 57 (verify: `find docs/sprints -name "*.md" \| wc -l`) |
| Strategy decisions | 40 | 41 (SD#41 added; may be 42 if we count REVISED as separate) |
| Schema tables | 53 | verify via registry |

---

## Task List

### Task 1 — MASTER.md Section 1 (System Identity)

**Release line:** Update from v0.17.2 to:

```
**Release:** v0.21.0 (2026-04-16: earnings filter hard block SD#33; prior: v0.19.0 SPY-matched excess instrumentation SD#41 D1; v0.18.0 IB cold storage SD#41; v0.17.2 Grafana Loki + NSSM)
```

**Tech stack — Trading line:** Update to:

```
- Trading: Alpaca paper + live API (bracket orders, GTC); IB Gateway dormant
  per SD#41 (`trading.ib_enabled=false`), all code preserved for reactivation
```

---

### Task 2 — MASTER.md Section 2 (Current State)

**Key Metrics table:** Update all stale values using the counts from the table above. Critical fixes:

- `Closed trades` → `85 closed (verify via shadow-status; 77 quarantine resolved in v0.16.x)`
- `Phase` → `1 (Diagnostic) -- paper $100K + $100 live via Alpaca. SD#41 REVISED: halt optimization, run diagnostics first.`
- `Tests`, `Test files`, `Dashboard pages`, `Research docs`, `Sprint docs` → current counts

**Deployed Components table:** Add/update:

| Component | Status |
|---|---|
| Earnings filter (SD#33) | LIVE — v0.21.0, hard block within 10 calendar days of earnings |
| SPY-matched excess instrumentation | LIVE — v0.19.0, primary metric is now excess-Sharpe |
| IB integration | DORMANT — v0.18.0, `trading.ib_enabled=false`, all code preserved |
| Dashboard (Arcis) | LIVE — 25 pages (Trade History replaces Broker Comparison; excess-Sharpe lead panel) |

Remove "PEAD enrichment (5 signals)" line if PEAD is dead per SD#3.

**Add new subsection after Diagnostic D2 Status:**

```markdown
### Forensic Analysis Status (2026-04-16)

- **Report:** `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf`
- **Key finding:** Per-trade Sharpe 3.38 is SPY beta during a bull run, not alpha.
  Mean excess vs SPY = +0.039% with t=0.098 over 75 matched periods.
- **Action:** SD#41 REVISED — halt Phase 1 optimization, run 3 diagnostics first.
- **Diagnostic D1 (SPY excess):** COMPLETE — v0.19.0, all 85 trades backfilled
- **Diagnostic D2 (attribution audit):** COMPLETE — Hypothesis B confirmed (yfinance MultiIndex bug), fix sprint drafted
- **Diagnostic D3 (regime/sector):** IN PROGRESS
- **Attribution resolver fix:** DRAFTED — `docs/sprints/sprint-attribution-resolver-fix.md`, awaiting execution
- **Stage 1 OOS validation:** NOT STARTED — gate: excess-mean > 0 at t > 1.0 over 30 trades
- **Stage 2 OOS validation:** NOT STARTED — gate: excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 trades

### Permanent Methodology Guardrails (SD#41 REVISED)

1. Every Sharpe claim must specify raw vs excess vs alpha
2. Every metric update must refresh the trade count
3. Category 2 forensics (own data) runs before Category 1 (literature) when both available
4. Attribution claims require methodology review — "100% accuracy" should trigger skepticism
```

**Known Blockers:** Add:

```
- Attribution resolver produces garbage data (yfinance MultiIndex bug); fix sprint drafted
- Alpha vs SPY is statistically zero at N=85; Stage 1 OOS validation not started
- Regime classifier NULL on 67% of trades (D3 in progress)
- sector_context 100% NULL (realized_sector backfilled as temporary fix)
```

---

### Task 3 — MASTER.md Section 5 (Strategy Decisions)

**Update count** in heading: "40 confirmed" → "41 confirmed" (or 42 if REVISED counts separately).

**Add SD#41:**

```
41. SD#41 REVISED: Diagnostic-first plan (docs/research/SD-41-REVISED-diagnostic-first-plan.md).
    Forensic analysis of 85 closed trades revealed per-trade Sharpe 3.38 is SPY beta during a
    bull run (excess vs SPY = +0.039%, t=0.098). HALT Phase 1 optimization. Run 3 diagnostics:
    D1 SPY excess instrumentation (DONE v0.19.0), D2 attribution resolver audit (DONE, Hypothesis B
    — yfinance MultiIndex bug), D3 regime/sector diagnostic (IN PROGRESS). New IB gate:
    excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades. Fund timeline: 24-30 months (was 18-24).
    Supersedes prior SD#41 trade lifecycle synthesis. Category 2 (own data) overrides Category 1
    (literature).
```

**Update SD#3:** Add note that PEAD is eliminated:

```
3. ~~Strategy #3 = Evolved PEAD (Phase 3)~~ **ELIMINATED.** PEAD dead for large caps
   (Martineau 2022, Subrahmanyam 2025). Replaced by Options Volatility Desk in Phase 3-4.
```

**Update SD#17:** Add note that attribution data is compromised:

```
17. Alpha attribution: parallel ranker-only shadow portfolio (second Alpaca paper account).
    **COMPROMISED (D2 audit 2026-04-16):** resolver produces 100% loss due to yfinance
    MultiIndex bug. Fix sprint drafted. All attribution claims rescinded until re-resolution.
```

**Update SD#36:** Phase 1 gate numbers are now wrong:

```
36. Phased live deployment gates ... Currently in Phase 1 ($100 live). Next gate:
    **REDEFINED (SD#41 REVISED):** excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades
    (was raw Sharpe-based at 50 trades). See Section 6 Phase Gates.
```

---

### Task 4 — MASTER.md Section 6 (Phase Gates)

**Replace the Phase 1→2 gate row completely:**

```
| Phase 1 -> 2 | **REDEFINED (SD#41 REVISED):** excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades, zero critical bugs, 7-day uptime, ≥90% conviction parse. Raw Sharpe ≥ 1.0 gate deprecated (trivially passed by SPY beta). Alpha attribution running with FIXED resolver (≥50 paired trades). Stress test (2008/2020/2022). | 85 closed, D1/D2 complete, D3 in progress, attribution resolver fix pending, Stage 1 OOS not started | ~15% (diagnostics phase) |
```

**Update Phase 2→3:**

```
| Phase 2 -> 3 | 100 closed Strategy #2 + RTX 3090 + options paper at $15-25K. NOTE: PEAD eliminated; Phase 2 is Equity Research Desk, Phase 3-4 is Options Volatility. | 0 | Not started |
```

**Update GRPO row:**

```
| GRPO | 100+ closed trades + RTX 3090 (24GB VRAM needed for num_generations=8) | 85 closed (approaching threshold) | Blocked on hardware + excess-Sharpe validation |
```

---

### Task 5 — MASTER.md Section 8 (Revenue & Business)

**Update the timeline table:**

| Month | Stream | Milestone |
|---|---|---|
| 0 (now) | Personal trading + capital injections ($1K/mo) | Start |
| 3 | Open Collective2 account (~$99/mo) | Track record clock starts |
| ~~6~~ **9-12** | Phase 1 validated (excess-Sharpe ≥ 0.5) → go live ($5-10K) | Verifiable live returns |
| ~~12~~ **15-18** | Signal marketplace ($200-$1K/mo) + RIA outreach | First external revenue |
| ~~18~~ **24** | Wyoming LLC + Section 475(f) | Legal entity (July 2026 target unchanged) |
| ~~24~~ **30** | Fund formation at $1-2M AUM | Management + performance fees |
| ~~36~~ **36-42** | Fund self-sustaining at $2M+ AUM (1.5%+17.5%) | Day job optional |

Add note: "Timeline extended 6-12 months per SD#41 REVISED diagnostic-first pivot. Wyoming LLC formation (July 2026) is calendar-driven, not gated on validation."

**Future Desks:** Update the intraday entry:

```
4. **Intraday Desk** (Phase 6+) -- separate model, 1-min bars, VWAP reversion.
   **Feasibility research in progress** (deep research prompt: docs/research/deep-research/intraday-desk-feasibility-prompt.md).
   IB historical data as potential primary source (free with account, 1-min bars ~1yr).
   Hardware gate: RTX 3090 minimum for sub-second inference.
```

---

### Task 6 — MASTER.md Section 11 (Sprint Queue)

**Replace the entire sprint queue** with the current diagnostic-first queue from SD#41 REVISED:

```markdown
## 11. Sprint Queue

### Active / Next (SD#41 REVISED diagnostic-first plan)

| # | Sprint | Status | Gate |
|---|--------|--------|------|
| 0 | SPY-matched excess instrumentation (D1) | **DONE v0.19.0** | — |
| 1 | Attribution resolver audit (D2) | **DONE** (Hypothesis B) | — |
| 2 | Regime/sector diagnostic (D3) | **IN PROGRESS** | — |
| 3 | IB cold storage | **DONE v0.18.0** | — |
| 4 | Earnings filter (H1 / SD#33) | **DONE v0.21.0** | — |
| 5 | Attribution resolver fix | DRAFTED | D2 audit complete |
| 6 | Stage 1 OOS validation (30 trades) | NOT STARTED | D1 + D3 + resolver fix |
| 7 | Time-decay exits on high-MFE stales | QUEUED | Stage 1 excess-Sharpe ≥ 0.3 |
| 8 | Sector concentration cap (max 4/sector) | QUEUED | D3 complete |
| 9 | Vol-targeted gross exposure | QUEUED | Volatile regime to test against |
| 10 | VIX step function | QUEUED | Populated vix_at_entry |
| 11 | Regime classifier v2 (SD#35) | DEFERRED | Post-diagnostics rebuild |

### Research Queue

| Topic | Status |
|---|---|
| Intraday desk feasibility | Deep research prompt drafted |
| Connors RSI(2) as alternative entry | Research pending (contingency if excess-Sharpe fails) |
| Options volatility desk | Phase 3-4, not active |

### Completed Sprints (historical)

[Preserve the existing DONE items from the old queue, but move them to a
"Completed" subsection so the active queue is clean]
```

---

### Task 7 — MASTER.md Section 12 (Reference Pointers)

**Dashboard Pages:** Update count from 22 to 25. Update the page list:
- Remove "Broker Comparison" (replaced by Trade History)
- Add "Trade History" with note "(excess-Sharpe lead panel, SD#41 D1)"
- Verify all page names match actual `frontend/src/pages/*.jsx` filenames

---

### Task 8 — Dashboard: Roadmap page update

**File:** `frontend/src/pages/Roadmap.jsx` (if it exists — check first)

If a Roadmap page exists, update it to reflect:
- SD#41 REVISED diagnostic-first plan
- New phase gate definitions (excess-Sharpe, not raw Sharpe)
- Sprint progress (D1 ✅, D2 ✅, H1 ✅, IB ✅, D3 🔄)
- Timeline adjustment (24-30 months, not 18-24)
- Attribution claims rescinded

If no Roadmap page exists, check whether the Dashboard.jsx or a similar page has roadmap/milestone content that needs updating.

```bash
# Check if Roadmap page exists
ls frontend/src/pages/Roadmap* 2>/dev/null
# Check for roadmap content in other pages
grep -rn "roadmap\|phase.*gate\|milestone\|timeline" frontend/src/pages/ --include="*.jsx" | head -10
```

---

### Task 9 — Dashboard: Trade History page verify

**File:** `frontend/src/pages/TradeHistory.jsx`

Verify the excess-Sharpe lead panel (from D1) renders correctly by checking:
1. The `useQuery` for `sharpe-attribution` exists
2. The `verdictColor` helper exists
3. The panel renders before the recency cards
4. No hardcoded "Sharpe 3.38" or similar stale numbers appear anywhere

If any stale references exist in other dashboard pages (Dashboard.jsx, Analytics.jsx, etc.), update them:

```bash
grep -rn "3\.38\|Sharpe.*1\.0\|50 trades\|18 closed" frontend/src/pages/ --include="*.jsx" | head -10
```

---

### Task 10 — README.md, CHANGELOG.md, RELEASES.md consistency check

**README.md:**
- Version badge should show v0.21.0
- Any "Phase 1 gate" language should reference excess-Sharpe, not raw Sharpe
- Trade count should say 85+, not 18

**CHANGELOG.md:**
- Verify version ordering is descending: v0.21.0 → v0.19.0 → v0.18.0 → v0.17.2 → ...

**RELEASES.md:**
- Verify v0.18.0, v0.19.0, v0.21.0 entries all present

---

## Success Criteria

1. MASTER.md reflects all 4 sprint merges from 2026-04-16
2. Phase gates use excess-Sharpe language everywhere
3. Trade count is 85 (not 18)
4. Attribution claims are marked as rescinded
5. Sprint queue reflects diagnostic-first plan
6. Revenue timeline shows 24-30 month adjustment
7. Dashboard pages have no stale hardcoded metrics
8. `scripts/verify_docs.py` passes
9. `cd frontend && npm run build` succeeds

---

## Commit Messages

```
docs(master): update Section 1 release + tech stack for v0.21.0
docs(master): update Section 2 metrics, deployed components, forensic status
docs(master): update Section 5 strategy decisions (SD#41, SD#3, SD#17, SD#36)
docs(master): redefine Section 6 phase gates for excess-Sharpe
docs(master): adjust Section 8 revenue timeline for 24-30mo diagnostic pivot
docs(master): replace Section 11 sprint queue with diagnostic-first plan
docs(master): update Section 12 reference pointers + dashboard page list
feat(frontend): update Roadmap/Dashboard pages for post-forensic state
docs: README/CHANGELOG/RELEASES consistency check
```

---

## Out-of-Scope

- Code changes beyond frontend JSX
- New research documents
- Sprint spec writing for future work
- Architecture diagram updates (separate sprint)

---

*Ready for CC execution.*
