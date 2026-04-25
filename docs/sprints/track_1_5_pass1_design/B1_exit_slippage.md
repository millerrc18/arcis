# B1 — Exit Slippage Persistence: Pass 1 Design

**Task:** Track-1.5 / B1  
**Pass:** 1 (Design Only — no code changes)  
**Date:** 2026-04-25  
**Author:** AI session (Pass 1 investigation)

---

## 1. Pass 1 Finding — Where Is the Regression?

### Headline

The regression is a **green-field omission, not a regression from a previously-wired state.** `signal_exit_price` and `exit_slippage_bps` were never written at trade close. The computation for `exit_slippage_bps` IS present at `executor.py:1842–1846` but the computed values are **local variables that die without being persisted** — they are logged (`executor.py:1847–1853`) and then silently discarded. No call to `update_shadow_trade` or `close_shadow_trade` includes either column.

### Evidence

**Entry slippage (working correctly):**

`src/shadow_trading/executor.py:1013–1021` — at trade open, the entry path explicitly writes both columns to `trade_data` before `insert_shadow_trade`:

```
executor.py:1015  trade_data["signal_entry_price"] = entry_price
executor.py:1019  trade_data["entry_slippage_bps"] = round(slippage_bps, 1)
```

**Exit slippage (broken):**

The main exit path runs in `check_and_manage_open_trades`. The exact lines:

- `executor.py:1712` — `signal_exit = current_price` (the signal trigger price is captured)
- `executor.py:1713` — `exit_slippage_bps = 0.0` (initialized)
- `executor.py:1838–1846` — when the exit order returns a filled status, `exit_slippage_bps` is recomputed correctly:

  ```python
  exit_slippage_bps = (
      (current_price - signal_exit) / signal_exit * 10000
      if signal_exit > 0
      else 0
  )
  ```

- `executor.py:1847–1853` — the log line fires correctly:

  ```python
  logger.info(
      "[SLIPPAGE] %s exit: signal=$%.2f, fill=$%.2f, slippage=%.1f bps",
      ticker, signal_exit, current_price, exit_slippage_bps,
  )
  ```

- `executor.py:1937–1945` — `close_shadow_trade(...)` is called immediately after, but `signal_exit_price` and `exit_slippage_bps` are **not** passed to it.

- `executor.py:1956–1964` — the post-close `update_shadow_trade` call writes only MFE/MAE/duration:

  ```python
  update_shadow_trade(
      trade["trade_id"],
      {
          "max_favorable_excursion": mfe,
          "max_adverse_excursion": mae,
          "duration_days": days_open,
      },
      db_path,
  )
  ```

  `signal_exit_price` and `exit_slippage_bps` are absent from this dict.

**close_shadow_trade signature** (`src/journal/store.py:405–412`) accepts only: `trade_id`, `exit_price`, `exit_time`, `exit_reason`, `pnl_dollars`, `pnl_pct`, `db_path`. No `signal_exit_price` or `exit_slippage_bps` parameters exist — it delegates all writes to `update_shadow_trade` internally.

**Schema columns confirmed present** (`src/schema/registry.py:247–252`):

```
ColumnDef("signal_entry_price", "REAL"),   # line 247
ColumnDef("entry_slippage_bps",  "REAL"),   # line 249
ColumnDef("signal_exit_price",   "REAL"),   # line 250
ColumnDef("exit_slippage_bps",   "REAL"),   # line 252
```

No schema changes needed.

### Secondary Close Paths (also missing the write)

Three other close paths also call `close_shadow_trade` without writing `signal_exit_price` / `exit_slippage_bps`:

1. **`_close_from_broker_fill`** (`executor.py:1209–1233`) — called when a cancel races a fill. No slippage fields written.
2. **`_retry_exit` filled path** (`executor.py:1356–1370`) — calls `close_shadow_trade` on successful retry fill. No slippage fields written.
3. **Mean-reversion exits** (`executor.py:1533–1541`, `executor.py:1568–1576`) — synthetic exits with no broker fill; `signal_exit_price` semantically N/A here. **Out of scope for B1** — these are model-priced exits, not fill-slippage events.

### Bracket Exit Path

The bracket exit path (`executor.py:1598–1660`) sets `current_price = leg_price` from the broker fill and `bracket_exit = True`. It then falls through to the same `close_shadow_trade` call at `executor.py:1937`. The `signal_exit` variable is set at `executor.py:1712` to the pre-bracket `current_price` (last polled price before bracket detection). The `exit_slippage_bps` computation block at `executor.py:1838–1846` is guarded by `if not bracket_exit:` — so for bracket exits, `exit_slippage_bps` stays at 0.0 (the initialized value) and is never logged or persisted either. This is a separate gap; Pass 2 scope below addresses what to do.

---

## 2. Implementation Plan (Pass 2 Will Execute)

### File and Function to Modify

**Single file:** `src/shadow_trading/executor.py`

**Location of the fix:** The post-close `update_shadow_trade` call at `executor.py:1956–1964`.

### Exact Change

Extend the post-close `update_shadow_trade` dict to include `signal_exit_price` and `exit_slippage_bps`. Both variables are already in scope at this call site: `signal_exit` (set at line 1712) and `exit_slippage_bps` (set at line 1713, updated at line 1842 when fill is available).

Current dict (`executor.py:1958–1962`):
```python
{
    "max_favorable_excursion": mfe,
    "max_adverse_excursion": mae,
    "duration_days": days_open,
}
```

Replace with:
```python
{
    "max_favorable_excursion": mfe,
    "max_adverse_excursion": mae,
    "duration_days": days_open,
    "signal_exit_price": signal_exit if signal_exit > 0 else None,
    "exit_slippage_bps": exit_slippage_bps if signal_exit > 0 else None,
}
```

### Defensive Behavior

- If `signal_exit` is 0 (price fetch returned 0 or None): write `signal_exit_price = None`, `exit_slippage_bps = None`. No division-by-zero risk since the `exit_slippage_bps` computation already guards `if signal_exit > 0`.
- If exit fill returns None (order not filled at exit, e.g. partial or pending path): the `fill_exit` branch at `executor.py:1839–1846` never executes, so `exit_slippage_bps` stays 0.0. In that case `signal_exit > 0` may still be true, and we would write `exit_slippage_bps = 0.0`. This is **undesirable** — 0 bps slippage with no fill is misleading. The fix should set `exit_slippage_bps = None` when the fill price is not available.

  Revised logic (replacing the existing lines 1713 and 1842–1846):

  ```python
  # executor.py:1712-1713  (replace exit_slippage_bps = 0.0)
  signal_exit = current_price
  _fill_exit_price = None   # set when broker confirms fill
  exit_slippage_bps = None  # NULL until fill confirmed

  # executor.py:1839-1846  (replace the fill_exit block)
  if fill_exit is not None:
      _fill_exit_price = float(fill_exit)
      current_price = _fill_exit_price
      if signal_exit and signal_exit > 0:
          exit_slippage_bps = (_fill_exit_price - signal_exit) / signal_exit * 10000
          logger.info(
              "[SLIPPAGE] %s exit: signal=$%.2f, fill=$%.2f, slippage=%.1f bps",
              ticker, signal_exit, _fill_exit_price, exit_slippage_bps,
          )
  ```

  With this, `exit_slippage_bps` is `None` unless a real fill price is present.

- Boundary: `signal_exit = 0` → `signal_exit_price = None`, `exit_slippage_bps = None`.

### Log Line Format (already present, just confirming)

The existing log at `executor.py:1847–1853` already emits:

```
[SLIPPAGE] {ticker} exit: signal=$X.XX, fill=$Y.YY, slippage=Z bps
```

No change needed to the log format. The log may move a few lines up/down as part of the refactor above, but the format is correct.

### Secondary Paths

**`_close_from_broker_fill` (`executor.py:1209–1233`):** This path closes from a broker fill that was detected via cancel-race or pre-check. The "signal price" here is ambiguous — we don't have a signal trigger price in scope. The clean approach is to write `signal_exit_price = None`, `exit_slippage_bps = None` for this path (or pass them explicitly if the caller has context). Pass 2 should add an `update_shadow_trade` call after `close_shadow_trade` in `_close_from_broker_fill` that writes `NULL` for both columns explicitly. This ensures the columns are populated (with NULL) rather than left in their prior state.

**`_retry_exit` filled path (`executor.py:1361–1370`):** Same as `_close_from_broker_fill`. The retry path has a `fill_price` from the broker but no `signal_exit` in scope. Write `signal_exit_price = None`, `exit_slippage_bps = None`.

**Bracket exits:** `signal_exit` (the pre-bracket polled price) is in scope at the close site. But the `exit_slippage_bps` computation is currently gated `if not bracket_exit:`. The bracket fill price IS available as `current_price` by the time we reach `close_shadow_trade`. Pass 2 can extend the fix to bracket exits by writing `signal_exit_price = signal_exit`, `exit_slippage_bps = None` (slippage not computed for bracket legs — the fill is at a specific limit/stop price, not a market fill). Marking as **IB bracket fills are out of scope per B2 scope fence** — the Alpaca bracket path can be included if the implementation is trivial.

---

## 3. Test Strategy (Pass 2 Will Write Tests)

**Test file:** `tests/shadow_trading/test_exit_slippage_persistence.py` (NEW)

**Fixture convention** (matching `tests/shadow_trading/test_paper_exit_qty_sync.py`):

```python
@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "exit_slippage.db")
    initialize_database(db)
    return db
```

Seed helper inserts a trade via `insert_shadow_trade` with `entry_price`, `actual_entry_price`, `signal_entry_price`, `planned_shares` set. Mocks: `_get_current_price_safe` (return signal price), `place_paper_exit` (return fill dict), `get_all_positions`, `get_order_status`, `cancel_paper_order`.

### Test Cases

**1. `test_exit_slippage_normal_fill` (positive case)**

- Seed a trade: `entry_price=100.00`, `target_1=105.00`
- Mock `_get_current_price_safe` → `105.00` (target hit)
- Mock `place_paper_exit` → `{"status": "filled", "filled_avg_price": 105.25, "order_id": "oid-1", "filled_qty": 100}`
- Run `check_and_manage_open_trades`
- Assert: `signal_exit_price == 105.00`, `exit_slippage_bps` is approximately `23.8` bps (`(105.25 - 105.00) / 105.00 * 10000`)
- Assert: row `status == "closed"`

**2. `test_exit_slippage_none_fill` (None fill → NULL slippage)**

- Same seed; mock `place_paper_exit` → `{"status": "filled", "filled_avg_price": None, "order_id": "oid-2", "filled_qty": 100}`
- Assert: `signal_exit_price == 105.00` (or None, depending on signal_exit > 0 logic)
- Assert: `exit_slippage_bps IS NULL`

**3. `test_exit_slippage_zero_signal_price` (boundary: signal_exit = 0 → NULL)**

- Seed a trade; mock `_get_current_price_safe` → `0` (or None, coerced to 0)
- Assert: `signal_exit_price IS NULL`, `exit_slippage_bps IS NULL`
- Assert: trade does NOT reach "closed" (exit should not trigger at price=0)
  - Alternatively, if exit does not trigger (which is correct — `exit_reason` requires price > target/stop), this test verifies no spurious NULL-slippage row

**4. `test_exit_slippage_idempotent` (re-run on already-closed trade doesn't overwrite)**

- Seed a trade pre-closed with `signal_exit_price=105.00`, `exit_slippage_bps=23.8`
- Run `check_and_manage_open_trades` again
- Assert: `signal_exit_price` and `exit_slippage_bps` remain unchanged (closed trades are not processed again)

**5. `test_exit_slippage_negative_slippage` (fill below signal price)**

- Mock fill price `104.80` vs signal `105.00`
- Assert: `exit_slippage_bps` is approximately `-19.0` bps (negative — filled better than signal)

**Query helper:**

```python
def _row(db_path, trade_id):
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute(
            "SELECT signal_exit_price, exit_slippage_bps, status "
            "FROM shadow_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone())
```

---

## 4. Scope Fence Verification

### Files Pass 2 Will Touch

| File | Change |
|------|--------|
| `src/shadow_trading/executor.py` | Extend post-close `update_shadow_trade` dict; change `exit_slippage_bps = 0.0` initialization to `None`; adjust fill-detection block |
| `tests/shadow_trading/test_exit_slippage_persistence.py` | NEW — test file |

**Total: 2 files. Within scope fence.**

No schema changes. No changes to `src/journal/store.py` (the `close_shadow_trade` signature does not need to change — the fix calls `update_shadow_trade` separately, which is already the established pattern for the MFE/MAE/duration write at line 1956).

### IB Exit Path

The IB exit path routes through `src/trading/broker_factory.py` and `_retry_exit` for live trades. It shares the same `close_shadow_trade` call in `_retry_exit` but the missing-slippage issue there is covered under B2. Pass 2 will NOT touch the IB path. The `_close_from_broker_fill` function is technically reached by both paper and live code paths; Pass 2 should write `signal_exit_price = None, exit_slippage_bps = None` for that path to avoid ambiguity, but this is a NULL-write (no computation) and does not constitute IB exit logic.

---

## 5. Risks / Unknowns

**R1 — `exit_slippage_bps = 0.0` initialization scope.**  
The variable is initialized at `executor.py:1713` inside the `if exit_reason:` block but outside `if not bracket_exit:`. Pass 2 must verify that changing the initialization from `0.0` to `None` does not affect any other downstream use of `exit_slippage_bps` within the same loop body (e.g., the Telegram notification at `executor.py:2058` reads `trade.get("exit_slippage_bps")` — from the DB, not the local variable, so this is safe).

**R2 — `signal_exit` is set to `current_price` (the pre-exit polled price).**  
For bracket exits, `current_price` gets overwritten to the bracket fill price before `signal_exit` is set. Reading the code order:
- `executor.py:1644,1652`: `current_price = exit_price` (bracket fill)
- `executor.py:1712`: `signal_exit = current_price` (would capture the fill, not the pre-trigger signal)

This means `signal_exit` for bracket exits will equal the fill price → `exit_slippage_bps = 0`. Pass 2 needs to read this carefully and either (a) capture `signal_exit` before the bracket detection block, or (b) write `NULL` for bracket slippage. Option (b) is cleaner and already noted in section 2.

**R3 — Mean reversion exit paths.**  
Three MR exit calls (`executor.py:1533`, `executor.py:1568`) call `close_shadow_trade` directly. These never set `signal_exit` or `exit_slippage_bps`. Pass 2's change is only to the post-close `update_shadow_trade` at line 1956 — the MR paths do not reach that update (they `continue` before it). No MR interference.

**R4 — `_filter_to_schema` in `update_shadow_trade`.**  
`src/journal/store.py:252` calls `_filter_to_schema("shadow_trades", updates)` before writing. This strips keys not in the registry. Since `signal_exit_price` and `exit_slippage_bps` ARE in `src/schema/registry.py` (lines 250, 252), they will pass through. No risk here, but Pass 2 should include a test that the columns are actually written (not silently dropped).

**R5 — Confirmed no IB-specific close path is reached by the main exit loop.**  
The bracket IB path (`executor.py:1606–1634`) sets `bracket_exit = True` and `current_price`, then falls through to the same `close_shadow_trade` at line 1937. The IB path does reach the post-close `update_shadow_trade` at 1956. Writing `signal_exit_price` and `exit_slippage_bps` in that dict will also persist (NULL) values for IB bracket exits. This is acceptable — NULL for IB bracket slippage is correct (not measured in this sprint).
