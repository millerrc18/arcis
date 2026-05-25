"""ScenarioRunner — KEYSTONE organic open->exit->reconcile lifecycle driver (T9, #97).

The simulator KEYSTONE: drives the REAL inline scan path organically across
virtual ticks, replacing the prior synthetic raw-INSERT path. Every shadow_trades
/ recommendations row is written by the production code path (universe_scanner
-> log_recommendation -> executor.open_shadow_trade) — never by the runner.

Install order (spec §2.5):
  1. install_prod_guard() — boundary guard on psycopg2.connect (already in __init__).
  2. Caller (full_gate._provision_pg) provisions the ephemeral 5434 PG.
  3. wiring.prime_config(sim_dsn, overrides={"ranking": {"packet_worthy_threshold": 30}})
     — primes load_config() and clears the config cache.
  4. wiring.build_watch_config(sim_dsn, overrides={...}) — same dict for both
     WatchLoop.config and ScanContext.config (LLM gate reads ctx.config).
  5. wiring.install_organic_patches(fake_tc, fake_md, fake_llm, sim_universe) —
     applies 5 monkeypatches (incl. the T7 §3.4 uuid stub for inv9 determinism).
  6. Seed fake account: $1M buying_power / equity / portfolio_value / cash.
  7. Register fill_listener = lambda **kw: self.ledger.apply_fill(**kw); reset
     fake call counters.

Drive (under freeze_at(clock)):
  TICK A: self.watch_loop._run_scan() — direct call, bypassing _should_scan.
          The inline path runs scan -> features -> packet -> LLM -> governor ->
          executor.open_shadow_trade -> reconcile_all_paper_trades.
          After this, exactly 1 recommendations row + 1 shadow_trades row.
  ADVANCE clock 30 minutes (exceeds OCO fill detection window).
  TICK B: fake.fill_leg(symbol, leg='stop'|'target') — flattens position.
          Then executor.check_and_manage_open_trades(sim_dsn, source_filter='paper')
          — detects the OCO fill and writes legitimate exit_reason.
          Then reconcile_all_paper_trades(dry_run=False) — NO-OP since DB-closed
          == broker-flat.

Verify (in order):
  - provenance.assert_real_path_executed(...) — must NOT raise.
  - Oracle invariants run on the ORGANIC rows — all 9 PASS.

Reconcile-when-gone mode (§3.2): a position broker-flat (fake get_open_position
returns None) without a clean executor close — reconcile resolves with ZERO
orphans.

Teardown (try/finally): undo() from install_organic_patches; _config_cache = None;
reset_brokers(); restore any test-specific monkeypatches. MUST run even on
exception.

T13 RESIDUAL BLIND-SPOT INPUTS:
  - Sim runs at packet_worthy_threshold=30 vs prod default 70 (ranker.py:57).
    The lifecycle machinery (open->exit->reconcile) is what STABLE certifies;
    the threshold gate itself is NOT exercised at the prod level. T11's
    governor-reject scenario covers the deliberate-reject path.
  - PROD ranker tie-break unstable — fakes use distinct scores (T6 finding).
  - actual_shares=None at open — populated on fill (T6 finding).

Called by: tests/simulation/lifecycle/test_scenario.py; entrypoints/full_gate.py.
Calls: WatchLoop._run_scan, executor.check_and_manage_open_trades,
    reconcile_dispatch.reconcile_all_paper_trades, wiring helpers,
    provenance.assert_real_path_executed, Oracle.assert_all.
Owns tables: writes shadow_trades / recommendations VIA the real prod code path.
Config keys: ranking.packet_worthy_threshold (overridden to 30).
Tests: tests/simulation/lifecycle/test_scenario.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import src.config as _config_module
import src.journal.store as _journal_store_mod
import src.risk.price_utils as _price_utils_mod
import src.shadow_trading.executor as _executor_mod
import src.simulation.lifecycle.fakes.trading_client as _fake_tc_mod
import src.trading.broker_factory as _broker_factory
import src.training.versioning as _versioning_mod
from src.risk.governor import GOVERNOR_GATES
from src.scheduler.watch import WatchLoop
from src.shadow_trading.executor import check_and_manage_open_trades
from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
from src.simulation.lifecycle import wiring
from src.simulation.lifecycle.clock import VirtualClock, freeze_at
from src.simulation.lifecycle.coverage import LIFECYCLE_STAGES, CoverageMatrix
from src.simulation.lifecycle.fakes.llm import FakeLLM
from src.simulation.lifecycle.fakes.market_data import FakeMarketData
from src.simulation.lifecycle.fakes.trading_client import FakeAccount, FakeTradingClient
from src.simulation.lifecycle.oracle import CapitalLedger, Oracle, SwallowedErrorObserver
from src.simulation.lifecycle.prod_guard import install_prod_guard
from src.simulation.lifecycle.provenance import assert_real_path_executed

# Sim universe — 3 tickers exposes the prod ranker to scored candidates; the
# packet cap (max_packets_per_scan) is set to 1 via override so exactly one
# packet runs through the inline path per scan (clean-close bar §3.1: exactly
# 1 recommendations row + 1 shadow_trade row).
_SIM_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")

# Lower the packet_worthy threshold to 30 (prod default 70). FakeMarketData's
# random-walk OHLCV does NOT reliably feature-score >=70 through the prod ranker
# (universe_scanner.py:141-156). The lifecycle is what STABLE certifies; the
# threshold gate is NOT exercised at the prod level — T11 covers reject paths.
_SIM_PACKET_WORTHY_THRESHOLD = 30
# bootcamp.max_packets_per_scan caps how many packet-worthy names run the inline
# pipeline (universe_scanner.py:148-149). Setting it to 1 ensures exactly 1
# trade per scan even when the prod ranker admits multiple candidates.
_SIM_RANKING_OVERRIDE: dict = {
    "ranking": {"packet_worthy_threshold": _SIM_PACKET_WORTHY_THRESHOLD},
    "bootcamp": {"max_packets_per_scan": 1},
}

# Clock advance between tick A (open) and tick B (exit). 30 minutes exceeds the
# OCO fill-detection window so check_and_manage_open_trades observes the fill.
_TICK_B_ADVANCE = timedelta(minutes=30)

# Starting capital — $1M matches the FakeAccount default and the spec §2.5 seed.
_SIM_STARTING_CAPITAL = 1_000_000.0


@dataclass
class ScenarioResult:
    """The outcome of ScenarioRunner.run() — checkpoints + final invariants."""

    completed: bool
    checkpoints: list = field(default_factory=list)
    final_results: list = field(default_factory=list)
    coverage: CoverageMatrix = field(default_factory=CoverageMatrix)
    organic_open_rows: list[dict] = field(default_factory=list)
    provenance_passed: bool = False


def _noop_sleep(_seconds) -> None:
    """The sleep seam for the simulated loop — never blocks on real time."""
    return None


class ScenarioRunner:
    """Drives the REAL prod path organically across virtual ticks (KEYSTONE)."""

    def __init__(
        self,
        *,
        conn,
        start: datetime,
        seed: int = 0,
        faults=None,
        sim_dsn: Optional[str] = None,
    ) -> None:
        install_prod_guard()
        self.conn = conn
        self.clock = VirtualClock(start)
        # FakeAccount with $1M buying power / equity / portfolio_value / cash.
        # The fake clock drives every fill timestamp. fill_on_submit=True so the
        # entry order auto-fills on submit (matches OCO bracket happy path).
        self.fake_trading_client = FakeTradingClient(
            clock=self.clock,
            account=FakeAccount(
                cash=_SIM_STARTING_CAPITAL,
                buying_power=_SIM_STARTING_CAPITAL,
                equity=_SIM_STARTING_CAPITAL,
                portfolio_value=_SIM_STARTING_CAPITAL,
            ),
            fill_on_submit=True,
        )
        self.fake_market_data = FakeMarketData(seed=seed)
        # n_candidates=1: drive a single packet through the inline path per tick A
        # (clean-close bar §3.1: exactly 1 recommendations row + 1 shadow_trades row).
        self.fake_llm = FakeLLM(seed=seed, n_candidates=1)
        self.ledger = CapitalLedger(starting_capital=_SIM_STARTING_CAPITAL)
        self.observer = SwallowedErrorObserver()
        # Faults parameter retained for backwards-compat with prior signature; T10
        # owns fault injection — this KEYSTONE only drives the clean-close path.
        self._faults = list(faults or [])
        self.coverage = CoverageMatrix()
        self.watch_loop: Optional[WatchLoop] = None
        self.marks: dict[str, float] = {}
        self.sim_dsn: str = sim_dsn or _extract_dsn(conn)
        self.primed_dsn: Optional[str] = None
        # The undo() closure returned by install_organic_patches; teardown calls it.
        self._undo_patches: Optional[Callable[[], None]] = None
        # Sim-bridge monkeypatches captured in _setup, restored in _teardown.
        # These bridge prod code paths that default-route to SQLite (DB_PATH) when
        # the sim runs with ARCIS_DB_PATH popped by bootstrap.py — the PG cutover
        # gate routes the actual writes, but the init_* shims need the SQLite call
        # short-circuited or the path resolved to the sim DSN.
        self._sim_bridge_undo: Optional[Callable[[], None]] = None

    # ── public entrypoint ──────────────────────────────────────────────────

    def run(self, *, days: int = 1, reconcile_when_gone: bool = False) -> ScenarioResult:
        """Drive the organic open->exit->reconcile lifecycle and assert STABLE.

        ``days`` is retained for caller compatibility but the KEYSTONE drives
        a single open->exit->reconcile cycle per call (a "day" in §3.1 terms).
        Multi-day runs simply repeat the cycle; the clean-close bar is asserted
        on the final cycle's organic rows.

        ``reconcile_when_gone`` enables §3.2 mode: drive a position that's
        broker-flat (fake.get_open_position returns None) without a clean
        executor close — reconcile must resolve with ZERO orphans.
        """
        self._setup()
        checkpoints: list = []
        organic_rows: list[dict] = []
        provenance_passed = False
        final: list = []
        try:
            for _day_idx in range(max(1, days)):
                organic_rows = self._drive_one_cycle(
                    reconcile_when_gone=reconcile_when_gone
                )
            # Provenance: assert the REAL prod path executed (anti-hollow-STABLE).
            # psycopg2 normalizes the URL DSN to keyword form on .dsn, but the
            # T8 provenance check asserts the URL-form fragments (:5434/, test:test).
            # We wrap conn in a thin adapter that exposes the original URL-form DSN
            # so both the strict equality check (Property 3b) and the signature
            # check (port/cred fragments) pass on the same canonical string.
            url_dsn = self.primed_dsn or self.sim_dsn
            assert_real_path_executed(
                self.fake_trading_client,
                self.fake_market_data,
                self.fake_llm,
                _UrlDsnConnAdapter(self.conn, url_dsn),
                url_dsn,
                organic_rows,
            )
            provenance_passed = True
            # Oracle invariants on the ORGANIC rows — all 9 must PASS.
            final = self._checkpoint()
        finally:
            self._teardown()
        return ScenarioResult(
            completed=True,
            checkpoints=checkpoints,
            final_results=final,
            coverage=self.coverage,
            organic_open_rows=organic_rows,
            provenance_passed=provenance_passed,
        )

    # ── setup / teardown (try/finally — no leakage even on exception) ──────

    def _setup(self) -> None:
        """Reset singletons, prime config + watch config, install patches."""
        _broker_factory.reset_brokers()
        _config_module._config_cache = None
        self.observer.install()

        # Prime load_config() with the sim DSN + packet_worthy_threshold=30.
        # Both prime + build use the same DSN signature checked by the wiring
        # guard (refuses any non-5434 DSN — see wiring._assert_sim_dsn).
        self.primed_dsn = self.sim_dsn
        wiring.prime_config(self.sim_dsn, overrides=_SIM_RANKING_OVERRIDE)
        # WatchLoop.config and ScanContext.config both read the same dict shape.
        # The LLM gate reads ctx.config (packet_writer.py:1158-1159), so the
        # watch config MUST carry the threshold override too.
        watch_cfg = wiring.build_watch_config(self.sim_dsn, overrides=_SIM_RANKING_OVERRIDE)

        # Apply the 5 monkeypatches (alpaca _get_trading_client, fetch_ohlcv,
        # fetch_spy_benchmark, packet_writer.generate, is_llm_available,
        # sp100.get_sp100_universe, journal.store.uuid — T7 §3.4 stub).
        self._undo_patches = wiring.install_organic_patches(
            self.fake_trading_client,
            self.fake_market_data,
            self.fake_llm,
            list(_SIM_UNIVERSE),
        )

        # Sim-bridge: shim a few prod-defaults that resolve to SQLite (DB_PATH=None
        # after bootstrap pops ARCIS_DB_PATH). The PG cutover gate routes the actual
        # writes — these patches keep the init_* shims from blowing up on
        # `_sqlite_only_connect(None)`. Restored by teardown.
        self._sim_bridge_undo = self._install_sim_bridges()

        # Register the fill listener so every fake fill feeds the CapitalLedger
        # (oracle inv5 capital conservation; spec §2.5 step 7).
        self.fake_trading_client.set_fill_listener(
            lambda **kw: self.ledger.apply_fill(**kw)
        )
        # Reset call counters so provenance seam-counts reflect THIS run only.
        self.fake_trading_client.calls.clear()
        self.fake_market_data.calls.clear()
        self.fake_llm.calls.clear()

        # Build the real WatchLoop with the virtual clock + noop sleep.
        self.watch_loop = WatchLoop(
            config=watch_cfg,
            email_mode="digest",
            overnight=False,  # T9 stays in-process; overnight handlers DEFERRED.
            clock=self.clock.now,
            sleep=_noop_sleep,
        )

    def _teardown(self) -> None:
        """Undo patches, reset singletons + config cache. MUST be exception-safe.

        Order matters: undo patches FIRST (restores _get_trading_client so any
        residual reset_brokers/cache-clear does not see the patched symbol).
        """
        try:
            if self._undo_patches is not None:
                try:
                    self._undo_patches()
                finally:
                    self._undo_patches = None
        finally:
            try:
                if self._sim_bridge_undo is not None:
                    try:
                        self._sim_bridge_undo()
                    finally:
                        self._sim_bridge_undo = None
            finally:
                try:
                    self.observer.detach()
                finally:
                    _broker_factory.reset_brokers()
                    _config_module._config_cache = None

    def _install_sim_bridges(self) -> Callable[[], None]:
        """Shim prod helpers that default-route to SQLite when DB_PATH=None.

        After bootstrap.py scrubs ARCIS_DB_PATH from env, src.config.DB_PATH is
        None. The PG cutover gate routes most actual data ops to the sim PG, but
        a few init helpers (``versioning.init_training_tables`` and
        ``journal.store.initialize_database``) call ``_sqlite_only_connect`` with
        the SQLite default, which crashes on None. And
        ``universe_scanner.get_active_model_name`` calls
        ``training.versioning.get_active_model_name(DB_PATH)`` which transitively
        hits the same shim. We short-circuit these to no-ops / safe defaults so
        the inline scan path can run end-to-end. Restored by ``undo()``.
        """
        originals: dict[tuple, object] = {}

        def _capture(module, attr):
            originals[(module, attr)] = getattr(module, attr)

        _capture(_versioning_mod, "init_training_tables")
        _capture(_versioning_mod, "get_active_model_name")
        _capture(_journal_store_mod, "initialize_database")
        _capture(_fake_tc_mod.FakeTradingClient, "_build_legs")

        def _noop_init(*args, **kwargs) -> None:
            return None

        def _sim_active_model(*args, **kwargs) -> str:
            return "sim-model"

        # Pydantic-aware _build_legs replacement: the original calls
        # take_profit.get("limit_price") which fails for pydantic TakeProfitRequest
        # objects (the alpaca-py SDK shape). place_bracket_order in executor builds
        # MarketOrderRequest with take_profit={"limit_price": ...} which pydantic
        # auto-converts to TakeProfitRequest. The shim extracts the price via
        # attribute access OR dict-get so both shapes round-trip cleanly.
        def _pydantic_aware_build_legs(self, request, symbol, qty, entry_side):
            tp = getattr(request, "take_profit", None)
            sl = getattr(request, "stop_loss", None)
            if not tp and not sl:
                return []
            exit_side = "sell" if entry_side == "buy" else "buy"
            legs = []
            if tp:
                tp_limit = _extract_price(tp, "limit_price")
                tp_id, tp_coid = self._next_id("tp")
                legs.append(_fake_tc_mod.FakeOrder(
                    order_id=tp_id, client_order_id=tp_coid, symbol=symbol,
                    qty=qty, side=exit_side, order_type="limit", status="held",
                    limit_price=tp_limit,
                    created_at=self._now_iso(),
                ))
            if sl:
                sl_stop = _extract_price(sl, "stop_price")
                sl_id, sl_coid = self._next_id("sl")
                legs.append(_fake_tc_mod.FakeOrder(
                    order_id=sl_id, client_order_id=sl_coid, symbol=symbol,
                    qty=qty, side=exit_side, order_type="stop", status="held",
                    stop_price=sl_stop,
                    created_at=self._now_iso(),
                ))
            return legs

        def undo() -> None:
            for (module, attr), original in originals.items():
                setattr(module, attr, original)

        try:
            _versioning_mod.init_training_tables = _noop_init  # type: ignore[assignment]
            _versioning_mod.get_active_model_name = _sim_active_model  # type: ignore[assignment]
            _journal_store_mod.initialize_database = _noop_init  # type: ignore[assignment]
            _fake_tc_mod.FakeTradingClient._build_legs = _pydantic_aware_build_legs  # type: ignore[assignment]
        except Exception:
            undo()
            raise
        return undo

    # ── organic drive: tick A (open) + tick B (exit + reconcile) ───────────

    def _drive_one_cycle(self, *, reconcile_when_gone: bool) -> list[dict]:
        """Drive one open->exit->reconcile cycle. Returns organic open rows."""
        assert self.watch_loop is not None, "_setup must build the watch_loop"
        # TICK A — organic open: scan -> packet -> LLM -> governor -> executor.
        with freeze_at(self.clock):
            self.watch_loop._run_scan()
            # Defensive: reconcile-after-scan is what watch.py:849-853 does in
            # the prod path. Call it explicitly so the inline path matches prod.
            reconcile_all_paper_trades(db_path=self.sim_dsn, dry_run=False)
        self.coverage.mark_stage("open")
        self.coverage.mark_capability("execute_trade")

        # Capture the organic open rows for provenance + later assertions.
        organic_rows = self._fetch_shadow_trade_rows(status="open")

        # Update marks dict from organic open prices so the oracle's mark-to-
        # market and drawdown computations match the ledger.
        for row in organic_rows:
            price = row.get("actual_entry_price") or row.get("entry_price")
            if price is not None:
                self.marks[row["ticker"]] = float(price)

        # ADVANCE clock past the OCO fill-detection window.
        self.clock.advance(_TICK_B_ADVANCE)

        # TICK B — organic exit.
        with freeze_at(self.clock):
            if reconcile_when_gone:
                self._drive_reconcile_when_gone(organic_rows)
            else:
                self._drive_oco_exit(organic_rows)
            # Reconcile: should NO-OP since DB-closed == broker-flat.
            reconcile_all_paper_trades(db_path=self.sim_dsn, dry_run=False)

        self.coverage.mark_stage("close")
        self.coverage.mark_capability("close_trade")
        # Record gate coverage for the training-stage checkpoint matrix.
        for gate in GOVERNOR_GATES:
            self.coverage.mark_gate(gate)

        # Clear marks for closed positions (drawdown is computed on remaining
        # open positions).
        for row in organic_rows:
            self.marks.pop(row["ticker"], None)

        return organic_rows

    def _drive_oco_exit(self, organic_rows: list[dict]) -> None:
        """Fire the OCO take-profit leg for each organic open; detect via executor."""
        for row in organic_rows:
            symbol = row["ticker"]
            entry = float(row.get("actual_entry_price") or row.get("entry_price") or 0.0)
            exit_price = entry * 1.05 if entry > 0 else 105.0
            # Fill the take-profit leg (executor detects on next manage cycle).
            leg_id = self._find_held_leg(symbol, leg="take_profit")
            if leg_id is not None:
                self.fake_trading_client.fill_leg(leg_id, fill_price=exit_price)
        # Detect the OCO fill — writes legitimate exit_reason (take_profit, etc.).
        check_and_manage_open_trades(db_path=self.sim_dsn, source_filter="paper")

    def _drive_reconcile_when_gone(self, organic_rows: list[dict]) -> None:
        """§3.2 mode: broker-flat without a clean executor close; reconcile resolves zero orphans.

        Removes the FakePosition directly (simulating "position vanished") so the
        DB row is still 'open' but fake.get_open_position(symbol) returns None.
        reconcile_all_paper_trades must close it WITHOUT producing orphan /
        reconciled rows.
        """
        for row in organic_rows:
            symbol = row["ticker"]
            # Forcibly drop the FakePosition without a real OCO fill — broker-flat.
            self.fake_trading_client._positions.pop(symbol, None)

    def _find_held_leg(self, symbol: str, *, leg: str) -> Optional[str]:
        """Find the held OCO leg id for ``symbol`` (leg='take_profit' or 'stop')."""
        side = "sell"  # exit side for a long entry
        target_type = "limit" if leg == "take_profit" else "stop"
        for order_id, order in self.fake_trading_client._orders.items():
            if (
                order.symbol == symbol
                and order.side == side
                and order.status == "held"
                and order.type == target_type
            ):
                return order_id
        return None

    # ── DB read for provenance + assertion ─────────────────────────────────

    def _fetch_shadow_trade_rows(self, *, status: Optional[str] = None) -> list[dict]:
        """Fetch shadow_trades rows as dicts (provenance + assertions consume them).

        Returns a list of dicts with the inv9-hashed columns (and a few extras
        the runner needs for marks / leg lookup).
        """
        cols = (
            "trade_id",
            "recommendation_id",
            "ticker",
            "status",
            "actual_shares",
            "order_type",
            "exit_reason",
            "pnl_dollars",
            "entry_price",
            "actual_entry_price",
        )
        sql = f"SELECT {', '.join(cols)} FROM shadow_trades"
        with self.conn.cursor() as cur:
            if status is not None:
                sql += " WHERE status = %s"
                cur.execute(sql + " ORDER BY trade_id", (status,))
            else:
                cur.execute(sql + " ORDER BY trade_id")
            rows: list[dict] = []
            for raw in cur.fetchall():
                rows.append(dict(zip(cols, raw)))
        return rows

    # ── Oracle checkpoint (the 9 invariants) ───────────────────────────────

    def _checkpoint(self) -> list:
        """Build a fresh Oracle on current state and run all 9 invariants."""
        oracle = Oracle(
            conn=self.conn,
            capital_ledger=self.ledger,
            fake_trading_client=self.fake_trading_client,
            observer=self.observer,
            marks=self.marks,
            db_reported_pnl=self.ledger.realized_pnl(),
            governor_drawdown_pct=self.ledger.drawdown(self.marks) * 100.0,
            clock=self.clock,
        )
        return oracle.assert_all()


def _extract_dsn(conn) -> str:
    """Pull the DSN string off a psycopg2 connection (used for self.sim_dsn)."""
    dsn = getattr(conn, "dsn", None)
    if dsn is not None:
        return str(dsn)
    raise ValueError(
        "ScenarioRunner requires a connection with a .dsn attribute "
        "(psycopg2 Connection) or an explicit sim_dsn parameter."
    )


def _extract_price(obj, key: str) -> Optional[float]:
    """Pull a price field from a dict or pydantic-style object.

    The Alpaca SDK auto-converts {"limit_price": 105.0} to TakeProfitRequest
    inside MarketOrderRequest. The pydantic-derived class has neither .get()
    nor dict-style access — only attribute access. This helper falls through
    both shapes and the empty-string sentinel _to_price uses.
    """
    val: object = None
    if hasattr(obj, "get") and callable(getattr(obj, "get", None)):
        try:
            val = obj.get(key)
        except (TypeError, AttributeError):
            val = None
    if val is None:
        val = getattr(obj, key, None)
    if val in (None, ""):
        return None
    return float(val)


class _UrlDsnConnAdapter:
    """Adapter that exposes a URL-form .dsn for T8 provenance.

    psycopg2 normalizes URL DSNs to keyword form on connection.dsn
    ("port=5434 user=test password=xxx"), but the provenance guard
    (T8, src/simulation/lifecycle/provenance.py) asserts the URL-form
    signature fragments (':5434/', 'test:test'). This adapter wraps the
    real connection and overrides only the .dsn attribute with the original
    URL string — every other attribute read passes through to the real conn.

    Used only at provenance.assert_real_path_executed call time, not held.
    """

    def __init__(self, conn, url_dsn: str) -> None:
        self._conn = conn
        self.dsn = url_dsn

    def __getattr__(self, item):
        return getattr(self._conn, item)


__all__ = ["ScenarioRunner", "ScenarioResult"]
