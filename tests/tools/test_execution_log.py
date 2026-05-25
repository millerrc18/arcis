"""Tests for src.tools._execution_log — JSON-lines tool-call audit log.

Verifies: event shape, secret sanitization, ISO 8601 + ET offset, rotation,
file creation. Per #104 boundary-touch discipline: tests assert on the
ACTUAL file content (not mocks of file writes), so a future regression in
the JSON shape or sanitizer is caught immediately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── Event shape + write ─────────────────────────────────────────────


def test_write_event_creates_log_file_with_one_jsonline(tmp_path):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"

    write_event(
        log_path=log,
        tool_name="test_tool",
        params={"foo": "bar"},
        result="success",
        duration_ms=12,
    )

    assert log.exists()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["tool_name"] == "test_tool"
    assert event["params"] == {"foo": "bar"}
    assert event["result"] == "success"
    assert event["duration_ms"] == 12


def test_write_event_appends_subsequent_events(tmp_path):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(log_path=log, tool_name="a", params={}, result="success", duration_ms=1)
    write_event(log_path=log, tool_name="b", params={}, result="success", duration_ms=2)
    write_event(log_path=log, tool_name="c", params={}, result="dry_run", duration_ms=3)

    lines = log.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["tool_name"] for line in lines] == ["a", "b", "c"]


def test_write_event_timestamp_is_iso8601_with_et_offset(tmp_path):
    """Timestamps must be ISO 8601 with America/New_York offset (not UTC, not naive)."""
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(log_path=log, tool_name="t", params={}, result="success", duration_ms=1)

    event = json.loads(log.read_text(encoding="utf-8"))
    ts = event["timestamp"]
    # ISO 8601 format with offset: YYYY-MM-DDTHH:MM:SS(.ffffff)?[+-]HH:MM
    # ET offset is -04:00 (EDT) or -05:00 (EST), NEVER +00:00 or naive.
    assert "T" in ts, f"not ISO 8601: {ts!r}"
    assert ts.endswith(("-04:00", "-05:00")), (
        f"timestamp must use ET offset, got {ts!r}"
    )


def test_write_event_session_id_optional(tmp_path):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(log_path=log, tool_name="t", params={}, result="success", duration_ms=1, session_id="abc123")

    event = json.loads(log.read_text(encoding="utf-8"))
    assert event["session_id"] == "abc123"


def test_write_event_omits_session_id_when_not_provided(tmp_path):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(log_path=log, tool_name="t", params={}, result="success", duration_ms=1)

    event = json.loads(log.read_text(encoding="utf-8"))
    assert "session_id" not in event or event["session_id"] is None


# ── Secret sanitization ─────────────────────────────────────────────


def test_sanitize_params_redacts_dsn_password():
    """A DSN with embedded password must have the password redacted."""
    from src.tools._execution_log import sanitize_params

    dirty = {
        "dsn": "postgresql://halcyon_app:supersecret123@localhost:5433/halcyon",
    }
    clean = sanitize_params(dirty)

    assert "supersecret123" not in clean["dsn"]
    assert "halcyon_app" in clean["dsn"]
    assert "localhost:5433" in clean["dsn"]
    assert "REDACTED" in clean["dsn"]


def test_sanitize_params_redacts_libpq_keyvalue_dsn_password():
    """libpq key=value form DSN must also have password=VALUE redacted.

    Audit #105 T2 fix — the URL-only _DSN_PASSWORD_RE missed the libpq
    key=value form (host=... password=... port=... user=...) that the
    operator passes via DBQuery's --dsn arg. This test pins the
    _LIBPQ_PASSWORD_RE redaction so future regressions are caught immediately.

    Verify-by-mutation: removing _LIBPQ_PASSWORD_RE from _sanitize_dsn would
    leave the password in the cleaned dict and this assertion would fail.
    """
    from src.tools._execution_log import sanitize_params

    dirty = {
        "dsn": "host=127.0.0.1 port=5434 dbname=halcyon user=test password=mysecret123",
    }
    clean = sanitize_params(dirty)

    assert "mysecret123" not in clean["dsn"], "libpq password leaked"
    assert "password=REDACTED" in clean["dsn"]
    # Other fields preserved for diagnostics
    assert "host=127.0.0.1" in clean["dsn"]
    assert "port=5434" in clean["dsn"]
    assert "user=test" in clean["dsn"]


def test_sanitize_params_redacts_known_secret_keys():
    """Common secret param names (api_key, token, password, secret) are redacted."""
    from src.tools._execution_log import sanitize_params

    dirty = {
        "api_key": "sk-abcdef",
        "ALPACA_API_SECRET": "secretvalue",
        "telegram_token": "12345:abc",
        "password": "hunter2",
        "database_url": "postgresql://u:p@h/d",
        "innocent": "shows up",
    }
    clean = sanitize_params(dirty)

    assert clean["api_key"] == "REDACTED"
    assert clean["ALPACA_API_SECRET"] == "REDACTED"
    assert clean["telegram_token"] == "REDACTED"
    assert clean["password"] == "REDACTED"
    # database_url is a DSN — partial redact (preserves host/db for diagnostics)
    assert "p" not in clean["database_url"] or "REDACTED" in clean["database_url"]
    assert clean["innocent"] == "shows up"


def test_write_event_sanitizes_params_in_log(tmp_path):
    """write_event must sanitize secrets BEFORE writing — never leak to disk."""
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(
        log_path=log,
        tool_name="t",
        params={"password": "leaky", "dsn": "postgresql://u:LEAKY@h/d"},
        result="success",
        duration_ms=1,
    )

    contents = log.read_text(encoding="utf-8")
    assert "leaky" not in contents
    assert "LEAKY" not in contents
    assert "REDACTED" in contents


# ── Rotation ────────────────────────────────────────────────────────


def test_rotate_at_10mb(tmp_path):
    """When the log reaches 10MB, the NEXT write rotates it to .1 and starts a fresh file."""
    from src.tools._execution_log import write_event, ROTATE_BYTES

    log = tmp_path / "tool-execution.log"
    # Seed the file AT the rotation threshold (size >= ROTATE_BYTES triggers rotation).
    log.write_text("x" * ROTATE_BYTES, encoding="utf-8")
    assert log.stat().st_size >= ROTATE_BYTES

    # Next event rotates BEFORE writing — seeded data preserved in .1,
    # new event starts a fresh file.
    write_event(log_path=log, tool_name="post_rotate", params={}, result="success", duration_ms=1)

    rotated = log.with_suffix(".log.1")
    assert rotated.exists(), "expected .log.1 rotation file"
    # New log is small (one event only)
    assert log.stat().st_size < 1000
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["tool_name"] == "post_rotate"


def test_no_rotate_when_under_10mb(tmp_path):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    log.write_text("small", encoding="utf-8")

    write_event(log_path=log, tool_name="t", params={}, result="success", duration_ms=1)

    rotated = log.with_suffix(".log.1")
    assert not rotated.exists()


# ── Result enum coverage ────────────────────────────────────────────


@pytest.mark.parametrize("result", [
    "success", "dry_run", "safety_window_block", "prod_guard_block", "error",
    "secret_leak_block",
])
def test_write_event_accepts_all_result_kinds(tmp_path, result):
    from src.tools._execution_log import write_event

    log = tmp_path / "tool-execution.log"
    write_event(log_path=log, tool_name="t", params={}, result=result, duration_ms=1)

    event = json.loads(log.read_text(encoding="utf-8"))
    assert event["result"] == result


def test_valid_results_frozenset_exhaustive():
    """Lock the _VALID_RESULTS frozenset against silent drift.

    Verify-by-mutation: if a future change adds a 7th result kind to
    _execution_log._VALID_RESULTS without updating this assertion, this
    test fails RED — forcing the test author to acknowledge the change.
    """
    from src.tools._execution_log import _VALID_RESULTS
    assert _VALID_RESULTS == frozenset({
        'success', 'dry_run', 'safety_window_block', 'prod_guard_block',
        'error', 'secret_leak_block',
    })
