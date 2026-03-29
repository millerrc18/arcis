# Halcyon Lab — Render Deployment Guide

Step-by-step guide for deploying the Halcyon Lab cloud dashboard to Render.

## Prerequisites

- GitHub account with the halcyon-lab repository
- Render account (free tier works)
- Local Halcyon Lab instance running with populated SQLite database

## Step 1: Create Render Account + Connect GitHub

1. Sign up at [render.com](https://render.com)
2. Go to **Account Settings > Git Providers**
3. Click **Connect GitHub** and authorize Render to access your repositories
4. Select the `halcyon-lab` repository

## Step 2: Create Postgres Database

1. In the Render dashboard, click **New > PostgreSQL**
2. Configure:
   - **Name:** `halcyon-db`
   - **Database:** `halcyon`
   - **User:** `halcyon_user`
   - **Plan:** Free (90-day expiry) or Starter ($7/mo)
3. Click **Create Database**
4. Copy the **Internal Database URL** — you will need it for the API service

## Step 3: Deploy via Blueprint (render.yaml)

The repository includes a `render.yaml` Blueprint that configures both services automatically.

1. In Render dashboard, click **New > Blueprint**
2. Select the `halcyon-lab` repository
3. Render will detect `render.yaml` and show the planned resources:
   - **halcyon-frontend** — Static site (React/Vite build)
   - **halcyon-api** — Python web service (FastAPI/Uvicorn)
   - **halcyon-db** — PostgreSQL database
4. Set the `API_SECRET` environment variable when prompted (generate a random string)
5. Click **Apply** to deploy

### What the Blueprint Creates

| Service | Type | Runtime | Notes |
|---------|------|---------|-------|
| `halcyon-frontend` | Static Site | Node.js build | Serves `frontend/dist` |
| `halcyon-api` | Web Service | Python 3.11 | Read-only cloud API |
| `halcyon-db` | PostgreSQL | Managed | Free tier available |

## Step 4: Run Schema Init Script

After the database is created, initialize the Postgres schema:

```bash
# Get the external connection string from Render dashboard
# (Database > halcyon-db > External Database URL)

# Option A: Use the sync script
python -m src.sync.render_sync --init-schema

# Option B: Connect directly with psql
psql "YOUR_EXTERNAL_DATABASE_URL" -f src/sync/pg_schema.sql
```

The schema mirrors the SQLite tables needed for the read-only cloud dashboard (recommendations, shadow_trades, model_versions, metric_snapshots, etc.).

## Step 5: Configure Local Sync

The local machine pushes data to the cloud Postgres on a schedule.

1. Add the database URL to your local config (`config/settings.local.yaml`):

```yaml
cloud:
  enabled: true
  database_url: "postgresql://halcyon_user:PASSWORD@HOST:5432/halcyon"
  sync_interval_minutes: 15
```

2. The watch loop (`python -m src.main watch --overnight`) automatically syncs on the configured interval.

3. To manually trigger a sync:

```bash
python -m src.sync.render_sync --push
```

## Step 6: Verify Dashboard Loads

1. Visit your frontend URL: `https://halcyon-frontend.onrender.com`
2. Confirm the dashboard loads and shows:
   - System status on the Dashboard page
   - Open/closed trades in the Shadow Ledger
   - Model version history on the Training page
   - CTO Report with fund metrics
3. Check the API health endpoint: `https://halcyon-api.onrender.com/api/status`

## Dashboard Authentication

The cloud dashboard is protected by a password gate when `API_SECRET` is configured.

### How It Works

- Set `API_SECRET` as an environment variable on the Render API service
- The same value acts as the **dashboard password** users enter to sign in
- The frontend stores the password in `sessionStorage` (cleared when the browser tab closes)
- Sessions automatically expire after **24 hours**, requiring re-authentication
- If `API_SECRET` is empty or unset, authentication is disabled (open access)

### Setting Up

1. In the Render dashboard, go to **halcyon-api > Environment**
2. Add or update `API_SECRET` with a strong random string (e.g., `openssl rand -hex 32`)
3. On the frontend service, set `VITE_IS_CLOUD=true` so the auth gate appears
4. Redeploy both services

### Security Notes

- The password is sent as a `Bearer` token in the `Authorization` header
- All API endpoints require the token when `API_SECRET` is set
- On 401 responses, the frontend clears the session and shows the login screen

## Troubleshooting

### Frontend shows "API connection error"
- Verify `VITE_API_URL` in the frontend service matches the API service URL
- Check that the API service is running (green status in Render dashboard)

### API returns empty data
- Run `python -m src.sync.render_sync --push` locally to force a sync
- Check the Render API logs for database connection errors

### Database connection refused
- Free-tier databases expire after 90 days — check if it needs recreation
- Verify the `DATABASE_URL` env var is set correctly on the API service

### Build failures
- Frontend: Check that `frontend/package.json` has the correct build script
- API: Check `requirements-cloud.txt` for missing dependencies

## Architecture Notes

The cloud deployment is **read-only**. All trading, scanning, training, and data collection runs on the local machine. The cloud dashboard provides remote monitoring only.

```
Local Machine (RTX 3060)          Render Cloud
┌─────────────────────┐           ┌─────────────────────┐
│ SQLite DB            │──sync──> │ PostgreSQL           │
│ Ollama/halcyon-v1    │           │ halcyon-api (FastAPI)│
│ Watch loop           │           │ halcyon-frontend     │
│ Training pipeline    │           │ (React/Vite)         │
│ Data collection      │           └─────────────────────┘
│ Telegram bot         │
└─────────────────────┘
```
