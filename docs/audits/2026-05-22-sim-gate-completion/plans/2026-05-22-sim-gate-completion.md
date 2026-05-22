# Simulator Gate-Completion (#97) — Implementation Plan (revised)

Phase 1 (seam prereqs, parallel): Tasks 1,3,4 independent (get_account+counters; market_data adapters+counter; freeze_at regression-lock). Task 4 is RE-SCOPED to a verification/regression-lock (freezegun already rebinds module-level datetime in both watch.py:33 + universe_scanner.py:19 — NO FrozenDatetime shim is built). Phase 1.5: Task 2 depends on 1; Task 5 (wiring: global config cache + WatchLoop.config + 4 patches) depends on 1+3. Phase 1.7 (parallel build-spikes + guard): Task 6 (ranker candidate + stable tie-break + executor->inv9 columns + reconcile-seam consistency), Task 7 (full inv9-column determinism: recommendation_id + actual_shares + pnl_dollars, with §3.4 no-weaken escalation), Task 8 (provenance guard module). Phase 2 (KEYSTONE): Task 9 rewrites ScenarioRunner to a MULTI-TICK organic open->monitor->exit->reconcile drive (the bug machinery: check_and_manage_open_trades executor.py:1614 + reconcile_dispatch.py:27 + the legitimate exit_reason set executor.py:1876-1941) + reconcile-when-gone + the provenance guard; depends on 2,4,5,6,7,8. Phase 3: Task 10 (full-inv9 determinism + clock robustness) and Task 11 (organic governor-REJECT — drives the sacred governor's reject branch, never bypasses) run after 9. Phase 4: Task 12 (per-fault matrix bound to the SPECIFIC first-principles invariant per family, NOT a verdict-bucket tautology; the 6 families are broker/clock/data/market/network/process_faults.py) depends on 9+11. Phase 5: Task 13 (verdict blind-spots — honest STABLE scope + residual blind-spots incl. synthetic accounting-side ledger). Phase 6: Task 14 rewires entrypoints last. ALL work confined to src/simulation/lifecycle/** + tests; bootstrap.py/prod_guard.py UNTOUCHED. #94 INTERACTION: dual-GPU merges first; DIFF #94's actual scenario.py + scan-path changes BEFORE integrating (it may have touched the scan path, not only overnight symbols), rebase Task 9's scenario.py onto #94, and `git diff --cached | grep '<<<<<<<'` BEFORE `git rebase --continue` (operator's stranded-marker discipline). Builds on sprint/lifecycle-sim/base (held PR #1162).

**Execution order:** [1,3,4] → [2,5] → [6,7,8] → [9] → [10,11] → [12] → [13] → [14]

## Task 1: Add FakeTradingClient.get_account + FakeAccount + call counters

_Complexity: low_

**Depends on:** none

Add a FakeAccount dataclass and FakeTradingClient.get_account() returning a seeded account whose attributes EXACTLY match alpaca_adapter.py:215-221 (.id='sim-account', .status='ACTIVE', .cash/.buying_power/.equity/.portfolio_value=1_000_000.0, .currency='USD'). Make buying_power/equity/etc parameterizable so the governor-reject scenario can seed a below-allocation account. Add a self.calls Counter incremented on get_account/submit_order/get_all_positions/fill_leg (consumed by the provenance guard, Task 9). Unblocks the executor BP gate so organic trades are not fail-closed.

**Files in scope:**
- `src/simulation/lifecycle/fakes/trading_client.py`
- `tests/simulation/lifecycle/test_fake_trading_client.py`

**Read-only:**
- `src/shadow_trading/alpaca_adapter.py`
- `src/shadow_trading/executor.py`

**Test strategy:** Unit test: get_account() returns the seeded surface with each attr name+value matching get_account_info reads; the calls Counter increments on get_account; a parameterized below-allocation buying_power is honored.

**Scope fence:** Do NOT add fill_on_submit/fill_listener (Task 2). Do NOT change existing submit_order/fill_entry/fill_leg behavior. Do NOT touch prod code.

## Task 2: Add fill_on_submit + fill_listener + OCO-leg-fill wiring to FakeTradingClient

_Complexity: medium_

**Depends on:** [1]

Add an opt-in fill_on_submit policy and a fill_listener callback. When fill_on_submit is on, submit_order fills the entry at a deterministic price, books the position, invokes fill_listener(symbol, side, qty, price), and increments calls['submit_order']. Confirm the existing fill_leg (trading_client.py:188) fills an OCO exit leg at the stop/target price and flattens the position; increment calls['fill_leg']. Default fill_on_submit OFF preserves existing synthetic tests. This lets the organic path feed CapitalLedger (invariants 5/6) and lets the exit machinery detect the OCO fill.

**Files in scope:**
- `src/simulation/lifecycle/fakes/trading_client.py`
- `tests/simulation/lifecycle/test_fake_trading_client.py`

**Read-only:**
- `src/shadow_trading/alpaca_adapter.py`
- `src/shadow_trading/executor.py`
- `src/simulation/lifecycle/oracle/capital.py`

**Test strategy:** Unit test: with fill_on_submit on, submit_order books a position + invokes fill_listener once with (symbol,'buy',qty,price); fill_leg flattens the position so get_open_position returns None; with fill_on_submit off behavior is unchanged (existing tests pass).

**Scope fence:** Do NOT wire the listener to CapitalLedger here (ScenarioRunner, Task 10). Keep default OFF. Do NOT touch prod code.

## Task 3: Add FakeMarketData.fetch_ohlcv + fetch_spy_benchmark adapters + counter

_Complexity: low_

**Depends on:** none

Add fetch_ohlcv(universe)->dict[str,DataFrame] (dict comp over fetch_cached_ohlcv) and fetch_spy_benchmark()->DataFrame (non-empty SPY). Windows derived from a fixed deterministic anchor so identical seeds reproduce identical frames. SPY MUST be non-empty (universe_scanner.py:97 aborts on spy.empty) and Close>0 (positive random walk satisfies market_data.py:103 trim). Add a self.calls counter on fetch_ohlcv/fetch_spy (consumed by the provenance guard).

**Files in scope:**
- `src/simulation/lifecycle/fakes/market_data.py`
- `tests/simulation/lifecycle/test_fake_market_llm.py`

**Read-only:**
- `src/data_ingestion/market_data.py`
- `src/scheduler/universe_scanner.py`

**Test strategy:** Unit test: fetch_ohlcv returns a dict keyed by the universe, each non-empty with Open/High/Low/Close/Volume and Close>0; fetch_spy_benchmark non-empty; two same-seed instances return frame-equal results; the calls counter increments.

**Scope fence:** Do NOT change fetch_cached_ohlcv. Do NOT monkeypatch the source module here (wiring, Task 5). Do NOT touch prod code.

## Task 4: Add freeze_at regression-lock test (freezegun already covers both scan namespaces)

_Complexity: low_

**Depends on:** none

Add a regression-lock test asserting that the EXISTING freeze_at(clock) — via freezegun rebinding module-level `from datetime import datetime` — already freezes BOTH src.scheduler.watch.datetime.now(ET) (watch.py:33/737) and src.scheduler.universe_scanner.datetime.now(ET) (universe_scanner.py:19, reads at 87/286/364) to clock.now(), with originals restored after the context. Do NOT build a FrozenDatetime shim — it is redundant. If clock.py contains any prior shim machinery for this, the test must pass with that shim disabled (proving freezegun alone suffices); remove dead shim code if present.

**Files in scope:**
- `src/simulation/lifecycle/clock.py`
- `tests/simulation/lifecycle/test_clock.py`

**Read-only:**
- `src/scheduler/watch.py`
- `src/scheduler/universe_scanner.py`

**Test strategy:** Unit test: inside freeze_at, src.scheduler.watch.datetime.now(ET) and src.scheduler.universe_scanner.datetime.now(ET) both equal clock.now(); after the context both are the original datetime class; existing freeze_at pandas/time assertions still pass. Test must NOT depend on any shim.

**Scope fence:** Do NOT build a FrozenDatetime shim. Do NOT change VirtualClock or freeze_at's freezegun/pandas behavior beyond removing dead shim code. Do NOT touch prod code. Do NOT patch any module manually.

## Task 5: Add wiring.py: prime_config (global + WatchLoop.config) + install_organic_patches

_Complexity: medium_

**Depends on:** [1, 3]

New module src/simulation/lifecycle/wiring.py: (a) prime_config(dsn, overrides) — clear _config_module._config_cache then prime load_config() with shadow_trading.enabled=True, llm.enabled=True, use_grammar_enforcement=False, and the 5434 sim DSN (NOT prod); (b) build_watch_config(dsn, overrides) — return the SAME dict for WatchLoop.config/ctx.config, because enhance_packet_with_llm reads its PASSED-IN config at packet_writer.py:1158-1159 (not a global load_config); (c) install_organic_patches(fake_tc, fake_md, fake_llm, universe) — apply the 4 monkeypatches (_get_trading_client->fake on alpaca_adapter; market_data.fetch_ohlcv/fetch_spy_benchmark->fake; packet_writer.generate->fake_llm.generate + is_llm_available->True; sp100.get_sp100_universe->small list) and return an undo() closure restoring every original.

**Files in scope:**
- `src/simulation/lifecycle/wiring.py`
- `tests/simulation/lifecycle/test_wiring.py`

**Read-only:**
- `src/config/__init__.py`
- `src/shadow_trading/alpaca_adapter.py`
- `src/data_ingestion/market_data.py`
- `src/llm/packet_writer.py`

**Test strategy:** Unit test: prime_config sets the cache with the 3 keys + sim DSN; build_watch_config returns the equivalent dict; install_organic_patches swaps each target and undo() restores every original (identity equality post-undo); the DSN is the 5434 sim DSN, never a prod signature.

**Scope fence:** Do NOT call _run_scan here. Do NOT edit src.universe.sp100 (read-only — patch at runtime only). Keep all patches reversible. Do NOT touch bootstrap.py/prod_guard.py.

## Task 6: Build-spike: ranker yields a candidate, stable tie-break, executor->inv9 columns, reconcile-seam consistency

_Complexity: medium_

**Depends on:** [3, 5]

Read-only verification spike capturing findings as inline comments + a test: (a) rank_universe/get_top_candidates yields >=1 candidate from the FakeMarketData/FakeLLM feature shape (tune fake feature VALUES if filtered); confirm the ranker tie-break is stable OR the fakes have no ties (inv9 ranker-ordering); (b) the organic open_shadow_trade INSERT column set covers every inv9-hashed column; (c) reconcile_all_paper_trades (reconcile_dispatch.py:27) reads positions via the SAME fake _get_trading_client seam the executor booked the entry through (consistency, so monitor/exit and reconcile observe the same fake broker state).

**Files in scope:**
- `src/simulation/lifecycle/fakes/llm.py`
- `src/simulation/lifecycle/fakes/market_data.py`

**Read-only:**
- `src/scheduler/universe_scanner.py`
- `src/shadow_trading/executor.py`
- `src/shadow_trading/reconcile_dispatch.py`
- `src/journal/store.py`

**Test strategy:** Test: the fake feature dict produces >=1 ranked candidate through the real ranker (import rank_universe, feed fake features); a docstring documents the executor INSERT->inv9 column mapping and the reconcile position-read seam identity.

**Scope fence:** Do NOT modify the ranker, executor, journal, or reconcile. Only tune fake feature VALUES. Do NOT touch prod code.

## Task 7: Build-spike: full inv9-column determinism (recommendation_id + actual_shares + pnl_dollars)

_Complexity: medium_

**Depends on:** [4, 5]

Read-only verification: confirm reproducibility across two seeded+frozen-clock runs of EVERY inv9-hashed column that involves runtime math/minting: recommendation_id (journal.store mint), actual_shares (floor(buying_power*pct/entry_price) float math), pnl_dollars (derived from the deterministic OCO fill price). If any embeds a UUID/wall-clock or unstable ordering, document the exact source and apply the §3.4 escalation: prefer fix-under-frozen-clock in the sim seeding; if the source is PROD, record either (i) the operator-approved minimal prod fix WITH an explicit constraint-waiver note, or (ii) the exclude-from-authoritative decision. Output a finding consumed by Tasks 10/13. NEVER weaken inv9.

**Files in scope:**
- `tests/simulation/lifecycle/test_recid_determinism.py`

**Read-only:**
- `src/journal/store.py`
- `src/shadow_trading/executor.py`
- `src/scheduler/universe_scanner.py`
- `src/simulation/lifecycle/oracle/_checks_db.py`

**Test strategy:** Test: drive log_recommendation + open_shadow_trade twice under freeze_at + fixed seed; assert recommendation_id, actual_shares, pnl_dollars identical. If non-deterministic, the test documents the source + the chosen §3.4 escalation path.

**Scope fence:** Do NOT modify prod journal/store/executor. If a prod fix is required, record the remediation note + waiver decision only — do not apply it without operator approval. Do NOT weaken the inv9 hash set.

## Task 8: Add provenance guard module (seam call-counts + executor-only artifact + runtime DSN/column)

_Complexity: medium_

**Depends on:** [1, 2, 3]

New module src/simulation/lifecycle/provenance.py: assert_real_path_executed(fake_tc, fake_md, fake_llm, oracle_conn, primed_dsn, rows). Asserts (1) fake_md.calls['fetch_ohlcv']>=1, fetch_spy>=1, fake_llm.calls['generate']>=1, fake_tc.calls['get_account']>=1, fake_tc.calls['submit_order']>=1; (2) every open shadow_trade row's order_type in {bracket,simple_with_stop} (an executor-only artifact the runner never sets); (3) RUNTIME identity: oracle_conn DSN == primed_dsn == the 5434 sim DSN (never prod) and the written column set covers the inv9-hashed columns (promoted from §7 build-time checklist). Raises a clear ProvenanceError on any miss.

**Files in scope:**
- `src/simulation/lifecycle/provenance.py`
- `tests/simulation/lifecycle/test_provenance.py`

**Read-only:**
- `src/simulation/lifecycle/fakes/trading_client.py`
- `src/simulation/lifecycle/fakes/market_data.py`
- `src/simulation/lifecycle/fakes/llm.py`

**Test strategy:** Unit test: with all seams invoked + bracket rows + matching DSN, the guard passes; with a zeroed counter (simulating a missed patch) it FAILS (negative test); with a prod-signature DSN it FAILS.

**Scope fence:** Do NOT call _run_scan here (the runner wires this in, Task 10). Do NOT touch prod code. The guard READS the fakes' counters; it does not mutate broker state.

## Task 9: Rewrite ScenarioRunner: multi-tick organic open->monitor->exit->reconcile + provenance

_Complexity: high_

**Depends on:** [2, 4, 5, 6, 7, 8]

Rewrite ScenarioRunner to drive the REAL inline path organically across multiple virtual ticks. Execute the install order: prod_guard (existing) -> reset brokers + prime_config + build_watch_config (Task 5) -> install_organic_patches -> seed account ($1M) + register fill_listener routing fills into self.ledger.apply_fill + reset fake counters -> under freeze_at(clock): TICK A self.watch_loop._run_scan() (open, bypass _should_scan); advance clock; TICK B fake fill_leg fills an OCO exit leg, then check_and_manage_open_trades(db_path=<5434 dsn>, source_filter='paper') (executor.py:1614) + reconcile_all_paper_trades(dry_run=False) (reconcile_dispatch.py:27) -> run provenance.assert_real_path_executed -> run the oracle on the organic rows. Add a reconcile-when-gone mode (broker-flat, no clean close) asserting zero orphans. Remove the synthetic _insert_recommendation/_insert_shadow_trade/_open_trade/_close_trade raw-INSERT path and the manual scenario.py:212 ledger feed. Teardown restores all patches (undo()), config cache, brokers, faults, observer (try/finally).

**Files in scope:**
- `src/simulation/lifecycle/scenario.py`
- `tests/simulation/lifecycle/test_scenario.py`

**Read-only:**
- `src/scheduler/watch.py`
- `src/scheduler/universe_scanner.py`
- `src/shadow_trading/executor.py`
- `src/shadow_trading/reconcile_dispatch.py`

**Test strategy:** Integration test (PG): organic open->exit->reconcile yields the CLEAN-CLOSE bar (1 clean rec + 1 clean trade, terminal status, exit_reason in {take_profit,stop_loss,stop_hit,target_2_hit}, DB-closed==broker-flat, held_for_orders cleared, zero reconciled/synthetic/orphan rows); the provenance guard passes; reconcile-when-gone yields zero orphans; teardown leaves no residual patch (originals restored, _config_cache None).

**Scope fence:** Do NOT add the governor-reject scenario (Task 11), per-fault matrix (Task 12), or verdict rewrite (Task 13) here. Do NOT touch bootstrap.py/prod_guard.py. Do NOT edit prod handlers — only call them + monkeypatch via wiring.py. Keep overnight subprocess handlers DEFERRED (fired-not-asserted).

## Task 10: Add organic full-inv9 determinism + clock-robustness tests

_Complexity: medium_

**Depends on:** [9]

Add the organic determinism test: two organic open->exit runs on the same seed produce identical inv9 hashes across EVERY hashed column (recommendation_id, ticker, status, actual_shares, order_type, exit_reason, pnl_dollars); fail loudly and reference the Task 7 §3.4 escalation if any column diverges. Add clock-robustness coverage: assert the organic scan+exit+reconcile runs fully under freeze_at (in-process), and document/assert that subprocess-spawning overnight handlers stay DEFERRED (fired-not-asserted) and DBLogHandler log timestamps are NOT asserted on.

**Files in scope:**
- `tests/simulation/lifecycle/test_scenario_organic.py`
- `tests/simulation/lifecycle/test_clock_robustness.py`

**Read-only:**
- `src/simulation/lifecycle/scenario.py`
- `src/simulation/lifecycle/clock.py`
- `src/simulation/lifecycle/oracle/_checks_db.py`

**Test strategy:** Test: hash(run1)==hash(run2) on the full inv9 snapshot for the organic open->exit path; the overnight subprocess stages are recorded deferred on the coverage matrix; no assertion on log-thread timestamps.

**Scope fence:** Do NOT attempt to freeze subprocess children (impossible). Do NOT add prod handlers. Do NOT weaken inv9.

## Task 11: Add organic governor-REJECT scenario

_Complexity: medium_

**Depends on:** [9]

Add an organic governor-reject scenario (test + a ScenarioRunner mode/flag): seed a condition that trips ONE specific governor gate (preferred: buying_power just below the allocation -> BP reject; alternatives: candidate over the position-size cap, or max-positions already full) and run the organic scan. Assert the organic outcome: a recommendations row with the REJECTED status, ZERO shadow_trades rows, and NO recommendation_id IS NULL orphan (the reject path must not write a NULL-rec orphan). Confirm the real src/risk/governor.py reject branch executed organically (not mocked). This drives the sacred risk governor's reject path, never bypassing it.

**Files in scope:**
- `src/simulation/lifecycle/scenario.py`
- `tests/simulation/lifecycle/test_scenario_governor_reject.py`

**Read-only:**
- `src/risk/governor.py`
- `src/scheduler/universe_scanner.py`
- `src/shadow_trading/executor.py`

**Test strategy:** Integration test (PG): the seeded condition trips the targeted gate organically; assert rejected-status recommendation row, zero shadow_trades, zero recommendation_id IS NULL orphan; assert the governor reject branch was reached (via the rejected status / a coverage hook), not short-circuited.

**Scope fence:** Do NOT bypass, weaken, or mock the governor. Do NOT add the per-fault matrix (Task 12). Do NOT edit src/risk/governor.py. Keep the seed scoped to one gate per assertion.

## Task 12: Add per-fault matrix with first-principles invariant binding

_Complexity: high_

**Depends on:** [9, 11]

Add src/simulation/lifecycle/entrypoints/fault_matrix.py: a FAULT_INVARIANT_BINDING mapping each of the 6 fault families (broker/clock/data/market/network/process) to (fault_ctor, the SPECIFIC invariant it SHOULD violate, a first-principles rationale string) — e.g. data/BP-rejection -> inv2 zero_orphans (writes recommendation_id=NULL); market/phantom-close -> inv3 zero_synthetic_closes; broker/sticky-position -> DB==broker. run_fault_matrix(conn_factory) builds a FRESH ScenarioRunner(faults=[ctor]) per fault, runs the organic drive, asserts the BOUND invariant failed (with the rationale in the message) AND the aggregate verdict is DEGRADED/UNSTABLE, and aggregates into a coverage report. Teardown disarms each fault (FaultRegistry reverse-order). Wire into full_gate alongside (not replacing) the clean STABLE run. Finalize the exact bindings against the 6 concrete fault classes at build.

**Files in scope:**
- `src/simulation/lifecycle/entrypoints/fault_matrix.py`
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `tests/simulation/lifecycle/test_fault_matrix.py`

**Read-only:**
- `src/simulation/lifecycle/faults/__init__.py`
- `src/simulation/lifecycle/faults/broker_faults.py`
- `src/simulation/lifecycle/faults/clock_faults.py`
- `src/simulation/lifecycle/faults/data_faults.py`

**Test strategy:** Test: each of the 6 fault families breaks its BOUND invariant (assert the specific invariant id failed, with rationale) and yields DEGRADED/UNSTABLE; the clean run stays STABLE; after the matrix no fault is armed and no patch leaks; the aggregate report lists per-fault (family, invariant, verdict).

**Scope fence:** Do NOT change FaultRegistry or the fault families (already unit-tested). Do NOT assert verdict==EXPECTED[family] (tautology) — assert the SPECIFIC bound invariant. Do NOT make the clean-run STABLE depend on the matrix. Keep each fault run isolated (fresh conn + teardown). NOTE: market_faults.py, network_faults.py, process_faults.py are also read-only inputs — add them to scope if the binding references them.

## Task 13: Rewrite verdict blind-spots: STABLE certifies organic open->exit->reconcile + reject + matrix

_Complexity: low_

**Depends on:** [9, 11, 12]

Rewrite the CORE-PATH-vs-FULL-LOOP blind spot in verdict.py: STABLE now certifies the ORGANIC open->monitor->exit->reconcile lifecycle + the organic governor-reject + the per-fault matrix (all asserted on organically-emitted rows + the provenance guard). Enumerate the HONEST residual blind-spots: real fills/latency, concurrency, the synthetic-accounting-side CapitalLedger feed (organic on trade side / synthetic on accounting side, §8), overnight subprocess handlers (undrivable — freezegun can't reach subprocess children), real broker behavior, market regimes, DST shape-only, DB wall-clock excluded. Add the clock-robustness caveat (organic path frozen in-process via freezegun's module-level datetime rebind; subprocess handlers deferred). Keep classify()/INTEGRITY_INVARIANTS rules unchanged.

**Files in scope:**
- `src/simulation/lifecycle/verdict.py`
- `tests/simulation/lifecycle/test_verdict.py`

**Read-only:**
- `src/simulation/lifecycle/scenario.py`
- `src/simulation/lifecycle/provenance.py`

**Test strategy:** Test: the rendered blind-spots assert STABLE certifies the organic open->exit->reconcile + governor-reject + fault matrix and enumerate the residual blind-spots (real fills/latency, concurrency, synthetic accounting-side ledger, subprocess, real broker, regimes, DB wall-clock); classify() rules unchanged (zero-tolerance integrity); the deferred-subprocess + synthetic-ledger caveats are present.

**Scope fence:** Do NOT change classify()/Verdict/INTEGRITY_INVARIANTS rules — only the blind-spots prose. Do NOT soften the zero-tolerance rule. Do NOT overstate (no real-fill/concurrency claims).

## Task 14: Rewire smoke + full_gate to organic; update package docstring

_Complexity: medium_

**Depends on:** [9, 12, 13]

Update entrypoints/smoke.py (SQLite, non-authoritative) and full_gate.py (PG, authoritative) to run the rewritten organic ScenarioRunner (open->exit->reconcile), wire run_fault_matrix and the governor-reject scenario into the full gate alongside the clean STABLE run. Update __init__.py package docstring + STABLE definition to state STABLE certifies the organic open->monitor->exit->reconcile + governor-reject + fault-matrix lifecycle. Confirm CI workflows still reference the entrypoints (read-only). Keep the smoke tier's 'non-authoritative (SQLite)' label.

**Files in scope:**
- `src/simulation/lifecycle/entrypoints/smoke.py`
- `src/simulation/lifecycle/__init__.py`
- `tests/simulation/lifecycle/test_entrypoints.py`

**Read-only:**
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `src/simulation/lifecycle/entrypoints/fault_matrix.py`
- `.github/workflows/lifecycle-smoke.yml`

**Test strategy:** Test: run_smoke completes on SQLite with the organic runner labeled integrity non-authoritative; run_full_gate returns an authoritative verdict from the organic open->exit->reconcile run + includes the governor-reject + fault-matrix aggregate; the package docstring/STABLE wording matches the organic certification.

**Scope fence:** Do NOT change the smoke tier's non-authoritative labeling or PG authority semantics. Do NOT touch bootstrap/prod_guard. Do NOT edit CI yml beyond confirming references (read-only).

