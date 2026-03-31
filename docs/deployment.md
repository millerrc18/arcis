# Arcis — Render Deployment Guide

This guide documents the current Render deployment path for the read-only cloud dashboard. The local machine remains the source of truth for trading, training, and data collection; Render hosts the remote frontend, API, and Postgres mirror.

## What Gets Deployed

`render.yaml` defines two cloud services:

- `halcyon-frontend` — static Vite build served from `frontend/dist`
- `halcyon-api` — FastAPI app served from `src.api.cloud_app:app`

The Postgres database is created separately in Render and wired into the API through `DATABASE_URL`.

## Prerequisites

- A Render account connected to the GitHub repository
- A local Arcis instance with a populated SQLite database
- `DATABASE_URL` from the Render Postgres instance
- A local Python environment with project dependencies installed

## Step 1: Create the Render Postgres Database

1. In Render, create a PostgreSQL database for Arcis.
2. Copy the **external** connection string for running migrations from your local machine.
3. Copy the **internal** connection string if you also want to compare it against the API service config later.

## Step 2: Deploy the Blueprint

1. In Render, create a new Blueprint deployment from this repository.
2. Confirm the services match `render.yaml`:
   - `halcyon-frontend`
   - `halcyon-api`
3. Set these environment variables on the API service:
   - `DATABASE_URL`
   - `API_SECRET`
4. Set these environment variables on the frontend service:
   - `VITE_API_URL`
   - `VITE_IS_CLOUD=true`

`VITE_API_URL` should usually point to the API service URL plus `/api`, for example:

```text
https://halcyon-api.onrender.com/api
```

## Step 3: Bootstrap or Repair the Render Schema

The current Postgres bootstrap path is `scripts/render_migrate.py`. It is safe to rerun.

```bash
# Windows PowerShell
$env:DATABASE_URL = "postgresql://..."
.venv\Scripts\python.exe scripts/render_migrate.py

# macOS / Linux
export DATABASE_URL="postgresql://..."
.venv/Scripts/python.exe scripts/render_migrate.py
```

This script creates missing synced tables and applies additive schema fixes so Render Postgres matches the live sync contract used by `src/sync/render_sync.py`.

## Step 4: Configure Local Render Sync

Render sync is controlled through the `render:` section in `config/settings.local.yaml`:

```yaml
render:
  enabled: true
  database_url: "postgresql://user:pass@host:5432/halcyon"
  sync_interval_seconds: 120
```

The watch loop starts the Render sync thread automatically when `render.enabled` is true and a `database_url` is configured.

## Step 5: Start the Local Watch Loop

```bash
python -m src.main watch --email-mode daily_summary --overnight
```

During the watch loop, `src/sync/render_sync.py` pushes incremental, latest-only, and full-sync tables into Render Postgres on the configured interval.

## Step 6: Verify the Cloud Surface

Check the following endpoints after the sync thread has had time to push data:

- `GET /healthz`
- `GET /api/status`
- `GET /api/diagnostics`

`/api/diagnostics` is the best first check because it validates every configured Render-synced table, including newer surfaces like:

- `validation_results`
- `traffic_light_state`
- `council_parameter_state`
- `user_notes`

## Authentication Behavior

When `API_SECRET` is set on the API service:

- every protected API route requires `Authorization: Bearer <token>`
- the frontend AuthGate prompts for the same secret
- the token is stored in `localStorage`
- the browser session remains valid for up to **7 days**
- a `401` clears the local session and forces a fresh sign-in

If `API_SECRET` is unset, the API allows unauthenticated access and logs a warning at startup. That is convenient for local debugging and unsafe for public deployment.

## Troubleshooting

### The frontend loads but data is empty

- Confirm the local watch loop is running
- Confirm `render.enabled: true` locally
- Confirm the local config points to the correct Render Postgres URL
- Call `/api/diagnostics` and inspect `failed_tables`

### The API starts but reports database errors

- Re-check the Render `DATABASE_URL`
- Rerun `scripts/render_migrate.py`
- Confirm the API service can reach the Render Postgres instance

### New tables are missing in cloud

- Verify they are listed in `src/sync/render_sync.py`
- Verify the local database actually contains the table
- Rerun `scripts/render_migrate.py`
- Re-check `/api/diagnostics`

### Auth keeps expiring unexpectedly

- Confirm the API and frontend are pointing at the same deployment
- Clear `localStorage` and sign in again
- Verify `API_SECRET` is set only on the API service, not accidentally baked into the frontend config

## Deployment Model

The cloud deployment is intentionally read-only:

- local machine: source of truth for scans, broker execution, training, and data collection
- Render Postgres: synced mirror for remote observability
- Render API + frontend: remote dashboard for monitoring and review

```text
Local SQLite + Watch Loop  -->  Render Postgres  -->  FastAPI + React dashboard
```
