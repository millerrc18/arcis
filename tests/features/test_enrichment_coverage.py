"""Regression tests for SD#41 REVISED D3 — every scanner path must enrich features.

These are source-literal checks (we grep the scanner file for the helper's name)
rather than mocking the import graph. Simpler and more robust: if someone forgets
the call, the grep misses and the test fails fast.

Rationale documented in `src/features/enrichment.py:8-14` and
`docs/research/regime-classifier-audit.md`.
"""

import inspect

import pytest


def _module_source(module) -> str:
    """Return the on-disk source of a module."""
    return inspect.getsource(module)


def test_universe_scanner_calls_attach_post_scan_features():
    """Fail if scheduler/universe_scanner forgets to enrich features."""
    from src.scheduler import universe_scanner
    source = _module_source(universe_scanner)
    assert "attach_post_scan_features" in source, (
        "scheduler/universe_scanner.py must call attach_post_scan_features — "
        "see src/features/enrichment.py:8-14 for rationale"
    )


def test_main_scanner_calls_attach_post_scan_features():
    """Fail if services/scan_service forgets to enrich features."""
    from src.services import scan_service
    source = _module_source(scan_service)
    assert "attach_post_scan_features" in source, (
        "services/scan_service.py must call attach_post_scan_features — "
        "see src/features/enrichment.py:8-14 for rationale"
    )


def test_mr_scanner_calls_attach_post_scan_features():
    """Fail if services/mr_scan_service forgets to enrich (historical bug source)."""
    try:
        from src.services import mr_scan_service
    except ImportError:
        pytest.skip("mr_scan_service not present")
    source = _module_source(mr_scan_service)
    assert "attach_post_scan_features" in source, (
        "services/mr_scan_service.py must call attach_post_scan_features — "
        "was the source of the pre-2026-04-14 NULL regime bug per "
        "src/features/enrichment.py:8-14"
    )


def test_classify_regime_never_returns_none():
    """classify_regime must always return a non-empty string (known 7-state vocabulary)."""
    from src.features.regime import classify_regime
    VALID_LABELS = {
        "BULL_LOW_VOL", "BULL_HIGH_VOL", "TRANSITION", "CORRECTION",
        "BEAR_EARLY", "BEAR_ESTABLISHED", "CRISIS",
    }

    # Empty dict — must still produce a label (default to a safe regime)
    result = classify_regime({})
    assert isinstance(result, str) and result, (
        f"classify_regime({{}}) returned {result!r}"
    )
    assert result in VALID_LABELS, (
        f"classify_regime({{}}) returned unknown label {result!r}; "
        f"valid set is {VALID_LABELS}"
    )

    # Several realistic inputs spanning the vocabulary
    scenarios = [
        # calm bull
        {"vix_proxy": 12, "spy_above_sma200": True, "spy_above_sma50": True,
         "regime_label": "calm_uptrend", "spy_drawdown_from_high": 0.01,
         "market_breadth_pct": 70},
        # volatile bull
        {"vix_proxy": 22, "spy_above_sma200": True, "spy_above_sma50": True,
         "regime_label": "volatile_uptrend", "spy_drawdown_from_high": 0.04,
         "market_breadth_pct": 55},
        # crisis
        {"vix_proxy": 45, "spy_above_sma200": False, "spy_above_sma50": False,
         "regime_label": "volatile_downtrend", "spy_drawdown_from_high": 0.25,
         "market_breadth_pct": 20},
    ]
    for data in scenarios:
        result = classify_regime(data)
        assert result in VALID_LABELS, (
            f"classify_regime({data!r}) returned unknown label {result!r}"
        )
