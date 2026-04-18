"""Dashboard-triggered diagnostic command handlers.

Extracted from src.commands.executor to keep that file under the
400-line guardrail. Each handler assembles CLI args for one of the
diagnostic scripts and delegates to dashboard_runner.

Called by: src.commands.executor (via COMMAND_HANDLERS dispatch)
Calls: src.diagnostics.dashboard_runner, src.diagnostics.summary_extractor
Owns tables: none (writes happen in dashboard_runner)
Config keys: none
Tests: tests/test_diagnostic_handlers.py
"""

from __future__ import annotations

from pathlib import Path

from src.config import DB_PATH


def _prepare_output_paths(prefix: str, run_id: str) -> tuple[str, str]:
    """Allocate unique report + plot_dir paths keyed by run_id."""
    report_path = f"docs/diagnostics/{prefix}-{run_id}.md"
    plot_dir = f"docs/diagnostics/{prefix}-{run_id}/"
    Path(plot_dir).mkdir(parents=True, exist_ok=True)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    return report_path, plot_dir


def handle_run_regime_diagnostic(payload: dict, config: dict) -> dict:
    """Run the regime diagnostic script via dashboard_runner.

    Payload fields:
      - run_id: UUID matching the diagnostic_runs row seeded by the API
      - db_path: override for local SQLite (tests); defaults to DB_PATH
      - exclude_quarantined: bool flag passed to the script
      - bootstrap_n: int override for bootstrap count
    """
    import src.diagnostics.dashboard_runner as _runner
    from src.diagnostics.summary_extractor import parse_regime_report

    run_id = payload.get("run_id")
    if not run_id:
        return {"error": "Missing run_id in payload"}

    db_path = payload.get("db_path") or DB_PATH
    args: list[str] = ["--db", db_path]
    if payload.get("exclude_quarantined"):
        args.append("--exclude-quarantined")
    if payload.get("bootstrap_n"):
        args.extend(["--bootstrap-n", str(int(payload["bootstrap_n"]))])

    report_path, plot_dir = _prepare_output_paths("regime", run_id)
    return _runner.run_diagnostic(
        run_id=run_id,
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=args,
        report_parser=parse_regime_report,
        report_path=report_path,
        plot_dir=plot_dir,
        db_path=db_path,
    )


def handle_run_forensic_audit(payload: dict, config: dict) -> dict:
    """Run the forensic trade audit script via dashboard_runner."""
    import src.diagnostics.dashboard_runner as _runner
    from src.diagnostics.summary_extractor import parse_forensic_report

    run_id = payload.get("run_id")
    if not run_id:
        return {"error": "Missing run_id in payload"}

    db_path = payload.get("db_path") or DB_PATH
    report_path, plot_dir = _prepare_output_paths("forensic-audit", run_id)

    return _runner.run_diagnostic(
        run_id=run_id,
        script_path="scripts/diagnostics/forensic_trade_audit_v1.py",
        script_args=[],
        report_parser=parse_forensic_report,
        report_path=report_path,
        plot_dir=plot_dir,
        db_path=db_path,
    )
