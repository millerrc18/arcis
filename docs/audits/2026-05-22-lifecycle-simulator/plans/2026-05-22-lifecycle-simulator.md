# Lifecycle Simulator — Implementation Plan

SAFETY-FIRST PHASING (unchanged priority, expanded): Task 1 (bootstrap + prod guard + the narrow ARCIS_DISABLE_DOTENV dotenv guard in src/config/__init__.py) MUST land first. Task 2 (refuse-if-prod proof) AND Task 21 (the NEW real-child subprocess-isolation proof, CRITICAL-1) both gate the rest — nothing downstream is safe until prod cannot be reached from the parent OR any child. Task 3 is the WatchLoop clock seam; Task 81 is the NEW SwallowedErrorObserver (CRITICAL-2 discriminator) which Task 9's invariant #6 consumes — both can build in parallel with Task 4 once the safety gate is green. Tasks 5/6/7 (fakes) parallelize after the clock. Task 8 (capital) -> Task 9 (oracle, depends on capital + observer). Faults (10) depend on all fakes. Scenario (11) -> verdict (12) -> entrypoints (13) -> determinism/DST hardening (14) -> CI (15). All paths use the verified src/<package>/ form. CI decision: NEW lifecycle-smoke.yml for the smoke; EXTEND pg-tests.yml (nightly + workflow_dispatch) for the full gate — verified no general PR pytest workflow exists. freezegun added in Task 4. Task IDs 21 and 81 are insertions; execution_order reflects true dependency batches. Each task respects 400-line-file / 60-line-function guards (oracle/faults/scenario split across submodules).

**Execution order (parallel batches):** [1] → [2,21] → [3,4,81] → [5,6,7] → [8] → [9] → [10] → [11] → [12] → [13] → [14] → [15]

## Task 1: Bootstrap + prod guard + dotenv guard (safety foundation)

_Complexity: medium_

**Depends on:** none

Create src/simulation/lifecycle/bootstrap.py (FIRST-import env scrub: pop ARCIS_DB_PATH + prod-signature URLs; set DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon, ARCIS_PG_CUTOVER_ENABLED=1, ALPACA_PAPER_TRADE=true, ARCIS_DISABLE_DOTENV=1, PYTHONHASHSEED=0; assert_safe_db_env(); scrubbed_env() returning the sanitized env dict for child processes) and src/simulation/lifecycle/prod_guard.py (install_prod_guard() guards BOTH psycopg2.connect AND the connect_db DSN-resolution boundary at src/utils/db.py:621 to raise SimProdGuardError on prod signatures localhost:5433/127.0.0.1:5433/halcyon_app:, NO escape hatch). Reuse _is_prod_pg_url semantics from tests/conftest.py:51. SCOPE-FENCED PROD EDIT: in src/config/__init__.py wrap the load_dotenv(...) call at L62 in `if os.environ.get('ARCIS_DISABLE_DOTENV') != '1':` (zero behavior change in prod; closes the subprocess-isolation hole). Create package __init__.py importing bootstrap FIRST.

**Files in scope:**
- `src/simulation/lifecycle/bootstrap.py`
- `src/simulation/lifecycle/prod_guard.py`
- `src/simulation/lifecycle/__init__.py`
- `src/config/__init__.py`

**Read-only context:**
- `src/utils/db.py`
- `tests/conftest.py`

**Test strategy:** Deferred to Tasks 2 + 2b. This task builds the guard modules + the single narrow dotenv guard. The ONLY edit to src/config/__init__.py is wrapping L62 load_dotenv in the ARCIS_DISABLE_DOTENV check — nothing else in config changes.

**Scope fence:** Do NOT modify src/utils/db.py or tests/conftest.py. Do NOT edit tests/config/__init__.py (different file). In src/config/__init__.py change ONLY the load_dotenv guard at L62 — no other lines. Do NOT add a prod escape hatch. Do NOT use force_sqlite. Do NOT build the clock, fakes, or oracle here.

## Task 2: MANDATORY refuse-if-prod proof test

_Complexity: medium_

**Depends on:** [1]

Create tests/simulation/lifecycle/test_prod_guard.py and test_bootstrap.py. Prove install_prod_guard() rejects a connect to postgresql://halcyon_app:...@127.0.0.1:5433/halcyon_app and a 5433 URL with SimProdGuardError — via the psycopg2.connect patch AND via an aliased `from psycopg2 import connect` call (verify the connect_db DSN-boundary guard catches it). Prove assert_safe_db_env() raises on a prod-signature env. Test bootstrap scrubs ARCIS_DB_PATH, sets 5434 URL + ALPACA_PAPER_TRADE=true + ARCIS_DISABLE_DOTENV=1 + PYTHONHASHSEED=0, override-wins ordering, and scrubbed_env() contains the 5434 URL + the disable-dotenv flag and NOT the prod URL.

**Files in scope:**
- `tests/simulation/lifecycle/test_prod_guard.py`
- `tests/simulation/lifecycle/test_bootstrap.py`

**Read-only context:**
- `src/simulation/lifecycle/bootstrap.py`
- `src/simulation/lifecycle/prod_guard.py`
- `tests/conftest.py`

**Test strategy:** These ARE the tests. pytest tests/simulation/lifecycle/test_prod_guard.py + test_bootstrap.py MUST pass before any downstream task.

**Scope fence:** Do NOT touch prod code or any DB on 5433. Tests must never actually connect to prod — assert on the raised guard / resolved DSN string only. Do NOT build downstream components.

## Task 21: MANDATORY subprocess-isolation proof test (real child)

_Complexity: medium_

**Depends on:** [1]

Create tests/simulation/lifecycle/test_subprocess_isolation.py. Write a prod-signature .env (DATABASE_URL=postgresql://halcyon_app:x@127.0.0.1:5433/halcyon_app) to a temp repo-root-shaped location, then spawn a REAL python child (`python -c 'import src.config; import src.utils.db as db; print(db.connect_db.__module__)'` or equivalent that resolves the DSN) with env=bootstrap.scrubbed_env(). Assert the child does NOT resolve/connect to 5433 — it resolves the 5434 test URL or raises the prod guard, because ARCIS_DISABLE_DOTENV=1 stops load_dotenv from reading the prod .env. Include a control assertion (documented) that WITHOUT the flag the child WOULD read the file — assert on the resolved DSN STRING only, never a live 5433 connect.

**Files in scope:**
- `tests/simulation/lifecycle/test_subprocess_isolation.py`

**Read-only context:**
- `src/simulation/lifecycle/bootstrap.py`
- `src/config/__init__.py`
- `src/utils/db.py`

**Test strategy:** This IS the test. It closes CRITICAL-1 (subprocess wipe-vector). Must pass alongside Task 2 before any downstream build. Child must use env=scrubbed_env(); never connect to a real 5433.

**Scope fence:** Do NOT connect to a real 5433 DB under any branch. Do NOT modify prod code. Do NOT spawn a child that inherits the operator's real environment (always pass env=scrubbed_env()).

## Task 3: WatchLoop clock + sleep seam (the prod-code change)

_Complexity: low_

**Depends on:** [2, 21]

In src/scheduler/watch.py: add self._clock (default lambda: datetime.now(ET)) and self._sleep (default time.sleep) to WatchLoop.__init__; replace `now = datetime.now(ET)` at L1577 with `now = self._clock()`; replace `time.sleep(60)` at L2094 with `self._sleep(60)`. ZERO behavior change in prod (defaults preserve current behavior).

**Files in scope:**
- `src/scheduler/watch.py`
- `tests/scheduler/test_watch_clock_seam.py`

**Test strategy:** Assert default _clock matches datetime.now(ET) behavior and that an injected clock/sleep is honored without firing real sleeps.

**Scope fence:** Do NOT modify src/risk/governor.py or src/shadow_trading/executor.py (freezegun handles those). Do NOT change loop logic beyond the two seam lines + __init__ wiring. Do NOT touch the heartbeat writes.

## Task 4: VirtualClock + freezegun sync + clock-source pinning

_Complexity: low_

**Depends on:** [2, 21]

Create src/simulation/lifecycle/clock.py: VirtualClock(start tz-aware ET) with now()/advance()/tick_to(hour,minute); a freeze_at(clock) helper returning a freezegun context synced to clock.now() that freezes datetime, time.time/monotonic, and pd.Timestamp.now consistently (§4.4). Add freezegun to requirements.txt.

**Files in scope:**
- `src/simulation/lifecycle/clock.py`
- `requirements.txt`
- `tests/simulation/lifecycle/test_clock.py`

**Test strategy:** Unit test advance/tick_to monotonicity, tz-awareness (ET), and that inside freeze_at datetime.now(), time.time(), and pd.Timestamp.now() all equal clock.now().

**Scope fence:** Do NOT wire into ScenarioRunner yet. Do NOT modify watch.py. Keep file under 400 lines.

## Task 5: FakeTradingClient at the SDK seam

_Complexity: medium_

**Depends on:** [4]

Create src/simulation/lifecycle/fakes/trading_client.py: stateful FakeTradingClient implementing submit_order (bracket/OCO), get_order_by_id, get_orders, get_all_positions, get_open_position, cancel_order_by_id with SDK-shaped return objects so real _serialize_order (src/shadow_trading/alpaca_adapter.py:66) consumes them. Model OCO (fill one leg auto-cancels sibling + closes position). Expose a position book + deterministic fill scheduling driven by VirtualClock. Use a monotonic counter for client_order_id (determinism, §7.2). Extend the conftest._mock_alpaca_sdk shape (tests/conftest.py:292).

**Files in scope:**
- `src/simulation/lifecycle/fakes/trading_client.py`
- `src/simulation/lifecycle/fakes/__init__.py`
- `tests/simulation/lifecycle/test_fake_trading_client.py`

**Read-only context:**
- `src/shadow_trading/alpaca_adapter.py`
- `src/shadow_trading/alpaca_adapter_paper.py`
- `tests/conftest.py`

**Test strategy:** Unit test: bracket submit returns SDK shape, OCO sibling auto-cancel on fill, partial fill, qty=0 exit, position book set/qty equality, deterministic client_order_id sequence.

**Scope fence:** Do NOT add fault hooks here (Task 10 wires faults). Do NOT fake at the BrokerAdapter ABC level (src/trading/broker_interface.py). Do NOT modify the alpaca adapters.

## Task 6: FakeMarketData + FakeLLM

_Complexity: medium_

**Depends on:** [4]

Create src/simulation/lifecycle/fakes/market_data.py (deterministic seeded OHLCV reusing src/simulation/cache.py row shape; hooks for gap/halt/regime later) and src/simulation/lifecycle/fakes/llm.py (canned/seeded packets; configurable candidate volume/content to drive scan->packet->council and governor gates).

**Files in scope:**
- `src/simulation/lifecycle/fakes/market_data.py`
- `src/simulation/lifecycle/fakes/llm.py`
- `tests/simulation/lifecycle/test_fake_market_llm.py`

**Read-only context:**
- `src/simulation/cache.py`

**Test strategy:** Unit test determinism (same seed -> identical bars/packets) and the candidate-volume knob.

**Scope fence:** Do NOT inject market/regime faults here (Task 10). Do NOT call real market-data or LLM services.

## Task 7: Faked trainer subprocess + REAL controllable pidfile

_Complexity: medium_

**Depends on:** [4]

Create src/simulation/lifecycle/fakes/trainer.py: helpers to stub subprocess.run at src/training/trainer.py:814 and ollama create/cp at 851/861, and _find_gguf at L838 -> fake GGUF path; redirect CWD-relative training_data/ writes (L797/844) to a sim temp dir; any real child spawn uses scrubbed_env(). The stub WRITES and CLEARS a REAL pidfile with a controllable PID value so the prod write/stale-detect/recycle-detect paths are exercised (§5.4). Exercise REAL export_training_data, empty-corpus guard, empty-holdout block (L786-794), canary, evaluate_on_holdout, register/promotion logic. NO real GPU.

**Files in scope:**
- `src/simulation/lifecycle/fakes/trainer.py`
- `tests/simulation/lifecycle/test_trainer_stub.py`

**Read-only context:**
- `src/training/trainer.py`
- `src/simulation/lifecycle/bootstrap.py`

**Test strategy:** Unit test: stubbed subprocess returns success with env=scrubbed_env(); fake GGUF resolves; empty-holdout (holdout==0) causes run_fine_tune to return None (promotion blocked); pidfile write/clear/stale/recycle controllable.

**Scope fence:** Do NOT modify src/training/trainer.py. Do NOT run real torch/Ollama. Do NOT seed corpus faults here (Task 10). Never spawn a child without env=scrubbed_env().

## Task 8: Authoritative capital ledger

_Complexity: low_

**Depends on:** [5]

Create src/simulation/lifecycle/oracle/capital.py: an authoritative capital ledger tracking starting capital, realized/unrealized P&L from FakeTradingClient fills, used for capital-conservation (invariant 5) and honest-metrics drawdown-denominator (invariant 6).

**Files in scope:**
- `src/simulation/lifecycle/oracle/capital.py`
- `src/simulation/lifecycle/oracle/__init__.py`
- `tests/simulation/lifecycle/test_capital.py`

**Read-only context:**
- `src/simulation/lifecycle/fakes/trading_client.py`

**Test strategy:** Unit test ledger reconciles a sequence of fills; flags an unattributed (phantom) P&L delta.

**Scope fence:** Do NOT implement the 9 invariant SQL checks here (Task 9). Do NOT modify src/risk/governor.py.

## Task 81: SwallowedErrorObserver (error-swallow discriminator mechanism)

_Complexity: medium_

**Depends on:** [2, 21]

Create src/simulation/lifecycle/oracle/error_observer.py: SwallowedErrorObserver, a test-only logging.Handler that attaches to the prod loggers for src/risk/governor.py, src/shadow_trading/reconcile.py, and the validator module, recording every fail-conservative branch hit (logger name, message, exc_info) into an in-memory list. install()/detach() lifecycle. BLOCKING: confirm the exact distinguishing log strings at impl time — governor.py:392-397 emits `[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)` (verified); reconcile tz-coercion L124 and the validator reject-on-import-fail strings must be confirmed; if any branch has no distinguishing log, attach the handler at the narrowest seam to capture the swallowed exception WITHOUT editing prod control flow.

**Files in scope:**
- `src/simulation/lifecycle/oracle/error_observer.py`
- `tests/simulation/lifecycle/test_error_observer.py`

**Read-only context:**
- `src/risk/governor.py`
- `src/shadow_trading/reconcile.py`

**Test strategy:** Unit test: observer records the exact [RISK] Drawdown computation failed event when the branch fires; records NO event on a clean compute; detach() removes the handler with no residue.

**Scope fence:** Do NOT edit prod control flow in governor.py/reconcile.py/validator — attach a logging handler only. Do NOT implement the invariant checks here (Task 9 consumes this).

## Task 9: Oracle — 9 invariants (with error-swallow + determinism canonicalization)

_Complexity: high_

**Depends on:** [8, 81]

Create src/simulation/lifecycle/oracle/invariants.py + Oracle.assert_all() in oracle/__init__.py: the 9 checks. ALL SQL uses explicit ORDER BY on stable business keys (§7.2). Checks: 1:1 attribution; orphans order_type='reconciled' OR recommendation_id IS NULL; reconciled_stale closes; DB-open==FakeBroker positions set+qty; capital conservation via capital.py; honest metrics + degraded-correctly vs error-swallowed drawdown via SwallowedErrorObserver (governor.py:392-397); corpus integrity/empty-holdout block; heartbeat freshness keyed to frozen clock + no stale/recycled pidfile; deterministic reproducibility canonical hash (exclude SERIAL PKs + raw timestamps, normalize surrogate keys, PYTHONHASHSEED pinned). Each returns InvariantResult(...degraded_correctly, error_swallowed). BLOCKING acceptance: confirm the per-branch distinguishing evidence (§7.1 table) exists before accepting the task.

**Files in scope:**
- `src/simulation/lifecycle/oracle/invariants.py`
- `src/simulation/lifecycle/oracle/__init__.py`
- `tests/simulation/lifecycle/test_oracle.py`

**Read-only context:**
- `src/shadow_trading/reconcile.py`
- `src/risk/governor.py`
- `src/simulation/lifecycle/oracle/capital.py`
- `src/simulation/lifecycle/oracle/error_observer.py`

**Test strategy:** Unit test each invariant flags a seeded violation (orphan row, reconciled_stale, position mismatch, error-swallowed drawdown via observer, empty-holdout, stale/recycled pidfile) and passes on clean state; reproducibility hash stable across two seeded snapshots.

**Scope fence:** Do NOT run a full scenario here. Do NOT modify prod code. Split files to respect the 400-line guard. Every SQL query MUST have ORDER BY.

## Task 10: Fault-injection framework

_Complexity: high_

**Depends on:** [5, 6, 7]

Create src/simulation/lifecycle/faults/__init__.py (FaultInjector base + FaultRegistry arm/disarm) and broker_faults/network_faults/process_faults/market_faults/clock_faults/data_faults modules covering all required fault classes (partial/qty0/OCO-race/dup/transient-empty/sticky/close-didn't-clear/phantom; 500/timeout/mid-submit; IN-PROCESS watch+training restart, PID recycling via the controllable pidfile; DST edges; gaps/halts/regime/high-volume; schema drift; corpus starvation/holdout-empty). Process faults reconstruct WatchLoop IN-PROCESS (no real fork). Faults patch the fakes + harness only.

**Files in scope:**
- `src/simulation/lifecycle/faults/__init__.py`
- `src/simulation/lifecycle/faults/broker_faults.py`
- `src/simulation/lifecycle/faults/process_faults.py`
- `src/simulation/lifecycle/faults/market_faults.py`

**Read-only context:**
- `src/simulation/lifecycle/fakes/trading_client.py`
- `src/simulation/lifecycle/fakes/trainer.py`

**Test strategy:** Unit test: compose two faults, arm/disarm cleanly, verify no leakage between runs; each broker fault produces the expected fake behavior; process-restart fault reconstructs the loop in-process with no real subprocess.

**Scope fence:** Do NOT modify prod code to enable faults. Do NOT real-fork the watch loop. network_faults/clock_faults/data_faults submodules go in the same package; keep each file <400 lines (split if needed) — they may be created in a follow-up edit within this task. Do NOT wire the scenario runner here.

## Task 11: ScenarioRunner + coverage matrix

_Complexity: high_

**Depends on:** [9, 10]

Create src/simulation/lifecycle/scenario.py (build WatchLoop with injected _clock=VirtualClock.now + _sleep=noop; install fakes via sys.modules + reset_brokers() (src/trading/broker_factory.py:75) + config-cache clear (src/config/__init__.py:93); attach SwallowedErrorObserver; register FaultRegistry; advance clock through daily cadence wrapping on_tick in freeze_at; run Oracle checkpoints post-open/close/reconcile/training/end; detach observer + reset on teardown) and src/simulation/lifecycle/coverage.py (lifecycle-stage x fault-dimension matrix, cross-ref src/platform/capability_registry/registry.py:35-38 dicts; drive all 11 GOVERNOR_GATES at src/risk/governor.py:522).

**Files in scope:**
- `src/simulation/lifecycle/scenario.py`
- `src/simulation/lifecycle/coverage.py`
- `tests/simulation/lifecycle/test_scenario.py`

**Read-only context:**
- `src/scheduler/watch.py`
- `src/trading/broker_factory.py`
- `src/platform/capability_registry/registry.py`
- `src/simulation/lifecycle/oracle/__init__.py`

**Test strategy:** Integration test: a 2-sim-day no-fault run reaches run-end with all integrity invariants passing; coverage matrix records exercised cells; observer detached + reset_brokers called on teardown.

**Scope fence:** Do NOT modify watch.py beyond Task 3's seam. Clear reset_brokers() + config cache + detach observer between runs. Keep files <400 lines (split runner helpers if needed).

## Task 12: VerdictReporter + blind-spots section

_Complexity: medium_

**Depends on:** [11]

Create src/simulation/lifecycle/verdict.py: aggregate InvariantResults into STABLE/DEGRADED/UNSTABLE (UNSTABLE on ANY integrity violation OR error_swallowed; DEGRADED on non-integrity quality/coverage gaps only; STABLE otherwise). Render the report INCLUDING the mandatory Blind Spots & Trust Calibration section (§9): real fills/latency/slippage, regime, real GPU/Ollama, real network nondeterminism, real concurrency/thread+timer interleaving (OCO-race tests data-shape NOT thread-safety), DB wall-clock exclusion; AND §9.1 — state plainly the live-fill gap is currently UNCOVERED (no live broker-vs-DB monitor exists) with the tracked follow-up. Smoke reports MUST label integrity results 'wiring-only / non-authoritative (SQLite)'.

**Files in scope:**
- `src/simulation/lifecycle/verdict.py`
- `tests/simulation/lifecycle/test_verdict.py`

**Read-only context:**
- `src/simulation/lifecycle/oracle/__init__.py`
- `src/simulation/lifecycle/coverage.py`

**Test strategy:** Unit test: any integrity violation -> UNSTABLE; error_swallowed -> UNSTABLE; coverage-gap-only -> DEGRADED; clean -> STABLE; report contains the blind-spots section INCLUDING the concurrency blind-spot and the 'live-fill gap UNCOVERED' statement; smoke report labels integrity non-authoritative.

**Scope fence:** Do NOT change the zero-tolerance rule. Do NOT omit the blind-spots section. Do NOT reference a live broker-vs-DB monitor as if it exists. Do NOT build entrypoints here.

## Task 13: Entrypoints (smoke + full gate)

_Complexity: medium_

**Depends on:** [12]

Create src/simulation/lifecycle/entrypoints/smoke.py (no Docker/GPU; SQLite-temp via bootstrap; few sim-days; core invariant subset; light fault set; report labels integrity non-authoritative) and entrypoints/full_gate.py (ephemeral 5434 PG via docker-compose.test.yml + pg_wrapper schema bootstrap; many sim-days; all faults + 11 gates; authoritative verdict). Both import bootstrap FIRST then install_prod_guard. Expose run_smoke()/run_full_gate() from package __init__.

**Files in scope:**
- `src/simulation/lifecycle/entrypoints/smoke.py`
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `src/simulation/lifecycle/entrypoints/__init__.py`
- `src/simulation/lifecycle/__init__.py`

**Read-only context:**
- `tests/conftest.py`
- `src/simulation/lifecycle/scenario.py`
- `src/simulation/lifecycle/verdict.py`

**Test strategy:** Smoke entrypoint runs end-to-end on SQLite producing a verdict object (integrity labeled non-authoritative); full_gate guarded to run only when Docker present (skip otherwise).

**Scope fence:** Do NOT make smoke require Docker/GPU. Do NOT make full_gate skip the prod guard. Bootstrap MUST be the first import line in both entrypoints.

## Task 14: Determinism + DST + no-leakage hardening tests

_Complexity: medium_

**Depends on:** [13]

Create tests/simulation/lifecycle/test_determinism.py (two seeded smoke runs produce identical canonical hashes — id-normalized, ORDER BY, PYTHONHASHSEED pinned, prod uuid/random seeded) and round out fault no-leakage coverage. Add the DST fault oracle assertion: the daily cadence fires exactly once across the spring-forward AND fall-back hour, and the reconcile 24h window math stays correct across the DST boundary.

**Files in scope:**
- `tests/simulation/lifecycle/test_determinism.py`
- `tests/simulation/lifecycle/test_fault_framework.py`

**Read-only context:**
- `src/simulation/lifecycle/scenario.py`
- `src/simulation/lifecycle/faults/__init__.py`
- `src/simulation/lifecycle/oracle/invariants.py`

**Test strategy:** Two seeded runs produce identical event-log + DB-snapshot canonical hashes (invariant 9); fault arm/disarm leaves no residue; DST fault asserts single-fire cadence + correct reconcile window math.

**Scope fence:** Do NOT modify harness source to make tests pass — fix root cause if a test fails. Do NOT touch prod code.

## Task 15: CI wiring (smoke workflow + extend pg-tests full gate)

_Complexity: medium_

**Depends on:** [14]

Create NEW .github/workflows/lifecycle-smoke.yml (push/PR; no Docker/GPU; runs run_smoke() via pytest/entry; ensures freezegun installed; integrity results labeled non-authoritative). EXTEND .github/workflows/pg-tests.yml with an additional job reusing its existing 5434 Docker pattern, gated to nightly schedule + workflow_dispatch (NOT every PR), running run_full_gate() and uploading the verdict artifact. Document invocation in the package docstring within src/simulation/lifecycle/__init__.py.

**Files in scope:**
- `.github/workflows/lifecycle-smoke.yml`
- `.github/workflows/pg-tests.yml`
- `src/simulation/lifecycle/__init__.py`

**Read-only context:**
- `src/simulation/lifecycle/entrypoints/smoke.py`
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `requirements.txt`

**Test strategy:** CI dry-run: lifecycle-smoke.yml job green on bare-metal (no Docker); pg-tests.yml nightly job provisions 5434 and produces a verdict artifact. Verified: only pg-tests.yml + stale-base-check.yml pre-exist — there is NO general PR pytest workflow, hence the new smoke workflow.

**Scope fence:** Do NOT run the full gate on every PR (cost) — nightly + workflow_dispatch only. Do NOT add GPU to CI. Do NOT break the existing pg-tests.yml jobs — add a new job alongside them.

