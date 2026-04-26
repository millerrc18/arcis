"""Regression tests for DB-STUB path enforcement (Sprint 0 Wave 1d).

CLAUDE.md mandate (#642): writes to <halcyon-lab>/ai_research_desk.sqlite3
or any "data/ai_research_desk.sqlite3" relative path are FORBIDDEN — the
canonical location is C:/arcis/data/ai_research_desk.sqlite3, supplied via
ARCIS_DB_PATH env var (loaded from .env).

These tests lock in the Sprint 0 Wave 1d fixes:

1. src/config/__init__.py — must hard-fail when ARCIS_DB_PATH is missing
   instead of silently falling back to <repo_root>/ai_research_desk.sqlite3
   (the stub).
2. src/services/mr_scan_service.py — must NOT contain a literal
   "data/ai_research_desk.sqlite3" stub fallback in the config.get(...)
   call for the VIX query path.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest


def _drop_dotenv_arcis_db_path(monkeypatch):
    """Make sure neither os.environ nor a .env load can supply ARCIS_DB_PATH.

    src/config/__init__.py calls load_dotenv() at import time which walks up
    directories looking for .env files. To force the hard-fail branch, we
    must (a) clear the env var in the OS, AND (b) prevent load_dotenv from
    re-populating it. We do (b) by monkeypatching dotenv.load_dotenv to a no-op.
    """
    monkeypatch.delenv("ARCIS_DB_PATH", raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    # Also patch the binding inside src.config in case it's already imported
    # and we're about to reload it — the reload will re-bind from the dotenv
    # module attribute we just neutered.


def test_db_path_raises_or_uses_canonical_when_env_missing(monkeypatch):
    """src.config import must hard-fail when ARCIS_DB_PATH is missing.

    This regression locks in the Option A fix: rather than silently falling
    back to the forbidden stub <repo_root>/ai_research_desk.sqlite3, the
    config module raises RuntimeError with a clear pointer to the canonical
    path so the operator (or CI) can correct the setup.
    """
    _drop_dotenv_arcis_db_path(monkeypatch)

    # Force a fresh import of src.config so the module-level env check runs.
    monkeypatch.delitem(sys.modules, "src.config", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        importlib.import_module("src.config")

    msg = str(excinfo.value)
    assert "ARCIS_DB_PATH" in msg, (
        f"RuntimeError must mention ARCIS_DB_PATH; got: {msg!r}"
    )
    assert "C:/arcis/data/ai_research_desk.sqlite3" in msg, (
        f"RuntimeError must point to the canonical path; got: {msg!r}"
    )


def test_db_path_uses_env_var_when_set(monkeypatch, tmp_path):
    """When ARCIS_DB_PATH is set, DB_PATH must equal the env-var value.

    Companion to the hard-fail test: confirms that the env-var override
    path still works end-to-end (no regression on the normal path).
    """
    target = str(tmp_path / "test_canonical.sqlite3")
    monkeypatch.setenv("ARCIS_DB_PATH", target)
    monkeypatch.delitem(sys.modules, "src.config", raising=False)

    cfg = importlib.import_module("src.config")
    assert cfg.DB_PATH == target, (
        f"DB_PATH {cfg.DB_PATH!r} must equal env var {target!r}"
    )


def test_no_stub_fallback_in_mr_scan_service():
    """src/services/mr_scan_service.py must NOT contain a stub-path fallback.

    Specifically asserts the forbidden pattern
        config.get("db_path", "data/ai_research_desk.sqlite3")
    has been removed. The canonical replacement is
        config.get("db_path") or DB_PATH
    where DB_PATH is imported from src.config.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    target = repo_root / "src" / "services" / "mr_scan_service.py"
    source = target.read_text(encoding="utf-8")

    # Forbidden pattern: config.get with a string literal default
    # ending in "ai_research_desk.sqlite3" (the stub anti-pattern).
    forbidden = re.compile(
        r"""config\.get\(\s*['"]db_path['"]\s*,\s*['"][^'"]*ai_research_desk\.sqlite3['"]\s*\)""",
        re.VERBOSE,
    )
    match = forbidden.search(source)
    assert match is None, (
        f"Forbidden stub fallback survived in {target}:\n  {match.group(0)!r}\n"
        "Use `config.get('db_path') or DB_PATH` (importing DB_PATH from src.config)."
    )

    # Positive assertion: the canonical pattern is present.
    assert "from src.config import" in source and "DB_PATH" in source, (
        f"{target} must import DB_PATH from src.config to use as the canonical default"
    )


def test_no_stub_fallback_in_config_module():
    """src/config/__init__.py must NOT fall back to repo-root sqlite3 stub.

    Asserts the legacy pattern
        os.environ.get("ARCIS_DB_PATH", str(_REPO_ROOT / "ai_research_desk.sqlite3"))
    has been removed in favor of an explicit hard-fail (RuntimeError) when
    the env var is missing.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    target = repo_root / "src" / "config" / "__init__.py"
    source = target.read_text(encoding="utf-8")

    # Forbidden pattern: os.environ.get with a string default that builds
    # the repo-root stub path.
    forbidden = re.compile(
        r"""os\.environ\.get\(\s*['"]ARCIS_DB_PATH['"]\s*,\s*str\(\s*_REPO_ROOT\s*/\s*['"]ai_research_desk\.sqlite3['"]\s*\)\s*\)""",
        re.VERBOSE,
    )
    match = forbidden.search(source)
    assert match is None, (
        f"Forbidden stub fallback survived in {target}:\n  {match.group(0)!r}\n"
        "Replace with an explicit RuntimeError when ARCIS_DB_PATH is unset."
    )

    # Positive assertion: the hard-fail RuntimeError is present.
    assert "raise RuntimeError" in source and "ARCIS_DB_PATH not set" in source, (
        f"{target} must hard-fail with RuntimeError when ARCIS_DB_PATH is missing"
    )
