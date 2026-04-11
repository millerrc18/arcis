# IB Integration: Success Criteria — All 7 Sprints

**Every sprint must pass ALL criteria before merging. No partial credit.**

---

## IB-1: Tests + Shadow Mode

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | ≥24 new IBBroker unit tests passing | `pytest tests/test_ib_broker.py -v` shows 24+ passed |
| 2 | All tests run WITHOUT ib_async installed | No `skipif` guards — pure mocks |
| 3 | ≥6 shadow logger tests passing | `pytest tests/test_ib_shadow.py -v` shows 6+ passed |
| 4 | Shadow mode logs to `ib_shadow_log` table | Test verifies DB row insertion |
| 5 | Shadow mode NEVER calls `placeOrder()` | Dedicated test: `test_never_calls_place_order` |
| 6 | Shadow mode never blocks Alpaca execution | All shadow calls wrapped in try/except |
| 7 | `ib_broker.py` is UNCHANGED | `git diff src/trading/ib_broker.py` is empty |
| 8 | All existing tests still pass | `pytest tests/ -x -q --ignore=tests/test_ingestion.py` |
| 9 | No file exceeds 400 lines | `wc -l` check on all new/modified files |

---

## IB-2: Critical Structural Fixes

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | `get_live_broker()` called with config (not bare) | `grep "get_live_broker(load_config())" src/shadow_trading/executor.py` |
| 2 | `get_all_positions()` replaces `get_positions()` | `grep -c "get_positions()" src/shadow_trading/executor.py` returns 0 |
| 3 | IB bracket orders return child order IDs | Test: `test_bracket_order_returns_child_ids` passes |
| 4 | `BrokerOrder` dataclass has `child_order_ids` field | `grep "child_order_ids" src/trading/broker_interface.py` |
| 5 | `ib_child_order_ids` column exists in shadow_trades schema | `grep "ib_child_order_ids" src/schema/registry.py` |
| 6 | Live bracket exit monitoring uses broker factory | Test: `test_live_bracket_exit_uses_broker_factory` passes |
| 7 | IB child order fills detected | Test: `test_ib_child_order_fill_detected` passes |
| 8 | `_retry_exit` uses broker-aware cancel for live trades | Test: `test_retry_exit_cancels_via_broker_for_live` passes |
| 9 | Risk governor uses IB equity when broker is IB | Test: `test_equity_from_ib_when_live_ib` passes |
| 10 | Reconciler cancel is broker-aware | Test: `test_reconciler_cancels_ib_orders` passes |
| 11 | `get_position()` returns real current_price (not 0.0) | Test: `test_get_position_fetches_current_price` passes |
| 12 | Startup checks for ib_async when IB configured | `grep "ib_async" src/startup_checks.py` |
| 13 | `broker_order_id` alias column in schema | `grep "broker_order_id" src/schema/registry.py` |
| 14 | All existing tests still pass | Full test suite green |
| 15 | No Alpaca paper trading regression | Alpaca lifecycle test passes unchanged |

---

## IB-3: Shadow Dashboard

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | `ib_shadow_log` syncs to Postgres | `grep "sync_to_postgres.*True" src/schema/registry.py` near ib_shadow_log |
| 2 | `/api/ib-shadow/summary` returns valid JSON | `curl` test or API import check |
| 3 | `/api/ib-shadow/log` returns paginated entries | Endpoint accepts `?limit=` parameter |
| 4 | `/api/ib-shadow/health` returns shadow mode status | Response includes `shadow_mode_enabled` field |
| 5 | IB Shadow page renders without errors | `cd frontend && npm run build` succeeds |
| 6 | IB Shadow page shows empty state when no data | Visual check or component test |
| 7 | Nav menu includes IB Shadow link | `grep "ib-shadow" frontend/src/components/Layout.jsx` |
| 8 | Route registered in App.jsx | `grep "ib-shadow" frontend/src/App.jsx` |
| 9 | API methods added to api.js | `grep "IBShadow" frontend/src/api.js` |

---

## IB-4: Dual-Execution Routing

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Trades with score ≥ threshold route to IB when connected | Integration test with mock IB |
| 2 | Trades with score < threshold route to Alpaca | Integration test |
| 3 | IB Gateway down → automatic Alpaca fallback | Fallback test with connection failure mock |
| 4 | Fallback logs warning with ticker and reason | Log output verified |
| 5 | `broker` column populated on every new shadow_trade | No NULL values in broker column for new trades |
| 6 | Existing trades default to `broker='alpaca'` | `SELECT COUNT(*) FROM shadow_trades WHERE broker IS NULL` returns 0 |
| 7 | Reconciler checks correct broker per trade | IB trades → IB positions, Alpaca trades → Alpaca positions |
| 8 | Risk governor counts positions across BOTH brokers | 3 IB + 4 Alpaca = 7 in max_positions check |
| 9 | Bracket monitor checks both brokers | `check_bracket_health()` covers IB and Alpaca trades |
| 10 | Routing threshold configurable via YAML | `paper_routing_threshold` read from config |
| 11 | Live trade routing unchanged | Live path still uses broker factory as before |
| 12 | All existing tests pass | Full suite green |

---

## IB-5: Production Hardening

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Gateway reconnect with exponential backoff (3 retries) | Test: `test_reconnect_with_backoff` |
| 2 | Bracket integrity verified after reconnect | Test: `test_reconnect_verifies_brackets` |
| 3 | Partial fills handled (quantity updated, logged) | Test: `test_partial_fill_updates_quantity` |
| 4 | IB error codes mapped to specific handling | Test: `test_error_code_201_rejected` |
| 5 | All IB order statuses map to normalized statuses | Test: `test_status_mapping_all_values` |
| 6 | Market data lines tracked (≤100 limit) | Test: `test_market_data_line_tracking` |
| 7 | `outsideRth=False` on ALL order types | Test: `test_outside_rth_false` |
| 8 | Account summary timeout → retry | Test: `test_account_summary_timeout_retry` |
| 9 | OCA group integrity after reconnect | Test: `test_oca_integrity_after_reconnect` |
| 10 | Duplicate order prevention before entry | Test: `test_duplicate_order_prevention` |
| 11 | Graceful disconnect on shutdown | Test: `test_graceful_disconnect_on_shutdown` |
| 12 | No `time.sleep()` in any connected IB method | `grep -n "time.sleep" src/trading/ib_broker.py` returns only `_ensure_connected` (pre-connect) |
| 13 | All existing tests pass | Full suite green |

---

## IB-6: Paper Trading Activation

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Gateway validation script detects paper vs live account | Test: `test_validate_gateway_paper_account` |
| 2 | Validation script checks contract qualification | 10+ S&P 100 tickers validated |
| 3 | Validation script checks buying power > $0 | Reported in validation output |
| 4 | Gateway disconnect alert fires via Telegram | Test: `test_gateway_restart_alert_sent` |
| 5 | Gateway reconnect alert fires via Telegram | Paired with disconnect alert |
| 6 | 30-day stability tracking records daily uptime | Test: `test_stability_tracking_records_uptime` |
| 7 | Stability gate criteria defined and configurable | Config: min 95% uptime, <5 reconnects/day |
| 8 | IB Gateway setup guide complete | `docs/operations/ib-gateway-setup.md` exists, covers install → config → troubleshooting |
| 9 | EOD digest includes IB health section | IB trades, errors, uptime in email |
| 10 | Health page shows IB Gateway status | Dashboard card visible |

---

## IB-7: Integration Validation

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Full IB trade lifecycle test passes | `test_full_ib_paper_trade_lifecycle` — entry → monitor → exit → P&L |
| 2 | Full Alpaca trade lifecycle unchanged | `test_full_alpaca_paper_trade_lifecycle_unchanged` — zero regression |
| 3 | Governor + reconciler + executor agree on position counts | `test_governor_counts_both_brokers` + cross-component tests |
| 4 | Config progression works: shadow → routing → live | 5 config matrix tests pass |
| 5 | IB failure → Alpaca fallback → IB recovery → clean state | `test_ib_down_mid_session_falls_back` + recovery test |
| 6 | Mixed-broker session works (IB + Alpaca trades coexist) | `test_mixed_broker_trades_in_same_session` |
| 7 | Validation script reports all green | `python scripts/validate_ib_integration.py` — no ❌ |
| 8 | API responses include broker field and aggregate correctly | 4 API validation tests pass |
| 9 | **Manual smoke test passes on Ryan's machine** | `docs/operations/ib-smoke-test.md` — all checkboxes ✅ |
| 10 | **Zero open issues related to IB** | GitHub issues search returns 0 IB-related open issues |

---

## Overall IB Integration Gate

**IB paper trading is approved for production when ALL of the following are true:**

- [ ] All 7 sprints merged
- [ ] All automated tests pass (total IB test count: ~100)
- [ ] Validation script reports all green
- [ ] Manual smoke test passes
- [ ] IB Gateway stable for 7 consecutive days
- [ ] Zero IB-related GitHub issues open
- [ ] MASTER.md updated with IB status
- [ ] Strategy Decision #25 validation criteria met (60+ trades, Sharpe >1.0 — evaluated separately from IB integration)
