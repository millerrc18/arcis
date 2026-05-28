"""HTTP-seam boundary-touch tests — safe_op wrapping a real HTTP-calling tool.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: @safe_op wrapping a function that makes a REAL HTTP request to a local
server. The contract is that:
  1. For mutates=False, safe_op always calls the function AND logs 'success'.
  2. For mutates=True without confirm, safe_op short-circuits BEFORE the HTTP
     call (dry-run), so the server never receives a request.
  3. When the wrapped function raises an unexpected exception (network error),
     safe_op logs 'error' and re-raises — the seam between decorator and HTTP
     call is what this test guards.

This mirrors the architecture of tests/tools/test_safe_op_integration.py (the
canonical boundary-touch positive example) but focuses on the HTTP boundary
specifically: the function under test makes a real TCP connection.

Non-vacuity proved by:
  1. Removed the `result = fn(*args, **kwargs)` call in _execute_safe_op_call
     (replaced with `result = None`): test_safe_op_read_only_calls_http_and_logs
     FAILED because the request count was 0 and the returned value was None.
  2. Removed the dry-run short-circuit in `safe_op` wrapper (deleted the
     `if mutates and not kwargs.get('confirm', False): return _build_dry_run…`
     block): test_safe_op_mutating_dry_run_skips_http FAILED because the
     server received a request (request_count == 1 instead of 0).
  3. Changed `result="error"` in the exception handler to `result="success"`:
     test_safe_op_logs_error_on_http_failure FAILED (events[0]['result'] != 'error').
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _start_counting_server() -> tuple[str, HTTPServer, dict]:
    """Start a real HTTP server that counts GET requests and returns 200 JSON."""
    state = {"request_count": 0}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["request_count"] += 1
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{port}", server, state


def _read_log(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_safe_op_read_only_calls_http_and_logs_success(tmp_path):
    """mutates=False safe_op always calls the wrapped fn (real HTTP request is made).

    Non-vacuity: removing the `result = fn(*args, **kwargs)` call in
    _execute_safe_op_call causes request_count to remain 0 and the
    returned result to be None — this test FAILS on both asserts.
    """
    import requests as _requests
    from src.tools._safety import safe_op

    log = tmp_path / "exec.log"
    base_url, server, state = _start_counting_server()

    try:
        @safe_op(name="fake_http_read", mutates=False, log_path=log)
        def fetch_status(url: str) -> dict:
            return _requests.get(url, timeout=5).json()

        result = fetch_status(url=base_url)
        assert result == {"ok": True}, f"expected ok=True from real HTTP, got {result}"
        assert state["request_count"] == 1, (
            f"expected 1 HTTP request, got {state['request_count']}"
        )
        events = _read_log(log)
        assert len(events) == 1
        assert events[0]["result"] == "success"
        assert events[0]["tool_name"] == "fake_http_read"
    finally:
        server.shutdown()


def test_safe_op_mutating_dry_run_skips_http(tmp_path):
    """mutates=True without confirm → DryRunResult, NO HTTP request sent.

    Non-vacuity: removing the dry-run short-circuit in safe_op causes the
    server to receive a request (state['request_count'] == 1), and the
    returned value is a dict not a DryRunResult — this test FAILS.
    """
    import requests as _requests
    from src.tools._safety import safe_op, DryRunResult

    log = tmp_path / "exec.log"
    base_url, server, state = _start_counting_server()

    try:
        @safe_op(name="fake_http_mutate", mutates=True, log_path=log)
        def send_command(url: str, *, confirm: bool = False) -> dict:
            return _requests.post(url, json={"cmd": "restart"}, timeout=5).json()

        result = send_command(url=base_url)
        assert isinstance(result, DryRunResult), (
            f"expected DryRunResult on dry-run, got {type(result).__name__}"
        )
        assert state["request_count"] == 0, (
            f"HTTP request must NOT be sent on dry-run; got {state['request_count']}"
        )
        events = _read_log(log)
        assert events[0]["result"] == "dry_run"
    finally:
        server.shutdown()


def test_safe_op_logs_error_on_http_failure(tmp_path):
    """When the wrapped fn raises a connection error, safe_op logs 'error' and re-raises.

    Non-vacuity: changing `result="error"` to `result="success"` in the
    exception handler of _execute_safe_op_call causes the log to show
    'success' — this test FAILS on events[0]['result'] == 'error'.
    """
    from src.tools._safety import safe_op

    log = tmp_path / "exec.log"

    @safe_op(name="fake_http_error", mutates=False, log_path=log)
    def fetch_dead_endpoint(url: str) -> dict:
        import requests as _requests
        # Connect to a port that refuses connections (port 1 is always closed)
        return _requests.get(url, timeout=2).json()

    with pytest.raises(Exception):
        fetch_dead_endpoint(url="http://127.0.0.1:1/never")

    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "error", (
        f"expected 'error' log on HTTP failure, got {events[0]['result']!r}"
    )
    assert events[0]["tool_name"] == "fake_http_error"
