# Sprint 5 — Scope Inventory (Final / Terminal Sprint)

**Created:** 2026-05-08 (post-Sprint-4 close, main HEAD `56fd7fb`, tag `v0.34.0`)
**Operator policy (per memory `feedback_sprint_5_is_final`):** Sprint 5 is the **last** sprint. No SP6+ tags. Anything that does not ship in SP5 must be explicitly closed-without-fix with operator acknowledgement, or formally scoped out (separate post-S5 effort).

---

## Strategic constraints (operator-decided 2026-05-08)

1. **Terminal sprint.** Queue must hit zero by SP5 close. Tag `#SP6-*` is forbidden.
2. **Post-Sprint-5 posture: feature-freeze / bug-fix only.** No live-trading promotion gate as a S5 deliverable. Paper trading continues post-S5; live-trading promotion is a separate decision later. SP5 must NOT include live-trading-readiness tasks.
3. **#37 unified DB consolidation is OUT OF SCOPE.** PR #940 design investigation already merged; further work parked as a separate post-S5 effort. Do not pull #37 prerequisites back into SP5.
4. **Scope of "maintainable state":** post-S5, no new functionality. Bug fixes, security patches, dependency bumps only.

---

## A. Notifications subsystem (4 canonical GH issues)

| # | Issue | Title | Implementation surface |
|---|-------|-------|------------------------|
| A1 | #1040 | T22 deferred — routing/policy/digest | `src/notifications/telegram.py`, `src/services/email_*.py`, new routing module |
| A2 | #1041 | CC6: `[ARCIS]` prefix on Telegram | `safe_send` / `_send_single` in `src/notifications/telegram.py` |
| A3 | #1044 | Convert remaining 28 `notify_*` to typed dataclass payloads | `src/notifications/telegram.py` (extend pattern from T21-REV) |
| A4 | #1045 | Move 5 typed council exceptions to `src/council/errors.py` | `src/notifications/telegram_commands.py:33-50` → `src/council/errors.py` |

**Dependency note:** A1 should land **before or with** A3 since safe_send routing entries need to know the event types A3 introduces. A2 is mechanically independent. A4 is independent.

**Implicit follow-ups discovered during SP4:**
- `_PAYLOAD_EVENTS` set should be hoisted out of inline definition to a top-level constant for readability (cosmetic, ~5 lines).
- `notify_risk_alert` + `notify_exposure_alert` need `_html_escape` wiring (tracker #65 — SP4 T13 follow-up).

---

## B. Code-quality canon (test_repo_structure.py)

These have been "pre-existing" across 4 sprints. SP5 closes the pattern.

### B1. `test_no_file_over_400_lines` — 1 NEW + 6 grandfathered

| Status | File | Lines | Disposition candidate |
|--------|------|-------|------------------------|
| **NEW** | `src/evaluation/backtester.py` | 408 | Trim or split (added during SP4 — Calmar migration likely pushed over) |
| GF | `src/startup_checks.py` | 482 | Split into per-check modules |
| GF | `src/cli/commands.py` | 1456 | Major refactor — split by command group |
| GF | `src/council/agent_data.py` | 450 | Split per-agent gather_*_data fns |
| GF | `src/council/engine.py` | 703 | Split engine vs phase orchestration |
| GF | `src/data_enrichment/news.py` | 490 | Split fetch / enrich / cache |
| GF | `src/email/digest_builder.py` | 409 | Trim or split section builders |

### B2. `test_no_function_over_60_lines` — 1 NEW + ~13 grandfathered

| Status | Function | Lines |
|--------|----------|-------|
| **NEW** | `src/data_enrichment/news.py:fetch_news_sentiment` | 77 |
| GF | `src/main.py:build_parser` | 214 |
| GF | `src/cli/commands.py:cmd_config_fix` | 85 |
| GF | `src/cli/commands.py:cmd_collect_data` | 71 |
| GF | `src/cli/commands.py:cmd_live_close` | 70 |
| GF | `src/council/agent_data.py:gather_innovation_data` | 87 |
| GF | `src/council/agent_data.py:gather_tactical_data` | 87 |
| GF | `src/council/agent_data.py:gather_macro_data` | 82 |
| GF | `src/council/agent_data.py:gather_risk_data` | 79 |
| GF | `src/council/agent_data.py:gather_strategic_data` | 72 |
| GF | `src/council/aggregation.py:aggregate_votes` | 96 |
| GF | `src/council/aggregation.py:compute_dynamic_weights` | 89 |
| GF | `src/council/context.py:build_shared_context` | 70 |
| GF | `src/startup_checks.py:_check_render_postgres` | 65 |

### B3. `test_todos_have_issue_numbers` — 1 violation
- `src/scheduler/watch.py:793` — `# TODO: wire real per-packet conviction list from result when` — needs issue number or removal.

### B4. `test_all_modules_have_standard_docstring` — 7 grandfathered (warning, not failure)
- `src/services/mr_scan_service.py`
- `src/simulation/engine.py`
- `src/simulation/monte_carlo.py`
- `src/trading/alpaca_broker.py`
- `src/trading/broker_factory.py`
- `src/utils/type_safety.py`
- (one more — confirm via fresh run during design)

**SP5 canon disposition: HYBRID (operator-decided 2026-05-08).**

Scope (operator-confirmed, ~8–10 tasks):
- Fix the **1 NEW file violation:** `src/evaluation/backtester.py` (408 → ≤400)
- Fix the **1 NEW function violation:** `src/data_enrichment/news.py:fetch_news_sentiment` (77 → ≤60)
- Fix the **1 TODO violation:** `src/scheduler/watch.py:793` (add issue number or remove)
- Refactor the **4 worst-offender files** (split or trim):
  - `src/cli/commands.py` (1456 lines) — split by command group
  - `src/council/engine.py` (703 lines) — split engine vs phase orchestration
  - `src/data_enrichment/news.py` (490 lines) — split fetch / enrich / cache
  - `src/council/agent_data.py` (450 lines) — split per-agent gather_*_data fns
- Refactor the **2 worst-offender functions:**
  - `src/main.py:build_parser` (214 lines) — split into per-command parser builders
  - `src/council/aggregation.py:aggregate_votes` (96 lines) — extract sub-helpers
- **Accept all other grandfathered items as permanent.** Rename `known_violations.json` → `accepted_legacy_violations.json` (or comparable) so the test framing changes from "future fix" to "explicitly accepted". Tests must still PASS.

NOT in scope under Hybrid:
- `src/startup_checks.py` (482), `src/email/digest_builder.py` (409) — accept as permanent
- All other grandfathered functions in `cli/commands.py`, `council/agent_data.py`, `council/aggregation.py:compute_dynamic_weights`, `council/context.py:build_shared_context`, `startup_checks.py:_check_render_postgres` — accept as permanent
- All grandfathered docstring warnings (§B4) — accept as permanent unless a refactor incidentally adds the docstring

---

## C. Pending tracker tail (prior-sprint follow-ups)

| Tracker # | Title | Cluster |
|-----------|-------|---------|
| #15 | Pre-merge stale-base hook (server-side / merge-time) | Tooling |
| #26 | Separate PR for known_violations.json render_sync.py size update | Code-quality |
| #27 | (=B1+B2+B3 above) | Code-quality |
| #45 | Operator-manual-intervention drift detection | Observability |
| #47 | Triage findings from #46 Telegram + email sweep audit | Notifications (overlaps A1) |
| #48 | Mirror #44 kwarg assertions to test_bracket_safety.py | Testing |
| #54 | Wire `kpis.py:91` to pass dates+directions to `_compute_promotion_gate_kpi` | Dashboard / API |
| #56 | Add `strategy_id` FK to `shadow_trades` + wire into methodology gate filter | Schema |
| #65 | Extend `_html_escape` to `notify_risk_alert` + `notify_exposure_alert` | Notifications (sub-task of A1) |
| #66 | Add negative `total_pnl_dollars` test fixture in KPIStrip | Frontend testing |
| #67 | Wire `write_heartbeat()` into watch-loop scheduler | Observability |

**Cluster summary:** Notifications cluster (#47, #65 + GH A1) consolidates with §A. Code-quality cluster (#26, #27) consolidates with §B. Observability cluster (#45, #67) is a small new section §D below.

---

## D. Observability / drift detection (new section)

| Item | Source | Justification |
|------|--------|---------------|
| Operator-manual-intervention drift detection | #45 | Operator manual halt/override leaves no audit trail; needed for post-S5 maintenance posture |
| Watch-loop heartbeat metric (`write_heartbeat()` wiring) | #67 (SP4 T15 follow-up) | T15 added the function; never wired into scheduler. Needed for "is the loop healthy?" check |
| Pre-merge stale-base hook (server-side) | #15 | Complements client-side #59; prevents stale-base PRs from merging |

---

## E. Testing tail

| Item | Source |
|------|--------|
| Mirror #44 kwarg assertions to `test_bracket_safety.py` | #48 |
| Add negative `total_pnl_dollars` test fixture in KPIStrip | #66 |
| env-drift test fixtures (test_live_trading) — implicit | per memory `feedback_worktree_env_drift` |
| `_PAYLOAD_EVENTS` regression-lock test | implicit (SP4 hardening) |

---

## F. Dashboard / API tail

| Item | Source |
|------|--------|
| Wire `kpis.py:91` to pass dates+directions to `_compute_promotion_gate_kpi` | #54 (SP2 T3 follow-up) |
| Add `strategy_id` FK to `shadow_trades` + methodology-gate filter | #56 (SP2 T2 forward-compat) |

---

## G. Out of scope (operator-decided 2026-05-08)

| Item | Reason |
|------|--------|
| Unified DB consolidation (#37 / PR #940) | Multi-week effort; separate post-S5 project |
| Live-trading promotion gate | Post-S5 decision; not part of terminal-sprint cleanup |
| Live-broker validation tasks | Implies live-trading commitment; out of scope per posture |

---

## H. Open design questions for the Architect

1. **Canon disposition mode** — Aggressive vs Conservative vs Hybrid (see §B disposition options). Operator may prefer a specific stance to bound scope.
2. **Routing-policy abstraction layer** — Where does the routing engine live? Options: `src/notifications/routing.py` new module; or expand `safe_send` to include routing logic; or per-channel adapters. (Affects A1 + A3 sequencing.)
3. **Quiet-hours config** — Hardcode (e.g., 22:00–07:00 ET) vs config-driven. Per-event-type quiet-hours overrides allowed?
4. **Weekend-digest scheduler** — New scheduler or piggyback on existing `scheduler/watch.py`? Where does the digest accumulator persist (SQLite table vs in-memory + crash-recovery)?
5. **Backtester 408-line trim approach** — natural split point or just remove dead code? (A SP4 commit pushed it over the line; the diff history will show the cleanest fix.)

---

## I. Sprint 5 success criteria

- All 4 SP5 GH issues closed (#1040, #1041, #1044, #1045).
- 11 pending tracker tail items closed (each either fixed or explicitly closed-not-planned with operator ack).
- `test_no_file_over_400_lines`, `test_no_function_over_60_lines`, `test_todos_have_issue_numbers` either PASS or explicitly accepted as permanent (whitelist renamed/restructured to reflect that).
- Test floor: SP4 ended at 4995. SP5 should add ≥30 tests (canon fixes + notifications regression locks + env-drift fixtures + kwarg mirror).
- Versioning: SP5 ships as `v0.35.0` per established cadence.
- Documentation: operator-guide + CHANGELOG + MASTER.md updated to reflect "system in maintainable state" closing chapter.
- Visual-verify gate on Render after merge — same protocol as SP3/SP4 closeouts.
