# Phase 5 — Codebase + Docs Consolidation (Unified Design)

**Date:** 2026-05-27
**Scope:** Closes #102 + #72 + #65 + #73 + #99 — the keystone phase before the #95 capstone (clean-slate wipe).
**Status:** READY FOR IMPLEMENTATION (r3 — post-Feasibility + Devil's Advocate revisions)

## Documents

- **[Master Spec](./master-spec.md)** — full design covering all 5 sub-efforts inline (hybrid shape c)
- **[Implementation Plan](./implementation-plan.md)** — 40 tasks across 7 PRs (PR-A through PR-G) with execution order, scope-fences, and dependencies
- **[Design Decisions](./design-decisions.md)** — 45 DDs with rationale + alternatives considered

## The Five Efforts

| Effort | Wave | What it does |
|---|---|---|
| **#99-debris + standards** | PR-A | Delete 17 `_*.py` repo-root scratch + 2 new structure rules + boundary-touch standards refresh (T0a) |
| **#73 Render code sweep** | PR-B | Delete `cloud_app.py` + `render.yaml` + `requirements-cloud.txt` + 2 render scripts; strip `DATABASE_URL` from 7 cloud_routes files (cloud_routes/ KEPT — load-bearing per DD-01) |
| **#65 Structure-debt** | PR-C | Targeted refactor of 8 grandfathered files in 3 sub-waves (C-i sequential, C-ii/C-iii parallel) |
| **#72 CollectorResult** | PR-D | New `CollectorResult` dataclass; migrate 22 collectors + `_safe_run` (Big Bang: collectors first, _safe_run last per DD-15 r3) |
| **#102 Test audit** | PR-E | Two-pass hybrid audit (heuristic + empirical) + 6-seam boundary-touch additions |
| **#99 Docs consolidation** | PR-F | README rewrite + MASTER §2 rolling-window + DIRECTORY regen + docs/audits archive sweep + CHANGELOG/RELEASES de-overlap |
| **Phase-5 close** | PR-G | 3 sentinels + known_violations final prune + kin-task subsumption commits (#125, #126) |

## Critical Architectural Decisions (highlights)

- **DD-01:** `cloud_routes/` is LOAD-BEARING for the local app via `app.py:183-190` — KEEP the directory, delete only `cloud_app.py` and Render infra files
- **DD-15 (r3, OPTION A):** Collectors migrate to `CollectorResult` FIRST; `_safe_run` flips LAST in PR-D to avoid intermediate broken HEAD
- **DD-08c:** T16 email_digest.py 3-module split (~380 + ~480 + ~250) is MINIMUM acceptable; optional 4th file if budget allows
- **DD-37:** CHANGELOG.md per-PR sentinel markers (`<!-- PR-A entries -->`, etc.) prevent merge conflicts across 7 PRs
- **DD-38:** Pass-B test audit methodology defined for unit / integration / fully-shimmed cases
- **DD-39:** Boundary-touch 6-item checklist embedded in spec §6.5 + verified in `docs/standards/boundary-touch-tests.md` via T0a
- **DD-40:** T13 CLI split uses decorator-preservation pattern (b) — sub-modules export DECORATED functions
- **DD-41:** T20-T25 per-task file cap raised from 4 to 6-8 to allow paired collector + test updates

## Review History

| Pass | Verdict | Findings |
|---|---|---|
| Feasibility r1 | REQUEST_CHANGES | 4 critical (scan_service.py path, sentinel-test path, email_digest size, telegram_commands collision) + 2 major + 3 minor |
| Architect revision r1 | REJECTED | Rescoping rewrite — lost 15 DDs + 16 tasks + dropped #102 audit entirely |
| Architect revision r2 | accepted with drift | Surgical fix preserving 36+2 DDs, 39 tasks |
| Feasibility r2 | REQUEST_CHANGES | 1 major (`_collector` suffix on 4 files) + 1 minor (DD count) |
| Devil's Advocate r2 | CONCERNS | 8 major + 3 minor + 1 nit + 6 strengths |
| **Architect revision r3 (FINAL)** | **READY** | All DA majors addressed + remaining feasibility drift fixed (45 DDs, 40 tasks including new T0a) |

## Implementation Notes

- Per-PR dual-Opus QA at 100% confidence (operator standard per `feedback_use_coding_team_skill.md`)
- Test floor: ≥5,467 SQLite-only / ≥5,267 PG-aware (held; net-add discipline per DD-20)
- 21:30-22:30 ET overnight merge embargo on all PRs (DD-34 / `feedback_no_restart_during_overnight_window.md`)
- NSSM smoke-test + visual-verify mandatory for PRs touching watch.py or src/api/* (DD-36)
- Sibling-search per `feedback_review_sibling_search.md` before each refactor (DD-16)
- Worktree isolation for parallel-dispatched agent waves (`feedback_strict_rigor_no_handwave.md`)

## Operator Decisions (§14 — RESOLVED 2026-05-27)

- **OQ-1 (KIN SUBSUMPTION) → RESOLVED:** PR-G subsumes BOTH #125 (6 tests need lazy-import) and #126 (2 walkforward stale-row tests). PR-G adds 1-commit close-out covering both; both close at Phase 5 end.
- **OQ-2 (TRADING-EMBARGO WINDOW) → RESOLVED:** Dead window 22:30-09:30 ET for PR-B + PR-D merges. Architect recommendation accepted.
- **OQ-3 (README AUDIENCE) → RESOLVED:** Operator-only + 1 link to MASTER.md for contributor case. Architect recommendation accepted.

All three resolutions confirmed by operator at design output time; no more pending operator-decisions for Phase 5 implementation.

## Out of Scope (deferred separately)

- #95 capstone clean-slate wipe (gated on Phase 5 STABLE)
- Sprint Cleanup-2 (#51 + #77)
- #115 PR-2 cutover (1-week hold-over)
- #116 PR-time vuln scanning
- New product features

## Dispatch

```
/arcis:code --spec docs/audits/2026-05-27-phase-5-unified/master-spec.md \
            --plan docs/audits/2026-05-27-phase-5-unified/implementation-plan.md
```

(or dispatch wave-by-wave for tighter control of QA cycles — recommended given multi-PR shape)
