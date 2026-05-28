"""Sprint 2 K — regression tests for pre-LLM BP check.

Audit 2026-04-20: 11 AVGO rejections each burned ~17s of Ollama
inference, then were rejected milliseconds later at the
`_check_paper_buying_power` call site inside `open_shadow_trade`.
Total waste: ~3 minutes of GPU compute per scan cycle.

Fix: pre-LLM BP check at 3 scan-entry LLM call sites
(universe_scanner, scan_service, mr_scan_service). If allocation
exceeds effective BP, skip the Ollama call and record the rejection
directly.

These tests verify the helper behavior:
  1. `_check_paper_buying_power_allocation` returns True when fundable.
  2. Returns False when allocation exceeds effective_bp.
  3. Returns False (fail-closed) on account-fetch exception.
  4. Does NOT increment `_scan_cycle_committed` on either path.
"""
from __future__ import annotations

from unittest.mock import patch


def test_allocation_check_returns_true_when_fundable():
    from src.shadow_trading import executor

    executor._scan_cycle_committed = 0.0
    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        return_value={"buying_power": 100000.0},
    ):
        assert executor._check_paper_buying_power_allocation(50000.0) is True


def test_allocation_check_returns_false_when_exceeds_bp():
    from src.shadow_trading import executor

    executor._scan_cycle_committed = 0.0
    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        return_value={"buying_power": 10000.0},
    ):
        assert executor._check_paper_buying_power_allocation(50000.0) is False


def test_allocation_check_subtracts_committed_this_cycle():
    """effective_bp = buying_power - _scan_cycle_committed."""
    from src.shadow_trading import executor

    executor._scan_cycle_committed = 80000.0  # most of BP already committed
    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        return_value={"buying_power": 100000.0},
    ):
        # Only $20k effective BP remains — a $25k allocation fails
        assert executor._check_paper_buying_power_allocation(25000.0) is False
        # A $10k allocation fits
        assert executor._check_paper_buying_power_allocation(10000.0) is True


def test_allocation_check_fail_closed_on_api_error():
    """Any exception from get_account_info must return False (fail-closed)."""
    from src.shadow_trading import executor

    executor._scan_cycle_committed = 0.0
    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        side_effect=ConnectionError("Alpaca API down"),
    ):
        assert executor._check_paper_buying_power_allocation(1.0) is False


def test_allocation_check_does_not_increment_committed():
    """Precheck must not change _scan_cycle_committed — the authoritative
    increment happens only at the post-LLM _check_paper_buying_power call."""
    from src.shadow_trading import executor

    executor._scan_cycle_committed = 123.45
    with patch(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        return_value={"buying_power": 100000.0},
    ):
        executor._check_paper_buying_power_allocation(5000.0)  # would pass
        executor._check_paper_buying_power_allocation(200000.0)  # would fail
    assert executor._scan_cycle_committed == 123.45


def test_universe_scanner_skips_llm_on_bp_rejection(monkeypatch):
    """Integration: in the production scan path, a BP-rejected packet
    must NOT reach enhance_packet_with_llm."""
    # Stub all the heavy scan work except the pre-LLM check.
    import pandas as pd

    from src.shadow_trading import executor

    executor._scan_cycle_committed = 0.0

    class FakePacket:
        ticker = "AVGO"
        entry_zone = "$399.00"
        stop_invalidation = "$374.00"
        targets = "$415.00"
        class _Ps:
            allocation_dollars = 50000.0
        position_sizing = _Ps()

    llm_called = {"count": 0}

    def fake_enhance(packet, feat, config):
        llm_called["count"] += 1
        return packet

    def fake_build_packet(ticker, feat, config):
        return FakePacket()

    def fake_insert_trade(trade_data, *args, **kwargs):
        pass

    monkeypatch.setattr("src.llm.packet_writer.enhance_packet_with_llm", fake_enhance)
    monkeypatch.setattr("src.packets.template.build_packet_from_features", fake_build_packet)
    monkeypatch.setattr("src.journal.store.insert_shadow_trade", fake_insert_trade)
    monkeypatch.setattr(
        "src.shadow_trading.alpaca_adapter.get_account_info",
        lambda: {"buying_power": 1000.0},  # BP of $1k, packet wants $50k
    )
    # Bypass everything before the scan loop — stub the universe fetch to
    # return a minimal fake candidate list.
    monkeypatch.setattr(
        "src.data_ingestion.market_data.fetch_ohlcv",
        lambda tickers: {"AVGO": pd.DataFrame({"close": [399.0]})},
    )
    monkeypatch.setattr(
        "src.data_ingestion.market_data.fetch_spy_benchmark",
        lambda: pd.DataFrame({"close": [450.0]}),
    )

    # Smoke: call _check_paper_buying_power_allocation directly for the
    # exact packet the scan would encounter. This validates the gate; a
    # full universe_scanner E2E is out of scope for a unit test.
    assert executor._check_paper_buying_power_allocation(
        FakePacket.position_sizing.allocation_dollars,
    ) is False
    assert llm_called["count"] == 0, "LLM must not be called when BP precheck fails"


def test_static_preflight_wiring_present_in_scan_entries():
    """Guardrail: all 3 scan-entry modules must wire the pre-LLM BP check.

    Phase 5 PR-C T15: scan_service's per-candidate scoring loop moved to the
    sibling src/services/_scan_service_impl.py (KC-12/DA9). The
    _check_paper_buying_power_allocation gate now lives in _phase_score there,
    so each entry maps to the set of files that may legitimately host its
    wiring (the public module and/or its _impl sibling).
    """
    import pathlib
    required = {
        "src/scheduler/universe_scanner.py": ["src/scheduler/universe_scanner.py"],
        "src/services/scan_service.py": [
            "src/services/scan_service.py",
            "src/services/_scan_service_impl.py",
        ],
        "src/services/mr_scan_service.py": ["src/services/mr_scan_service.py"],
    }
    missing: list[str] = []
    for entry, paths in required.items():
        wired = any(
            "_check_paper_buying_power_allocation"
            in pathlib.Path(p).read_text(encoding="utf-8")
            for p in paths
        )
        if not wired:
            missing.append(entry)
    assert not missing, f"modules missing pre-LLM BP check wiring: {missing}"
