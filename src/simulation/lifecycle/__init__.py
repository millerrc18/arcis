"""Lifecycle simulator package (T9 organic open->exit->reconcile; #97).

`bootstrap` is imported FIRST so importing this package scrubs the
environment (pinning the safe test PG and disabling .env loading) before
any other simulator code — or anything it transitively imports — runs.

Run entrypoints
---------------
``run_smoke()`` — the fast per-PR tier. Runs end-to-end on a TEMPORARY SQLite
DB (NO Docker / NO 5434 PG / NO GPU). Drives the T9 organic open->exit->reconcile
lifecycle (ScenarioRunner KEYSTONE) with the real prod scan path, then renders a
Verdict report that labels the integrity results "non-authoritative (SQLite)".
Wired into the `lifecycle-smoke` workflow (.github/workflows/lifecycle-smoke.yml),
which triggers on every push + pull_request. The per-PR job exists for wiring +
regression coverage, not integrity authority.

``run_full_gate()`` — the authoritative nightly tier. Provisions the ephemeral
5434 Postgres (docker-compose.test.yml shape: user/pass test/test, db halcyon),
bootstraps the registry schema there, runs the T9 organic lifecycle over many
sim-days, and returns the AUTHORITATIVE Verdict. Wired into the
`lifecycle-full-gate` job in .github/workflows/pg-tests.yml, gated to
`schedule:` (nightly cron) + `workflow_dispatch:` ONLY (NOT every PR — cost),
which uploads the verdict as an artifact. Only the PG schema enforces the
constraints the invariants assert against, so only this tier's verdict is
authoritative.

STABLE definition (organic certification scope, T9 + T8 + T13)
---------------------------------------------------------------
A STABLE verdict means the T9 organic open->exit->reconcile lifecycle passed:
  - provenance.assert_real_path_executed confirmed the real prod path fired
    (universe_scanner -> log_recommendation -> executor.open_shadow_trade).
  - All 9 data-integrity invariants passed on the ORGANIC rows (no synthetic
    raw-INSERT shortcuts — every row is written by the real prod code path).
  - reconcile-when-gone mode resolved with ZERO orphans.

Deferred scope (honest disclosure): T10 (fault injection), T11 (governor-reject
scenario), and T12 (multi-day stress) are DEFERRED to follow-up tasks. STABLE
at this certification level certifies the organic lifecycle mechanics; it does NOT
certify adversarial fault paths, deliberate-reject flows, or extended multi-day
stress (those will extend the STABLE bar when T10/T11/T12 land).

Clean-close xfail: the clean-close oracle bar (exactly 1 rec + 1 trade row,
deterministic exit_reason) is exercised but xfailed pending T10 determinism
hardening. Provenance + reconcile-when-gone pass unconditionally.

Blind-spots caveat: a STABLE verdict is bounded by the simulated scenarios — the
sim-day count, the fault set exercised, and the invariants encoded. It is NOT a
proof of correctness for unmodeled faults, untested code paths, or production
load profiles the scenario does not reproduce. The smoke tier's STABLE is weaker
still (SQLite) and is wiring-only.
"""

from src.simulation.lifecycle import bootstrap  # noqa: F401  (import for side effect)

# Public run entrypoints (imported AFTER bootstrap so the env is already
# scrubbed before any entrypoint module — or its transitive imports — runs).
from src.simulation.lifecycle.entrypoints import run_full_gate, run_smoke  # noqa: E402

__all__ = ["bootstrap", "run_smoke", "run_full_gate"]
