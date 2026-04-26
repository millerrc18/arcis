# B3 — Exit-Reason Taxonomy: Pass 1 Design
**Track:** 1.5 | **Block:** B3 | **Pass:** 1 (DESIGN ONLY — no code, no tests)
**Date:** 2026-04-25

---

## 1. Current `exit_reason` Distribution (Archive DB)

Archive: `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3`
Total `shadow_trades` rows: **320**

| `exit_reason` value | Count | Closed | Open/Other | Code path that writes it | Inferred semantic |
|---|---|---|---|---|---|
| `NULL` | 162 | 0 | 7 open, 155 non-closed | Multiple paths; open/active trades have no exit yet | Trade not yet closed, or entry rejected without an exit tag |
| `reconciled_stale` | 72 | 72 | 0 | `src/shadow_trading/reconcile.py:329, 663, 815` | Reconciler force-closed a trade that had no matching Alpaca position |
| `order_rejected_buying_power` | 42 | 0 | 42 (status='rejected') | `src/shadow_trading/executor.py:317, 763` — sets `order_type`, not `exit_reason` | Entry was never placed; row marks a rejected entry attempt (buying-power violation) |
| `target_1_hit` | 14 | 13 | 0 | `src/shadow_trading/executor.py:1680` | Exit price crossed first take-profit bracket target |
| `overshoot_covered_post_deploy` | 13 | 13 | 0 | `scripts/cleanup_overshoot_zombies_2026_04_21.py:135` | One-shot ops script retroactively closed overshoot zombies; not a live code path |
| `broker_exception:APIError` | 6 | 6 | 0 | `src/shadow_trading/executor.py:1814` — dynamic string `f"broker_exception:{type(e).__name__}"` | Broker API raised an exception during exit submission |
| `timeout` | 4 | 2 | 0 (1 still-open WMT) | `src/shadow_trading/executor.py:1682` | Trade exceeded `timeout_days` threshold |
| `stop_hit` | 4 | 3 | 0 | `src/shadow_trading/executor.py:1676` | Exit price crossed stop-loss level (price-poll path) |
| `stop_loss` | 1 | 1 | 0 | `src/shadow_trading/executor.py:1631, 1656` — IB/Alpaca bracket leg fill | Bracket leg (stop) filled via broker order event |
| `manual_alpaca_close_op_confirmed` | 1 | 1 | 0 | **Source not found in current src/** — appears to be a one-time CLI/manual DB write | Operator manually closed a position and stamped a reason |
| `exit_overshoot_detected` | 1 | 0 | 1 | `src/shadow_trading/reconcile.py:743` | Reconciler detected a short overshoot; row left in non-terminal state |

**Additional values written by live code paths (not yet present in archive):**

| Value | Code path | Inferred semantic |
|---|---|---|
| `target_2_hit` | `executor.py:1678` | Exit crossed second take-profit level |
| `take_profit` | `executor.py:1631, 1658` — bracket leg fill | Bracket take-profit leg filled via broker event |
| `mr_timeout` | `executor.py:1572` | Mean-reversion strategy timed out |
| `rsi_exit` | `src/features/mean_reversion.py:176` | MR strategy RSI-based exit signal |
| `atr_stop` | `src/features/mean_reversion.py:188` | MR strategy ATR-based stop |
| `late_fill_reconciled` | `executor.py:1229` | Late fill detected and reconciled post-facto |
| `retry_exit` | `executor.py:1365` | Exit re-attempted after earlier failure |
| `qty_mismatch_partial_fill` | `reconcile.py:764` | Quantity mismatch detected during reconciliation |
| `partial_<exit_reason>` | `executor.py:1870` — dynamic prefix | Partial fill recorded; appended to base reason |
| `entry_unfilled_<exit_reason>` | `executor.py:1700` — dynamic prefix | Entry never filled when exit was triggered |

### WMT and GOOG Timeout Verification

Both were tagged `exit_reason='timeout'` as expected.

| Ticker | Entry time | Exit time | Holding days (calculated) | `timeout_days` in row | `duration_days` |
|---|---|---|---|---|---|
| GOOG | 2026-04-15T11:41 | 2026-04-23T11:42 | **8.0** | NULL | 8 |
| WMT | 2026-04-13T09:41 | 2026-04-21T09:43 | **8.0** | NULL | 8 |
| WMT | 2026-04-01T09:35 | NULL (still open) | — | 15 | 8 |

**Findings:**

1. GOOG and the second WMT row held for 8 calendar days. The `timeout_days` column is NULL in both closed rows. The default registry value is `timeout_days INTEGER DEFAULT 15` (`registry.py:229`). Eight calendar days is less than 15 — these trades timed out in fewer than the configured maximum, likely due to market day counting rather than calendar day counting, or `timeout_days` was lowered at entry time (the open WMT row has `timeout_days=15`). Pass 2 should confirm whether `days_open` in the executor uses calendar days or market days.

2. The `duration_days` column already exists on `shadow_trades` and is populated (values of 8 in both closed timeout rows). This is the existing column that records hold duration.

3. The `timeout_days` column also exists on `shadow_trades` but is NULL in many closed rows, meaning the configured timeout at entry time was not always persisted.

---

## 2. Controlled Vocabulary Design

### Proposed Vocab vs. Existing Production Values

The sprint proposed: `target_1`, `target_2`, `stop_loss`, `timeout`, `manual`, `error`, `unknown`.

**Analysis of conflicts and gaps:**

| Sprint proposal | Production-written value | Relationship | Recommendation |
|---|---|---|---|
| `target_1` | `target_1_hit` | Synonyms — `_hit` suffix adds no information | **Standardize to `target_1`** |
| `target_2` | `target_2_hit` | Synonyms | **Standardize to `target_2`** |
| `stop_loss` | `stop_hit`, `stop_loss` | Two values for same semantic — `stop_hit` = price-poll path, `stop_loss` = bracket leg fill path | **Standardize to `stop_loss`** |
| `timeout` | `timeout` | Match | **Keep** |
| `manual` | `manual_alpaca_close_op_confirmed` | Superset — the production value encodes extra info in the string | **`manual` as canonical; notes go to logs, not the column** |
| `error` | `broker_exception:APIError`, `exit_overshoot_detected`, `reconciled_stale` | Production splits "error" into distinct sub-types; sprint lumps them | **See sub-type recommendation below** |
| `unknown` | NULL (162 rows) | NULL and `unknown` are different states | **Keep `unknown` as explicit string; NULL means not-yet-closed** |

### Recommended Final Vocabulary

```
CONTROLLED_VOCAB = {
    "target_1",       # Exit price crossed first take-profit level
    "target_2",       # Exit price crossed second take-profit level
    "stop_loss",      # Exit price crossed stop level (price-poll OR bracket leg)
    "timeout",        # Trade exceeded timeout_days threshold
    "manual",         # Operator-initiated close
    "reconciled",     # Reconciler force-closed a stale/orphaned trade
    "error",          # Broker exception, overshoot, or unrecoverable state
    "unknown",        # Exit reason could not be determined
}
```

**Rationale per term:**

- `target_1` / `target_2`: Merge the `_hit` suffix. The suffix is redundant — if the trade closed at that level, it was obviously "hit." `analytics.py:520` already checks for `("target_1_hit", "target_2_hit", "target_1", "target_2")` showing the codebase already handles both spellings.

- `stop_loss`: Merge `stop_hit` and `stop_loss`. `reconcile.py:115` already treats them as synonyms in `_resolve_stuck_pnl`. Unifying eliminates the branch.

- `timeout`: No change. Already canonical and consistent with `mr_timeout` (which becomes `timeout` after coercion — see below).

- `manual`: Replace the verbose `manual_alpaca_close_op_confirmed`. Additional operator context (which broker, which operation) belongs in a log line, not encoded into the column value.

- `reconciled`: Rename `reconciled_stale`. "Stale" is an implementation detail of why reconciliation was triggered. The canonical meaning is "reconciler closed this because the system state was inconsistent." This is not an `error` — reconciliation is an expected recovery path, not a failure.

- `error`: Umbrella for `broker_exception:*`, `exit_overshoot_detected`, `qty_mismatch_partial_fill`, and any future unrecoverable states. The current `broker_exception:APIError` pattern embeds the Python class name into the value — this makes SQL `GROUP BY` and dashboard aggregation unreliable (every exception type becomes a unique row). The exception detail belongs in logs, not in the column.

- `unknown`: Explicit fallback for values that cannot be coerced. Semantically distinct from NULL (which means the trade has not exited yet). Forward-only: existing NULL rows stay NULL.

**MR-specific values:**

`mr_timeout` → coerce to `timeout`. A mean-reversion timeout is still a timeout.
`rsi_exit` → coerce to `target_1` (RSI crossing back = hitting a signal-based profit target). This is debatable; if MR exits need to be analytically separate, add `mr_exit` to the vocab. Recommendation: keep the vocab small and add MR-specific fields to `shadow_trades` (e.g., `strategy_type` already exists) rather than multiplying exit_reason values. **Final call: coerce `rsi_exit` and `atr_stop` to `target_1` and `stop_loss` respectively.**

**Partial and dynamic-string values:**

`partial_<exit_reason>`, `entry_unfilled_<exit_reason>`, `broker_exception:*`, `late_fill_reconciled`, `retry_exit` — these are transient states written to non-terminal rows (status=`exit_pending`, `exit_failed`) or intermediate states. They are **not** final closed-trade exit reasons. The reconciliation pass should only evaluate `exit_reason` on rows with `status='closed'`. Transient values in non-closed rows are out of scope for the taxonomy enforcement.

`overshoot_covered_post_deploy` — one-shot ops script; pre-existing value preserved per backward-compatibility contract (see section 8). Coerce to `error` on future writes if this path were to recur.

**Values to preserve as-is (no coercion, no deletion):** `order_rejected_buying_power` — this is set on `order_type`, not `exit_reason`, for `status='rejected'` rows. These rows never entered the bracket; they are entry failures, not exit events. The taxonomy applies only to closed-trade `exit_reason` values.

---

## 3. Holding-Days Decision

### Option A: Add `holding_days` INTEGER column (schema-add via `registry.py`)

**Pros:**
- Directly queryable: `WHERE holding_days >= 8`
- Writer (executor.py) can set it once at close time; no downstream computation needed
- Reconciliation pass can read it directly without parsing ISO timestamp strings

**Cons:**
- Redundant: `duration_days` **already exists** on `shadow_trades` and is already being written by the executor (`executor.py:2034` passes `days_open`). The archive confirms values of 8 in both GOOG and WMT timeout rows.
- A second "holding days" column with a different name creates confusion and potential inconsistency.

### Option B: Compute from `actual_entry_time` / `actual_exit_time` at query time

**Pros:**
- No schema change
- `duration_days` already gives the pre-computed version

**Cons:**
- Every new consumer query becomes more complex
- Requires parsing timezone-aware ISO strings in SQL

### Recommendation: **Use existing `duration_days` column — no schema add required**

`duration_days` already serves the purpose of `holding_days`. The column exists, is populated, and is an INTEGER (`registry.py:222`). Pass 2 should use `duration_days` wherever the reconciliation pass needs "days held."

If the column is sometimes NULL on timeout rows (the open WMT row shows `duration_days=8` even without an `actual_exit_time`, suggesting executor writes it pre-close), the reconciliation pass should fall back to:
```sql
COALESCE(duration_days, CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER))
```

**Action for Pass 2:** Document that `duration_days` = `holding_days` in the reconciliation pass. No `ALTER TABLE` or schema add. This saves one file from the Pass 2 scope.

---

## 4. Validation Contract (Writer-Side)

### Helper module: `src/shadow_trading/exit_reason.py` (NEW)

```python
CONTROLLED_VOCAB = frozenset({
    "target_1", "target_2", "stop_loss", "timeout",
    "manual", "reconciled", "error", "unknown",
})

def coerce_exit_reason(value: str, ticker: str = "") -> str:
    """Return value if in vocab, else log warning and return 'unknown'."""
    if value in CONTROLLED_VOCAB:
        return value
    logger.warning(
        "[EXIT_REASON_INVALID] received=%r ticker=%s fallback=unknown",
        value, ticker,
    )
    return "unknown"
```

**Log format** (exact): `[EXIT_REASON_INVALID] received={value!r} ticker={ticker} fallback=unknown`

The module also exposes a `LEGACY_COERCIONS` dict for the known synonym mappings:

```python
LEGACY_COERCIONS = {
    "target_1_hit": "target_1",
    "target_2_hit": "target_2",
    "stop_hit": "stop_loss",
    "take_profit": "target_1",       # bracket leg take-profit
    "reconciled_stale": "reconciled",
    "mr_timeout": "timeout",
    "rsi_exit": "target_1",
    "atr_stop": "stop_loss",
    "late_fill_reconciled": "reconciled",
    "manual_alpaca_close_op_confirmed": "manual",
}
```

`coerce_exit_reason` checks `LEGACY_COERCIONS` before the vocab check, so known synonyms map silently (no warning). Unknown values fall through to the warning + `'unknown'` path.

### Call sites that write `exit_reason` to `shadow_trades`

Every site below must route through `coerce_exit_reason` before the DB write. The table covers all paths identified from the grep above:

| File | Line(s) | Current value written | Action |
|---|---|---|---|
| `src/shadow_trading/executor.py` | 1676 | `"stop_hit"` | Route through `coerce_exit_reason` → maps to `"stop_loss"` |
| `src/shadow_trading/executor.py` | 1678 | `"target_2_hit"` | Route through `coerce_exit_reason` → maps to `"target_2"` |
| `src/shadow_trading/executor.py` | 1680 | `"target_1_hit"` | Route through `coerce_exit_reason` → maps to `"target_1"` |
| `src/shadow_trading/executor.py` | 1682 | `"timeout"` | Route through `coerce_exit_reason` → no change |
| `src/shadow_trading/executor.py` | 1572 | `"mr_timeout"` | Route through `coerce_exit_reason` → maps to `"timeout"` |
| `src/shadow_trading/executor.py` | 1537 | `mr_exit["exit_reason"]` (from mean_reversion) | Route through `coerce_exit_reason` → maps `"rsi_exit"` / `"atr_stop"` |
| `src/shadow_trading/executor.py` | 1631, 1656, 1658 | `"take_profit"` / `"stop_loss"` | Route through `coerce_exit_reason` → `"take_profit"` maps to `"target_1"` |
| `src/shadow_trading/executor.py` | 1814 | `f"broker_exception:{type(e).__name__}"` | Route through `coerce_exit_reason` → logs warning, returns `"error"` |
| `src/shadow_trading/executor.py` | 1229 | `"late_fill_reconciled"` | Route through `coerce_exit_reason` → maps to `"reconciled"` |
| `src/shadow_trading/executor.py` | 1365 | `"retry_exit"` | **Exempt**: this is written to a non-terminal row (`status='exit_failed'`); coercion applies only when the trade actually closes. Note in code. |
| `src/shadow_trading/executor.py` | 1700 | `f"entry_unfilled_{exit_reason}"` | **Exempt**: written to `status='cancelled'` rows, not closed trades. Note in code. |
| `src/shadow_trading/executor.py` | 1870 | `f"partial_{exit_reason}"` | **Exempt**: written to `status='open'` partial-fill rows awaiting re-exit. Note in code. |
| `src/shadow_trading/reconcile.py` | 329, 663, 815 | `"reconciled_stale"` | Route through `coerce_exit_reason` → maps to `"reconciled"` |
| `src/shadow_trading/reconcile.py` | 743 | `"exit_overshoot_detected"` | Route through `coerce_exit_reason` → logs warning (not in `LEGACY_COERCIONS`), returns `"error"` |
| `src/shadow_trading/reconcile.py` | 764 | `"qty_mismatch_partial_fill"` | Route through `coerce_exit_reason` → logs warning, returns `"error"` |
| `src/cli/commands.py` | 231, 416 | `reason` (operator-supplied string) | Route through `coerce_exit_reason` → unknown operator strings return `"unknown"` |
| `src/api/routes/shadow.py` | 122, 141 | `reason` (API-supplied string) | Route through `coerce_exit_reason` → unknown strings return `"unknown"` |
| `src/journal/store.py` | 366, 409 | `exit_reason: str` parameter | Route through `coerce_exit_reason` at each call site OR at the `store.py` function boundary |
| `src/features/mean_reversion.py` | 176, 188 | `"rsi_exit"`, `"atr_stop"` | Route through `coerce_exit_reason` at the point executor reads these values (already handled above at `executor.py:1537`) |

**Note on `journal/store.py`:** The two functions `close_shadow_trade` (line 366) and `update_shadow_trade` (line 409) accept `exit_reason` as a parameter. The cleanest enforcement point is at these function boundaries — apply `coerce_exit_reason` at the start of each function so all callers are covered automatically. This avoids having to patch every call site.

---

## 5. Reconciliation Design (Nightly Pass)

### Where to add: Extend `src/scheduler/watch.py` daily audit

**Recommendation: Extend `watch.py`'s existing `_run_daily_audit` method, not a new script.**

Rationale:
- `watch.py` already has a `_daily_audit_done` flag and a 4:15 PM ET slot for `_run_daily_audit` (line 1429). The audit infrastructure is in place.
- A new `scripts/reconcile_exits.py` would require operators to remember to run it, add it to the NSSM service configuration, and handle its failure modes separately. The watch loop already has `_safe_run` with per-task exponential backoff.
- The reconciliation pass is lightweight (SQL queries + logging) and fits within the existing audit window.

**Implementation path:** `src/scheduler/overnight.py` → `run_daily_audit()` calls a new `run_exit_reconciliation()` function imported from a new module `src/shadow_trading/exit_reconciliation.py`.

### Reconciliation predicate per closed trade (last 24h)

Query scope: `status='closed' AND actual_exit_time >= datetime('now', '-24 hours') AND COALESCE(quarantined, 0) = 0`

**Per-reason checks:**

| `exit_reason` | Check | Flag condition |
|---|---|---|
| `target_1` | `actual_exit_price >= target_1` | `actual_exit_price < target_1` (exit below first target) |
| `target_2` | `actual_exit_price >= target_2` (where `target_2 > 0`) | `actual_exit_price < target_2` AND `target_2 > 0` |
| `stop_loss` | `actual_exit_price <= stop_price` (where `stop_price > 0`) | `actual_exit_price > stop_price * 1.01` (allow 1% slippage tolerance) |
| `timeout` | `COALESCE(duration_days, ...) >= COALESCE(timeout_days, 15)` | Holding days materially less than `timeout_days` |

> **B8 coordination (added 2026-04-25):** Post-B8, `shadow_trades.timeout_days` is reliably populated at trade-open time (executor stamps either the LLM's `llm_timeout_days` or the global default 15). The `COALESCE(timeout_days, 15)` fallback shown above is therefore a backward-compat shim for pre-B8 rows only. For post-B8 trades, the predicate effectively becomes `COALESCE(duration_days, ...) >= shadow_trades.timeout_days` (no fallback needed). This means the WMT/GOOG-style ambiguity ("did this trade time out at 8 days because the LLM said 8 days, or because of a calendar/market-day bug?") becomes answerable: the LLM's expected window is now persisted alongside the realized window. See `B8_llm_timeout_days.md` for the full design.
| `reconciled` | No price check — count only | — |
| `manual` | No price check — count only | — |
| `error` | No price check — count only | — |
| `unknown` | No price check — count only | — |

**Slippage tolerance:** The stop_loss check uses a 1% tolerance buffer because gap-down opens and order routing can cause fills 1-3% beyond the stop level. Flagging stop-hit trades where exit was 5% above stop is the real anomaly.

**Bracket check caveat:** For `target_1` and `target_2`, the check requires `target_1` / `target_2` columns to be non-NULL. If they are NULL (orphaned backfilled rows), skip the price check and just count. Log a `[RECONCILE_SKIP]` warning for NULL-bracket rows.

### Output

```python
{
    "reconciliation_date": "2026-04-25",
    "window_hours": 24,
    "total_closed": int,
    "anomaly_count": int,
    "flagged_trade_ids": list[str],
    "by_reason": {
        "target_1": {"checked": int, "anomalies": int},
        "target_2": {"checked": int, "anomalies": int},
        "stop_loss": {"checked": int, "anomalies": int},
        "timeout": {"checked": int, "anomalies": int},
        "reconciled": {"checked": int},
        "manual": {"checked": int},
        "error": {"checked": int},
        "unknown": {"checked": int},
    }
}
```

This dict is:
1. Logged at INFO level with `[EXIT_RECONCILE]` prefix
2. Written to a `reconciliation_results` table (if Pass 2 adds it — see scope fence) OR logged only (MVP)
3. Emitted as a dashboard data hook: the watch loop's existing `_get_live_stats()` dict is extended with `"exit_anomalies_24h": result["anomaly_count"]` — no dashboard widget implementation now, just the data in the stats dict that the frontend can read when ready.

For flagged trades, individual log lines:
```
[EXIT_RECONCILE_ANOMALY] trade_id={id} ticker={ticker} exit_reason={reason} exit_price={price} expected_range=({low}, {high})
```

---

## 6. Test Strategy

### Test file 1: `tests/shadow_trading/test_exit_reason_taxonomy.py`

Tests for `src/shadow_trading/exit_reason.py`:

| Test name | What it asserts |
|---|---|
| `test_vocab_values_pass_through` | Each of the 8 vocab strings returns unchanged from `coerce_exit_reason` |
| `test_legacy_synonym_target_1_hit` | `"target_1_hit"` → `"target_1"` with no warning logged |
| `test_legacy_synonym_target_2_hit` | `"target_2_hit"` → `"target_2"` with no warning |
| `test_legacy_synonym_stop_hit` | `"stop_hit"` → `"stop_loss"` with no warning |
| `test_legacy_synonym_take_profit` | `"take_profit"` → `"target_1"` with no warning |
| `test_legacy_synonym_reconciled_stale` | `"reconciled_stale"` → `"reconciled"` with no warning |
| `test_legacy_synonym_mr_timeout` | `"mr_timeout"` → `"timeout"` with no warning |
| `test_legacy_synonym_rsi_exit` | `"rsi_exit"` → `"target_1"` with no warning |
| `test_legacy_synonym_atr_stop` | `"atr_stop"` → `"stop_loss"` with no warning |
| `test_out_of_vocab_returns_unknown` | `"foo_bar"` → `"unknown"` |
| `test_out_of_vocab_logs_warning` | `"foo_bar"` triggers a WARNING log containing `[EXIT_REASON_INVALID]`, `received='foo_bar'`, `fallback=unknown` |
| `test_out_of_vocab_includes_ticker_in_log` | Warning log includes the passed `ticker` value |
| `test_broker_exception_dynamic_string` | `"broker_exception:APIError"` → `"unknown"` (not in vocab, not in coercions) with warning |
| `test_empty_string_returns_unknown` | `""` → `"unknown"` with warning |
| `test_none_string_returns_unknown` | `None` coerced to string → `"unknown"` (or raises TypeError — specify the contract) |

### Test file 2: `tests/scheduler/test_exit_reconciliation.py`

Tests for `src/shadow_trading/exit_reconciliation.py`:

Fixtures: in-memory SQLite DB seeded with synthetic `shadow_trades` rows.

| Test name | Fixture | What it asserts |
|---|---|---|
| `test_target_1_clean` | exit_reason='target_1', exit_price=120, target_1=119 | No anomaly flagged |
| `test_target_1_anomaly` | exit_reason='target_1', exit_price=115, target_1=119 | Anomaly flagged; trade_id in `flagged_trade_ids` |
| `test_target_2_clean` | exit_reason='target_2', exit_price=130, target_2=128 | No anomaly |
| `test_target_2_anomaly` | exit_reason='target_2', exit_price=125, target_2=128 | Anomaly flagged |
| `test_stop_loss_clean` | exit_reason='stop_loss', exit_price=95, stop_price=96 | No anomaly (within tolerance) |
| `test_stop_loss_anomaly` | exit_reason='stop_loss', exit_price=105, stop_price=96 | Anomaly flagged (exit well above stop) |
| `test_timeout_clean` | exit_reason='timeout', duration_days=8, timeout_days=8 | No anomaly |
| `test_timeout_anomaly` | exit_reason='timeout', duration_days=3, timeout_days=15 | Anomaly flagged |
| `test_timeout_null_duration_uses_fallback` | exit_reason='timeout', duration_days=NULL, actual_entry_time set to 10 days ago | No anomaly (computed fallback ≥ timeout_days default) |
| `test_manual_no_check` | exit_reason='manual' | No anomaly regardless of prices |
| `test_reconciled_no_check` | exit_reason='reconciled' | No anomaly regardless of prices |
| `test_error_no_check` | exit_reason='error' | No anomaly |
| `test_unknown_no_check` | exit_reason='unknown' | No anomaly |
| `test_null_bracket_skipped` | exit_reason='target_1', target_1=NULL | No anomaly (skipped with RECONCILE_SKIP log) |
| `test_output_structure` | Mixed fixture | Result dict has all required keys: `reconciliation_date`, `anomaly_count`, `flagged_trade_ids`, `by_reason` |
| `test_only_last_24h` | One row from 48h ago, one from 12h ago | Only the 12h row is checked |
| `test_quarantined_excluded` | quarantined=1 | Row excluded from reconciliation |

---

## 7. Scope Fence — Files Pass 2 Will Touch

Based on the design above, Pass 2 scope is:

| File | Change type | Why |
|---|---|---|
| `src/shadow_trading/exit_reason.py` | **NEW** | Vocabulary module + `coerce_exit_reason` helper |
| `src/shadow_trading/exit_reconciliation.py` | **NEW** | Nightly reconciliation pass logic |
| `src/shadow_trading/executor.py` | MODIFY | Route exit_reason writes through `coerce_exit_reason` at ~12 call sites |
| `src/shadow_trading/reconcile.py` | MODIFY | Route `reconciled_stale`, `exit_overshoot_detected`, `qty_mismatch_partial_fill` through coerce |
| `src/scheduler/overnight.py` | MODIFY | Call `run_exit_reconciliation()` from `run_daily_audit()` |
| `src/journal/store.py` | MODIFY | Apply `coerce_exit_reason` at `close_shadow_trade` / `update_shadow_trade` function boundary |
| `src/cli/commands.py` | MODIFY | Route operator-supplied `reason` through `coerce_exit_reason` |
| `src/api/routes/shadow.py` | MODIFY | Route API-supplied `reason` through `coerce_exit_reason` |
| `tests/shadow_trading/test_exit_reason_taxonomy.py` | **NEW** | 15 tests for vocabulary module |
| `tests/scheduler/test_exit_reconciliation.py` | **NEW** | 17 tests for reconciliation pass |

**Total: 8 existing files modified + 4 new files = 12 file changes.**

**`src/schema/registry.py` is NOT in Pass 2 scope.** No schema add is required because `duration_days` already exists and will be used for holding-day comparisons.

**`scripts/reconcile_exits.py` will NOT be created.** The reconciliation pass is wired into `watch.py`'s existing daily audit slot via `overnight.py`.

**`src/features/mean_reversion.py` is NOT in scope.** The `rsi_exit` / `atr_stop` values it emits are coerced when the executor reads them at `executor.py:1537`, not at the source. This avoids modifying the feature module.

---

## 8. Backward-Compatibility

**Critical requirement (from sprint spec): Do not delete existing rows with non-conforming values.**

The design satisfies this as follows:

1. **`coerce_exit_reason` is forward-only.** It is called only at write time — when a trade is being closed or updated. It does not retroactively scan or update existing rows.

2. **The reconciliation pass reads `exit_reason` as-is.** When a pre-existing row with `exit_reason='reconciled_stale'` is within the 24-hour window (unlikely given the archive date, but possible in production), the reconciler's per-reason dispatch table includes `reconciled_stale` as an alias for `reconciled` in the "no price check" bucket. Pre-existing values in the "count only" category (manual, reconciled, error, unknown) are never flagged for anomalies regardless of the string form.

3. **Analytics code continues to work.** `analytics.py:520` already checks for both `"target_1_hit"` and `"target_1"` in the same list. After coercion is in place, only new writes will produce `"target_1"`; old rows retain `"target_1_hit"`. The analytics query handles both.

4. **The 162 NULL rows are left untouched.** NULL means "not yet closed" — it is not a vocabulary violation. The enforcement applies only to the string value when a trade is being closed.

5. **`overshoot_covered_post_deploy` (13 rows), `manual_alpaca_close_op_confirmed` (1 row)** — these are pre-existing one-time-op values. They are archived data that will never be re-written. They stay in the DB unchanged. The reconciliation pass treats them as `"error"` and `"manual"` semantically when dispatching, without modifying the stored value.

6. **`order_rejected_buying_power` (42 rows, status='rejected')** — these are not exit events; they are entry-rejection records. The taxonomy does not apply to non-closed rows without an exit. These rows are excluded from reconciliation scope (`status='closed'` filter).

---

## Summary Answers to PM Checklist

**Q: Were WMT and GOOG tagged as `'timeout'`?**
Yes. Two WMT rows and one GOOG row carry `exit_reason='timeout'`. The closed timeout trades held for 8 calendar days. `timeout_days` is NULL in the closed rows, and the registry default is 15 — this discrepancy (8 < 15) should be investigated in Pass 2 (possible that the executor uses market days, or `timeout_days` was overridden at entry for those trades).

**Q: Holding-days schema add decision?**
No schema add. `duration_days` (INTEGER) already exists and is populated. Pass 2 uses `COALESCE(duration_days, computed_fallback)`.

**Q: Recommended reconciliation home?**
Extend `watch.py` daily audit via `overnight.py::run_daily_audit()` → new `src/shadow_trading/exit_reconciliation.py`. No new `scripts/` file.
