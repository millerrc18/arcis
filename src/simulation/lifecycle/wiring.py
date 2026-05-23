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

from typing import Callable

import src.config as _config_module
import src.data_ingestion.market_data as _market_data_mod
import src.llm.packet_writer as _packet_writer_mod
import src.shadow_trading.alpaca_adapter as _alpaca_mod
import src.universe.sp100 as _sp100_mod
from src.config import load_config

_SIM_DSN_DEFAULT = "postgresql://test:test@127.0.0.1:5434/halcyon"


def _base_sim_dict(dsn: str) -> dict:
    """Return the canonical sim config dict (shadow + llm enabled, 5434 DSN)."""
    return {
        "shadow_trading": {"enabled": True},
        "llm": {"enabled": True},
        "use_grammar_enforcement": False,
        "database_url": dsn,
    }


def prime_config(dsn: str, overrides: dict | None = None) -> dict:
    """Clear the config cache, prime load_config() with the sim dict, return it.

    After this call, any module that calls load_config() will receive the primed
    dict — which has shadow_trading.enabled=True, llm.enabled=True,
    use_grammar_enforcement=False, and the 5434 sim DSN.

    The overrides dict is merged on top for test parameterization.
    """
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
    """
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
    """Apply 4 monkeypatches and return an undo() closure.

    Patches applied:
      1. alpaca_adapter._get_trading_client → lambda returning fake_tc
      2. market_data.fetch_ohlcv → fake_md.fetch_ohlcv
         market_data.fetch_spy_benchmark → fake_md.fetch_spy_benchmark
      3. packet_writer.generate → fake_llm.generate
         packet_writer.is_llm_available → lambda: True
      4. sp100.get_sp100_universe → lambda: universe

    All originals are captured via getattr BEFORE any setattr. undo() restores
    every original to is-identity (verified by test_wiring.py).
    """
    originals: dict[tuple, object] = {
        (_alpaca_mod, "_get_trading_client"): _alpaca_mod._get_trading_client,
        (_market_data_mod, "fetch_ohlcv"): _market_data_mod.fetch_ohlcv,
        (_market_data_mod, "fetch_spy_benchmark"): _market_data_mod.fetch_spy_benchmark,
        (_packet_writer_mod, "generate"): _packet_writer_mod.generate,
        (_packet_writer_mod, "is_llm_available"): _packet_writer_mod.is_llm_available,
        (_sp100_mod, "get_sp100_universe"): _sp100_mod.get_sp100_universe,
    }

    setattr(_alpaca_mod, "_get_trading_client", lambda **kw: fake_tc)
    setattr(_market_data_mod, "fetch_ohlcv", fake_md.fetch_ohlcv)
    setattr(_market_data_mod, "fetch_spy_benchmark", fake_md.fetch_spy_benchmark)
    setattr(_packet_writer_mod, "generate", fake_llm.generate)
    setattr(_packet_writer_mod, "is_llm_available", lambda: True)
    setattr(_sp100_mod, "get_sp100_universe", lambda: universe)

    def undo() -> None:
        for (module, attr), original in originals.items():
            setattr(module, attr, original)

    return undo
