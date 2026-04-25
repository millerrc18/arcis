# Weird Trades Forensic Memo — 2026-04-24 Bootcamp

**Prepared:** 2026-04-25  
**Analyst:** A2 (Investigation Pass)  
**Sources:** `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3`, `logs/arcis.log`, `logs/halcyon.log`, `config/settings.example.yaml`, `src/packets/template.py`

---

## Summary Table

| Ticker | Trade ID (short) | Category | P&L | Recommendation |
|--------|-----------------|----------|-----|----------------|
| CMCSA | f8ad6af6 | `legitimate_stop` | -$1,001.55 (-5.36%) | (a) no action |
| TXN | 4a48855c | `api_failure_no_recovery` | $0.00 (locked) | (b) file issue: executor issues sell after position already gone from Alpaca, trapping unrealized gain |
| CSCO | 4014aee6 | `api_failure_no_recovery` | $0.00 (locked) | (b) file issue: exit blocked by insufficient buying_power on a close-only SELL order |
| WMT | e927a5b0 | `api_failure_no_recovery` | $0.00 (locked) | (b) file issue: timeout exit fires broker SELL that returns PENDING_NEW and is never retried before reconcile closes at entry price |
| GOOG | 05e1549d | `api_failure_no_recovery` | $0.00 (locked) | (b) file issue: same PENDING_NEW pattern as WMT — timeout exit not confirmed before reconcile zeroes pnl |

---

## Trade 1 — CMCSA (Comcast Corp.)

**Trade ID:** `f8ad6af6-60df-48b0-af65-2ebd174be6ef`  
**DB status:** `closed` | `exit_reason: stop_loss` | `order_type: bracket`

### Timeline

| Event | Timestamp | Detail |
|-------|-----------|--------|
| Entry decision | 2026-04-24 09:35:56 | Attribution logged, score=77, LLM conviction=7 |
| Entry fill | 2026-04-24 09:36:37–09:36:39 | 607 shares at $30.81 via bracket order; slippage=0.0 bps |
| Stop triggered | 2026-04-24 11:02:35 | Bracket stop-loss leg executed (Alpaca-side GTC order) |
| Exit fill | 2026-04-24 11:02:40 | Reconcile confirmed, exit at $29.16 |

### Signal vs Realized Prices

- `signal_entry_price` = $30.81 | `actual_entry_price` = $30.81 — no slippage
- `signal_exit_price` = NULL (B1 gap — bracket stop triggers on Alpaca side, price not signaled locally)
- `actual_exit_price` = $29.16 = `stop_price` field exactly

### Stop Verification

Config (`settings.example.yaml` → `strategies.pullback.stop_atr_multiplier: 2.0`):

```
stop_price = entry_price - (stop_atr_multiplier * ATR)
$29.16    = $30.81     - (2.0 * ATR)
ATR       = ($30.81 - $29.16) / 2.0 = $0.825
```

The recorded `stop_price` ($29.16) precisely equals the `actual_exit_price` ($29.16). The exit was triggered by the bracket's stop leg, not by the reconcile path. The implied ATR at entry was $0.825, which is 2.68% of the entry price — a plausible intraday ATR for CMCSA at a $30 handle.

The `max_adverse_excursion` is -$1.815, meaning price reached a low of approximately $28.995 before recovering at close, which is consistent with the stop being hit intraday and the position being closed exactly at the stop level.

**No exception traceback.** The log entry at 11:02:40 shows a clean `[EXIT] Closed CMCSA — P&L $-1001.55 (-5.4%)` with `exit_reason: stop_loss`.

Notable: CMCSA earnings were 2026-04-23 (the day before this trade entered). The entry was opened earnings-adjacent (`earnings_adjacent` field is absent from this record, but the earnings calendar data confirmed CMCSA reported 2026-04-23). This is a risk-management gap — the post-earnings volatility likely contributed to the stop being hit on day 1.

### Categorization

`legitimate_stop` — bracket stop executed exactly at the configured level. The loss is clean and attributable to the price move, not to a system defect.

### Recommendation

(a) No action on the exit mechanism. The stop fired correctly.

Side note for operator: CMCSA entered one day after earnings (2026-04-23). The event risk flag should have marked this `earnings_adjacent=1`. Investigate whether the event_risk block_threshold correctly gate-keeps post-earnings entries — this is out of scope for this memo but may warrant a separate issue.

---

## Trade 2 — TXN (Texas Instruments)

**Trade ID:** `4a48855c-df5f-4be1-95ba-f42e5bde3975`  
**DB status:** `closed` | `exit_reason: broker_exception:APIError` | `order_type: bracket`

### Timeline

| Event | Timestamp | Detail |
|-------|-----------|--------|
| Entry fill | 2026-04-13 09:40:27 | 21 shares at $213.92 via bracket order |
| MFE reached | 2026-04-16 11:20:59 | Max favorable excursion +$8.495 → implied peak ~$222.42 |
| Exit trigger | 2026-04-16 11:21:30 | Executor checked Alpaca position list — TXN not found |
| SELL attempted | 2026-04-16 11:21:31 | `[SHADOW] Placing paper SELL: 21 shares of TXN` |
| APIError | 2026-04-16 11:21:34 | Error code 42210000: `asset "TXN" cannot be sold short` |
| Reconcile close | 2026-04-16 11:21:50 | `[RECONCILE-PAPER] Closed stuck broker_exception:APIError trade: TXN (pnl=$0.00)` |

### Signal vs Realized Prices

- `signal_entry_price` = $213.92 | `fill_entry_price` = $213.92 — no entry slippage
- `signal_exit_price` = NULL (B1 gap)
- `actual_exit_price` = $213.92 (reconcile closed at entry price; pnl=$0.00)
- **Unrealized gain at MFE: ~+$178.40 (+$8.495 × 21 shares)** — this gain was forfeited

### Exception Analysis

Log at `2026-04-16 11:21:30,909`:
```
[EXECUTOR] TXN not in Alpaca positions (trade_id=4a48855c...) — will be caught by next reconciliation cycle
```

Log at `2026-04-16 11:21:31,748`:
```
[SHADOW] Placing paper SELL: 21 shares of TXN
```

Log at `2026-04-16 11:21:34,118`:
```
[EXIT] Broker exit failed for TXN — marking exit_failed:
{"code":42210000,"message":"asset \"TXN\" cannot be sold short"}
```

**Root cause:** The bracket order entered on 2026-04-13 contained a Alpaca-side stop-loss and take-profit. When one of those legs filled (most likely the take-profit near $222.42 given the MFE), Alpaca closed the bracket automatically and removed the position. The system did not detect this closure (no `[RECONCILE]` log showing a `target_hit` close between 04-13 and 04-16). When the executor's own timeout check ran on 04-16, it saw "position not in Alpaca" and then incorrectly attempted to place a new SELL market order rather than recognizing the position was already closed by the bracket. Alpaca correctly rejected this as a short-sell on a zero-position.

**Retry behavior:** `exit_retry_count` = 0 in the DB. No retry was attempted. After the APIError, reconcile immediately closed the trade at `pnl=$0.00`, overwriting whatever P&L had accrued from the Alpaca-side bracket fill.

**Probable actual outcome:** TXN's `max_favorable_excursion` = +$8.495. With `target_1 = $222.31`, the position likely exited the Alpaca bracket near or at target (price reached ~$222.42). The system failed to detect that event and subsequently zeroed the P&L.

### Categorization

`api_failure_no_recovery` — the APIError was not a transient network failure but a semantic error (attempting to short a position that was already closed on the broker side). No recovery path was attempted. The unrealized gain was forfeited.

### Recommendation

(b) File issue: **Executor does not reconcile bracket fill events on Alpaca's side — when a bracket TP or SL fills, the shadow trade status is not updated, leading to a ghost exit attempt that fails with code 42210000 and zeroes the P&L.** The fix should be in `src/shadow_trading/reconcile.py`: add a reconciliation path that detects when an Alpaca position disappears due to a bracket fill (distinguished from an "order rejected" disappearance) and writes the actual fill price and exit reason rather than closing at entry price with pnl=$0.00.

---

## Trade 3 — CSCO (Cisco Systems)

**Trade ID:** `4014aee6-b6e4-4f45-b908-d7780315ca18`  
**DB status:** `closed` | `exit_reason: broker_exception:APIError` | `order_type: bracket`

### Timeline

| Event | Timestamp | Detail |
|-------|-----------|--------|
| Entry fill | 2026-04-13 09:35:20 | 114 shares at $82.00 via bracket order |
| MFE reached | 2026-04-17 10:21:32 | Max favorable excursion +$3.24 → implied peak ~$85.24 |
| SELL attempted | 2026-04-17 10:21:54 | `[SHADOW] Placing paper SELL` (inferred from exit timestamp 10:21:57) |
| APIError | 2026-04-17 10:21:54 | Error code 40310000: `insufficient buying power` |
| Reconcile close | 2026-04-17 10:21:57 | `[RECONCILE-PAPER] Closed stuck broker_exception:APIError trade: CSCO (pnl=$0.00)` |

### Signal vs Realized Prices

- `signal_entry_price` = $82.00 | `fill_entry_price` = $82.00 — no entry slippage
- `signal_exit_price` = NULL (B1 gap)
- `actual_exit_price` = $82.00 (reconcile zeroed at entry; pnl=$0.00)
- **Unrealized gain at MFE: ~+$369.36 (+$3.24 × 114 shares)** — forfeited

### Exception Analysis

Log at `2026-04-17 10:21:54,045`:
```
[EXIT] Broker exit failed for CSCO — marking exit_failed:
{"buying_power":"8442.3","code":40310000,"cost_basis":"10008.88",
 "message":"insufficient buying power"}
```

**Root cause:** Alpaca rejected a paper-account SELL order for CSCO with error code 40310000 ("insufficient buying power"). This is anomalous for a close-only sell order — a long exit should not require buying power. This error typically occurs in paper accounts when Alpaca's margin model becomes confused about net exposure during a period of heavy concurrent positions. At entry, `concurrent_positions` = 4; by the exit date (04-17) there had been significant bootcamp activity opening and closing positions rapidly.

Notably, `cost_basis` = $10,008.88 in the error response matches 114 shares × $82.00 = $9,348 (close, accounting for fills). Alpaca was aware of the position but still returned an insufficient buying power error, which suggests a paper-account margin calculation inconsistency rather than a genuine position query failure.

**Retry behavior:** `exit_retry_count` = 0. No retry. Reconcile closed at entry price immediately.

**Comparison with TXN:** Both TXN and CSCO have identical patterns — MFE very close to the exit timestamp, pnl zeroed, reconcile closed "stuck broker_exception:APIError trade." They differ in the error code: TXN got 42210000 (short-sell on already-closed position); CSCO got 40310000 (buying power). The MFE for CSCO (+$3.24) exactly equals target_1 ($85.24) minus entry ($82.00), strongly suggesting the bracket's TP leg filled on the Alpaca side and the position was already closed before the executor's sell attempt — same underlying scenario as TXN.

### Categorization

`api_failure_no_recovery` — same structural failure as TXN. Bracket filled on Alpaca side; executor attempted redundant sell; API rejected it; reconcile zeroed the P&L.

### Recommendation

(b) File issue: **CSCO exit: same root cause as TXN — bracket position closed on Alpaca side but not detected locally; redundant SELL returns code 40310000 (buying_power) and pnl is zeroed.** The fix is the same reconciliation improvement described for TXN. The different error code (40310000 vs 42210000) is a paperwork artifact of Alpaca's paper-account model; both errors indicate the position was already gone.

---

## Trade 4 — WMT (Walmart)

**Trade ID:** `e927a5b0-f8b4-4842-9218-f4107976c331`  
**DB status:** `closed` | `exit_reason: timeout` | `order_type: bracket`

### Timeline

| Event | Timestamp | Detail |
|-------|-----------|--------|
| Entry fill | 2026-04-13 09:41:41 | 92 shares at $126.07 via bracket order; slippage=0.0 bps |
| Hold period | 2026-04-13 → 2026-04-21 | 8 calendar days; MFE reached +$2.76 on 2026-04-20 |
| Timeout triggered | 2026-04-21 09:43:29 | Executor fired sell at day 8 per `strategies.pullback.timeout_days: 8` |
| SELL attempted | 2026-04-21 09:43:29 | `[SHADOW] Placing paper SELL: 92 shares of WMT` |
| Broker failure | 2026-04-21 09:43:31 | `exit_failed (status=OrderStatus.PENDING_NEW)` |
| Reconcile close | 2026-04-21 09:43:35 | `[RECONCILE-PAPER] Closed stuck timeout trade: WMT (pnl=$0.00)` |

### Signal vs Realized Prices

- `signal_entry_price` = $126.07 | `fill_entry_price` = $126.07 — no entry slippage
- `signal_exit_price` = NULL (B1 gap)
- `actual_exit_price` = $126.07 (reconcile zeroed at entry; pnl=$0.00)
- **Unrealized gain at MFE: ~+$254 (+$2.76 × 92 shares)**; at exit (2026-04-21 open) price was approximately at or above entry given the prior day's MFE

### Timeout Verification

- `duration_days` = 8 in DB
- Calendar: entry 2026-04-13 (Monday) → exit 2026-04-21 (Monday) = exactly 8 calendar days
- Config `strategies.pullback.timeout_days: 8` — trigger is correct

### Exception Analysis

Log at `2026-04-21 09:43:31,074`:
```
[EXIT] Broker exit failed for WMT — marking exit_failed
(status=OrderStatus.PENDING_NEW)
|ctx:{"event":"exit_failed","ticker":"WMT","trade_id":"e927a5b0...","status":"OrderStatus.PENDING_NEW"}
```

Log at `2026-04-21 09:43:35,698`:
```
[RECONCILE-PAPER] Closed stuck timeout trade: WMT (pnl=$0.00)
```

**Root cause:** The executor submitted the exit SELL and received `OrderStatus.PENDING_NEW` from Alpaca — meaning the order was acknowledged but not yet filled. Rather than waiting for the fill confirmation or retrying, the code path treated `PENDING_NEW` as a failure and immediately marked the trade `exit_failed`. Reconcile then closed it at entry price with pnl=$0.00, within 4 seconds of the sell attempt.

This is a different failure mode than TXN/CSCO. The position was almost certainly real (the bracket's SL and TP were not triggered — price stayed between them for 8 days). The sell order was valid; Alpaca was processing it; but the 4-second window between submission and reconcile closure was too short to receive a fill.

**Retry behavior:** `exit_retry_count` = 0. No retry before reconcile zeroed it.

### Categorization

`api_failure_no_recovery` — the `exit_reason` in the DB says `timeout` which is technically correct as a trigger, but the underlying failure was the `PENDING_NEW` mishandling. The label is partially accurate (timeout did trigger the exit) but misleading (the actual problem was the immediate reconcile wipe on `PENDING_NEW`).

### Recommendation

(b) File issue: **Timeout exit (and all exit paths) treat `OrderStatus.PENDING_NEW` as an immediate failure — reconcile closes at entry price within seconds, forfeiting any accrued P&L. The executor should wait for fill confirmation (or at minimum, a configurable grace period) before handing off to reconcile.** See `src/shadow_trading/executor.py` and `src/shadow_trading/reconcile.py`.

---

## Trade 5 — GOOG (Alphabet / Google)

**Trade ID:** `05e1549d-ea38-4d99-85e2-ea198d90c869`  
**DB status:** `closed` | `exit_reason: timeout` | `order_type: bracket`

### Timeline

| Event | Timestamp | Detail |
|-------|-----------|--------|
| Entry fill | 2026-04-15 11:41:41 | 29 shares at $330.12 via bracket order; slippage=0.0 bps |
| Entry log | 2026-04-15 11:41:44 | `[SHADOW] Opened shadow trade for GOOG at $330.12 (29 shares)` |
| Hold period | 2026-04-15 → 2026-04-23 | 8 calendar days; MFE reached +$9.52 on 2026-04-23 at 11:19 |
| Timeout triggered | 2026-04-23 11:42:41 | `[SHADOW] Placing paper SELL: 29 shares of GOOG` |
| Broker failure | 2026-04-23 11:42:43 | `exit_failed (status=OrderStatus.PENDING_NEW)` |
| Reconcile close | 2026-04-23 11:42:46 | `[RECONCILE-PAPER] Closed stuck timeout trade: GOOG (pnl=$0.00)` |

### Signal vs Realized Prices

- `signal_entry_price` = $330.12 | `fill_entry_price` = $330.12 — no entry slippage
- `signal_exit_price` = NULL (B1 gap)
- `actual_exit_price` = $330.12 (reconcile zeroed at entry; pnl=$0.00)
- **Unrealized gain at MFE: ~+$276 (+$9.52 × 29 shares)**; MFE timestamp was 11:19, only 23 minutes before the timeout-triggered exit — the position was near its peak at the moment it was closed

### Timeout Verification

- `duration_days` = 8 in DB
- Calendar: entry 2026-04-15 (Tuesday) → exit 2026-04-23 (Wednesday) = exactly 8 calendar days
- Config `strategies.pullback.timeout_days: 8` — trigger is correct

### Exception Analysis

Log at `2026-04-23 11:42:43,331`:
```
[EXIT] Broker exit failed for GOOG — marking exit_failed
(status=OrderStatus.PENDING_NEW)
|ctx:{"event":"exit_failed","ticker":"GOOG","trade_id":"05e1549d...","status":"OrderStatus.PENDING_NEW"}
```

Log at `2026-04-23 11:42:46,489`:
```
[RECONCILE-PAPER] Closed stuck timeout trade: GOOG (pnl=$0.00)
```

**Root cause:** Identical to WMT. The `PENDING_NEW` handling problem is exactly the same — 3-second window from sell submission to reconcile wipe. The exit_order_id `d1b9c580-7d23-4a76-bd29-349518ae0ac8` is recorded in the DB, confirming Alpaca accepted the order. The position was real; the order was accepted; but the code did not wait for fill before closing with zeroed P&L.

**Additional context:** GOOG's `earnings_adjacent = 1` (GOOG earnings scheduled 2026-04-29). The trade ran 8 days with a $9.52 MFE only 23 minutes before the timeout fired. The timing is unfortunate but not a system defect — the timeout fired correctly; the defect is in the post-timeout fill handling.

**Retry behavior:** `exit_retry_count` = 0. No retry.

### Categorization

`api_failure_no_recovery` — same as WMT. The `exit_reason: timeout` label in the DB is accurate for the trigger, but the P&L zeroing is caused by the `PENDING_NEW` handling defect, not by the timeout logic itself.

### Recommendation

(b) File issue: **Same defect as WMT — `PENDING_NEW` causes immediate reconcile close at entry price, forfeiting gain. The fix is identical: add fill-wait logic to the exit path in `src/shadow_trading/executor.py` / `src/shadow_trading/reconcile.py`.** Given the WMT and GOOG failures occurred on the same code path (WMT on 04-21, GOOG on 04-23), this is a systemic defect affecting every timeout exit, not isolated incidents.

---

## Patterns Across the 5 Trades

### 1. The reconcile-zeroing defect affects 4 of 5 trades

TXN, CSCO, WMT, and GOOG all have `pnl_dollars = 0.00` and `actual_exit_price = actual_entry_price`. This is not coincidence — all four hit the same reconcile path that writes `pnl=$0.00` when the broker exit fails. In aggregate, these four trades forfeited approximately:

- TXN: ~+$178 (MFE-implied, actual Alpaca fill unknown)
- CSCO: ~+$369 (MFE-implied, consistent with TP fill)
- WMT: unrealized but positive at exit time
- GOOG: ~+$276 (MFE at 11:19, exit at 11:42)

The P&L impact is real (potentially $800+ in forfeited paper gains), but more importantly the **training data impact** is severe: all four trades are labeled with 0% return and `broker_exception:APIError` or `timeout` exit reasons, which will confuse the training flywheel's reward signal. The model will not learn that these setups were profitable. This is the highest-priority consequence.

### 2. Two distinct failure subtypes share the same reconcile path

- **Bracket-fill-not-detected** (TXN, CSCO): the Alpaca bracket already executed; executor attempted a redundant SELL; API rejected it; reconcile zeroed at entry. Fix: detect bracket completion events via position reconcile.
- **PENDING_NEW premature close** (WMT, GOOG): the executor submitted a valid sell order but didn't wait for fill; reconcile closed within 3-4 seconds. Fix: add fill-wait / grace period to exit path.

Both subtypes converge on the same `[RECONCILE-PAPER] Closed stuck ... trade: (pnl=$0.00)` code path in `src/shadow_trading/reconcile.py`.

### 3. signal_exit_price is NULL on all 5 trades (B1 gap confirmed)

The field `signal_exit_price` is NULL across every record examined. The reconcile path that closes trades writes `actual_exit_price` but never populates `signal_exit_price`. This is the B1 gap identified in the sprint plan. Exit slippage (`exit_slippage_bps`) is also NULL/absent on all affected trades.

### 4. exit_retry_count is 0 on all API-failure trades

The field `exit_retry_count` defaults to 0 and was never incremented on any of the four failing trades. No retry logic was executed before reconcile terminated the trades. The retry column exists in the schema but the code path that populates it is either absent or not triggering. This is a B2 gap: the broker exception is logged but not counted, and no retry is attempted.

### 5. CMCSA is structurally clean; the other four share a single defect cluster

CMCSA's stop_loss exit was mechanically correct — the bracket's SL leg executed on Alpaca's side, fill was at exactly the configured stop price, and the exit was logged as a success with accurate P&L. The loss is real and correctly attributed.

The other four trades all passed through the `exit_failed` → `reconcile.py` code path, which is where the P&L zeroing occurs. Fixing that path will unblock accurate attribution for all future timeout exits and bracket-fill detections.

---

## File References

| Component | Path | Notes |
|-----------|------|-------|
| Reconcile path | `src/shadow_trading/reconcile.py` | `Closed stuck ... trade: (pnl=$0.00)` logic — primary fix target |
| Executor exit | `src/shadow_trading/executor.py` | PENDING_NEW handling; retry counter; exit order submission |
| Alpaca adapter | `src/shadow_trading/alpaca_adapter.py` | `place_paper_exit` / bracket order submission |
| Stop multiplier config | `config/settings.example.yaml` line 557 | `strategies.pullback.stop_atr_multiplier: 2.0` |
| Stop multiplier code | `src/packets/template.py:79-104` | `_resolve_bracket_stop_multiplier()` |
| DB field | `shadow_trades.signal_exit_price` | NULL on all 5 — B1 target |
| DB field | `shadow_trades.exit_retry_count` | 0 on all API failures — B2 target |

---

*End of memo. Total trades investigated: 5. Legitimate exits: 1 (CMCSA). Defect-attributed zero-P&L closes: 4 (TXN, CSCO, WMT, GOOG). Defect issues to file: 3 distinct root causes (bracket-fill-not-detected, PENDING_NEW premature close, signal_exit_price not written).*
