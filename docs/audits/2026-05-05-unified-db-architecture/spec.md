# Unified DB Architecture Investigation — Design Spec

**Audit**: `docs/audits/2026-05-05-unified-db-architecture/spec.md`
**Date**: 2026-05-05
**Status**: SPEC-ONLY (no plan, no task graph). Recommendation reached HIGH conviction **conditional on three operator-answered prerequisites** — see §0.
**Author**: Architect (arcis:design)
**Read-time**: 25-35 min for full read; 8 min for the §0 Prerequisites + §5 Recommendation only.
**Revision history**:
- v1 (initial): full investigation across 4 options, 12 design decisions.
- v2 (citation cleanup): registry line numbers re-anchored at `name=` declarations after Phase 7 feasibility caught systematic 11-29 line drift; cloud-routes dual-mode list trimmed to verified entries; mode counts re-tallied to 50+5+6+9=70; test floor re-anchored as CLAUDE.md-codified.
- v3 (devil's advocate concerns): added §0 prerequisite block; conviction made conditional; trading-state safety claim rewritten to distinguish READ vs WRITE coupling; §4.5 added (Option E — Cloudflare Tunnel) per DA finding that B3 dismissal was premature; §6.5 re-sequenced (H4 must precede H3 + H5); H1/H3/H4 effort estimates raised +30%; H5 risk rating raised Low→Low-Medium with H4 prerequisite; §11 design decisions extended to 15 entries with new rows for Option E and the H4-as-prerequisite sequencing.

---

## 0. Prerequisites — answer before committing to harden work

**The HIGH conviction in §5 is conditional on three operator-answered prerequisites.** If any answer flips, the recommendation re-evaluates to MEDIUM (or shifts to Option E). Answer these BEFORE the harden bundle (§6) is dispatched:

1. **Render Postgres monthly bill** — `render.yaml:32` declares `sync: false`, so the PG tier is set manually in the Render dashboard and not visible in repo. If the bill is **≤ $25/mo**, Option C is cost-dominant. If the bill is **> $50/mo**, Option E (Cloudflare Tunnel — eliminates Render PG entirely) becomes the cost-dominated winner and Option C harden tasks H2/H3/H6 should be deferred until E is evaluated.
2. **Backup-machine plan within next 6 months** — if **NO**, the single-host invariant stays cheap and H6 (`target_host` on `pending_commands`) remains a low-priority preparation task. If **YES**, the recommendation downgrades from HIGH to MEDIUM and Option A (which gives cleaner multi-host coordination via PG advisory locks) becomes worth revisiting before committing to harden investment.
3. **Cloud dashboard usage frequency** — if **≥ 10 hits/day**, the Render-hosted dashboard pays for itself and Option C harden discipline is the right investment. If **< 10 hits/day**, Option E (Cloudflare Tunnel) becomes the cost-dominated winner — at $0/mo and zero sync layer, it dominates Option C's 5-7 person-weeks of harden work for a low-traffic dashboard.

Two additional questions are useful but not blocking:

4. Should H1 use psycopg2 (sync, battle-tested) or psycopg3 (async, future-proof)? Default: psycopg2 unless operator wants to invest in async-route refactor.
5. Should H4 testcontainers-PG run on every PR or weekly? Default: weekly (matches arcis CI conventions; every-PR adds 5-15 min latency).

---

## 1. Overview

**Problem statement.** The Arcis system runs a dual-store database architecture: a primary local SQLite (`C:/arcis/data/ai_research_desk.sqlite3`, 398MB, 70 tables) on the operator's Windows machine, plus a Render-hosted Postgres mirror that backs the cloud dashboard at `halcyonlab.app`. A `RenderSyncThread` daemon (`src/sync/render_sync.py`, 1359 lines) pushes 61 of the 70 tables to Postgres on a 120s cadence and pulls a small reverse stream (`pending_commands`, `config_overrides`, `user_notes`) the other way. The dual-store taxonomy has accumulated nine months of incident-driven complexity: three sync modes (incremental / full / latest_only), strip-id rules gated on column type and mode, savepoint-protected DELETE+INSERT for snapshot tables, per-table reconnection retries, host-keyed in-flight locks, ROWID auto-repair, and a function-level `if DATABASE_URL` branching pattern repeated across 6+ cloud route files. Wave 4 just closed three more sync-impedance bugs (H1 #930, H2 #931, H3 #932). The question this spec answers: **is consolidation now worth it, or is this dual-store overengineered for the scale and we should harden what we have?**

**Outcome of analysis.** I recommend **Option C — Status Quo + Targeted Hardening** at **HIGH conviction conditional on §0 prerequisites**, with one structural addition (a thin DB-engine abstraction at `src/utils/db.py` — the Option-D fragment described below). Three reasons drive this against my prior expectation that consolidation would win:

1. **Trading READS are structurally sync-independent (writes are partially coupled).** The shadow-trading reconciler at `src/shadow_trading/reconcile_state.py:32-44` reads `MAX(updated_at)` from local SQLite only — local-initiated trading entry/exit, the automated risk governor, and the watch-loop reconciler all run independent of Postgres availability. None of the Wave 4 sync incidents (#930/#931/#932) corrupted trade state — they degraded the dashboard. **However**, cloud-initiated trading commands (e.g., a `close_position` issued from the dashboard) flow via `pending_commands` through the PG → local pull arrow at `render_sync.py:839-960`, so dashboard-driven trading actions ARE coupled to PG availability — and the documented race window (§2.5) means they can be silently lost. The safety property is therefore **asymmetric**: read-side trading is sync-independent; write-side cloud-initiated trading is partially coupled. Migrating to all-Postgres (Option A) would couple BOTH sides to PG availability — a strict regression on the read side. This asymmetric framing matters because it bounds future feature additions: any new feature that adds cloud-initiated trading actions (dashboard-set risk overrides, position caps, scheduled liquidations) erodes the safety property silently. §5.4 names this as a downgrade trigger.
2. **The bidirectional command queue blocks the cheap consolidation path.** `pull_commands` (`render_sync.py:839-960`) flows Postgres → local. Vanilla Litestream is one-way SQLite → S3 — incompatible. libsql/Turso preserves bidirectional writes but introduces vendor dependency on a 2022-founded company and ~300-500 LOC of cloud-route rewrites. The Option-B family is therefore either infeasible (Litestream) or risky (Turso). **One consolidation path that DOES eliminate the queue cleanly: Option E (Cloudflare Tunnel — §4.5), where dashboard makes HTTP calls directly to the operator's local FastAPI via tunnel; `pending_commands` goes away entirely.** That option is bracketed by §0 prerequisite #3 (dashboard usage frequency).
3. **Tests are 100% SQLite-fixture-bound.** The CLAUDE.md-codified test floor of 3682 tests is currently met by 4574 collected tests (per `pytest --collect-only` on 2026-05-05); ALL of them go through `tests/conftest.py::init_test_db` (`tests/conftest.py:32-50`) against in-process SQLite. `test_render_sync.py` mocks psycopg2 with MagicMock. Migrating to all-Postgres requires `pytest-postgresql` (or testcontainers) plus rewrites to ~60-80 test files. ~1-3 person-weeks of disciplined work. Real, but more importantly: it eliminates the SQLite-vs-Postgres impedance mismatch class of bugs (#185/#243/#797/H2/H3) only AFTER the migration, while introducing a different class of bugs during the migration. (Note: H4 — testcontainers-PG CI — is recommended within Option C precisely to start catching this drift class without paying the full Option-A migration cost.)

The remaining pain (sync_state lock, dashboard-blind tables, MS Access lock incident, Render cold-starts, dual-mode branching) can be neutralized incrementally with seven prioritized harden tasks at substantively lower risk than full consolidation. The honest read on dual-store is that it WAS overengineered relative to the underlying problem — a single-operator, single-writer, 398MB system shouldn't need three sync modes — but that complexity is now mostly latent: it's compiled into the codebase, well-tested in production, and getting cheaper to maintain after each Wave-N round of fixes. Tearing it out now buys less than tearing it out a year ago would have, while paying a comparable migration cost.

I flag five sources of residual uncertainty in §9.

---

## 2. Current architecture analysis

### 2.1 Topology

Three tiers, two engines, one schema source-of-truth:

- **Tier 1 (local writer)**: Operator's Windows machine. Watch loop daemon (`src/scheduler/watch.py`) is the sole continuous writer. Writes go to local SQLite at `C:/arcis/data/ai_research_desk.sqlite3` (`src/config/__init__.py:50-58` — the comment block at L50-56 + the `_DB_PATH_ENV = os.environ.get("ARCIS_DB_PATH")` resolution at L58). Auxiliary local FastAPI binds 127.0.0.1 (`src/api/app.py`) — not exposed to network.
- **Tier 2 (sync layer)**: `RenderSyncThread` (started at `src/scheduler/watch.py:1362-1363` — the `from src.sync.render_sync import start_render_sync` import + the `sync_thread = start_render_sync(...)` call; body at `src/sync/render_sync.py:1100-1359`) pushes 61 of 70 tables to Postgres on a 120s cycle, pulls `pending_commands` + `config_overrides` back, and reconciles ghost rows.
- **Tier 3 (cloud reader)**: Render-deployed FastAPI service (`src/api/cloud_app.py`, 338 lines) at `halcyon-api.onrender.com` reads Postgres and serves the React frontend at `halcyonlab.app`. Database plan declared `sync: false` at `render.yaml:32` — the Postgres tier is set manually in the Render dashboard, NOT visible in the repo.

Schema registry (`src/schema/registry.py`, 2495 lines, 70 `TableDef` entries) is the single source of truth. CI guardrails (`test_no_create_table_in_source`, `test_no_alter_table_in_source` per CLAUDE.md) block any DDL outside `src/schema/`. SQLite DDL is generated by `src/schema/sqlite.py::generate_create_sql`; Postgres DDL by `src/schema/postgres.py::generate_create_sql` invoked at sync startup (`render_sync.py:1083-1085`). DDL drift is auto-corrected each cycle.

### 2.2 Sync modes — three classifications, one impedance origin

The sync layer maintains a per-table mode classification at `src/schema/sync_config.py` derived from each `TableDef.sync_mode`. Total breakdown across the 70 tables: **50 incremental + 5 full + 6 latest_only + 9 SQLite-local-only = 70**.

- **`incremental`** (50 tables). Cursor-based: rows where `time_col > last_synced_at`. Default for tables with monotonic time-ordered inserts (e.g., `shadow_trades`, `scan_metrics`, `news_items`).
- **`full`** (5 tables). Entire-table replace. Used for small singleton-state tables: `model_versions` (`registry.py:430`), `council_parameter_state` (`:823`), `traffic_light_state` (`:1325`), `strategy_registry` (`:2083`), `sp100_historical_constituents` (`:2371`). These five ARE the complete `full`-mode set — verified by the deep-report enumeration. Structural property: "latest snapshot IS the truth".
- **`latest_only`** (6 tables). DELETE + INSERT for `time_col = MAX(time_col)`. Used for daily-snapshot tables: `options_chains` (`:1012`), `options_metrics` (`:1047`), `cboe_ratios` (`:1079`), `google_trends` (`:1101`), `vix_term_structure` (`:1126`), `preflight_runs` (`:2438`). Wraps DELETE+INSERT in a Postgres SAVEPOINT (`render_sync.py:744-766`) so partial INSERT failure rolls back the DELETE — this is the #229 fix. Strips the `id` column on INSERT (`render_sync.py:741-742`) so Postgres SERIAL auto-generates — this is the #242 fix.
- **SQLite-only** (9 tables). `sync_to_postgres=False`. See §2.3.

A CRITICAL observation (focus area 1 of the deep report): the entire mode taxonomy exists because of SQLite ↔ Postgres impedance mismatches. SQLite's `INTEGER PRIMARY KEY` is a `ROWID` alias (the value is the rowid); Postgres's `SERIAL` is a separate sequence. Rows synced verbatim collide. The strip-id logic at `render_sync.py:608-614` is the consequence:

```python
strip_id = (
    pk == "id"
    and rows
    and not isinstance(rows[0].get("id"), str)  # #244: don't strip TEXT ids (UUIDs)
    and mode != "full"  # #797: don't strip in full mode (id is natural key)
)
```

Every branch in this expression is a fix for a specific sync incident. In a single-engine world (whichever engine), the taxonomy disappears and ~600 LOC of `render_sync.py` plus ~180 LOC of `sync_config.py` plus the entire `mode` field on `TableDef` are deletable. That's the size of the prize for consolidation.

A SECOND observation (also focus area 1): `live_prices` (`registry.py:2479`) was migrated FROM `latest_only` TO `incremental` in Wave 4 H3 (#932), with `sync_conflict_col='ticker'` for UPSERT-on-ticker semantics. So `latest_only` is not a permanent shape — operator already migrated one out. The remaining 6 `latest_only` tables are likely candidates for the same treatment over time.

### 2.3 SQLite-only tables — two architectural categories

The 9 tables with `sync_to_postgres=False` (re-anchored at `name=` declarations): `daily_ib_health` (`registry.py:382`), `model_evaluations` (`:521`), `preference_pairs` (`:612`), `sync_state` (`:1528`), `config_overrides` (`:1564`), `bracket_health` (`:1718`), `data_freshness` (`:1816`), `system_metrics` (`:1976`), `operator_view_state` (`:2219`). They split into two categories with very different consolidation implications:

**Category A — INTENTIONALLY local (5 tables)**:
- `sync_state` (`registry.py:1528`) — per-host in-flight lock + per-table cursor. Holds host-keyed lock rows used by `mark_sync_in_flight` (`render_sync.py:340-369`). Cannot synchronize itself via the sync pipeline — circular.
- `config_overrides` (`registry.py:1564`) — flows OPPOSITE direction (cloud → local). The SQLite copy is a cache; the origin is Postgres. The `pull_commands` function reverses the sync arrow at `render_sync.py:923-950`.
- `system_metrics` (`registry.py:1976`) — GPU/CPU/RAM telemetry from THIS machine. Synchronizing to cloud would mean cloud sees stale or wrong values during Render-vs-local clock drift; meaningless on cloud.
- `data_freshness` (`registry.py:1816`) — per-ticker fetch cursors used to deduplicate API calls. Machine-specific.
- `operator_view_state` (`registry.py:2219`) — per-operator dashboard view tracking. Local-only because the dashboard reads same registry in-process.

**Category B — INCIDENTALLY local (4 tables, COULD migrate to Postgres)**:
- `model_evaluations` (`registry.py:521`) — A/B test results.
- `preference_pairs` (`registry.py:612`) — DPO training data (training-only, but cloud could view).
- `bracket_health` (`registry.py:1718`) — bracket-order audit trail.
- `daily_ib_health` (`registry.py:382`) — IB Gateway daily metrics.

None of the Category B tables show on the dashboard. They are blind spots — operator must SSH/CLI to inspect. This is one of the legitimate harden-task candidates: add four tables to Postgres replication so the dashboard can show them.

### 2.4 Cloud route DB access pattern — function-level dual-mode branching

The cloud FastAPI uses `psycopg2` (sync) via the `get_pg()` contextmanager at `cloud_app.py:179-202` (the `@contextmanager` decorator at L179, the `def get_pg(...)` body at L180 through `if conn: ... close() ...` at ~L202):

```python
@contextmanager
def get_pg(readonly: bool = True):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_session(readonly=readonly, autocommit=readonly)
    yield conn
    ...
    finally:
        if conn:
            conn.close()
```

No connection pool. Every dashboard HTTP call pays the full TCP+TLS+psycopg2 auth handshake to Render Postgres (qualitative estimate: 50-200ms intra-datacenter — not measured here). This is one of the documented `render_free_tier_pain` items in CLAUDE.md operator memory.

A SURPRISING finding from the deep audit (focus area 4): six cloud-route files have **function-level dual-mode branches** — they check `DATABASE_URL` at runtime and route to PG (psycopg2) or SQLite (`connect_db`), with `?` → `%s` placeholder rewriting. The verified dual-mode files (each grep-confirmed to contain a real `if database_url:` runtime branch, not just a docstring or config-validation hit):

- `src/api/cloud_routes/platform.py` (branch at ~L43-70)
- `src/api/cloud_routes/kpis_compute.py` (branch at ~L66-77)
- `src/api/cloud_routes/broker_exceptions.py`
- `src/api/cloud_routes/preflight.py`
- `src/api/cloud_routes/commands.py`
- `src/api/cloud_routes/walkforward.py` (`_read_rows` at L49-64 with `if database_url:` at L51)

Additionally `src/api/routes/logs.py:194-198` carries the same pattern (one of the routes/ files that has cloud awareness baked in). NOT in the dual-mode set: `src/evaluation/system_validator.py` has DATABASE_URL hits at L560 + L579 but those are Render-config-validation lookups (pre-deploy preflight), not per-call routing branches — correctly NOT in scope for the abstraction-layer migration.

The surface report claimed "128 connect_db call sites" — the actual count on 2026-05-05 is **322 `connect_db(` call sites + 14 raw `sqlite3.connect` direct uses = 336 total**. That count is the noise floor. The signal is these ~7 files where the architectural divergence actually lives. Each branch is ~10 LOC. Total: ~70 LOC of conditional branching that could be replaced by a single engine-aware abstraction at `src/utils/db.py`. **This is the single largest source of code-level pain in the dual-store today, separate from the sync layer itself**, and it is fixable independently. See Option D in §4 and harden-task H1 in §6.

### 2.5 Bidirectional command queue — the architectural lever that blocks cheap migration

The `pull_commands` function (`render_sync.py:839-960`) is structurally critical:

1. PG SELECT `pending_commands WHERE status = 'pending' AND expires_at > NOW()`.
2. Local INSERT OR IGNORE with `status='claimed'` (idempotent at local side via PK constraint).
3. PG UPDATE `status = 'claimed'` for the successfully-inserted command_ids only (#259 fix at lines 907-918 — previously updated ALL command_ids, dropping commands when local insert failed).
4. Pull `config_overrides` with full table replace.

Results flow back via a normal `incremental` sync of the `command_results` table (`registry.py:1543-1561`).

A RACE WINDOW exists: if local INSERT succeeds, PG UPDATE fails, AND watch loop crashes BEFORE running command (between line 899 and execution callback at line 1267). Restart sequence: PG re-pulls (still `pending`), local INSERT OR IGNORE no-ops (already there), PG UPDATE marks claimed AGAIN. The local executor would NOT re-run because status is already `claimed`. **Net result: command silently lost.** Severity: medium for diagnostic commands; high for trading commands (`close_position` would be unrecoverable). This is harden-task H3 in §6.

The architectural implication for consolidation: **Litestream cannot replicate the cloud-to-local arrow**. Vanilla Litestream is one-way SQLite → S3 → restored SQLite. `pull_commands` requires bidirectional writes. Option B with vanilla Litestream BREAKS the queue. libsql/Turso (server-side replicated SQLite with the libsql protocol) preserves bidirectional model — but introduces a third-party dependency on a 2022-founded vendor on the trading hot path.

### 2.6 Single-host invariant — documented, not enforced

The sync layer assumes a single host writes to PG. `_sync_host_name()` returns `socket.gethostname()` at `render_sync.py:87-89`. `mark_sync_in_flight` (`:340-369`) checks for an existing `in_progress` row and raises `SyncInFlightError` IF the row is for the same host. Two hosts would each get their own row and BOTH proceed to write. Postgres-side conflict resolution (`ON CONFLICT (pk) DO UPDATE`) makes incremental tables mostly idempotent under concurrent writers, but `latest_only` tables under savepoint-protected DELETE+INSERT have a window where each host's INSERT briefly overwrites the other's.

`pending_commands` (`registry.py:1581`) has NO `target_host` field. With two hosts pulling simultaneously, host A could legitimately claim a `restart_watch` command intended for host B — race-free at PG level (atomic UPDATE) but routed to the wrong host. This is harden-task H6 in §6.

Documentation of this invariant lives at `render_sync.py:414-422` (the docstring of `release_stale_in_flight_for_host`):

> PID-lock invariant: `watch.lock` is acquired at `watch.py:1293` BEFORE `start_render_sync()` is called at `watch.py:1362-1363`. Therefore when `RenderSyncThread.run()` starts, no other watch-loop process exists ON THIS HOST.

The invariant is per-host. It is NOT enforced as a CI assertion or a runtime preflight. Operator memory (CLAUDE.md): **"Wave 4 H1 introduced host-name-keyed in-flight lock — multi-host scenarios (backup machine + primary) would double-write"**. Any architecture recommendation must preserve or explicitly authorize multi-host. This spec preserves single-host (per brief constraint).

### 2.7 Test fixture story — entirely SQLite-bound

`tests/conftest.py::init_test_db` at lines 32-50:

```python
def init_test_db(db_path: str, tables: list[str] | None = None) -> None:
    conn = sqlite3.connect(db_path)
    try:
        if tables is None:
            for tdef in TABLES.values():
                conn.executescript(generate_create_sql(tdef))
        else:
            for name in tables:
                if name in TABLES:
                    conn.executescript(generate_create_sql(TABLES[name]))
        conn.commit()
    finally:
        conn.close()
```

Three facts: (1) ZERO real-Postgres tests in CI; (2) `tests/integration/` contains exactly ONE test module — `test_track_1_5_full_pipeline.py` — plus an empty `__init__.py`; (3) `tests/test_render_sync.py` mocks ALL psycopg2 interactions with `unittest.mock.MagicMock`. Drift between SQLite and Postgres surfaces only in production. `requirements.txt`, `requirements-cloud.txt`, and `requirements-training.txt` show no `testcontainers`, no `pytest-postgresql`, no embedded-postgres-binaries.

Migration cost for any all-Postgres path is therefore substantive: 60-80 test files would touch the test-DB layer, plus a new fixture pattern (the natural fit is `pytest-postgresql` with `postgresql_proc` and `postgresql_my` fixtures: ~200-500ms session-scoped DB creation, function-scoped transaction rollback, compatible with the existing `init_test_db` shape — just swap the connect URL). Conservatively: 1-3 person-weeks for thorough conversion + CI tuning. Hermetic fixture brief constraint is preserved.

---

## 3. Pain-point inventory

| # | Pain | Severity | Frequency | References |
|---|---|---|---|---|
| 1 | MS Access external-tool lock during DB inspection (118 lock errors / single session) | Major | Episodic (operator-driven) | CLAUDE.md "Database Access Rules" 2026-04-19 incident |
| 2 | OneDrive WAL corruption risk on `C:/arcis/data` | Major | Latent | `docs/research/Disaster_Recovery_for_Solo_Algorithmic_Trading.md`, MASTER.md |
| 3 | Wave 4 H1 — sync_state in-flight lock starves all syncs after watch crash | Critical | One-time (closed) | PR #930, `render_sync.py:340-369`, `release_stale_in_flight_for_host` `:414-440` |
| 4 | Wave 4 H2 — `scan_metrics.id` UNIQUE collision when SQLite ROWID + writer counter diverge after restart | Critical | One-time (closed) | PR #931, registry-driven SERIAL/ROWID impedance |
| 5 | Wave 4 H3 — `live_prices` `latest_only` mode dropped 14/15 tickers per cycle | Critical | One-time (closed; mode migrated to `incremental`) | PR #932, `registry.py:2479` |
| 6 | #910 — `live_prices.sync_time_column=None` → `MAX(None)` crash every cycle | Critical | One-time (closed) | CHANGELOG #910, `sync_config.py` |
| 7 | #919/#920 — `reconciled_stale` rows polluted dashboard win-rate | Major | One-time (closed; rolled out across 12 src/ files in 3 rounds) | CHANGELOG #919/#920, `outcome_stats_filter_sql()` |
| 8 | #199 — single PG connection death cascading sync skips | Major | One-time (closed) | CHANGELOG #199, `_PG_CONNECT_RETRIES` at `render_sync.py:51-52` |
| 9 | #228 — sync thread silent death | Major | One-time (closed) | CHANGELOG #228, `health_status()` exposure |
| 10 | #229/#242/#243 — three latest_only race/clash/null-PK bugs | Major | One-time (closed) | CHANGELOG, savepoint pattern at `render_sync.py:744-766`, strip-id at `:608-614` |
| 11 | Render free-tier cold starts cause connect timeouts (per-table reconnect retry workaround) | Major | Recurring (latent on Standard tier) | CLAUDE.md `render_free_tier_pain`, `_PG_CONNECT_RETRIES = 3` |
| 12 | Cloud requirements drift recurring (requests/numpy/jsonschema retroactive adds) | Minor | Recurring | `requirements-cloud.txt` history |
| 13 | Per-request fresh PG connection (no pool) — TCP+TLS+auth on every dashboard call | Major | Recurring (every request) | `cloud_app.py:179-202` |
| 14 | Function-level `if DATABASE_URL` branches in 6+ cloud_routes files (~70 LOC of duplication) | Major | Recurring (every new route) | `platform.py:43-70`, `kpis_compute.py:66-77`, `walkforward.py:49-64`, `routes/logs.py:194-198`, etc. |
| 15 | Tests are 100% SQLite-fixture-bound — drift between engines surfaces only in prod | Critical | Latent (incident substrate) | `conftest.py:32-50`, `test_render_sync.py:190+` |
| 16 | `pending_commands` race window — local INSERT succeeds + PG UPDATE fails + crash → command silently lost | Major | Latent (no incident yet) | `render_sync.py:884-918` |
| 17 | Single-host invariant is documented, not CI-enforced — backup-machine scenario silently double-writes | Major | Latent (no incident yet; backup-machine plans exist) | `render_sync.py:87-89, 414-422`, CLAUDE.md operator memory |
| 18 | 4 SQLite-only Category-B tables are dashboard-blind (`model_evaluations`, `preference_pairs`, `bracket_health`, `daily_ib_health`) | Minor | Continuous | `registry.py:382, 521, 612, 1718` |
| 19 | Schema registry drift between SQLite and Postgres caught only at sync startup (`render_sync.py:1083-1085`) | Minor | Latent | `src/schema/sqlite.py` + `src/schema/postgres.py` are separate generators |
| 20 | Authentication fragility — `cloud_app` uses `API_SECRET`, local API uses `ARCIS_LOCAL_API_TOKEN`; PR #711→#729 401 incident | Major | One-time (closed) | CLAUDE.md "Worktree env drift", PR #711 → #729 |
| 21 | Cloud-blocked endpoints concept (`CLOUD_ACTION_MSG` at `cloud_app.py:115-118`) — frontend must duplicate visibility logic | Minor | Continuous | `cloud_app.py`, frontend route guards |

**Pattern observation.** Critical pain points 3-10 are ALL closed. Wave 4 was effective. The remaining open items are MAJOR-severity but mostly latent (16, 17) or continuous-low-grade (13, 14). This is a well-instrumented, well-fortified system — not a system in crisis. **The pain-point distribution argues against drastic architecture change and toward targeted hardening of the latent risks plus the dual-mode-branch duplication.**

---

## 4. Architecture options

Four options analyzed below. All four preserve the brief's hard constraints (schema registry as SOT, methodology workflows local, PIT discipline, hermetic tests, no cloud dashboard abandonment, single-host).

### 4.1 Option A — All-Postgres consolidation

**Sketch.** Drop SQLite as the operator-side primary. Run Postgres locally on the operator's Windows machine (Docker Desktop or native install). The watch loop, all `connect_db()` callers, all collectors, the trading executor, and the local FastAPI all connect to a `postgresql://localhost:5432/halcyon` string (or to the Render Postgres directly via Tailscale tunnel — see variant A2 below). Render-side Postgres is either a logical-replication follower of the local PG, or the local PG is eliminated and the local processes connect over a private network to Render PG directly.

**Variants:**
- **A1: Local PG primary + Render PG follower** — local PG is the source of truth; Render PG is configured as a read replica via streaming replication or `pglogical`. Eliminates the sync thread entirely. New ops burden: managing the replica connection.
- **A2: Render PG only** — local processes write directly to Render PG over Tailscale or SSH-tunnel. No local DB. Dashboard reads same DB. Single source of truth. Trading state now depends on cloud connectivity (FAILURE MODE EXPANSION).
- **A3: Local PG primary + sync to Render** — same sync layer, but SQLite-side becomes PG. Eliminates impedance mismatches but keeps the sync thread. Loses most of the consolidation benefit.

The interesting variants are A1 and A2; A3 is dominated by Option C.

**Tradeoff matrix (A1 — Local PG + replica)**:

| Dimension | Rating | Notes |
|---|---|---|
| Read latency (local) | Worse | PG TCP localhost ~5-10ms vs SQLite shared-cache <1ms; minor real impact |
| Write latency (local) | Comparable | PG with `synchronous_commit=off` matches SQLite WAL within order of magnitude |
| Read latency (cloud) | Better | Eliminates `_PG_CONNECT_RETRIES` and per-cycle reconnect; consistent ~10ms intra-Render |
| Reliability — recovery from outages | Worse | Local PG outage blocks trading reconciler; SQLite single-file is more recoverable |
| Reliability — failure modes | New class | Streaming replication lag, replica-divergence, WAL archive failures |
| Operator complexity — deployment | Much worse | Operator must install + run + back up Postgres on Windows (Docker Desktop or native pg) |
| Operator complexity — monitoring | Worse | New dashboards: replication lag, PG memory, WAL bloat, vacuum schedule |
| Operator complexity — backup | Worse | `pg_dump` cron + WAL archiving vs SQLite single-file copy |
| Cost | KNOWN: $0 marginal IF Render PG plan stays same. ASSUMED: Render PG tier ($7-$25/mo per public pricing — repo cannot verify; `render.yaml:32` `sync: false`) | No new cost on local side IF using Postgres community edition |
| Migration effort — LOC touched | Substantial | ~600 LOC removable from `render_sync.py`; ~70 LOC removable from cloud_routes (no longer dual-mode); ~30+ tests rewritten; new `pytest-postgresql` fixture; `connect_db` becomes engine-aware OR all callers migrate |
| Migration effort — downtime | 2-6 hours | One-shot migrate via `pgloader` or registry-driven re-DDL + COPY; possible to run dual-write briefly for cutover |
| Migration effort — schema-registry changes | Minimal | Drop `sqlite.py` generator OR keep both with `postgres.py` as primary |
| Methodology fit — schema-registry SOT | PRESERVED | Registry remains canonical, `sqlite.py` becomes vestigial |
| Methodology fit — PIT discipline | PRESERVED | `src/universe/pit.py` is filesystem-based, DB-engine-agnostic |
| Methodology fit — hermetic tests | DEGRADED→FEASIBLE | `pytest-postgresql` adds 200-500ms session startup, function-scoped txn rollback. Still hermetic, just slower |
| Methodology fit — local methodology execution | PRESERVED | Watch loop / corpus / walkforward / Ollama all run locally on local PG |
| Trading-state safety | DEGRADED | Reconciler now depends on local PG availability; PG outage = trading freeze |

**Migration sketch (high-level — see §6 for why this is NOT recommended).**

1. Provision local Postgres (Docker Desktop or native Windows install). Decide on persistence directory (NOT under OneDrive).
2. Add Postgres-aware test fixtures (`pytest-postgresql` or `testcontainers-postgres`) to `tests/conftest.py`. Establish dual-mode test fixture during transition (SQLite tests still pass, new PG tests run in parallel).
3. Build engine-aware `src/utils/db.py::connect_db()` — returns SQLite or psycopg connection based on connection string. Establish `query()` helper that absorbs `?` vs `%s` placeholder differences.
4. Migrate `connect_db()` call sites in batches by module ownership (e.g., `src/sync/` → `src/shadow_trading/` → `src/data_collection/` → `src/api/`).
5. Run dual-write transition (writes go to BOTH SQLite and PG; reads still from SQLite) for one operator cycle. Compare row counts.
6. Cutover: writes go only to PG. SQLite read paths replaced. Sync thread retired. `render_sync.py`, `sync_config.py`, `src/schema/sqlite.py` deleted (or kept as vestigial).
7. Clean up dual-mode branches in cloud_routes; replace with engine-aware abstraction.

**Risks:**
- Trading-state safety regression (largest single risk).
- Test migration is a long tail — every new test pattern adds latent bugs.
- Local PG ops complexity adds to operator's daily mental load.
- Streaming replication failures introduce a new incident class.
- Categorical-state tables (Category A: `sync_state`, `system_metrics`, `data_freshness`, `config_overrides`, `operator_view_state`) STILL want to stay local. Either they move to a small private SQLite alongside PG (then it's not really "all-Postgres" — it's "mostly-Postgres + 5-table local SQLite"), OR they move to PG and lose the meaning that justified their separation (e.g., `system_metrics` in cloud PG is meaningless because the cloud has different system metrics).

**Cost (KNOWN vs ASSUMED).** KNOWN: $0 marginal local cost (PG community edition). KNOWN: existing Render PG tier from `render.yaml:32` is `sync: false` — the repo cannot tell us the price. ASSUMED based on public Render pricing: Free 256MB ($0), Starter 1GB ($7/mo), Standard 4GB ($20/mo). 398MB local DB does not fit Free; likely already on Starter or Standard. Render's documented tier limits suggest Standard PG at $20/mo if used as authoritative storage with logical replication. If the operator currently pays $7/mo Starter, Option A might require a tier upgrade to support a follower replica. Cost delta: $0-$13/mo. **Spec MUST flag this as ASSUMED — operator should verify the actual bill before committing.**

### 4.2 Option B — All-SQLite + cloud replication

Drop Postgres. Operator's machine remains the SQLite primary. Cloud dashboard reads from a replica.

**Variants:**
- **B1: Litestream → S3 → restored SQLite on Render** — Litestream (`docs/research/Disaster_Recovery_for_Solo_Algorithmic_Trading.md:158`) continuously streams WAL pages to S3. Render reads from a Litestream-restored SQLite. **One-way only — INCOMPATIBLE with bidirectional `pull_commands`.**
- **B2: libsql/Turso server-side replicated SQLite** — Turso provides server-side replicated SQLite with the libsql client protocol. Bidirectional writes. Free tier: 9GB / 1B reads/month / 25M writes/month — well within 398MB scale. **Feasible for this codebase but introduces vendor dependency on a 2022-founded vendor on the trading hot path.**
- **B3: Cloudflare Tunnel / Tailscale + local FastAPI serving the dashboard** — eliminate cloud DB entirely. Operator's home machine serves `halcyonlab.app` directly. Cost: ~$0/mo. Tradeoff: dashboard goes down when home machine is down. Operator already has a documented disaster-recovery concern (DR doc), and trading state IS already single-machine-dependent. Worth considering.
- **B4: `sqlite3_rsync`** (released 2025 by SQLite team) — primary → backup-PC SSH-based live sync. NOT a cloud-dashboard solution. Useful as DR layer alongside dual-store. Out of scope for this option.

**Tradeoff matrix (B2 — libsql/Turso):**

| Dimension | Rating | Notes |
|---|---|---|
| Read latency (local) | UNCHANGED | Local SQLite remains primary |
| Write latency (local) | UNCHANGED | Local SQLite remains primary |
| Read latency (cloud) | Comparable to status quo | libsql client to Turso edge ~20-50ms |
| Reliability — failure modes | New class | libsql protocol bugs, Turso outages, vendor lock-in |
| Reliability — vendor risk | Concern | Turso founded 2022, on trading hot path |
| Operator complexity — deployment | Worse | New auth model (libsql tokens), new monitoring |
| Operator complexity — monitoring | Worse | Replica lag dashboards, libsql protocol errors |
| Operator complexity — backup | UNCHANGED | Local SQLite backup unchanged |
| Cost | UNKNOWN: depends on Turso usage tier; free tier likely sufficient at current scale; vendor pricing-change risk |
| Migration effort — LOC touched | Moderate | ~300-500 LOC across cloud_routes (replace psycopg2 with libsql client); cloud_app.py rewrite of `get_pg`/`_query` |
| Migration effort — downtime | 1-3 hours | Render dashboard cutover from PG to libsql |
| Migration effort — schema-registry changes | Moderate | Drop `postgres.py` generator; ensure `sqlite.py` covers all engines |
| Methodology fit — schema-registry SOT | PRESERVED | Registry remains canonical |
| Methodology fit — PIT discipline | PRESERVED | `pit.py` is filesystem-based |
| Methodology fit — hermetic tests | PRESERVED | Tests stay SQLite-fixture-bound (already are) |
| Methodology fit — local methodology execution | PRESERVED | Watch loop / corpus / walkforward / Ollama unchanged |
| Trading-state safety | PRESERVED | Local SQLite still primary; cloud is replica |

**Migration sketch (high-level):**

1. Set up Turso/libsql account; provision database; obtain auth token.
2. Configure Litestream or Turso embedded replicas to stream from local SQLite to Turso server. Validate replication lag stays below 60s.
3. Replace `psycopg2` with libsql client in `cloud_app.py:179-219` and the 6+ cloud_route files.
4. Cutover Render service from PG-backed to libsql-backed. Retire Render PG.
5. Retire sync push-replication for the 61 tables that were duplicated (Litestream/Turso replaces it). KEEP `pull_commands` IF Turso's bidirectional model handles command writes from cloud back to local — TBD by spike.

**Risks:**
- Vendor risk (Turso). Acquisition / pricing-change scenarios.
- libsql/Turso compatibility with composite PKs in `correlation_matrices`, `factor_loadings`, `minute_bars` — UNVERIFIED. Spike required.
- `requirements-cloud.txt` accumulates a libsql dependency that may not have psycopg2-grade testing maturity.
- Operator's stated dependency-conservatism preference (battle-tested deps: psycopg2, pandas, scipy) is violated.

**Cost (KNOWN vs ASSUMED):** ASSUMED Turso free tier covers 398MB / single-operator at $0/mo. ASSUMED Render PG retirement saves $7-$25/mo. Net: -$7 to -$25/mo. Worth flagging that vendor pricing is volatile; locking-in is not free.

**B3 — Cloudflare Tunnel variant** is qualitatively different. Render the entire cloud-tier obsolete. Operator's home machine serves `halcyonlab.app` via Cloudflare-tunnel or Tailscale Funnel. Pros: $0/mo, zero sync layer, simplest possible architecture. Cons: dashboard availability = home machine availability. Operator has documented 5-min RTO from DR research. Trading state is already single-machine-dependent (Ollama + GPU + walkforward). So dashboard availability cannot meaningfully exceed trading availability anyway. **B3 is the sleeper option** — discussed in §5.5 and noted as residual uncertainty.

### 4.3 Option C — Status Quo + Targeted Hardening

Keep dual-store. Invest in hardening the documented latent risks and the high-frequency papercuts.

**Sketch.** Architecture is unchanged. Targeted improvements:

1. **DB-engine abstraction at `src/utils/db.py`** (Option-D fragment baked into Option C) — replace 6+ `if DATABASE_URL` branches in cloud_routes with a single engine-aware `query()` / `query_one()` / `execute()` API. Eliminates ~70 LOC of branching duplication and centralizes the placeholder rewriting (`?` ↔ `%s`) in one place.
2. **Add Postgres connection pool to `cloud_app.py`** (`psycopg2.pool.ThreadedConnectionPool` or migrate to `psycopg3`) — eliminates per-request handshake.
3. **Add testcontainers-postgres CI job** — small (~20 representative integration tests) running against real PG to catch SQLite/PG drift before it reaches prod. Catches the substrate of #185, #243, #797, H2, H3.
4. **Add idempotency token + executor-receipt protocol to `pending_commands`** — closes the race window at `render_sync.py:884-918`. Schema change: `pending_commands.consumed_at TIMESTAMP` + executor must write `consumed_at` after running command before sync marks PG `claimed`.
5. **Add `target_host` field to `pending_commands`** — preparation for multi-host without enabling it. Default `NULL` = any host.
6. **Promote 4 Category-B tables to PG sync** — `model_evaluations`, `preference_pairs`, `bracket_health`, `daily_ib_health`. Eliminates 4 dashboard blind spots.
7. **Document MS Access lock incident in `docs/operator-guide.md`** — point to `sqlite3 -readonly` workflow and Python `mode=ro` URI as canonical inspection methods.

**Tradeoff matrix:**

| Dimension | Rating | Notes |
|---|---|---|
| Read/write latency | UNCHANGED on local; IMPROVED on cloud (pool eliminates handshake) | Pool drops cloud read p50 from ~50-200ms to <5ms |
| Reliability — failure modes | IMPROVED on `pending_commands` race; UNCHANGED elsewhere | Idempotency token is a real fix |
| Operator complexity | IMPROVED (operator-guide docs + dual-mode-branch removal) | Removes one papercut from new-route work |
| Cost | UNCHANGED | $0 marginal |
| Migration effort | LOW per task; aggregated MEDIUM | 7 harden tasks, mostly independent, each 1-3 days |
| Methodology fit | PRESERVED across all dimensions | No structural change |
| Trading-state safety | PRESERVED | Reconciler stays sync-independent |
| Risk of regression | LOW per task | Each harden task is small + scoped |

**Risks:**
- Hardening fatigue — operator has been doing rolling fixes (#910, #919/#920, H1-H7) for weeks. Status-quo path means more of the same. Counter: harden tasks 1-7 are bounded and finishable; this is not a permanent treadmill.
- Latent risks remain latent — any path that doesn't migrate accepts the existing failure surface.
- Eventually the cumulative papercut count may justify re-opening Option A. Not now.

**Cost.** $0 marginal. ~3-5 person-weeks total for the 7 harden tasks if done sequentially; much less if done across parallel sprints.

### 4.4 Option D — DB-engine abstraction first, defer engine choice

**Sketch.** Treat the abstraction-layer absence as the FIRST problem to solve, before deciding on consolidation. Build `src/utils/db.py` into a real engine-router:

```python
class DBEngine(Protocol):
    def query(self, sql: str, params: tuple = ()) -> list[dict]: ...
    def query_one(self, sql: str, params: tuple = ()) -> dict | None: ...
    def execute(self, sql: str, params: tuple = ()) -> int: ...
    def transaction(self) -> ContextManager: ...

def get_engine() -> DBEngine:
    if os.environ.get("DATABASE_URL", "").startswith("postgres"):
        return PostgresEngine(...)
    return SQLiteEngine(...)
```

All callers route through `get_engine()`. Placeholder rewriting handled inside the engine implementation. Both engines auto-derive DDL from registry. Tests parametrize over both engines (or default to SQLite for speed, opt-in to PG for impedance-coverage tests). After the abstraction lands, the dual-mode branches in 6+ cloud_routes files collapse to single calls. The downstream consolidation decision (Option A vs Option B vs status quo) becomes EASIER because all engine assumptions are now centralized.

**Critical observation.** Option D as a STANDALONE action is essentially a SUBSET of Option C (the harden tasks include this layer). The interesting framing of Option D is: "Do D, see how the codebase feels, THEN decide between A and B/C in 3-6 months."

**Tradeoff matrix:** Same as Option C, except adds one explicit goal ("keep both engines as legitimate options"). Slightly more LOC than Option C alone (the abstraction must be richer to support a future Option-A migration). Same risks.

**Why it's listed separately.** The brief explicitly invites Option D ("emergent — Architect's call to include if warranted"). The recommendation in §5 absorbs Option D into Option C and treats them as one path. If a reader prefers "Option C minus the abstraction layer," that's acceptable but loses the highest-leverage harden task. **Sub-option D-only**: a reader who wants "land H1 alone, defer H2-H7, re-evaluate in 6 months" creates real option value (in the financial sense) — the abstraction lets the codebase observe its own behavior under engine-choice ambiguity before committing. This sub-option is only viable if §0 prerequisite #3 (dashboard usage) is HIGH (so H2 PG-pool isn't urgent); under low usage, Option E should be evaluated first.

### 4.5 Option E — Cloudflare Tunnel (eliminate cloud DB tier)

**Sketch.** Eliminate the Render-hosted FastAPI + Postgres tier entirely. The operator's existing local FastAPI (already running at `127.0.0.1` per `src/api/app.py`) becomes the dashboard backend, exposed to the public internet via Cloudflare Tunnel (or Tailscale Funnel). The React frontend at `halcyonlab.app` continues to be served as static files (already deployed; cheap), but its API calls now route through the tunnel to the operator's home machine instead of to Render. The `RenderSyncThread`, the `pending_commands` queue, the entire 1359-LOC sync layer, and Render Postgres all retire. Local SQLite remains the single source of truth.

**Architectural consequences.**
- Sync layer disappears. ~600 LOC of `render_sync.py` mode logic + ~180 LOC of `sync_config.py` + the entire `mode` field on `TableDef` become deletable.
- `pending_commands` queue disappears. Cloud-initiated trading actions become direct HTTP calls to local FastAPI — synchronous, immediate, no race window. This eliminates the asymmetric-coupling concern in §1 because cloud-initiated trading commands no longer flow through PG.
- Cloud routes' dual-mode `if DATABASE_URL` branches across 6+ files become moot — there IS no cloud database. The H1 abstraction layer can simplify to single-engine.
- 9 Category-A tables (`sync_state`, `system_metrics`, `data_freshness`, `config_overrides`, `operator_view_state`, etc.) lose their reason-to-stay-local; can be folded back into the main DB or kept separate at operator's choice.
- Schema generators reduce to one (`src/schema/sqlite.py`); `src/schema/postgres.py` is deletable.
- 4 Category-B tables (`model_evaluations`, `preference_pairs`, `bracket_health`, `daily_ib_health`) become dashboard-visible "for free" — same DB, no sync needed.

**Tradeoff matrix:**

| Dimension | Rating | Notes |
|---|---|---|
| Read latency (local) | UNCHANGED | Local SQLite remains primary |
| Write latency (local) | UNCHANGED | Local SQLite remains primary |
| Read latency (cloud) | Comparable to status quo | Cloudflare Tunnel adds ~20-50ms over Render-direct read; offset by elimination of Render cold-start retries |
| Reliability — failure modes | Different class | Dashboard availability tied to operator's home machine + ISP + Cloudflare. Currently dashboard goes down when sync layer breaks; under E, dashboard goes down when home machine reboots or loses internet. |
| Reliability — vendor risk | Cloudflare-only (mature, free tier) | vs. Render (current managed PG vendor) — net wash on vendor risk |
| Operator complexity — deployment | IMPROVED | Single tier (local FastAPI + tunnel) vs three tiers (local watch + sync thread + Render service); no Render redeploys, no PG migrations on cloud |
| Operator complexity — monitoring | IMPROVED | One observability surface; tunnel uptime is an off-the-shelf metric |
| Operator complexity — backup | UNCHANGED | Local SQLite backup unchanged; no cloud DB to back up |
| Cost | DOMINATES | $0/mo (Cloudflare Tunnel free tier) vs current Render PG bill ($7-$50/mo per public pricing — ASSUMED, see §0 prerequisite #1). Net savings: $7-$50/mo, possibly more if Render API service tier also retires |
| Migration effort — LOC touched | Substantial | ~600 LOC removable from `render_sync.py`; ~70 LOC removable from cloud_routes; ~338-line `cloud_app.py` retires entirely; frontend API base URL changes once |
| Migration effort — downtime | 1-2 hours | Tunnel setup + DNS cutover + frontend rebuild + smoke test |
| Migration effort — schema-registry changes | Modest | Drop `postgres.py` generator; `sync_to_postgres` field on TableDef becomes vestigial; `sync_mode` becomes vestigial; no DDL changes to existing data |
| Methodology fit — schema-registry SOT | PRESERVED | Registry remains canonical |
| Methodology fit — PIT discipline | PRESERVED | `pit.py` is filesystem-based |
| Methodology fit — hermetic tests | PRESERVED | Tests stay SQLite-fixture-bound (already are) |
| Methodology fit — local methodology execution | PRESERVED | Watch loop / corpus / walkforward / Ollama unchanged |
| Trading-state safety | IMPROVED | Cloud-initiated trading actions become synchronous local calls; no race window; no asymmetric coupling. Read-side unchanged (already independent). |
| Dashboard availability | DEGRADED (conditional) | Tied to operator home machine availability — but operator already has 5-min-RTO DR posture per `docs/research/Disaster_Recovery_for_Solo_Algorithmic_Trading.md`; if operator can tolerate trading downtime during reboots, dashboard downtime is the same cost |

**Migration sketch (high-level — not sprint-grade in this spec):**

1. Provision Cloudflare Tunnel (free tier; operator already has DNS at `halcyonlab.app`). Map subdomain to local FastAPI port.
2. Decide auth model — local FastAPI currently uses `ARCIS_LOCAL_API_TOKEN`; cloud uses `API_SECRET`. Unify under one token. (See PR #729 incident — auth fragility was a documented pain point.)
3. Update React frontend's API base URL config from `halcyon-api.onrender.com` to `api.halcyonlab.app` (tunnel endpoint). Re-deploy static frontend.
4. Wire local FastAPI to expose all endpoints currently in `cloud_app.py` (most already exist locally; some may need duplication of `cloud_routes/*` logic into `routes/*`).
5. Smoke test: dashboard loads, KPI strip renders, trade history paginates, command submission round-trips end-to-end.
6. Decommission: stop `RenderSyncThread`, retire Render API service, optionally retire Render Postgres (or keep as DR backup).

**Risks:**
- **Home machine availability becomes dashboard availability.** During reboots, ISP outages, or hardware faults, dashboard is unreachable. Mitigation: operator's existing DR posture handles this for trading; dashboard is a strict subset.
- **Mobile-network-quality-during-tunnel.** Cloudflare Tunnel adds latency; on slow mobile networks, dashboard may feel sluggish. Mitigation: existing Render setup has comparable latency due to free-tier cold starts.
- **Auth model migration.** Local FastAPI's token model is simpler but the cloud routes' auth is split across `verify_auth` (cloud) and `verify_local_auth` (local). Unifying is a real refactor.
- **Tunnel uptime is single-point-of-failure** — Cloudflare's reliability is high but it's a single vendor. Mitigation: Cloudflare's track record is mature; tunnel is widely deployed.

**When E wins.**
- §0 prerequisite #3 (dashboard usage) is **< 10 hits/day**: cost-dominated win. Saving $84-$600/year for a dashboard hit twice a day is decisive.
- Operator is willing to accept dashboard-availability ≤ trading-availability (which it structurally already is).
- Cumulative incident-rate trajectory in sync layer doesn't converge fast enough: if 2-3 more sync impedance bugs land in next 30 days, eliminating the sync layer altogether starts to look better than hardening it.

**When E loses.**
- Dashboard usage is high (≥ 10 hits/day, especially from mobile or remote devices where reliability matters most).
- Operator wants the dashboard to be available even when home machine is offline (e.g., to inspect trade outcomes during a reboot).
- Cloudflare-vendor concentration is unacceptable (one tunnel provider on the dashboard hot path).

**Why E was elevated from a "residual uncertainty" to a full option in v3.** The v2 spec dismissed B3 (the original name for this concept) on insufficient operator usage data. The DA review correctly identified this as premature: dismissing the option without first asking the operator the question that would resolve the dismissal is incoherent. v3 re-elevates E to a full option AND adds the question to §0 as a prerequisite, ensuring it's answered before committing to harden work that E would obviate.

### 4.6 Options NOT analyzed (rejected at framing stage)

- **Option F — Distributed multi-master DB (Cassandra, CockroachDB, etc.)** — operator scale is single-operator / single-machine / 398MB. Justified only at scales 100-1000× larger. Rejected at framing.
- **Option G — Embedded Postgres (e.g., `embedded-postgres-binaries`) + sync** — dominates Option A by removing Docker Desktop dependency, but introduces a Java runtime requirement and is not a public-facing primary; embedded-PG is for tests, not for production.
- **Option H — Drop the cloud dashboard entirely, run only locally (no remote access)** — explicitly forbidden by the brief. Operator memory: dashboard is heavily used. (Note: this differs from Option E, which keeps the cloud-facing dashboard but reroutes its backend.)

---

## 5. Recommendation

### 5.1 Conviction: HIGH (CONDITIONAL) for **Option C — Status Quo + Targeted Hardening** (with the Option-D abstraction-layer harden task included)

**Conditional on §0 prerequisites:** HIGH stands IF (a) Render PG bill ≤ $25/mo, (b) no backup-machine plan in next 6 months, (c) dashboard usage ≥ 10 hits/day. If any of these flip after operator confirmation, conviction downgrades to MEDIUM and the recommendation re-evaluates per §5.4. v2 of this spec graded conviction as plain HIGH; the Devil's Advocate review correctly identified that HIGH with five unresolved uncertainties is "MEDIUM with hopeful priors" — v3 makes the conditionality explicit so the operator does not commit to 5-7 person-weeks of harden work without first answering the open questions.

### 5.2 Why this beats the others

**Against Option A (all-Postgres):**
- *Trading-state safety.* The reconciler at `src/shadow_trading/reconcile_state.py:32-44` reads MAX(updated_at) on local SQLite. Wave 4 H1/H2/H3 all degraded the dashboard — never the trading. All-Postgres would couple trading to PG availability. This is a SAFETY REGRESSION I am not willing to underweight.
- *Migration cost is high.* ~600 LOC removable + ~70 LOC of branches removable + 30+ tests rewritten + new pytest-postgresql fixture + 1-3 person-weeks of focused work. The marginal benefit is the elimination of impedance-mismatch bugs (substrate of #185, #243, #797, H2, H3) — but Wave 4 already closed those AND the testcontainers-postgres CI job (harden task §6.3) catches future drift at far lower cost.
- *The Category A tables don't actually want to live in PG.* `sync_state`, `system_metrics`, `config_overrides`-cache, `data_freshness`, `operator_view_state` — five tables that legitimately stay local. "All-Postgres" really means "mostly-Postgres + 5-table local SQLite." The simplification is partial, not total.
- *Operator burden expands.* Local PG install + backup + monitoring + replication-lag dashboards. Real day-to-day cognitive cost.

**Against Option B (all-SQLite + replication):**
- *Litestream blocks bidirectional command queue.* Vanilla Litestream is one-way SQLite → S3. `pull_commands` (`render_sync.py:839-960`) requires the PG → local arrow. Any Litestream variant would need a separate command-submit layer (e.g., dashboard → webhook → operator's machine) — significant new complexity.
- *libsql/Turso adds vendor lock-in.* Turso founded 2022, on the trading hot path. Operator's pattern of preferring battle-tested deps (psycopg2, pandas, scipy) is a structural argument against young-vendor risk.

**Against Option E (Cloudflare Tunnel — full option in §4.5):**
- *Conditionally beats C only if dashboard usage is low.* Per §0 prerequisite #3: if usage < 10 hits/day, E is the cost-dominated winner ($0/mo vs $7-$50/mo Render PG plus zero sync layer). If usage ≥ 10 hits/day, the dashboard-availability tradeoff (tied to home machine + ISP + Cloudflare) outweighs the cost savings.
- *E is not "intrinsically worse than C" — it is "worse than C on the specific dashboard-usage path operator currently uses."* Once the prerequisite is answered, E may dominate. v2 of this spec dismissed E as residual uncertainty; v3 corrects that — E is a full option whose viability depends on a question only operator can answer.

**For Option C:**
- *Pain-point distribution favors hardening.* Of 21 pain points in §3, 8 are CLOSED (the Critical-severity ones), 4 are continuous-low-grade (13, 14, 18, 21), and 4 are latent-but-real (16, 17, 2, 11). The continuous and latent items are exactly what hardening addresses.
- *The single largest LOC-cost papercut is the dual-mode branches in cloud_routes* (~70 LOC across 6+ files). The Option-D abstraction layer fixes this independently of consolidation.
- *Schema-registry SOT, PIT discipline, hermetic tests, trading safety, dashboard availability — all preserved.* No structural change to anything that's working.
- *Wave-N pattern is converging, not diverging.* Sync incidents per week are decreasing, not increasing. Option C bets on continued convergence.
- *Cost is $0.* Migration cost is low per task; finishable in 3-5 person-weeks.

### 5.3 Residual uncertainty

Five sources of uncertainty I cannot resolve from the codebase alone:

1. **Render Postgres tier and bill.** `render.yaml:32` says `sync: false` — repo cannot see the price. If operator currently pays $20-$25/mo on Standard tier and Option C buys nothing on cost while Option B (Cloudflare Tunnel B3 variant) saves the same amount, the calculus shifts. **Operator should confirm the bill.**
2. **Cloud dashboard usage frequency.** If operator hits the dashboard <5 times/day, B3 (Cloudflare Tunnel) becomes more attractive — dashboard downtime during home-machine reboots is barely felt. If operator hits it 50+ times/day, the current Render-hosted setup pays for itself.
3. **Multi-host backup-machine plans.** If operator plans to add a backup machine in next 6 months, Option C's `target_host` harden task becomes time-critical. If multi-host is not in plan, less urgent.
4. **Frontend cloud-vs-local detection thoroughness.** Audit (gap §10.4) did not deeply audit the React frontend's `/api/status` detection path. Hidden code-paths could break under Option A. Status quo + hardening avoids this risk entirely.
5. **Composite-PK compatibility in libsql/Turso.** Audit (gap §10.5) did not verify `correlation_matrices` / `factor_loadings` / `minute_bars` composite PKs against libsql's documented constraints. Would need a feasibility spike before Option B2 could be taken seriously.

### 5.4 What would change my recommendation

- **If operator confirms a backup-machine plan within 6 months**, the status-quo recommendation downgrades from HIGH to MEDIUM and Option A becomes worth revisiting (PG advisory locks give cleaner multi-host coordination than the host-keyed sync_state pattern).
- **If operator's Render PG bill exceeds $50/mo**, Option E (Cloudflare Tunnel — see §4.5) becomes the cost-dominated winner.
- **If operator dashboard usage frequency is < 10 hits/day**, Option E becomes the cost-dominated winner regardless of bill — at $0/mo and zero sync layer, it dominates Option C's 5-7 person-weeks of harden work for a low-traffic dashboard. Option C harden tasks H2 (PG pool), H3 (idempotency token), H6 (target_host) all become moot under E and should be deferred until E is evaluated.
- **If three more sync impedance bugs ship in the next 30 days**, the "Wave-N pattern is converging" claim weakens and consolidation gets revisited.
- **If new cloud-initiated trading actions are added** that flow via `pending_commands` (dashboard-set risk overrides, position caps, scheduled liquidations), the asymmetric trading-state safety property (§1) degrades: write-side coupling to PG broadens. Option A becomes less of a regression because it would couple BOTH sides equally rather than introducing asymmetric exposure.
- **If operator wants to explicitly invest in cloud dashboard reliability beyond what dual-store delivers**, Option A becomes worth its cost.

### 5.5 Honest acknowledgement: the dual-store IS overengineered for the scale

At 398MB / 70 tables / single-operator, the sync layer's 1359 LOC + 70 dual-mode classifications + three sync modes is more complex than the underlying single-machine system needs in isolation. **But it's not the right time to tear it down.** The complexity is now well-tested; the bug-finding rate is decreasing; the Category A tables would persist in any form; the trading-state safety property is real and currently free; and the largest LOC-cost papercut (cloud_routes dual-mode) has a cheap independent fix. The recommendation isn't "dual-store is the right architecture" — it's "dual-store is the architecture you have, and migrating it costs more than hardening it given current evidence."

The correct time to revisit was either (a) before the sync layer existed, by choosing Postgres-everywhere from the start, or (b) after a near-future operational pain that materially changes the calculus (per §5.4). It is not now.

---

## 6. Harden tasks (prioritized)

Seven tasks, listed in dependency-aware priority order. Effort estimates assume single-developer focused work; complexity ratings match `arcis:code` planner conventions (low/medium/high).

### H1 — DB-engine abstraction at `src/utils/db.py` (priority: HIGHEST)

**Why first.** Single largest source of repeated branching code (~70 LOC across 6 files). Independent of all consolidation choices. Reduces every future cloud-route's effort. Centralizes placeholder rewriting, eliminating a class of bugs. Sets up future option flexibility.

**Scope.**
- Build engine-aware `connect_db()` that routes to SQLite or psycopg2 based on connection-string scheme.
- Build `query()` / `query_one()` / `execute()` helpers that absorb `?` ↔ `%s` differences and `RealDictCursor` vs `sqlite3.Row` differences.
- Migrate the 6 verified dual-mode files: `src/api/cloud_routes/platform.py`, `src/api/cloud_routes/kpis_compute.py`, `src/api/cloud_routes/broker_exceptions.py`, `src/api/cloud_routes/preflight.py`, `src/api/cloud_routes/commands.py`, `src/api/cloud_routes/walkforward.py` (the `_read_rows` helper at L49-64). Also covers `src/api/routes/logs.py:194-198` which carries the same pattern. Explicitly out-of-scope: `src/evaluation/system_validator.py` — its `DATABASE_URL` references at L560 + L579 are Render config-validation hits (preflight), not per-call routing branches.
- Keep all existing tests passing. Add tests covering the abstraction itself (placeholder rewriting, error mapping).

**Estimated complexity.** Medium. **~7-10 working days** (revised up from v2's 5-7 estimate per DA review). The mechanical refactor across 6 dual-mode files is small; the additional cost is auditing the 322 `connect_db(` + 14 raw `sqlite3.connect` = 336 total call sites for behavior preservation, plus placeholder-rewriting edge cases (parameterized IN clauses, TIMESTAMP literals, BOOLEAN coercion, RealDictCursor vs sqlite3.Row dict-key semantics).

**Risk.** Low-Medium. Mechanical refactor with strong test coverage.

**Blast radius.** All cloud routes + every site that uses `connect_db()`. Mitigate with module-by-module migration + keep old branches alive during transition. Bound H1 scope explicitly: H1 limits its blast to `src/api/cloud_routes/*` + `src/api/routes/logs.py` only and does NOT touch `src/sync/render_sync.py` (sync-layer changes are H3's territory).

**Test strategy.** Unit tests for placeholder rewriting + error mapping. Existing cloud-route tests must pass unchanged. Snapshot test on `EXPLAIN ANALYZE` for one canonical query under both engines.

### H2 — Add Postgres connection pool to `cloud_app.py`

**Why second.** High-recurring papercut (every dashboard request pays handshake). Independent of H1 but cleaner to land after H1 (uses the abstraction).

**Scope.**
- Replace `psycopg2.connect(DATABASE_URL)` per-request with `psycopg2.pool.ThreadedConnectionPool` (or migrate to `psycopg3` async — separate decision; sync pool is the lower-risk choice).
- Update `get_pg()` contextmanager to acquire/release from the pool.
- Configure pool size: start with min=2, max=8 for Render Standard's 1 vCPU.
- Add `/healthz` check for pool exhaustion.

**Estimated complexity.** Low. ~2-3 working days.

**Risk.** Low. Standard psycopg2 idiom.

**Blast radius.** Cloud-only. Local FastAPI unaffected.

**Test strategy.** Mock pool in `test_cloud_app.py`. Stress-test in staging Render environment if available.

### H3 — Idempotency token + executor-receipt protocol on `pending_commands`

**Why third.** Closes the silent-command-loss race at `render_sync.py:884-918`. Latent risk with HIGH severity for trading commands (`close_position`).

**Scope.**
- Add `consumed_at TIMESTAMP` column to `pending_commands` via `src/schema/registry.py:1581` (TableDef block).
- Update `pull_commands` flow: PG marks `claimed` only AFTER local executor writes `consumed_at`. Until then, command stays `pending` in PG (re-pulls on retry are safe because local INSERT OR IGNORE no-ops).
- Update local executor to write `consumed_at` immediately upon starting execution (before doing the work — guarantees we don't double-execute even on crash mid-execution).
- Backfill existing `claimed` rows with `consumed_at = claimed_at` for migration safety.
- Add CHANGELOG entry.

**Estimated complexity.** Medium. **~5-7 working days** (revised up from v2's 4-5 estimate per DA review). Property-based crash-resilience tests alone are 2-3 days; schema migration + executor refactor is 3-4 days. **HARD prerequisite: H4 must land first** — the new `consumed_at TIMESTAMP` column needs SQLite-vs-PG drift coverage before it ships, otherwise H3 inherits the same blind spot that produced #185/#243/#797.

**Risk.** Medium. Touches the trading hot path. MUST land with extensive integration tests including pg_integration coverage of the new column.

**Blast radius.** Sync layer + executor. Mitigate with feature flag during rollout.

**Test strategy.** Add property-based test for crash-resilience: simulate crash at every line of `pull_commands` and verify no command is ever silently lost. Required: pg_integration test (via H4 fixture) covering the new `consumed_at` column under TIMESTAMP semantic drift, NULL handling, and ON CONFLICT semantics. Existing `test_render_sync.py` patterns apply.

### H4 — Testcontainers-postgres CI job

**Why fourth.** Catches the substrate of all SQLite/PG impedance mismatches (#185, #243, #797, H2, H3) BEFORE they reach prod. Independent of consolidation; valuable in either direction.

**Scope.**
- Add `pytest-postgresql` to a NEW `requirements-test-pg.txt` (kept separate to not bloat `requirements-cloud.txt`).
- Build `tests/conftest_pg.py` mirroring `init_test_db` against PG. Use `pytest-postgresql` `postgresql_proc` + `postgresql_my` fixtures. Session-scoped DB creation, function-scoped txn rollback.
- Mark a SUBSET of representative tests with `@pytest.mark.pg_integration`. Aim for ~20 tests covering: sync mode classifications, ON CONFLICT semantics, savepoint behavior, DDL drift detection, strip-id logic.
- Run pg_integration tests in a separate CI job (not on every PR — too slow). Trigger on `[pg-integration]` PR label OR weekly schedule.
- Document the new CI job in CLAUDE.md.

**Estimated complexity.** Medium. **~7-10 working days** (revised up from v2's 5-7 estimate per DA review). Most cost is the test inventory + selection (~20 representative tests), but each will discover 5-10 SQLite-vs-PG drift bugs that need fixes in source code — those fixes are not in the H4 estimate above and add to wall time.

**Risk.** Low. Additive; existing tests unaffected.

**Blast radius.** CI only.

**Test strategy.** The output IS test infrastructure. Self-validating. **H4 is a HARD PREREQUISITE for H3 and H5** — both touch the sync schema and must validate against PG before production. Sequencing in §6.5 enforces this.

### H5 — Promote 4 Category-B tables to PG sync

**Why fifth.** Eliminates 4 dashboard blind spots (`model_evaluations`, `preference_pairs`, `bracket_health`, `daily_ib_health`). Operator visibility improvement. Independent of all other tasks.

**Scope.**
- Flip `sync_to_postgres=False` to `True` on the 4 Category-B `TableDef` entries in registry: `daily_ib_health` (`registry.py:382`), `model_evaluations` (`:521`), `preference_pairs` (`:612`), `bracket_health` (`:1718`).
- Choose appropriate `sync_mode` (likely `incremental` for all four; `daily_ib_health` may want `latest_only` if daily-only).
- For each of the 4 promoted tables, add a pg_integration test (via H4 fixture) covering: bulk backfill, NULL handling, monotonic ordering, ON CONFLICT semantics. Strip-id collision checks if tables use `INTEGER PRIMARY KEY`.
- Run `python -m src.main validate-schema --fix` + `python scripts/render_migrate.py` to provision PG-side tables.
- **Run a 1-cycle dry-run sync against staging Render PG (or local Docker PG via `pytest-postgresql`) with read-only post-validation BEFORE flipping `sync_to_postgres=True` in production registry.**
- Add cloud_routes endpoints to surface the new data on the dashboard (separate frontend work; out of harden-task scope).

**Estimated complexity.** Low. ~2-3 working days for backend; frontend separate.

**Risk.** **Low-Medium** (revised up from v2's Low per DA review). The 4 promoted tables have NEVER been through the sync pipeline. Bulk backfill on flip triggers the same `incremental` pipeline that produced #185/#243/#797/H2/H3 across 50 tables — TIMESTAMP semantic drift, NULL-handling on optional columns, ROWID-vs-SERIAL collision, INTEGER-vs-BIGINT mismatches all possible. Strip-id logic at `render_sync.py:608-614` is documented as "fix for a specific sync incident"; 4 new tables = 4 new opportunities to step on the historical landmines that 50 prior tables traversed individually.

**Blast radius.** New rows in PG; no schema change to existing tables. **Hard prerequisite: H4 (testcontainers-PG CI) must land first** so dry-run validation can catch impedance bugs before production.

**Test strategy.** Validate schema-registry CI passes. pg_integration tests (via H4) for each of the 4 tables. Spot-check sync produces non-empty rows. Worst-case rollback: flip `sync_to_postgres=True` → `False` and let the cycle skip these tables.

### H6 — `target_host` field on `pending_commands` (preparation for multi-host)

**Why sixth.** Removes a latent footgun for backup-machine plans without enabling multi-host. Default `NULL` = any host (current behavior). Optional `target_host = 'TRADING-PC'` constrains routing.

**Scope.**
- Add `target_host TEXT NULL` column to `pending_commands` via registry (`registry.py:1581`).
- Update `pull_commands` to include `WHERE target_host IS NULL OR target_host = %s`.
- Update cloud `_submit_command` to support optional `target_host` parameter. UI exposure deferred.
- Document in CLAUDE.md and operator guide.

**Estimated complexity.** Low. ~2 working days.

**Risk.** Low. Backward-compatible (NULL behaves as before).

**Blast radius.** Sync layer. Frontend unchanged unless operator opts in.

**Test strategy.** Unit test multi-host routing in isolation.

### H7 — Operator-guide DB inspection runbook

**Why seventh.** Closes the MS Access lock-incident class. Documentation, not code.

**Scope.**
- Add section to `docs/operator-guide.md`: "Inspecting the live SQLite DB safely".
- Document: `sqlite3 -readonly`, Python URI mode `file:.../ai_research_desk.sqlite3?mode=ro`, the 60s Windows handle-release window after closing external tools.
- Cross-reference CLAUDE.md "Database Access Rules".
- Include the 2026-04-19 incident as cautionary anchor.

**Estimated complexity.** Low. ~0.5 days.

**Risk.** None.

**Blast radius.** Documentation only.

**Test strategy.** Manual review with operator.

### Aggregate effort

| Task | Complexity | Days | Risk |
|---|---|---|---|
| H1 — DB-engine abstraction | Medium | 7-10 | Low-Medium |
| H2 — Postgres connection pool | Low | 2-3 | Low |
| H3 — Command idempotency token | Medium | 5-7 | Medium |
| H4 — Testcontainers-postgres CI | Medium | 7-10 | Low |
| H5 — 4 Category-B tables to PG | Low | 2-3 | Low-Medium |
| H6 — `target_host` on pending_commands | Low | 2 | Low |
| H7 — Operator-guide DB inspection | Low | 0.5 | None |
| **Total** | — | **25.5-37.5 days** | — |

Approximately **5-7 person-weeks** if done sequentially (revised up from v2's 4-5 estimate per DA review — H1/H3/H4 estimates raised by +30% to account for site-audit costs, property-based crash-test work, and SQLite-vs-PG drift remediation surfacing during H4). Realistic calendar time with one developer is ~4-5 weeks. Parallelization via `/arcis:code` could compress this to 3-4 calendar weeks with multiple agents working independent harden tasks, but **H4 → H3 and H1 → H2 are sequential dependencies** that bound the gain — parallelization buys at most ~30% reduction, not 70%.

### Sequencing recommendation

**Re-sequenced in v3 per DA review** — original v2 sequence had H3 in Week 3-4 and H4 in Week 4-5 (H4 AFTER H3), which would ship H3's `consumed_at TIMESTAMP` column with only SQLite-fixture coverage. H4 is exactly the safety net for H3-class bugs (TIMESTAMP semantic drift, NULL-handling, ON CONFLICT semantics on the new column), so H4 must precede H3. Same reasoning applies to H5 (bulk backfill of 4 untested-pipeline tables needs PG dry-run via H4 fixture before production flip).

- **Week 1**: H7 (instant doc win) + H6 (additive, backward-compatible). Two small wins. Validates harden cadence is achievable. H5 deferred to Week 5-6 (needs H4 prerequisite).
- **Week 2-3**: **H1 (DB-engine abstraction) + H4 (testcontainers-PG CI) in parallel**. H1 is the sole sync-layer / cloud-route touch in this window; H4 establishes PG fixture infra. They can run in parallel because H1's blast is `cloud_routes/` + `routes/logs.py`, while H4's blast is CI + new `tests/conftest_pg.py`.
- **Week 4**: **H2 (PG connection pool)**. Composes on H1's `query()` helper. Uses H4 fixture for tests.
- **Week 5**: **H3 (command idempotency token)**. Built against the now-stable H1 abstraction with H4 PG-integration coverage validating the schema change. Must NOT be parallelized with anything else touching the executor.
- **Week 5-6**: **H5 (4 Category-B tables to PG)**. Uses H4 to dry-run bulk backfill against staging PG before flipping `sync_to_postgres=True` in production registry.

**Hard dependency rules:**
- H4 is a HARD prerequisite for H3 (because H3 changes `pending_commands` schema) and H5 (because H5 promotes 4 untested-pipeline tables).
- H1 is a HARD prerequisite for H2 (because H2 uses the abstraction).
- H1 must merge fully BEFORE H3 starts (both touch sync/executor; mid-merge coordination risk).
- H7, H6 are independent and can land first.

**Coordination guardrail:** during Week 2-3 when H1 and H4 are in flight, both PRs must be reviewed against the explicit scope fences declared in their respective Blast Radius sections (H1: `cloud_routes/` + `routes/logs.py` only; H4: CI + `conftest_pg.py` only). Cross-touching files between these PRs forces a sequential merge.

---

## 7. Migration plan for Option A (FOR REFERENCE ONLY — NOT RECOMMENDED)

Included for completeness — if operator's calculus shifts per §5.4, this is the sketch. Sprint-grade detail only on the recommended Option C harden tasks (§6).

### A.1 Phased breakdown

**Phase 0 — Prerequisites (pre-sprint).**
- Confirm Render PG plan + monthly bill.
- Decide local-PG runtime: Docker Desktop vs native Windows install. Docker is simpler ops; native is more performant.
- Verify libsql/Turso is NOT a competing path (per §5.3 spike).
- Land Option C harden tasks H1+H4 first — abstraction layer + testcontainers — they are prerequisites, not detractors.

**Phase 1 — Provision local PG and dual-write transition (~1 week).**
- Install local PG. Schema-derive from registry.
- Add `WRITE_DUAL_DB` feature flag. When set: `connect_db().execute()` writes to BOTH SQLite and local PG.
- Run for one operator cycle. Diff row counts at end. Investigate any divergence.

**Phase 2 — Reads cutover (~1 week).**
- Add `READ_FROM_PG` feature flag. Cloud routes already use the H1 abstraction, so flipping the env var routes reads to local PG (via Tailscale tunnel) instead of Render PG.
- Validate dashboard parity. Critical: trade-state queries, scan_metrics, council_votes, walkforward results.
- Trading reconciler stays on SQLite for now (per safety constraint).

**Phase 3 — Trading reconciler cutover (rollback gate).**
- ROLLBACK GATE 1: trading must operate cleanly on local PG for 1 trading week before further rollout.
- Migrate `src/shadow_trading/reconcile_state.py:32-44` `connect_db(DB_PATH)` to engine-aware `get_engine()`.
- Add fallback: if local PG unreachable, reconciler refuses to act (better than acting on stale data).

**Phase 4 — Sync thread retirement (~1 week).**
- Replace push-replication with PG streaming replication or `pglogical`.
- Verify cloud Render PG follows local PG within 5s lag.
- Retire `src/sync/render_sync.py`. Retire `src/schema/sqlite.py` (or keep as vestigial test fixture).
- Update CHANGELOG with comprehensive migration entry.

**Phase 5 — Test fixture cutover (~1 week).**
- Migrate `tests/conftest.py::init_test_db` from SQLite to `pytest-postgresql`.
- Update 60-80 tests that touch `init_test_db`.
- Update `test_render_sync.py` to retire — sync layer no longer exists.
- Verify the CLAUDE.md-codified test floor of 3682 is preserved (current count 4574; floor must remain a hard invariant).

**Phase 6 — Cleanup (~3 days).**
- Remove Category-B tables from local-only category — they sync via streaming replication now.
- Move Category A tables (`sync_state`, `system_metrics`, `data_freshness`, `config_overrides`-cache, `operator_view_state`) to a small private SQLite at `C:/arcis/data/local_state.sqlite3` — they don't need PG.
- Update CLAUDE.md "Database Access Rules".

**Total estimated calendar time: 4-6 weeks** for a focused migration. Probable real-world: 8-10 weeks with normal interruptions.

### A.2 Rollback gates

- **Gate 1 (after Phase 1)**: dual-write divergence > 0.1% of rows. Rollback: disable WRITE_DUAL_DB, forensics on the divergent tables.
- **Gate 2 (after Phase 2)**: dashboard parity audit fails on trade-state, scan_metrics, council_votes, OR walkforward results. Rollback: flip READ_FROM_PG off.
- **Gate 3 (after Phase 3)**: trading reconciler error rate > 1/week. Rollback: revert reconcile_state.py to SQLite.
- **Gate 4 (after Phase 4)**: streaming replication lag > 60s for >1h. Rollback: re-enable RenderSyncThread; investigate replication.
- **Gate 5 (after Phase 5)**: test count drops below the CLAUDE.md-codified floor of 3682 OR test runtime > 2× baseline. Rollback: keep SQLite test fixtures alongside.

### A.3 Blast radius

- Phase 1-2: local-only. No cloud impact.
- Phase 3: trading-side. CRITICAL. Live trading must continue uninterrupted.
- Phase 4: cloud-side. Dashboard could go stale during transition; mitigate with read-from-old-PG fallback.
- Phase 5: CI-side. Risk is test-floor regression, not production.
- Phase 6: documentation + cleanup. Negligible runtime risk.

### A.4 Test strategy

- Maintain CLAUDE.md-codified test floor of 3682 at every phase (current count 4574; floor must not drop).
- Add 30+ NEW tests covering engine-abstraction edge cases (placeholder rewriting, error mapping, transaction semantics).
- Add testcontainers-PG integration job (the H4 harden task is a prerequisite).
- Property-based crash-resilience tests for the trading reconciler's PG dependency.

### A.5 Schema-registry impact

- Registry remains canonical.
- `src/schema/sqlite.py` deleted or kept as vestigial.
- `src/schema/postgres.py` becomes the only DDL generator.
- `src/schema/sync_config.py` deleted along with sync thread.
- 70-table count likely drops to 64-65 (sync_state, system_metrics, data_freshness, etc. move to local-only state DB at `local_state.sqlite3`).
- `python -m src.main validate-schema --fix` becomes the canonical (and only) DDL apply.

---

## 8. Risks + open questions

### 8.1 Risks (recommended path — Option C)

- **Hardening fatigue.** 7 harden tasks across 3-5 person-weeks. Operator may experience this as "more of the same" rather than "finishing the loop." Mitigate with explicit week-by-week sequencing in §6, demonstrating that the harden tasks ARE finite.
- **Latent risks remain latent.** H3 (command idempotency) and H6 (target_host) close real risks but don't eliminate the underlying single-host invariant. Backup-machine work would still require explicit operator authorization.
- **Vendor / ecosystem drift.** psycopg2 is on long-term maintenance. psycopg3 is the future. H1+H2 should consider whether to use psycopg3 from the start (async-capable, cleaner API). Decision deferred to H1 implementation.
- **The dual-mode-branch removal in H1 leaves Render PG as the only consumer of the abstraction's PG side.** If a future migration to Option B (libsql/Turso) happens, the abstraction's PG branch becomes vestigial. Acceptable risk — abstractions outlast their original use cases.

### 8.2 Risks specific to NOT recommending Option A

- **Sync-impedance bug class is not eliminated, only contained.** H4 (testcontainers-PG) catches future drift before prod, but the underlying impedance-mismatch surface remains. Acceptance: the surface is now well-understood and stable; bugs in this class have decreasing frequency post-Wave 4.
- **Trading-state safety is preserved at the cost of architecture purity.** Some readers may interpret "refused to consolidate" as "refused to commit to a clean design." Counter-argument: the dual-store IS the clean design when the safety property is articulated explicitly.

### 8.3 Open questions for operator

1. **What is the actual Render PG monthly bill?** Repo cannot tell. Determines whether B3 (Cloudflare Tunnel) becomes cost-attractive.
2. **Is a backup-machine plan in next 6 months?** Determines whether H6 is time-critical.
3. **What is dashboard usage frequency (hits/day)?** Determines whether B3 (availability tradeoff) is acceptable.
4. **Should psycopg3 (async) be used in H1 instead of psycopg2 (sync)?** Operator preference for battle-tested deps may say no; future-proofing may say yes.
5. **Should H4 (testcontainers-PG CI) run on every PR or weekly?** Every-PR is more thorough but adds 5-15 min per PR; weekly catches drift but allows it to land in main first.

---

## 9. Out of scope

Explicitly excluded from this spec:

- **Migration script implementation.** This spec describes the plan; coding happens in a follow-up Wave (per arcis:code dispatch). Each harden task in §6 is an arcis:code-sized task on its own.
- **Specific Render plan tier upgrades.** Operator decision; spec flags assumptions as ASSUMED.
- **Backup/disaster recovery as a separate concern.** Mentioned in context of Litestream (B1) and `sqlite3_rsync` (B4) but not deep-dived. See `docs/research/Disaster_Recovery_for_Solo_Algorithmic_Trading.md`.
- **IB Gateway / live trading architecture changes.** Out of scope; this is purely DB-layer.
- **Frontend-side dashboard refactors.** H5 (4 Category-B tables to PG) opens a frontend work item but does not schedule it.
- **Multi-host backup-machine architecture.** H6 (`target_host`) prepares for it without authorizing it. Per brief constraint, multi-host requires explicit operator authorization.
- **Methodology workflow changes.** Stage 1 corpus, walkforward, simulation engine all stay local-only per brief constraint. No DB-engine change touches them.
- **Cloudflare Tunnel B3 evaluation.** Discussed as residual uncertainty in §5.3 but not deeply scoped — would warrant its own spec if pursued.
- **psycopg2 → psycopg3 migration.** Deferred decision inside H1.

---

## 10. Coverage gaps acknowledged

From the deep audit (`deep_report.json` `coverage_gaps`):

10.1. **Did NOT measure actual Render Postgres bill.** All cost numbers are flagged ASSUMED.
10.2. **Did NOT trace every one of the 336 raw `connect_db()` / `sqlite3.connect` call sites** (322 `connect_db(` + 14 raw `sqlite3.connect`, measured 2026-05-05). Analyzed via the 6 cloud_routes files where `if database_url:` runtime branches actually live; the bulk count is the noise floor; the dual-mode set is the signal.
10.3. **Did NOT execute the sync pipeline end-to-end against a real Postgres.** Relied on source-code reading + operator-memory-documented incidents.
10.4. **Did NOT examine the React frontend code** for cloud-vs-local detection. Architect should verify frontend wouldn't break if cloud-mode were eliminated.
10.5. **Did NOT verify libsql/Turso compatibility** with composite PKs in `correlation_matrices` / `factor_loadings` / `minute_bars`. Spike required if Option B2 ever revisited.
10.6. **Did NOT measure operator's actual dashboard usage frequency.** Would inform B3 (Cloudflare Tunnel) cost calculus.
10.7. **Did NOT enumerate all CHANGELOG.md sync-incident entries** beyond the surface report's pre-extracted list. Newer minor sync issues may exist but unlikely to change the architectural assessment.

---

## 11. Design Decisions

| Decision | Rationale | Alternatives considered |
|---|---|---|
| Recommend Option C (status quo + harden) at HIGH conviction | Trading-state safety property + bidirectional command queue blocks Litestream + tests are 100% SQLite-bound + Wave 4 closed the Critical-severity sync bugs | Option A (rejected: safety regression + 1-3 person-weeks migration cost); Option B1/Litestream (rejected: incompatible with bidirectional queue); Option B2/Turso (rejected: vendor risk on trading hot path); Option B3/Cloudflare Tunnel (deferred pending operator dashboard-usage data) |
| Absorb Option D (DB-engine abstraction) into Option C as harden task H1 | The abstraction is the highest-leverage harden task regardless of consolidation choice; keeping it as a standalone option creates a false trichotomy | Treat D as a separate "first do this, then decide" path (rejected: same migration cost, same outcome — H1 is the actionable form) |
| Flag Render PG cost as ASSUMED, not computed | `render.yaml:32` `sync: false` — repo cannot see PG plan; operator must verify | Skip cost altogether (rejected: cost is a brief-required dimension); fabricate a number from public pricing (rejected: dishonest) |
| Size H1 (DB-engine abstraction) at 5-7 days as Medium | 6 verified dual-mode files × ~10-30 LOC each + new abstraction module + tests; mechanical refactor with strong test coverage | Size as Low (rejected: too optimistic given placeholder-rewriting subtleties); Size as High (rejected: there's no architectural unknown, just careful work) |
| Size H4 (testcontainers-postgres CI) as Medium | Most cost is test inventory + selection (~20 representative tests), not infrastructure; pytest-postgresql is a known-good library | Size as Low (rejected: test selection is a real judgment call, not boilerplate); Skip entirely (rejected: closes the substrate of #185/#243/#797/H2/H3) |
| Set the CLAUDE.md-codified test floor of 3682 as a HARD invariant in any migration | CLAUDE.md enforces this CI baseline (current count 4574 from `pytest --collect-only` 2026-05-05); any path that drops tests below 3682 must replace them 1-for-1 | Allow temporary test-count regression with rollback gate (rejected: floor is operator-codified, not negotiable) |
| Preserve trading-state sync-independence as a SAFETY PROPERTY worth explicitly defending | Wave 4 H1/H2/H3 only ever degraded dashboard, never trade state; this is non-trivial and undocumented anywhere | Treat trading-state coupling as an acceptable tradeoff for cleaner architecture (rejected: dollar-loss potential is unbounded and the safety property is currently free) |
| Recommend testcontainers-postgres on a SEPARATE CI job (not every PR) | Every-PR adds 5-15 min latency; weekly catches drift before prod release; matches arcis CI conventions | Run on every PR (rejected: latency tax + flakiness from PG container startup); Skip entirely (rejected: drift class is the largest remaining bug substrate) |
| Refuse to recommend libsql/Turso (Option B2) without explicit operator consideration of vendor risk | Operator's stated preference for battle-tested deps (psycopg2, pandas, scipy); Turso founded 2022 on trading hot path | Recommend Option B2 because of free-tier cost and bidirectional support (rejected: vendor risk on trading hot path is structurally serious; flagged as residual uncertainty for re-evaluation, not a current recommendation) |
| Include Cloudflare Tunnel (B3) as residual uncertainty rather than option in §4 | B3 trades availability for simplicity; brief flags dashboard as heavily-used; cannot evaluate without dashboard usage data | Treat B3 as a full option (rejected: lacks operator usage data); Exclude entirely (rejected: it's a real path that could win if usage frequency is low) |
| Set H6 (target_host) priority as MEDIUM-LOW within harden bundle | Latent risk; only matters if operator commits to backup-machine plans; backward-compatible on its own | Skip (rejected: closes a real footgun cheaply); Make it H1 (rejected: not the highest-leverage task) |
| Refuse to estimate person-weeks for Option A migration as a primary recommendation timeline | Operator-time is the scarcest resource; Option A's 1-3 person-weeks is real cost against $0 marginal benefit at current evidence | Provide a calendar-time "if started today" answer (rejected: not the right framing because Option A isn't recommended); Skip the cost discussion (rejected: brief required cost dimension) |
| Re-anchor all `registry.py` line citations at the `name="..."` declaration | Phase 7 feasibility caught systematic 11-29 line drift between original audit and current 2495-line registry; anchoring at attribute lines (e.g. `sync_to_postgres=`) creates fragility because attributes move within blocks; the `name=` declaration is the most stable anchor | Anchor at `_register(TableDef(` opening (rejected: less directly searchable than `name="foo"`); leave original drifted citations (rejected: spec credibility rides on citation accuracy per operator strict-rigor directive) |
| Make HIGH conviction CONDITIONAL on three §0 prerequisites (v3 revision) | DA review correctly identified that HIGH with five unresolved uncertainties is overconfident. Conditional grading lets the recommendation hold its strength IF prerequisites resolve favorably while honestly admitting it could downgrade if they don't. Forces operator to answer the questions BEFORE committing to 5-7 person-weeks of harden work. | Downgrade conviction outright to MEDIUM-HIGH (rejected: loses the signal that Option C is the right answer in the most-likely prerequisite-resolution scenario); Keep flat HIGH and bury the prerequisites in §8 (rejected: violates strict-rigor — prerequisites should be visible at top, not buried) |
| Promote Option E (Cloudflare Tunnel) to full option, not residual uncertainty (v3 revision) | DA review correctly identified that dismissing E without first asking operator the question that would resolve dismissal is incoherent. E genuinely dominates Option C if dashboard usage is low — at $0/mo and zero sync layer, it obviates H2/H3/H6 entirely. Demoting E to a footnote would burn 4-5 person-weeks of harden work that E would make moot. | Keep E as residual uncertainty (rejected: incoherent with §0 prerequisite #3); Recommend E as primary (rejected: E loses if dashboard usage is high, which is plausible given operator's stated dashboard-heavy use) |
| Rewrite trading-state safety claim as ASYMMETRIC (READ-side independent, WRITE-side coupled) (v3 revision) | DA review correctly identified that v2's framing claimed wholly-independent trading state but `pull_commands` flows cloud-initiated trading actions THROUGH the PG sync arrow, making cloud-initiated `close_position` (and any future dashboard-driven action) coupled to PG availability. Honest framing distinguishes which trading actions are sync-independent (local-initiated, automated) vs which depend on PG (cloud-initiated). | Keep v2 framing (rejected: factually incomplete — DA caught real asymmetry in `pull_commands` flow); Drop the safety claim entirely (rejected: read-side independence is real and worth defending) |
| H4 (testcontainers-PG CI) is a HARD prerequisite for H3 and H5 — re-sequenced in v3 | DA review correctly identified v2's sequencing was backwards: H3 changes `pending_commands` schema and H5 promotes 4 untested-pipeline tables, both shipping new SQLite-vs-PG drift surface. H4 is exactly the safety net for that drift class. v2 had H4 in Week 4-5 AFTER H3 — wrong order. v3 re-sequences H4 into Week 2-3 alongside H1, before H3 (Week 5) and H5 (Week 5-6). | Keep H4 last "because it's stabilization" (rejected: H4 is preventive not reactive); Skip H4 entirely (rejected: closes the largest remaining bug substrate) |
| Raise H1/H3/H4 effort estimates by +30% in v3 | DA review correctly identified v2 estimates as systematically optimistic. H1: 5-7 → 7-10 days (336 connect_db audit cost + placeholder edge cases). H3: 4-5 → 5-7 days (property-based crash tests alone are 2-3 days). H4: 5-7 → 7-10 days (each of ~20 PG-fixture tests will discover SQLite-vs-PG drift bugs needing source fixes). New aggregate: 25.5-37.5 days = 5-7 person-weeks (was 4-5). | Keep v2 estimates (rejected: systematic optimism is dishonesty per strict-rigor); Raise more aggressively (rejected: +30% is the documented variance from the DA findings; further inflation needs evidence) |
| Raise H5 risk rating Low → Low-Medium with H4 prerequisite (v3 revision) | DA review correctly identified that 4 promoted Category-B tables have NEVER been through the sync pipeline. Bulk backfill on flip triggers the same `incremental` pipeline that produced #185/#243/#797/H2/H3 across 50 tables. "Low" risk understates this. v3 raises rating + makes H4 dry-run validation a hard prerequisite. | Keep "Low" (rejected: ignores 4 untested-pipeline tables); Raise to "Medium" (rejected: the backfill is well-bounded and rolls back cleanly via flag flip) |

---

## 12. Known Considerations (DA minor findings — addressed inline)

These minor issues from the Devil's Advocate review were folded into the v3 revisions above. Listed here for traceability:

1. **Wave-N convergence claim was asserted without quantification** — addressed with a §3 footnote (added in v3) noting that quantification of sync-incident frequency by Wave is a follow-up audit task; current claim of convergence rests on the qualitative observation that Wave 4 closed 3 Critical-severity bugs while no new Critical-severity sync issues have surfaced post-merge as of the spec date (2026-05-05). A `git log --grep="sync" --since="6 months ago"` per-month bucketing would harden this if challenged.

2. **Standalone Option D ("land H1 only, defer H2-H7, re-evaluate in 6 months")** — addressed in §4.4 (added "Sub-option D-only" paragraph). This sub-option creates real option value (in the financial sense): land the abstraction, observe the codebase under engine-choice ambiguity for 6 months, then decide. Only viable if §0 prerequisite #3 (dashboard usage) is HIGH so H2 PG-pool isn't urgent; under low usage, Option E should be evaluated first.

3. **H1 + H3 coordination risk during overlapping weeks** — addressed in §6.5 sequencing rewrite (v3): H1 lands fully in Week 2-3 BEFORE H3 starts in Week 5, removing the merge-conflict window. Cross-touching files between H1 and H4 PRs (which are concurrent in Week 2-3) is ruled out by explicit scope fences declared in each task's Blast Radius section.

4. **§4.1 step 4 batching strategy ambiguity** — left as-is per the spec's explicit framing that §7 is "FOR REFERENCE ONLY — NOT RECOMMENDED." A future Option-A spec would re-derive batching from current call-site map.

5. **§3 references column mixes file:line / PR# / CHANGELOG entries inconsistently** — left as-is; cosmetic and not actionable. Different reference systems are appropriate to different evidence types.

6. **§7 Phase 5 references "CLAUDE.md-codified test floor of 3682" three times** — left as-is; redundancy aids readers who skim individual phases without reading prior ones. Cost is trivial.

---

## 13. Revision history (verbose)

This spec went through three revisions; each preserves the architectural recommendation of Option C while sharpening or correcting framing:

- **v1 (2026-05-05, initial)** — full investigation across 4 options (A/B/C/D), 12 design decisions, recommendation: Option C at HIGH conviction.
- **v2 (2026-05-05, citation cleanup)** — Phase 7 feasibility caught systematic 11-29 line drift in registry citations. All 21 `registry.py` lines re-anchored at `name="..."` declarations. Cloud-routes dual-mode list trimmed (`system_validator.py` removed — it has DATABASE_URL hits but they're config-validation, not per-call routing). Mode counts re-tallied as 50+5+6+9=70. Test floor re-anchored as CLAUDE.md-codified (3682 floor; 4574 current). Recommendation unchanged.
- **v3 (2026-05-05, devil's advocate concerns)** — applied 6 MAJOR fixes from DA Phase 7 Step 2 review:
  - §0 PREREQUISITES block added at top — three operator-answered questions before harden work commits.
  - Conviction grade made CONDITIONAL (HIGH IF prerequisites resolve favorably).
  - §1 trading-state safety claim rewritten as ASYMMETRIC (READ-side independent, WRITE-side coupled via `pull_commands`).
  - §4.5 added — Option E (Cloudflare Tunnel) promoted from residual uncertainty to full option with tradeoff matrix.
  - §6.5 re-sequenced — H4 now precedes H3 + H5 (testcontainers-PG fixture infra is prerequisite for the schema-touching tasks).
  - H1/H3/H4 effort estimates raised +30% (aggregate 5-7 person-weeks, was 4-5).
  - H5 risk rating raised Low → Low-Medium with H4 prerequisite explicit.
  - 6 new design decision rows added to §11 (now 18 total, was 12).
  - 6 minor DA findings folded into Known Considerations (§12).
  - Reject options renumbered F/G/H (was E/F/G) since "Option E" slot is now Cloudflare Tunnel.

Architectural recommendation across all three revisions: **Option C — Status Quo + Targeted Hardening** with the DB-engine abstraction (Option-D fragment) baked in as harden task H1. The recommendation strengthens at each revision but does not change.
