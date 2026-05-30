# Sprint 0 / Wave 1b STATUS-CONST — Postgres-domain deferral

**Date:** 2026-04-26
**Branch:** `feature/sprint-0-wave-1b-status-const-shadow`
**Scope:** This PR migrates SQLite-domain (`src/shadow_trading/`) call sites to
`terminal_in_clause()` / `active_in_clause()` from
`src/shadow_trading/_status_sql.py`. Postgres-domain call sites are deferred
because the helpers emit `?` placeholders (sqlite3) and Postgres uses `%s`.

## Why a separate helper is needed

The current helpers in `src/shadow_trading/_status_sql.py` hard-code SQLite
positional placeholders:

```python
def terminal_in_clause() -> tuple[str, tuple[str, ...]]:
    values = tuple(sorted(TERMINAL_STATUSES))
    placeholders = ", ".join("?" * len(values))     # SQLite syntax
    return placeholders, values
```

A Postgres-compatible variant must emit `%s` (or named `%(name)s`) so
`psycopg2` / `asyncpg` accept the bind. A direct port:

```python
def terminal_in_clause_pg() -> tuple[str, tuple[str, ...]]:
    values = tuple(sorted(TERMINAL_STATUSES))
    placeholders = ", ".join(["%s"] * len(values))
    return placeholders, values
```

Adding this in the same PR would expand scope beyond `src/shadow_trading/`
and require auditing the Postgres call sites for execute() params shape (some
use list-of-tuples, some named, some pass dicts). That's a separate sprint.

## Postgres / cloud-route sibling sites that need migration

The following sites filter on hardcoded `status = 'closed'` or
`status = 'open'` (or the equivalent literal IN clauses) and use Postgres
`%s` placeholders, so they require the not-yet-implemented Postgres helper
variant before they can adopt the canonical-status pattern.

These were enumerated by:

```bash
grep -nE "status\s*(=|IN)\s*['\"](closed|open|pending|rejected|failed|exit_abandoned|exit_pending|exit_failed|submission_uncertain)['\"]" \
    src/{api,council,email,evaluation,journal,training,scheduler,sync,cost_model,notifications,diagnostics}/**/*.py
```

### `src/api/cloud_routes/`

- `analytics.py:248` — `WHERE status = 'closed'`
- `analytics.py:259` — `WHERE status = 'open'`
- `analytics.py:317` — `WHERE status = 'closed'`
- `analytics.py:321` — `WHERE status = 'open'`
- `analytics.py:415` — `WHERE status = 'open'`
- `analytics.py:422` — `WHERE st.status = 'closed' AND st.actual_exit_time >= %s`
- `analytics.py:673` — `WHERE status = 'closed'`
- `analytics.py:761` — `WHERE st.status = 'closed' AND st.strategy_type = %s`
- `core.py:146` — `WHERE status = 'open'`
- `core.py:150` — `WHERE status = 'closed'`
- `trades.py:145` — `WHERE st.status = 'open' AND COALESCE(st.quarantined, 0) = 0 AND {desk_frag}`
- `trades.py:150` — `WHERE status = 'closed'`
- `trades.py:224` — `WHERE st.status = 'closed'`
- `trades.py:289` — `WHERE status = 'closed' AND actual_exit_time >= %s`
- `trades.py:363` — `WHERE source = 'live' AND status = 'open'`
- `trades.py:367` — `WHERE source = 'live' AND status = 'closed'`
- `trades.py:424` — `WHERE source = 'live' AND status = 'closed'`
- `trades.py:428` — `WHERE source = 'live' AND status = 'open'`
- `trades.py:453` — `WHERE status = 'open'`
- `trades.py:458` — `WHERE status = 'closed'`
- `trades.py:518` — `WHERE status = 'closed'`
- `trades.py:549` — `WHERE st.status = 'closed' AND st.actual_exit_time >= %s`
- `trades.py:578` — `WHERE status = 'closed' AND pnl_pct IS NOT NULL`
- `training.py:568` — `WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL`

### `src/api/routes/` (FastAPI routes that touch Postgres in cloud or sqlite locally)

- `health.py:68` — `WHERE status = 'closed'`
- `health.py:189` — `WHERE status = 'closed'`
- `live.py:46` — `WHERE source = 'live' AND status = 'open'`
- `live.py:51` — `WHERE source = 'live' AND status = 'closed'`
- `live.py:99` — `WHERE source = 'live' AND status = 'closed'`
- `live.py:103` — `WHERE source = 'live' AND status = 'open'`
- `projections.py:78` — `WHERE status = 'closed' AND pnl_pct IS NOT NULL`
- `strategy_detail.py:33` — `WHERE st.status = 'closed' AND st.strategy_type = ?`

### `src/council/`

- `agent_data.py:92` — `WHERE st.status = 'open'`
- `agent_data.py:128` — `WHERE status = 'closed'`
- `agent_data.py:145` — `WHERE status = 'closed' AND pnl_dollars IS NOT NULL`
- `agent_data.py:206` — `WHERE st.status = 'open' AND r.sector_context IS NOT NULL`
- `agent_data.py:223` — `WHERE status = 'closed' AND pnl_pct < 0`
- `agent_data.py:251` — `WHERE status = 'closed'`
- `agent_data.py:262` — `WHERE status = 'closed' AND max_adverse_excursion IS NOT NULL`
- `agent_data.py:433` — `WHERE st.status = 'closed' AND r.sector_context IS NOT NULL`
- `aggregation.py:70` — `WHERE status = 'closed'`
- `context.py:44` — `WHERE status = 'open'`
- `value_tracker.py:178` — `WHERE status = 'closed' AND actual_entry_time >= ?`
- `value_tracker.py:243` — `AND st.status = 'closed'`

### `src/email/`

- `digest_builder.py:142` — `WHERE status = 'open' AND COALESCE(quarantined, 0) = 0`
- `digest_builder.py:152` — `WHERE status = 'closed' AND date(actual_exit_time) = ?`
- `digest_builder.py:225` — `WHERE status = 'closed' AND date(actual_exit_time) = ?`
- `digest_builder.py:289` — `WHERE status = 'closed' AND date(actual_exit_time) = ? AND ...`
- `digest_builder.py:290` — `WHERE status = 'open' AND COALESCE(quarantined, 0) = 0 ORDER BY ...`
- `digest_builder.py:291` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`
- `digest_builder.py:355` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`

### `src/evaluation/`

- `auditor.py:265` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`
- `build_score.py:96` — `WHERE status = 'closed' AND actual_exit_time >= ?`
- `build_score.py:270` — `WHERE status = 'closed' AND actual_exit_time >= ?`
- `build_score.py:295` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`
- `change_detector.py:66` — `WHERE status = 'closed'`
- `gate_evaluator.py:38` — `WHERE status = 'closed' AND pnl_pct IS NOT NULL`
- `hshs_live.py:80` — `WHERE status = 'closed'`
- `hshs_live.py:90` — `WHERE status = 'closed' AND pnl_dollars > 0`
- `hshs_live.py:101` — `WHERE status = 'closed' AND pnl_dollars > 0`
- `hshs_live.py:108` — `WHERE status = 'closed' AND pnl_dollars < 0`
- `hshs_live.py:123` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`
- `model_monitor.py:162` — `WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL`
- `model_monitor.py:186` — `WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL`
- `system_validator.py:327` — `WHERE status='open' AND created_at < ?`
- `system_validator.py:380` — `WHERE status='open'`

### `src/journal/`

- `store.py:96` — `WHERE status = 'closed' AND actual_exit_time IS NULL`
- `store.py:274` — `WHERE status IN ('open', 'exit_pending')` *(literal IN — partial canonicalization, but still hardcoded)*
- `store.py:305` — `WHERE status = 'closed' AND actual_exit_time >= ?`

### `src/training/` and `src/scheduler/`

- `data_collector.py:314` — `WHERE st.status = 'closed'`
- `versioning.py:345` — `WHERE st.status = 'closed' AND COALESCE(st.quarantined, 0) = 0`
- `scheduler/watch.py:490` — `WHERE status='open' AND source='paper'`
- `scheduler/watch.py:494` — `WHERE status='open' AND source='live'`
- `scheduler/watch.py:500` — `WHERE status='closed'`
- `scheduler/watch.py:508` — `WHERE status='closed' AND actual_exit_time LIKE ?`
- `scheduler/watch.py:1402` — `WHERE status='open'`
- `scheduler/watch.py:1406` — `WHERE status='closed'`
- `scheduler/watch.py:1412` — `WHERE status='closed' AND actual_exit_time LIKE ?`

### `src/notifications/` + `src/cost_model/`

- `notifications/telegram_commands.py:125` — `WHERE status = 'closed'`
- `notifications/telegram_commands.py:357` — `WHERE status = 'open' AND COALESCE(quarantined, 0) = 0`
- `notifications/telegram_commands.py:418` — `WHERE status = 'open' AND COALESCE(quarantined, 0) = 0`
- `notifications/telegram_commands.py:424` — `WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0`
- `notifications/telegram_commands.py:430` — `WHERE status = 'open' AND source = 'live'`
- `notifications/telegram_commands.py:437` — `WHERE status = 'closed' AND source = 'live'`
- `cost_model/calibration.py:106` — `WHERE status = 'closed'`

### Counts

| Module | Sites | Backend |
|--------|-------|---------|
| `api/cloud_routes/` (analytics + core + trades + training) | 24 | Postgres (`%s`) |
| `api/routes/` (health + live + projections + strategy_detail) | 8 | mixed |
| `council/` (agent_data + aggregation + context + value_tracker) | 12 | sqlite (`?`) |
| `email/digest_builder.py` | 7 | sqlite |
| `evaluation/` (auditor + build_score + change_detector + gate_evaluator + hshs_live + model_monitor + system_validator) | 14 | sqlite |
| `journal/store.py` | 3 | sqlite |
| `training/` + `scheduler/watch.py` | 11 | sqlite |
| `notifications/telegram_commands.py` + `cost_model/calibration.py` | 7 | sqlite |
| **Total** | **86** | mixed |

## Plan for the next sprint

1. Add `terminal_in_clause_pg()` / `active_in_clause_pg()` (or a single
   helper with a `placeholder` kwarg defaulting to `?`) in
   `src/shadow_trading/_status_sql.py`.
2. Sweep the 24 cloud-routes sites first (they were the original prompt
   for the helper).
3. Then sweep the sqlite-domain non-`shadow_trading/` sites — they could
   adopt the existing `?` helper today, but bundling them with the
   Postgres sweep keeps the audit coherent.
4. Extend `tests/test_tier_1_hardening.py::test_no_hardcoded_status_filter_predicates`
   to scan the additional paths so the guard doesn't silently regress
   after the sweep.

## Behavioral risk if NOT migrated

For any site filtering on `status = 'closed'` only:

- `rejected`, `failed`, `exit_abandoned`, `needs_manual_review` rows are
  silently excluded.
- Aggregate stats (win rate, total pnl, count_closed) understate the
  full terminal cohort.
- Operator-facing dashboards (analytics, council, telegram) report
  systematically smaller "closed" populations than reality.

For sites filtering on `status = 'open'` only:

- `submission_uncertain`, `pending`, `exit_pending`, `exit_failed` rows
  are silently excluded.
- Health / capacity panels understate active exposure.
- Reconcile-loop touch proxies (the bug fixed in
  `src/shadow_trading/reconcile_state.py:28` this sprint) miss work the
  loop is doing on non-`open` rows.

## References

- CLAUDE.md > Shadow Trading Rules: "Status constants are canonical — use
  TERMINAL_STATUSES and ACTIVE_STATUSES from src/shadow_trading/models.py
  in queries. Never hardcode `status != 'closed'`."
- `src/shadow_trading/_status_sql.py` — current helpers (sqlite-only).
- `src/shadow_trading/models.py` — canonical `TERMINAL_STATUSES` and
  `ACTIVE_STATUSES` frozensets.
- Sprint 0 / Wave 1b STATUS-CONST commit (this PR).
