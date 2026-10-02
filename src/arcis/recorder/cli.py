"""arcis-recorder command line. Subcommands grow per sprint; S01 ships
universe now and poll/sweep/gaps in T8."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from arcis.recorder.config import load_config
from arcis.recorder.errors import RecorderError
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arcis-recorder", description="Forward news recorder")
    _add_config_arg(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p_universe = sub.add_parser("universe", help="build the dated universe snapshot")
    p_universe.add_argument("--date", help="snapshot date YYYY-MM-DD (default: today)")
    p_universe.set_defaults(func=cmd_universe)
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


if __name__ == "__main__":
    sys.exit(main())
