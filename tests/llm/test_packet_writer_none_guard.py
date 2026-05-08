"""Regression test for #52 / packet_writer None-guard hot-fix.

`build_packet_from_features` in src/packets/template.py:177 legitimately returns
None for tickers with current_price <= 0 (#621 defensive). Callers must guard
with `if packet is None: continue` before invoking `enhance_packet_with_llm`.

Two callers were missing the guard:
- src/services/mr_scan_service.py (Mean Reversion scan)
- src/services/scan_service.py (Pullback scan)

Both crashed every scan with `'NoneType' object has no attribute
'llm_conviction_parse_failed'` at packet_writer.py:729. Watch loop's
_safe_run caught and backed off 60s, but every MR scan attempt was lost.

The hot-fix: belt-and-suspenders.
1. `enhance_packet_with_llm(None, ...)` short-circuits at the top of the
   function, logs WARNING, returns None — defends against any future
   missed caller.
2. `mr_scan_service` + `scan_service` add `if packet is None: continue` after
   `build_packet_from_features` (matching the existing pattern in
   universe_scanner.py:175 and corpus_generator.py:274 and backtester.py:204).
"""
from __future__ import annotations

import logging

import pytest

from src.llm.packet_writer import enhance_packet_with_llm


def test_enhance_packet_with_llm_returns_none_when_packet_is_none():
    """The most direct repro: passing None as packet must NOT raise AttributeError.

    Pre-fix: `'NoneType' object has no attribute 'llm_conviction_parse_failed'`
    at packet_writer.py:729 (the first attribute write) — but actually
    line 726 (`packet.ticker` for the disabled-config log) would fire first.
    Either way the function crashes any caller that didn't pre-guard.
    Post-fix: returns None cleanly.
    """
    result = enhance_packet_with_llm(None, {}, {})
    assert result is None


def test_enhance_packet_with_llm_returns_none_with_empty_config():
    """Empty config (which would normally fall through to disabled-LLM branch
    at packet_writer.py:725) must not crash when packet=None either."""
    result = enhance_packet_with_llm(None, {"current_price": 0.0}, {"llm": {}})
    assert result is None


def test_enhance_packet_with_llm_returns_none_with_llm_enabled():
    """LLM enabled in config must still short-circuit cleanly when packet=None.

    This exercises the new guard (lines 723-735) which sits BEFORE the
    `if not llm_cfg.get("enabled", False)` branch — so the return-None path
    fires regardless of llm enabled state.
    """
    result = enhance_packet_with_llm(None, {"current_price": 0.0}, {"llm": {"enabled": True}})
    assert result is None


def test_enhance_packet_with_llm_logs_warning_when_packet_is_none(caplog):
    """The None-guard must emit a WARNING with the #621 + #52 cross-references
    so operators can correlate skipped tickers with upstream feature failures."""
    with caplog.at_level(logging.WARNING, logger="src.llm.packet_writer"):
        enhance_packet_with_llm(None, {}, {})
    assert any(
        "packet=None" in r.message and "build_packet_from_features" in r.message
        for r in caplog.records
    ), f"expected None-guard warning; got records: {[r.message for r in caplog.records]}"
