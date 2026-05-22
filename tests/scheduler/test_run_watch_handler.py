"""Smoke tests for scripts/run_watch_handler.py (the watch-handler dispatcher).

Asserts --list prints exactly the 16 ALL_HANDLERS names (maybe_-stripped)
and that doing so does NOT import the heavy WatchLoop module.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.scheduler.watch_handlers import ALL_HANDLERS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_watch_handler.py"


def _load_dispatcher():
    spec = importlib.util.spec_from_file_location("_run_watch_handler_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_names():
    return {
        (h.__name__[len("maybe_"):] if h.__name__.startswith("maybe_") else h.__name__)
        for h in ALL_HANDLERS
    }


def test_script_file_exists():
    assert _SCRIPT.is_file(), f"dispatcher missing at {_SCRIPT}"


def test_list_prints_all_handler_names(capsys):
    module = _load_dispatcher()
    rc = module.main(["--list"])
    assert rc == 0
    printed = {ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip()}
    assert printed == _expected_names()


def test_list_prints_seventeen_names(capsys):
    module = _load_dispatcher()
    module.main(["--list"])
    printed = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(printed) == 17, f"expected 17 handler names, got {len(printed)}: {printed}"


def test_unknown_handler_exits_nonzero():
    module = _load_dispatcher()
    with pytest.raises(SystemExit):
        module.main(["--handler", "no_such_handler"])


def test_list_does_not_import_watchloop():
    """--list must run without constructing the heavy WatchLoop (deferred import)."""
    code = (
        "import importlib.util, sys; "
        f"spec = importlib.util.spec_from_file_location('rwh', r'{_SCRIPT}'); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod); "
        "rc = mod.main(['--list']); "
        "assert rc == 0, rc; "
        "assert 'src.scheduler.watch' not in sys.modules, 'WatchLoop was imported by --list'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
