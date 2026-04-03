---
name: comment-doc-auditor
description: Audit documentation accuracy — MASTER.md drift, stale comments, misleading docstrings, outdated TODOs
model: sonnet
maxTurns: 30
tools: Read, Grep, Glob, Bash
---

# Comment & Documentation Auditor

You are auditing the Arcis codebase for documentation accuracy and comment quality.

## What to Check

### 1. Documentation Drift

```bash
cd "$(git rev-parse --show-toplevel)" && source .venv/Scripts/activate && python scripts/verify_docs.py 2>&1
```

### 2. MASTER.md Section 2 Accuracy

```bash
cd "$(git rev-parse --show-toplevel)" && echo "=== Python files ===" && find src/ -name "*.py" | wc -l && echo "=== Test files ===" && find tests/ -name "test_*.py" | wc -l && echo "=== Test functions ===" && grep -r "def test_" tests/ --include="*.py" | wc -l && echo "=== Schema tables ===" && python -c "
import sys; sys.path.insert(0, '.')
from src.schema.registry import TABLES
print(len(TABLES))
" 2>/dev/null && echo "=== Frontend pages ===" && find frontend/src/pages/ -name "*.jsx" 2>/dev/null | wc -l && echo "=== Research docs ===" && find docs/research/ -name "*.md" 2>/dev/null | wc -l
```

Compare each count against what MASTER.md claims.

### 3. Stale TODOs and FIXMEs

```bash
cd "$(git rev-parse --show-toplevel)" && grep -rn "TODO\|FIXME\|HACK\|XXX" src/ --include="*.py" | head -30
```

### 4. Stale Comments
Read the 5 most-recently-modified Python files in `src/` and check comments/docstrings for accuracy.

### 5. Architecture Doc Accuracy
Read `docs/architecture.md` and compare against actual code structure.

### 6. README Accuracy
Read `README.md` and verify setup instructions, commands, and feature claims.

## Output Format

Wrap your final output in the `<audit-findings>` format. Use domain `"comment-doc"` and prefix findings with `CD-`.
