# Purpose: Locks in the security-review fix that --json error envelopes route the
#          exception message through src.utils.secret_redact.sanitize_error, so DSN
#          passwords and similar credentials never leak via stdout (spec §4.4
#          redaction precedent, Audit #414).
# Called by: pytest
# Calls: src.tools._cli_envelope.run_cli
# Owns tables: none
# Config keys: none
# Tests: this file
"""Regression tests for src/tools/_cli_envelope.py sanitization contract.

Why this file exists despite spec §4.6 saying `_cli_envelope` is "tested
indirectly by each tool's CLI subprocess test (Tasks 2-7)":

The security review on T1 (DA-T1-SEC-01) flagged that `str(exc)` written
verbatim into the envelope's `message` field can leak DSN passwords or
other credentials if a wrapped exception text ever embeds them. Routing
through `sanitize_error` is a one-line defense-in-depth fix that aligns
with the §4.4 precedent (already used by `_execution_log.write_event`).

Without a unit test here, a future T2-T7 Developer reading spec §4.6's
"<str(e)>" verbatim wording could regress this by removing the
`sanitize_error` call. This test pins the contract so the regression
is caught immediately.
"""

from __future__ import annotations

import argparse
import json

import pytest

from src.tools._cli_envelope import run_cli


class _LeakingError(RuntimeError):
    """Synthetic exception whose str() contains a DSN-shaped password fragment.

    Mimics the realistic case where a wrapped psycopg2 error or a tool's own
    error message accidentally embeds the DSN. The leak vector is the
    error-envelope's `message` field — sanitization must redact this before
    the envelope reaches stdout.
    """


def _raise_leaking(**_kwargs):
    raise _LeakingError(
        "pg_connect failed: could not connect to host=127.0.0.1 port=5434 "
        "user=halcyon_app password=ABCD1234secret_must_not_leak dbname=halcyon"
    )


def test_envelope_message_redacts_dsn_password(capsys):
    """Envelope's `message` field MUST redact the `password=...` fragment.

    Verify-by-mutation: this test would fail if `_cli_envelope.run_cli`
    reverted `sanitize_error(exc)` back to `str(exc)` — the password substring
    would then appear verbatim in stdout JSON.
    """
    ns = argparse.Namespace()  # no kwargs needed

    with pytest.raises(SystemExit) as exc_info:
        run_cli("test_tool", _raise_leaking, ns, json_mode=True)

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    envelope = json.loads(captured.out)

    assert envelope["error"]["type"] == "_LeakingError"
    assert envelope["error"]["tool"] == "test_tool"
    # The message MUST be redacted — password value MUST NOT appear verbatim.
    assert "ABCD1234secret_must_not_leak" not in envelope["error"]["message"], (
        "DSN password leaked through envelope — sanitize_error regression"
    )
    # The redaction marker MUST appear — secret_redact substitutes the entire
    # `password=<value>` token with the literal "<REDACTED>" placeholder.
    assert "<REDACTED>" in envelope["error"]["message"]
    # Non-credential DSN fields should still be present (the leak fix is
    # surgical, not a full message wipe).
    assert "host=127.0.0.1" in envelope["error"]["message"]


def test_envelope_success_path_prints_result(capsys):
    """No exception → result printed to stdout + exit 0.

    Verify-by-mutation: removing `sys.exit(0)` would cause this test to hang
    or skip the exit assertion entirely.
    """
    def _return_payload(**_kwargs):
        return "ok-result"

    ns = argparse.Namespace()

    with pytest.raises(SystemExit) as exc_info:
        run_cli("test_tool", _return_payload, ns, json_mode=False)

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ok-result" in captured.out


def test_envelope_non_json_mode_reraises(capsys):
    """No --json AND fn raises → re-raise (Python default traceback path).

    Verify-by-mutation: changing the `raise` to `sys.exit(1)` would cause this
    test to see SystemExit instead of the original exception class.
    """
    ns = argparse.Namespace()

    with pytest.raises(_LeakingError):
        run_cli("test_tool", _raise_leaking, ns, json_mode=False)

    # Stdout should NOT have any envelope when not in json_mode.
    captured = capsys.readouterr()
    assert captured.out == ""
