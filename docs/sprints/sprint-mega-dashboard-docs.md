# Mega Sprint: Dashboard Polish + Documentation Consolidation

> **Priority:** HIGH — Dashboard shows misleading data + agents waste 34K tokens reading 5 overlapping docs
> **Scope:** 4 frontend fixes + 2 backend fixes + documentation restructure
> **Note:** Roadmap page already updated (529 lines) — do NOT touch `Roadmap.jsx`.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after. Run `cd frontend && npm run build` after all frontend changes.**

---

## Pre-Flight

1. Read `SYSTEM_STATE.md` — current state
2. Read `AGENTS.md` — architecture overview, data sources, CLI commands
3. Read `CLAUDE.md` — CC rules (this stays as-is)
4. Read `docs/conventions.md` — module docstring format, adding features/collectors
5. Read `docs/sprint-checklist.md` — post-sprint documentation requirements
6. Read `frontend/src/pages/Dashboard.jsx` — audit banner (lines 15-28, 224-232), build score (BuildScoreCard ~line 38)
7. Read `frontend/src/components/ActivityFeed.jsx` — event type switch (lines 40-78), normalizer (line 82)
8. Read `src/api/cloud_routes/training.py` lines 261-275 — audit latest endpoint
9. Read `src/api/cloud_routes/core.py` lines 357-395 — action button command mappings
10. Read `src/commands/executor.py` — COMMAND_HANDLERS dict (note: `cto-report` is MISSING)
11. Read `src/evaluation/build_score.py` — `persist_build_score()` (line 368)
12. Run `python -m pytest tests/ -x -q` — record baseline

---

# PART A: Dashboard Polish

## Task 1: Redesign Audit Banner

**File:** `frontend/src/pages/Dashboard.jsx`

The current red audit banner is a full-width wall of text that dumps raw auditor output. Replace with a compact expandable chip.

### Current implementation:
- `parseAuditSummary()` (lines 15-28) already extracts text from JSON — improve, don't rewrite
- Banner at lines 224-232 shows when `auditAssessment !== 'green'`
- API: `GET /api/audit/latest` in `src/api/cloud_routes/training.py:261` — returns `{overall_assessment, summary, flags, created_at, ...}` or `{audit: null}`

### Collapsed state (default):
Single-line chip, right-aligned near "HALT TRADING":

| Condition | Chip |
|---|---|
| `overall_assessment === 'green'` or `'healthy'` | `🟢 System OK` — subtle green text |
| `overall_assessment === 'yellow'` or `'warning'` | `🟡 Warnings` — amber text |
| `overall_assessment === 'red'` or `'critical'` | `🔴 Issues found` — red text (NOT a screaming wall) |
| No audit data (`{audit: null}` response) | `⚪ No audit` — muted text |
| `created_at` >24 hours old | `⚪ Stale (>24h)` — muted, OVERRIDES assessment color |

Staleness check:
```javascript
const auditCreatedAt = auditData?.created_at || auditData?.audit_date
const isStale = auditCreatedAt && 
  (Date.now() - new Date(auditCreatedAt).getTime()) > 24 * 60 * 60 * 1000
```

### Expanded state (on click):
Card below chip with:
- Assessment level with icon
- Clean summary from `parseAuditSummary()` — max 300 chars
- "Last audit: 2 hours ago" relative timestamp
- "Collapse" link

### Design:
- Chip: `inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium cursor-pointer`
- Card: `rounded-lg border p-4 mt-2` with Arcis palette
- `useState` for toggle — collapsed by default
- NEVER show raw JSON, code fences, or truncated garbage

---

## Task 2: Fix Build Score Empty State + CTO Report Button

### 2A: Frontend empty state
**File:** `frontend/src/pages/Dashboard.jsx`

BuildScoreCard (~line 38) shows 0.0 with all bars at zero when `build_score_history` is empty.

When API returns `{"build_score": 0, "components": {}}` OR all components are 0:
```jsx
if (!data || (data.build_score === 0 && (!data.components || Object.values(data.components).every(v => v === 0)))) {
  return (
    <div className="card p-4 text-center">
      <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>
        Build Score not yet computed
      </span>
      <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
        Click "Generate CTO Report" or wait for 4:30 PM ET daily computation
      </p>
    </div>
  )
}
```

### 2B: Add `cto-report` command handler
**File:** `src/commands/executor.py`

"Generate CTO Report" button maps to `_submit_command("scan")` — WRONG. No `cto-report` handler exists.

Add handler:
```python
def _handle_cto_report(payload: dict, config: dict) -> dict:
    """Generate CTO report and compute build score."""
    from src.evaluation.build_score import persist_build_score
    result = persist_build_score()
    return {
        "build_score": result.get("build_score", 0),
        "components": result.get("components", {}),
        "status": "completed",
    }
```

Add to COMMAND_HANDLERS: `"cto-report": _handle_cto_report,`

### 2C: Fix action endpoint mappings
**File:** `src/api/cloud_routes/core.py`

Change:
```python
# FROM:
def action_cto_report():
    return _submit_command("scan")  # WRONG

def action_score():
    return _submit_command("scan")  # WRONG

# TO:
def action_cto_report():
    return _submit_command("cto-report")

def action_score():
    return _submit_command("cto-report")
```

---

## Task 3: Fix Activity Feed "task: ?" Entries

**File:** `frontend/src/components/ActivityFeed.jsx`

Fix overnight_task case (lines 61-62):
```javascript
case 'overnight_task': {
  if (d.task) {
    const parts = [`${d.task.replace(/_/g, ' ')}: ${d.status || 'complete'}`]
    if (d.articles_cached) parts.push(`(${d.articles_cached} articles)`)
    if (d.tickers_enriched) parts.push(`(${d.tickers_enriched} tickers)`)
    return parts.join(' ')
  }
  return evt.detail ? String(evt.detail).slice(0, 120) : 'Overnight task completed'
}
```

Fix default case (lines 74-77):
```javascript
default: {
  const detail = evt.detail || ''
  if (detail && !detail.startsWith('{')) return detail.slice(0, 120)
  const eventName = (evt.type || evt.event || 'system').replace(/_/g, ' ')
  const summary = d.detail || d.message || d.status || ''
  return summary ? `${eventName}: ${String(summary).slice(0, 80)}` : eventName
}
```

---

# PART B: Documentation Consolidation

## Why

Agents currently read 5 files / 34,000+ tokens before starting work:
- `SYSTEM_STATE.md` (509 lines, ~7.5K tokens) — system state + decisions + frameworks
- `AGENTS.md` (280 lines, ~4K tokens) — architecture overview, data sources, CLI
- `CLAUDE.md` (104 lines, ~1.2K tokens) — CC rules
- `docs/architecture.md` (1,235 lines, ~13.5K tokens) — per-module file listing
- `docs/database-schema.md` (945 lines, ~8.2K tokens) — full table DDL

This is unsustainable. Most content overlaps, much is stale, and the per-file listings in `architecture.md` are redundant with Python docstring headers.

## Target State

```
Root:
  MASTER.md              ← THE document. Every agent reads this. (~1,000 lines)
  CLAUDE.md              ← CC-specific rules (stays as-is, 104 lines)
  README.md              ← Public-facing (stays)
  CHANGELOG.md           ← Historical (stays)

docs/
  archive/               ← Moved here (not deleted)
    SYSTEM_STATE.md          (content absorbed into MASTER.md)
    AGENTS.md                (content absorbed into MASTER.md)
    architecture.md          (per-file detail in Python docstrings)
    database-schema.md       (schema registry is source of truth)
    dependency-graph.md      (1,448 lines, auto-generated)
    roadmap.md               (dashboard Roadmap page is source of truth)
    roadmap-complete.md      (superseded)
    conventions.md           (absorbed into MASTER.md)
    sprint-checklist.md      (absorbed into MASTER.md)
    schema-governance.md     (absorbed into MASTER.md)
    diagrams.md              (stale)
    sprints/                 (all COMPLETED sprint prompts — already there)
    
  sprints/               ← ACTIVE sprint prompts only (queued work)
  research/              ← Reference corpus (60+ docs, read on-demand)
  guides/                ← How-to guides (deployment, training, email)
```

## Task 4: Create MASTER.md

Create `MASTER.md` in the repo root. Structure follows an **inverted pyramid** — most critical info in the first 200 lines. If an agent's context is tight, it still has the essentials.

### MASTER.md Section Outline

**Section 1: System Identity (~30 lines)**
```markdown
# Arcis — Master Reference Document

> **This is THE document. Every agent reads this at session start.**
> Last updated: {date} · {trade count} closed trades · {issue count} open issues

Arcis is an autonomous AI-powered equity trading system targeting S&P 100 stocks
with a pullback-in-uptrend strategy and 2-15 day holding periods.

- **Repo:** github.com/millerrc18/halcyon-lab
- **Dashboard:** halcyonlab.app
- **License:** BSL 1.1
- **Owner:** Ryan Miller (ryan.c.miller@gd-ms.com)
```

**Section 2: Current State — Volatile (~80 lines)**
Pull from SYSTEM_STATE.md:
- Phase progress (13/50 trades, 26% gate)
- Open issues (table with issue #, title, severity)
- What's deployed and running
- Active sprint / CC queue
- Known bugs and blockers
- Last audit results

**Section 3: Architecture Overview (~100 lines)**
Condensed from AGENTS.md:
- System flow diagram (text-based: Universe → Features → Ranking → LLM → Trade)
- Component table: module name, purpose, key files (NOT per-file listing — just the key entry points)
- Data sources table (7 enrichment + 12 collection)
- Infrastructure: SQLite local, Render Postgres cloud, Ollama, Alpaca

**Section 4: Schema Summary (~60 lines)**
NOT full DDL. Just a table:
```markdown
| Table | Purpose | Key Columns | Sync |
|---|---|---|---|
| shadow_trades | Paper/live trade ledger | trade_id, ticker, status, pnl_dollars | incremental |
| recommendations | LLM-generated trade theses | recommendation_id, ticker, thesis_text | incremental |
| training_examples | Model training data | example_id, input, output, quality_score | incremental |
...
```
With note: "Full DDL in `src/schema/registry.py` — the single source of truth."

**Section 5: Strategy Decisions (~40 lines)**
All 24 decisions, numbered, from SYSTEM_STATE.md — verbatim copy.

**Section 6: Phase Gates (~20 lines)**
Gate table from SYSTEM_STATE.md — verbatim copy.

**Section 7: Frameworks (~80 lines)**
- GPU Utilization (4 time blocks with targets)
- Exit Management (4 phases)
- Scanning Cadence (4 tiers)
- Training Data (11 sections, random subsetting)

**Section 8: Revenue & Business (~30 lines)**
- Revenue milestones table (month 0 → 36)
- Fund path: LLC → 475(f) → incubator → fund
- Hardware path: 3060 → dedicated server → 3090

**Section 9: Conventions & Rules (~100 lines)**
Absorb from `conventions.md`, `sprint-checklist.md`, CLAUDE.md rules:
- Module docstring format (5-field header)
- Adding features / data collectors / API endpoints
- Sprint checklist (required/optional docs)
- Database schema rules (registry is source of truth, never write DDL outside registry)
- Codebase guardrails (no file >400 lines, no function >60 lines, ≤10 tasks/sprint)
- PR review rules (check every changed file for stubs/TODOs)

**Section 10: Key Principles (~40 lines)**
The durable truths that never change:
- Training data quality is the #1 competitive advantage
- Self-blinding is architectural, not instructional
- Quality > quantity (LIMA, AlpaGasus)
- Equal weight until 200+ trades
- Dashboard is the control plane
- Never refactor and add features in the same sprint
- The data asset — not the model, not the returns — is the most valuable component

**Section 11: Sprint Queue (~40 lines)**
Current queue with status (from SYSTEM_STATE.md).

**Section 12: Reference Pointers (~30 lines)**
Explicit "For X, read Y" pointers:
```markdown
| Topic | Document |
|---|---|
| Full table DDL | `src/schema/registry.py` |
| Training methodology | `docs/research/Training_Data_Strategies_...md` |
| Options research | `docs/research/AI-Powered_Options_Trading_...md` |
| Fund formation | `docs/research/From_Solo_AI_Trader_to_Fund_Manager_...md` |
| Deep research results | `docs/research/deep-research/` (3 completed, 1 unfired) |
| Sprint implementation plan | `docs/sprints/implementation-plan-sprints-3-7.md` |
```

**Section 13: Brand (~15 lines)**
Name, palette, typography, voice — from SYSTEM_STATE.md.

### Total: ~660 lines → with tables and formatting ~800-1,000 lines → ~5,000 tokens

## Task 5: Archive Original Documents

Move files to `docs/archive/`:
```bash
# Create archive directories if needed
mkdir -p docs/archive/governance
mkdir -p docs/archive/reference

# Archive governance docs (absorbed into MASTER.md)
mv SYSTEM_STATE.md docs/archive/governance/SYSTEM_STATE.md
mv AGENTS.md docs/archive/governance/AGENTS.md
mv docs/conventions.md docs/archive/governance/conventions.md
mv docs/sprint-checklist.md docs/archive/governance/sprint-checklist.md
mv docs/schema-governance.md docs/archive/governance/schema-governance.md

# Archive reference docs (redundant with source of truth)
mv docs/architecture.md docs/archive/reference/architecture.md
mv docs/database-schema.md docs/archive/reference/database-schema.md
mv docs/dependency-graph.md docs/archive/reference/dependency-graph.md
mv docs/roadmap.md docs/archive/reference/roadmap.md
mv docs/roadmap-complete.md docs/archive/reference/roadmap-complete.md
mv docs/diagrams.md docs/archive/reference/diagrams.md
```

**Leave in place (not archived):**
- `CLAUDE.md` — CC reads this (104 lines, stays)
- `README.md` — public-facing
- `CHANGELOG.md` — historical
- `docs/research/` — reference corpus (read on-demand)
- `docs/guides/` — how-to guides
- `docs/sprints/` — active sprint prompts
- `docs/decisions/` — ADRs (historical reference)
- `docs/blueprint/` — v1 blueprint

## Task 6: Update All References

### 6A: CLAUDE.md
Change:
```markdown
All project rules, architecture, data sources, and constraints are in **AGENTS.md** — read it before making changes.
```
To:
```markdown
All project rules, architecture, data sources, and constraints are in **MASTER.md** — read it before making changes.
```

### 6B: docs route (src/api/routes/docs.py)
Update the DOCS list to serve MASTER.md instead of archived files:
```python
DOCS = [
    {"id": "master", "path": "MASTER.md", "title": "MASTER.md — Complete System Reference"},
    {"id": "claude", "path": "CLAUDE.md", "title": "CLAUDE.md — CC Rules"},
    {"id": "readme", "path": "README.md", "title": "README"},
    # ... research docs stay ...
]
```
Remove references to `architecture.md`, `roadmap.md` (now archived).

### 6C: README.md
Update documentation section to point to MASTER.md as the entry point.

### 6D: Sprint checklist reference
Every CC sprint prompt references `docs/sprint-checklist.md`. The sprint checklist is now Section 9 of MASTER.md. Update the sprint template at `docs/sprints/TEMPLATE.md` to reference MASTER.md Section 9 instead.

### 6E: hookify / CI references
Check if any CI scripts, git hooks, or `scripts/verify_docs.py` reference the old file paths:
```bash
grep -rn "SYSTEM_STATE.md\|AGENTS.md\|architecture.md\|sprint-checklist" scripts/ .github/ .husky/ 2>/dev/null
```
Update any matches.

## Task 7: Create Archive README

Create `docs/archive/README.md`:
```markdown
# Archived Documentation

These documents were consolidated into `MASTER.md` (repo root) on April 2, 2026.
They are preserved for historical reference. Do NOT edit these files.

## Governance (absorbed into MASTER.md)
- `SYSTEM_STATE.md` — Previous system state document
- `AGENTS.md` — Previous governance document
- `conventions.md` — Module patterns and conventions
- `sprint-checklist.md` — Post-sprint documentation requirements
- `schema-governance.md` — Schema registry rules

## Reference (superseded by source of truth)
- `architecture.md` — Per-module file listing (Python docstrings are source of truth)
- `database-schema.md` — Full DDL (schema registry is source of truth)
- `dependency-graph.md` — Auto-generated module dependencies
- `roadmap.md` — Superseded by dashboard Roadmap page
- `roadmap-complete.md` — Superseded by dashboard Roadmap page
- `diagrams.md` — System diagrams (stale)
```

## Task 8: Update MASTER.md and Verify

After all changes:
- Update MASTER.md Section 2 (volatile state) with current numbers
- Verify `npm run build` succeeds
- Verify all Python tests pass
- Verify `python scripts/verify_docs.py` (may need updating to check MASTER.md instead of SYSTEM_STATE.md)
- Verify dashboard Docs page loads MASTER.md correctly

---

# Acceptance Criteria

### Part A: Dashboard
- [ ] Audit banner: compact chip, not red wall. Shows 🟢/🟡/🔴/⚪
- [ ] Staleness: >24h old audit shows `⚪ Stale` regardless of assessment
- [ ] Click expands to clean card with summary + relative timestamp
- [ ] No raw JSON/code fences ever visible
- [ ] Build Score: empty state shows "Not yet computed" (not 0.0)
- [ ] "Generate CTO Report" submits `cto-report` command (not `scan`)
- [ ] `_handle_cto_report` exists in COMMAND_HANDLERS, calls `persist_build_score()`
- [ ] "Score" action submits `cto-report` (not `scan`)
- [ ] Activity feed: no "task: ?" entries
- [ ] Default case renders human-readable text

### Part B: Documentation
- [ ] `MASTER.md` exists in repo root, ~800-1,000 lines
- [ ] MASTER.md Section 1-13 all populated with real data
- [ ] Strategy Decisions shows all 24
- [ ] Phase Gates show expanded requirements
- [ ] Frameworks section covers GPU, exit, scanning, training
- [ ] Conventions section includes module format, sprint checklist, schema rules
- [ ] Old docs moved to `docs/archive/` (not deleted)
- [ ] `CLAUDE.md` updated to reference MASTER.md
- [ ] `src/api/routes/docs.py` serves MASTER.md
- [ ] `README.md` points to MASTER.md
- [ ] `docs/archive/README.md` exists explaining the archive
- [ ] No broken references to archived files in src/ or frontend/
- [ ] `scripts/verify_docs.py` updated if it references old files

### Zero Regressions
- [ ] All Python tests pass
- [ ] `npm run build` succeeds
- [ ] All 16 dashboard pages load correctly
- [ ] Dashboard Docs page shows MASTER.md

---

## Files Changed (expected)

| File | Change |
|---|---|
| `MASTER.md` | **NEW** — consolidated system reference (~800-1,000 lines) |
| `CLAUDE.md` | Update AGENTS.md → MASTER.md reference |
| `README.md` | Update documentation pointer |
| `frontend/src/pages/Dashboard.jsx` | Audit chip, build score empty state |
| `frontend/src/components/ActivityFeed.jsx` | Fix overnight_task + default case |
| `src/commands/executor.py` | Add `_handle_cto_report` handler |
| `src/api/cloud_routes/core.py` | Fix action button mappings |
| `src/api/routes/docs.py` | Serve MASTER.md, remove archived refs |
| `docs/sprints/TEMPLATE.md` | Update sprint-checklist reference |
| `docs/archive/README.md` | **NEW** — archive explanation |
| `docs/archive/governance/*` | **MOVED** — 5 governance docs |
| `docs/archive/reference/*` | **MOVED** — 6 reference docs |
