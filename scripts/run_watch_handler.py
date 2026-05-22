"""CLI dispatcher: invoke a single watch-loop handler by name.

This is the real kickoff endpoint for the scheduler watch-handler ACTIONs
registered in the capability registry. It is import-light: ``ALL_HANDLERS``
(a leaf list in ``watch_handlers``) is imported at module top, but the heavy
``WatchLoop`` is imported only inside ``main()`` so ``--list`` works in a
bare environment without constructing the loop.

Usage:
  python scripts/run_watch_handler.py --list
  python scripts/run_watch_handler.py --handler stress_test [--at 2026-05-21T19:00:00] [--force]

The ``--handler`` value accepts either the bare handler name or the
``maybe_``-prefixed function name (the registered ACTION name is the
``maybe_``-stripped form).

Called by: operators / automation (the ACTION kickoff_endpoint)
Calls: src.scheduler.watch_handlers.ALL_HANDLERS, src.scheduler.watch.WatchLoop (deferred)
Owns tables: none
Config keys: none (reads config via load_config inside main)
Tests: tests/scheduler/test_run_watch_handler.py
"""
from __future__ import annotations

import argparse
import datetime as _dt

from src.scheduler.watch_handlers import ALL_HANDLERS

# Index handlers by both their real function name (maybe_*) and the
# maybe_-stripped ACTION name, so either form resolves.
_BY_FUNC_NAME = {h.__name__: h for h in ALL_HANDLERS}


def _stripped(name: str) -> str:
    return name[len("maybe_"):] if name.startswith("maybe_") else name


_BY_ACTION_NAME = {_stripped(h.__name__): h for h in ALL_HANDLERS}


def _resolve(name: str | None):
    if name is None:
        return None
    return _BY_FUNC_NAME.get(name) or _BY_ACTION_NAME.get(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Invoke a single watch-loop handler by name.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="print the registered handler names (maybe_-stripped) and exit",
    )
    parser.add_argument(
        "--handler",
        help="handler to invoke (bare ACTION name or maybe_-prefixed func name)",
    )
    parser.add_argument(
        "--at",
        help="ISO timestamp override for `now`; defaults to datetime.now()",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="bypass the schedule-window gate (sets watch.overnight = True)",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name in _BY_ACTION_NAME:
            print(name)
        return 0

    fn = _resolve(args.handler)
    if fn is None:
        raise SystemExit(
            f"unknown handler {args.handler!r}; "
            f"known: {sorted(_BY_ACTION_NAME)}"
        )

    # Heavy import deferred so --list works without constructing the loop.
    from src.config import load_config
    from src.scheduler.watch import WatchLoop

    now = _dt.datetime.fromisoformat(args.at) if args.at else _dt.datetime.now()
    watch = WatchLoop(load_config())
    if args.force:
        watch.overnight = True  # let the overnight-window predicate pass
    fn(watch, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
