# Issue Log

## 2026-03-30 — Data collection stats schema drift between local and cloud APIs
- **Issue:** Local `/api/data-collection-stats` had uneven per-table payload shapes and omitted newer collector tables, while cloud API lacked the endpoint.
- **Impact:** Frontend needed environment-specific branching and could not reliably display full overnight collector coverage.
- **Fix:** Standardized table stat shape (`total_records`, `latest_collection`, `coverage_count`), expanded local coverage to newer collector tables + earnings calendar, and added cloud endpoint with equivalent Postgres coverage and graceful zero-shape fallback.
- **Evidence:** `pytest tests/test_local_api_routes.py tests/test_cloud_app.py -k "data_collection_stats"` passes with shape assertions for both environments.

## 2026-03-30 — Critical observability gap for non-trading + Telegram disabled states
- **Issue:** Operators could see `shadow-status` output `No open trades` even when paper trading was globally disabled, which can mask misconfiguration during incident triage.
- **Impact:** False assumption that trading loop is active; delayed diagnosis for missing trade execution and missing notifications.
- **Fix:** `shadow-status` now explicitly reports when `shadow_trading.enabled` is false and points to `settings.local.yaml`.
- **Evidence:** `python -m src.main shadow-status` now prints disabled-state guidance when config is disabled.

## 2026-03-30 — Startup readiness blockers for trading + notifications
- **Issue:** Runtime verification shows the system is still using `config/settings.example.yaml`, leaving trading and notifications disabled with placeholder credentials.
- **Impact:** As of Monday, March 30, 2026, the environment cannot execute live trades, cannot execute paper trades, and cannot send Telegram/email alerts.
- **Evidence:**
  - `python -m src.main preflight` → Source: `example`, Shadow: `Disabled`, Live: `Disabled`, Telegram: `FAIL`, Alpaca: `FAIL`
  - `python -m src.main shadow-account` → unauthorized from Alpaca
  - `python -m src.main send-test-email` → network/auth failure in this environment
  - `python -m src.main send-test-telegram` → telegram not configured
