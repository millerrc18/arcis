"""Lifecycle simulator package.

`bootstrap` is imported FIRST so importing this package scrubs the
environment (pinning the safe test PG and disabling .env loading) before
any other simulator code — or anything it transitively imports — runs.

Run entrypoints
---------------
``run_smoke()`` — the fast per-PR tier. Runs end-to-end on a TEMPORARY SQLite
DB (NO Docker / NO 5434 PG / NO GPU), a couple sim-days and a light fault set.
Wired into the `lifecycle-smoke` workflow (.github/workflows/lifecycle-smoke.yml),
which triggers on every push + pull_request. Its integrity verdict is
NON-authoritative: SQLite cannot enforce the FK / NOT NULL / type constraints
the data-integrity invariants assert against, so the rendered report labels the
integrity results "non-authoritative (SQLite)". The per-PR job exists for wiring
+ regression coverage, not integrity authority.

``run_full_gate()`` — the authoritative nightly tier. Provisions the ephemeral
5434 Postgres (docker-compose.test.yml shape: user/pass test/test, db halcyon),
bootstraps the registry schema there, runs many sim-days + all faults, and
returns the AUTHORITATIVE Verdict. Wired into the `lifecycle-full-gate` job in
.github/workflows/pg-tests.yml, gated to `schedule:` (nightly cron) +
`workflow_dispatch:` ONLY (NOT every PR — cost), which uploads the verdict as an
artifact. Only the PG schema enforces the constraints the invariants assert
against, so only this tier's verdict is authoritative.

STABLE means all 9 data-integrity invariants passed for that run.

Blind-spots caveat: a STABLE verdict is bounded by the simulated scenarios — the
sim-day count, the fault set exercised, and the invariants encoded. It is NOT a
proof of correctness for unmodeled faults, untested code paths, or production
load profiles the scenario does not reproduce. The smoke tier's STABLE is weaker
still (SQLite, fewer days, lighter faults) and is wiring-only.
"""

from src.simulation.lifecycle import bootstrap  # noqa: F401  (import for side effect)

# Public run entrypoints (imported AFTER bootstrap so the env is already
# scrubbed before any entrypoint module — or its transitive imports — runs).
from src.simulation.lifecycle.entrypoints import run_full_gate, run_smoke  # noqa: E402

__all__ = ["bootstrap", "run_smoke", "run_full_gate"]
