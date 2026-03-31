# Conventions — Halcyon Lab Pattern Library

> Reference card for AI agents (Claude Code, Codex). Read this + AGENTS.md to understand the entire codebase.

## Module Docstring Format

Every `.py` file in `src/` (except `__init__.py`) must have this 5-field header:

```python
"""Module name — one-line description.

Called by: caller1.py, caller2.py
Calls: callee1.py, callee2.py
Owns tables: table1, table2
Config keys: section.key1, section.key2
Tests: tests/test_module.py
"""
```

Use `none` for empty fields. Entry points use `Called by: none (entry point)`.

## Adding a Feature / Signal

1. Create `src/features/{name}.py` with standard docstring header
2. Wire it into `src/services/scan_service.py` (import + call in scan pipeline)
3. Add test at `tests/test_{name}.py` (minimum 5 tests)
4. Update AGENTS.md module registry entry

## Adding a Data Collector

1. Create `src/data_collection/{name}_collector.py` with standard docstring header
2. Add the table creation in the collector (use `CREATE TABLE IF NOT EXISTS`)
3. Add the table to `scripts/render_migrate.py` for cloud sync
4. Wire into `src/scheduler/watch.py` overnight collection schedule
5. Add test at `tests/test_data_collectors.py` or dedicated test file
6. Update AGENTS.md module registry + data sources section

## Adding an API Endpoint

1. **Local dashboard:** Add route in `src/api/routes/{module}.py`, register in `src/api/app.py`
2. **Cloud (Render):** Add route in `src/api/cloud_routes/{module}.py`, register in `src/api/cloud_app.py`
3. Add corresponding frontend call in `frontend/src/api.js`
4. Add test in `tests/test_local_api_routes.py` or `tests/test_cloud_app.py`

## Adding a Dashboard Page

1. Create `frontend/src/pages/{PageName}.jsx`
2. Add route in `frontend/src/App.jsx`
3. Add nav entry in `frontend/src/components/Layout.jsx`
4. Use existing CSS variables: `var(--arcis-*)` palette
5. Financial data must use class `financial-data` for monospace rendering
6. Price changes must show directional arrows: `▲` green / `▼` red

## Adding a DB Table

1. Add `CREATE TABLE IF NOT EXISTS` in the owning module
2. Add the same `CREATE TABLE` to `scripts/render_migrate.py`
3. If the table needs cloud sync, add it to `src/sync/render_sync.py` config
4. Update AGENTS.md module registry (Owns tables field)

## CSS / Frontend Rules

- Use `var(--arcis-*)` CSS custom properties — never hardcode colors
- Financial data: wrap in `<span class="financial-data">` for monospace
- Directional arrows are mandatory: `▲` (green, positive) / `▼` (red, negative)
- Use Tailwind utility classes where possible
- Component files: PascalCase (`TradeCard.jsx`), pages: PascalCase (`Council.jsx`)

## Testing Conventions

- Minimum **5 tests per module** for new modules
- Use `tmp_path` fixtures for any file/DB operations — never write to repo paths
- Use **real SQLite** over mocks — our tests are integration tests
- Test file naming: `tests/test_{module_name}.py`
- Tests are auto-discovered by pytest — no registration needed
- Fixtures go in `tests/conftest.py` for shared state

## File Size Guardrails

- **Max 400 lines per file** — enforced by `tests/test_repo_structure.py`
- **Max 60 lines per function** — enforced by `tests/test_repo_structure.py`
- Existing violations are grandfathered in `config/known_violations.json` (warn-only)
- New violations fail CI

## Dependency Hierarchy

```
Layer 4: Orchestration — watch.py, main.py
Layer 3: Services — scan_service.py, council/engine.py, *_service.py
Layer 2: Domain — executor.py, governor.py, traffic_light.py, features/*, ranker.py
Layer 1: Infrastructure — alpaca_adapter.py, telegram.py, render_sync.py, llm/client.py
```

**Rule:** Imports only go DOWN. Never import from a higher layer.

## Sprint Prompt Template

Use `docs/sprints/TEMPLATE.md` for new sprint prompts. Key rules:
- Always include pre-sprint guardrail checks
- Reference AGENTS.md + conventions.md as required reading
- End with mandatory documentation update task
- Use `docs/sprint-checklist.md` verification commands

## Config Access Pattern

```python
from src.config import load_config
cfg = load_config()
value = cfg.get("section", {}).get("key", default)
```

Config lives in `config/settings.yaml` (gitignored). See `config/settings.example.yaml` for structure.

## Commit / PR Conventions

- Branch from `main`
- PR titles: imperative mood, concise (`Add bracket monitor health checks`)
- Squash merge preferred for feature branches
- Run `python -m pytest tests/ -x -q` before pushing
