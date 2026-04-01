# Sprint: React Flow Interactive Diagrams + Dashboard UI Polish

> **Dependencies:** Reconciliation fix (#177) and log audit (#176) are merged. Data integrity is clean.
> **Frontend plugin:** ENABLED — use it to preview and verify every visual change.
> **Scope:** Add React Flow diagrams to dashboard + polish the existing UI across all 14 pages.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after. Run `cd frontend && npm run build` after all changes. Use the frontend plugin to verify visual quality on EVERY page you touch.**

---

## Pre-Flight

1. Read `SYSTEM_STATE.md` and `AGENTS.md`
2. Read `frontend/src/App.jsx` — understand routing and layout
3. Read `frontend/src/index.css` — understand Arcis Palette H (CSS variables)
4. Browse ALL 14 pages in the running dashboard — note visual inconsistencies, broken layouts, empty states, and rough edges
5. Read `docs/sprints/sprint-react-flow.md` — the original React Flow spec
6. Install: `cd frontend && npm install @xyflow/react`
7. Run baseline: `cd frontend && npm run build`

---

## PART A: React Flow Setup + Shared Components

### A1: Install React Flow
```bash
cd frontend && npm install @xyflow/react
```

### A2: Shared diagram wrapper
**File:** `frontend/src/components/diagrams/FlowDiagram.jsx`

Reusable wrapper providing:
- React Flow canvas with zoom/pan controls
- Minimap (toggleable)
- Dark/light mode via Arcis CSS variables
- Controls panel (zoom in/out, fit view)
- Consistent node and edge styling

### A3: Custom node component
**File:** `frontend/src/components/diagrams/SystemNode.jsx`

- Title + subtitle + optional status badge ("LIVE", "PLANNED", "Phase 2")
- Left color accent bar by category:
  - Data: `var(--arcis-success)` green
  - AI/LLM: `var(--arcis-accent)` blue
  - Risk: `var(--arcis-danger)` red
  - Training: `var(--arcis-warning)` amber
  - Infrastructure: `var(--arcis-text-muted)` gray
- Click to expand → detail panel with description + key files
- Handles on appropriate sides for edges

### A4: Edge styles
- Data flow: solid, `var(--arcis-accent)`, animated
- Training feedback: dashed, `var(--arcis-warning)`
- Control flow: solid thin, `var(--arcis-text-muted)`

---

## PART B: Architecture Flow Diagram Page

**File:** `frontend/src/pages/Architecture.jsx`

Full system architecture as interactive React Flow diagram.

### Layout (top-to-bottom flow):

**Row 1 — Data Sources** (green): yfinance, FRED Macro, Finnhub, SEC EDGAR, Options/VIX, 12 Night Collectors, Claude Sonnet

**Row 2 — Processing** (blue): Feature Engine → Data Enrichment → Ranking (0-100) → Setup Classifier → Signal Zoo

**Row 3 — Decision & Risk** (red + blue): AI Council → LLM Packet Writer → Risk Governor → LLM Validator → Kill Switch

**Row 4 — Execution** (blue): Executor → Alpaca Paper / Alpaca Live → Bracket Monitor

**Row 5 — Training Flywheel** (amber, feedback arrow to Row 3): Trade Outcomes → Self-Blinded Gen → Quality Scoring → Leakage Detector → Curriculum → QDoRA SFT → Champion-Challenger → GGUF → Ollama

**Row 6 — Infrastructure** (gray): halcyonlab.app, Telegram, SQLite, Render Postgres, Email Digests

### Edges:
- Rows flow downward (data → processing → decision → execution → training)
- Training → LLM feedback loop (dashed amber)
- Infrastructure connected to all rows

### Node click → detail panel:
- What: 1-2 sentence description
- Key files: code paths
- Status: Active / Planned / Phase 2+
- Detail data hardcoded initially (wire to API later)

### Route: `/architecture` in App.jsx

---

## PART C: Database Schema Diagram Page

**File:** `frontend/src/pages/DatabaseSchema.jsx`

Interactive ERD using React Flow, showing all 40 tables grouped by domain.

### 6 clusters:
1. **Trading Core** (green): recommendations, shadow_trades, setup_signals
2. **Training Pipeline** (amber): training_examples, model_versions, canary_evaluations, quality_drift_metrics
3. **AI Council** (purple): council_sessions, council_votes, council_calibrations + 3 more
4. **Data Collection** (teal): 12 collector tables
5. **Evaluation** (blue): build_score_history, audit_reports, scan_metrics + 3 more
6. **Infrastructure** (gray): api_costs, activity_log, pending_commands + 8 more

### Foreign key edges:
- shadow_trades → recommendations
- training_examples → recommendations
- council_votes → council_sessions
- command_results → pending_commands

### Node content:
- Table name (bold) + row count badge (from API)
- Click to expand → column list with types

### API endpoint:
**File:** `src/api/cloud_routes/core.py`

```python
@router.get("/api/system/table-counts", dependencies=[Depends(verify_auth)])
def table_counts():
    counts = {}
    for table in ["shadow_trades", "recommendations", "training_examples", ...]:  # whitelist
        try:
            row = runtime.query_one(f"SELECT COUNT(*) as c FROM {table}")
            counts[table] = row["c"] if row else 0
        except Exception:
            counts[table] = -1
    return counts
```

### Route: `/schema` in App.jsx

---

## PART D: Dashboard UI Polish (All 14 Pages)

Use the frontend plugin to preview each page. Fix every rough edge you find. Below are known issues — also fix anything else you notice.

### D1: Global consistency
- Ensure all pages use consistent padding, card borders, and spacing
- All empty states should show a helpful message (not a blank area or raw "null")
- All loading states should use `<LoadingSpinner />` consistently
- All error states should show a user-friendly message, not a stack trace
- Page titles should be consistent size/weight across all pages
- Ensure dark/light mode toggle works correctly on every page

### D2: Dashboard (main page)
- Verify KPI cards are populated (not showing zeros if data exists)
- Activity feed should show recent events, not empty
- Build Score card should show the latest score (we just fixed the persistence)

### D3: Shadow Ledger
- Closed trades should now appear (reconciliation fix landed)
- Verify P&L colors (green positive, red negative) have consistent intensity
- Verify search/filter works
- Verify sortable columns work

### D4: CTO Report
- Period selector (7d/30d/90d/All) should load data for each period
- If no data for a period, show "No closed trades in this period" not a blank page
- Verify the regime/sector/exit reason breakdowns render

### D5: Training page
- "Outcome data pending migration" message — is this still showing? The backfill should have fixed it. If outcome column is populated, show the distribution chart.
- Collector grid freshness indicators should be accurate
- Quality score histogram if data exists

### D6: Health / HSHS
- Verify all 5 dimensions show values (not all zeros)
- If insufficient data, show "Insufficient data (N/50 trades)" not just 0

### D7: Settings page
- System Health section shows "Off" for everything in cloud mode — add a note: "Health checks run locally. Cloud dashboard shows cached status."
- API costs should now show real numbers (we fixed the cost_dollars column)

### D8: Live Ledger
- Verify expandable rows work
- If no live trades, show appropriate empty state

### D9: Validation page
- Verify the success/failure banner appears after running validation
- Verify pass/warn/fail counts display correctly

### D10: Sidebar navigation update
Add new pages to sidebar under organized sections:
```
── Trading ──
Dashboard
Packets
Shadow Ledger
Live Ledger
── Intelligence ──
Training
Council
CTO Report
── System ──
Architecture        ← new (React Flow)
DB Schema           ← new (React Flow)
Health Score
Validation
── Reference ──
Settings
Roadmap
Docs
Logs
Notes
```

Use `lucide-react` icons: Architecture → `Workflow`, DB Schema → `Database`

---

## PART E: Documentation

1. Update SYSTEM_STATE.md: dashboard page count (14 → 16), React Flow added
2. Update README: note React Flow diagrams on dashboard
3. Keep `frontend/public/architecture.html` as standalone printable version

---

## Acceptance Criteria

### React Flow:
- [ ] `@xyflow/react` in package.json
- [ ] `/architecture` renders full system diagram with 6 rows, color-coded nodes, animated edges
- [ ] `/schema` renders 40-table ERD grouped by 6 domains with foreign key edges
- [ ] Clicking any node shows detail panel
- [ ] Zoom, pan, fit-view, minimap all work
- [ ] Both diagrams respect dark/light mode
- [ ] `/api/system/table-counts` returns row counts

### UI Polish:
- [ ] All 14 existing pages reviewed with frontend plugin — no broken layouts
- [ ] All empty states have user-friendly messages
- [ ] All loading states use LoadingSpinner
- [ ] Dark/light toggle works on every page including new ones
- [ ] Sidebar reorganized with section headers
- [ ] Settings page has cloud mode note
- [ ] CTO Report shows "no data" message instead of blank
- [ ] Training outcome distribution renders if data exists

### Build:
- [ ] `npm run build` succeeds
- [ ] All Python tests pass (>= 1235)
- [ ] SYSTEM_STATE.md updated
