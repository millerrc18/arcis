# Diagnostic Dashboard v1 — Design Spec

**Sprint:** Diagnostic Dashboard Page v1
**Branch:** `feat/diagnostic-dashboard-v1`
**Design date:** 2026-04-18
**Target tag:** v0.25.0
**Upstream:** `docs/sprints/SPRINT_diagnostic_dashboard_v1.md` (the original sprint spec from the operator)

---

## 1. Context

Two diagnostic pipelines shipped today (2026-04-18):

- `scripts/diagnostics/regime_diagnostic_v1.py` — CONTAMINATED / UNIFORMLY_NULL / PENDING decision based on VIX regression, day clustering, sector rotation, entry-time, and holding-period analyses (5 analyses, each bootstrapped).
- `scripts/diagnostics/forensic_trade_audit_v1.py` — 8-question forensic with bootcamp counterfactual.

Both run via CLI. Both will be re-invoked at cohort milestones (N=88 today, planned N=150, N=200…). Each re-run currently requires SSH to the Windows machine.

This sprint adds `/diagnostics` page with two buttons that kick off runs via the existing command-queue pattern (Sprint 4C), persists every run in a new `diagnostic_runs` table, and renders the resulting markdown report + plots inline on the cloud dashboard.

**Critical constraint discovered in Pass 2:** `src/sync/render_sync.py` is tables-only — no file-blob sync. Reports and plots must live as table rows (TEXT + base64) to reach the Render dashboard. The local API binds `127.0.0.1` only, so proxy-through-local-API is not an option.

---

## 2. Architecture overview

```
  ┌─────────────────────┐    POST /api/diagnostic-runs/regime
  │  React /diagnostics │ ──────────────────────────────▶  ┌──────────────────────────┐
  │  (Render static)    │                                   │  Render Postgres          │
  │                     │ ◀────────────────────────────    │  pending_commands         │
  │  TanStack Query     │    GET  /api/diagnostic-runs      │  diagnostic_runs          │
  │  react-markdown     │    GET  /api/diagnostic-runs/:id  │  diagnostic_run_plots     │
  └─────────────────────┘         /report, /plots           └──────────────────────────┘
                                                                         ▲
                                                                         │ render-sync (120s)
                                                                         │   - local → cloud
                                                                         ▼
                                                            ┌──────────────────────────┐
                                                            │  Local SQLite             │
                                                            │  pending_commands (pulled)│
                                                            │  diagnostic_runs (local)  │
                                                            │  diagnostic_run_plots     │
                                                            └──────────────────────────┘
                                                                         ▲
                                                                         │ executor dispatch
                                                                         │
                                                            ┌──────────────────────────┐
                                                            │  src/commands/executor.py │
                                                            │   run-regime-diagnostic   │
                                                            │   run-forensic-audit      │
                                                            │      │                    │
                                                            │      ▼                    │
                                                            │  subprocess.run           │
                                                            │  scripts/diagnostics/...  │
                                                            └──────────────────────────┘
```

### 2.1 Data flow

1. Operator clicks "Run Regime Diagnostic" → `POST /api/diagnostic-runs/regime` (cloud).
2. Cloud endpoint:
   - Allocates `run_id = uuid4()`
   - Checks dedup: `SELECT … FROM diagnostic_runs WHERE diagnostic_type='regime' AND status IN ('queued','running')`. If found → 409 CONFLICT.
   - Inserts `diagnostic_runs(run_id, type='regime', status='queued', trigger_source='dashboard', triggered_by=<email>, created_at=now, updated_at=now)` into Postgres.
   - Inserts `pending_commands(command_id=run_id, command_name='run-regime-diagnostic', payload_json={run_id, db_path, exclude_quarantined}, status='pending', expires_at=now+5m)` into Postgres.
   - Returns `202 {run_id, command_id, status: 'queued'}`.
3. `render_sync.pull_commands()` pulls `pending_commands` to local SQLite (within 120s).
4. Watch-loop executor (`execute_commands`) picks up the command, dispatches to `_handle_run_regime_diagnostic`.
5. Handler:
   - UPSERTs local `diagnostic_runs(run_id, status='running', started_at=now, updated_at=now, cohort_n=<queried>)`.
   - Invokes `subprocess.run([python, 'scripts/diagnostics/regime_diagnostic_v1.py', '--output', <tmp>, '--plot-dir', <tmp>, '--db', <db_path>])` with `timeout=900`.
   - On success: reads the generated markdown and PNG files, extracts summary via `summary_extractor.parse_regime_report(md_text) → summary_dict`, INSERTs `diagnostic_run_plots` rows (one per PNG, base64-encoded), UPDATEs `diagnostic_runs(status='completed', completed_at, report_markdown, summary_json, exit_code=0, updated_at)`.
   - On failure (non-zero exit or exception): captures last 2KB of stderr, UPDATEs `diagnostic_runs(status='failed', stderr_tail, exit_code, updated_at)`.
6. Next render-sync cycle pushes local `diagnostic_runs` + `diagnostic_run_plots` changes to Postgres.
7. Dashboard polls `GET /api/diagnostic-runs` every 5s while any run is active → sees `queued → running → completed`.
8. Operator clicks the row → `GET /api/diagnostic-runs/:run_id/report` returns the markdown; `GET /api/diagnostic-runs/:run_id/plots` returns `[{filename, content_b64}, …]`. Page renders inline with `react-markdown` + `<img src="data:image/png;base64,...">`.

### 2.2 Why this shape

- **Reuses Sprint 4C command-queue pattern.** No new sync infrastructure, no new long-poll mechanism.
- **Postgres is single source of truth for the dashboard.** Dashboard never queries local. Local writes drive Postgres via existing `render_sync`.
- **Table rows carry the report/plot payload.** Works within the existing tables-only sync mechanism.
- **`run_id` is the same as `command_id`.** Simplifies plumbing: no join needed between `pending_commands` and `diagnostic_runs` beyond this shared key.

---

## 3. Data model

### 3.1 New table: `diagnostic_runs`

```
run_id             TEXT   PK, UUID4
diagnostic_type    TEXT   'regime' | 'forensic'
status             TEXT   'queued' | 'running' | 'completed' | 'failed'
trigger_source     TEXT   'dashboard' | 'cli' (v1 only writes 'dashboard')
triggered_by       TEXT   operator email | 'system' | 'cli-<hostname>'
cohort_n           INT    size of closed-trade cohort at run start
started_at         TEXT   ISO8601 ET, set when status → 'running'
completed_at       TEXT   ISO8601 ET, set when status → terminal
exit_code          INT    subprocess exit code (null until terminal)
report_markdown    TEXT   full markdown body (set when status → 'completed')
summary_json       TEXT   extracted summary dict (decision, N, mean_excess, headline findings)
stderr_tail        TEXT   last 2KB of stderr (null unless 'failed')
payload_json       TEXT   original submission payload
created_at         TEXT   ISO8601 ET, set at initial insert (API or handler)
updated_at         TEXT   ISO8601 ET, bumped on every row modification (for sync cursor)
```

**Sync:** `sync_to_postgres=True`, `sync_mode='incremental'`, `sync_time_column='updated_at'`.

**Indexes:** `idx_diagnostic_runs_type_status` on `(diagnostic_type, status)` for dedup queries. `idx_diagnostic_runs_created_at` on `created_at` for history sort.

### 3.2 New table: `diagnostic_run_plots`

```
plot_id         TEXT   PK, UUID4
run_id          TEXT   FK → diagnostic_runs(run_id)
filename        TEXT   e.g. 'vix_regression.png'
content_b64     TEXT   base64-encoded PNG bytes
sort_order      INT    display order within the report
created_at      TEXT   ISO8601 ET
```

**Sync:** `sync_to_postgres=True`, `sync_mode='incremental'`, `sync_time_column='created_at'`.

**Indexes:** `idx_diagnostic_run_plots_run_id` on `run_id`.

### 3.3 Why two tables instead of one JSON blob

Sibling table gives:

- Per-plot row size (~150-500 KB each) instead of mega-row updates.
- Incremental sync granularity — one failed plot doesn't poison the run row.
- Easier GET endpoint implementation (`SELECT filename, content_b64 FROM diagnostic_run_plots WHERE run_id=? ORDER BY sort_order`).

---

## 4. API contract (cloud routes)

All endpoints under `/api/diagnostic-runs/*` (see decision D09). All require `verify_auth` dependency.

### 4.1 `POST /api/diagnostic-runs/regime`

**Body:** `{ "exclude_quarantined": bool, "bootstrap_n": int }` (both optional; defaults match CLI).
**Response 202:** `{ run_id, command_id, status: 'queued' }`.
**Response 409:** `{ detail: 'Regime diagnostic already running (run_id=…)' }`.

### 4.2 `POST /api/diagnostic-runs/forensic`

**Body:** `{}` (forensic has no operator-tunable params per spec non-goals).
**Response:** same shape as regime.

### 4.3 `GET /api/diagnostic-runs`

**Query params:** `limit=20`, `type=regime|forensic|all` (default `all`), `status=queued|running|completed|failed|all` (default `all`).
**Response 200:** `{ runs: [{ run_id, diagnostic_type, status, trigger_source, cohort_n, started_at, completed_at, summary_json }], count }`.
**Note:** `report_markdown` and plot blobs are NOT returned here (payload minimization). Use `GET /:id/report` and `GET /:id/plots` for detail.

### 4.4 `GET /api/diagnostic-runs/{run_id}`

**Response 200:** single run row (same shape as list, but a single object).
**Response 404:** `{ detail: 'Run not found' }`.

### 4.5 `GET /api/diagnostic-runs/{run_id}/report`

**Response 200:** `{ markdown: "..." }`. Large payload (≤100 KB). Cached with `Cache-Control: private, max-age=300` since runs are immutable once completed.
**Response 404:** if run not found or not yet completed.

### 4.6 `GET /api/diagnostic-runs/{run_id}/plots`

**Response 200:** `{ plots: [{ filename, content_b64, sort_order }] }`. Large payload (≤2 MB).
**Response 404:** if run not found.

---

## 5. Component design

### 5.1 Backend modules

**`src/commands/executor.py`** — extend `COMMAND_HANDLERS` with two new entries:

- `_handle_run_regime_diagnostic(payload, config) -> dict` — invokes `scripts/diagnostics/regime_diagnostic_v1.py`, manages `diagnostic_runs` lifecycle. Returns summary dict for `command_results`.
- `_handle_run_forensic_audit(payload, config) -> dict` — same pattern for forensic script.

Both handlers delegate file-handling and lifecycle bookkeeping to a new helper:

**`src/diagnostics/dashboard_runner.py`** (NEW) — `run_diagnostic(run_id, script_path, args, report_parser, db_path) -> dict`. This keeps the executor handlers tight (<30 lines each) and centralizes the pattern: temp-dir allocation, subprocess invocation, report read, plot scan, base64 encoding, SQLite transaction for status updates + plot inserts, cleanup.

**`src/diagnostics/summary_extractor.py`** (NEW) — `parse_regime_report(md_text) -> dict` and `parse_forensic_report(md_text) -> dict`. Both regex-parse the `## Executive Summary` section. Fall back to storing raw executive-summary text if a headline field can't be extracted.

**`src/api/cloud_routes/diagnostics.py`** (NEW) — the six endpoints above. Under 200 lines. Follows `cloud_routes/core.py` pattern.

### 5.2 Frontend modules

**`frontend/src/pages/Diagnostics.jsx`** (NEW) — top-level page. ~150 lines. Sections:

1. Kickoff panel (two buttons, disabled while type-matching run is active).
2. Active-run status strip (shown while any run is queued/running, with "Cancel" disabled per spec non-goals).
3. History table (past 20 runs, sortable, click-to-expand).
4. Detail view (inline markdown + plots when a row is expanded).

**`frontend/src/components/DiagnosticKickoffButtons.jsx`** (NEW) — two-button panel. Takes `activeRuns` prop, disables button for type matching any active run. Uses existing `StatusBadge` component.

**`frontend/src/components/DiagnosticRunTable.jsx`** (NEW) — history table. Mirrors `StrategyResearch.jsx`'s table pattern (`bg-gray-100` header, `cursor-pointer hover:bg-gray-50 border-t` rows). Columns: date, type, status, cohort N, decision (from summary_json), view-link.

**`frontend/src/components/DiagnosticRunDetail.jsx`** (NEW) — inline report viewer. Uses `react-markdown` + `remark-gfm` for the markdown; renders plots inline with `<img src="data:image/png;base64,${content_b64}">`. Plots appear in `sort_order`.

**`frontend/src/api.js`** — 6 new methods in the `api` object.

**`frontend/src/App.jsx`** — add `<Route path="/diagnostics" element={<ErrorBoundary><Diagnostics /></ErrorBoundary>} />`.

**`frontend/src/components/Layout.jsx`** — add `{ to: '/diagnostics', icon: Stethoscope, label: 'Diagnostics' }` to the Intelligence group (after Velocity, before Research Platform).

---

## 6. Summary extraction strategy (regex-based, per D03)

Both scripts emit `## Executive Summary` sections with predictable structure.

**Regime report** (`src/diagnostics/report.py` generates it):
- `**Decision:** CONTAMINATED` → regex `r'\*\*Decision:\*\*\s+(\w+)'` → `decision`
- `**N = 88**` → `r'\*\*N\s*=\s*(\d+)\*\*'` → `n_total`
- `Mean excess return: -0.0012` → `r'Mean excess return:\s*([\-\d\.]+)'` → `mean_excess`
- Rationale paragraph verbatim

**Forensic report** (`forensic_trade_audit_v1.py:1022+`):
- `Analyzed **88** closed trades` → `r'Analyzed \*\*(\d+)\*\*'` → `n_total`
- `### 3 Most Surprising Findings` → capture the three bullet points verbatim
- Bootcamp counterfactual N: regex for it at the bootcamp section header

**Fallback:** If any field fails to extract, `summary_json` stores `{"raw_executive_summary": "<first 2000 chars of executive summary section>", "parse_errors": ["decision"]}`. UI handles missing fields gracefully (shows em-dash).

**Unit tests:** sample markdown fixtures in `tests/diagnostics/fixtures/` for both regime and forensic, covering success path and each parse-failure path.

---

## 7. Error handling

### 7.1 Handler-level errors

| Error | Detection | Recorded as |
|---|---|---|
| Subprocess exit code ≠ 0 | `result.returncode` | `status='failed'`, `stderr_tail=<last 2KB>`, `exit_code` |
| Subprocess timeout | `subprocess.TimeoutExpired` caught | `status='failed'`, `stderr_tail='Timed out after 900s'` |
| Report file not created | `Path(report).exists() is False` after subprocess success | `status='failed'`, `stderr_tail='Subprocess succeeded but report not generated: <path>'` |
| Plot dir missing / empty | scan returns 0 files | `status='completed'` (still succeed), `summary_json.plots_warning='No plots generated'` |
| Summary parse failure | caught `re.error` / `AttributeError` | `status='completed'`, `summary_json={raw_executive_summary, parse_errors:[fields]}` |
| SQLite transaction failure during finalize | any DB exception | Log + re-raise; leaves row in `running` state for operator retry. Watch loop moves on. |

### 7.2 API-level errors

- **R3 dedup (409):** atomic check-then-insert in a single Postgres transaction.
- **Missing run (404):** standard FastAPI HTTPException.
- **Auth failure (401):** inherited from `Depends(verify_auth)`.
- **Postgres down (503):** propagates from `runtime.get_pg()`.

### 7.3 Frontend-level errors

- Kickoff failure → inline error banner above kickoff panel, dismissible.
- Poll failure → don't unmount running-run state; retry at next interval. Only unmount after 3 consecutive failures (use TanStack Query retry config).
- Telegram notification on kickoff failure + completion, via `src/notifications/platform_events.py` pattern (D07).

---

## 8. Testing strategy

### 8.1 Backend

- `tests/api/test_diagnostic_routes.py` — ≥8 tests: POST regime/forensic happy path, 409 dedup, 404 missing, GET list with filters, GET report, GET plots, auth required.
- `tests/test_diagnostic_handlers.py` — ≥6 tests: regime handler success path, forensic handler success path, subprocess failure captured as `failed`, timeout handled, SQLite write verified, plot inserts sorted.
- `tests/diagnostics/test_summary_extractor.py` — ≥10 tests: regime success, regime missing-decision fallback, regime malformed, forensic success, forensic missing-findings fallback, etc.
- `tests/test_schema.py` — add the `diagnostic_runs` + `diagnostic_run_plots` tables to the whitelist of known tables for the schema-drift test.

### 8.2 Frontend

- Smoke-only (frontend testing is light in this codebase). Manual verification via `npm run dev` + screenshot in PR body per sprint spec's "Operator hand-off" section.

### 8.3 End-to-end

- Python-level smoke test `tests/test_diagnostic_smoke.py`: synthesize a fake `pending_commands` row, invoke `execute_command`, assert `diagnostic_runs` transitions `running → completed`, assert `diagnostic_run_plots` has rows. Uses the real regime script against a test-fixture database (tiny cohort, bootstrap_n=10 for speed). Runs in ≤30s.
- Manual: click button in dev dashboard, wait 3-5 min, verify report renders, verify plots render, verify Telegram notification arrives.

---

## 9. File manifest

### Create
- `src/diagnostics/dashboard_runner.py` — run orchestration helper
- `src/diagnostics/summary_extractor.py` — regex report parser
- `src/api/cloud_routes/diagnostics.py` — 6 REST endpoints
- `src/api/cloud_routes/__init__.py` — register the new router (modify or create as needed)
- `tests/api/test_diagnostic_routes.py`
- `tests/test_diagnostic_handlers.py`
- `tests/diagnostics/test_summary_extractor.py`
- `tests/diagnostics/fixtures/regime_report_sample.md`
- `tests/diagnostics/fixtures/forensic_report_sample.md`
- `tests/test_diagnostic_smoke.py`
- `frontend/src/pages/Diagnostics.jsx`
- `frontend/src/components/DiagnosticKickoffButtons.jsx`
- `frontend/src/components/DiagnosticRunTable.jsx`
- `frontend/src/components/DiagnosticRunDetail.jsx`

### Modify
- `src/schema/registry.py` — register `diagnostic_runs` + `diagnostic_run_plots`
- `src/commands/executor.py` — add two new `_handle_*` functions + dict entries
- `src/api/cloud_app.py` or equivalent router mount — register the diagnostics router
- `frontend/src/api.js` — 6 new methods on `api` object
- `frontend/src/App.jsx` — 1 new `<Route>`
- `frontend/src/components/Layout.jsx` — 1 new nav item
- `frontend/package.json` — add `react-markdown@^9`, `remark-gfm@^4`
- `docs/MASTER.md` — document the new tables + page
- `CHANGELOG.md` — v0.25.0 entry

### Delete
None.

All files will stay under 400 lines; all functions under 60 lines (per CLAUDE.md guardrails).

---

## 10. Non-goals (verbatim from sprint spec)

- Not parameter-tuning UI.
- Not time-series comparison of past runs.
- Not scheduled auto-runs.
- Not email notifications (Telegram is sufficient).
- Not multi-user concurrency UI.
- Not CSV export.
- Not retrofitting CLI to write `diagnostic_runs` rows (D06).
- Not a library refactor of the diagnostic scripts (D03).

---

## 11. R1–R7 verification matrix (updated from Pass 1)

| R | Requirement | Design satisfies by … |
|---|---|---|
| R1 | Reuse command-queue pattern | Two new entries in `src/commands/executor.py:COMMAND_HANDLERS`. No new scheduler directory. |
| R2 | Persist every run with full metadata | `diagnostic_runs` table with `queued → running → completed/failed` lifecycle; 15 columns per §3.1. |
| R3 | Dedup | API-side atomic check-then-insert in `POST /api/diagnostic-runs/{type}`; 409 on collision. |
| R4 | Inline report + plot rendering | `report_markdown` TEXT + `diagnostic_run_plots.content_b64` TEXT rows; GET endpoints; `react-markdown` + inline PNG data URIs. |
| R5 | Historical runs browsable | `GET /api/diagnostic-runs?limit=20` + `DiagnosticRunTable.jsx`. |
| R6 | Status polling without websockets | TanStack Query `refetchInterval=5000` while any run active; stops at terminal. |
| R7 | Reuse existing components | `StatusBadge`, `ErrorBoundary`, TanStack Query, tailwind utilities. Only new deps: `react-markdown`, `remark-gfm` (operator-approved). |

---

## 12. Next steps

- Invoke `superpowers:writing-plans` to produce the executable implementation plan.
- Plan will break this spec into sequenced, independently-testable steps.
- Pass 3 executes the plan.
