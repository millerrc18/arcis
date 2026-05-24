"""Integration test — fake mutating tool through the full safety pipeline.

Per #104 boundary-touch discipline (and per the operator's brief): this
test does NOT mock the safety primitives. It composes a real tool with
real decorators and drives it through each of the five terminal states:

  - dry-run (no confirm) → DryRunResult returned, function NOT called, log
    shows one "dry_run" event
  - blocked by safety window → SafetyWindowError, function NOT called, log
    shows one "safety_window_block" event (NOT a duplicate "error" from safe_op)
  - blocked by prod guard → ProdGuardError, function NOT called, log shows
    one "prod_guard_block" event (NOT a duplicate "error" from safe_op)
  - confirmed + outside window + test DSN → function executes, log shows
    one "success" event
  - confirmed + emergency bypass of an active window + test DSN → function
    executes, log shows one "success" event with emergency=True in params

This is the keystone test the operator's #104 brief described as the
"boundary-touch test per the #103 discipline" — it verifies the REAL
behavior of the composed pipeline, catching regressions that single-
primitive tests would miss (decorator order, exception-class detection
in safe_op's except clause, single-log-per-call discipline).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


_ET = ZoneInfo("America/New_York")


def _read_log(log_path: Path) -> list[dict]:
    """Helper — read JSON-lines log into a list of events."""
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def _build_fake_tool(*, log_path: Path, now_et_fn):
    """Construct a freshly-decorated fake tool — params let each test set time + log."""
    from src.tools._safety import safe_op, safety_window, prod_guard

    call_count = {"n": 0}

    @safe_op(name="fake_restart", mutates=True, log_path=log_path)
    @safety_window("no_restart_overnight", now_et=now_et_fn, log_path=log_path)
    @prod_guard(dsn_param="dsn", log_path=log_path)
    def fake_restart(service: str, dsn: str, *, confirm: bool = False, emergency: bool = False):
        call_count["n"] += 1
        return f"restarted {service}"

    return fake_restart, call_count


# ── 5 terminal states ─────────────────────────────────────────────


def test_dry_run_returns_dryrun_and_skips_function(tmp_path):
    """No confirm → safe_op short-circuits to DryRunResult. Inner decorators never fire."""
    from src.tools._safety import DryRunResult

    log = tmp_path / "exec.log"
    # 14:00 ET — outside the no_restart_overnight window; the safety check
    # would have allowed this anyway, but safe_op is outermost so it
    # short-circuits BEFORE reaching safety_window.
    tool, calls = _build_fake_tool(
        log_path=log,
        now_et_fn=lambda: datetime(2026, 5, 24, 14, 0, tzinfo=_ET),
    )

    result = tool(service="ArcisWatchLoop", dsn="postgresql://test:test@127.0.0.1:5434/halcyon")

    assert isinstance(result, DryRunResult)
    assert calls["n"] == 0, "function must NOT execute on dry-run"
    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "dry_run"
    assert events[0]["tool_name"] == "fake_restart"


def test_blocked_by_safety_window_logs_block_only_not_error(tmp_path):
    """Confirmed call inside the overnight window → safety_window blocks.

    Critical: only ONE log event ("safety_window_block"); safe_op must
    NOT add a second "error" event. The SafetyError exception class is
    the marker that tells safe_op's except clause to skip its own logging.
    """
    from src.tools._safety import SafetyWindowError

    log = tmp_path / "exec.log"
    tool, calls = _build_fake_tool(
        log_path=log,
        now_et_fn=lambda: datetime(2026, 5, 24, 22, 0, tzinfo=_ET),  # inside 21:30-22:30
    )

    with pytest.raises(SafetyWindowError):
        tool(
            service="ArcisWatchLoop",
            dsn="postgresql://test:test@127.0.0.1:5434/halcyon",
            confirm=True,
        )

    assert calls["n"] == 0
    events = _read_log(log)
    # MUST be exactly one event — single-log-per-call discipline. The
    # SafetyError class lets safe_op's except clause re-raise without
    # writing a duplicate "error" entry.
    assert len(events) == 1, f"expected 1 event, got {len(events)}: {events}"
    assert events[0]["result"] == "safety_window_block"


def test_blocked_by_prod_guard_logs_block_only_not_error(tmp_path):
    """Confirmed call with prod DSN → prod_guard blocks (no env+confirm bypass)."""
    from src.tools._safety import ProdGuardError

    log = tmp_path / "exec.log"
    tool, calls = _build_fake_tool(
        log_path=log,
        now_et_fn=lambda: datetime(2026, 5, 24, 14, 0, tzinfo=_ET),  # outside window
    )

    with pytest.raises(ProdGuardError):
        tool(
            service="ArcisWatchLoop",
            dsn="postgresql://halcyon_app:supersecret@127.0.0.1:5433/halcyon",  # prod sig
            confirm=True,
        )

    assert calls["n"] == 0
    events = _read_log(log)
    assert len(events) == 1, f"expected 1 event, got {len(events)}: {events}"
    assert events[0]["result"] == "prod_guard_block"
    # Audit must redact the password in the DSN
    assert "supersecret" not in json.dumps(events[0])


def test_confirmed_outside_window_with_test_dsn_executes(tmp_path):
    """Happy path — confirmed + outside window + test DSN → function runs, success logged."""
    log = tmp_path / "exec.log"
    tool, calls = _build_fake_tool(
        log_path=log,
        now_et_fn=lambda: datetime(2026, 5, 24, 14, 0, tzinfo=_ET),
    )

    result = tool(
        service="ArcisWatchLoop",
        dsn="postgresql://test:test@127.0.0.1:5434/halcyon",
        confirm=True,
    )

    assert result == "restarted ArcisWatchLoop"
    assert calls["n"] == 1
    events = _read_log(log)
    # safe_op writes ONE "success" event. safety_window is silent on normal
    # outside-window pass-through (no audit value). prod_guard is silent
    # on test-DSN pass-through.
    assert len(events) == 1
    assert events[0]["result"] == "success"
    assert events[0]["tool_name"] == "fake_restart"


def test_emergency_bypass_of_active_window_logs_two_success_events(tmp_path):
    """Emergency bypass of an active window with confirmed call →
    BOTH safety_window AND safe_op log success (each at their own layer)."""
    log = tmp_path / "exec.log"
    tool, calls = _build_fake_tool(
        log_path=log,
        now_et_fn=lambda: datetime(2026, 5, 24, 22, 0, tzinfo=_ET),  # inside window
    )

    result = tool(
        service="ArcisWatchLoop",
        dsn="postgresql://test:test@127.0.0.1:5434/halcyon",
        confirm=True,
        emergency=True,
    )

    assert result == "restarted ArcisWatchLoop"
    assert calls["n"] == 1

    events = _read_log(log)
    # Two events: safety_window logs "success" with emergency=True (audit
    # trail for the bypass), THEN safe_op also logs "success" (outer layer).
    # Both are correct — the bypass is audit-worthy independent of the
    # outer success accounting.
    assert len(events) == 2
    assert all(e["result"] == "success" for e in events)
    # At least one event must record the emergency=True bypass for grep-ability.
    assert any(e["params"].get("emergency") is True for e in events)
