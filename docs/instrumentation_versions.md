# Instrumentation Versions — `shadow_trades.instrumentation_version`

> **Source of truth for the `instrumentation_version` INTEGER sentinel.** This
> document is referenced from the column description in `src/schema/registry.py`
> and from the B5 design doc (`docs/sprints/track_1_5_pass1_design/B5_instrumentation_version.md`).

---

## Version-to-Feature Matrix

| Field | v0 | v1 | v2 | v3 |
|---|---|---|---|---|
| Row valid for analytics | No (quarantined=1) | Yes, with caveats | Yes | Yes |
| `llm_conviction` | NULL | NULL | Populated (integer) | Populated (integer) |
| `llm_conviction_reason` | NULL | NULL | NULL | Populated (text) |
| `exit_slippage_bps` | NULL | NULL | Populated only for regression-era Alpaca writes; otherwise NULL | Populated (NULL only when fill price unavailable) |
| `signal_exit_price` | NULL | NULL | NULL | Populated (NULL only when fill price unavailable) |
| `exit_reason` | NULL or raw | Raw (non-canonical) | Raw (non-canonical) | Canonical taxonomy (B3) |
| `actual_entry_time` | May be NULL | Present | Present | Present |
| `actual_exit_time` | May be NULL | Present when closed | Present when closed | Present when closed |
| `pnl_pct` | NULL or wrong | Present | Present | Present |
| `excess_return` | NULL | May be NULL | Present | Present |
| `key_risk_assessment` | NULL | NULL | NULL | Populated (text) |
| `expected_holding_period_days` | NULL | NULL | NULL | Populated (integer) |

---

## Version Definitions

| Value | Name | Meaning |
|---|---|---|
| `0` | `quarantined` | Row exists but is marked do-not-use. Equivalent to `quarantined=1`. These rows predate trade #651 — the April 10 cascade event. |
| `1` | `pre_conviction` | Opened before 2026-04-09. `llm_conviction` is NULL. Entry/exit slippage may be absent. |
| `2` | `conviction_only` | Opened 2026-04-09 or later, before Track-1.5 merge. `llm_conviction` (integer) is present. `llm_conviction_reason` is NULL. `exit_slippage_bps` is populated only for the regression-era subset where `alpaca_adapter` wrote it. |
| `3` | `full_instrumentation` | Opened after Track-1.5 merges to main. All B1 + B3 + B4 fields are populated. See cross-references below. |

---

## Why a Version Sentinel

A single INTEGER column is directly filterable (`WHERE instrumentation_version >= 3`), indexable without a generated column, and unambiguous at a cardinality of 4 values (unlikely to exceed 10 over the system's lifetime).

The alternative — a JSON `data_quality_flags` blob — was rejected in B5 design because it requires caller-side deserialization for every filter, prevents direct indexing, and creates schema-drift risk from unrelated flags sharing the blob.

**Analytics rule:** Any query that produces a performance figure (Sharpe, win rate, average P&L) MUST filter to `instrumentation_version >= 3` to produce interpretable results.

- Filtering to `>= 2` is permissible for conviction-stratified analysis that does not depend on `exit_slippage_bps` or `exit_reason` taxonomy.
- Version 1 trades are usable only for pre-conviction baseline comparisons.
- Version 0 rows are never usable.

Stage-2 onward, the KPI strip and all performance endpoints enforce `instrumentation_version >= 3` by default.

---

## Archive DB Note

The immutable bootcamp archive at `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3` predates this column. All archive rows have `instrumentation_version = NULL`. The `filter_to_version` helper treats NULL as v0 — so all archive rows are excluded by default when `min_version=3`. Operators analyzing archive data must use `min_version=1` or `min_version=2` with explicit awareness of the missing fields.

---

## Cross-References

- **B5 design doc** — `docs/sprints/track_1_5_pass1_design/B5_instrumentation_version.md`: full design rationale, INTEGER vs JSON decision, backfill SQL, risks.
- **Executor stamping point** — `src/shadow_trading/executor.py`, constant `INSTRUMENTATION_VERSION_CURRENT = 3`. All new trades are stamped at open via this constant; the `NOT NULL DEFAULT 3` column definition provides belt-and-braces coverage.
- **Filter helper** — `src/analytics/instrumentation.py::filter_to_version(trades, min_version=3)`. Accepts `list[dict]` or `pd.DataFrame`. Returns same type filtered to `instrumentation_version >= min_version`. NULL/missing version treated as v0. Shelf module — not wired into production query paths yet.
- **Schema registry** — `src/schema/registry.py`, `shadow_trades` table, `instrumentation_version` column. Column docstring references this document.
- **v3 prerequisite deliverables** — a trade stamped v3 must have been opened by a writer where B1 (exit slippage), B3 (exit_reason taxonomy), and B4 (key_risk_assessment / expected_holding_period_days) are all deployed. Track-1.5 delivers all three simultaneously; the DEFAULT 3 column only carries the correct semantic after all three are merged.
