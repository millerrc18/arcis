"""Regression tests for the operator-only kill-switch source allowlist.

Operator policy 2026-05-08: only operator-action sources can call
`_global_halt(True, ...)`. Auto-halt paths (auditor, scheduler, scan service)
are blocked at the governor boundary even if they slip past code review.

Allowed halt sources: cli, dashboard, api, test
Forbidden halt sources: auditor, scheduler, scanner, watch, recurring,
                        anything else (raises HaltSourceForbiddenError)

Resume calls (`_global_halt(False, ...)`) are unrestricted — anyone can
clear the halt, including the auditor's recovery path if it ever fires.
"""
from __future__ import annotations

import pytest

from src.risk.governor import (
    _global_halt,
    _HALT_ALLOWED_SOURCES,
    HaltSourceForbiddenError,
)


@pytest.fixture(autouse=True)
def _redirect_halt_file(monkeypatch, tmp_path):
    """All tests use a tmp halt file so they don't disturb the live halt state."""
    from src.risk import governor as gov_module
    monkeypatch.setattr(gov_module, "_DEFAULT_HALT_FILE", str(tmp_path / "trading_halted"))


class TestSourceAllowlist:
    def test_allowlist_contains_expected_operator_sources(self):
        """The allowlist must contain exactly: cli, dashboard, api, test."""
        assert _HALT_ALLOWED_SOURCES == frozenset({"cli", "dashboard", "api", "test"})

    def test_halt_from_cli_succeeds(self):
        _global_halt(True, source="cli", reason="manual halt")
        # No exception raised → allowed

    def test_halt_from_dashboard_succeeds(self):
        _global_halt(True, source="dashboard", reason="dashboard click")

    def test_halt_from_api_succeeds(self):
        _global_halt(True, source="api", reason="POST /halt-trading")

    def test_halt_from_test_succeeds(self):
        _global_halt(True, source="test", reason="unit test")


class TestForbiddenSourcesRaise:
    def test_halt_from_auditor_raises(self):
        with pytest.raises(HaltSourceForbiddenError) as exc:
            _global_halt(True, source="auditor", reason="critical audit flag")
        assert "auditor" in str(exc.value)
        assert "operator-action-only" in str(exc.value)

    def test_halt_from_scheduler_raises(self):
        with pytest.raises(HaltSourceForbiddenError):
            _global_halt(True, source="scheduler", reason="anything")

    def test_halt_from_scanner_raises(self):
        with pytest.raises(HaltSourceForbiddenError):
            _global_halt(True, source="scanner", reason="anything")

    def test_halt_from_unknown_source_raises(self):
        with pytest.raises(HaltSourceForbiddenError):
            _global_halt(True, source="unknown", reason="default source")

    def test_halt_from_empty_source_raises(self):
        with pytest.raises(HaltSourceForbiddenError):
            _global_halt(True, source="", reason="empty source")


class TestResumeIsUnrestricted:
    """Resume calls are NEVER blocked — anyone can clear the halt.

    This is intentional: if some auto-recovery path needs to clear a halt
    (e.g., auditor regaining green status), it should be free to do so.
    The tight gate is on STARTING a halt, not ENDING one.
    """

    def test_resume_from_auditor_succeeds(self):
        # First set the halt as allowed source
        _global_halt(True, source="cli", reason="setup")
        # Then resume from forbidden source — must succeed
        _global_halt(False, source="auditor", reason="auditor cleared")

    def test_resume_from_scheduler_succeeds(self):
        _global_halt(True, source="cli", reason="setup")
        _global_halt(False, source="scheduler", reason="scheduler resume")

    def test_resume_from_unknown_source_succeeds(self):
        _global_halt(True, source="cli", reason="setup")
        _global_halt(False, source="unknown", reason="anything")

    def test_resume_with_no_active_halt_no_error(self):
        """Resume when no halt is active should be a no-op, not an error."""
        _global_halt(False, source="auditor", reason="never been halted")


class TestErrorMessageQuality:
    def test_error_includes_offending_source(self):
        with pytest.raises(HaltSourceForbiddenError) as exc:
            _global_halt(True, source="rogue_module", reason="x")
        assert "'rogue_module'" in str(exc.value) or "rogue_module" in str(exc.value)

    def test_error_lists_allowed_sources(self):
        with pytest.raises(HaltSourceForbiddenError) as exc:
            _global_halt(True, source="auditor", reason="x")
        msg = str(exc.value)
        # Lists allowed sources to help operator + future devs
        for allowed in ("cli", "dashboard", "api"):
            assert allowed in msg

    def test_error_includes_reason_for_audit_trail(self):
        with pytest.raises(HaltSourceForbiddenError) as exc:
            _global_halt(True, source="auditor", reason="catastrophic loss detected")
        assert "catastrophic loss detected" in str(exc.value)
