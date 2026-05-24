"""CLI entry point for the TradingState tool — python -m src.tools.tradingstate.

Called by: operator agents, test subprocesses (pytest subprocess cases)
Calls: src.tools.tradingstate.core.state, src.tools.tradingstate.render.render_markdown,
       src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: pg.test_dsn (via arcis_config.yaml, resolved in core),
             paths.db_canonical (via arcis_config.yaml, resolved in core)
Tests: tests/tools/test_tradingstate_cli.py (subprocess cases a-d)

Usage:
    python -m src.tools.tradingstate [--dsn DSN] [--sqlite-path PATH] [--json]
"""

from __future__ import annotations

import argparse
import json as json_mod
from pathlib import Path

from src.tools._cli_envelope import run_cli
from src.tools.tradingstate.core import state
from src.tools.tradingstate.render import render_markdown


def _run(*, dsn: str | None, sqlite_path: str | None, json: bool) -> str:
    """Invoke state() and return formatted output string.

    Called by run_cli(**vars(args_namespace)). Raises TradingStateError
    on failure — run_cli handles the JSON envelope.
    """
    resolved_sqlite = Path(sqlite_path) if sqlite_path is not None else None
    snapshot = state(dsn=dsn, sqlite_path=resolved_sqlite)

    if json:
        return json_mod.dumps(snapshot, default=str, indent=2)
    return render_markdown(snapshot)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.tradingstate",
        description="Snapshot current trading-day state (positions, audit, GPU health).",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL DSN (overrides default test_dsn from arcis_config.yaml)",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        dest="sqlite_path",
        help="SQLite fallback DB path (overrides paths.db_canonical from arcis_config.yaml)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output JSON snapshot instead of markdown",
    )

    args = parser.parse_args()

    run_cli(
        tool_name="tradingstate",
        fn=_run,
        args_namespace=args,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
