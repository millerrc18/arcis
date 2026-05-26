"""GitArchaeology v1 — read-only git CLI wrapper for the Arcis tool suite.

Purpose: Provide a single subprocess-disciplined surface for the 7 most
         common read-only git operations. Primary client is the git-historian
         specialized agent (#108 / DD-10). All invocations go through
         src.tools._subprocess.run (no direct subprocess.run / check_output).

Called by: src.tools.gitarchaeology.__main__ (CLI entry point),
           git-historian agent (#108), any tool needing read-only git access
Calls:     src.tools.gitarchaeology.core (all 7 public ops)
Owns tables: none
Config keys: none
Tests: tests/tools/test_gitarchaeology_integration.py (T7)

FORBIDDEN ops (structural defense — NOT registered as CLI subparsers):
  git commit       — mutates history
  git push         — mutates remote
  git reset        — mutates working tree / HEAD
  git rebase       — mutates history
  git checkout     — mutates working tree (destructive variants)
  git branch -D    — destroys branches
  git clean -f     — destroys untracked files
  git cherry-pick  — mutates history
  git stash drop   — destroys stashed work
  git tag -d       — destroys tags
"""

from src.tools.gitarchaeology.core import (
    GitArchaeologyError,
    GitArgError,
    GitInvocationError,
    GitMissingError,
    GitOutputTruncatedError,
    GitParseError,
    blame,
    diff,
    log,
    merge_base,
    rev_list,
    show,
    tag_l,
)

__all__ = [
    "log",
    "blame",
    "show",
    "diff",
    "rev_list",
    "merge_base",
    "tag_l",
    "GitArchaeologyError",
    "GitInvocationError",
    "GitArgError",
    "GitParseError",
    "GitOutputTruncatedError",
    "GitMissingError",
]
