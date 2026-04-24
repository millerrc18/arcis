# docs/archive/

Archived documentation moved here during Sprint A (April 2026) when MASTER.md was created as the single consolidated governance document.

## What was moved and why

### governance/ (absorbed into MASTER.md)

| File | Original Location | Absorbed Into |
|---|---|---|
| SYSTEM_STATE.md | repo root | MASTER.md Sections 2, 5, 6, 7, 8, 11 |
| AGENTS.md | repo root | MASTER.md Sections 1, 3, 4, 9, 12 |
| conventions.md | docs/ | MASTER.md Section 9 |
| sprint-checklist.md | docs/ | MASTER.md Section 9 |
| schema-governance.md | docs/ | MASTER.md Section 4 |

### reference/ (superseded by source of truth)

| File | Why Archived |
|---|---|
| architecture.md | Stale module registry; interactive diagram at halcyonlab.app/architecture replaces it |
| database-schema.md | Schema registry (`src/schema/registry.py`) is the single source of truth |
| dependency-graph.md | Stale within hours of any code change |
| roadmap.md | Dashboard Roadmap page is the live version |
| roadmap-complete.md | Superseded by dashboard Roadmap page |
| diagrams.md | Replaced by React Flow interactive diagrams |

## Policy

- **Do not delete archived files** — git history matters for traceability
- **Do not update archived files** — they represent a point-in-time snapshot
- **All new governance updates** go into MASTER.md

---

# Friday 2026-04-24 Bootcamp DB Archive — Operator README

> This section is separate from the documentation archive above. It describes the **database archive** created at the Phase 1 → Phase 2 cutover on Friday 2026-04-24, which lives at `C:/arcis/data/archive/` (outside the repo), not in this `docs/archive/` directory. The three files described below are the runtime archive artifacts; this README is the only in-repo reference.

## 1. Purpose

This section documents the Friday 2026-04-24 bootcamp DB archive plus its manifest and SHA-256 sidecar, produced by `scripts/archive_bootcamp_2026_04_24.py`. The archive is a point-in-time `VACUUM INTO` copy of the production SQLite DB captured at the moment of the Phase 1 → Phase 2 cutover, preserved indefinitely as the sole witness of pre-cutover state.

## 2. When and how was the archive created?

- **Date:** 2026-04-24 (Friday), post-market.
- **Trigger:** operator-run `python scripts/archive_bootcamp_2026_04_24.py --apply` after first running `--dry-run` and reviewing the plan output.
- **Primitive:** SQLite `VACUUM INTO '<archive-path>'`. Rationale (defragmented single file, no `-wal`/`-shm` sidecar trap, equivalent safety to `.backup()` but better output shape for a long-lived archive) is in [Pass 1 §1](../sprints/friday_archive_sprint_evaluation.md#1-archive-primitive-choice) — not duplicated here.
- **Preflight:** the script verifies the watch loop is halted via four independent mechanisms before it will write a byte. Mechanisms are enumerated in [Pass 1 §3](../sprints/friday_archive_sprint_evaluation.md#3-watch-loop--render-sync-detection). Archive refuses (non-zero exit) if any check fails.
- **Expected duration:** ~17–21 s linear extrapolation, budget 5 minutes end-to-end including stop/verify/restart. See [Pass 2 §3](../sprints/friday_archive_sprint_research.md#3-vacuum-into-actual-timing).

**Output layout at `C:/arcis/data/archive/`:**

| File | Description |
|---|---|
| `ai_research_desk_bootcamp_2026-04-24.sqlite3` | The archive DB — VACUUMed, single file, no `-wal`/`-shm` sidecars |
| `ai_research_desk_bootcamp_2026-04-24.sha256` | One line: `<sha256-hex>  <filename>` (for external integrity checks) |
| `ai_research_desk_bootcamp_2026-04-24.manifest.json` | Manifest with row counts, preflight context, and prod-only column breadcrumbs (see §5) |

## 3. How to access bootcamp data

Three access paths, in order of preference:

1. **Read-only SQLite CLI (canonical):**
   ```bash
   sqlite3 -readonly C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3
   ```
2. **Python (read-only, URI mode) — preferred for scripts:**
   ```python
   import sqlite3
   conn = sqlite3.connect(
       "file:C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3?mode=ro",
       uri=True,
   )
   ```
   Read-only is **mandatory**, not advisory. See `CLAUDE.md` → "Database Access Rules" for why external tools holding file locks on a live DB burned an afternoon of lock-contention debugging.
3. **Render Postgres dashboards:** historical Postgres rows with `created_at < '2026-04-24'` are queryable via `psql` or the Render web console.
   > **Caveat:** the dashboard "Bootcamp history" view **is not currently wired** — per [Pass 2 §6.2](../sprints/friday_archive_sprint_research.md#62-dashboard-wiring-status--classification-c-no-wiring-exists), no frontend route or API endpoint exposes it as of the cutover. Do not look for a UI that does not yet exist. Query Postgres directly until the dashboard catches up.

## 4. How to verify an existing archive

```bash
python scripts/archive_bootcamp_2026_04_24.py --verify C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3
```

What it does: re-hashes the archive file with SHA-256, compares against the manifest's `sha256` field, re-counts the tables listed in `row_counts` (`shadow_trades`, `training_examples`, `bracket_health`, `sync_state`), and compares those counts to the manifest. Exit code **0** = OK; exit code **2** = mismatch (SHA drift or row-count drift). Any non-zero exit means the archive has been mutated since cutover — investigate before trusting it.

## 5. Manifest contents

The manifest is a single JSON object written atomically alongside the archive. Fields:

| Field | Meaning |
|---|---|
| `archive_path` | Absolute path to the archive DB at write time |
| `source_path` | Absolute path to the production DB that was archived |
| `archive_timestamp_et` | ISO-8601 timestamp, America/New_York timezone |
| `file_size_bytes` | Size of the archive file in bytes |
| `sha256` | SHA-256 hex digest of the archive file (also in the `.sha256` sidecar) |
| `row_counts` | Row counts for `shadow_trades`, `training_examples`, `bracket_health`, `sync_state` (parity vs. source verified pre-write) |
| `arcis_db_path_at_archive_time` | Value of `ARCIS_DB_PATH` in the archive process's environment |
| `watch_loop_process_state` | NSSM service status at preflight (expected: `SERVICE_STOPPED`) |
| `render_sync_state` | `{last_synced_at, staleness_verdict}` from the `sync_state` table |
| `alpaca_positions_open` | List of open Alpaca positions at cutover (empty = clean) |
| `prod_only_columns_preserved` | **See below** — 17 columns across 6 tables that exist in prod but NOT in `src/schema/registry.py`. The archive preserves them verbatim; the post-cutover fresh DB does not reintroduce them. |

**Highlight — `prod_only_columns_preserved`:** a deliberate breadcrumb. If a historical analysis ever depends on a column that exists in the bootcamp DB but not in the current registry, the enumeration in this manifest is how an operator discovers it. The manifest contains the exact list; do **not** duplicate that enumeration here — read the manifest (`ai_research_desk_bootcamp_2026-04-24.manifest.json` → `prod_only_columns_preserved`). Drift context and classification live in [Pass 2 §2](../sprints/friday_archive_sprint_research.md#2-schema-drift-actual-check).

## 6. Retention policy

**Indefinite.** The archive DB, manifest, and SHA-256 sidecar are all preserved. Do **NOT** delete any of the three without a documented retention-policy decision filed alongside the deletion. As of the cutover, the archive is the only witness of pre-cutover state AND the only machine-readable record of the 17 prod-only columns. Losing it is unrecoverable.

## 7. Operator choreography (cutover)

> ⚠️ **CRITICAL — `ArcisWatchLoop` is the ONLY NSSM service to halt.**
> The `RenderSyncThread` that pushes to Postgres is an in-process **daemon thread** inside the watch-loop process (`src/sync/render_sync.py:812` sets `daemon=True`). `nssm stop ArcisWatchLoop` transitively halts the sync thread — it dies with its parent. **Do not look for a second service to manage. It does not exist.**

Condensed step-by-step, mirroring [Pass 1 §4](../sprints/friday_archive_sprint_evaluation.md#4-cutover-atomicity):

1. **Stop the watch loop:** `nssm stop ArcisWatchLoop` and wait for the command to return.
2. **Verify no `python.exe` has the DB open.** Use at least one method (two preferred) from CLAUDE.md → "Startup / Restart Sequence":
   - PowerShell: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'src\.main|watch|dashboard' }` — expected empty.
   - Sysinternals: `handle.exe -a -nobanner ai_research_desk.sqlite3` — expected no rows.
   - Confirm `data/watch.lock` is gone.
3. **Run the archive:** `python scripts/archive_bootcamp_2026_04_24.py --apply`. Script performs preflight (4 signals), `VACUUM INTO`, SHA-256, manifest write, fresh-DB anchor creation.
4. **Verify archive:** the script self-verifies before exiting, but confirm externally that the archive directory contains exactly three files (`.sqlite3`, `.sha256`, `.manifest.json`), the SHA in the sidecar matches `manifest.json → sha256`, and `row_counts` match the expected pre-cutover counts.
5. **Edit `.env` if the fresh DB path differs from the source path.** In the default `--apply` mode the fresh DB is written back to `ARCIS_DB_PATH` (same location as source), so this step is **typically a no-op**. If you used `--fresh-path` or `--fresh-only` to relocate the fresh DB, update `C:\arcis\halcyon-lab\.env` → `ARCIS_DB_PATH=<new-path>`.
6. **Audit NSSM service env:** `nssm dump ArcisWatchLoop | findstr AppEnvironmentExtra`. Expected: no match. If `AppEnvironmentExtra` pins `ARCIS_DB_PATH`, service env overrides `.env` — update via `nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=<new-path>` or remove the pin.
7. **Start the watch loop:** `nssm start ArcisWatchLoop`.
8. **First-scan verification:** follow the checklist in [Pass 2 §6](../sprints/friday_archive_sprint_research.md#6-post-archive-first-scan-verification) — zero active shadow trades, zero training examples, clean scan cycle, matching Postgres history counts.

## 8. Known caveats

- **173 type-affinity mismatches** between prod and registry (from [Pass 2 §2](../sprints/friday_archive_sprint_research.md#2-schema-drift-actual-check)): prod declares some columns `TEXT` where registry declares `REAL`/`INTEGER`. SQLite's loose affinity coercion hides most issues. **Does NOT affect this archive operation** — archive is row-level, not a schema rebuild. It IS a blocker for any future "rebuild from registry and backfill" work. Separate follow-up issue.
- **Dashboard "Bootcamp history" view is not yet wired** ([Pass 2 §6](../sprints/friday_archive_sprint_research.md#62-dashboard-wiring-status--classification-c-no-wiring-exists)). Until the frontend/API catches up, read historical Postgres rows directly via `psql` or the Render console.
- **Windows sqlite3 file-handle lifecycle (from T2 of this sprint).** The archive script explicitly closes every `sqlite3` connection and applies `gc.collect()` + retry-on-unlink. Any refactor that reintroduces `with sqlite3.connect() as conn:` as a supposed "close on exit" pattern risks regression: the context manager only commits — it does **NOT** close the connection. Flagged here for future maintainers who might try to "clean up" the explicit-close pattern.

## 9. Rollback

If a problem surfaces hours or days after cutover and the decision is to restore the bootcamp DB as the active DB, follow the step-by-step rollback procedure in [Pass 2 §5](../sprints/friday_archive_sprint_research.md#5-rollback-procedure). Do **not** improvise. The rollback doc covers preconditions, audit note requirements, WAL/SHM handling, Option A (pre-archive backup, preferred) vs. Option B (copy from the archive — never move), integrity verification, and the rollback-window decay curve (rollback cost grows with every hour of post-cutover divergence).

## 10. References

**Sprint docs (Pass 1 & 2):**
- [`docs/sprints/friday_archive_sprint_evaluation.md`](../sprints/friday_archive_sprint_evaluation.md) — Pass 1 (evaluation)
- [`docs/sprints/friday_archive_sprint_research.md`](../sprints/friday_archive_sprint_research.md) — Pass 2 (research)

**Script and tests:**
- `scripts/archive_bootcamp_2026_04_24.py` — the archive script
- `tests/scripts/test_archive_bootcamp_2026_04_24.py` — verification parity, preflight signals, and Windows file-handle lifecycle tests

**PRs:**
- This sprint's PR (to be opened at T5)
- Hotfix PR #670 — Telegram redaction restoration (unrelated but merged in the same window)

**Follow-up issues:**
- `sync_state` in-flight fields (no `started_at`/`status` columns today — see Pass 1 §3.2)
- 17-column prod-vs-registry reconciliation (see Pass 2 §2)
- `scripts/import_chatgpt_outputs.py` `ARCIS_DB_PATH` non-honor (see Pass 1 §2, Issue draft 3)
- Process issue #671 — CI guardrail for silent-merge-revert regressions
