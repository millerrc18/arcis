# 2026-W21 Execution Cleanup — Inventory

**Goal:** Catalog every known trading-execution error in the system. Burn down through the week. No new features until this list is clear.

**Operator directive (2026-05-18):** No new features this week. Tidy the house first. (Memory: `feedback_week_of_2026_05_18_no_features_only_cleanup`.)

**Date opened:** 2026-05-18
**Author:** PM session
**Status:** OPEN — awaiting operator prioritization
**Source data:** `git log --since="2026-05-11"`, `logs/arcis.log` last ~7 days, PG halcyon state queries (post-recovery), code scan of `src/shadow_trading/`, `src/services/`, `src/trading/`, `src/journal/`

---

## P0 — Production risk RIGHT NOW

### P0-1. ~~Twelve~~ open positions show NULL `alpaca_order_id` in PG — **CLOSED 2026-05-18 09:26**

**Resolution:**
- Watch-loop reconciler (running post-restart) auto-closed 5 ghost positions and orphan-backfilled 9+ active ones via `reconcile_paper_trades`. State after reconciler: 18 open positions, 8 still DB-blind, 2 of which had qty mismatches.
- One-shot recovery script `scripts/recovery/backfill_alpaca_order_id_post_wipe_2026_05_18.py` ran with qty validation: **6 unambiguous backfills committed** (BAC, COST, DUK, FDX, JNJ, UNP). 2 qty mismatches (AVGO 6→4, KO 55→20) skipped and surfaced as P1-4 partial-exit work.
- Final state: 16 of 18 open positions have full DB→broker OID linkage. The 2 remaining are tracked under P1-4.

**Original severity:** Critical. **Actual outcome:** observability gap, not actual unprotected positions — the brackets existed at Alpaca all along.

**Original evidence (pre-resolution):**

**Evidence:**
```
status=open, count=18
status=open AND (alpaca_order_id IS NULL OR ''), count=12
```

| Ticker | Entered | Stop | Target |
|---|---|---|---|
| BAC | 2026-05-08 | 49.01 | 54.17 |
| BMY | 2026-05-08 | 53.44 | 59.06 |
| DUK | 2026-05-08 | 118.41 | 130.87 |
| COP | 2026-05-08 | 108.89 | 120.35 |
| CVX | 2026-05-08 | 172.63 | 190.81 |
| UNP | 2026-05-11 | 250.27 | 276.61 |
| COST | 2026-05-11 | 951.93 | 1052.13 |
| DIS | 2026-05-11 | 102.35 | 113.12 |
| FDX | 2026-05-11 | 353.05 | 390.21 |
| KO | 2026-05-11 | 74.26 | 82.08 |
| JNJ | 2026-05-11 | 209.77 | 231.85 |
| (one more) | | | |

**Hypothesis:** These had bracket protection in PRE-WIPE PG (yesterday I queried `alpaca_order_id` populated for all 18 opens). After yesterday's wipe, the migrate restored from SQLite — but SQLite was stale relative to live PG when wipe occurred (the cutover routed writes to PG only, so the bracket order IDs added via OCO-attach work only existed in PG). The 12 unprotected-looking positions may actually have brackets at Alpaca but our DB lost the linkage.

**Fix path:**
1. Query Alpaca for currently-open orders per ticker
2. Reconcile: any ticker with a matching bracket order → backfill `alpaca_order_id` and `exit_order_id` from Alpaca's IDs
3. Any ticker WITHOUT a bracket → re-attach via `src/shadow_trading/bracket_attach.py` (the v0.36.4 tool)

**Effort:** ~30 min, no new code

**Status:** ⚠️ Highest priority. Address before any code work.

---

### P0-2. `executor.py:665` — SQLite-only `BEGIN IMMEDIATE` fails on PG, duplicate-check silently disabled

**Severity:** High. The atomic duplicate-check that protects against race conditions between concurrent scan paths (pullback / MR / sentiment scanners opening the same ticker simultaneously) is silently bypassed on PG. Falls back to non-atomic check.

**Evidence:**
```
src/shadow_trading/executor.py:665: _dup_conn.execute("BEGIN IMMEDIATE")
[SHADOW] Atomic duplicate check failed for GILD: syntax error at or near "IMMEDIATE"
```
18 occurrences in logs since 2026-05-15.

**Class:** PG dialect leak. Same family as v0.36.2 `date(text)`, v0.36.12 `INSERT OR REPLACE`. Sibling-search miss — the prior PG-dialect hotfixes didn't sweep transaction-isolation keywords.

**Fix path:**
- PG equivalent: `BEGIN; LOCK TABLE shadow_trades IN SHARE ROW EXCLUSIVE MODE;` or use `SELECT ... FOR UPDATE` on the dedup query
- Engine-aware helper for transaction isolation in `src/utils/db.py`
- Regression-lock test using fixture parametrized over sqlite/postgres
- Sibling-search across `src/` for other SQLite-only `BEGIN`/`ROLLBACK`/`SAVEPOINT` keywords

**Effort:** ~1 hour (small but needs careful test design for race condition coverage)

---

## P1 — Data integrity / observability gaps

### P1-1. ~~14 trades with sentinel `duration_days=999`~~ — **CLOSED 2026-05-18 v0.36.16**

**Resolution:** `scripts/backfill_v0.36.13_archaeology.py` ran with COMMIT. All 14 affected trades cleared (all `exit_reason='unknown'` — the 3 'manual' trades from the original spec had already been cleared via a prior session, count was 0 at run time).

**Two script PG-compat patches shipped with the cleanup:**
- Raw psycopg2 connection wrapped with `PostgresConnectionWrapper` from `src.utils.db` so the script's `conn.execute()` calls work (psycopg2 raw conns don't expose top-level execute).
- Regime-table probe rewritten to query `information_schema.tables` rather than `SELECT FROM <name>` — the latter aborted the PG transaction on missing relations, cascading every subsequent query in the script to "current transaction is aborted".
- 3 regression-lock tests added at `tests/scripts/test_backfill_v0_36_13_archaeology_pg_compat.py`.

**Post-state (PG halcyon):** `duration_days=999` count is now 0. `regime_at_entry IS NULL` count remains 555 (informational; P2-2 territory).

**Effort actual:** ~25 min (5 min cleanup execution + 20 min script PG-compat patches + tests)

---

### P1-2. 74 shadow_trades with NULL `recommendation_id` (orphan trades)

**Evidence:** PG query A7 — 74 orphan trades. These cause the `data_collector.py` SELECT collision class (the underlying cause we fixed in v0.36.13 T1).

**Fix path:**
- Code-level: v0.36.13 T1 fix already handles them via UNMEASURED skip
- Data-level: the 74 orphans are historical (MO/BK/etc manual cleanups + early Phase 1 trades). Best-effort backfill: try to match each orphan trade against a recommendation by `(ticker, scan_date, setup_type)` proximity. Lower priority — they don't actively cause issues post-v0.36.13.

**Effort:** ~2 hours if doing the proximity-match backfill, or punt indefinitely

---

### P1-3. 53 quarantined trades (42 closed, 11 rejected)

**Evidence:** PG query A9 — `COALESCE(quarantined, 0) != 0` count = 53.

**Need to investigate:** what put these into quarantine? Schema registry mentions `scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py`. May be a historical migration artifact, or active quarantine logic firing. Unclear.

**Fix path:**
- Investigate: what code paths SET `quarantined=1`?
- Audit: review the 53 trades — are they genuinely bad data, or false-positive quarantine?
- Either clean them or document why they stay quarantined

**Effort:** ~1 hour investigation + cleanup TBD

---

### P1-NEW-1. ~~Reconciler creates duplicate open shadow_trades~~ — **CLOSED 2026-05-18 v0.36.17**

**Resolution:** Reconciler's orphan-check tracked-status filter extended to include `exit_failed` and `exit_pending` (was `'open'` only). The brief window where a trade transitions through `exit_failed` no longer leaks the trade out of `tracked_map`, preventing the duplicate orphan-backfill.

ETN DB cleanup committed: `465b63ed` (no OID, no fills) closed with new vocab `'duplicate_orphan_backfill'`. Canonical `90f28c15` (active OCO `b93cc89c`) reverted to `open` from `needs_manual_review`.

2 new regression-lock tests at `tests/shadow_trading/test_reconcile_orphan_status_tracking.py`.

**Original trace** (for posterity):

**Evidence:** ETN has 2 open shadow_trades (`90f28c15...` with bracket OID, `465b63ed...` without) for a single 5-share broker position.

**Reproduction trace (from logs):**
- 09:02:17 — `[EXIT] Closed ETN — P&L $8.10 (0.4%)` — original `415531e1` timed out (held 11 days)
- 09:07:14 — `[RECONCILE-PAPER] Cancelled 1 dangling orders for ETN before backfill`
- 09:07:24 — `[RECONCILE-PAPER] Backfilled orphaned position: ETN (5.0000 shares @ $419.24)` — creates `90f28c15`
- 09:07:27 — `[RECONCILE-PAPER] Auto-attached OCO for ETN (oid=b93cc89c..., qty=5)`
- 09:31:12 — `[SHADOW] Placing paper SELL: 5 shares of ETN` — exit cycle (re)tried exit on `90f28c15`
- 09:31:12 — `APIError: insufficient qty available — 5 held_for_orders by bracket b93cc89c`
- 09:31:17 — `[EXIT] Broker exit failed for ETN — marking exit_failed (retry=1)`
- 09:32:09 — `[RECONCILE-PAPER] Backfilled orphaned position: ETN` — **SECOND orphan-backfill creates `465b63ed`**
- 09:32:11 — `[RECONCILE-PAPER] Bracket auto-attach for ETN skipped: stop $398.28 >= current $393.58`
- 09:32:16 — `[RECONCILE-PAPER] Reverted premature exit to open: ETN` — restores `90f28c15` to status='open'

**Root cause hypothesis:** The reconciler's "revert premature exit" and "orphan backfill" passes don't see each other's pending writes in the same scan cycle. When the 09:32 cycle ran:
- Pass A (orphan-backfill): scans broker positions, sees ETN with no MATCHING open shadow_trade (because `90f28c15` was still `exit_failed`). Creates `465b63ed`.
- Pass B (premature exit revert): scans `exit_failed` trades, finds `90f28c15`, restores to `open`.
- Result: two open shadow_trades for the same broker position.

**Why only ETN today:** the pattern requires `timeout-exit → orphan-backfill → premature-exit retry fails → revert + duplicate orphan`. Other tickers (AMD/AMZN/etc.) escaped because their timeouts cleanly closed and orphan-backfilled without the secondary exit retry.

**Fix path:**
- Inside reconciler: orphan-backfill should also check `exit_failed`/`exit_pending` shadow_trades for the ticker before creating a new row. Match a candidate trade for revival rather than create.
- Order operations within a single reconcile cycle so "revert premature exit" runs FIRST, then orphan-backfill sees the revived row.
- Regression test using sqlite memory fixture with the exact 4-trade lifecycle.

**Immediate cleanup needed:** close the duplicate `465b63ed` (no bracket, no fills, planned but no shares attributed) with `exit_reason='duplicate_orphan_backfill'` or similar new vocabulary item. The remaining `90f28c15` is the canonical record with active OCO protection.

**Effort:** 30 min cleanup + 1-2 hours code fix + tests

---

### P1-NEW-2. ~~`coerce_exit_reason()` doesn't recognize `'position_already_closed'`~~ — **CLOSED 2026-05-18 v0.36.17**

**Resolution:** Added `'position_already_closed'` to `CONTROLLED_VOCAB` in `src/shadow_trading/exit_reason.py`. Also added to `EXCLUDED_FROM_OUTCOME_STATS` and to `_UNMEASURABLE_EXIT_REASONS` in `cto_report.py` + `model_monitor.py`. 6 regression-lock tests.

**Original problem:**

**Evidence:** 4 events in this morning's logs:
```
[EXECUTOR] CVX position already closed at broker (qty=0) — marking exit_pending:position_already_closed for reconcile
[EXIT_REASON_INVALID] received='position_already_closed' ticker=CVX fallback=unknown
```

`coerce_exit_reason()` lives in `src/shadow_trading/exit_reason.py`. The controlled vocabulary doesn't include `'position_already_closed'`, so it falls back to `'unknown'`. This pollutes the exit-reason histogram and removes a useful broker-side signal.

**Fix path:** add `'position_already_closed'` (or normalize to `'broker_already_closed'`) to `_VALID_EXIT_REASONS`. Update the schema description if it lists valid reasons. Adjust audit's `_UNMEASURABLE_EXIT_REASONS` filter if appropriate (probably yes — we couldn't measure the actual P&L).

**Effort:** 15 min + regression test

---

### P1-NEW-3. ~~`connect_db` cutover-gate warning fires on every call~~ — **CLOSED 2026-05-18 v0.36.18**

**Resolution:** dedup function `_warn_db_path_ignored_once` was using `id(db_path)` (memory address) as the key — each fresh string instance got a different id, so the "once" check failed → 570/hour. Fixed to dedup by `os.path.normpath(str(db_path)).lower()` which collapses str-equal values + backslash/forward-slash path separator variants. 3 regression-lock tests.

**Original problem:**

**Evidence:** WARN cluster cluster shows:
- 465 occurrences of `[DB] connect_db(...) overridden by Phase 3 cutover gate; ARCIS_PG_CUTOVER_ENABLED=1 routes to PG. Unset to revert to SQLite path.`
- 105 occurrences of the forward-slash variant of the same path
- = 570 total in one hour

The message is informational — it confirms the cutover gate is doing its job — but it's logged at WARNING level on every single connect_db() call. The log is otherwise clean during normal operation; this single message dominates volume.

**Fix path:** change to `_warn_once` pattern (log once per process, suppress subsequent). Other Sprint 5 cutover gates use this pattern already.

**Effort:** ~15 min + test

---

### P1-NEW-4. ~~5 stale-position WARN signals~~ — **CLOSED 2026-05-18 (auto-resolved by reconciler)**

**Resolution:** the reconciler auto-closed all 5 ghost positions between 09:07-09:32 ET. The 1-hour safety guard didn't actually block closure — the guard was for IB-side outages, not Alpaca. The positions transitioned cleanly:
- BMY → closed (reconciled_stale) 09:07
- BK → closed (unknown) 09:07
- COP → closed (unknown) 09:07
- CVX → closed (unknown) 09:07
- DIS → closed (reconciled_stale) 09:07

The WARN logs I saw in the inventory scan were from the window BEFORE these closures (08:34-09:07). No code work needed.

**Original signal context:**

**Evidence:** From this morning's logs:
```
[EXECUTOR] DIS not in Alpaca positions (trade_id=ef3b0126...) — will be caught by next reconciliation cycle
[EXECUTOR] CVX not in Alpaca positions (trade_id=469e8933...) — will be caught by next reconciliation cycle
[EXECUTOR] COP not in Alpaca positions (trade_id=e7478f4c...) — will be caught by next reconciliation cycle
[EXECUTOR] BMY not in Alpaca positions (trade_id=876c6c51...) — will be caught by next reconciliation cycle
[EXECUTOR] BK not in Alpaca positions (trade_id=a6c374ee...) — will be caught by next reconciliation cycle
```

These are the Cat B ghost positions from yesterday's PG-wipe inventory. The watch loop's exit cycle detects them every scan, log a warning, and notes they'll be caught by reconcile. But they're STILL OPEN in DB an hour later — reconcile hasn't actually closed them yet.

**Hypothesis:** reconcile's 1-hour safety guard (operator memory `feedback_strict_rigor_no_handwave` and the comment in reconcile.py line 462-468) is preventing closure on these. They were "open" before today's restart, and the safety guard wants to wait for them to be "stable stale" before closing.

**Fix path:** check whether these have now passed the 1-hour guard threshold. If yes, force-close. If no, wait.

**Effort:** 10 min check + decision

---

### P1-4. 78% of closed trades have non-measurable exit reasons (75 of 96)

**Evidence:** PG query A4:
- reconciled_stale: 58
- unknown: 14
- stop_loss: 13
- target_1: 8
- timeout: 3

Of the 75 non-measurable, 10 have negative pnl (A12) suggesting real losses that weren't recorded with `stop_loss` exit_reason. Reconciliation gap.

**Fix path:**
- For `reconciled_stale`: query Alpaca's `/v2/orders` for each ticker's exit fill timestamp + price → derive real exit_reason. Backfill `exit_reason`, `actual_exit_price`, `pnl_dollars` from broker truth.
- For `unknown`: same approach, but lower confidence — broker history may not be retrievable for older trades.
- The v0.36.13 audit-hardening already filters these from quadrant/calibration math, so the audit alerts shouldn't fire. But the underlying data is still dirty.

**Effort:** ~3-4 hours (Alpaca API recon + backfill script + verification)

---

## P2 — Live-path bugs from yesterday's investigations

### P2-1. ~~`scan_service.py:405` — secondary regime bug from T6~~ — **CLOSED 2026-05-18 v0.36.17**

**Resolution:** Replaced the ternary with `feat.get("traffic_light", {}).get("regime_label") or feat.get("regime_label")`. 2 regression-lock tests at `tests/services/test_scan_service_regime_keys.py`. Next scan cycle will populate `regime_at_entry` in Telegram trade-open notifications correctly.

**Original problem context:** see [`regime_capture_followup.md`](../2026-05-17-v0.36.13-training-page/regime_capture_followup.md) from v0.36.13 T6 Path B investigation.

---

### P2-2. 12 of 18 open positions have NULL `regime_at_entry` (root cause unclear)

**Evidence:** PG query A11. Companion to P0-1 — same 12 positions that show NULL `alpaca_order_id` also show NULL `regime_at_entry`. Strongly suggests the 12 were opened via a code path that doesn't populate either field (vs the 6 protected+regime'd opens that go through a different path).

**Hypothesis:** There are TWO open-shadow-trade code paths:
- Path A (6 positions, healthy): includes bracket attach + regime capture
- Path B (12 positions, broken): missing both

**Fix path:** Trace the 12 positions back via `created_at` in logs to find which scan path created them. Identify the divergence.

**Effort:** ~1 hour investigation, then code fix TBD

---

### P2-3. ~~`[BuildScore] model_quality error: list index out of range`~~ — **CLOSED 2026-05-18 v0.36.18**

**Resolution:** `_score_model_quality()` SQL was `SELECT SUM(llm_success), SUM(llm_total) ...` without column aliases. On PG (psycopg2 RealDictCursor), both un-aliased SUMs collapse to the same column name `sum`, so the row dict has one entry — `row[1]` raises IndexError. Fixed by aliasing the SUMs (`AS success_sum`, `AS total_sum`) and accessing by name. 2 regression-lock tests at `tests/evaluation/test_build_score_model_quality_pg_compat.py`.

---

## P3 — Audit truthfulness (mostly addressed in v0.36.13, verify)

### P3-1. v0.36.13 audit hardening — verify tonight

**What to confirm tomorrow morning:** the four daily audit alerts that fired through this week (75% good process, unknown regime, 336d hold, 0% calibration) should NOT fire tonight after v0.36.13 deploy. If any still fires, that's a real bug to chase.

**Effort:** 5 min check tomorrow morning

---

### P3-2. Scorecard sibling-sweep — verify

**What to confirm:** the weekly scorecard (when next generated) should NOT show `longest_hold=999`. The v0.36.13 T4 cycle-2 sweep routed scorecard through `_measurable_hold_durations`.

**Effort:** Wait for next scorecard generation (Friday?), spot-check

---

## P4 — Test infrastructure hygiene (the v0.36.14 lesson)

### P4-1. 24 test files mentioned in conftest as "broken fallback pattern"

**Evidence:** conftest.py:31 docstring references 24 files using `os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")`. Yesterday's grep found only 3 still matching the literal pattern — but the docstring count suggests there are more variants.

**Fix path:**
- Find all such files (need a more comprehensive grep)
- Either fix them to skip cleanly when TEST_DATABASE_URL is unset, OR
- Whitelist them as "needs explicit test PG" via pytest.mark.skipif

**Effort:** ~2-3 hours (find + audit + patch each file)

**Note:** The v0.36.14 second-line defense in pg_wrapper now catches this class. But proactive sweep prevents the warning noise during normal test runs.

---

### P4-2. Test PG on port 5434 (recommended infrastructure)

**Not strictly an execution error, but enabling work for safer test cycles.** Operator memory could carry: "halcyon-pg-test on port 5434" as the canonical test PG. Sets up via docker-compose with empty schema, ready for test fixture writes.

**Fix path:** Docker compose addition + setup doc

**Effort:** ~1 hour

---

## P5 — Forward-observability (non-urgent)

### P5-1. FED scrape — first real test tonight

**Evidence:** `fed_communications` has 2 rows from 2026-04-28. v0.36.13 T2 fixed the link_filter pattern. Tonight's overnight cycle is the first real test.

**Effort:** Check tomorrow morning — if `fed_communications` count increased, fix works. If still 2, follow-up.

---

### P5-2. FINRA short-volume — first real run tonight

**Evidence:** `short_volume_daily` table is empty (created in v0.36.13 but never populated). Tonight's overnight cycle should run the new FINRA collector for first time.

**Effort:** Check tomorrow morning

---

## Summary by priority (updated 2026-05-18 post-trading-hour scan)

| Priority | Count | Total effort | Notes |
|---|---|---|---|
| P0 | 2 | ~1.5 hours | ✅ CLOSED v0.36.15 |
| P1 (original) | 4 | ~6-7 hours | 1/4 closed (P1-1 v0.36.16) |
| P1-NEW (live-trading scan) | 4 | ~3-4 hours | Discovered 2026-05-18 09:30 |
| P2 | 3 | ~2 hours | Live bugs |
| P3 | 2 | ~10 min checks | Tomorrow morning |
| P4 | 2 | ~3-4 hours | Test infra hygiene |
| P5 | 2 | ~10 min checks | Tomorrow morning |

**Updated total effort:** ~17-18 hours of focused work to clear the whole list (originally 14-15, +3-4 hours of new findings).

**Closed today (3 items via v0.36.14/15/16):** P0-1, P0-2, P1-1.

**Newly discovered (4 items, all medium severity):**
- P1-NEW-1: Reconciler creates duplicate orphan-backfill on "premature exit revert" path (active ETN duplicate)
- P1-NEW-2: `coerce_exit_reason()` doesn't recognize `'position_already_closed'` → drops signal
- P1-NEW-3: `connect_db` cutover-gate WARN noise (570/hour)
- P1-NEW-4: 5 stale ghost positions (BMY/BK/COP/CVX/DIS) flagged every scan, reconcile guard preventing closure

---

## Open questions for operator

1. **P0-1 reconciliation approach:** prefer manual Alpaca dashboard check, or automated Alpaca API sweep via a script? The latter is more thorough but takes setup.
2. **P1-3 quarantined trades:** do you remember setting these quarantine flags, or is it from an automated rule that's still firing?
3. **P1-4 reconciled_stale backfill:** worth the effort to backfill broker truth, or accept the data loss as historical?
4. **P4-2 test PG:** want me to set up halcyon-pg-test as part of this week's work, or is that a separate project?

---

## Tracking

This document is the single source of truth for the week. As items close, mark them DONE inline with the commit SHA. PR-merge moments naturally update this file.

**Next action:** operator reviews this inventory, confirms priorities (or adjusts), then we burn down starting with P0-1.
