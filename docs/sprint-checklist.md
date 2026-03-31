# MANDATORY DOCUMENTATION CHECKLIST

> **Append this section to EVERY CC sprint prompt. No sprint is complete until every applicable item is verified.**

## Tier 1: Update EVERY Sprint (mandatory)

- [ ] **AGENTS.md** — Verify ALL counts match code reality:
  - Python file count (`find src -name "*.py" | wc -l`)
  - Total LOC (`find src -name "*.py" -exec wc -l {} + | tail -1`)
  - Test file count and test function count
  - Database table count (grep CREATE TABLE across all files)
  - API route count (grep route decorators across all `src/api/**/*.py`)
  - CLI command count (grep add_parser in main.py)
  - Dashboard page count (ls frontend/src/pages/)
  - Data source count (enrichment + collection)
  - Research doc count (ls docs/research/)
  - Notification type count (grep "def notify_" in telegram.py)
- [ ] **CHANGELOG.md** — Add sprint entry with date, feature list, and counts
- [ ] **docs/architecture.md** — Update if any of these changed:
  - Database tables (new tables, new columns)
  - API endpoints (new routes)
  - Module structure (new files, renamed files)
  - Data flow (new integrations)
  - Configuration keys (new settings)
- [ ] **README.md** — Update if major features or setup steps changed

## Tier 2: Update When Applicable

- [ ] **docs/cli-reference.md** — If any CLI commands were added, removed, or changed
- [ ] **docs/telegram-commands.md** — If any Telegram commands/notifications were added
- [ ] **config/settings.example.yaml** — If any new config keys were added to code
- [ ] **frontend/src/api.js** — If any new API endpoints were added to cloud_app.py
- [ ] **render.yaml** — If any new services, env vars, or build steps changed
- [ ] **docs/roadmap.md** + **docs/roadmap-complete.md** — If phase gates, strategy decisions, or timeline changed
- [ ] **frontend/src/pages/Roadmap.jsx** — Must match roadmap docs
- [ ] **scripts/render_migrate.py** — If any new Postgres tables or columns were added
- [ ] **scripts/create_missing_tables.py** — If any new SQLite tables were added

## Tier 3: Update Periodically (flag if stale)

- [ ] **Architecture Diagram** (`frontend/public/architecture.html`) — If any system component was added, removed, or changed. This is the visual source of truth.
- [ ] **Arcis Framework v2** — If research findings change strategy, training, or infrastructure decisions
- [ ] **docs/system-state-YYYY-MM-DD.md** — Generate new snapshot after major sprints

## Verification Commands

Run these at the end of every sprint to catch drift:

```bash
# Count verification
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "LOC:" && find src -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
echo "Test files:" && find tests -name "*.py" | wc -l
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "API routes:" && rg -n "@(app|router)\.(get|post|put|delete|patch)" src/api --glob '*.py' | wc -l
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "Dashboard pages:" && ls frontend/src/pages/*.jsx | wc -l
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md docs/research/*.pdf docs/research/*.docx 2>/dev/null | wc -l

# Frontend build
cd frontend && npm run build && cd ..

# Tests
python -m pytest tests/ -x -q
```

## Anti-Patterns to Avoid

- **Never skip docs "because it's a small change"** — small changes accumulate into large drift
- **Never update counts without running the verification commands** — guessing counts is worse than stale counts
- **Never add a config key to code without adding it to settings.example.yaml** — breaks new installations
- **Never add an API route without adding it to api.js** — breaks the frontend
- **Never add a DB table without adding it to render_migrate.py** — breaks cloud sync
