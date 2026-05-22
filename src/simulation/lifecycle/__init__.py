"""Lifecycle simulator package.

`bootstrap` is imported FIRST so importing this package scrubs the
environment (pinning the safe test PG and disabling .env loading) before
any other simulator code — or anything it transitively imports — runs.
"""

from src.simulation.lifecycle import bootstrap  # noqa: F401  (import for side effect)
