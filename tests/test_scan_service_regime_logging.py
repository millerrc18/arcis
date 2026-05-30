"""Regression-lock for forensic logging of regime_at_entry NULL captures.

Background (2026-05-17): live Postgres state shows 13 of 18 OPEN shadow trades
have regime_at_entry=NULL despite being opened on the same Friday trading
session. The writer at src/shadow_trading/executor.py:1116 reads
feat["traffic_light"]["regime_label"] and silently coerces missing keys to "".
The Telegram-side notification at src/services/scan_service.py:370 reads
feat.get("regime") or feat.get("market_regime") — but the enrichment pipeline
sets feat["regime_label"] (not "regime") and feat["traffic_light"] (a nested
dict), so both keys are absent in healthy runs.

This forensic logging is the load-bearing deliverable: when the enrichment
chain fails (intermittent FRED/credit lookup, SPY data gap, traffic_light
persistence DB write race), the warning surface lets the next overnight
cycle leave a diagnostic trail in the watch log instead of silently
producing NULL rows.
"""

import logging
from src.services.scan_service import _log_regime_capture_failure


class TestRegimeCaptureLogging:
    def test_logs_warning_when_regime_missing(self, caplog):
        """Both `regime` and `market_regime` keys absent → WARNING fires."""
        feat = {"ticker": "AAPL", "price": 100.0}
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", feat)

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "regime_at_entry NULL" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            f"Expected exactly one regime-NULL warning, got {len(warnings)}: "
            f"{[r.getMessage() for r in warnings]}"
        )
        assert "AAPL" in warnings[0].getMessage(), (
            "Warning must include ticker for forensic attribution"
        )

    def test_no_warning_when_regime_present(self, caplog):
        """regime='GREEN' present → no warning."""
        feat = {"ticker": "AAPL", "regime": "GREEN"}
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", feat)

        warnings = [
            r for r in caplog.records
            if "regime_at_entry NULL" in r.getMessage()
        ]
        assert warnings == [], (
            f"No warning expected when regime is present; got: "
            f"{[r.getMessage() for r in warnings]}"
        )

    def test_no_warning_when_market_regime_present(self, caplog):
        """market_regime fallback key present → no warning."""
        feat = {"ticker": "AAPL", "market_regime": "YELLOW"}
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", feat)

        warnings = [
            r for r in caplog.records
            if "regime_at_entry NULL" in r.getMessage()
        ]
        assert warnings == [], (
            f"No warning expected when market_regime is present; got: "
            f"{[r.getMessage() for r in warnings]}"
        )

    def test_no_crash_on_empty_feat(self, caplog):
        """feat={} must not crash; exactly one warning logged."""
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", {})

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "regime_at_entry NULL" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            f"Expected exactly one regime-NULL warning on empty feat, "
            f"got {len(warnings)}"
        )

    def test_warning_includes_feat_keys_for_diagnosis(self, caplog):
        """Warning must emit sorted feat keys so the operator can see what
        the enricher *did* attach (e.g. traffic_light_multiplier without
        traffic_light)."""
        feat = {"ticker": "AAPL", "price": 100.0, "traffic_light_multiplier": 1.0}
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", feat)

        warnings = [
            r for r in caplog.records
            if "regime_at_entry NULL" in r.getMessage()
        ]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        # Sorted keys must appear so we can diagnose which enrichment step
        # short-circuited.
        for key in ("price", "ticker", "traffic_light_multiplier"):
            assert key in msg, f"Expected key {key!r} in forensic log; got: {msg}"

    def test_empty_string_regime_treated_as_missing(self, caplog):
        """The executor.py:1116 writer falls back to "" when traffic_light
        is missing. Empty string is FALSY — log the warning so the silent
        NULL-vs-"" ambiguity is visible."""
        feat = {"ticker": "AAPL", "regime": "", "market_regime": ""}
        with caplog.at_level(logging.WARNING):
            _log_regime_capture_failure("AAPL", feat)

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "regime_at_entry NULL" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            "Empty-string regime must trigger the warning (silent NULL surrogate)"
        )


class TestRegimeFollowupAuditExists:
    """Path B deliverable: the followup audit document must exist and have
    the required investigation sections so the next sprint has clear scope."""

    def test_followup_audit_exists_and_has_required_sections(self):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / "docs" / "archive" / "sprint-receipts" / "2026-05-17-v0.36.13-training-page" / "regime_capture_followup.md"
        assert path.exists(), f"Followup audit missing at {path}"
        contents = path.read_text(encoding="utf-8")
        required_sections = [
            "Hypotheses",
            "Evidence",
            "Why escalated",
            "Recommended next-sprint scope",
            "Risk if left unfixed",
        ]
        for section in required_sections:
            assert section in contents, (
                f"Followup audit missing required section: {section!r}"
            )
