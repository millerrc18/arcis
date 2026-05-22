"""Lifecycle simulator package.

`bootstrap` is imported FIRST so importing this package scrubs the
environment (pinning the safe test PG and disabling .env loading) before
any other simulator code — or anything it transitively imports — runs.
"""

from src.simulation.lifecycle import bootstrap  # noqa: F401  (import for side effect)

# Public run entrypoints (imported AFTER bootstrap so the env is already
# scrubbed before any entrypoint module — or its transitive imports — runs).
from src.simulation.lifecycle.entrypoints import run_full_gate, run_smoke  # noqa: E402

__all__ = ["bootstrap", "run_smoke", "run_full_gate"]
