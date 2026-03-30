# Sprint 4D: The Flywheel — AI-Agent-Friendly Repo Structure (Codex)

> **Executor:** Codex (mechanical: docstrings, AGENTS.md rewrite, file creation)
> **Scope:** 6 tasks
> **Prerequisite:** Sprint 4A MERGED
> **Can run in PARALLEL with:** Sprint 4B (no overlapping code files — 4D touches docstrings + docs, 4B touches implementations + frontend)
> **Why now:** Every future sprint gets cheaper. The repo becomes self-documenting, sprint prompts shrink from ~600 lines to ~100 lines.

---

## System Overview

Arcis (repo: `halcyon-lab`) is maintained by AI coding agents (Claude Code, Codex) as the primary developers. The goal: CC/Codex reads 2 files (AGENTS.md + conventions.md) and understands the entire codebase. No more re-explaining architecture in every sprint prompt.

### Current Baseline (from `config/known_violations.json`, already committed)
- **16 oversized files** (>400 lines) — grandfathered, warn-only
- **129 oversized functions** (>60 lines) — grandfathered, warn-only
- **138 modules missing standard docstring headers** — Task 2 fixes these
- **0 missing migrate tables** — clean

---

## Pre-Sprint Checks (MANDATORY)

```bash
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60: print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
find src -name "*.py" ! -name "__init__.py" ! -path "*__pycache__*" | wc -l
# ^ This is how many files need the standard docstring header
```

Do NOT fix file size / function length violations (those are grandfathered). Focus only on the 6 tasks below.

---

## Task 1: Rewrite AGENTS.md as Module Registry

Replace prose-heavy AGENTS.md with a structured, machine-parseable module registry.

**Keep:** Quick Stats section (counts), Purpose, Core Principle, Business Model

**Replace architecture overview with Module Registry.** Format per module:

```markdown
### src/scheduler/watch.py
- **Purpose:** Main watch loop — orchestrates scans, monitors, collectors via APScheduler
- **Called by:** CLI (`python -m src.main watch`)
- **Calls:** scan_service, executor, bracket_monitor, council.engine, telegram, render_sync
- **Owns tables:** none (orchestrator)
- **Config keys:** scheduler.*
- **Tests:** tests/test_watch_bootstrap.py
```

**List ALL modules in src/ (excluding __init__.py), grouped by directory.**

**How to determine each field:**
- **Called by:** `grep -rn "from src.{module}" src/ --include="*.py"` — who imports this?
- **Calls:** Read the import statements in the file
- **Owns tables:** `grep "CREATE TABLE" {file}` — what tables does it create?
- **Config keys:** `grep "config\[" {file}` or `grep "_cfg\|settings" {file}`
- **Tests:** Check if `tests/test_{name}.py` exists

**Also add these sections:**

Dependency Hierarchy:
```
Layer 4: Orchestration — watch.py, main.py
Layer 3: Services — scan_service.py, council/engine.py
Layer 2: Domain — executor.py, governor.py, traffic_light.py, features/*
Layer 1: Infrastructure — alpaca_adapter.py, telegram.py, render_sync.py, llm/*
```
Rule: imports only go DOWN.

"Where New Things Go" table:

| I need to... | Put it in... | Wire it into... |
|---|---|---|
| Add a feature/signal | `src/features/` | `scan_service.py` |
| Add a data collector | `src/data_collection/` | `watch.py` scheduler |
| Add an API endpoint | `src/api/cloud_routes/` | `cloud_app.py` router + `api.js` |
| Add a dashboard page | `frontend/src/pages/` | `App.jsx` routes + `Layout.jsx` nav |
| Add a DB table | `scripts/create_missing_tables.py` + `render_migrate.py` | `render_sync.py` |
| Add a notification | `src/notifications/telegram.py` | caller module |
| Add a CLI command | `src/cli/commands.py` | `main.py` subparser |
| Add a test | `tests/test_{module}.py` | auto-discovered |

---

## Task 2: Add Standard Docstring Headers to ALL Modules

Every `.py` file in `src/` (except `__init__.py`) gets this 5-field header:

```python
"""Module name — one-line description.

Called by: caller1.py, caller2.py
Calls: callee1.py, callee2.py
Owns tables: table1, table2
Config keys: section.key1, section.key2
Tests: tests/test_module.py
"""
```

**Rules:**
- If a module has an existing docstring, PREPEND the 5 fields below the first line. Keep existing content.
- If no docstring, create one with one-line description + 5 fields.
- `Called by: none` is valid for entry points. `Owns tables: none` is valid for stateless modules.
- Use the same grep techniques from Task 1 to determine each field.
- There are ~138 files that need this. Work through them systematically by directory.

---

## Task 3: Create conventions.md

Create `docs/conventions.md` — the pattern library for AI agents.

Include sections for: Adding a feature, Adding a dashboard page, Adding an API endpoint, Adding a DB table, CSS/frontend rules (use `var(--arcis-*)`, financial data class, ▲/▼ arrows mandatory), Testing conventions (≥5 tests per module, tmp_path fixtures, real SQLite over mocks), Module docstring format (the 5-field header), Sprint prompt template format.

Keep it concise — this is a reference card, not a tutorial.

---

## Task 4: Create tests/test_repo_structure.py

Automated guardrails. **Warn-only for existing violations (from `config/known_violations.json`), fail for new violations.**

```python
"""Repository structure enforcement — prevents drift."""
import ast, json, re, warnings
from pathlib import Path

KNOWN = json.loads(Path("config/known_violations.json").read_text())

def test_no_file_over_400_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py": continue
        lines = len(p.read_text().splitlines())
        if lines > 400:
            if str(p) in KNOWN.get("oversized_files", []):
                warnings.warn(f"GRANDFATHERED: {p} ({lines} lines)")
            else:
                assert False, f"NEW VIOLATION: {p} is {lines} lines (max 400)"

def test_no_function_over_60_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py": continue
        try: tree = ast.parse(p.read_text())
        except SyntaxError: continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    key = f"{p}:{node.name}"
                    if key in KNOWN.get("oversized_functions", []):
                        warnings.warn(f"GRANDFATHERED: {key} ({length} lines)")
                    else:
                        assert False, f"NEW VIOLATION: {key} is {length} lines (max 60)"

def test_all_modules_have_standard_docstring():
    required = ["Called by:", "Calls:", "Owns tables:", "Config keys:", "Tests:"]
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py": continue
        try: tree = ast.parse(p.read_text())
        except SyntaxError: continue
        has = (tree.body and isinstance(tree.body[0], ast.Expr)
               and isinstance(tree.body[0].value, ast.Constant)
               and isinstance(tree.body[0].value.value, str))
        if not has or not all(f in tree.body[0].value.value for f in required):
            if str(p) in KNOWN.get("missing_docstring_headers", []):
                warnings.warn(f"GRANDFATHERED: {p} missing standard docstring")
            else:
                missing = [f for f in required if not has or f not in tree.body[0].value.value]
                assert False, f"NEW VIOLATION: {p} missing: {missing}"

def test_every_new_table_in_render_migrate():
    migrate = Path("scripts/render_migrate.py").read_text().lower()
    for p in Path("src").rglob("*.py"):
        for line in p.read_text().splitlines():
            m = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', line, re.IGNORECASE)
            if m:
                table = m.group(1).lower()
                if table not in migrate:
                    if table in KNOWN.get("missing_migrate_tables", []):
                        warnings.warn(f"GRANDFATHERED: table '{table}'")
                    else:
                        assert False, f"NEW VIOLATION: table '{table}' in {p} not in render_migrate.py"
```

After Task 2 adds docstring headers, regenerate `known_violations.json` to reflect the smaller violation set:

```bash
python3 -c "
import ast, json, re
from pathlib import Path
violations = {'oversized_files':[], 'oversized_functions':[], 'missing_docstring_headers':[], 'missing_migrate_tables':[]}
required = ['Called by:', 'Calls:', 'Owns tables:', 'Config keys:', 'Tests:']
for p in Path('src').rglob('*.py'):
    if p.name == '__init__.py': continue
    content = p.read_text(); lines = len(content.splitlines())
    if lines > 400: violations['oversized_files'].append(str(p))
    try: tree = ast.parse(content)
    except: continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno - node.lineno > 60:
                violations['oversized_functions'].append(f'{p}:{node.name}')
    has = (tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str))
    if not has or not all(f in tree.body[0].value.value for f in required):
        violations['missing_docstring_headers'].append(str(p))
with open('config/known_violations.json','w') as f: json.dump(violations, f, indent=2)
print(f'Files: {len(violations[\"oversized_files\"])}, Functions: {len(violations[\"oversized_functions\"])}, Headers: {len(violations[\"missing_docstring_headers\"])}')
"
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

[standard guardrail checks — copy from any recent sprint]

## Tasks

1. [verb] [file path] — [one-line spec]. Ref: [doc]
2. ...

## Detailed Specs (ONLY for genuinely new/complex tasks — not system overview)

## Documentation Update (MANDATORY — always last task)

Run verification from docs/sprint-checklist.md. Update AGENTS.md counts, CHANGELOG, architecture.md.
```

---

## Task 6: Documentation Update (MANDATORY)

1. Run all verification commands from `docs/sprint-checklist.md`
2. Update AGENTS.md Quick Stats counts (should now be auto-derivable from the module registry)
3. Add Sprint 4D entry to CHANGELOG.md
4. Regenerate `config/known_violations.json` (missing_docstring_headers should be near-zero after Task 2)
5. Verify `test_repo_structure.py` passes with warnings only for grandfathered items

```bash
python -m pytest tests/test_repo_structure.py -v
python -m pytest tests/ -x -q
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
grep "Called by:" AGENTS.md | wc -l  # Should be ≥ module count
cat docs/conventions.md | head -5    # Should exist
cat docs/sprints/TEMPLATE.md | head -5  # Should exist
```

Paste and complete sprint checklist.
