# Wave 3 — Render Decommission Runbook

**Date:** 2026-05-10  
**Branch:** `cutover/cloudflare-tunnel-modified-a-2026-05-10`  
**Operator action required:** All steps in this runbook are operator-only. Do not execute
Render deletion until §1 pre-checks are complete.

---

## §1 Pre-deletion checklist

Run through each item in order. Do not proceed to §2 until all three are confirmed.

| # | Check | Done |
|---|-------|------|
| 1 | Browser smoke test in `wave-3-smoke-test-checklist.md` fully passed (all 6 pages `[x]`) | `[ ]` |
| 2 | Render PG snapshot exists at `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (pre-flight §0.4) | `[ ]` |
| 3 | Local SQLite snapshot exists at `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (pre-flight §0.5) | `[ ]` |

Cold-backup window: 7 days from 2026-05-10, expiring **2026-05-17**. The Render PG instance
must remain alive until that date per §6 below.

---

## §2 Render dashboard — delete API and frontend services

Steps performed in the Render web dashboard (`https://dashboard.render.com`):

1. Navigate to **Services** → select `halcyon-api`.
2. Open **Settings** → scroll to the bottom → click **Delete Service**.
3. Confirm the deletion prompt (Render requires you to type the service name).
4. Navigate to **Services** → select `halcyon-frontend`.
5. Open **Settings** → scroll to the bottom → click **Delete Service**.
6. Confirm the deletion prompt.

**Do NOT delete the Render Postgres instance** — leave it alive until 2026-05-17 as a cold
backup. See §6 for the retention schedule.

---

## §3 DNS cleanup

After deleting the two Render services, audit any Cloudflare zone CNAME records that pointed
at those services. The operator performs this audit:

```bash
# Check for stale CNAME records pointing at Render hostnames
dig CNAME halcyon-api.onrender.com
dig CNAME halcyon-frontend-3ioh.onrender.com
```

Open the Cloudflare dashboard → **DNS** for the `halcyonlab.app` zone and look for any CNAME
records whose target includes `onrender.com`.

**Operator decision point:** For each such record found:
- If the CNAME was used to route traffic to Render (e.g. `api.halcyonlab.app → halcyon-api.onrender.com`), it can be deleted — `halcyonlab.app` now routes through the tunnel.
- If uncertain, leave it in place and document in `wave-3-receipt.md §4`.

The primary `halcyonlab.app` A/CNAME record now points at the Cloudflare Tunnel; Render
hostnames are no longer in the traffic path.

---

## §4 Verification post-deletion

After both Render services are deleted, run these two probes:

### 4a. Confirm Render API is gone

```bash
curl -v https://halcyon-api.onrender.com/healthz
```

Expected: `404 Not Found` or DNS `NXDOMAIN`. A `200` means the service was not deleted.

### 4b. Confirm halcyonlab.app is still live (tunnel health check)

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" \
  https://halcyonlab.app/healthz
```

Expected: `{"status":"ok"}` with `HTTP_STATUS:200`.

> **Note on User-Agent header:** Cloudflare Bot Fight Mode blocks requests with default Python
> UA strings (returns 1010 challenge). The Chrome UA above is required for automated curl
> probes. This applies to the auth-gated `/api/system/build-score` endpoint too.

For the auth-gated build-score endpoint (requires `API_SECRET` from `.env`):

```bash
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" \
  -H "Authorization: Bearer $API_SECRET" \
  https://halcyonlab.app/api/system/build-score
```

Expected: JSON response with HTTP 200.

### PM-verified tunnel health (pre-deletion baseline)

The following curl was run by the PM agent during Wave 3 documentation (2026-05-10):

```
$ curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ..." \
    https://halcyonlab.app/healthz

{"status":"ok"}
HTTP_STATUS:200
```

Tunnel was healthy at time of documentation. Re-run §4b after deletion to confirm it remains so.

---

## §5 Rollback window

| Scenario | Action |
|----------|--------|
| Within 7 days, need Render API back | Re-deploy `halcyon-api` from the same git repo via `git push render` (Render re-provisions in ~10 min); restore `VITE_API_URL` on the frontend Render service |
| Within 7 days, need data from Render PG | `psql $RENDER_DATABASE_URL` — instance is still alive until 2026-05-17 |
| After 2026-05-17, need Render PG data | Restore from `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` into a local PG instance |

If the tunnel becomes unavailable (e.g. Cloudflare config error):

1. In Cloudflare Zero Trust → Networks → Tunnels → tunnel `f6f41208…` → Public Hostnames — verify the `halcyonlab.app → http://localhost:8000` rule exists.
2. Run `nssm status cloudflared` to confirm the tunnel daemon is running.
3. If the Render API service was not yet deleted, temporarily update the Cloudflare hostname rule to point back at `halcyon-api.onrender.com` while debugging.

---

## §6 Render PG retention schedule

The Render Postgres instance must remain alive until **2026-05-17** (7-day cold-backup window).

**Action required:** Create a calendar reminder for 2026-05-17 with the note:

> "Delete Render Postgres instance — cold backup window has expired.
> Confirm local PG (Docker) is the sole store before deletion.
> Snapshot at: `C:/arcis/data/render-pg-snapshot-2026-05-10.sql`"

On 2026-05-17: navigate to Render dashboard → Databases → select the Render Postgres instance
→ Settings → Delete. This is the final Render resource removal.
