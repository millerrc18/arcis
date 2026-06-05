# Founder Console — Phase 1 Pre-flight (Planner)

**Date:** 2026-06-05
**STATUS: COMPLETE** — task graph emitted to PM.
**Spec:** `docs/superpowers/specs/2026-06-04-founder-console-design.md` (Phase 1 scope only)

## Verified integration points (actual paths)

- **Schema registry:** `src/schema/registry.py` — `TableDef`/`ColumnDef`/`IndexDef`; register via `_register(...)`, then `python -m src.main validate-schema --fix`. New tables for break-events + PAUSE state go HERE only.
- **Metric compute (to consolidate):** `src/api/cloud_routes/kpis.py` (router) + `src/api/cloud_routes/kpis_compute.py` (pure compute) + `src/analytics/kpis_compute.py`. Each KPI returns N + as_of + cohort label via `src/api/cohort_meta.py` (`COHORT_LABELS`, `meta_entry`).
- **Route registration:** `src/api/app.py` (~line 148-190, `app.include_router(...)`); `cloud_routes` mounted at `prefix="/api"`. New routers register here.
- **Canonical book source:** `src/tools/tradingstate/` (core/queries/render) — TradingState, `source='live'` vs paper; PG-with-SQLite-fallback. Open-positions + book reads MUST go through this (#134).
- **Freshness/heartbeat:** `src/tools/healthprobe/core.py` — `_DEFAULT_STALENESS` per service, `_HEARTBEAT_SOURCES` (only ArcisWatchLoop has a real heartbeat at `cfg.paths.watchdog_heartbeat`), `_PORT_SOURCES` for fileless services. Reuse, do NOT reinvent.
- **Reconcile / break events:** `src/shadow_trading/reconcile.py` — `reconcile_live_trades()` returns `{orphaned, stale, backfilled, marked_closed}`; `_backfill_trade_data()` is the auto-heal point. Break-event emission hooks where backfill/orphan is detected (law #9 — retain BEFORE backfill erases evidence). Paper reconcile also in this module.
- **PAUSE origin points:** autonomous actions originate at `src/scheduler/watch.py::ArcisWatchLoop._run_scan()` (line 928) and the executor `src/shadow_trading/executor.py`. Existing precedent: governor file-based kill switch `src/risk/governor.py::_global_halt/_is_halted/_halt_info` (line 199-280) — graceful PAUSE is DISTINCT (blocks new actions only; keeps position_monitor + reconcile running; vs hard kill that stops trades). Model the file/state + audit-log on `_global_halt` but do NOT reuse the halt file.
- **Audit log:** `src/utils/activity_logger.py::log_activity(event_type, detail, metadata)`.
- **Governor limits-used:** `src/risk/governor.py::effective_position_cap(config)` (line 102) + `get_portfolio_state()` (line 836).
- **Version/header:** `src/version.py::VERSION` (v0.36.85). PAPER/bootcamp flags from `src/config/__init__.py` (bootcamp cfg) + market state from `watch.py::_is_market_open`.
- **Frontend:** `frontend/` React 19 + Vite + Tailwind 4 + TanStack Query 5 + Recharts 3 + react-router-dom 7. Entry `src/main.jsx` → `src/App.jsx` (single `QueryClient`, `BrowserRouter`, `Layout`). API client `src/api.js`, config `src/config.js`. Tests colocated `*.test.jsx` (vitest + @testing-library/react). DO NOT touch existing pages.

## Test conventions
- Backend: `tests/api/test_*.py` (pytest). Run with `TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon` and `DATABASE_URL` UNSET. NEVER `ARCIS_ALLOW_PROD_PG_IN_TESTS=1`.
- Frontend: `npm test` (vitest) in `frontend/`; colocated `*.test.jsx`.
- CI floor ≥5467 tests — every task ADDS tests.

## Phase-1 under-specified decisions (flagged to PM)
1. New-console mount: spec says "alongside old." Plan choice = SAME `frontend/` app, new `/console/*` route subtree + dedicated `consoleQueryClient`/route group, so the old 28 pages are byte-untouched and one build/deploy serves both. (Alternative parallel-app rejected: doubles build/deploy infra for a temporary parity window.)
2. "Decision count" for NOW's routed chip: Decide queue is NOT built this phase. Plan = a minimal read-only `pending_decisions_count` endpoint that counts already-existing pending gates (gate_decisions, promotion gates, auditor halt recs) — count only, no queue, no actions.
3. Break-event table: introduced as a registry `TableDef` (`reconciliation_breaks`) — break-RATE needs retained history independent of the auto-healed shadow_trades row.
4. PAUSE state store: a registry-backed table (`console_pause_state`) preferred over a file, so status-read is a single canonical DB read coherent across processes (file-based halt is the legacy pattern; D10 graceful pause is new). Gate is read at `_run_scan` + executor entry.
