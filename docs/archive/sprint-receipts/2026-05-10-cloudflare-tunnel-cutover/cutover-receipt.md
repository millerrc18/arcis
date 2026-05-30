# Cloudflare Tunnel + Modified-A Cutover — Cutover Receipt

**Date:** 2026-05-10 (Sun)
**Spec:** [`spec.md`](./spec.md)
**Branch:** `cutover/cloudflare-tunnel-modified-a-2026-05-10`
**Status:** Waves 1, 2, 3, 5 LANDED — Wave 4 OPERATOR-PENDING

---

## Wave 1 — Infrastructure ✅

| Item | Evidence |
|---|---|
| Spec committed (deliverable 0) | `18366bb` |
| `train.py` rewrite (Unsloth → Transformers+PEFT+TRL) + `.gitignore` allowlist | `c65fa19` |
| SP3 visual-verify + SP5 inventory artifacts | `d2d0fdc` |
| `docker-compose.yml` for Postgres 16 on `127.0.0.1:5433` | `3ae79d8` |
| Auth-gated local `app.py` + 3 missing routers (notifications/platform/walkforward) | `3ae79d8` |
| Render PG snapshot at `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB, 65 CREATE TABLE + 65 COPY blocks) | rollback artifact |
| Local SQLite snapshot at `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (507 MB) | rollback artifact |
| Schema mirrored to Docker PG (63 tables, 862 columns, 70 indexes) | `render_migrate.py` output |
| Frontend rebuilt with new `VITE_API_SECRET` | `dist/assets/index-CQ4STVC_.js` |
| NSSM `ArcisDashboard` service installed (sibling to `ArcisWatchLoop`) | operator-confirmed |
| Cloudflare Zero Trust public hostname `halcyonlab.app → http://localhost:8000` | operator-confirmed; apex `A 216.24.57.1` Render record deleted |
| E2E auth-gated curl through tunnel verified — 7 endpoints respond correctly | recorded in PM session log |

## Wave 2 — Engine awareness ✅

| Item | Commit | Reviewer Verdict |
|---|---|---|
| Engine-aware `connect_db` shim with `PostgresConnectionWrapper` + 4 new tests | `df728af` | QA APPROVE |

Key contract: default behavior (DATABASE_URL unset) byte-for-byte identical; `DATABASE_URL=postgres://…` returns PG wrapper; explicit `db_path` always SQLite (test fixture compat).

## Wave 3 — Cutover verification + Render decommission docs ✅ (operator handoff PENDING)

| Item | Commit | Status |
|---|---|---|
| Browser smoke-test checklist | `3141f0c` | template ready; **OPERATOR ACTION** to fill 6 pages |
| Render decommission runbook | `3141f0c` | template ready; **OPERATOR ACTION** to delete services |
| Wave 3 receipt template | `3141f0c` | operator fills post-completion |
| Auth-gated tunnel verification curl | PM-side | confirmed: 7/7 endpoints return correct status |

## Wave 4 — Live data migration + NSSM env flip ⚠️ OPERATOR-PENDING

**Not executed by PM** — too destructive without operator supervision (stops watch loop, writes 1.3M rows to PG, requires admin shell for `nssm set AppEnvironmentExtra`). Operator runs after PR merge OR before merge if preferred.

| Step | Status |
|---|---|
| Migration script (`scripts/sqlite_to_pg_migrate.py`) | LANDED — `80d882e` initial + `d8a0cf6` perf revisions |
| Perf optimizations (execute_values + streaming + single PG conn) | LANDED — Performance reviewer APPROVE round 2 |
| **Dry-run on operator's actual data** | ✅ Done — `migration-dry-run.log` shows 63 tables / 1,323,393 rows total (committed at `a185009`) |
| `SYNC_THREAD_ENABLED=false` feature flag | LANDED — `4e810d4` |
| **NSSM stop ArcisWatchLoop** | OPERATOR ACTION |
| **Live migration execution** | OPERATOR ACTION (~30-90 sec wall-clock estimate) |
| **NSSM env update**: add `DATABASE_URL=postgresql://halcyon:<pwd>@localhost:5433/halcyon` + `SYNC_THREAD_ENABLED=false` | OPERATOR ACTION (admin elevation required) |
| **NSSM start ArcisWatchLoop** | OPERATOR ACTION |
| Verify watch loop writes hit PG (psql query) | OPERATOR ACTION (verification) |

### Operator runbook for Wave 4 (post-merge)

1. **Stop the watch loop**:
   ```powershell
   nssm stop ArcisWatchLoop
   ```
2. **Run the migration** (read-only on SQLite source; writes to Docker PG):
   ```powershell
   $env:DATABASE_URL = (Select-String -Path .env -Pattern '^DOCKER_PG_PASSWORD=' | ForEach-Object { "postgresql://halcyon:$(($_ -split '=', 2)[1])@localhost:5433/halcyon" })
   python scripts/sqlite_to_pg_migrate.py --dry-run    # final sanity check
   python scripts/sqlite_to_pg_migrate.py              # live execute
   ```
3. **Update NSSM service env** (admin shell required):
   ```powershell
   # Snapshot current env first
   nssm get ArcisWatchLoop AppEnvironmentExtra > docs/audits/2026-05-10-cloudflare-tunnel-cutover/nssm-env-pre-cutover.txt
   nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 DATABASE_URL=postgresql://halcyon:<pwd-from-env>@localhost:5433/halcyon SYNC_THREAD_ENABLED=false
   ```
4. **Restart the watch loop**:
   ```powershell
   nssm start ArcisWatchLoop
   Start-Sleep -Seconds 30
   Get-Content C:/arcis/logs/arcis.log -Tail 100   # verify clean startup
   Get-Content C:/arcis/data/watchdog.txt          # verify recent timestamp
   ```
5. **Verify writes hit PG**:
   ```bash
   psql $DATABASE_URL -c "SELECT count(*) FROM scan_metrics WHERE created_at > NOW() - INTERVAL '5 minutes'"
   # Expect non-zero within one watch cycle
   ```

### Rollback (if Step 4 startup is broken)

```powershell
nssm stop ArcisWatchLoop
nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3
# Drops DATABASE_URL — connect_db falls back to SQLite path; sync thread re-enables
nssm start ArcisWatchLoop
```

## Wave 5 — Training-readiness verification ✅

| Item | Commit | Reviewer Verdict |
|---|---|---|
| `scripts/verify_training_readiness.py` + 4 tests | `cd516bc` (merge) | QA APPROVE |

Live verification (`python scripts/verify_training_readiness.py` on operator's RTX 3090) is post-merge OPERATOR ACTION.

## Operator action checklist (consolidated)

After PR review + merge, operator runs in order:

- [ ] **Wave 3 browser smoke test** — visit `https://halcyonlab.app`, complete 6-page checklist at `docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-smoke-test-checklist.md`, paste results into `wave-3-receipt.md`, commit
- [ ] **Wave 4 step 1**: `nssm stop ArcisWatchLoop`
- [ ] **Wave 4 step 2**: live migration (~30-90 sec)
- [ ] **Wave 4 step 3**: NSSM env update (admin shell)
- [ ] **Wave 4 step 4**: `nssm start ArcisWatchLoop`; verify watchdog + arcis.log clean
- [ ] **Wave 4 step 5**: psql verify writes hit PG
- [ ] **Wave 5 live verification**: `python scripts/verify_training_readiness.py` on the RTX 3090 — expect `READINESS: PASS`
- [ ] **Render decommission**: delete `halcyon-api` + `halcyon-frontend` services from Render dashboard; cleanup stale CNAMEs (`api`, `www`); calendar reminder for 2026-05-17 PG retention disposal

## Test counts

- Pre-cutover floor: **4995** (Sprint 4 close)
- New tests added in this PR: **+16** (T1: 4, T2: 6, T3: 2, T6: 4)
- Post-merge floor target: **≥5005** (operator runs full sweep on machine with .env to confirm; CLAUDE.md test-floor bump deferred to a follow-up commit)

Note: pre-existing test failures observed during development (per multiple agents' receipts):
- 3 `test_repo_structure.py` failures (file/function size + TODO format) — pre-existing on `80d882e`; tracked in SP5 inventory at `docs/audits/2026-05-08-sprint-5-final-cleanup/sp5-scope-inventory.md` §B
- ~6 `test_projections_*` auth-mismatch failures — pre-existing
- `test_walkforward.py::test_all_folds_produce_trades` makes a live FRED API call without mock — pre-existing CLAUDE.md "mock all external APIs" violation; should be fixed in a follow-up

## Branch state at PR open

15 commits ahead of `main`:

```
a185009 docs(cutover): commit migration dry-run log (force-add over .log gitignore)
d8a0cf6 merge T2-rev: perf optimizations on sqlite_to_pg_migrate.py (Wave 4.1)
3dbb943 perf(wave4.1): apply 3 performance optimizations to sqlite_to_pg_migrate.py
df728af feat(wave2.1): engine-aware connect_db shim — dual SQLite/Postgres dispatch
80d882e merge T2: sqlite_to_pg_migrate.py one-shot migration script (Wave 4.1)
4e810d4 merge T3: SYNC_THREAD_ENABLED feature flag (Wave 4.2)
a19a574 feat(wave4.2): add SYNC_THREAD_ENABLED env-var feature flag to short-circuit start_render_sync
10869c2 feat(wave4.1): add sqlite_to_pg_migrate.py one-shot data migration script
3141f0c docs(cutover): Wave 3 smoke-test checklist, Render decommission runbook, and receipt template
cd516bc merge T6: verify_training_readiness.py + tests (Wave 5.1)
d62645c feat(wave5.1): add verify_training_readiness.py — post-3090-upgrade trainer preflight
c8fa289 docs(changelog): Wave 1 cutover entry under [Unreleased]
3ae79d8 feat(infra): docker-compose Postgres 16 + auth-gated local FastAPI
d2d0fdc chore(audits): add SP3 visual-verify + SP5 scope inventory to history
c65fa19 feat(train): switch to Transformers+PEFT+TRL trainer (post-3090-upgrade)
18366bb spec(cutover): Cloudflare Tunnel + Modified-A migration plan (2026-05-10)
```
