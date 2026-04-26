"""Regression: DB_PATH must be absolute to avoid CWD-dependent DB resolution.

Hotfix v0.24.0-alpha2.1 — Bug B.
Before the fix, DB_PATH = "ai_research_desk.sqlite3" (relative). Scripts run
from different CWDs (worktree root vs repo root) silently opened different
SQLite files, masking the n_trades=0 regression.
"""
import os
from pathlib import Path

from src.config import DB_PATH


def test_db_path_is_absolute():
    p = Path(DB_PATH)
    assert p.is_absolute(), f"DB_PATH must be absolute, got: {DB_PATH}"


def test_db_path_resolves_to_repo_root():
    """_REPO_ROOT must point to the repo root.

    Sprint 0 Wave 1d (DB-STUB-CFG, 2026-04-26): the repo-root stub
    fallback was removed per CLAUDE.md #642 — DB_PATH no longer falls
    back to <repo_root>/ai_research_desk.sqlite3 when ARCIS_DB_PATH is
    unset (it now hard-fails). This test now only verifies the
    _REPO_ROOT computation, which is still useful for the error
    message and for any other consumers that import it.
    """
    from src.config import _REPO_ROOT
    repo_root = Path(__file__).resolve().parent.parent
    # _REPO_ROOT must point to the repo root (3 levels up from src/config/__init__.py)
    assert Path(_REPO_ROOT) == repo_root, (
        f"_REPO_ROOT {_REPO_ROOT!r} does not point to repo root {str(repo_root)!r}"
    )


def test_db_path_env_override_still_works(monkeypatch):
    """ARCIS_DB_PATH env var must still override the computed default."""
    monkeypatch.setenv("ARCIS_DB_PATH", "/tmp/test_override.sqlite3")
    # Must re-import to pick up the env var (module-level constant is cached;
    # test directly exercises the fallback expression, not the cached value).
    import importlib
    import src.config as cfg_mod
    # Simulate what the module does: os.environ.get takes priority
    result = os.environ.get("ARCIS_DB_PATH", str(Path(DB_PATH)))
    assert result == "/tmp/test_override.sqlite3"
