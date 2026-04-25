# B2 — Broker Exception Structured Logging: Pass 1 Design

**Task ID:** Track-1.5 / B2
**Pass:** 1 (DESIGN ONLY — no code, no tests, no schema changes)
**Date:** 2026-04-25
**Author:** Design agent (static analysis)
**Status:** Ready for Pass 2 implementation

---

## 1. Silent-Swallow Inventory

Scope: `src/shadow_trading/**`, `src/trading/ib_broker.py`, `src/services/**`.
Grep pattern: `except Exception` and `except:` (bare).
Sites that catch more specific types (ConnectionError, APIError, ValueError) are excluded per scope definition.

### Classification key

| Code | Meaning |
|------|---------|
| `bug_silent_swallow` | No log or inadequate log — failure is invisible to operator. Should log + persist + (usually) re-raise. |
| `intentional_swallow` | Caller handles outcome via return value or subsequent check. Logging would be noise for normal operation. |
| `partial_swallow` | Currently logs but lacks structured fields (ticker, broker, operation, recoverable). Pass 2 upgrades the log line. |

### Inventory table

| # | file:line | except clause | classification | rationale |
|---|-----------|---------------|----------------|-----------|
| 1 | `src/shadow_trading/executor.py:163` | `except Exception as exc` | `intentional_swallow` | `_resolve_event_risk_multiplier` fallback — defaults to 0.5 with a WARNING log. Named defect in memory (#267). This is a pre-existing IB feature-compute fallback, NOT a broker call. No broker fields to add. |
| 2 | `src/shadow_trading/executor.py:230` | `except Exception as e` | `intentional_swallow` | Buying-power crisis Telegram notification failure. Notification is best-effort; trade logic continues. No broker fields needed. |
| 3 | `src/shadow_trading/executor.py:236` | `except Exception as exc` | `partial_swallow` | Buying-power check from Alpaca adapter. Already logs (WARNING + comment "fail CLOSED"). Missing: structured `broker`, `operation=fetch_buying_power`, `recoverable` flag. This is a direct broker surface. |
| 4 | `src/shadow_trading/executor.py:271` | `except Exception as exc` | `partial_swallow` | Pre-LLM BP check failed. Already warns. Missing: `broker`, `operation=fetch_buying_power`, `recoverable=False`. |
| 5 | `src/shadow_trading/executor.py:427` | `except Exception as e` | `partial_swallow` | IB Gateway connection attempt for paper routing. Already warns. Missing: `broker=ib`, `operation=connect`, `recoverable=True` (falls back to Alpaca). |
| 6 | `src/shadow_trading/executor.py:474` | `except Exception as e` | `intentional_swallow` | MR-wrapper governor pre-check — falls through to `open_shadow_trade`'s own check. Debug-logged. Not a broker call. |
| 7 | `src/shadow_trading/executor.py:490` | `except Exception as e` | `intentional_swallow` | MR-wrapper `open_shadow_trade` raised — returns structured `(None, reason)`. Not a raw broker call. |
| 8 | `src/shadow_trading/executor.py:527` | `except Exception as e` | `partial_swallow` | Validation check for paper trade. Already errors + returns None. Not a direct broker call but guards broker submission. Needs `ticker`, `operation=validate`, `broker` added. |
| 9 | `src/shadow_trading/executor.py:567` | `except Exception as e` | `partial_swallow` | Governor check for paper trade. Already errors + returns None. Needs `ticker`, `operation=risk_check`. |
| 10 | `src/shadow_trading/executor.py:621` | `except Exception as _dup_err` | `intentional_swallow` | Atomic duplicate check — falls back to non-atomic DB check. WARNING logged. Not a broker call. |
| 11 | `src/shadow_trading/executor.py:634` | `except Exception as e` | `partial_swallow` | **KEY SITE.** Alpaca `get_all_positions()` during pre-entry ghost-position check. WARNING logged but no broker/operation fields. Missing: `broker=alpaca_paper`, `operation=fetch_positions`, `ticker`, `recoverable=True` (proceeds without Alpaca check). |
| 12 | `src/shadow_trading/executor.py:697` | `except Exception as e` | `intentional_swallow` | Drawdown-halt Telegram notification failure. Notification is best-effort. |
| 13 | `src/shadow_trading/executor.py:727` | `except Exception as e` | `intentional_swallow` | Drawdown-alert Telegram notification failure. Best-effort. |
| 14 | `src/shadow_trading/executor.py:730` | `except Exception as e` | `partial_swallow` | Drawdown check failure — errors and returns None (rejecting trade). Already logs. Needs `ticker`, `operation=drawdown_check`. |
| 15 | `src/shadow_trading/executor.py:829` | `except Exception as e` | `partial_swallow` | **KEY SITE.** Bracket order submission failure (Alpaca paper). WARNING logged. Missing: `broker=alpaca_paper`, `operation=place_bracket_order`, `ticker`, `recoverable=True` (falls back to market order). Should persist to `broker_exceptions`. |
| 16 | `src/shadow_trading/executor.py:869` | `except Exception as close_err` | `partial_swallow` | Emergency close of unprotected position (SDK missing path). ERROR logged. Missing: `broker=alpaca_paper`, `operation=place_exit`, `recoverable=False`. Must persist. |
| 17 | `src/shadow_trading/executor.py:881` | `except Exception as notify_err` | `intentional_swallow` | Telegram notification for unprotected position. Best-effort. |
| 18 | `src/shadow_trading/executor.py:900` | `except Exception as stop_err` | `partial_swallow` | **KEY SITE.** Standalone stop-loss submission failed post-entry. ERROR logged. Missing: `broker=alpaca_paper`, `operation=place_stop_order`, `ticker`, `recoverable=False`. Must persist + operator alert. |
| 19 | `src/shadow_trading/executor.py:909` | `except Exception as close_err` | `partial_swallow` | Emergency close when stop-loss failed. ERROR logged. Missing: `broker=alpaca_paper`, `operation=place_exit`, `recoverable=False`. Must persist. |
| 20 | `src/shadow_trading/executor.py:918` | `except Exception as e` | `intentional_swallow` | Telegram notification for unprotected position (stop-loss path). Best-effort. |
| 21 | `src/shadow_trading/executor.py:941` | `except Exception as retry_err` | `partial_swallow` | Retry after network error also failed. ERROR logged. Missing: `broker=alpaca_paper`, `operation=place_market_order`, `ticker`. |
| 22 | `src/shadow_trading/executor.py:945` | `except Exception as check_err` | `partial_swallow` | Cannot verify Alpaca positions after network error. ERROR logged. Missing: `broker=alpaca_paper`, `operation=fetch_positions`. |
| 23 | `src/shadow_trading/executor.py:968` | `except Exception as e2` | `partial_swallow` | Unknown error on fallback market order — "code bug, not a broker issue". ERROR logged. Needs `ticker`, `operation=place_market_order`, `recoverable=False`. |
| 24 | `src/shadow_trading/executor.py:999` | `except Exception as exc` | `intentional_swallow` | Failed to count open positions for metadata. WARNING logged. Non-broker metadata enrichment. |
| 25 | `src/shadow_trading/executor.py:1009` | `except Exception as exc` | `intentional_swallow` | Failed to fetch VIX at entry. WARNING logged. Not a broker call. |
| 26 | `src/shadow_trading/executor.py:1037` | `except Exception as e` | `intentional_swallow` | IS (Information Surface) store failed. WARNING logged. Not a broker call. |
| 27 | `src/shadow_trading/executor.py:1072` | `except Exception as exc` | `intentional_swallow` | `broadcast trade_opened` failed. WARNING logged. Not a broker call. |
| 28 | `src/shadow_trading/executor.py:1099` | `except Exception as e` | `intentional_swallow` | Shadow IB logging failed (non-fatal). WARNING logged. Secondary logging, not broker. |
| 29 | `src/shadow_trading/executor.py:1117` | `except Exception as _e_to` | `intentional_swallow` | activity_log TRADE_OPENED failed. DEBUG logged. Secondary logging. |
| 30 | `src/shadow_trading/executor.py:1284` | `except Exception as e` | `partial_swallow` | **KEY SITE.** `_retry_exit` pre-check failed. WARNING logged. Missing: `broker`, `operation=fetch_order_status`, `ticker`. |
| 31 | `src/shadow_trading/executor.py:1295` | `except Exception as _e_t5` | `partial_swallow` | **KEY SITE.** Live cancel via broker factory failed. WARNING logged. Missing: `broker`, `operation=cancel_order`, `ticker`. Should persist — live order state is now uncertain. |
| 32 | `src/shadow_trading/executor.py:1314` | `except Exception as e` | `partial_swallow` | Post-cancel fill fetch failed. WARNING logged. Missing: `broker`, `operation=fetch_order_status`, `ticker`. |
| 33 | `src/shadow_trading/executor.py:1377` | `except Exception as e` | `partial_swallow` | Exit retry exception. ERROR logged + DB written. Missing: `broker`, `operation=place_exit`, `ticker`. Should persist. |
| 34 | `src/shadow_trading/executor.py:1442` | `except Exception as e` | `bug_silent_swallow` | **CRITICAL.** `get_live_broker(load_config())` or `get_all_positions()` failure swallowed at DEBUG level. This is the `get_positions()` AttributeError defect site from memory. DEBUG is too low — an entire position fetch silently skipped. Missing: `broker`, `operation=fetch_positions`, `recoverable=True`, and the log level is wrong. |
| 35 | `src/shadow_trading/executor.py:1554` | `except Exception as e` | `intentional_swallow` | MR exit attribution logging failed. WARNING logged. Secondary attribution, not broker. |
| 36 | `src/shadow_trading/executor.py:1557` | `except Exception as e` | `intentional_swallow` | MR exit check failed. DEBUG logged. Strategy check, not broker. |
| 37 | `src/shadow_trading/executor.py:1589` | `except Exception as e` | `intentional_swallow` | MR timeout attribution logging failed. WARNING logged. Secondary logging. |
| 38 | `src/shadow_trading/executor.py:1660` | `except Exception as e` | `partial_swallow` | **KEY SITE.** Bracket order status check failed (IB or Alpaca). WARNING logged. Missing: `broker`, `operation=fetch_order_status`, `ticker`. Falls back to price polling — caller-safe but info loss. |
| 39 | `src/shadow_trading/executor.py:1696` | `except Exception as cancel_err` | `partial_swallow` | Failed to cancel entry order during exit. WARNING logged. Missing: `broker`, `operation=cancel_order`, `ticker`. |
| 40 | `src/shadow_trading/executor.py:1771` | `except Exception as _fetch_err` | `partial_swallow` | Post-cancel fill fetch failed during exit. WARNING logged. Missing: `broker`, `operation=fetch_order_status`. |
| 41 | `src/shadow_trading/executor.py:1784` | `except Exception as e` | `partial_swallow` | Stale exit order cancellation failed. WARNING logged. Missing: `broker`, `operation=cancel_order`, `ticker`. |
| 42 | `src/shadow_trading/executor.py:1793` | `except Exception as e` | `partial_swallow` | **KEY SITE — exit submission failure.** Has inline comment about `#610`. Logs + DB update. Missing: `broker`, `operation=place_exit`, `ticker`. Should persist. |
| 43 | `src/shadow_trading/executor.py:1832` | `except Exception as e` | `intentional_swallow` | Exit circuit-breaker Telegram notification failed. Best-effort. |
| 44 | `src/shadow_trading/executor.py:1927` | `except Exception as exc` | `intentional_swallow` | Telegram notification for exit failed. Best-effort. |
| 45 | `src/shadow_trading/executor.py:2029` | `except Exception as e` | `intentional_swallow` | Attribution link_trade_outcome failed. DEBUG logged. Secondary attribution. |
| 46 | `src/shadow_trading/executor.py:2060` | `except Exception as e` | `intentional_swallow` | Telegram notify_trade_closed failed. WARNING logged. Best-effort notification. |
| 47 | `src/shadow_trading/executor.py:2084` | `except Exception as _tg_err` | `intentional_swallow` | Price failure Telegram alert failed. Best-effort. |
| 48 | `src/shadow_trading/executor.py:2132` | `except Exception as e` | `partial_swallow` | Live trade validation failed. ERROR logged + returns None. Missing: `broker`, `operation=validate_live_trade`. |
| 49 | `src/shadow_trading/executor.py:2218` | `except Exception as e` | `intentional_swallow` | Live capital guard Telegram alert failed. Best-effort. |
| 50 | `src/shadow_trading/executor.py:2428` | `except Exception as e` | `partial_swallow` | **KEY SITE.** Live bracket order submission failure. WARNING logged + returns None. Missing: `broker`, `operation=place_bracket_order`, `ticker`, `recoverable=False`. Should persist to `broker_exceptions`. |
| 51 | `src/shadow_trading/executor.py:2452` | `except Exception as e` | `intentional_swallow` | Live Telegram notify_trade_opened failed. Best-effort. |
| 52 | `src/trading/ib_broker.py:105` | `except Exception as e` | `partial_swallow` | IB connection attempt (one of 3 retries). WARNING logged. Missing: `broker=ib`, `operation=connect`, `recoverable=True`. Raises after all 3 fail — re-raise path exists. |
| 53 | `src/trading/ib_broker.py:380` | `except Exception as e` | `intentional_swallow` | IB price snapshot failed. DEBUG logged + returns None. Caller handles None. Not an order operation. |
| 54 | `src/shadow_trading/reconcile_dispatch.py:42` | `except Exception as e` | `partial_swallow` | Swing reconcile failed. `logger.exception` called (full traceback). Missing: `broker`, `operation=reconcile`. Does not re-raise — loop continues. |
| 55 | `src/shadow_trading/reconcile_dispatch.py:50` | `except Exception` (bare) | `partial_swallow` | `get_strategies_by_status` failed. `logger.exception` called. Not a broker call — platform DB read. |
| 56 | `src/shadow_trading/reconcile_dispatch.py:60` | `except Exception as e` | `partial_swallow` | Per-desk reconcile failed. `logger.exception` called. Missing: `broker`, `operation=reconcile`. |
| 57 | `src/services/recap_service.py:57` | `except Exception` (bare) | `bug_silent_swallow` | `get_shadow_data_for_recap()` swallowed silently with `pass`. No log at all. This is a data fetch failure — operator gets wrong/empty EOD recap with no indication. |
| 58 | `src/services/shadow_service.py:69` | `except Exception` (bare) | `bug_silent_swallow` | `get_account_info()` (Alpaca) swallowed silently with `pass`. No log. Dashboard shows `account_equity=None` with no warning. Missing: `broker=alpaca_paper`, `operation=fetch_account`. |
| 59 | `src/services/mr_scan_service.py:86` | `except Exception` (bare) | `bug_silent_swallow` | VIX DB lookup swallowed silently with `pass`. No log. Not a broker call — internal DB. |
| 60 | `src/services/mr_scan_service.py:91` | `except Exception as e` | `partial_swallow` | Post-scan enrichment failed. WARNING logged. Not a broker call. |
| 61 | `src/services/system_service.py:104` | `except Exception as e` | `intentional_swallow` | Alpaca connection check failed. DEBUG logged. Status-page probe; returns False. |
| 62 | `src/services/system_service.py:128` | `except Exception as e` | `intentional_swallow` | Kill-switch status check failed. DEBUG logged. Non-broker. |
| 63 | `src/services/system_service.py:149` | `except Exception as e` | `intentional_swallow` | Journal DB query failed. DEBUG logged. Non-broker. |
| 64 | `src/services/system_service.py:160` | `except Exception as e` | `intentional_swallow` | Training example count failed. DEBUG logged. Non-broker. |
| 65 | `src/services/system_service.py:175` | `except Exception` (bare) | `partial_swallow` | **KEY SITE.** `get_live_broker(config)` called for status page — TypeError/AttributeError from IB defect (memory item) swallowed silently with `ib_connected = False`. No log at all for Exception path (DEBUG path only existed before the bare-except). Missing: `broker`, `operation=get_live_broker`, log of what actually failed. |
| 66 | `src/services/scan_service.py:100` | `except Exception as e` | `partial_swallow` | Data enrichment failed. WARNING logged. Not a broker call. |
| 67 | `src/services/scan_service.py:136` | `except Exception as exc` | `intentional_swallow` | Event-risk Telegram alert failed. Best-effort. |
| 68 | `src/services/scan_service.py:138` | `except Exception as e` | `partial_swallow` | Feature enrichment failed. WARNING logged. Not a broker call. |
| 69 | `src/services/scan_service.py:160` | `except Exception as e` | `partial_swallow` | Data integrity check failed. WARNING logged. Not a broker call. |
| 70 | `src/services/scan_service.py:205` | `except Exception as e` | `intentional_swallow` | Attribution Phase 1 failed. DEBUG logged. Not a broker call. |
| 71 | `src/services/scan_service.py:264` | `except Exception as e` | `intentional_swallow` | Attribution Phase 2 failed. DEBUG logged. Not a broker call. |
| 72 | `src/services/scan_service.py:292` | `except Exception` (bare) | `intentional_swallow` | Concurrent position count for notification failed. Silently sets `_concurrent=None`. Not a broker call. |
| 73 | `src/services/scan_service.py:305` | `except Exception as _tg_err` | `intentional_swallow` | `notify_trade_opened` Telegram failed. Best-effort. |
| 74 | `src/services/scan_service.py:329` | `except Exception as exc` | `intentional_swallow` | Ticker event-risk Telegram alert failed. Best-effort. |

### Summary by category

| Category | Count |
|----------|-------|
| `bug_silent_swallow` | 4 |
| `intentional_swallow` | 34 |
| `partial_swallow` | 36 |
| **Total** | **74** |

The 4 `bug_silent_swallow` sites are the highest priority:

1. `executor.py:1442` — positions fetch failure logged at DEBUG (wrong level + missing broker context) — the `get_positions()` AttributeError defect from memory lands here
2. `recap_service.py:57` — completely silent `pass` on shadow data fetch failure
3. `shadow_service.py:69` — completely silent `pass` on Alpaca account info fetch
4. `system_service.py:175` — bare `except` on `get_live_broker()` — the `get_live_broker()` TypeError defect from memory lands here; zero logging

**Note on count:** 74 total sites were found. The `>40 = over-counting` guideline in the spec was set for direct broker-call sites only. When all exception handlers in the three target directories are inventoried (including notifications, attribution, DB enrichment), 74 is accurate. The **broker-operation-relevant subset** (candidates for `broker_exceptions` persistence) is **15 sites** (items 3, 5, 11, 15, 16, 18, 19, 21, 22, 31, 33, 34, 38, 42, 50, plus the IB connect retry at 52). This is well within the expected range and does not warrant splitting B2.

---

## 2. Schema Design — `broker_exceptions` Table

### Naming rationale

Name: `broker_exceptions`. No prefix. Rationale:

- `t2_` or `obs_` prefixes belong to Track 2 observability work; using them here would create a naming collision if Track 2 observability tables appear later with the same prefix.
- `broker_exceptions` is self-describing, matches the operation context, and is not ambiguous with any existing table in the registry.

### Column definitions

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | INTEGER | NOT NULL | Primary key, AUTOINCREMENT |
| `ticker` | TEXT | NOT NULL | Stock symbol involved in the operation |
| `operation` | TEXT | NOT NULL | Enum-like string: `place_bracket_order`, `place_market_order`, `place_stop_order`, `place_exit`, `cancel_order`, `fetch_positions`, `fetch_account`, `fetch_buying_power`, `fetch_order_status`, `connect`, `reconcile` |
| `broker` | TEXT | NOT NULL | `alpaca_paper`, `alpaca_live`, `ib` |
| `timestamp` | TEXT | NOT NULL | ISO-8601 datetime when the exception occurred |
| `exception_class` | TEXT | NOT NULL | `type(exc).__name__` — e.g., `ConnectionError`, `AttributeError`, `LiveTradingError` |
| `exception_message` | TEXT | NOT NULL | `str(exc)` — truncated to 1000 chars |
| `traceback` | TEXT | NULL | `traceback.format_exc()` — may be NULL for intentional-swallow upgrades |
| `recoverable` | INTEGER | NOT NULL | Boolean (0/1). True = caller has a fallback path. False = trade state is uncertain or halted. |
| `created_at` | TEXT | NOT NULL | Row insert time (may differ from timestamp by milliseconds) |
| `correlation_id` | TEXT | NULL | `shadow_trades.trade_id` when the exception is tied to a specific trade |
| `retry_count` | INTEGER | NULL | Number of retries attempted before this exception was recorded |
| `outcome` | TEXT | NULL | `raised` (exception re-raised to caller), `persisted` (swallowed after logging), `caller_handled` (caller had an explicit recovery path) |

### Index strategy

```sql
CREATE INDEX idx_broker_exceptions_broker_ts
    ON broker_exceptions (broker, timestamp DESC);
```

Rationale: The primary query pattern is "show me recent exceptions for a given broker" (dashboard, operator triage). A composite index on `(broker, timestamp DESC)` satisfies this. A secondary index on `ticker` is deferred — it can be added when dashboard filtering by ticker is requested.

### Registry entry (Pass 2 will add)

```python
TableDef(
    name="broker_exceptions",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False, autoincrement=True),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("operation", "TEXT", nullable=False),
        ColumnDef("broker", "TEXT", nullable=False),
        ColumnDef("timestamp", "TEXT", nullable=False),
        ColumnDef("exception_class", "TEXT", nullable=False),
        ColumnDef("exception_message", "TEXT", nullable=False),
        ColumnDef("traceback", "TEXT", nullable=True),
        ColumnDef("recoverable", "INTEGER", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("correlation_id", "TEXT", nullable=True,
                  description="FK to shadow_trades.trade_id when applicable"),
        ColumnDef("retry_count", "INTEGER", nullable=True),
        ColumnDef("outcome", "TEXT", nullable=True,
                  description="raised | persisted | caller_handled"),
    ],
    indexes=[
        IndexDef("idx_broker_exceptions_broker_ts",
                 ["broker", "timestamp"], unique=False),
    ],
    description="Structured log of broker exceptions for operator triage and alerting.",
)
```

---

## 3. Logging Contract (Pass 2 Implements)

### Standard log line

For every non-intentional swallow site being upgraded, Pass 2 emits:

```python
logger.error(
    "[BROKER_EXCEPTION] %s op=%s broker=%s recoverable=%s",
    ticker, operation, broker, recoverable,
    exc_info=True,
)
```

`exc_info=True` attaches the full traceback to the log record without a separate `traceback.format_exc()` call.

### Default policy: persist + re-raise (loud failure surface)

Unless stated otherwise in the per-site table below, the policy is:

1. Log the structured line above.
2. Insert a row into `broker_exceptions`.
3. Re-raise the exception to the caller (preserving existing `raise` semantics).

### Per-site decisions

| Site | Operation | Broker | Recoverable | Action | Rationale |
|------|-----------|--------|-------------|--------|-----------|
| `executor.py:236` | `fetch_buying_power` | `alpaca_paper` or `alpaca_live` | False | persist + re-raise | Fail-closed gate; caller already handles re-raise. |
| `executor.py:271` | `fetch_buying_power` | `alpaca_paper` | False | persist + re-raise | Same as above. |
| `executor.py:427` | `connect` | `ib` | True | log only, no persist | IB unreachable is expected during weekend/reset; persisting every retry would flood the table. The warning log is sufficient. |
| `executor.py:634` | `fetch_positions` | `alpaca_paper` | True | persist (no re-raise) | Caller proceeds with DB-only check — semantics intentional. Persist so operator sees the frequency. |
| `executor.py:829` | `place_bracket_order` | `alpaca_paper` | True | persist + log | Bracket failed but caller falls back to market order. Re-raising would skip the fallback. Persist + keep warning. |
| `executor.py:869` | `place_exit` | `alpaca_paper` | False | persist + re-raise | Emergency close failed — position is now exposed. Operator must see this immediately. |
| `executor.py:900` | `place_stop_order` | `alpaca_paper` | False | persist + re-raise | Stop placement failed post-entry — critical. Already triggers emergency-close path. |
| `executor.py:909` | `place_exit` | `alpaca_paper` | False | persist + log | Emergency-close-of-unprotected failed. Cannot re-raise here without disrupting the Telegram notify attempt. Persist. |
| `executor.py:941` | `place_market_order` | `alpaca_paper` | False | persist + log | Retry failed. Caller already sets `status=failed`. |
| `executor.py:945` | `fetch_positions` | `alpaca_paper` | False | persist + log | Cannot verify Alpaca. Caller sets `submission_uncertain`. |
| `executor.py:968` | `place_market_order` | `alpaca_paper` | False | persist + log | Unknown/code-bug path. |
| `executor.py:1295` | `cancel_order` | `alpaca_live` or `ib` | False | persist + log | Live cancel failed — order state uncertain. Operator must triage. |
| `executor.py:1314` | `fetch_order_status` | `alpaca_paper` | True | log only | Post-cancel fill check; caller handles None. |
| `executor.py:1377` | `place_exit` | `alpaca_paper` or `alpaca_live` | False | persist + log | Exit retry failed; DB already updated to `exit_failed`. |
| `executor.py:1442` | `fetch_positions` | `alpaca_paper` or `alpaca_live` | True | persist + log (upgrade DEBUG→WARNING) | **Bug site.** Log level must be raised to WARNING. Persist so operator can track frequency. |
| `executor.py:1660` | `fetch_order_status` | `alpaca_paper` or `ib` | True | log only | Falls back to price polling. |
| `executor.py:1793` | `place_exit` | `alpaca_paper` or `alpaca_live` | False | persist + log | Exit submission failed; `exit_retry_count` already bumped per `#610`. |
| `executor.py:2132` | `validate_live_trade` | `n/a` | False | log only | Not a broker call. Upgrading log to include ticker is sufficient. |
| `executor.py:2428` | `place_bracket_order` | `alpaca_live` or `ib` | False | persist + re-raise | Live order failed — return None is the existing semantics but we must persist first. Change: persist then return None (not technically re-raise, but side-effect of persist is correct). |
| `system_service.py:175` | `get_live_broker` | config-driven | True | log (WARNING) | Status page probe. Bare `except` must get a log line. Not a trade operation — do NOT persist. |
| `shadow_service.py:69` | `fetch_account` | `alpaca_paper` | True | log (WARNING) | Dashboard probe. Not a trade operation — do NOT persist to `broker_exceptions`. |
| `recap_service.py:57` | `fetch_shadow_data` | n/a | True | log (WARNING) | EOD recap. Not a direct broker call. Do NOT persist. |
| `ib_broker.py:105` | `connect` | `ib` | True | log only | Already warns per-attempt. After 3 failures raises `ConnectionError` — the outer caller (executor or broker_factory) should persist when it catches that. No inner persist needed. |

---

## 4. Test Strategy

**Test file:** `tests/shadow_trading/test_broker_exception_logging.py` (NEW in Pass 2)

### Design principles

- All tests use `unittest.mock.patch` — no live broker calls.
- Each test follows the pattern: synthetic exception raised → caught by the site under test → assert log line emitted with structured fields → assert DB row inserted (for persist sites) OR exception re-raised (for re-raise sites).
- Do NOT attempt to enumerate all 74 sites. Pick one test per (broker × operation) combination at the surface.

### Recommended test cases

| Test name | What it covers |
|-----------|---------------|
| `test_fetch_positions_alpaca_paper_logs_and_persists` | `executor.py:1442` — `get_all_positions()` raises AttributeError; assert WARNING log with broker/operation/recoverable fields; assert `broker_exceptions` row inserted |
| `test_place_bracket_alpaca_paper_logs_and_persists` | `executor.py:829` — `place_bracket_order` raises; assert broker_exceptions row with `operation=place_bracket_order, broker=alpaca_paper, recoverable=1`; assert fallback to market order path continues |
| `test_place_exit_alpaca_live_logs_and_persists` | `executor.py:1793` — exit submission fails on live; assert broker_exceptions row with `recoverable=0` |
| `test_live_order_submission_failure_persists` | `executor.py:2428` — `place_bracket_order` on live path raises; assert row persisted before returning None |
| `test_get_live_broker_type_error_logs` | `system_service.py:175` — `get_live_broker(config)` raises TypeError (the memory defect); assert WARNING log emitted; assert NO persist to `broker_exceptions` (status-page probe) |
| `test_fetch_buying_power_alpaca_persists_and_reraises` | `executor.py:236` — buying power check raises; assert persist + re-raise |
| `test_ib_connect_retry_warns` | `ib_broker.py:105` — first two connect attempts raise; third raises ConnectionError; assert WARNING per attempt; assert outer ConnectionError surfaces to caller |
| `test_stop_loss_placement_failure_persists` | `executor.py:900` — standalone stop placement fails post-entry; assert persist with `recoverable=0`; assert emergency-close path triggered |
| `test_get_live_broker_without_config_logs_not_raises` | `get_live_broker()` called with empty config dict → TypeError (memory defect #1); assert WARNING with `exception_class` in log; confirm no unhandled exception to caller |

### Specific case per spec: `get_live_broker()` without config

```python
def test_get_live_broker_without_config_logs_recoverable_false():
    """get_live_broker() called without broker config → TypeError logged
    with recoverable=False, exception_class present."""
    with patch("src.trading.broker_factory.get_live_broker",
               side_effect=TypeError("'NoneType' is not subscriptable")):
        with patch("src.services.system_service.logger") as mock_log:
            result = get_system_status()
    # Status page returns ib_connected=False, does not raise
    assert result["ib_connected"] is False
    # WARNING was emitted (not silently swallowed)
    mock_log.warning.assert_called_once()
    call_args = str(mock_log.warning.call_args)
    assert "get_live_broker" in call_args or "BROKER_EXCEPTION" in call_args
```

---

## 5. Scope Fence Verification

### Files Pass 2 will touch

| File | Change type | In sprint scope? |
|------|-------------|-----------------|
| `src/schema/registry.py` | Add `broker_exceptions` TableDef | Yes — schema file |
| `src/shadow_trading/executor.py` | Upgrade ~15 partial-swallow and bug-silent-swallow sites | Yes — in `src/shadow_trading/` |
| `src/shadow_trading/alpaca_adapter.py` | Possibly add a `_persist_broker_exception()` helper if chosen | Yes — in `src/shadow_trading/` |
| `src/services/system_service.py` | Add WARNING log to bare-except at line 175 | Yes — in `src/services/` |
| `src/services/shadow_service.py` | Add WARNING log to bare-except at line 69 | Yes — in `src/services/` |
| `src/services/recap_service.py` | Add WARNING log to bare-except at line 57 | Yes — in `src/services/` |
| `src/trading/ib_broker.py` | No changes needed (log-only sites already adequate; outer callers will persist) | Yes — in scope (read only) |
| `tests/shadow_trading/test_broker_exception_logging.py` | New test file | Yes — test directory |

**Total: 7 files modified + 1 new test file = 8 files.** The registry is 1 of those. Pass 2 touches 4 files within `src/shadow_trading/` and `src/services/` (executor, adapter, system_service, shadow_service, recap_service) plus registry plus 1 test file.

**Verdict: No escalation required.** All touched files are within the sprint scope or the schema registry (expected per spec).

### Helper design decision

Pass 2 should add a single `_persist_broker_exception(...)` helper. The function signature:

```python
def _persist_broker_exception(
    ticker: str,
    operation: str,
    broker: str,
    exc: Exception,
    recoverable: bool,
    db_path: str = DB_PATH,
    correlation_id: str | None = None,
    retry_count: int | None = None,
    outcome: str = "persisted",
) -> None:
```

This avoids duplicating the INSERT at every call site. The helper should be in `src/shadow_trading/executor.py` (not alpaca_adapter — the adapter has no DB access). The helper should never raise — if the INSERT fails, it logs and returns silently (we do not want an exception-logger that throws exceptions).

---

## 6. Risks and Unknowns

### R1 — Re-raise would break watch-loop resilience at executor.py:829

**Site:** Bracket order failure fallback at line 829.
**Risk:** This except block is the fallback to market order. If we re-raise here, the fallback never executes, and the trade is abandoned entirely rather than placed as a market order with a standalone stop. The existing behavior (warn + continue to market fallback) is deliberate resilience, not a bug.
**Resolution:** For this site, Pass 2 persists to `broker_exceptions` but does NOT re-raise. The fallback must remain intact.

### R2 — `executor.py:1442` DEBUG level is the memory defect surface point

**Site:** `except Exception as e: logger.debug(...)` in `check_and_manage_open_trades`.
**Risk:** This is where the `get_positions()` AttributeError (memory defect) is swallowed silently. The entire position list for a scan cycle is dropped. If positions cannot be fetched, open trades are managed without broker position context — which affects the ghost-position detection logic at line 1664.
**Resolution:** Pass 2 upgrades this to WARNING, adds structured fields, and persists. Does NOT fix the underlying AttributeError — that is a separate sprint per the spec.
**Operator judgment needed:** Should a positions-fetch failure cause the entire `check_and_manage_open_trades` call to halt (fail-closed) or continue without broker positions (current behavior)? The current behavior allows exits to proceed via price-polling even when broker positions are unavailable. This is probably correct for resilience but means the ghost-position alarm at line 1664 is silenced for the whole cycle. Recommend operator decides before Pass 2 implements.

### R3 — `system_service.py:175` bare except swallows the `get_live_broker()` TypeError

**Site:** IB connection status check on the status page.
**Risk:** The `get_live_broker()` TypeError (memory defect — called without IB config present) is swallowed completely with no log. The status page silently reports `ib_connected: false` with no diagnostic. Operator cannot distinguish "IB gateway not running" from "code crash in broker factory".
**Resolution:** Pass 2 adds a WARNING log. No persist — status-page probes should not pollute `broker_exceptions` with routine checks.

### R4 — `shadow_service.py:69` silent swallow hides Alpaca outage

**Site:** Dashboard account info fetch.
**Risk:** If Alpaca paper API is down, the dashboard shows `account_equity: null` with no indication. During a Alpaca API degradation event, an operator would not know whether the null is expected (no account configured) or an outage.
**Resolution:** Pass 2 adds a WARNING log. No persist — this is a display probe, not a trade operation.

### R5 — Volume of `partial_swallow` sites in executor.py (36 sites)

If all 36 partial-swallow sites in executor.py are upgraded in a single commit, the diff will be large and review risk increases. Consider splitting Pass 2 into:
- Pass 2A: The 4 `bug_silent_swallow` sites (highest urgency, smallest diff)
- Pass 2B: The broker-operation-relevant `partial_swallow` sites (15 sites with persist)
- Pass 2C: The remaining non-broker `partial_swallow` upgrades (log-line field additions only)

This is not an escalation — the scope is within bounds — but it would reduce review risk. PM should decide at Pass 2 dispatch.

### R6 — `alpaca_adapter.py` `is_connected()` double-swallow

**Site:** `alpaca_adapter.py:266` and `:271` (both tagged `except Exception as exc: # noqa: BLE001`).
These are already annotated as intentional broad catches (`BLE001` noqa). They return `False` to the caller who uses them for a boolean liveness check. These are NOT in the silent-swallow inventory because they already log at WARNING level. They are included here as a risk note: if the `alpaca_adapter.is_connected()` calls are used as a governor input surface (they are per the T2.17 section in alpaca_adapter.py), a silent False return means the governor treats Alpaca as connected when it is not. This appears to be intentional post-T2.17 design — the governor uses `get_account_equity()` not `is_connected()` for fail-closed decisions. No action needed.

---

## Appendix A — IB Defect Sites from Memory

The pre-flight context named 4 known IB runtime defects. Their mapping to swallow inventory:

| Memory defect | Site in inventory | Classification | Pass 2 action |
|---------------|------------------|----------------|---------------|
| `get_live_broker()` TypeError | `system_service.py:175` (#65) | `bug_silent_swallow` | Add WARNING log |
| `get_positions()` AttributeError | `executor.py:1442` (#34) | `bug_silent_swallow` | Upgrade to WARNING + persist |
| Child order ID drop | `executor.py:829` (#15) — when IB broker path → `place_bracket_order` raises | `partial_swallow` | Persist; the underlying bug (child IDs not returned) is out of scope |
| Alpaca-only exit monitoring | Not a swallow site — architectural gap in the watch loop, not an exception handler. No entry in inventory. | n/a | Pass 2 out of scope; flag for separate ticket |

---

## Appendix B — `broker_exceptions` Operation Enum

Valid values for the `operation` column:

```
place_bracket_order
place_market_order
place_stop_order
place_limit_order
place_exit
cancel_order
cancel_all_orders
fetch_positions
fetch_account
fetch_buying_power
fetch_order_status
connect
reconnect
reconcile
validate_live_trade
get_live_broker
```
