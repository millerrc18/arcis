#!/usr/bin/env python
"""Generate Sprint F byte-identity fixtures from the legacy runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.platform.byte_identity.helpers import (
    FIXTURE_DATES,
    compute_engine_outputs,
    compute_ranked_outputs,
    dump_fixture,
    engine_fixture_payload,
    fixture_path,
    ranker_fixture_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-root",
        default=None,
        help="Override simulation-cache root (defaults to ARCIS_SIM_CACHE_ROOT or known local roots).",
    )
    parser.add_argument(
        "--dates",
        nargs="*",
        default=list(FIXTURE_DATES),
        help="Fixture dates to generate (YYYY-MM-DD). Defaults to the full Sprint F schedule.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for as_of_date in args.dates:
        features = compute_engine_outputs(as_of_date, cache_root=args.cache_root)
        ranked = compute_ranked_outputs(as_of_date, cache_root=args.cache_root)

        dump_fixture(
            fixture_path("engine", as_of_date),
            engine_fixture_payload(as_of_date, features),
        )
        dump_fixture(
            fixture_path("ranker", as_of_date),
            ranker_fixture_payload(as_of_date, ranked),
        )
        print(
            f"[sprint-f] {as_of_date}: "
            f"features={len(features)} ranked={len(ranked)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
