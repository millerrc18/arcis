# Sprint N: Title

> **Executor:** [Claude Code / Codex]
> **Scope:** [N] tasks
> **Prerequisite:** [what must be merged first]
> **Read first:** MASTER.md (especially Section 9: Conventions & Rules)

---

## Pre-Sprint Checks (MANDATORY)

```bash
# File size guardrails (warn-only for grandfathered)
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrails (warn-only for grandfathered)
python -c "
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

# Test count baseline
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'

# Module count
find src -name "*.py" ! -name "__init__.py" ! -path "*__pycache__*" | wc -l
```

Do NOT fix file size / function length violations (those are grandfathered). Focus only on the tasks below.

---

## Tasks

1. [verb] [file path] — [one-line spec]. Ref: [doc]
2. ...

---

## Detailed Specs (ONLY for genuinely new/complex tasks — not system overview)

### Task N: Title

[Detailed specification only if needed]

---

## Documentation Update (MANDATORY — always last task)

1. Run `python scripts/verify_docs.py` to check documentation drift
2. Update MASTER.md Section 2 counts
3. Add sprint entry to CHANGELOG.md
4. Regenerate `config/known_violations.json` if docstrings or structure changed
5. Verify `test_repo_structure.py` passes with warnings only for grandfathered items

```bash
python -m pytest tests/test_repo_structure.py -v
python -m pytest tests/ -x -q
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Paste and complete sprint checklist.
