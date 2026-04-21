# Fix Sprint — Paper Exit Qty Asymmetry + Phantom Exit-Intent — Pass 2 Research

**Branch:** `fix/paper-exit-qty-asymmetry` (commit 1 = Pass 1 @ 943d647).
**Inputs:** Pass 1 evaluation, DB read-only, Alpaca read-only, repo source. Empirical Python runtime test.
**Purpose:** verify Pass 1 evidence, finalize recommendations, propose cleanup script spec, explicitly scope what this sprint does and doesn't fix. Gated — push after this commit, wait for operator.

---

## 1. Line-number verification

Pass 1 cited ~23 file:line references. All verified via grep. Two corrections:

| Pass 1 citation | Corrected | Reason |
|-----------------|-----------|--------|
| `alpaca_adapter.py:43-48 _strip_enum` | `alpaca_adapter.py:38-48` (def at **line 38**, docstring 39-44, body 45-48) | Off by 5; I was counting docstring start |
| `reconcile.py:643-665 overshoot guard` | `reconcile.py:651-674` (try at 651, `if alpaca_qty <= 0` at **line 655**, `continue` at 666, `else` revert at 667-674) | Line 643 in Pass 1 was the comment header; actual guard starts at 651 |

All other citations (executor `1094`, `1182`, `1202`, `1375`, `1383`, `1418`, `1461`, `1566`; callsites in `cli/commands.py`, `api/routes/shadow.py`, `shadow_harness.py`) verified exact.

**Additional lookups discovered in Pass 2 sweep:**

| Location | What |
|----------|------|
| `alpaca_adapter.py:457-465` | `get_order_status` — no `nested=True` passed, but Alpaca REST API returns legs regardless (confirmed empirically). Not the failure point. |
| `alpaca_adapter.py:264-299` | `place_paper_exit` — returns `"status": str(order.status)` **without** `_strip_enum`. This is why the log shows `OrderStatus.PENDING_NEW` raw form at `executor.py:1566`. |
| `alpaca_adapter.py:51-91` | `_serialize_order` — applies `_strip_enum` to `status`, `side`, `type` but returns uppercase-result strings due to the same bug. |

## 2. The `_strip_enum` bug — empirical proof

Python 3.12 + alpaca-py 0.43 runtime test (executed in this sprint's shell):

```python
from alpaca.trading.enums import OrderStatus
str(OrderStatus.FILLED)        # → 'OrderStatus.FILLED'
OrderStatus.FILLED.value       # → 'filled'
type(OrderStatus.FILLED).__mro__
# [EnumType, type, object]  — a regular Enum, NOT StrEnum
```

`_strip_enum("OrderStatus.FILLED")`:
```python
s = str("OrderStatus.FILLED")         # 'OrderStatus.FILLED'
return s.split(".")[-1] if "." in s else s
# → 'FILLED'   (uppercase!)
```

The docstring at `alpaca_adapter.py:39-44` describes the intended behavior:

> "Alpaca SDK enums like OrderStatus.held stringify as 'OrderStatus.held', but downstream code (bracket monitor) compares against plain 'held'."

**Note the lowercase "held" in the docstring.** The *intent* was to produce lowercase strings to match downstream checks. The implementation uses the enum's NAME, which is uppercase, not the enum's VALUE, which is lowercase. So the function works for `bracket_monitor.py` only because bracket_monitor ALSO applies `.lower()` before comparing (`bracket_monitor.py:75`), rendering the uppercase output harmless there. Every other caller — including `executor.py` — compares against lowercase sets and silently misses.

### Downstream callers that compare `_strip_enum` output against lowercase literals

| Caller | Set/Comparison | Broken? |
|--------|----------------|---------|
| `executor.py:1375` | `in FILLED_ORDER_STATUSES = {"filled","closed"}` | **Yes** |
| `executor.py:1383` | `in ("filled","partially_filled")` | **Yes** |
| `executor.py:1491+` | `_is_filled_status` / `_is_pending_status` (lowercase-first then set-in) | **Yes — but partially**: `.lower()` converts "FILLED" → "filled" (matches!) but "OrderStatus.FILLED" → "orderstatus.filled" (still prefixed, fails). So _is_filled_status works on `_strip_enum` output but NOT on raw `str(enum)` output from `place_paper_exit` |
| `bracket_monitor.py:75` | `.lower()` applied before split | **No** — it explicitly lowercases first |
| `_serialize_order` callers for `side`, `type` | Various | Would need per-callsite audit |

**This explains why the log shows both error forms:**

1. `[EXIT] Broker exit failed for CVS — marking exit_failed (status=OrderStatus.PENDING_NEW)` at `executor.py:1566` — the `exit_status` here came from `place_paper_exit` which doesn't strip (bug in `place_paper_exit:296 "status": str(order.status)`). Then `_is_pending_status` lowercases the full string → `"orderstatus.pending_new"` — doesn't match, falls through to exit_failed.
2. `[EXIT] Broker exit failed for CVS — marking exit_failed: {...insufficient qty...}` at `executor.py:1467` — different path: exception from Alpaca REST API bubbles up as APIError, caught, logged with the JSON payload.

Both paths lead to `status=exit_failed`, reconcile reverts to `open`, loop continues.

## 3. Overshoot cluster at market open — mechanism

The prior audit's open question was: "why do overshoots cluster 09:01-10:52 ET for 9 of 13?"

**Answer:** Bracket child legs fire on price moves. Price moves cluster at market open (overnight gap, auction cross, first-bar volatility). When a child leg fills server-side during market open:

1. Position is closed at Alpaca.
2. Executor's next intraday exit check queries the bracket parent's status via `get_order_status`.
3. `_strip_enum` returns uppercase leg status — check at `executor.py:1383` misses.
4. `bracket_exit` remains False; `exit_reason` remains None.
5. Fallback stop/target/timeout path engages.
6. `current_price` (real-time market, not overridden because bracket_exit stayed False for parent check too — `"FILLED"` not in `{"filled","closed"}` at line 1375) — is post-open price, often close to target or past it.
7. `target_1_hit` or `stop_hit` or `timeout` fires.
8. `_submit_exit_order(shares=planned_shares)` — sell-to-close of full planned_shares.
9. Alpaca sees position qty=0 or < planned_shares → sell_to_open — overshoot.

**Selection bias, not a race condition.** The 09:01-10:52 ET window is simply when bracket legs most often trigger, which is when this latent bug most often manifests. Outside that window, the only way the bug manifests is timeout (like CVS today — day 8 = timeout_days, no leg fill needed).

## 4. Recommendations (operator approves or redirects at gated checkpoint)

### D2 — reconcile 3rd branch

**Recommended: Option 2c — mark `needs_manual_review` with `exit_reason='qty_mismatch_partial_fill'`.**

Rationale:
- Lowest blast radius; matches existing overshoot-guard pattern exactly.
- Does not mutate `planned_shares` (preserves per-trade analytics integrity).
- Zombies from this class will accumulate, but operator already manages overshoot zombies; same cleanup path.

Trade-off: a trade in this state requires operator intervention to close the residual 4 shares (for CVS-type case). Pass 3 proposes the cleanup script spec.

### D3 — paper exit qty

**Recommended: Option 3.1 — query broker position, use `min(planned_shares, alpaca_qty)`.**

Threading: reuse the `_alpaca_tickers` set already fetched at `executor.py:1174` via `get_all_positions()`. Extend it from a simple set of symbols to a `dict[symbol → qty]`, then pass through to `_submit_exit_order` or check inside.

Rationale:
- Zero additional API calls (reuses existing cache).
- Defensive: catches phantom-exit (qty=0 → no submit) AND qty-mismatch (resize).
- Simple, testable, narrow.

Implementation notes:
- `get_all_positions()` returns `[{"symbol": "C", "qty": "-65", ...}, ...]`. Convert to `{sym: float(qty)}`.
- In `_submit_exit_order`, if `qty <= 0`, **do not submit**; instead mark the trade with an appropriate status (recommend: delegate to reconcile via `status='exit_pending'` + `exit_reason='position_already_closed'`; reconcile handles terminal state in its usual cycle).
- If `0 < qty < planned_shares`, submit with `qty` instead of `planned_shares`. Log the discrepancy.
- If `qty >= planned_shares`, submit with `planned_shares` (unchanged behavior).

### Upstream fix — bundle or separate?

**Recommended: separate follow-up sprint.** 

Rationale:
- The `_strip_enum` fix is the actual root cause, and the cleanest fix is a one-line change (add `.lower()` before return). But:
- Callsite sweep is non-trivial. Every caller of `_serialize_order` and `get_order_status` currently receives uppercase-result strings. Some may have accumulated case-insensitive handling as a workaround; changing to lowercase might re-break those.
- Changing enum normalization mid-session with an active watch loop is high-risk: all in-flight orders and cached state use the current representation. Deploy window matters.
- The follow-up sprint can include the callsite audit + careful migration (e.g., two-phase: first introduce `_strip_enum_value` that returns lowercase; migrate callers one-by-one; then retire the old one).

Alternative (operator may prefer): bundle as **commit 6** in this sprint with a strict callsite audit as part of Pass 1 of that commit. Increases sprint scope but ships the real fix together with its guards. Trade-off is deploy timing risk.

**My recommendation: ship D2+D3 as guards now (this sprint), file follow-up sprint for upstream.** D2+D3 together prevent the overshoot symptom entirely. The `_strip_enum` bug becomes cosmetic (silent detection miss, but no economic damage because D3 Option 3.1 prevents the submit). This removes time pressure from the upstream fix and lets it be done carefully.

### Hypothesis classification — confirmed H5 (Other)

- H1 (phantom DB row): rejected — rows correctly reflect real trades.
- H2 (race with entry): rejected — entries filled cleanly.
- H3 (signal regeneration): rejected — exits come from DB-driven intraday check, not scan-signal regeneration.
- H4 (reconcile race): rejected — reconcile and executor run sequentially in the watch loop; no observed parallelism.
- **H5: `_strip_enum` case-sensitivity bug + fallback exit path using DB planned_shares on a closed position.** All evidence aligns.

## 5. Cleanup path for existing zombies (post-deploy, operator-executed)

### Current zombie population (from Pass 1 audit)

13 `needs_manual_review` rows with `exit_reason='exit_overshoot_detected'`:

- GOOGL (4/15), NVDA (4/15), MO (4/15), TGT (4/15 — same DB row as current Alpaca short -161)
- BK (4/16)
- CVX (4/17), FDX (4/17), INTC (4/17), GM (4/17), CAT (4/17)
- NEE (4/20 — same DB row as current Alpaca short -153)
- GS (4/20)
- C (4/21 — the one traced above)

Plus the CVS retry-loop row `00330e8d` which is a different class (partial-fill residual, not overshoot).

### Proposed cleanup script spec (author in Pass 3, operator runs after deploy + verification)

File: `scripts/cleanup_overshoot_zombies_2026_04_21.py`

**Behavior:**
1. Read all `needs_manual_review` rows with `exit_reason='exit_overshoot_detected'` from `shadow_trades`.
2. For each: fetch Alpaca position via `get_open_position(ticker)`. 3 cases:
   - **Position qty = 0 (no longer short):** the short was covered (via operator action or scripted cover). Close the DB row with `status='closed'`, `exit_reason='overshoot_covered'`, `actual_exit_price=last_known_close_fill_price` (look up most recent `buy_to_close` fill for ticker), compute pnl.
   - **Position qty < 0 (still short):** leave the row as-is (still needs operator decision on whether to cover).
   - **Position qty > 0 (long again, unexpected):** log warning, leave as-is.
3. Emit summary to stdout: per-row before/after state.
4. `--dry-run` mode: print planned changes, write nothing.

**Guardrails:**
- Dry-run default. Requires `--apply` to write.
- Never close a row whose Alpaca position is still non-zero.
- Never alter `planned_shares` (analytics integrity).
- Read-only on Alpaca side (`get_open_position` only, no cancel/submit).

**Out of scope for script:**
- Covering the remaining shorts (C partially covered 12:59 today via unknown source; NEE, NVDA, TGT still short). Operator covers those manually or via a separate `cover_residual_shorts.py` that requires explicit confirmation per ticker.

### CVS `00330e8d` — handled separately

Not an overshoot zombie. Partial-fill residual. After D2+D3 ship:
- D3 Option 3.1 will prevent the bogus 130-share sell next cycle (will submit qty=4 instead, which fills, closes the row cleanly).
- OR operator sets `quarantined=1` pre-deploy to stop the retry spam (one-time manual DB mutation).

Either approach works. The manual quarantine is the faster ops fix; the code fix is the durable solution.

## 6. What this sprint does NOT fix — explicit scope boundaries

Fixed by this sprint (D2 + D3):
- [x] CVS retry loop (D3 Option 3.1 prevents the 130-share sell attempt; D2 marks any new partial-fill mismatches for review).
- [x] Future overshoots from the same mechanism (D3 Option 3.1 produces qty=0 submit → no sell → no short opened).
- [x] Visible state pollution (D2 surfaces the residual-qty case explicitly).

Not fixed by this sprint:
- **Upstream `_strip_enum` bug** — follow-up sprint recommended. Until then, bracket leg-fill detection continues to silently miss; the system does NOT benefit from the intended leg-filled-early-close logic; trades that could have closed clean with a nice P&L entry via target leg instead close via fallback at a possibly worse price. Economic impact: low (positions still close, just with higher exit slippage and no per-leg attribution).
- **Existing 13 `needs_manual_review` zombies** — cleanup script in Pass 3; operator runs post-deploy.
- **4 current unmanaged shorts (C partially covered, NEE, NVDA, TGT)** — operator decision; out of scope for code sprint.
- **CVS row `00330e8d`** — either manual quarantine pre-deploy or automatic cleanup on first post-deploy scan cycle (depending on operator preference).
- **Sleep-recovery false-positive log spam** (`watch.py:442`) — cosmetic, separate one-line fix sprint.
- **`place_paper_exit` return value normalization** — `alpaca_adapter.py:296` returns raw `str(order.status)` which produces "OrderStatus.PENDING_NEW" logs. Related to upstream fix; ship together.
- **NVDA -245 vs planned 49** — discrepancy indicates multiple overshoot events compounded on NVDA. Root cause likely the same mechanism firing multiple cycles before reconcile caught it. With D3 deployed, will not recur. Worth a one-off post-deploy audit to confirm.
- **`timeout_days=8` vs implied `default=15`** — operator configured override. Not a bug but contributes to CVS being timeout-eligible on day 8. Outside scope.

## 7. Pass 3 implementation checklist (for operator-triggered execution)

Pre-flight (before operator triggers Pass 3):
- [ ] Operator reviews Pass 1 + Pass 2 at gated checkpoint.
- [ ] Operator approves or redirects D2 option selection (default: 2c).
- [ ] Operator approves or redirects D3 option selection (default: 3.1).
- [ ] Operator decides on upstream fix bundling (default: separate follow-up).
- [ ] Operator addresses the 4 unmanaged shorts pre-deploy (can be in parallel).
- [ ] Operator decides on CVS `00330e8d` pre-deploy (quarantine or let code fix handle).

Pass 3 commits (after approval):
- Commit 3: Test scaffolding — 7 tests from Pass 1 D4 that fail against current main.
- Commit 4: D2 implementation — reconcile.py 3rd branch (Option 2c).
- Commit 5: D3 implementation — executor.py paper exit qty sync (Option 3.1).
- Commit 6: Tests now pass. Verify: 7 new tests pass; existing reconcile/executor suites pass; Sprint F byte-identity fixtures pass.
- Commit 7: Cleanup script `scripts/cleanup_overshoot_zombies_2026_04_21.py`. Dry-run default. Operator-executed.
- Commit 8: CHANGELOG entry + MASTER.md counts if needed. Issue filing (2 new issues: #TBD for qty-mismatch guard, #TBD for paper exit qty sync). Close them in the commit message.
- Open PR.

---

## Pass 2 Decisions Summary

1. **D2 = Option 2c** (pending operator approval): needs_manual_review + `qty_mismatch_partial_fill`.
2. **D3 = Option 3.1** (pending operator approval): query broker qty, use `min(planned, alpaca_qty)`.
3. **Upstream fix**: separate follow-up sprint (pending operator approval).
4. **Hypothesis classification**: H5 (`_strip_enum` case-sensitivity + fallback exit path).
5. **Cleanup script**: authored in Pass 3, operator-executed post-deploy.
6. **Pre-deploy operator actions**: address 4 shorts, decide CVS `00330e8d` handling.

Push branch. STOP per gated protocol.
