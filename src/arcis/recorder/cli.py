"""arcis-recorder command line. Subcommands: universe, poll, sweep, gaps."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from arcis.recorder.config import load_config
from arcis.recorder.errors import RecorderError
from arcis.recorder.runner import gaps as gaps_run
from arcis.recorder.runner import poll as poll_run
from arcis.recorder.runner import sweep as sweep_run
from arcis.recorder.universe import build_universe


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/recorder.yaml"),
        help="path to recorder.yaml (default: config/recorder.yaml)",
    )


def cmd_universe(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    day = date.fromisoformat(args.date) if args.date else date.today()
    path = build_universe(config, day, args.config.parent)
    print(f"universe snapshot: {path} ({len(config.symbols)} symbols)")
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    summary = poll_run(config)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    summary = sweep_run(config, date.fromisoformat(args.start), date.fromisoformat(args.end))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    report = gaps_run(config.data_root, days=args.days)
    print(json.dumps(report, indent=2))
    return 1 if report["missing_days"] or report["last_poll_at"] is None else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arcis-recorder", description="Forward news recorder")
    _add_config_arg(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p_universe = sub.add_parser("universe", help="build the dated universe snapshot")
    p_universe.add_argument("--date", help="snapshot date YYYY-MM-DD (default: today)")
    p_universe.set_defaults(func=cmd_universe)

    p_poll = sub.add_parser("poll", help="fetch the last 24h of news (runs via cron)")
    p_poll.set_defaults(func=cmd_poll)

    p_sweep = sub.add_parser("sweep", help="backfill a date range")
    p_sweep.add_argument("--start", required=True, help="start date YYYY-MM-DD")
    p_sweep.add_argument("--end", required=True, help="end date YYYY-MM-DD")
    p_sweep.set_defaults(func=cmd_sweep)

    p_gaps = sub.add_parser("gaps", help="report coverage gaps")
    p_gaps.add_argument("--days", type=int, default=7, help="days to report (default: 7)")
    p_gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except RecorderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
