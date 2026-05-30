# Methodology Gate Wiring — Design Spec v5

## Revision History

- **v5 (this revision, 2026-05-05)** — Final architect revision before Sprint 2 resumes. DA verdict on v4 was CONCERNS (1 critical + 6 major + 3 minor). Operator decided **Choice A** on critical #1 (MC permutation is mathematically degenerate under a long-only system where `directions=[+1]*N`; T3 is documented as an input-quality fix only — it does NOT enable promote decisions in trainer.py / kpis_compute.py call paths). Six mechanical major fixes applied: (1) line 298 added to AND-compose insertion list (the wf-pass success branch was missing); (2) vote name and shape aligned with `_decide` in `promotion_gate.py:107` — keys are `cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc` (no `pbo`; `mc_perm` not `mc_permutation`), value shape is `{name: passed_bool_or_None}` with `details[name]` carrying `{value, threshold, details}` separately; (3) `actual_entry_time IS NOT NULL` filter added to T3 SQL; (4) `walkforward_status` placement specified — added alongside `walkforward_outcome_state` in `_evaluate_walkforward_gate`, NOT replacing; (5) production gate asymmetry documented (production target only checks DSR — walkforward and PBO are Sprint-4 placeholders); (6) sibling-search third callsite at `cli/commands.py:964 cmd_run_promotion_gate` covered by transitive trainer fix + explicit regression test. Three minor findings folded into Known Considerations + an explicit T5/T2 ordering ratchet. T3 complexity raised from medium to high.
- v4 (2026-05-05) — Sprint 2 implementation paused after T3 dispatch revealed v3 architect mislabel of Phase 4 deep_report finding 5. T3 corrected to fix the REAL line 1039 bug (missing dates+directions kwargs causing unconditional MC-perm + White-RC abstentions, plus a double-rf-subtraction at lines 975-976 once `dates` flows). Mirror bug at `kpis_compute.py:376` brought into T3 scope. Walkforward-data-gap addressed via `walkforward_status='no_data_yet'` evidence semantics. T3 complexity raised from low to medium.
- v3 (2026-05-05) — Devil's Advocate review `a161731b7f88ceabb` (3 CRIT + 5 MAJ): CLI now wraps `promote()`; `platform.promotion.py` modified by new task; cadence pinned to watch.py 16:35 ET; new table dropped (uses sentinel `triggered_by` values on existing table); instrumentation filter explicit; `threshold_used` persisted in JSON; AND-composition explicit; behavior-coverage tests replace count target.
- v2 — initial integration-style spec (drifted from Phase 3+4 commitments on the 8 axes addressed in v3).
- v1 — separate-gate sketch (rejected at INTERVIEW Phase 3).

## 1. Overview

Wires the existing 4-of-5 methodology toolkit (`src/methods/promotion_gate.py`) into the production strategy promotion path so that a promotion candidate cannot advance from `shadow_trading` or `backtested` to `live` without methodology-gate concurrence. The gate currently exists as a shelf module — fully tested in isolation but never invoked by `src/platform/promotion.py::check_promotion_gate`. After this change it becomes part of the AND-composed promotion check.

### 1.1 Cadence — pinned

**The gate fires daily at 16:35 ET via the watch.py scheduler, NOT via trainer.py training-cycle checkpoints.** The trainer fires on event-driven training cycles (irregular, sometimes multiple per day). The methodology gate fires exactly once per trading day, immediately after the post-close reconciliation slot. trainer.py is touched by this work only to fix its own pre-existing input-quality bug at line 1039 (a separate concern that surfaces during daily-gate runs because the daily gate consumes trainer-emitted artifacts).

### 1.2 Composition rule — pinned

**The methodology gate is AND-composed with existing checks.** A strategy is promotable only if the methodology gate returns `decision='promote'` AND every relevant existing check returns True. Composition occurs in `src/platform/promotion.py::check_promotion_gate` (line 331) via a new `_evaluate_strategy_methodology_gate(strategy_id, db_path) -> tuple[bool, dict]` helper, AND-composed into `_evaluate_shadow_trading_gate` (line 246) and `_evaluate_production_gate` (line 318). Defer / abstain outcomes from the methodology side do NOT short-circuit existing checks — they evaluate to False on the gate side, blocking promotion until operator confirmation.

**Asymmetry by promotion target (DA major fix 5, verified 2026-05-05):**
- For the **shadow_trading** target (i.e. `backtested → shadow_trading`), `_evaluate_shadow_trading_gate` AND-composes methodology gate WITH walkforward + DSR + PBO. (PBO check at line 296; DSR via `_evaluate_dsr_evidence` at line 258; walkforward via `_evaluate_walkforward_gate` at line 263.)
- For the **production** target (i.e. `shadow_trading → production`), `_evaluate_production_gate` (lines 318-328) ONLY checks DSR. The function explicitly sets `evidence['pbo'] = None  # Sprint 4 wires production gate PBO check` at line 326 and `evidence['oos_efficiency'] = None` at line 327. **At this stage the methodology gate AND-composes with DSR only** — walkforward and PBO are Sprint-4 placeholders not yet wired.
- The operator runbook (T9) MUST surface this asymmetry so the operator does not assume both transitions enforce identical preconditions.

**Walkforward bootstrap-window degradation:** If upstream walkforward has not yet produced data (`walkforward_results` empty for a strategy — currently 0 rows as of 2026-05-05; last filesystem artifact dates 2026-04-12), the existing `_evaluate_walkforward_gate` at line 222-225 sets `walkforward_outcome_state = None` and returns `(None, evidence)`. v5 specifies an evidence-side annotation `walkforward_status='no_data_yet'` placed alongside `walkforward_outcome_state` (NOT replacing it; backwards-compat preserved) so the operator/dashboard can distinguish "no data yet — run smoke_gate_9_fold1.bat once corpus is ready" from "FAIL — methodology problem". The composed result remains False (conservative); the annotation makes the cause visible. This is NOT a methodology bug — it's a sequencing prerequisite the operator addresses by populating walkforward_results.

**`walkforward_status` placement (DA major fix 4):**
- Assignment happens **inside** `_evaluate_walkforward_gate` itself (T2 task scope includes `src/platform/promotion.py`).
- Mapping: `evidence['walkforward_status'] = 'no_data_yet' if outcome_state is None else outcome_state.lower()`.
- The existing `walkforward_outcome_state` key (assigned at line 223 when no row, 226 when row exists) **continues to be set unchanged** — `walkforward_status` is purely additive.
- Possible values: `'no_data_yet' | 'pass' | 'fail' | 'inconclusive'`.

### 1.3 Outcome semantics

- `decision='promote'` (4-of-5 votes pass) — methodology side returns True; promotion proceeds if other gates also pass.
- `decision='reject'` (≥2 votes fail OR inverse hard-block) — methodology side returns False; promotion blocked. NOT overridable via the CLI flow.
- `decision='defer'` (no quorum, e.g. abstentions push tally below threshold) — methodology side returns False; operator MAY confirm-promotion via CLI with a justification note ≥40 chars. The CLI flow re-fires the gate server-side and writes a real audit transition row.

#### 1.3.1 Sprint 2 limitations — long-only system + degenerate MC permutation

**Operator decision (Choice A, 2026-05-05):** Document T3 honestly. The methodology gate is currently **incapable of producing `decision='promote'` from the trainer.py and kpis_compute.py call paths** because of a structural property of the test-statistic, NOT a bug fixable by the wiring work in this sprint.

**Why:** The system is long-only per `src/schema/registry.py:202` (`recommendations.direction` defaults to `'long'`). T3 fixes the missing-kwargs bug by passing `directions=[+1]*N` (the semantically honest encoding for a long-only system). However, `src/methods/mc_permutation.py:74-93` defines:
```python
def _statistic(d: list[int]) -> float | None:
    signed = [r * di for r, di in zip(rets, d)]
    return rf_adjusted_excess_sharpe(signed, rf_period=0.0)
```
The permutation procedure shuffles `d` in place and recomputes the statistic. **When `d` is a constant array `[+1, +1, ..., +1]`, shuffling is identity** — every permutation produces the same statistic, so `count_ge` always equals `n_permutations`, producing **p-value = 1.0 deterministically**. Per `_run_mc_perm` (`promotion_gate_helpers.py:139`), the vote `passed = p_value < alpha` evaluates to `False`. This is a hard FAIL, not abstention — but for the 4-of-5 vote tally it has the same effect: MC permutation cannot contribute a passing vote.

Net effect on the gate ceiling for trainer.py and kpis_compute.py call sites:

| Method | Trainer path (n_trials>1, candidate_pool=None) | kpi_compute path (n_trials=1, candidate_pool=None) |
|---|---|---|
| CPCV | Can pass on healthy returns | Can pass on healthy returns |
| block_bootstrap | Can pass on healthy returns | Can pass on healthy returns |
| psr_dsr | Can pass on healthy returns | Can pass on healthy returns |
| mc_perm (post-T3) | **Always FAIL (p=1.0)** under long-only directions | **Always FAIL (p=1.0)** under long-only directions |
| white_rc | Runs only if candidate_pool present; else abstains | Always abstains (n_trials=1, no pool) |
| **Maximum achievable** | **3-of-5 votes** | **3-of-5 votes** |
| **Achievable decisions** | `'reject'` or `'defer'` only | `'reject'` or `'defer'` only |

**The promote-capable path lives in `watch.py` daily orchestrator (T4)**, where the operator can wire `active_research_strategies` as a real `candidate_pool` for White's Reality Check. Under that path:

| Method | watch.py path with candidate_pool |
|---|---|
| CPCV | Can pass on healthy returns |
| block_bootstrap | Can pass on healthy returns |
| psr_dsr | Can pass on healthy returns |
| mc_perm | Still FAIL (long-only directions structural) |
| white_rc | Can pass when candidate_pool ≥ 2 |
| **Maximum achievable** | **4-of-5 votes** |
| **Achievable decisions** | `'promote'` (when 4-of-5 reached), `'reject'`, or `'defer'` |

In other words: T3 makes the gate inputs well-formed; T2+T4 makes the gate functional from the daily orchestrator with a candidate_pool. The trainer.py / kpis_compute.py call sites remain ceiling-3-of-5 and therefore cannot promote until either:
- a future sprint wires `candidate_pool` into those call sites (lifts ceiling to 4-of-5), OR
- a future sprint refactors MC permutation to use a non-degenerate test (e.g., shuffling entry timestamps across the trading-day universe rather than direction labels).

**Operator runbook (T9) MUST document this** so the dashboard's "decision=reject" / "decision=defer" outputs from the trainer/kpi call paths are not misread as methodology problems with the strategy.

**Test lock (T3):** `test_trainer_promotion_gate_currently_cannot_promote_long_only` — feeds healthy returns through `run_promotion_gate_for_version`; asserts `result['decision'] in {'reject', 'defer'}`; asserts MC-perm vote in evidence is the deterministic `passed=False, value≈1.0` outcome. This regression-locks the documented behaviour and prevents a future contributor from "fixing" it without understanding the structural constraint.

### 1.4 Out of scope

- Any new database tables (Phase 4 finding: schema is sufficient).
- Any change to the 4-of-5 voting math itself (`promotion_gate.py` is not modified).
- Frontend dashboard implementation (only the read-side KPI is surfaced; full UI is deferred).
- Refactoring MC permutation to use a non-degenerate test under long-only systems (future sprint).
- Wiring `candidate_pool` into trainer.py / kpis_compute.py call sites (future sprint).

## 2. Architecture

### 2.1 Module map

```
src/scheduler/watch.py            (firing site: daily 16:35 ET)
  └── src/platform/promotion.py   (NEW: integration site; check_promotion_gate AND-composes)
        ├── src/methods/promotion_gate.py        (existing 4-of-5 voting; unchanged)
        ├── src/analytics/instrumentation_filter.py  (input filter: is_fully_instrumented)
        └── src/schema/registry.py:2106-2128     (persistence: strategy_promotion_events)

src/cli/...                       (operator confirm-promotion command — thin front-end to promote())
src/training/trainer.py           (pre-existing input-quality bug fix, NOT a gate-firing site — see §2.3)
src/api/cloud_routes/kpis_compute.py  (mirror bug fix — see §2.3)
src/cli/commands.py               (cmd_run_promotion_gate at line 964 — transitively fixed via trainer.py; see §2.3)
```

### 2.2 Data flow

1. **16:35 ET daily**: `WatchLoop._daily_loop()` enters the post-close-reconcile slot (lines 1615-1623). Immediately after `_postclose_reconcile_done = True`, a new block checks `_strategy_gate_done`; if False, calls `run_daily_gate_for_all_active_strategies(db_path, notify=...)` (late-imported from `src.platform.promotion`).
2. **For each strategy** in `get_strategies_by_status(['shadow_trading', 'backtested'])` (existing helper at promotion.py:483):
   a. Load shadow_trades for the strategy.
   b. **Filter**: keep only rows where `instrumentation_filter.is_fully_instrumented(row) == True` AND `actual_entry_time IS NOT NULL` AND `pnl_pct IS NOT NULL`. Partially-instrumented or undated rows are excluded from the gate input entirely.
   c. Build the `MethodInputs` payload required by `promotion_gate.promotion_gate(...)` — including `returns`, `dates`, and `directions`. (`directions` defaults to +1 per trade since the system is long-only per `registry.py:202`.) Length invariant `len(returns) == len(dates) == len(directions)` MUST hold.
   d. Call `promotion_gate(returns, n_trials=n_trials, dates=dates, directions=directions, candidate_pool=...)`.
   e. Compose evidence dict per spec §3.2.
   f. Persist a `strategy_promotion_events` row with `triggered_by='gate_proposal'`, `from_status==to_status`, `gate_result_json=<evidence>`, `justification_note=NULL`.
   g. If `decision='promote'` AND existing walkforward+DSR+PBO checks also pass, send notification to operator (or auto-promote depending on `STRICT_GATE` env var; default behavior is notify-only).
3. **Operator confirm-promotion (CLI)** — see §4.4.

### 2.3 Pre-existing trainer/kpi-compute input-quality bugs (T3 scope)

**Phase 4 deep_report finding 5 — verified 2026-05-05 by re-reading current source.**

**Bug A: `src/training/trainer.py:1039` — missing `dates` and `directions` kwargs.**

```python
# Current (line 1039):
result = promotion_gate(returns, n_trials=n_trials)
```

Per `src/methods/promotion_gate_helpers.py:121-131` (MC permutation: abstains when `directions is None`) and `:178-188` (White RC: abstains when `n_trials==1` and `candidate_pool is None`), the missing kwargs cause both methods to abstain unconditionally (`passed=None`).

**Bug B: `src/training/trainer.py:975-976` — pre-subtraction of `rf_placeholder` would double-count once Bug A is fixed.**

```python
# Current (lines 975-976):
rf_placeholder = 0.0001
return [float(r[0]) / 100.0 - rf_placeholder for r in rows]
```

Once `dates` is passed to `promotion_gate(...)`, `_adjust_returns_via_fred` (helpers.py:225) subtracts the FRED-derived rf again. Pre-subtracting would double-count.

**Bug C: `src/api/cloud_routes/kpis_compute.py:376` — same call-site pattern as Bug A.**

```python
# Current (line 376):
gate_result = promotion_gate(returns, n_trials=1)
```

Caller at `src/api/cloud_routes/kpis.py:91` has access to the full `instrumented` trade list (with `actual_entry_time` available — see line 79 where `_compute_per_trade_rf` already parses it). The fix: pass dates+directions to `_compute_promotion_gate_kpi` and through to the gate.

**Sibling search — third callsite at `src/cli/commands.py:964` (`cmd_run_promotion_gate`):**

```python
# Current (lines 983-988):
result = run_promotion_gate_for_version(
    version_id=row["version_id"],
    version_name=row["version_name"],
    db_path=DB_PATH,
    n_trials=n_trials,
)
```

This calls `trainer.run_promotion_gate_for_version`, which calls `_resolve_returns_for_gate` and then the `promotion_gate(...)` at trainer.py line 1039. **CLI is transitively fixed by the T3 trainer.py fix.** No code change needed at `cli/commands.py:964` itself, but T3 adds explicit regression tests there to prevent silent drift.

**Critical clarification (operator Choice A, 2026-05-05):**

T3 is a **pre-existing input-quality fix** that prevents wrong-shape data from reaching the gate. It does NOT, by itself, enable promote decisions in the trainer/kpi call paths. Per spec §1.3.1 "Sprint 2 limitations":
- Once T3 lands, MC permutation will receive `directions=[+1]*N` and deterministically return p=1.0 → vote `passed=False`.
- Once T3 lands, White RC at trainer.py (n_trials>1, no pool) may abstain or fail; at kpis_compute.py (n_trials=1, no pool) will continue to abstain.
- Maximum achievable from these call sites is 3-of-5 votes → `decision='reject' | 'defer'` only.
- Promote-capable evaluation runs through the **watch.py daily orchestrator (T4)** where `active_research_strategies` provides the `candidate_pool` and lifts the ceiling to 4-of-5.

**Fix shape (T3):**

1. Refactor `_resolve_returns_for_gate` (trainer.py line 955) to return tuple `(returns, dates, directions)`:
   - `returns: list[float]` — `pnl_pct/100` (raw, NO rf pre-subtraction)
   - `dates: list[date]` — `date.fromisoformat(actual_entry_time[:10])` per trade
   - `directions: list[int]` — `+1` per trade (long-only system per `registry.py:202` `recommendations.direction` default `'long'`)
2. Update SELECT at trainer.py lines 967-972 to fetch `actual_entry_time` AND **enforce `actual_entry_time IS NOT NULL`** alongside the existing `pnl_pct IS NOT NULL` filter.
3. **DROP** `rf_placeholder = 0.0001` pre-subtraction at lines 975-976.
4. If filtered list is empty (no rows survive `pnl_pct IS NOT NULL AND actual_entry_time IS NOT NULL`), `_resolve_returns_for_gate` returns `([], [], [])` and the upstream `run_promotion_gate_for_version` already handles the "no qualifying returns" branch (lines 1019-1036). For gate evaluation contexts that require a non-empty input (e.g. T2's `_evaluate_strategy_methodology_gate`), gate returns `decision='defer'` with `reason='insufficient_dated_returns'`.
5. Update call at trainer.py line 1039 to: `result = promotion_gate(returns, n_trials=n_trials, dates=dates, directions=directions)`.
6. Update `_compute_promotion_gate_kpi` signature (kpis_compute.py:364) to accept the trade list (or `dates` + `directions`) and call line 376 with the new kwargs. Update the caller at `kpis.py:91` to pass the data through.

This is INPUT-quality only — trainer.py is NOT a gate-firing site under any condition. T3 is scope-fenced strictly to Bugs A+B+C and the trivial helper refactor.

### 2.4 4-of-4 fallback

When the candidate-pool size for White's Reality Check (`len(active_research_strategies)`) is < 2, White RC cannot run meaningfully. The gate falls back to a 4-of-4 threshold over the remaining four methods (CPCV, block-bootstrap, MC-permutation, PSR/DSR). This fallback is signaled in the evidence payload via `threshold_used='4_of_4_no_white_rc'`. The default value is `threshold_used='4_of_5'`. The fallback is implemented inside `promotion_gate.promotion_gate(...)` (already correctly handles abstentions per its existing strict-mode logic — this revision just makes the threshold value explicit and persisted).

NOTE: Even with the 4-of-4 fallback, the long-only directions degeneracy (§1.3.1) still floors MC permutation to FAIL. From the trainer/kpi call paths, the achievable ceiling under 4-of-4 is 3-of-4 (CPCV + block_bootstrap + PSR_DSR), which is still below threshold → `decision='reject' | 'defer'`.

## 3. Data Model

**No new tables.** Per Phase 4 deep-report finding ("schema is sufficient"), persistence uses the existing `strategy_promotion_events` table at `src/schema/registry.py:2105-2128`. Two existing columns carry the new semantics.

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

Existing `ColumnDef` (TEXT, free-form JSON, description `"Evidence dict from check_promotion_gate"`). Schema of the JSON payload (documented; not enforced by SQL) — **aligned to the actual `_decide` shape in `promotion_gate.py:107` (DA major fix 2):**

```json
{
  "methodology_gate": {
    "decision": "promote" | "reject" | "defer",
    "n_obs": <int>,
    "mintrl": <int>,
    "votes": {
      "cpcv": true | false | null,
      "block_bootstrap": true | false | null,
      "mc_perm": true | false | null,
      "psr_dsr": true | false | null,
      "white_rc": true | false | null
    },
    "details": {
      "cpcv": {"value": <float|null>, "threshold": <float>, "details": {...} | absent},
      "block_bootstrap": {"value": <float|null>, "threshold": <float>},
      "mc_perm": {"value": <float|null>, "threshold": <float>, "details": {...} | absent},
      "psr_dsr": {"value": <float|null>, "threshold": <float>},
      "white_rc": {"value": <float|null>, "threshold": <float>, "details": {...} | absent},
      "inverse_hard_block": <bool>,
      "n_pass": <int>,
      "n_fail": <int>,
      "n_abstentions": <int>,
      "rf_source": "fred_dtb3" | "placeholder" | "unwired"
    },
    "reason": "insufficient_track_record" | <str> | absent
  },
  "threshold_used": "4_of_5" | "4_of_4_no_white_rc",
  "instrumentation_excluded_count": <int>,
  "existing_gates": {
    "walkforward_passes": <bool>,
    "walkforward_outcome_state": "PASS" | "FAIL" | "INCONCLUSIVE" | null,
    "walkforward_status": "no_data_yet" | "pass" | "fail" | "inconclusive",
    "dsr_passes": <bool>,
    "pbo_passes": <bool> | null
  },
  "composed_pass": <bool>,
  "override_by": <str|null>,
  "override_reason": <str|null>
}
```

Key clarifications (DA major fix 2):
- **`votes`** is a flat `{name: passed_bool_or_None}` dict per the `votes_bool` assignment at `promotion_gate.py:107`. Possible per-method values: `true` (clear pass), `false` (clear fail), `null` (abstention).
- **Vote names match the `name` field returned by each `_run_*` helper exactly:** `cpcv` (helpers.py:90), `block_bootstrap` (helpers.py:104), `mc_perm` (helpers.py:123, 141 — note `mc_perm`, not `mc_permutation`), `psr_dsr` (helpers.py:160), `white_rc` (helpers.py:180, 204).
- **There is NO `pbo` vote in the methodology-gate `votes` dict.** PBO is a separate legacy gate read from `backtest_results.pbo` in `_evaluate_shadow_trading_gate` (line 277) and surfaced in the top-level `existing_gates.pbo_passes` field, not as a methodology vote.
- **There is NO top-level `tally` key.** Counts live in `methodology_gate.details.n_pass / n_fail / n_abstentions` per `promotion_gate.py:115-120`.
- **Per-vote details (`value`, `threshold`, optional `details` substructure) live in `methodology_gate.details[name]`** per `promotion_gate.py:108-113`, not co-located with the boolean.

The `composed_pass` boolean is the AND-composition of methodology + existing gates. It is written by the gate-proposal row for dashboard convenience; the CLI still re-fires the gate before promote().

The `walkforward_status` key is populated by `_evaluate_walkforward_gate` (existing function modified by T2) — `'no_data_yet'` distinguishes the bootstrap-window case from a real FAIL. Set alongside (NOT replacing) `walkforward_outcome_state` for backwards-compat.

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

**Modified call sites — AND-composition insertion at all return points (DA major fix 1):**

DA verified that `_evaluate_shadow_trading_gate` returns at **SEVEN sites** (not six as v4 listed). The complete list, with v5 corrections:

| Line | Branch | Source snippet | Returns |
|---|---|---|---|
| 260 | `_evaluate_dsr_evidence` failure | `if "error" in evidence: return False, evidence` | False |
| 269 | walkforward INCONCLUSIVE / FAIL | `if wf_pass is False: return False, evidence` | False |
| 295 | wf-pass + missing PBO | `evidence["error"] = "backtest has no PBO ..."; return False, evidence` | False |
| **298** | **wf-pass + PBO check (success branch)** | `return passes_dsr and passes_pbo, evidence` | **passes_dsr and passes_pbo** |
| 303 | legacy + missing PBO | `evidence["error"] = ...; return False, evidence` | False |
| 309 | legacy + missing oos_efficiency | `evidence["error"] = ...; return False, evidence` | False |
| 315 | legacy + final compose | `return passes_dsr and passes_pbo and passes_oos, evidence` | **bool compose** |

**Insertion pattern** at EACH return site (apply uniformly to all seven, including the previously-missed line 298):

```python
mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(strategy_id, db_path)
evidence['methodology_gate'] = mg_evidence
return (passes and mg_passes), evidence  # 'passes' substituted with the existing return-expression
```

**Why line 298 is the most critical:** It is the ONLY return site that returns True for new walkforward strategies (wf-pass-PBO-pass success branch). Without AND-composition at 298, the methodology gate is silently bypassed on the most important promotion path — exactly the path the gate is meant to protect.

`_evaluate_production_gate` (lines 318-328) has ONE return site at line 328:
```python
return passes_dsr, evidence
```
Apply the same insertion pattern. **Note (DA major fix 5):** the production gate only checks DSR; methodology is AND-composed with DSR only here (walkforward and PBO are Sprint-4 placeholders set to None at lines 326-327 and not part of the boolean compose).

**`_evaluate_walkforward_gate` modification (DA major fix 4):**

In addition to the existing assignments of `walkforward_outcome_state` (preserved unchanged for backwards-compat), add `walkforward_status` alongside:

```python
# At line 223-225 (no-row branch):
evidence["walkforward_outcome_state"] = None
evidence["walkforward_reason"] = None
evidence["walkforward_status"] = "no_data_yet"   # NEW (v5)
return None, evidence

# At line 226 onward (row exists branch):
evidence["walkforward_outcome_state"] = wf["outcome_state"]
evidence["walkforward_reason"] = wf["reason"]
# ... existing assignments unchanged ...
state = wf["outcome_state"]
evidence["walkforward_status"] = state.lower() if state else "no_data_yet"   # NEW (v5)
```

Possible `walkforward_status` values: `'no_data_yet' | 'pass' | 'fail' | 'inconclusive'`.

**New top-level orchestrator:**

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

- `__init__` at line 258 — append: `self._strategy_gate_done = False` (immediately after `self._postclose_reconcile_done = False`)
- `_reset_daily_state` at line 365 — append: `self._strategy_gate_done = False` (alongside the existing reset of `_postclose_reconcile_done`)
- Daily loop body — insert IMMEDIATELY AFTER the post-close-reconcile block (after line 1623, where `self._postclose_reconcile_done = True` is set):
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

### 4.3 `src/training/trainer.py` + `src/api/cloud_routes/kpis_compute.py` + `src/cli/commands.py` (bug-fix-only)

NOT gate-firing sites. The only changes are the pre-existing input-quality bug fixes per §2.3:
- trainer.py: refactor `_resolve_returns_for_gate` to return `(returns, dates, directions)`; drop rf pre-subtraction; enforce `actual_entry_time IS NOT NULL`; update call at line 1039 to pass new kwargs.
- kpis_compute.py: update `_compute_promotion_gate_kpi` to accept dates+directions; update line 376 to pass them; update caller at kpis.py:91.
- cli/commands.py:964 (`cmd_run_promotion_gate`): no code change — transitively fixed via trainer.py. T3 adds regression tests at this callsite.

Scope-fenced to those bugs; no new gate-related logic.

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
5. `promote()` re-fires `check_promotion_gate` server-side at line 409 (verified 2026-05-05); if it now rejects, promote() raises and the CLI exits 5 with the rejection reason.
6. On success, print the new event_id and exit 0.

The CLI is a thin wrapper around `promote()`. It is NOT an alternative promotion path. The 40-char justification, audit row, gate re-firing, and AND-composition are all enforced by `promote()` itself. The CLI's only added value is (a) ergonomic justification-length pre-check, (b) proposal-staleness guard, (c) operator-readable display of the proposal.

## 5. Error Handling

| Condition | Detection site | Behavior |
|---|---|---|
| `instrumentation_filter` excludes ALL rows for a strategy | `_evaluate_strategy_methodology_gate` | Set `decision='defer'`, `instrumentation_excluded_count=<all>`; persist proposal; do not promote. |
| All rows have NULL `actual_entry_time` (T3 NULL handling) | `_resolve_returns_for_gate` returns `([], [], [])`; `_evaluate_strategy_methodology_gate` sees empty | `decision='defer'`, `reason='insufficient_dated_returns'` (DA major fix 3). |
| Length mismatch `len(returns) != len(dates) != len(directions)` | call boundary (raises in `mc_permutation_pvalue` or `_run_mc_perm`) | Raise; caller in T2 catches via `_safe_run`, persists proposal with `decision='defer'` and `error_message=<str>`. The boundary check at the helper's `len(rets) != len(dirs)` (mc_permutation.py:64-68) is the canonical guard. |
| `len(active_research_strategies) < 2` | inside `promotion_gate.promotion_gate(...)` (existing code path) | Fall back to 4-of-4; set `threshold_used='4_of_4_no_white_rc'`; persist as normal. |
| Methodology gate raises (e.g. malformed inputs) | `run_daily_gate_for_all_active_strategies` | Catch, log via `_safe_run`, persist a proposal with `decision='defer'` and `error_message=<str>` in evidence; continue with next strategy. |
| `promote()` server-side re-fire rejects after operator confirm | `platform.promotion.promote` (line 409, existing path) | Raise; CLI exits non-zero with rejection reason. NO transition row written. |
| Justification < 40 chars | CLI client-side AND `promote()` server-side | Both reject. Defense in depth — server-side validation is authoritative (promotion.py:402-407). |
| Stale proposal (>24h) at operator-confirm time | CLI client-side | Reject with exit 4. |
| Feature flag `METHODOLOGY_GATE_ENABLED=false` | `_evaluate_strategy_methodology_gate` early-return | Return `(True, {'methodology_gate': {'decision': 'skipped', 'reason': 'feature_flag_disabled'}})`. NO persistence side-effects in disabled mode. |
| Watch loop misses 16:35 ET window (e.g. NSSM restart) | `_strategy_gate_done` flag remains False; window check fails | The check `hour == 16 and minute >= 35` is open-ended on the upper side until day rolls. After day rolls, `_reset_daily_state` clears the flag. (Identical resilience pattern to existing post-close-reconcile slot.) |
| Concurrent CLI confirm-promotion races daily gate proposal-write | DB row lock + `promote()` re-fire | The re-fire acts as the canonical check. |
| `walkforward_results` table empty for the strategy (bootstrap window) | `_evaluate_walkforward_gate` walkforward check (existing) | Existing behavior: `_evaluate_walkforward_gate` returns `(None, evidence)` with `walkforward_outcome_state=None`. v5 evidence-side annotation: `evidence['walkforward_status'] = 'no_data_yet'` (DA major fix 4). The methodology gate STILL runs on its own inputs. Composed result is False (conservative — no walkforward data means we cannot approve), but the evidence dict makes the cause operator-visible. Operator runs `scripts/smoke_gate_9_fold1.bat` to populate walkforward_results once corpus is sufficient. NOT a methodology bug; a sequencing prerequisite. |

## 6. Testing Strategy — Behavior Coverage

Named tests, one per critical safety property. Test count is derived from this list (currently 8 mandatory + supporting unit tests around each named test → expected 16-22 net new tests, but the count is consequence, not goal).

Mandatory named tests:

1. **`test_operator_confirm_calls_promote_not_synthetic_outcome`** — Locks Critical 1 fix. Mocks `platform.promotion.promote`; runs CLI `confirm-promotion`; asserts `promote()` was called once with `triggered_by='operator_confirm'`, `justification_note=<arg>`. Asserts no synthetic `_apply_gate_outcome` path is exercised.
2. **`test_reject_outcome_not_overridable_via_cli`** — Locks Decision 4. Sets up a strategy with `decision='reject'` proposal; runs CLI confirm-promotion; asserts non-zero exit with rejection-reason message; asserts no `triggered_by='operator_confirm'` row written.
3. **`test_and_composition_with_walkforward_blocks_methodology_only_pass`** — Locks Major 7. Constructs a strategy where methodology gate returns `decision='promote'` but existing walkforward check returns False; calls `check_promotion_gate`; asserts overall result is False; asserts evidence contains both gates' outputs.
4. **`test_methodology_gate_and_composed_at_walkforward_pass_path`** (DA major fix 1) — Constructs a strategy with wf-PASS + PBO-PASS + DSR-PASS but methodology gate returns False; calls `check_promotion_gate(target='shadow_trading')`; asserts overall result is False; asserts AND-compose fired at line 298 (the wf-pass success branch). Without this test, line 298 could silently bypass the methodology gate.
5. **`test_partial_instrumentation_excluded_from_gate_input`** — Locks Major 5. Constructs shadow_trades where 50% of rows fail `is_fully_instrumented`; runs `_evaluate_strategy_methodology_gate`; asserts `instrumentation_excluded_count == <half>` in evidence; asserts the gate input passed to `promotion_gate(...)` excludes those rows (verified via mock).
6. **`test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key`** — Locks Major 6. Sets `active_research_strategies=[]`; runs gate; asserts `evidence['threshold_used'] == '4_of_4_no_white_rc'`; asserts White RC vote is None / abstained.
7. **`test_feature_flag_disabled_short_circuits_persistence`** — Locks Decision 6. Sets `METHODOLOGY_GATE_ENABLED=false`; runs `run_daily_gate_for_all_active_strategies`; asserts NO `strategy_promotion_events` rows written; asserts return value reflects `decision='skipped'`.
8. **`test_gate_proposal_row_has_from_status_eq_to_status`** — Locks Major 4 sentinel mechanism. Runs daily gate; queries the resulting row; asserts `triggered_by='gate_proposal'`, `from_status == to_status`, `justification_note IS NULL`.
9. **`test_operator_confirm_row_has_real_transition`** — Locks Major 4 sentinel mechanism. Runs CLI confirm-promotion against a passing proposal; asserts resulting row has `triggered_by='operator_confirm'`, `from_status != to_status`, `justification_note` non-NULL and ≥40 chars.

Supporting unit tests (derived, not target):
- `test_helper_aggregates_shadow_trades_correctly` — `_evaluate_strategy_methodology_gate` builds correct `MethodInputs`.
- `test_run_daily_iterates_active_strategies_only` — `run_daily_gate_for_all_active_strategies` skips strategies in terminal statuses.
- `test_watch_loop_idempotent_within_day` — fires twice in same day; second is no-op via `_strategy_gate_done`.
- `test_watch_loop_resets_flag_at_day_roll` — `_reset_daily_state` clears the flag.
- `test_stale_proposal_rejected_by_cli` — proposal >24h old → CLI exit 4.
- `test_promote_re_fires_gate_server_side` — even if proposal is stale-but-CLI-bypassed, promote() catches it.

**T3-specific (input-quality bug locks + Choice A regression):**
- `test_resolve_returns_for_gate_returns_tuple_shape` — locks new return shape `(returns, dates, directions)`.
- `test_resolve_returns_for_gate_returns_length_matched_tuple` (DA major fix 3) — asserts invariant `len(returns) == len(dates) == len(directions)` for every non-empty result.
- `test_resolve_returns_for_gate_handles_null_entry_times` (DA major fix 3) — seeds row with NULL `actual_entry_time`; asserts the row is filtered by SQL (`actual_entry_time IS NOT NULL`); asserts no `TypeError: unsubscriptable` from `None[:10]`.
- `test_resolve_returns_for_gate_returns_empty_when_all_undated` — seeds rows with NULL `actual_entry_time`; asserts `_resolve_returns_for_gate` returns `([], [], [])`; asserts gate evaluation `decision='defer'` with `reason='insufficient_dated_returns'`.
- `test_promotion_gate_called_with_dates_and_directions` — patches `promotion_gate` and asserts the call signature includes the new kwargs from trainer.py.
- `test_rf_placeholder_subtraction_removed` — locks that the pre-subtraction at trainer.py:975-976 is gone (raw `pnl_pct/100` is what's returned).
- `test_kpi_compute_promotion_gate_passes_dates_and_directions` — locks the kpis_compute.py:376 fix.
- `test_directions_default_long_for_long_only_system` — asserts directions list is all +1.
- **`test_trainer_promotion_gate_currently_cannot_promote_long_only`** (Choice A lock) — feeds healthy returns through `run_promotion_gate_for_version`; asserts `result['decision'] in {'reject', 'defer'}`; asserts MC-perm vote in evidence is `passed=False, value≈1.0`. Regression-locks the documented degeneracy from spec §1.3.1.
- **`test_cmd_run_promotion_gate_post_fix_behavior`** (DA major fix 6) — runs CLI `cmd_run_promotion_gate` end-to-end on synthetic returns; asserts deterministic FAIL outcome from Choice A.
- **`test_cmd_run_promotion_gate_passes_dates_directions`** (DA major fix 6) — patches `promotion_gate`; asserts kwargs flow through from `cmd_run_promotion_gate` → `run_promotion_gate_for_version` → trainer.py:1039.

**Walkforward bootstrap-window:**
- **`test_walkforward_status_populated_for_all_four_states`** (DA major fix 4) — asserts all four values (`'no_data_yet', 'ok', 'fail', 'inconclusive'`) appear under their respective conditions (no row, PASS row, FAIL row, INCONCLUSIVE row).
- **`test_walkforward_outcome_state_still_populated_for_backwards_compat`** (DA major fix 4) — locks that the existing `walkforward_outcome_state` key is still set on every code path (preserves backwards-compat for any consumer reading the old key).
- `test_walkforward_status_no_data_yet_when_table_empty` — locks the §6 evidence annotation.

**Vote schema lock:**
- **`test_methodology_gate_evidence_schema_matches_decide_function`** (DA major fix 2) — calls `_evaluate_strategy_methodology_gate` with valid inputs; asserts evidence keys exactly match the spec §3.2 schema: `votes` keys are `{cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc}` (NO `pbo`); each `votes[name]` is `bool | None`; `details[name]` carries `{value, threshold, [details]}`; counts are at `details.{n_pass, n_fail, n_abstentions}` and NOT at top-level `tally`.

**Production gate asymmetry:**
- **`test_production_gate_methodology_compose_with_dsr_only`** (DA major fix 5) — calls `check_promotion_gate(target='production')` with passing DSR + failing methodology; asserts overall False (compose fired); asserts `evidence['pbo'] is None` and `evidence['oos_efficiency'] is None` (Sprint-4 placeholders unchanged).

**T5 ordering ratchet (Minor 1):**
- **`test_cli_confirm_promotion_re_fire_includes_methodology_gate`** (Minor 1) — mocks `promote()`; runs CLI confirm-promotion against a passing proposal; asserts the call to `promote()` causes `check_promotion_gate` re-fire which AND-composes the methodology gate. Verifies T5 cannot meaningfully gate-block until T2 has merged (already implicit via dependency graph; this test makes it observable).

Plus regression-locks for each integration point in `_evaluate_shadow_trading_gate` / `_evaluate_production_gate`.

Test infrastructure: existing `tests/conftest.py` fixtures for in-memory SQLite + schema-registry initialization. Mock external calls; no network. Test count baseline: CLAUDE.md cites 3682 — bump after sprint completes.

## 7. Operational Notes

### 7.1 Feature flag

`METHODOLOGY_GATE_ENABLED` env var. Default: `true` (per Decision 6). Setting to `false` short-circuits `_evaluate_strategy_methodology_gate` to return `(True, {'methodology_gate': {'decision': 'skipped'}})`. NO persistence side-effects in disabled mode. Intended use: emergency disable if a methodology-side bug blocks all promotions during a market event.

### 7.2 Strict mode

`STRICT_GATE` env var (existing semantics — see Decision 8). When `true`, the daily gate's PASS proposals AUTO-promote (skip operator confirmation). Default: `false`. The two flags compose as a 2x2 — see §9 Known Considerations for the grid.

### 7.3 Operator runbook update (T9 scope)

`docs/operator-guide.md` gains a new section: "Daily methodology-gate workflow" — covers reading the daily digest, interpreting evidence JSON, running confirm-promotion, troubleshooting defer outcomes, and the bootstrap-window `walkforward_status='no_data_yet'` case (operator runs `scripts/smoke_gate_9_fold1.bat` once corpus is ready). T9 MUST also document:
- **Sprint 2 limitations from §1.3.1** — trainer/kpi call paths cannot reach `decision='promote'` due to long-only directions degeneracy in MC permutation. Operator should NOT interpret `decision='reject'` from those paths as a methodology problem; instead, look at the watch.py daily orchestrator's evidence (which has the candidate_pool wired).
- **Production-gate asymmetry from §1.2** — production target only AND-composes methodology with DSR (PBO and walkforward are Sprint-4 placeholders set to None). Shadow_trading target AND-composes methodology with walkforward + DSR + PBO. Different transitions enforce different preconditions.

## 8. File Inventory (citations — RE-VERIFIED 2026-05-05 against current source)

All citations re-verified against the working tree as of v5 revision.

- `src/platform/promotion.py:46` — `GATE_JUSTIFICATION_MIN_CHARS = 40` ✓
- `src/platform/promotion.py:222-225` — `_evaluate_walkforward_gate` no-row branch (T2 inserts `walkforward_status='no_data_yet'` here) ✓
- `src/platform/promotion.py:226-243` — `_evaluate_walkforward_gate` row-exists branches (T2 inserts `walkforward_status=state.lower()` here) ✓
- `src/platform/promotion.py:246` — `_evaluate_shadow_trading_gate` (AND-compose target) ✓
- `src/platform/promotion.py:260, 269, 295, **298**, 303, 309, 315` — SEVEN return sites (DA major fix 1: line 298 is the wf-pass-PBO-pass success branch) ✓
- `src/platform/promotion.py:298` — `return passes_dsr and passes_pbo, evidence` (most critical AND-compose insertion site — the only return site that returns True for new walkforward strategies) ✓
- `src/platform/promotion.py:318-328` — `_evaluate_production_gate` — DSR-only check (lines 326-327 explicitly set `pbo=None` and `oos_efficiency=None` as Sprint-4 placeholders; methodology AND-composes with DSR only here) ✓
- `src/platform/promotion.py:331` — `check_promotion_gate` (top-level dispatcher) ✓
- `src/platform/promotion.py:390-432` — `promote()` (justification enforcement at 402-407, server-side re-fire at 409) ✓
- `src/platform/promotion.py:483` — `get_strategies_by_status` (existing helper used by daily orchestrator) ✓
- `src/methods/promotion_gate.py:107` — `votes_bool = {v["name"]: v["passed"] for v in all_votes}` (canonical vote-shape source) ✓
- `src/methods/promotion_gate.py:108-120` — `details[name] = {"value", "threshold", "details"}` + `details["n_pass"|"n_fail"|"n_abstentions"]` (DA major fix 2: per-vote details and counts schema) ✓
- `src/methods/promotion_gate.py:134` — `promotion_gate()` (4-of-5 voter; UNCHANGED). Signature: `(returns, n_trials, alpha=_ALPHA, dates=None, directions=None, candidate_pool=None)` ✓
- `src/methods/mc_permutation.py:74-93` — `_statistic` shuffles `directions`; with `directions=[+1]*N`, shuffling is identity → p=1.0 deterministically (Choice A degeneracy) ✓
- `src/methods/promotion_gate_helpers.py:90, 104, 123, 141, 160, 180, 204` — vote `name` field assignments: `"cpcv", "block_bootstrap", "mc_perm", "psr_dsr", "white_rc"` (DA major fix 2: canonical vote names) ✓
- `src/methods/promotion_gate_helpers.py:121-131` — MC permutation abstention path (when `directions is None`) ✓
- `src/methods/promotion_gate_helpers.py:178-188` — White RC abstention path (when `n_trials<=1` and no `candidate_pool`) ✓
- `src/methods/promotion_gate_helpers.py:225-247` — `_adjust_returns_via_fred` (subtracts FRED rf when dates passed) ✓
- `src/analytics/instrumentation_filter.py:48` — `is_fully_instrumented(row) -> bool`
- `src/analytics/instrumentation_filter.py:73-75` — `filter_fully_instrumented(rows)` convenience helper
- `src/scheduler/watch.py:258` — `__init__` flag init insertion point ✓ (`_postclose_reconcile_done = False` at this exact line)
- `src/scheduler/watch.py:365` — `_reset_daily_state` flag reset insertion point ✓
- `src/scheduler/watch.py:1617-1623` — post-close reconcile slot (insert gate-firing block AFTER line 1623) ✓
- `src/schema/registry.py:202` — `recommendations.direction` ColumnDef default `'long'` (long-only system source-of-truth) ✓
- `src/schema/registry.py:2105-2128` — `strategy_promotion_events` TableDef ✓
  - `triggered_by` ColumnDef at lines 2113-2114 with description `"'manual' | 'auto_gate'"` ✓
  - `gate_result_json` ColumnDef at lines 2115-2116 with description `"Evidence dict from check_promotion_gate"` ✓
- `src/training/trainer.py:955-979` — `_resolve_returns_for_gate` (refactor to return tuple) ✓
- `src/training/trainer.py:967-972` — SQL SELECT (T3 adds `actual_entry_time` column AND `actual_entry_time IS NOT NULL` filter) ✓
- `src/training/trainer.py:975-976` — `rf_placeholder = 0.0001` pre-subtraction (DROP) ✓
- `src/training/trainer.py:1039` — `result = promotion_gate(returns, n_trials=n_trials)` (add `dates`, `directions` kwargs) ✓
- `src/api/cloud_routes/kpis_compute.py:364-385` — `_compute_promotion_gate_kpi` ✓
- `src/api/cloud_routes/kpis_compute.py:376` — `gate_result = promotion_gate(returns, n_trials=1)` (add `dates`, `directions` kwargs) ✓
- `src/api/cloud_routes/kpis.py:91` — caller; needs to pass `instrumented` trade list (or dates+directions) into helper ✓
- `src/cli/commands.py:964-989` — `cmd_run_promotion_gate` (transitively fixed via trainer.py; T3 adds explicit regression tests) ✓

**Sibling-search verified for `promotion_gate(returns, ...)` callsites (DA major fix 6):**
- `src/training/trainer.py:1039` — T3 fix
- `src/api/cloud_routes/kpis_compute.py:376` — T3 sibling fix
- `src/cli/commands.py:964 cmd_run_promotion_gate` — transitively fixed via trainer.py; T3 adds explicit regression tests `test_cmd_run_promotion_gate_post_fix_behavior` and `test_cmd_run_promotion_gate_passes_dates_directions`
- No other callsites of `promotion_gate(...)` found in `src/` (verified via grep on 2026-05-05).

**Phase 4 finding re-verification summary (v5):**

| # | Spec claim | v5 status | Notes |
|---|---|---|---|
| 1 | trainer.py:1039 missing dates+directions kwargs | VERIFIED (Choice A: input-quality fix only; no promote-capable on this path) |
| 2 | registry.py:2113-2114 triggered_by ColumnDef | VERIFIED |
| 3 | promotion.py:246, 318, 331 (shadow/production/check_promotion_gate) | VERIFIED |
| 4 | watch.py:258, 365, 1615-1623 | VERIFIED (slot ends at 1623) |
| 5 | promote() at 390-432 re-fires gate at 409 | VERIFIED |
| 6 | gate_result_json at 2115-2116 is TEXT free-form | VERIFIED |
| 7 | walkforward+DSR+PBO already exist as gates for shadow_trading; production=DSR-only | VERIFIED (DA major fix 5) |
| 8 | get_strategies_by_status at promotion.py:483 | VERIFIED |
| 9 | _evaluate_shadow_trading_gate has 7 return sites (incl. line 298) | VERIFIED 2026-05-05 (DA major fix 1) |
| 10 | Vote keys per `_decide`: `cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc` | VERIFIED (DA major fix 2) |
| 11 | `_evaluate_walkforward_gate` sets `walkforward_outcome_state=None` at no-row branch | VERIFIED (DA major fix 4) |

## 9. Known Considerations (minor, deferred)

### 9.1 STRICT_GATE × METHODOLOGY_GATE_ENABLED interaction grid

| `METHODOLOGY_GATE_ENABLED` | `STRICT_GATE` | Behavior |
|---|---|---|
| true | true | Daily gate fires; PASS proposals AUTO-promote; defer/reject blocks promotion. (Most strict.) |
| true | false | Daily gate fires; PASS proposals notify operator; operator confirms via CLI. (Default.) |
| false | true | Methodology side short-circuits to True; existing walkforward+DSR+PBO checks still gate; PASS auto-promotes. |
| false | false | Methodology side short-circuits to True; existing checks notify; operator confirms. (Effectively v0 behavior.) |

### 9.2 Feature-flag default direction

Decision 6 sets `METHODOLOGY_GATE_ENABLED=true` as default, against the convention of `default=false` for new gates. Rationale: this is a wiring of an already-tested module, not a new gate algorithm.

### 9.3 Walkforward bootstrap window (NEW in v4, refined v5)

`walkforward_results` table has 0 rows as of 2026-05-05. The methodology gate runs independently on its own inputs (instrumented shadow_trades), but composed promotion still requires walkforward PASS. Operator action: run `scripts/smoke_gate_9_fold1.bat` to populate walkforward_results once corpus is sufficient. The `walkforward_status='no_data_yet'` evidence annotation surfaces the cause to the dashboard. v5 clarifies placement: set inside `_evaluate_walkforward_gate` alongside (NOT replacing) `walkforward_outcome_state`.

### 9.4 T5/T2 ordering ratchet (Minor 1, NEW in v5)

T5 (CLI confirm-promotion) calls `platform.promotion.promote(...)`, which calls `check_promotion_gate(...)`. The methodology-gate AND-composition only fires once T2 has merged. The plan's execution order [Wave 1 = T1+T3, Wave 2 = T2, Wave 3 = T4+T5+T6] already enforces this via the dependency graph (T5 has `depends_on: [T2]`); v5 documents it explicitly. The test `test_cli_confirm_promotion_re_fire_includes_methodology_gate` makes the dependency observable: it mocks `promote()` and asserts the methodology gate is in the re-fire call graph.

### 9.5 Long-only directions degeneracy (Choice A, NEW in v5)

Per spec §1.3.1, MC permutation produces deterministic p=1.0 (`passed=False`) under `directions=[+1]*N`. From the trainer.py and kpis_compute.py call sites, this caps the achievable vote tally at 3-of-5 → `decision='reject' | 'defer'`, never `'promote'`. Promote-capable evaluation runs through the watch.py daily orchestrator (T4) where `active_research_strategies` provides a candidate_pool that lifts White RC out of abstention (4-of-5 ceiling).

The structural fix — refactoring MC permutation to use a non-degenerate test (e.g., shuffling entry timestamps across the trading-day universe rather than direction labels) — is deferred to a future sprint. Tracking ticket TBD.

The test `test_trainer_promotion_gate_currently_cannot_promote_long_only` regression-locks this behaviour to prevent a future contributor from "fixing" it without understanding the structural constraint.

## 10. Revision History — full

- **v5 (2026-05-05)** — Final architect revision before Sprint 2 resumes. DA verdict on v4 was CONCERNS (1 critical + 6 major + 3 minor). Operator decided Choice A on critical #1 (MC perm expected-FAIL under long-only system; T3 documented as input-quality fix only). Six mechanical major fixes applied: line 298 AND-compose insertion; vote name/shape alignment with code; actual_entry_time NULL handling; walkforward_status placement specified; production gate asymmetry documented; sibling-search third callsite covered. Three minor findings folded into Known Considerations + ordering ratchet for T5. T3 complexity bumped medium → high.
- v4 (2026-05-05) — Sprint 2 implementation paused after T3 dispatch revealed v3 architect mislabel. T3 corrected to fix the REAL line 1039 bug (missing dates+directions kwargs). Mirror bug at `kpis_compute.py:376` brought into T3 scope. Walkforward-data-gap addressed via `walkforward_status='no_data_yet'` evidence semantics. T3 complexity raised low → medium.
- v3 (2026-05-05) — Devil's Advocate review `a161731b7f88ceabb` (3 CRIT + 5 MAJ): CLI now wraps `promote()`; `platform.promotion.py` modified by new task; cadence pinned to watch.py 16:35 ET; new table dropped; instrumentation filter explicit; `threshold_used` persisted in JSON; AND-composition explicit; behavior-coverage tests replace count target.
- v2 — 18 decisions, 10 tasks; introduced new `promotion_gate_decisions` table (later dropped); placed gate inside trainer.py (later corrected to watch.py); CLI used synthetic `_apply_gate_outcome` (later corrected to thin `promote()` wrapper).
- v1 — separate-gate sketch; rejected at INTERVIEW Phase 3 in favor of integration into `platform.promotion`.

## 11. Design Decisions Table

(All 17 decisions preserved verbatim from v3/v4. Decision 12 rationale rewritten per Minor 2 to drop the v4-correction parenthetical in favor of a single coherent paragraph + the Choice A clarification.)

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
| 12 | Trainer.py is touched only for its pre-existing input-quality bug fix (line 1039 missing kwargs + lines 975-976 rf double-count); it is NOT a gate-firing site. | T3 is a pre-existing input-quality bug fix. The trainer.py call at line 1039 omits `dates`+`directions` kwargs, causing MC permutation and White RC to abstain unconditionally per `promotion_gate_helpers.py:121-131 / 178-188`. Lines 975-976 also pre-subtract a `rf_placeholder=0.0001` which would double-count once `dates` flows to FRED via `_adjust_returns_via_fred` (helpers.py:225). Cadence was pinned to watch.py daily slot (Decision 3); trainer feeds inputs to the gate, it does not drive gate decisions. The bug is in scope because the daily gate consumes trainer-emitted artifacts and unconditional abstentions would corrupt evidence. **Per operator Choice A (2026-05-05): T3 fixes input quality but does NOT enable promote decisions from the trainer/kpi call paths — see spec §1.3.1 'Sprint 2 limitations' for why (long-only directions render MC permutation degenerate, capping ceiling at 3-of-5 votes). Promote-capable evaluation runs via watch.py (T4) where candidate_pool is available.** |
| 13 | promote() re-fires check_promotion_gate server-side as a redundant safety check. | Defense in depth. Even if the CLI's staleness guard or justification check is bypassed, the server-side re-fire catches data drift between proposal and confirm. This is the existing behavior of promote() at line 409 — preserving it is non-negotiable. |
| 14 | Stale-proposal guard at 24h. | Proposals are generated daily; a >24h-old proposal means the operator missed a trading day's worth of new data. The CLI rejects with exit 4 and asks the operator to wait for tomorrow's gate. Server-side promote() re-fire is the authoritative check; the staleness guard is operator-ergonomic. |
| 15 | Test plan is a behavior-coverage list of named tests; count is derived, not target. | Major 8 fix: a count target (12-18 tests) could land entirely on happy paths. Naming each test 1:1 to a critical safety property ensures coverage of the actual correctness conditions. |
| 16 | Override metadata (override_by, override_reason) lives as JSON keys in gate_result_json, NOT as new columns. | Major 4 conformance: no new columns on strategy_promotion_events. JSON keys are sufficient for read-side dashboard rendering and audit-log searches; SQL filtering on override_by is rare enough that JSON is acceptable. |
| 17 | AND-composition is implemented at the existing return points of _evaluate_shadow_trading_gate / _evaluate_production_gate, not by wrapping check_promotion_gate. | Wrapping check_promotion_gate would create a second dispatcher and split the call graph. Inserting AND-composition at the existing return points is a minimal change that preserves the dispatcher's structure and naturally inherits the existing audit-row behavior. |
