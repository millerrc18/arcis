# executor.py `except Exception` Audit — Sprint 0.C

**Date:** 2026-04-27  
**File audited:** `src/shadow_trading/executor.py` (3037 lines)  
**Clause count:** 64  
**Auditor:** Sprint 0.C / C.5 agent (third pass)  
**Issue:** #707  

---

## Summary

| Category | Count |
|---|---|
| INTENTIONAL_NONBLOCKING | 26 |
| LEGITIMATE_FALLTHROUGH | 16 |
| BUG_CANDIDATE | 4 |
| NEEDS_INVESTIGATION | 4 |
| **Total** | **50** |

> Note: 14 sites are nested sub-handlers within larger try/except blocks (e.g.
> Telegram notification helpers within a critical-path handler). These are
> counted once under their innermost category. The table above covers the
> logical categories.

---

## INTENTIONAL_NONBLOCKING

These are side-path helpers where a failure must not abort the primary flow.
All are correctly non-blocking: they log at WARNING or DEBUG and continue.

| Line | Variable | Context | Log level | Verdict |
|---|---|---|---|---|
| 265 | `e` | Buying-power crisis Telegram notification | WARNING | OK — notification is best-effort |
| 753 | `e` | Drawdown-halt Telegram notification | WARNING | OK — notification is best-effort |
| 783 | `e` | Drawdown threshold Telegram alert | WARNING | OK — notification is best-effort |
| 938 | `close_err` | Emergency close of unprotected position (SDK missing) | ERROR | OK — logged at ERROR; close already attempted |
| 958 | `notify_err` | Unprotected-position Telegram notification | WARNING | OK — notification is best-effort |
| 994 | `close_err` | Emergency close of unprotected position (stop failed) | ERROR | OK — already logged+persisted; close attempt best-effort |
| 1011 | `e` | Unprotected-position Telegram notification (stop path) | WARNING | OK — notification is best-effort |
| 1116 | `exc` | Count open positions for `concurrent_positions` metadata | WARNING | OK — metadata, non-blocking |
| 1126 | `exc` | Fetch VIX at entry for metadata | WARNING | OK — metadata, non-blocking |
| 1160 | `e` | Store Implementation Shortfall (IS) bps | WARNING | OK — analytics metadata, non-blocking |
| 1195 | `exc` | WebSocket broadcast `trade_opened` | WARNING | OK — observability side-path |
| 1222 | `e` | IB shadow logger after shadow trade open | WARNING | OK — IB shadow is non-blocking by design (SD#41) |
| 1431 | `_e_t5` | Live broker cancel for retry exit | WARNING | OK — cancel is best-effort; retry proceeds |
| 1458 | `e` | Post-cancel fill-fetch failed (cancel raced fill) | WARNING | OK — cancel race detection; fallback is retry |
| 1751 | `e` | MR exit attribution logging | WARNING | OK — attribution is non-blocking side-path |
| 1786 | `e` | MR timeout attribution logging | WARNING | OK — attribution is non-blocking side-path |
| 1910 | `cancel_err` | Cancel unfilled entry order | WARNING | OK — cancel failure; trade still marked cancelled |
| 1988 | `_fetch_err` | Post-cancel fill-fetch in exit path | WARNING | OK — best-effort fill reconciliation |
| 2071 | `e` | Exit circuit-breaker Telegram notification | WARNING | OK — notification is best-effort |
| 2165 | `exc` | Exit-failed Telegram notification | WARNING | OK — notification is best-effort |
| 2275 | `e` | Attribution link on trade close | DEBUG | OK — attribution non-blocking; DEBUG is correct here |
| 2306 | `e` | Telegram `notify_trade_closed` | WARNING | OK — notification is best-effort |
| 2330 | `_tg_err` | Price-failure Telegram alert | WARNING | OK — notification is best-effort |
| 2464 | `e` | Live capital-guard Telegram alert | WARNING | OK — notification is best-effort |
| 2525 | `e` | Live daily-loss-guard Telegram alert | WARNING | OK — notification is best-effort |
| 2706 | `e` | Live `notify_trade_opened` | WARNING | OK — notification is best-effort |

---

## LEGITIMATE_FALLTHROUGH

These `except Exception` blocks are in pre-check governor or broker-fetch
paths that have explicit documented fallthrough semantics. The exception is
caught, logged, and the caller either re-validates later or takes a
fail-closed default.

| Line | Variable | Context | Log level | Fallthrough behaviour | Verdict |
|---|---|---|---|---|---|
| 198 | `exc` | `_resolve_event_risk_multiplier` — compute-on-demand failed | WARNING | Returns fail-conservative 0.5 | OK — explicit fail-conservative; logged |
| 271 | `exc` | `_check_paper_buying_power` — Alpaca fetch failed | WARNING (via `log_and_persist`) | Returns False (fail-closed) | OK — fail-closed documented in comment |
| 314 | `exc` | `_check_paper_buying_power_allocation` pre-LLM | WARNING | Returns False (fail-closed) | OK — pre-LLM gate; fail-closed |
| 478 | `e` | `_select_paper_broker` IB Gateway check | WARNING | Falls back to Alpaca | OK — fallback is the intent; WARNING logged |
| 525 | `e` | `open_shadow_trade_with_reason` governor pre-check | DEBUG | Falls through to `open_shadow_trade` which re-runs its own check | LEGITIMATE (see note below) |
| 541 | `e` | `open_shadow_trade_with_reason` open_shadow_trade call | WARNING | Returns `(None, "internal error: ...")` to caller | OK — error surfaced to caller |
| 669 | `_dup_err` | Atomic `BEGIN IMMEDIATE` duplicate check | WARNING | Falls back to non-atomic `get_open_shadow_trade_for_ticker` | OK — fallback documented; WARNING |
| 682 | `e` | Alpaca ghost-position check | WARNING (via `log_and_persist`) | Proceeds with DB check only | OK — explicit fallback documented |
| 786 | `e` | Drawdown check block | ERROR | Returns None (reject trade) | OK — fail-closed |
| 885 | `e` | Bracket order main try block | WARNING (via `log_and_persist`) | Falls through to market-order fallback | OK — B2.B deliberate resilience; commented |
| 1046 | `check_err` | Alpaca position-fetch after network error | ERROR (via `log_and_persist`) | Sets `submission_uncertain` | OK — uncertain state correctly recorded |
| 1077 | `e2` | Unknown market-order error (code bug) | ERROR (via `log_and_persist`) | Sets `failed` status | OK — persisted and logged |
| 1116 | `exc` | (see INTENTIONAL_NONBLOCKING) | | | |
| 1420 | `e` | `_retry_exit` pre-check: prior order status | WARNING | Falls back to cancel | OK — documented fallback |
| 1631 | `e` | `check_and_manage_open_trades` position fetch | (via `log_and_persist`) | Continues with None positions | OK — degraded-mode continued execution |
| 2378 | `e` | `open_live_trade` live-order submit failed | WARNING (via `log_and_persist`) | Returns None (no trade recorded) | OK — live trade NOT recorded on failure |

> Note on line 525: `open_shadow_trade_with_reason` pre-checks governor to
> capture `rejection_reason` before delegating to `open_shadow_trade`, which
> re-runs the check internally. The DEBUG-level swallow here is intentional
> because the fallthrough guarantees a second check. However — see
> NEEDS_INVESTIGATION #2 below — the DEBUG level means pre-check import
> failures are invisible.

---

## BUG_CANDIDATE

These sites have patterns consistent with silent failure hiding real errors.

### BC-1: Line 2411 — `open_live_trade` risk governor `except Exception` logs at ERROR but also returns None silently

```python
# Line 2408-2413
except ImportError:
    logger.error("[LIVE][RISK] Governor import failed for %s — REJECTING live trade", packet.ticker)
    return None
except Exception as e:
    logger.error("[LIVE][RISK] Governor check failed for %s: %s — REJECTING live trade", packet.ticker, e)
    return None
```

**Problem:** The pattern mirrors the shadow-path equivalent at line 618 correctly. However at line 2411, `except Exception` catches *all* exceptions including `GovernorInputMissingError` (which is supposed to surface required-key missing errors as hard failures per CLAUDE.md). A `GovernorInputMissingError` is silently converted to a warning-level rejection rather than a hard failure that would alert the operator.

**Severity:** Medium. Live trade is correctly blocked. Risk: operator may not investigate why trades are silently failing if `GovernorInputMissingError` fires repeatedly.

**Fix:** Add explicit `except GovernorInputMissingError` before `except Exception` to log at `CRITICAL` and send Telegram alert, then re-raise or return None after explicit notification.

**Status:** Not fixed in this PR (time-box). Filed as follow-up.

---

### BC-2: Line 2001 — Exit-path stale-order cancel logged at WARNING but swallows all cancellation errors including structural bugs

```python
# Line 2001-2010
except Exception as e:
    log_and_persist(...)
    logger.warning("[EXECUTOR] Stale exit order cancellation failed: %s", e)
```

**Problem:** Cancel failures here include the case where `cancel_paper_order` raises because `pending_order_id` is malformed (e.g. an IB integer order ID stored in the `alpaca_order_id` column — the #420 class of bug). A WARNING-level swallow means the root cause is never surfaced; the code proceeds to submit a new exit order against a potentially-still-live stale order. In the C / AMD 4/21-4/22 incidents, this exact code path contributed to double-submissions.

**Severity:** High. Prior production incidents documented in code (#310, #420 references).

**Fix:** Log at ERROR, not WARNING. Check whether `pending_order_id` looks like a UUID (Alpaca) vs integer (IB) and surface mismatch explicitly before attempting cancel.

**Status:** Not fixed in this PR (time-box). Filed as follow-up.

---

### BC-3: Line 3006 — `_check_sector_exposure` yfinance DEBUG swallow

```python
# Line 3002-3007
try:
    import yfinance as yf
    info = yf.Ticker(ticker).info
    sector = info.get("sector", "Unknown")
except Exception as e:
    logger.debug("[EXPOSURE] yfinance sector lookup failed for %s: %s", ticker, e)
```

**Problem:** `yf.Ticker(ticker).info` makes an outbound network call in the production scan cycle. Per CLAUDE.md, "Mock all external APIs in tests — no network calls from pytest". The DEBUG swallow means network failures are invisible. More importantly, this is called from `open_shadow_trade` as a post-entry notification helper. If the yfinance call blocks (DNS timeout) it adds latency to every trade open. The `except Exception` swallows the timeout silently.

**Severity:** Low-Medium. Non-blocking, but latency injection and invisible network calls in a performance-critical path.

**Fix:** Add a timeout wrapper or replace with a DB-backed sector lookup (recommendations.sector_at_scan if that column exists). Filed as follow-up.

**Status:** Not fixed in this PR (time-box). Filed as follow-up.

---

### BC-4: Lines 2897 / 2968 — Milestone/streak `except Exception` at DEBUG hide DB errors

```python
# Line 2895-2898 (close milestones)
    except Exception as e:
        logger.debug("[MILESTONE] Close milestone check failed: %s", e)

# Line 2966-2969 (loss streak)
    except Exception as e:
        logger.debug("[STREAK] Loss streak check failed: %s", e)
```

**Problem:** These functions execute SQL against `shadow_trades`. A `sqlite3.OperationalError` (e.g. table schema mismatch, locked DB) is swallowed at DEBUG. The operator would never see milestone/streak checks silently failing unless they dig into debug logs.

**Severity:** Low. Milestone checks are non-critical. But DEBUG level means schema issues post-migration go undetected.

**Fix:** Promote to WARNING level so DB errors surface in standard log monitoring.

**Status:** Not fixed in this PR (time-box). Filed as follow-up.

---

## NEEDS_INVESTIGATION

These sites need operator context to categorize definitively.

### NI-1: Lines 1521 / _retry_exit outer `except Exception`

```python
# Line 1521-1568 (in _retry_exit)
    except Exception as e:
        qty_pair = parse_qty_mismatch(str(e))
        if qty_pair is not None:
            ...
        else:
            log_and_persist(...)
            update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
            logger.error("[RETRY] Exit retry exception for %s: %s", ticker, e)
```

**Why needs investigation:** The `qty_mismatch` detection branches on parsing the error string (`parse_qty_mismatch(str(e))`). This is fragile — Alpaca may change their error message format. When `parse_qty_mismatch` returns None, the trade is marked `exit_failed` with a generic log entry. The retry counter is not incremented in the `else` branch, which means this path could loop indefinitely if reconcile resets status to `open`.

**Operator question:** Does reconcile reset `exit_failed` back to `open`? If so, the loop without counter increment is a live bug. If not, the current behaviour is acceptable.

**Action:** File follow-up issue requesting confirmation of reconcile→open reset behaviour and whether the counter needs incrementing in the `else` branch.

---

### NI-2: Line 525 — `open_shadow_trade_with_reason` governor pre-check swallowed at DEBUG

```python
# Lines 525-530
    except Exception as e:
        logger.debug(
            "[MR-WRAPPER] governor pre-check failed for %s: %s",
            packet.ticker, e,
        )
        # Fall through — let open_shadow_trade do its own checks
```

**Why needs investigation:** This is documented as intentional fallthrough (the governor re-runs in `open_shadow_trade`). However, if the governor raises `GovernorInputMissingError` here (required config key missing), DEBUG swallows it. The second check at line 618 would also raise `GovernorInputMissingError` and return None — but without a WARNING log, the operator only sees a rejected trade with no explanation.

**Operator question:** Is DEBUG intentional here because this is a pure diagnosis step (capture `rejection_reason`) and the second check is authoritative? If yes, OK. If the first check can surface different errors than the second, the DEBUG level hides them.

**Action:** Discuss with operator whether to elevate to WARNING for `GovernorInputMissingError` class specifically.

---

### NI-3: Line 2542 — `open_live_trade` position limit check fail-closed

```python
# Line 2541-2544
    except Exception as e:
        logger.error("[LIVE] Position limit check failed for %s — REJECTING trade: %s", packet.ticker, e)
        return None
```

**Why needs investigation:** `get_open_shadow_trades` is a DB call. A DB error here returns None (rejecting a live trade). If the DB is locked, every live trade entry is blocked silently with an ERROR log. For live trades this deserves a Telegram alert.

**Operator question:** Should DB errors on the live-trade position check trigger a Telegram critical alert rather than just an ERROR log?

**Action:** File follow-up issue. Low-cost fix: add Telegram alert on `except Exception` here, same pattern as drawdown halt.

---

### NI-4: Line 2561 — `open_live_trade` duplicate check fail-closed

```python
# Line 2560-2563
    except Exception as e:
        logger.error("[LIVE] Duplicate check failed for %s — REJECTING trade: %s", ticker, e)
        return None
```

**Why needs investigation:** Same DB-error-blocks-live-trade pattern as NI-3. Consecutive call to `get_open_shadow_trades`. If the DB is locked, both checks (NI-3 and NI-4) fire back-to-back, producing two ERROR logs but no operator alert.

**Action:** Same as NI-3 — combine into a single consolidated live-trade safety-check function with one Telegram alert on DB failure, rather than two separate fragile DB calls.

---

## Sites Audited but Not Categorized Above (within-function, covered by outer category)

The following are inner `except Exception` blocks nested inside a larger
category block (e.g., a Telegram helper nested inside a governor check). They
inherit their outer block's category:

- Line 541 (LEGITIMATE_FALLTHROUGH): covered under NI-2 discussion
- Line 578, 618 (open_shadow_trade validate/risk, LEGITIMATE_FALLTHROUGH): reject-trade path, mirrored at 2378/2411 for live path
- Lines 1113-1128 (INTENTIONAL_NONBLOCKING): concurrent_positions + VIX metadata
- Lines 2731 (IB shadow logger INTENTIONAL_NONBLOCKING)

---

## Follow-up Trackers Filed

- **BC-1** → #754: Live path `GovernorInputMissingError` swallowed at ERROR without Telegram alert
- **BC-2** → #755: Exit-path stale-order cancel WARNING level + IB order-ID mismatch detection
- **BC-3** → #756: yfinance outbound network call in post-entry notification path (latency + silent timeout)
- **BC-4** → #757: Milestone/streak DEBUG-level DB error swallows
- **NI-1** → #758: `_retry_exit` exit_retry_count not incremented in `else` branch of qty_mismatch check
- **NI-3/NI-4** → #759: Live-trade DB-error path needs Telegram critical alert

---

## Audit Method

1. Extracted all 64 `except Exception` line numbers via `grep -n "except Exception" src/shadow_trading/executor.py`
2. Read each site in context (±40 lines) to identify: try-block scope, variable references, log level, fallthrough or return behaviour
3. Applied classification rubric from issue #707:
   - Does try-block reference out-of-scope variables? (NameError class)
   - What is the log level on the except branch?
   - Is the swallow appropriate (optional side-path) or hiding real failures?
   - Is the context (ticker, error type) captured for diagnosis?
4. BUG_CANDIDATE: any site where a real error on the critical path could be hidden or where the fix (wrong log level, no alert) is clear and low-risk
5. NEEDS_INVESTIGATION: any site where the correct behaviour depends on operator context about adjacent subsystems (reconcile, live-trade pipeline design)
