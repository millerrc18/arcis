# Dashboard Fix Sprint: Implementation Plan

**Date:** April 12, 2026
**Issues cataloged:** 97 across 16 pages
**Author:** Claude (Opus 4.6), Ralph-looped 3x

---

## Root Cause Analysis

Before listing tasks, the 97 issues collapse into **6 root causes** that explain ~80% of the bugs:

### Root Cause 1: Quarantine values never synced to Render Postgres
**Issues affected:** #2, #3, #5, #11, #12, #13, #14, #34, #35, #36, #37, #38, #43, #44, #50, #66, #70
**Why:** The quarantine script runs locally and UPDATEs `shadow_trades.quarantined = 1`. But Render sync is **incremental** — it only pushes rows where `created_at > last_synced_at`. UPDATE to existing rows never reaches Postgres. The `COALESCE(quarantined, 0) = 0` filter is correct in the code but the quarantined=1 values don't exist on Postgres.
**Fix:** One-time sync of quarantine flags to Postgres + add quarantined column to the upsert conflict resolution.

### Root Cause 2: Model version detection returns "base"
**Issues affected:** #25, #41, #48, #77, #78
**Why:** `get_active_model_name()` reads from `model_versions` table. If no row is marked active, returns "base". The `model_versions` table is either empty or the active flag wasn't set when halcyon-v1.0.0 was deployed. Ollama correctly reports the model name, but the versioning system doesn't.
**Fix:** Ensure `model_versions` table has halcyon-v1.0.0 marked as active. Add fallback: if DB says "base" but Ollama is loaded, use Ollama's model name.

### Root Cause 3: Attribution logger not wired into trade flow
**Issues affected:** #45, #46, #51
**Why:** `log_attribution_before_llm()` was deployed in v0.10.0 but the executor refactoring may have disconnected the call. Zero paired trades means the before/after logging isn't firing.
**Fix:** Verify the attribution hooks in the executor are actually being called on every trade.

### Root Cause 4: Stress test displaying all runs instead of latest
**Issues affected:** #52, #53, #54, #55
**Why:** The page queries all stress_test_results rows and renders a card for each. Multiple runs produce duplicate cards.
**Fix:** Group by scenario, show only the latest run per scenario. Archive previous runs.

### Root Cause 5: No mobile responsive design
**Issues affected:** #96, #97
**Why:** Never designed for mobile — the dashboard was built desktop-first with fixed-width containers.
**Fix:** Responsive pass across all pages (separate sprint — too large to mix with bug fixes).

### Root Cause 6: Canvas rendering artifacts
**Issues affected:** #62, #64
**Why:** Architecture and DB Schema pages use a canvas/SVG library that produces glitched graphics in certain viewport sizes or browsers.
**Fix:** Investigate canvas library rendering, or replace with deterministic layout.

---

## Sprint Structure

The 97 issues split into **3 sprints** by category:

| Sprint | Name | Issues | CC Time | Priority |
|--------|------|--------|---------|----------|
| **DB-1** | Data Integrity + Quarantine Sync | #1-5, #11-14, #25, #34-44, #48, #50, #63, #66, #69, #70, #77-78, #80, #87-90 | 4-6 hrs | CRITICAL |
| **DB-2** | Bug Fixes + Feature Additions | #9-10, #15-16, #18-20, #22-24, #26-33, #45-47, #49, #51-55, #58, #65, #74-76, #82-86, #91-95 | 8-12 hrs | HIGH |
| **DB-3** | Responsive Design + Polish | #56-57, #59-62, #64, #96-97 | 6-8 hrs | MEDIUM |

---

## SPRINT DB-1: Data Integrity + Quarantine Sync

> **Branch:** `fix/dashboard-data-integrity`
> **Priority:** CRITICAL — every analytics page shows wrong numbers
> **Estimated CC time:** 4-6 hrs

### Task 1: Sync quarantine flags to Render Postgres

**Root cause fix.** The quarantine flags exist locally but never reached Postgres.

**Option A (recommended):** Add a one-time migration script + modify the sync to handle quarantine updates:

```python
# scripts/sync_quarantine_to_postgres.py
"""One-time sync of quarantine flags from local SQLite to Render Postgres."""
import os, sqlite3, psycopg2
from src.config import DB_PATH

def sync():
    local = sqlite3.connect(DB_PATH)
    local.row_factory = sqlite3.Row
    quarantined = local.execute(
        "SELECT trade_id FROM shadow_trades WHERE quarantined = 1"
    ).fetchall()
    trade_ids = [r["trade_id"] for r in quarantined]

    pg = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = pg.cursor()
    for tid in trade_ids:
        cur.execute(
            "UPDATE shadow_trades SET quarantined = 1 WHERE trade_id = %s", (tid,)
        )
    pg.commit()
    print(f"Synced {len(trade_ids)} quarantine flags to Postgres")
```

**Option B:** Change shadow_trades sync to "full" mode with upsert. More expensive but ensures future quarantine updates sync automatically.

**Recommended:** Option A for immediate fix + add quarantined to the ON CONFLICT UPDATE clause for future-proofing.

### Task 2: Fix version display in header bar

**File:** `src/services/system_service.py`

The hardcoded `"version": "v0.16.12"` needs to read from git tags or a VERSION file.

```python
# Read from CHANGELOG or git tag
import subprocess
try:
    version = subprocess.check_output(
        ["git", "describe", "--tags", "--abbrev=0"],
        stderr=subprocess.DEVNULL, text=True
    ).strip()
except Exception:
    version = "v0.16.12"  # fallback
```

### Task 3: Fix model version detection

**File:** `src/training/versioning.py`

`get_active_model_name()` returns "base" when no active model version row exists. Fix:

```python
def get_active_model_name(db_path: str = DB_PATH) -> str:
    version = get_active_model_version(db_path)
    if version:
        return version["version_name"]
    # Fallback: check what Ollama has loaded
    try:
        from src.llm.client import get_loaded_model_name
        name = get_loaded_model_name()
        if name and name != "unknown":
            return name
    except Exception:
        pass
    return "base"
```

Also: insert a row into `model_versions` for halcyon-v1.0.0 if it doesn't exist.

### Task 4: Fix table count on DB Schema page

**File:** `frontend/src/pages/DBSchema.jsx`

Hardcoded "40 tables across 6 domains" — should query the actual count from the schema API.

### Task 5: Fix Settings page system health indicators

**File:** `frontend/src/pages/Settings.jsx` or its API source

All indicators show "OFF" because they're checking cloud-side availability. Should display the last-known status from the sync'd data, or show "CLOUD" (can't check local services from Render).

### Task 6: Fix Settings page values

- Risk % Max: verify it reads from config correctly (should be 0.02)
- Timeout Days: populate from config (should be 8)
- Min Conviction Score: show "Disabled" instead of blank

### Task 7: Fix Flywheel Velocity score

**Issue #69:** Shows 100 but flywheel has zero complete cycles. The metric computation is likely measuring something other than what HSHS defines.

### Task 8: Fix Council using stale metrics

**Issue #31:** Council agents reference "76% win rate" and "exceeded Phase 1 gate." The council input context needs the quarantine filter applied to any metrics it receives.

### Task 9: Council parameter application guardrail

**Issue #32:** `cash_reserve_target_pct` was auto-applied. Per FINSABER/LLM authority boundaries, council should be advisory only in Phase 1. Add a config flag `council.auto_apply_parameters: false` and enforce it.

---

## SPRINT DB-2: Bug Fixes + Feature Additions

> **Branch:** `fix/dashboard-bugs-features`
> **Depends on:** DB-1 merged
> **Priority:** HIGH
> **Estimated CC time:** 8-12 hrs

### Task 1: Fix Packets page prompt leakage display

**Issue #9, #10.** The analysis field contains the raw system prompt + LLM output concatenated. Fix the display to extract only the XML content between tags, or strip everything before the first `<why_now>`.

### Task 2: Fix current_price=0.0 on Live Ledger

**Issue #19, #20.** The live trade current price shows $0.00. The API endpoint needs to fetch current price for open positions.

### Task 3: Open trade position monitor cards

**Issue #18, #22.** Replace flat table rows for open trades with rich cards showing:
- Current price vs entry (unrealized P&L $ and %)
- Stop/target progress gauge
- Days held / timeout remaining
- MFE/MAE
- Bracket status
- Conviction at entry
- Close button

Apply to both Shadow Ledger and Live Ledger (or merged page).

### Task 4: Merge Shadow Ledger + Live Ledger

**Issue #23.** One page with source toggle (Paper / Live / All). Same data shape, different `source` filter.

### Task 5: Add broker column to trade tables

**Issue #16.** Shadow Ledger table needs a "Broker" column showing alpaca/ib per trade. Add filter toggle.

### Task 6: Strategy page — win/loss magnitude overlay

**Issue #24.** Overlay per-trade win magnitudes (green, above zero) on the drawdown profile chart. Same x-axis (trade number), dual display showing whether losses are compressing and wins expanding.

### Task 7: Fix Stress Test duplicate cards + latest-only display

**Issue #52, #53, #55.** Group by scenario, show latest run only. Add collapsible "Previous Runs" archive.

### Task 8: Fix Monitoring page crash

**Issue #82.** `(e || []).map is not a function` — the API returns non-array data. Fix: `Array.isArray(data) ? data : []`.

### Task 9: Fix attribution logger wiring

**Issue #45, #46, #51.** Verify `log_attribution_before_llm()` and `log_attribution_after_llm()` are called in the executor. If disconnected during refactoring, re-wire them.

### Task 10: Fix Model Performance version attribution

**Issue #47, #49.** All trades show 0 for each version because `model_version` on `recommendations` table is NULL or inconsistent. Fix: backfill model_version on existing recommendations from the scan that created them.

### Task 11: Add IB data across trading pages

**Issue #74, #75, #76.**
- Move IB Shadow to Trading nav section
- Rename to "Broker Comparison"
- Add broker filter to Shadow Ledger
- Add by-broker breakdown to CTO Report

### Task 12: Add export errors button to Logs page

**Issue #86.** Download filtered log (ERROR + CRITICAL + WARNING, last 24h, markdown format).

### Task 13: Fix stale commands in Logs

**Issue #83, #84.** Pending commands with no duration should have a TTL — auto-expire after 1 hour. Add "Clear Stale" button.

### Task 14: Add IB settings section to Settings page

**Issue #91.** Show shadow_mode, paper_routing, threshold, port, client_id.

### Task 15: Add missing docs to Docs page

**Issue #94, #95.** Include IB research docs and operations docs in the docs index.

### Task 16: Fix Outcome Distribution placeholder

**Issue #29.** Wire up actual outcome distribution data from closed trades.

### Task 17: Fix outdated data collectors

**Issue #26, #27, #28.** Investigate why CBOE, Short Interest, Earnings Calendar, SEC EDGAR, Insider Transactions, Fed Communications collectors are stale or broken.

---

## SPRINT DB-3: Responsive Design + Polish

> **Branch:** `feat/dashboard-responsive`
> **Depends on:** DB-2 merged
> **Priority:** MEDIUM
> **Estimated CC time:** 6-8 hrs

### Task 1: Mobile responsive pass

**Issue #96, #97.** Cross-cutting across all pages:
- Collapsible sidebar with hamburger menu
- Metric cards: stack to 1-2 columns on mobile
- Tables: horizontal scroll or card layout on narrow viewports
- Charts: full-width, touch-friendly tooltips
- Nav: bottom tab bar on mobile?

### Task 2: Whitespace and content width

**Issue #96.** Increase max-width containers, improve card padding, better section spacing across all pages.

### Task 3: Architecture page auto-layout

**Issue #65.** Deterministic hierarchical layout on first render. Keep drag interaction for exploration.

### Task 4: DB Schema page auto-layout

**Issue #65.** Grouped grid layout by domain, deterministic positioning.

### Task 5: Fix canvas rendering artifacts

**Issue #62, #64.** Investigate and fix the pixelated/glitched graphics on Architecture and DB Schema pages.

### Task 6: Simulation equity curve regime selector

**Issue #58.** Add dropdown to highlight one regime curve at a time, dim the rest.

### Task 7: Architecture diagram — add IB nodes

**Issue #59, #60, #61.** Add IB Gateway to Infrastructure layer, dual-broker routing to Execution layer, update page count.

### Task 8: Stress test — add 4 additional scenarios

**Issue #54.** Add 2018 Q4, 2011 debt ceiling, 2015 China deval, 2024 yen unwind.

---

## Ralph Loop Findings

### Pass 1:
**The quarantine sync is the #1 fix.** 17 of 97 issues (18%) trace to a single root cause: quarantine UPDATE values not syncing to Postgres. The COALESCE filter is correctly implemented in every cloud route — the data just isn't there. A 20-line script fixes all 17 issues at once. This should be Task 1 in DB-1 and everything else should wait until it's verified.

### Pass 2:
**DB-2 is too large.** 17 tasks at 8-12 hours is aggressive for one CC sprint. Split into DB-2a (bug fixes: Tasks 1-10, ~6 hrs) and DB-2b (features: Tasks 11-17, ~4 hrs). Bug fixes should ship before features. The open trade redesign (Task 3) is the most complex single task — it touches the frontend significantly and should be its own commit, not mixed with data fixes.

### Pass 3:
**The model version fix (DB-1 Task 3) needs a migration.** Just fixing `get_active_model_name()` doesn't backfill the NULL `model_version` values on existing recommendation rows. Need a one-time backfill: `UPDATE recommendations SET model_version = 'halcyon-v1.0.0' WHERE model_version IS NULL AND created_at >= '2026-03-20'` (date of v1.0.0 deployment). Without this, Model Performance page (#47) stays broken even after the detection fix.

Also caught: the Council parameter application (#32) is a safety issue, not a cosmetic one. If the council is auto-applying parameters during Phase 1, it's violating the FINSABER authority boundaries. This should be in DB-1 (critical), not DB-2.
