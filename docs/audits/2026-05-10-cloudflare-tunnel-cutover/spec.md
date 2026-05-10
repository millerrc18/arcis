# Cloudflare Tunnel Cutover + Modified-A Migration — Execution Spec

**Date:** 2026-05-10 (Sun)
**Author:** PM (chat session)
**Read time:** 8 min
**Status:** EXECUTION-READY (operator green-light pending after spec review)

---

## TL;DR

Today's job: stand up the **infrastructure** for Modified A (Docker Postgres as sole DB, Cloudflare Tunnel as sole entry point) and **decommission Render**. The watch loop continues to write SQLite all day; nothing about the trading hot path changes. Docker PG is provisioned with a mirrored schema but holds no data yet.

This week and next: data migration + test-fixture migration + SQLite retirement land in waves. Today's exit state is **transitional Hybrid** with the Modified-A destination locked in.

**Why staged:** A 1-day full Modified-A migration is hand-waving. 336 `connect_db()` call sites + 4995 SQLite-fixture tests + 398 MB of data don't move cleanly under a Sunday clock. The infrastructure pieces *do*. Doing them today buys Render decommission + tunnel cutover without coupling them to the much larger SQLite-retirement work, and Monday market open is unaffected because trading still flows through SQLite.

---

## 0. Pre-flight checklist (~20 min)

- [ ] **0.1 Commit `training_data/train.py`** — the GPU-upgrade rewrite (Unsloth → Transformers+PEFT+TRL+BitsAndBytes). Standalone commit so the cutover diff is clean.
- [ ] **0.2 Triage uncommitted untracked**:
  - `.clone/` — investigate; likely a stray shallow clone, delete if so
  - `Temppr997_full.diff` (path is `C:Temppr997_full.diff` rendered weirdly in `git status`) — stray temp diff; delete
  - `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/` — Sprint 3 visual-verify artifacts; commit as a follow-up doc PR (separate from cutover) OR `git add -p` into the cutover branch (low priority)
  - `docs/audits/2026-05-08-sprint-5-final-cleanup/` — SP5 inventory written 2026-05-08; commit standalone before cutover
- [ ] **0.3 Stop `RenderSyncThread`** — the cleanest path is to leave it running and let it die when the watch loop restarts at the end of Wave 1. (Killing it manually mid-cycle could leave a half-flushed sync state.)
- [ ] **0.4 Snapshot Render PG** — `pg_dump $RENDER_DATABASE_URL > /tmp/render-pg-snapshot-2026-05-10.sql` BEFORE any cutover touches Render. This is the rollback artifact.
- [ ] **0.5 Snapshot local SQLite** — `cp C:/arcis/data/ai_research_desk.sqlite3 C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (398 MB; rollback artifact for the data-migration phase too).
- [ ] **0.6 Verify Docker Desktop is running** on the operator's machine. The cutover assumes Docker is available.

---

## 1. Wave 1 — Infrastructure (~2 hr)

### 1.1 Spin up Docker Postgres
- File: new `docker-compose.yml` at repo root
- Postgres 16 (matches Render's), volume mount `./data/pg-data:/var/lib/postgresql/data` (gitignored)
- Bind to `127.0.0.1:5432` only — never expose Postgres to the network; tunnel exposes the FastAPI in front of it, not PG itself
- Generate a strong password, write it to `.env` as `DATABASE_URL=postgresql://halcyon:<generated>@localhost:5432/halcyon`

### 1.2 Mirror schema into Docker PG
- Run `DATABASE_URL=$(grep DATABASE_URL .env | cut -d= -f2-) python scripts/render_migrate.py` against the new local PG host
- This uses the existing 70-table registry generator (`src/schema/postgres.py`) — no code changes required for schema creation
- Verify table count: `psql $DATABASE_URL -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"` should be ≥70

### 1.3 Add `verify_auth` to local `app.py`
- Lift `cloud_app.py:153-176` (the `verify_auth` function + `API_SECRET` env var + `_API_SECRET_HASH` precomputation at line 150) into `src/api/app.py`
- Apply as a router-level dependency: `app.include_router(..., dependencies=[Depends(verify_auth)])` for every router currently in app.py
- Generate a fresh 32-byte hex `API_SECRET`, write to `.env`, also write to `frontend/.env.production` as `VITE_API_SECRET`
- Frontend already supports this — `frontend/src/config.js:18` reads `VITE_API_SECRET`

### 1.4 Add 3 missing routers to local `app.py`
- Imports near the existing `from src.api.cloud_routes import kpis, broker_exceptions, preflight` block:
  ```python
  from src.api.cloud_routes import notifications as notifications_route
  from src.api.cloud_routes import platform as platform_module
  from src.api.cloud_routes import walkforward as walkforward_module
  ```
- Includes after the existing `app.include_router(preflight_route.router, ...)`:
  ```python
  app.include_router(notifications_route.router, prefix="/api", dependencies=[Depends(verify_auth)])
  app.include_router(platform_module.router, dependencies=[Depends(verify_auth)])  # router carries own /api prefix
  app.include_router(walkforward_module.router, dependencies=[Depends(verify_auth)])
  ```
- Apply same `dependency_overrides` pattern from `cloud_app.py:316-340` so each router's placeholder `verify_auth` resolves to the real one

### 1.5 Configure Cloudflare Zero Trust Public Hostname (operator step)
- Operator: open Cloudflare Zero Trust → Networks → Tunnels → tunnel `f6f41208…` → Public Hostnames
- Add: `halcyonlab.app` → service `http://localhost:8000` (matches local FastAPI port — see §6 decisions below)
- Save; DNS propagates within seconds
- (Frontend's `config.js:7` will fall back to `/api` same-origin — no rebuild needed for routing)

### 1.6 Wave-1 acceptance
- [ ] Docker PG running, schema has ≥70 tables, no data
- [ ] `.env` has `DATABASE_URL=postgresql://...` and `API_SECRET=...`
- [ ] `frontend/.env.production` has matching `VITE_API_SECRET`
- [ ] `python -c "from src.api.app import app; print(len(app.routes))"` shows 3 more routes than before
- [ ] `curl https://halcyonlab.app/api/system/status -H "Authorization: Bearer $API_SECRET"` returns JSON (not HTML SPA fallback)

---

## 2. Wave 2 — Engine awareness (~1.5 hr)

### 2.1 Refactor `src/utils/db.py:connect_db` into engine-aware shim
- Current: `connect_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection` — always SQLite
- New: `connect_db(db_path: str | None = None)` — if `os.environ.get("DATABASE_URL", "").startswith("postgres")` → return a `psycopg2.connect(...)` wrapped in a thin context-manager class that exposes the same `cursor`, `execute`, `fetchall`, `fetchone`, `commit`, `close`, `row_factory` surface; else → existing sqlite3 path with `busy_timeout=30000` and `Row` factory
- This is the §6 H1 harden task from the original spec, repurposed as the wedge for the data-migration phase
- Tests: in this wave, just keep tests passing with `DATABASE_URL` UNSET (default behavior unchanged); PG fixtures arrive in the data-migration wave next week

### 2.2 Build the frontend
- `cd frontend && npm install && npm run build`
- Verify `frontend/dist/index.html` exists and references `assets/index-*.js`
- The local `app.py:78-80` StaticFiles mount picks it up automatically when FastAPI restarts

### 2.3 Wave-2 acceptance
- [ ] `python -m pytest tests/ -q --timeout=60` passes (4995 tests minimum, no regressions — DATABASE_URL is unset so SQLite path runs)
- [ ] `frontend/dist/` populated with current build
- [ ] Manual sanity: `python -c "from src.utils.db import connect_db; c = connect_db(); print(type(c))"` returns `<class 'sqlite3.Connection'>` (DATABASE_URL unset → SQLite path)

---

## 3. Wave 3 — Cutover + verify (~1 hr)

### 3.1 Restart watch loop via NSSM
- `nssm restart ArcisWatchLoop`
- This picks up the new `app.py` code (3 new routers + auth)
- The `start_render_sync` call at `src/scheduler/watch.py:1346-1347` is left in for now — sync thread starts up, fails to find a usable Render PG host (we're about to retire it), and degrades gracefully. **Removal of the call site is on Wave 5 (this week), not today** — keeping the import alive avoids a watch-loop crash if the sync thread is somehow expected by other code paths.

### 3.2 End-to-end smoke test (browser)
- Visit `https://halcyonlab.app` (or `https://halcyonlab.app/?cb=$(date +%s)` cache-buster)
- Verify dashboard loads
- KPI strip renders real numbers
- Trade history paginates
- Council page returns council data
- Notifications health widget shows OK
- Platform page renders walkforward results
- (The 7th test from the spec — "command submission round-trips end-to-end" — is paused because RenderSyncThread is degraded; submit a command via `pending_commands` UI and verify it lands in Docker PG via `psql`)

### 3.3 Decommission Render (operator step)
- Render dashboard → `halcyon-api` service → Settings → Delete
- Render dashboard → `halcyon-frontend` service → Settings → Delete
- **Render Postgres**: leave alive for 7 days as cold backup; format disposal notice on Sun May 17
- DNS: `halcyon-api.onrender.com` and `halcyon-frontend.onrender.com` records can be removed if any Cloudflare zone references them; `halcyonlab.app` already points at Cloudflare

### 3.4 Wave-3 acceptance
- [ ] All 6 dashboard pages render with real data via the tunnel
- [ ] No CORS errors in browser console
- [ ] WebSocket `/ws/live` connects (operator can verify via DevTools Network tab)
- [ ] Render API service deleted; Render PG snapshot retained
- [ ] Watch loop healthy (watchdog.txt updating; no error logs from sync thread that block other tasks)

### 3.5 Commit + push series
Commits land in this order on a single branch (`cutover/cloudflare-tunnel-modified-a-2026-05-10`):

1. `feat(train): switch to Transformers+PEFT+TRL trainer (post-3090-upgrade)` — the train.py rewrite (pre-flight 0.1)
2. `chore(audits): add SP3 visual-verify + SP5 inventory artifacts to history` — 0.2 untracked items
3. `feat(infra): docker-compose for local Postgres 16` — Wave 1.1
4. `feat(api): add API_SECRET auth + 3 cloud routers to local app.py` — Wave 1.3 + 1.4
5. `feat(db): engine-aware connect_db shim (Modified-A wedge)` — Wave 2.1
6. `chore(frontend): rebuild for tunnel deployment` — Wave 2.2
7. `chore(deploy): retire Render API + frontend; cutover to halcyonlab.app via Cloudflare Tunnel` — Wave 3 docs/CHANGELOG

PR title: `cutover: Cloudflare Tunnel + Modified-A migration wedge (2026-05-10 Wave 1-3)`

---

## 4. Rollback playbook

| Failure mode | Detection | Rollback |
|---|---|---|
| Wave 1.1 — Docker PG fails to start | `docker compose up` errors | Skip PG provisioning; abort cutover; revert .env; restart watch loop |
| Wave 1.2 — Schema migration fails | `render_migrate.py` exits non-zero | Drop the local DB (`docker compose down -v`); investigate; do NOT proceed to 1.3 |
| Wave 1.3-1.4 — auth + routers break the local server | `python -m src.api.app` fails to import OR test suite fails | `git reset --hard <pre-Wave-1.3-sha>` on the cutover branch; restart NSSM (picks up reverted code) |
| Wave 1.5 — Cloudflare tunnel routing wrong | `https://halcyonlab.app/healthz` 502/504 | In Cloudflare Zero Trust dashboard, delete the Public Hostname rule. Frontend can be temporarily pointed back at `halcyon-api.onrender.com` by re-adding `VITE_API_URL` env var on Render frontend service |
| Wave 2 — engine shim breaks tests | `pytest tests/ -q` fails | `git revert` the connect_db commit; tests should pass on prior SHA |
| Wave 3 — dashboard 500s after cutover | Browser console errors, Sentry-like signal | Re-enable Render API service (it stays alive in your Render dashboard until you click Delete; deletion is the final step). Update Cloudflare Zero Trust hostname back to onrender.com OR delete the tunnel rule entirely (frontend's `IS_CLOUD` detection sends to onrender.com fallback) |
| Wave 3.3 — Render decommission was premature | Anytime in next 7 days | Render PG snapshot exists; can re-deploy a new Render service from the same git repo within ~10 min |

---

## 5. Decisions decided up-front (no operator action needed)

| Decision | Value | Rationale |
|---|---|---|
| PG container image | `postgres:16-alpine` | Matches Render PG version; alpine is small |
| PG database name | `halcyon` | Matches brand |
| PG user | `halcyon` | Matches db name (Postgres convention) |
| PG password | Random 32-byte hex via `python -c "import secrets; print(secrets.token_hex(32))"` | Stronger than human-typed; rotates easily |
| PG port binding | `127.0.0.1:5432` | Localhost-only; tunnel fronts FastAPI not PG |
| API_SECRET | Random 32-byte hex (separate from PG password) | Same pattern as cloud_app's existing `API_SECRET` |
| Local FastAPI port | `8000` | FastAPI default; current local dev uses this |
| Tunnel hostname route | `halcyonlab.app` → `http://localhost:8000` | Same-origin frontend + /api; no CORS; matches operator's "local FastAPI serves the build" choice |
| Frontend rebuild | Yes, with same-origin `/api` and `VITE_API_SECRET` set | `config.js` defaults to `/api` when `VITE_API_URL` unset; clean |
| Docker compose vs raw `docker run` | Compose | Survives reboot via `docker compose up -d`; one source of truth |
| `.env` location | Repo root (existing) | Already gitignored |
| Branch name | `cutover/cloudflare-tunnel-modified-a-2026-05-10` | Date-anchored; clear scope |
| PR-merge style | Merge commit (preserve 7-commit series) | Granular rollback if needed; not squash |

---

## 6. Out of scope today (the Modified-A tail)

These are the multi-week follow-ups that complete Modified A. NOT today's work.

- **6.1 Data migration:** SQLite → PG. `pg_dump` from a snapshot OR write a per-table migration script. ~2-3 days when undertaken; risks: ROWID-vs-SERIAL impedance, INSERT OR REPLACE semantics, savepoint behavior in PG, FK constraint ordering on bulk insert.
- **6.2 Watch loop write-side migration:** Set `DATABASE_URL` in NSSM service env so `connect_db()` engine-aware shim routes to PG. Watch loop now writes PG natively. ~1 day, but contingent on 6.1.
- **6.3 Test-fixture migration:** All 4995 tests currently use `tests/conftest.py::init_test_db` against in-process SQLite. Move to `pytest-postgresql` or `testcontainers` so impedance is exercised in CI. ~2-4 days, ~80 conftests to touch.
- **6.4 SQLite-ism audit:** All 336 `connect_db()` call sites use SQL strings that may contain `?` placeholders (PG wants `%s`), `INSERT OR REPLACE` (PG: `ON CONFLICT DO UPDATE`), `ROWID` references, or other SQLite-isms. Static-grep first, then runtime-test.
- **6.5 Cloud-route dual-mode collapse:** The 6 `cloud_routes/*.py` files with `if database_url:` runtime branches collapse to single-engine logic once Modified A is complete. ~70 LOC removable.
- **6.6 `render_sync.py` retirement:** 1359 LOC delete. Watch loop call site at `watch.py:1346-1347` removes too. ~1 day for the delete + the test sweep.
- **6.7 `cloud_app.py` retirement:** 341 LOC. After local `app.py` is the only entry point, this file deletes.
- **6.8 `src/schema/postgres.py` becomes the only generator:** `src/schema/sqlite.py` deletes once SQLite is fully retired. CI guardrails update.
- **6.9 Sprint 5 spec adjustment:** Tracker #56 (strategy_id FK to shadow_trades) is now PG-native, not dual-write — simpler. #1040 routing-policy unaffected. The Sprint 5 design dispatch resumes when 6.1-6.2 complete.

Cumulative tail estimate: 8-12 person-days across 2-3 weeks.

---

## 7. Open risks (acknowledged)

- **R1: Watch loop import-error after `connect_db()` shim.** The shim adds a psycopg2 import path. If `psycopg2-binary` isn't already a hard dep, the import fails. Mitigation: psycopg2-binary IS already in `requirements.txt` (used by render_sync); should be safe. Verify in pre-flight 0.6.
- **R2: Same-origin frontend means CSP/X-Frame-Options needs to allow same-origin XHR.** Local FastAPI doesn't set restrictive CSP currently; should be fine. Verify in Wave 3.2 smoke test.
- **R3: WebSocket `/ws/live` over the tunnel** — Cloudflare Tunnel does support WebSockets but verify in Wave 3.4. If broken, fallback is polling.
- **R4: Operator's home ISP outage during cutover** would orphan the dashboard immediately. Mitigation: pick a stable network window; operator's ISP outage history should inform timing.
- **R5: Watch loop's RenderSyncThread keeps trying to connect to Render PG even after we retire the service** — it'll log errors continuously. Mitigation: add an env-var feature-flag (`SYNC_THREAD_ENABLED=false`) before Wave 3.1 to short-circuit `start_render_sync()`. Cheap hedge.
- **R6: Render service deletion is permanent.** Once deleted, redeploy is from-scratch (~10 min from git). Mitigation: don't delete until smoke test passes.
- **R7: Docker Desktop drains memory/CPU on the operator's machine** while the watch loop + corpus generator run. Mitigation: Docker PG is idle-light; if pressure becomes real, the PG container can be paused without affecting today's outcomes.

---

## 8. Sprint 5 interaction

- The cutover lands on its own branch + PR. NOT part of Sprint 5.
- Sprint 5 design (paused mid-INTERVIEW with 3 answers locked: #1044=all-47 / quiet-hours=settings-driven-with-overrides / digest=new-table) **resumes after Wave 3 lands**.
- The post-cutover Sprint 5 design adjusts §F.1 (#56 strategy_id FK) to single-engine PG and removes any dual-mode assumption from §H.1.
- The cutover-tail items 6.1-6.8 are NOT folded into Sprint 5 — they're their own ongoing migration project tracked separately.

---

## 9. Glossary

- **Modified A:** Postgres becomes the sole DB. SQLite retires. Migration multi-stage.
- **Pure E:** Cloudflare Tunnel + SQLite-only (no PG anywhere). Spec-recommended; operator declined in favor of Modified A.
- **Hybrid (transitional):** Today's exit state — PG provisioned but no live data; SQLite still primary. Bridge between current dual-store and Modified A endpoint.
- **Engine-aware `connect_db`:** Single function that returns sqlite3 or psycopg2 connection based on `DATABASE_URL` env. Wedge that lets us migrate one process at a time.
