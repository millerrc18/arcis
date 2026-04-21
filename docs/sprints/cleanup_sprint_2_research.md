# Cleanup Sprint 2 — Pass 2 Research

**Branch:** `fix/cleanup-sprint-2-reconcile-and-code`
**Base:** `main` @ `bf25de3a` (post-Sprint 1)
**Prereq:** `cleanup_sprint_2_evaluation.md` (Pass 1, commit `e743607`)

Pass 2 confirms line numbers, resolves all 19 trade_ids, traces the BP path, and corrects two Pass-1 claims. After this commit, **STOP** for operator review.

---

## 1. 19 trade_ids — resolved

Cross-referenced via `(ticker, DATE(created_at), status)` tuple; every target row matched exactly **one** DB row. Broker column preserved for awareness.

| # | Class | Ticker | Created | Status | Shares | trade_id | Broker |
|---|---|---|---|---|---|---|---|
| 1 | CLOSE | CVX | 2026-04-09 | needs_manual_review | 38 | `7084665a-bf4f-40d5-aff5-b5cd5ebdd3ee` | alpaca |
| 2 | CLOSE | CAT | 2026-04-09 | needs_manual_review | 9 | `217eddba-606e-44ea-ad88-78d90c2b0419` | alpaca |
| 3 | CLOSE | FDX | 2026-04-13 | needs_manual_review | 28 | `07046983-14f1-48ca-bf60-e0c1d8f00d6c` | alpaca |
| 4 | CLOSE | MO  | 2026-04-13 | needs_manual_review | 169 | `b54f0a67-a4d6-4b34-b9b3-ef4a80c1a6be` | alpaca |
| 5 | CLOSE | BK  | 2026-04-14 | needs_manual_review | 96 | `5bd67cab-092a-478a-84ba-8e3938e7de98` | alpaca |
| 6 | CLOSE | NEE | 2026-04-15 | needs_manual_review | 153 | `a685fc8a-d173-42b3-ab79-ddb5c47035ca` | alpaca |
| 7 | CLOSE | INTC| 2026-04-15 | needs_manual_review | 74 | `7e71d087-03d4-4dee-bde1-554ceebedabc` | alpaca |
| 8 | CLOSE | GM  | 2026-04-15 | needs_manual_review | 216 | `3d8251d2-174b-4115-b4d9-bd2b49231a3c` | alpaca |
| 9 | CLOSE | **GS** (gate #1) | 2026-04-16 | needs_manual_review | 18 | `d42a5afc-7e2b-4ff3-bba0-6eaf23f61a49` | alpaca |
| 10 | JUDGE | GOOGL | 2026-04-13 | needs_manual_review | 13 | `3dcf9f7e-2195-4975-b01b-c2387f74e283` | alpaca |
| 11 | JUDGE | NVDA | 2026-04-13 | needs_manual_review | 49 | `f01dc590-f4f1-4049-ac73-6572da43b735` | alpaca |
| 12 | JUDGE | TGT  | 2026-04-14 | needs_manual_review | 161 | `f00641fe-77b3-4da3-a78d-83d8cef19bd9` | **ib** (to be corrected to alpaca) |
| 13 | ORPHAN | AAPL | 2026-03-27 | exit_failed | 0 | `1630b6c5-d7df-44f6-aca6-d0c4826ca697` | alpaca |
| 14 | ORPHAN | WMT  | 2026-04-01 | exit_failed | 1 | `bb10c4b7-1952-40fd-9a3a-c5db9b96c018` | alpaca |
| 15 | ORPHAN | CAT  | 2026-04-01 | exit_failed | 1 | `9ad299c0-cf79-45f1-854a-3aa7b6ee2925` | alpaca |
| 16 | ORPHAN | CVX  | 2026-04-01 | exit_failed | 1 | `ce1322fd-3035-4e2d-9c08-10ad3755e00b` | alpaca |
| 17 | ORPHAN | SBUX | 2026-04-10 | open | 1 | `09b629e3-0bf6-4ba7-8293-73f4f3f90265` | alpaca |
| 18 | ORPHAN | CAT  | 2026-04-17 | open | 2 | `748a97f1-c0e9-462c-9ce0-41deaefa00dc` | alpaca |
| 19 | ORPHAN | TGT  | 2026-04-13 | open | 76 | `730a113b-eb9b-4040-a320-6aaebacb3f2a` | **ib** (left as ib — IB is dormant; no Alpaca cleanup available) |

**Zero ambiguity — every (ticker, date, status) triple uniquely identifies a row.** Pass 3 can embed these UUIDs directly.

---

## 2. Race vs. watch loop

Kill-switch engaged (`data/trading_halted` present). The pre-flight check (step 1 of the script) refuses to run without it, so the race is closed by design. Additionally:

- Sprint 1 fixed C3 (reconcile_dispatch db_path=None), but reconcile still runs on the intra-day 15-min throttle in `src/scheduler/watch.py:694` if the watch loop is up.
- With kill-switch file present, the executor's entry paths short-circuit before any new orders; however, **the reconciler still runs** and would see the 12 `needs_manual_review` rows.
- Reconciler's current behavior on those rows: it leaves them alone (no orphan backfill since rows exist, no close since status is terminal).

**Conclusion:** Track A script is safe to run while watch loop is up, as long as kill-switch stays engaged. Operator may nonetheless prefer to pause the loop out of defensive habit.

---

## 3. Track B — line-number confirmation + corrections

### L — `_scan_cycle_committed` lifecycle (Pass-1 hypothesis confirmed; real bug located)

`src/services/scan_service.py:35-37`:
```python
# #392: Reset per-cycle buying power tracker to prevent stale state
from src.shadow_trading.executor import reset_scan_cycle_committed
reset_scan_cycle_committed()
```

So the reset **is** wired to the main scan entry. **The bug hypothesis (counter persists across scans) remains valid for the 2026-04-20 evidence** — $37,942 matched exactly the AMD ($13,384) + SPG ($24,558) commits from the morning's 09:49 scan. If reset were firing, the 11:15+ scans should have started with `committed=$0`.

Candidate root causes:
1. **Bootcamp has a separate scan path** that bypasses `scan_service.run_scan` → no reset invocation. Pass-3 audit targets: grep for `_check_paper_buying_power`, `open_shadow_trade`, and any alternate entry point.
2. **`_scan_cycle_committed` is a module-level global**, not per-call state. If multiple scan entry points share the module but only one calls `reset_scan_cycle_committed`, subsequent scans from the other path see stale state. Confirmed: only `scan_service.py:37` calls the reset.

**Pass-3 recommended action:** audit all invocations of `_check_paper_buying_power` and `open_shadow_trade` to find the scan path that doesn't reset. Candidates to grep: `src/scheduler/watch.py`, `src/services/*`, `src/cli/commands.py`, `src/shadow_trading/executor.py`. Then ensure reset fires at the top of that path too — likely one line added to the alternate entry.

**Fix approach:** reset at the top of every scan-cycle entry, not only `scan_service.run_scan`. Defensive decrement-on-rejection (the prompt's original framing) is not the right fix — rejections don't increment, so there's nothing to decrement.

### K — BP pre-LLM refactor target: `src/services/scan_service.py:169`, not `executor.py`

The LLM call lives in the scan orchestration, not the executor. Trace:

- `src/services/scan_service.py:35-37` — scan start, resets counter
- `src/services/scan_service.py:169` — `packet = enhance_packet_with_llm(packet, feat, config)` — **the LLM call**
- `src/services/scan_service.py:205` — `trade_id = open_shadow_trade(rec_id, packet, feat)` — the shadow-trade creation
- `src/shadow_trading/executor.py:598` — `_check_paper_buying_power(entry_price, planned_shares)` — the current BP-reject point, called **inside** `open_shadow_trade`

So today's flow: scan loop → **LLM enhancement** → open_shadow_trade → BP check → reject. Moving BP pre-LLM means inserting a check **in scan_service.py between lines 165-169**, before `enhance_packet_with_llm`.

**Data needed for early check:** `packet.position_sizing.allocation_dollars` is known at that point (ranker produces it before LLM). The shares/entry_price computation happens later in `open_shadow_trade`, but a coarse-grained check on `allocation_dollars` vs. `effective_bp` is sufficient — if allocation exceeds BP, the trade is guaranteed to reject later.

**Proposed fix:**
```python
# NEW pre-LLM BP check (insert before scan_service.py:169)
from src.shadow_trading.executor import _check_paper_buying_power_allocation
if not _check_paper_buying_power_allocation(packet.position_sizing.allocation_dollars):
    # Record rejection without LLM enhancement; matches post-LLM reject behavior
    _record_bp_rejection(packet, feat, db_path)
    continue  # skip to next candidate
packet = enhance_packet_with_llm(packet, feat, config)  # existing
```

A helper `_check_paper_buying_power_allocation(allocation: float) -> bool` takes the already-computed allocation dollars. This avoids duplicating the entry_price × shares computation. The existing `_check_paper_buying_power(entry_price, shares)` can stay as a redundant safety net inside `open_shadow_trade` (or be removed — simpler is one check).

**Scope note (correction to Pass 1):** the live-trade path at `executor.py:1927` is resize-to-fit, not reject. K applies to the paper path only. Live path's BP handling is intentionally different — no change.

**Test plan:** `tests/services/test_scan_bp_preflight.py` — stub `enhance_packet_with_llm` and `_check_paper_buying_power_allocation`; feed a packet with allocation > BP; assert LLM was NOT called; assert rejection row recorded.

### L5 — `notify_eod_report` format bug: **pnl_dollars and pnl_pct are TEXT, not REAL**

Live-DB check: `typeof(pnl_dollars)` returns `text` for 89 rows, `null` for 188. Same for `pnl_pct`. Example values: `'4.4'`, `'3.56'`, `'-5.65'`.

**Flow:**
- `src/scheduler/reports.py:399-407` passes DB values into `notify_eod_report` kwargs (`best_pct=best["pnl_pct"] if best else 0.0`, etc.)
- `src/notifications/telegram.py:555` formats `${paper_open_pnl:+.2f}` → TypeError if `paper_open_pnl` is `'4.4'` (str)
- Log evidence: bug has fired on 2026-04-14, 04-15, 04-16, 04-17 — not a one-off.

**Fix target:** `src/scheduler/reports.py:399-407` — wrap each numeric kwarg in `float()` cast. Minimal change:
```python
notify_eod_report(
    paper_open=paper_open_row["cnt"],
    paper_open_pnl=float(paper_open_row["pnl"] or 0),
    paper_closed_today=paper_closed_row["cnt"],
    paper_closed_pnl=float(paper_closed_row["pnl"] or 0),
    live_open=live_open_row["cnt"],
    live_open_pnl=float(live_open_row["pnl"] or 0),
    live_closed_today=live_closed_row["cnt"],
    live_closed_pnl=float(live_closed_row["pnl"] or 0),
    win_rate=win_rate, wins=wins, losses=losses,
    best_ticker=best["ticker"] if best else "N/A",
    best_pct=float(best["pnl_pct"]) if best else 0.0,
    worst_ticker=worst["ticker"] if worst else "N/A",
    worst_pct=float(worst["pnl_pct"]) if worst else 0.0,
    regime=regime, vix=vix, vix_change=vix - vix_prev,
    risk_rejected=risk_rejected, risk_qualified=risk_worthy,
)
```

**Follow-up flag (out of scope):** pnl_dollars/pnl_pct TEXT storage is an upstream writer bug. Someone is calling `conn.execute("UPDATE shadow_trades SET pnl_dollars=?", (str(x),))` instead of passing the numeric. Ticket separately — SQLite tolerates mixed types but downstream code breaks. Not in Sprint 2.

**Test plan:** `tests/scheduler/test_eod_report_format.py` — seed shadow_trades with TEXT-typed pnl values; call `send_eod_report()`; assert no exception; assert emitted Telegram payload contains correctly-formatted numbers.

### C2-partial — cancel-before-close helper

Confirmed line numbers at `src/shadow_trading/reconcile.py:498` (orphan backfill path) and `:511` (logging after backfill). Actual orphan-backfill site is 498-512. Cancel-before-close helper should fire **before `insert_shadow_trade` on line 505**, not after.

Proposed signature:
```python
def cancel_orders_for_ticker(ticker: str, desk: str = "swing") -> list[str]:
    """Cancel all open orders for ticker; return list of cancelled order IDs.

    Used by reconcile paths before closing or backfilling a position, to
    avoid the exit-overshoot pattern where bracket TPs fill AND arcis
    submits a duplicate sell, creating a net-short overshoot.
    """
```

Note: `src/shadow_trading/alpaca_adapter.py:531` already has a function named `cancel_orders_for_ticker` with this exact signature (confirmed in Sprint 1 research). **The helper already exists.** The fix is to call it from reconcile.py's orphan-backfill path before line 505 and before the stale-close path at line 517+.

**Pass-1 revision:** C2-partial is not "create a new helper," it's "call the existing helper from the right place."

**Test plan:** `tests/shadow_trading/test_reconcile_cancel_before_close.py` — mock `cancel_orders_for_ticker` to return `['order-123']`; invoke orphan backfill; assert helper called once per orphan ticker; assert cancellation logged before `insert_shadow_trade`.

### H4 — governor-disabled alert

Line numbers confirmed at `src/risk/governor.py:394-400`. Today's behavior: returns `approved=True` with `governor_disabled` check, no escalation.

**Idempotency concern:** `assess_trade` is called once per candidate ticker per scan — potentially dozens of calls per scan. A naive `logger.critical + send_telegram` emits once per call. Need a module-level sentinel that emits once per process lifetime (reset on import reload).

**Proposed pattern:**
```python
_governor_disabled_alerted = False

def _warn_governor_disabled_once():
    global _governor_disabled_alerted
    if _governor_disabled_alerted:
        return
    _governor_disabled_alerted = True
    logger.critical("[RISK] Governor disabled — all trades auto-approved; review config/settings.local.yaml.")
    try:
        from src.notifications.telegram import send_telegram, is_telegram_enabled
        if is_telegram_enabled():
            send_telegram("[FAIL] RISK GOVERNOR DISABLED -- all trades auto-approved. Review config/settings.local.yaml.")
    except Exception as e:
        logger.warning("[RISK] governor-disabled alert telegram failed: %s", e)
```
Call `_warn_governor_disabled_once()` at `governor.py:394` before the `return` block.

**Test plan:** `tests/risk/test_governor_disabled_alert.py` — set `governor.enabled=False`, call `assess_trade` twice, assert `logger.critical` fires exactly once, `send_telegram` fires exactly once. Reset sentinel via `governor._governor_disabled_alerted = False` and confirm emits again.

### H5 — traffic-light `int + str` TypeError

`src/features/traffic_light.py:91-119` — `_classify_credit`. Root cause confirmed: `macro_snapshots.value` for `series_id='BAMLH0A0HYM2'` is **stored as TEXT** (31 rows in today's DB, all type=text, values like `'2.86'`).

**Fix (single-line):**
```python
# line 102 before:
values = [r[0] for r in rows if r[0] is not None]
# line 102 after:
values = [float(r[0]) for r in rows if r[0] is not None]
```

Optional hardening (skip malformed):
```python
values = []
for r in rows:
    if r[0] is None:
        continue
    try:
        values.append(float(r[0]))
    except (ValueError, TypeError):
        continue  # skip malformed; don't break classification
```

**Test plan:** `tests/features/test_traffic_light_credit.py` — seed an in-memory DB with 30 `macro_snapshots` rows at `series_id='BAMLH0A0HYM2'`, values as text strings spanning the z-score bands (low/mid/high); call `_classify_credit`; assert returned value is one of `{0, 1, 2}` without warnings or exceptions.

### H7 — bare `sqlite3.connect()` sites — **Pass-1 correction**

**Locations confirmed (7):** `src/shadow_trading/reconcile.py:413, 606, 634, 645, 688, 704, 712`.

**`connect_db()` behavior (from `src/utils/db.py:34-44`):**
```python
def connect_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn
```

**Pass-1 claim** said `connect_db()` also applies `PRAGMA foreign_keys` and WAL mode. **Correction: it does NOT.** It applies only `busy_timeout=30s` and `row_factory=Row`. The Pass-1 test plan ("assert `PRAGMA foreign_keys` returns 1 on the returned connection") is therefore wrong — that test would fail against the current `connect_db` implementation.

**Behavior differences between bare `sqlite3.connect` and `connect_db`:**
| Feature | bare `sqlite3.connect` | `connect_db` |
|---|---|---|
| busy_timeout | 5 seconds (Python default) | 30,000 ms (30 s) |
| row_factory | `None` (tuples) | `sqlite3.Row` (dict-like) |
| foreign_keys | OFF | OFF (both) |
| WAL mode | DB-wide setting (inherited) | same |

So the fix gives **busy_timeout + Row factory**, not foreign-keys enforcement. Operator should know so expectations are calibrated. If foreign-keys enforcement is a goal, that's a separate change (add `PRAGMA foreign_keys=ON` to connect_db and audit the resulting FK violations).

**Row-factory impact:** existing reconcile.py code might index rows by integer (`row[0]`). `sqlite3.Row` supports both int and str indexing, so the swap is safe. To be defensive, Pass 3 will grep for int-indexed usage in reconcile.py after the swap and confirm no regressions.

**Test plan:** `tests/shadow_trading/test_reconcile_connection.py` — verify (a) busy_timeout is 30000 ms on returned connections, (b) row_factory is Row (check by `isinstance(cur.fetchone(), sqlite3.Row)`), (c) a deliberate DB lock (held by another connection) is correctly waited on rather than raising immediately.

### H8 — gate decision still pending

Gate #6 in Pass 1 recommended deferring H8 (schema migration). No further research until operator resolves. If retained, Pass 3 needs:
- Migration path design (SQLite ADD PRIMARY KEY requires table rebuild).
- `validate-schema --fix` behavior against registry changes on `activity_log`.
- Postgres sync via `render_migrate.py`.
- Backfill: existing 1,427 NULL-id rows need ids assigned — `UPDATE activity_log SET id = rowid WHERE id IS NULL`.

Deferring keeps Sprint 2 to 8 Track-B items; including adds a migration PR to the scope.

---

## 4. Sprint-wide risk check

- **Merge-window risk:** Sprint 2 touches 7 code files. Coupled PRs unlikely. `main` is post-Sprint 1 at `bf25de3a`; no pending PRs observed.
- **Reconciliation timing:** Track A script runs AFTER Alpaca fills (operator-controlled). If the script runs BEFORE fills, the pre-flight abort catches it (ticker still short → exit code 3). Idempotent re-run after fills succeeds.
- **Kill-switch:** engaged. Every code change in Track B touches non-hot paths or is gated by kill-switch at runtime. No risk of enabling trading mid-sprint.
- **Test-baseline:** Sprint 1 post-merge baseline was 2748 passed / 1 pre-existing fail / 2 skipped. Sprint 2 adds ~8 new tests; expected post-merge: 2756 passed / 1 fail / 2 skipped. Well above 1339 floor.

## 5. Pass-3 commit plan (pending operator green-light)

- Commit 3 — Track A script + 5 tests
- Commit 4 — L (scan-reset audit fix)
- Commit 5 — K (pre-LLM BP check in scan_service)
- Commit 6 — bootcamp cap 20 → 8 (config-only)
- Commit 7 — C2-partial (wire existing helper into reconcile.py)
- Commit 8 — H4 (governor-disabled alert with once-per-process sentinel)
- Commit 9 — H5 (traffic_light credit float-cast)
- Commit 10 — H7 (7 × connect_db swap)
- Commit 11 — L5 (EOD float-cast in reports.py)
- Commit 12 — CHANGELOG entry + PR open

**If H8 is retained:** add commits 13-14 for schema registry change + migration + Postgres sync.

---

## 6. Summary — STOP conditions

No fresh STOP conditions surfaced in Pass 2 beyond the 6 gate decisions from Pass 1. Specifically:

- **No Track B item needs scope expansion.** Each fix is bounded to 1-2 files plus a test.
- **C2-partial scope shrank** (helper already exists, not a new one) — good, smaller blast radius.
- **H7 scope is accurate** but expectations corrected (busy_timeout + Row, not foreign_keys/WAL).
- **K and L** require rethinking per the Pass-1 gate decisions (#4 and #5) — but no new code files discovered; the refactor is still confined.
- **L5 fix trivially correct** — float-cast at the call site.

After this commit: `git push`, then **STOP** pending operator review of the 6 Pass-1 gate decisions.
