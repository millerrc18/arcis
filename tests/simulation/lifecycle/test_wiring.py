"""Tests for src.simulation.lifecycle.wiring (T5, #97).

Covers:
  1. prime_config: clears cache, primes load_config() with correct keys + DSN
  2. build_watch_config: returns same dict shape (keys + DSN)
  3. install_organic_patches: all 4 symbol groups patched (identity check)
  4. undo(): all originals restored (is-identity check)
  5. DSN safety: primed DSN contains :5434/ (never prod signature)
  6. Idempotency: install → undo → install → undo leaves originals intact
  7. No leakage: try/finally semantics — originals restored even on teardown
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import src.config as _config_module
import src.data_ingestion.market_data as _market_data_mod
import src.llm.packet_writer as _packet_writer_mod
import src.shadow_trading.alpaca_adapter as _alpaca_mod
import src.universe.sp100 as _sp100_mod
from src.simulation.lifecycle.fakes.llm import FakeLLM
from src.simulation.lifecycle.fakes.market_data import FakeMarketData
from src.simulation.lifecycle.fakes.trading_client import FakeTradingClient
from src.simulation.lifecycle.clock import VirtualClock
from src.simulation.lifecycle.wiring import (
    build_watch_config,
    install_organic_patches,
    prime_config,
)

_ET = ZoneInfo("America/New_York")

_SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"
_UNIVERSE = ["AAPL", "MSFT", "NVDA"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_fakes():
    clock = VirtualClock(start=datetime(2025, 6, 2, 9, 30, tzinfo=_ET))
    fake_tc = FakeTradingClient(clock=clock)
    fake_md = FakeMarketData(seed=42)
    fake_llm = FakeLLM(seed=0)
    return fake_tc, fake_md, fake_llm


# ── 1. prime_config ──────────────────────────────────────────────────────────

def test_prime_config_clears_cache():
    """prime_config must set _config_cache to None before re-priming."""
    _config_module._config_cache = {"stale": True}
    prime_config(_SIM_DSN)
    # After the call the cache is the primed dict, not the stale one
    assert _config_module._config_cache is not None
    assert "stale" not in _config_module._config_cache


def test_prime_config_shadow_trading_enabled():
    result = prime_config(_SIM_DSN)
    assert result.get("shadow_trading", {}).get("enabled") is True


def test_prime_config_llm_enabled():
    result = prime_config(_SIM_DSN)
    assert result.get("llm", {}).get("enabled") is True


def test_prime_config_grammar_enforcement_false():
    result = prime_config(_SIM_DSN)
    assert result.get("use_grammar_enforcement") is False


def test_prime_config_dsn_present():
    result = prime_config(_SIM_DSN)
    assert result.get("database_url") == _SIM_DSN


def test_prime_config_load_config_returns_primed():
    """After prime_config, load_config() must return the same primed dict."""
    primed = prime_config(_SIM_DSN)
    from src.config import load_config
    loaded = load_config()
    assert loaded is primed


def test_prime_config_overrides_applied():
    result = prime_config(_SIM_DSN, overrides={"custom_key": "custom_val"})
    assert result["custom_key"] == "custom_val"


# ── 2. build_watch_config ────────────────────────────────────────────────────

def test_build_watch_config_shadow_trading_enabled():
    result = build_watch_config(_SIM_DSN)
    assert result.get("shadow_trading", {}).get("enabled") is True


def test_build_watch_config_llm_enabled():
    result = build_watch_config(_SIM_DSN)
    assert result.get("llm", {}).get("enabled") is True


def test_build_watch_config_grammar_enforcement_false():
    result = build_watch_config(_SIM_DSN)
    assert result.get("use_grammar_enforcement") is False


def test_build_watch_config_dsn_present():
    result = build_watch_config(_SIM_DSN)
    assert result.get("database_url") == _SIM_DSN


def test_build_watch_config_overrides_applied():
    result = build_watch_config(_SIM_DSN, overrides={"my_override": 99})
    assert result["my_override"] == 99


def test_build_watch_config_same_keys_as_prime_config():
    """build_watch_config must have the same required key set as prime_config."""
    prime = prime_config(_SIM_DSN)
    watch = build_watch_config(_SIM_DSN)
    for key in ("shadow_trading", "llm", "use_grammar_enforcement", "database_url"):
        assert key in prime
        assert key in watch


# ── 3. install_organic_patches — after-install symbol identity ──────────────

def test_install_patches_alpaca_adapter():
    """_get_trading_client must be replaced (not the original)."""
    orig = _alpaca_mod._get_trading_client
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        assert _alpaca_mod._get_trading_client is not orig
    finally:
        undo()


def test_install_patches_market_data_fetch_ohlcv():
    """fetch_ohlcv must be replaced."""
    orig = _market_data_mod.fetch_ohlcv
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        assert _market_data_mod.fetch_ohlcv is not orig
    finally:
        undo()


def test_install_patches_market_data_fetch_spy_benchmark():
    """fetch_spy_benchmark must be replaced."""
    orig = _market_data_mod.fetch_spy_benchmark
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        assert _market_data_mod.fetch_spy_benchmark is not orig
    finally:
        undo()


def test_install_patches_packet_writer_generate():
    """packet_writer.generate must be replaced."""
    orig = _packet_writer_mod.generate
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        assert _packet_writer_mod.generate is not orig
    finally:
        undo()


def test_install_patches_packet_writer_is_llm_available():
    """packet_writer.is_llm_available must be replaced and return True."""
    orig = _packet_writer_mod.is_llm_available
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        assert _packet_writer_mod.is_llm_available is not orig
        assert _packet_writer_mod.is_llm_available() is True
    finally:
        undo()


def test_install_patches_sp100_universe():
    """get_sp100_universe must return the injected small list."""
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        result = _sp100_mod.get_sp100_universe()
        assert result == _UNIVERSE
    finally:
        undo()


def test_install_patches_alpaca_returns_fake_tc():
    """_get_trading_client() must return the fake_tc object."""
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        returned = _alpaca_mod._get_trading_client()
        assert returned is fake_tc
    finally:
        undo()


# ── 4. undo() — originals restored with is-identity ─────────────────────────

def test_undo_restores_alpaca_adapter():
    orig = _alpaca_mod._get_trading_client
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _alpaca_mod._get_trading_client is orig


def test_undo_restores_fetch_ohlcv():
    orig = _market_data_mod.fetch_ohlcv
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _market_data_mod.fetch_ohlcv is orig


def test_undo_restores_fetch_spy_benchmark():
    orig = _market_data_mod.fetch_spy_benchmark
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _market_data_mod.fetch_spy_benchmark is orig


def test_undo_restores_packet_writer_generate():
    orig = _packet_writer_mod.generate
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _packet_writer_mod.generate is orig


def test_undo_restores_packet_writer_is_llm_available():
    orig = _packet_writer_mod.is_llm_available
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _packet_writer_mod.is_llm_available is orig


def test_undo_restores_sp100_universe():
    orig = _sp100_mod.get_sp100_universe
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _sp100_mod.get_sp100_universe is orig


# ── 4b. journal.store.uuid — T7 §3.4 deterministic recommendation_id ─────────


def test_install_patches_store_uuid_is_deterministic_stub():
    """Patched store.uuid.uuid4() returns DISTINCT, sequential, version-4 UUIDs."""
    import src.journal.store as _store_mod
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        id1 = _store_mod.uuid.uuid4()
        id2 = _store_mod.uuid.uuid4()
        id3 = _store_mod.uuid.uuid4()
        # Distinct (the counter advances each call)
        assert id1 != id2 != id3 and id1 != id3
        # Real UUID instances with version=4 (UUID() sets version/variant bits;
        # the counter-int=1/2/3 isn't preserved as .int directly)
        assert id1.version == 4 and id2.version == 4 and id3.version == 4
        # str() yields canonical UUID format (what store.py uses for rec_id)
        assert isinstance(str(id1), str) and len(str(id1)) == 36
        # Sequential — id1 < id2 < id3 because UUID(int=n) ordering matches n
        assert id1.int < id2.int < id3.int
    finally:
        undo()


def test_recommendation_id_reproducible_across_install_cycles():
    """Two full install→undo→install cycles produce the same first UUID each time.

    This is the T7 §3.4 acceptance criterion: a fresh ScenarioRunner install
    must start the counter at 1, so two seeded runs that drive the same number
    of log_recommendation calls produce identical recommendation_id sequences.
    """
    import src.journal.store as _store_mod
    fake_tc, fake_md, fake_llm = _make_fakes()

    undo1 = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    first_id_cycle_a = _store_mod.uuid.uuid4()
    second_id_cycle_a = _store_mod.uuid.uuid4()
    undo1()

    undo2 = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    first_id_cycle_b = _store_mod.uuid.uuid4()
    second_id_cycle_b = _store_mod.uuid.uuid4()
    undo2()

    assert first_id_cycle_a == first_id_cycle_b
    assert second_id_cycle_a == second_id_cycle_b


def test_undo_restores_store_uuid_to_stdlib():
    """After undo, src.journal.store.uuid IS the stdlib uuid module again."""
    import uuid as _real_uuid
    import src.journal.store as _store_mod
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    undo()
    assert _store_mod.uuid is _real_uuid


def test_global_uuid_module_unaffected_during_install():
    """Patching store.uuid must NOT pollute the global stdlib uuid module.

    Other code paths (anywhere outside journal.store) should still get real
    random uuid4 from the stdlib — proving the stub is module-local, not global.
    """
    import uuid as _real_uuid
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        # Real stdlib uuid module still produces non-deterministic UUIDs
        real_a = _real_uuid.uuid4()
        real_b = _real_uuid.uuid4()
        assert real_a != real_b  # extremely unlikely to collide
        # And they are NOT the deterministic int=1, int=2 sequence
        assert real_a.int != 1
    finally:
        undo()


# ── 5. DSN safety ────────────────────────────────────────────────────────────

def test_prime_config_dsn_contains_sim_port():
    """Primed DSN must contain :5434/ — never a prod-shaped URL."""
    result = prime_config(_SIM_DSN)
    assert ":5434/" in result["database_url"]


def test_build_watch_config_dsn_contains_sim_port():
    result = build_watch_config(_SIM_DSN)
    assert ":5434/" in result["database_url"]


def test_dsn_safety_rejects_prod_shaped_url():
    """prime_config MUST raise ValueError on any DSN missing the :5434/ sim port."""
    import pytest
    prod_dsn = "postgresql://user:pass@prod-host:5432/halcyon"
    with pytest.raises(ValueError, match=r":5434/"):
        prime_config(prod_dsn)


def test_build_watch_config_rejects_prod_shaped_url():
    """build_watch_config MUST raise ValueError on any DSN missing :5434/."""
    import pytest
    prod_dsn = "postgresql://user:pass@prod-host:5432/halcyon"
    with pytest.raises(ValueError, match=r":5434/"):
        build_watch_config(prod_dsn)


def test_prime_config_rejects_localhost_prod_port():
    """Even a local-looking DSN on the prod port (5432) is rejected."""
    import pytest
    near_miss = "postgresql://test:test@127.0.0.1:5432/halcyon"
    with pytest.raises(ValueError, match=r":5434/"):
        prime_config(near_miss)


def test_install_organic_patches_alpaca_accepts_positional_desk():
    """The _get_trading_client patch must accept positional desk arg (e.g., 'equity_long')."""
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    try:
        # Real prod signature: _get_trading_client(desk: str | None = None)
        # Common positional call site: _get_trading_client('equity_long')
        # The lambda must accept both no-arg and positional.
        assert _alpaca_mod._get_trading_client() is fake_tc
        assert _alpaca_mod._get_trading_client("equity_long") is fake_tc
        assert _alpaca_mod._get_trading_client(desk="paper") is fake_tc
    finally:
        undo()


# ── 6. Idempotency / re-install ───────────────────────────────────────────────

def test_idempotency_double_cycle():
    """install → undo → install → undo leaves all originals intact."""
    orig_tc = _alpaca_mod._get_trading_client
    orig_ohlcv = _market_data_mod.fetch_ohlcv
    orig_spy = _market_data_mod.fetch_spy_benchmark
    orig_gen = _packet_writer_mod.generate
    orig_llm_avail = _packet_writer_mod.is_llm_available
    orig_sp100 = _sp100_mod.get_sp100_universe

    for _ in range(2):
        fake_tc, fake_md, fake_llm = _make_fakes()
        undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
        undo()

    assert _alpaca_mod._get_trading_client is orig_tc
    assert _market_data_mod.fetch_ohlcv is orig_ohlcv
    assert _market_data_mod.fetch_spy_benchmark is orig_spy
    assert _packet_writer_mod.generate is orig_gen
    assert _packet_writer_mod.is_llm_available is orig_llm_avail
    assert _sp100_mod.get_sp100_universe is orig_sp100


# ── 7. No leakage on teardown (try/finally semantics) ────────────────────────

def test_no_leakage_on_early_teardown():
    """undo() restores originals even when called before any usage."""
    orig_tc = _alpaca_mod._get_trading_client
    fake_tc, fake_md, fake_llm = _make_fakes()
    undo = install_organic_patches(fake_tc, fake_md, fake_llm, _UNIVERSE)
    # Simulate early teardown (e.g., fixture cleanup before test body ran)
    try:
        pass  # test body would go here
    finally:
        undo()
    assert _alpaca_mod._get_trading_client is orig_tc
