#!/usr/bin/env bash
# Pre-commit scope check hook (#699 deliverable 2).
#
# Reads agent-declared scope from .claude/agent-scope.json (written by the
# PM at dispatch time) and compares against the file list in staged changes.
# Fails if any staged file is outside the declared scope.
#
# Bypass:
#   SCOPE_CHECK_BYPASS=1 git commit ...   — skip for legitimate cross-scope commits
#
# agent-scope.json format:
#   {
#     "agent_id": "developer-1",
#     "files_in_scope": ["src/foo.py", "tests/test_foo.py"]
#   }
#
# Install (one-time per worktree):
#   cp scripts/hooks/check_agent_scope.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit

set -euo pipefail

SCOPE_FILE=".claude/agent-scope.json"

# Bypass: operator or CI explicitly allows cross-scope commits
if [[ "${SCOPE_CHECK_BYPASS:-0}" == "1" ]]; then
    exit 0
fi

# No scope file — hook is a no-op (single-agent or non-agent commit)
if [[ ! -f "$SCOPE_FILE" ]]; then
    exit 0
fi

# Parse agent_id and files_in_scope from JSON using python (always available)
AGENT_ID=$(python -c "
import json, sys
d = json.load(open('$SCOPE_FILE'))
print(d.get('agent_id', 'unknown'))
" 2>/dev/null || echo "unknown")

SCOPE_FILES=$(python -c "
import json, sys
d = json.load(open('$SCOPE_FILE'))
for f in d.get('files_in_scope', []):
    print(f)
" 2>/dev/null)

if [[ -z "$SCOPE_FILES" ]]; then
    # Empty scope list — treat as unconstrained (no check)
    exit 0
fi

# Get staged files
STAGED=$(git diff --cached --name-only)

if [[ -z "$STAGED" ]]; then
    exit 0
fi

VIOLATIONS=()
while IFS= read -r staged_file; do
    if ! echo "$SCOPE_FILES" | grep -qxF "$staged_file"; then
        VIOLATIONS+=("$staged_file")
    fi
done <<< "$STAGED"

if [[ ${#VIOLATIONS[@]} -gt 0 ]]; then
    echo "SCOPE CHECK FAILED: agent '$AGENT_ID' attempted to commit files outside declared scope." >&2
    echo "" >&2
    echo "Staged files outside scope:" >&2
    for v in "${VIOLATIONS[@]}"; do
        echo "  $v" >&2
    done
    echo "" >&2
    echo "Declared scope (from $SCOPE_FILE):" >&2
    echo "$SCOPE_FILES" | sed 's/^/  /' >&2
    echo "" >&2
    echo "To bypass: SCOPE_CHECK_BYPASS=1 git commit ..." >&2
    exit 1
fi

exit 0
