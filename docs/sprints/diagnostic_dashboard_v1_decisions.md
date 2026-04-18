# Diagnostic Dashboard v1 — Decisions Log

Running record of every non-obvious choice made during this sprint, with reasoning. For post-sprint operator review.

**Format per entry:** Decision # / phase / title → options considered → choice → why. Add inline as decisions are made.

---

## Pass 1 decisions (all operator-accepted defaults from `diagnostic_dashboard_v1_evaluation.md` §5)

### D01 — Pass 1 — Plot storage strategy

- **Options:** A. Sibling `diagnostic_run_plots` table (base64 TEXT per plot); B. Single BLOB on `diagnostic_runs.plots_blob`; C. No plot sync (text-only in dashboard)
- **Choice:** A
- **Why:** Matches R4 requirement (dashboard can render plots). Sibling table gives per-plot granularity (partial sync if one plot update fails) and avoids mega-row updates. Postgres TEXT column handles ≤2 MB total comfortably. Additive schema cost is trivial given the registry is single-source-of-truth.

### D02 — Pass 1 — Nav group placement

- **Options:** Intelligence; System
- **Choice:** Intelligence
- **Why:** Diagnostics are research/decision tools (sit alongside Training, Council, CTO Report, Model Perf). System group is for ops tools (Validation, Health, Monitoring). Diagnostic reports inform operator about the *trading system's behavior*, not the *platform's health*.

### D03 — Pass 1 — Summary extraction path

- **Options:** Library refactor (handler calls `run_diagnostic(args) -> dict`); subprocess + regex parse `## Executive Summary`
- **Choice:** Subprocess + regex for v1
- **Why:** Smaller blast radius — doesn't require refactoring the shipped diagnostic scripts. Parsing a consistent `## Executive Summary` section with a well-tested regex has acceptable fragility. Library refactor is a worthwhile v0.26 followup.

### D04 — Pass 1 — Polling cadence

- **Options:** 3s, 5s (spec default), 10s
- **Choice:** 5s while any run active; stop (or revert to 30s) when all terminal
- **Why:** Matches spec. 3s is more responsive but increases API load for marginal UX gain in a 3-5 min operation. 10s makes operators feel the UI is stuck.

### D05 — Pass 1 — Retention policy

- **Options:** Keep forever; age out after 90d; keep last 50
- **Choice:** Keep forever for v1
- **Why:** Rows are tiny (≤6 plot rows + 1 run row per diagnostic). Even 10 runs/day × 365 days = 3650 + 21900 rows = well under concern levels. Retention tooling is a v0.26 followup if volume ever matters.

### D06 — Pass 1 — Trigger source labeling

- **Options:** Dashboard writes rows; CLI also retrofits to write rows
- **Choice:** Dashboard-only row writes for v1
- **Why:** CLI users already have the local markdown file; they don't need the dashboard's history table. Retrofitting the CLI couples this sprint's completion to touching shipped scripts — avoidable.

### D07 — Pass 1 — Failure UX

- **Options:** Error banner; toast; Telegram push; all three
- **Choice:** Error banner + Telegram
- **Why:** Banner gives in-page context; Telegram reaches operator when they're not looking at the dashboard. Toast is redundant with banner. Telegram uses existing `src/notifications/platform_events.py` — zero new infrastructure.

### D08 — Pass 1 — Run naming

- **Options:** UUID (per spec); human-readable `regime-2026-04-18-a`
- **Choice:** UUID
- **Why:** Uniqueness is more important than readability; UI truncates to 8 chars for display. Human-readable naming introduces collision logic (what's after `-z`?) that adds complexity for marginal UX gain.

---

## Pass 2 decisions

### D09 — Pass 2 — API prefix

- **Options:** `/api/diagnostics/*` (as originally spec'd); `/api/diagnostic-runs/*`
- **Choice:** `/api/diagnostic-runs/*`
- **Why:** `GET /api/diagnostics` already exists in `cloud_routes/core.py:111` as a Postgres-table-health endpoint. While the sub-paths (`/api/diagnostics/regime`, `/api/diagnostics/runs`) don't technically conflict, the semantic overlap is confusing. `/api/diagnostic-runs/*` matches the new table name and reads clearly.

### D10 — Pass 2 — Queued-state persistence across sync boundary

- **Options:** (a) API inserts `diagnostic_runs(queued)` directly in Postgres; local handler INSERTs locally when execution starts; render-sync merges on UPSERT. (b) API only inserts `pending_commands`; `diagnostic_runs` row is created by local handler at execution start (no 'queued' state persisted). (c) API inserts both `pending_commands` and `diagnostic_runs(queued)` locally; pulled to Postgres via normal sync (but local wouldn't have the "queued" row until sync lands — defeats purpose).
- **Choice:** (a)
- **Why:** R2 explicitly lists `'queued'` as a status value — spec-faithful. Postgres row is authoritative for "queued" (dashboard UI), local row is authoritative for "running"/"completed"/"failed". Render-sync's normal incremental mechanism propagates local-side updates back to Postgres, overwriting the queued state. Requires UPSERT-on-conflict for TEXT-PK table — to verify in Pass 3.

### D-correction to Pass 1 — `/research-platform` is NOT a dead link

- Pass 1 eval claimed `Layout.jsx:26` `/research-platform` nav link has no page backing it.
- `App.jsx:128` actually routes `/research-platform` to `StrategyResearch.jsx`. Not a dead link — just an odd path-to-component mapping.
- **Impact on sprint:** none. Still mirror `StrategyResearch.jsx` as the visual pattern.

---

---

## Pass 3 decisions

_To be appended during implementation._
