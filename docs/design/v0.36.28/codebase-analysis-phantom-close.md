# Codebase analysis: phantom-close bug v0.36.28

## Sibling-bug findings

- **`src/shadow_trading/executor.py:1430-1434`** — **CONFIRMED SIBLING, same anti-pattern.** `_retry_exit` falls back to `pending_order_id = trade.get("exit_order_id") or trade.get("alpaca_order_id")` (line 1424). For a paper bracket whose exit never filled, `exit_order_id` is NULL and `alpaca_order_id` is the **parent BUY** order. Line 1430 calls `get_order_status(pending_order_id)`; line 1431 checks `_is_filled_status(prior.get("status"))` against `{"filled","closed"}` (executor.py:223,427). On a healthy open bracket, the BUY parent is `filled` → triggers `_close_from_broker_fill(trade, prior, db_path)` at line 1434, which writes `exit_price = parent.filled_avg_price` (entry fill price) and closes the trade. Same phantom-close mechanism. Severity: HIGH; same class as 1865-1869.

- **`src/shadow_trading/executor.py:2007-2009`** — **CONFIRMED SIBLING, same anti-pattern.** `_pending_oid = trade.get("exit_order_id") or trade.get("alpaca_order_id")` (line 1989). When cancel-races-fill returns `terminal_state='filled'` (line 2000 → `_handle_pre_exit_cancel`), code re-fetches the parent order at 2007 and runs `_is_filled_status(_filled.get("status"))` at 2008. For a paper bracket where cancel hits the parent BUY (`alpaca_order_id`), cancel of an already-filled BUY returns 422 "already in filled state" → `terminal_state='filled'`. Then 2008 sees parent.status='filled' and routes to `_close_from_broker_fill` (2009). Severity: HIGH. Mitigating factor: this path requires the operator/system to have initiated an exit cycle first (cancel call at 1995); a pure timeout flow won't reach here, but the same code is reached if any exit attempt is made on a bracket whose `exit_order_id` was never set.

- **`src/shadow_trading/executor.py:1361-1385`** (`_close_from_broker_fill`) — **STRUCTURAL ENABLER.** Function unconditionally treats `filled_order.get("filled_avg_price")` as the exit price (1370). No check that `filled_order` is a SELL (`side="sell"`). Both sibling sites above feed this with the parent BUY order. Severity: MEDIUM (called by buggy sites; not itself wrong, but a `side != "sell"` guard would defuse both siblings).

- **`src/shadow_trading/reconcile.py`** — **CLEAN.** Reconciler never uses `parent.status='filled'` as an exit signal. Stale-detection uses POSITION existence, not order status. No siblings.

- **`src/shadow_trading/bracket_attach.py:64-71`** and **`src/shadow_trading/bracket_monitor.py:90-143`** — **CLEAN.** Both treat parent.status carefully: `bracket_attach._is_protected` checks ACTIVE statuses for protection; `bracket_monitor._is_oco_topology` distinguishes OCO (parent=TP-limit) from BRACKET (parent=entry) before classifying. No "BUY-filled = exit happened" confusion.

## Live-trading impact

- **IB path (executor.py:1830-1858)**: **Verified safe.** Live trades enter the `if trade.get("source") == "live":` branch. `order_status` is constructed with `"legs": []` (line 1839) — empty by construction. Exit detection comes only from `child_order.status == "filled"` (1851-1855) via `ib_child_order_ids`. The post-block `if not bracket_exit:` (1863) then runs against `order_status['status']` (the parent IB order status). If a live IB bracket has parent filled but children unfilled, this branch would set `bracket_exit=True` against the IB **parent fill price** — same bug class as paper. **Caveat to operator's assertion:** removing 1865-1869 is safe for live IB because `bracket_exit` was already set inside the live block when a child fills (1853), so the `if not bracket_exit` gate skips. But if NO child has filled, the legacy code would currently set `bracket_exit=True` against parent fill — meaning we are TODAY phantom-closing live IB timeouts too, just no live trades have hit timeout for us to observe it.

- **Live Alpaca (non-IB)**: **DB confirms 0 live trades of any kind exist** (`SELECT source, broker, order_type, COUNT(*) FROM shadow_trades WHERE source='live'` returned empty). All live trades route through IB per `broker_factory.get_live_broker`. The parent-status branch at 1865-1869 has no live-Alpaca consumers. **Safe to delete.**

## Recovery scope

- **Paper bracket timeout closures since 2026-04-13**: **8 rows.**
  - Query: `SELECT trade_id, ticker, actual_entry_price, actual_exit_price, actual_exit_time FROM shadow_trades WHERE exit_reason='timeout' AND COALESCE(order_type,'')='bracket' AND source='paper' AND actual_exit_time >= '2026-04-13'`
  - **0 rows** match `exit_price == entry_price` — the brief's signature is wrong. `actual_entry_price` on the row is the ORIGINAL planned/submit price; the phantom exit_price = parent's `filled_avg_price` (entry FILL price, post-slippage), which differs from the submitted entry. **AMD `dcd090be` confirms**: row carries `actual_entry_price=439.80` (planned), `actual_exit_price=440.72` (parent filled_avg_price). Subsequent reconciled backfill `45eb2078` for AMD closed at 440.72 as `stop_loss` on 2026-05-18 09:07:10 — 5 minutes after the phantom close.
  - **4 of 8** have a follow-on `order_type='reconciled'` row for the same ticker within 24h → high-confidence phantoms.
  - **Sample**: 5 of the 8 closed in a single cycle at `2026-05-18T09:02:17` (ETN, MO, C, AMZN, AMD) — suggesting one timeout-sweep through a batch of bracket positions.

- **Recommended recovery approach**:
  1. Build candidate set: `exit_reason='timeout' AND order_type='bracket' AND source='paper' AND actual_exit_time >= '2026-04-13'`.
  2. For each, fetch the original Alpaca bracket parent order by `alpaca_order_id` and read `filled_avg_price` + `legs[*].status`. If `parent.filled_avg_price ≈ row.actual_exit_price` AND no leg is in a filled state, mark phantom.
  3. Cross-check by querying for a same-ticker `order_type='reconciled'` row created within 24h of the timeout close → strong corroboration.
  4. For confirmed phantoms: (a) preserve the original row with a new status flag (e.g. `quarantined=1` + `exit_reason='phantom_close_v0.36.28'`); (b) zero out `pnl_dollars`/`pnl_pct` to avoid corpus contamination; (c) if a follow-on reconciled row exists, link it via a new column or annotation. Do NOT delete — training-data integrity requires audit trail.
  5. Run as one-shot script under `scripts/recovery/v0_36_28_phantom_close.py` with `--dry-run` default. Estimated affected rows: ≤8 paper bracket trades + ~4 paired reconciled backfills.

## Alpaca legs contract

- **`get_order_status`** (`src/shadow_trading/alpaca_adapter_paper.py:228-233`) calls `client.get_order_by_id(order_id)` and routes through `_serialize_order` (`alpaca_adapter.py:66-105`).
- **Legs structure** (`alpaca_adapter.py:101-104`): `legs` is a list built by recursive `_serialize_order(leg, ...)` over `getattr(order, "legs", None) or []`. Each leg dict carries: `order_id`, `symbol`, `qty`, `side`, `type`, `status`, `filled_qty`, `filled_avg_price`, `filled_at`, `created_at`, `limit_price`, `stop_price`, `legs`.
- **Verification**: Alpaca-py `Order` objects for BRACKET parent orders return `legs` populated with the TP (limit) + SL (stop) child orders. The `executor.py:1870-1883` leg-walking code reads exactly the fields `_serialize_order` produces (`status`, `filled_avg_price`, `order_type`, `stop_price`, `limit_price`). `bracket_monitor._classify_legs` (lines 90-143) is a production consumer that exercises this same shape every cycle and passes — corroborates that `legs` IS populated for paper bracket parents.

## Confidence in proposed fix

- **HIGH** for the immediate paper-Alpaca fix at executor.py:1865-1869 (delete). No live-Alpaca brackets exist; live IB doesn't reach this branch when children fill; leg-walk at 1870-1883 captures the correct exit signal.

- **RISK 1 (must address in same PR)**: The SAME anti-pattern exists at `executor.py:1430-1434` and `2007-2009` (`_retry_exit` and pre-exit-cancel paths). Both feed parent BUY status into `_is_filled_status` then into `_close_from_broker_fill`. Shipping the 1865-1869 fix alone leaves these latent. Recommend: add a `side == "sell"` guard inside `_close_from_broker_fill` (line 1361) as defense-in-depth — `if str(filled_order.get("side","")).lower() != "sell": logger.warning(...); return`. Cheap, covers all three sites.

- **RISK 2 (note, not block)**: Live IB bracket with parent filled but no child fills would have hit the same phantom logic if any live IB trades had reached timeout. Currently 0 live trades, so no historical bad rows. Same `side != "sell"` guard mitigates.

- **RISK 3 (low)**: Removing 1865-1869 changes timeout-exit slippage tracking — `_signal_exit_pre_bracket` (line 1815) now reflects the actual signal price, not the phantom entry fill. This is a CORRECTION not a regression; B1 R2 comment at 1813-1815 anticipated this.
