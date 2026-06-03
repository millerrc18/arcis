# Runbook — `clean_slate_wipe.py` (W21 capstone #95)

> **DESTRUCTIVE.** This script TRUNCATEs the trade/learning table set on **PROD PG
> (5433)**. It is **dry-run by default** and refuses a prod DSN without
> `ARCIS_ALLOW_PROD_PG=1` AND `--confirm`. Read this runbook fully before running.
> EXECUTION is operator-gated; the build/test PR never runs a real wipe.

Spec: `docs/superpowers/specs/2026-06-03-clean-slate-wipe-design.md`
Plan: `docs/superpowers/plans/2026-06-03-clean-slate-wipe.md`

---

## What it does (auto)

1. **Reconciles** the live prod public schema + the wipe-touching FK edges against
   the registry (authoritative gate — aborts on drift).
2. **Backs up** prod PG (`docker exec halcyon-pg pg_dump`), **verifies** the dump
   (size + SHA + exactly 80 `CREATE TABLE`), and **verify-restores** it into a
   FRESH EPHEMERAL DB created+dropped on the **5434** test server (NOT the shared
   test DB) with a per-table count-compare. Any failure REFUSES the wipe.
3. **TRUNCATEs** the 53-table WIPE set in a single `TRUNCATE ... RESTART IDENTITY
   CASCADE` transaction (the 27-table KEEP/market-data set is preserved),
   re-checking the watch loop at the transaction boundary.
4. Writes a fsync'd **`WIPE_COMMITTED.marker`** immediately after commit.
5. **Retires** the legacy SQLite residue (archive → fsync → empty-in-place; never
   blind-delete).
6. **Post-verifies** the DB (WIPE → 0, KEEP unchanged, `model_versions` empty) and,
   with `--verify-config`, the config/Ollama reset.
7. Emits a structured **`manifest.json`** + an operator banner.

## What it does NOT do (you do these — see "After")

- Edit prod YAML config (`llm.model`, `risk.starting_capital`, `post_bootcamp`).
- Pull/load the Ollama base tag at the OS level.
- Flatten the Alpaca/IB broker — it **ABORTS** on open positions.
- Run the wipe without `--confirm` + `ARCIS_ALLOW_PROD_PG=1`.

---

## Hard preconditions (the script aborts otherwise)

| Gate | Abort verdict | Operator action |
|---|---|---|
| Watch loop running (Phase 0 + re-checked at the TRUNCATE boundary) | `ABORT_WATCHLOOP` / `ABORT_WATCHLOOP_RECHECK` | `nssm stop ArcisWatchLoop`; verify `SERVICE_STOPPED`. |
| NSSM stopped-state unverifiable (nssm not on PATH) | `ABORT_WATCHLOOP_UNVERIFIED` | Run the stop + pass `--i-have-stopped-nssm` (attestation). |
| Live public schema ≠ registry | `ABORT_LIVE_SCHEMA_DRIFT` | Register+classify the live-only table, or `create_all_tables` the registry-only one. |
| Unexpected live FK edge touching a WIPE table | `ABORT_FK_DRIFT` | Investigate the unmodeled edge (a CASCADE could reach KEEP data). |
| Open broker positions | `ABORT_BROKER_NOT_FLAT` | Flatten the broker; pass `--i-have-flattened-broker` ONLY when truly flat. |

> There is **no market-hours `@safety_window`** — the config key does not exist. The
> gates above are the destructive-run guards. `--emergency` is **inert** (it bypasses
> nothing).

---

## Procedure

### Before

```
nssm stop ArcisWatchLoop          # verify SERVICE_STOPPED / disabled, not just idle
# Flatten the broker (the script ABORTS on open positions). --i-have-flattened-broker
# only after the broker is truly flat.
set ARCIS_ALLOW_PROD_PG=1         # explicit operator opt-in (required for prod)
```

### 1. Dry run first (no `--confirm`)

```
python scripts/clean_slate_wipe.py
```

Review: the WIPE list + **live row deltas**, the KEEP list (proof market data is
preserved), the reconciliation verdicts, and all WARN/ABORT flags.

> **Note:** the dry run **already connects to and DUMPS prod** (read-path:
> reconcile + pg_dump + preview run before the confirm/guard short-circuit). This is
> read-only / off-box and is surfaced in the banner.

### 2. Execute (operator GO)

```
python scripts/clean_slate_wipe.py --confirm
```

The wipe runs only with `--confirm` AND `ARCIS_ALLOW_PROD_PG=1`. The script backs up
+ verify-restores, then TRUNCATEs in one transaction.

### After (config — MANUAL, utf-8)

Edit `config/settings.local.yaml` (use a utf-8-safe editor — cp1252 corrupts glyphs):

- `llm.model` → the **base Ollama tag** (else inference keeps serving the fine-tune).
- `live_trading.post_bootcamp` → `false`.
- `risk.starting_capital` → `100000` (PAPER).
- **DO NOT touch `live_trading.starting_capital` = 100** (the $100 LIVE account).

> Capital resets **emergently** on the paper path: realized equity is
> `risk.starting_capital + SUM(shadow_trades.pnl_dollars)`; TRUNCATE-ing `shadow_trades`
> zeroes the PnL term, so the config step only *confirms* `starting_capital=100000`.

### After (Ollama — OS)

Ensure the **base tag** is the loaded Ollama model.

### 3. Re-run `--verify-config` to certify the config/Ollama layer

```
python scripts/clean_slate_wipe.py --verify-config --base-tag <base-ollama-tag>
```

This flips the manifest's `POST_VERIFY_CONFIG_PENDING` → `PASSED` (or `FAILED`). A
clean slate is **certified only when BOTH** `POST_VERIFY` (DB) and
`POST_VERIFY_CONFIG` (config/Ollama) are `PASSED`.

### 4. Restart + regenerate (two-layer staleness)

Restart the watch loop **AND** force-regenerate the stale `audit_reports` verdict so
the governor does not act on pre-wipe state (the governor trusts the last verdict
~36 h — a restart alone is insufficient).

### 5. Verify

Confirm the clean restart against `manifest.json` (final verdict + both post-verifies
`PASSED`).

---

## CLI flags

| Flag | Effect |
|---|---|
| `--confirm` | Execute the wipe (default: dry-run preview only). |
| `--dsn DSN` | Prod PG DSN (default: `.env DATABASE_URL` via dotenv). |
| `--scratch-server-dsn DSN` | Maintenance DSN for the ephemeral verify DB (default: `postgresql://test:test@127.0.0.1:5434/postgres` — the 5434 maintenance DB, **NOT** the shared `halcyon` test DB). |
| `--out-dir DIR` | Backup/manifest output base (default: `data/backups/clean_slate`). |
| `--skip-sqlite` | Skip the SQLite retire phase. |
| `--i-have-flattened-broker` | Attest the broker is flat (downgrades open-positions ABORT to a recorded WARN). |
| `--i-have-stopped-nssm` | Attest `nssm stop ArcisWatchLoop` was run (when nssm cannot self-verify). |
| `--verify-config` | Run the config/Ollama post-reset assertion (run AFTER the manual config steps). |
| `--base-tag TAG` | Expected base Ollama tag for `--verify-config`. |
| `--emergency` | **RESERVED / INERT** — does nothing. The wipe still requires `--confirm` + `ARCIS_ALLOW_PROD_PG=1` and all hard gates. |

---

## `manifest.json` schema (Phase 7)

Atomic write (`temp + os.replace`). Fields:

| Field | Meaning |
|---|---|
| `started_at_et`, `completed_at_et` | ISO 8601 ET run bounds. |
| `run_dir` | `data/backups/clean_slate/<ISO8601>/`. |
| `confirm`, `flags` | The run mode + the attestation/skip flags. |
| `server` | `{database, port}` (read via `current_database()` / `inet_server_port()`). |
| `live_schema` | `{result: LIVE_SCHEMA_OK, live_count, registered_count}`. |
| `live_fk_edges` | `{result: LIVE_FK_OK, edge_count, missing_modeled_edges}`. |
| `broker_positions_open`, `open_shadow_trades` | Advisory/gating inputs. |
| `wipe_counts_phase0`, `keep_counts_phase0` | Pre-wipe per-table counts. |
| `backup` | `{result: BACKUP_VERIFIED, dump_path, size_bytes, sha256, create_table_count, restore_verdict, restored_table_count, verify_db, per_wipe_table_counts, empty_state_tag?}`. |
| `truncate` | `{before, after, deltas, statement}` (per-table row deltas). |
| `model_reset` | `{model_versions_after, l1_db_reset, l2_l3_config}`. |
| `sqlite_retire` | `{result: SQLITE_RETIRED|SQLITE_ABSENT|SKIPPED, archive_path, archive_sha, emptied_tables}`. |
| `post_verify_db` | `{result: POST_VERIFY_PASSED|POST_VERIFY_FAILED, failures, wipe_counts, keep_counts}`. |
| `post_verify_config` | `{result: POST_VERIFY_CONFIG_PENDING|PASSED|FAILED, failures, config, ollama_loaded}`. |
| `warnings` | Recorded WARN strings (e.g. `BROKER_NOT_FLAT_OVERRIDE`). |
| `result` | Final verdict: `WIPE_COMPLETE` / `ALREADY_CLEAN` / `POST_VERIFY_FAILED`. |

Sidecar: **`WIPE_COMMITTED.marker`** (fsync'd) is written in the run dir immediately
after the TRUNCATE commits and before Phase 4. A `WIPE_COMMITTED.marker` present
WITHOUT a sibling `manifest.json` means the run was interrupted after the
(irreversible) commit — re-entry is safe: the re-run hits the `ALREADY_CLEAN`
short-circuit (TRUNCATE of empty tables + already-empty SQLite are no-ops).

---

## Refuse / abort verdicts (quick reference)

| Verdict | Phase | Meaning |
|---|---|---|
| `dry_run` | — | No `--confirm`; preview only, zero mutation. |
| `prod_guard_block` | decorator | Prod DSN without `ARCIS_ALLOW_PROD_PG=1` AND `--confirm`. |
| `ABORT_WATCHLOOP` / `ABORT_WATCHLOOP_RECHECK` / `ABORT_WATCHLOOP_UNVERIFIED` | 0 / 3.0 | Watch loop running / unverifiable. |
| `ABORT_LIVE_SCHEMA_DRIFT` / `ABORT_FK_DRIFT` | 0 | Live schema / FK reconciliation drift. |
| `ABORT_BROKER_NOT_FLAT` | 0 | Open broker positions (no override). |
| `ALREADY_CLEAN` | 0 | All WIPE tables already empty — no-op, NO backup. |
| `REFUSE_BACKUP` | 1 | pg_dump failed / dump < 1 MB / `CREATE TABLE` count < 80. |
| `REFUSE_SCHEMA_DRIFT` | 1 | `CREATE TABLE` count > 80 (live drift; reconcile first). |
| `REFUSE_VERIFY` | 1 | Ephemeral DB not empty pre-restore / restore error / count divergence. |
| `POST_VERIFY_FAILED` | 6 | DB post-verify mismatch (wipe already committed). |
| `POST_VERIFY_CONFIG_PENDING` / `..._FAILED` | 6 | Config/Ollama not yet reset / still stale. |

> `--emergency` is **inert**: it bypasses no gate. (No `@safety_window` in the stack.)
