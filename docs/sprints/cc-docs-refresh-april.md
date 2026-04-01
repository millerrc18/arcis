# CC Sprint: Documentation Refresh — April 2026

## Context

This is a documentation-only sprint. No code changes except fixing stale counts and references.

The system has undergone massive changes since the last docs update:
- Sprints 5-8 merged (82 issues closed from 87)
- Analytics endpoints migrated to Postgres
- Dashboard redesigned (Shadow/Live Ledger, CTO period selector, Build Score scheduling)
- BSL 1.1 license (was MIT)
- Brand: Halcyon Lab → Arcis
- CC tooling installed (MCP servers, hooks, skills, subagents)
- 7 missing Postgres tables added to render_migrate.py
- VRAM handoff completed (torch cleanup, process kill, Ollama restart on failure)
- WebSocket backoff added (5 retries, exponential)
- Pre-market brief now pulls real S&P futures + 10Y yield via yfinance
- API costs endpoint fixed (COALESCE cost_dollars/estimated_cost)
- recommendations.regime_label → market_regime fixed

**CRITICAL: Read SYSTEM_STATE.md first. It is the single source of truth.**

## Current Verified Counts (April 1, 2026)

| Metric | Count |
|---|---|
| Python files | 173 |
| Test files | 101 |
| Test functions | 1,235 |
| DB tables (unique) | 49 |
| Sync tables (Postgres) | 40 |
| API routes | 126 |
| CLI commands | 53 |
| Dashboard pages | 14 |
| Telegram notification types | 32 |
| Research docs | 60+ |
| GitHub issues | 5 open (from 87) |
| License | BSL 1.1 |

---

## Task 1: Update `docs/architecture.md`

This is the primary deliverable. The file is 1,235 lines and covers:
- System overview
- Module inventory (every .py file with one-line description)
- Database schema (all tables)
- API endpoints (all routes)
- Configuration keys
- Data flow

**What to update:**

1. **Module Inventory** — Walk every `src/` directory and verify:
   - All 173 Python files are listed
   - One-line descriptions match current functionality (not stale)
   - New files from Sprints 5-8 are included (e.g., `src/data_collection/retention.py`, `src/scheduler/holidays.py`, `src/utils/db.py`, `src/config/overrides.py`)
   - Removed/renamed files are deleted from the list

2. **Database Schema** — Verify all 49 tables are documented:
   - Cross-reference with `scripts/render_migrate.py` (40 sync tables)
   - Cross-reference with `scripts/create_missing_tables.py`
   - Cross-reference with inline `CREATE TABLE` statements in `src/`
   - New tables from Sprint 8: ensure all are listed

3. **API Endpoints** — Verify all 126 routes are listed:
   - `src/api/cloud_routes/analytics.py` — HSHS, CTO Report, Build Score, Traffic Light
   - `src/api/cloud_routes/core.py` — system/validation (new), costs, commands
   - `src/api/cloud_routes/trades.py` — shadow/open, shadow/closed now JOIN recommendations
   - `src/api/cloud_routes/training.py` — training/history (new), scan/metrics (paginated)

4. **Configuration Keys** — Cross-reference `config/settings.example.yaml` (423 lines, 20 sections)

5. **Brand References** — Replace any remaining "Halcyon Lab" with "Arcis"

6. **System Overview** — Update the prose to reflect current state:
   - 40-table Postgres sync (was less)
   - 14 dashboard pages
   - BSL 1.1 license
   - CC tooling (MCP servers, hooks, skills)
   - Pull-based command queue architecture
   - Build Score persistence at 4:45 PM
   - Reconciliation at 4:30 PM

---

## Task 2: Update `AGENTS.md`

1. Update ALL counts using the verification commands in `docs/sprint-checklist.md`
2. Verify the module registry matches `docs/architecture.md`
3. Update "Current System State" section with latest info from SYSTEM_STATE.md
4. Update technology stack (Claude Sonnet 4, not Haiku 4.5)
5. Replace any "Halcyon Lab" references with "Arcis"

---

## Task 3: Update `CHANGELOG.md`

Add entry for March 31, 2026:
- Sprints 5-8 merged (82 issues from 2 audits)
- Analytics migration to Postgres (#174)
- Dashboard redesign (#175)
- BSL 1.1 license
- VRAM handoff fix
- 7 missing Postgres tables
- Pre-market brief with real S&P futures + 10Y yield
- API costs fix
- WebSocket exponential backoff
- Settings.example.yaml expanded to 423 lines
- Database schema ERD added (docs/database-schema.md)
- Architecture SVG + logo SVGs in README
- CC tooling installed

---

## Task 4: Update `CLAUDE.md`

1. Rename header: "Halcyon Lab" → "Arcis"
2. Add CC sprint workflow steps (mandatory steps every sprint)
3. Update Architecture Quick Ref with current counts
4. Add reference to SYSTEM_STATE.md as source of truth
5. Add reference to docs/sprint-checklist.md

---

## Task 5: Update `frontend/public/architecture.html`

The interactive architecture diagram needs:
1. Brand: "HALCYON LAB" → "ARCIS" in header and footer
2. Update metrics bar counts (173 files, 1,235 tests, 126 routes, 40 tables)
3. Update footer: "BSL 1.1" not MIT, "77+ research docs"
4. Verify all component boxes match current system (especially training pipeline, data collectors, council)

Also update `architecture-letter.html` with same changes.

---

## Task 6: Verify Render Sync Coverage

Run this check and fix any gaps:
```python
# All SYNC_TABLES entries must have render_migrate.py CREATE TABLE
# All render_migrate.py tables should be in SYNC_TABLES if they contain data
```

---

## Mandatory Checklist (from docs/sprint-checklist.md)

Run ALL verification commands at the end:

```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "Test files:" && find tests -name "test_*.py" | wc -l
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "API routes:" && grep -rn "@router\.\|@app\." src/api/ --include="*.py" | grep "get\|post\|put\|delete" | grep -v __pycache__ | wc -l
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "Dashboard pages:" && ls frontend/src/pages/*.jsx | wc -l
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md 2>/dev/null | wc -l
echo "Sync tables:" && python3 -c "import re; f=open('src/sync/render_sync.py').read(); print(len(re.findall(r'\"(\w+)\":\s*\{', f.split('SYNC_TABLES')[1].split('\n}')[0])))"

# Frontend build
cd frontend && npm run build && cd ..

# Tests
python -m pytest tests/ -x -q
```

Update SYSTEM_STATE.md with any changes to counts.

---

## Acceptance Criteria

- [ ] `docs/architecture.md` — All 173 Python files listed, all 49 tables documented, all 126 API routes listed
- [ ] `AGENTS.md` — All counts match verification commands output
- [ ] `CHANGELOG.md` — March 31 session entry added
- [ ] `CLAUDE.md` — Renamed to Arcis, workflow steps added
- [ ] `frontend/public/architecture.html` — Arcis branding, current counts
- [ ] `frontend/public/architecture-letter.html` — Same updates
- [ ] All brand references updated (Halcyon Lab → Arcis)
- [ ] `npm run build` succeeds
- [ ] `python -m pytest tests/ -x -q` passes
- [ ] SYSTEM_STATE.md updated if any counts changed
