# Pass 1 — Roadmap completeness audit evaluation (v0.25.2, #526)

**Branch:** `feat/roadmap-completeness-audit`
**Date:** 2026-04-19
**Sprint kind:** additions-only — no new code, Roadmap.jsx data + CHANGELOG [Unreleased] entry only.

## Scope

The updated prompt enumerates 21 items to add to `frontend/src/pages/Roadmap.jsx`:

- 16 under a new Phase 1 "Parked / deferred" subphase
- 1 under Phase 2 "Month 3: Validation + hardware" (UPS purchase)
- 3 under Phase 5 "Fund formation" (CPCV, live walk-forward, v1.0.0 release gate)
- 1 under Phase 3 as a new subphase "Second strategy candidate (v0.27.x)"

Guardrails from prompt:
1. Additions only — do not modify existing items.
2. Every item must have `r:` reference to issue/memory/spec.
3. Don't invent items — if memory reference is vague, either find concrete provenance or skip.
4. If memory-referenced item turns out to be already shipped, flip status to `done` with evidence.

## Per-item verification (Phase 1 Parked subphase)

### 1. HSHS dashboard page → **SURPRISE-SHIPPED → flip to `done`**
- Claim: "Geometric mean of 5 dimensions..."
- Evidence of prior shipment:
  - `frontend/src/pages/Health.jsx:247-280` — HSHS section with composite score + radar chart
  - `frontend/src/api.js` — `getHSHS()` client
  - `CHANGELOG.md:2329` — "Added: HSHS radar chart and live phase-weight display on the Health page"
  - `CHANGELOG.md:2374` — "HSHS live: 5-dimension health score from database, wired into CTO report + council + API"
  - `docs/dashboard-data-map.md:84` — `/api/health/hshs` endpoint documented
- **Resolution:** Add as `s: 'done'` with reference to Health.jsx. Not a "separate dashboard page" — it's already a first-class section of the Health page.

### 2. AI Council 5→7 agent expansion → **confirm pending**
- Claim: Expand 5 → 7 agents for strategic decisions
- Current state: `src/api/routes/council.py:14` — "multi-agent deliberation system where 5 specialized..."; `scripts/generate_directory.py:65` — "5-agent AI Council — Modified Delphi protocol"
- Verified: AI Council is 5 agents (Bull/Bear/Quant/Macro/Risk). Already in Roadmap as done at line 56 ("AI Council (5 agents)").
- **Resolution:** Add new item for 5→7 expansion as `pending`, distinct from existing done item.

### 3. Alpaca MCP server integration → **confirm pending**
- Claim: Planned Sprint 3 / shadow ledger M4
- Current state: Only 3 mention files (all docs/specs); no Alpaca MCP integration code
- **Resolution:** Add as `pending`.

### 4. IB shadow broker mode (log-only) → **confirm pending, clarify distinction**
- Claim: Log-only second broker for pre-migration comparison
- Current state: Roadmap line 93 has "IB shadow mode + dual routing" done — but that's *active dual execution* (score ≥80 routes to IB paper). The parked item is *log-only* — IB records what it would have done without actually submitting anything, for comparison.
- Verified: No "log-only" IB mode in source; distinct from dual-routing.
- **Resolution:** Add as `pending`. Clarify wording in description so it's unambiguously separate from shipped dual routing.

### 5. Research Analyst setup → **SKIP (superseded)**
- Claim: "Deferred until full training pipeline cycle confirmed end-to-end"
- Current state: `Roadmap.jsx:161` explicitly supersedes this concept:
  > "Supersedes the stale 'Research Analyst desk (relaxed thresholds)' concept — platform evaluates genuinely uncorrelated strategies, not relaxed variants of swing."
- Memory is vague ("Memory reference"), and the concrete provenance in the existing Roadmap marks it as intentionally retired.
- **Resolution:** Skip per guardrail #3 (don't invent items when memory is vague).

### 6. Refactor forensic_trade_audit_v1.py → **confirm pending (#497 OPEN)**
- Issue #497 OPEN, title: "Tech debt: refactor forensic_trade_audit_v1.py (1,534 lines) into src/diagnostics/ modules"
- Actual file: `scripts/diagnostics/forensic_trade_audit_v1.py`, **1,553 lines** (prompt said 1,534; drift of +19 lines)
- **Resolution:** Add as `pending`. Description should reflect scripts/ location (issue calls for relocation to src/diagnostics/).

### 7. Repository pattern for SQLite access → **confirm pending (#478 OPEN)**
- Issue #478 OPEN, severity:critical, title: "19 API route files directly access SQLite — no service/repository layer"
- **Resolution:** Add as `pending`.

### 8. Refactor executor.py mega-functions → **confirm pending (#479 OPEN)**
- Issue #479 OPEN, severity:critical, title: "executor.py contains three mega-functions (617/564/386 lines)"
- Verified current sizes in `src/shadow_trading/executor.py`:
  - `open_shadow_trade` (line 339 → 904): ~565 lines (prompt: 564 ✓)
  - `check_and_manage_open_trades` (line 1045 → 1663): ~618 lines (prompt: 617 ✓)
  - `open_live_trade` (line 1663 → 2050): ~387 lines (prompt: 386 ✓)
- Exact match. Total file: 2,334 lines.
- **Resolution:** Add as `pending`.

### 9. shadow_trading test suite organization → **confirm pending (#480 OPEN)**
- Issue #480 OPEN, severity:critical, title: "shadow_trading module lacks organized test suite despite being highest-risk code"
- **Resolution:** Add as `pending`.

### 10. WatchLoop god object refactor → **confirm pending (#367 OPEN)**
- Issue #367 OPEN, label: audit + architecture + technical-debt; title: "WatchLoop god object — 2003-line class, 721-line run() method"
- Actual file: `src/scheduler/watch.py`, **2,023 lines total**; `class WatchLoop` starts at line 103 (~1,920 lines for the class). Prompt said 2,003 — drift within tolerance.
- **Resolution:** Add as `pending`.

### 11. Phase 0 — Manual unwind of residual shorts → **confirm pending (#451 OPEN)**
- Issue #451 OPEN, label: shadow-ledger, title: "Phase 0 — Manual unwind of residual NVDA/GOOGL shorts (operator-owned)"
- **Resolution:** Add as `pending`. Category: `risk`.

### 12. Consolidate 4 position-cap sources → **confirm pending (#432 OPEN)**
- Issue #432 OPEN, title: "[refactor] Consolidate 4 disjoint position-cap sources into one source of truth"
- **Resolution:** Add as `pending`. Category: `risk`.

### 13. v0.24.1 scheduled-kind find_candidates_for_date wiring → **confirm pending (#494 OPEN)**
- Issue #494 OPEN, title: "Wire scheduled-kind find_candidates_for_date (v0.24.1)"
- **Resolution:** Add as `pending`. Category: `strategy`.

### 14. v0.24.1 python_plugin execution wiring → **confirm pending (#493 OPEN)**
- Issue #493 OPEN, title: "Wire python_plugin execution into find_candidates_for_date (v0.24.1)"
- **Resolution:** Add as `pending`. Category: `strategy`.

### 15. Tier 7: Factor decomposition + regime change detection → **confirm pending (#492 OPEN)**
- Issue #492 OPEN, title: "Tier 7: Factor decomposition + regime change detection + alerting (v0.24.1)"
- Distinct from existing Roadmap.jsx:120 correlation monitoring stack (which is Tier 1-3, not Tier 7).
- **Resolution:** Add as `pending`. Category: `risk`.

### 16. Tier 7: Pairwise Spearman correlation monitoring → **confirm pending (#491 OPEN)**
- Issue #491 OPEN, title: "Tier 7: Pairwise Spearman correlation monitoring (v0.24.1)"
- **Resolution:** Add as `pending`. Category: `risk`.

## Phase 2 addition (Month 3: Validation + hardware)

### 17. UPS purchase (CyberPower CP1500PFCLCD ~$220) → **confirm pending**
- Claim: Complements dedicated Arcis machine (hardware roadmap)
- Current Phase 2 Month 3 line 177: "Dedicated Arcis machine" pending item mentions "UPS" in specs but no dedicated UPS-purchase line.
- **Resolution:** Add as `pending`. Category: `hardware`.

## Phase 5 additions (Fund formation)

### 18. CPCV upgrade → **confirm pending**
- Claim: Lopez de Prado combinatorial purged cross-validation; ~20x compute
- Current state: walk-forward v1 framework live (PR #520). CPCV is referenced in research docs as future upgrade.
- **Resolution:** Add as `pending`. Category: `validation`.

### 19. Live walk-forward (rolling OOS extension) → **confirm pending**
- Claim: Rolling OOS window using live trades
- **Resolution:** Add as `pending`. Category: `validation`.

### 20. v1.0.0 release gate → **confirm pending**
- Claim: Fund-formation readiness gate with explicit prerequisites (WF live + v0.26 PASS + N=150 trades + WY LLC + 475(f) + Collective2)
- Current RELEASES.md: v1.0.0 gate criteria documented.
- **Resolution:** Add as `pending`. Category: `legal` (matches other gate items like 475 MTM election).

## Phase 3 addition (new subphase "Second strategy candidate (v0.27.x)")

### 21. v0.27.x — Second strategy candidate → **confirm pending, new subphase**
- Claim: Overnight/intraday tug-of-war OR Medhat-Schmeling STMOM
- Placement note: "Months 1-3: Breakout R&D" subphase already exists; creating a new subphase "Second strategy candidate (v0.27.x)" keeps second-strategy work grouped separately from breakout-specific work.
- **Resolution:** Add new subphase under Phase 3 with 1 pending item. Category: `strategy`.

## Summary

| Bucket | Item count | Notes |
|---|---|---|
| Phase 1 "Parked / deferred" (new subphase) | 15 | 16 minus #5 Research Analyst skipped; 1 of 15 (HSHS) ships as `done` |
| Phase 2 Month 3 | 1 | UPS |
| Phase 3 new "Second strategy candidate (v0.27.x)" subphase | 1 | |
| Phase 5 Fund formation | 3 | CPCV, live walk-forward, v1.0.0 gate |
| **Total items added** | **20** | |
| Skipped | 1 | Research Analyst (superseded) |
| Surprise-shipped (status `done` instead of `pending`) | 1 | HSHS → Health.jsx |

## Placement decisions

1. **Phase 1 "Parked / deferred" subphase** — place AFTER "v0.25.0 — Rigor + hygiene bundle" (current line 125-137). This keeps the completed-work subphase adjacent to the current deferred-work subphase and preserves the chronological story.
2. **Phase 2 UPS** — append to Month 3 items (current ends at "Dead man's switch" line 178).
3. **Phase 3 new subphase** — add AFTER "Months 3–6: Validation + scaling" (current ends at line 205) so it's the last subphase of Phase 3, signaling "future" within the phase.
4. **Phase 5** — append to "Fund formation" subphase (current ends at "Seed capital conversations" line 238).

## Pass 2 investigation list

For Pass 2 (research doc), confirm:
- Issue bodies still match prompt descriptions (paraphrase check)
- Memory claims for Alpaca MCP + IB log-only + HSHS are consistent with git history (no intermediate shipments)
- `forensic_trade_audit_v1.py` line-count drift (1,534→1,553): does issue #497 body need an update, or is 1,534 acceptable context?
- WatchLoop `run()` method actual length vs 721-line claim
- Any other surprise-shipped items
