"""Sprint 2 L — regression tests for _scan_cycle_committed reset.

Audit finding (2026-04-20): `committed $37,942` persisted across 11 scan
cycles because only `src/services/scan_service.py:37` called
`reset_scan_cycle_committed()`. The production watch path
(`universe_scanner.run_universe_scan`) and the MR path
(`mr_scan_service.run_mr_scan`) both bypassed the reset, so the
module-level counter carried between scans and silently degraded
effective_bp.

Fix: add `reset_scan_cycle_committed()` to the top of both scan-entry
functions. These tests verify the reset fires on every invocation,
regardless of whether the rest of the scan body succeeds.

Static check guards against a future refactor removing the reset line
without a matching test update.
"""
from __future__ import annotations

import pathlib

import pytest


def _monkey_reset_counter():
    """Set the module-level counter to a non-zero sentinel value."""
    from src.shadow_trading import executor
    executor._scan_cycle_committed = 12345.0


def _get_counter() -> float:
    from src.shadow_trading import executor
    return executor._scan_cycle_committed


def test_universe_scan_resets_committed_counter_on_entry(monkeypatch):
    """run_universe_scan must reset the per-cycle BP counter before doing
    any scan work. Verified by raising from the first downstream import
    and asserting the counter was reset before the raise."""
    _monkey_reset_counter()
    assert _get_counter() == 12345.0

    # Force fetch_ohlcv to raise, bypassing the rest of the scan body.
    # The reset must have happened before this raise.
    def fake_fetch(*args, **kwargs):
        raise RuntimeError("test bail")
    monkeypatch.setattr(
        "src.data_ingestion.market_data.fetch_ohlcv", fake_fetch,
    )

    from src.scheduler.universe_scanner import run_universe_scan, ScanContext
    ctx = ScanContext(config={})
    with pytest.raises(RuntimeError, match="test bail"):
        run_universe_scan(ctx)

    assert _get_counter() == 0.0, "counter must be reset before scan body runs"


def test_mr_scan_resets_committed_counter_on_entry(monkeypatch):
    """run_mr_scan must reset the per-cycle BP counter before doing any
    scan work, even when disabled in config."""
    _monkey_reset_counter()
    assert _get_counter() == 12345.0

    # Call with disabled strategy config — scan returns early but reset
    # must have fired first.
    from src.services.mr_scan_service import run_mr_scan
    result = run_mr_scan(config={"strategies": {"mean_reversion": {"enabled": False}}})

    assert result["status"] == "disabled"
    assert _get_counter() == 0.0, "reset must fire regardless of early-return"


def test_scan_service_run_scan_resets_committed_counter(monkeypatch):
    """scan_service.run_scan already resets (pre-Sprint-2); regression
    guard so the reset line is not accidentally removed."""
    _monkey_reset_counter()

    def fake_fetch(*args, **kwargs):
        raise RuntimeError("test bail")
    monkeypatch.setattr(
        "src.data_ingestion.market_data.fetch_ohlcv", fake_fetch,
    )

    from src.services.scan_service import run_scan
    with pytest.raises(RuntimeError, match="test bail"):
        run_scan(config={})

    assert _get_counter() == 0.0


def test_static_reset_call_present_in_production_scan_entries():
    """Static-source guard: each production scan-entry module must
    contain a literal `reset_scan_cycle_committed()` call. Prevents a
    future refactor from silently dropping the reset.

    Phase 5 PR-C T15: scan_service's collect phase moved to the sibling
    src/services/_scan_service_impl.py (KC-12/DA9); the reset call now lives
    in _phase_collect there. Each entry maps to the set of files that may
    legitimately host its reset wiring (the public module and/or its sibling).
    """
    entries = {
        "src/services/scan_service.py": (
            "src/services/scan_service.py",
            "src/services/_scan_service_impl.py",
        ),
        "src/scheduler/universe_scanner.py": ("src/scheduler/universe_scanner.py",),
        "src/services/mr_scan_service.py": ("src/services/mr_scan_service.py",),
    }
    checked: list[tuple[str, bool]] = []
    for entry, paths in entries.items():
        present = any(
            "reset_scan_cycle_committed()"
            in pathlib.Path(p).read_text(encoding="utf-8")
            for p in paths
        )
        checked.append((entry, present))

    missing = [p for p, ok in checked if not ok]
    assert not missing, f"scan modules missing reset call: {missing}"
