# Sprint 4B: Dashboard Logic & Build Score

**Status:** Complete
**Date:** 2026-03-30

## Summary

Sprint 4B adds the Build Score composite KPI, integrates it into the
dashboard and health pages, adds income-statement columns to the Shadow
Ledger, improves the Council page, wires secrets through `.env`, and
creates the `build_score_history` database table with Render sync.

## Tasks Completed

### Task 1 -- Build Score Computation Module
- Created `src/evaluation/build_score.py` (< 400 lines)
- Six components via geometric mean: gate_velocity, system_health,
  data_asset_value, model_quality, research_velocity, reliability
- Daily idle-day decay (-1 point)
- `compute_build_score()` returns full API response shape
- `persist_build_score()` saves to `build_score_history` table

### Task 2 -- API Endpoint
- Added `GET /api/build-score` to `analytics.py` cloud routes
- Added `api.getBuildScore()` to frontend `api.js`

### Task 3 -- Dashboard Main Page (The Glance)
- Added `BuildScoreHero` component: large score, 7d delta, decay badge,
  6 component progress bars, 7-day sparkline, phase progress
- Fetches from `/api/build-score` with 120s refetch interval

### Task 4 -- ShadowLedger IS Columns
- Added to closed-trade table: Slip (bps), R-Multiple columns
- Added to expanded trade detail: Entry Slippage, Slippage bps,
  R-Multiple with color coding, IS Capture percentage
- Added aggregate metrics: Avg Slippage (bps), Avg R-Multiple
- Helper functions: `computeRMultiple()`, `computeIsCapture()`

### Task 5 -- Council Page Redesign
- Added Council Summary section (teal-tinted card with summary text)
- Added Cost column to consensus header (3-column: Confidence, Rounds, Cost)

### Task 6 -- Health Page Build Score Integration
- Added full Build Score hero section above HSHS
- Component breakdown with progress bars
- 7-day trend sparkline
- Data asset detail (Quality, Diversity, Freshness)
- Phase gate progress indicator

### Task 7 -- Render Sync + DB Tables
- Added `build_score_history` CREATE TABLE to `scripts/create_missing_tables.py`
- Added `build_score_history` to `SYNC_TABLES` in `src/sync/render_sync.py`
- Added CREATE TABLE and index migrations to `scripts/render_migrate.py`

### Task 8 -- Wire Secrets Through .env
- Added `python-dotenv` to `requirements.txt`
- Added `load_dotenv()` to `src/main.py` and `src/scheduler/watch.py`
- Created `.env.example` with all required environment variables

## Files Changed

| File | Action |
|------|--------|
| `src/evaluation/build_score.py` | Created |
| `src/api/cloud_routes/analytics.py` | Modified (added endpoint) |
| `frontend/src/api.js` | Modified (added getBuildScore) |
| `frontend/src/pages/Dashboard.jsx` | Rewritten (Build Score hero) |
| `frontend/src/pages/ShadowLedger.jsx` | Rewritten (IS columns) |
| `frontend/src/pages/Council.jsx` | Modified (summary + cost) |
| `frontend/src/pages/Health.jsx` | Rewritten (Build Score integration) |
| `scripts/create_missing_tables.py` | Modified (build_score_history) |
| `scripts/render_migrate.py` | Modified (build_score_history) |
| `src/sync/render_sync.py` | Modified (build_score_history) |
| `requirements.txt` | Modified (python-dotenv) |
| `src/main.py` | Modified (load_dotenv) |
| `src/scheduler/watch.py` | Modified (load_dotenv) |
| `.env.example` | Created |
| `docs/sprints/sprint-4b-dashboard-logic.md` | Created |

## Pre-existing Violations

File-length and function-length violations listed below are **pre-existing**
from prior sprints. No new violations were introduced in Sprint 4B.

- `build_score.py`: 302 lines (under 400-line limit)
- All new frontend pages remain under their respective limits

## Sprint 4A Status

Sprint 4A was **partially completed**: fonts, CSS design tokens, and
Layout.jsx are present. The Arcis rename and ThemeToggle were not
implemented. Sprint 4B adapted to use existing CSS variable names
(--teal-*, --slate-*) and kept "HALCYON LAB" branding.
