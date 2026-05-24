"""Tests for src.tools._safety — SafeOp, SafetyWindowGuard, ProdGuard.

Per #104 boundary-touch discipline: tests drive the REAL decorator
behavior (function called / not called, log written / not written, dry
run preview content) — not "the decorator is present" assertions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest


_ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════
# Part 1 — SafeOp + DryRunResult
# ═══════════════════════════════════════════════════════════════════


class TestDryRunResult:
    def test_is_frozen_dataclass(self):
        """DryRunResult is immutable — mutation raises."""
        from src.tools._safety import DryRunResult

        r = DryRunResult(
            tool_name="t",
            would_do="x",
            params={"k": "v"},
            timestamp="2026-05-24T10:00:00-04:00",
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            r.tool_name = "other"  # type: ignore[misc]

    def test_repr_is_operator_readable(self):
        """__repr__ produces multi-line text with tool/would_do/params clearly labeled."""
        from src.tools._safety import DryRunResult

        r = DryRunResult(
            tool_name="nssm_restart",
            would_do="restart ArcisWatchLoop",
            params={"service": "ArcisWatchLoop"},
            timestamp="2026-05-24T10:00:00-04:00",
        )
        text = repr(r)
        assert "nssm_restart" in text
        assert "restart ArcisWatchLoop" in text
        assert "ArcisWatchLoop" in text
        # Multi-line indicator (not just a one-line repr)
        assert "\n" in text

    def test_to_json_returns_dict_with_all_fields(self):
        from src.tools._safety import DryRunResult

        r = DryRunResult(
            tool_name="t",
            would_do="x",
            params={"k": "v"},
            timestamp="2026-05-24T10:00:00-04:00",
        )
        d = r.to_json()
        assert d == {
            "tool_name": "t",
            "would_do": "x",
            "params": {"k": "v"},
            "timestamp": "2026-05-24T10:00:00-04:00",
        }


class TestSafeOpDecorator:
    def test_mutating_op_without_confirm_returns_dryrun_and_does_not_call_function(self, tmp_path):
        """@safe_op(mutates=True) with confirm=False → DryRunResult, function NOT executed."""
        from src.tools._safety import safe_op, DryRunResult

        call_count = {"n": 0}

        @safe_op(name="test_mutator", mutates=True, log_path=tmp_path / "exec.log")
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            call_count["n"] += 1
            return f"restarted {service}"

        result = my_mutator(service="ArcisWatchLoop")

        assert isinstance(result, DryRunResult)
        assert call_count["n"] == 0, "function MUST NOT execute on dry-run"
        assert "ArcisWatchLoop" in result.would_do or "ArcisWatchLoop" in str(result.params)

    def test_mutating_op_with_confirm_actually_runs_function(self, tmp_path):
        from src.tools._safety import safe_op

        @safe_op(name="test_mutator", mutates=True, log_path=tmp_path / "exec.log")
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            return f"restarted {service}"

        result = my_mutator(service="ArcisWatchLoop", confirm=True)
        assert result == "restarted ArcisWatchLoop"

    def test_non_mutating_op_always_runs_function(self, tmp_path):
        """@safe_op(mutates=False) bypasses dry-run dispatch entirely."""
        from src.tools._safety import safe_op

        @safe_op(name="test_reader", mutates=False, log_path=tmp_path / "exec.log")
        def my_reader(query: str) -> str:
            return f"executed {query}"

        result = my_reader(query="SELECT 1")
        assert result == "executed SELECT 1"

    def test_describe_lambda_customizes_dryrun_description(self, tmp_path):
        from src.tools._safety import safe_op

        @safe_op(
            name="test_mutator",
            mutates=True,
            describe=lambda kwargs: f"would restart {kwargs['service']} (custom desc)",
            log_path=tmp_path / "exec.log",
        )
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            return f"restarted {service}"

        result = my_mutator(service="ArcisWatchLoop")
        assert result.would_do == "would restart ArcisWatchLoop (custom desc)"

    def test_default_description_when_no_describe_provided(self, tmp_path):
        from src.tools._safety import safe_op

        @safe_op(name="test_mutator", mutates=True, log_path=tmp_path / "exec.log")
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            return f"restarted {service}"

        result = my_mutator(service="ArcisWatchLoop")
        # Default description should mention the tool name + params
        assert "test_mutator" in result.would_do

    def test_dryrun_logs_event_with_result_dry_run(self, tmp_path):
        from src.tools._safety import safe_op

        log = tmp_path / "exec.log"

        @safe_op(name="test_mutator", mutates=True, log_path=log)
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            return "ran"

        my_mutator(service="ArcisWatchLoop")

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert len(events) == 1
        assert events[0]["result"] == "dry_run"
        assert events[0]["tool_name"] == "test_mutator"

    def test_confirmed_call_logs_event_with_result_success(self, tmp_path):
        from src.tools._safety import safe_op

        log = tmp_path / "exec.log"

        @safe_op(name="test_mutator", mutates=True, log_path=log)
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            return "ran"

        my_mutator(service="ArcisWatchLoop", confirm=True)

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert events[0]["result"] == "success"

    def test_function_raising_logs_event_with_result_error(self, tmp_path):
        from src.tools._safety import safe_op

        log = tmp_path / "exec.log"

        @safe_op(name="test_mutator", mutates=True, log_path=log)
        def my_mutator(service: str, *, confirm: bool = False) -> str:
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError, match="kaboom"):
            my_mutator(service="ArcisWatchLoop", confirm=True)

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert events[0]["result"] == "error"

    def test_logged_event_has_sanitized_params(self, tmp_path):
        """Secrets in kwargs must be sanitized BEFORE the log write."""
        from src.tools._safety import safe_op

        log = tmp_path / "exec.log"

        @safe_op(name="test_reader", mutates=False, log_path=log)
        def my_reader(api_key: str, query: str) -> str:
            return "ok"

        my_reader(api_key="sk-leaky-secret", query="SELECT 1")

        contents = log.read_text(encoding="utf-8")
        assert "sk-leaky-secret" not in contents
        assert "REDACTED" in contents
        assert "SELECT 1" in contents

    def test_duration_ms_logged(self, tmp_path):
        from src.tools._safety import safe_op

        log = tmp_path / "exec.log"

        @safe_op(name="test_reader", mutates=False, log_path=log)
        def my_reader() -> str:
            return "ok"

        my_reader()

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert "duration_ms" in events[0]
        assert events[0]["duration_ms"] >= 0


# ═══════════════════════════════════════════════════════════════════
# Part 2 — SafetyWindowGuard (pluggable clock seam, #97 pattern)
# ═══════════════════════════════════════════════════════════════════


class TestSafetyWindowGuard:
    def test_blocks_inside_window(self, tmp_path):
        """Decorator raises SafetyWindowError when current ET time is inside the declared window."""
        from src.tools._safety import safety_window, SafetyWindowError

        log = tmp_path / "exec.log"
        fake_now = datetime(2026, 5, 24, 22, 0, tzinfo=_ET)  # 22:00 ET — inside 21:30-22:30

        @safety_window(
            "no_restart_overnight",
            now_et=lambda: fake_now,
            log_path=log,
        )
        def restart_service(service: str, *, emergency: bool = False) -> str:
            return f"restarted {service}"

        with pytest.raises(SafetyWindowError) as exc_info:
            restart_service(service="ArcisWatchLoop")

        assert "no_restart_overnight" in str(exc_info.value)
        # Block logged
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert events[0]["result"] == "safety_window_block"

    def test_allows_outside_window(self, tmp_path):
        from src.tools._safety import safety_window

        fake_now = datetime(2026, 5, 24, 14, 0, tzinfo=_ET)  # 14:00 ET — outside

        @safety_window(
            "no_restart_overnight",
            now_et=lambda: fake_now,
            log_path=tmp_path / "exec.log",
        )
        def restart_service(service: str, *, emergency: bool = False) -> str:
            return f"restarted {service}"

        result = restart_service(service="ArcisWatchLoop")
        assert result == "restarted ArcisWatchLoop"

    def test_emergency_bypass_logged_with_reason(self, tmp_path):
        from src.tools._safety import safety_window

        log = tmp_path / "exec.log"
        fake_now = datetime(2026, 5, 24, 22, 0, tzinfo=_ET)

        @safety_window(
            "no_restart_overnight",
            now_et=lambda: fake_now,
            log_path=log,
        )
        def restart_service(service: str, *, emergency: bool = False) -> str:
            return f"restarted {service}"

        result = restart_service(service="ArcisWatchLoop", emergency=True)
        assert result == "restarted ArcisWatchLoop"

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert events[0]["result"] == "success"
        # The emergency bypass must be recorded in the params for audit
        assert events[0]["params"].get("emergency") is True

    def test_window_boundary_inclusive_start_exclusive_end(self, tmp_path):
        """21:30:00 ET is INSIDE the window; 22:30:00 ET is OUTSIDE.

        This matches feedback_no_restart_during_overnight_window's framing:
        '21:30 ET' onward is the overnight kickoff; the window ends 'after
        the cycle completes, typically ~22:30+ ET'.
        """
        from src.tools._safety import safety_window, SafetyWindowError

        @safety_window(
            "no_restart_overnight",
            now_et=lambda: datetime(2026, 5, 24, 21, 30, tzinfo=_ET),
            log_path="/dev/null" if os.name != "nt" else "NUL",
        )
        def at_start() -> str:
            return "ran"

        @safety_window(
            "no_restart_overnight",
            now_et=lambda: datetime(2026, 5, 24, 22, 30, tzinfo=_ET),
            log_path="/dev/null" if os.name != "nt" else "NUL",
        )
        def at_end() -> str:
            return "ran"

        with pytest.raises(SafetyWindowError):
            at_start()

        # 22:30 is OUT — function runs
        assert at_end() == "ran"


# ═══════════════════════════════════════════════════════════════════
# Part 3 — ProdGuard (DSN signature check + env+confirm bypass)
# ═══════════════════════════════════════════════════════════════════


class TestProdGuard:
    def test_rejects_prod_dsn_by_default(self, tmp_path):
        from src.tools._safety import prod_guard, ProdGuardError

        @prod_guard(dsn_param="dsn", log_path=tmp_path / "exec.log")
        def my_query(dsn: str, sql: str, *, confirm: bool = False) -> str:
            return "queried"

        prod_dsn = "postgresql://halcyon_app:secret@127.0.0.1:5433/halcyon"
        with pytest.raises(ProdGuardError) as exc_info:
            my_query(dsn=prod_dsn, sql="SELECT 1")
        assert "prod" in str(exc_info.value).lower()

    def test_allows_test_dsn(self, tmp_path):
        from src.tools._safety import prod_guard

        @prod_guard(dsn_param="dsn", log_path=tmp_path / "exec.log")
        def my_query(dsn: str, sql: str, *, confirm: bool = False) -> str:
            return "queried"

        test_dsn = "postgresql://test:test@127.0.0.1:5434/halcyon"
        result = my_query(dsn=test_dsn, sql="SELECT 1")
        assert result == "queried"

    def test_env_AND_confirm_bypass(self, tmp_path, monkeypatch):
        """ARCIS_ALLOW_PROD_PG=1 ALONE is not enough; needs confirm=True too."""
        from src.tools._safety import prod_guard, ProdGuardError

        log = tmp_path / "exec.log"

        @prod_guard(dsn_param="dsn", log_path=log)
        def my_query(dsn: str, sql: str, *, confirm: bool = False) -> str:
            return "queried"

        prod_dsn = "postgresql://halcyon_app:secret@127.0.0.1:5433/halcyon"

        # Env alone (no confirm) — still blocked
        monkeypatch.setenv("ARCIS_ALLOW_PROD_PG", "1")
        with pytest.raises(ProdGuardError):
            my_query(dsn=prod_dsn, sql="SELECT 1")

        # Confirm alone (no env) — still blocked
        monkeypatch.delenv("ARCIS_ALLOW_PROD_PG", raising=False)
        with pytest.raises(ProdGuardError):
            my_query(dsn=prod_dsn, sql="SELECT 1", confirm=True)

        # Env + confirm — allowed
        monkeypatch.setenv("ARCIS_ALLOW_PROD_PG", "1")
        result = my_query(dsn=prod_dsn, sql="SELECT 1", confirm=True)
        assert result == "queried"

    def test_prod_dsn_block_logged(self, tmp_path):
        from src.tools._safety import prod_guard, ProdGuardError

        log = tmp_path / "exec.log"

        @prod_guard(dsn_param="dsn", log_path=log)
        def my_query(dsn: str, sql: str, *, confirm: bool = False) -> str:
            return "queried"

        with pytest.raises(ProdGuardError):
            my_query(dsn="postgresql://u:p@127.0.0.1:5433/halcyon", sql="SELECT 1")

        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert events[0]["result"] == "prod_guard_block"
        # DSN password should be redacted in the audit event
        assert "p" not in events[0]["params"]["dsn"].split("@")[0].split(":")[-1] or \
               "REDACTED" in events[0]["params"]["dsn"]
