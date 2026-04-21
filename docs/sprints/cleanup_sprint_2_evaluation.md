# Cleanup Sprint 2 — Pass 1 Evaluation

**Branch:** `fix/cleanup-sprint-2-reconcile-and-code`
**Base:** `main` @ `bf25de3a` (post-Cleanup Sprint 1 merge)
**Mode:** gated (Pass 1 + Pass 2 then STOP for operator review; Pass 3 only after green-light)
**Kill-switch:** engaged (`data/trading_halted`), untouched by this sprint
**Source artifacts:** `docs/audit/live_state_analysis_2026-04-20.md` (decision driver)

## Summary

Two disjoint tracks with zero cross-coupling:

- **Track A** — author-only one-shot DB reconciliation script `scripts/reconcile_2026_04_20.py` that updates 19 shadow_trades rows + 1 model_versions row atomically. CC **does not run it**; operator runs after Alpaca fills confirm tomorrow.
- **Track B** — 9 medium-risk code fixes, disjoint files, tests per item.

Pass 1 surfaces **six scope items** that need operator clarification at the gate before Pass 3 implements anything. These are listed explicitly at the end under **§ Gate Decisions**; do not implement Track A or Track B without resolving them.

---

## Pass-1 findings requiring operator decisions at the gate

1. **CLOSE_AT_OPEN count is 9, not 8** — the prompt lists 8 tickers (CVX, CAT, FDX, MO, BK, NEE, INTC, GM) but the 2026-04-20 live-state-analysis table (row #16) also classifies `GS` as `CLOSE_AT_OPEN` with `buy 18`. My Pass-2 audit's classification-summary bullet undercounted by one; the prompt inherited that undercount. Alpaca currently shows `GS qty=-18 short at avg $936.47, unrealized_pl=+$287.46`. **Operator decision: include GS in CLOSE_AT_OPEN (making it 9) — yes/no.**

2. **`notes` column does not exist on `shadow_trades`.** The schema has 64 columns; the closest is `exit_reason` (short-text, already used for codes like `reconciled_stale`, `target_1_hit`, `exit_overshoot_detected`). No `notes`, `comment`, `metadata`, or free-text column. **Operator decision: (a) add a `notes` column via schema registry + migration (scope expansion), (b) repurpose `exit_reason` with a new code like `manual_reconcile` and persist full prose in the audit log file, (c) skip persisting notes in the DB and rely entirely on the audit log file.** Recommend (b) — preserves DB schema, still puts a discoverable marker on the row.

3. **Status values `closed_manual_reconcile` and `orphan` are not canonical.** `src/shadow_trading/models.py:19-20` defines:
   ```
   TERMINAL_STATUSES = frozenset({"closed", "rejected", "failed", "exit_abandoned", "needs_manual_review"})
   ACTIVE_STATUSES   = frozenset({"pending", "open", "exit_pending", "exit_failed", "submission_uncertain"})
   ```
   Queries and reports (`src/scheduler/reports.py`, `src/scheduler/watch.py`, `src/shadow_trading/executor.py`) filter on `status='closed'` exclusively; a new value would be invisible to win-rate, EOD recap, and dashboard queries. **Operator-prompt anti-goal already addresses this** ("if `closed_manual_reconcile` conflicts, use existing close-status naming convention"). Proposed mapping:
   - 8 or 9 `CLOSE_AT_OPEN` + 3 `NEEDS_OPERATOR_JUDGMENT` → `status='closed'` with `exit_reason='manual_reconcile'` (new exit_reason code; no conflict — checked today's 7 distinct exit_reason values).
   - 7 `MARK_ORPHAN` → `status='exit_abandoned'` with `exit_reason='phantom_row_cleanup'`. `exit_abandoned` is the closest canonical fit for "we tried to exit but there's no position to close."
   **Operator decision: confirm the `closed` + `exit_abandoned` mapping or pick alternatives.**

4. **Alpaca pre-flight check requires importing alpaca_adapter.** The prompt's anti-goal says *"Script has NO external imports beyond stdlib + `src.config` for DB_PATH"* but also requires *"Alpaca verification: calls `get_all_positions()`, asserts zero short positions"* which needs `src.shadow_trading.alpaca_adapter`. **Operator decision: (a) relax the anti-goal to allow `alpaca_adapter` and `alpaca` SDK imports for the pre-flight only, (b) skip the Alpaca check entirely and trust the operator's pre-run confirmation, (c) replace the automated check with an interactive `input("Confirm Alpaca shows zero shorts for ...? [y/N]: ")` prompt.** Recommend (a) — the automated check is the strongest safety net against running before Alpaca fills.

5. **Track B item L — "release counter on rejection" — the diagnosis is wrong.** The prompt says: *"Pattern: `committed += required` then on reject `committed -= required`."* But `src/shadow_trading/executor.py:184-222` shows the increment fires **only on success** (line 221, after `return True` path), never on rejection. The true bug is that `_scan_cycle_committed` carries across scan cycles — the $37,942 persists because it is the **successful** AMD+SPG commits from the 09:49 scan (AMD $278.85 × 48 = $13,384, SPG $206.37 × 119 = $24,558, sum = $37,942 exact), and `reset_scan_cycle_committed()` at `src/services/scan_service.py:37` either isn't firing on subsequent scans or the bootcamp path bypasses it. **Operator decision: (a) accept the original fix framing is wrong and redirect L to an audit of scan-start-reset invocation paths, (b) apply a defensive decrement anyway (harmless but doesn't fix the real bug), (c) split L into L-a (reset-path audit) and L-b (defensive decrement).** Recommend (a). Pass 2 will trace the full scan-lifecycle path.

6. **Track B item H8 is a schema migration, not a writer fix.** The prompt says *"Ensure `id` column is populated on every INSERT (autoincrement or explicit UUID — match existing schema pattern)."* But the live DB schema is `CREATE TABLE activity_log ("event_type" TEXT, "detail" TEXT, "created_at" TEXT, "level" TEXT, id INTEGER)` — `id INTEGER` **without PRIMARY KEY or AUTOINCREMENT**. None of the 4 writers pass `id` because the schema doesn't hint they should, and SQLite doesn't auto-populate a plain INTEGER column. The fix is a registry change in `src/schema/registry.py:1370` to make `id INTEGER PRIMARY KEY AUTOINCREMENT` (or equivalent), then `python -m src.main validate-schema --fix` to run the migration. **This is a migration, not a code fix.** CLAUDE.md § "Database Schema Rules" mandates the registry-first workflow. **Operator decision: (a) proceed with schema migration in Sprint 2 (scope expansion), (b) defer H8 to a dedicated schema sprint, (c) hack writers to generate sequential ids via `SELECT COALESCE(MAX(id),0)+1` (ugly, race-prone, not recommended).** Recommend (b) — H8 deserves its own review because migration tools need careful validation. If deferred, Sprint 2 keeps the 8 remaining Track-B items.

## Coupling check — Track A vs. Track B

No cross-coupling:

| Track A writes | Tables `shadow_trades` (19 rows), `model_versions` (1 row). Uses `exit_reason` text column on shadow_trades. Appends to flat audit-log file `docs/audit/reconcile_2026_04_20_execution.log`. Does **not** write to `activity_log`, which decouples Track A from Track B's H8. |
| Track B edits  | `src/shadow_trading/executor.py` (L, K), `src/shadow_trading/reconcile.py` (C2-partial, H7), `src/risk/governor.py` (H4), `src/features/traffic_light.py` (H5), `src/schema/registry.py` + migration (H8 if accepted), `src/notifications/telegram.py` (L5), `config/settings.local.yaml` (cap). |

Track B files never touch the 19 rows Track A will UPDATE. Track A file never touches code Track B edits. Tests are in separate directories. The config-cap change takes effect the next time the watch loop restarts — has no bearing on Track A script.

Only indirect consideration: **if H8 is included**, it rebuilds the `activity_log` table, which would briefly lock the DB. Operator should run Track A script **before** or **after** the H8 migration, not interleaved. Pass 2 will note this explicitly.

---

## Track A — DB reconciliation script

### Target file

`scripts/reconcile_2026_04_20.py`

### Behavior (pseudocode)

```python
#!/usr/bin/env python
"""One-shot DB reconciliation for 2026-04-20 broken-state trades.

Run AFTER confirming Alpaca shows zero short positions for the 12 target
tickers (operator closes via Alpaca UI, then runs this script).

Idempotent: re-runs skip rows already in target terminal state.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH
from src.shadow_trading.alpaca_adapter import get_all_positions  # pending gate #4

# ---- Target rows (19 trades + 1 model) ----
# trade_id, ticker, target_status, exit_reason_code, detail_note
CLOSE_TRADES = [
    # CLOSE_AT_OPEN (8 or 9 — pending gate #1)
    ("<cvx_5_uuid>", "CVX", "closed", "manual_reconcile", "..."),
    ("<cat_6_uuid>", "CAT", "closed", "manual_reconcile", "..."),
    ("<fdx_uuid>",   "FDX", "closed", "manual_reconcile", "..."),
    ("<mo_uuid>",    "MO",  "closed", "manual_reconcile", "..."),
    ("<bk_uuid>",    "BK",  "closed", "manual_reconcile", "..."),
    ("<nee_uuid>",   "NEE", "closed", "manual_reconcile", "..."),
    ("<intc_uuid>",  "INTC","closed", "manual_reconcile", "..."),
    ("<gm_uuid>",    "GM",  "closed", "manual_reconcile", "..."),
    # ("<gs_uuid>",  "GS",  "closed", "manual_reconcile", "..."),  # pending gate #1
    # NEEDS_OPERATOR_JUDGMENT (3)
    ("<googl_uuid>", "GOOGL","closed", "manual_reconcile", "4x overshoot; single close @ open"),
    ("<nvda_uuid>",  "NVDA", "closed", "manual_reconcile", "5x overshoot; split close 100/75/70"),
    ("<tgt_11_uuid>","TGT",  "closed", "manual_reconcile", "broker tag corrected to alpaca"),
]
ORPHAN_TRADES = [
    ("<aapl_uuid>",  "AAPL", "exit_abandoned", "phantom_row_cleanup", "backfill default never fired"),
    ("<wmt_2026_04_01_uuid>", "WMT", "exit_abandoned", "phantom_row_cleanup", "live-era ghost"),
    ("<cat_2026_04_01_uuid>", "CAT", "exit_abandoned", "phantom_row_cleanup", "live-era ghost"),
    ("<cvx_2026_04_01_uuid>", "CVX", "exit_abandoned", "phantom_row_cleanup", "live-era ghost"),
    ("<sbux_uuid>",  "SBUX","exit_abandoned", "phantom_row_cleanup", "no Alpaca position"),
    ("<cat_2026_04_17_uuid>", "CAT", "exit_abandoned", "phantom_row_cleanup", "phantom open row; short belongs to #6"),
    ("<tgt_2026_04_13_uuid>", "TGT", "exit_abandoned", "phantom_row_cleanup", "ib-tagged phantom"),
]
MODEL_UPDATE = (
    "arcis:v1.0.0",
    "active",
    "Re-activated 2026-04-20 after three-way reconciliation found Ollama+config still operational on this model; rollback was not operationally executed. See docs/audit/live_state_analysis_2026-04-20.md.",
)
SHORT_CHECK_TICKERS = ["CVX","CAT","FDX","MO","GOOGL","NVDA","TGT","BK","NEE","INTC","GM","GS"]

def main():
    log_path = Path("docs/audit/reconcile_2026_04_20_execution.log")
    log_lines = []
    def log(msg):
        stamp = datetime.now(timezone.utc).isoformat()
        line = f"{stamp} {msg}"
        print(line)
        log_lines.append(line)

    # Pre-flight 1: kill-switch engaged
    if not Path("data/trading_halted").exists():
        log("ABORT: data/trading_halted missing. Refusing to run without halt.")
        sys.exit(2)

    # Pre-flight 2: Alpaca shows zero shorts
    positions = get_all_positions()
    for p in positions:
        if p["symbol"] in SHORT_CHECK_TICKERS and p["qty"] < 0:
            log(f"ABORT: {p['symbol']} still short {p['qty']} on Alpaca. Close via UI first.")
            sys.exit(3)
    log(f"Pre-flight OK: zero shorts for {SHORT_CHECK_TICKERS}")

    # Main transaction
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        cur = conn.cursor()

        for trade_id, ticker, target_status, exit_reason_code, detail in CLOSE_TRADES + ORPHAN_TRADES:
            # Idempotency: skip if already in target status
            row = cur.execute(
                "SELECT status, exit_reason FROM shadow_trades WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
            if row is None:
                log(f"SKIP: trade_id={trade_id} not found")
                continue
            cur_status, cur_reason = row
            if cur_status == target_status and cur_reason == exit_reason_code:
                log(f"SKIP (already resolved): {ticker} {trade_id} → {target_status}/{exit_reason_code}")
                continue
            cur.execute(
                "UPDATE shadow_trades SET status=?, exit_reason=?, updated_at=? WHERE trade_id=?",
                (target_status, exit_reason_code, datetime.now(timezone.utc).isoformat(), trade_id),
            )
            log(f"UPDATE {ticker} {trade_id}: status={cur_status}→{target_status}, exit_reason→{exit_reason_code}. Detail: {detail}")

        # TGT #11 broker-tag correction (separate UPDATE per gate #3 mapping)
        cur.execute(
            "UPDATE shadow_trades SET broker='alpaca' WHERE trade_id=? AND broker='ib'",
            ("<tgt_11_uuid>",),
        )
        if cur.rowcount == 1:
            log("UPDATE TGT broker tag: ib → alpaca")

        # Model registry
        model_name, model_status, model_notes = MODEL_UPDATE
        cur.execute(
            "UPDATE model_versions SET status=?, notes=? WHERE version_name=? AND status != ?",
            (model_status, model_notes, model_name, model_status),
        )
        if cur.rowcount == 1:
            log(f"UPDATE model_versions: {model_name} → status={model_status}")
        else:
            log(f"SKIP model_versions: {model_name} already active or not found")

        # Post-update verification (assert counts)
        close_count = cur.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE trade_id IN (...) AND status='closed'"
        ).fetchone()[0]
        orphan_count = cur.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE trade_id IN (...) AND status='exit_abandoned'"
        ).fetchone()[0]
        model_active = cur.execute(
            "SELECT COUNT(*) FROM model_versions WHERE version_name=? AND status='active'",
            (model_name,),
        ).fetchone()[0]

        expected_close = 11  # or 12 if gate #1 includes GS
        expected_orphan = 7
        if close_count != expected_close or orphan_count != expected_orphan or model_active != 1:
            log(f"ABORT: verification failed. close={close_count}/{expected_close} orphan={orphan_count}/{expected_orphan} model={model_active}/1")
            conn.rollback()
            sys.exit(4)

        conn.commit()
        log(f"SUCCESS: {close_count} closed, {orphan_count} orphan, 1 model active")

    # Append audit log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    print(f"Audit log: {log_path}")

if __name__ == "__main__":
    main()
```

Pass 2 will replace the `<...uuid>` placeholders with real trade_ids extracted from the DB.

### Track A tests

`tests/scripts/test_reconcile_2026_04_20.py`:

1. **End-to-end happy path**: seed test DB with all 19 rows + model_versions row; run script with `get_all_positions` mocked to return empty shorts; assert final state (11 closed, 7 exit_abandoned, 1 active model).
2. **Idempotency**: run twice. First run: N updates, second run: zero UPDATEs, all lines logged as SKIP.
3. **Abort on persistent short**: mock `get_all_positions` to return `NVDA qty=-100`; assert `SystemExit(3)` with log entry naming NVDA; assert DB unchanged.
4. **Abort on missing kill-switch**: delete `data/trading_halted` mock; assert `SystemExit(2)`; assert DB unchanged.
5. **Transaction rollback on verification failure**: inject a synthetic row-count mismatch (e.g., by patching expected_close to 999); assert `SystemExit(4)`; assert DB unchanged (rollback fired).

---

## Track B — code fixes (Pass 1 per-item evaluation)

### L — `_scan_cycle_committed` lifecycle

**Prompt-proposed fix:** decrement on rejection.
**Actual code:** `src/shadow_trading/executor.py:184-222` — increment is on **success only** (line 221). Rejections don't touch the counter.
**Real bug:** counter persists across scan cycles despite `reset_scan_cycle_committed()` existing at `executor.py:178` and being called from `src/services/scan_service.py:37`. Pass 2 will trace whether bootcamp's scan path skips that reset, or whether it's a process-lifetime issue.

**Blast radius:** module-level global state in executor.py. Any caller relying on the committed counter within a scan cycle (the `_check_paper_buying_power` race-condition fix per #392) would be affected. Tests need to mock `get_account_info` and verify counter state transitions.

**Test plan:** `tests/shadow_trading/test_scan_cycle_counter.py`:
- Counter starts at 0, successful BP check advances it, next successful BP check accumulates.
- Rejected BP check does NOT advance the counter (current behavior, lock in).
- After `reset_scan_cycle_committed()` counter returns to 0.
- Multi-scan simulation: 2 successful trades → reset → 2 more successful trades → counter reflects only the 2nd scan's commits.

Pending gate #5 — operator direction on real-vs-proposed-bug framing.

### K — BP check pre-LLM

**Current state:** `_check_paper_buying_power` at `executor.py:184-231`; invocation at `executor.py:598` (inside `open_shadow_trade`, after risk checks + LLM inference at ~570). Live-trade path at `executor.py:1927` is a resize-to-fit (`planned_shares = min(planned_shares, max_shares_by_bp)`), **not** a boolean reject — different semantics. Moving it earlier requires only the paper path refactor; the live path already resizes, not rejects, so pre-LLM check there would change behavior (forcing a reject where today there's a resize).

**Blast radius (paper):** single invocation site change; move from :598 to pre-LLM. Must ensure the planned_shares passed to BP check matches what the LLM would have seen.

**Test plan:** `tests/shadow_trading/test_bp_preflight.py` — mock `get_account_info` to return BP below required; mock `ollama.generate` and assert it was NOT called; assert trade recorded with `order_type='rejected_buying_power'`.

### Bootcamp cap 20 → 8

**File:** `config/settings.local.yaml:103`
**Change:** `max_packets_per_scan: 20` → `max_packets_per_scan: 8`
**Rationale (arithmetic):** per the live-state analysis §4, today's 20-cap × ~$15.5K packet = $310K needed vs. $6,982 BP. Post-reconcile BP should recover to ~$100-200K range. 8 × $15.5K = $124K, comfortable fit. Matches `settings.example.yaml:455` default.
**Test plan:** none; config-only.

### C2-partial — cancel-before-close helper

**Location:** `src/shadow_trading/reconcile.py:498, 511` (per audit). Pass 2 will confirm line numbers (post-Sprint 1 drift possible).
**Fix:** Extract a helper `cancel_orders_for_ticker(ticker: str) -> list[str]` that calls `client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker]))` then cancels each. Return the list of cancelled order IDs for caller logging.
**Blast radius:** reconcile.py's orphan-backfill paths. Callers to update: the two invocation sites at :498, :511. No behavior change for callers that don't use the helper.
**Test plan:** `tests/shadow_trading/test_reconcile_cancel_before_close.py` — mock Alpaca to return 2 open orders for ticker, assert both cancelled + ids returned.

### H4 — governor-disabled alert

**Location:** `src/risk/governor.py:394-400` — currently returns `approved=True` with a `governor_disabled` check entry. No logger.critical, no Telegram.
**Fix:** Add `logger.critical("[RISK] Governor disabled — all trades auto-approved; review config/settings.local.yaml.")` before the return. Conditionally call `src.notifications.telegram.send_telegram(f"[FAIL] RISK GOVERNOR DISABLED — all trades auto-approved.")` if `is_telegram_enabled()`. Idempotency concern: don't spam per-trade; use a module-level flag to emit once per process lifetime.
**Blast radius:** governor.py. Tests that stub governor and set `enabled=False` need to now also mock telegram/logger. Existing tests likely tolerate warning-level but not critical.
**Test plan:** `tests/risk/test_governor_disabled_alert.py` — set `enabled=False`, call `assess_trade`, assert `logger.critical` fired once, `send_telegram` called once. Call again — assert no re-emission.

### H5 — traffic-light `int + str` TypeError

**Location:** `src/features/traffic_light.py:91-119` `_classify_credit`.
**Root cause (confirmed):** `macro_snapshots.value` for `series_id='BAMLH0A0HYM2'` is stored as TEXT ('2.86', '2.86', ...). Line 102 builds `values = [r[0] for r in rows if r[0] is not None]`. Line 106 computes `sum(values) / len(values)` → `sum()` with int seed `0` + string `'2.86'` raises `TypeError: unsupported operand type(s) for +: 'int' and 'str'`.
**Fix:** Line 102 → `values = [float(r[0]) for r in rows if r[0] is not None]`. Optional hardening: wrap `float()` in try/except to skip malformed values rather than reject the whole set.
**Blast radius:** single function. Today's 26 warnings cease. Regime classification `_classify_credit` now produces real z-scores instead of always returning `0` (Green fallback).
**Separately:** the TEXT-vs-REAL storage is a **data-layer drift** — `macro_snapshots.value` should be REAL/FLOAT. Out of scope for H5 (column-type migration would touch the upstream FRED collector). Flag to operator for a later data-cleanup sprint. With H5 fix, traffic-light starts working regardless.
**Test plan:** `tests/features/test_traffic_light_credit.py` — seed mock macro_snapshots with 50 rows of stringified values; assert `_classify_credit` returns 0/1/2 based on z-score without warnings.

### H7 — bare `sqlite3.connect()` in `reconcile.py`

**Locations (confirmed via grep):** `src/shadow_trading/reconcile.py:413, 606, 634, 645, 688, 704, 712` — 7 sites, all as context managers (`with sqlite3.connect(db_path) as conn:`).
**Canonical wrapper:** `connect_db()` in `src/utils/db.py` (per CLAUDE.md). Applies `busy_timeout=30s`, `row_factory=sqlite3.Row`, PRAGMA foreign_keys, WAL mode.
**Fix:** mechanical replacement — import at top, swap each `sqlite3.connect(db_path)` → `connect_db(db_path)`. Pass 2 verifies `connect_db` is drop-in-compatible with context-manager usage (it should be; other code uses it that way).
**Blast radius:** reconcile.py read/write paths. Callers get busy_timeout and row_factory "for free." One behavior change: `row_factory=Row` means callers indexing rows by integer keep working (Row supports both int and str indexing); callers relying on plain tuples might need a cast.
**Test plan:** existing reconcile tests should still pass. New test in `tests/shadow_trading/test_reconcile_connection.py`: patch `connect_db` and assert it was called 7× with the expected paths; additionally assert `PRAGMA foreign_keys` returns 1 on the returned connection.

### H8 — `activity_log` NULL id writer  → **schema migration**

**Schema (confirmed):** `CREATE TABLE activity_log ("event_type" TEXT, "detail" TEXT, "created_at" TEXT, "level" TEXT, id INTEGER)` — `id` is plain INTEGER without PRIMARY KEY.
**Registry entry:** `src/schema/registry.py:1370` defines the table.
**Writer sites:** 4 (`src/logging/activity.py:65`, `src/utils/activity_logger.py:56`, `src/notifications/telegram_commands.py:148`, `src/scheduler/reports.py:389`) — all omit `id` from INSERT. SQLite does not auto-populate plain-INTEGER columns.
**Result:** 1,427 NULL ids observed in the DB (per 2026-04-20 audit). render_sync silently drops them.

**Fix (correct):** registry change — `id INTEGER PRIMARY KEY AUTOINCREMENT` (or `INTEGER PRIMARY KEY` which SQLite aliases to rowid). Then migration: `python -m src.main validate-schema --fix`. Then Postgres sync: `python scripts/render_migrate.py`. SQLite cannot ADD PRIMARY KEY on an existing column — would need a full table rebuild via CREATE → INSERT SELECT → DROP → RENAME. The `validate-schema --fix` may or may not handle this; needs Pass 2 investigation.

**Gate #6 — recommend deferring H8 to a dedicated schema sprint.** If operator accepts, drop H8 from Sprint 2 and re-file as SprintTicket.

---

## Sprint-wide anti-goals (per prompt)

- Sprint does NOT execute Track A script (operator runs post-Alpaca-fills).
- Sprint does NOT submit Alpaca orders.
- Sprint does NOT lift kill-switch.
- Sprint does NOT touch M-series items (M1-M16 from the 2026-04-20 audit).
- Separate commits per Track B item (9, or 8 if H8 deferred).

## Out of scope — filed separately (per prompt)

- AAPL 24-day stop=0/target=0 root-cause investigation.
- model_versions rollback archaeology.

## Gate decisions required (STOP here, operator review)

Before Pass 3 implements anything, the operator must resolve **six** questions — listed top of doc, repeated here for bookmarking:

1. **Include GS in CLOSE_AT_OPEN?** (9 rows vs. 8 — likely yes, Alpaca has GS -18.)
2. **How to persist the operator-decision notes?** Recommend: exit_reason code + flat audit-log file.
3. **Confirm terminal-status mapping?** Recommend: `closed` for 11/12, `exit_abandoned` for 7.
4. **Alpaca import for pre-flight?** Recommend: allow `alpaca_adapter` import (anti-goal relax).
5. **Redirect L fix from "decrement on reject" to "audit reset-path invocation"?**
6. **Defer H8 (schema migration) to a separate sprint?**

## Pass-2 plan (runs next before STOP)

- Extract all 19 trade_ids from the DB by (ticker, entry_date) tuples from the live-state analysis table.
- Confirm exact line numbers for H4, H7, H8 writers, C2-partial after any post-Sprint-1 file drift.
- For K + L: trace scan → ranker → executor BP path end-to-end to confirm where to insert the pre-LLM BP check and to locate the scan-start reset hook.
- For L5: identify which PnL value arrives as str (most likely `best_pct` or `worst_pct` via `pnl_pct` column).
- Confirm `connect_db()` is drop-in-compatible with `with ... as conn:` usage in reconcile.py (H7).
- Write `docs/sprints/cleanup_sprint_2_research.md`, commit, push, **STOP**.
