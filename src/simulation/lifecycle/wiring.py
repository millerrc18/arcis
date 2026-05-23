"""Simulator wiring helpers for the lifecycle sim (T5, #97).

Three callables consumed by ScenarioRunner (T9):

  prime_config(dsn, overrides)           — clears the global config cache then
                                           primes load_config() with the sim dict.
  build_watch_config(dsn, overrides)     — returns the same dict shape for
                                           WatchLoop.config / ScanContext.config.
  install_organic_patches(...)           — applies 4 monkeypatches and returns an
                                           undo() closure that restores every
                                           original to is-identity.

Called by: simulation.lifecycle.scenario (T9 — not yet wired).
Calls: src.config, src.shadow_trading.alpaca_adapter, src.data_ingestion.market_data,
       src.llm.packet_writer, src.universe.sp100.
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_wiring.py
"""

from __future__ import annotations

import itertools
import uuid as _uuid_module
from typing import Callable

import src.config as _config_module
import src.data_ingestion.market_data as _market_data_mod
import src.journal.store as _journal_store_mod
import src.llm.packet_writer as _packet_writer_mod
import src.shadow_trading.alpaca_adapter as _alpaca_mod
import src.shadow_trading.executor as _executor_mod
import src.trading.broker_factory as _broker_factory_mod
import src.universe.sp100 as _sp100_mod
from src.config import load_config

_SIM_DSN_DEFAULT = "postgresql://test:test@127.0.0.1:5434/halcyon"


class _DeterministicUuidStub:
    """Module-shaped stub replacing journal.store's `uuid` reference (T7 §3.4).

    journal.store does `import uuid` then `uuid.uuid4()` at line 132 (the
    recommendation_id mint) and line 245 (trade_id fallback). Stdlib `uuid.uuid4()`
    draws from os.urandom — NOT seedable, NOT freezable — so two seeded+frozen
    sim runs produce DIFFERENT recommendation_ids, breaking inv9 determinism.

    This stub replaces store's module-local `uuid` reference (NOT the global
    stdlib uuid module) with a counter-based deterministic minter. Same install
    cycle → counter starts at 1 → identical recommendation_id sequence across
    runs. undo() restores store.uuid to the stdlib module.

    The stub exposes uuid.UUID (for downstream isinstance checks) and uuid4().
    Other uuid surface (uuid1, uuid5, etc.) is not stubbed — store doesn't use it.
    """

    UUID = _uuid_module.UUID

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def uuid4(self):
        return _uuid_module.UUID(int=next(self._counter), version=4)


def _base_sim_dict(dsn: str) -> dict:
    """Return the canonical sim config dict (shadow + llm enabled, 5434 DSN)."""
    return {
        "shadow_trading": {"enabled": True},
        "llm": {"enabled": True},
        "use_grammar_enforcement": False,
        "database_url": dsn,
    }


def _assert_sim_dsn(dsn: str) -> None:
    """Hard prod-isolation guard — reject any DSN missing the :5434/ sim port.

    The simulator MUST NEVER touch a prod DB (CLAUDE.md sacred-rule territory).
    Per spec §4.5, the sim runs against an ephemeral PG on port 5434 (the
    docker-compose.test.yml local fixture). This guard refuses any DSN that
    doesn't carry the :5434/ signature — convention alone is too weak.
    """
    if ":5434/" not in dsn:
        raise ValueError(
            f"Sim DSN must contain ':5434/' (5434 = ephemeral test PG port); "
            f"got: {dsn!r}. Refusing to prime a non-sim DSN — the simulator "
            f"NEVER touches prod (spec §4.5, CLAUDE.md prod-isolation rule)."
        )


def prime_config(dsn: str, overrides: dict | None = None) -> dict:
    """Clear the config cache, prime load_config() with the sim dict, return it.

    After this call, any module that calls load_config() will receive the primed
    dict — which has shadow_trading.enabled=True, llm.enabled=True,
    use_grammar_enforcement=False, and the 5434 sim DSN.

    The overrides dict is merged on top for test parameterization.

    Raises ValueError if dsn is not a 5434 sim DSN (prod-isolation guard).
    """
    _assert_sim_dsn(dsn)
    _config_module._config_cache = None
    primed: dict = _base_sim_dict(dsn)
    if overrides:
        primed.update(overrides)
    _config_module._config_cache = primed
    return primed


def build_watch_config(dsn: str, overrides: dict | None = None) -> dict:
    """Return a sim config dict for assignment to WatchLoop.config / ScanContext.config.

    enhance_packet_with_llm reads its passed-in config (ctx.config == WatchLoop.config)
    at packet_writer.py:1158-1159, NOT a global load_config(). Both WatchLoop.config
    and any ScanContext must be primed with this dict for the LLM-enabled gate to fire.

    Returns the same key shape as prime_config; does NOT touch _config_cache.

    Raises ValueError if dsn is not a 5434 sim DSN (prod-isolation guard).
    """
    _assert_sim_dsn(dsn)
    cfg: dict = _base_sim_dict(dsn)
    if overrides:
        cfg.update(overrides)
    return cfg


def install_organic_patches(
    fake_tc,
    fake_md,
    fake_llm,
    universe: list[str],
) -> Callable[[], None]:
    """Apply 5 monkeypatches and return an undo() closure.

    Patches applied:
      1. alpaca_adapter._get_trading_client → lambda returning fake_tc
      2. market_data.fetch_ohlcv → fake_md.fetch_ohlcv
         market_data.fetch_spy_benchmark → fake_md.fetch_spy_benchmark
      3. packet_writer.generate → fake_llm.generate
         packet_writer.is_llm_available → lambda: True
      4. sp100.get_sp100_universe → lambda: universe
      5. journal.store.uuid → _DeterministicUuidStub() (T7 §3.4 escalation:
         the stdlib uuid.uuid4 isn't seedable, breaking recommendation_id
         determinism for inv9 equality — the stub replaces store's local
         `uuid` reference with a counter-based deterministic minter, leaving
         the global stdlib uuid module untouched).
      6. trading.broker_factory.get_live_broker → lambda: None (T9 spec
         gap: executor.check_and_manage_open_trades calls live_broker.
         get_all_positions(), which reaches alpaca_adapter_live's
         _get_live_trading_client — NOT covered by patch #1 (paper-only).
         Returning None makes the executor's `if live_broker:` branches
         (executor.py:1664 et al.) short-circuit to paper-only. The
         simulator's broker state is the PAPER fake_tc by design; the live
         broker is not part of the lifecycle being certified.
      7. shadow_trading.executor._get_current_price_safe → lambda ticker:
         100.0 (T9 spec gap: real impl tries to call market data with a
         signature the fake doesn't support, returns None, which makes
         check_and_manage_open_trades skip OCO exit detection at
         executor.py:1702-1705. Returning a fixed sim price lets the exit
         loop proceed to the OCO leg-fill check. The exit decision is
         actually driven by the fake's fill_leg, not by current_price.

    Each install_organic_patches call creates a FRESH _DeterministicUuidStub
    (counter starts at 1), so two seeded sim runs that drive the same number
    of log_recommendation calls produce identical recommendation_id sequences.

    All originals are captured via getattr BEFORE any setattr. undo() restores
    every original to is-identity (verified by test_wiring.py).
    """
    uuid_stub = _DeterministicUuidStub()

    originals: dict[tuple, object] = {
        (_alpaca_mod, "_get_trading_client"): _alpaca_mod._get_trading_client,
        (_market_data_mod, "fetch_ohlcv"): _market_data_mod.fetch_ohlcv,
        (_market_data_mod, "fetch_spy_benchmark"): _market_data_mod.fetch_spy_benchmark,
        (_packet_writer_mod, "generate"): _packet_writer_mod.generate,
        (_packet_writer_mod, "is_llm_available"): _packet_writer_mod.is_llm_available,
        (_sp100_mod, "get_sp100_universe"): _sp100_mod.get_sp100_universe,
        (_journal_store_mod, "uuid"): _journal_store_mod.uuid,
        (_broker_factory_mod, "get_live_broker"): _broker_factory_mod.get_live_broker,
        (_executor_mod, "_get_current_price_safe"): _executor_mod._get_current_price_safe,
    }

    def undo() -> None:
        for (module, attr), original in originals.items():
            setattr(module, attr, original)

    # The setattrs are wrapped in try/except so a partial-patch failure mid-way
    # rolls back to the captured originals (no leakage). All targets are plain
    # module-level attributes, so setattr is extremely unlikely to raise — but
    # the spec calls out leak-resistance as a requirement (§2.5 teardown
    # discipline). _get_trading_client uses (*a, **kw) to accept positional
    # `desk` calls (e.g., `_get_trading_client('equity_long')`) without TypeError.
    try:
        setattr(_alpaca_mod, "_get_trading_client", lambda *a, **kw: fake_tc)
        setattr(_market_data_mod, "fetch_ohlcv", fake_md.fetch_ohlcv)
        setattr(_market_data_mod, "fetch_spy_benchmark", fake_md.fetch_spy_benchmark)
        setattr(_packet_writer_mod, "generate", fake_llm.generate)
        setattr(_packet_writer_mod, "is_llm_available", lambda: True)
        setattr(_sp100_mod, "get_sp100_universe", lambda: universe)
        setattr(_journal_store_mod, "uuid", uuid_stub)
        setattr(_broker_factory_mod, "get_live_broker", lambda *a, **kw: None)
        setattr(_executor_mod, "_get_current_price_safe", lambda ticker: 100.0)
    except Exception:
        undo()
        raise

    return undo
