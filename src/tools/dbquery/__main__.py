"""CLI entry point for the DBQuery tool — python -m src.tools.dbquery.

Called by: operator agents, test subprocesses (pytest subprocess cases)
Calls: src.tools.dbquery.core._query_impl_with_truncated,
       src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: pg.test_dsn (via arcis_config.yaml, resolved in core)
Tests: tests/tools/test_dbquery_integration.py (subprocess cases f, g)
"""

from __future__ import annotations

import argparse
import json as json_mod

from src.tools._cli_envelope import run_cli
from src.tools.dbquery.core import _query_impl_with_truncated


def _render_markdown(rows: list[dict], truncated: bool) -> str:
    """Render rows as a column-aligned markdown table with a truncation footer."""
    n = len(rows)
    footer = f"({n} rows, truncated={truncated})"

    if not rows:
        return footer

    cols = list(rows[0].keys())

    widths = {c: len(c) for c in cols}
    for row in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))

    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-|-".join("-" * widths[c] for c in cols)
    data_lines = [
        " | ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols)
        for row in rows
    ]

    table = "\n".join([header, sep] + data_lines)
    return f"{table}\n{footer}"


def _run(sql: str, *, dsn: str | None, limit: int, json: bool) -> str:
    """Execute the query and return a formatted string (markdown or JSON).

    Called by run_cli(**vars(args_namespace)). Raises WriteNotPermittedError
    or DBQueryError on failure — run_cli handles the JSON envelope.
    """
    rows, truncated = _query_impl_with_truncated(sql, dsn=dsn, limit=limit)

    if json:
        return json_mod.dumps(rows, default=str)
    return _render_markdown(rows, truncated)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.dbquery",
        description="Run a read-only SELECT/WITH against the configured test PG.",
    )
    parser.add_argument("sql", help="SQL SELECT or WITH statement to execute")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum rows to return (default: 1000)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output JSON array instead of markdown table",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL DSN (overrides default test_dsn from arcis_config.yaml)",
    )

    args = parser.parse_args()

    run_cli(
        tool_name="dbquery",
        fn=_run,
        args_namespace=args,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
