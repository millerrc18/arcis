# Design Spec — #97: Organic Full-Lifecycle Gate for the Lifecycle Simulator (REV 2)

## 1. Overview

The lifecycle simulator (held PR #1162, branch `sprint/lifecycle-sim/base`, worktree `C:/arcis/hl-sim`) currently runs a **synthetic** ScenarioRunner: it hand-writes clean `recommendations`/`shadow_trades` rows (`scenario.py:242-272`) and manually calls `submit_order`/`fill_entry` on `FakeTradingClient` (`scenario.py:211`). The 9 oracle invariants therefore assert on rows the runner itself crafted, not on rows the real code emitted. The verdict's own Blind-Spots section confesses this (`verdict.py:87-93`, "CORE-PATH-vs-FULL-LOOP GAP (CRITICAL)").

This design turns the simulator into the **FULL AUTHORITATIVE organic gate** that exercises the BUG MACHINERY, not just the open path. The motivating production incidents (orphans, phantom closes, close-didn't-clear, the reconcile cycle) all live in the EXIT / MONITOR / RECONCILE handlers and the governor REJECT branches — so the gate MUST drive those organically. The ScenarioRunner drives the REAL inline path across MULTIPLE virtual ticks:
1. **open** — `WatchLoop._run_scan()` (`watch.py:728`) → `scan → features → packet → LLM → governor → executor.open_shadow_trade → reconcile`.
2. **monitor → exit** — advance the virtual clock, the FakeTradingClient fills an OCO exit leg (`fakes/trading_client.py:188 fill_leg`), then `check_and_manage_open_trades` (`executor.py:1614`) + `reconcile_all_paper_trades` (`reconcile_dispatch.py:27`) detect the exit, write a LEGITIMATE `exit_reason`, run OCO-cancel + close-clears-`held_for_orders` + no-phantom-close.
3. **reconcile-when-gone** — a second organic drive where the position is broker-flat with no clean close, exercising the orphan-breeding path and asserting zero orphans result.
4. **governor REJECT** — a seeded scenario that organically trips a specific governor gate and asserts a rejected recommendation with ZERO shadow_trade and NO `recommendation_id=NULL` orphan.

The oracle asserts on **organically-emitted rows** at every stage. A green run must **PROVE** (via runtime provenance guards) that the real executor wrote the rows. It also adds a **per-fault matrix** that binds each fault to the SPECIFIC invariant it should violate (first principles, not a tautological verdict-bucket lookup).

**Goal:** a STABLE verdict certifies the ORGANIC full lifecycle — open → monitor → exit → reconcile, governor-reject, and the fault matrix — unblocking the v0.36.50 merge of #1162 and the destructive #95 clean-slate wipe.

**Hard constraints (preserved):**
- All edits confined to `src/simulation/lifecycle/**` + `tests/simulation/lifecycle/**`. NO prod-code edits — the sim READS the real handlers and monkeypatches at module boundaries.
- `bootstrap.py` and `prod_guard.py` (the bulletproof prod-DB isolation) are UNTOUCHED.
- Builds ON `sprint/lifecycle-sim/base` (extends the held PR, does not replace it).
- Risk governor is sacred — the governor-reject scenario DRIVES the real reject path; it never bypasses or weakens a gate.

## 2. Architecture

### 2.1 The scan path being driven (verified)
`WatchLoop._run_scan()` (watch.py:728) → `from src.scheduler.universe_scanner import run_universe_scan, ScanContext` → `run_universe_scan(ctx)`. Inside `run_universe_scan` (function-local imports at `universe_scanner.py:66-73`, resolved at call time):
- `get_sp100_universe()` (universe_scanner.py:92, from `src.universe.sp100`)
- `fetch_ohlcv(universe)->dict[str,DataFrame]` + `fetch_spy_benchmark()->DataFrame` (universe_scanner.py:93-94, from `src.data_ingestion.market_data`)
- features → rank → `enhance_packet_with_llm` (universe_scanner.py:229, from `src.llm.packet_writer`)
- governor gate → `log_recommendation(...)` (→ `recommendations`) or `_record_bp_rejection_pre_llm` (universe_scanner.py:192/199, the orphan path that writes `recommendation_id=None`)
- `open_shadow_trade(rec_id, packet, feat)` (→ executor → `shadow_trades`)
- back in `_run_scan`: `reconcile_all_paper_trades(dry_run=False)` (watch.py:784-785).

The scan is **inline**, gated via `_should_scan → _safe_run('scan', _run_scan)` in `_run_sync_body` — it is NOT an `on_tick` registered handler. The runner therefore calls `self.watch_loop._run_scan()` **directly**, under `freeze_at(clock)`, bypassing `_should_scan`.

### 2.2 The exit/monitor/reconcile path being driven (verified — THE bug machinery)
- `check_and_manage_open_trades(db_path, source_filter)` (executor.py:1614) reads open shadow trades, queries the broker via the trading-client seam for OCO leg fills, and writes the legitimate `exit_reason` set: `take_profit`/`stop_loss` (executor.py:1876), `stop_loss` (1907), `stop_hit` (1939), `target_2_hit` (1941). It cancels the sibling OCO leg and clears `held_for_orders`.
- `reconcile_all_paper_trades(dry_run=False)` (reconcile_dispatch.py:27) delegates per-desk; each desk resolves the broker via `_get_trading_client` (same seam the executor booked through) and detects broker-flat / stale positions. Its synthesizing branches write `exit_reason IN ('reconciled_stale','resolved_stuck','synthetic')` and/or `order_type='reconciled'` — the rows the oracle must NOT see on a clean close, but SHOULD see when we deliberately drive the gone/sticky paths under faults.

The runner advances the VirtualClock between scan and monitor, drives an OCO leg fill on the fake, then calls `check_and_manage_open_trades(db_path=<5434 DSN>, source_filter='paper')` and `reconcile_all_paper_trades(dry_run=False)` — all under `freeze_at(clock)`.

### 2.3 Clock seam — freezegun ALREADY covers both scan namespaces (corrected)
Both `src.scheduler.watch` (watch.py:33) and `src.scheduler.universe_scanner` (universe_scanner.py:19) do `from datetime import datetime` at MODULE level. freezegun's `freeze_time` rebinds module-level `datetime` symbols, so the EXISTING `freeze_at(clock)` ALREADY freezes `watch.datetime.now(ET)` (watch.py:733/737) and `universe_scanner.datetime.now(ET)` (universe_scanner.py:87/286/364). **No FrozenDatetime shim is built.** The clock task is re-scoped to a REGRESSION-LOCK: assert (with any shim disabled) that freezegun alone makes both namespace reads == `clock.now()`. (Note: 192/199 is the `_record_bp_rejection_pre_llm` orphan path, not a clock read.)

### 2.4 Component map (all in `src/simulation/lifecycle/`)

| Component | File | Change |
|---|---|---|
| `FakeTradingClient` | `fakes/trading_client.py` | ADD `FakeAccount` + `get_account()`; ADD `fill_on_submit` policy (entry auto-fills + books position), a `fill_listener` callback for ledger routing, and CALL COUNTERS (`get_account` / `submit_order` / `get_all_positions` invocation counts) for the provenance guard. `fill_leg`/`get_all_positions`/`get_open_position` already exist. |
| `FakeMarketData` | `fakes/market_data.py` | ADD `fetch_ohlcv(universe)->dict` + `fetch_spy_benchmark()->DataFrame` adapters (non-empty SPY, Close>0); ADD a fetch-invocation counter. |
| `FakeLLM` | `fakes/llm.py` | ADD a `generate`-invocation counter; tune feature/conviction values so the ranker yields ≥1 candidate (Task spike). |
| `freeze_at` | `clock.py` | UNCHANGED behavior — covered by a regression-lock test only (NO shim). |
| `prime_config` + patches | NEW `wiring.py` | clear+prime global `load_config()` cache (for `open_shadow_trade`'s `load_config()` at executor.py:567); ALSO set `WatchLoop.config`/`ctx.config` (for `enhance_packet_with_llm`'s passed-in config at packet_writer.py:1158-1159); build/apply patch list (sp100, market_data, packet_writer, `_get_trading_client`) + `undo()`. |
| `ScenarioRunner` | `scenario.py` | REWRITE: multi-tick organic drive (open→monitor→exit→reconcile); organic install-order; fill→ledger hook; runtime provenance guards; governor-reject mode; reconcile-when-gone mode. |
| Governor-reject scenario | `scenario.py` + helper | Seed BP/position conditions to trip a specific gate organically; assert rejected-rec + zero-trade + zero-orphan. |
| Provenance guard | NEW `provenance.py` | Assert each patched seam was invoked ≥1 AND the written row carries an executor-only artifact (`order_type IN {bracket,simple_with_stop}`); RUNTIME DSN/column checks. |
| Per-fault matrix | NEW `entrypoints/fault_matrix.py` | Per-fault fresh runner → classify → assert the SPECIFIC first-principles invariant violated → aggregate. |
| Verdict/blind-spots | `verdict.py` | REWRITE: STABLE now certifies the organic open→monitor→exit→reconcile + governor-reject + fault matrix; enumerate honest residual blind-spots. |

### 2.5 Install order (organic boot, executed in `ScenarioRunner._setup` + `run`)
1. `install_prod_guard()` (already in `__init__`; preserved).
2. Bootstrap ephemeral 5434 PG + schema (done by `full_gate._provision_pg`; the runner receives the conn).
3. Clear config cache (`_config_module._config_cache = None`) then PRIME `load_config()` with `shadow_trading.enabled=True`, `llm.enabled=True`, `use_grammar_enforcement=False`, and the **5434 sim DSN** (NOT prod). ALSO set `WatchLoop.config` / `ctx.config` to the same dict (the LLM-enabled gate reads the passed-in config, packet_writer.py:1158-1159).
4. Patch `src.shadow_trading.alpaca_adapter._get_trading_client -> (lambda **kw: fake_trading_client)` (the SDK seam; the fake has `get_account`).
5. Patch `src.data_ingestion.market_data.fetch_ohlcv -> fake.fetch_ohlcv` and `.fetch_spy_benchmark -> fake.fetch_spy_benchmark`.
6. Patch `src.llm.packet_writer.generate -> fake_llm.generate` and `src.llm.packet_writer.is_llm_available -> (lambda: True)`.
7. Patch `src.universe.sp100.get_sp100_universe -> (lambda: SIM_UNIVERSE)` (small fixed deterministic list).
8. Seed the account in the fake: for the happy/exit path `buying_power = equity = portfolio_value = cash = 1_000_000.0` (above any single allocation, BP path never fires). For the governor-reject scenario, seed the SPECIFIC tripping condition instead.
9. Register `fill_listener = lambda **kw: self.ledger.apply_fill(**kw)` and reset the fake call counters.
10. Under `freeze_at(clock)` (freezegun freezes both scan namespaces — §2.3): TICK A → `self.watch_loop._run_scan()` (open). Advance clock. TICK B → fake fills an OCO leg, then `check_and_manage_open_trades(...)` + `reconcile_all_paper_trades(dry_run=False)` (monitor→exit→reconcile).
11. Run the PROVENANCE guard (assert seams invoked ≥1, executor-only artifact present, runtime DSN/column identity).
12. Run the oracle on the organic rows.

All monkeypatches are stashed and restored in `_teardown` (try/finally, no leakage; mirrors FaultInjector arm/disarm), plus `_config_cache` reset and `reset_brokers()`.

## 3. Data Model

**No schema changes.** The simulator writes to the existing registry tables on the ephemeral 5434 PG via the REAL code: `recommendations` (via `log_recommendation`), `shadow_trades` (via `open_shadow_trade` and updated by `check_and_manage_open_trades`/reconcile). No `CREATE`/`ALTER TABLE` — schema created by `src.schema.postgres.create_all_tables` (full_gate.py).

### 3.1 Organic CLEAN-CLOSE bar (the primary bar — after open→exit→reconcile)
- exactly **1** `recommendations` row (recommendation_id NOT NULL, organic from `log_recommendation`).
- exactly **1** `shadow_trades` row: `order_type IN {'bracket','simple_with_stop'}` (executor.py:889/925), `recommendation_id` NOT NULL (executor.py:817), and after exit: `status` terminal (closed), `exit_reason IN {'take_profit','stop_loss','stop_hit','target_2_hit'}` (the LEGITIMATE set, executor.py:1876-1941) — explicitly NOT IN `{'reconciled_stale','resolved_stuck','synthetic'}`.
- **zero** `order_type='reconciled'` rows and **zero** `recommendation_id IS NULL` orphan rows (else inv2 trips).
- **zero** `exit_reason IN ('reconciled_stale','resolved_stuck','synthetic')` and **zero** phantom/synthetic-close rows (else inv3 trips).
- **DB-position closed == broker flat**: after the clean close, the fake reports the position closed (`get_open_position` None) AND the DB row is terminal — 1:1 attribution intact.
- `held_for_orders` cleared (the close-clears-held logic ran).

### 3.2 Organic RECONCILE-WHEN-GONE bar
- Drive a position that is broker-flat (fake `get_open_position` returns None) without a clean executor close. Assert reconcile resolves it WITHOUT breeding an orphan: **zero** `recommendation_id IS NULL` rows and a single coherent terminal row. (This exercises the orphan-breeding path organically and asserts inv2 holds.)

### 3.3 Organic GOVERNOR-REJECT bar
- Seed a condition that trips ONE specific gate (e.g. `buying_power` just below the allocation → BP reject; OR a candidate exceeding the position-size cap; OR max-positions already full). Assert: a `recommendations` row exists with the REJECTED status, **zero** `shadow_trades` rows, and **NO** `recommendation_id IS NULL` orphan (the reject path must not write a NULL-rec orphan). This DRIVES `src/risk/governor.py` organically — it does not bypass it.

### 3.4 Oracle invariant 9 (determinism) hashed columns
Inv9 hashes the business-key set `(recommendation_id, ticker, status, actual_shares, order_type, exit_reason, pnl_dollars)` ORDER BY business keys (`_checks_db.py:139-156`) — SERIAL PKs and raw timestamps excluded. **Every hashed column must be reproducible across two seeded+frozen runs**, not just `recommendation_id`:
- `recommendation_id` (mint path, journal.store) — Task spike.
- `actual_shares` — computed `floor(buying_power * pct / entry_price)`; float math must be deterministic under fixed seeds + frozen entry price.
- `pnl_dollars` — derived from the deterministic OCO fill price.
- `status` / `exit_reason` / `order_type` — set by the executor; deterministic given the driven path.
- **ranker tie-ordering** — `rank_universe`/`get_top_candidates` must be pinned to a STABLE tie-break key (e.g. ticker) so two runs select the same candidate; the sim controls this via fixed FakeMarketData/FakeLLM feature values and (if the ranker's tie-break is unstable) by ensuring the fake features have no ties.

**Determinism escalation policy:** if a nondeterminism source is found in PROD code (e.g. id-mint embeds a UUID/wall-clock; ranker tie-break is unstable and ties are unavoidable), the resolution is EITHER (a) an operator-approved minimal prod fix WITH an explicit constraint-waiver recorded in the PR (the no-prod-edit constraint is waived only with operator sign-off), OR (b) exclude that specific run from AUTHORITATIVE status and document the exclusion in the verdict. NEVER weaken the inv9 hash set to make it pass. The build-time spike (Task 8) determines which path applies and records the finding.

## 4. API / Seam Design

### 4.1 `FakeTradingClient.get_account()` + call counters (fakes/trading_client.py)
```
class FakeAccount:
    def __init__(self, *, account_id='sim-account', status='ACTIVE',
                 cash=1_000_000.0, buying_power=1_000_000.0,
                 equity=1_000_000.0, portfolio_value=1_000_000.0,
                 currency='USD'):
        self.id=account_id; self.status=status; self.cash=cash
        self.buying_power=buying_power; self.equity=equity
        self.portfolio_value=portfolio_value; self.currency=currency
# FakeTradingClient.__init__: self._account=FakeAccount(); accept fill_listener, fill_on_submit
#   self.calls = Counter()  # 'get_account','submit_order','get_all_positions','fill_leg'
    def get_account(self): self.calls['get_account']+=1; return self._account
```
Attribute names match `alpaca_adapter.py:215-221` exactly. The `calls` Counter feeds the provenance guard (§4.6). The account is parameterizable so the governor-reject scenario can seed `buying_power` below the allocation.

### 4.2 Auto-fill + ledger hook + OCO leg fill (fakes/trading_client.py)
`submit_order` gains opt-in `fill_on_submit` (default off, preserving existing synthetic tests): when on, the entry fills immediately at a deterministic price, books the position, and invokes `self._fill_listener(symbol, side, qty, price)` if set. `fill_leg` (already at trading_client.py:188) fills an OCO exit leg at the stop or target price and marks the position flat; the monitor drive uses it. The runner registers `fill_listener = lambda **kw: self.ledger.apply_fill(**kw)`. This feeds the CapitalLedger organic fills on the trade side (invariants 5/6) and lets the exit/reconcile machinery see the broker state transition.

### 4.3 FakeMarketData adapters + counter (fakes/market_data.py)
```
def fetch_ohlcv(self, universe):
    self.calls['fetch_ohlcv']+=1
    return {t: self.fetch_cached_ohlcv(t,start,end) for t in universe}
def fetch_spy_benchmark(self):
    self.calls['fetch_spy']+=1
    return self.fetch_cached_ohlcv('SPY',start,end)  # non-empty, Close>0
```
SPY must be NON-empty (universe_scanner.py:97 aborts on `spy.empty`); the positive random walk keeps Close>0 (satisfies `market_data.py:103` trim). Window bounds derived from a fixed anchor so identical seeds reproduce identical frames.

### 4.4 `freeze_at` — verification only, NO shim (clock.py + test)
The existing `freeze_at(clock)` uses freezegun + pandas Timestamp pinning. Because both `src.scheduler.watch` (watch.py:33) and `src.scheduler.universe_scanner` (universe_scanner.py:19) import `datetime` at module level, freezegun ALREADY rebinds them — the existing context manager freezes both `datetime.now(ET)` reads with no additional machinery. The clock work is therefore a REGRESSION-LOCK test (Task 4): with any prior shim disabled, assert `src.scheduler.watch.datetime.now(ET) == clock.now()` and `src.scheduler.universe_scanner.datetime.now(ET) == clock.now()` inside the context, and originals restored after. Do NOT build a FrozenDatetime shim.

### 4.5 `prime_config()` + patch helpers (NEW wiring.py)
(a) `prime_config(dsn, overrides)` — clears `_config_module._config_cache` then sets it to a dict with `shadow_trading.enabled=True`, `llm.enabled=True`, `use_grammar_enforcement=False`, and the 5434 sim DSN, merged over a minimal base. (b) `build_watch_config(dsn, overrides)` — the SAME dict for `WatchLoop.config`/`ctx.config`, because `enhance_packet_with_llm` reads its PASSED-IN config (`ctx.config == WatchLoop.config`) at packet_writer.py:1158-1159, NOT a global `load_config()`. (c) `install_organic_patches(fake_trading_client, fake_market_data, fake_llm, universe)` — applies the 4 monkeypatches (steps 4-7) and returns an `undo()` closure. Keeps `scenario.py` readable and the patch list testable.

### 4.6 Provenance guard (NEW provenance.py)
```
def assert_real_path_executed(fake_tc, fake_md, fake_llm, oracle_conn, rows):
    # 1) the patched seams were actually invoked by the real code
    assert fake_md.calls['fetch_ohlcv'] >= 1
    assert fake_md.calls['fetch_spy'] >= 1
    assert fake_llm.calls['generate'] >= 1
    assert fake_tc.calls['get_account'] >= 1     # executor BP gate hit it
    assert fake_tc.calls['submit_order'] >= 1    # executor placed an order
    # 2) the written row carries an executor-ONLY artifact the runner never sets
    assert all(r['order_type'] in ('bracket','simple_with_stop') for r in open_rows)
    # 3) RUNTIME DSN/column identity (promoted from §7 build-time checklist)
    assert oracle_conn_dsn == primed_dsn == sim_5434_dsn  # NOT prod
    assert insert_columns >= INV9_HASHED_COLUMNS
```
A green run that did NOT exercise the real path (a missed patch → early-return / hollow fallback) FAILS the provenance guard. This closes the "green-but-hollow STABLE" hazard. The guard runs inside `ScenarioRunner.run` before the oracle.

### 4.7 Per-fault matrix with first-principles invariant binding (entrypoints/fault_matrix.py)
Each fault is bound to the SPECIFIC invariant it SHOULD violate, derived from first principles — NOT a `verdict == EXPECTED[family]` bucket lookup:
```
FAULT_INVARIANT_BINDING = {
  # family -> (fault_ctor, invariant_id, rationale)
  'broker':  (StickyPositionFault, INV_DB_EQ_BROKER,
              'broker never reports flat -> DB closes while broker holds -> DB!=broker'),
  'data':    (BPRejectionFault,    INV2_ZERO_ORPHANS,
              'forces _record_bp_rejection -> writes recommendation_id=NULL orphan'),
  'market':  (PhantomCloseFault,   INV3_ZERO_SYNTHETIC_CLOSES,
              'synthesizes a close with no broker fill -> phantom/synthetic close row'),
  'network': (DroppedReconcileFault, INV2_ZERO_ORPHANS,
              'reconcile read fails -> stale position breeds orphan'),
  'clock':   (ClockSkewFault,      INV9_DETERMINISM_or_DB_EQ_BROKER, '<rationale>'),
  'process': (ReconcileLoopFault,  INV_DB_EQ_BROKER, '<rationale>'),
}
def run_fault_matrix(conn_factory):
    for family,(ctor,inv,why) in FAULT_INVARIANT_BINDING.items():
        conn=conn_factory(); runner=ScenarioRunner(conn=conn, faults=[ctor()])
        result=runner.run()
        # assert the SPECIFIC invariant failed, with first-principles rationale
        assert result.invariant_failed(inv), f'{family}: expected {inv} to fail ({why})'
        assert classify(result) in (DEGRADED, UNSTABLE)
```
The exact family→fault→invariant bindings are finalized at build against the 6 concrete fault classes (`faults/broker_faults.py`, `clock_faults.py`, `data_faults.py`, `market_faults.py`, `network_faults.py`, `process_faults.py`). Each fault gets a fresh `ScenarioRunner`; teardown disarms via FaultRegistry reverse-order. The clean (no-fault) organic run remains the primary STABLE certifier in `full_gate.run_full_gate`.

## 5. Error Handling

- **BP fail-closed → zero trades** (the #1 organic happy-path trap): mitigated by `get_account()` returning seeded $1M BP, so `_check_paper_buying_power` (executor.py:241) and `_check_paper_buying_power_allocation` (298) never fail on the happy/exit path; the `_record_bp_rejection*` paths never fire there. The governor-reject scenario DELIBERATELY seeds BP below the allocation to drive the reject organically.
- **SPY abort**: FakeMarketData.fetch_spy_benchmark returns a non-empty frame → universe_scanner.py:97 does not abort.
- **LLM unavailable**: `is_llm_available -> True` + config `llm.enabled=True` + `WatchLoop.config`/`ctx.config` primed so `enhance_packet_with_llm` (packet_writer.py:1158-1159) proceeds; `use_grammar_enforcement=False` so the canned XML parses.
- **Clean close not synthesized as 'reconciled'**: the fake fills the OCO leg and `check_and_manage_open_trades` writes the legitimate `exit_reason`; reconcile then sees broker-flat-and-DB-closed and NO-OPs — so no `order_type='reconciled'` / synthetic-close row on the clean path. The reconcile-when-gone and fault scenarios DELIBERATELY drive the synthesizing branches and assert the SPECIFIC invariant.
- **Green-but-hollow STABLE** (missed monkeypatch → real path skipped): caught by the §4.6 provenance guard (seam call-counts + executor-only artifact + runtime DSN/column identity). A run that didn't exercise the real executor cannot pass.
- **Monkeypatch leakage**: every patch stashed/restored in `_teardown` even on exception (try/finally), plus `_config_cache` reset and `reset_brokers()`.
- **Non-determinism**: see §3.4 escalation policy — fix-under-frozen-clock OR operator-waived minimal prod fix OR exclude-from-authoritative; never weaken inv9.
- **Subprocess-spawning overnight handlers** (VRAM/training): CANNOT be frozen (freezegun is in-process). They stay DEFERRED — fired via `_dispatch_sync('on_tick')` but not asserted, documented as a blind spot. DBLogHandler log-thread timestamps are NOT asserted.

## 6. Testing Strategy

Test infra exists under `tests/simulation/lifecycle/` (pytest; PG full-gate fixtures from `docker-compose.test.yml`, user/pass test/test, db halcyon, 5434). New/updated tests:

1. **Organic full-lifecycle smoke** (`test_scenario_organic.py`): drive open→monitor→exit→reconcile; assert the CLEAN-CLOSE bar (§3.1): 1 clean recommendation + 1 clean shadow_trade, terminal status, `exit_reason` in the legitimate set, DB-closed==broker-flat, `held_for_orders` cleared, zero reconciled/synthetic/orphan rows; assert all 9 invariants PASS on the ORGANIC rows.
2. **Organic reconcile-when-gone** (`test_scenario_organic.py`): drive a broker-flat-no-clean-close position; assert reconcile resolves it with ZERO orphans (§3.2, inv2).
3. **Organic governor-reject** (`test_scenario_governor_reject.py`): seed a tripping condition; assert rejected-rec + zero shadow_trade + zero NULL-rec orphan (§3.3); assert `src/risk/governor.py` reject branch executed organically (not mocked).
4. **Provenance guard** (`test_provenance.py`): assert each patched seam invoked ≥1, the executor-only `order_type` artifact present, runtime DSN/column identity; assert a deliberately-missed patch FAILS the guard (negative test).
5. **freeze_at regression-lock** (`test_clock.py`): with no shim, assert both scan-namespace `datetime.now(ET)` reads == `clock.now()` inside the context and restored after.
6. **Seam unit tests**: `get_account()` returns the seeded surface (correct attr names + counter increments); `fetch_ohlcv`/`fetch_spy_benchmark` non-empty Close>0; `fill_on_submit` books + invokes `fill_listener` once; `fill_leg` flattens the position.
7. **Full inv9 determinism** (`test_scenario_organic.py`): two organic open→exit runs, same seed, identical inv9 hash across EVERY hashed column (recommendation_id, actual_shares, pnl_dollars, status, order_type, exit_reason, ticker); fail loudly + record the §3.4 escalation if any column diverges.
8. **Per-fault matrix** (`test_fault_matrix.py`): each of the 6 fault families → fresh organic runner → assert the SPECIFIC bound invariant failed with its first-principles rationale + an aggregate DEGRADED/UNSTABLE; clean run stays STABLE; no residual patch/fault after.
9. **Verdict/blind-spots** (`test_verdict.py`): assert the rewritten prose states STABLE certifies the ORGANIC open→monitor→exit→reconcile + governor-reject + fault matrix, and enumerates residual blind-spots (real fills/latency, concurrency, synthetic accounting-side ledger, overnight subprocess, real broker, regimes, DB wall-clock).
10. **No-leakage regression**: after a full organic run, `_config_cache is None`, brokers reset, the 4 patched source symbols are the originals.

CI: the organic smoke runs in `lifecycle-smoke.yml` (SQLite, non-authoritative — SQLite cannot enforce FK/NOT NULL, so integrity stays labeled non-authoritative there). The authoritative organic verdict + fault matrix run nightly in `lifecycle-full-gate` (PG, `pg-tests.yml`). Test count must not drop (CLAUDE.md floor 5300).

## 7. Build-time Verification Spikes (for the implementer)

- Confirm `rank_universe`/`get_top_candidates` yields ≥1 candidate from the fake features (tune FakeLLM/FakeMarketData values if filtered); confirm the ranker tie-break is stable OR the fakes have no ties (inv9 ranker-ordering).
- Confirm the organic `open_shadow_trade` INSERT column set covers every inv9-hashed column (promoted to a RUNTIME provenance assertion, §4.6).
- Confirm the 5434 bootstrap conn the oracle reads == the DB the executor writes (primed config DSN points at 5434, NOT prod) — promoted to a RUNTIME assertion (§4.6).
- Confirm `recommendation_id`, `actual_shares`, `pnl_dollars` reproducibility across two seeded+frozen runs; record the §3.4 escalation finding.
- **Confirm `reconcile_all_paper_trades` reads positions via the SAME fake `_get_trading_client` seam the executor booked the entry through** (consistency spike) — so the monitor/exit and reconcile both observe the same fake broker state.

## 8. CapitalLedger blind-spot disclosure (DA minor, folded)

CapitalLedger invariants 5/6 are fed via the sim's `fill_listener`: ORGANIC on the trade side (the fake's real fill emits to the listener), but SYNTHETIC on the accounting side (the runner routes the fill into `ledger.apply_fill` rather than the prod accounting reading the broker independently). The verdict blind-spots MUST state this honestly: the ledger invariants verify the sim's accounting reconciles with the organic fills, NOT that prod's independent accounting path is exercised end-to-end.

## 9. #94 Interaction (flagged)

Dual-GPU (#94, in_progress) merges first and renames the overnight/handoff handlers — which #97 does NOT drive (DEFERRED). The scan/exit/reconcile path #97 drives is independent. The ONLY overlap surface is `scenario.py`. Mitigation: **diff #94's actual `scenario.py` + scan-path changes BEFORE integrating** (#94 may have touched the scan path, not only overnight symbols); rebase #97's `scenario.py` rewrite onto #94's merge; and **`git diff --cached | grep '<<<<<<<'` BEFORE `git rebase --continue`** (per the operator's stranded-marker discipline). Flagged in plan notes.

## Design Decisions

| Decision | Rationale |
|---|---|
| Drive WatchLoop._run_scan() directly under freeze_at, bypassing _should_scan. | The trade lifecycle is INLINE in _run_sync_body gated by _should_scan->_safe_run('scan',_run_scan), NOT a registered on_tick handler. Calling _run_scan() directly is the only way to drive scan->features->packet->LLM->governor->executor->reconcile organically. |
| Drive a MULTI-TICK open->monitor->exit->reconcile sequence, not a 1-day open-only run. | The motivating bugs (orphans, phantom closes, close-didn't-clear, the reconcile cycle) live in the EXIT/MONITOR/RECONCILE machinery (check_and_manage_open_trades executor.py:1614, reconcile_dispatch.py:27, exit-reason set executor.py:1876-1941). An open-only run engineered to make reconcile NO-OP never touches that machinery. The gate must exercise the bug machinery to authorize the destructive #95 wipe. |
| Add an organic governor-REJECT scenario that seeds a tripping condition. | $1M BP + clean market means the organic scan ALWAYS approves; the governor's reject branches (position-size/max-positions/sector/daily-loss) never run organically. The risk governor is sacred (CLAUDE.md). Seeding a specific tripping condition and asserting rejected-rec + zero-trade + zero-NULL-rec-orphan DRIVES the real reject path, rather than only marking coverage. |
| Add a RUNTIME provenance guard (seam call-counters + executor-only artifact + runtime DSN/column identity). | The rewrite monkeypatches fragile prod seams (function-local imports, module rebinds, the global config cache, _get_trading_client). A future prod refactor could make a patch miss -> _run_scan early-returns/hollow-fallbacks -> oracle runs on zero/hollow rows -> green-but-hollow STABLE. The guard PROVES the real executor wrote the rows (order_type bracket/simple_with_stop is executor-only). §7's DSN/column checks are promoted from build-time to runtime. |
| Bind each fault to the SPECIFIC invariant it should violate (first principles), not verdict==EXPECTED[family]. | A hand-coded family->verdict-bucket dict asserts the code does what it does (tautology). Binding (e.g.) BP-rejection->inv2 zero_orphans, phantom-close->inv3 zero_synthetic_closes, sticky-position->DB==broker, with a documented rationale per family, tests that the fault breaks the RIGHT invariant — a real adversarial check. |
| Expand determinism to EVERY inv9-hashed column + pin ranker tie-break + define a no-weaken escalation. | inv9 hashes recommendation_id, actual_shares (BP*pct/price float math), pnl_dollars, status, order_type, exit_reason, ticker — checking only recommendation_id leaves the float-math + ranker-tie columns unverified. If nondeterminism is in PROD, the resolution is operator-waived minimal prod fix OR exclude-from-authoritative — never weaken inv9 (the operator's standard). |
| Re-scope the clock task to a freeze_at REGRESSION-LOCK; do NOT build a FrozenDatetime shim. | freezegun's freeze_time rebinds module-level `from datetime import datetime` in BOTH src.scheduler.watch (watch.py:33) and src.scheduler.universe_scanner (universe_scanner.py:19), so the EXISTING freeze_at already freezes watch.datetime.now(ET) (737) and universe_scanner.datetime.now(ET) (87/286/364). A shim is redundant. The regression-lock asserts (with any shim disabled) freezegun alone covers both namespaces. (192/199 is the _record_bp_rejection_pre_llm orphan path, not a clock read.) |
| Prime BOTH the global load_config() cache AND WatchLoop.config/ctx.config. | open_shadow_trade reads the GLOBAL load_config() (executor.py:567), but enhance_packet_with_llm reads its PASSED-IN config (ctx.config == WatchLoop.config) at packet_writer.py:1158-1159 — NOT a global load_config(). Priming only one leaves a gate unconfigured. Both must point at the 5434 sim DSN (never prod). |
| Add FakeTradingClient.get_account() returning a seeded account; parameterize BP for the reject scenario. | Without get_account the executor's get_account_info (alpaca_adapter.py:212) raises -> the BP check fail-closes -> ZERO organic trades and the _record_bp_rejection orphan path fires. $1M for happy/exit; a below-allocation value for the governor-reject drive. |
| Add fill_on_submit + fill_listener and use the existing fill_leg for OCO exits; route fills to CapitalLedger via the listener. | Organically the executor calls place_bracket_order->submit_order; the fake must auto-fill+book on submit and emit to a listener bound to ledger.apply_fill (invariants 5/6). For the exit drive, fill_leg (already present, trading_client.py:188) fills an OCO leg so check_and_manage_open_trades detects the exit. Default fill_on_submit OFF preserves existing synthetic tests. The ledger feed is ORGANIC on the trade side / SYNTHETIC on the accounting side — disclosed in blind-spots. |
| Replace the synthetic raw-INSERT path entirely; the organic drive emits all rows. | The point of #97 is the oracle asserting on what the REAL code wrote across the full lifecycle. Keeping synthetic hand-written rows would mask organic defects in the exit/reconcile machinery. |
| Build-time spike confirming reconcile reads positions via the SAME fake seam the executor booked through. | reconcile_dispatch.py:27 delegates per-desk and resolves the broker via _get_trading_client; the monitor/exit and reconcile must observe the same fake broker state for the clean-close NO-OP and the gone/sticky drives to be coherent. Verifying this consistency de-risks the keystone rewrite. |
| Subprocess overnight handlers stay DEFERRED; do not assert log-thread timestamps. | freezegun is in-process and cannot reach subprocess children (VRAM/training handoff). The organic scan/exit/reconcile runs in-process and is fully frozen. The DBLogHandler log-thread datetime.now is outside the frozen instant. |
| Keep classify()'s zero-tolerance rule unchanged; only rewrite blind-spots prose. | classify() (verdict.py:62) already enforces the operator's bar (UNSTABLE on any integrity fail / error_swallowed). #97 changes WHAT STABLE certifies (organic full-lifecycle + governor-reject + fault matrix), a documentation concern, not a classification-rule change. Do not soften the rule. |
| #94: diff actual scenario.py/scan-path changes before integrating + grep '<<<<<<<' before rebase --continue. | #94 may have touched the scan path, not only overnight symbols; assuming a mechanical rebase risks a silent revert. The operator has had 2 stranded-conflict-marker incidents in 24h — verify the staged diff is marker-free before continuing the rebase. |

## Design Decisions

| Decision | Rationale |
|---|---|
| Extend the organic scenario from a 1-day open-only run to a MULTI-TICK open->monitor->exit->reconcile drive (new exit/reconcile drive folded into the ScenarioRunner rewrite, Task 9). | The CRITICAL finding: the prior design engineered the fake to HOLD the position so reconcile NO-OPs, asserting status='open'/exit_reason IS NULL — which never touches the EXIT/MONITOR/RECONCILE machinery where the motivating bugs (orphans, phantom closes, close-didn't-clear, the reconcile cycle) live. The gate authorizes the destructive #95 wipe, so it must exercise that machinery: advance the virtual clock, fill an OCO leg via the fake's existing fill_leg, drive check_and_manage_open_trades (executor.py:1614) + reconcile_all_paper_trades (reconcile_dispatch.py:27), and assert a CLEAN close (legitimate exit_reason set executor.py:1876-1941, DB-closed==broker-flat, held_for_orders cleared, zero phantom/synthetic/orphan rows) plus a reconcile-when-gone drive asserting zero orphans. |
| Add an organic governor-REJECT scenario (Task 11) that seeds a specific tripping condition and asserts the rejected-rec + zero-trade + zero-NULL-orphan outcome. | MAJOR finding: $1M BP + a clean fake market means the organic scan ALWAYS approves, so the governor's position-size/max-positions/sector/daily-loss REJECT branches never run organically — yet 'risk governor is sacred' (CLAUDE.md). Seeding a below-allocation account (or an over-cap candidate / full book) drives the REAL reject path organically and asserts it writes a rejected recommendation, no shadow_trade, and crucially NO recommendation_id=NULL orphan — never bypassing or weakening the governor. |
| Add a RUNTIME provenance guard (Task 8): seam call-counters, an executor-only order_type artifact, and runtime DSN/column identity, run inside ScenarioRunner before the oracle. | MAJOR finding: the rewrite monkeypatches fragile prod seams (universe_scanner function-local imports, packet_writer module-rebind, the global config cache, _get_trading_client). A future prod refactor could silently make a patch miss, so _run_scan early-returns / a fallback emits hollow rows -> green-but-hollow STABLE. The guard asserts each fake seam was invoked >=1, every open row carries order_type in {bracket,simple_with_stop} (an executor-only artifact the runner never sets), and the oracle conn DSN == primed DSN == 5434 (never prod) with the inv9 columns present. A green run must PROVE the real executor wrote the rows. |
| Bind each fault to the SPECIFIC invariant it should violate (first principles, Task 12), replacing the verdict==EXPECTED[family] bucket lookup. | MAJOR finding: asserting verdict==EXPECTED[family] against a hand-coded family->{DEGRADED|UNSTABLE} dict is tautological (asserts the code does what it does). Binding (e.g.) data/BP-rejection -> inv2 zero_orphans (writes recommendation_id=NULL), market/phantom-close -> inv3 zero_synthetic_closes, broker/sticky-position -> DB==broker, each with a documented first-principles rationale, asserts the fault breaks the RIGHT invariant — a genuine adversarial check. |
| Expand determinism verification (Tasks 7/10) to EVERY inv9-hashed column (recommendation_id, actual_shares, pnl_dollars, status, order_type, exit_reason, ticker), pin the ranker tie-break, and define a no-weaken escalation policy. | MAJOR finding: the prior T7 spiked only recommendation_id, leaving actual_shares (BP*pct/price float math), pnl_dollars, and ranker tie-ordering unchecked, and the fallback (fix prod's id-mint) would violate the no-prod-edit constraint. The revision verifies all hashed columns, pins the ranker tie-break to a stable key (or ensures the fakes have no ties), and specifies the §3.4 escalation when a nondeterminism source is in PROD: operator-approved minimal prod fix WITH an explicit constraint-waiver, OR exclude that run from authoritative status — NEVER weaken inv9. |
| Re-scope the clock task (Task 4) from building a FrozenDatetime 2-namespace shim to a freeze_at REGRESSION-LOCK test, and correct the rationale. | Feasibility MAJOR: freezegun's freeze_time already rebinds module-level `from datetime import datetime` in BOTH src.scheduler.watch (watch.py:33) and src.scheduler.universe_scanner (universe_scanner.py:19), so the EXISTING freeze_at already freezes their datetime.now(ET) reads (watch.py:737; universe_scanner.py:87/286/364 — NOT 195, which is the _record_bp_rejection_pre_llm orphan path). A shim is redundant. Task 4 becomes a regression-lock asserting (with any shim disabled) that freezegun alone covers both namespaces; the prior 'the #1 correctness item' framing is removed. |
| Prime BOTH the global load_config() cache AND WatchLoop.config/ctx.config in wiring.py (Task 5); correct the LLM-config attribution. | Feasibility MINOR: open_shadow_trade reads the GLOBAL load_config() (executor.py:567), but enhance_packet_with_llm reads its PASSED-IN config (ctx.config == WatchLoop.config) at packet_writer.py:1158-1159 — NOT a global load_config(). Priming only the global cache would leave the LLM-enabled gate unconfigured; priming only WatchLoop.config would leave the executor's BP/shadow gates unconfigured. Both must be set, both pointing at the 5434 sim DSN (never prod). |
| Add a build-spike confirming reconcile reads positions via the same fake _get_trading_client seam the executor booked through, and document the synthetic-accounting-side CapitalLedger feed as a residual blind-spot. | DA minors: reconcile_dispatch.py:27 delegates per-desk and resolves the broker via _get_trading_client; for the clean-close NO-OP and the gone/sticky drives to be coherent, monitor/exit and reconcile must observe the SAME fake broker state — verified by a spike (Task 6). Separately, the CapitalLedger invariants 5/6 are fed via the sim's fill_listener: organic on the trade side, synthetic on the accounting side — the verdict (Task 13) must disclose this honestly rather than imply prod's independent accounting is exercised end-to-end. |
