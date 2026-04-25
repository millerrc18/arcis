# Track 1.5 — PM Design Decisions (autonomous)

> **Decisions made autonomously by the PM (Claude Opus 4.7) on 2026-04-25 evening, after the operator stepped away with the directive: "make these design decisions, document them, and ensure they are executed. Everything we do has to make the system better, not worse, but sometimes that means surfacing the hard truths first."**
>
> Operator returns tomorrow morning to a Track 1.5 PR awaiting review. Every decision below is overrideable before merge.

## Operating principles invoked

1. **Fix-now over fix-later** (memory: `feedback_fix_before_trade.md`) — Critical+Important findings are deploy-blockers; default to fix-now.
2. **Make the system better, not worse** — surface hard truths even when uncomfortable; deploying a strategy we don't believe in is neutral in $ terms but psychologically committing in a way that distorts later judgment.
3. **Dashboard is operator's primary cockpit** (memory: `feedback_dashboard_strategic_lens.md`) — gaps + redundancies are first-class, not just technical hygiene.
4. **Backlog-fill workflow** (memory: `user_workflow_backlog.md`) — mid-sprint scope additions queue, don't pivot.

## Decision 1: Mon $100 deploy — DEFER

**The hard truth:** Stage-1 SPY-relative was non-significant at p=0.4326. Translation: we cannot reject the null hypothesis "this strategy's returns are indistinguishable from being randomly long stocks in a bullish window."

The operator's gut already knows this ("I really don't feel like the strategy has alpha right now"). Deploying $100 to "find out cheap" was defensible — but the operator chose the fix-now-before-trade principle, which materially changes the calculus:

- Pre-fix-now-principle: $100 is paper-grade noise, deploying is a $100 information bet → defensible.
- Post-fix-now-principle: trading is gated on technical health, AND deploying a strategy we believe doesn't have alpha is "making things worse" by spending live-data slots on a strategy we'll likely retire → not defensible under the operator's stated principle.

**Decision:** No live deploy Monday. Mon AM preflight still runs (system-health check, NOT deploy gate). Dashboard echoes the result via Round 8 (S4 fix). Next deploy decision happens after Cohort 3 redesign produces a strategy we have reason to believe in.

**Reversal trigger:** if operator wakes up tomorrow and explicitly overrides ("deploy anyway, I want the data"), reverse this decision before market open. Not blocking.

## Decision 2: Round 8 scope — fix all Critical + Important from both audits + 5-KPI strip

Per fix-now principle. Specific scope:

### From Round 7 technical audit (`docs/sprints/track_1_5_pass2_dashboard_audit.md`, commit `0380193`)

- **C1 Monitoring history shape mismatch** — backend returns `{snapshots: [...]}`, frontend expects array. One-line fix.
- **C2/C3/C4 Local-route parity** — `/ib-shadow/*`, `/strategy-detail/{type}`, `/system/index` exist only in cloud_routes. Add local route mirrors. Batched as single dispatch per agent recommendation.
- **C5 RevenueProjection live mode** — degrades gracefully but live route absent. Fix.
- **9 Important findings** — empty/loading state issues, mobile responsive gaps, dark/light edges, useQuery cache key inconsistencies. Bundled into one Round 8 catch-all.

### From Round 7b strategic audit (`docs/sprints/track_1_5_pass2_dashboard_strategic_audit.md`, commit `df9a249`)

- **R1 Three Sharpe formulas across four surfaces** — Dashboard hero + CTOReport use uncanonical `mean/stdev`; TradeHistory rolling chart adds partial annualization; only TradeHistory attribution panel uses canonical T1.03. Hero disagrees with signed Stage-1 memo. **Resolves via the 5-KPI strip rebuild.**
- **R2 Win rate silent Alpaca fallback** — Dashboard.jsx:469 falls back to Alpaca account API value (different denominator, no quarantine). Remove fallback; if shadow_service is null, show "—" not a misleading number.
- **R3 P&L source inconsistency** — Shadow Equity reads Alpaca paper balance; cumulative P&L chart reads shadow_trades with quarantine filter. Will diverge on first live trade. Document + reconcile.
- **G1 broker_exceptions not surfaced** — table written by B2.A (commit `c3e5431`); no API route, no panel. **Add `/api/broker-exceptions` endpoint + `BrokerExceptionsPanel.jsx`.** Critical for live-trade observability per fix-now principle.
- **G3 instrumentation_version distribution invisible** — operator can't see "what % of recent trades are v3?" Bundle into 5-KPI strip's N caption.
- **G6 Stage-2 OOS progress bar missing** — operator's most important medium-term countdown. Add to 5-KPI strip area.
- **S1 Dashboard hero answers wrong question** — uncanonical Sharpe instead of SPY-relative excess. **Resolved by 5-KPI strip.**
- **S2 No "distance to Halt" surface** — §3.1 Decision Matrix halt criteria invisible. Add to 5-KPI strip's Stage-1/2 traffic light.
- **S4 Preflight gate output no UI echo** — Mon AM transcript writes to disk, never read back. **Add preflight result card to Dashboard.**
- **6 Strategic-alignment findings remaining** — bundled into Round 8.E catch-all where applicable, deferred where they're "Future-need."

### NOT in scope (deferred)

- All Round 7 Cleanup-tier (7 findings): dead routes, dead components, hardcoded URLs. Defer to post-merge follow-up.
- All Round 7 Future-need (4 findings): not bugs. Defer to design decisions.
- Round 7b Future-need-tagged items: defer.

## Decision 3: Sprint queue post-Track-1.5

Operator queued 3 sprints in their final pre-step-away message. PM-amended order with Cohort 3 added:

1. **Sprint 1 — v0.26.3 sections_json widening** (operator-queued; ~3-pass cycle)
2. **Sprint 2 — System Index visibility audit** (operator-queued)
3. **Sprint 3 — Council impact analysis** (operator-queued)
4. **Sprint 4 — Cohort 3 strategy redesign** (PM-added; T2.14b + T2.14c + T2.16b at minimum; T2.07/T2.08 likely too)
5. Re-run Stage-1 baseline against the redesigned strategy
6. Deploy decision on the new strategy with new baseline

The fix-now principle does NOT compel doing Cohort 3 before deploy — Cohort 3 is research, not bug-fix. But the operator's stated lack-of-alpha gut says deploying the existing strategy is mis-aligned with "make it better not worse." So Cohort 3 logically precedes the next deploy.

## Decision 4: 5-KPI hero strip implementation

Operator-approved candidates (all 5):
1. **rf-adjusted excess Sharpe** (canonical T1.03)
2. **SPY-relative Sharpe + p-value + 95% CI lower**
3. **Win rate** (over closed quarantine-filtered trades)
4. **Stage-1/2 traffic light** (Green/Hold/Halt per §3.1 Decision Matrix)
5. **promotion_gate vote count** (≥4-of-5; placeholder until Stage-2 evaluation point)

**Implementation:**
- Backend: `src/api/cloud_routes/kpis.py` (NEW) — `/api/kpis` endpoint returning all 5 + N + last-updated timestamp + status flags. Single source of truth — every KPI uses canonical formulas.
- Frontend: `frontend/src/components/dashboard/KPIStrip.jsx` (NEW) — 5 cards, responsive (stacks mobile, row desktop). Each card has: name, value, color treatment, N caption, p/CI sub-line where applicable.
- Replace Dashboard hero's existing MetricCards. The redundant Sharpe surfaces on CTOReport / TradeHistory rolling chart get re-pointed at /api/kpis or marked as "diagnostic, see hero KPI strip for canonical."
- Rounds 7b's G3 (instrumentation_version distribution) and G6 (Stage-2 OOS progress bar) become caption + side-widget on the strip.

**Color rules per KPI:**
- rf-adjusted excess Sharpe: green if S>0 AND p<0.05, amber if positive but not significant, red if S<0 AND p<0.05.
- SPY-relative: green if positive AND p<0.10 AND CI lower>0; amber if positive but not sig; red if negative AND p<0.10.
- Win rate: green >55%, amber 45-55%, red <45%. Caveat: misleading on asymmetric P&L; use as supporting signal.
- Stage-1/2 traffic light: green/amber/red per §3.1 Decision Matrix (S, t-stat, CI lower).
- Promotion gate: shows X/5 with "MinTRL: gate not yet evaluable" caption until N≥150.

## Decision 5: Mon AM preflight protocol

- Run `scripts/preflight_monday.py` Mon AM unconditionally as system-health check.
- Output goes to disk (existing) + dashboard via Round 8.S4 fix.
- Result has no deploy effect — we're in fix-mode regardless.
- Operator reviews fix-mode-cleared status in dashboard, then advances to Sprint 1.

## Risks I'm taking on

1. **Deploy reversal**: if operator wakes up wanting to deploy anyway, my Decision 1 needs reversing fast. Mitigated by: PR not yet open, no irreversible state.
2. **5-KPI strip layout subjective**: my color rules may not match operator's mental model. Mitigated by: each rule is documented above; easy to tune in a follow-up.
3. **Round 8 scope sweeping**: ~14 fixes is a lot to dispatch in one wave. Mitigated by: each task has a narrow test command + commits independently; integrator sweep at Pass 2 close catches regressions.
4. **Cohort 3 added to queue without explicit approval**: operator queued 3 sprints; I added a 4th (Cohort 3 wiring). Mitigated by: queue is just a list; operator can re-sequence.

## What I'm explicitly NOT deciding

- Specific Cohort 3 task ordering (T2.14b vs T2.14c first, etc.) — defer until Sprint 4 dispatch
- Whether to add "Halt" auto-trigger to the dashboard — that's strategy decision, not technical
- Council disable/keep — Sprint 3's investigation comes first; I won't pre-empt
- v1.0.0 vs v0.27.0 — operator already chose v0.27.0
- Mon-AM-trade-anyway override — that's operator's call to make explicitly

## Hard truths surfaced (the "make it better not worse" lens)

1. **The bootcamp Sharpe of 6.14 was real but ~25% of the gap from "just SPY beta" survived rigor.** With 35 instrumented trades over 30 days in a bullish window, no methodology test can distinguish skill from regime tailwind. The audit didn't manufacture this honesty — it just stopped masking it.

2. **The dashboard you've been making decisions from has been showing you wrong numbers.** R1's three-Sharpe-formulas-disagree finding means the hero metric and the signed memo's metric have been different all along. T1.03 fixed the backend but never reached the frontend. Round 8 closes that gap.

3. **The "30 trades feel meaningful" intuition is incorrect at any normal Sharpe distribution.** MinTRL for declaring Sharpe > 0.5 at α=0.05 is in the 80-150 range for retail equity strategies. We're far from there. Deploy decisions before that point are committing capital on intuition, not data.

4. **Cohort 3 redesign might also not have alpha.** I'm not promising the new strategy will work. I'm saying: if we're going to spend the next deploy slot on something, we should spend it on something we have *reason* to believe in (T2.14b's logistic model has at least a non-heuristic basis), not something we already suspect doesn't work.

5. **Track 1.5's value is not in producing alpha — it's in giving you a system you can trust to tell you when you don't have alpha.** That sounds defeatist; it isn't. It's the precondition for ever knowing if you do.

## Execution log (updates as Round 8 dispatches land)

To be filled in as the night runs. Final summary will land in `SHIPPED.md` and the Track 1.5 PR body.
