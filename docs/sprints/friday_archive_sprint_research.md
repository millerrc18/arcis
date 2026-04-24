# Friday Bootcamp Archive Sprint — Pass 2 Research (SD#42)

> **Sprint:** Friday Bootcamp Archive Sprint (SD#42)
> **Branch:** `feat/bootcamp-archive-friday`
> **Date:** 2026-04-24
> **Pass:** 2 of 2 (research with empirical checks). Companion to Pass 1 evaluation. Pass 3 (archive script + tests + archive README + CHANGELOG + follow-up-issue filing) is operator-gated and out of scope for this sprint.
> **Source commit when research was written:** `d32fb5d` (HEAD of `feat/bootcamp-archive-friday` after Pass 1 commit)

---

## 1. Line-number verification

<!-- SECTION:P2.1 START -->

Verified against `feat/bootcamp-archive-friday` HEAD (`d32fb5d`). Since the branch cut cleanly from `origin/main` at `95e439c` and no `src/` files were modified by this sprint, line numbers should be stable — but this is the empirical check.

**Method.** For each `file:line` citation in Pass 1 (`docs/sprints/friday_archive_sprint_evaluation.md`), re-open the referenced file via the `Read` tool at an offset window around the cited line and confirm the cited content is present on that line. Range citations (e.g. `796-893`) are verified by checking both endpoints and at least one interior line. The table below is in the order citations first appear in Pass 1.

| Pass 1 citation | Current line | Match? (Y/N) | Notes if N (correct line or drift explanation) |
|---|---|---|---|
| `src/scheduler/watch.py:1047` — `.backup()` call (`src.backup(dst)`) | 1047 | Y | Verbatim: `src.backup(dst)`. |
| `src/scheduler/watch.py:1035-1058` — `_backup_database` method span | 1035-1058 | Y | `def _backup_database(self):` at 1035; final `except … logger.warning(…)` at 1057-1058. |
| `src/scheduler/watch.py:1061` — `LOCKFILE = Path("data/watch.lock")` | 1061 | Y | Verbatim match after the section-header comment at 1060. |
| `src/scheduler/watch.py:1083-1114` — `_acquire_lock()` | 1083-1114 | Y | `def _acquire_lock(self):` at 1083; final `atexit.register(self._release_lock)` at 1114. |
| `src/scheduler/watch.py:1105` — lockfile writer (`self.LOCKFILE.write_text(str(os.getpid()))`) | 1105 | Y | Verbatim match. |
| `src/scheduler/watch.py:1108-1112` — inline comment about `taskkill /F` not being interceptable | 1108-1112 | Y | The cited 5-line window is the body of the taskkill-rationale comment; the comment actually begins at 1107 (`# atexit catches normal Python exits …`) and ends at 1112 (`# so this is belt-and-suspenders …`). Pass 1's range covers the core `taskkill /F` lines inside it. |
| `src/scheduler/watch.py:1116-1124` — `_release_lock()` | 1116-1124 | Y | `def _release_lock(self):` at 1116; `except Exception: pass` at 1123-1124. |
| `src/scheduler/watch.py:1182` — overnight-schedule handler registration | 1182 | Y | Line 1182 is the comment `# Phase B: register handlers for the extracted overnight schedule.` which introduces `self._register_default_handlers()` on line 1185. Pass 1 cites this as illustrative of the watch loop's schedule usage; match is conceptual but the line is on-point. |
| `src/services/mr_scan_service.py:78` — hardcoded path bug (`_db = config.get("db_path", "data/ai_research_desk.sqlite3")`) | 78 | Y | Verbatim match. |
| `src/schema/registry.py:1415-1416` — registry comment (*"Cursor tracking for render_sync. …"*) | 1415-1416 | Y | Verbatim. |
| `src/schema/registry.py:1417` / `:1417-1426` — `sync_state` `_register(TableDef(...))` | 1417-1426 | Y | `_register(TableDef(` at 1417; closing `))` at 1426. Two columns (`table_name`, `last_synced_at`) match Pass 1's schema table. |
| `src/sync/render_sync.py:33` — docstring line for fix #130 (`_sync_lock prevents concurrent runs`) | 33 | Y | Verbatim: `- #130: Overlapping sync cycles — _sync_lock prevents concurrent runs`. |
| `src/sync/render_sync.py:367-472` — `_replace_latest_in_postgres` | 367-472 | Y | `def _replace_latest_in_postgres(` at 367; `cursor.close()` final `finally` at 472. |
| `src/sync/render_sync.py:761` — `logger.info("Synced %d rows to %s", …)` | 761 | Y | Verbatim match inside the per-table loop. |
| `src/sync/render_sync.py:796-893` — `RenderSyncThread` class body | 796-893 | Y | `class RenderSyncThread(threading.Thread):` at 796; final `logger.info("Render sync thread stopped")` at 893. |
| `src/sync/render_sync.py:812` — `daemon=True` in `super().__init__` | 812 | Y | Verbatim: `super().__init__(daemon=True, name="render-sync")`. |
| `src/sync/render_sync.py:817` — `self._sync_lock = threading.Lock()` | 817 | Y | Verbatim match. |
| `src/sync/render_sync.py:827-837` — `health_status()` method | 827-837 | Y | `def health_status(self) -> dict:` at 827; closing `}` of returned dict at 837. |
| `src/sync/render_sync.py:831` — `stale` threshold (`interval_seconds * 3`) | 831 | Y | Verbatim: `stale = last_ago is not None and last_ago > self.interval_seconds * 3`. |
| `src/sync/render_sync.py:845` — non-blocking `_sync_lock.acquire` | 845 | Y | Verbatim: `if not self._sync_lock.acquire(blocking=False):`. |
| `src/sync/render_sync.py:857-861` — cycle-summary log | 857-861 | Y | `logger.info("Sync cycle complete: %d rows synced, %d errors", …)` spans 857-861 (multi-line call). |
| `src/sync/render_sync.py:866-870` — 30-cycle quiet heartbeat | 866-870 | Y | `elif self._cycle_count % 30 == 0:` at 866; the `logger.info(…)` call with heartbeat message spans 867-870. Pass 1's range covers the full heartbeat `elif` branch. |
| `src/sync/render_sync.py:889` — `_sync_lock.release()` in `finally` | 889 | Y | Verbatim match. |
| `src/config/__init__.py:44` — `load_dotenv()` call | 44 | Y | Verbatim match. |
| `src/config/__init__.py:56` — `DB_PATH = os.environ.get("ARCIS_DB_PATH", str(_REPO_ROOT / "ai_research_desk.sqlite3"))` (cited in §2, §4, §5) | 56 | Y | Verbatim match. |
| `src/startup.py:73-91` — `is_watch_loop_running()` | 73-91 | Y | `def is_watch_loop_running() -> int | None:` at 73; final `return None` at 91. |
| `src/utils/activity_logger.py:54` — comment about kill_switch_halt rows | 54 | Y | Verbatim: `# fake kill_switch_halt rows into the prod ai_research_desk.sqlite3`. |
| `src/cli/commands.py:1349-1353` — `cmd_dashboard`/`uvicorn.run` | 1349-1353 | Y | `import uvicorn` at 1349; `uvicorn.run("src.api.app:app", host="127.0.0.1", …)` at 1353. |
| `src/observability/loki_handler.py:79` — `threading.Timer` flush scheduler | 79 | Y | Verbatim: `self._timer = threading.Timer(self.flush_interval, self._flush)`. |
| `src/schema/sqlite.py:147-148` — "duplicate column" / "Expected race condition" | 147-148 | Y | Line 147: `if "duplicate column" in str(e).lower():`; line 148: `pass  # Expected race condition`. |
| `scripts/install_service.ps1` line 92 — `AppDirectory $RepoRoot` | 92 | Y | Verbatim: `& $nssm set $ServiceName AppDirectory   $RepoRoot`. |
| `scripts/install_service.ps1` line 102 — `AppExit Default Restart` | 102 | Y | Verbatim: `& $nssm set $ServiceName AppExit         Default Restart`. |
| `scripts/install_service.ps1` line 106 — `AppRestartDelay 10000` | 106 | Y | Verbatim: `& $nssm set $ServiceName AppRestartDelay 10000`. |
| `scripts/cleanup_test_pollution_647.py:74` — repo-root-anchored fallback | 74 | Y | Verbatim: `return str(repo_root / "data" / "ai_research_desk.sqlite3")`. |
| `scripts/diagnose_leakage.py:28` — `DB_CANDIDATES = [...]` | 28 | Y | Verbatim match. |
| `scripts/fix_training_page.py:20` — `DB_PATH = os.environ.get("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")` | 20 | Y | Verbatim match. |
| `scripts/export_chatgpt_inputs.py:25` — function default `db_path="ai_research_desk.sqlite3"` | 25 | Y | Verbatim match. |
| `scripts/export_chatgpt_inputs.py:75` — argparse default `--db` | 75 | Y | Verbatim: `p.add_argument("--db", default="ai_research_desk.sqlite3")`. |
| `scripts/weekly_review.py:39` — `DB_CANDIDATES = [...]` | 39 | Y | Verbatim match. |
| `scripts/import_chatgpt_outputs.py:34` — function default `db_path="ai_research_desk.sqlite3"` | 34 | Y | Verbatim match. |
| `scripts/import_chatgpt_outputs.py:89` — argparse default `--db` | 89 | Y | Verbatim: `p.add_argument("--db", default="ai_research_desk.sqlite3")`. |
| `scripts/post_close_check.py:36` — `DB_CANDIDATES = [...]` | 36 | Y | Verbatim match. |
| `scripts/render_architecture_doc.py:10` — docstring bullet | 10 | Y | Verbatim: `- ai_research_desk.sqlite3 for the live schema report`. |
| `scripts/render_architecture_doc.py:153` — `render_schema(ROOT / "ai_research_desk.sqlite3")` | 153 | Y | Verbatim: `schema_report = render_schema(ROOT / "ai_research_desk.sqlite3")`. |
| `scripts/diagnostics/regime_diagnostic_v1.py:120` — `default_db = "C:/arcis/data/ai_research_desk.sqlite3"` | 120 | Y | Verbatim match. |
| `scripts/statusline.py:11` — docstring bullet (shadow_trades counts) | 11 | Y | Verbatim: `- ai_research_desk.sqlite3 (shadow_trades counts)`. |
| `scripts/statusline.py:40-55` — `_resolve_data_root()` | 40-55 | Y | `def _resolve_data_root() -> Path:` at 40; trailing `return ROOT` at 55. |
| `scripts/statusline.py:61` — `DB = _DATA_DIR / "ai_research_desk.sqlite3"` | 61 | Y | Verbatim match. |
| `scripts/diagnostics/forensic_trade_audit_v1.py:16` — usage-example `--db` argument | 16 | Y | Verbatim: `--db C:/arcis/data/ai_research_desk.sqlite3 \`. |
| `scripts/schema_report.py:125-126` — argparse default + help text | 125-126 | Y | Line 125: `default="ai_research_desk.sqlite3",`; line 126: `help="Path to the SQLite database (default: ai_research_desk.sqlite3)",`. |
| `scripts/migrate_production_db.py` — `COLUMN_MIGRATIONS` list (cited in §5; no line number given) | 56 | Y | File exists; `COLUMN_MIGRATIONS = [` is defined at line 56, consumed by `migrate_columns()` at lines 67 and 134. |

**Final tally: 51 citations verified, 0 mismatches found.**

All citations resolve to the exact content Pass 1 attributed to them. No drift detected. The branch-cut analysis at the top of this section held empirically: because `feat/bootcamp-archive-friday` branched cleanly from `origin/main` at `95e439c` and this sprint has only touched `docs/sprints/*.md`, no `src/` or `scripts/` line numbers could have moved. This section exists to eliminate the "should" in that sentence.

<!-- SECTION:P2.1 END -->

---

## 2. Schema drift actual check

<!-- SECTION:P2.2 START -->

**Date performed:** 2026-04-24
**Watch loop state during inspection:** running (PID 18896, NSSM service `ArcisWatchLoop`)
**Access method:** Python `sqlite3.connect('file:...?mode=ro', uri=True)` — the sanctioned live-inspection method per CLAUDE.md. No writes attempted on prod.

### Commands actually run (for reproducibility)

```bash
# Scratch DBs live outside the repo (CLAUDE.md §"Repo Layout — state lives outside the repo").
# On this Windows box Python's /tmp resolves to C:\tmp\; MSYS's /tmp is separate —
# all artifacts below are at Windows C:\tmp\ (confirmed via os.path.getsize).

# 1. Dump prod schema (READ-ONLY)
python -c "
import sqlite3
conn = sqlite3.connect('file:C:/arcis/data/ai_research_desk.sqlite3?mode=ro', uri=True)
rows = conn.execute(\"SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name\").fetchall()
open('/tmp/prod_schema.sql','w',encoding='utf-8').write(''.join(sql+';\n' for _,_,sql in rows if sql))
"

# 2. Build scratch #1 — registry only
python -c "from src.schema.sqlite import create_all_tables; create_all_tables('/tmp/scratch_registry.sqlite3')"
# Then dump (same pattern as #1, different source path) -> /tmp/registry_schema.sql

# 3. Build scratch #2 — registry + COLUMN_MIGRATIONS
python -c "
from src.schema.sqlite import create_all_tables
create_all_tables('/tmp/scratch_registry_plus_migrations.sqlite3')
import importlib.util
spec = importlib.util.spec_from_file_location('m','scripts/migrate_production_db.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import sqlite3
conn = sqlite3.connect('/tmp/scratch_registry_plus_migrations.sqlite3')
for a in m.migrate_columns(conn): print(a)
"
# Dump -> /tmp/registry_plus_migrations_schema.sql

# 4. Diff (Python difflib.unified_diff, since sqlite3 CLI isn't on PATH)
# Diff A: registry vs prod   -> /tmp/diff_a.txt (883 lines, 38,189 bytes)
# Diff B: registry vs registry+migrations -> /tmp/diff_b.txt (0 bytes)
```

**sqlite3 CLI note:** the system has no `sqlite3` on PATH (`which sqlite3` returns not-found). Python's stdlib `sqlite3` module was used for both dumping and diffing. `difflib.unified_diff` produces the same `-u` format a shell `diff` would produce, so the output format below is unchanged.

---

### Diff B: Registry DDL vs. Registry + `migrate_production_db.py COLUMN_MIGRATIONS`

**Result: EMPTY (0 bytes).** The migration script is a no-op against a fresh registry-generated DB.

```
(diff is empty — files identical)
```

Output from `migrate_columns()` invoked on scratch #2:

```
OK: shadow_trades.strategy_type already exists
OK: training_examples.outcome_type already exists
OK: training_examples.regime already exists
OK: activity_log.level already exists
COLUMN_MIGRATIONS list length: 4
```

**Interpretation.** All 4 entries in `COLUMN_MIGRATIONS` are already present in the registry (`src/schema/registry.py`). `create_all_tables()` emits them; `migrate_columns()` then finds nothing to add. The registry HAS absorbed its own historical migrations — there is no "registry-drift-from-its-own-migration-script" condition.

**Pass 1 §5 correction needed.** Pass 1 reported "3 ALTER TABLE hits in `migrate_production_db.py`". The actual `COLUMN_MIGRATIONS` list has **4 entries** (`shadow_trades.strategy_type`, `training_examples.outcome_type`, `training_examples.regime`, `activity_log.level`). The 4-entry list yields 4 `ALTER TABLE ... ADD COLUMN` statements at runtime, not 3. Pass 1 undercounted by 1. (This also nudges Pass 1's "8 ALTER TABLE hits total" up to 9 if the 4-count here is authoritative. The exact global count should be re-verified by P2.4 if anything depends on it; the classification conclusions here are not affected.)

**Follow-up-issue flag for Diff B:** NOT required. Registry already owns what the migration script applies.

---

### Diff A: Prod DB vs. Registry-generated DDL

**Raw size:** 883 lines / 38,189 bytes of unified-diff. Summary of structural observations first; truncated diff with a pointer to the full file after that; column-level semantic diff last (the column-level diff is the one that matters for cutover risk — raw DDL diff is noisy because prod tables were originally created with heterogeneous DDL shapes from legacy code paths).

#### Structural summary

| Dimension | Prod | Registry | Delta |
|---|---|---|---|
| Tables | 67 | 67 | 0 |
| Indexes | 76 | 65 | +11 in prod |
| Tables with registry-only columns | — | — | **0** |
| Tables with prod-only columns | — | — | **6** |
| Columns with type-affinity drift on shared cols | — | — | **173** |

Headline: **table counts match, no tables are prod-orphaned, and there are ZERO columns that exist in the registry but are missing from prod** (the `ensure_columns()` path has been doing its job). The drift is exclusively in the direction of **prod has more than registry** — which is the harder direction for cutover reasoning.

#### Prod-only columns (6 tables, 17 columns total)

| Table | Prod-only columns | Classification |
|---|---|---|
| `api_costs` | `estimated_cost` | (b) HARD BLOCKER — data may exist here |
| `canary_evaluations` | `id`, `perplexity`, `verdict` | (b) HARD BLOCKER |
| `quality_drift_metrics` | `avg_score`, `id`, `metric_date`, `pass_rate`, `score_std`, `template_fallback_rate` | (b) HARD BLOCKER — 6 columns |
| `recommendations` | `setup_confidence` | (b) HARD BLOCKER — core operational table |
| `setup_signals` | `features_json`, `scan_date` | (b) HARD BLOCKER — feature snapshot column |
| `training_examples` | `model_version`, `outcome`, `regime_label`, `trade_date` | (b) HARD BLOCKER — training data table |

Rows populated in these columns would be **lost** on any operation that re-creates these tables from the registry without preserving the prod column set. **Archive-sprint implication:** the archive operation does NOT drop/recreate tables (it archives *rows*, not schema), so this drift does not block the archive itself — but it DOES block any "drop and rebuild from registry" recovery path. The archive script must preserve prod schema as-is.

#### Prod-only indexes (11, all rebuildable)

```
idx_api_costs_created_at                 on api_costs
idx_api_costs_purpose                    on api_costs
idx_earnings_date                        on earnings_calendar
idx_earnings_ticker                      on earnings_calendar
idx_earnings_ticker_date                 on earnings_calendar
idx_metric_snapshots_date                on metric_snapshots
idx_model_versions_status                on model_versions
idx_training_examples_created_at         on training_examples
idx_training_examples_recommendation_id  on training_examples
idx_training_examples_source             on training_examples
idx_training_examples_ticker             on training_examples
```

Classification: (a) registry-can-catch-up — indexes hold no data, so "missing from registry" is recoverable by rebuilding. But until the registry is updated, queries on a fresh DB will be slower on these 11 access paths. Low severity but non-zero.

#### Type-affinity drift (173 columns across shared tables)

Most shared columns with type drift show `prod=TEXT` vs `registry=REAL`/`INTEGER`. SQLite uses **loose type affinity** (a column declared `TEXT` can still hold REAL/INT values via coercion rules), so arithmetic queries mostly still work — but:

- `PRAGMA table_info` returns prod types as TEXT, which mis-signals to any consumer that inspects schema before querying
- ORDER BY on "looks like a number but is TEXT" performs lexicographic sort unless CAST-ed
- JSON serialization may emit strings where callers expect numbers

Spot-checked examples (not exhaustive — full list of 173 available in `C:\tmp\diff_a.txt`):

```
api_costs.input_tokens:          prod='TEXT' registry='INTEGER'
api_costs.output_tokens:         prod='TEXT' registry='INTEGER'
api_costs.cost_dollars:          prod='TEXT' registry='REAL'
cboe_ratios.equity_pc_ratio:     prod='TEXT' registry='REAL'
council_sessions.is_contested:   prod='TEXT' registry='INTEGER'
council_votes.confidence:        prod='TEXT' registry='INTEGER'
(... 167 more)
```

Classification: **(c)-adjacent**. Not a column *rename* — the column names match. But the declared type drifted, which means a fresh-from-registry DB would declare these columns with "correct" types and callers that currently rely on TEXT coercion could behave differently. Not a hard blocker for the archive sprint (archive is row-level delete, doesn't touch schema) but a hard blocker for any "rebuild from registry and backfill" operation. **Does not fit cleanly into (a)/(b)/(c)** — it's a fourth category: (d) "prod has weaker-typed columns than registry". Flagged separately.

#### Raw diff output (truncated + pointer to full file)

First ~40 lines of the unified diff (all index-only or structural reshuffling):

```diff
--- registry_schema.sql
+++ prod_schema.sql
@@ -1,4 +1,6 @@
 CREATE INDEX idx_analyst_ticker_date ON analyst_estimates(ticker, date);
 CREATE UNIQUE INDEX idx_analyst_unique ON analyst_estimates(ticker, date, source);
+CREATE INDEX idx_api_costs_created_at ON api_costs(created_at);
+CREATE INDEX idx_api_costs_purpose ON api_costs(purpose);
 CREATE INDEX idx_attribution_created ON attribution_trades(created_at);
 CREATE INDEX idx_attribution_pair_type ON attribution_trades(pair_type);
@@ -17,4 +19,10 @@
 CREATE INDEX idx_diagnostic_runs_created_at ON diagnostic_runs(created_at);
 CREATE INDEX idx_diagnostic_runs_type_status ON diagnostic_runs(diagnostic_type, status);
+CREATE INDEX idx_earnings_date
+    ON earnings_calendar(earnings_date);
+CREATE INDEX idx_earnings_ticker
+    ON earnings_calendar(ticker);
+CREATE UNIQUE INDEX idx_earnings_ticker_date
+    ON earnings_calendar(ticker, earnings_date);
 CREATE UNIQUE INDEX idx_edgar_accession ON edgar_filings(accession_number);
 CREATE INDEX idx_edgar_ticker_date ON edgar_filings(ticker, filing_date);
@@ -30,5 +38,9 @@
 CREATE INDEX idx_macro_snapshots_date ON macro_snapshots(collected_date);
 CREATE INDEX idx_macro_snapshots_series ON macro_snapshots(series_id, collected_date);
+CREATE INDEX idx_metric_snapshots_date
+            ON metric_snapshots(snapshot_date)
+        ;
 CREATE INDEX idx_minute_bars_timestamp ON minute_bars(timestamp);
+CREATE INDEX idx_model_versions_status ON model_versions(status);
 CREATE INDEX idx_options_chains_collected ON options_chains(collected_at);
... (truncated — 883 lines total; stored at C:\tmp\diff_a.txt during research)
```

Representative table-rewrite noise (same columns, different DDL syntax — NOT semantic drift):

```diff
-CREATE TABLE activity_log (
-    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
-    event_type TEXT NOT NULL,
-    detail TEXT,
-    level TEXT,
-    created_at TEXT NOT NULL
-);
+CREATE TABLE "activity_log" (
+                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
+                event_type TEXT NOT NULL,
+                detail TEXT,
+                level TEXT,
+                created_at TEXT NOT NULL
+            );
```

(Registry form vs prod form — columns identical, formatting differs because prod was created by an older code path that quoted the table name and used different indentation. `PRAGMA table_info` confirms column-set equality.)

Representative actual drift (prod has extra column `setup_confidence` in `recommendations`):

```diff
-CREATE TABLE recommendations (
-    recommendation_id TEXT NOT NULL,
-    [... 56 columns identical ...]
-    model_version TEXT,
-    enriched_prompt TEXT,
-    llm_conviction INTEGER,
-    llm_conviction_reason TEXT,
-    updated_at TEXT,
-    PRIMARY KEY (recommendation_id)
-);
+CREATE TABLE recommendations ("recommendation_id" TEXT, [... 56 columns ...] "enriched_prompt" TEXT, "setup_confidence" TEXT, "llm_conviction" TEXT, "llm_conviction_reason" TEXT, updated_at TEXT);
```

<details>
<summary>Full 883-line unified diff (registry vs prod)</summary>

The full diff was captured to `C:\tmp\diff_a.txt` during research. It is not inlined in this document to keep the PR reviewable. The structural summary table, prod-only column enumeration, index delta, and type-affinity sample above capture every class of difference present. If a reviewer needs the full diff during PR review, regenerate via the Python snippet at the top of this section — runtime is under 2 seconds.

Key statistics of the full diff:
- 883 total lines
- ~60 `-` lines that are structural reshuffling (old DDL shape)
- ~60 `+` lines that are the prod-canonical DDL shape
- ~17 `+` lines that are genuine prod-only columns (enumerated in the table above)
- ~11 `+` lines that are prod-only indexes (enumerated above)

</details>

---

### Classification summary (per operator rubric)

| Class | Count | Notes |
|---|---|---|
| **(a) registry-can-catch-up** | **11** | All prod-only indexes. Registry missing 11 indexes on `api_costs` (2), `earnings_calendar` (3), `metric_snapshots` (1), `model_versions` (1), `training_examples` (4). Rebuildable, no data loss. |
| **(b) prod-has-extra-columns-to-preserve (HARD BLOCKER)** | **17** | 17 columns across 6 tables (see table above). Any operation that recreates these tables from the registry DDL would drop these columns and their data. |
| **(c) prod-has-renamed-columns (HARD BLOCKER)** | **0** | No evidence of in-place renames. Every column in the registry is also present in prod. |
| **(d) type-affinity drift (outside rubric; new category)** | **173** | Shared columns where prod declared TEXT but registry declares REAL/INTEGER. Not a rename, not an extra column — but would cause subtle behavior changes in any rebuild-from-registry path. SQLite coercion hides this for most queries but not all. |

---

### Diff C (synthesis): does `migrate_production_db.py` close the gap?

**No.** The migration script closes **zero** of the Diff A gap:

- Diff B is empty (registry is a superset of what the migration script applies). Running `migrate_production_db.py` on a fresh registry-generated DB produces a DB that is **identical** to the fresh registry-generated DB.
- The 17 prod-only columns (class b), 11 prod-only indexes (class a), and 173 type-affinity drifts (class d) are **not** in `COLUMN_MIGRATIONS` and are **not** added by `migrate_tables`. They originated from **manual patches or historical code-paths** that bypassed both the registry and the migration script.

In plain English: **prod schema ≠ registry + migrations.** Prod has drift *beyond* what the migration script introduces. The gap is explained by:
1. Legacy `CREATE TABLE` statements that existed in the codebase before the registry was introduced (#580-era refactor), now removed from `src/` but preserved in prod by the idempotency of `CREATE TABLE IF NOT EXISTS`.
2. Manual `ALTER TABLE` statements applied directly to prod (operator surgery) that were never back-ported into the registry.
3. Types drifting because prod tables were born as TEXT-everything and later "upgraded" only in the registry.

For the **archive sprint specifically** (row-level DELETE on bootcamp-era data): this drift is **not a blocker** — the archive does not touch schema. But:
- **Flag for follow-up:** the 17 prod-only columns and 173 type drifts constitute an unbounded technical-debt surface. A principled fix is (a) reconciling each into the registry or (b) making a deliberate deprecation+drop decision per column. **This is out of scope for P2 and should be considered for follow-up issue filing in P2.4 / Pass 3.**
- **Cutover-to-fresh-DB operations are blocked** until class (b) is resolved. If any team member ever runs "drop DB, recreate from registry, re-migrate, reload backup" as a recovery path, they will silently lose data in 17 columns.

---

### Scratch cleanup

```bash
# Python-side cleanup (equivalent to `rm`):
python -c "
import os
for f in ('/tmp/scratch_registry.sqlite3','/tmp/scratch_registry_plus_migrations.sqlite3'):
    if os.path.exists(f): os.remove(f); print('removed',f)
"
```

SQLite scratch files removed after research. SQL dumps (`/tmp/*.sql`, `/tmp/diff_*.txt`) left on disk as research artifacts — they contain no prod data, only schema text. They will be purged by the OS tmp-cleanup on next reboot.

<!-- SECTION:P2.2 END -->

---

## 3. VACUUM INTO actual timing

<!-- SECTION:P2.3 START -->
### 3.1 Method

Goal: estimate how long `VACUUM INTO '<archive_path>'` will take on the ~1,070 MB prod SQLite DB, without ever running VACUUM on the prod DB itself.

Approach:

1. Build a fixture DB with the full schema (all 67 tables from `src/schema/registry.py` via `create_all_tables`), then seed ~1,000 rows across 3 tables to exercise page allocation beyond the empty-schema minimum.
2. Run `VACUUM INTO` into a fresh destination file, time it with `time.perf_counter()`, and divide source bytes by elapsed seconds to get a MB/s throughput figure.
3. Extrapolate linearly to 1,070 MB, then apply honest downward adjustments for the factors the fixture cannot reproduce (index B-tree rebuild cost, fragmentation, fsync non-linearity, disk-vs-RAM).

All scratch DBs live at `C:/tmp/` (the bash shell mounts this as `/tmp/`; it maps to a real NTFS directory on the Windows C: drive, **not** tmpfs/RAM — see 3.4 below). The prod DB was never touched.

### 3.2 Fixture construction

```bash
python -c "from src.schema.sqlite import create_all_tables; create_all_tables('/tmp/vacuum_fixture.sqlite3')"
```

- Post-create size: **794,624 bytes** (~776 KB). All 67 tables, zero rows.

Seed ~1,000 rows (400 `activity_log` + 400 `api_costs` + 200 `correlation_matrices`) via a short Python script:

```python
import sqlite3
c = sqlite3.connect('C:/tmp/vacuum_fixture.sqlite3')
cur = c.cursor()
for i in range(400):
    cur.execute("INSERT INTO activity_log (event_type, detail, level, created_at) VALUES (?, ?, ?, ?)",
                (f'evt_{i%10}', f'detail row {i} ' * 10, 'info', '2026-04-24T00:00:00'))
for i in range(400):
    cur.execute("INSERT INTO api_costs (cost_id, created_at, model, purpose, input_tokens, output_tokens, cost_dollars) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f'cost_{i}', '2026-04-24T00:00:00', 'halcyon-v1', 'scan', 100+i, 50+i, 0.001*i))
for i in range(200):
    cur.execute("INSERT INTO correlation_matrices (date, method, strategy_a, strategy_b, value, window_days, n_observations) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('2026-04-24', 'pearson', f'A{i}', f'B{i}', 0.1*i, 30, 100))
c.commit()
c.close()
```

- Post-insert size: **929,792 bytes** (~908 KB).

### 3.3 Measurement

Script actually run (three iterations to observe warm-cache variance):

```python
import time, sqlite3, os
src = 'C:/tmp/vacuum_fixture.sqlite3'
dst = 'C:/tmp/vacuum_target.sqlite3'
for i in range(3):
    if os.path.exists(dst):
        os.remove(dst)
    c = sqlite3.connect(src)
    t0 = time.perf_counter()
    c.execute(f"VACUUM INTO '{dst}'")
    t1 = time.perf_counter()
    c.close()
    src_size = os.path.getsize(src)
    print(f'run {i+1}: elapsed={t1-t0:.4f}s, MB/s={(src_size/1024/1024)/(t1-t0):.2f}')
```

Actual output:

```
run 1: elapsed=0.0172s, MB/s=51.64
run 2: elapsed=0.0147s, MB/s=60.17
run 3: elapsed=0.0142s, MB/s=62.32
```

Source size through all three rewrites: 929,792 bytes (unchanged — VACUUM INTO produces a byte-identical-sized file here because the fixture is essentially unfragmented). Destination size after each run: 929,792 bytes.

**Headline numbers from run 1 (cold-ish cache, most representative of a first-run archive in operator flow):**

- `elapsed_seconds = 0.0172`
- `throughput_MB_per_sec = 51.64`

### 3.4 Storage backing

- In this bash shell, `/tmp/` translates to `C:/tmp/`, which is a real NTFS directory on the Windows C: drive — **not** tmpfs, **not** a ramdisk. (On native Windows, `$env:TEMP` points to `C:\Users\mille\AppData\Local\Temp`, which is also NTFS on C:. Either way: real disk, not RAM-backed.)
- Physical device for C:: **Samsung SSD 990 EVO Plus 1TB, NVMe**. Modern consumer NVMe with low queue-depth latency.
- Prod DB lives at `C:/arcis/data/ai_research_desk.sqlite3` — same physical device, same filesystem. So the fixture and the prod measurement would run on **the same storage class**. This is the one favorable fact for extrapolation: no disk-class mismatch to correct for.

### 3.5 Extrapolation to prod

Prod DB size (measured at time of writing via `ls -la C:/arcis/data/ai_research_desk.sqlite3`): **1,124,130,816 bytes = 1,072 MB**.

Linear extrapolation using the cold-cache (run 1) throughput:

```
extrapolated_seconds = prod_size_MB / measured_MB_per_sec
                     = 1072 / 51.64
                     ≈ 20.76 seconds
```

Using the fastest (run 3, warm-cache) throughput:

```
extrapolated_seconds = 1072 / 62.32 ≈ 17.20 seconds
```

Call it **~17-21 seconds under ideal conditions**, before applying the honest caveats in 3.6.

### 3.6 Caveats — why the linear extrapolation will UNDER-estimate real prod VACUUM

The fixture's throughput will over-estimate prod throughput (i.e., prod VACUUM will take longer per MB than the fixture suggests) for at least these reasons:

1. **Index B-tree rebuild cost.** `VACUUM INTO` rewrites every table *and every index* into the destination in sorted order. The fixture has ~1,000 rows across 3 tables and only the minimum index set from the registry. Prod has millions of rows and the full index set (e.g., `shadow_trades`, `market_data_daily`, `news_articles`, `training_examples` all carry multi-column indexes). Index rebuild is CPU+I/O work that scales with row count, not just byte count — so effective MB/s throughput drops as index density grows.
2. **Fragmentation.** The fixture's pages were just written and are contiguous. Prod has ~18 months of inserts/updates/deletes and is fragmented. `VACUUM INTO` reads scattered pages (more I/O work per MB, though NVMe mitigates this more than HDD would) and writes them sequentially — the read side is slower than the fixture's all-sequential read.
3. **fsync non-linearity.** SQLite issues fsyncs at commit boundaries. For a sub-MB file the fsync cost is amortized into microseconds; for a 1 GB output file the OS page-cache flush and NTFS journal work scale super-linearly in some regimes. The archive runs with the watch loop halted, so there is little concurrent I/O contention, but journal flush cost still applies.
4. **Page iteration CPU cost scales with journal mode.** Prod runs in WAL mode; the fixture used default rollback journal. WAL has slightly higher per-page CPU cost during VACUUM than rollback-journal (checksumming, frame header writes). Not huge, but non-zero and asymmetric across fixture vs. prod.

Reasonable safety factor: multiply the linear extrapolation by **3x-5x** to cover these effects. That yields **~60-105 seconds** — still comfortably under two minutes for prod.

### 3.7 Operator timing recommendation

- Linear extrapolation (best case): **~17-21 s**.
- With 3x-5x caveat factor: **~60-105 s**.
- With a paranoid 10x factor: **~170-210 s (under 4 min)**.

All estimates are **well under the 10-minute threshold**, so no special scheduling window is required beyond the existing rule of halting the watch loop (NSSM service `ArcisWatchLoop`) before archive to avoid the SQLite writer-contention / file-lock issues documented in CLAUDE.md under "Database Access Rules".

**Recommendation:** Operator should budget **5 minutes** end-to-end for the VACUUM INTO step (includes stop-watch-loop, run VACUUM INTO, verify destination integrity with `PRAGMA integrity_check`, restart-watch-loop). If the real measurement at archive-time exceeds 3 minutes, that is a signal worth investigating (possible external tool still holding a file handle, unexpected fragmentation, or antivirus scanning the output file) — but it is NOT a reason to abort the archive.

### 3.8 Cleanup

```bash
rm C:/tmp/vacuum_fixture.sqlite3 C:/tmp/vacuum_target.sqlite3
ls C:/tmp/vacuum*   # returns "No such file or directory" — confirmed clean
```

Scratch files removed. No residue on disk.
<!-- SECTION:P2.3 END -->

---

## 4. Hardcoded-path followup issues

<!-- SECTION:P2.4 START -->

Five ready-to-file GitHub issue drafts, one per category (b) finding from Pass 1 §2. The production-reachable `mr_scan_service.py:78` finding is listed first; the `import_chatgpt_outputs.py` finding carries an explicit write-blast-radius callout because it is the only category (b) bug that *writes* to whatever SQLite file it lands on.

All five drafts reference the correct pattern as implemented at `src/config/__init__.py:56`:

```python
DB_PATH = os.environ.get("ARCIS_DB_PATH", str(_REPO_ROOT / "ai_research_desk.sqlite3"))
```

The two failure modes of the bugs below are (i) ignoring `ARCIS_DB_PATH` entirely, and (ii) resolving a CWD-relative literal that escapes the repo root whenever the script is invoked from any directory other than `C:\arcis\halcyon-lab\`. Per CLAUDE.md "Repo Layout", the canonical DB lives *outside* the repo at `C:/arcis/data/ai_research_desk.sqlite3`, so every CWD-relative default is wrong in production.

---

### Issue draft 1: Hardcoded DB path in `src/services/mr_scan_service.py:78`

**Summary**
MR scan service uses a CWD-relative dict-default fallback for the VIX lookup DB path, bypassing `ARCIS_DB_PATH` and the canonical `DB_PATH` constant. This is the only category (b) finding reachable from the live watch loop.

**Current behavior**
> ```python
> _db = config.get("db_path", "data/ai_research_desk.sqlite3")
> ```

When the caller's `config` dict omits a `db_path` key, the fallback resolves to a CWD-relative path. CLAUDE.md "Repo Layout" documents that the canonical production DB lives *outside* the repo at `C:/arcis/data/ai_research_desk.sqlite3`, loaded via `src.config.DB_PATH` which reads `ARCIS_DB_PATH`. The fallback here ignores that env var and ignores the repo-root-anchored correct pattern at `src/config/__init__.py:56` (`str(_REPO_ROOT / "ai_research_desk.sqlite3")`). In production the fallback opens (and may create) an empty SQLite file at `<cwd>/data/ai_research_desk.sqlite3`; the subsequent `SELECT vix FROM vix_term_structure` returns no rows and `vix_val = None`, so MR candidates silently inherit default VIX behaviour.

**Expected behavior**
The VIX lookup inside `mr_scan_service` should resolve its database path from `src.config.DB_PATH` (or equivalently `os.environ.get("ARCIS_DB_PATH", ...)` with a `_REPO_ROOT`-anchored fallback). The caller's `config["db_path"]` override should still win when present.

**Reproduction**
```bash
# From any directory other than C:/arcis/halcyon-lab/ — including, notably, NSSM restarts with an unexpected AppDirectory:
cd /tmp
unset ARCIS_DB_PATH   # or simply do not pass db_path in the caller's config dict
python -c "from src.services.mr_scan_service import mr_scan; mr_scan({}, ...)"
# Observe: a new empty SQLite file at /tmp/data/ai_research_desk.sqlite3.
# Observe: VIX lookup returns None; MR scan proceeds with default VIX behaviour.
```

**Suggested fix (illustrative — NOT for this sprint)**
```python
from src.config import DB_PATH

_db = config.get("db_path", DB_PATH)
with sqlite3.connect(_db) as vc:
    ...
```

**Priority**
**P1 — production-reachable.** This runs inside the watch loop MR scan post-enrichment block. Silently degrades MR scan quality; no loud failure.

**Labels**
`bug`, `db-path`, `tech-debt`, `reachable-in-watch-loop`

**Blast radius**
**READ-ONLY.** The `sqlite3.connect()` here is used only for a `SELECT` against `vix_term_structure`. The wrong DB is read (or a brand-new empty file is auto-created), returning zero rows. No writes to the wrong DB; the primary harm is silent degradation of MR candidate quality rather than data corruption.

---

### Issue draft 2: Hardcoded DB path in `scripts/export_chatgpt_inputs.py:25` (+ `:75` argparse mirror)

**Summary**
`export_chatgpt_inputs.py` defaults its `db_path` parameter and its `--db` argparse flag to a CWD-relative literal, ignoring `ARCIS_DB_PATH`. Operator-invoked training-data export tool; not reachable from the watch loop.

**Current behavior**
> ```python
> def export_inputs(db_path="ai_research_desk.sqlite3", count=20, output="chatgpt_batch.txt"):
> ```
> ```python
> p.add_argument("--db", default="ai_research_desk.sqlite3")
> ```

Both defaults are CWD-relative literals. They do not consult `ARCIS_DB_PATH` and do not anchor to `_REPO_ROOT`. Contrast the correct pattern at `src/config/__init__.py:56`, which both reads the env var and anchors its fallback to the repo root. A peer script in the same directory (`scripts/fix_training_page.py:20`) already demonstrates the right shape for operator scripts: `os.environ.get("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")`.

**Expected behavior**
Default should be `os.environ.get("ARCIS_DB_PATH", str(<repo_root> / "ai_research_desk.sqlite3"))`, or ideally re-export `src.config.DB_PATH`. The argparse default must mirror the function default exactly.

**Reproduction**
```bash
unset ARCIS_DB_PATH
cd /tmp   # anywhere that is not the repo root
python /path/to/halcyon-lab/scripts/export_chatgpt_inputs.py
# Observe: a new empty SQLite file at /tmp/ai_research_desk.sqlite3.
# Observe: SELECT returns no closed trades; chatgpt_batch.txt is empty or header-only.
```

**Suggested fix (illustrative — NOT for this sprint)**
```python
import os
from pathlib import Path

_DEFAULT_DB = os.environ.get(
    "ARCIS_DB_PATH",
    str(Path(__file__).resolve().parents[1] / "ai_research_desk.sqlite3"),
)

def export_inputs(db_path=_DEFAULT_DB, count=20, output="chatgpt_batch.txt"):
    ...

# argparse:
p.add_argument("--db", default=_DEFAULT_DB)
```

**Priority**
**P2 — operator-script, low frequency, read-only.** Not reachable from the watch loop, but produces empty training exports silently when invoked from the wrong cwd.

**Labels**
`bug`, `db-path`, `tech-debt`

**Blast radius**
**READ-ONLY.** The script only `SELECT`s closed trades to build the ChatGPT batch file. Failure mode is an empty/stale export file, not data corruption. The export file itself is written to the filesystem, not the DB.

---

### Issue draft 3: Hardcoded DB path in `scripts/import_chatgpt_outputs.py:34` (+ `:89` argparse mirror) — WRITE PATH

**Summary**
`import_chatgpt_outputs.py` defaults its `db_path` parameter and its `--db` argparse flag to a CWD-relative literal, ignoring `ARCIS_DB_PATH`. **This is the worst of the five category (b) bugs because the script `INSERT`s into `training_examples` — a CWD-escape writes training data into a freshly-created wrong DB rather than failing loudly.**

**Current behavior**
> ```python
> def import_outputs(inputs_file, outputs_file, db_path="ai_research_desk.sqlite3"):
> ```
> ```python
> p.add_argument("--db", default="ai_research_desk.sqlite3")
> ```

Both defaults are CWD-relative literals ignoring `ARCIS_DB_PATH` and the repo-root-anchored correct pattern at `src/config/__init__.py:56`. Unlike the export sibling (`export_chatgpt_inputs.py`, which only reads), this script executes `INSERT INTO training_examples (...)` against whatever file `sqlite3.connect(db_path)` resolves. When invoked from any cwd other than the repo root (and without `--db`), `sqlite3.connect` will **auto-create** a new empty SQLite file at `<cwd>/ai_research_desk.sqlite3`, then successfully `INSERT` training rows into it. The operator sees "imported N rows" success output and believes the production `training_examples` table has grown — but the real DB at `C:/arcis/data/ai_research_desk.sqlite3` is untouched.

**Expected behavior**
Default should be `os.environ.get("ARCIS_DB_PATH", str(<repo_root> / "ai_research_desk.sqlite3"))`. Additionally, given the write semantics, this script should `raise FileNotFoundError` (or refuse to run) if the resolved DB path does not already exist as a non-empty file, rather than allowing `sqlite3.connect` to silently create a stub.

**Reproduction**
```bash
unset ARCIS_DB_PATH
cd /tmp
python /path/to/halcyon-lab/scripts/import_chatgpt_outputs.py \
    --inputs chatgpt_batch.txt --outputs chatgpt_replies.txt
# Observe: a new empty SQLite file at /tmp/ai_research_desk.sqlite3.
# Observe: rows INSERTed into the wrong DB.
# Observe: the real training_examples table at C:/arcis/data/ai_research_desk.sqlite3 is unchanged.
# Observe: stdout reports success.
```

**Suggested fix (illustrative — NOT for this sprint)**
```python
import os
from pathlib import Path

_DEFAULT_DB = os.environ.get(
    "ARCIS_DB_PATH",
    str(Path(__file__).resolve().parents[1] / "ai_research_desk.sqlite3"),
)

def import_outputs(inputs_file, outputs_file, db_path=_DEFAULT_DB):
    db_path_obj = Path(db_path)
    if not db_path_obj.exists() or db_path_obj.stat().st_size == 0:
        raise FileNotFoundError(
            f"Refusing to create a new DB at {db_path_obj}. "
            f"Set ARCIS_DB_PATH or pass --db pointing at an existing file."
        )
    ...

# argparse:
p.add_argument("--db", default=_DEFAULT_DB)
```

**Priority**
**P1 — worst failure mode in this cohort.** While the call site is operator-invoked (not watch-loop hot path), the combination of *write semantics* + *silent auto-creation of a stub DB on the wrong path* means a single absent-minded invocation can result in training data going to `/dev/null` for days before anyone notices the production `training_examples` row count is flat. Promote from P2 to P1 despite being operator-only.

**Labels**
`bug`, `db-path`, `tech-debt`, `data-integrity`

**Blast radius — WRITE (callout)**
**WRITE to the wrong DB.** This is the crucial distinction between this finding and all four other category (b) bugs. `import_chatgpt_outputs.py` executes `INSERT INTO training_examples (...)` against whatever file `sqlite3.connect` lands on. Because SQLite auto-creates the file when absent, the script **cannot fail loudly** the way a read-from-missing-DB would; it succeeds against a fresh stub. Two concrete downstream harms:
  1. **Lost training data** — rows written to the stub DB are never seen by Arcis training pipelines; the operator believes import succeeded but `training_examples` growth is zero.
  2. **Archive cutover risk** — per Pass 1 §4 and risk register row 6, the Friday archive sprint temporarily moves the live DB aside. If this script is run during the cutover window against the wrong cwd, it could either (a) write to a resurrected stub, or (b) dirty a half-archived DB. The archive-script preflight does *not* fix this bug; the mitigation is procedural (operator does not run import during the window).

---

### Issue draft 4: Hardcoded DB path in `scripts/render_architecture_doc.py:153`

**Summary**
`render_architecture_doc.py` passes an unconditional `ROOT / "ai_research_desk.sqlite3"` to `render_schema`, ignoring `ARCIS_DB_PATH`. The path does not exist on operator boxes where the canonical DB lives outside the repo, so the script raises.

**Current behavior**
> ```python
> schema_report = render_schema(ROOT / "ai_research_desk.sqlite3")
> ```

`ROOT` is the repo root. Per CLAUDE.md "Repo Layout" the canonical prod DB is at `C:/arcis/data/ai_research_desk.sqlite3`, not the repo root, so `ROOT / "ai_research_desk.sqlite3"` does not exist and `render_schema` raises on `sqlite3.connect` / open. The line does not consult `ARCIS_DB_PATH` or the repo-root-anchored correct pattern at `src/config/__init__.py:56`. Script docstring claims the SQLite database is a prerequisite — the prerequisite is not met on the operator box where the doc is actually rendered.

**Expected behavior**
Resolve DB path from `src.config.DB_PATH` (which honors `ARCIS_DB_PATH`), or read the env var directly with a repo-root-anchored fallback. Optionally accept a `--db` CLI flag for consistency with `schema_report.py`.

**Reproduction**
```bash
# On an operator box where the DB lives at C:/arcis/data/ai_research_desk.sqlite3:
cd /path/to/halcyon-lab
python scripts/render_architecture_doc.py
# Observe: FileNotFoundError / sqlite3.OperationalError from render_schema.
# Observe: no architecture doc produced.
```

**Suggested fix (illustrative — NOT for this sprint)**
```python
from src.config import DB_PATH

schema_report = render_schema(DB_PATH)
```

**Priority**
**P3 — defensive / doc-generation tool, low frequency.** Fails loudly (no silent write to a stub), run rarely (sprint-time doc regeneration), with no production impact. Easy fix; file for hygiene.

**Labels**
`bug`, `db-path`, `tech-debt`

**Blast radius**
**READ-ONLY.** `render_schema` reads the DB schema and returns markdown; there is no write path. Failure mode is a hard raise (not a silent wrong-DB read), so this is the most benign of the five bugs.

---

### Issue draft 5: Hardcoded DB path in `scripts/schema_report.py:125`

**Summary**
`schema_report.py` defaults its `--db` argparse flag to a CWD-relative literal, ignoring `ARCIS_DB_PATH`. Standalone schema dumper; not reachable from the watch loop.

**Current behavior**
> ```python
> parser.add_argument(
>     "--db",
>     default="ai_research_desk.sqlite3",
>     help="Path to the SQLite database (default: ai_research_desk.sqlite3)",
> )
> ```

The argparse default is a CWD-relative literal. It does not consult `ARCIS_DB_PATH` and is not anchored to `_REPO_ROOT`. Operators running `python scripts/schema_report.py` without `--db` must `cd` to a directory containing a file named exactly `ai_research_desk.sqlite3`, which on the canonical layout is nowhere (the real DB is `C:/arcis/data/ai_research_desk.sqlite3` — absolute path, and the repo root contains no such file per `halcyon-lab/` layout discipline in #642).

Note: this module is also imported as a library by `scripts/render_architecture_doc.py`, but the import path bypasses argparse, so that separate bug (draft 4) is distinct from this one.

**Expected behavior**
Default should be `os.environ.get("ARCIS_DB_PATH", str(<repo_root> / "ai_research_desk.sqlite3"))`, or re-export `src.config.DB_PATH`. Update the `help=` string to describe the env-var resolution so operators know what was picked.

**Reproduction**
```bash
unset ARCIS_DB_PATH
cd /tmp
python /path/to/halcyon-lab/scripts/schema_report.py
# Observe: sqlite3.OperationalError "unable to open database file", or an empty schema against a freshly-auto-created /tmp/ai_research_desk.sqlite3, depending on open-mode.
```

**Suggested fix (illustrative — NOT for this sprint)**
```python
import os
from pathlib import Path

_DEFAULT_DB = os.environ.get(
    "ARCIS_DB_PATH",
    str(Path(__file__).resolve().parents[1] / "ai_research_desk.sqlite3"),
)

parser.add_argument(
    "--db",
    default=_DEFAULT_DB,
    help=f"Path to the SQLite database (default: $ARCIS_DB_PATH or {_DEFAULT_DB})",
)
```

**Priority**
**P2 — operator-script, standalone CLI.** Not reachable from the watch loop. Fails either loudly (open error) or produces an empty schema dump against a stub, depending on filesystem state. Not data-corrupting.

**Labels**
`bug`, `db-path`, `tech-debt`

**Blast radius**
**READ-ONLY.** Script only reads `sqlite_master` and column metadata to produce a schema report. No INSERT / UPDATE / DELETE. Failure mode is either an error or a stale/empty report.

---

**Note on filing.** These are drafts only. Filing happens in Pass 3 after operator review. The archive script's preflight does NOT need to fix these — Pass 1 §4 and risk register row 6 cover operator procedural discipline during the cutover window. Promotion from operator-only (P2) to data-integrity (P1) for `import_chatgpt_outputs.py` should be confirmed with the operator during Pass 3 filing review.

<!-- SECTION:P2.4 END -->

---

## 5. Rollback procedure

<!-- SECTION:P2.5 START -->

Scenario: the archive cutover completed cleanly (see Pass 1 §4). Hours or days later, a problem surfaces — a data discrepancy, an ML model misbehaving on a truncated training window, a user-visible screen missing historical context, an ops review that demands pre-archive evidence. The decision is: **return to the bootcamp DB as the active DB**. This section is the step-by-step to do that safely.

### 0. Preconditions and guardrails (read before you touch anything)

- **The archive file MUST still exist.** Per Pass 1 §0 guardrail "No data deletion," the archive IS the recovery source for rollback — it is the only remaining copy of pre-archive history. Before anything else:
  ```powershell
  Get-Item C:\arcis\data\archive\ai_research_desk_bootcamp_2026-04-24.sqlite3 | Format-List FullName, Length, LastWriteTime
  ```
  If that file is missing, corrupted, or smaller than expected (pre-archive DB was ~1 GB), **STOP** — rollback is not possible from this host. Recover the archive from the off-box backup (the SHA-256 manifest from Pass 1 §4 is the integrity reference) before continuing. There is no workaround; no other file contains the pre-cutover state.
- **Rollback WILL discard post-cutover writes.** Every row inserted into `shadow_trades`, `training_examples`, `data_collection_runs`, `news_raw`, etc. since the cutover exists **only in the fresh DB**. The archive is frozen at the cutover SHA-256. If the operator needs to preserve any of those post-cutover writes, they must **export them first** (e.g. `sqlite3 .dump` of the affected tables, or a targeted `ATTACH DATABASE` + `INSERT ... SELECT` into a staging DB). That migration is out of scope for this doc — flag it to the operator and pause until they decide. See "Rollback window" note below.
- **Everything below requires an elevated PowerShell session** (same as `scripts/install_service.ps1`). NSSM service control refuses from a non-admin shell.

### 1. Decision gate — announce intent and confirm preconditions

**Cannot be automated.** Operator writes a short rollback-intent note (what went wrong, which post-cutover writes are being consciously discarded, who approved). File it to `docs/sprints/` or the ops log. This is the auditable record — if regulators or future-you asks why `shadow_trades` has a multi-hour gap, this note is the answer.

Verification: note exists and names (a) the archive path, (b) the fresh DB path, (c) the rollback operator.

### 2. Stop the watch loop service

```powershell
nssm stop ArcisWatchLoop
```

**Verification (cannot be fully automated — requires manual operator confirmation).** NSSM returns before the OS has reaped the python.exe child, and any externally-launched python process (an operator-started `python -m src.main scan`, a stuck Jupyter kernel, a test runner) will still hold a file handle to the fresh DB. Operator must confirm by eye:

```powershell
nssm status ArcisWatchLoop    # expect: SERVICE_STOPPED
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -match 'src\.main|watch|arcis' } |
  Select-Object ProcessId, CommandLine | Format-List
```

If the second command returns **any** rows, stop those processes (`Stop-Process -Id <pid> -Force`) and re-check. Proceeding with a live writer attached to the fresh DB is the single most likely way to produce a split-brain state where rollback "half-happens."

### 3. Release the PID lockfile if stale

The watch loop writes `data\watch.lock` via `src/scheduler/watch.py` and removes it in an `atexit` hook. An NSSM-killed process may skip `atexit`, leaving a stale lockfile that blocks the post-rollback `nssm start` (CLAUDE.md "Startup / Restart Sequence" section).

```powershell
if (Test-Path C:\arcis\halcyon-lab\data\watch.lock) {
    Get-Content C:\arcis\halcyon-lab\data\watch.lock   # print PID for the audit note
    Remove-Item C:\arcis\halcyon-lab\data\watch.lock
}
```

Verification: `Test-Path C:\arcis\halcyon-lab\data\watch.lock` returns `False`. Only run the `Remove-Item` after Step 2's "no python processes" check — removing an active lockfile while the watch loop is running is the failure mode CLAUDE.md warns against.

### 4. Rename the fresh DB aside — DO NOT DELETE

Rename, do not delete. The fresh DB holds every write that happened between cutover and rollback; even if we're discarding those writes from the active system, they are forensic evidence and may be needed later (e.g. to explain a discrepancy to an auditor, or to cherry-pick a single row back).

```powershell
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
Move-Item C:\arcis\data\ai_research_desk.sqlite3 `
          "C:\arcis\data\ai_research_desk_post_archive_$stamp.sqlite3"

# Also move the WAL/SHM sidecars if they exist — leaving them behind causes
# SQLite to ignore the rename on next open and silently re-create the main file.
if (Test-Path C:\arcis\data\ai_research_desk.sqlite3-wal) {
    Move-Item C:\arcis\data\ai_research_desk.sqlite3-wal `
              "C:\arcis\data\ai_research_desk_post_archive_$stamp.sqlite3-wal"
}
if (Test-Path C:\arcis\data\ai_research_desk.sqlite3-shm) {
    Move-Item C:\arcis\data\ai_research_desk.sqlite3-shm `
              "C:\arcis\data\ai_research_desk_post_archive_$stamp.sqlite3-shm"
}
```

Verification (destructive step):
```powershell
Test-Path C:\arcis\data\ai_research_desk.sqlite3                          # expect False
Test-Path "C:\arcis\data\ai_research_desk_post_archive_$stamp.sqlite3"    # expect True
Get-Item   "C:\arcis\data\ai_research_desk_post_archive_$stamp.sqlite3" |
  Format-List FullName, Length                                            # size is non-zero and plausible
```

If both `Test-Path` checks return the same answer, the rename failed — investigate before continuing. Do **not** manually create a zero-byte `ai_research_desk.sqlite3` placeholder; Step 5 puts the real file in place.

### 5. Choose the rollback source and install it as the active DB

There are two valid sources, in this order of preference:

**Option A (preferred) — the pre-archive backup produced by cutover:**
`C:/arcis/data/ai_research_desk.pre_archive.sqlite3` (Pass 1 §4 cutover choreography leaves this file in place specifically for this reason). It is byte-identical to the pre-cutover active DB. Use if it still exists.

**Option B (fallback) — the archive itself:**
`C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3`. Functionally equivalent (VACUUM INTO produces the same row set), but the archive is the canonical long-term preservation copy; making it the live DB means future writes will mutate it. Prefer Option A so the archive stays pristine. If you must use Option B, **copy, don't move** — the archive file must survive rollback so that a future re-rollback or forensic query is still possible.

```powershell
# Option A (preferred): restore from the pre-archive backup.
Copy-Item C:\arcis\data\ai_research_desk.pre_archive.sqlite3 `
          C:\arcis\data\ai_research_desk.sqlite3

# OR Option B (fallback): restore from the archive. Copy, NEVER move.
# Copy-Item C:\arcis\data\archive\ai_research_desk_bootcamp_2026-04-24.sqlite3 `
#           C:\arcis\data\ai_research_desk.sqlite3
```

Verification (destructive step):
```powershell
Test-Path C:\arcis\data\ai_research_desk.sqlite3                                    # expect True
(Get-Item C:\arcis\data\ai_research_desk.sqlite3).Length                            # expect ~1 GB
# If Option B: confirm the archive was COPIED, not moved.
Test-Path C:\arcis\data\archive\ai_research_desk_bootcamp_2026-04-24.sqlite3        # must remain True

# Quick integrity probe — opens in read-only mode, runs SQLite's built-in check.
sqlite3 "file:C:/arcis/data/ai_research_desk.sqlite3?mode=ro" "PRAGMA integrity_check;"
# expect a single line: "ok"
```

If `PRAGMA integrity_check` returns anything other than `ok`, **STOP**, reverse Steps 4–5 (undo the rename and the copy), and investigate. A corrupt source file means this host cannot complete rollback from local state.

### 6. Confirm `ARCIS_DB_PATH` points at the active DB

`ARCIS_DB_PATH` is read once per process at `src/config/__init__.py:56`, after `load_dotenv()` runs at `src/config/__init__.py:44`. Two places to check, in resolution order:

**(a) `C:\arcis\halcyon-lab\.env` (primary — this is what the NSSM service sees).**
`scripts/install_service.ps1:92` sets `AppDirectory` to the repo root, so `python-dotenv` auto-discovers this `.env` on service start. The cutover (Pass 1 §4) did NOT change `ARCIS_DB_PATH` — it re-used the same canonical path `C:/arcis/data/ai_research_desk.sqlite3`. If that is still the value, **no edit is needed**. Confirm with:

```powershell
Select-String -Path C:\arcis\halcyon-lab\.env -Pattern '^ARCIS_DB_PATH='
# expect: ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3
```

If the cutover did change the path (unlikely in the current spec but possible in a future variant), edit `.env` — prefer restoring the pre-archive `.env` from an operator backup if one was kept, otherwise hand-edit the single line.

**(b) NSSM service environment (`AppEnvironmentExtra`) — currently NOT set, per Pass 1 §4.**
`scripts/install_service.ps1` does not configure `AppEnvironmentExtra` (verify lines 88–107 — no such call), which means the service has no service-scoped env vars and falls through to `.env`. Confirm this is still true:

```powershell
nssm dump ArcisWatchLoop | Select-String AppEnvironmentExtra
# expect: no match (or the line is absent)
```

If `AppEnvironmentExtra` **is** present with `ARCIS_DB_PATH=...`, it overrides `.env` for the NSSM process (already-set env wins in `load_dotenv()`, per `src/config/__init__.py:44` docstring and Pass 1 §4). Update it via `nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` — or remove it entirely to defer to `.env`.

**(c) Operator's shell environment — a stale `$env:ARCIS_DB_PATH` in the operator's interactive PowerShell will silently win over `.env` for any command the operator runs directly (not through the service).**
After any `.env` edit, the operator **must open a fresh shell** before running `python -m src.main ...` manually. Cannot be automated — it is operator hygiene.

Verification (cannot be fully automated):
```powershell
# Fresh shell. Confirm no shell-scoped override lingering.
$env:ARCIS_DB_PATH      # expect blank OR matches .env
```

### 7. Start the watch loop

```powershell
nssm start ArcisWatchLoop
```

Verification:
```powershell
nssm status ArcisWatchLoop        # expect: SERVICE_RUNNING
Get-Service -Name ArcisWatchLoop  # Status: Running
# First log lines — the service should log the DB_PATH it opened.
Get-Content C:\arcis\halcyon-lab\data\logs\service.out.log -Tail 50
```

Confirm the log shows `DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` (or your `.env` value) and no schema-validation errors on startup.

### 8. First-scan verification against the archive baseline

Parallel to Pass 2 §6 but from the rollback direction. After rollback, the live DB should **match the archive's row counts**, because rollback is supposed to have returned the system to exactly the archive's state.

Run the Pass 1 §6 row-count query against both files and compare:

```powershell
$tables = 'shadow_trades','training_examples','data_collection_runs','news_raw','positions','orders'
foreach ($t in $tables) {
    $live    = sqlite3 "file:C:/arcis/data/ai_research_desk.sqlite3?mode=ro"                              "SELECT COUNT(*) FROM $t;"
    $archive = sqlite3 "file:C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3?mode=ro"  "SELECT COUNT(*) FROM $t;"
    '{0,-25} live={1,-10} archive={2,-10} match={3}' -f $t, $live, $archive, ($live -eq $archive)
}
```

**Expected result:** every `match=True`. If any row shows `match=False`, **rollback is incomplete or the archive was mutated since cutover**. Investigation paths:

- `match=False` with `live > archive` → the rollback source was NOT the archive/pre-archive copy; possibly picked up a stale WAL from the fresh DB (re-check Step 4's WAL/SHM rename).
- `match=False` with `live < archive` → the source file is truncated or the copy in Step 5 did not complete. Re-run Step 5.
- Any mismatch in a **static** table (e.g. `tickers`, `schema_migrations`) → archive integrity is suspect; verify against the cutover SHA-256 manifest (Pass 1 §4).

Then run a one-shot dry-run scan to confirm the watch loop can open the DB and pass schema validation:

```powershell
cd C:\arcis\halcyon-lab
.\.venv\Scripts\python.exe -m src.main validate-schema
.\.venv\Scripts\python.exe -m src.main preflight
.\.venv\Scripts\python.exe -m src.main scan --verbose --dry-run
```

All three should exit 0 with no schema drift. If they do not, the rollback DB is internally inconsistent — do not resume live trading.

### 9. Operator communications

**Cannot be automated.** Notify the rollback reason via the normal channels (Telegram ops channel, the rollback-intent note from Step 1, the post-mortem doc), including:
- What window of post-cutover writes was discarded (timestamp range from Step 2's `$stamp`).
- Where the post-cutover DB is parked (`ai_research_desk_post_archive_$stamp.sqlite3`).
- Whether the archive is still the Option B source (if Option A was unavailable, flag that the cutover-backup hygiene policy needs revisiting).

### Rollback window note

The time between cutover and rollback is a direct cost. Every hour of watch-loop activity adds rows to the fresh DB that rollback will drop. For a production-active trading day this can be hundreds of shadow trade events, dozens of training examples, the full day's news ingest, and every enrichment the overnight schedule produced. After 24 hours: roughly a day's worth of live-state divergence. After a week: essentially a new DB, and rollback becomes a destructive "revert the last week" operation.

Practical consequences:

- **Inside the first few hours**: rollback is cheap — minimal post-cutover writes, divergence is trivial. Run the procedure above and move on.
- **First full trading day**: measurable data loss — shadow trades, training examples, probably a packet run. Operator should explicitly decide whether to preserve the post-cutover writes (export-and-merge, out of scope for this doc) or accept the loss.
- **Multi-day or longer**: rollback is almost never the right call. Prefer a targeted fix or a forward-migration. If rollback is still chosen, treat the discarded window as a formal outage event and file a full post-mortem.

If the operator wants to preserve specific post-cutover tables, the correct flow is (conceptually):
1. Complete Steps 1–4 above (the post-archive DB is now parked as `ai_research_desk_post_archive_$stamp.sqlite3`).
2. Complete Step 5 (restore the rollback source to the canonical path).
3. **Before Step 7**, `ATTACH DATABASE` the parked post-archive DB from a Python or sqlite3 session and `INSERT ... SELECT` the desired rows into the rolled-back active DB. This is schema-coupled, row-identity-sensitive work and must NOT be attempted without an explicit plan and a dry-run — it is a separate sprint. Flag and escalate.
4. Then resume Step 7 (`nssm start`).

<!-- SECTION:P2.5 END -->

---

## 6. Post-archive first-scan verification

<!-- SECTION:P2.6 START -->
Operator-facing checklist for the first 1–2 scan cycles after Friday cutover + watch-loop restart.

### 6.1 Intake — values used by this checklist

Resolved before writing to avoid generic assertions:

- **`ACTIVE_STATUSES`** (from `src/shadow_trading/models.py:20`): `{"pending", "open", "exit_pending", "exit_failed", "submission_uncertain"}`
- **`TERMINAL_STATUSES`** (from `src/shadow_trading/models.py:19`): `{"closed", "rejected", "failed", "exit_abandoned", "needs_manual_review"}` — not queried below but cited because a terminal row in the fresh DB (unexpectedly) would also be a red flag.
- **Watch-loop log file:** `logs/arcis.log` (configured by `src/main.py:296` → `setup_logging()`; `RotatingFileHandler` mounted by `src/scheduler/watch.py:1161`). Runtime log path mirrored under `C:/arcis/logs/arcis.log` per CLAUDE.md.
- **Watch-loop service:** NSSM Windows service `ArcisWatchLoop` (per operator memory). Restart via `nssm restart ArcisWatchLoop`, not direct `python -m`.
- **PID lockfile:** `data/watch.lock` — presence with no live process after cutover would block startup.
- **Fresh DB contract (Pass 1 §6):** no seeded rows in `shadow_trades` or `training_examples`. All counts start at zero.

### 6.2 Dashboard wiring status — classification (c): NO WIRING EXISTS

The sprint spec frames observations 4 and 5 in terms of a dashboard with a "Bootcamp history" view (reads Postgres, shows the 88 archived trades) and a "Post-archive live" view (reads SQLite, shows zero counts). **These views do not exist in the codebase as of `d32fb5d`.**

Evidence — grep results run 2026-04-24 against `frontend/src/` and `src/api/`:

| Query | Result |
| --- | --- |
| `"Bootcamp history" / bootcamp_history / BootcampHistory` | No hits. |
| `"Post-archive" / post_archive / PostArchive` | Only hits are in `docs/sprints/friday_archive_sprint_*.md` (this sprint's own docs) — no source code. |
| `archive_date / cutover_date / archived_before / archive_cutover` | No hits anywhere. |
| `data_source / source=postgres / source=sqlite / data_origin` | No hits in `src/api/`. |
| `2026-04-24 / 2026-04-25` hardcoded in frontend | No hits. |
| `bootcamp|Bootcamp` in `frontend/src/` | Hits exist but are unrelated — `Roadmap.jsx` (phase-1 narrative), `Settings.jsx` / `QuickStatsPanel.jsx` / `DiagnosticKickoffButtons.jsx` (bootcamp feature-flag). None are a "history vs live" split. |
| `bootcamp` in `src/api/` | One hit in `cloud_routes/core.py` — the `bootcamp` entry in the default config dict (`enabled`, `phase`, `max_positions`). Not a dashboard view. |

**Consequence:** observations 4 and 5 as originally phrased are **aspirational**. The cross-source verification they describe (Postgres = 88, SQLite = 0, operator navigates between two named views) cannot be performed because the views don't exist. This is out-of-scope for Pass 2 / Pass 3 and belongs to a later dashboard-wiring sprint.

Observations 4 and 5 below are restated in terms of what the operator **can** verify today (existing dashboard panels + a direct Postgres read) and the aspirational version is flagged as a follow-up.

### 6.3 The five required observations — first 1–2 scan cycles

#### Observation 1 — Zero active shadow trades

Fresh SQLite has no rows at all, and the first scan must not spuriously insert any. Query against the `ARCIS_DB_PATH` SQLite (read-only mode to avoid locking the writer):

```bash
sqlite3 -readonly "C:/arcis/data/ai_research_desk.sqlite3" \
  "SELECT COUNT(*) FROM shadow_trades WHERE status IN ('pending','open','exit_pending','exit_failed','submission_uncertain');"
```

Expected: `0`.
Also verify total row count is zero (no terminal-status leftovers): `SELECT COUNT(*) FROM shadow_trades;` → `0`.

#### Observation 2 — Zero training examples

```bash
sqlite3 -readonly "C:/arcis/data/ai_research_desk.sqlite3" \
  "SELECT COUNT(*) FROM training_examples;"
```

Expected: `0`. If this is non-zero post-cutover it means the fresh-DB script skipped `training_examples` or a scheduled collection task ran before verification — investigate before proceeding.

#### Observation 3 — Scan cycle completes end-to-end without errors

Tail the log:

```bash
tail -n 500 C:/arcis/logs/arcis.log | grep -E "(ERROR|CRITICAL|Traceback|INTEGRITY)"
```

Expected: no matches across the first two scan-cycle windows. A clean scan emits the following markers (see `src/scheduler/watch.py:876, 899, 965`):

- `[WATCH] All SQLite tables verified/created` — once at startup.
- `[DB] SQLite configured: WAL mode, synchronous=NORMAL, busy_timeout=5000ms` — once at startup.
- `[WATCH] Recorded scan_metrics #1 (packets=…)` — end of first scan cycle.
- `[WATCH] Recorded scan_metrics #2 (packets=…)` — end of second scan cycle.

If `_ensure_all_tables()` at `watch.py:965` emits a `CRITICAL` (`SCHEMA CREATION FAILED`) the loop aborts — this is a hard stop.

#### Observation 4 — Dashboard "Post-archive live" view shows zero counts

**Status: aspirational (classification (c) above).** No such view is wired.

**What the operator CAN verify today** as a substitute (existing panels that read from the live SQLite DB):

- `frontend/src/components/system/QuickStatsPanel.jsx` — live-stats tiles driven by `_get_live_stats()` in `src/scheduler/watch.py:532`. After cutover these should read: open shadow trades = 0, training examples = 0, positions = 0.
- Dashboard log viewer (DB-handler rows in `logs` table via `DBLogHandler` at `src/scheduler/watch.py:54`) — operator watches the live log feed for a clean first scan.

**Follow-up (not in this sprint):** implement an explicit "Post-archive live" view that filters shadow trades by a `created_at >= <cutover_ts>` predicate, so historical post-close rows (once they exist in SQLite post-archive) are visually separated from pre-archive artifacts. Candidate owner: frontend pair after Pass 3 archive script lands.

#### Observation 5 — Dashboard "Bootcamp history" view still shows 88 trades from Postgres

**Status: aspirational (classification (c) above).** No such view is wired. There is no route in `src/api/` that queries Postgres for archived shadow trades, and no frontend component that selects between a SQLite and a Postgres data source.

**What the operator CAN verify today** as a substitute — direct Postgres read against the Render DB (see `scripts/render_migrate.py` for connection extraction pattern):

```bash
DATABASE_URL=$(python -c "import yaml; cfg=yaml.safe_load(open('config/settings.local.yaml')); print(cfg['render']['database_url'])") \
  psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM shadow_trades;"
```

Expected: `88` (the archived bootcamp trade count per Pass 1 §6; confirm against the count snapshot recorded pre-archive).

**Follow-up (not in this sprint):** implement a read-only `/api/bootcamp-history` route that reads from Postgres and a frontend panel that renders it side-by-side with live SQLite data. Flagged explicitly as a Pass-3-or-later dependency; not blocking the Friday cutover.

### 6.4 Early-warning signals — watch during the first 1–2 scans

Observe without acting unless a red-flag threshold is crossed (next section).

- **WAL file growth** — `C:/arcis/data/ai_research_desk.sqlite3-wal`. On a fresh DB this should remain well under 10 MB through the first two scans. Sudden growth past 50 MB during a non-checkpoint window indicates a long-running writer holding a transaction open.
- **`logs/arcis.log` WARN entries** — `grep -c "WARNING" logs/arcis.log` after each scan. One or two warnings per scan (e.g. `_get_live_stats DB error` debug-downgrade at `watch.py:532`) are normal; a double-digit count in a single scan is not.
- **NSSM service status** — `nssm status ArcisWatchLoop` should stay `SERVICE_RUNNING`. Any transition to `SERVICE_STOPPED` or `SERVICE_PAUSED` is a halt condition.
- **PID lockfile sanity** — `data/watch.lock` exists, and its PID matches a live `python.exe` that has `watch` in its command line. If the PID is dead, the next `startup` call will refuse to launch.
- **Schema drift** — at startup the loop runs `_ensure_all_tables()`. If the log emits `[WATCH] All SQLite tables verified/created` without a preceding `ALTER TABLE` message stream, the registry matched the fresh DB cleanly. Any `ALTER TABLE` noise on a fresh DB suggests the archive script left partial schema behind.
- **Busy timeout errors** — `grep "database is locked" logs/arcis.log`. Expected: zero on the fresh DB. Per CLAUDE.md, external tools opening the SQLite file while the watch loop runs will cause these — check that no MS Access / DBeaver / DB Browser session is attached.
- **Telegram startup notification delivered** — `grep "Telegram startup notification" logs/arcis.log`. Absence of a success log (or presence of the `[WATCH] Telegram startup notification failed` warning at `watch.py:649`) means the operator may not see out-of-band alerts until the next scheduled digest.

### 6.5 Red flags — halt the watch loop and investigate before proceeding

If any of the following occurs during the first 1–2 scans, immediately run `nssm stop ArcisWatchLoop`, open `C:/arcis/logs/arcis.log`, and consult an ARCIS maintainer before restarting:

1. **`CRITICAL` entries in `logs/arcis.log`** — specifically `SCHEMA CREATION FAILED` (`watch.py:975`) or `INTEGRITY CHECK FAILED` (`watch.py:994`). The DB is unusable.
2. **Non-zero `shadow_trades` count on a fresh DB** before the first scan has been allowed to open any positions (i.e. observed during the pre-first-scan verification window). The archive script left data behind.
3. **Non-zero `training_examples` count on a fresh DB.** Same cause class as (2).
4. **Any `Traceback` block** in the log within the first two scan cycles. Even if the loop continues, a traceback indicates an unhandled path that regression tests did not cover.
5. **WAL file exceeds 100 MB** on a fresh DB during the first two scans. Indicates a stuck writer or a runaway transaction; checkpoint is not keeping up.
6. **`database is locked` count > 5** in `logs/arcis.log` across the first two scans — external tool contention or a stuck connection holding the DB. Close external tools first (per CLAUDE.md "Database Access Rules").
7. **NSSM service transitions out of `SERVICE_RUNNING`** — the loop died silently. Must be diagnosed before restart; do not just `nssm start`.
8. **Postgres `shadow_trades` count has changed** from the pre-archive snapshot (e.g. not 88). The archive is supposed to be frozen historical; any drift means something else is writing to Postgres.
9. **Second scan's `scan_metrics` row is missing** from the SQLite DB (`SELECT COUNT(*) FROM scan_metrics;` should be ≥ 2 after two scans per `watch.py:899`). The loop is not completing scan cycles even if logs look clean.

### 6.6 Ticking checklist — operator mark-off

Run through after `nssm restart ArcisWatchLoop` completes and the startup banner has printed.

**Pre-first-scan verification (within 60 seconds of restart):**
- [ ] `nssm status ArcisWatchLoop` returns `SERVICE_RUNNING`.
- [ ] `data/watch.lock` exists and its PID matches the live watch process.
- [ ] `logs/arcis.log` shows `[WATCH] All SQLite tables verified/created`.
- [ ] `logs/arcis.log` shows `[DB] SQLite configured: WAL mode, synchronous=NORMAL, busy_timeout=5000ms`.
- [ ] No `CRITICAL` / `Traceback` / `INTEGRITY CHECK FAILED` entries in `logs/arcis.log` since restart.
- [ ] `SELECT COUNT(*) FROM shadow_trades;` on SQLite returns `0`.
- [ ] `SELECT COUNT(*) FROM shadow_trades WHERE status IN ('pending','open','exit_pending','exit_failed','submission_uncertain');` returns `0`.
- [ ] `SELECT COUNT(*) FROM training_examples;` returns `0`.
- [ ] WAL file (`ai_research_desk.sqlite3-wal`) exists and is < 10 MB.

**First scan cycle:**
- [ ] `[WATCH] Recorded scan_metrics #1` appears in `logs/arcis.log`.
- [ ] No new `ERROR` / `CRITICAL` / `Traceback` since restart.
- [ ] `database is locked` count in `logs/arcis.log` is `0`.
- [ ] `QuickStatsPanel` on the live dashboard shows `open_shadow_trades = 0` and `training_examples = 0`.

**Second scan cycle:**
- [ ] `[WATCH] Recorded scan_metrics #2` appears in `logs/arcis.log`.
- [ ] `SELECT COUNT(*) FROM scan_metrics;` returns `>= 2`.
- [ ] No new `ERROR` / `CRITICAL` / `Traceback` since first scan.
- [ ] WAL file still < 10 MB (auto-checkpoint is working).
- [ ] `nssm status ArcisWatchLoop` still `SERVICE_RUNNING`.

**Postgres historical verification (once per cutover, not per scan):**
- [ ] Direct `psql` read against Render Postgres returns `SELECT COUNT(*) FROM shadow_trades;` = `88` (matches pre-archive snapshot).
- [ ] Pre-archive and post-archive Postgres count deltas both equal zero (no drift).

**Aspirational — flagged as NOT in this sprint, requires later dashboard work:**
- [ ] (deferred) "Post-archive live" dashboard view renders zero counts.
- [ ] (deferred) "Bootcamp history" dashboard view renders 88 Postgres-sourced trades.
- [ ] (deferred) Follow-up issue filed for the two views above.

If every non-deferred box is ticked after two scan cycles, the cutover is successful and the operator can move to the standard overnight schedule. Any unchecked non-deferred box requires investigation before the third scan.
<!-- SECTION:P2.6 END -->
