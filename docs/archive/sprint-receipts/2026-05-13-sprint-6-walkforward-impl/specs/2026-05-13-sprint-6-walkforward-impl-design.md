# Sprint 6 — Walk-Forward Framework Wiring (Spec Extension)

## Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v1.0 | 2026-05-13 | Sprint 6 Architect | Spec extension on top of `walkforward-spec-v1.md`. Adds T13 (scheduler auto-fire) + T14 (production-gate symmetry) + T15 (sprint closeout) on top of locked v1 plan T1-T12. |
| v1.1 | 2026-05-13 | Director (post-Feasibility) | Applied 7 Feasibility-review findings as targeted spec patches. See §"Feasibility Resolutions" at end of doc. Headline changes: (a) `derived_from_backtest_id` column absorbed into T4 schema scope (column-additive — operator's "no new tables" constraint preserved); (b) `filelock>=3.0,<4.0` added to T13 dependencies + CLAUDE.md `New Dependencies` update folded into T13 scope_fence; (c) `_resolve_corpus_id_for_strategy(strategy_id, db_path) -> str | None` helper contract specified; (d) `WALKFORWARD_AUTOFIRE_ENABLED` docstring registration discipline added to T13 scope_fence; (e) cadence-mirror reference corrected from `_run_postclose_reconciliation` (once-daily) to the hourly market-hours handler pattern in `watch_handlers.py`; (f) `platform_events` JSON-path SQL form clarified for retry counting (`json_extract(payload_json, '$.strategy_id')`); (g) T15 test-count target tightened from 5320 to 5345 (5300 + 45 net adds across T1-T14). |
| v1.2 | 2026-05-13 | Director (post-Devil's-Advocate) | Applied 6 MAJOR DA findings as targeted spec patches + introduced NEW SP-WF-017 (sentinel-consistency check). See §"Devil's Advocate Resolutions" at end of doc. Headline changes: (DA-1) walkforward freshness cap (30 days + sha-match); (DA-2) retry-cap IN-list extension covering no-corpus + timeout paths; (DA-3) 90-min subprocess wallclock timeout + watchdog; (DA-4) manual CLI MUST acquire same lock as auto-fire (`--force` override); (DA-5) verification test that `promote()` persists walkforward_outcome_state in gate_result_json; (DA-6) NEW SP-WF-017 startup-time sentinel-asymmetry warning + gate-reject evidence includes `auto_fire_enabled`. 7 MINOR + 1 NIT findings land in §"Known Considerations" (non-blocking). |

## Provenance

This spec is an **extension**, not a replacement, of the binding v1 spec at `docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md` (12 design decisions SP-WF-001…012). The v1 spec is **ADOPTED** as authoritative. The companion v1 plan at `docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md` (T1-T12) is the implementation base — every Sprint 6 dev agent will reference both v1 docs verbatim. Adopt-mode (operator decision) skipped the ANALYZE phase since the SCOUT report at file:line precision was sufficient.

This extension adds three new tasks (T13, T14, T15) and four new design decisions (SP-WF-013…016) that close two specific gaps left open by v1:
1. The v1 spec §Operational Notes "Run trigger" paragraph says walkforward is "run on-demand via CLI" — Sprint 6 closes that manual-CLI gap (T13).
2. The v1 spec §Architecture only wires walkforward into `_evaluate_shadow_trading_gate`. The promotion gate's `_evaluate_production_gate` still has placeholder `pbo=None, oos_efficiency=None` at `src/platform/promotion.py:519-520` — Sprint 6 closes the production-gate asymmetry (T14).
3. The Sprint 6 close PR aggregates the `[Unreleased]` CHANGELOG into `[v0.36.0]`, bumps `src/version.py`, and appends operator-guide entries (T15) — mirroring the just-merged T16/v0.35.0 close PR at commit `8d06e8ca`.

## Operator Decisions Captured During INTERVIEW (verbatim)

The BRIEF preserves six operator decisions; reproduced here for traceability:

1. **Sprint 6 is the first post-Sprint-5 sprint.** Sprint 5 closed at v0.35.0 (commit `8d06e8ca`). Sprint 6 will close at v0.36.0.
2. **v1 spec is ADOPTED, not re-opened.** The 12 SP-WF decisions are locked. New design decisions are SP-WF-013 onward.
3. **Scheduler auto-fire is in scope** (T13). Manual CLI is the v1 default; auto-fire closes the operator-CLI gap.
4. **Production-gate walkforward check is in scope** (T14). The placeholder lines 519-520 in `promotion.py` will be closed symmetrically with the existing shadow_trading wiring.
5. **Single-strategy assumption is preserved.** No `shadow_trades.strategy_id` backfill in Sprint 6 (deferred per tracker #106). No per-strategy filtering changes.
6. **Walkforward stays on its own dashboard page.** No new KPI hero strip surfacing; the `/api/walkforward/runs` page is the only UI exposure.

## v1 Spec Decisions — Locked (One-Line Summaries)

| ID | Decision | Selected |
|----|----------|----------|
| SP-WF-001 | Window geometry | Fixed non-overlapping (R1 default: 5 windows, 2-year IS / 15-month OOS) |
| SP-WF-002 | IS/OOS split ratio | R1 canonical 2-year IS / 15-month OOS |
| SP-WF-003 | Refit cadence | Per OOS window (one refit per window boundary) |
| SP-WF-004 | Per-window statistical gate | Excess-Sharpe ≥ 0.3 (rf-adjusted) |
| SP-WF-005 | Cross-window acceptance | ≥4-of-5 windows must pass Criterion 2 |
| SP-WF-006 | Module location for new code | Extend `src/platform/rigor/walkforward_*.py` in-place |
| SP-WF-007 | Gate persistence target | Reuse existing `walkforward_results` table |
| SP-WF-008 | Vote contribution to `_decide` | AND-composed at orchestrator level (NOT a 6th vote) |
| SP-WF-009 | Sentinel default | `WALKFORWARD_GATE_ENABLED=true` (on by default, blocking) |
| SP-WF-010 | Corpus binding requirement | `corpus_id` required for all promotion-grade runs |
| SP-WF-011 | Shadow-portfolio bundling | Opt-in via `--with-shadow` CLI flag |
| SP-WF-012 | Embargo geometry | Trading days via `subtract_trading_days` (bilateral) |

All twelve remain in scope; the Sprint 6 plan preserves them verbatim as T1-T12.

---

## New Design Decisions (SP-WF-013 through SP-WF-016)

### SP-WF-013 — Scheduler auto-fire trigger semantics

**Decision.** Auto-fire is **dual-mechanism**:

1. **Synchronous post-persist hook** in `scripts/run_backtest.py:main()`. After `persist_backtest_result()` returns a `result_id` (line 92-94 in current file), invoke `auto_fire_walkforward(strategy_id, backtest_result_id, db_path)` — a NEW thin helper in `src/platform/walkforward_autofire.py` (≤120 lines). The helper:
   - Spawns a detached child via `subprocess.Popen([sys.executable, '-m', 'scripts.backtest.run_walkforward', '--strategy', strategy_id, '--backtest-result-id', result_id, '--corpus-id', <auto-resolved>, '--auto-fire'])`.
   - Returns immediately; the child writes to `walkforward_results` asynchronously.
   - On spawn failure, emits a `platform_events` row with `event_type='walkforward_auto_fire_spawn_failed'` and logs WARNING; **does NOT raise** (a walkforward auto-fire failure must never void a successful backtest persist).
   - Per-strategy concurrency: acquires a `filelock.FileLock` at `data/walkforward-{strategy_id}.lock` with a 1s non-blocking acquire; if locked, emits `event_type='walkforward_auto_fire_skipped_locked'` and returns without spawning.

2. **Periodic scheduler reconciler** registered in `src/scheduler/watch_handlers.py` (NOT `watch.py:_run_postclose_reconciliation` — that's a once-daily handler; mirror instead the existing hourly market-hours handler pattern e.g. sentiment-refresh at `watch.py:1673` which fires every 60 min during market hours). The handler `_run_walkforward_reconciler()` fires once per hour during market hours (1100, 1200, 1300, 1400, 1500 ET) via the existing `_safe_run`/done-flag pattern. Registration: append to `ALL_HANDLERS` in `watch_handlers.py` with the 5-tick schedule. The reconciler:
   - Scans `backtest_results` for rows created in the last 24h whose `(strategy_id, code_git_sha)` pair has no matching `walkforward_results` row.
   - For each missing pair, runs the same `auto_fire_walkforward` helper (idempotent — lockfile guard prevents double-fire).
   - Limit: max 3 fire attempts per `(strategy_id, code_git_sha)` per 24h, tracked via `platform_events` count query. After 3 failures, emits `event_type='walkforward_auto_fire_giveup'` and stops — operator must intervene via manual CLI.
   - Behind `WALKFORWARD_AUTOFIRE_ENABLED` env var (default `true` — explicit per SP-WF-009 sentinel-style discipline).

**Rationale.** The post-persist hook is the canonical trigger — it fires at the source-of-truth and has zero latency. The scheduler reconciler is a safety net for the case where the post-persist hook itself crashes after `result_id` is written (network blip, process kill, OOM). Both write to the same `auto_fire_walkforward` helper to keep the failure-handling code path unified.

**Alternatives considered.**
- *Pure scheduler-tick polling* — adds 60-min latency between backtest persist and walkforward fire. Rejected: operator runs ad-hoc backtests and expects same-day walkforward result for promotion decisions.
- *Event-bus pub/sub* — would require introducing a new event-bus abstraction. Rejected: YAGNI; the codebase has no event-bus today (`platform_events` is an append-only audit log, not a queue).
- *Synchronous in-process walkforward call* — would make `scripts/run_backtest.py` block for 10-60 min on the walkforward run. Rejected: backtest-CLI ergonomics; operator runs `python scripts/run_backtest.py --persist` and expects it to exit ≤ 5 min.
- *Single mechanism (post-persist hook only)* — leaves a gap when the parent script crashes after persist. Rejected: the safety-net reconciler is cheap and closes the gap.

**Falsifiability trigger.** Integration test: run `scripts/run_backtest.py --strategy <test> --persist` → assert within 5 minutes a `walkforward_results` row exists for that strategy with `derived_from_backtest_id = <new_result_id>`. Production-detectable via SQL: `SELECT br.result_id FROM backtest_results br LEFT JOIN walkforward_results wfr ON wfr.derived_from_backtest_id = br.result_id WHERE br.created_at > datetime('now', '-24 hours') AND wfr.run_id IS NULL` — should return zero rows after the reconciler runs at the next hourly tick. If non-zero rows persist > 24h, the wiring is broken.

---

### SP-WF-014 — Production-gate walkforward composition

**Decision.** `_evaluate_production_gate` in `src/platform/promotion.py:506-525` is extended to **call `_evaluate_walkforward_gate` symmetrically** with `_evaluate_shadow_trading_gate`. Composition:

```
production_gate_pass = (
    passes_dsr
    AND walkforward_pass    # NEW — was implicit None on lines 519-520
    AND methodology_pass
)
```

Key rules:
- **Same sentinel.** Honors `WALKFORWARD_GATE_ENABLED` (the T9 sentinel). No new env var.
- **Stricter no-row policy.** If `_evaluate_walkforward_gate` returns `(None, evidence)` (no walkforward row found), the production gate returns `False` — NOT the legacy fall-through that shadow_trading uses. Rationale: any strategy reaching `shadow_trading → production` must have already passed `backtested → shadow_trading`, which by the same composition required a walkforward PASS (or, for legacy strategies, a legacy `oos_efficiency` gate pass). The production transition is stricter — no fall-through to legacy gates.
- **PBO stays None for now.** Lines 519-520 currently set `pbo=None, oos_efficiency=None`. T14 replaces line 520 with the walkforward composition. Line 519 (`pbo=None`) stays — production-side PBO wiring is explicitly out of scope (deferred to a future sprint; the v1 spec does not cover it).
- **Evidence schema additions for production target.** `evidence` dict gains the same walkforward keys as shadow_trading: `walkforward_outcome_state`, `walkforward_status`, `walkforward_reason`, `walkforward_run_id`, `walkforward_pooled_sharpe`, `walkforward_pooled_mde`, `walkforward_heavy_tail_flag`. The dashboard `/api/promotion/proposals` read-route (if it surfaces production-target proposals) will see these keys uniformly.

**Rationale.** Symmetry with `_evaluate_shadow_trading_gate` is the simplest design and aligns with v1 spec SP-WF-008 (AND-composition at orchestrator level). The stricter no-row policy reflects the production lifecycle invariant: by the time a strategy is shadow_trading-eligible, it has either passed walkforward OR passed legacy `oos_efficiency` — either of which leaves a row that production-gate can read. A strategy reaching production with no walkforward row indicates a manual override or a broken lifecycle, both of which should block.

**Alternatives considered.**
- *Legacy fall-through (mirror shadow_trading exactly)* — would allow a strategy with no walkforward row but a legacy `oos_efficiency` row to promote to production. Rejected: production is a higher-stakes transition; we choose conservatism over symmetry with legacy.
- *New sentinel `PRODUCTION_WALKFORWARD_GATE_ENABLED`* — duplicates SP-WF-009 work. Rejected: one sentinel for both gates is operationally simpler. If the operator wants to bypass walkforward for production specifically, they set `WALKFORWARD_GATE_ENABLED=false` (which bypasses for both).
- *Add PBO+oos_efficiency wiring in same task* — scope creep beyond walkforward symmetry. Rejected: PBO production-gate wiring is a separate concern with its own decision history; T14 stays scoped to closing the placeholder lines for walkforward only.

**Falsifiability trigger.** Integration test: mock a `walkforward_results` row with `outcome_state='FAIL'`, mock a methodology gate PASS, mock DSR PASS. Call `check_promotion_gate(strategy_id, target_status='production', db_path)`. Assert `(False, evidence)` where `evidence['walkforward_outcome_state']='FAIL'`. Production-detectable: query `strategy_promotion_events` for rows with `to_status='production'` after Sprint 6 close — every row's `gate_result_json` must contain a `walkforward_outcome_state` key. Absence of that key on any post-Sprint-6 production promotion proves T14 didn't wire.

---

### SP-WF-015 — Sprint 6 framing & closeout

**Decision.** Sprint 6 is **PM-orchestrated** via `/arcis:code` with worktree-isolated dispatch. Wave structure follows the v1 plan's batches:

- **Wave 1 (parallel)**: T1, T2, T3 — independent foundation tasks (sentinel wiring, trading-day arithmetic, excess-Sharpe alignment).
- **Wave 2 (parallel)**: T4, T5, T6 — schema-registry additions + window-builder + VIX validator.
- **Wave 3 (sequential)**: T7 → T8 — schema migration depends on T4; runner integration depends on T5/T6.
- **Wave 4 (parallel)**: T9, T10 — promotion-gate sentinel guard + CLI/HTTP updates.
- **Wave 5 (parallel)**: T13, T14 — NEW Sprint 6 tasks. Both depend on T9 (sentinel) and T8 (runner integration). T13 is independent of T14 (different files).
- **Wave 6 (sequential)**: T11 → T15. T11 regression-lock suite first; T15 closeout PR last (depends on T1-T14 all merged).
- T12 from v1 plan (operator-guide append + CHANGELOG entry) is folded into T15's closeout PR — Sprint 6 has ONE closeout PR per the T16/v0.35.0 pattern, not a per-task operator-guide rewrite.

Version target: **v0.36.0**. Version bump in `src/version.py` from `v0.35.0` to `v0.36.0`. CHANGELOG aggregate dated to Sprint 6 close.

Test floor: must increase from current 5300 baseline by ≥20 tests (v1 plan §Acceptance estimates ~17 across T1-T11; T13 adds ~4; T14 adds ~3 ≈ 24 total).

**Rationale.** Worktree-isolated PM orchestration is required by CLAUDE.md "Parallel Agent Dispatch — Worktree Discipline" — Sprint 6 has 15 tasks crossing ~25 files, well above the single-developer threshold. The 6-wave structure preserves the v1 plan's batch dependencies verbatim while adding two new tasks (T13/T14) in a parallel wave behind T8/T9 dependencies.

**Alternatives considered.**
- *Two close PRs (split T15 into v0.36.0-rc1 + v0.36.0)* — adds release-engineering overhead for no benefit. Rejected.
- *Skip the closeout PR, let T12 ship in-task* — drifts the version bump out of band with the CHANGELOG aggregate, recreating the failure mode CLAUDE.md "Every PR updates CHANGELOG.md" rule guards against. Rejected.
- *Fold T12 into T15 entirely* (chosen — see plan).

**Falsifiability trigger.** After Sprint 6 close: `git tag --list v0.36.0` returns one tag pointing at the T15 merge SHA. `src/version.py` line 23 reads `VERSION = "v0.36.0"`. `CHANGELOG.md` line 3 (currently `## [Unreleased]`) is empty under the heading (entries pushed down to `[v0.36.0]`). `docs/operator-guide.md` has a new "Walk-Forward Validation Gate" subsection. If any of these four artifacts diverges, the close PR failed.

---

### SP-WF-016 — Falsifiability triggers for T13 + T14 (silent-failure detection)

**Decision.** Three production-detectable observation queries are documented in `docs/operator-guide.md` as part of T15 closeout:

1. **Orphan backtest detection.** SQL: `SELECT br.result_id, br.strategy_id, br.created_at FROM backtest_results br LEFT JOIN walkforward_results wfr ON wfr.derived_from_backtest_id = br.result_id WHERE br.created_at < datetime('now', '-2 hours') AND wfr.run_id IS NULL`. Expected: zero rows after the reconciler runs. Non-zero → T13 wiring is broken.

2. **Production promotion without walkforward evidence.** SQL: `SELECT spe.strategy_id, spe.timestamp, spe.gate_result_json FROM strategy_promotion_events spe WHERE spe.to_status = 'production' AND spe.timestamp > '2026-05-13' AND json_extract(spe.gate_result_json, '$.walkforward_outcome_state') IS NULL`. Expected: zero rows post-Sprint 6. Non-zero → T14 wiring is broken.

3. **Auto-fire failure rate.** SQL: `SELECT COUNT(*) FROM platform_events WHERE event_type IN ('walkforward_auto_fire_spawn_failed', 'walkforward_auto_fire_giveup') AND timestamp > datetime('now', '-7 days')`. Expected: < 5% of total auto-fires in same window. Higher → T13 has a systemic failure (likely env-drift between operator machine and worktree, or corpus auto-resolution broken). Add to weekly health digest.

All three queries are added to `docs/operator-guide.md` §Walk-Forward Validation Gate by T15.

**Rationale.** Silent-failure modes for scheduler triggers are the highest-risk class — they pass tests in worktree (where the trigger fires synchronously) but fail in production (where the child process dies post-fork). Per CLAUDE.md "feedback_worktree_env_drift" memory: env-drift incidents have happened before (PR #711→#729). T13's child-process spawn is particularly susceptible. Three queries with concrete thresholds let the operator detect drift without reading code.

**Alternatives considered.**
- *Heartbeat/health-check endpoint* — would add HTTP-route surface. Rejected: heavier than three SQL queries an operator can paste into a SQLite REPL.
- *Telegram alert on auto-fire failure* — would require modifying the notification routing layer. Rejected: out of Sprint 6 scope; the SQL queries provide the visibility, and the operator can opt in to alerts in a future sprint.
- *Don't document falsifiability* — operator memory "feedback_review_sibling_search" requires falsifiability claims be testable. Rejected.

**Falsifiability trigger.** Manual operator-run of all three queries 24 hours after T15 merge:
1. Query 1: zero rows → T13 wiring sound.
2. Query 2: requires a production promotion to happen post-Sprint-6 to test; first-strategy production promotion will validate.
3. Query 3: requires ≥10 auto-fires to evaluate stably; reassess at first weekly digest.

If any query returns a non-zero result outside expected bounds, file a follow-up tracker as the first Sprint 7 priority.

---

## Architecture: Post-Sprint-6 Walk-Forward Control Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ Operator runs:                                                       │
│   python scripts/run_backtest.py --strategy X --start ... --persist  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
           ┌───────────────────────────────────────────┐
           │ scripts/run_backtest.py:main()             │
           │  1. run_backtest(cfg) → result              │
           │  2. persist_backtest_result() → result_id   │ ◄── current code (line 92-94)
           │  3. auto_fire_walkforward(strategy_id,      │ ◄── NEW (T13)
           │       result_id, db_path)                   │
           └───────────────────────────────────────────┘
                                │
                                ▼
           ┌───────────────────────────────────────────┐
           │ src/platform/walkforward_autofire.py        │ ◄── NEW FILE (T13)
           │  auto_fire_walkforward():                   │
           │   - acquires data/walkforward-{sid}.lock    │
           │   - subprocess.Popen([sys.executable,       │
           │     '-m', 'scripts.backtest.run_walkforward'│
           │     '--strategy', sid,                      │
           │     '--backtest-result-id', rid,            │
           │     '--corpus-id', <auto>,                  │
           │     '--auto-fire'])                         │
           │   - returns immediately (child runs async)  │
           └───────────────────────────────────────────┘
                                │
                  ┌─────────────┴────────────┐
                  ▼                          ▼
   ┌────────────────────────┐   ┌────────────────────────────────┐
   │ Child: walkforward run  │   │ Parent: returns from main()    │
   │ (existing v1 pipeline)  │   │ exit 0                          │
   │ writes walkforward_results│   └────────────────────────────────┘
   └────────────────────────┘

  AND in parallel:

┌─────────────────────────────────────────────────────────────────────┐
│ src/scheduler/watch.py — every hour during market open               │
│  _run_walkforward_reconciler():                                       │
│   1. SELECT FROM backtest_results LEFT JOIN walkforward_results       │
│      WHERE wfr.run_id IS NULL AND br.created_at > -24h                │
│   2. For each missing pair, call auto_fire_walkforward() (idempotent) │
│   3. Cap at 3 attempts per (strategy_id, code_git_sha) per 24h        │
└─────────────────────────────────────────────────────────────────────┘

  AND when operator/cron evaluates promotion:

┌─────────────────────────────────────────────────────────────────────┐
│ src/platform/promotion.py:check_promotion_gate(strategy_id, target)   │
│                                                                       │
│ target='shadow_trading' →                                             │
│   _evaluate_shadow_trading_gate() ◄── EXISTING (v1)                  │
│     _evaluate_dsr_evidence()                                          │
│     _evaluate_walkforward_gate() ◄── reads walkforward_results       │
│     _evaluate_strategy_methodology_gate()                             │
│     return passes_dsr AND wf_pass AND mg_passes, evidence             │
│                                                                       │
│ target='production' →                                                 │
│   _evaluate_production_gate() ◄── EXTENDED (T14)                     │
│     _evaluate_dsr_evidence()                                          │
│     _evaluate_walkforward_gate() ◄── NEW call (T14)                  │
│     _evaluate_strategy_methodology_gate()                             │
│     return passes_dsr AND wf_pass AND mg_passes, evidence             │
│                                                                       │
│ Sentinel (WALKFORWARD_GATE_ENABLED, from T9) honored in BOTH paths.   │
└─────────────────────────────────────────────────────────────────────┘
```

## File Inventory (Sprint 6)

| File | Status | Owner Task | Role |
|------|--------|------------|------|
| `src/platform/promotion.py` | EXTEND | T1, T9, T14 | Sentinel guard + production-gate symmetry |
| `src/platform/rigor/walkforward_config.py` | EXTEND | T3, T5 | Excess-Sharpe field + WindowBuilder + corpus_id |
| `src/platform/rigor/walkforward_metrics.py` | EXTEND | T3 | Excess-Sharpe per-window gate |
| `src/platform/rigor/walkforward_runner.py` | EXTEND | T8 | Wire T5/T6 outputs; gate_version field |
| `src/platform/rigor/walkforward_power.py` | EXTEND | T6 | VIX coverage validator |
| `src/platform/walkforward_autofire.py` | NEW | T13 | Auto-fire helper (~120 LOC) |
| `src/schema/registry.py` | EXTEND | T4 | `excess_sharpe_min_used` + `gate_version` columns |
| `src/scheduler/watch.py` | EXTEND | T13 | `_run_walkforward_reconciler` method (~80 LOC) |
| `src/evaluation/walkforward.py` | EXTEND | T2 | Trading-day arithmetic migration |
| `src/api/cloud_routes/walkforward.py` | EXTEND | T10 | Read-route includes new columns |
| `scripts/backtest/run_walkforward.py` | EXTEND | T10, T13 | `--corpus-id`, `--excess-sharpe-min`, `--backtest-result-id`, `--auto-fire` flags |
| `scripts/run_backtest.py` | EXTEND | T13 | Post-persist hook calls `auto_fire_walkforward` |
| `tests/platform/test_promotion.py` | EXTEND | T1, T9, T14 | 9 new tests across 3 tasks |
| `tests/evaluation/test_walkforward.py` | EXTEND | T2 | 2 new trading-day tests |
| `tests/platform/rigor/test_walkforward_metrics.py` | EXTEND | T3 | 3 new excess-Sharpe tests |
| `tests/test_schema.py` | EXTEND | T4 | 2 new column-existence tests |
| `tests/platform/rigor/test_walkforward_config.py` | EXTEND | T5 | 4 new window-builder tests |
| `tests/platform/rigor/test_walkforward_power.py` | EXTEND | T6 | 4 new VIX-coverage tests |
| `tests/platform/rigor/test_walkforward_runner.py` | EXTEND | T8 | 4 new runner-integration tests |
| `tests/platform/rigor/test_walkforward_regression_lock.py` | NEW | T11 | 4 regression locks (≤80 LOC) |
| `tests/scripts/test_run_walkforward_cli.py` | NEW | T10 | 2 new CLI flag tests |
| `tests/api/test_walkforward_route.py` | NEW or EXTEND | T10 | 1 new field test |
| `tests/platform/test_walkforward_autofire.py` | NEW | T13 | 5 new autofire tests (lock, spawn, failure, reconciler, giveup) |
| `tests/scheduler/test_walkforward_reconciler.py` | NEW | T13 | 3 new reconciler tests |
| `config/known_violations.json` | EXTEND (conditional) | T8 | Runner LOC waiver update if needed |
| `docs/operator-guide.md` | EXTEND | T15 | Sprint 6 §Walk-Forward Validation Gate section |
| `CHANGELOG.md` | EXTEND | T1-T14 (per task) + T15 (aggregate to v0.36.0) | Per-task `[Unreleased]` entries; T15 aggregates |
| `src/version.py` | EXTEND | T15 | v0.35.0 → v0.36.0 |
| `docs/audits/2026-05-11-stage1-completion/*.md` | READ-ONLY | all | Source-of-truth references |
| `src/platform/rigor/walkforward.py` (legacy) | READ-ONLY | all | Pardo legacy — frozen |
| `src/evaluation/walkforward.py` (anchored) | READ-ONLY EXCEPT T2 | T2 only touches the trading-day helper | Stage-1 anchored harness — frozen except for T2 helper migration |

## Error Handling

**Auto-fire spawn failure (T13).**
`subprocess.Popen` raises `OSError` or `FileNotFoundError` on bad executable path. `auto_fire_walkforward` catches, logs `WARNING`, emits `platform_events` row with `event_type='walkforward_auto_fire_spawn_failed'` and payload `{'strategy_id', 'backtest_result_id', 'error_class', 'error_msg'}`. **Does NOT raise** — backtest persist succeeded; walkforward retry is the reconciler's job.

**Auto-fire child crash (T13).**
Child process exits non-zero. The reconciler (running hourly) detects the missing `walkforward_results` row and re-fires (subject to the 3-attempt cap). Operator sees the platform_events trail.

**Lockfile contention (T13).**
`filelock.FileLock(path).acquire(timeout=1)` raises `Timeout` if another auto-fire is in-flight. Caught silently; emits `event_type='walkforward_auto_fire_skipped_locked'`. The reconciler will re-check at the next hour.

**Production gate no-row (T14).**
If `_evaluate_walkforward_gate` returns `(None, evidence)` for production target, `_evaluate_production_gate` returns `(False, evidence)` with `evidence['error'] = 'production_gate_requires_walkforward_row'`. The operator must trigger an auto-fire (or wait for the reconciler) before retrying the promotion.

**Production gate sentinel disabled (T14).**
If `WALKFORWARD_GATE_ENABLED=false`, the production gate skips the walkforward check entirely and reverts to the v0.35.0 composition (`passes_dsr AND mg_passes`). This is symmetric with T1's sentinel handling in `_evaluate_walkforward_gate` and inherits the same operator override path.

**Reconciler error (T13).**
If the reconciler SQL or auto-fire helper raises inside `_run_walkforward_reconciler`, `_safe_run` (existing pattern at `watch.py:2115`) catches and returns `False`. The done-flag is NOT set; next hour retries. Mirrors existing `_run_postclose_reconciliation` failure handling.

## Testing Strategy

**T13 unit tests** (new file `tests/platform/test_walkforward_autofire.py`, ≤120 lines):
- `test_auto_fire_spawns_child_process` — mock `subprocess.Popen`, call helper, assert Popen called with expected args.
- `test_auto_fire_emits_platform_event_on_spawn_failure` — patch Popen to raise OSError; assert `platform_events` row created with `event_type='walkforward_auto_fire_spawn_failed'`; helper does NOT raise.
- `test_auto_fire_skips_when_locked` — pre-acquire lockfile; call helper; assert no Popen call, `event_type='walkforward_auto_fire_skipped_locked'` emitted.
- `test_auto_fire_does_not_raise_on_any_failure` — fuzz with 3 different exception types from Popen; helper always returns cleanly.
- `test_auto_fire_releases_lock_after_spawn` — confirm lock released; second call succeeds.

**T13 reconciler tests** (new file `tests/scheduler/test_walkforward_reconciler.py`, ≤80 lines):
- `test_reconciler_finds_orphan_backtest` — insert `backtest_results` row without matching `walkforward_results`; call reconciler; assert auto_fire called for it.
- `test_reconciler_skips_paired_backtest` — insert paired rows; call reconciler; assert no auto_fire call.
- `test_reconciler_caps_at_three_attempts` — pre-seed `platform_events` with 3 spawn-failed entries for a strategy; call reconciler; assert no new auto_fire, emits `walkforward_auto_fire_giveup`.

**T14 production-gate tests** (extend `tests/platform/test_promotion.py`, ≤60 net lines added):
- `test_production_gate_passes_with_walkforward_pass` — mock WF PASS + DSR PASS + MG PASS → returns `(True, evidence)`; evidence has `walkforward_outcome_state='PASS'`.
- `test_production_gate_fails_with_walkforward_fail` — mock WF FAIL + DSR PASS + MG PASS → returns `(False, evidence)`.
- `test_production_gate_fails_with_walkforward_inconclusive` — mock WF INCONCLUSIVE; assert `(False, evidence)` with error key.
- `test_production_gate_fails_when_no_walkforward_row` — mock `_fetch_latest_walkforward_outcome` returns None; production gate returns False (NOT legacy fall-through). evidence['error'] = 'production_gate_requires_walkforward_row'.
- `test_production_gate_skips_walkforward_when_sentinel_disabled` — env `WALKFORWARD_GATE_ENABLED=false`; production gate composes only DSR+MG (v0.35.0 behavior preserved as bypass).

**T15 closeout verification** (no new tests; structural):
- `python -m pytest tests/ -q` test count ≥ 5345 (5300 floor + ~45 net adds across T1-T14: T1=3, T2=2, T3=3, T4=2, T5=4, T6=4, T8=4, T9=3, T10=3, T11=4, T13=8, T14=5. Reviewer-tightened from initial 5320 target — a 25-test silent-drop would have slipped past the looser floor).
- `git tag --list v0.36.0` returns one tag (operator runs the tag command — pattern from prior closeouts).
- `python -c "from src.version import VERSION; print(VERSION)"` outputs `v0.36.0`.
- `scripts/verify_docs.py` zero drift.
- `python -m pytest tests/test_repo_structure.py -v` zero new violations.

All tests use `unittest.mock.patch` for SQLite and `subprocess.Popen`; no live DB, no real subprocess spawns. Hermetic.

## Falsifiability Triggers (Sprint 6 holistic)

In addition to the per-decision triggers in SP-WF-013…016, these spec-level triggers void Sprint 6 if observed:

1. **Auto-fire latency > 5 min.** If `auto_fire_walkforward` takes more than 5 min between backtest persist and `walkforward_results` row creation, the design assumption ("same-day walkforward result for promotion decisions") is broken. Production-detectable: SQL `SELECT AVG(julianday(wfr.created_at) - julianday(br.created_at)) * 86400 FROM ...` — should be < 300 seconds.
2. **Reconciler false-positive re-fire.** If reconciler re-fires a strategy that already has a `walkforward_results` row, the join predicate is broken. Detectable via duplicate-row SQL.
3. **Production gate accepts a strategy without walkforward.** Per SP-WF-016 query 2.
4. **Sentinel default flipped silently.** Env-drift: if `WALKFORWARD_GATE_ENABLED` is unset on operator machine and the gate behaves as `false`, the default-true contract is broken. Detectable: `os.environ.get('WALKFORWARD_GATE_ENABLED', 'true')` returning `'false'` in production logs.
5. **CHANGELOG drift after T15.** `git log v0.35.0..v0.36.0 -- CHANGELOG.md` should show exactly one commit (the T15 close). More than one indicates a per-task drift that T15 missed.

Any of these voids the design; first Sprint 7 task is corrective spec-redraft.

## Do-Not-Do (this sprint)

The following are explicitly **out of scope for Sprint 6**; any agent proposing them must escalate to the operator:

1. **KPI hero strip walkforward surfacing.** No new fields on `/api/kpis`. Walkforward stays on `/api/walkforward/runs` page only. Per operator decision in BRIEF.
2. **Per-strategy filtering (`shadow_trades.strategy_id` backfill).** Single-strategy assumption preserved. Tracker `#106` covers this; not Sprint 6.
3. **Cadence-based walkforward firing.** No Sunday-weekly cron, no weekly digest. T13 covers post-backtest auto-fire only.
4. **Promote-time defensive walkforward.** No firing inside `promote()` — gate reads existing rows only.
5. **Anchored-expanding harness migration** (`src/evaluation/walkforward.py`). Frozen READ-ONLY except for T2's trading-day helper extraction.
6. **Other roadmap-deferred items**: trackers #97, #105, #107, #112, #114.
7. **PBO production-gate wiring.** Line 519 `evidence['pbo'] = None` stays. T14 only closes the walkforward placeholder (line 520).
8. **New event-bus abstraction.** No new event/queue infrastructure. `platform_events` (existing table) is the only audit trail.
9. **New top-level walkforward module.** SP-WF-006 locks the module location at `src/platform/rigor/`. T13's `walkforward_autofire.py` lives one directory up at `src/platform/` because it bridges scheduler + rigor + promotion concerns; it is NOT a fork of the rigor module.

## Operational Notes

**Operator override path (Sprint 6, unchanged from v1).**
Set `WALKFORWARD_GATE_ENABLED=false` in `.env` before NSSM restart to bypass the gate for both shadow_trading and production transitions. Set `WALKFORWARD_AUTOFIRE_ENABLED=false` to disable T13 auto-fire (the manual CLI `python scripts/backtest/run_walkforward.py --strategy X` still works). Both are escape-hatches; default is `true`.

**Post-Sprint-6 SQL queries** (also written to `docs/operator-guide.md` by T15):
```sql
-- Orphan backtest check (SP-WF-016 query 1)
SELECT br.result_id, br.strategy_id, br.created_at
FROM backtest_results br
LEFT JOIN walkforward_results wfr ON wfr.derived_from_backtest_id = br.result_id
WHERE br.created_at < datetime('now', '-2 hours')
  AND wfr.run_id IS NULL;

-- Production-promotion walkforward-evidence check (SP-WF-016 query 2)
SELECT spe.strategy_id, spe.timestamp
FROM strategy_promotion_events spe
WHERE spe.to_status = 'production'
  AND spe.timestamp > '2026-05-13'
  AND json_extract(spe.gate_result_json, '$.walkforward_outcome_state') IS NULL;

-- Auto-fire failure-rate check (SP-WF-016 query 3)
SELECT event_type, COUNT(*)
FROM platform_events
WHERE event_type LIKE 'walkforward_auto_fire%'
  AND timestamp > datetime('now', '-7 days')
GROUP BY event_type;
```

**Provenance traceability.** Every Sprint 6 PR must reference both the v1 spec and v1 plan paths in its description, and link to the closing of relevant placeholders (e.g., T14 PR description: "Closes the `pbo=None, oos_efficiency=None` placeholder at `src/platform/promotion.py:519-520` introduced by Sprint 2 T2"). T15 aggregates these references into the v0.36.0 CHANGELOG.

---

## Feasibility Resolutions (post-Architect, v1.1)

The Feasibility Reviewer (2026-05-13) flagged 1 CRITICAL + 3 MAJOR + 3 MINOR findings against v1.0. All seven were resolved without re-dispatching the Architect — the findings carried concrete remediation text with file:line refs, applied here as targeted patches. Each row below documents the original finding, the patch, and where the patch landed in the spec/plan.

| # | Severity | Finding | Patch | Location |
|---|----------|---------|-------|----------|
| 1 | CRITICAL | `derived_from_backtest_id` column does NOT exist on `walkforward_results` — but T13 reconciler SQL + SP-WF-016 falsifiability queries reference it | Absorbed into **T4 scope** (schema column-additive change). T4 already adds new outcome columns; column `derived_from_backtest_id TEXT NULL` joins that list. Operator's "no NEW tables" constraint preserved — column-additive is in scope. Runner (T8) populates this column when invoked via auto-fire (T13). | T4 description + scope_fence (plan); spec §Data Model |
| 2 | MAJOR | `filelock>=3.0,<4.0` not in any requirements file. T13 needs it for per-strategy concurrency. | T13 scope_fence extended: must add `filelock>=3.0,<4.0` to `requirements.txt` AND a CLAUDE.md `New Dependencies` section bump (mirror the `pandas_market_calendars` precedent). Test that runs in fresh worktree env validates the dep is reachable. | T13 description + scope_fence; CLAUDE.md edit in T15 |
| 3 | MAJOR | "Auto-resolved corpus-id" never defined — T13's subprocess spawn cannot be built without the contract. | T13 scope extended: implement `_resolve_corpus_id_for_strategy(strategy_id, db_path) -> str \| None` helper in `src/platform/walkforward_autofire.py`. Reads `strategy_registry.corpus_id` (or fallback to `corpus_metadata` latest-per-strategy lookup). On null: emit `event_type='walkforward_auto_fire_skipped_no_corpus'` and return without spawning (corpus is REQUIRED per SP-WF-010, so absence is fail-loud not silent-skip). | T13 description + scope_fence |
| 4 | MAJOR | `WALKFORWARD_AUTOFIRE_ENABLED` net-new env var lacks the docstring registration discipline that `METHODOLOGY_GATE_ENABLED` uses at `promotion.py:12`. | T13 scope_fence extended: new file `src/platform/walkforward_autofire.py` module docstring MUST include `Config keys: WALKFORWARD_AUTOFIRE_ENABLED (env, default true).` line, mirroring `promotion.py:12` discipline. Env-read pattern matches `promotion.py:286`. | T13 scope_fence |
| 5 | MINOR | Spec mirror reference to `_run_postclose_reconciliation` (watch.py:2176) is wrong — that's a once-daily handler. T13 needs once-per-hour during market hours. | Architecture section corrected — reconciler registers via `src/scheduler/watch_handlers.py` `ALL_HANDLERS` list with the 5-tick (1100/1200/1300/1400/1500 ET) schedule. Mirror the hourly sentiment-refresh handler pattern instead (existing precedent at `watch.py:1673`). | Architecture section (this spec); T13 description (plan) |
| 6 | MINOR | platform_events retry-count SQL not explicit about json_extract on payload_json | Spec §Error Handling clarified: `SELECT COUNT(*) FROM platform_events WHERE event_type LIKE 'walkforward_auto_fire_spawn_failed' AND json_extract(payload_json, '$.strategy_id') = ? AND json_extract(payload_json, '$.code_git_sha') = ? AND created_at > datetime('now', '-24 hours')`. Added test `test_reconciler_caps_at_three_attempts` to T13 test_strategy. | §Error Handling (this spec); T13 test_strategy (plan) |
| 7 | MINOR | T15 test-count target 5320 is too lax — undercounts the ~45 net adds across T1-T14 | Tightened: spec §Testing Strategy now says `≥ 5345 (5300 floor + ~45 net adds: T1=3, T2=2, T3=3, T4=2, T5=4, T6=4, T8=4, T9=3, T10=3, T11=4, T13=8, T14=5)`. A 25-test silent-drop would now fail-loud instead of slipping past the 5320 buffer. | §Testing Strategy (this spec); T15 acceptance criterion (plan) |

**Director's note (procedural):** Feasibility findings #1, #2, #3, #4 are STRUCTURAL — they change the impl contract. Findings #5, #6, #7 are EDITORIAL — they sharpen existing claims. All 7 are integrated below into the body of the spec; this table is the post-Feasibility traceability ledger so Devil's Advocate can verify all findings landed without re-reviewing the diff against v1.0.

---

## Devil's Advocate Resolutions (post-DA, v1.2)

Devil's Advocate review (2026-05-13) flagged 6 MAJOR + 7 MINOR + 1 NIT issues against v1.1. Per skill protocol (CONCERNS verdict), MAJOR issues are addressed via spec patches; MINOR + NIT issues land in §"Known Considerations" below (do not block deploy). All 6 MAJOR patches:

| # | Severity | Finding | Patch | Location |
|---|----------|---------|-------|----------|
| DA-1 | MAJOR | Promotion-gate STALENESS unaddressed — walkforward verdict keyed to `code_git_sha` snapshot; stale evidence accepted indefinitely. A strategy at production candidacy months later might pass on outdated code. | **SP-WF-014 extended:** `_evaluate_walkforward_gate` (production path) MUST require BOTH: (a) `walkforward_results.code_git_sha == current strategy code_git_sha` (strict sha-match) AND (b) `walkforward_results.created_at > datetime('now', '-30 days')` (freshness cap). On staleness or sha-mismatch: return `passes=False` with `evidence['walkforward_stale']=True` and `evidence['walkforward_stale_reason']` ('code_git_sha mismatch' \| 'older than 30 days'). Add new test `test_production_gate_rejects_stale_walkforward_code_git_sha` + `test_production_gate_rejects_walkforward_older_than_30_days`. Extend SP-WF-016 query 2 with the staleness filter. | T14 description + scope_fence; SP-WF-014 body |
| DA-2 | MAJOR | `walkforward_auto_fire_skipped_no_corpus` event creates unbounded retry loop — cap SQL filters only `'spawn_failed'`, so no-corpus path retries every hour forever. | **T13 retry-cap SQL extended:** Use explicit IN list `WHERE event_type IN ('walkforward_auto_fire_spawn_failed', 'walkforward_auto_fire_skipped_no_corpus', 'walkforward_auto_fire_timeout')`. Each of these increments the 3-attempt cap. After 3 attempts in 24h, emit `walkforward_auto_fire_giveup` and stop. Add test `test_reconciler_caps_at_three_no_corpus_attempts` to T13 test_strategy. | T13 description + test_strategy; SP-WF-013 body |
| DA-3 | MAJOR | Subprocess timeout unspecified — hung walkforward child becomes zombie + holds lock indefinitely + reconciler silenced by lockfile. | **SP-WF-013 extended:** Auto-fire spawns subprocess with 90-min wallclock timeout (well above 10-60 min normal range). Implementation: parent watchdog via `proc.wait(timeout=5400)` followed by `TimeoutExpired` catch → `proc.kill()` → lockfile release → emit `event_type='walkforward_auto_fire_timeout'` (cap-eligible, see DA-2). Add test `test_auto_fire_kills_hung_child_after_90_min_timeout`. | T13 description + test_strategy; SP-WF-013 body |
| DA-4 | MAJOR | Manual CLI bypasses lockfile — operator running CLI while auto-fire is in-flight produces duplicate walkforward_results rows. | **T13 scope extended:** `scripts/backtest/run_walkforward.py` main() MUST acquire `data/walkforward-{strategy_id}.lock` via the same `filelock.FileLock(...).acquire(timeout=1)` pattern as auto-fire. Add `--force` CLI flag to bypass for operator emergencies (with WARNING log emitted). Test `test_manual_cli_acquires_same_lock_as_auto_fire`. Document the operator workflow in operator-guide via T15: "before manual CLI, check `Get-ChildItem data/walkforward-*.lock`". | T13 scope_fence; SP-WF-013 body |
| DA-5 | MAJOR | Promotion-event audit-trail depends on unstated precondition — `promote()` must persist full evidence dict to `gate_result_json` for SP-WF-016 query 2 to work. | **T14 scope extended:** Add explicit verification test `test_promote_persists_walkforward_keys_in_gate_result_json` that calls `promote(strategy_id='test', target='production', ...)` end-to-end and asserts `strategy_promotion_events.gate_result_json` contains `walkforward_outcome_state`, `walkforward_status`, `walkforward_run_id`. If the test fails, it's a precondition violation that must be addressed BEFORE T14 ships (escalate to operator for scope expansion). | T14 description + test_strategy; SP-WF-014 body |
| DA-6 | MAJOR | Sentinel-combination deadlock — GATE=true + AUTOFIRE=false creates hard-stop on promotion attempts; spec mentioned casually but never surfaced operationally. | **NEW SP-WF-017** — Sentinel-consistency check at startup. Add to `python -m src.main startup`: when WALKFORWARD_GATE_ENABLED=true AND WALKFORWARD_AUTOFIRE_ENABLED=false (asymmetric default), emit warning to Telegram + log: `[SENTINEL_ASYMMETRY] WALKFORWARD_GATE=on but AUTOFIRE=off — production gate will fail unless manual walkforward runs are kept current`. ALSO: when `_evaluate_walkforward_gate` returns `passes=False` due to no-row, include `evidence['auto_fire_enabled']` so operator sees both pieces of state at gate-reject time. Add test `test_startup_warns_on_sentinel_asymmetry`. | NEW SP-WF-017 design decision; T13 + T14 scope_fences; `src/main.py` startup path |

**Director's note:** All 6 MAJOR patches preserve the locked v1 SP-WF-001…012 decisions. DA-6 adds one new design decision (SP-WF-017 sentinel-consistency check) that did not exist in v1.0 — this is operator-visible at OUTPUT time. The 7 MINOR + 1 NIT findings land in §"Known Considerations" below.

## Known Considerations (post-DA, non-blocking)

These were flagged by Devil's Advocate as worth tracking but do not block the v0.36.0 release. Operator may choose to address in Sprint 6 follow-up PRs or defer to post-Sprint-6.

1. **MINOR — Auto-fire `--with-shadow` behavior implicit.** SP-WF-013 auto-fire path does NOT pass `--with-shadow`; manual CLI is the only path for shadow-portfolio bundling. Operator-guide (via T15) should explicitly state this so operators don't expect shadow analysis from auto-fire.

2. **MINOR — Reconciler half-day market schedule.** Reconciler ticks (1100/1200/1300/1400/1500 ET) fire outside market hours on ~9 NYSE early-close days per year. If the mirrored sentiment-refresh handler at `watch.py:1673` is half-day aware, reconciler inherits it; if not, file a follow-up tracker.

3. **MINOR — Test vacuity risk on 3 tests.** Lock-release test, reconciler-skips-paired test, and sentinel-bypass test could PASS via vacuous paths. Add positive existence assertions and byte-identical evidence-dict snapshot comparison per DA finding #11.

4. **MINOR — SP-WF-016 falsifiability queries lack action playbooks.** Each query says "non-zero → wiring broken" but doesn't tell operator what to do. T15 operator-guide append should include: detection threshold, probable cause, immediate action, escalation timer per query.

5. **MINOR — Rollback path for runaway auto-fire is shallow.** Setting env=false + NSSM restart doesn't kill in-flight runaway subprocesses. T15 operator-guide append should include: `taskkill /F /IM python.exe /FI "COMMANDLINE eq *run_walkforward*"` + stale-lock cleanup + then NSSM restart.

6. **MINOR — T13 LOC budget may understate scope.** With v1.1 + v1.2 additions, `walkforward_autofire.py` may exceed 120 LOC. Raise ceiling to 180 LOC in scope_fence, with rationale documented.

7. **MINOR — Multi-day NSSM downtime gap.** If watch loop is down >24h, backtests in the first 24h of downtime become permanent orphans (reconciler's 24h window excludes them). T15 operator-guide append should include: post-downtime orphan-inventory SQL query for operator to run manually.

8. **NIT — Hermetic test policy vs filelock import.** Feasibility patch #2 + DA's nit — add top-of-test-file `import filelock` so pytest collection fails at import-time if dep missing; no separate test needed. T13 test_strategy should clarify.
