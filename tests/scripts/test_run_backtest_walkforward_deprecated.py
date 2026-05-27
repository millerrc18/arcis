"""Tests for --with-walkforward deprecation in scripts/run_backtest.py.

#118 — Deprecate scripts/run_backtest.py --with-walkforward.
Canonical surface: /arcis:strategy backtest.

Test strategy (verify-by-mutation):
  (a) subprocess invocation with --with-walkforward: assert stderr contains
      'deprecated' AND exit code is non-zero.
  (b) mock run_walkforward + invoke with flag: assert mock.called is False
      (deprecation short-circuits before import / call).
  (c) default path (no flag): main() returns 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch


def _subprocess_env(tmp_path) -> dict:
    """Build a subprocess env with ARCIS_DB_PATH pointing at a temp SQLite file
    and PYTHONPATH pointing at the worktree root so `from src.config import
    DB_PATH` resolves without error.  The DB file need not exist — the
    deprecation exit fires before any DB access.
    """
    env = dict(os.environ)
    env["ARCIS_DB_PATH"] = str(tmp_path / "dummy.sqlite3")
    env.pop("DATABASE_URL", None)
    # Ensure the worktree root is on PYTHONPATH so `import src` works.
    worktree_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        worktree_root + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else worktree_root
    )
    return env


# ---------------------------------------------------------------------------
# (a) Subprocess — flag triggers stderr deprecation notice + non-zero exit
# ---------------------------------------------------------------------------

def test_with_walkforward_flag_exits_nonzero(tmp_path):
    """--with-walkforward must exit with non-zero code."""
    result = subprocess.run(
        [
            sys.executable, "scripts/run_backtest.py",
            "--strategy", "dummy_strategy",
            "--start", "2022-01-01",
            "--end", "2023-01-01",
            "--with-walkforward",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(tmp_path),
    )
    assert result.returncode != 0, (
        f"Expected non-zero exit when --with-walkforward is set, got {result.returncode}. "
        f"stderr={result.stderr!r}"
    )


def test_with_walkforward_flag_stderr_contains_deprecated(tmp_path):
    """--with-walkforward must print 'deprecated' to stderr."""
    result = subprocess.run(
        [
            sys.executable, "scripts/run_backtest.py",
            "--strategy", "dummy_strategy",
            "--start", "2022-01-01",
            "--end", "2023-01-01",
            "--with-walkforward",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(tmp_path),
    )
    assert "deprecated" in result.stderr.lower(), (
        f"Expected 'deprecated' in stderr. Got stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# (b) Mock path — run_walkforward must never be called when flag is set
# ---------------------------------------------------------------------------

def test_run_walkforward_not_called_when_flag_set(monkeypatch, tmp_path):
    """run_walkforward must not be called even when --with-walkforward is passed.

    Patches sys.argv and all heavy imports so main() reaches the flag-check
    without hitting the DB or strategy spec. Confirms the deprecation path
    calls sys.exit before any import/call of run_walkforward.
    """
    monkeypatch.setenv("ARCIS_DB_PATH", str(tmp_path / "dummy.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    mock_run_walkforward = MagicMock(return_value={
        "oos_efficiency": 0.80,
        "overfit_flag": False,
    })

    import importlib
    import scripts.run_backtest as run_backtest_mod

    importlib.reload(run_backtest_mod)

    mock_result = MagicMock()
    mock_result.metrics = {}

    with (
        patch("src.platform.rigor.walkforward.run_walkforward", mock_run_walkforward),
        patch.object(run_backtest_mod, "load_spec", return_value=MagicMock()),
        patch.object(
            run_backtest_mod, "_get_survivorship_haircut_bps", return_value=75
        ),
        patch.object(run_backtest_mod, "run_backtest", return_value=mock_result),
        patch("sys.argv", [
            "run_backtest.py",
            "--strategy", "dummy_strategy",
            "--start", "2022-01-01",
            "--end", "2023-01-01",
            "--with-walkforward",
        ]),
        patch("sys.stderr"),
    ):
        try:
            run_backtest_mod.main()
        except SystemExit:
            pass  # expected — deprecation path calls sys.exit(2)

    assert mock_run_walkforward.called is False, (
        "run_walkforward was invoked despite --with-walkforward being deprecated"
    )


# ---------------------------------------------------------------------------
# (c) Default path (no flag) — main() returns 0
# ---------------------------------------------------------------------------

def test_default_path_no_walkforward_flag_returns_zero(monkeypatch, tmp_path):
    """Without --with-walkforward, main() must return 0 (no regression)."""
    monkeypatch.setenv("ARCIS_DB_PATH", str(tmp_path / "dummy.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import importlib
    import scripts.run_backtest as run_backtest_mod

    importlib.reload(run_backtest_mod)

    mock_result = MagicMock()
    mock_result.metrics = {
        "n_trades": 0,
        "total_return_pct": None,
        "sharpe": None,
        "max_drawdown_pct": None,
    }
    mock_result.strategy_id = "dummy_strategy"

    with (
        patch.object(run_backtest_mod, "load_spec", return_value=MagicMock()),
        patch.object(
            run_backtest_mod, "_get_survivorship_haircut_bps", return_value=75
        ),
        patch.object(run_backtest_mod, "run_backtest", return_value=mock_result),
        patch("sys.argv", [
            "run_backtest.py",
            "--strategy", "dummy_strategy",
            "--start", "2022-01-01",
            "--end", "2023-01-01",
        ]),
    ):
        exit_code = run_backtest_mod.main()

    assert exit_code == 0, f"Expected exit code 0 without flag, got {exit_code}"
