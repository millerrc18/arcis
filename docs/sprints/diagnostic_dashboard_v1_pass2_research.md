# Diagnostic Dashboard v1 — Pass 2 Research Findings

**Sprint:** Diagnostic Dashboard Page v1
**Branch:** `feat/diagnostic-dashboard-v1`
**Pass 2 date:** 2026-04-18
**Purpose:** Verify architectural assumptions from Pass 1 and surface new decisions before implementation.

---

## 1. Verified: schema registry `TableDef` shape (`src/schema/registry.py:60-77`)

```python
@dataclass
class TableDef:
    name: str
    description: str
    columns: list[ColumnDef]
    primary_key: str | list[str]
    indexes: list[IndexDef] = ...
    foreign_keys: list[ForeignKeyDef] = ...
    sync_to_postgres: bool = True
    sync_mode: str = "incremental"  # or "full" or "latest_only"
    sync_time_column: str | None = "created_at"
    sync_pk: str | None = None
    sync_conflict_col: str | None = None
```

**Incremental sync requires a column that bumps on UPDATE, not just on INSERT.** Existing convention for tables with lifecycle status changes (e.g. `recommendations:166`, `shadow_trades:302`, `user_notes:1485`): use `sync_time_column="updated_at"` and bump `updated_at` on every row modification.

**Applied to `diagnostic_runs`:** columns include both `created_at` and `updated_at`. `sync_time_column="updated_at"`. Handler code bumps `updated_at = now()` on every status transition (`queued → running → completed/failed`).

---

## 2. Verified: API-side command submission pattern (`src/api/cloud_routes/core.py:62-103`)

The `_submit_command()` helper in `core.py` does one job: insert into `pending_commands` table in Postgres with a fresh UUID, `status='pending'`, and a 5-minute `expires_at`. It returns `{command_id, status, expires_at}` with HTTP 200 (not 202 — existing pattern).

All existing action endpoints (`/api/actions/scan`, `/api/actions/council`, etc.) follow this exact pattern — one-liner delegation to `_submit_command("handler-name", payload={...})`.

**Applied to diagnostic endpoints:** Mirror this pattern. But also insert a `diagnostic_runs` row (status='queued') in Postgres at the same moment, so the history table reflects every attempted run per R2. The new cloud route file will have a thin variant of `_submit_command` that does both inserts atomically.

---

## 3. Verified: frontend API pattern (`frontend/src/api.js`)

- Single `fetchApi(path, options)` helper handles auth + errors.
- `api` object is a flat dict of named methods. My additions extend this object.
- Pattern: `triggerScan: () => fetchApi('/scan', { method: 'POST' })`.

**Applied:** Add `triggerRegimeDiagnostic`, `triggerForensicAudit`, `getDiagnosticRuns`, `getDiagnosticRun`, `getDiagnosticRunReport`, `getDiagnosticRunPlots` (returns list of base64 data URIs).

---

## 4. Verified: React routing + layout

- `App.jsx:128` has `<Route path="/research-platform" element={<ErrorBoundary><StrategyResearch /></ErrorBoundary>} />`. **Correction to Pass 1:** the `/research-platform` link is wired, just to `StrategyResearch.jsx` under a weirdly-named path. No dead link. My `/diagnostics` route follows the same `<Route path … element={<ErrorBoundary><Diagnostics /></ErrorBoundary>} />` wrapping.
- `Layout.jsx:19-29` — Intelligence section contains Training, Council, CTO Report, Attribution, Model Perf, Velocity, Research Platform, Stress Test, Simulation. Correct home for Diagnostics.
- Existing `refetchInterval: 30000` default (`App.jsx:43`) with per-query overrides for polling — our `useQuery` hooks will override `refetchInterval` to 5000 conditionally while any run is active.

---

## 5. Verified: `react-markdown` + `remark-gfm` are latest stable

- `react-markdown@9.x` (current stable as of 2026-01) — React 19 compatible.
- `remark-gfm@4.x` — pairs with react-markdown@9 for GitHub-flavored markdown (tables, task lists).
- Both are small, well-maintained, no native deps. Operator-approved (Pass 1 decision D-prelim; logged as operator-approved in Pass 1).

---

## 6. New finding: `/api/diagnostics` already exists as a Postgres health endpoint

`cloud_routes/core.py:111-127`:
```python
@router.get("/api/diagnostics", dependencies=[Depends(verify_auth)])
def diagnostics():
    # returns Postgres table health for runtime.diagnostic_tables
```

The spec proposed `POST /api/diagnostics/regime`, `GET /api/diagnostics/runs`, etc. These *don't technically conflict* with the existing `GET /api/diagnostics` (different paths), but the semantic overlap is confusing — "/api/diagnostics" already means "Postgres table health", and we'd be reusing the same prefix for "trade-cohort diagnostic runs".

**Decision D09 — API prefix:** Use `/api/diagnostic-runs/*` instead of `/api/diagnostics/*`. Matches the table name (`diagnostic_runs`), avoids collision with the existing health endpoint, reads clearly in code.

Endpoints become:
- `POST /api/diagnostic-runs/regime` → start a regime run
- `POST /api/diagnostic-runs/forensic` → start a forensic run
- `GET /api/diagnostic-runs?limit=20&type=regime&status=completed` → list
- `GET /api/diagnostic-runs/{run_id}` → single run
- `GET /api/diagnostic-runs/{run_id}/report` → markdown text
- `GET /api/diagnostic-runs/{run_id}/plots` → list of `{filename, content_b64}` for all plots

---

## 7. New finding: queued-row lifecycle across the sync boundary

The sprint requires 4 status values (`queued → running → completed/failed`) per R2. But `diagnostic_runs` is a local-SQLite-first table; queued state needs to exist in Postgres *before* the local machine picks up the command.

**Decision D10 — Queued-state handling:** At API POST time, insert *directly into Postgres* `diagnostic_runs` with `status='queued'`, keyed by the same `run_id` that goes into the `pending_commands.payload`. Local handler, on first execution, INSERTs locally with same `run_id` and `status='running'`; subsequent status updates happen locally. Render-sync pushes local writes to Postgres using the existing incremental mechanism (our PK is `run_id TEXT`, not SERIAL, so ON CONFLICT DO UPDATE is the correct merge mode — will verify the exact sync-cursor handling in Pass 3 and adjust if needed).

Timeline:
1. **Dashboard POST.** Postgres row: `queued`; local row: none. Dashboard shows "queued".
2. **Render-sync pulls pending_commands.** No change to `diagnostic_runs`.
3. **Local handler starts.** Local insert: `running`. Render-sync pushes on next cycle (up to 120s delay).
4. **Next sync.** Postgres row: `running`. Dashboard polls & sees running.
5. **Handler completes.** Local update: `completed` + summary/plots rows. Next sync propagates.

The 120s sync lag means dashboard can be up to 2 min behind local state. Acceptable for a 3-5 min diagnostic — operator sees "queued" briefly, then "running", then "completed". Progress updates within the "running" phase are not granular. That's a non-goal per sprint spec.

---

## 8. New finding: `ON CONFLICT DO UPDATE` needed for `diagnostic_runs` sync

Existing render_sync comment at line 24 of the module docstring says `ON CONFLICT DO NOTHING` is used for SERIAL-PK tables to avoid duplicate key errors. `diagnostic_runs` has TEXT PK (`run_id`) — sync needs to UPDATE on conflict, not skip. Need to verify render_sync honors this.

**Action for Pass 3:** Read `sync_config.py` + the per-table upsert logic in render_sync to confirm TEXT-PK tables do the correct UPSERT. If not, either (a) use a sync_mode that does so, or (b) document a small extension.

---

## 9. Verified: cloud_routes test pattern

`tests/test_cloud_analytics.py` is the nearest analog. I'll read it briefly in Pass 3 before writing tests — expect a FastAPI TestClient pattern with mocked `runtime`. Out of scope for Pass 2.

---

## 10. New decisions added to the log

- **D09** — API prefix `/api/diagnostic-runs/*` (not `/api/diagnostics/*`) to avoid collision with existing health endpoint.
- **D10** — Queued-state persistence: API inserts directly into Postgres `diagnostic_runs(queued)`; local handler upserts `running` via sync. Local is authoritative for `running`/`completed`; Postgres is the dashboard read path.

Both appended to `diagnostic_dashboard_v1_decisions.md`.

---

## 11. Pass 2 complete — proceeding to design spec + writing-plans

Operator's standing authorization (2026-04-18) is to bypass mid-sprint check-ins and review the full decisions log at sprint end. Pass 2 is committed on the feature branch; onward to:

- Full design spec at `docs/superpowers/specs/2026-04-18-diagnostic-dashboard-design.md`
- `superpowers:writing-plans` skill to produce the implementation plan
- Pass 3 execution
