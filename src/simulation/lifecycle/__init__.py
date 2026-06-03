"""Lifecycle simulator package (T9 organic open->exit->reconcile; #97).

`bootstrap` exposes ``scoped_scrub()``, which the run entrypoints wrap around
their work to pin the safe test PG (and disable .env loading) for the DURATION
of a run only. The scrub is NOT an import side-effect: importing this package
no longer mutates os.environ, so importing the simulator can never freeze
``src.config.DB_PATH`` to None or leak the :5434 gate env into unrelated tests
(test-determinism #128 / T5).

Run entrypoints
---------------
``run_smoke()`` — the fast per-PR tier. Runs end-to-end against the ephemeral
5434 test PG via the cutover gate (DATABASE_URL=:5434 + ARCIS_PG_CUTOVER_ENABLED=1,
pinned by the scoped bootstrap scrub for the run; NO GPU). Drives the T9 organic
open->exit->reconcile lifecycle (ScenarioRunner KEYSTONE) with the real prod scan
path, then renders a Verdict report that labels the integrity results
"non-authoritative (smoke tier)" — the historical "SQLite" wording is kept on the
label, but the backing store is the 5434 PG.
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

Clean-close certified (#132): the clean-close oracle bar (exactly 1 rec + 1 trade
row, canonical 'target_1' exit, db_open==broker, zero orphans) now passes — was
previously xfailed. The fix uncovered three real PG-cutover regressions in the
close path (postmortem datetime slice, days_open fromisoformat, SPY-benchmark
.replace) plus a harness neutral-price drift. Provenance + reconcile-when-gone
pass unconditionally. Full end-to-end two-run inv9 determinism (T10) is still
deferred, but no longer blocked by the clean-close bar.

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
