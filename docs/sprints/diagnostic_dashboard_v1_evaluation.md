# Diagnostic Dashboard v1 — Pass 1 Evaluation

**Sprint:** Diagnostic Dashboard Page v1
**Branch:** `feat/diagnostic-dashboard-v1` (created from `origin/main` at `c2692fa`)
**Target tag:** v0.25.0
**Pass 1 author:** Claude (Opus 4.7, 1M context)
**Pass 1 date:** 2026-04-18
**Status:** Awaiting operator review before Pass 2

---

## 1. Spec corrections applied

The original spec had three drift-from-reality items that the operator corrected inline. Pass 1 incorporates them:

| Spec stated | Reality at `c2692fa` | Resolution |
|---|---|---|
| `src/scheduler/command_handlers/` directory for handlers | No such directory. Pattern lives in `src/commands/executor.py` with a `COMMAND_HANDLERS` dict (14 entries) and `_handle_X(payload, config) -> dict` functions. | Extend `COMMAND_HANDLERS` in `executor.py` with two new entries: `run-regime-diagnostic`, `run-forensic-audit`. No new directory. |
| Dashboard pattern: `/research-platform` page | The `/research-platform` nav link exists (`Layout.jsx:26`) but no `ResearchPlatform.jsx` page — the link is dead. Closest real precedent is `StrategyResearch.jsx` (262 lines, TanStack Query + tailwind + `p-6` container). | Mirror `StrategyResearch.jsx` structure for `Diagnostics.jsx`. Do not fix the dead `/research-platform` link in this sprint. |
| `react-markdown` fallback acceptable | Confirmed not installed (`frontend/package.json` has no markdown dep). | Operator approved adding `react-markdown` + `remark-gfm` as new npm deps for inline rendering. Document the approval in the Pass 2 research notes. |

Additionally: the stale `feat/forensic-trade-audit-v1` untracked docs and the 4 unpushed pre-squash commits on local `main` were discarded (operator-authorized 2026-04-18). Branch `feat/diagnostic-dashboard-v1` is now clean off `origin/main@c2692fa`.

---

## 2. R1–R7 satisfaction map

| Req | Requirement | Feasibility | Notes |
|---|---|---|---|
| **R1** | Reuse command-queue pattern; don't build parallel infrastructure | ✅ Clean | Two new `COMMAND_HANDLERS` entries in `src/commands/executor.py`. Simulation handler (`executor.py:264`) is a direct precedent — it already invokes a script via `subprocess.run` with timeout. |
| **R2** | Persist every run with full metadata (`diagnostic_runs` table) | ✅ Clean | Add `TableDef` to `src/schema/registry.py`. `validate-schema --fix` propagates to SQLite; `render_migrate.py` propagates to Postgres. `sync_config.py` auto-wires sync from the registry entry. |
| **R3** | Dedup: one running diagnostic of each type at a time | ✅ Clean | Serial executor gives free enforcement at the queue level. API still must check `SELECT status FROM diagnostic_runs WHERE diagnostic_type=? AND status IN ('queued','running')` before INSERT → 409 on hit. Minor race on concurrent requests; acceptable for single-operator UI. |
| **R4** | Inline report rendering (markdown + plots) | ⚠️ **Material risk — see §4** | No file-blob sync infrastructure exists. Reports/plots must live as table rows (TEXT + base64 BLOB) to reach the Render dashboard. See "Plot storage strategy" decision. |
| **R5** | Historical runs browsable (table of past runs) | ✅ Clean | Standard `GET /api/diagnostics/runs?limit=20&type=&status=` endpoint + table component. Mirrors the `StrategyResearch.jsx` expand-on-click pattern. |
| **R6** | Status polling without websockets | ✅ Clean | TanStack Query with `refetchInterval` (same as `Layout.jsx:94` uses `refetchInterval: 30000` for status). Polling ticks down to 5s only while any run is `queued`/`running`; reverts to 30s (or stops) when all terminal. |
| **R7** | Reuse existing components; no new npm deps unless approved | ⚠️ Partial | `react-markdown` + `remark-gfm` operator-approved as new deps. No other new deps needed: `DataTable`-style patterns already exist, `StatusBadge` already exists, TanStack Query already present. |

**Bottom line:** R1, R2, R3, R5, R6 satisfy cleanly on existing infrastructure. R4 is the sprint's primary technical risk; R7 has one approved exception.

---

## 3. Architectural findings from existing code

### 3.1 `src/commands/executor.py` — the real extension point

- `COMMAND_HANDLERS` dict at `executor.py:277` maps kebab-case names to handler fns. Currently 14 entries (spec claimed 10 — stale count, immaterial).
- Each handler signature: `def _handle_X(payload: dict, config: dict) -> dict` returning a result dict.
- Simulation handler (`executor.py:264-274`) is the template for long-running subprocess commands: `subprocess.run([sys.executable, "scripts/X.py", ...], capture_output=True, text=True, timeout=7200)`.
- Safety invariants: commands rate-limited to 10/min, expire after 5 min of queue age, results truncated to 10KB before storing in `command_results`. **Execution duration itself is not capped by the executor** — only by the subprocess's `timeout=`.
- `_store_result` writes to `command_results` (generic audit) and updates `pending_commands.status` to `completed`/`failed`.

### 3.2 `scripts/diagnostics/regime_diagnostic_v1.py` — the regime CLI surface

- 224 lines. Args: `--db`, `--output`, `--plot-dir`, `--bootstrap-n`, `--exclude-quarantined`.
- Output defaults: `docs/diagnostics/regime-{today}.md` and `docs/diagnostics/regime-{today}/` — **shared path space per calendar date**. Two runs on the same day collide unless explicit `--output` is passed.
- Internal `results` dict (line 167-177) has rich structure: `decision`, `decision_rationale`, `n_total`, `mean_excess`, `aggregate_ci`, `a1_vix`, `a2_days`, `a3_sector`, `a4_hour`, `a5_holding`. Summary extraction should prefer re-invoking the script's data layer over regex-parsing the markdown.

### 3.3 `scripts/diagnostics/forensic_trade_audit_v1.py` — the forensic CLI surface

- 1553 lines. Args: `--output`, `--plot-dir` (**both required**, no defaults). This asymmetry with regime matters for the dashboard: handlers must supply paths explicitly.
- Reports use `## Executive Summary` section header (regime does too) — consistent parse target.

### 3.4 Render sync — files do not sync, only table rows

- `src/sync/render_sync.py` is tables-only. Every 120s it pushes new/changed SQLite rows to Postgres via per-table strategies (`incremental`, `latest_only`, `full`).
- **No file or blob sync mechanism exists.** Files on the local filesystem are invisible to the Render cloud dashboard.
- **Implication:** if a markdown report and PNG plots live as files, the Render dashboard cannot display them. They must become row content.

### 3.5 Local API binds `127.0.0.1` only

- Per `CLAUDE.md`: "Local API binds to 127.0.0.1 only — not exposed to network." Proxying plot downloads from Render → local API is not feasible. Reinforces §3.4 conclusion.

### 3.6 Frontend visual pattern — `StrategyResearch.jsx`

- 262 lines. `p-6` container, `h1 text-2xl font-semibold`, sections with `h2`.
- TanStack Query `useQuery` for each data fetch; enabled-gated secondary queries for drill-down.
- Table: `<table className="w-full text-sm">` with `bg-gray-100` header, `cursor-pointer hover:bg-gray-50 border-t` rows, expand-on-click pattern.
- Uses existing `StatusBadge` component (import from `./StatusBadge`).

---

## 4. Identified risks

### R4.1 — Plot storage strategy [MATERIAL]

**Problem:** R4 requires inline plot rendering on the Render dashboard, but render_sync doesn't move files.

**Options considered:**

- **A. Store plots as base64 TEXT in a sibling table `diagnostic_run_plots(run_id, filename, content_b64, sort_order)`** — one row per plot. Each plot is ~100-300 KB raw → ~130-400 KB base64. Six plots per regime run → ~1-2 MB total. Postgres TEXT handles this. Syncs cleanly via existing incremental sync. **Recommended.**
- **B. Store plots as binary BLOB on `diagnostic_runs.plots_blob`** — single JSON-of-b64 blob. Simpler schema but larger single-row updates; harder to sync incrementally if a plot is patched.
- **C. Skip plot sync; dashboard shows report text only, with a "download on local machine" note** — degrades R4 to text-only. Fallback if A/B prove problematic.

**Impact if ignored:** R4 silently degrades (operator sees "report generated" but no images); sprint fails pass/fail criteria #1.

**Recommendation:** A. Requires a new `diagnostic_run_plots` table, but schema is single source of truth so additive cost is low.

### R4.2 — Report markdown size [LOW]

**Problem:** Forensic report is ~20-40 KB of markdown; regime is ~15-25 KB. `command_results.result_json` truncates at 10KB, but `diagnostic_runs.report_markdown TEXT` has no hard cap. Postgres TEXT column allows up to 1 GB; practical concern is sync bandwidth.

**Mitigation:** None needed. A 40KB report every 3-5 min of operator activity is trivial.

### R4.3 — Subprocess timeout vs. executor expiry [LOW]

**Problem:** Regime takes 3-5 min (10k bootstrap resamples). Command `EXPIRY_SECONDS = 300` in executor. If watch loop is idle when command is created and picks it up at 4:55 into the 5-min window, it could expire mid-execution.

**Mitigation:** `expires_at` is checked only at dispatch (`_is_expired` at `executor.py:84`). Once dispatched, the handler runs to subprocess completion regardless. So expiry is not a live risk — just a consideration for command freshness on the queue.

**Action:** Set subprocess `timeout=900` (15 min) to leave headroom for slower machines; no executor change needed.

### R4.4 — Dedup race at API insert [LOW]

**Problem:** `SELECT … WHERE status IN ('queued','running')` followed by `INSERT` is not atomic. Two POST requests within ~5ms could both pass the check and both insert.

**Mitigation:** Single-operator UI + frontend button-disable-while-pending makes this a <1/year event. Acceptable. If hardening needed, wrap in SQLite transaction with `BEGIN IMMEDIATE`.

### R4.5 — Two runs on same date collide on filesystem [LOW]

**Problem:** `regime_diagnostic_v1.py` default `--output` is `docs/diagnostics/regime-{today}.md`. Dashboard re-runs on the same day overwrite the prior file.

**Mitigation:** Handler always passes explicit `--output docs/diagnostics/regime-{run_id}.md` and `--plot-dir docs/diagnostics/regime-{run_id}/`. Use the dashboard-assigned `run_id` as the uniqueness namespace. The files become transient staging — the canonical copy lives in the `diagnostic_runs` table rows.

### R4.6 — Serial executor blocks queue during run [LOW]

**Problem:** A 5-min regime run blocks other commands in the queue. If an operator clicks "halt trading" while a diagnostic is running, it waits 5 min.

**Mitigation:** Operator UX issue, not correctness. Accept for v1. If needed in future, split executor into a type-aware worker pool. Not this sprint.

### R4.7 — Summary extraction fragility [LOW]

**Problem:** Spec's fallback says "If parsing fails (report format drift), fall back to storing raw executive summary text."

**Mitigation:** Better approach — have the handler use the diagnostic script's internal `results` dict (`regime_diagnostic_v1.py:167`) directly rather than regex-parsing the markdown it just wrote. Two viable paths:

- **Preferred:** Expose `run_diagnostic(args) -> results_dict` as a library entry point in `src/diagnostics/report.py` (or a new `src/diagnostics/runner.py`). Handler calls it directly, gets the dict, writes summary fields and the rendered markdown. No parsing.
- **Fallback:** Keep the subprocess approach, parse `## Executive Summary` via regex in `src/diagnostics/summary_extractor.py`. Covered by the spec's original plan.

Operator decision needed on which path (§5 decision #3).

---

## 5. Operator decisions needed

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Plot storage strategy (§4.1) | A: sibling `diagnostic_run_plots` table; B: single BLOB on `diagnostic_runs`; C: skip plot sync | **A** |
| 2 | Nav group placement | `Intelligence` (next to Training, Council, Model Perf) or `System` (next to Validation, Health, Monitoring) | **Intelligence** — diagnostics are research/decision tools, not ops tools |
| 3 | Summary extraction path | Library refactor (handler calls `run_diagnostic(args) -> dict` directly) vs. subprocess + regex parse | **Subprocess + regex** for v1 — keeps blast radius small; library refactor is a worthwhile v0.26 followup but doubles sprint scope |
| 4 | Polling cadence | 5s (spec default) vs. 3s (more responsive) vs. 10s (less load) | **5s** while any run active; stop polling when terminal |
| 5 | Retention policy | Keep forever vs. age out after 90d vs. keep last 50 | **Keep forever for v1** — diagnostic runs are small (one row per run + ≤6 plot rows); delete tooling is a v0.26 followup if volume becomes a concern |
| 6 | Trigger-source labeling | `trigger_source='dashboard'` for button clicks; for CLI invocations, do we retrofit the CLI to write `diagnostic_runs` rows? | **Dashboard writes rows, CLI does not for v1**. CLI users already have the markdown file. Retrofit CLI in a followup if we want unified history. |
| 7 | Failure UX | Error banner at top of page vs. toast vs. Telegram push vs. all three | **Error banner + Telegram** — use existing `platform_events.py` pattern for Telegram, inline banner for in-page feedback |
| 8 | Run naming | Auto `run_id = uuid4()` (spec) vs. human-readable like `regime-2026-04-18-a` | **UUID** — uniqueness matters more than readability; UI can truncate to 8 chars for display |

---

## 6. Non-goals (verbatim from spec, explicit)

- **Not parameter-tuning UI.** `--bootstrap-n`, `--exclude-quarantined`, FDR q, sector bucket config all stay at script defaults when invoked from the dashboard. CLI override flags remain for advanced users.
- **Not time-series comparison.** Trend of CONTAMINATED across re-runs is a v0.26.x feature.
- **Not scheduled auto-runs.** Operator-click-triggered only.
- **Not email notifications.** Telegram via existing `src/notifications/platform_events.py` is sufficient.
- **Not multi-user concurrency UI.** Single-operator system.
- **Not historical export.** View inline only; CSV export is a followup.

---

## 7. Proposed sequence for Pass 2 and Pass 3

### Pass 2 — research before code (≈20 min)

Confirm / deepen:

1. Schema registry `TableDef` shape (read `registry.py:1-100` + one recent additive example).
2. `sync_config.py` generation — does a table automatically get sync'd if it has `created_at`? What `sync_mode` should `diagnostic_runs` use? (`incremental` based on `created_at`, most likely.)
3. Read a recent command handler that returns rich data (e.g., `_handle_validate_system`) to confirm the envelope the dashboard displays.
4. `api/cloud_routes/core.py` — how is the cloud side of `pending_commands` currently populated? (API POST → Postgres row → render_sync pulls to local.)
5. Frontend: `frontend/src/api.js` — confirm `axios`/`fetch` pattern and whether `IS_CLOUD` affects request routing.
6. Confirm `react-markdown` + `remark-gfm` latest stable versions (current is `react-markdown@9.x`, `remark-gfm@4.x` as of 2026-01).
7. Smoke-check `docs/diagnostics/` directory for existing markdown — is it safe for handlers to write transient files here, or should we use a scratch dir?

Output: Pass 2 findings committed as `docs/sprints/diagnostic_dashboard_v1_pass2_research.md`, linking to code paths with line numbers.

### Pass 3 — implementation (≈45 min if operator decisions resolved)

Sequence:
1. Schema: add `diagnostic_runs` + `diagnostic_run_plots` TableDefs to `registry.py`. Run `validate-schema --fix`. Run `render_migrate.py`.
2. Backend: `summary_extractor.py`, new handlers in `executor.py`, new `cloud_routes/diagnostics.py`, dashboard-sync logic (if any new code needed beyond auto-sync).
3. Tests: handler unit tests, API integration tests, extractor tests with both regime and forensic sample markdown.
4. Frontend: `Diagnostics.jsx` + 3 components, `api.js` additions, `App.jsx` route, `Layout.jsx` nav item.
5. Install `react-markdown` + `remark-gfm`.
6. End-to-end smoke test.
7. Update MASTER.md (new table + new page); CHANGELOG for v0.25.0.

### Pass 3 — refinement before PR

Self-review R1-R7 satisfaction in PR body; screenshot; verify no CI guardrail violations; run full pytest at least once.

---

## 8. Files Pass 3 will touch (preview)

### Create
- `src/diagnostics/summary_extractor.py` — parse `## Executive Summary` for regime (decision, N, mean excess) and forensic (findings summary)
- `src/api/cloud_routes/diagnostics.py` — six endpoints
- `tests/api/test_diagnostics_routes.py` — ≥8 tests
- `tests/test_diagnostic_handlers.py` — ≥6 tests
- `tests/diagnostics/test_summary_extractor.py` — new
- `frontend/src/pages/Diagnostics.jsx`
- `frontend/src/components/DiagnosticRunTable.jsx`
- `frontend/src/components/DiagnosticRunDetail.jsx`
- `frontend/src/components/DiagnosticKickoffButtons.jsx`

### Modify
- `src/schema/registry.py` — add `diagnostic_runs` + `diagnostic_run_plots`
- `src/commands/executor.py` — add two new `_handle_*` fns + dict entries
- `frontend/src/api.js` — add diagnostic API calls
- `frontend/src/App.jsx` — register `/diagnostics` route
- `frontend/src/components/Layout.jsx` — add nav item to Intelligence group
- `frontend/package.json` — add `react-markdown`, `remark-gfm`
- `docs/MASTER.md` — new table + new page documentation
- `CHANGELOG.md` — v0.25.0 entry

All files will stay under 400 lines; all functions under 60 lines (per CLAUDE.md guardrails).

---

## 9. Operator review gate

**Pass 1 is complete pending your review.** Before I start Pass 2 research, please confirm:

- [ ] Decisions #1–#8 in §5 — do you accept my recommendations, or override?
- [ ] R4 plot-storage approach (sibling table) — acceptable?
- [ ] Intelligence nav group — correct bucket?
- [ ] Scope of v1 non-goals (§6) — anything to pull forward or defer further?
- [ ] Any risks in §4 you want mitigated now rather than accepted?

Once you sign off, I'll proceed to Pass 2 research. Pass 2 deliverable is a shorter follow-up doc with verified answers to §7.1–§7.7, then onward to Pass 3 implementation.
