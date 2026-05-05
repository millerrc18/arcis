# Methodology Gate Wiring — Design Spec v3

## Revision History

- **v3 (this revision)** — Addresses Devil's Advocate review `a161731b7f88ceabb` (3 CRITICAL + 5 MAJOR findings):
  1. CLI now calls `platform.promotion.promote()` (no synthetic-outcome bypass); justification ≥40 chars validated client-side then re-validated by promote().
  2. New task explicitly modifies `src/platform/promotion.py` to AND-compose methodology gate into `check_promotion_gate`.
  3. Cadence pinned to watch.py 16:35 ET daily slot; trainer.py is NOT a gate-firing site (only an inputs-update site with a pre-existing abstention bug fix).
  4. New `promotion_gate_decisions` table dropped; persistence uses existing `strategy_promotion_events.gate_result_json` with two new `triggered_by` sentinel values (`gate_proposal`, `operator_confirm`).
  5. `is_fully_instrumented` filter explicitly applied to gate input.
  6. `threshold_used` (`4_of_5` | `4_of_4_no_white_rc`) persisted as a JSON key in `gate_result_json`.
  7. AND-composition with existing walkforward+DSR+PBO checks made explicit.
  8. Test plan reframed as named behavior-coverage list, not a count target.
- v2 — initial integration-style spec (drifted from Phase 3+4 commitments on the 8 axes above).
- v1 — separate-gate sketch (rejected at INTERVIEW Phase 3).

## 1. Overview

Wires the existing 4-of-5 methodology toolkit (`src/methods/promotion_gate.py`) into the production strategy promotion path so that a promotion candidate cannot advance from `shadow_trading` or `backtested` to `live` without methodology-gate concurrence. The gate currently exists as a shelf module — fully tested in isolation but never invoked by `src/platform/promotion.py::check_promotion_gate`. After this change it becomes part of the AND-composed promotion check.

### 1.1 Cadence — pinned

**The gate fires daily at 16:35 ET via the watch.py scheduler, NOT via trainer.py training-cycle checkpoints.** The trainer fires on event-driven training cycles (irregular, sometimes multiple per day). The methodology gate fires exactly once per trading day, immediately after the post-close reconciliation slot. trainer.py is touched by this work only to fix its own pre-existing abstention bug for model-version gating (a separate concern that surfaces during daily-gate runs because the daily gate consumes trainer-emitted artifacts).

### 1.2 Composition rule — pinned

**The methodology gate is AND-composed with the existing walkforward + DSR + PBO checks already in `check_promotion_gate`.** A strategy is promotable only if the methodology gate returns `decision='promote'` AND every existing check returns True. Composition occurs in `src/platform/promotion.py::check_promotion_gate` (line 331) via a new `_evaluate_strategy_methodology_gate(strategy_id, db_path) -> tuple[bool, dict]` helper, AND-composed into `_evaluate_shadow_trading_gate` (line 246) and `_evaluate_production_gate` (line 318). Defer / abstain outcomes from the methodology side do NOT short-circuit existing checks — they evaluate to False on the gate side, blocking promotion until operator confirmation.

### 1.3 Outcome semantics

- `decision='promote'` (4-of-5 votes pass) — methodology side returns True; promotion proceeds if other gates also pass.
- `decision='reject'` (≥2 votes fail) — methodology side returns False; promotion blocked. NOT overridable via the CLI flow.
- `decision='defer'` (no quorum, e.g. abstentions push tally below threshold) — methodology side returns False; operator MAY confirm-promotion via CLI with a justification note ≥40 chars. The CLI flow re-fires the gate server-side and writes a real audit transition row.

### 1.4 Out of scope

- Any new database tables (Phase 4 finding: schema is sufficient).
- Any change to the 4-of-5 voting math itself (`promotion_gate.py` is not modified).
- Frontend dashboard implementation (only the read-side KPI is surfaced; full UI is deferred).

## 2. Architecture

### 2.1 Module map

```
src/scheduler/watch.py            (firing site: daily 16:35 ET)
  └── src/platform/promotion.py   (NEW: integration site; check_promotion_gate AND-composes)
        ├── src/methods/promotion_gate.py        (existing 4-of-5 voting; unchanged)
        ├── src/analytics/instrumentation_filter.py  (input filter: is_fully_instrumented)
        └── src/schema/registry.py:2106-2128     (persistence: strategy_promotion_events)

src/cli/...                       (operator confirm-promotion command — thin front-end to promote())
src/training/trainer.py           (pre-existing abstention-bug fix, NOT a gate-firing site)
```

### 2.2 Data flow

1. **16:35 ET daily**: `WatchLoop._daily_loop()` enters the post-close-reconcile slot (lines 1615-1623). Immediately after `_postclose_reconcile_done = True`, a new block checks `_strategy_gate_done`; if False, calls `run_daily_gate_for_all_active_strategies(db_path, notify=...)` (late-imported from `src.platform.promotion`).
2. **For each strategy** in `get_strategies_by_status(['shadow_trading', 'backtested'])` (existing helper at promotion.py:483):
   a. Load shadow_trades for the strategy.
   b. **Filter**: keep only rows where `instrumentation_filter.is_fully_instrumented(row) == True`. Partially-instrumented rows are excluded from the gate input entirely.
   c. Build the `MethodInputs` payload required by `promotion_gate.promotion_gate(...)`.
   d. Call `promotion_gate(...)` — returns `{'decision': 'promote'|'reject'|'defer', 'tally': N, 'votes': {...}, 'threshold_used': '4_of_5'|'4_of_4_no_white_rc', ...}`.
   e. Compose evidence dict: `{'methodology_gate': {<promotion_gate output>}, 'threshold_used': ..., 'instrumentation_excluded_count': N, ...}`.
   f. Persist a `strategy_promotion_events` row with `triggered_by='gate_proposal'`, `from_status==to_status` (no transition), `gate_result_json=<evidence>`, `justification_note=NULL`.
   g. If `decision='promote'` AND existing walkforward+DSR+PBO checks also pass, send notification to operator (or auto-promote depending on `STRICT_GATE` env var; default behavior is notify-only — operator confirms via CLI).
3. **Operator confirm-promotion (CLI)**:
   a. Operator runs `python -m src.main confirm-promotion --strategy <id> --justification "..."`.
   b. CLI validates `len(justification) >= GATE_JUSTIFICATION_MIN_CHARS` (40 chars) client-side; rejects with non-zero exit if too short.
   c. CLI looks up the latest `gate_proposal` row for `<strategy_id>`; refuses if none exists or if it's older than 24h (stale-proposal guard).
   d. CLI calls `platform.promotion.promote(strategy_id=<id>, target_status='live', triggered_by='operator_confirm', justification_note=<arg>)`.
   e. `promote()` re-fires `check_promotion_gate` server-side as a redundant safety check (Phase 4 finding 8). If the gate now rejects (e.g. data shifted between proposal and confirm), promotion is blocked.
   f. On success, `promote()` writes a real `strategy_promotion_events` row with `triggered_by='operator_confirm'`, `from_status!=to_status`, full audit metadata.

### 2.3 4-of-4 fallback

When the candidate-pool size for White's Reality Check (`len(active_research_strategies)`) is < 2, White RC cannot run meaningfully. The gate falls back to a 4-of-4 threshold over the remaining four methods (PBO, CPCV, block-bootstrap, MC-permutation). This fallback is signaled in the evidence payload via `threshold_used='4_of_4_no_white_rc'`. The default value is `threshold_used='4_of_5'`. The fallback is implemented inside `promotion_gate.promotion_gate(...)` (already correctly handles abstentions per its existing strict-mode logic — this revision just makes the threshold value explicit and persisted).

## 3. Data Model

**No new tables.** Per Phase 4 deep-report finding ("schema is sufficient"), persistence uses the existing `strategy_promotion_events` table at `src/schema/registry.py:2106-2128`. Two existing columns carry the new semantics:

### 3.1 `triggered_by` column (registry.py:2113-2114)

Existing `ColumnDef`. Description string is updated from:

```python
description="'manual' | 'auto_gate'"
```

to:

```python
description="'manual' | 'auto_gate' | 'gate_proposal' | 'operator_confirm'"
```

New sentinel semantics:
- `'gate_proposal'` — informational row written by the daily gate firing. `from_status == to_status` (no real transition). `justification_note` is NULL. Used by the dashboard to surface defer/reject states.
- `'operator_confirm'` — real transition row written by `promote()` after the operator confirms via CLI. `from_status != to_status`. `justification_note` is non-NULL and ≥40 chars (enforced by `promote()` at promotion.py:402-407).

No SQL migration needed — the column already exists, only the description-string changes. The `validate-schema` test will not flag this; the description is metadata-only.

### 3.2 `gate_result_json` column (registry.py:2115-2116)

Existing `ColumnDef` (TEXT, free-form JSON). Schema of the JSON payload (documented; not enforced by SQL):

```json
{
  "methodology_gate": {
    "decision": "promote" | "reject" | "defer",
    "tally": <int>,
    "votes": {
      "pbo": {"decision": ..., "value": ..., "threshold": ...},
      "cpcv": {...},
      "block_bootstrap": {...},
      "mc_permutation": {...},
      "white_rc": {...} | null
    }
  },
  "threshold_used": "4_of_5" | "4_of_4_no_white_rc",
  "instrumentation_excluded_count": <int>,
  "existing_gates": {
    "walkforward_passes": <bool>,
    "dsr_passes": <bool>,
    "pbo_passes": <bool>
  },
  "composed_pass": <bool>,
  "override_by": <str|null>,    // JSON key, NOT a column. Set on operator_confirm rows.
  "override_reason": <str|null> // JSON key, NOT a column. Same as justification_note for convenience.
}
```

The `composed_pass` boolean is the AND-composition of methodology + existing gates. It is written by the gate-proposal row for dashboard convenience; the CLI still re-fires the gate before promote().

## 4. API & Module Surface

### 4.1 `src/platform/promotion.py` (modified)

New helper:

```python
def _evaluate_strategy_methodology_gate(
    strategy_id: str, db_path: str
) -> tuple[bool, dict]:
    """Run the 4-of-5 methodology gate against a strategy's instrumented shadow trades.

    Returns (passes, evidence_dict) where:
      - passes is True only when promotion_gate returns decision='promote'.
      - evidence_dict matches the schema documented in spec §3.2.

    Defer / reject / abstain do NOT short-circuit upstream checks; they are
    encoded as passes=False so that AND-composition naturally blocks promotion.
    """
```

Modified call sites (existing functions; insert AND-composition at the existing return points):

- `_evaluate_shadow_trading_gate(...)` at line 246 — append:
  ```python
  mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(strategy_id, db_path)
  evidence['methodology_gate'] = mg_evidence
  return (passes and mg_passes), evidence
  ```
- `_evaluate_production_gate(...)` at line 318 — same pattern.

New top-level orchestrator:

```python
def run_daily_gate_for_all_active_strategies(
    db_path: str, notify: Callable[[str, dict], None] | None = None
) -> list[dict]:
    """Iterate get_strategies_by_status(['shadow_trading', 'backtested']) and
    persist a 'gate_proposal' row per strategy. Invoke notify(strategy_id, evidence)
    on PASS proposals (composed_pass=True) so the operator gets a daily digest.
    Idempotent within a calendar day via the WatchLoop._strategy_gate_done flag.
    Returns the list of evidence dicts (used for tests and notifications).
    """
```

### 4.2 `src/scheduler/watch.py` (modified)

- `__init__` at line 258 — append: `self._strategy_gate_done = False`
- `_reset_daily_state` at line 365 — append: `self._strategy_gate_done = False`
- Daily loop body — insert immediately AFTER the `_postclose_reconcile_done` block (after line 1623):
  ```python
  # 4d. Daily methodology gate sweep (16:35 ET, after post-close reconcile)
  if (hour == 16 and now.minute >= 35
          and not self._strategy_gate_done):
      from src.platform.promotion import run_daily_gate_for_all_active_strategies
      if self._safe_run(
          "daily methodology gate sweep",
          lambda: run_daily_gate_for_all_active_strategies(
              self.db_path, notify=self._notify_gate_proposal),
      ):
          self._strategy_gate_done = True
  ```
  The late-import inside the method body avoids circular imports between platform and scheduler.

### 4.3 `src/training/trainer.py` (bug-fix-only)

Not a gate-firing site. The only change is the pre-existing abstention bug fix for model-version gating (Phase 4 finding 5: trainer's abstention check returns True when the model-version field is `None`, causing false-positive abstentions). Scope-fenced to that single fix; no new gate-related logic.

### 4.4 CLI `confirm-promotion` (new, thin front-end)

Location: `src/main.py` (existing CLI dispatcher) or `src/cli/promotion_cmd.py` (matching existing module convention — Documentarian to choose).

Usage:
```
python -m src.main confirm-promotion --strategy <id> --justification "..." [--target-status live]
```

Behavior (in order; failure at any step exits non-zero):
1. Validate `len(args.justification.strip()) >= GATE_JUSTIFICATION_MIN_CHARS` (40). If shorter, print error and exit 2.
2. Look up the latest `strategy_promotion_events` row for `args.strategy` with `triggered_by='gate_proposal'`. If none, exit 3 with message "no gate proposal exists; run the daily gate first". If older than 24 hours, exit 4 with message "proposal is stale (>24h); wait for tomorrow's gate".
3. Display the proposal's `gate_result_json` to the operator and prompt y/N (skipped if `--yes` flag set).
4. Call `platform.promotion.promote(strategy_id=args.strategy, target_status=args.target_status or 'live', triggered_by='operator_confirm', justification_note=args.justification)`.
5. `promote()` re-fires `check_promotion_gate` server-side; if it now rejects, promote() raises and the CLI exits 5 with the rejection reason.
6. On success, print the new event_id and exit 0.

The CLI is a thin wrapper around `promote()`. It is NOT an alternative promotion path. The 40-char justification, audit row, gate re-firing, and AND-composition are all enforced by `promote()` itself. The CLI's only added value is (a) ergonomic justification-length pre-check, (b) proposal-staleness guard, (c) operator-readable display of the proposal.

## 5. Error Handling

| Condition | Detection site | Behavior |
|---|---|---|
| `instrumentation_filter` excludes ALL rows for a strategy | `_evaluate_strategy_methodology_gate` | Set `decision='defer'`, `instrumentation_excluded_count=<all>`; persist proposal; do not promote. |
| `len(active_research_strategies) < 2` | inside `promotion_gate.promotion_gate(...)` (existing code path) | Fall back to 4-of-4; set `threshold_used='4_of_4_no_white_rc'`; persist as normal. |
| Methodology gate raises (e.g. malformed inputs) | `run_daily_gate_for_all_active_strategies` | Catch, log via `_safe_run`, persist a proposal with `decision='defer'` and `error_message=<str>` in evidence; continue with next strategy. |
| `promote()` server-side re-fire rejects after operator confirm | `platform.promotion.promote` (existing path) | Raise; CLI exits non-zero with rejection reason. NO transition row written. |
| Justification < 40 chars | CLI client-side AND `promote()` server-side | Both reject. Defense in depth — server-side validation is authoritative (promotion.py:402-407). |
| Stale proposal (>24h) at operator-confirm time | CLI client-side | Reject with exit 4. (Defense: server-side `check_promotion_gate` re-fire will catch any data drift even if the staleness guard is bypassed.) |
| Feature flag `METHODOLOGY_GATE_ENABLED=false` | `_evaluate_strategy_methodology_gate` early-return | Return `(True, {'methodology_gate': {'decision': 'skipped', 'reason': 'feature_flag_disabled'}})`. NO persistence side-effects in disabled mode. |
| Watch loop misses 16:35 ET window (e.g. NSSM restart) | `_strategy_gate_done` flag remains False; window check fails | The check `hour == 16 and minute >= 35` is open-ended on the upper side until day rolls — the gate can still fire later in the same day. After day rolls, `_reset_daily_state` clears the flag for the next trading day. (Identical resilience pattern to existing post-close-reconcile slot.) |
| Concurrent CLI confirm-promotion races daily gate proposal-write | DB row lock + `promote()` re-fire | The re-fire acts as the canonical check; if proposal-write races and an operator confirms against an in-flight proposal, the re-fire either accepts (gate still passes) or rejects (gate state changed) — no half-written transitions. |

## 6. Testing Strategy — Behavior Coverage

Named tests, one per critical safety property. Test count is derived from this list (currently 8 mandatory + supporting unit tests around each named test → expected 12-18 net new tests, but the 12-18 is consequence, not goal).

Mandatory named tests:

1. **`test_operator_confirm_calls_promote_not_synthetic_outcome`** — Locks Critical 1 fix. Mocks `platform.promotion.promote`; runs CLI `confirm-promotion`; asserts `promote()` was called once with `triggered_by='operator_confirm'`, `justification_note=<arg>`. Asserts no synthetic `_apply_gate_outcome` path is exercised.
2. **`test_reject_outcome_not_overridable_via_cli`** — Locks Decision 4. Sets up a strategy with `decision='reject'` proposal; runs CLI confirm-promotion; asserts non-zero exit with rejection-reason message; asserts no `triggered_by='operator_confirm'` row written.
3. **`test_and_composition_with_walkforward_blocks_methodology_only_pass`** — Locks Major 7. Constructs a strategy where methodology gate returns `decision='promote'` but existing walkforward check returns False; calls `check_promotion_gate`; asserts overall result is False; asserts evidence contains both gates' outputs.
4. **`test_partial_instrumentation_excluded_from_gate_input`** — Locks Major 5. Constructs shadow_trades where 50% of rows fail `is_fully_instrumented`; runs `_evaluate_strategy_methodology_gate`; asserts `instrumentation_excluded_count == <half>` in evidence; asserts the gate input passed to `promotion_gate(...)` excludes those rows (verified via mock).
5. **`test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key`** — Locks Major 6. Sets `active_research_strategies=[]`; runs gate; asserts `evidence['threshold_used'] == '4_of_4_no_white_rc'`; asserts White RC vote is None / abstained.
6. **`test_feature_flag_disabled_short_circuits_persistence`** — Locks Decision 6. Sets `METHODOLOGY_GATE_ENABLED=false`; runs `run_daily_gate_for_all_active_strategies`; asserts NO `strategy_promotion_events` rows written; asserts return value reflects `decision='skipped'`.
7. **`test_gate_proposal_row_has_from_status_eq_to_status`** — Locks Major 4 sentinel mechanism. Runs daily gate; queries the resulting row; asserts `triggered_by='gate_proposal'`, `from_status == to_status`, `justification_note IS NULL`.
8. **`test_operator_confirm_row_has_real_transition`** — Locks Major 4 sentinel mechanism. Runs CLI confirm-promotion against a passing proposal; asserts resulting row has `triggered_by='operator_confirm'`, `from_status != to_status`, `justification_note` non-NULL and ≥40 chars.

Supporting unit tests (derived, not target):
- `test_helper_aggregates_shadow_trades_correctly` — `_evaluate_strategy_methodology_gate` builds correct `MethodInputs`.
- `test_run_daily_iterates_active_strategies_only` — `run_daily_gate_for_all_active_strategies` skips strategies in terminal statuses.
- `test_watch_loop_idempotent_within_day` — fires twice in same day; second is no-op via `_strategy_gate_done`.
- `test_watch_loop_resets_flag_at_day_roll` — `_reset_daily_state` clears the flag.
- `test_stale_proposal_rejected_by_cli` — proposal >24h old → CLI exit 4.
- `test_promote_re_fires_gate_server_side` — even if proposal is stale-but-CLI-bypassed, promote() catches it.
- Plus regression-locks for each integration point in `_evaluate_shadow_trading_gate` / `_evaluate_production_gate`.

Test infrastructure: existing `tests/conftest.py` fixtures for in-memory SQLite + schema-registry initialization. Mock external calls; no network. Test count baseline: CLAUDE.md cites 3682 — bump after sprint completes.

## 7. Operational Notes

### 7.1 Feature flag

`METHODOLOGY_GATE_ENABLED` env var. Default: `true` (per Decision 6). Setting to `false` short-circuits `_evaluate_strategy_methodology_gate` to return `(True, {'methodology_gate': {'decision': 'skipped'}})`. NO persistence side-effects in disabled mode. Intended use: emergency disable if a methodology-side bug blocks all promotions during a market event.

### 7.2 Strict mode

`STRICT_GATE` env var (existing semantics — see Decision 8). When `true`, the daily gate's PASS proposals AUTO-promote (skip operator confirmation). Default: `false`. The two flags compose as a 2x2 — see §9 Known Considerations for the grid.

### 7.3 Operator runbook update

`docs/operator-guide.md` gains a new section: "Daily methodology-gate workflow" — covers reading the daily digest, interpreting evidence JSON, running confirm-promotion, troubleshooting defer outcomes. Updated as part of T9.

## 8. File Inventory (citations)

All citations verified against the working tree as of v3 review.

- `src/platform/promotion.py:46` — `GATE_JUSTIFICATION_MIN_CHARS = 40`
- `src/platform/promotion.py:246` — `_evaluate_shadow_trading_gate` (AND-compose target)
- `src/platform/promotion.py:318` — `_evaluate_production_gate` (AND-compose target)
- `src/platform/promotion.py:331` — `check_promotion_gate` (top-level dispatcher)
- `src/platform/promotion.py:390-427` — `promote()` (justification enforcement + audit row writer)
- `src/platform/promotion.py:483` — `get_strategies_by_status` (existing helper used by daily orchestrator)
- `src/methods/promotion_gate.py:134` — `promotion_gate()` (4-of-5 voter; UNCHANGED)
- `src/analytics/instrumentation_filter.py:48` — `is_fully_instrumented(row) -> bool`
- `src/analytics/instrumentation_filter.py:73-75` — `filter_fully_instrumented(rows)` convenience helper
- `src/scheduler/watch.py:258` — `__init__` flag init insertion point
- `src/scheduler/watch.py:316,365` — `_reset_daily_state` flag reset insertion point
- `src/scheduler/watch.py:1615-1623` — post-close reconcile slot (insert gate-firing block AFTER)
- `src/schema/registry.py:2106-2128` — `strategy_promotion_events` TableDef (no schema change; description string update only at 2113-2114)
- `src/training/trainer.py` — abstention-bug-fix scope only (Phase 4 finding 5)

## 9. Known Considerations (minor, deferred)

Appended per revision-feedback minor-finding policy. NOT in v3 implementation scope.

### 9.1 STRICT_GATE × METHODOLOGY_GATE_ENABLED interaction grid

| `METHODOLOGY_GATE_ENABLED` | `STRICT_GATE` | Behavior |
|---|---|---|
| true | true | Daily gate fires; PASS proposals AUTO-promote; defer/reject blocks promotion. (Most strict.) |
| true | false | Daily gate fires; PASS proposals notify operator; operator confirms via CLI. (Default.) |
| false | true | Methodology side short-circuits to True; existing walkforward+DSR+PBO checks still gate; PASS auto-promotes. (Methodology disabled, but full strict on existing checks.) |
| false | false | Methodology side short-circuits to True; existing checks notify; operator confirms. (Effectively v0 behavior — useful for emergency rollback.) |

Operator may want a structured way to express "strict on existing gates, advisory on methodology" — current design supports this via the 2x2. If finer-grained mode-switching is needed, a follow-up sprint could introduce a 3-state enum.

### 9.2 Feature-flag default direction

Decision 6 sets `METHODOLOGY_GATE_ENABLED=true` as default, against the convention of `default=false` for new gates. Rationale: this is a wiring of an already-tested module, not a new gate algorithm — it earned the `default=true` by virtue of the toolkit's prior validation. Operator may revisit this default after observing the first 5 trading days of daily proposals.

## 10. Revision History — full

- **v3 (2026-05-05)** — Devil's Advocate review `a161731b7f88ceabb` (3 CRIT + 5 MAJ): CLI now wraps `promote()`; `platform.promotion.py` modified by new task; cadence pinned to watch.py 16:35 ET; new table dropped (uses sentinel `triggered_by` values on existing table); instrumentation filter explicit; `threshold_used` persisted in JSON; AND-composition explicit; behavior-coverage tests replace count target. Path corrections: `src/methods/instrumentation_filter.py` → `src/analytics/instrumentation_filter.py`; `src/watch.py` → `src/scheduler/watch.py`; `src/schemas/registry.py` → `src/schema/registry.py`. Decision count 18 → 17 (dropped index decision since table dropped).
- v2 — 18 decisions, 10 tasks; introduced new `promotion_gate_decisions` table (later dropped); placed gate inside trainer.py (later corrected to watch.py); CLI used synthetic `_apply_gate_outcome` (later corrected to thin `promote()` wrapper).
- v1 — separate-gate sketch; rejected at INTERVIEW Phase 3 in favor of integration into `platform.promotion`.


## 11. Design Decisions Table

| # | Decision | Rationale |
|---|---|---|
| 1 | Integrate methodology gate into existing platform.promotion.check_promotion_gate via AND-composition, NOT as a separate gate. | Phase 3 INTERVIEW chose this path. AND-composition with existing walkforward+DSR+PBO checks gives a single source of truth for promotability; defer/reject naturally block via the False arm of AND without short-circuit complexity. |
| 2 | Persist gate outcomes to existing strategy_promotion_events table via two new triggered_by sentinel values: 'gate_proposal' and 'operator_confirm'. | Phase 4 deep-report concluded schema is sufficient — no new tables needed. Sentinel values + JSON keys in gate_result_json carry all needed metadata. Avoids migration risk and preserves audit-trail invariants. |
| 3 | Daily gate fires at 16:35 ET via src/scheduler/watch.py, NOT via trainer.py event-driven cycles. | Phase 3 INTERVIEW pinned cadence to daily off-hours. Trainer cycles are irregular and can fire multiple times per day; the methodology gate must fire exactly once per trading day after post-close-reconcile completes (so MinTRL/instrumentation inputs are stable). |
| 4 | Reject outcome is NOT overridable via the CLI flow. | Operator-side intent: a hard methodology-side reject means a methodology problem the operator cannot fix by writing a justification note. Override capability for reject would defeat the purpose of having a methodology gate at all. |
| 5 | CLI confirm-promotion is a thin wrapper around platform.promotion.promote() — NOT an alternative promotion path. | Critical-1 review finding: a synthetic-outcome path bypasses promote()'s server-side re-fire of check_promotion_gate, bypasses 40-char justification enforcement, and bypasses audit-row writing. The CLI's only added value is ergonomic pre-checks (justification length, proposal staleness). |
| 6 | Feature flag METHODOLOGY_GATE_ENABLED defaults to true. | This wires an already-tested module, not a new gate algorithm. The 4-of-5 voter has independent test coverage. Default-true reflects readiness; default-false would force every dev/test environment to opt in and create a hidden-disabled-by-default footgun. |
| 7 | Feature-flag short-circuit returns (True, {'decision': 'skipped'}) with NO persistence side-effects. | Disabled mode should be inert — writing rows in disabled mode would pollute the dashboard and confuse the audit trail. (True, ...) ensures AND-composition still allows existing gates to run. |
| 8 | STRICT_GATE × METHODOLOGY_GATE_ENABLED compose as a 2x2 grid, not a 3-state enum. | The two flags address orthogonal concerns: STRICT_GATE governs whether PASS proposals auto-promote vs notify; METHODOLOGY_GATE_ENABLED governs whether methodology side runs at all. A 3-state enum would conflate them and lose flexibility. |
| 9 | Apply analytics.instrumentation_filter.is_fully_instrumented as the gate input filter. | Operator constraint per Major 5. Partially-instrumented trades have unreliable cost/timing data and would skew the methodology-gate inputs. The filter is the existing canonical predicate. |
| 10 | When len(active_research_strategies) < 2, fall back to 4-of-4 threshold and persist threshold_used='4_of_4_no_white_rc'. | White RC needs ≥2 strategies for meaningful multi-strategy data-snooping correction. Falling back to 4-of-4 over the remaining methods preserves gate strictness when White RC must abstain. Persisting the threshold_used key lets the dashboard distinguish 4-of-5 days from 4-of-4 days. |
| 11 | Late-import platform.promotion inside watch.py method body, not at module top. | platform.promotion imports schema and analytics modules; watch.py is imported during scheduler init before some of those modules are fully loaded. Late-import inside the method body avoids a circular-import risk that has bitten this codebase before. |
| 12 | Trainer.py is touched only for its pre-existing model-version abstention bug fix; it is NOT a gate-firing site. | Critical 3 fix: cadence pinned to watch.py daily slot. Trainer feeds inputs to the gate; it does not drive gate decisions. The abstention bug is in scope because the daily gate consumes trainer-emitted artifacts and false-positive abstentions would corrupt evidence. |
| 13 | promote() re-fires check_promotion_gate server-side as a redundant safety check. | Defense in depth. Even if the CLI's staleness guard or justification check is bypassed, the server-side re-fire catches data drift between proposal and confirm. This is the existing behavior of promote() — preserving it is non-negotiable. |
| 14 | Stale-proposal guard at 24h. | Proposals are generated daily; a >24h-old proposal means the operator missed a trading day's worth of new data. The CLI rejects with exit 4 and asks the operator to wait for tomorrow's gate. Server-side promote() re-fire is the authoritative check; the staleness guard is operator-ergonomic. |
| 15 | Test plan is a behavior-coverage list of 8 named tests; count is derived, not target. | Major 8 fix: a count target (12-18 tests) could land entirely on happy paths. Naming each test 1:1 to a critical safety property ensures coverage of the actual correctness conditions. |
| 16 | Override metadata (override_by, override_reason) lives as JSON keys in gate_result_json, NOT as new columns. | Major 4 conformance: no new columns on strategy_promotion_events. JSON keys are sufficient for read-side dashboard rendering and audit-log searches; SQL filtering on override_by is rare enough that JSON is acceptable. |
| 17 | AND-composition is implemented at the existing return points of _evaluate_shadow_trading_gate / _evaluate_production_gate, not by wrapping check_promotion_gate. | Wrapping check_promotion_gate would create a second dispatcher and split the call graph. Inserting AND-composition at the existing return points is a minimal change that preserves the dispatcher's structure and naturally inherits the existing audit-row behavior. |
