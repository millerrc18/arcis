# Issue Log

## 2026-03-30 — Dashboard missing manual collect-data trigger
- **Issue:** The dashboard Actions row had no button wired to the `/actions/collect-data` endpoint, so operators could not trigger data collection from the UI.
- **Impact:** Operators had to leave the dashboard and run CLI/manual workflows for an otherwise standard action.
- **Fix:** Added `api.triggerCollectData` and wired a dashboard action mutation/button with existing cloud-mode toast/error behavior.
- **Evidence:** `frontend/src/api.js` now exports `triggerCollectData`; `frontend/src/pages/Dashboard.jsx` now includes a `Collect Data` action button.

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

## 2026-03-30 — Data collection parity gap between scheduler vs API/CLI
- **Issue:** `watch.py::_run_data_collection` ran 12+ collectors (including EDGAR, insider, short-interest gating, Fed comms, analyst estimates), while API action and CLI `collect-data` only ran a subset.
- **Impact:** Dashboard/manual operations missed key datasets and could falsely appear healthy when only early collectors succeeded.
- **Fix:** Updated API action + CLI command to mirror scheduler collector coverage, including earnings + date-gated short interest behavior.
- **Evidence:** `python -m compileall src/api/routes/actions.py src/cli/commands.py`
