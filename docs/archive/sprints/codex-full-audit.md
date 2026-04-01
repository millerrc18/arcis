# Codex Audit: Full Codebase Health Check

> **Executor:** Codex
> **Goal:** Audit the entire codebase for bugs, inconsistencies, stale code, and improvement opportunities. Open a GitHub Issue for every finding. Do NOT fix anything — only report.
> **Repo:** millerrc18/halcyon-lab (will be renamed to arcis soon)
> **Read first:** AGENTS.md, docs/conventions.md

---

## Context

Arcis is an autonomous AI-powered equity trading system. It has gone through rapid development (Sprints 1-5 plus a Codex mega PR #64) over the past week. The system is now in lockdown — paper trading autonomously. Before we let it run unattended, we need a comprehensive audit to catch anything that slipped through.

The codebase has:
- 169 Python files in src/
- 81 test files with 1,110 test functions
- 14 React dashboard pages
- 67 research documents
- 40+ SQLite tables

---

## Audit Scope

Run ALL of the following checks. For each finding, open a GitHub Issue with:
- **Title:** Clear, specific description (e.g., "Dead import in src/training/bootstrap.py")
- **Labels:** Use one of: `bug`, `tech-debt`, `security`, `performance`, `documentation`, `test-gap`
- **Body:** File path, line number(s), what's wrong, and suggested fix

---

## 1. CODE QUALITY

### 1a. Dead Code & Unused Imports
```bash
# Find unused imports in every Python file
for f in $(find src -name "*.py" ! -path "*__pycache__*"); do
    python3 -c "
import ast, sys
with open('$f') as fh:
    tree = ast.parse(fh.read())
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            imports.append(alias.asname or alias.name)
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            imports.append(alias.asname or alias.name)
# Check if each import is actually used in the file
with open('$f') as fh:
    content = fh.read()
for imp in imports:
    # Simple heuristic: import name appears only in import statement
    name = imp.split('.')[-1]
    occurrences = content.count(name)
    if occurrences <= 1:
        print(f'UNUSED IMPORT: $f — {imp}')
" 2>/dev/null
done
```

### 1b. Unreachable Code
Look for:
- Functions that are never called (defined but no caller references them anywhere in src/)
- `return` statements followed by more code
- `if False:` or `if True:` blocks
- Commented-out code blocks longer than 5 lines

### 1c. Duplicate Code
Look for functions or code blocks that are substantially duplicated across files. Flag anything where >10 lines are essentially copy-pasted.

### 1d. Exception Handling
```bash
# Find bare except clauses (should be except Exception)
grep -rn "except:" src/ --include="*.py" | grep -v "except Exception" | grep -v "__pycache__"
```
Also check for:
- Exceptions that are caught and silently swallowed (empty except blocks)
- Overly broad `except Exception` where specific exceptions should be caught
- Missing error logging in except blocks

---

## 2. SECURITY

### 2a. Hardcoded Secrets
```bash
# Search for potential hardcoded API keys, tokens, passwords
grep -rn "api_key\|api_secret\|password\|token\|secret" src/ config/ --include="*.py" --include="*.yaml" --include="*.yml" | grep -v ".env" | grep -v "__pycache__" | grep -v "os.environ" | grep -v "# " | grep -v "load_dotenv"
```
Flag any string that looks like an actual key/token rather than a variable reference.

### 2b. SQL Injection
```bash
# Find f-string or format SQL queries (potential injection)
grep -rn "f\".*SELECT\|f\".*INSERT\|f\".*UPDATE\|f\".*DELETE\|\.format.*SELECT" src/ --include="*.py" | grep -v "__pycache__"
```
All SQL should use parameterized queries (`?` placeholders), not string formatting.

### 2c. .env and .gitignore
- Verify `.env` is in `.gitignore`
- Verify no `.env` file is committed to git history
- Verify `settings.yaml` doesn't contain actual secrets (should reference env vars)
- Verify `.env.example` has all keys that the code references

---

## 3. DATA INTEGRITY

### 3a. Schema Consistency
Compare what `scripts/create_missing_tables.py` defines vs what's actually in the production schema. Check:
- Are there tables in the code's CREATE TABLE statements that aren't in `create_missing_tables.py`?
- Are there columns referenced in queries but not in any CREATE TABLE?
- Does `scripts/render_migrate.py` have Postgres versions of ALL tables in `create_missing_tables.py`?

### 3b. Missing Foreign Keys / Orphan References
Check for queries that JOIN tables — are there foreign key references that could produce orphan records? For example:
- `training_examples.recommendation_id` → does every referenced recommendation actually exist?
- `council_votes.session_id` → does every referenced session exist?

### 3c. Database Path Inconsistency
```bash
# Find all database path references
grep -rn "ai_research_desk.sqlite3\|halcyon.db\|arcis.db\|data/halcyon\|data/arcis" src/ scripts/ --include="*.py" | grep -v "__pycache__"
```
All should use a consistent path. Flag any file using a different default.

---

## 4. TEST COVERAGE

### 4a. Modules Without Tests
```bash
# List src/ modules that have no corresponding test file
for f in $(find src -name "*.py" ! -name "__init__.py" ! -path "*__pycache__*"); do
    module=$(basename "$f" .py)
    if ! find tests -name "test_*${module}*" -o -name "*${module}*test*" 2>/dev/null | grep -q .; then
        echo "NO TEST FILE: $f"
    fi
done
```

### 4b. Test Quality
Check for:
- Tests that don't actually assert anything (just call a function)
- Tests that are always skipped or marked xfail
- Tests that mock so aggressively they don't test real behavior
- Tests that depend on external services (API calls, network) without mocking

### 4c. Flaky Test Detection
```bash
# Run tests and check for any that are non-deterministic
python -m pytest tests/ -x -q --timeout=60 2>&1 | tail -20
```
Note any failures and whether they're consistent or intermittent.

---

## 5. CONFIGURATION

### 5a. Settings Consistency
- Does `config/settings.yaml` (or `settings.local.yaml`) have all keys that the code references?
- Are there config keys referenced in code that have no default value and no .env fallback?
- Are there config keys defined but never read by any code?

### 5b. Environment Variable Coverage
```bash
# Find all os.environ.get / os.getenv references
grep -rn "os.environ\|os.getenv\|environ.get" src/ --include="*.py" | grep -v "__pycache__"
```
Cross-reference with `.env.example` — every env var the code reads should be documented there.

---

## 6. FRONTEND

### 6a. Dead Components
Check `frontend/src/components/` and `frontend/src/pages/` for:
- Components that are never imported anywhere
- Pages that aren't in `App.jsx` routes
- CSS classes defined but never used

### 6b. API Consistency
```bash
# Find all API calls in frontend
grep -rn "fetchApi\|api\." frontend/src/ --include="*.js" --include="*.jsx" | grep -v node_modules
```
Cross-reference with backend routes in `src/api/cloud_routes/`. Flag:
- Frontend calls endpoints that don't exist
- Backend endpoints that no frontend page calls
- Mismatched response shapes (frontend expects fields the backend doesn't return)

### 6c. Console Errors
- Check for `console.log` statements that should be removed for production
- Check for missing error boundaries in React components

---

## 7. DOCUMENTATION

### 7a. Docstring Accuracy
For each module with a 5-field docstring header (Added by Sprint 4D):
- Is the "Called by" list accurate? (grep for imports to verify)
- Is the "Calls" list accurate? (check import statements)
- Is the "Owns tables" list accurate? (check CREATE TABLE statements)

### 7b. AGENTS.md Accuracy
- Do the Quick Stats counts match reality?
- Are all modules listed in the Module Registry?
- Is the dependency hierarchy correct?

### 7c. Stale References
```bash
# Find references to old names
grep -rn "Halcyon Lab\|halcyon-lab\|HALCYON" src/ frontend/ docs/ --include="*.py" --include="*.jsx" --include="*.js" --include="*.md" --include="*.html" | grep -v __pycache__ | grep -v node_modules | grep -v .git
```
Flag any that should say "Arcis" instead.

---

## 8. PERFORMANCE

### 8a. N+1 Queries
Look for patterns where a loop executes a SQL query per iteration instead of a single batch query.

### 8b. Missing Indexes
Check for queries that filter/sort on columns without indexes. Especially:
- `WHERE status = 'open'` on shadow_trades (high frequency)
- `WHERE created_at > datetime(...)` on any table (common pattern)
- `ORDER BY created_at DESC` on large tables

### 8c. Memory / Resource Leaks
Check for:
- Database connections opened but never closed (missing `with` context manager)
- File handles not properly closed
- Large data structures loaded into memory unnecessarily

---

## 9. DEPENDENCY HEALTH

### 9a. Outdated Dependencies
```bash
pip list --outdated 2>/dev/null | head -20
```

### 9b. Unused Dependencies
Check `requirements.txt` — are there packages listed that no code actually imports?

### 9c. Missing Dependencies
Are there imports in the code that aren't in `requirements.txt`?

---

## 10. REPO STRUCTURE

### 10a. Guardrail Violations
```bash
# Run the existing guardrail tests
python -m pytest tests/test_repo_structure.py -v 2>&1
```
Report any new violations not in `config/known_violations.json`.

### 10b. Git Hygiene
- Are there any large binary files committed (>1MB)?
- Are there any .pyc or __pycache__ directories committed?
- Is .gitignore comprehensive?

---

## Issue Labeling Guide

| Label | When to use |
|---|---|
| `bug` | Code that will produce incorrect behavior at runtime |
| `tech-debt` | Code that works but is messy, duplicated, or hard to maintain |
| `security` | Hardcoded secrets, SQL injection, auth gaps |
| `performance` | N+1 queries, missing indexes, unnecessary computation |
| `documentation` | Stale docs, inaccurate docstrings, missing docs |
| `test-gap` | Missing test coverage for important functionality |

---

## Output Format

For each finding, create a GitHub Issue. Group related findings into single issues where appropriate (e.g., "5 unused imports across src/training/" can be one issue, not five).

At the end, create a summary issue titled "Audit Summary — [DATE]" that lists:
- Total issues opened
- Breakdown by label
- Top 3 most critical findings
- Overall codebase health assessment (1-10)
