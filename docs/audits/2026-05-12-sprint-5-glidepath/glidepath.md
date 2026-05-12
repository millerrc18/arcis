# Sprint 5 Glidepath — Final Sprint Plan

**Created:** 2026-05-12
**Author:** PM (Claude) at operator request
**Sprint status:** Sprint 5 in flight; SP5 §J5/§J6 cutover-rectification CLOSED (PR #1056); SP5 §J5/§J6 Phase 3-revised one-DB cutover EXECUTED (2026-05-11 → 2026-05-12 02:52 ET, smoke clean, halcyon_app least-privilege role flip complete).

## Sprint goal

Close all remaining Arcis backlog into a launch-ready state. **Sprint 5 is the final sprint.** After Sprint 5 closes, the only active development scope is **walk-forward framework implementation**, which is explicitly deferred per operator directive ("separate focus from that one until the DB unification is complete" — 2026-05-11; DB unification is now complete, but walk-forward stays its own track).

## Out of scope (no SP6)

- **Walk-forward framework implementation** — spec exists at `docs/audits/.../walkforward-spec-v1.md` (Batch B, task #81), implementation is a separate post-Sprint-5 sprint
- Anything labeled `#SP6-*` (none exist by design — Sprint 5 absorbs all current backlog)

## Wave decomposition

Six waves, ordered by (1) fresh-context affinity, (2) dependency, (3) blast-radius. Each wave ends with a green test suite + CHANGELOG entries.

### Wave A — Cutover settlement (small, fresh) — ~½ day

| Task | Title | Size |
|---|---|---|
| #92 | `_check_row_counts` cross-engine KeyError:0 fix + AST sweep for `.fetchone()[N]` siblings | small (1-line fix + lint) |
| #77 | Document `PYTHONUTF8=1` training-env requirement | trivial (docs) |
| #26 | `known_violations.json` render_sync.py size update follow-up | trivial (config) |
| #27 | Pre-existing `test_repo_structure` violations — decide: real-fix or grandfather | small-medium |

Rationale: All four are cutover-adjacent or recently-surfaced. Banging them out first builds momentum and clears noise before tackling larger pieces.

### Wave B — Sprint 4 close-outs — ~½ day

| Task | Title | Size |
|---|---|---|
| #65 | Extend `_html_escape` to `notify_risk_alert` + `notify_exposure_alert` | small |
| #66 | Negative `total_pnl_dollars` test fixture in KPIStrip | small |
| #67 | Wire `write_heartbeat()` into watch-loop scheduler | small |
| #48 | Mirror #44 kwarg assertions to `test_bracket_safety.py` | small |

Rationale: Sprint 4 follow-throughs deferred at sprint close. They're orphan-adjacent — closing them now removes Sprint 4 from the active surface and lets Sprint 5 own a clean board.

### Wave C — Data integrity hardening — ~1 day

| Task | Title | Size |
|---|---|---|
| #54 | Wire `kpis.py:91` to pass dates+directions to `_compute_promotion_gate_kpi` | small-medium |
| #56 | Add `strategy_id` FK to `shadow_trades` + wire into methodology gate filter | medium (schema + migration + caller updates) |
| #68 | Consolidate council typed exceptions into `src/council/errors.py` | medium (refactor) |
| #45 | Operator-manual-intervention drift detection | medium (new detection layer) |
| #47 | Triage findings from Telegram + email sweep audit (#46) | medium (assess + file individual fixes) |

Rationale: Sprint 6's notifications-routing-policy (Wave D) will rely on consistent typed exceptions and FK integrity. Doing the data-model groundwork first means Wave D builds on a solid base.

### Wave D — Notifications routing policy (`#SP5-notifications-routing-policy`, #69) — ~1.5–2 days

The largest single piece. Needs an `arcis:design` spec before any code.

**Scope:**
- Mute rules per channel (Telegram, email) — by time-of-day, by severity, by event_type
- Digest mode — bundle low-severity events into 5-min / 15-min / hourly summaries instead of per-event firing
- Routing layer — operator-defined "event_type X goes to channel Y" config

**Plan:**
1. Dispatch `arcis:design` skill against an inline brief (mute / digest / routing requirements + current notifications inventory)
2. Operator reviews + approves spec
3. Dispatch `arcis:code --spec ...` for implementation
4. Reviewer wave (QA + security on config-loading paths)
5. Visual-verify on dashboard's Notifications panel if affected
6. Sprint 5 docs update

### Wave E — Dual-GPU utilization (#91) — design ~1 day, impl deferred

Triggered by 2026-05-12 hardware install (RTX 3060 alongside existing RTX 3090).

**Plan:**
1. Dispatch `arcis:design` skill to spec workload-separation strategy (3060 inference, 3090 training+council, vs alternatives)
2. Spec stays "ideation deliverable" — actual implementation may slip to Wave F or post-sprint if low-impact
3. Decision point: ship as design-only and defer implementation, or implement in Sprint 5

Parallel-execution candidate with Wave D (different domains — notifications vs ML infrastructure).

### Wave F — Dev tooling / test infrastructure — ~1 day

| Task | Title | Size |
|---|---|---|
| #15 | Pre-merge stale-base hook (server-side complement to client-side #59) | medium (CI workflow) |
| #86 | Speed up full test suite (chronic timeout root cause = `test_cloud_requirements_imports.py`) | medium-large (investigation + restructure) |
| #87 | Provision local test PG for agents (so cross-engine tests no longer skip) | medium-large (Docker integration in conftest.py) |

Rationale: These are PM-quality-of-life improvements that didn't block any prior sprint but compound long-term. Doing them at sprint-close means future post-Sprint-5 work (walk-forward) inherits a smoother dev loop.

### Sprint Close — ~½ day

- Final integration sweep across all waves (cross-task regression check)
- CHANGELOG: aggregate Sprint 5 closeout entry under `[Unreleased]`
- `src/version.py` bump + git tag (release decision: minor or patch?)
- Roadmap update — Sprint 5 marked complete, walk-forward becomes the active track
- Operator-guide append: post-Sprint-5 state summary

## Estimated wall-clock

| Wave | Effort |
|---|---|
| A | 0.5 day |
| B | 0.5 day |
| C | 1.0 day |
| D | 1.5–2.0 days |
| E | 1.0 day (design only); +1–2 days if implementation lands in sprint |
| F | 1.0 day |
| Close | 0.5 day |
| **Total** | **6.0–8.0 days** of focused dev time |

Calendar — if working through at 6 focused dev hours/day, ~7-10 calendar days. If split with market-watching during sessions, ~10-14 days.

## Sequencing logic

```
Wave A ──┐
         ├─→ Wave B ──→ Wave C ──┬─→ Wave D ──┐
                                  │            ├─→ Close
                                  └─→ Wave E ──┤
                                  └─→ Wave F ──┘
```

- A→B→C is strict sequential (each compounds context)
- C must complete before D (typed exceptions + FK groundwork)
- D, E, F can run in parallel after C (different domains)
- All three must complete before Close

## Dispatch pattern

For each Wave, the PM (Claude) follows the standard `arcis:code` orchestration:

1. **INTAKE** — read backlog tasks for the wave
2. **PLAN** — dispatch `coding-planner` with all tasks bundled (small waves) or per-task (larger waves)
3. **EXECUTE** — parallel developer dispatches with worktree isolation
4. **REVIEW** — QA + Security + Performance reviewers per planner's selection
5. **DOCUMENT** — Documentarian for each closed task
6. **INTEGRATE** — Integrator final sweep
7. **REPORT** — PR open + operator review

**Variant for Wave D:** `arcis:design` first → spec doc → operator approval → `arcis:code --spec`
**Variant for Wave E:** `arcis:design --spec-only` first → spec doc → operator decides if implementation goes into sprint

## Risk areas / known landmines

1. **Test suite chronic timeout (#86)** — recurring throughout cutover-rectification sprint. Plan: fix #86 EARLY (Wave A or B) so subsequent waves don't lose agent budget to hung agents.
2. **Cross-engine row-factory bugs (#92)** — the AST sweep may surface 5–20 sites. Plan: triage as small follow-ups within Wave A; don't let it balloon.
3. **Wave D scope creep** — notifications-routing-policy is operator-defined surface. The spec needs hard boundaries. Plan: design-team's adversarial reviewer is the gate.
4. **Wave E hardware drift** — 3060 install may have driver / VRAM-detection / CUDA-version surprises. Plan: pre-flight `nvidia-smi` confirmation + ML stack import test before design spec gets specific about workload split.

## Open questions for operator

- **Wave E (#91)** — design-only or design + implementation in Sprint 5? Affects total effort by 1–2 days.
- **Sprint close versioning** — is the post-Sprint-5 release a minor bump (0.X.0) or patch (0.X.Y)? Currently `src/version.py` reads... (need to check)
- **Wave D notifications-routing-policy** — any pre-existing operator preferences (e.g., "I always want shadow_trades.status='filled' to ping Telegram immediately")? Affects spec defaults.

## Success criteria — Sprint 5 close

- [ ] All pending tasks (Waves A–F) closed OR explicitly scoped-out to post-sprint
- [ ] Zero `#SP5-*` pending issues remain
- [ ] Test floor preserved (≥3682, growing with new test additions)
- [ ] CHANGELOG `[Unreleased]` aggregated into a sprint-close entry
- [ ] Roadmap updated; walk-forward becomes the active post-Sprint-5 track
- [ ] One operator-visible PR per Wave (6 total + Close) for clean review surface

## Out of scope: walk-forward framework

Per operator directive (2026-05-11): walk-forward implementation is deferred to post-Sprint-5. Spec exists at `docs/audits/2026-05-08-walkforward-framework/spec-v1.md` from Batch B (task #81). When Sprint 5 closes, this becomes the active development scope as a new sprint.
