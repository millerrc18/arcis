# Startup Readiness Verification — 2026-03-30

## Scope
Critical minimum checks requested before restart:
1. Live trade path on Alpaca
2. Paper trade path on Alpaca
3. Email + Telegram notification readiness

## Runtime checks (this environment)

### 1) Global preflight
- Command: `python -m src.main preflight`
- Result: **NOT READY**
- Key output:
  - Config source: `example`
  - Alpaca: `FAIL`
  - Shadow: `Disabled`
  - Live: `Disabled`
  - Telegram: `FAIL`

### 2) Live trading CLI status
- Command: `python -m src.main live-status`
- Result: **NOT READY** (`live_trading.enabled` is false)

### 3) Paper trading CLI status
- Command: `python -m src.main shadow-status`
- Result: **NOT READY** (`shadow_trading.enabled` is false)

### 4) Alpaca paper account probe
- Command: `python -m src.main shadow-account`
- Result: **NOT READY** (Alpaca unauthorized)

### 5) Email notification probe
- Command: `python -m src.main send-test-email`
- Result: **NOT READY** in this environment (delivery failure)

### 6) Telegram notification probe
- Command: `python -m src.main send-test-telegram`
- Result: **NOT READY** (`telegram.enabled` false + placeholder credentials)

## Unit-level module smoke checks (code-path confidence)

### Live/paper/Telegram execution paths
- Command:
  `PYTHONPATH=. pytest -q \
  tests/test_live_trading.py::TestLiveCLICommands::test_live_status_disabled \
  tests/test_live_trading.py::TestPaperSourceTagging::test_paper_trade_tagged_as_paper \
  tests/test_live_trading.py::TestTelegramSourceParameter::test_paper_trade_header \
  tests/test_live_trading.py::TestLiveAdapter::test_live_trading_client_uses_paper_false`
- Result: **PASS** (4 passed)

### Notification formatting + validation alert path
- Command:
  `PYTHONPATH=. pytest -q \
  tests/test_expanded_notifications.py::TestPremarketBrief::test_basic_format \
  tests/test_expanded_notifications.py::TestEodReport::test_basic_format \
  tests/test_system_validator.py::TestNotifyValidationSummary::test_sends_on_failures`
- Result: **PASS** (3 passed)

## Required remediation before market-open restart
1. Create `config/settings.local.yaml` (do not use example file in production runtime).
2. Set valid Alpaca paper credentials and verify `shadow-account` succeeds.
3. Set `shadow_trading.enabled: true` for paper trading.
4. If live trading is intended today, set valid live keys and `live_trading.enabled: true`.
5. Set valid SMTP credentials and pass `send-test-email`.
6. Set valid Telegram bot token/chat ID and pass `send-test-telegram`.
7. Re-run `preflight`; require all critical rows green before scheduler start.

## Final verdict (this environment)
- **Live trading:** NOT READY
- **Paper trading:** NOT READY
- **Email notifications:** NOT READY
- **Telegram notifications:** NOT READY
