# Sprint 4D: The Flywheel — AI-Agent-Friendly Repo Structure

> **Executor:** Codex (mechanical: docstrings, AGENTS.md rewrite, test file creation)
> **Scope:** 6 tasks
> **Prerequisite:** Sprint 4A merged (Arcis branding in place)
> **Can run in parallel with:** Sprint 4B (no overlapping files)
> **Why now:** Every future sprint gets cheaper after this. The repo becomes self-documenting, so sprint prompts shrink from ~600 lines to ~100 lines.

---

## System Overview

You are working on Arcis (GitHub repo: `halcyon-lab`), an autonomous AI-powered equity trading system.

This sprint makes the repo optimized for AI coding agents (Claude Code, Codex) as the primary maintainers. The goal: CC/Codex reads 2 files (AGENTS.md + conventions.md) and understands the entire codebase. No more 600-line sprint prompts.

### Current Baseline (from config/known_violations.json, already generated)
- **16 oversized files** (>400 lines) — grandfathered, warn-only
- **129 oversized functions** (>60 lines) — grandfathered, warn-only
- **138 modules missing standard docstring headers** — Task 2 fixes these
- **0 missing migrate tables** — clean

The `config/known_violations.json` file is already committed with the full list. The test_repo_structure.py test (Task 4) uses this file to distinguish grandfathered violations from new ones.

---

## Pre-Sprint Checks (MANDATORY)

```bash
# File size guardrail
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"

# Count modules that need docstring headers
find src -name "*.py" ! -name "__init__.py" ! -path "*__pycache__*" | wc -l
# This is how many files need the standard header

# Current test count baseline
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Fix file size / function length violations BEFORE starting feature work.

---

## Task 1: Rewrite AGENTS.md as Machine-Readable Module Registry

Replace the current prose-heavy AGENTS.md with a structured module registry.

**Keep:** The Quick Stats section (auto-verifiable counts), Purpose, Core Principle, Business Model
**Replace:** The architecture overview and data sources sections with a Module Registry

### Format for each module:

```markdown
### src/scheduler/watch.py
- **Purpose:** Main watch loop — orchestrates scans, monitors, collectors via APScheduler
- **Called by:** CLI (`python -m src.main watch`)
- **Calls:** scan_service, executor, bracket_monitor, council.engine, telegram, render_sync
- **Owns tables:** (none — orchestrator only)
- **Config keys:** scheduler.*
- **Tests:** tests/test_watch_bootstrap.py
```

### Must include ALL modules in src/ (excluding __init__.py files)

Group by directory:
- `src/scheduler/` — Watch loop and scheduling
- `src/services/` — Core business logic (scan pipeline)
- `src/features/` — Feature engineering and signals
- `src/risk/` — Risk management
- `src/shadow_trading/` — Trade execution
- `src/council/` — AI council (10 modules)
- `src/evaluation/` — Scoring and evaluation
- `src/training/` — Training pipeline
- `src/data_collection/` — Overnight data collectors
- `src/llm/` — LLM client and validation
- `src/notifications/` — Telegram and email
- `src/sync/` — Render Postgres sync
- `src/api/` — FastAPI cloud and local routes
- `src/cli/` — CLI command handlers
- `src/journal/` — Trade journal

### Also include these sections:

**Dependency Hierarchy:**
```
Layer 4: Orchestration — watch.py, main.py (can import anything below)
Layer 3: Services — scan_service.py, council/engine.py (can import Layer 2)
Layer 2: Domain — executor.py, governor.py, traffic_light.py, features/* (can import Layer 1)
Layer 1: Infrastructure — alpaca_adapter.py, telegram.py, render_sync.py, llm/* (no domain imports)
```

**Where New Things Go:**

| I need to... | Put it in... | Wire it into... |
|---|---|---|
| Add a feature/signal | src/features/new_signal.py | scan_service.py |
| Add a data collector | src/data_collection/new_collector.py | watch.py scheduler |
| Add an API endpoint | src/api/cloud_routes/{group}.py | cloud_app.py router + api.js |
| Add a dashboard page | frontend/src/pages/PageName.jsx | App.jsx routes + Layout.jsx nav |
| Add a DB table | scripts/create_missing_tables.py + render_migrate.py | render_sync.py |
| Add a notification | src/notifications/telegram.py (new function) | caller module |
| Add a CLI command | src/cli/commands.py | main.py subparser |
| Add a test | tests/test_{module_name}.py | (auto-discovered) |

**To determine the module registry content:** Read each .py file's existing docstring and imports. The "Called by" field comes from grepping which other files import this module. The "Calls" field comes from this module's import statements. The "Owns tables" field comes from any CREATE TABLE statements in the module. The "Config keys" field comes from any config/settings references.

---

## Task 2: Add Standard Docstring Headers to ALL Modules

Every .py file in src/ (except __init__.py) gets this header format:

```python
"""Module name — one-line description.

Called by: caller1.py, caller2.py
Calls: callee1.py, callee2.py
Owns tables: table_name1, table_name2
Config keys: section.key1, section.key2
Tests: tests/test_this_module.py
"""
```

**Rules:**
- If a module has an existing docstring, PREPEND the 5 structured fields below the first line. Don't delete existing content.
- If a module has no docstring, create one with the one-line description + 5 fields.
- "Called by: none" is valid for entry points (main.py, watch.py)
- "Owns tables: none" is valid for stateless modules
- "Config keys: none" is valid for modules that don't read settings

**How to determine each field:**
- **Called by:** `grep -rn "from src.{this_module}" src/ --include="*.py"` — which files import this one?
- **Calls:** Read the import statements at the top of this file
- **Owns tables:** `grep "CREATE TABLE" {this_file}` — which tables does this module create?
- **Config keys:** `grep "config\[" {this_file}` or `grep "settings" {this_file}` — what config does it read?
- **Tests:** Check if a matching test file exists in tests/

---

## Task 3: Create conventions.md

Create `docs/conventions.md` — the pattern library that CC/Codex reads alongside AGENTS.md.

```markdown
# conventions.md — How We Build Things in Arcis

## Adding a new feature/signal
1. Create `src/features/feature_name.py` with standard docstring header
2. Write tests in `tests/test_feature_name.py` (≥5 tests)
3. Wire into caller (usually `scan_service.py`)
4. If it needs an API: add route to `src/api/cloud_routes/{group}.py` + method to `frontend/src/api.js`
5. If it needs a DB table: add to `scripts/create_missing_tables.py` + `scripts/render_migrate.py` + `src/sync/render_sync.py`
6. If it needs Render sync: add to sync config in `render_sync.py`
7. Update AGENTS.md module registry entry

## Adding a dashboard page
1. Create `frontend/src/pages/PageName.jsx`
2. Add route in `frontend/src/App.jsx`
3. Add nav item in `frontend/src/components/Layout.jsx`
4. Add API methods in `frontend/src/api.js`
5. Update AGENTS.md dashboard page count

## Adding an API endpoint
1. Add route to `src/api/cloud_routes/{group}.py`
2. Add corresponding method to `frontend/src/api.js`
3. Update AGENTS.md API route count

## Adding a DB table
1. Add CREATE TABLE to `scripts/create_missing_tables.py` (SQLite)
2. Add CREATE TABLE to `scripts/render_migrate.py` (Postgres)
3. Add sync config entry to `src/sync/render_sync.py`
4. Update AGENTS.md DB table count

## CSS / Frontend
- Use `var(--arcis-*)` CSS variables for ALL colors (no hardcoded hex)
- Financial data: `className="financial-data"` (JetBrains Mono, tabular-nums)
- All P&L values MUST include ▲/▼ arrows alongside green/red (colorblind accessibility)
- Mobile-first: single column layout, no horizontal scroll
- Use `useQuery` hooks with 60-second refetch intervals

## Testing
- ≥5 tests per new module
- Use pytest fixtures with `tmp_path` for DB isolation
- Test happy path, edge cases, error handling
- Prefer real SQLite over mocked queries
- Test file naming: `tests/test_{module_name}.py`

## Module docstring format (MANDATORY)
Every .py file in src/ (except __init__.py):
```
"""Module name — one-line description.

Called by: caller1.py, caller2.py
Calls: callee1.py, callee2.py
Owns tables: table1, table2
Config keys: section.key1
Tests: tests/test_module.py
"""
```

## Sprint prompt format (for writing future sprints)
```
# Sprint N: Title

> Read AGENTS.md first. Read docs/conventions.md for patterns.
> Prerequisite: [what must be merged first]

## Pre-Sprint Checks
[standard guardrail checks]

## Tasks
1. [verb] [file path] — [one-line description]. See spec: [reference doc]
2. ...

## Detailed Specs (only for genuinely new/complex things)
[specs here — NOT system overview, NOT architecture, NOT CSS variables]
```
```

---

## Task 4: Create tests/test_repo_structure.py

Automated guardrails that run with every test suite.

**Approach: warn-only for existing files, strict for new files.**

Create a `config/known_violations.json` file listing current violations:
```json
{
  "oversized_files": ["src/some/large_file.py"],
  "oversized_functions": ["src/some/file.py:long_function_name"],
  "missing_docstring_headers": ["src/some/old_module.py"]
}
```

The test uses this allowlist: violations in the list produce warnings (printed but don't fail). Violations NOT in the list fail the test.

```python
"""Repository structure enforcement — prevents drift.

New files/functions must comply. Existing violations are grandfathered
in config/known_violations.json and produce warnings, not failures.
"""
import ast
import json
import re
import warnings
from pathlib import Path

KNOWN = json.loads(Path("config/known_violations.json").read_text())

def test_no_file_over_400_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        lines = len(p.read_text().splitlines())
        if lines > 400:
            if str(p) in KNOWN.get("oversized_files", []):
                warnings.warn(f"GRANDFATHERED: {p} is {lines} lines")
            else:
                assert False, f"NEW VIOLATION: {p} is {lines} lines (max 400)"

def test_no_function_over_60_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    key = f"{p}:{node.name}"
                    if key in KNOWN.get("oversized_functions", []):
                        warnings.warn(f"GRANDFATHERED: {key} is {length} lines")
                    else:
                        assert False, f"NEW VIOLATION: {key} is {length} lines (max 60)"

def test_all_modules_have_standard_docstring():
    required_fields = ["Called by:", "Calls:", "Owns tables:", "Config keys:", "Tests:"]
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        # Check module-level docstring exists
        has_docstring = (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        )
        if not has_docstring or not all(f in tree.body[0].value.value for f in required_fields):
            if str(p) in KNOWN.get("missing_docstring_headers", []):
                warnings.warn(f"GRANDFATHERED: {p} missing standard docstring")
            else:
                missing = [f for f in required_fields if not has_docstring or f not in tree.body[0].value.value]
                assert False, f"NEW VIOLATION: {p} missing docstring fields: {missing}"

def test_every_new_table_in_render_migrate():
    migrate = Path("scripts/render_migrate.py").read_text().lower()
    for p in Path("src").rglob("*.py"):
        for line in p.read_text().splitlines():
            m = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', line, re.IGNORECASE)
            if m:
                table = m.group(1).lower()
                if table not in migrate:
                    # Check known violations
                    if table in KNOWN.get("missing_migrate_tables", []):
                        warnings.warn(f"GRANDFATHERED: table '{table}' not in render_migrate.py")
                    else:
                        assert False, f"NEW VIOLATION: table '{table}' in {p} not in render_migrate.py"
```

**`config/known_violations.json` is already generated and committed.** It contains 16 oversized files, 129 oversized functions, and 138 missing docstring headers as the grandfathered baseline. Do NOT regenerate it — the baseline was captured before Sprint 4D started. After Task 2 adds docstring headers, the `missing_docstring_headers` list will shrink to near-zero, which is expected. Update the JSON file at the end of this sprint to reflect the new (smaller) violation set.

```bash
# POST-SPRINT ONLY: Regenerate known_violations.json after Task 2 adds headers
# This updates the baseline to reflect the smaller violation set
python3 -c "
import ast, json, re
from pathlib import Path

violations = {
    'oversized_files': [],
    'oversized_functions': [],
    'missing_docstring_headers': [],
    'missing_migrate_tables': []
}

required_fields = ['Called by:', 'Calls:', 'Owns tables:', 'Config keys:', 'Tests:']

for p in Path('src').rglob('*.py'):
    if p.name == '__init__.py':
        continue
    content = p.read_text()
    lines = len(content.splitlines())

    if lines > 400:
        violations['oversized_files'].append(str(p))

    try:
        tree = ast.parse(content)
    except SyntaxError:
        continue

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno
            if length > 60:
                violations['oversized_functions'].append(f'{p}:{node.name}')

    has_docstring = (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    )
    if not has_docstring or not all(f in tree.body[0].value.value for f in required_fields):
        violations['missing_docstring_headers'].append(str(p))

print(json.dumps(violations, indent=2))
" > config/known_violations.json
```

---

## Task 5: Create Sprint Prompt Template

Create `docs/sprints/TEMPLATE.md`:

```markdown
# Sprint N: Title

> **Executor:** [Claude Code / Codex]
> **Scope:** [N] tasks
> **Prerequisite:** [what must be merged first]
> **Read first:** AGENTS.md, docs/conventions.md

## Pre-Sprint Checks (MANDATORY)

\```bash
# File size guardrail
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"

# Current test count baseline
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
\```

Fix any violations BEFORE starting feature work.

## Tasks

1. [verb] [file path] — [one-line spec]. Reference: [doc or spec file]
2. ...

## Detailed Specs (only for genuinely new/complex tasks)

[Only include specs for things that AGENTS.md + conventions.md don't already cover]

## Documentation Update (MANDATORY — always the last task)

Run verification commands from docs/sprint-checklist.md. Update AGENTS.md counts, CHANGELOG.md, architecture.md.
```

---

## Task 6: Documentation Update (MANDATORY)

1. Run all verification commands from `docs/sprint-checklist.md`
2. Update AGENTS.md Quick Stats counts
3. Add Sprint 4D entry to CHANGELOG.md
4. Verify the new test_repo_structure.py passes (with grandfathered violations producing warnings only)

---

## Final Verification

```bash
# 1. All tests pass (including new test_repo_structure.py)
python -m pytest tests/ -x -q

# 2. test_repo_structure.py specifically
python -m pytest tests/test_repo_structure.py -v

# 3. AGENTS.md has module registry format
grep "Called by:" AGENTS.md | wc -l
# Should be ≥ number of modules in src/

# 4. conventions.md exists
cat docs/conventions.md | head -5

# 5. Sprint template exists
cat docs/sprints/TEMPLATE.md | head -5

# 6. known_violations.json exists
cat config/known_violations.json | python3 -m json.tool | head -10

# 7. Test count hasn't decreased
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

---

## Sprint Checklist

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item before marking this sprint done.
