"""W21 P2-1 regression-lock: scan_service must read regime_label, not regime.

Background:
  src/services/scan_service.py:405 pre-fix read
    `feat.get("regime") or feat.get("market_regime")`
  but the enricher writes the regime label to:
    `feat["traffic_light"]["regime_label"]`  (3-label vocab)
    `feat["regime_label"]`                    (5-label vocab)
  So the Telegram-side `regime_at_entry` payload was NULL even on healthy
  enrichment runs. See docs/audits/2026-05-17-v0.36.13-training-page/
  regime_capture_followup.md for the full investigation (v0.36.13 T6
  Path B finding).
"""

import os


_SCAN_SERVICE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "services", "scan_service.py",
)


def _load_source() -> str:
    with open(_SCAN_SERVICE_PATH, encoding="utf-8") as f:
        return f.read()


def test_scan_service_reads_traffic_light_regime_label():
    """regime_at_entry must come from feat['traffic_light']['regime_label']."""
    source = _load_source()
    # Locate the regime_at_entry assignment line
    idx = source.find("regime_at_entry=")
    assert idx > 0, "regime_at_entry= assignment not found in scan_service.py"
    window = source[idx:idx + 400]
    assert "traffic_light" in window, (
        "scan_service.py regime_at_entry must read feat['traffic_light']"
    )
    assert "regime_label" in window, (
        "scan_service.py regime_at_entry must read regime_label key (not 'regime')"
    )


def test_scan_service_does_not_read_nonexistent_regime_key():
    """Pre-fix pattern `feat.get('regime') or feat.get('market_regime')`
    must not remain — those keys don't exist in the enricher output."""
    source = _load_source()
    idx = source.find("regime_at_entry=")
    window = source[idx:idx + 400]
    # The pre-fix exact pattern must not appear
    bad_pattern = 'feat.get("regime") or feat.get("market_regime")'
    assert bad_pattern not in window, (
        f"Pre-fix pattern still present in regime_at_entry assignment: {bad_pattern}\n"
        f"Window: {window[:200]}"
    )
