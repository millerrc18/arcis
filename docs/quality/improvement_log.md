# Improvement Log

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
