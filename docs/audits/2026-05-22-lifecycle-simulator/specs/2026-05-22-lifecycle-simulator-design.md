# Full-Lifecycle Trading-Platform Simulator + Stress-Test — Design Spec (rev 2)

## 0. Revision note
This is revision 2, addressing two adversarial reviews (Feasibility REQUEST_CHANGES + Devil's Advocate). Changes: corrected all paths to `src/<package>/` form; closed the subprocess-isolation hole (CRITICAL-1, new §3.5 + `ARCIS_DISABLE_DOTENV` guard + a real-child proof test); replaced the error-swallow 'sentinel/log' hand-wave with a concrete `SwallowedErrorObserver` mechanism + per-branch evidence table (CRITICAL-2, new §7.1); removed the phantom live-monitor dependency (§9 rewritten); added thread/timer interleaving + clock-source-skew + pidfile-fiction + determinism-canonicalization to the honesty model (§4.4, §7.2, §9). All cited line numbers re-verified against the codebase.

## 1. Overview

### 1.1 Purpose
A faithful + adversarial full-lifecycle simulator for halcyon-lab (v0.36.49). It runs the REAL platform lifecycle code (data ingestion -> scan -> LLM packet -> scoring/council -> risk governor -> Alpaca bracket execution -> monitor/exits -> reconciliation -> attribution -> corpus -> fine-tune/eval/promote -> audit/notify) against FAKED external boundaries, compresses time via a virtual clock, injects faults, and emits a single **STABLE / DEGRADED / UNSTABLE** verdict.

Two roles: (1) **Pre-wipe gate** before the clean-slate restart; (2) **permanent regression guard** against the data-integrity bugs that motivated it (phantom closes, the orphan/reconcile cycle, close-didn't-clear, training-pidfile mismatch, drawdown miscalc).

### 1.2 Existential safety constraint
Motivated by the **2026-05-22 production-PG WIPE** caused by a test routing to production via a lazily-loaded `.env`. The FIRST property of this package is that **it can never touch production — including from any child process it spawns** (see §3.5). The DB-isolation bootstrap + a connect-time refuse-if-prod guard + a subprocess-env-sanitization guarantee are built and proven FIRST; nothing else is safe to build until prod cannot be reached from the parent OR any child.

### 1.3 Package location
New greenfield package: `src/simulation/lifecycle/`. The existing `src/simulation/engine.py` / `src/simulation/monte_carlo.py` / `src/simulation/cache.py` are an UNRELATED Monte-Carlo backtester and are not modified (we reuse only the OHLCV row shape from `src/simulation/cache.py`).

### 1.4 The prod-code changes (exactly two, both narrow + scope-fenced)
1. **Clock seam** in `WatchLoop` at `src/scheduler/watch.py:1577`: introduce `self._clock()` defaulting to `lambda: datetime.now(ET)` (zero behavior change) and make the loop's `time.sleep(60)` at `src/scheduler/watch.py:2094` injectable.
2. **Dotenv guard** in `src/config/__init__.py`: wrap the `load_dotenv(...)` call at L62 in `if os.environ.get('ARCIS_DISABLE_DOTENV') != '1':` (zero behavior change in prod where the flag is unset). This is what makes the subprocess-isolation guarantee (§3.5) hold for any child that imports `src.*`.

The governor and executor hot paths are NOT modified — freezegun handles their inline `datetime.now()` reads.

### 1.5 Structure guards
All new files respect the platform's 400-line-file / 60-line-function guards. Large components (FakeTradingClient, Oracle, Scenario runner, faults) are split across cohesive submodules.

---

## 2. Architecture

### 2.1 Component map (src/simulation/lifecycle/)
```
src/simulation/lifecycle/
  __init__.py                 # exports run_smoke(), run_full_gate(); imports bootstrap FIRST; NO heavy imports
  bootstrap.py                # *** FIRST import *** env-scrub + 5434 PG + scrub ARCIS_DB_PATH/prod URLs + ALPACA_PAPER_TRADE=true + ARCIS_DISABLE_DOTENV=1 + build scrubbed_env() for children
  prod_guard.py               # connect-time refuse-if-prod guard (guards BOTH psycopg2.connect AND connect_db L621 DSN boundary)
  clock.py                    # VirtualClock (tz-aware ET), advance(), freezegun sync helper, clock-source pinning
  fakes/
    __init__.py
    trading_client.py         # stateful FakeTradingClient at the alpaca SDK boundary
    market_data.py            # FakeMarketData — deterministic OHLCV (reuse src/simulation/cache.py shape)
    llm.py                    # FakeLLM — canned/seeded packets
    trainer.py                # faked trainer subprocess + fake GGUF + REAL controllable pidfile
  faults/
    __init__.py               # FaultRegistry + composable injector base
    broker_faults.py          # partial fills, qty=0 exit, OCO race, dup fills, transient-empty, sticky, phantom/close-didn't-clear
    network_faults.py         # API 500s / timeouts / mid-submit network errors
    process_faults.py         # IN-PROCESS WatchLoop reconstruct + training restart mid-cycle + PID recycling (no real fork)
    market_faults.py          # gaps/halts, regime shifts, high candidate volume
    clock_faults.py           # timezone/DST edges
    data_faults.py            # schema drift, corpus starvation / holdout-empty
  oracle/
    __init__.py               # Oracle.assert_all() -> list[InvariantResult]
    invariants.py             # the 9 invariant checks (precise, ORDER-BY'd SQL/state)
    capital.py                # authoritative capital ledger
    error_observer.py         # SwallowedErrorObserver: test-only logging handler that records fail-conservative branch hits
  scenario.py                 # ScenarioRunner — drives N sim-days, fires handlers per virtual tick
  coverage.py                 # coverage matrix (lifecycle-stage x fault-dimension), cross-ref capability registry
  verdict.py                  # VerdictReporter (STABLE/DEGRADED/UNSTABLE) + blind-spots/trust-calibration section
  entrypoints/
    smoke.py                  # fast CI smoke (no Docker/GPU, core invariants, few sim-days)
    full_gate.py              # full nightly/on-demand authoritative gate (ephemeral 5434 PG, all faults)
```

### 2.2 Data / control flow
```
 bootstrap.py (FIRST import): scrub env, set 5434 URL + cutover + paper + ARCIS_DISABLE_DOTENV=1, build scrubbed_env()
      |
 prod_guard.install_prod_guard(): patch psycopg2.connect AND connect_db DSN boundary -> refuse-if-prod
      |
 entrypoint (smoke|full_gate) provisions DB (5434 PG via docker-compose.test.yml, or SQLite for smoke)
      |
 ScenarioRunner builds WatchLoop with injected _clock=VirtualClock.now and _sleep=noop
      |  installs fakes: sys.modules alpaca -> FakeTradingClient ; FakeMarketData ; FakeLLM ; trainer stub (REAL pidfile)
      |  attaches SwallowedErrorObserver to governor/reconcile/validator loggers
      |  registers selected FaultInjectors via FaultRegistry
      v
 for each virtual tick (clock.advance): freezegun.freeze_time(clock.now) wraps WatchLoop._dispatch_sync('on_tick', now)
      |  REAL lifecycle handlers execute; faults perturb the FAKE boundaries (never prod code)
      |  any child process spawned receives env=scrubbed_env (never the prod .env value)
      v
 at each checkpoint + run end: Oracle.assert_all() against real PG state + FakeTradingClient state + capital ledger + observer
      v
 VerdictReporter aggregates -> STABLE | DEGRADED | UNSTABLE + coverage matrix + blind-spots section
```

### 2.3 Why the SDK-client seam (not the BrokerAdapter ABC)
The deep report found a **dual contract**: the paper path `open_shadow_trade` (`src/shadow_trading/executor.py:557`) bypasses the broker factory; `alpaca_adapter_paper.place_bracket_order` returns a raw dict (`src/shadow_trading/alpaca_adapter_paper.py:152-162`) normalized by `_serialize_order` (`src/shadow_trading/alpaca_adapter.py:66`). Faking at the `BrokerAdapter` ABC (`src/trading/broker_interface.py:73`) would NOT exercise the paper path — the path that produces orphans. Therefore the fake is installed at the alpaca SDK trading-client object returned by `_get_trading_client` (`submit_order/get_order_by_id/get_all_positions/get_open_position/cancel_order_by_id/get_orders`), extending `conftest._mock_alpaca_sdk` (tests/conftest.py:292). Both the paper path AND `AlpacaLiveBroker` normalization flow through real code. The interlock at `_get_alpaca_config` (`src/shadow_trading/alpaca_adapter.py:112`, paper guard L122-126) requires `ALPACA_PAPER_TRADE=true` (set by bootstrap).

---

## 3. DB Isolation & Refuse-If-Prod (TASK 1 — built first)

### 3.1 The wipe vector
- `src/config/__init__.py:62` calls `load_dotenv(dotenv_path=_ENV_PATH, override=False)` at import; L77 reads `DATABASE_URL` at import.
- `override=False` means **a pre-set environment variable WINS** over `.env`.
- `connect_db` (`src/utils/db.py:558`) reads env at CALL time: L621 `DATABASE_URL`, L622 `ARCIS_PG_CUTOVER_ENABLED=='1'`, L623 `startswith('postgres')`, connect at L631.
- The 2026-05-22 wipe: a `.env` was lazily loaded after `pytest_configure`, and the timing hole let a prod URL through (tracked task #96).
- (Disambiguation: the prod config module is `src/config/__init__.py`; a separate, unrelated `tests/config/__init__.py` exists and is NOT touched.)

### 3.2 Defense layer 1 — bootstrap.py (the lever)
`bootstrap.py` MUST be imported before ANY `src.*` import (enforced by `__init__.py` import order and by entrypoints importing it on line 1). It:
1. Pops/scrubs `ARCIS_DB_PATH` and any prod-signature `DATABASE_URL`/`TEST_DATABASE_URL` from `os.environ`.
2. Sets `DATABASE_URL = postgresql://test:test@127.0.0.1:5434/halcyon` (full gate) or marks SQLite-temp mode (smoke).
3. Sets `ARCIS_PG_CUTOVER_ENABLED=1`, `ALPACA_PAPER_TRADE=true`, `ARCIS_DISABLE_DOTENV=1`, `PYTHONHASHSEED=0`.
4. Because `load_dotenv(override=False)` will NOT override a pre-set var, these win unconditionally.
5. Provides `assert_safe_db_env()` raising `SimProdGuardError` if any prod signature is present after scrub.
6. Provides `scrubbed_env() -> dict` — the sanitized env mapping that MUST be passed as `env=` to any child process (§3.5).

### 3.3 Defense layer 2 — prod_guard.py (connect-time, unbypassable)
Guards at TWO chokepoints (verified: `src/utils/db.py:41` does `import psycopg2` un-aliased, resolves the DSN at L621, connects at L631):
- Monkeypatch `psycopg2.connect` to raise `SimProdGuardError` if the DSN matches a prod signature.
- ALSO guard at the `connect_db` DSN-resolution boundary (validate the resolved `database_url` before L631) so an aliased `from psycopg2 import connect`, a connection pool, or any other psycopg2 entry cannot slip past. Reuses `_is_prod_pg_url` signatures from tests/conftest.py:51 (`localhost:5433`, `127.0.0.1:5433`, `halcyon_app:`).
- **No escape hatch** in sim mode (unlike conftest's `ARCIS_ALLOW_PROD_PG_IN_TESTS`). Deliberately NOT relying on `pytest_configure` (the #96 timing hole).
- Does NOT use `force_sqlite` for the full gate (goal = exercise the real `PostgresConnectionWrapper`).

### 3.4 Mandatory in-process proof test (Task 2)
`tests/simulation/lifecycle/test_prod_guard.py` MUST prove `install_prod_guard()` rejects both a `5433` URL and a `halcyon_app:` URL with `SimProdGuardError` (at the `psycopg2.connect` patch AND via an aliased `from psycopg2 import connect` call), AND that `assert_safe_db_env()` raises on a prod-signature env.

### 3.5 Subprocess isolation — closing the wipe-vector-reborn (CRITICAL-1, Task 2b)
The parent-process defenses (env-scrub + monkeypatched `psycopg2.connect`) live only in PARENT memory. A naively spawned child re-runs `src/config/__init__.py` `load_dotenv(override=False)` against the operator's REAL `.env` FILE and could resolve a prod `5433` DSN. Three-part guarantee:

**(a) Sanitized child env.** Every child the harness or faults spawn MUST be launched with `env=bootstrap.scrubbed_env()` (the 5434 URL + `ARCIS_DISABLE_DOTENV=1`, never inheriting the operator's prod `.env` value). The harness owns all `subprocess.run`/`Popen` kwargs; faults never call subprocess directly.

**(b) Dotenv guard in prod (narrow, scope-fenced).** Wrap `src/config/__init__.py:62` `load_dotenv(...)` in `if os.environ.get('ARCIS_DISABLE_DOTENV') != '1':`. In prod the flag is unset -> behavior unchanged. In any sim child, bootstrap set the flag -> the child will NOT load `.env` at all, so even a misconfigured spawn cannot resolve a prod DSN from the file. This is the ONLY edit to config; it is its own scope-fenced change in Task 1.

**(c) No real forks for restart faults.** Process-restart and PID-recycle faults reconstruct `WatchLoop` IN-PROCESS (tear down + rebuild the object) — there is no real `fork`/`exec` of the watch loop. The only real child is the trainer subprocess, which is STUBBED (§5.4) and, where it must spawn, uses `scrubbed_env()`.

**(d) Real-child proof test (Task 2b).** `tests/simulation/lifecycle/test_subprocess_isolation.py` writes a prod-signature `.env` (containing `DATABASE_URL=postgresql://halcyon_app:x@127.0.0.1:5433/halcyon_app`) to a temp repo-root-shaped path, then spawns a REAL `python -c "import src.config; import src.utils.db as db; db.connect_db()"` child with `env=scrubbed_env()`, and asserts the child does NOT connect to 5433 — it either resolves the 5434 test URL or raises the prod guard. A control case (child WITHOUT the flag / WITHOUT scrubbed env) is documented but NOT run against a live 5433 (it asserts on the resolved DSN string only, never an actual prod connect). This test is part of the FIRST safety gate alongside Task 2.

---

## 4. Virtual Clock & Hybrid Time (TASK 3-4)

### 4.1 The single brain-clock seam
WatchLoop reads `now = datetime.now(ET)` once at **src/scheduler/watch.py:1577**, governing ALL cadence. Change:
- Add `self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(ET))` in `WatchLoop.__init__`.
- Replace L1577 `now = datetime.now(ET)` with `now = self._clock()`.
- Add `self._sleep = sleep or time.sleep`; replace `time.sleep(60)` at src/scheduler/watch.py:2094 with `self._sleep(60)`. Sim injects a no-op sleep.
- Daily rollover (`_reset_daily_state`) and on_tick dispatch (L1602) then run on virtual time automatically.

### 4.2 freezegun for stage functions
Governor (`src/risk/governor.py`) and executor (`src/shadow_trading/executor.py`) hot paths call `datetime.now()` inline; they are NOT edited. ScenarioRunner wraps each `_dispatch_sync('on_tick', now)` in `freezegun.freeze_time(clock.now())` so those inline reads see the SAME virtual instant (tz-aware ET). This keeps the reconcile recent-close window (`src/shadow_trading/reconcile.py:124-125`, `_RECENT_CLOSE_WINDOW_HOURS=24` at L80) consistent. **Add `freezegun` to requirements.txt.**

### 4.3 VirtualClock contract
```python
class VirtualClock:
    def __init__(self, start: datetime, tz=ET): ...   # start tz-aware ET
    def now(self) -> datetime: ...
    def advance(self, delta: timedelta) -> None: ...
    def tick_to(self, hour, minute) -> None: ...      # jump to next occurrence
```
Compression: ScenarioRunner advances in handler-relevant jumps (premarket/open/intraday/close/overnight), achieving high sim-day throughput. Determinism: fixed seed -> identical advance schedule + identical fake responses (invariant #9, §7.2).

### 4.4 Clock-source consistency (MAJOR — Python-clock-vs-other-clock skew)
freezegun freezes Python `datetime.datetime.now`/`.utcnow` AND `time.time`/`time.monotonic` AND `pandas.Timestamp.now`/`.utcnow` (all within the frozen block), but it does NOT freeze a DB server's `now()`/`CURRENT_TIMESTAMP`. The invariants therefore pin every time source explicitly:

| Time source | Used by (asserted invariant) | How pinned |
|---|---|---|
| `datetime.now(ET)` | WatchLoop cadence; governor; executor | Frozen via `freeze_time(clock.now())` + the `_clock` seam |
| `time.time()` / `time.monotonic()` | any elapsed-delta gate | Frozen by freezegun (tick-aware) |
| `pd.Timestamp.now()` | data-stage timestamps | Frozen by freezegun |
| DB `now()` / `CURRENT_TIMESTAMP` | any row inserted by prod code with a server-side default | **Avoid relying on it for asserts.** The reconcile 24h window compares an APP-supplied timestamp (frozen) against `created_at`; the harness ensures inserts that the oracle reads use APP-supplied (frozen) timestamps, NOT server `now()`. Where a column is genuinely server-defaulted and unavoidable, the oracle EXCLUDES it from time-window asserts and the runner sets the PG session clock is NOT used (PG cannot freeze `now()`); instead those rows are written through code paths that pass an explicit timestamp. |
| heartbeat freshness (invariant #8) | `data/watchdog.txt` + `platform_events` heartbeat | Asserted as MONOTONIC ADVANCE keyed to the frozen `clock.now()` value the loop wrote, NEVER against wall-clock |

Rule: **assert against app-supplied frozen timestamps; never compare a frozen Python time against a live DB wall-clock.** Any invariant that cannot satisfy this is excluded and noted in the blind-spots section.

---

## 5. Fakes (TASK 5-8)

### 5.1 FakeTradingClient (fakes/trading_client.py)
Stateful object matching the alpaca SDK trading-client surface returned by `_get_trading_client`:
- `submit_order(req)` — bracket/OCO order classes; returns SDK-shaped order objects so real `_serialize_order` (`src/shadow_trading/alpaca_adapter.py:66`) consumes them.
- `get_order_by_id`, `get_orders`, `get_all_positions`, `get_open_position`, `cancel_order_by_id`.
- **OCO model**: filling one leg auto-cancels the sibling + closes the position; deterministic fill scheduling driven by VirtualClock.
- Internal position book compared by the Oracle against the DB (invariant #4).
- All fault hooks applied here via the FaultRegistry (Task 10).
- **Concurrency note (blind-spot, §9):** fills are applied synchronously inside the single-threaded `on_tick`; OCO-race/dup-fill faults emit both legs/duplicate events within ONE tick to test DATA-SHAPE resilience, NOT real thread interleaving.

### 5.2 FakeMarketData (fakes/market_data.py)
Deterministic OHLCV reusing the `src/simulation/cache.py` row shape; seeded. Supports gap/halt/regime-shift faults.

### 5.3 FakeLLM (fakes/llm.py)
Canned/seeded packets for scan->packet->council; configurable candidate volume + content (drives governor gates).

### 5.4 Faked trainer subprocess (fakes/trainer.py)
Stubs `subprocess.run` at `src/training/trainer.py:814` (and ollama create/cp at 851/861) and `_find_gguf` at L838 -> fake GGUF path. The REAL logic is exercised: `export_training_data` (L778), empty-corpus guard, the empty-holdout block (L786-794: train>0 & holdout==0 -> return None blocks promotion), canary (L879), `evaluate_on_holdout` (L911), `register_model_version` (L928/967), `promotion_gate` (L982). NO real GPU. CWD-relative `training_data/` writes (L797/844) redirected to a sim temp dir. Any child it must spawn uses `scrubbed_env()` (§3.5a).

**Real controllable pidfile (MAJOR — pidfile fiction):** the stub WRITES and CLEARS a REAL pidfile at the path the prod stale/recycle logic reads, with a CONTROLLABLE PID value. Mapping fault -> real code path -> oracle assert:
- *normal*: stub writes pidfile on start, clears on completion -> #8 asserts no stale pidfile after a clean training cycle.
- *process-restart fault*: stub leaves the pidfile present after an in-process restart -> drives the prod STALE-DETECT path -> #8 asserts the platform detects + clears the stale pidfile (no wedge).
- *PID-recycle fault*: stub writes a pidfile whose PID now belongs to an unrelated live process -> drives the prod RECYCLE-DETECT (liveness+identity) path (task #87 guard) -> #8 asserts the platform does NOT treat the recycled PID as a live trainer.
Thus #8 tests real pidfile logic, not a fiction.

---

## 6. Fault-Injection Framework (TASK 10)

### 6.1 Design
Composable, scenario-driven. Base `FaultInjector` with `arm(harness)` / `disarm()`; `FaultRegistry` activates a set per scenario. Faults patch the FAKE boundaries (and, for process faults, the harness lifecycle IN-PROCESS), never prod code, never real subprocess env.

### 6.2 Fault classes (all required)
| Class | Module | Mechanism |
|---|---|---|
| partial bracket fills | broker_faults | FakeTradingClient fills < requested qty |
| broker qty=0 on exit | broker_faults | exit leg reports filled qty 0 |
| OCO-leg race | broker_faults | both legs report fill in same tick (DATA-SHAPE, not thread race — §9) |
| duplicate fills | broker_faults | same fill event emitted twice in one tick |
| network errors / 500 / timeout mid-submit | network_faults | submit raises APIError/Timeout |
| sticky/lingering paper positions | broker_faults | position persists after close |
| close-didn't-clear | broker_faults | DB close written but broker still holds |
| phantom closes | broker_faults | broker reports flat with no close event |
| process restart mid-cycle (watch+training) | process_faults | IN-PROCESS WatchLoop reconstruct; trainer stub restart (no real fork) |
| PID recycling | process_faults | stub writes pidfile with a recycled live PID (§5.4) |
| clock/timezone/DST edges | clock_faults | VirtualClock start at DST boundary |
| market gaps/halts | market_faults | FakeMarketData emits gap/halt |
| regime shifts | market_faults | shift OHLCV distribution mid-run |
| high candidate volume | market_faults | FakeLLM emits N x candidates |
| transient-empty broker responses | broker_faults | get_all_positions returns [] then recovers |
| schema drift | data_faults | add/rename a column in sim DB pre-run |
| corpus starvation / holdout-empty | data_faults | seed corpus to trigger empty-holdout block |
| drive all 11 governor gates | market_faults + llm | shape candidates to hit each GOVERNOR_GATES entry (governor.py:522) |

---

## 7. The Oracle — 9 Invariants (TASK 9)

ZERO-TOLERANCE: any integrity-invariant violation -> **UNSTABLE**. Each check returns `InvariantResult(name, passed, severity, evidence, degraded_correctly: bool, error_swallowed: bool)`. **All oracle SQL MUST use explicit `ORDER BY` on stable, non-surrogate keys (see §7.2).**

| # | Invariant | Precise check |
|---|---|---|
| 1 | 1:1 attribution | every trade row has non-null `recommendation_id` linkage (join shadow_trades -> recommendations; 0 unlinked) |
| 2 | zero orphans | `count WHERE order_type='reconciled' OR recommendation_id IS NULL == 0` after a clean run (orphan signature `src/shadow_trading/reconcile.py:155-169`) |
| 3 | zero synthetic/reconciled_stale closes | 0 rows `exit_reason='reconciled_stale'` (synthetic close from `_resolve_stuck_pnl`, `src/shadow_trading/reconcile.py:172`) |
| 4 | DB-open == FakeBroker positions EXACTLY | set + qty equality between DB open positions and FakeTradingClient book at every checkpoint |
| 5 | capital conservation / no phantom P&L | sim capital ledger (oracle/capital.py) reconciles realized+unrealized P&L; no unattributed delta |
| 6 | honest metrics | governor drawdown denominator == sim authoritative capital; AND detect whether `compute_current_drawdown` hit its fail-conservative 15% branch (`src/risk/governor.py:392-397`) via the SwallowedErrorObserver (§7.1) -> sets `degraded_correctly` vs `error_swallowed` |
| 7 | corpus integrity | only clean measured trades become examples; empty-holdout blocks promotion (assert trainer returned None at trainer.py:786-794 when holdout==0) |
| 8 | no wedged processes | heartbeat freshness (data/watchdog.txt at watch.py:1573/1581 + platform_events heartbeat L1587) advances each virtual tick keyed to frozen clock; no stale/recycled pidfile (§5.4) |
| 9 | deterministic reproducibility | same seed -> identical canonical projection hash across two runs (§7.2) |

### 7.1 degraded-correctly vs error-swallowed — concrete mechanism (CRITICAL-2)
Fail-conservative defaults can MASK faults. The oracle MUST be able to read the swallow signal directly. Since prod logic is NOT edited, the harness installs `oracle/error_observer.py::SwallowedErrorObserver` — a **test-only `logging.Handler`** attached to the specific prod loggers at scenario setup. It records every fail-conservative branch hit (logger name, message, exc_info) into an in-memory event list the oracle reads. No prod edit.

**Per-error-path evidence table (BLOCKING confirmation at implementation time — Task 9 must verify each string/branch exists before the task is accepted):**
| Branch | Verified distinguishing evidence | 'degraded correctly' | 'error swallowed' |
|---|---|---|---|
| governor drawdown `src/risk/governor.py:392-397` | `logger.error("[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)", e)` then `return 15.0` (VERIFIED this revision) | returns a REAL computed drawdown; observer recorded NO `[RISK] Drawdown computation failed` event | observer recorded the `[RISK] Drawdown computation failed` event -> error_swallowed=True -> UNSTABLE |
| reconcile tz-coercion `src/shadow_trading/reconcile.py:124` | confirm at impl time the exact log/branch when a tz-naive `created_at` is coerced | coercion of a legitimately-naive value with a logged INFO/debug | coercion inside an `except` that swallowed a parse error |
| validator reject-on-import-fail | confirm at impl time the exact reject path + log | reject due to a real validation failure | reject because an import/exception was swallowed |

If, for any branch, NO distinguishing log/sentinel exists in prod, the implementer MUST add the observer hook at the narrowest seam (attach the handler to that module's logger) and record the swallowed exception WITHOUT editing prod control flow. Confirming the exact evidence at each branch is a BLOCKING acceptance criterion of Task 9, not a buried phrase. This discriminator is the gate's whole reason to exist.

### 7.2 Determinism canonicalization (MAJOR — invariant #9)
The reproducibility hash is computed over a CANONICAL, id-normalized projection, NOT raw rows:
- **Mandate `ORDER BY`** on every oracle query, keyed to stable business columns (e.g. `symbol, entry_ts`), never on insertion order.
- **Exclude/normalize surrogate keys:** SERIAL/autoincrement PKs and any FK to them differ across container recreation -> EXCLUDE from the hash, or replace each surrogate id with its rank within a deterministic ORDER BY before hashing.
- **Exclude raw timestamps**, OR snap them to the virtual clock's frozen value (which is deterministic by seed). Server-defaulted timestamps are excluded.
- **Pin `PYTHONHASHSEED=0`** in bootstrap (set before any `src.*` import) so set/dict ordering in prod code is stable.
- **Seed prod nondeterminism sources:** identify prod `uuid4()`/`random`/`secrets` call sites that land in hashed columns (confirm at impl time) and seed/patch them deterministically via the fakes layer (e.g. monotonic counter for client_order_id) so two runs match.
The hash = sha256 of the canonical projection of (ordered event log) + (id-normalized, timestamp-stripped final DB snapshot). Two seeded runs must produce identical hashes.

---

## 8. Scenario Runner, Coverage & Verdict (TASK 11-12)

### 8.1 ScenarioRunner (scenario.py)
Builds WatchLoop with injected `_clock`/`_sleep`, installs fakes + the requested FaultRegistry, attaches the SwallowedErrorObserver, then drives N sim-days by advancing the VirtualClock through daily cadence and firing `on_tick` inside `freeze_at`. Oracle checkpoints at: post-open, post-close, post-reconcile, post-training, run-end. Per-run cleanup: `reset_brokers()` (`src/trading/broker_factory.py:75`) + config cache clear (`src/config/__init__.py:93`) + detach observer + fresh 5434 teardown.

### 8.2 Coverage matrix (coverage.py)
A `lifecycle-stage x fault-dimension` matrix; cross-referenced to the capability registry (`src/platform/capability_registry/registry.py:35-38` import-time dicts ACTIONS/STATES/SYSTEMS/DECISIONS). Reports exercised cells; uncovered integrity-critical cells surface and may downgrade to DEGRADED (coverage gap is a NON-integrity quality signal).

### 8.3 VerdictReporter (verdict.py)
- **UNSTABLE** if ANY integrity invariant (1-9) is violated OR any oracle result is `error_swallowed`.
- **DEGRADED** if all integrity invariants pass but non-integrity quality signals are weak (fill-realism, coverage gaps, DEGRADED-marked checks).
- **STABLE** otherwise.
Report MUST include the mandatory **Blind Spots & Trust Calibration** section (§9).

---

## 9. Blind Spots & Trust Calibration (MANDATORY)

A STABLE verdict is necessary, not sufficient. What this simulator CANNOT catch:
- **Real broker fills/latency/slippage** — FakeTradingClient fills are deterministic + instantaneous; real Alpaca partial-fill timing, queue position, slippage are unmodeled.
- **Regime-specific real-market behavior** — FakeMarketData is seeded synthetic; real volatility clustering, news gaps, microstructure are not reproduced.
- **Real GPU / Ollama placement & training nondeterminism** — trainer subprocess is stubbed; real CUDA OOM, RTX 3090 / NUM_PARALLEL=4 VRAM placement, Ollama model-create failures are out of scope.
- **Real network nondeterminism** — injected network faults are scripted; real flaky DNS/TLS/rate-limit backoff timing are not.
- **Real concurrency / thread+timer interleaving (NEW, MAJOR):** the sim drives everything single-threaded via synchronous `on_tick` under frozen time. This structurally HIDES real thread/timer interleavings — the OCO-leg race, duplicate-fill, and reconcile-vs-close races that are the exact orphan/phantom-close family motivating this project. The OCO-race/dup-fill faults test **data-shape resilience** (can the platform's logic handle two-leg/duplicate fill EVENTS) NOT **thread-safety** (can it handle them arriving concurrently). Calibration: the prod WatchLoop itself is single-threaded synchronous (so loop cadence matches), but prod reconcile / monitor timers and broker callbacks may interleave with the loop in ways the sim does not reproduce. Thread-safety remains UNCOVERED here.
- **Real DB wall-clock interactions (NEW):** invariants assert against app-supplied frozen timestamps; any prod path that depends on server `now()` is excluded from time-window asserts (§4.4) and therefore not validated by this gate.
- **Live-only env drift** — agent-worktree `.env` absence, NSSM service identity, real DST transitions on the wall clock.

### 9.1 The live-fill gap is currently UNCOVERED (NEW — phantom-monitor removed)
There is **no existing live broker-vs-DB consistency monitor** in the codebase (verified). The earlier draft leaned on one as if it shipped — it does not. The simulator proves the platform LOGIC is correct under adversarial DATA conditions; it does NOT prove the logic stays correct against the REAL Alpaca broker in real time. **This gap is presently UNCOVERED.** Tracked follow-up: a production live broker-vs-DB reconciliation monitor (relates to orphan-source tasks #82/#83/#86) would run the same `DB-open == broker-positions` check (invariant #4) against the live account on a cadence. Until that ships, the verdict report states plainly that live-fill correctness is monitored only by the existing reconcile loop, not by a dedicated consistency monitor. **A simulator that gives false confidence is worse than none** — this section is part of every verdict report.

---

## 10. Split Run Model (TASK 13)

| | CI smoke (entrypoints/smoke.py) | Full gate (entrypoints/full_gate.py) |
|---|---|---|
| Infra | NO Docker, NO GPU | ephemeral 5434 PG via docker-compose.test.yml |
| DB | SQLite-temp via bootstrap (still through connect_db) | real PostgresConnectionWrapper on 5434 |
| Sim-days | few (2-3) | many (multi-day) |
| Faults | core integrity invariants, light fault set | all fault classes + all 11 governor gates |
| Authority | wiring + invariant subset, reproducible | AUTHORITATIVE STABLE/DEGRADED/UNSTABLE |
| Trigger | every push (lifecycle-smoke.yml) | nightly + on-demand (pg-tests.yml full-gate job) |

**Integrity authority note (NEW, MINOR):** the smoke runs on SQLite, which the design itself says misses PG-specific bugs (`?->%s` rewrite, RowFactory/CompatRow, PG commit/rollback). Therefore the smoke report MUST label its integrity-invariant results **"wiring-only / non-authoritative (SQLite)"**. Only the full PG gate's integrity results are authoritative. The safety guarantee (bootstrap+guard+subprocess sanitization) is identical in both.

---

## 11. Error Handling Strategy

- `SimProdGuardError` — raised by bootstrap/prod_guard on any prod signature; ABORTS loudly. No escape hatch in sim mode.
- Fake-boundary errors are intentional (faults); the Oracle interprets the platform's RESPONSE, not the fault itself.
- Swallowed exceptions in prod code (fail-conservative defaults) are detected via the SwallowedErrorObserver, not masked (§7.1).
- Subprocess errors: any child launched without `scrubbed_env()` is a harness bug -> the Task 2b proof test guards against it.
- Per-run cleanup: `reset_brokers()` + config cache clear + observer detach + fresh 5434 teardown.
- freezegun/clock desync prevented by always freezing FROM `clock.now()` (tz-aware ET); clock-source rules in §4.4.

---

## 12. Testing Strategy (TASK 14-16)

Harness components unit-tested under `tests/simulation/lifecycle/`:
- `test_prod_guard.py` — **MANDATORY (Task 2)**: guard rejects 5433/halcyon_app URLs (incl. aliased import), `assert_safe_db_env()` raises on prod-signature env.
- `test_subprocess_isolation.py` — **MANDATORY (Task 2b)**: a REAL python child with a prod-signature `.env` on disk + `env=scrubbed_env()` refuses to resolve/connect prod.
- `test_bootstrap.py` — env scrub correctness (ARCIS_DB_PATH removed, 5434 set, ALPACA_PAPER_TRADE=true, ARCIS_DISABLE_DOTENV=1, PYTHONHASHSEED=0, override-wins ordering, scrubbed_env() shape).
- `test_clock.py` — VirtualClock advance/tick_to + freezegun sync (tz-aware ET) + clock-source pinning (datetime/time.time/pd.Timestamp all frozen).
- `test_fake_trading_client.py` — OCO sibling-cancel, partial fill, qty=0, position book.
- `test_trainer_stub.py` — empty-holdout block returns None; REAL controllable pidfile write/clear/stale/recycle.
- `test_oracle.py` — each invariant flags a seeded violation (orphan, reconciled_stale, position mismatch, error-swallowed drawdown via observer, empty-holdout, stale/recycled pidfile) + passes clean.
- `test_error_observer.py` — observer records the exact `[RISK] Drawdown computation failed` event; no event on a clean compute.
- `test_determinism.py` — two seeded runs produce identical canonical hashes (id-normalized, ORDER BY, PYTHONHASHSEED pinned).
- `test_fault_framework.py` — compose two faults, arm/disarm, no leakage; DST fault asserts cadence fires exactly once across the spring-forward/fall-back hour and reconcile window math stays correct.
- `test_verdict.py` — UNSTABLE on any integrity violation or error_swallowed; DEGRADED on coverage gap only.

Reuse existing scaffolding: `pg_docker_url` (tests/conftest.py:589), `pg_wrapper` schema bootstrap (L394/L470), `_mock_alpaca_sdk` (L292), telegram null router (L683), `_is_prod_pg_url` (L54).

## 13. Honest implementation-time confirmations (flagged, non-blocking unless noted)
- **BLOCKING (Task 9):** exact distinguishing log/sentinel at each fail-conservative branch in §7.1.
- bracket_monitor exit-write columns; literal `record_shadow_trade`/`update_shadow_trade` INSERT column list; full registry enumeration; `trainer.export_training_data` corpus SQL; the prod uuid4/random sources that land in hashed columns (§7.2); the exact reconcile tz-coercion branch (§7.1); docker-compose.test.yml (verified: postgres:16-alpine, 5434, test/test/halcyon).

## 14. CI wiring (TASK 17) — verified workflow inventory
Only `.github/workflows/pg-tests.yml` and `.github/workflows/stale-base-check.yml` exist; there is NO general PR/push pytest workflow. Decision:
- **Smoke** -> NEW workflow `.github/workflows/lifecycle-smoke.yml` (push/PR; no Docker/GPU; runs `run_smoke()`; labels integrity results non-authoritative).
- **Full gate** -> EXTEND `.github/workflows/pg-tests.yml` with an additional job that reuses its existing 5434 Docker pattern, gated to nightly + manual `workflow_dispatch` (NOT every PR — cost), running `run_full_gate()` and uploading the verdict artifact.

## Design Decisions

| Decision | Rationale |
|---|---|
| Close the subprocess wipe-vector with a three-part guarantee: sanitized child env (env=scrubbed_env()), a narrow ARCIS_DISABLE_DOTENV guard around src/config/__init__.py:62 load_dotenv, in-process WatchLoop reconstruction for restart faults (no real fork), plus a real-child proof test (Task 21). | The parent-process env-scrub + monkeypatched psycopg2.connect live only in PARENT memory. A child re-runs src/config/__init__.py load_dotenv(override=False) against the operator's REAL .env and could resolve a prod 5433 DSN — the wipe vector reborn (CRITICAL-1). The dotenv guard (zero behavior change in prod where the flag is unset) means any sim child that imports src.* will NOT read .env at all. Passing env=scrubbed_env() to every spawned child ensures the 5434 URL + flag are present and the prod URL is absent. Reconstructing WatchLoop in-process removes the only would-be fork. The Task 21 proof test spawns a REAL python child with a prod-signature .env on disk and asserts refuse-to-connect, making the guarantee testable rather than asserted. |
| Implement the error-swallowed vs degraded-correctly discriminator with a test-only SwallowedErrorObserver logging.Handler attached to the governor/reconcile/validator loggers, backed by a verified per-branch evidence table; making the evidence confirmation a BLOCKING acceptance criterion of the oracle task. | Invariant #6 is the gate's whole reason to exist, and the spec must forbid editing governor.py. The earlier 'via sentinel/log' phrasing was structurally unable to guarantee the oracle could read the signal (CRITICAL-2). A logging.Handler attached to the prod logger reads the swallowed-error event WITHOUT touching prod control flow. The governor branch was verified this revision: src/risk/governor.py:392-397 emits the exact string `[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)` then returns 15.0 — so a recorded event means error-swallowed (UNSTABLE) while a real computed drawdown with no event means degraded-correctly. For branches where no distinguishing log exists, the implementer attaches the handler at the narrowest seam. Making this a blocking confirmation prevents the discriminator from silently degrading to a no-op. |
| Remove the phantom live broker-vs-DB monitor dependency; rewrite Section 9 to state the live-fill gap is currently UNCOVERED with a tracked follow-up, and add real-concurrency/thread-timer interleaving + DB-wall-clock exclusion to the blind-spots. | Grep confirmed no live broker-vs-DB consistency monitor exists in the codebase — the honesty section cannot rest on a non-existent deliverable (MAJOR). The single-threaded frozen-time driver structurally hides the OCO-race/dup-fill/reconcile-vs-close thread interleavings that motivated the project; the faults test data-shape resilience, not thread-safety, and the report must say so. freezegun also cannot freeze DB server now(), so any invariant touching a server-defaulted timestamp is excluded. A trust-calibration section that overstates coverage is exactly the false confidence the operator said is worse than no simulator. |
| Define a canonical id-normalized hashed projection for invariant #9 (exclude SERIAL PKs + raw timestamps, normalize surrogate keys to ORDER-BY rank, mandate ORDER BY on all oracle SQL, pin PYTHONHASHSEED=0 in bootstrap, seed prod uuid/random sources via the fakes layer). | A naive 'hash the rows' check (MAJOR) would spuriously fail across container recreation (SERIAL PKs differ), under unstable SQL ordering (no ORDER BY), under Python set/dict hash randomization (PYTHONHASHSEED), and under prod uuid4()/random. Pinning all of these makes 'same seed -> identical hash' a real determinism guarantee instead of a flaky check that erodes trust in the gate. |
| Guard the prod-connection at BOTH the psycopg2.connect symbol and the connect_db DSN-resolution boundary (src/utils/db.py:621); add an aliased-import test. | Verified src/utils/db.py:41 does `import psycopg2` un-aliased and resolves the DSN at L621 before connecting at L631. Monkeypatching psycopg2.connect alone could be bypassed by an aliased `from psycopg2 import connect`, a pool, or any other entry (MINOR). Validating the resolved DSN at the connect_db boundary closes that gap and the aliased-import test proves it. |
| Trainer stub writes/clears a REAL pidfile with a controllable PID, mapping each process fault to a real prod code path (write/stale-detect/recycle-detect) the oracle asserts. | With the trainer subprocess stubbed there is no real PID, yet invariant #8 asserts on the training pidfile (MAJOR — pidfile fiction). Having the stub write/clear a REAL pidfile with a controllable PID drives the actual prod stale-detect and PID-recycle (liveness+identity, task #87) logic, so #8 tests real code rather than a fiction. |
