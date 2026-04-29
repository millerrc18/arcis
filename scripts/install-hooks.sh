#!/usr/bin/env bash
# Install repo git hooks (#59 / #699).
#
# One command activates BOTH:
#   - scripts/hooks/pre-commit  (agent scope check, #699)
#   - scripts/hooks/pre-push    (stale-base hazard refusal, #59)
#
# Run once per fresh clone. The setting is per-clone (lives in .git/config,
# not committed), so each developer/operator must run this.
#
# Worktrees: share .git/config and .git/hooks with the parent clone, so this
# install propagates to all worktrees automatically.
#
# Verification:
#   git config core.hooksPath           # must print: scripts/hooks
#   ls scripts/hooks/                   # must show: pre-commit  pre-push

set -e

# Check we're in the repo root (where scripts/hooks/ should be)
if [ ! -d scripts/hooks ]; then
    echo "ERROR: run from repo root (scripts/hooks/ not found in cwd)" >&2
    exit 1
fi

# Check the hook files exist + are executable
for hook in pre-commit pre-push; do
    if [ ! -f "scripts/hooks/$hook" ]; then
        echo "ERROR: scripts/hooks/$hook missing — repo state is broken" >&2
        exit 1
    fi
    chmod +x "scripts/hooks/$hook"
done

# Point git at the tracked hooks directory
git config core.hooksPath scripts/hooks

echo "Installed hooks: scripts/hooks/{pre-commit,pre-push}"
echo "Active for all worktrees of this clone."
echo ""
echo "Verify with: git config core.hooksPath  (should print: scripts/hooks)"
