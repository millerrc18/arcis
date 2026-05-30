# Literal `%` in SQL Strings — Pre-Flight Audit (T0.0)

**Date:** 2026-05-11
**Purpose:** Identify every SQL string literal in `src/` containing a literal `%` character to prevent psycopg2 format-string crashes after Phase 0's `?`→`%s` rewrite ships.
**Source spec:** `docs/audits/2026-05-11-modified-a-migration/spec.md` (section 2.3, C1 fix)

## Background

psycopg2 uses `%` as both the parameter sigil (`%s`, `%(name)s`) AND the format-specifier prefix. After T0.2's `?`→`%s` rewrite lands, any literal `%` left in the SQL string (e.g. inside a LIKE wildcard) causes psycopg2's parameter binding to crash with `IndexError: tuple index out of range` or `TypeError: not enough arguments for format string`. The 2026-05-10 cutover failure happened to be a different root cause (unrewritten `?` placeholders), but the failure-class is the same: silent SQL strings that break only on the PG path.

The T0.2 quote-AND-percent-aware rewrite will:
1. Leave `%` characters **inside single-quoted string literals** untouched (these are the LIKE wildcards baked into the SQL).
2. Double any **unpaired** `%` characters **outside string literals** to `%%`.

This audit therefore needs to distinguish:
- **Category (a) — already-safe**: site never sees the PG path; the `%` will never be format-bound (e.g. wrapped in `_sqlite_only_connect`, retiring file, allowlisted SQLite-only-by-design).
- **Category (b) — requires `%%` escape**: site WILL execute against PG post-cutover via the wrapper, and the literal `%` lives **inside a single-quoted string literal** in the SQL. T0.2's tokenizer leaves these alone, so they survive format binding unchanged. No rewrite work needed at the call site — but the audit records them so downstream verification knows what to assert.
- **Category (c) — parameter-substitutable**: site bakes the `%` into the SQL as a literal but the value is dynamic (e.g. `f"WHERE x LIKE '%{val}%'"`), or the literal is a fixed wildcard that would survive equally well as a bound parameter. Phase 1+ tasks may choose to move these to `LIKE ?` with the `'%X%'` value passed as a bound parameter (which is what most call sites in this codebase already do).

Note: SQL strings where the `%` arrives **as a bound parameter** (e.g. `conn.execute("... LIKE ?", (f"{today_str}%",))`) are inherently safe — psycopg2 only does format-binding on the SQL string, not on the param values. Those sites are catalogued under "passing `%` via bound param" below for completeness and are NOT a migration concern.

## Grep methodology

Commands used (Bash → ripgrep via the `Grep` tool):

```bash
# Find LIKE patterns containing literal % inside the SQL string
grep -rn -i "LIKE\s*['\"][^'\"]*%" src/

# Find all files containing LIKE (any form) — used to confirm completeness
grep -rn -i "LIKE" src/

# Find all sites where % appears
grep -rn "%" src/   # noisy, then refine

# Find f-string-built LIKE patterns where % is in the SQL string
grep -rn "f['\"]\\{[^}]+\\}%" src/
grep -rn "f['\"]%" src/

# Find sites passing %-bearing bound params (for the safe catalogue)
# Covered by the f-string scans above; verified by reading shadow_trades sites.
```

**Patterns the regex won't catch** (acknowledged limitations — must verify by reading):
1. Multi-line SQL strings where `LIKE 'X%'` is split across two source lines (would need multiline ripgrep).
2. Dynamic SQL fragments built via `.join()` / `.format()` / f-string-with-nested-{} that the AST scanner T2.14 catches but a substring grep does not.
3. `LIKE` patterns where the `%` arrives through a variable named `LIKE_PCT_CONSTANT = '%foo%'`-style indirection.

Mitigation: T0.2's rewrite is conservative — `%` outside a string literal is escaped to `%%` regardless of provenance, so any pattern this audit misses will be **escaped, not crashed**. The risk is over-escape, not under-escape. Phase 1 per-site reviewers may decide to refactor a missed site into category (c) for clarity.

## Sites enumerated

### Category (a) — already-safe (no rewrite needed; never executed against PG)

These sites either live in retiring files (deleted in Phase 4 — out of T0.2 scope) or in SQLite-only-by-design files (spec §2.7 allowlist: `src/schema/sqlite.py`, `src/schema/registry.py`, `src/scheduler/watch.py:1164-1165` SQLite backup API, `src/training/trainer.py:1171`).

| File:line | SQL fragment | Why safe |
|---|---|---|
| `src/training/trainer.py:1175` | `"WHERE source LIKE 'outcome_template_%' "` | Inside `_sqlite3.connect(db_path)` block at line 1171 — file is in spec §2.7 SQLite-only-by-design allowlist; trainer writes to training_corpus SQLite only. **Confirmed:** opened via `_sqlite3.connect(...)`, not via `connect_db`. |

### Category (b) — requires `%%` escape (LIKE survives format binding; tokenizer-handled)

These sites are reached via `connect_db()` / wrapper path, and the literal `%` lives **inside a single-quoted string literal** in the SQL string. T0.2's quote-aware tokenizer detects the string literal and leaves the `%` untouched, so psycopg2 format-binding sees the SQL as `... LIKE '%paper%' ...` unchanged and binds parameters correctly. **No call-site code change required.** Audit records the sites so smoke-tests / Phase-1-1.5 reviewers can verify post-rewrite behaviour.

| File:line | SQL fragment | Notes |
|---|---|---|
| `src/scheduler/overnight.py:222` | `"SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'"` | Inside-quotes `%paper%` — tokenizer treats as string-literal contents, leaves untouched. `?` outside literal gets rewritten to `%s`. |
| `src/scheduler/reports.py:198` | `"SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'"` | Same as overnight.py:222 (sibling site — identical query). |
| `src/api/routes/health.py:121` | `"WHERE results_json LIKE '%\"trigger\": \"startup\"%' "` | Embedded quoted JSON fragment; the `%` chars sit inside the outer `'...'` literal. Tokenizer-safe. |
| `src/api/routes/health.py:132` | `"WHERE results_json LIKE '%\"trigger\": \"startup\"%' "` | Sibling site (lines 121 + 132 in same function — sibling-search rule applied). |
| `src/startup.py:144` | `"WHERE results_json LIKE '%\"trigger\": \"startup\"%' "` | Sibling site — same JSON-prefix LIKE pattern, duplicated across health.py and startup.py paths. |

**Sibling-search check (per CLAUDE.md):** I grepped each of these files for additional LIKE patterns with literal `%`. `health.py` has the pattern at both line 121 and line 132 (within the same function — two SELECTs against `validation_results`). `startup.py` has one copy at line 144. `overnight.py` has one copy at line 222. `reports.py` has the `LIKE '%paper%'` once at line 198; the other `LIKE ?` sites in `reports.py` (lines 46, 402, 418, 436, 443, 466, 526, 534, 550) all pass the `%` as a **bound parameter** (`(f"{today_str}%",)`) and are therefore in the "safe by bound-param" catalogue (not category b).

### Category (c) — parameter-substitutable (literal `%` in SQL CAN be moved to bound param; Phase 1+ may rewrite)

These sites currently have **no** literal `%` outside string literals — they already pass the `%` as a bound parameter. **All sites listed below are SAFE AS-IS** post T0.2 rewrite because the rewrite operates only on the SQL string, not on parameter tuples. They're catalogued here so Phase 1+ reviewers can decide whether to harden category (b) sites by migrating them into this style.

**Per spec §2.3:** Phase 1+ tasks do NOT need to pre-decide rewriting strategy. This catalogue is informational.

| File:line | SQL fragment | Param tuple | Notes |
|---|---|---|---|
| `src/shadow_trading/executor.py:776` | `"SELECT 1 FROM activity_log WHERE event_type = ? AND detail LIKE ? AND created_at > date('now')"` | `(alert_key, f"%{int(threshold)}%")` | **The activity_log LIKE site explicitly flagged by spec §2.3.** `date('now')` is SQLite-specific time function — Phase 2B will rewrite this. The `?`→`%s` rewrite + bound-param flow is already correct for psycopg2. Smoke test T3.4 covers this path per spec. |
| `src/scheduler/watch.py:567` | `"WHERE status='closed' AND actual_exit_time LIKE ?"` | `(f"{today_str}%",)` | Bound-param `%` — wrapper-safe. |
| `src/scheduler/watch.py:1532` | `"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0"` | `(f"{_today}%",)` | Bound-param `%` — wrapper-safe. |
| `src/scheduler/watch.py:1537` | `"WHERE status='closed' AND actual_exit_time LIKE ?"` | `(f"{_today}%",)` | Bound-param `%` — wrapper-safe. Sibling of :1532. |
| `src/scheduler/reports.py:46` | `"SELECT created_at FROM scan_metrics WHERE created_at LIKE ? ORDER BY created_at ASC"` | `(f"{metric_date}%",)` | Bound-param. |
| `src/scheduler/reports.py:402` | `f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"` | `(f"{today_str}%",)` | Bound-param. Note: outer f-string interpolates a filter fragment with no `%` — verified. |
| `src/scheduler/reports.py:418` | `f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"` | `(f"{today_str}%",)` | Bound-param. Sibling of :402. |
| `src/scheduler/reports.py:436` | `"WHERE status = 'closed' AND actual_exit_time LIKE ?"` | `(f"{today_str}%",)` | Bound-param. |
| `src/scheduler/reports.py:443` | `"WHERE status = 'closed' AND actual_exit_time LIKE ?"` | `(f"{today_str}%",)` | Bound-param. Sibling of :436 (worst-trade query). |
| `src/scheduler/reports.py:466` | `"FROM scan_metrics WHERE scan_time LIKE ?"` | `(f"{today_str}%",)` | Bound-param. |
| `src/scheduler/reports.py:526` | `"SELECT COUNT(*) FROM training_examples WHERE created_at LIKE ?"` | `(f"{today_str}%",)` | Bound-param. |
| `src/scheduler/reports.py:534` | `"SELECT COUNT(*) FROM setup_signals WHERE created_at LIKE ?"` | `(f"{today_str}%",)` | Bound-param. |
| `src/scheduler/reports.py:550` | `"WHERE source IN ('outcome_win','outcome_loss') AND created_at LIKE ?"` | `(f"{today_str}%",)` | Bound-param. |
| `src/shadow_trading/executor.py:2511` | `f"WHERE status IN ({_t_frag275}) AND source='live' AND actual_exit_time LIKE ?"` | `(*_t_params275, f"{today_str}%")` | Bound-param. `{_t_frag275}` is a status-IN placeholder fragment with no `%`. |
| `src/shadow_trading/executor.py:2520` | `f"FROM shadow_trades WHERE status IN ({_a_frag275}) AND source='live' AND created_at LIKE ?"` | `(*_a_params275, f"{today_str}%")` | Bound-param. Sibling of :2511. |
| `src/journal/store.py:214` | `f"SELECT {columns_sql} FROM recommendations WHERE created_at LIKE ?"` | `(f"{today_str}%",)` | Bound-param. `{columns_sql}` is a `, `-joined column list with no `%`. |
| `src/training/backfill.py:89` | (multi-line) `"... AND feature_snapshot LIKE ? LIMIT 1"` | `(ticker, f"%{scan_date}%")` | Bound-param. |
| `src/notifications/telegram_commands.py:141` | `"WHERE event_type = 'gate_milestone' AND detail LIKE ?"` | `(f"%{milestone}%",)` | Bound-param. |

### Auxiliary catalogue — sites passing `%`-bearing values via bound parameters (informational, NOT migration concerns)

The category (c) table above already lists every site where the SQL string contains `LIKE ?` and the matching param tuple contains a `%`-bearing value. Including them under (c) preserves the spec's "parameter-substitutable" framing even though no rewrite is required. These sites are guaranteed safe post-T0.2 because the rewrite operates on the SQL string only.

## Edge cases & non-LIKE `%` usage in SQL

Confirmed **no** other production SQL paths use a literal `%` outside the LIKE-pattern cases above:
- Searched for `'100%'`, `'%X%'`-style embedded literals — none found in `src/`.
- Searched for arithmetic `%` (modulo) — only found in `src/platform/rigor/cscv.py` (Python modulo, not SQL).
- Searched for `MOD()` / strftime `%Y` / `%m` etc — Python's `datetime.strftime()` (Python format string, not SQL) is used in many places (e.g. `datetime.now().strftime("%Y-%m-%d")`) but these resolve **before** the value reaches `conn.execute()` as a bound parameter. Not a concern.
- `src/scheduler/watch.py:564, 1525`, `src/scheduler/reports.py:520`, `src/email/digest_builder.py:172`: `strftime("%Y-%m-%d")` → resolves to a regular string in Python before becoming a bound param. Safe.
- `src/journal/store.py:215`: `(f"{today_str}%",)` — bound param, safe (already in category c).
- `src/api/cloud_routes/trades.py:59`: `("desk LIKE %s", [desk.replace("*", "%")], ...)` — this site is **already on the PG-only path** (it uses `%s` placeholders directly, not `?`). The `%` it injects into the parameter value is a wildcard for `LIKE`; psycopg2 binds the parameter as a string value, so the `%` is data, not format-spec. Safe.

## Sibling-search receipts

Per memory `feedback_review_sibling_search`: when a literal-`%` site was found at `file:line`, I grepped the rest of `file` for additional matches. Results recorded above:
- `src/api/routes/health.py` — 2 sibling sites (lines 121, 132). Both catalogued.
- `src/scheduler/reports.py` — 1 category-(b) site (line 198) + 9 category-(c) bound-param sites. All catalogued.
- `src/scheduler/watch.py` — 3 category-(c) bound-param sites (lines 567, 1532, 1537). All catalogued.
- `src/scheduler/overnight.py` — 1 category-(b) site (line 222). No siblings.
- `src/startup.py` — 1 category-(b) site (line 144). No siblings.
- `src/training/trainer.py` — 1 category-(a) site (line 1175). No siblings inside SQLite-only block.
- `src/shadow_trading/executor.py` — 1 LIKE-pattern site with `%`-bearing bound param (line 776 — the activity_log LIKE), 2 category-(c) bound-param sites (lines 2511, 2520). All catalogued.
- `src/journal/store.py` — 1 category-(c) bound-param site (line 214). No additional siblings.
- `src/training/backfill.py` — 1 category-(c) bound-param site (line 89). No siblings.
- `src/notifications/telegram_commands.py` — 1 category-(c) bound-param site (line 141). No siblings.

## Summary

Total sites: 28 (1 in category a, 5 in category b, 18 in category c, plus 4 informational notes on non-LIKE `%` usage)
- **Category (a) — already-safe** (SQLite-only-by-design / retiring): **1** — trainer.py:1175 (allowlisted).
- **Category (b) — requires `%%` escape via tokenizer** (literal-in-SQL LIKE; T0.2 must NOT crash on these): **5** — overnight.py:222, reports.py:198, health.py:121+132, startup.py:144.
- **Category (c) — parameter-substitutable** (already pass `%` as bound param; safe by design; Phase 1+ may further normalise): **18** — see table.

**Activity-log LIKE site (spec §2.3 explicit smoke target):** `src/shadow_trading/executor.py:776` — already uses bound-param `%`, so category (c). T3.4 smoke-test must execute this query against PG after the T0.2 rewrite lands. The wrapper's quote-aware tokenizer plus the bound-param flow together guarantee no IndexError/TypeError.

**Cloud_routes LIKE site (spec § audit-target):** `src/api/cloud_routes/trades.py:59` — already PG-native (uses `%s`, not `?`); param value `desk.replace("*", "%")` is bound, not format-spec. Wrapper rewrite does not touch this site.

**Walkforward universe filters:** No literal-`%` LIKE patterns found in `src/platform/rigor/walkforward_runner.py`, `src/platform/rigor/walkforward_universe.py`, or `src/platform/rigor/walkforward_*.py`. Spec target item retired — these files contain modulo operators only (in CSCV index math), no SQL `%`.

**Council/value_tracker reporting queries:** No literal-`%` LIKE patterns found in `src/council/value_tracker.py` (verified via `grep -i LIKE`; only INSERT/UPDATE/SELECT statements without `%`). No category (b) sites here.

## Implications for T0.2 rewrite

The T0.2 tokenizer MUST:
1. Detect the 5 category-(b) sites' `LIKE '...%...'` literals and leave them unchanged (the `%` is data inside a single-quoted string literal).
2. NOT introduce `%%` doubling inside string literals — that would corrupt the LIKE pattern matching.
3. Properly handle the JSON-fragment case in health.py / startup.py: `LIKE '%\"trigger\": \"startup\"%'` — the `%` characters surround an escaped-quote payload. The Python source uses `'\"'` to escape the inner double quotes inside the outer single-quoted SQL literal. The SQL parser sees `'%"trigger": "startup"%'` as one continuous single-quoted string. T0.2 must not be confused by the embedded double-quote escapes.

The 4 category-(c) sites that pass `%` as a bound parameter need **no** wrapper handling — psycopg2 binds parameter values verbatim, no format-spec processing.

The 1 category-(a) site is reached only via `_sqlite3.connect(db_path)` direct (not via the wrapper), so the rewrite never sees it.

**Recommendation for T0.2 test fixture:** Use the JSON-fragment pattern from health.py:121 as the most adversarial test case (embedded double-quote escapes inside a single-quoted SQL string with `%` on both ends). If T0.2 handles that correctly, the simpler `LIKE '%paper%'` and `LIKE 'outcome_template_%'` patterns will also be handled.
