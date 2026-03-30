# Improvement Log

<<<<<<< codex/extend-data-collection-queries-and-api
## 2026-03-30 — Unified local/cloud data collection stats contract
- **Improvement:** Added consistent data collection stats contract in both environments with coverage for options, volatility, macro, trends, CBOE, earnings, EDGAR, insider, short interest, Fed communications, and analyst collectors.
- **Why it matters:** Dashboard can render the same schema in local and cloud without branching and now includes newer collector visibility.
- **Evidence:** `pytest tests/test_local_api_routes.py tests/test_cloud_app.py -k "data_collection_stats"` validates endpoint presence and schema consistency.
=======
## 2026-03-30 — Added Dashboard “Collect Data” action endpoint wiring
- **Improvement:** Added `triggerCollectData` in the frontend API client and wired a Dashboard action mutation/button with consistent loading, success toast, cloud-mode message handling, and error toast behavior.
- **Why it matters:** Operators can trigger data collection directly from the Dashboard without changing workflows, while preserving cloud read-only behavior messaging.
- **Evidence:** `frontend/src/api.js`, `frontend/src/pages/Dashboard.jsx`, plus UI checks via `npm --prefix frontend run build` and `bin/ui-screenshots` (see command results).
>>>>>>> main

## 2026-03-30 — Preflight now checks Telegram/live/kill-switch and config source
- **Improvement:** Expanded preflight diagnostics to include:
  - config source (`local` vs `example`)
  - Telegram configuration health
  - live-trading enabled status
  - kill-switch (`data/trading_halted`) status
- **Why it matters:** Critical incident triage now surfaces the exact reasons for no trades/no alerts in one command.
- **Evidence:** `python -m src.main preflight` output includes `Source`, `Telegram`, `Live`, and `Halt` rows.

## 2026-03-30 — Added startup readiness verification report
- **Improvement:** Added a single quality report documenting pass/fail status for:
  - live Alpaca readiness
  - paper Alpaca readiness
  - email notifications
  - Telegram notifications
  - targeted unit-level smoke coverage for live/paper/notification modules
- **Why it matters:** Gives operators an explicit go/no-go checklist before restarting market automation.
- **Evidence:** `docs/quality/startup_readiness_2026-03-30.md` + command outputs listed in this run.

## 2026-03-30 — Structured per-collector results for dashboard partial-failure visibility
- **Improvement:** `src/api/routes/actions.py::_run_collect_data` now returns/broadcasts collector-level result objects (`results`, failed collector list/count), rather than only options contract/ticker totals.
- **Why it matters:** Dashboard can now render partial failures by collector while preserving successful collector outputs in the same run.
- **Evidence:** `python -m compileall src/api/routes/actions.py src/cli/commands.py`
