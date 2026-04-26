# B5 — Instrumentation Version Sentinel: Pass 1 Design

**Task:** Track-1.5 / B5
**Pass:** 1 (Design Only — no code changes)
**Date:** 2026-04-25
**Author:** AI session (Pass 1 investigation)

---

## 1. Decision — INTEGER vs JSON `data_quality_flags`

**Decision: INTEGER. `data_quality_flags` (JSON) is rejected.**

### Rationale

A JSON column would require callers to deserialize a string to test a single condition (e.g., `json.loads(row["data_quality_flags"]).get("instrumentation_version")`). Every filter, index lookup, and GROUP BY would require either a virtual column or a function-wrapped expression. SQLite has no generated-column syntax compatible with our current registry pattern, so JSON imposes:

1. No direct indexability of the version value.
2. Caller-side deserialization in every analytics query.
3. Schema drift risk — future developers stuffing unrelated flags into the same blob.

An INTEGER column is directly filterable (`WHERE instrumentation_version >= 3`), indexable, and unambiguous. Cardinality is low (4 values today, unlikely to exceed 10 over the system's lifetime). The sprint recommendation of INTEGER is validated.

---

## 2. Version Schema

| Value | Name | Meaning |
|-------|------|---------|
| `0` | `quarantined` | Row exists but is marked do-not-use. Equivalent to `quarantined=1`. These rows predate trade #651 — the April 10 cascade event. |
| `1` | `pre_conviction` | Opened before 2026-04-09. Conviction (`llm_conviction`) is NULL. Entry/exit slippage may be absent. |
| `2` | `conviction_only` | Opened 2026-04-09 or later, before Track-1.5 merge. `llm_conviction` (integer) is present. `llm_conviction_reason` is NULL. `exit_slippage_bps` is populated only for the subset of trades where `alpaca_adapter` wrote it (regression-era case; see B1 design). |
| `3` | `full_instrumentation` | Opened after Track-1.5 merges to main. All B1 + B3 + B4 fields are populated. See cross-references below. |

### What "v3" Requires (Cross-References to Companion Designs)

A trade with `instrumentation_version = 3` must have been opened under a writer that satisfied all of the following Track-1.5 deliverables:

- **B1 (exit slippage persistence):** `exit_slippage_bps` and `signal_exit_price` are written at close. See `B1_exit_slippage.md` — the fix is an extension to the post-close `update_shadow_trade` call at `executor.py:1956–1964`.
- **B3 (conviction reason persistence):** `llm_conviction_reason` is written at trade open. B3 design doc will specify the exact `trade_data` key written by `open_shadow_trade`.
- **B4 (reconciled exit_reason):** `exit_reason` values are reconciled to a canonical taxonomy at close. B4 design doc will specify the canonicalization logic in `executor.py`.

Pass 2 will NOT stamp `instrumentation_version = 3` unless B1, B3, and B4 are merged. The writer stamp (`instrumentation_version = INSTRUMENTATION_VERSION_CURRENT`) is a constant set in `executor.py`; until all three are merged, the constant remains at 2 (or the column does not exist). Pass 2 sets it to 3 as part of this task.

### Column DDL Target

```
ColumnDef("instrumentation_version", "INTEGER", nullable=False, default="3",
          description="Era flag: 0=quarantined/pre-651, 1=pre-April-9 (no conviction), "
                      "2=April-9-to-Track-1.5 (conviction integer only), "
                      "3=post-Track-1.5 (B1+B3+B4 fully populated). "
                      "NOT NULL DEFAULT 3 so new rows from the current writer "
                      "are always stamped without an explicit write.")
```

`NOT NULL DEFAULT 3` is correct: any new `INSERT` that does not supply the column receives version=3, which is the correct assumption for all post-Track-1.5 writers.

---

## 3. Version-to-Feature Matrix

This matrix is the source of truth for `docs/instrumentation_versions.md` (B7, Pass 3 will lift it verbatim).

| Field | v0 | v1 | v2 | v3 |
|-------|----|----|----|----|
| Row valid for analytics | No (quarantined=1) | Yes, with caveats | Yes | Yes |
| `llm_conviction` | NULL | NULL | Populated (integer) | Populated (integer) |
| `llm_conviction_reason` | NULL | NULL | NULL | Populated (text) |
| `exit_slippage_bps` | NULL | NULL | Populated only for regression-era alpaca writes; otherwise NULL | Populated (NULL only when fill price unavailable) |
| `signal_exit_price` | NULL | NULL | NULL | Populated (NULL only when fill price unavailable) |
| `exit_reason` | NULL or raw | Raw (non-canonical) | Raw (non-canonical) | Canonical taxonomy (B4) |
| `actual_entry_time` | May be NULL | Present | Present | Present |
| `actual_exit_time` | May be NULL | Present when closed | Present when closed | Present when closed |
| `pnl_pct` | NULL or wrong | Present | Present | Present |
| `excess_return` | NULL | May be NULL | Present | Present |

**Analytics rule:** Any query producing a performance figure (Sharpe, win rate, average P&L) MUST filter to `instrumentation_version >= 3` to produce interpretable results. Filtering to `>= 2` is permissible for conviction-stratified analysis that does not depend on `exit_slippage_bps` or `exit_reason` taxonomy. Version 1 trades are usable only for pre-conviction baseline comparisons. Version 0 rows are never usable.

---

## 4. Backfill Design

### Target

The **current DB only** (`C:/arcis/data/ai_research_desk.sqlite3`). Per PM decision, the archive DB at `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3` is the immutable audit baseline and MUST NOT be modified by this sprint.

### Backfill SQL

```sql
UPDATE shadow_trades
SET instrumentation_version = CASE
    WHEN COALESCE(quarantined, 0) = 1       THEN 0
    WHEN actual_entry_time < '2026-04-09'   THEN 1
    WHEN actual_entry_time < '<TRACK_1_5_MERGE_DATE>' THEN 2
    ELSE 3
END
WHERE instrumentation_version IS NULL;
```

`<TRACK_1_5_MERGE_DATE>` is filled in by Pass 2 at execution time (the merge date of this sprint to main). Because the column DEFAULT is 3, the `ELSE 3` branch handles any row whose `actual_entry_time` falls on or after the merge — i.e., rows opened by a post-Track-1.5 writer that did not explicitly write the column (this should not occur given DEFAULT 3, but the backfill is belt-and-braces for any edge case where `actual_entry_time` is present but the writer pre-dated the column addition).

### Current DB Behavior

**If executed against the current DB (0 rows post-archive), this is a no-op.** The script must log:

```
backfill: 0 rows updated; this is expected if the DB is post-archive fresh state
```

This log message is mandatory per sprint risk #3 so the operator can distinguish "no rows needed updating" from "the script failed silently."

### Archive DB Note

**If this SQL were executed against the archive DB (320 rows), it would correctly classify them** — quarantined rows to v0, pre-April-9 rows to v1, April-9-to-archive rows to v2, and any remainder to v3. However, per PM decision, the archive is NOT modified by this sprint. The archive's `instrumentation_version` column will remain absent (NULL for all rows) and serves purely as an audit baseline.

### Backfill Script

`scripts/backfill_instrumentation_version.py` (NEW in Pass 2). Single responsibility: apply the SQL above, log the row count, exit. No other writes.

---

## 5. Helper Design — `filter_to_version`

### Module

`src/analytics/instrumentation.py` (NEW file — distinct from the existing `src/analytics/instrumentation_filter.py` which handles the pre-v3 era's four-column completeness check).

**Naming note:** The existing `instrumentation_filter.py` implements `is_fully_instrumented` / `filter_fully_instrumented` based on the four legacy columns (`pnl_pct`, `actual_entry_time`, `actual_exit_time`, `excess_return`). The new module owns the version-integer filter. Pass 2 must not modify `instrumentation_filter.py`.

### Function Signature

```python
def filter_to_version(
    trades: list[dict] | "pd.DataFrame",
    min_version: int = 3,
) -> list[dict] | "pd.DataFrame":
    """Return the subset of rows where instrumentation_version >= min_version.

    Accepts either a pandas DataFrame or a list of dicts (caller-friendly).
    Returns the same type as the input.
    Missing or NULL instrumentation_version is treated as version 0 (excluded
    by default).

    Default min_version=3: Stage-2 onward analytics demand full instrumentation.
    Pass min_version=2 for conviction-stratified analysis that accepts missing
    exit_slippage_bps.
    """
```

### Behavior Notes

- If `instrumentation_version` is absent from a row (NULL in DB, or the key is missing from the dict), treat it as version 0. This means pre-column rows are always excluded, which is the correct default — pre-Track-1.5 rows that were never backfilled have no version stamp and are not trusted.
- Returns the same container type as input: `list[dict]` in → `list[dict]` out; `pd.DataFrame` in → `pd.DataFrame` out (filtered, index preserved).
- Does NOT modify the input in-place.
- `pandas` is an optional import — the function must not `import pandas` unconditionally. It should detect the type and only import if a DataFrame is passed. This keeps the module importable in environments where pandas is absent (e.g., unit tests that use list-of-dicts).

### Scope Fence

`filter_to_version` is a downstream helper. Pass 2 does NOT modify any existing analytics query to use it. The function is shipped as a building block; wiring it into the query layer is a separate task outside this sprint.

---

## 6. Test Strategy

**Test file:** `tests/test_instrumentation_version.py` (NEW)

### Test Cases

#### T1 — Backfill Correctness

Synthetic fixture: 4 rows representing v0–v3 boundary conditions.

| row | quarantined | actual_entry_time | expected version |
|-----|-------------|------------------|-----------------|
| A | 1 | 2026-04-05 | 0 |
| B | 0 | 2026-04-07 | 1 |
| C | 0 | 2026-04-12 | 2 |
| D | 0 | `<today or after merge date>` | 3 |

Test: apply backfill SQL against a `tmp_path` SQLite DB seeded with these rows. Assert each row's `instrumentation_version` matches the expected value.

**Edge cases:**
- `quarantined=1` overrides `actual_entry_time` (row A has pre-April-9 time but is v0 due to quarantine).
- `actual_entry_time = NULL` with `quarantined=0` — should fall into ELSE 3 (or a special NULL-handling branch; Pass 2 decides). Document the decision.

#### T2 — New Trade Opens with version=3

Test: call `open_shadow_trade` (or the write path) with a mocked DB. Assert the inserted row has `instrumentation_version = 3`. This test validates the DEFAULT 3 column behavior — the writer does not need to explicitly pass the column; the DB default handles it.

#### T3 — `filter_to_version` Subsets Correctly

Three sub-cases:

1. **Default (min_version=3):** Mix of v0, v1, v2, v3 rows. Assert only v3 rows are returned.
2. **min_version=2:** Assert v2 and v3 rows are returned, v0 and v1 are excluded.
3. **Missing key:** A row with no `instrumentation_version` key is treated as v0, excluded from min_version=3 result.

Test with list-of-dicts input (pandas is optional; include a separate subtest with DataFrame input if pandas is available in the test environment, using a `pytest.importorskip("pandas")` guard).

---

## 7. Scope Fence Verification

### Files Pass 2 Will Touch

| File | Change | Collision Risk |
|------|--------|---------------|
| `src/schema/registry.py` | Add `ColumnDef("instrumentation_version", ...)` to `shadow_trades` table | None — column does not exist |
| `src/shadow_trading/executor.py` | Add `INSTRUMENTATION_VERSION_CURRENT = 3` constant; writer stamps the column at trade open | **See collision risk below** |
| `src/analytics/instrumentation.py` | NEW file — `filter_to_version` function | None |
| `tests/test_instrumentation_version.py` | NEW test file | None |
| `scripts/backfill_instrumentation_version.py` | NEW backfill script | None |

**Total: 5 files. Within sprint scope.**

### Executor.py Collision with B1

**This is the primary risk for Pass 2 ordering.**

B1 (`B1_exit_slippage.md`) also modifies `src/shadow_trading/executor.py`. B1's change is:
- Extends the post-close `update_shadow_trade` dict at `executor.py:1956–1964` to include `signal_exit_price` and `exit_slippage_bps`.
- Changes `exit_slippage_bps = 0.0` initialization to `None` at line 1713.
- Adjusts the fill-detection block at lines 1838–1846.

B5's change to `executor.py` is:
- Adds `INSTRUMENTATION_VERSION_CURRENT = 3` as a module-level constant.
- Stamps `trade_data["instrumentation_version"] = INSTRUMENTATION_VERSION_CURRENT` in `open_shadow_trade` at the `trade_data` assembly point (approximately line 1000–1030 in the trade-open path, alongside `entry_slippage_bps`).

These are **non-overlapping edits** — B1 touches the exit/close path (~line 1713–1964) and B5 touches the open path (~line 1000–1030) plus adds a module-level constant. They can be applied independently without merge conflict.

**Recommended ordering:**

Apply B1 first, then B5. Rationale: B1 is a fix to an existing regression (exit slippage not persisted) and carries higher urgency. B5's stamp is additive. If B5 is applied first, the `INSTRUMENTATION_VERSION_CURRENT = 3` constant will sit in the file without conflict when B1 is applied afterward.

Either order works mechanically. The executor.py collision is **low risk** but must be flagged so the implementing developer reads both design docs before touching the file.

---

## 8. Risks

### R1 — Backfill No-Op Visibility

The backfill is a no-op against the current DB (0 rows). This is intentional. The script MUST log the row count explicitly:

```
backfill_instrumentation_version: 0 rows updated (DB has 0 shadow_trades rows; this is expected post-archive).
```

Without this log, a silent no-op is indistinguishable from a script that silently failed or connected to the wrong DB. The log is mandatory.

### R2 — Archive Immutability

The archive DB will not have `instrumentation_version` populated. Any analytics query run against the archive (e.g., operator runs a one-off Sharpe calculation against the bootcamp data) will see NULL for all rows. `filter_to_version` treats NULL as v0 — which means ALL archive rows are excluded by default when `min_version=3`. This is correct behavior: the archive predates full instrumentation. Operators who need to analyze archive data must either:

1. Use `min_version=1` or `min_version=2` with awareness of the missing fields.
2. Or manually run a read-only version classification on the archive (not writing back).

Document this in `docs/instrumentation_versions.md` (B7/Pass 3).

### R3 — `actual_entry_time` as Classification Key

The backfill uses `actual_entry_time < '2026-04-09'` as the v1/v2 boundary. This is a string comparison in SQLite. SQLite string comparison of ISO-format timestamps is lexicographically correct, so `'2026-04-09T00:00:00' < '2026-04-09'` is FALSE (longer string compares as greater). Pass 2 must use `'2026-04-09'` as the cutoff, which in SQLite string comparison correctly places any timestamp on April 9 or later into the v2 bucket. This is the intended behavior (April 9 was the day conviction instrumentation was added; trades from that day onward have conviction populated).

### R4 — B1/B3/B4 Dependency for v3 Semantic Validity

The `DEFAULT 3` column means the DB and writer will stamp v3 from day one of the column's existence, even if B1/B3/B4 are not yet fully deployed. If B5 is merged before B1, v3-stamped rows will have NULL `exit_slippage_bps` — contradicting the v3 definition. **Pass 2 must merge B1, B3, and B4 before or simultaneously with B5.** If the sprint ordering requires B5 to ship alone, the constant should be set to `INSTRUMENTATION_VERSION_CURRENT = 2` until the other tasks are complete, with a TODO comment. Document this decision at merge time.

### R5 — `filter_to_version` is Shelf (Not Wired)

Per sprint scope fence, Pass 2 does NOT wire `filter_to_version` into any existing analytics query. The function ships but is unused by the production code path. This is consistent with the "shelf" pattern documented in `CLAUDE.md` (see Analytics & Methodology Modules section). The function is available for the operator to invoke manually and for future analytics tasks to adopt.

---

## 9. Summary

B5 delivers two effective outcomes:

1. **Schema + writer:** `instrumentation_version INTEGER NOT NULL DEFAULT 3` on `shadow_trades`. New trades are automatically stamped v3. No writer code change is needed for basic operation (the DEFAULT handles it), but an explicit stamp constant is added to `executor.py` for clarity.

2. **Backfill SQL:** A no-op against the current empty DB, but correctly classifies all 320 archive-era rows if run against the archive (which per PM decision it will not be). The backfill script logs explicitly when it updates 0 rows.

The helper `filter_to_version` ships as a shelf tool for downstream analytics. The executor.py collision with B1 is low risk and resolved by applying B1 first. The critical ordering dependency is that B5 should not stamp `INSTRUMENTATION_VERSION_CURRENT = 3` until B1, B3, and B4 are also merged.
