# Sprint: React Flow Interactive Diagrams on Dashboard

> **Goal:** Add React Flow to the dashboard for interactive, zoomable, pannable system diagrams.
> **Library:** `@xyflow/react` (formerly reactflow) — MIT license, React 18 compatible, zero cost.
> **Scope:** 3 new interactive diagram views replacing static visuals.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after. Run `cd frontend && npm run build` after all frontend changes.**

---

## Pre-Flight

1. Read `SYSTEM_STATE.md` and `AGENTS.md`
2. Read `frontend/src/App.jsx` — understand routing
3. Read `frontend/public/architecture.html` — this is the existing interactive architecture diagram we're replacing with an in-dashboard React Flow version
4. Read `docs/database-schema.md` — this is the ERD we're bringing into the dashboard
5. Install: `cd frontend && npm install @xyflow/react`

---

## Task 1: Install React Flow + Create Shared Components

### 1A: Install dependency
```bash
cd frontend
npm install @xyflow/react
```

### 1B: Create shared diagram components

**File:** `frontend/src/components/diagrams/FlowDiagram.jsx`

A reusable wrapper that provides:
- React Flow canvas with zoom/pan controls
- Minimap (toggleable)
- Dark mode support using Arcis CSS variables
- Controls panel (zoom in/out, fit view, toggle minimap)
- Consistent node and edge styling matching Palette H

**Node style guide (use Arcis CSS variables):**
- Default nodes: `var(--arcis-bg-surface)` background, `var(--arcis-border)` border
- AI/LLM nodes: `var(--arcis-accent)` left border accent (blue)
- Risk nodes: `var(--arcis-danger)` left border accent (red)
- Training nodes: `var(--arcis-warning)` left border accent (amber)
- Data nodes: `var(--arcis-success)` left border accent (green)
- Infrastructure: `var(--arcis-text-muted)` left border accent (gray)

**Edge style guide:**
- Data flow: solid, `var(--arcis-accent)` with animated dots
- Training feedback: dashed, `var(--arcis-warning)`
- Control flow: solid thin, `var(--arcis-text-muted)`

**Custom node component:** `frontend/src/components/diagrams/SystemNode.jsx`
- Title + subtitle + optional badge (e.g., "LIVE", "PLANNED", "Phase 2")
- Left color accent bar based on category
- Expandable on click → shows detail panel with description
- Handles on appropriate sides for edge connections

---

## Task 2: Architecture Flow Diagram Page

**File:** `frontend/src/pages/Architecture.jsx`

Replace the current link to `architecture.html` with a full React Flow interactive diagram rendered inside the dashboard. This is the primary deliverable.

### Layout: Top-to-bottom data flow

**Row 1 — Data Sources** (green accent):
- `yfinance OHLCV` → `FRED Macro (34+)` → `Finnhub (News/Insider)` → `SEC EDGAR` → `Options/VIX` → `12 Night Collectors` → `Claude Sonnet`

**Row 2 — Processing Pipeline** (blue accent):
- `Feature Engine (50+ features)` → `Data Enrichment` → `Ranking (0-100)` → `Setup Classifier (6 types)` → `Signal Zoo`

**Row 3 — Decision & Risk** (red accent):
- `AI Council (5 agents)` → `LLM Packet Writer (Qwen3 8B)` → `Risk Governor (8 checks)` → `LLM Validator` → `Kill Switch`

**Row 4 — Execution** (blue accent):
- `Executor (bracket orders)` → `Alpaca Paper ($100K)` / `Alpaca Live ($100)` → `Bracket Monitor`

**Row 5 — Training Flywheel** (amber accent, with feedback arrow back to Row 3):
- `Trade Outcomes` → `Self-Blinded Gen` → `Quality Scoring (6-dim)` → `Leakage Detector` → `Curriculum 3-Stage` → `QDoRA SFT` → `Champion-Challenger` → `GGUF → Ollama`

**Row 6 — Infrastructure** (gray accent):
- `halcyonlab.app` → `Telegram (32 cmds)` → `SQLite (40 tables)` → `Render Postgres` → `Email Digests`

### Edges:
- Row 1 → Row 2 (data flows down)
- Row 2 → Row 3 (ranked candidates flow to decision layer)
- Row 3 → Row 4 (approved trades flow to execution)
- Row 4 → Row 5 (closed trades feed training)
- Row 5 → Row 3 (retrained model feeds back — dashed amber "flywheel" edge)
- Row 6 connected to all rows (infrastructure serves everything)

### Node click behavior:
Clicking any node shows a detail panel (slide-in from right, or modal) with:
- **What:** 1-2 sentence description
- **Key files:** Code paths (e.g., `src/features/engine.py`)
- **Status:** Active / Planned / Phase 2+
- **Metrics:** Live data if available (e.g., "972 training examples", "5/5 closed winners")

Data for the detail panel should be hardcoded initially — we can wire to API endpoints later.

### Add to router:
Add `/architecture` route in `App.jsx`. Add "Architecture" to the sidebar navigation with a diagram icon.

---

## Task 3: Database Schema Diagram Page

**File:** `frontend/src/pages/DatabaseSchema.jsx`

Interactive ERD using React Flow, replacing the static Mermaid in `docs/database-schema.md`.

### Layout: Group by domain (6 clusters)

**Cluster layout (use React Flow subflows or grouped positioning):**

1. **Trading Core** (top-left, green):
   - `recommendations` (PK: recommendation_id)
   - `shadow_trades` (PK: trade_id, FK → recommendations)
   - `setup_signals` (PK: id)

2. **Training Pipeline** (top-right, amber):
   - `training_examples` (PK: example_id, FK → recommendations)
   - `model_versions` (PK: version_id)
   - `canary_evaluations` (PK: id)
   - `quality_drift_metrics` (PK: id)

3. **AI Council** (middle-left, purple):
   - `council_sessions` (PK: session_id)
   - `council_votes` (PK: id, FK → council_sessions)
   - `council_calibrations`, `council_debug_log`, `council_parameter_log`, `council_parameter_state`

4. **Data Collection** (middle-right, teal):
   - All 12 collector tables: `earnings_calendar`, `edgar_filings`, `insider_transactions`, `analyst_estimates`, `short_interest`, `fed_communications`, `macro_snapshots`, `options_metrics`, `options_chains`, `cboe_ratios`, `vix_term_structure`, `google_trends`

5. **Evaluation** (bottom-left, blue):
   - `build_score_history`, `audit_reports`, `metric_snapshots`, `scan_metrics`, `validation_results`, `traffic_light_state`

6. **Infrastructure** (bottom-right, gray):
   - `api_costs`, `activity_log`, `log_entries`, `pending_commands`, `command_results`, `schedule_metrics`, `sync_state`, `user_notes`, `research_docs`, `research_papers`, `research_digests`

### Edges (foreign keys):
- `shadow_trades.recommendation_id` → `recommendations.recommendation_id`
- `training_examples.recommendation_id` → `recommendations.recommendation_id`
- `council_votes.session_id` → `council_sessions.session_id`
- `command_results.command_id` → `pending_commands.command_id`

### Node content:
Each table node shows:
- Table name (bold)
- Row count badge (fetch from `/api/system/table-counts` — see Task 4)
- Primary key column name
- Click to expand → show all columns with types

### Add to router:
Add `/schema` route. Add "DB Schema" to sidebar under a "System" group or similar.

---

## Task 4: Table Counts API Endpoint

**File:** `src/api/cloud_routes/core.py`

Add endpoint to power the DB schema diagram with live row counts:

```python
@router.get("/api/system/table-counts", dependencies=[Depends(verify_auth)])
def table_counts():
    """Return row counts for all synced tables."""
    counts = {}
    for table in SYNC_TABLE_NAMES:
        try:
            row = runtime.query_one(f"SELECT COUNT(*) as c FROM {table}")
            counts[table] = row["c"] if row else 0
        except Exception:
            counts[table] = -1  # table may not exist
    return counts
```

Note: Use a whitelist of known table names — never interpolate user input into SQL.

---

## Task 5: Sidebar Navigation Update

Update the sidebar to include the new pages:

```
Dashboard
Packets  
Shadow Ledger
Live Ledger
Training
CTO Report
── System ──
Architecture        (new — React Flow)
DB Schema           (new — React Flow)
Health Score
Validation
── Reference ──
Council
Settings
Roadmap
Docs
```

Use `lucide-react` icons:
- Architecture: `GitBranch` or `Workflow`
- DB Schema: `Database` or `TableProperties`

---

## Task 6: Update Documentation

1. Remove the "See Interactive Architecture" link from README.md (it's now in the dashboard)
2. Keep `frontend/public/architecture.html` as a standalone printable version
3. Update SYSTEM_STATE.md: note React Flow added, dashboard page count increased
4. Update `docs/database-schema.md`: add note that interactive version is on dashboard

---

## Acceptance Criteria

- [ ] `@xyflow/react` installed and in package.json
- [ ] `/architecture` page renders full system diagram with all 6 rows
- [ ] Nodes are color-coded by category (data=green, AI=blue, risk=red, training=amber, infra=gray)
- [ ] Clicking a node shows detail panel with description + code paths
- [ ] Edges show data flow direction with appropriate styling (solid/dashed/animated)
- [ ] Zoom, pan, fit-view, and minimap all work
- [ ] `/schema` page renders all 40 tables grouped by domain
- [ ] Foreign key edges connect related tables
- [ ] Table nodes show live row counts from API
- [ ] Clicking a table shows column list
- [ ] Both diagrams respect dark/light mode via Arcis CSS variables
- [ ] Sidebar updated with new pages under "System" section
- [ ] `/api/system/table-counts` returns counts for all tables
- [ ] `npm run build` succeeds
- [ ] All Python tests pass
- [ ] Dashboard page count updated in SYSTEM_STATE.md
