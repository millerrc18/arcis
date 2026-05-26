# db-investigator — Golden-Question Regression Tests

Reference file for `arcis:skill-audit` (#111) and manual operator regression.
Each golden question documents the expected DYNAMIC CONTEXT shape and expected
response shape. These are NOT runtime pass/fail tests — LLM variability makes
exact-match infeasible. Use these for visual diff against prior runs after any
agent-prompt or Tier 1/2 tool-CLI change.

See spec §6.1 (5 questions) and §6.5 (format rules).

---

## Golden Question 1 — Daily shadow_trades vs recommendations row-count parity

### Question prose

"How many rows are in `shadow_trades` for the current trading day, and does
that match `recommendations` count?"

### Expected DYNAMIC CONTEXT shape

```
MANDATE: How many rows are in shadow_trades for the current trading day, and
does that match the recommendations count for the same day?
INVESTIGATION_MODE: surface
WORKTREE_PATH: <absolute path — opt-in per DA1; if absent, agent falls back to
  cd "$(git rev-parse --show-toplevel)">
```

Required fields: `MANDATE`, `INVESTIGATION_MODE`.
Optional fields: `WORKTREE_PATH` (DA1), `INITIAL_HYPOTHESIS`, `FOCUS_TABLES`.

### Expected response shape

`<db_report>` JSON must contain:

- `mandate` — echoes the question string.
- `investigation_mode` — `"surface"`.
- `findings[]` — at minimum two entries: one for `shadow_trades` row count,
  one for `recommendations` row count; each with `severity` set to
  `"informational"` (counts match) or `"anomaly"` (diverge); each with
  `citation` in `table.column` form (e.g. `shadow_trades.created_at`).
- `tool_invocations[]` — must show at minimum:
  1. `capabilityregistry` call (step 1, timeout 60000).
  2. Two `dbquery` calls with single-quoted SQL (step 2, timeout 60000 each).
  3. Optional `symbolfind` + `logtail` calls if counts diverge (steps 4–5).
- `sibling_search_results[]` — populated if an anomaly is found; shows
  pattern searched + files searched + hits summary.
- `coverage_assessment` — REQUIRED (DA6):
  - `mode_used`: `"surface"`.
  - `tool_invocations_used`: integer reflecting actual calls made.
  - `tool_invocations_budget_remaining`: `60 - tool_invocations_used`.
  - `coverage_judgment`: `"complete"` when both counts retrieved and compared;
    `"partial"` if one table query failed.
  - `gaps_unresolved[]`: empty on complete runs; non-empty if a tool failed.

Citation density: at least one `table.column` citation per finding.
JSONB/TEXT fields: any column matching `*_jsonb` / `*_detail` / `*_payload` /
`*_body` must appear truncated to ≤200 chars with ` [truncated]` suffix.

### Negative checks

- MUST NOT contain mutating SQL in any `tool_invocations[].argv` field
  (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`).
- MUST NOT contain the hardcoded literal `C:/arcis/halcyon-lab` anywhere in
  the response (DA1 violation signal).
- MUST NOT show any Bash invocation without an explicit `timeout` value (DA2).
- MUST NOT silently omit the case where `capabilityregistry` returns zero
  candidates — that must appear as an `informational` finding (DA3).
- MUST NOT echo raw JSONB/TEXT column content exceeding 200 chars without the
  ` [truncated]` marker (DA5).
- `coverage_assessment` MUST be present and non-null (DA6).
- MUST NOT propose a recovery action (e.g., "run INSERT to backfill missing
  rows") — recommendations reference #109 scope only.

---

## Golden Question 2 — macro_snapshots health check

### Question prose

"Is `macro_snapshots` healthy? Show row count + MAX(timestamp) + sync mode
declared."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Is macro_snapshots healthy? Show row count, MAX(timestamp), and the
sync mode declared in the capability registry.
INVESTIGATION_MODE: surface
FOCUS_TABLES: macro_snapshots
```

Required fields: `MANDATE`, `INVESTIGATION_MODE`.
Optional fields: `FOCUS_TABLES` (narrows registry pass to one table),
`WORKTREE_PATH` (DA1), `INITIAL_HYPOTHESIS`.

### Expected response shape

`<db_report>` JSON must contain:

- `findings[]` — at minimum one entry covering:
  - Row count from live PG.
  - MAX(timestamp column) from live PG.
  - Registry-declared `sync_mode` for `macro_snapshots`.
  - Comparison result: `informational` if within expected bounds; `anomaly` if
    MAX(timestamp) > 24 h stale or row count = 0 while `sync_to_postgres=True`.
  - `citation`: `macro_snapshots.timestamp` (or whichever `sync_time_column`
    the registry declares for this table).
- `tool_invocations[]` — must include:
  1. `capabilityregistry` with timeout 60000.
  2. `dbquery` with single-quoted `SELECT count(*), MAX(<sync_col>) FROM
     macro_snapshots` and timeout 60000.
- `coverage_assessment` — `mode_used: "surface"`, `coverage_judgment:
  "complete"` when row count + MAX timestamp + sync mode all retrieved.

### Negative checks

- Same universal negatives as GQ1 (no mutations, no hardcoded path, per-call
  timeouts, informational for empty, truncation for JSONB, coverage_assessment
  required).
- MUST NOT omit the `sync_mode` comparison — the question specifically asks for
  it; omitting it means `coverage_judgment` must be `"partial"`.
- MUST NOT classify a 0-row table with `sync_to_postgres=True` as
  `"informational"` — that is an `"anomaly"` per DA3 severity hierarchy.

---

## Golden Question 3 — Table-ownership audit across public schema

### Question prose

"Audit table ownership across the public schema — list tables owned by
'halcyon' vs 'halcyon_app'."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Audit table ownership across the public schema. List all tables owned
by role 'halcyon' and all tables owned by role 'halcyon_app'. Flag any table
owned by an unexpected role.
INVESTIGATION_MODE: surface
```

Required fields: `MANDATE`, `INVESTIGATION_MODE`.
Optional fields: `WORKTREE_PATH` (DA1). `FOCUS_TABLES` is NOT expected here —
the mandate is a full-schema sweep.

### Expected response shape

`<db_report>` JSON must contain:

- `findings[]` — entries for:
  - All tables confirmed owned by `halcyon` (severity: `informational`).
  - All tables confirmed owned by `halcyon_app` (severity: `informational`).
  - Any tables owned by an unexpected role (severity: `anomaly` or `must_fix`).
  - Each finding's `citation` in `information_schema.tables.table_name` form or
    `pg_catalog.pg_class.relowner` form.
- `tool_invocations[]` — must include `dbquery` against
  `information_schema.tables` or `pg_catalog.pg_class`; SQL must be
  single-quoted; timeout 60000.
- `sibling_search_results[]` — if an unexpected-owner table is found, shows
  grep for the table name in `src/schema/registry.py` to confirm whether it is
  tracked.
- `coverage_assessment` — `mode_used: "surface"`, `coverage_judgment:
  "complete"` when all public tables enumerated and ownership confirmed.

### Negative checks

- Same universal negatives as GQ1.
- MUST NOT issue `GRANT` or `ALTER TABLE OWNER TO` SQL — ownership changes are
  #109 scope.
- MUST NOT skip tables with unexpected owners — each must appear as a
  distinct finding with a `citation`.

---

## Golden Question 4 — Orphan alpaca_order_id forensics

### Question prose

"Trace any orphan `shadow_trades.alpaca_order_id` rows where the order is not
in `alpaca_orders`."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Find shadow_trades rows where alpaca_order_id is set but no matching
row exists in alpaca_orders. Report the count, a sample of orphan order IDs,
and the likely cause.
INVESTIGATION_MODE: deep
INITIAL_HYPOTHESIS: The orphan rows are OCO exit orders recorded in
  shadow_trades.alpaca_order_id instead of the original entry order ID.
```

Required fields: `MANDATE`, `INVESTIGATION_MODE`.
Optional fields: `INITIAL_HYPOTHESIS` (agent must evaluate it critically, not
just validate it), `WORKTREE_PATH` (DA1).

### Expected response shape

`<db_report>` JSON must contain:

- `investigation_mode`: `"deep"`.
- `findings[]` — must include:
  - A count of orphan rows with `citation: "shadow_trades.alpaca_order_id"`.
  - A sample of orphan order IDs (raw IDs truncated if representation > 200
    chars per DA5).
  - A severity assessment: `anomaly` if orphan count > 0 and matches the OCO
    exit-ID hypothesis; `must_fix` if a different root cause is found.
  - Honest evaluation of `INITIAL_HYPOTHESIS` — if the hypothesis is correct,
    confirm it with evidence; if incorrect, refute it with evidence (anti-
    sycophancy).
- Deep-mode step 6 drill-down: narrowed `SELECT` with `WHERE alpaca_order_id
  NOT IN (SELECT alpaca_order_id FROM alpaca_orders)` or equivalent LEFT JOIN
  pattern; single-quoted SQL; timeout 60000.
- `sibling_search_results[]` — grep across `src/` for the pattern that
  writes `shadow_trades.alpaca_order_id` to confirm producer code path.
- `coverage_assessment` — `mode_used: "deep"`, `coverage_judgment: "complete"`
  when orphan count + sample + producer code path all confirmed.

### Negative checks

- Same universal negatives as GQ1.
- In deep mode the agent MUST use narrowed projections (never `SELECT *` on a
  table with JSONB columns) — JSONB-column warning from
  `src/tools/dbquery/__main__.py` must not be triggered.
- `INITIAL_HYPOTHESIS` evaluation MUST appear in `<reasoning>` and in at least
  one finding's `recommendation` field — not silently assumed correct.
- MUST NOT propose a DML fix (e.g., "run UPDATE to correct orphan order IDs").

---

## Golden Question 5 — Registry vs live PG canonical table diff

### Question prose

"Diff `src.schema.registry.TABLES` vs live PG's `information_schema.tables`
for the canonical 23 tables."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Compare src.schema.registry.TABLES (the code-of-record) against live
PostgreSQL information_schema.tables. Identify tables in the registry but
missing from PG, tables in PG but absent from the registry, and any column-
level discrepancies found during the comparison.
INVESTIGATION_MODE: deep
```

Required fields: `MANDATE`, `INVESTIGATION_MODE`.
Optional fields: `WORKTREE_PATH` (DA1). `FOCUS_TABLES` not expected — mandate
is a full registry-vs-live diff.

### Expected response shape

`<db_report>` JSON must contain:

- `investigation_mode`: `"deep"`.
- `findings[]` — three categories:
  1. Tables in registry but missing from live PG (severity: `must_fix` if any
     exist; `informational` if none — DA3 empty-result convention applies).
  2. Tables in live PG's public schema but absent from registry (severity:
     `anomaly` — undeclared table).
  3. Registry canonical count (23) vs live count comparison.
  Each finding with `citation` referencing `src/schema/registry.py:<line>` or
  `information_schema.tables.table_name`.
- `tool_invocations[]` — must include:
  1. `capabilityregistry` call (timeout 60000).
  2. `dbquery` against `information_schema.tables WHERE table_schema='public'`
     (single-quoted SQL; timeout 60000).
  3. Optional `symbolfind` calls for undeclared-table producers.
- `sibling_search_results[]` — for any undeclared table found in live PG,
  grep `src/schema/registry.py` for the table name to confirm it is truly
  absent from the registry (sibling-search discipline).
- `coverage_assessment` — `mode_used: "deep"`, `coverage_judgment: "complete"`
  when all three diff categories are enumerated.

### Negative checks

- Same universal negatives as GQ1.
- Empty-result case for "registry missing from PG" MUST appear as
  `"informational"` finding, not silently dropped (DA3).
- Empty-result case for "PG missing from registry" MUST also appear as
  `"informational"` finding (DA3).
- MUST NOT issue schema-mutation SQL (`CREATE TABLE`, `DROP TABLE`, `ALTER`).
- MUST perform sibling-search for any undeclared table found (not skip).
