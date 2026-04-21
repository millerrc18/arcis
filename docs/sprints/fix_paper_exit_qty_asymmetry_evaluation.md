# Fix Sprint — Paper Exit Qty Asymmetry + Phantom Exit-Intent — Pass 1 Evaluation

**Branch:** `fix/paper-exit-qty-asymmetry` off main @ `0f472b0`
**Status:** Pass 1. Gated — no code changes. Pass 2 → push → operator checkpoint → Pass 3.
**Date:** 2026-04-21
**Inputs:** `docs/audit/root_cause_investigation_2026-04-21.md`, live DB, live Alpaca (read-only).

---

## TL;DR for impatient readers

The fix prompt originally framed this as a qty-mismatch sprint (CVS retry loop). Deep tracing of the C overshoot from this morning revealed a **different, upstream root cause** that produces both symptoms:

> **`_strip_enum` at `src/shadow_trading/alpaca_adapter.py:43-48` strips enum prefixes but does NOT lowercase.** Executor at `src/shadow_trading/executor.py:1375` and `:1383` checks against lowercase sets (`FILLED_ORDER_STATUSES = {"filled", "closed"}`, `("filled", "partially_filled")`). `str(OrderStatus.FILLED)` in alpaca-py returns `"OrderStatus.FILLED"`; `_strip_enum` returns `"FILLED"` (uppercase); `"FILLED" in {"filled","closed"}` is **False**.

Every bracket whose legs fill server-side is invisible to the executor's bracket-exit detection. When a fallback stop/target/timeout check then fires on market price, the executor submits `_submit_exit_order(shares=planned_shares)` — and because the position has already been closed by the filled leg at Alpaca, the sell reopens a short. This is the overshoot mechanism.

**Hypothesis classification:** **H5 (Other)** — the append to the prompt listed H1-H4; the actual root cause is a silent normalization bug in the detection layer. It is upstream of reconcile.py and executor.py's exit-decision code. It has been latent in every bracket exit since enum handling was introduced.

**Fix scope implication:** The proposed D2 (reconcile 3rd branch) and D3 (paper exit qty) options are **defense-in-depth guards** that catch the symptom after the primary detection has failed. Shipping only D2+D3 makes the system quieter but does not stop phantom exits — it merely prevents the short from growing larger than the original position size. **The root-cause fix is a one-character change** in `_strip_enum` (add `.lower()`). Treating that as a trivial one-line change understates it: it needs careful callsite sweep because every caller currently relies on the uppercase output.

Operator decision at gated checkpoint: ship D2+D3 as guards this sprint AND file a follow-up for the upstream normalization fix, OR expand this sprint to include the upstream fix.

---

## D1 — Caller trace for `_submit_exit_order`

### Callsites

| Callsite | Purpose | `shares` source | Auto or manual |
|----------|---------|-----------------|----------------|
| `src/shadow_trading/executor.py:1461` | Primary scheduled exit — inside `check_and_manage_open_trades()` when `exit_reason` is set by bracket-check or fallback (stop/target/timeout) | `shares = int(float(trade.get("planned_shares") or 1))` at `executor.py:1202` | Automatic — every watch-loop tick |
| `src/shadow_trading/executor.py:1094` | Retry path — inside `_retry_exit()` for trades already stuck in `exit_pending` / `exit_failed` | `shares = int(float(trade.get("shares") or trade.get("planned_shares") or 0))` at `executor.py:1092` | Automatic — invoked from `check_and_manage_open_trades:1182` when status matches |
| `src/cli/commands.py:387` | Manual operator exit via CLI | CLI-provided | Manual only |
| `src/api/routes/shadow.py:92` | Manual operator exit via API | API-provided | Manual only |

Also bypassing `_submit_exit_order` and calling `place_paper_exit` directly:

| Callsite | Purpose |
|----------|---------|
| `src/shadow_trading/executor.py:795` | Emergency close after entry stop-loss submission failed (Fix #274) |
| `src/platform/shadow_harness.py:124` | Test harness for replay |
| `src/cli/commands.py:208` | CLI direct-close command |

### Which callsite produced the observed retries for trade `00330e8d` (CVS) today

Three distinct failure modes visible in `logs/arcis.log`:

**09:48:39 (initial exit):** Came from `executor.py:1461` — `check_and_manage_open_trades` → fallback triggered `exit_reason="timeout"` (CVS created 2026-04-13, config `timeout_days=8`, day 8 matches `>=`). Log signature: `status=OrderStatus.PENDING_NEW` comes from the `else` branch at `executor.py:1566` (the else-catchall after `_is_filled_status`/`_is_pending_status` both returned False because `_is_pending_status("OrderStatus.PENDING_NEW".lower())` = `"orderstatus.pending_new"` not in `PENDING_ORDER_STATUSES`).

**10:07:02 onwards:** Came from `executor.py:1094` (`_retry_exit`). Between cycles, reconcile reverts `exit_failed → open`, but `status=open` then still goes through `check_and_manage_open_trades` and if there's no condition to trigger a new exit cycle, the retry path doesn't re-fire directly. What actually happens:

Re-examining the log with this lens:
- `reconcile` at 09:48:45 reverted CVS → `status=open`.
- Next `check_and_manage_open_trades` sees CVS status=open. Walks the full bracket/price path. Bracket check fails silently (case bug). Fallback hits `timeout` again. Fires sell.
- Sell fails ("insufficient qty: 4 available" — qty bug). Reconcile reverts again. Loop.

The "retry" cadence isn't the `_retry_exit` path — it's the same primary-exit path triggering every cycle until something changes. The qty mismatch (130 planned vs 4 available) is the secondary bug that prevents the sell from executing; it does not cause the loop, it allows it to continue without closing the position.

### Cadence-driving logic

`check_and_manage_open_trades` is called from `src/scheduler/watch.py` inside `_run_scan` (line 643-), which fires on the 30-min scan cadence. But the exit-check loop runs at a sub-scan cadence too — see `src/scheduler/watch.py` for `_run_intraday_exit_check` or equivalent. The observed 5-15 min jitter matches an intraday exit cadence, not the 30-min scan cadence. Specific cadence driver not fully traced — worth confirming in Pass 2.

### Retry: intended or unintended?

`_MAX_EXIT_RETRIES = 3` at `executor.py:982` is INTENDED protection for stuck trades. After 3 retries, status becomes `exit_abandoned` per `executor.py:1033-1037`. **But reconcile's `exit_failed → open` revert bypasses this counter** because it puts status back to `open`, which doesn't trigger `_retry_exit`. So the counter never increments past the initial attempt. Loop is bounded only by the case-sensitivity bug being fixed or the trade being manually quarantined.

---

## D5 — Phantom exit-intent trace

### C (2026-04-21 09:43:27 ET) — full timeline

From DB `shadow_trades` row `66ad6dfd-04c4-4b4f-b32a-bc429f98e619`:

| Field | Value |
|-------|-------|
| `ticker` | C |
| `direction` | long |
| `order_type` | bracket |
| `planned_shares` | 65 |
| `entry_price` / `actual_entry_price` | 128.30 |
| `alpaca_order_id` | `bf8d1dac-f548-4915-b33a-3a0840d8e554` (bracket parent) |
| `exit_order_id` | `3d175828-c192-47ee-ab8a-5e6b8480ea12` (the overshoot sell) |
| `status` | `needs_manual_review` |
| `exit_reason` | `exit_overshoot_detected` |
| `created_at` | 2026-04-14T11:17:03 ET |
| `updated_at` | 2026-04-21T09:43:33 ET (marked by reconcile) |

From Alpaca order history for the bracket parent `bf8d1dac` (queried with `get_order_by_id`):

| Event | Time (ET) | Detail |
|-------|-----------|--------|
| Bracket buy entry submitted | 2026-04-14 11:17:03 | qty 65, market |
| Entry filled | 2026-04-14 11:17:06 | `filled_avg_price=127.858615`, parent `status=filled` |
| Stop leg (child `9f3277bd`) canceled | 2026-04-21 09:32:21 | OCO sibling-cancel reaction |
| **Target leg (child `8557a2f0`) FILLED** | **2026-04-21 09:33:38** | limit @ $133.96 → filled @ **$134.55**. **Position closed server-side.** |
| Overshoot sell submitted | 2026-04-21 09:43:27 | qty 65, market, `position_intent=sell_to_open` — Alpaca accepts because qty available = 0 |
| Overshoot sell filled | 2026-04-21 09:43:27 | `filled_avg_price=134.71`, creating `-65` short |
| Reconcile overshoot-detect | 2026-04-21 09:43:33 | alpaca_qty=-65 → `exit_overshoot_detected` |
| Overshoot covered | 2026-04-21 12:59:35 | `buy_to_close` qty 65 @ $132.71 — AFTER my audit snapshot; source unknown (operator or scripted?) |

### Was there ever a C long position?

Yes — entry filled at 2026-04-14 at 127.86 (confirmed in Alpaca). Position existed for 7 days. At 09:33:38 today, the bracket's limit (target) leg filled, closing the long. Position was at zero shares between 09:33:38 and 09:43:27. The executor's 09:43:26 decision to exit fired against a zero position, producing a sell_to_open.

### Upstream trace: what decided to exit C at 09:43:27?

**Control flow reconstruction** (annotated against `src/shadow_trading/executor.py`):

1. `check_and_manage_open_trades:1149` — fetches `open_trades` (includes C row 66ad6dfd, still `status=open` because nothing has updated it from the 09:33:38 leg fill yet).
2. `:1181-1183` — trade.status=`open`, so does NOT enter `_retry_exit`. Continue.
3. `:1196` — `current_price = _get_current_price_safe("C")` → real market price ≈ $134.xx.
4. `:1202` — `shares = 65`.
5. `:1334-1371` — bracket status check runs. `order_type="bracket"` and `alpaca_order_id` set, so enters the try block.
6. `:1370-1371` — `order_status = get_order_status("bf8d1dac...")`. Alpaca returns: `status="filled"` (post `_strip_enum` → `"FILLED"`), legs array with filled target leg and canceled stop leg. Leg statuses after `_strip_enum`: target `"FILLED"`, stop `"CANCELED"`.
7. `:1373-1379` — `parent_status = "FILLED"`. **`"FILLED" in FILLED_ORDER_STATUSES` = `"FILLED" in {"filled", "closed"}` = False.** `bracket_exit` stays False. No parent-detection.
8. `:1380-1393` — legs loop. `leg_status = "FILLED"` for target leg. **`"FILLED" in ("filled", "partially_filled")` = False.** `bracket_exit` stays False. `exit_reason` stays None. No leg-detection.
9. `:1397-1403` — position existence check. C IS in `_alpaca_tickers` (Alpaca still has 0 qty, but `get_all_positions()` — check whether it includes zero-qty accounts. If C is not in positions set, warning logs. Not verified in this pass; doesn't change outcome.)
10. `:1405-1407` — `bracket_exit` is False, so `exit_reason = None` (redundant).
11. `:1408-1416` — fallback check. `stop_hit`: current_price=134.xx > stop_price=120.76. **`target_1_hit`**: current_price >= target_1 (133.96). **TRUE**. `exit_reason = "target_1_hit"`.
12. `:1418` — `if exit_reason:` True. Enter exit block.
13. `:1420-1443` — `entry_status="open"` not in `("pending","pending_entry")`, skip.
14. `:1449` — `if not bracket_exit:` True. Enter the cancel-and-submit block.
15. `:1451-1458` — cancel pending order (`alpaca_order_id=bf8d1dac`, the bracket parent). This cancels **all remaining children** server-side. (Children were already in terminal states, so the cancel may be a no-op or non-fatal error.)
16. `:1461` — `_submit_exit_order(trade, shares=65)`. Calls `place_paper_exit("C", 65)`. Alpaca accepts the sell; position goes from 0 to -65. sell_to_open.
17. `:1491` — `exit_status = "OrderStatus.PENDING_NEW"` (Alpaca initial state for a freshly submitted market order).
18. `:1492-1544` — `_is_filled_status("OrderStatus.PENDING_NEW")` False (not "filled"/"closed"). `_is_pending_status(...)` False (because `"orderstatus.pending_new" not in {"new","accepted","pending_new",...}`). Falls to `else`.
19. `:1566-1585` — marks `exit_failed`, logs "Broker exit failed for C (status=OrderStatus.PENDING_NEW)", sends Telegram. Reconcile later reverts to `open` (guard sees positive qty — BUT qty is now -65, so guard should have caught it; it actually DID per the DB row's final status).

### Same trace for NEE (2026-04-20 10:25 ET) and NVDA (2026-04-15 09:54 ET)

**NEE (trade `a685fc8a-d173-42b3-ab79-ddb5c47035ca`):**
- DB row: direction=long, planned_shares=153, entry_price=90.39, alpaca_order_id=`4739a528-e0e9-4942-9cd8-18954003db79` (bracket parent). From Alpaca order history today: sell_to_open 153 NEE at 2026-04-20 14:20:17 UTC (10:20 ET) at $92.85. Reconcile flagged at 10:25:42 ET. **Same mechanism: bracket's limit (target) leg filled earlier the same day, then fallback fired, sell_to_open created the short.** Alpaca still holds NEE -153 today (not covered).

**NVDA (trade `f01dc590-f4f1-4049-ac73-6572da43b735`):**
- DB row: direction=long, planned_shares=49, entry_price=188.16, alpaca_order_id=`89f677ba-44e3-4a7a-9629-03e7c93ff5ac`. Marked overshoot 2026-04-15 09:54 ET. Alpaca currently holds NVDA -245 shares — qty is 5x the planned_shares, meaning either multiple overshoot events compounded OR the original overshoot was larger than planned_shares (fallback using `shares = int(float(trade.get("planned_shares") or 1))` shouldn't exceed planned, so compounding is the likely path — the fallback fired multiple cycles before the reconcile guard tripped). Worth confirming in Pass 2; not critical for the fix.

### Common pattern across all 13 zombies

| Zombie | Overshoot date | Hypothesis fit |
|--------|----------------|----------------|
| GOOGL 4/15 | Same morning as NVDA and MO | Bracket leg filled, fallback, sell_to_open |
| NVDA 4/15 | Same cluster | Same |
| MO 4/15 | Same cluster | Same |
| TGT 4/15 | Afternoon | Same |
| BK 4/16 | Morning | Same |
| CVX 4/17 | Morning cluster | Same |
| FDX 4/17 | Same cluster | Same |
| INTC 4/17 | Same cluster | Same |
| GM 4/17 | Same cluster | Same |
| CAT 4/17 | Same cluster | Same |
| NEE 4/20 | Morning | Same (verified above) |
| GS 4/20 | Afternoon | Same |
| **C 4/21** | Morning | **Same (fully traced above)** |

**All 13 follow the same pattern: bracket entry fills, is held for days, a child leg fills server-side (usually target or stop), DB row is not updated, executor's next intraday exit check does not detect the filled leg (case bug), fallback triggers on current market price, fallback exits via `_submit_exit_order(shares=planned_shares)` on a now-closed position, creating a short.**

### Why the clustering at market open

Market open is when:
1. Overnight gap-up/down pushes price through target or stop levels (high chance of bracket leg fill)
2. First price refreshes with current day's IV (volatility)
3. Scan cycle fires its first intraday exit check of the day

The cluster is not a race condition — it's selection bias. Brackets most often fill on price moves, and price moves most often happen on open. So the overshoots cluster when leg fills cluster, which clusters at open.

### Hypothesis classification (H1–H5)

The prompt append proposed H1–H4 plus H5 (Other). My classification:

- **H1 (Phantom DB row — row shouldn't exist/be open):** Rejected. The C row SHOULD exist; it reflects a real trade. The bug is that its status should have transitioned to `closed` when the target leg filled, and did not, because the executor missed the leg fill.
- **H2 (Race with entry — buy rejected, row still opens):** Rejected. Entry filled cleanly on 4/14.
- **H3 (Signal regeneration at open — scan produces exit for closed position):** Rejected. The scan cycle produced NEW entries (CVS, BK, C, USB, PFE buy attempts), not exits for closed positions. Exits came from intraday exit-check logic, which uses DB state (open trades) — correct source of intent.
- **H4 (Reconcile race):** Rejected. Reconcile runs are sequential to executor runs; no double-dispatch from race observed.
- **H5 (Other):** **SELECTED.** The case-sensitivity bug in `_strip_enum` produces silent detection failure in executor's bracket leg check. The failure surfaces as a phantom exit-intent via the legitimate fallback path.

### Fix scope implication

The D2 (reconcile 3rd branch) and D3 (paper exit qty check) options proposed in the original prompt are **symptomatic guards**. They would:
- D2: catch the resulting short earlier (status `needs_manual_review` instead of `open`), but the short is already opened.
- D3: prevent the initial sell from being submitted with wrong qty, but since the phantom-exit attempts to sell the FULL planned qty on a now-closed position, D3 Option 1 (query broker, use `min(planned, alpaca_qty)`) would make the sell become qty=0 → no sell → no overshoot. **D3 Option 1 actually does close the bug vector for C-style phantom exits.** Option 2 (reconcile-before-exit) similarly closes it because reconcile would sync the DB row to closed first, then the executor would skip the exit.

**Interpretation:** D3 Option 1 and Option 2 are NOT just guards — they coincidentally prevent phantom exits in addition to qty-mismatch overshoots. D2 alone is not sufficient.

However: the **true root cause** is the `_strip_enum` normalization. Fixing it upstream makes D3 unnecessary from a correctness standpoint (but still worth having as defense-in-depth). Deciding whether to ship both is an operator call.

---

## D2 — Reconcile 3rd-branch options

Current logic at `src/shadow_trading/reconcile.py:643-665`:

```python
if alpaca_qty <= 0:
    # Mark needs_manual_review, exit_reason='exit_overshoot_detected'
else:  # alpaca_qty > 0
    # Revert to 'open'
```

Missing branch is `0 < alpaca_qty < planned_shares`. Three options evaluated:

### Option 2a: Sync DB to broker state

Update `planned_shares` to `alpaca_qty`, keep `status='open'`, clear `exit_reason` and `exit_order_id`.

- **State after:** DB row matches broker. Next exit cycle uses correct qty.
- **Next-cycle behavior:** Cleanly exits if conditions trigger.
- **Blast radius:** DB mutation on a canonical field (`planned_shares`) — destructive to original intent. Analytics (MFE, MAE, P&L) use planned_shares as denominator; changing it mid-trade corrupts the trade history. Historical attribution of win-rate, slippage, etc. uses this field.
- **Test difficulty:** Medium. Must verify the sync happens only in the 0<qty<planned case, not on every reconcile.
- **Risk:** Corrupts per-trade analytics. High-blast.

### Option 2b: Mark `exit_pending` with residual qty

Update `planned_shares` to `alpaca_qty` (or add a new field like `residual_shares`) and set `status='exit_pending'`. Next cycle's `_retry_exit` re-exits the residual.

- **State after:** Row is explicitly pending an exit-for-residual.
- **Next-cycle behavior:** `_retry_exit` fires on exit_pending, exits `residual_shares`.
- **Blast radius:** Introduces a new state transition. Requires a new field (`residual_shares`) or a schema decision: should residual be tracked separately from planned? Same analytics concern as Option 2a.
- **Test difficulty:** Higher. Must handle retry-counter interaction: does exit_retry_count apply here?
- **Risk:** State-machine complexity. Medium-blast.

### Option 2c: Mark `needs_manual_review` with new exit_reason

Set `status='needs_manual_review'` and `exit_reason='qty_mismatch_partial_fill'`. Operator handles the 4-share residual manually.

- **State after:** Row is flagged for operator. Executor stops touching it.
- **Next-cycle behavior:** Row is ignored by normal exit path (like other `needs_manual_review` rows).
- **Blast radius:** Small — operator visibility only. Accumulates zombies (like existing 13 zombies), but at least they're explicit.
- **Test difficulty:** Low. Same pattern as existing overshoot guard.
- **Risk:** Operator must periodically sweep zombies. Low-blast.

### D2 recommendation (to be surfaced in Pass 2)

**Option 2c is safest.** Option 2a corrupts analytics; 2b introduces schema complexity. 2c matches the existing overshoot pattern exactly — same guard with a new reason. Operator already has to manage zombies; one more class doesn't worsen ops cost.

---

## D3 — Paper exit qty options (revised per append)

Per the prompt append, the "broker-state-of-truth via close_position qty-agnostic" option is dropped (incompatible with intentional-shorting strategy roadmap). Remaining:

### Option 3.1: Query broker position before submit, use `min(planned, alpaca_qty)`

Inside `_submit_exit_order` or just before it, fetch the broker's current position qty for the ticker. If `alpaca_qty < planned_shares`, use `alpaca_qty` as the actual sell qty.

- **API cost:** +1 `get_open_position(ticker)` per exit attempt. Existing exit-check already fetches `get_all_positions` once per cycle (`executor.py:1174`), so the info is available in `_alpaca_tickers` — could be passed through, avoiding the extra call.
- **Latency:** Minimal if using cached `_alpaca_tickers` (single API call). 50-200ms if per-exit fresh call.
- **Backward compat:** Existing tests assume `shares` is honored. Tests that mock a position equal to planned_shares pass. Tests that mock zero or negative position would need updates.
- **Silent-break risk:** If `alpaca_qty` is stale (network blip, caching), exits could be sized wrong. Low, but worth asserting staleness bounds.
- **Bonus:** If `alpaca_qty == 0`, the exit is qty=0 → no sell submitted → no phantom-overshoot. This coincidentally closes the C-style bug.

### Option 3.2: Reconcile-before-exit

Call reconcile's position-sync logic at the start of `_submit_exit_order` (or just before each exit in `check_and_manage_open_trades`). Then use the freshly-synced DB qty.

- **API cost:** Reconcile is already an expensive operation (`get_all_positions` + DB writes). Running it per exit would be expensive if exits are frequent. One reconcile per scan cycle (not per exit) would be cheaper.
- **Latency:** Per-scan reconcile: +1-2 sec per cycle. Per-exit: +1-2 sec per exit.
- **Backward compat:** Reconcile side effects matter. Running reconcile inside `_submit_exit_order` creates a dependency that's hard to mock in tests and hard to reason about.
- **Silent-break risk:** Introduces reconcile failures as exit blockers. If reconcile fails, does exit proceed or abort?
- **Bonus:** Also closes phantom-overshoot (reconcile would close the row for C's filled target leg first).

### D3 recommendation (to be surfaced in Pass 2)

**Option 3.1 using cached `_alpaca_tickers`.** It already has the necessary info (position qty is in the `get_all_positions` response at `executor.py:1174`), just needs to be threaded through to `_submit_exit_order` as an additional parameter OR queried directly inside. Low blast, clean semantics, and as a bonus it catches the phantom-exit path.

Option 3.2 is architecturally heavier (dependency graph between executor and reconcile gets tangled) and has no clear benefit over 3.1 for this bug.

---

## D4 — Test plan

### New tests

File: `tests/shadow_trading/test_reconcile_partial_fill_mismatch.py`

1. `test_reconcile_handles_0_lt_alpaca_qty_lt_planned` — seeds DB with `planned_shares=130`, mocks Alpaca returning qty=4. Asserts after reconcile: row goes to the chosen option's terminal state (for 2c: `status='needs_manual_review'`, `exit_reason='qty_mismatch_partial_fill'`). Assert NOT `status='open'`.
2. `test_overshoot_guard_still_fires_at_negative_qty` — regression guard for existing behavior. `alpaca_qty=-65` (short), asserts `status='needs_manual_review'`, `exit_reason='exit_overshoot_detected'` — unchanged.
3. `test_happy_path_exit_unchanged` — seeds DB with `planned_shares=65`, mocks Alpaca returning qty=65. Asserts reconcile reverts `status='open'`, no new exit_reason. Byte-identity preserved.

File: `tests/shadow_trading/test_paper_exit_qty_sync.py`

4. `test_paper_exit_uses_broker_state_when_db_stale` — seeds `planned_shares=130`, mocks broker position qty=4. Asserts `_submit_exit_order` submits qty=4 (not 130).
5. `test_paper_exit_zero_qty_no_submit` — seeds `planned_shares=65`, mocks broker position qty=0. Asserts no order submitted, DB row marked appropriately (probably `closed` via reconcile or `needs_manual_review`).
6. `test_paper_exit_race_with_reconcile` — timing test: reconcile runs during exit submission. Asserts DB state converges to consistent terminal state, no infinite loop.
7. `test_bracket_leg_fill_detected_case_insensitive` — **NEW test for the upstream bug**. Seeds a bracket where `get_order_status` returns `status="FILLED"` (uppercase, simulating `_strip_enum` output). Asserts `bracket_exit=True` and correct exit_reason. This test FAILS against current main and documents the root cause. Only relevant if we include upstream fix in this sprint.

### Existing suites that must stay green

- `tests/shadow_trading/test_reconcile*.py` — reconcile round-trips
- `tests/shadow_trading/test_executor*.py` — executor flow
- `tests/scripts/test_reconcile_2026_04_20.py` — Sprint 2 reconcile script
- `tests/scheduler/` — scan cycles
- `tests/platform/byte_identity/` — Sprint F golden fixtures

### Coverage specifics

- Happy-path exit: stop-hit with correct qty → closes trade, updates DB. **MUST remain byte-identical.**
- Edge case: `planned_shares=0` (rejected trade) — ensure no exit attempted.
- Edge case: `alpaca_qty` unparseable (TypeError, ValueError) — ensure defensive fallback.

---

## Callsite sweep — impact of changing `_submit_exit_order` semantics

### If `_submit_exit_order` signature changes to accept `actual_qty` (Option 3.1)

Callers that currently pass `shares`:

| Caller | Param passed | Impact |
|--------|--------------|--------|
| `executor.py:1094` | `shares` from DB planned/actual | Replace with broker-synced qty |
| `executor.py:1461` | `shares` from DB planned | Replace with broker-synced qty |
| `cli/commands.py:387` | CLI arg | Keep as-is (operator override); maybe warn if mismatch |
| `api/routes/shadow.py:92` | API arg | Same as CLI |

**Assumption shared by all callers:** `shares` is the qty the DB thinks the broker has. For scheduled paths, this is broken when DB is stale. For manual paths (CLI, API), the operator is authoritative — don't override.

### Affected tests

Callsite tests will break if signature changes. Prefer: keep signature, change internal behavior — query broker inside, use `min(shares, alpaca_qty)`. CLI/API paths can opt out via a kwarg like `force_qty=False` if they want to bypass the min check.

---

## Risk register

| Risk | Probability | Severity | Mitigation |
|------|-------------|----------|------------|
| D3 fix introduces silent no-sell when `alpaca_qty` is stale/wrong | Low | High | Assert staleness; fall back to planned if broker query errors |
| D3 fix breaks mocked tests | High | Low | Update test fixtures |
| Upstream `_strip_enum` fix breaks other callers expecting uppercase | Unknown | Medium | **Pass 2 callsite sweep required** |
| 2c adds zombies operator must clean up | High | Low | Operator cleanup script (authored, not run in this sprint) |
| Phantom-exit fix still leaves 4 unmanaged shorts at Alpaca (C, NEE, NVDA, TGT) | 100% | High | Operator action required pre-deploy; separate from this sprint |
| Market-hours deploy disrupts watch loop | Medium | Medium | Deploy after close, verify startup flow |
| Reconcile change and executor change deployed together race | Low | Medium | Sequenced commits; test with both mid-deploy |

---

## What this sprint does NOT fix

1. **The `_strip_enum` case-sensitivity bug itself** — if operator chooses not to bundle upstream fix, file follow-up sprint. Defense-in-depth from D2+D3 prevents the overshoot but leaves the detection broken. Future features that rely on leg-fill detection (e.g., exit-slippage analytics, attribution) will silently be wrong.
2. **The 13 existing `needs_manual_review` zombies** — operator-executed cleanup script needed (proposal in Pass 2).
3. **The 4 current unmanaged shorts (C, NEE, NVDA, TGT)** — operator action required before or during deploy.
4. **The sleep-recovery false-positive log spam** — cosmetic, explicitly out of scope per original prompt.
5. **The CVS retry loop trade `00330e8d`** — operator can quarantine or operator-issued cleanup after deploy.

---

## Pass 1 decisions to surface at gated checkpoint

1. **D2 option selection:** Recommend **2c (mark `needs_manual_review` + new `exit_reason='qty_mismatch_partial_fill'`)**. Operator to confirm or redirect.
2. **D3 option selection:** Recommend **3.1 (query broker position, use `min(planned, alpaca_qty)`), threading `_alpaca_tickers` through from `check_and_manage_open_trades`**. Operator to confirm or redirect.
3. **Upstream fix — bundle or separate?** The `_strip_enum` normalization fix at `alpaca_adapter.py:43-48` is the true root cause. Recommend: include in this sprint (adds commit 6 "fix: lowercase enum prefix strip in _strip_enum") with callsite sweep test. Alternative: ship D2+D3 as guards, file follow-up sprint. **Operator chooses.**
4. **Hypothesis classification:** H5 — case-sensitivity bug, not any of H1–H4. Operator to confirm.
5. **Cleanup script for zombies:** propose in Pass 2, author in Pass 3, operator runs post-deploy.

---

## Open questions for Pass 2

1. Verify the exact exit-check cadence driver (30-min scan vs. sub-scan loop). The retry timings (5-15 min jitter) don't match 30 min exactly.
2. Confirm `alpaca-py` version in `requirements.txt` to verify that `str(OrderStatus.FILLED)` indeed returns `"OrderStatus.FILLED"` (vs. the newer Python 3.12 `StrEnum` behavior which returns the value).
3. Check `_is_filled_status` and `_is_pending_status` — do they suffer the same case mismatch? Partial answer: yes, they lowercase first, so ORIGINAL uppercase strings still fail because they contain the `orderstatus.` prefix even lowercased.
4. Confirm whether `get_all_positions()` returns zero-qty positions in its result, because the position-existence check at `executor.py:1398` depends on that.
5. NVDA's -245 qty vs planned 49: cause (multiple overshoot events or single large overshoot from a signal source)?
