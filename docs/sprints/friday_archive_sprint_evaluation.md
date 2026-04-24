# Friday Bootcamp Archive Sprint — Pass 1 Evaluation (SD#42)

> **Sprint:** Friday Bootcamp Archive Sprint (SD#42)
> **Branch:** `feat/bootcamp-archive-friday`
> **Date:** 2026-04-24
> **Pass:** 1 of 2 (evaluation). Pass 2 = research with empirical checks. Pass 3 (archive script + tests + archive README + CHANGELOG + follow-up-issue filing) is operator-gated and out of scope for this sprint.
> **Source commit when evaluation was written:** `95e439c` (HEAD of `feat/bootcamp-archive-friday` at branch cut)

---

## 1. Archive primitive choice

<!-- SECTION:P1.1 START -->

### Decision

**Recommended primitive: `VACUUM INTO 'target_path'`** executed via a short-lived `sqlite3` connection once the watch loop has been halted. (See "Watch-loop halt requirement" below — this is not optional.)

### Precedent in the codebase

Grep evidence (run 2026-04-24 against `feat/bootcamp-archive-friday`):

| Pattern | `src/` hits | `scripts/` hits |
|---|---|---|
| `VACUUM INTO` (case-insensitive) | 0 | 0 |
| `.backup(` | 1 (`src/scheduler/watch.py:1047`) | 0 |

There is **no existing precedent for `VACUUM INTO`** anywhere in `src/` or `scripts/`. There is one precedent for the Python Online Backup API: `WatchLoop._backup_database` (`src/scheduler/watch.py:1035-1058`) calls `src.backup(dst)` for daily rolling backups. That code is instructive (it also opens `sqlite3.connect(DB_PATH)` without the `src.utils.db.connect_db()` helper, so it inherits SQLite's default 5 s `busy_timeout` rather than our project-standard 30 s). It is, however, a backup — not an archive — and the sprint goal is a **point-in-time, VACUUMed, defragmented archive** of the full DB.

### Comparison

| Dimension | (a) `VACUUM INTO 'path'` | (b) `sqlite3.Connection.backup()` | (c) OS file copy (`shutil.copy2` / `cp`) |
|---|---|---|---|
| **Safety under concurrent writers** | Takes a shared read transaction for the duration of the copy; writers may be blocked or fail on `SQLITE_BUSY` for large DBs. Safe only if the DB is quiescent. | The Online Backup API iterates pages under a read lock, periodically yielding; handles writers on the *source* gracefully (restarts the copy if the source changes). Documented as the "correct" way to copy a live DB. | **Unsafe** even with `busy_timeout`. The `.sqlite3` file plus `-wal` and `-shm` sidecars are a three-file set; copying them non-atomically (or copying only the main file) yields a corrupt or stale DB. |
| **Output shape** | Produces a **fully VACUUMed, defragmented, page-aligned** single file with no `-wal`/`-shm` sidecars. Equivalent to a fresh DB with the same schema + rows. Size will typically be smaller than source. | Produces a byte-level page copy; **not** VACUUMed — retains free-list fragmentation and current page size. Single file, no sidecars (the destination is opened fresh). | Produces whatever was on disk at copy time: main file + possibly-stale sidecars. Not VACUUMed. Page-aligned only if fsync'd cleanly. |
| **Operator simplicity** | One SQL statement: `VACUUM INTO '/path/to/archive.sqlite3';`. Runs inside a single `sqlite3` CLI or Python call. Easiest to reason about in an archive script. | Requires a Python wrapper (open source + dest connections, call `.backup()`, close both). Straightforward but more moving parts than one SQL statement. | Trivial shell command — but the simplicity is a trap (see Safety row). |
| **Recoverability if interrupted** | If the process is killed mid-`VACUUM INTO`, the partial destination file is incomplete but the **source DB is untouched** (the write happens on the destination only). Delete partial file and retry. | Partial destination file on interrupt; source untouched. Destination can be resumed only by starting fresh. Same "delete and retry" recovery as (a). | Partial file on interrupt; if sidecars are split across the copy window the result is a silently-corrupt archive. "Recoverability" is the *detection* problem — you may not notice corruption until you try to open the archive. |

### Why the watch loop MUST be halted (regardless of primitive)

The watch loop holds open `sqlite3` connections for data collection, shadow trading reconciliation, scheduler state, and activity logging. Even for `VACUUM INTO` and `.backup()` — both of which are documented as concurrency-safe on a *correctly-configured* WAL-mode DB — running an hour-long full-DB copy against a live writer will produce `SQLITE_BUSY` retries, inflate WAL size (WAL cannot checkpoint while a long read is pinned), and risk operator-visible latency spikes in the watch loop's own work. The sprint goal is a clean point-in-time snapshot; the only defensible way to get that is to stop the writer first.

**Halt procedure (per `CLAUDE.md` and `reference_watchloop_nssm.md`):** `nssm stop ArcisWatchLoop`, verify `data/watch.lock` is gone, confirm no stray `python.exe ... watch` processes, then run the archive. Restart via `nssm start ArcisWatchLoop` when done.

### Why a raw OS copy is unsafe even when the loop is halted

WAL-mode SQLite is a three-file scheme: `<db>.sqlite3`, `<db>.sqlite3-wal`, `<db>.sqlite3-shm`. Committed pages may live in the `-wal` file and have not yet been checkpointed into the main file. A naive copy of only the `.sqlite3` file produces a DB that is missing recent committed transactions. Copying all three files non-atomically risks a skewed trio (main file from T0, `-wal` from T1). Even after `nssm stop ArcisWatchLoop`, unless a clean shutdown has forced a WAL checkpoint and the OS has fsync'd the pages, the `-wal`/`-shm` files can contain state that `shutil.copy2` captures inconsistently. `VACUUM INTO` sidesteps this entirely: SQLite reads all committed pages through its own transaction layer and writes a fresh file, sidecars not involved.

### Justification

`VACUUM INTO` wins on **output shape** (defragmented, single-file, no sidecar trap) and **operator simplicity** (one SQL statement in an archive script), and is tied with `.backup()` on safety and recoverability. The defragmentation matters here: the archive is intended to be a long-lived reference artifact, not a hot-swappable backup, so paying the VACUUM cost once at archive time is the right trade. `.backup()` remains the correct choice for the *existing* daily rolling-backup code path in `watch.py` (where speed and live-writer tolerance matter more than file size), and this evaluation does not propose changing that.

### Citation

- SQLite `VACUUM INTO` reference: <https://www.sqlite.org/lang_vacuum.html#vacuuminto>
- SQLite Online Backup API reference (for the `.backup()` precedent): <https://www.sqlite.org/backup.html>
- SQLite WAL mode reference (for the `-wal`/`-shm` sidecar discussion): <https://www.sqlite.org/wal.html>

<!-- SECTION:P1.1 END -->

---

## 2. Hardcoded DB path audit

<!-- SECTION:P1.2 START -->

**Method.** Grep the literal string `ai_research_desk.sqlite3` across `src/` and `scripts/`, then read a context window around each hit and classify:

- **(a) CORRECT** — canonical constant at `src/config/__init__.py:56` or call sites that respect `ARCIS_DB_PATH` using the same resolution pattern.
- **(b) BUG** — hardcoded fallback that ignores `ARCIS_DB_PATH` and/or uses a CWD-relative default that does not match the repo-root-anchored `DB_PATH`. CWD-escapes in prod because `.env` puts the canonical DB outside the repo (`C:/arcis/data/ai_research_desk.sqlite3`).
- **(c) FINE** — docstrings, comments, diagnostic/operator one-offs with deliberate fallback chains, or hardcoded absolute paths that match the prod layout and are not called by the watch loop.

**Grep command (Grep tool, pattern `ai_research_desk\.sqlite3`, output_mode `content`, -n true):**

- `path: src/` → 3 hits
- `path: scripts/` → 16 hits
- **Total: 19 hits**

**Found 5 category (b) bugs:**

1. `src/services/mr_scan_service.py:78` — reachable in production (watch-loop MR scan hot path)
2. `scripts/export_chatgpt_inputs.py:25` (with `:75` argparse mirror) — not reachable from the watch loop; operator-invoked
3. `scripts/import_chatgpt_outputs.py:34` (with `:89` argparse mirror) — not reachable from the watch loop; operator-invoked
4. `scripts/render_architecture_doc.py:153` — not reachable from the watch loop; sprint-time doc-gen
5. `scripts/schema_report.py:125` — not reachable from the watch loop; standalone CLI default

**Audit table.**

| file:line | code excerpt | class | reason |
|---|---|---|---|
| `src/config/__init__.py:56` | `DB_PATH = os.environ.get("ARCIS_DB_PATH", str(_REPO_ROOT / "ai_research_desk.sqlite3"))` | (a) | Canonical constant — the single authoritative definition. |
| `src/utils/activity_logger.py:54` | `# fake kill_switch_halt rows into the prod ai_research_desk.sqlite3` | (c) | Comment only, inside the `log_activity` test-pollution guard. No code path. |
| `src/services/mr_scan_service.py:78` | `_db = config.get("db_path", "data/ai_research_desk.sqlite3")` | **(b)** | CWD-relative dict-default fallback. Ignores `ARCIS_DB_PATH` whenever the caller's `config` dict lacks `db_path`. Called inside the MR scan post-enrichment block — reachable in the watch loop. See enumeration below. |
| `scripts/cleanup_test_pollution_647.py:74` | `return str(repo_root / "data" / "ai_research_desk.sqlite3")` | (c) | Final fallback in a 4-stage resolver (`--db-path` arg → `ARCIS_DB_PATH` env → `.env` parse → repo-relative). Operator one-off for issue #650. |
| `scripts/diagnose_leakage.py:28` | `DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]` | (c) | Interactive operator diagnostic. Size-filtered `DB_CANDIDATES` probe rooted at `REPO_ROOT`. Does not honor `ARCIS_DB_PATH`, but not production. |
| `scripts/fix_training_page.py:20` | `DB_PATH = os.environ.get("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")` | (c) | Honors `ARCIS_DB_PATH`. Fallback is the absolute prod path (matches `.env`), not CWD-relative. One-off fix script. |
| `scripts/export_chatgpt_inputs.py:25` | `def export_inputs(db_path="ai_research_desk.sqlite3", count=20, output="chatgpt_batch.txt")` | **(b)** | CWD-relative function default. No env check. |
| `scripts/export_chatgpt_inputs.py:75` | `p.add_argument("--db", default="ai_research_desk.sqlite3")` | **(b)** | CWD-relative argparse default. Mirror of `:25`. |
| `scripts/weekly_review.py:39` | `DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]` | (c) | Same `DB_CANDIDATES` probe pattern rooted at `REPO_ROOT`. Operator-invoked weekly, not watch loop. |
| `scripts/import_chatgpt_outputs.py:34` | `def import_outputs(inputs_file, outputs_file, db_path="ai_research_desk.sqlite3")` | **(b)** | CWD-relative function default. No env check. |
| `scripts/import_chatgpt_outputs.py:89` | `p.add_argument("--db", default="ai_research_desk.sqlite3")` | **(b)** | CWD-relative argparse default. Mirror of `:34`. Worse failure mode than the export sibling because this path *writes* (INSERT into `training_examples`). |
| `scripts/post_close_check.py:36` | `DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]` | (c) | Same `DB_CANDIDATES` probe. CLAUDE.md documents this script as a standard operator workflow; it is invoked from the repo root where candidates resolve. |
| `scripts/render_architecture_doc.py:10` | `- ai_research_desk.sqlite3 for the live schema report` | (c) | Docstring only. |
| `scripts/render_architecture_doc.py:153` | `schema_report = render_schema(ROOT / "ai_research_desk.sqlite3")` | **(b)** | Unconditional `ROOT / "ai_research_desk.sqlite3"` — no env check. In prod the DB lives at `C:/arcis/data/`, not repo root, so `render_schema` will raise. Doc-generation tool, not watch loop. |
| `scripts/diagnostics/regime_diagnostic_v1.py:120` | `default_db = "C:/arcis/data/ai_research_desk.sqlite3"` | (c) | Hardcoded absolute prod path as argparse default; matches `.env` canonical. Diagnostic tool, CLI-overridable. |
| `scripts/statusline.py:11` | `- ai_research_desk.sqlite3 (shadow_trades counts)` | (c) | Docstring only. |
| `scripts/statusline.py:61` | `DB = _DATA_DIR / "ai_research_desk.sqlite3"` | (a) | `_DATA_DIR` comes from `_resolve_data_root()` (see `scripts/statusline.py:40-55`), which reads `ARCIS_DB_PATH` then falls back to parsing `.env`. The canonical resolver pattern applied in an operator script. |
| `scripts/diagnostics/forensic_trade_audit_v1.py:16` | `--db C:/arcis/data/ai_research_desk.sqlite3 \` | (c) | Docstring usage example. No code path. |
| `scripts/schema_report.py:125-126` | `default="ai_research_desk.sqlite3", help="Path to the SQLite database (default: ai_research_desk.sqlite3)"` | **(b)** | CWD-relative argparse default. No env fallback. Standalone CLI; also imported as a library by `render_architecture_doc.py`, though the import path doesn't trigger the argparse default. |

**Category (b) enumeration with reachability notes** (follow-up-issue raw material for Pass 2 §4):

1. **`src/services/mr_scan_service.py:78`** — `_db = config.get("db_path", "data/ai_research_desk.sqlite3")`. **Reachable in production.** The MR scan service runs inside the watch loop. Whenever the caller's `config` dict omits a `db_path` key, the fallback resolves to a CWD-relative path, not `ARCIS_DB_PATH`. In prod the canonical DB lives at `C:/arcis/data/ai_research_desk.sqlite3` (outside the repo per CLAUDE.md "Repo Layout"), so the fallback opens an empty/new SQLite file at `<cwd>/data/ai_research_desk.sqlite3` and the VIX lookup returns no rows → `vix_val = None` → MR candidates silently inherit default VIX behaviour. Contrast the correct pattern at `src/config/__init__.py:56`: `str(_REPO_ROOT / "ai_research_desk.sqlite3")` is repo-root-anchored, not CWD-relative.

2. **`scripts/export_chatgpt_inputs.py:25` (and `:75` argparse default)** — `def export_inputs(db_path="ai_research_desk.sqlite3", …)` with `p.add_argument("--db", default="ai_research_desk.sqlite3")`. **Not reachable from the watch loop.** Operator-invoked training-data export tool. Will silently open an empty DB if invoked from any directory other than one that happens to contain a stub file of that name. Should mirror `scripts/fix_training_page.py:20` (`os.environ.get("ARCIS_DB_PATH", …)`).

3. **`scripts/import_chatgpt_outputs.py:34` (and `:89` argparse default)** — same pattern as export. **Not reachable from the watch loop.** Operator-invoked training-data import tool. Because this path *writes* (INSERT into `training_examples`), a CWD-escape would write to a freshly-created wrong DB rather than fail loudly — strictly worse failure mode than the export sibling.

4. **`scripts/render_architecture_doc.py:153`** — `schema_report = render_schema(ROOT / "ai_research_desk.sqlite3")`. **Not reachable from the watch loop.** Doc-generation tool run after sprints. `ROOT` is the repo root, but per CLAUDE.md the canonical prod DB is at `C:/arcis/data/`, so this path does not exist and `render_schema` will raise. Script docstring claims "prerequisite: SQLite database must exist" — the prerequisite isn't met on the operator box. Should honor `ARCIS_DB_PATH`.

5. **`scripts/schema_report.py:125`** — `parser.add_argument("--db", default="ai_research_desk.sqlite3", …)`. **Not reachable from the watch loop.** Standalone schema dumper. When invoked via CLI without `--db`, users must `cd` to a directory containing a file named exactly `ai_research_desk.sqlite3`. Should default to `os.environ.get("ARCIS_DB_PATH", …)` with a repo-root anchor.

**Counts:** (a) 3 · (b) 5 · (c) 11 · **total 19**. The (b) population splits into **1 production-reachable** (MR scan) and **4 operator-script-only** (all in `scripts/`).

<!-- SECTION:P1.2 END -->

---

## 3. Watch-loop + Render-sync detection

<!-- SECTION:P1.3 START -->

> **Scope note:** This section describes the detection mechanisms the Pass 3 archive script will need. **Detection is DESCRIBED only in this doc — not implemented in this sprint.** No runtime watch loop or sync state is manipulated during Pass 1/Pass 2.

### 3.1 Watch-loop detection (three layers)

The Pass 3 archive script MUST confirm no watch loop is active before moving the live SQLite DB, or it risks corrupting in-flight writes. Three independent signals, in order of authority:

**Layer 1 — PID lockfile `data/watch.lock`**

*Format (verified by direct inspection at `data/watch.lock`):* a single decimal PID written as plain text, no trailing newline, no JSON, no wrapper. Example contents: `18896`. That's the entire file.

*Writer:* `src/scheduler/watch.py:1105` — `self.LOCKFILE.write_text(str(os.getpid()))`, inside `WatchLoop._acquire_lock()` at `src/scheduler/watch.py:1083-1114`. The lockfile path is defined at `src/scheduler/watch.py:1061` as `Path("data/watch.lock")` (relative to cwd, which is the repo root for both the NSSM service and interactive runs).

*Acquisition flow (`src/scheduler/watch.py:1083-1114`):*
1. If the lockfile does not exist, write the current PID and register `atexit._release_lock`.
2. If the lockfile exists, parse the PID; if `_is_pid_alive(pid)` returns true, log an error and `sys.exit(1)`.
3. If the PID is dead (stale lockfile — common after `taskkill /F` because Windows force-kill sends no interceptable signal, per the inline comment at `src/scheduler/watch.py:1108-1112`), unlink and proceed.
4. If the file contents are not a valid int (`ValueError`), unlink and proceed.

*Release:* `_release_lock()` at `src/scheduler/watch.py:1116-1124`, registered via `atexit`. Only unlinks if the file's PID matches `os.getpid()` (prevents a stopping loop from deleting a new loop's lock).

*Existing reader the archive script can copy verbatim:* `is_watch_loop_running()` at `src/startup.py:73-91`. It already encapsulates: read-parse-int, `psutil.pid_exists()` with a fallback to `os.kill(pid, 0)`, and returns `int | None`. This is the same function the `startup` command uses to refuse double-starts.

**Layer 2 — Process-list fallback (stale lockfile with live loop under a different PID)**

Layer 1 is authoritative *when the lockfile is trustworthy*. It can lie in two directions:
- **False negative:** lockfile exists, recorded PID is dead, but a second watch-loop process is actually running (e.g. NSSM restarted the service and the new PID never got written because `_acquire_lock` saw the stale lock and unlinked it, while a race started another instance). Rare but possible.
- **False positive:** lockfile stale from `taskkill /F`, no loop running. This is the common case and Layer 1 already handles it (via `_is_pid_alive`).

For false-negative hardening, the script should also check the Windows process list directly. The canonical invocation (copied from `CLAUDE.md` → "Startup / Restart Sequence" section) is:

```powershell
powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe' and CommandLine like '%watch%'\" | Select-Object ProcessId, CreationDate | Format-List"
```

If this returns any rows, a watch loop (or something that looks like one) is running — abort the archive regardless of what the lockfile says.

**Layer 3 — NSSM service reality**

Per operator runbook memory, the watch loop is registered as a Windows NSSM service named **`ArcisWatchLoop`**. The service wraps `python -m src.main watch ...` and supervises restarts.

*Critical operator instruction that Pass 3 must surface verbatim:* if the archive needs the loop stopped, the operator must run:

```cmd
nssm stop ArcisWatchLoop
```

**Do NOT** instruct the operator to `taskkill /PID <n> /F` the Python process. NSSM interprets a PID kill as a crash and will restart the loop within seconds — the archive window never opens. Only `nssm stop` takes the supervisor out of "run" state.

After the archive completes, restart with `nssm start ArcisWatchLoop`.

*Summary of required preconditions for the archive script:*
1. `is_watch_loop_running()` from `src/startup.py` returns `None`, AND
2. The PowerShell process-list query returns zero rows, AND
3. Operator has confirmed `nssm status ArcisWatchLoop` reports `SERVICE_STOPPED` (not `SERVICE_RUNNING`, not `SERVICE_PAUSED`).

Any layer returning "active" aborts the archive.

### 3.2 Render-sync detection

The `RenderSyncThread` (`src/sync/render_sync.py:796-893`) is a **daemon thread inside the watch-loop Python process**. Consequence: if Layer 1-3 above confirm the watch loop is stopped, the Render sync is also stopped by definition — the thread dies with the process (declared `daemon=True` at `src/sync/render_sync.py:812`).

So "Render-sync detection" as a separate step only matters in two edge cases:
1. The operator stopped the watch loop but an independent `python scripts/render_migrate.py` or ad-hoc `run_sync_cycle()` call is running.
2. A prior sync cycle was interrupted mid-upsert and Postgres is in an inconsistent state (savepoints inside `_replace_latest_in_postgres` at `src/sync/render_sync.py:367-472` should have rolled this back, but verifying quiescence before archive is cheap insurance).

**`sync_state` table schema** (authoritative definition at `src/schema/registry.py:1417-1426`):

| Column | Type | Constraint |
|--------|------|------------|
| `table_name` | TEXT | PRIMARY KEY, NOT NULL |
| `last_synced_at` | TEXT | NOT NULL |

**That is the entire schema — two columns.** Registry comment (`src/schema/registry.py:1415-1416`): *"Cursor tracking for render_sync. One row per table with the last_synced_at timestamp. NOT synced to Postgres (that would be circular)."*

**Important finding — `sync_state` does NOT track in-flight state.** There is no `started_at`, no `completed_at`, no `status` column. The table is a **per-table high-water-mark cursor**, not a run tracker. It answers *"what's the newest row I've already pushed for table X?"*, not *"is a sync happening right now?"*.

In-flight detection is actually done **in-process** via `threading.Lock`:
- `RenderSyncThread._sync_lock` declared at `src/sync/render_sync.py:817`.
- Acquired non-blocking at `src/sync/render_sync.py:845` (`self._sync_lock.acquire(blocking=False)`).
- Released in `finally` at `src/sync/render_sync.py:889`.
- Purpose (per docstring at `src/sync/render_sync.py:33`, fix #130): prevent overlapping cycles when a cycle runs longer than the interval.

**This lock is not visible to an external script** — it lives in the Python process's memory. The only cross-process signals Pass 3 can use are:

*(a) Staleness check from `sync_state` (the closest thing to a quiescence query):*

```sql
SELECT MAX(last_synced_at) AS newest_cursor FROM sync_state;
```

Interpretation with wall-clock: if `newest_cursor` is within the last ~`interval_seconds` (default 120 s, config key `render.sync_interval_seconds`), a sync cycle was recently active. If it's older than `interval_seconds * 3` (matching the `stale` threshold at `src/sync/render_sync.py:831`), the sync is either stopped or stuck. In both cases it is **not currently pushing** when the cursor is old — but note the cursor advances only when rows actually sync, so a long quiet period outside market hours can make a *healthy* sync look stale. The cursor is a weak signal; Layer 1 (watch-loop absence) is the strong one.

*(b) Indirect confirmation via watch-loop absence.* Since the sync thread is a daemon of the watch-loop process, Layer 1 being clean is sufficient evidence that no sync is in-flight. Pass 3 should treat this as the primary signal and use (a) only as a sanity cross-check.

*(c) Live health endpoint (not usable from the archive script but documented here for completeness):* `RenderSyncThread.health_status()` at `src/sync/render_sync.py:827-837` returns `{"alive": bool, "last_success_seconds_ago": int, "consecutive_errors": int, "stale": bool}`. Exposed via `/health/sync`. Requires the watch loop to be running to answer — so not useful when deciding whether to archive.

**Typical sync duration (log-derived).** The codebase does not log a start/end-cycle pair with an explicit duration. Observable signals:
- Per-table row-count log at `src/sync/render_sync.py:761`: `logger.info("Synced %d rows to %s", count, table_name)`.
- Cycle-summary log at `src/sync/render_sync.py:857-861`: `logger.info("Sync cycle complete: %d rows synced, %d errors", ...)`.
- Quiet-cycle heartbeat every 30 cycles at `src/sync/render_sync.py:866-870`.

To estimate duration, compute the gap between the first `Synced … rows to <table>` line and the subsequent `Sync cycle complete` line in `C:\arcis\logs\arcis.log`. Empirically this is typically well under 60 s; the 120 s default interval is chosen to leave slack. **Pass 3 does not need an exact number** — the quiescence rule is "watch loop stopped → sync thread dead → safe to archive", not "wait N seconds after last cycle".

### 3.3 Recommended pre-archive checklist (for Pass 3)

```
1. Confirm NSSM service state:    nssm status ArcisWatchLoop       → SERVICE_STOPPED
2. Confirm no watch lockfile owner: is_watch_loop_running()          → None
3. Confirm no rogue python watch:   PowerShell Get-CimInstance query → 0 rows
4. Confirm sync cursor is cold:     MAX(last_synced_at) from sync_state
                                    → absent OR older than interval_seconds*3
5. Only then: proceed with archive cutover (see §4).
```

If any check fails, the script must refuse to archive and exit non-zero with a message that names the specific failing layer — no "I'll try anyway" fallback.

<!-- SECTION:P1.3 END -->

---

## 4. Cutover atomicity

<!-- SECTION:P1.4 START -->

### Scope of the window

The **cutover window** is the interval beginning the moment the archive script writes the VACUUMed archive file and creates the fresh empty DB, and ending only once BOTH of the following are true:

1. `ARCIS_DB_PATH` has been updated operator-side to point at the new active DB location, **and**
2. The watch loop (NSSM service `ArcisWatchLoop`) has been restarted so the new value is in its process environment.

Until step 2 completes, every Python process on the box that loads `src.config` inherits whatever `.env` / environment it was launched with. The archive on disk is a fait accompli, but the **old path** (wherever `ARCIS_DB_PATH` still points for a given process) may still be a legitimate SQLite file — typically the now-stale, pre-archive DB that was *renamed aside* before the archive, or the now-frozen archive file itself if the rename hasn't happened yet. Either way, writes to it during this window are orphaned: they happen to a file nobody will open again once the watch loop comes back on the new path.

### Where `ARCIS_DB_PATH` is resolved (citation)

All processes read the DB path through one choke point:

- **`src/config/__init__.py:44`** — `load_dotenv()` is called at module import. This loads `C:\arcis\halcyon-lab\.env` into `os.environ` **if and only if** the calling process's CWD (or an ancestor) contains a discoverable `.env`. It is idempotent but NOT re-entrant — already-set environment variables win over `.env`.
- **`src/config/__init__.py:56`** — `DB_PATH = os.environ.get("ARCIS_DB_PATH", str(_REPO_ROOT / "ai_research_desk.sqlite3"))`. One line, one lookup, cached at import for the lifetime of the process.

This means `ARCIS_DB_PATH` is resolved **once, at process start**, and is immutable for the rest of that process. No module re-reads `.env` mid-run. Consequence: editing `.env` while a process is running has **zero effect** on that process — only a fresh Python invocation picks up the new value.

### Restart-vector enumeration (the 5 categories)

For each vector: (i) is it real during the window; (ii) how it is prevented/detected today; (iii) residual exposure.

| # | Vector | Real? | Prevention / detection | Residual exposure |
|---|---|---|---|---|
| 1 | **Operator CLI run with stale env** (`python -m src.main scan`, `...validate-schema`, `...shadow-status`, etc., launched from a shell whose env still holds the old `ARCIS_DB_PATH`) | **Real.** Any CLI subcommand in `src/cli/commands.py` imports `src.config` and hits the line-56 resolution. If the operator edits `.env` but the shell was opened earlier, the shell's pre-existing `ARCIS_DB_PATH` (if any) wins over the new `.env` value; if the shell has no `ARCIS_DB_PATH`, `.env` loads cleanly and the **new** value is picked up. The dangerous case: operator forgets to edit `.env` at all and runs a CLI command out of habit. | Nothing today. No preflight hook compares process-resolved `DB_PATH` against an expected-path sentinel. Every CLI subcommand silently opens whatever `DB_PATH` resolves to. | **HIGH.** Muscle memory is the attack vector. Mitigation = the warning banner (below) + archive-mode marker file the next section (P1.7) will enumerate. |
| 2 | **NSSM service auto-restart or premature `nssm start`** | **Real.** `scripts/install_service.ps1` line 102 sets `AppExit Default Restart` — if someone only `nssm pause`s instead of `nssm stop`s, or if the service crashed mid-archive, NSSM will relaunch the watch loop on the OLD env. Even a clean `nssm stop` is reversible by any admin running `nssm start ArcisWatchLoop` before the operator has updated env and re-validated. Ten-second `AppRestartDelay` (line 106) buys a brief window but does not prevent relaunch. | `nssm stop` sets the service to STOPPED; the service does NOT auto-restart from STOPPED. The PID lockfile (`data/watch.lock`) is the secondary guard against two overlapping processes, but it does **not** guard against one process writing to the wrong DB. | **HIGH.** Must use `nssm stop` (not `pause`) and must NOT issue `nssm start` until env is updated. No programmatic interlock exists. |
| 3 | **Scheduled tasks / cron jobs / in-process schedulers** | **Partial.** There is no Windows Task Scheduler integration in-repo (grep of `scripts/` returned zero Task-Scheduler XMLs or `schtasks` calls). The `schedule` library is imported in several files but every live use (`src/scheduler/*.py`, `src/scheduler/watch.py:1182`) is a **sub-component of the watch loop** — those schedules only fire because the watch loop's main thread is calling `schedule.run_pending()`. When `nssm stop ArcisWatchLoop` halts the process, every one of those schedules dies with it. `scripts/overnight_train.py`, `scripts/collect_1min_bars.py`, `scripts/daily_repo_audit.py`, `scripts/build_event_calendar.py`, `scripts/fetch_earnings_calendar.py` all use the `schedule` library too but are **stand-alone scripts** — they run only when explicitly invoked. They are dormant until someone types their name. There is NO always-on scheduler process separate from the watch loop. | By architecture: all schedulers live inside the watch-loop process. Stopping the service stops them. | **LOW**, contingent on the operator not manually launching one of the stand-alone `scripts/*.py` during the window. Same mitigation as vector 1 (warning banner + `.env` must be correct before any Python invocation). |
| 4 | **Separate FastAPI / local API server with open DB handle** | **Real but rare.** The FastAPI app is defined in `src/api/app.py` and launched ONLY via the `dashboard` CLI subcommand (`src/cli/commands.py:1349-1353`, `uvicorn.run("src.api.app:app", host="127.0.0.1", ...)`). It is not auto-started by the watch loop. If an operator has a `python -m src.main dashboard` running in another terminal, that process has its own `src.config` import — and therefore its own frozen `DB_PATH` — and will continue serving `/api/shadow/*`, `/api/scan/*`, etc., hitting the **old** DB through its open connections. Several routes write (shadow-trade actions via `src/api/routes/actions.py` `BackgroundTasks`, journal writes via `src/journal/store.py`). | Nothing today prevents an orphan `dashboard` process from surviving the archive. The local API binds `127.0.0.1` only, so blast radius is operator-initiated, not external. | **MEDIUM.** Operator must close any `dashboard` process as part of the choreography (vector-2 cure covers vector-4: kill the dashboard terminal before running the archive). |
| 5 | **Background threads / pending writes inside the halted watch loop** | **Real, narrow window.** The watch loop spawns `RenderSyncThread` (`src/sync/render_sync.py:796`) as a `daemon=True` thread with a `_sync_lock` and a `_stop_event`. It also uses `threading.Timer` in `src/observability/loki_handler.py:79` to flush log batches. Because these are daemon threads of the watch-loop process, they die when the main process dies — but **`nssm stop` sends a termination signal that may cut off an in-flight SQLite transaction**. Any uncommitted write is rolled back by SQLite's own crash-recovery on next open (WAL replay). The archive primitive (`VACUUM INTO` per P1.1) reads a consistent snapshot even if a `-wal` file is present on the source, so the archive itself is not compromised. | SQLite's WAL durability + the watch loop's own `busy_timeout=30s` (`src/utils/db.py` via `connect_db()`). On a clean `nssm stop`, NSSM sends the equivalent of `CTRL_BREAK_EVENT`; the watch loop's `atexit` hook releases the PID lockfile. Pending WAL commits are replayed on first open of the source DB — which happens inside `VACUUM INTO` under a read transaction, so the read sees the post-recovery state. | **LOW-to-NEGLIGIBLE**, provided the operator issues `nssm stop` (not `taskkill /F`) and waits for `data/watch.lock` to disappear before running the archive. |

### Operator choreography (recommended ordered list)

This is the minimum-discipline procedure. It is the ONLY sequence that closes all five vectors.

1. **`nssm stop ArcisWatchLoop`** — gives the watch loop a chance to release its SQLite connections, flush its Loki timer, and drop the PID lockfile. Wait for the command to return.
2. **Verify no `python.exe` still has the DB open.** At least one method must be used; two independent methods preferred:
   - **PowerShell (no extra tools):**
     ```powershell
     Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
       Select-Object ProcessId, CommandLine |
       Where-Object { $_.CommandLine -match 'src\.main|watch|dashboard' }
     ```
     Expected: empty. Any hit = stop those processes first.
   - **Sysinternals `handle.exe`** (download from <https://learn.microsoft.com/sysinternals/downloads/handle>):
     ```powershell
     handle.exe -a -nobanner ai_research_desk.sqlite3
     ```
     Expected: no process listed. Any hit = that process has the DB open; kill it.
   - Also verify `data/watch.lock` has been removed. Presence = a watch loop is still live or crashed-without-cleanup.
3. **Run archive script** (Pass 3 deliverable): `python scripts/archive_bootcamp_db.py --apply` (name tentative). The script performs the `VACUUM INTO` per P1.1 and creates the fresh empty DB.
4. **Verify archive integrity:** archive file exists at the manifest-declared path, SHA-256 of the archive matches the value written to the archive manifest, row counts for a representative set of tables match pre-archive counts (the Pass 3 script must emit all three). **Do NOT proceed if any check fails.**
5. **Update `ARCIS_DB_PATH`.** This is the step most prone to quiet failure. There are TWO places that must agree:
   - **`C:\arcis\halcyon-lab\.env`** — edit the `ARCIS_DB_PATH=...` line to the new path. This is picked up by every future `python -m src.main ...` invocation AND by the NSSM-launched watch loop **because `scripts/install_service.ps1` sets `AppDirectory=$RepoRoot`** (line 92) and `python-dotenv` auto-discovers `.env` from the process CWD. So editing `.env` alone IS sufficient for the NSSM service in its current configuration.
   - **BUT:** `scripts/install_service.ps1` does **not** set `AppEnvironmentExtra`. If a future change to the install script starts pinning env vars there (e.g. for secrets), `ARCIS_DB_PATH` set in `AppEnvironmentExtra` would **override** `.env` (Windows service env beats `dotenv.load_dotenv()` default behavior since `os.environ` wins over dotenv). If such a pin exists, the operator must run `nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=<new-path>` (or edit via `nssm edit`) in addition to `.env`. **Audit `nssm dump ArcisWatchLoop` before cutover to confirm no conflicting `AppEnvironmentExtra` pin exists.**
   - The resolution order that actually matters at the config-line level is documented at `src/config/__init__.py:44` (load_dotenv — NOP if env already set) and `src/config/__init__.py:56` (os.environ.get with fallback). Read those two lines before convincing yourself `.env` is enough.
6. **`nssm start ArcisWatchLoop`.** The fresh process imports `src.config`, which loads `.env` from `AppDirectory`, which is `$RepoRoot`, which now has the new `ARCIS_DB_PATH`. The watch loop opens the new DB.
7. **First-scan verification** — deferred to Pass 2 §6. At minimum, `python -m src.main validate-schema` against the new DB should return clean, and the watch loop's first scan output should reference the new DB path in its startup log.

### Pass 3 warning banner

The archive script should print — immediately after step 3 succeeds and before exiting — a single loud banner like:

```
================================================================================
ARCHIVE COMPLETE. DO NOT start the watch loop until ARCIS_DB_PATH is updated.
  1. Edit .env: set ARCIS_DB_PATH=<new-path-shown-above>
  2. Audit: nssm dump ArcisWatchLoop | findstr AppEnvironmentExtra
  3. Start : nssm start ArcisWatchLoop
See docs/archive/README.md for the full cutover checklist.
================================================================================
```

This is the last line of defense against vector 1 and vector 2. It does NOT prevent the mistake, but it eliminates the "I didn't know" defense.

<!-- SECTION:P1.4 END -->

---

## 5. Schema drift risk (evaluation framing)

<!-- SECTION:P1.5 START -->

### Scope of this section

This is **framing only**. The empirical diff between the registry and the production DB at `C:\arcis\data\ai_research_desk.sqlite3` is Pass 2 §2's job. Here we (a) enumerate the mechanisms by which drift could plausibly have been introduced, (b) name the three drift categories the diff must classify findings into, and (c) define which categories are hard blockers for cutover.

### Why drift is plausible

The sprint plan proposes creating a fresh SQLite file from `src/schema/registry.py` (via `src.schema.sqlite.create_all_tables(db_path)`) and re-pointing the watch loop at it. That is safe **only if** the registry is a strict superset of whatever schema production has accumulated. Five mechanisms could have broken that invariant:

1. **Runtime `ensure_columns` patches that outran the registry.** `src/schema/sqlite.py::ensure_columns(db_path)` iterates `TABLES` and issues `ALTER TABLE ... ADD COLUMN` for any registry column that a live DB is missing. This is the correct, guardrail-compliant way to roll forward. But the inverse — a column added to a prod DB via an older registry commit, then later removed from the registry without a corresponding column-drop migration — would leave prod with a column the current registry no longer knows about. Grep shows `ensure_columns` is invoked from **9 call-sites** across `src/council/`, `src/journal/`, `src/training/`, `src/scheduler/watch.py`, `src/schema/validator.py`, `src/startup_checks.py`, and `src/sync/render_sync.py`. Any of those subsystems could have shipped a transient column that got rolled back in registry but not in prod.
2. **Manual `ALTER TABLE` via the `sqlite3` CLI by an operator.** CLAUDE.md forbids this but cannot mechanically prevent it. An operator debugging a schema issue in 2025 with `sqlite3 ai_research_desk.sqlite3 "ALTER TABLE foo ADD COLUMN bar TEXT"` leaves no git trace. This is the single likeliest origin of drift for a long-running local DB.
3. **Migration scripts that did not round-trip back into the registry.** `scripts/migrate_production_db.py` contains its own hardcoded `COLUMN_MIGRATIONS` list (shadow_trades.strategy_type, training_examples.outcome_type/regime, activity_log.level) and a `migrate_columns()` function that issues raw `ALTER TABLE` statements against the live DB. If this script was ever run with entries that were later removed from `src/schema/registry.py` — or with entries that were never added to the registry in the first place — the prod DB would carry those columns silently. This script is a **named, active drift source** and must be specifically audited in Pass 2.
4. **`create_all_tables`-on-startup race.** `ensure_columns` catches `duplicate column` errors as "Expected race condition" (`src/schema/sqlite.py:147-148`), which means the code explicitly anticipates two processes trying to add the same column concurrently. The race itself is benign for symmetrical additions, but it confirms that multiple processes have historically written DDL to the same DB. Any non-symmetrical writer (e.g. an old branch running against a shared DB) could have introduced columns the current `main` branch would not recreate.
5. **`CREATE TABLE IF NOT EXISTS` predating registry-as-SSOT discipline.** The CLAUDE.md rule that all DDL lives in `src/schema/registry.py` is a relatively recent discipline, enforced by `test_no_create_table_in_source` / `test_no_alter_table_in_source`. Tables created before that discipline landed — and never re-derived from the registry — may carry idiosyncratic column definitions, defaults, or column orderings that `create_all_tables` will not reproduce in the fresh archive-derived DB.

### Grep evidence (collected 2026-04-24, branch `feat/bootcamp-archive-friday`)

| Pattern | Scope | Hits | Notes |
|---|---|---|---|
| `ensure_columns` | `src/` | 19 | Definition + 9 invocation call-sites. All inside `src/` — none in `scripts/` or `tests/`. |
| `ALTER TABLE` | `src/`, `scripts/` | 8 | 4 in `src/schema/` (legitimate — registry's own DDL emitter in `sqlite.py`/`postgres.py`), 1 in `src/schema/validator.py` (guardrail-scanner comment), 3 in `scripts/migrate_production_db.py` (**drift source — see mechanism 3 above**). Zero in application code outside `src/schema/`, consistent with CI guardrail `test_no_alter_table_in_source`. |
| `ensure_schema` | entire repo | 0 | **Positive signal** — there is no legacy `ensure_schema` helper competing with `ensure_columns` + `create_all_tables`. Registry-only DDL discipline is holding at the pattern level. |

### The three drift categories Pass 2 must classify into

Pass 2 §2 will compare the registry's declared schema (via `src.schema.sqlite.create_all_tables` applied to a tmpfile) against the live production DB. Every difference must be binned into exactly one of:

- **(a) Registry has tables/columns that prod lacks.** The fresh, registry-derived archive DB will be a strict superset of prod on this dimension. **Impact: low.** A re-pointed app will find the extra columns empty / tables empty, which is the same state it would face on a cold install. No data is lost (none existed). Pass 2 should still flag these because they indicate the app has been running against a DB missing schema the code assumed was present — i.e. some code path was silently never exercising those columns, which is a latent bug worth separate triage. **Not a cutover blocker.**
- **(b) Prod has columns/tables that the registry lacks.** The fresh DB will not contain these. Writes to the fresh DB that the old code expected to hit these columns will fail loudly (insert-time schema error) — but **reads of legacy data that lived in those columns will return empty, silently**, because the archive DB preserves no historical data. Any code path that queries such a column against the re-pointed DB returns zero rows with no error. **Impact: HARD BLOCKER.** This category indicates unreconciled manual patches or stale migration-script output and must be resolved before cutover.
- **(c) Prod has renamed or retyped columns relative to the registry.** Worst case. Example: prod has `shadow_trades.entry_ts` (TEXT, ISO-format) but registry declares `shadow_trades.entered_at` (INTEGER, unix epoch). The fresh DB has `entered_at`. Any query written against the registry schema will silently return empty or type-mismatch against the old column; any query written against prod's actual column will fail on the fresh DB. Detection requires matching columns by semantic role, not name — which is outside the reach of a mechanical diff. **Impact: HARD BLOCKER.** Pass 2 must flag any suspected rename pairs (columns present in prod and absent from registry AND columns in registry that look like they could be the same concept) for manual operator review.

### Blocker policy

**Ship does not proceed if any category (b) or (c) findings remain unresolved.** Resolution means one of:

1. The column is added to `src/schema/registry.py` and `create_all_tables` + `ensure_columns` are re-run (preferred — preserves the column in the archive and the re-pointed DB).
2. The column is explicitly documented as deprecated and verified to be unused by all current code paths (grep for the column name against `src/`, `frontend/`, `scripts/` must be clean; extremely rare — would require deliberate deprecation with sign-off).

Category (a) findings are reported for record-keeping and follow-up, but do not block the archive cutover.

### Comparison basis

Pass 2's empirical diff takes `src/schema/registry.py` (67 `TableDef` entries per intake facts) as canonical and applies them to a tmpfile via `src.schema.sqlite.create_all_tables(db_path: str) -> None`. It then compares:

- Table set — `SELECT name FROM sqlite_master WHERE type='table'` on both DBs.
- Column set per table — `PRAGMA table_info(<table>)` on both DBs, comparing `(name, type, dflt_value, notnull, pk)` tuples.
- Index set per table — `PRAGMA index_list(<table>)` + `PRAGMA index_info(<name>)`.

Note that row counts are **irrelevant to drift**; drift is a schema-shape question. Row-count compatibility for the data-migration step of cutover is a separate concern (Pass 1 §4 cutover atomicity and Pass 1 §6 test data strategy).

### Handoff

See Pass 2 §2 for empirical diff results.

<!-- SECTION:P1.5 END -->

---

## 6. Test data strategy

<!-- SECTION:P1.6 START -->

> **Scope note.** This section defines requirements for the Pass 3 test fixture. **Implementation is Pass 3.** No test files are authored here, and no fixture code is proposed. What follows is a specification the Pass 3 developer will consume.

### Goal of the fixture

The archive script's verification pass (per the sprint spec) re-opens the archive DB and compares row counts in a set of tables against the source DB. The fixture must therefore produce a **minimal, deterministic seeded DB** such that:

1. Every table the verification step counts has a known, non-zero row count in the source DB (so "equal counts" is a meaningful assertion — counting `0 == 0` would pass even with a broken archive).
2. Two back-to-back fixture builds produce byte-identical DB files after `VACUUM INTO` normalizes page layout. This requires all timestamps, IDs, and numeric values to be pinned — no `datetime.utcnow()`, no `uuid4()`, no `random`.

### Seed tables (mandatory)

Four tables must have ≥1 deterministic row. The first three are mandatory because the verification pass counts them; the fourth is included to exercise the quiescent-state check.

All seed `created_at` / `updated_at` / `checked_at` / `last_synced_at` / `actual_entry_time` / `actual_exit_time` values use the fixed timestamp **`2026-04-01T14:30:00Z`** (or `2026-04-03T20:00:00Z` for the exit timestamps on the closed trade) so fixture builds are reproducible across machines and clocks.

#### 1. `shadow_trades` — ≥1 closed trade with known PnL

Required so the verification pass has a non-trivial row count to compare and so the `status` index (`idx_shadow_trades_status`) is exercised. One row is sufficient; two (one `closed`, one `active`) is better because it also exercises `ACTIVE_STATUSES` / `TERMINAL_STATUSES` filtering if verification slices by status.

| Column | Value (row 1 — closed) | Value (row 2 — active) |
|---|---|---|
| `trade_id` | `"TEST-TRADE-001"` | `"TEST-TRADE-002"` |
| `ticker` | `"SPY"` | `"AAPL"` |
| `direction` | `"long"` | `"long"` |
| `status` | `"closed"` (terminal) | `"active"` |
| `entry_price` | `500.00` | `180.00` |
| `stop_price` | `475.00` | `171.00` |
| `target_1` | `525.00` | `189.00` |
| `actual_entry_price` | `500.00` | `180.00` |
| `actual_entry_time` | `"2026-04-01T14:30:00Z"` | `"2026-04-01T14:30:00Z"` |
| `actual_exit_price` | `525.00` | *(NULL)* |
| `actual_exit_time` | `"2026-04-03T20:00:00Z"` | *(NULL)* |
| `pnl_dollars` | `25.00` | *(NULL)* |
| `pnl_pct` | `5.00` | *(NULL)* |
| `created_at` | `"2026-04-01T14:30:00Z"` | `"2026-04-01T14:30:00Z"` |
| `updated_at` | `"2026-04-03T20:00:00Z"` | `"2026-04-01T14:30:00Z"` |
| `source` | `"paper"` | `"paper"` |
| `broker` | `"alpaca"` | `"alpaca"` |
| `desk` | `"swing"` | `"swing"` |

Status constants (`"closed"`, `"active"`) come from `src/shadow_trading/models.py` (`TERMINAL_STATUSES` / `ACTIVE_STATUSES` per CLAUDE.md); do not hardcode other status strings.

#### 2. `training_examples` — ≥1 row

Required so verification can count `training_examples`.

| Column | Value |
|---|---|
| `example_id` | `"TEST-EX-001"` |
| `created_at` | `"2026-04-01T14:30:00Z"` |
| `source` | `"test_fixture"` |
| `ticker` | `"SPY"` |
| `instruction` | `"Analyze the following setup."` |
| `input_text` | `"SPY pullback to 20MA, RSI 35."` |
| `output_text` | `"Buy SPY at 500, stop 475, target 525."` |
| `quality_score` | `0.85` |
| `quarantined` | `0` |

#### 3. `bracket_health` — ≥1 row

Required so verification can count `bracket_health`. Exactly one row, referencing the active trade from `shadow_trades`, is sufficient.

| Column | Value |
|---|---|
| `check_id` | `"TEST-CHK-001"` |
| `trade_id` | `"TEST-TRADE-002"` (matches active shadow trade) |
| `ticker` | `"AAPL"` |
| `stop_leg_status` | `"active"` |
| `target_leg_status` | `"active"` |
| `bracket_intact` | `1` |
| `checked_at` | `"2026-04-01T14:30:00Z"` |

#### 4. `sync_state` — quiescent-state row

The `sync_state` table (`src/schema/registry.py:1417`) has only two columns: `table_name` (PK) and `last_synced_at`. It has no in-flight-status column — in-flight-ness of render_sync is inferred from **process presence and lockfile state elsewhere**, not from this table. Therefore "quiescent state" here means simply: one seeded row so the table is non-empty and the archive's row-count check is meaningful, with a `last_synced_at` timestamp safely in the past.

Seed one row:

| Column | Value |
|---|---|
| `table_name` | `"shadow_trades"` |
| `last_synced_at` | `"2026-04-01T14:30:00Z"` |

A second row for `training_examples` with the same timestamp is acceptable if the Pass 3 author wants the sync-state row count to match the number of synced tables, but is not required for verification parity.

### Out of scope for the fixture

- The remaining tables defined in the registry do not require seed rows for archive verification parity. If the Pass 3 script's verification pass expands to count additional tables, add those tables to this list in a Pass-3 docs update; do not pre-seed speculatively.
- Schema creation itself is delegated to `src.schema.registry` (via `validate-schema --fix` or equivalent) — the fixture does **not** run raw `CREATE TABLE` (see CLAUDE.md "Database Schema Rules").

### Determinism requirements

- No `datetime.utcnow()`, `time.time()`, `uuid.uuid4()`, or `random` in fixture setup. Every value is a hardcoded literal.
- Fixture must write to a tmp path (e.g. `tmp_path / "fixture.sqlite3"` if using pytest), **never** to `C:\arcis\data\ai_research_desk.sqlite3` (see CLAUDE.md — the runtime guard in `src/utils/activity_logger.py` enforces this, but defense-in-depth belongs at the fixture layer too).
- After seeding, fixture should run `VACUUM` on the source fixture DB so the input-side page layout is already normalized — otherwise byte-identity checks between archive and source fail on page-layout noise even when the data is equal.

### Mocking requirements (for verification-parity tests that exercise the archive script)

Pass 3 tests will drive the archive script end-to-end. The script includes a preflight check that the watch loop is NOT running before it proceeds (per `CLAUDE.md` and `reference_watchloop_nssm.md`). On a dev or CI machine, the real watch loop may be running — **PID 18896 in `data/watch.lock` at the time of this sprint's intake**. Tests that do not mock the preflight will either refuse to run or, worse, run the archive against the real prod DB.

The watch-loop preflight has **two detection mechanisms that are AND-ed together**; tests must mock **both**:

1. **Lockfile presence.** Patch the code path that reads `data/watch.lock` (or the resolved data-root path) to return "absent" regardless of what is actually on disk. Use pytest `monkeypatch` on the lockfile-probe function, or redirect the data root to `tmp_path` and ensure no lockfile is written there. **Mocking only this is insufficient** — the process scan will still find the real watch loop.
2. **Process-list scan for `python` + `watch`.** Patch `psutil.process_iter` (or the equivalent process-enumeration call the preflight uses) to return an empty iterator, or a list filtered of any matching processes. Without this, the test passes on a clean dev box and fails on any machine where a real watch loop is running — a flakiness hazard that will surface first in CI or on the operator's primary workstation.

Additionally:

3. **NSSM service status call.** If the Pass 3 archive script invokes `nssm status ArcisWatchLoop` (via `subprocess.run` or similar) in the preflight phase, tests must patch `subprocess.run` — or whatever wrapper the script uses — to return `"SERVICE_STOPPED"` (or the NSSM equivalent) without actually shelling out. If `nssm status` is only called during the apply phase (i.e. after preflight passes, to halt the service before VACUUM), test for that branch separately, and for parity-only tests either do not reach that branch or stub it with a no-op that returns success.

4. **Render sync in-flight detection.** Whatever mechanism P1.3 lands on (process scan for `render_sync`, sync-state freshness check, or an advisory file flag) must be stubbed analogously — the test must not be at the mercy of whether a real `render_sync` is running on the host.

All four mocks (lockfile, process scan, NSSM status, render-sync detection) should be provided by a shared pytest fixture (e.g. `mock_watch_loop_halted`) so individual test cases cannot forget one. A fixture that mocks only three of the four is the exact failure mode the intake fact is warning about.

### Handoff

**This section describes fixture requirements only. Implementation — the actual `conftest.py` fixtures, INSERT statements, and mock helpers — is Pass 3 work** and will live alongside the archive script and its test file. Pass 3 should open a docs-follow-up if any of the seed values above prove insufficient (e.g. verification adds a 5th counted table), not silently expand the fixture without updating this spec.

<!-- SECTION:P1.6 END -->

---

## 7. Risk register

<!-- SECTION:P1.7 START -->

The following register synthesizes the operator-visible failure modes surfaced by §§1-6, plus two operator-specified additions (row 6, a §2+§4 cross-reference; row 7, the Render-sync in-flight gap the operator flagged after reading §3). Likelihood and Impact are L/M/H. Detection, Mitigation, and Recovery cells are kept tight — 1-3 sentences each — and cite the authoring section(s) whose analysis they lean on. **Row 7 requires an explicit Pass 2 checkpoint decision** (pick option (a), (b), or (c)) before Pass 3 can spec the preflight; row 6 requires active operator discipline rather than a protocol tweak, because the underlying category (b) bugs in §2 are code defects that will not be fixed inside this sprint.

| Risk | Likelihood (L/M/H) | Impact (L/M/H) | Detection | Mitigation | Recovery |
|---|---|---|---|---|---|
| **1. Archive SHA-256 mismatches on re-verify.** The archive file's hash, re-computed at a later audit, does not match the value recorded in the archive manifest at archive time. | L | H | Re-run `sha256sum` (or Python `hashlib.sha256`) on the archive and diff against the manifest's recorded hash. §4 step 4 already mandates this as part of cutover verification; extend to a periodic audit task. | Write the manifest atomically alongside the archive (temp-file + `os.replace`), store on a filesystem with ECC/checksums if available, and keep the manifest adjacent to the archive (same directory) so no-manifest-found is distinguishable from hash-drift. | If source DB still exists unmodified: re-run `VACUUM INTO` (§1) to regenerate the archive and manifest. If source DB has been overwritten (post-cutover): the archive is the only witness — treat the mismatch as potential corruption, preserve the suspect file, and attempt `PRAGMA integrity_check` plus a schema-and-row-count comparison against the manifest's declared counts (§6) to scope damage. No byte-level recovery is possible from a lone corrupt archive. |
| **2. Fresh DB schema init fails midway** between creating the empty `sqlite3` file and completing `create_all_tables`. | L | H | `create_all_tables` raises; archive script catches and logs. A half-initialized DB is detectable by comparing `sqlite_master` table-count against the registry's 67-table baseline (`python -c "from src.schema.registry import TABLES; print(len(TABLES))"` per CLAUDE.md). | Wrap init in a single transaction where possible; run `validate-schema --fix` (CLAUDE.md) as a second pass; refuse to print the §4 "archive complete" banner until schema init has exited cleanly and the table count matches. Keep `ARCIS_DB_PATH` pointed at the OLD location until verification passes. | Delete the half-initialized fresh DB file (it holds no operator data — cutover has not completed, per §4's window definition). Re-run `create_all_tables` on a new empty file. If init fails repeatedly, abort cutover and leave `ARCIS_DB_PATH` on the old location; the archive itself is intact (source DB untouched per §1 recoverability row) and the system continues running on the pre-archive DB. |
| **3. Manifest write fails but archive succeeded.** Disk-full, permission error, or process kill between `VACUUM INTO` returning and manifest write completing. | L | M | Post-archive check: manifest file exists AND contains expected keys (archive path, SHA-256, row counts per §6 seed tables). Absence or truncation is the signal. | Write manifest via temp-file + `os.replace` for atomic replace semantics; write AFTER the archive file is fully fsync'd; fail loud in the archive script if manifest write raises, do not swallow the exception. | The archive IS usable without the manifest — it's a standalone SQLite file that opens and queries normally. The manifest can be regenerated from the archive itself: recompute SHA-256, re-run the §6 row-count queries against the archive, and write a fresh manifest. Mark the regenerated manifest with a `regenerated_at` field so future audits know the hash was not witnessed at archive time. |
| **4. Operator runs `--apply` twice.** Second invocation finds archive already on disk. | M | M | Archive script's first action after arg-parse: check whether the manifest-declared archive path already exists. If present, refuse to proceed unless `--force` is passed. | Idempotency is NOT free — a naive second `VACUUM INTO` to the same path fails (SQLite refuses to overwrite), but a second run against a DIFFERENT source (i.e. after cutover, the fresh empty DB) would produce a new "archive" of the empty DB and overwrite a previous manifest if paths collide. Design: require explicit `--archive-path` with no default, and require `--force` to overwrite any existing manifest or archive. Log both the source DB path and target archive path at the top of every run. | First run succeeded, second run refuses: no damage, operator sees the refusal message. First run succeeded, second run with `--force` overwrites: the original archive is lost. Recovery depends on whether source DB still holds the pre-archive state (if cutover already happened, it doesn't) — if lost, treat as a full archive re-run from whatever the current source DB is, and document the gap in the manifest. |
| **5. Production DB is larger than expected (2 GB+) and `VACUUM INTO` takes >30 min.** Operator has no visibility into progress and cannot distinguish "still running" from "hung". | M | M | `VACUUM INTO` (§1) is a single SQL statement and does not emit progress — SQLite has no VACUUM progress callback. External signals: the destination file grows on disk (watch with `ls -la` / `Get-Item` on the target path in a polling loop); the Python process holding the connection shows CPU and disk-I/O in Task Manager / `Get-Process`; `handle.exe ai_research_desk.sqlite3` (§4 step 2) continues to show the archive process with the source handle open. | Archive script prints source DB size and a rough ETA (e.g. "2.1 GB source → expect 20-40 min on SSD") before starting; launches `VACUUM INTO` on a thread and emits a heartbeat to stdout every 30 s ("still running, target file now X MB"); does NOT enforce a timeout — killing a long VACUUM is safe for the source (§1) but wastes the elapsed time. | If genuinely hung (no disk growth for 5+ min, no CPU): Ctrl-C or taskkill the archive process. Partial destination file is incomplete — delete it (§1 recoverability row: source is untouched). Investigate the hang (disk full? antivirus scanning the growing archive? see §4 vector 5 on ancillary processes), remediate, and re-run. Do NOT restart the watch loop until the archive has successfully completed OR the cutover has been explicitly abandoned. |
| **6. A category (b) hardcoded-path bug fires during the cutover window.** After the archive runs but before the operator updates `ARCIS_DB_PATH` and restarts NSSM (§4's cutover window), any Python invocation that hits a category (b) default from §2 writes to the WRONG DB — potentially corrupting the just-created fresh DB or appending stale writes to what should be a frozen archive. §2 lists five category (b) findings (one production-reachable at `src/services/mr_scan_service.py:78`; four operator scripts: `export_chatgpt_inputs.py`, `import_chatgpt_outputs.py`, `render_architecture_doc.py`, `schema_report.py`). | M | H | Cannot be detected by the archive script itself — the bug fires in a sibling process the archive has no handle on. Indirect signals: post-cutover row-count parity check (§6) reveals unexpected writes in the fresh DB, OR file-modification-time on the archive file changes after archive completion (archive should be read-only post-VACUUM). Operator must spot either symptom. | §4 operator choreography — the window is closed by strict sequencing: `nssm stop` → archive → verify → update `.env` → `nssm start`. During the window, operator must NOT launch any of the four §2 operator scripts and must NOT run `python -m src.main <anything>` from any shell where `ARCIS_DB_PATH` is unset or stale. The §4 "archive complete" banner is the primary guardrail; set archive file to read-only via `chmod -w` / `attrib +R` immediately after `VACUUM INTO` returns, so writes through the wrong path fail loudly rather than silently succeed. The production-reachable `mr_scan_service.py:78` default is mooted by the fact that the watch loop is stopped during the window (§3). | If fresh DB was written to during the window: compare row counts against the §6 seed-table baseline and the archive's counts; non-zero deltas in `shadow_trades`, `training_examples`, or any registry table indicate foreign writes. Remediation: re-create the fresh DB from registry (`validate-schema --fix`), re-run archive verification, restart cutover from §4 step 3. If the archive file itself was written to (attribute flip failed or was bypassed): the archive is compromised — SHA-256 will differ from manifest; treat as risk 1. Root-cause fix for the four operator scripts is a separate follow-up issue, not a sprint deliverable. |
| **7. Render sync worker may be running during archive without a sync_state in-flight mechanism to detect it** (P1.3 revealed `sync_state` is cursor-only, not a state machine). `VACUUM INTO` may acquire a reserved lock that blocks or crashes the sync worker. | L | H | **No reliable detection exists at the schema layer.** Per §3.2: `sync_state` has only two columns (`table_name`, `last_synced_at`) — it is a high-water-mark cursor, not a run tracker. In-flight state lives in a per-process `threading.Lock` (`RenderSyncThread._sync_lock` at `src/sync/render_sync.py:817`), invisible to external scripts. The only indirect protection is §3's watch-loop halt (the sync thread is `daemon=True` inside the watch-loop process, so `nssm stop ArcisWatchLoop` kills it). Cursor-staleness check (`MAX(last_synced_at)` older than `interval_seconds * 3`) is a weak signal only — a healthy idle sync outside market hours looks stale. | **Pass 2 checkpoint decision required.** Three options, operator picks one: **(a)** require operator halts the sync worker before archive — currently satisfied transitively by §3's NSSM-stop-watch-loop step, but make it explicit in Pass 3 choreography and in the pre-archive checklist; **(b)** add a lockfile-based check (sync worker writes a sentinel file while its `_sync_lock` is held, archive script refuses if present); **(c)** extend `sync_state` with `in_flight_since` / `completed_at` columns and flush on acquire/release of `_sync_lock` — cleanest but a separate sprint (registry change, migration, Postgres sync impact). Likelihood rated L because §3 establishes the sync thread is a daemon of the watch-loop process and §4's choreography halts the watch loop first, so under protocol the sync is already stopped; likelihood rises to M if option (a) is NOT made explicit or the operator skips the NSSM-stop step. | If sync worker crashes mid-archive: archive may be incomplete (partial destination file — delete and retry per §1), fresh DB may be un-created (no harm, re-run `create_all_tables`), AND the cursor in `sync_state` may be ahead of actual synced state (the cursor advances eagerly; savepoints in `_replace_latest_in_postgres` per §3.2 cover Postgres rollback but not the SQLite-side cursor). Restart of the sync worker after cutover may **double-sync rows** depending on its cursor-reset semantics: if the worker re-reads the cursor and uses it as an exclusive lower bound, rows synced-but-not-cursor-advanced get re-sent (idempotent if Postgres uses upsert, duplicative otherwise). Verify cursor vs. Postgres max-timestamp parity before the first post-cutover sync cycle. |

**Active-decision callout.** Two rows require something beyond "follow the protocol":

- **Row 7** needs an explicit Pass 2 checkpoint decision between options (a), (b), and (c). Without a call, Pass 3 cannot spec the preflight. Recommend (a) as the MVP (free, leans on §3's existing NSSM-stop step) with (c) queued as a follow-up sprint.
- **Row 6** depends on operator discipline during the cutover window — the five category (b) bugs from §2 are not being fixed in this sprint. The §4 warning banner and the post-VACUUM read-only attribute flip are the two concrete guardrails; everything else is "operator must not launch script X during the window", which is a procedural control, not a technical one. File the four operator-script fixes as a follow-up issue during Pass 3 per §2's audit hand-off.

<!-- SECTION:P1.7 END -->
