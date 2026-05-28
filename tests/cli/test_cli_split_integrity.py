"""Sentinel — cli/commands.py category-split integrity (Phase 5 PR-C T13).

This is a boundary-touch test for the seam between the re-export facade
(src/cli/commands.py) and (a) its three category sub-modules and (b) the
argparse dispatch entry point (src/main.py / `python -m src.main`).

Cites docs/standards/boundary-touch-tests.md — the CLI entry-point seam is
exactly the "mock target vs real call site" / "symbol-rename" class the
standard targets: a re-export that silently shadows or drops a command would
pass naive unit tests while breaking the dispatch contract.

DD-40 CORRECTION (kin #19): the original T13 design demanded a decorator-
preservation + audit_log sentinel. That premise was FALSE — src/cli has no
@prod_guard/@safety_window decorators and no audit_log table (that
architecture lives in src/tools/, a different subsystem). Per the coordinator
decision this sentinel substitutes two REAL non-vacuous checks for the
impossible one:

  1. Re-export import-identity — the facade exposes the SAME function object
     as the sub-module (`is`), proving it re-exports rather than redefining /
     wrapping the command.
  2. CLI dispatch smoke — `python -m src.main <cmd> --help` exits 0 and the
     command name appears in help, proving the re-exported command is still
     wired into the argparse dispatch (the split dropped no command from the
     entry point).
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import src.cli.commands as facade
import src.cli.commands_data as data_mod
import src.cli.commands_ops as ops_mod
import src.cli.commands_training as training_mod


# Map each moved command to the sub-module it now lives in. If the split
# moves a command between categories, update this map — that is the point:
# the map is the human-auditable record of where each command landed.
_DATA_COMMANDS = [
    "cmd_ingest", "cmd_scan", "cmd_morning_watchlist", "cmd_eod_recap",
    "cmd_shadow_status", "cmd_shadow_history", "cmd_shadow_close",
    "cmd_shadow_account", "cmd_live_status", "cmd_live_history",
    "cmd_live_close", "cmd_reconcile_live", "cmd_collect_data",
    "cmd_fetch_earnings", "cmd_halt_trading", "cmd_resume_trading",
    "cmd_cancel_all_pending",
]
_TRAINING_COMMANDS = [
    "cmd_review", "cmd_mark_executed", "cmd_review_scorecard",
    "cmd_review_bootcamp", "cmd_postmortems", "cmd_postmortem_detail",
    "cmd_training_status", "cmd_training_history", "cmd_training_report",
    "cmd_bootstrap_training", "cmd_backfill_training", "cmd_train",
    "cmd_classify_training", "cmd_score_training", "cmd_validate_training",
    "cmd_generate_contrastive", "cmd_generate_preferences", "cmd_cto_report",
    "cmd_evaluate_holdout", "cmd_model_evaluation_status", "cmd_promote_model",
    "cmd_feature_importance", "cmd_backtest", "cmd_compare_models",
    "cmd_check_leakage", "cmd_run_promotion_gate", "cmd_train_pipeline",
    "cmd_evaluate_gate", "cmd_performance_report", "cmd_council",
]
_OPS_COMMANDS = [
    "cmd_init_db", "cmd_demo_packet", "cmd_send_test_email",
    "cmd_send_test_telegram", "cmd_preflight", "cmd_config_fix",
    "cmd_config_diff", "cmd_startup", "cmd_watch", "cmd_dashboard",
    "cmd_validate_system", "cmd_validate_schema", "cmd_digest_preview",
    "cmd_digest_handover_check",
]

_IDENTITY_CASES = (
    [(name, data_mod) for name in _DATA_COMMANDS]
    + [(name, training_mod) for name in _TRAINING_COMMANDS]
    + [(name, ops_mod) for name in _OPS_COMMANDS]
)


# ── Check 1: re-export import-identity ─────────────────────────────────────

@pytest.mark.parametrize("name,submodule", _IDENTITY_CASES)
def test_reexport_is_same_object(name, submodule):
    """The facade re-exports the SAME function object as the sub-module.

    Verify-by-mutation: this FAILS if commands.py accidentally redefines or
    wraps a command (e.g. `def cmd_scan(args): return commands_data.cmd_scan(args)`
    or a decorator-wrap) instead of re-exporting the original object. An `is`
    identity check cannot pass for a shadow/rewrap — only a true re-export
    (`from commands_data import cmd_scan`) makes both names bind the one object.
    """
    facade_obj = getattr(facade, name)
    sub_obj = getattr(submodule, name)
    assert facade_obj is sub_obj, (
        f"{name}: facade object is not identical to {submodule.__name__}.{name} "
        f"— commands.py must RE-EXPORT (not redefine/wrap) the command"
    )


def test_every_command_covered_exactly_once():
    """Guard against the identity map silently drifting from reality.

    Every `cmd_*` attribute on the facade must appear in exactly one category
    list, and every listed name must exist on the facade. This makes the
    identity test above fail loudly if a future edit adds a command to a
    sub-module but forgets to list it here (otherwise an unlisted command
    would never be identity-checked — a vacuous-coverage gap).
    """
    facade_cmds = {n for n in dir(facade) if n.startswith("cmd_")}
    listed = set(_DATA_COMMANDS) | set(_TRAINING_COMMANDS) | set(_OPS_COMMANDS)
    assert facade_cmds == listed, (
        f"Command coverage drift — on facade but unlisted: "
        f"{sorted(facade_cmds - listed)}; listed but not on facade: "
        f"{sorted(listed - facade_cmds)}"
    )
    # No command may be double-counted across categories.
    all_listed = _DATA_COMMANDS + _TRAINING_COMMANDS + _OPS_COMMANDS
    assert len(all_listed) == len(set(all_listed)), "a command is listed in 2+ categories"


# ── Check 2: CLI dispatch smoke (one representative per sub-module) ─────────

@pytest.mark.parametrize(
    "subcommand",
    [
        "scan",         # representative of commands_data
        "cto-report",   # representative of commands_training
        "preflight",    # representative of commands_ops
    ],
)
def test_cli_dispatch_help_resolves(subcommand):
    """`python -m src.main <cmd> --help` exits 0 and names the command.

    Verify-by-mutation: this FAILS if a re-exported command is missing from
    the argparse dispatch — e.g. if the split dropped the command from the
    facade, `build_parser()` could not resolve `func=cmd_X` at import time and
    `--help` for that subcommand would exit non-zero (argparse error: invalid
    choice). Driving the REAL entry-point subprocess (no mocks at the seam)
    is what proves the facade → main.py wiring survived the split.
    """
    result = subprocess.run(
        [sys.executable, "-m", "src.main", subcommand, "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"`src.main {subcommand} --help` exited {result.returncode}; "
        f"stderr:\n{result.stderr}"
    )
    assert subcommand in result.stdout, (
        f"subcommand {subcommand!r} not present in --help output:\n{result.stdout}"
    )
