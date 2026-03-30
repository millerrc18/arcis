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
