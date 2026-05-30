# Render Decommission Runbook

**Status:** READY TO EXECUTE (operator-paced; runbook authored 2026-05-10 after Cloudflare Tunnel cutover)
**Pre-condition:** PR #1047 (Cloudflare Tunnel + Modified-A) merged. Tunnel serving `https://halcyonlab.app` end-to-end. ArcisDashboard NSSM service stable for ≥24h.
**Pre-condition:** Local SQLite at `C:/arcis/data/ai_research_desk.sqlite3` is the production write target. Render PG receives no live writes (sync paused since cutover).

---

## What gets decommissioned

| Resource | Render service name | Role pre-cutover | Role post-cutover |
|---|---|---|---|
| Web service | `arcis-api` (or equivalent) | Served `cloud_app.py` FastAPI at `arcis-api.onrender.com` | Replaced by Cloudflare Tunnel → local `ArcisDashboard` NSSM service |
| Managed Postgres | `arcis-pg` (or equivalent) | Cloud mirror of local SQLite via `render_sync.py` | Frozen snapshot taken; replaced (long-term) by local Docker PG once Modified-A migration completes |

**Domain:** `halcyonlab.app` apex `A 216.24.57.1` Render record has already been deleted by the operator (Wave 1 step). DNS now resolves through Cloudflare to the tunnel. No DNS work needed during decommission.

---

## Cost savings

| Service | Tier | Monthly cost |
|---|---|---|
| Render web (Standard) | $7-$25/mo depending on instance class | ~$7/mo |
| Render Postgres (Standard) | $7-$95/mo depending on storage | ~$15-$20/mo for ~1 GB tier |
| **Total savings** | | **~$22-$30/mo (~$260-$360/year)** |

Verify current tier in the Render dashboard before disabling. If on a higher tier than estimated, savings increase proportionally.

---

## Pre-flight checklist

Run all checks 24h before disabling. Re-run immediately before each disable step.

| Check | Command / location | Expected |
|---|---|---|
| Tunnel healthcheck | `curl -s -o NUL -w "%{http_code}" https://halcyonlab.app/healthz` | `200` |
| Auth-gated endpoint | `curl -H "Authorization: Bearer $API_SECRET" https://halcyonlab.app/api/status` | `200` with JSON |
| ArcisDashboard NSSM status | `nssm status ArcisDashboard` | `SERVICE_RUNNING` |
| ArcisWatchLoop NSSM status | `nssm status ArcisWatchLoop` | `SERVICE_RUNNING` |
| Local SQLite size | `Get-Item C:\arcis\data\ai_research_desk.sqlite3 \| select Length` | Growing steadily (recent activity) |
| Render snapshot present | `Test-Path C:\arcis\data\render-pg-snapshot-2026-05-10.sql` | `True` (478 MB) |
| Cloudflare DNS not pointing to Render | `nslookup halcyonlab.app` | Returns Cloudflare IPs (104.x / 172.x), NOT `216.24.57.1` |
| Render sync NOT running | `Get-Process python \| Where-Object { $_.CommandLine -like '*render_sync*' }` | empty (no process) |

If ANY check fails, do not proceed. Investigate and fix the root cause first.

---

## Decommission sequence

### Phase 1: Disable Render web service (DAY 0)

**Goal:** Stop serving traffic from `arcis-api.onrender.com`. Keep configuration so re-enabling is one click.

1. Log into Render dashboard → select `arcis-api` (or current web service name)
2. **Settings → Suspend** (do NOT delete; suspension is reversible, deletion isn't for free-tier services)
3. Verify in dashboard: service shows status `Suspended`
4. Smoke-test that traffic still flows through the tunnel:
   ```powershell
   curl -s https://halcyonlab.app/healthz                                                  # → 200
   curl -s -H "Authorization: Bearer $env:API_SECRET" https://halcyonlab.app/api/status    # → 200 JSON
   ```
5. Wait 30 min. Re-check both above. If still 200, Phase 1 complete.

**What changes for clients:** nothing. Cloudflare Tunnel was already serving 100% of traffic; the Render service was inert (no DNS pointing to it).

**Rollback (within Phase 1):** un-suspend the Render service. <2 min restore.

---

### Phase 2: Disable Render Postgres (DAY 0 + 30 min)

**Goal:** Stop the PG instance billing without dropping the database. Snapshot already exists locally; this just stops the instance.

1. **Verify snapshot integrity first:**
   ```powershell
   pg_dump --version    # confirm pg_dump 16.x or compatible installed
   # Spot-check the snapshot file: header should mention PostgreSQL version + the schema dump
   Get-Content C:\arcis\data\render-pg-snapshot-2026-05-10.sql -TotalCount 30
   ```
   If the snapshot file is missing, corrupted, or zero-byte → ABORT. Re-take a fresh dump via `pg_dump` against the live Render PG before suspending.

2. Render dashboard → `arcis-pg` → **Settings → Suspend**

3. Verify in dashboard: status `Suspended`. The dashboard will display "Last available backup" — note this timestamp.

4. **What changes:** the cloud_routes/* read paths (kpis, status, walkforward) in the FastAPI app will fail any DB query that routes to Render. **Verify they DON'T route to Render anymore** — the Wave 1 work moved them to the SQLite path. Spot-check:
   ```powershell
   curl -s -H "Authorization: Bearer $env:API_SECRET" https://halcyonlab.app/api/kpis | ConvertFrom-Json | Select-Object _meta
   ```
   `_meta.source` should be `sqlite` or `local`, NOT `postgres-render`.

**Rollback (within Phase 2):** un-suspend Render PG. ~5 min to come back online. The local SQLite snapshot + Docker PG snapshot remain authoritative; nothing depends on Render PG in the live read path.

---

### Phase 3: 7-day grace period (DAY 0 → DAY 7)

**Goal:** Observability window. Confirm zero functional regressions before final deletion.

**Daily checks (automate or manual):**
- `curl https://halcyonlab.app/healthz` → 200
- Dashboard renders all sections (visual-verify at least once per day during this window)
- No `RuntimeError` / `OperationalError` in `C:\arcis\logs\arcis.log` referencing `render-pg` or `arcis-api.onrender.com`
- Trading + corpus generation proceed normally (NSSM ArcisWatchLoop alive)

**End-of-grace-period checklist (DAY 7):**
- [ ] Zero render-related errors in logs
- [ ] Dashboard visually identical to pre-decommission baseline
- [ ] At least one auth-rotation cycle completed without Render dependency
- [ ] Operator green-lights final deletion

If ANY check fails, un-suspend the Render service to debug. Reset the grace period to DAY 0 on resumption.

---

### Phase 4: Final deletion (DAY 7+)

**Goal:** Free the Render account and reduce attack surface.

1. **Final snapshot refresh** (in case Render had any drift during grace period — unlikely but cheap to verify):
   ```powershell
   pg_dump $env:RENDER_PG_URL --no-owner --no-acl -F p -f C:\arcis\data\render-pg-snapshot-final-$(Get-Date -Format yyyy-MM-dd).sql
   ```
   This is read-only; no risk to a suspended instance after un-suspend.

2. Render dashboard → `arcis-api` → **Settings → Delete service**. Render will require typing the service name to confirm.

3. Render dashboard → `arcis-pg` → **Settings → Delete service**. Same confirmation.

4. Update the operator guide and CHANGELOG:
   - `docs/operator-guide.md`: remove any "Render dashboard URL" / "Render PG password rotation" sections
   - `CHANGELOG.md` `[Unreleased]`: add a `### Removed` line: `Render web service and Postgres mirror — replaced by Cloudflare Tunnel + local Docker PG (decommissioned YYYY-MM-DD)`

5. Update `config/settings.local.yaml` and `.env.example` to remove `RENDER_PG_URL`, `RENDER_API_KEY`, etc.

6. Run schema-validation to confirm nothing in the registry still references Render:
   ```bash
   python -m src.main validate-schema
   ```

---

## Rollback flowchart

```
                  ┌─────────────────────┐
                  │  Issue detected at  │
                  │  any phase?         │
                  └──────────┬──────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
       Phase 1 or 2                   Phase 3 or 4
       (un-suspend)                   (more involved)
              │                             │
              │                       ┌─────┴─────────────┐
              │                       │ Restore from      │
              │                       │ snapshot to a new │
              │                       │ Render PG instance│
              │                       │ (~30 min)         │
              │                       └─────┬─────────────┘
              │                             │
              ▼                             ▼
       Resume normal              Update connection
       operation                  strings + smoke-test
       (~2 min restore)           tunnel still works
```

**Restore from snapshot (worst case, post-deletion):**
```powershell
# Create a new Postgres instance on Render (or elsewhere)
# Then:
psql $env:NEW_PG_URL -f C:\arcis\data\render-pg-snapshot-final-YYYY-MM-DD.sql
# Update src/sync/render_sync.py + cloud_routes/*.py DATABASE_URL env vars
# Restart ArcisDashboard NSSM service
```

This is the nuclear-option restore. It rebuilds a full PG mirror from the snapshot file. Not needed in normal operation; documented for completeness.

---

## Decision points the operator owns

| Question | Default | Adjust if... |
|---|---|---|
| Disable now or wait? | Now — tunnel is stable, snapshot is fresh | Recent infrastructure changes haven't soaked yet |
| Grace period length | 7 days | Major trading event coming up — extend to 14 |
| Keep snapshot after deletion? | Yes, indefinitely (C:/arcis/data/) | Disk pressure on the C: drive; offload to external |
| Re-enable IF/WHEN Sprint 5 §J6 migration fails? | No — local Docker PG is the migration target. Render PG is decommissioned regardless of Sprint 5 outcome | n/a |

---

## What this runbook does NOT cover

- **The Modified-A write-side migration itself.** That's Sprint 5 §J5/§J6 scope. The Render decommission is independent — it removes the cloud mirror; the local-write switch from SQLite to Docker PG is a separate workstream.
- **Cloudflare Tunnel maintenance.** See `docs/operations/cloudflare-tunnel.md` (TODO; not yet written).
- **NSSM service management.** See memory `reference_watch_loop_management`: restart via `nssm restart <svc>`, never `python -m src.main startup` directly.
- **API_SECRET rotation.** Independent procedure; rotates Frontend `VITE_API_SECRET` + backend `API_SECRET` in lockstep. Not affected by this decommission.

---

## Related artifacts

- Snapshot: `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB, taken 2026-05-10 pre-cutover)
- Original cutover spec: `docs/audits/2026-05-10-cloudflare-tunnel-cutover/spec.md`
- Cutover receipt: `docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-1-receipt.md`
- Cutover rollback record: commits `344e5e6` → `ed1757c` → `449dfc0` on `main`
- SQLite-isms prelim audit (input for Sprint 5 design): `docs/audits/2026-05-10-cloudflare-tunnel-cutover/sqlite-isms-prelim-audit.md`
- This runbook: `docs/operations/render-decommission.md`

---

## Phase 4 receipt (2026-05-27)

Render code sweep landed in Phase 5 PR-B (#73). The cloud_app FastAPI entry, Render deployment manifest, requirements, and DB-init helper are gone; the cloud_routes/ modules no longer gate on DATABASE_URL (single-mode SQLite). 7 tier-2 tests redirected to `src/api/app.py`; 2 tier-2 tests with heavy cloud_app-internal patches deleted with rewrite kins (#10, #11). 2 regression-lock sentinels (`tests/test_cloud_app_removed.py` + `tests/test_no_database_url_branch.py`) enforce no-reintroduction.

### Commits

| Commit | Task | Description |
|---|---|---|
| `b7984155` | T4 | delete cloud_app.py + render.yaml + requirements-cloud.txt + scripts/render_init_db.py |
| `c2f7c4de` | T4b | delete dedicated cloud_app test suite + check_cloud_deploy_imports.py + structure-test fn (2233L) |
| `fa95d4a7` | T4c | redirect 7 tier-2 tests + render_architecture_doc.py to src.api.app |
| `b7c2d1ff` | T4d | delete 2 tier-2 tests with heavy cloud_app patches (kin #10, #11) |
| `2abe0fcb` | T6 | strip DATABASE_URL batch 1 (platform, broker_exceptions, commands, kpis_compute) |
| `bdde5cf9` | T7 | strip DATABASE_URL batch 2 (notifications, preflight, walkforward) + __init__ docstring |
| `7d708598` | T8 | add 2 regression-lock sentinels (test_cloud_app_removed + test_no_database_url_branch) |
| `<this commit>` | T9 | CHANGELOG entries + this receipt |

### Two-step rollback protocol (per Phase 5 §3.4)

If post-merge regression appears that traces to PR-B:

1. **Revert the merge commit on `main`**:
   ```bash
   git revert -m 1 <PR-B-merge-sha>
   git push origin main
   ```
   This restores cloud_app.py + cloud_routes DATABASE_URL branches in one step. Watch-loop and dashboard processes can be restarted to pick up the reverted code.

2. **Re-delete the sentinel commit** (separate step to keep history clean):
   The sentinels (`tests/test_cloud_app_removed.py` + `tests/test_no_database_url_branch.py`) will FAIL once cloud_app.py is restored — that's the regression-lock working as intended. Delete the sentinel files in a follow-up commit:
   ```bash
   git rm tests/test_cloud_app_removed.py tests/test_no_database_url_branch.py
   git commit -m "rollback: remove PR-B sentinels (companion to PR-B revert)"
   git push origin main
   ```

The two-step structure (revert + sentinel-delete in separate companion commit, per DA6) is required because step 1 alone leaves the test suite RED — the sentinels would assert "cloud_app should be gone" but cloud_app is back. The companion deletion clears the contradiction.

### Skipped sub-tasks

- T5 (delete `scripts/render_to_local_migrate.py`) — deferred to dedicated PR per kin #13. Script houses load-bearing `apply_ownership_reconciliation` function (the 2026-05-14 incident fix). Proper migration: move the function to `scripts/_shared_migration_utils.py`, update dependent tests, then delete the script.

### Verification

- All 7 cloud_routes modules: `grep DATABASE_URL src/api/cloud_routes/` → 0 hits
- All cloud_app references in tests/scripts (excl. 1 historical comment): `git grep src.api.cloud_app tests/ scripts/` → 0 hits in tests/, 1 in scripts/close_triage_bundle_issues.sh:42 (historical issue #598 context, intentionally preserved)
- Test floor: 7007 → ~6870 (delta -137; well above 5,467 floor)
- Regression-lock sentinels PASS with verify-by-mutation evidence (sabotage cycles documented in T8 commit body)

### Kins filed during PR-B execution

- #9: PLAN GAP T4 — cloud_app deletion required broader cleanup than original scope_fence allowed
- #10: rewrite tests/api/test_status.py using src.api.app
- #11: rewrite tests/test_shadow_desk_filter.py using src.api.app
- #12: test_route_excludes_operator_confirm_rows hardcoded-timestamp flake (unrelated, surfaced during T4c)
- #13: PLAN GAP T5 — render_to_local_migrate.py proper-expansion deletion

---

## Phase 4 — Decommission Complete (closeout 2026-05-29, PR-F T35)

This runbook is now **CLOSED**. All four decommission phases described above are complete; the Render web service and Postgres mirror no longer exist and nothing in the live system references them. This closeout receipt is the operational counterpart to the PR-B code-sweep receipt above (which removed the Render-facing *code*); together they confirm both the infrastructure and the codebase are fully Render-free.

### Status by phase

| Phase | What it covered | Status |
|---|---|---|
| Phase 1 | Suspend Render web service (`arcis-api`) | DONE — superseded by Cloudflare Tunnel since the 2026-05-10 cutover (PR #1047); Render traffic path was already inert |
| Phase 2 | Suspend Render Postgres (`arcis-pg`) | DONE — live read paths (`cloud_routes/*`) serve from local SQLite; Render PG received no live writes post-cutover |
| Phase 3 | 7-day grace observability window | DONE — `api_render_connection` / `api_render_config` / `api_cloud_healthz` validator probes were gutted in v0.36.39 (2026-05-20) precisely because the Render services were confirmed gone; expected-FAIL probes are documented as offline in operator memory (`project_render_resources_stopped`, 2026-05-18) |
| Phase 4 | Final deletion + config cleanup | DONE — Render account resources stopped/offline (operator, 2026-05-18); the last Render-facing code (`cloud_app.py`, `render.yaml`, `requirements-cloud.txt`, `scripts/render_init_db.py`, `DATABASE_URL` gating across `cloud_routes/*`) removed in Phase 5 PR-B (#73) |

### What confirms completion

- **Code side (PR-B, #73):** `src/api/cloud_app.py`, `render.yaml`, `requirements-cloud.txt`, `scripts/render_init_db.py` deleted; all 7 `cloud_routes/*` modules SQLite-only (no `DATABASE_URL` gating). Two regression-lock sentinels (`tests/test_cloud_app_removed.py`, `tests/test_no_database_url_branch.py`) prevent reintroduction. See the PR-B receipt above and the `## [v0.36.78]` → `### PR-B` CHANGELOG block.
- **Validator side (v0.36.39, 2026-05-20):** `src/evaluation/system_validator.py` Render checks removed — there is no longer any live probe that expects a Render endpoint to answer.
- **Operator side (2026-05-18):** Render Postgres + cloud_app + frontend intentionally taken offline post-cutover. Any residual `api_render_connection` FAIL is expected, not an alarm (operator memory `project_render_resources_stopped`).

### Residual / not-in-this-runbook

- **`scripts/render_to_local_migrate.py`** is intentionally retained (NOT a live Render dependency): it houses the load-bearing `apply_ownership_reconciliation` function from the 2026-05-14 incident fix. Its deletion is tracked separately under PR-B kin #13 (proper-expansion move to a shared utils module first). This is a code-hygiene follow-up, not a decommission gap.
- **Snapshot retention:** `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB) is kept indefinitely per the operator decision in the "Decision points" table above. It is the nuclear-option restore source and depends on nothing live.
