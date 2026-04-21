# Root-Cause Investigation — Recurring Shorts + Bracket Alerts
**Date:** 2026-04-21 (snapshot taken 12:35 ET, market open)
**Type:** Read-only investigation. No mutations performed. No fixes proposed.
**Alpaca account:** PA36B1S9B9LW (paper)
**Watch-loop PID:** 125820, started 2026-04-21 06:58:10 ET (uninterrupted since).
**Sources:** live SQLite at `C:/arcis/data/ai_research_desk.sqlite3` (read-only), Alpaca REST via MCP (read-only), `logs/arcis.log` (7.3 MB), repo source.

---

## 1. Executive Summary

The operator is looking at symptoms from **three distinct bugs**, not one:

1. **CVS bracket alert spam is a broken exit-retry loop, not a broken bracket.** Trade row `00330e8d` (CVS, 130 planned shares) was partially exited this morning at 09:48:41 ET (126 of 130 filled, then Alpaca canceled the residual). The DB row was reverted by reconcile to `status=open` with `planned_shares=130`. Since then, the executor has attempted to sell 130 shares **every scan cycle** (~5–8 min); Alpaca rejects with `insufficient qty available for order (requested: 130, available: 4)`; reconcile re-reverts to open; repeat. **17+ failed sell attempts and 24 bracket alerts today, all driven by the same stale row.** No other ticker is alerting.
2. **The overshoot mechanism is still firing, and new incidents are accumulating.** 13 tickers now carry `status=needs_manual_review, exit_reason=exit_overshoot_detected` zombies (GOOGL, NVDA, MO, TGT from 4/15; BK, CVX, FDX, INTC, GM, CAT from 4/16-17; NEE, GS from 4/20; **C added today at 09:43:33 ET** — the same mechanism produced a brand-new short today). Alpaca currently holds 4 net-short positions (C -65, NEE -153, NVDA -245, TGT -161) worth $-93,060 against $100,330 equity. **None of the shorts are represented in the DB as open rows; the DB only knows `direction=long`.** There are zero protective stop orders at Alpaca for any of the 10 current positions (confirmed via `get_orders(status=open)` — all 5 open orders are sell-to-close take-profit limits).
3. **"Sleep recovery: 31min gap" is a false-positive log spam, not a hardware sleep event.** `src/scheduler/watch.py:442` fires a warning whenever `elapsed > 30` min since the last scan, but the configured `scan_interval` is also 30 min — so every normal scan cycle that runs 30-31 min late trips the check. Six false "sleep recovery" warnings fired today at 30-min intervals (10:00, 10:31, 11:02, 11:32, 12:03, 12:34). The watch loop never actually slept and has been running continuously since 06:58 ET (verified via Win32_Process).

**Urgency ranking:**
- **P0 (operator must decide within market session):** Four unmanaged shorts with no stops. TGT is -8.8% ($-1,727 unrealized). Market closes 16:00 ET.
- **P1 (fix before next market open):** CVS exit-retry loop will resume tomorrow with the same pattern; BP-capacity is being consumed by every failed attempt. No active capital loss, but it masks real signals.
- **P2 (operational noise):** false sleep-recovery alerts; duplicate CVS DB rows; BP-rejected buy spam for CVS/BK/C/USB/PFE (the scanner keeps re-signaling the same tickers the system can't afford).

---

## 2. Thread 1 — Alpaca vs DB reconciliation

### Alpaca ground truth (10 positions, 5 open orders)

| Ticker | Side | Qty | Avg entry | Mkt value | Unrealized P/L | Matches DB? |
|--------|------|-----|-----------|-----------|----------------|-------------|
| AMD  | long  | 48   | $277.24 | $13,612   | +$304.92  | ✅ trade `8463dc15` bracket |
| **C**    | **short** | **-65**  | **$134.71** | **-$8,648**  | **+$108.55**  | **❌ no DB row (overshoot today 09:43)** |
| CVS  | long  | 4    | $78.70  | $310      | -$4.88    | ⚠️ 2 DB rows (see below) |
| GOOG | long  | 29   | $330.43 | $9,676    | +$93.38   | ✅ trade `05e1549d` bracket |
| LIN  | long  | 47   | $492.49 | $23,192   | +$45.12   | ✅ trade `20fb9f9c` bracket |
| **NEE**  | **short** | **-153** | **$92.84**  | **-$14,009** | **+$195.08**  | **❌ no DB row (overshoot 4/20)** |
| **NVDA** | **short** | **-245** | **$196.75** | **-$49,028** | **-$824.54**  | **❌ no DB row (overshoot 4/15)** |
| SPG  | long  | 119  | $206.50 | $24,598   | +$24.99   | ✅ trade `e7d94f44` bracket |
| **TGT**  | **short** | **-161** | **$122.03** | **-$21,374** | **-$1,727.53**| **❌ no match (DB row is `broker=ib`, quarantined)** |
| WMT  | long  | 177  | $127.96 | $22,875   | +$226.56  | ✅ trade `c640233d` bracket |

Open orders (all take-profit limits, sell-to-close, all against long positions — **no stops exist anywhere**):

| Order | Ticker | Qty | TP limit | Corresponds to |
|-------|--------|-----|----------|----------------|
| 2b2a08b1 | WMT  | 177 | $132.03 | trade c640233d |
| 5eac3d4d | SPG  | 119 | $211.67 | trade e7d94f44 |
| b1f65743 | AMD  | 48  | $294.01 | trade 8463dc15 |
| 452a6804 | LIN  | 47  | $507.88 | trade 20fb9f9c |
| bb7804e2 | GOOG | 29  | $342.79 | trade 05e1549d |

**Every overshoot ticker from the 4/15–4/20 window has a `needs_manual_review` DB row (all 13), including C created today.** None of them has an associated `actual_exit_price` or `actual_exit_time`. These rows are frozen markers — not active trades. The broker-side short positions corresponding to them (NEE -153, NVDA -245, TGT -161, C -65) exist on Alpaca with no DB row linking them. Three of last week's overshoots (CVX, CAT, BK, FDX, GM, GOOGL, INTC, MO, GS) were covered this morning at 09:30-09:33 ET via pre-submitted day-market `buy_to_close` orders (filled at open, net flat), so only 4 shorts remain.

**CVS double-row situation:**
- `00330e8d` — original 4/13 bracket, planned 130 @ $78.29, `status=open, order_type=bracket`, alpaca_order_id `f0a58eae`, `exit_order_id=6d21fbed` (the canceled exit). This is the row driving the alert loop.
- `47386416` — reconcile-backfilled today at 09:48:45, planned 5 @ $78.70, `status=open, order_type=reconciled`, no alpaca_order_id. This row reflects the residual 4-share position.
- Plus 5 CVS `rejected_buying_power` attempts today (10:06, 10:36, 11:07, 11:37, 12:08) — the scanner keeps trying to *enter* CVS for another 270 shares at ~$20.9k, rejected because effective BP is $16.7k.

### Active DB rows (`status IN ('open','exit_pending','submission_uncertain')`)

9 total: WMT, CVS×2, SPG, AMD, LIN, GOOG, TGT (broker=ib, quarantined), CVS-stale, SBUX (quarantined). All `direction=long`.

---

## 3. Thread 2 — Bracket-alert scope

**One ticker, one row, one day.** CVS accounts for **24 of 24 bracket alerts** today.

```
bracket_health stats 2026-04-21:
  CVS: 26 checks, 24 alerts
  AMD:  26 checks,  0 alerts
  GOOG: 26 checks,  0 alerts
  LIN:  26 checks,  0 alerts
  SPG:  26 checks,  0 alerts
  WMT:  22 checks,  0 alerts  (fewer because WMT-new opened at 10:06)
  C:     1 check,   0 alerts  (brand new short from today; has no bracket to monitor)
```

- First broken check: **2026-04-21T09:48:46 ET** (both `stop_leg_status=canceled` and `target_leg_status=canceled`).
- Cadence is set by the intraday `check_bracket_health` call inside the watch loop — roughly every 5–15 min, not a strict 5-min. Alerts fire every time the check runs because `bracket_monitor.py` has **no deduplication** — every broken check emits a Telegram alert (`src/shadow_trading/bracket_monitor.py:266-270`). Also, alerts are only sent to Telegram and are not written to any log file, which is why `grep "BRACKET ALERT" logs/*.log` returns zero matches.
- `bracket_monitor` never attempts to re-arm a canceled stop. It observes and notifies, nothing else (`_alert()` at line 152-163 is best-effort Telegram, then continues).

---

## 4. Thread 3 — CVS archaeology (full timeline)

### Pre-event state (4/13 → 4/20 EOD)

| Timestamp | Event |
|-----------|-------|
| 2026-04-13 09:44:20 ET | DB row `00330e8d` created: CVS long 130 @ $78.29, bracket order `f0a58eae`, stop $74.51, target $81.12. |
| 2026-04-14 → 2026-04-20 | Bracket intact every check (stop=held, target=new) — 29 healthy bracket_health rows on 4/20 alone. |
| 2026-04-21 09:00:43 ET | Premarket check: **7/7 protected.** |
| 2026-04-21 09:47:19 ET | Last intact check for CVS (stop=held, target=new). |

### The triggering event (09:48:39 → 09:48:46 ET)

| Timestamp | Log / event | Interpretation |
|-----------|-------------|----------------|
| 09:47:23 | `[WATCH] Bracket check (intraday): 5/5 protected` | Still healthy; 5 brackets counted (CVS, AMD, GOOG, LIN, SPG). |
| 09:48:39 | `[SHADOW] Placing paper SELL: 130 shares of CVS` | **Executor issued a full-size exit for the CVS row.** Source of this exit signal is not logged here — could be timeout / take-profit / signal-driven. TBI. |
| 09:48:41 | `[EXIT] Broker exit failed for CVS — marking exit_failed (status=OrderStatus.PENDING_NEW)` | Executor interpreted Alpaca's slow response as failure. In reality Alpaca was partial-filling. |
| 09:48:45 (Alpaca side) | Alpaca order `6d21fbed` recorded: qty 130, **filled_qty 126 @ $78.17, then status=canceled**. Alpaca canceled the residual 4 because position was now 4. | Alpaca's behavior: when a parent position is partially closed, child bracket legs (stop + target) are auto-canceled because their share count no longer matches position. |
| 09:48:45 | `[CANCEL] Cancelled 1 open orders for CVS` (reconcile-paper) | Reconcile canceled the dangling bracket children. |
| 09:48:45 | `[RECONCILE-PAPER] Backfilled orphaned position: CVS (5.0000 shares @ $78.70)` | **Created new row `47386416` for the residual.** Note: reconcile said 5 shares; Alpaca actually reports 4. |
| 09:48:45 | `[RECONCILE-PAPER] Reverted premature exit to open: CVS` | **Reverted `00330e8d` back to status=open with planned_shares still = 130.** The guard at reconcile.py:644-666 only blocks revert if `alpaca_qty <= 0` — it does not block when actual_qty > 0 but < planned. |
| 09:48:46 | First "canceled/canceled" bracket_health entry for CVS — Telegram alert #1 fires. | Stop leg now officially broken in the view of bracket_monitor. |

### The loop (09:48 → now)

Each scan cycle (~5-16 min apart, driven by executor's exit-check loop, not the 30-min scan cycle):

```
Placing paper SELL: 130 shares of CVS
  → Alpaca rejects: "insufficient qty available for order (requested: 130, available: 4)"
  → Executor marks status='exit_failed'
  → Reconcile sees alpaca_qty=4 > 0 → reverts to status='open'
  → bracket_monitor runs next tick → CVS still has canceled/canceled legs → alerts again
```

Counted: **17 confirmed "sell 130 CVS → rejected → reverted" cycles** today between 09:48 and 12:32 ET. None succeed, none change state, none escalate. Alerts continue every bracket-check tick.

Why does the exit keep retrying instead of failing terminally? Because reconcile.py:667-674 unconditionally reverts `exit_failed → open` whenever `alpaca_qty > 0`, without comparing against `planned_shares`. The guard was designed to prevent re-triggering an overshoot (flipping short) — it works for that narrow case but not for the mismatched-qty case.

---

## 5. Thread 4 — Overshoot exit-path analysis

### Dispatch graph for sells

**Paper trade exit** (source=paper, affects all current DB rows):
- `src/shadow_trading/executor.py:363-380  _submit_exit_order(trade, shares)`
  - Passes `shares = DB planned_shares` (not broker actual qty) to...
- `src/shadow_trading/alpaca_adapter.place_paper_exit(ticker, shares)`
  - Submits `MarketOrderRequest(qty=shares, side=SELL)` to Alpaca paper.

**Live trade exit** (source=live; none active today):
- `executor.py:369-376` → `broker.place_exit(trade["ticker"], 0)` → `alpaca_adapter.place_live_exit(ticker, 0)` which calls `client.close_position(ticker)` — **broker-side qty-agnostic.** This path cannot produce the CVS-type mismatch because it never sends an explicit qty.

**Asymmetry is the root:** paper path uses DB state as truth; live path uses broker state as truth. The CVS loop is a direct consequence of paper-path design. The overshoot flips (qty planned > actual remaining shares in a multi-step exit) occur on the same paper path.

### Overshoot-detection guard (reconcile.py:643-665)

```python
if alpaca_qty <= 0:
    # Mark needs_manual_review, exit_reason = 'exit_overshoot_detected'
elif alpaca_qty > 0:  # implicit
    # Revert status → 'open', re-enter the retry loop
```

The guard protects against **going short from zero-or-negative** but not against **retrying an exit whose planned qty has diverged from broker qty**. Result: CVS hits the elif branch every cycle.

### Is overshoot active today?

**Yes.** C (ticker Citigroup) was added to `exit_overshoot_detected` at **2026-04-21 09:43:33 ET** — the same morning, before market open. The Alpaca order log confirms: order `3d175828-c192-47ee-ab8a-5e6b8480ea12`, sell 65 C at $134.71, `position_intent=sell_to_open` at 09:43:27 ET — a system-issued sell that opened a fresh short. The Alpaca position C -65 exists now; DB row 66ad6dfd is frozen as needs_manual_review. **The mechanism has not been disabled; it produced at least one new overshoot today.**

Yesterday's 4/20 events (NEE and GS overshoot-detected) were followed by pre-market cover orders at 05:46-05:47 ET today. NEE was not covered (still -153 at Alpaca); GS was covered (filled 09:47:19 at $943.91). The cover pre-submission was partial and not driven by reconcile (no log line shows why GS covered but NEE did not — TBI by operator).

### Sell-to-close / sell-to-open today (Alpaca truth)

Only three sells today:
- **09:43:27 C** sell 65 `sell_to_open` @ $134.71 → opened short (the new overshoot)
- **09:43:31 WMT** sell 92 `sell_to_close` @ $127.87 → closed old WMT
- **09:48:41 CVS** sell 130 `sell_to_close` → 126 filled, 4 canceled → source of CVS loop

No other sells. So overshoot is not currently spewing orders — it has produced **one** new incident today (C).

---

## 6. Thread 5 — Sleep gap + restart

### The 31-min "sleep recovery" is a false positive

`src/scheduler/watch.py:439-454`:
```python
if elapsed > 30 and self._is_market_open(now):
    logger.warning("[WATCH] Possible sleep recovery detected: %.0f min since last scan "
                   "(expected %d min). Resuming scans.", elapsed, self.scan_interval,)
    ... send_telegram("Sleep recovery: ...")
```

`self.scan_interval = 30` (default, Strategy Decision #22). Elapsed time between scans is typically 30.0 to 31.x min in normal operation. The `elapsed > 30` branch fires on nearly every normal scan cycle. Evidence today:

```
10:00:20  30 min since last scan
10:31:05  31 min since last scan
11:02:00  31 min
11:32:39  31 min
12:03:09  31 min
12:34:04  31 min
```

Exactly 30-31 min between warnings — i.e., the watch loop is behaving normally and the warning is firing because the threshold is set at the same value as the interval.

### No actual hardware sleep event

- Watch-loop PID 125820 has been running continuously since **2026-04-21 06:58:10 ET** (`Get-CimInstance Win32_Process`). No restart.
- `ai_research_desk.sqlite3-wal` was last written at 12:34:15 ET (1 min before snapshot). DB is being written continuously.
- No `logger.error` traceback, no `logger.critical`, no "crash" / "killed" / "exit" / "restart" entries between 10:00 and 10:31 ET.

### The "ARCIS STARTED" operator saw at 10:11 ET

Source of that message: `src/scheduler/watch.py:628` — `notify_system_event("ARCIS STARTED", ...)` is called exactly once per process, in `_print_banner()` during watch-loop startup. That fired at 06:58:10 ET (when PID 125820 started). No second startup was observed in the process list or logs.

Hypotheses:
1. **Delayed Telegram delivery.** Telegram push notifications can be delayed by minutes-to-hours on some devices. The 10:11 message the operator saw may be the delayed 06:58 notification.
2. **An operator-issued restart attempt that aborted.** `python -m src.main startup` with a live lockfile at `data/watch.lock` would bail before launching the loop, but it still runs `notify_startup_complete` in some paths (see `src/cli/commands.py:1240-1244`). TBI whether anyone ran a command at 10:11.
3. **Hypothesis 3 (less likely): a child process** (pre-market scheduler, training subprocess) emitted the same text via another code path.

**Not confirmable from read-only evidence alone.** The authoritative answer is in the operator's Telegram timeline and in `logs/arcis.log` around 10:11 — but no `ARCIS STARTED` string appears in the live log file anywhere today (the string is only emitted via the Telegram notifier, never logged).

---

## 7. Hypothesis ranking

### Hypothesis A: **The CVS loop, the overshoots, and the alert spam share a single root: the paper exit path uses DB planned_shares as the source of truth for qty, while reconcile treats broker state as truth. They disagree, the loop never converges.**

- **For:** CVS `00330e8d` has planned=130 and Alpaca=4 — the exact disagreement. Every exit retries 130. Every revert preserves 130. Loop is perfectly consistent with this explanation. Overshoots happen when reconcile runs DURING a partial-fill sequence and the next exit re-fires; guard prevents going short but not retrying.
- **Against:** The overshoot incidents from 4/15-4/17 don't all look like the same mechanism — some may have been true "two sells fired simultaneously". Without Alpaca order history deeper than 48h I can't confirm that all 13 were qty-mismatch loops.
- **Confidence:** High. This explains today's loop completely, and at least the C overshoot this morning fits the pattern (sell-to-open 65 where DB had 65 long = zero remaining).

### Hypothesis B: **Two separate bugs.** Bug 1 is the CVS single-trade exit loop (planned_shares not updated on partial fill). Bug 2 is a race/double-dispatch where two sells fire near-simultaneously (classic overshoot, seen on 4/15-17).

- **For:** 4/15-17 overshoots were clustered at market open (09:01-10:52 ET) suggesting market-open timing coincidences or a specific codepath that fires only then. Today's CVS loop is mid-day, mechanism different.
- **Against:** No evidence in today's log of double-dispatch. C overshoot morning had only one sell order. Occam's razor favors Hypothesis A.
- **Confidence:** Medium.

### Hypothesis C: **The overshoots are caused by pre-market close-all orders interacting badly with intraday exits.** A pre-market cover order fires at market open (`sell_to_close`), then the intraday exit path fires again because the DB row still looks open, producing a second sell that flips short.

- **For:** Pre-market cover orders were submitted at 05:46-05:47 ET today for 10 tickers (the yesterday-shorts cover batch). Most fired as `buy_to_close`, not sells. But the design pattern — pre-submit a market order for market open — exists.
- **Against:** Today's C overshoot didn't follow this pattern (no pre-submitted sell found in Alpaca orders). Today's sells are: C at 09:43:27, WMT at 09:43:31, CVS at 09:48:41 — three sells, three different trajectories, none pre-market.
- **Confidence:** Low. Contributing, not causal.

### Hypothesis D: **bracket_monitor itself is triggering the exit retries** (the sells happen near bracket checks).

- **For:** Sells at 10:11, 10:27, 10:43, 10:58, 11:14, 11:29, 11:44, 12:00, 12:16, 12:32 — several land 0-3 minutes after a bracket_health check.
- **Against:** Code-path inspection of `bracket_monitor.py` shows NO call to executor or adapter sell functions. It only alerts and records. The timing correlation is likely because *both* run on the watch loop's tick cadence (which is more frequent than 30-min scans). The executor's exit-processing loop independently iterates open trades.
- **Confidence:** Low. Spurious correlation.

### Hypothesis E: **Sleep-recovery warnings mask real sleep events.** Even if the threshold is mis-tuned, maybe a real Windows sleep also happened.

- **For:** Windows 11 does sleep during idle hours.
- **Against:** Watch PID unchanged since 06:58; WAL file being written continuously; logs show regular activity at 09:00, 10:00, 10:11, 10:27 etc. with no gap > ~2 minutes anywhere today.
- **Confidence:** Very low. It's a log-spam bug, not a hidden outage.

---

## 8. Operator decision menu

### Decisions facing the next 3 hours (market closes 16:00 ET)

1. **Q: What to do about the 4 unmanaged shorts (C, NEE, NVDA, TGT)?** None has a protective stop. TGT is at -8.8% unrealized; NVDA is -1.7%; NEE and C are slightly positive. Total short exposure is $-93k on $100k equity. Do you want to cover them manually today, place stops manually, or let them ride overnight? Note TGT's move against position today (+1.98% intraday).
2. **Q: Do you halt the CVS retry loop before more attempts fire?** The loop is costing API calls and BP recomputation per cycle but is not losing money. Halting requires either a DB mutation (set `quarantined=1` on trade `00330e8d` — this is exactly what row `730a113b` (TGT stale) was used for back on 4/14), or a process kill. Not doing anything is bounded-risk (Alpaca keeps rejecting) but noisy.
3. **Q: Do you address the 13 `needs_manual_review` zombies today?** They clutter queries and keep the scanner trying to re-enter those tickers (CVS, BK, USB, PFE all had "rejected_buying_power" spam today because the scanner still signals them). The data is now a week stale on some of them.

### Investigation next steps (before proposing any fix)

4. **Who emits the "sell 130 CVS" signal every cycle?** I traced the dispatch path (`executor._submit_exit_order`) but did not identify which caller decides to exit on this particular cadence. Grep for `_submit_exit_order` callers and trace what condition fires for `00330e8d` at 09:48, 10:07, 10:11, etc.  Is it timeout? Is it a stop-trigger that's using a stale mark price? Is it an exit-queue that keeps requeuing failed exits? This is necessary to propose a durable fix.
5. **Why do overshoots cluster at market open (09:01-10:52 ET)?** Nine of the 13 overshoots have `updated_at` in this window. The 10th (TGT) at 11:20 is close. 4/20 NEE at 10:25, GS at 13:26. This is suspicious enough to warrant its own timeline review — possibly a premarket+open exit batch or a signal-regeneration issue at first bar. Only 1-2 hours worth of log evidence needed to resolve.
6. **Are any of today's BP-rejected entries (BK, C, USB, PFE, CVS) signaling real strategy intent?** If so, they're being silently dropped. If not, the scanner needs a deduplication layer that notices "tried 6 times today, rejected 6 times, don't try again". Either way, worth operator review of scanner output.

### What to keep running

7. The watch loop itself is behaving normally — continuous scans, continuous bracket checks, correct reconcile behavior for healthy trades (WMT rotation cleanly closed and reopened today). Don't stop it unless you want a hard halt.
8. The overshoot guard **is working** for its narrow case — it caught the C overshoot this morning and marked it for review rather than retrying into another short. The guard is a keeper. The hole is the qty-mismatch revert path, not the overshoot detection.

### What not to do

9. **Don't manually update `00330e8d.planned_shares` to 4** without considering that this is the same modification a fix would apply — and the fix belongs in the code (reconcile or executor), not as a one-off DB row edit. If you patch the row, the bug will resurface on the next partial fill.
10. **Don't restart the watch loop expecting to clear the loop.** The DB state is persistent; a restart will resume the same retry pattern.
11. **Don't disengage the bracket_monitor or the reconcile loop.** They are observing and reporting correctly; the bugs are in what executor does with their output.

---

## 9. Notes on read-only evidence quality

- **Live DB** was queried read-only via `sqlite3.connect('file:...?mode=ro', uri=True)` — no locks acquired, no writes.
- **Alpaca** was queried via MCP (`get_account_info`, `get_clock`, `get_all_positions`, `get_orders`) — read endpoints only. No cancel/close/replace/submit calls.
- **Logs** read from `logs/arcis.log` tail (last 6 MB) + targeted greps. The `arcis_err.log` was last written at 06:58 ET today — no new errors today; that stream captures startup output only.
- **Source** inspected read-only. No edits. No branch.
- **Nothing proposed, nothing fixed.** Decisions deferred to operator.

**Evidence confidence ranking:**
- High: CVS loop mechanism, Alpaca-vs-DB divergences, bracket-alert scope, sleep-recovery false positive, overshoot guard path.
- Medium: dispatch cadence of sell attempts (timing correlation observed, root caller not traced).
- Lower: exact cause of ARCIS STARTED at 10:11 ET (no code-path evidence in log; likely delayed notification).
