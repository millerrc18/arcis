# Founder Operating Console — Design Spec

**Date:** 2026-06-04
**Status:** Draft for operator review
**Supersedes:** the current 28-page React dashboard (`frontend/`)
**Topic slug:** `founder-console`

---

## 1. Context & problem

Arcis is a one-person autonomous trading **research desk** whose entire software-development team is agentic AI. It runs a closed loop — scan markets → LLM-generate theses/recommendations → execute (currently **paper-only**; the ~$100 live book is dormant; **bootcamp mode is OFF**) → observe outcomes → train → repeat — largely unattended via an NSSM watch loop, on a dual-GPU Windows box.

The current dashboard has grown to **28 pages / 118 components / ~15.8K LOC** (React 19 + Vite + Tailwind + TanStack Query + Recharts; FastAPI backend on `:8000` with 20+ `cloud_routes`). A 2026-05-06 coherence audit logged **58 critical/important findings**. The failures were not aesthetic — they were **coherence** failures:

- The same metric (e.g. "win rate") shown 5+ ways with different cohorts and no labels.
- Header disagreeing with body (`25 positions` vs `0 open`).
- Raw sentinels rendered as values (`Profit Factor 999`).
- Hand-maintained panels silently going stale (Architecture said "23 pages" with 26; Roadmap missing a whole sprint; the Roadmap page is still dated 2026-04-26 and omits the entire v0.36.x / W21 body of work).

The operator's decision: **nuke the shell and rebuild simpler**, around what a lone founder running an AI dev team actually needs.

### The operating model that drives the design

Three facts shape every decision below:

1. **Solo, human-on-the-loop, attention-scarce.** One person (with a day job) supervises an autonomous system; they cannot watch it live. The console's first job is **triage**, not completeness. Industrial alarm standards (EEMUA-191) put a sustainable human ceiling at ~6 deliberate interruptions/hour; the console must respect a hard attention budget.
2. **The goal is a fundable track record.** The platform is a gated, multi-year bootstrap from solo AI trader → registered, audited fund ($100 → $1K → $5K → $25K → $100K+ → $500K+ AUM). Every displayed statistic must be **audit-grade and single-sourced** — for a fund, an incoherent metric is a *credibility* failure, not a UI annoyance. The operator's deepest recurring question is **"where am I on the ladder, against the next gate?"**
3. **The dangerous failure mode is silent divergence.** Arcis's incident history (orphan positions, phantom auto-closes, stale-but-green verdicts) is the textbook autonomous-system failure class: doing the wrong thing quietly while looking healthy. The console exists to make that **loud**.

---

## 2. Goal & success criteria

**Goal:** a single, coherent **operating console** that lets one human (a) keep an autonomous trading system trustworthy day-to-day, and (b) see — to audit-grade standards — where they are on the path to a fund and whether the track record is fundable.

**Success criteria:**

- **Glanceable triage:** in ≤5 seconds the operator knows "is anything wrong / does anything need me?"
- **Audit-grade coherence:** every displayed number has exactly one canonical definition, shown once, carrying its cohort + sample size (N) + as-of timestamp. Zero header/body contradictions; zero raw sentinels.
- **Legible:** the operator can hold the whole system — architecture, capabilities, roadmap/gate-ladder, accumulated research — in their head on demand, from views **derived from source** (never hand-typed), so they cannot drift.
- **Decision-centric:** the few things that need a human veto are surfaced as structured, un-missable decisions.
- **Honest about state:** `PAPER · bootcamp OFF`, staleness, and "no data ≠ zero" are first-class displayed states; the system occasionally confirms it is *working* (calibrated trust), not only failures.
- **Simpler:** a few coherent regions replace 28 sibling pages, with full analytical depth preserved one click down.

---

## 3. Architecture — the three regions

Top-level shape: **Now / Decide / Know** (single nav, three regions). The split honors a cognitive distinction the old dashboard ignored: **observability** ("what's wrong now" — glanceable, exception-driven) is a different mode from **legibility** ("hold the system in my head" — browsable, on-demand), and **decisions** (human-on-the-loop veto) deserve their own un-missable surface.

A persistent **honest header** is on every region: `ARCIS · vX.Y.Z · PAPER · bootcamp OFF · market state · clock` — all read from config/runtime, never narrated. The header also carries the **global PAUSE control** (decided 2026-06-04): a graceful pause reachable in one click from any region — stops new autonomous actions while keeping positions + monitoring, audit-logged, distinct from a hard kill.

### 3.1 NOW — the live cockpit (default landing)

Purpose: *is anything wrong, and what needs me right now?* Exception-first, attention-budgeted.

- **North-star hero — gate progress:** "Phase 1 · Bootcamp gate → first live capital," with the live gate metrics (closed trades, excess-Sharpe vs SPY, t-stat, max DD) against their targets and a progress bar. Honest about the gap.
- **Attention row (two-tier):** an explicit *positive* "Desk healthy — nothing requires action" confirmation (trust calibration) **and** a routed "N decisions waiting → Decide" chip. Only genuinely actionable, deviation-gated items appear; everything else is ambient.
- **Integrity & liveness signals** (SRE golden-signals, translated to the desk): watch-loop heartbeat age, data-feed freshness (oldest feed), **reconciliation** (break count + age — DB vs broker), risk-governor status (limits used). Each with an as-of time. Absence-of-signal is itself alarmed; nothing reads green on missing data.
- **Open positions** (one canonical reconciled source) — paper book, equity, today's move.
- **"Since you last looked (Nh ago)"** delta band — opened/closed, alerts raised/resolved, audit-verdict changes, deploys — for the periodic-check-in cadence.
- **AI dev-team** quiet strip — current activity + this-week PRs/regressions/scope-violations.

### 3.2 DECIDE — the veto queue (its own tab)

Purpose: *the few strategic gates that need a human.* Nothing here auto-executes or touches live money; the LLM never holds exit/sizing/risk authority (FINSABER boundary). Human-on-the-loop.

- **Challenge-and-response cards** (not bare "Approve?"). Each decision shows the **evidence that cleared its gate**, then **Intent · Blast-radius · Rollback**, then Approve / Reject / Defer + a drill-in. Decision types: **strategy promotions** (proposed→backtested→shadow→production, gated on DSR/PBO/walkforward), **model challenger promotions** (sequential test), **capital-advance gates** (when a phase gate is met), **halts** (auditor recommendations to approve/override), and **AI-dev-team approvals** (e.g. merge asks surfaced from the coding pipeline).
- **Risk-tiered:** low-risk items may be configured to auto-run; medium/high route here. (Over-governing routine work *causes* rubber-stamping — tier deliberately.)
- **"Recently decided"** trail + an honest **override-rate** indicator (an approver who never overrides has stopped truly reviewing).
- **Halts** here are auditor *recommendations* to approve/override. The PAUSE control itself lives in the global header (decided 2026-06-04), not in Decide, so it's reachable from any region when the operator is away from this tab.

### 3.3 KNOW — legibility + analytics + research (on-demand)

Purpose: *hold the whole system — what it is, what it knows, how it's performing — in your head.* Synthesis-first, **overview → drill-down**. This is where a redesign quietly fails (the "new 28-page dump"); the discipline is a few synthesized overviews on top, full depth one click beneath.

- **Fund ladder** (the roadmap, **derived** from trades + tasks/versions): Phase 1→6 with live gate progress. Replaces the hand-maintained Roadmap page; cannot drift.
- **Track record** (the operator's pinned **CTO Report**, promoted to first-class synthesis): audit-grade headline stats — Sharpe, excess-Sharpe vs SPY, PSR, DSR, win rate, profit factor, max DD, expectancy — single-sourced with cohort + N + as-of, plus the equity curve, linking into the full CTO Report drill-down.
- **Trade ledgers** (pinned, first-class): open / closed / history, searchable.
- **Rigor stack** (drill-down): Validation (PSR/DSR/PBO), Walkforward (OOS windows), Stress Test. Present, not daily.
- **Attribution** (drill-down): alpha vs SPY-beta; strategy vs pipeline vs LLM.
- **Research & calibration** (drill-down): searchable thesis/packet corpus, a weekly auto-synthesized "what we learned" digest, and the **outcome-tagged calibration** view (do high-conviction theses actually win?) — turning the corpus into a self-improving instrument rather than a dumping ground.
- **System map** (derived, drill-down): architecture, capability registry, DB schema — generated from source at build/render time, stamped with the git SHA.
- **AI dev-team scorecards** (drill-down): per-role (Planner/Developer/Reviewer) and per-task-type success/rework/escalation trends; silent-failure signals (scope-drift, trajectory-vs-output quality).

---

## 4. Cross-cutting design laws (non-negotiable)

These are the rules the old dashboard broke. They are constraints on **every** region and panel.

1. **Single source of truth per metric.** Each metric is **defined and computed once** (formula + cohort + window) server-side; the console is a pure consumer and never re-derives a number per panel. This is a backend contract (a "metric registry," parallel to the existing schema registry), not a UI convention.
2. **Label every metric.** Every displayed number carries its **cohort + N + as-of timestamp** inline. "A metric without a time window is a slogan."
3. **No raw sentinels.** Sentinels/nulls (`999`, `NaN`, `-1`, `∞`) are caught at the render boundary and shown as an explicit labeled state; a true `0` is visually distinct from "no data."
4. **Staleness is a displayed state.** Every panel reads a real freshness signal (reuse HealthProbe heartbeats) and visibly degrades past a per-data-type threshold. No cached verdict/badge renders without an as-of age and a max-age beyond which it degrades to "unknown" — **never** stays green on absence. (Directly fixes the 36h stale-verdict false-halt class.)
5. **Two-tier signal model.** A small **push** tier (actionable, deviation-gated, high-precision — every item names a recommended action) over a large **ambient** dashboard-only tier. Sized to an EEMUA-style attention budget. One false CRITICAL destroys the channel for a solo operator — prefer a missed low-severity nudge over a false high-severity alarm. Also confirm "system working" occasionally (calibrated trust).
6. **Overview → drill-down** (Shneiderman). Synthesis on top; deep analytics one click beneath; context preserved. No region is a flat menu of pages.
7. **Derive-from-source, fail-closed.** Every legibility view (ladder, system map, schema) is generated from a machine-readable source and asserted against it in CI — generalizing the existing capability-registry anti-drift guard (#88). Counts are computed, never typed. The UI shows "generation failed / stale as of <SHA>" rather than a silently stale snapshot. (LLM doc-diffing is advisory only; never a substitute for deterministic derivation.)
8. **Respect the LLM-authority boundary.** The console never implies the LLM controls exits, sizing, or the risk governor. Conviction is surfaced as commentary/soft signal only.
9. **Reconciliation = break-rate, not post-backfill state.** The reconciler auto-backfills orphans, which *repairs the symptom and erases the evidence*. The console surfaces retained **break events** (type, symbol, magnitude, age) even after auto-remediation — the break *rate over time* is the health signal.

---

## 5. What's cut / kept / parked (operator-approved 2026-06-04)

**Kept & upgraded (the analytics suite → Know):** CTO Report *(pinned first-class)*, Attribution, Validation, Walkforward, Stress Test, Model Performance, Simulation, Velocity. These are the track record; they become audit-grade and single-sourced.

**Kept, relocated + derived:** Roadmap → Know's gate ladder (derived); Architecture + DB Schema → Know's system map (derived); Packets/Notes/Strategy/Training/StrategyResearch → Know research/ML lifecycle (promotions route to Decide); Shadow/Trade ledgers → Now (open) + Know (history, **pinned first-class**); Settings retained.

**Compressed:** Health, Monitoring, Diagnostics, Logs (4 observability pages) → Now's integrity-signal row + the existing ops layer (`arcis:operate`, investigator agents, Tier-1/2/3 tools). Deep forensics live in the tools, not dashboard pages.

**Cut / parked (approved):** Build Score and HSHS composite scores (vanity composites — killed); IBShadow and Live Ledger (parked while paper-only / IB cold); hardcoded "What's New" (dropped); duplicate cohort-proliferated metrics (collapsed to one canonical each); AI Council page → demoted to a panel in Know.

---

## 6. Data & derivation requirements (backend)

The simpler shell does **not** mean less engineering — the depth and the honesty laws impose real backend work:

- **Metric registry / single-source layer:** a server-side definition+computation layer so every panel reads the same number with the same cohort/window. Bind to the existing schema registry where possible.
- **Derived-legibility endpoints:** ladder-from-tasks-and-versions; system-map/architecture/schema-from-registry; each regenerated and CI-asserted against source.
- **Reconciliation break-event retention:** emit and retain break events (type/symbol/magnitude/timestamp) for the console even after auto-backfill.
- **Freshness/heartbeat exposure:** per-feed last-update and per-process heartbeat ages, intraday-aware thresholds (reuse #120/#122/#123 work).
- **Recommendation → trade → P&L linkage:** the calibration view depends on a reliable join from recommendation (confidence) → shadow_trade → realized P&L. This sits in Arcis's known FK-fragility zone — **dependency, must be verified** (relates to #134 TradingState source filter, #135 DBQuery DSN, and the orphan/dangling-FK history).
- **Decision-queue source:** a unified feed of pending gates (strategy/model promotions, capital advances, halts, AI-team asks) with the evidence + blast-radius + rollback fields per item.

---

## 7. Build approach (decided 2026-06-04)

- **Frontend:** **rebuild the shell** (a new 3-region app) on the **same stack** (React/Vite/Tailwind/TanStack Query/Recharts — modern, no reason to switch). **Salvage, don't rewrite** the high-value analytical components (CTO Report rendering, the rigor/stress/walkforward visualizations, attribution, ledgers, charts) — they are the depth that stays. "Nuke and start over" applies to the *shell and IA*, not the audit-grade analytics.
- **Backend:** **augment + consolidate**, not rebuild. The FastAPI `cloud_routes` and data largely stay; add the metric-registry layer, the derived-legibility endpoints, reconciliation break-event retention, and the decision-queue feed. Collapse duplicate/cohort-divergent endpoints to canonical ones.
- **Migration:** stand the new console up alongside the old, region by region (Now → Decide → Know), cutting over once each region reaches parity-or-better. The old app is deleted only when the new one is complete.

---

## 8. Module boundaries (for isolation & testability)

- **Region modules** (`Now`, `Decide`, `Know`) — each a self-contained feature with a clear data contract; no shared mutable state beyond the metric layer.
- **Metric layer** (backend) — the single owner of every displayed number; consumers cannot re-derive.
- **Derivation layer** (backend) — generators for ladder/system-map/schema, each independently testable and CI-asserted.
- **Decision-queue service** — owns the pending-gate feed + decision actions (approve/reject/defer) with audit-logged outcomes.
- **Render-boundary primitives** (frontend) — shared components enforcing laws #2/#3/#4 (a `<Metric>` that *requires* cohort/N/as-of, a sentinel/null guard, a staleness badge) so honesty is structural, not per-developer discipline.

---

## 9. Out of scope

- The autonomous trading/learning logic itself (strategies, risk governor, training) — unchanged.
- Reviving live trading or IB (parked; the console must *support* them returning, e.g. Live Ledger lights up when live resumes).
- Native mobile (Capacitor already deprecated; PWA/responsive only).
- The clean-slate wipe (#95) and other in-flight W21 items — independent, though a clean console pairs naturally with the clean-slate relaunch.

---

## 10. Success metrics (post-build)

- Coherence: 0 duplicate-cohort metrics; 0 header/body contradictions; 0 raw sentinels (enforced by render-boundary primitives + tests).
- Drift: legibility views CI-asserted against source; 0 hand-typed counts.
- Footprint: ≤ ~3 regions / a small set of synthesized overviews replacing 28 pages; component count materially reduced.
- Trust: every metric labeled (cohort/N/as-of); staleness always visible.

---

## 11. Decisions resolved at review (2026-06-04)

All four open questions were resolved by the operator:

1. **Build approach:** **Rebuild the shell + salvage analytics + augment backend** (§7). New 3-region app on the same stack; port the high-value analytical components; the backend gains a metric layer + derived endpoints rather than a rewrite.
2. **PAUSE placement:** **Global top-bar** — always visible, one click from any region (§3 header).
3. **Implementation pipeline:** **`arcis:code`** (PM orchestrator + dual-Opus-QA merge gate). The PM presents a task graph for approval, then builds region-by-region.
4. **Calibration dependency:** **#134 and #135 are hard prerequisites.** The recommendation→trade→P&L join must be corrected before any console work that touches it; the calibration view — and the live/paper book reads behind Now and Track-record — are gated on those fixes landing first.

**Prerequisite (Phase 0, before the console build):** land **#134** (TradingState `source='live'` hides the paper book) and **#135** (DBQuery default DSN reads stale SQLite) so the console reads the book from one correct, canonical source. These also directly de-risk law #1 (single source of truth) and law #9 (reconciliation).

---

## 12. Design decisions log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Shape = three regions (Now / Decide / Know) | Observability vs legibility are distinct modes; the veto queue is the human-on-the-loop core and must be un-missable. Operator-confirmed. |
| D2 | North-star = fund-ladder gate progress | The operator's deepest recurring question is "where am I on the ladder?"; the roadmap reframed the whole console. |
| D3 | Kill Build Score + HSHS | Composite-of-composites vanity metrics erode trust ("why is my score 73?"); the real gate ladder replaces them. Operator-approved. |
| D4 | CTO Report + ledgers pinned first-class; rigor pages as drill-down | Operator-stated daily reliance; everything else overview→drill-down. |
| D5 | Single-source metric layer + render-boundary honesty primitives | The audit's #1 failure (metric ambiguity) is fixed structurally, not by discipline. |
| D6 | Derive-from-source + fail-closed for legibility views | The roadmap/architecture/schema staleness was the literal cause of the audit's drift findings; generalizes #88. |
| D7 | Rebuild shell, salvage analytics, augment backend | "Nuke and simplify" targets the incoherent shell, not the audit-grade analytics depth (which a fund needs more of). |
| D8 | Reconciliation surfaces break-rate, retains break events post-backfill | The reconciler currently hides the orphan-source bug by auto-healing; the break rate is the real signal. |
| D9 | Rebuild shell + salvage analytics + augment backend | Operator-chosen; "nuke" targets the incoherent shell, preserves audit-grade depth and working API routes. |
| D10 | Global top-bar PAUSE | Operator-chosen; absent-operator risk demands a one-click halt from any region. |
| D11 | Implement via `arcis:code` (dual-Opus QA) | Operator-chosen; matches the standing feature-work standard (PM + dual-QA merge gate). |
| D12 | #134/#135 are hard prerequisites | Operator-chosen; the recommendation→trade→P&L join must be sound before the console reads or calibrates on it (fix-before-build). |

---

## Appendix A — Research foundation

This design is grounded in a 7-domain research sweep (2026-06-03). Key load-bearing findings → the laws they drive:

- **Solo-operator consoles / attention economy** → laws #5 (two-tier, attention budget), #6 (glanceable). *EEMUA-191 (~6 alerts/hr ceiling); DevOps alert-fatigue (PagerDuty/Datadog — "if an alert isn't actionable it shouldn't exist"); human-on-the-loop supervisory control.*
- **Quant/algo trading-desk oversight** → §3.1 integrity-first, law #9. *SEC 15c3-5 reject-not-scramble controls; FIX drop-copy reconciliation; "software can't substitute for human attention" (FIA).*
- **AI-agent ops & observability (frontier)** → §3.2 (challenge-and-response, risk-tiered), §3.3 AI-team scorecards. *Gartner "guardian agents" (Reviewer/Monitor/Protector); trajectory-vs-output grading (+20-40% failures caught); sycophantic "done" reports; OTel GenAI semantic conventions. Single-operator supervision is genuine whitespace.*
- **Operational information design** → laws #1, #2, #3, #6. *Google SRE golden signals + symptom-not-cause + every-page-actionable; Shneiderman overview→drill-down; Tufte data-ink; "metric without a time window is a slogan."*
- **Human oversight of autonomous systems** → laws #4, #9, §3.2 PAUSE. *Bainbridge "ironies of automation"; Knight Capital ($440M/45min, wrong trigger); freshness-as-first-class-signal; "untrained/complacent approver worse than no checkpoint" + override-rate as a health signal.*
- **System self-legibility** → law #7, §3.3 system map. *Backstage software catalogs; Structurizr/C4 + SchemaSpy/ChartDB (derive ERD from live schema in CI); GitHub Projects roadmap-from-issues; deterministic-derivation > LLM-advisory drift detection.*
- **Research-corpus surfacing** → §3.3 research & calibration. *NN/g insight-DB vs document-library (hybrid: synthesis linking to artifacts); collector's fallacy; ADR decision logs; outcome-tagged calibration (forecast quality control); avoid the searchable dumping ground.*

Full per-domain briefs (findings, candidate requirements, sources, maturity flags) are retained in the session research output.
