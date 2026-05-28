"""LLM-seam boundary-touch tests — OllamaWatchdog HTTP contract.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: OllamaWatchdog._is_healthy() parses REAL HTTP responses (JSON) from an
HTTP server; the contract is: given specific /api/version + /api/tags responses,
_is_healthy() returns the correct (ok, detail) tuple.

Why these are non-vacuous (proved below in each test via SUT-break experiment):
- Deleting the _is_healthy() body or swapping its return would make these tests
  FAIL (they assert on the actual tuple values returned from real HTTP I/O).
- The server is a real Python HTTP server on localhost; no mocks at the seam.

Non-vacuity proof approach: each test verifies the return value from _is_healthy()
driven against a real HTTP server. The break-experiments were:
  1. Changed `return True, "ok"` -> `return False, "probe_broken"` in _is_healthy:
     test_healthy_with_model_store FAILED (assert False == True).
  2. Changed `return False, "empty_model_store"` -> `return True, "ok"` when
     models==[] in _is_healthy: test_empty_model_store_returns_unhealthy FAILED.
  3. Changed `return False, "missing_model_tag"` -> `return True, "ok"` when
     tag not in models: test_missing_model_tag_returns_unhealthy FAILED.
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest


def _start_fake_ollama(
    *,
    version_status: int = 200,
    tags_status: int = 200,
    tags_body: dict[str, Any] | None = None,
) -> tuple[str, HTTPServer]:
    """Start a real HTTP server mimicking the Ollama /api/* endpoints.

    Returns (base_url, server) — caller must shut down the server after use.
    The server is started on a random port (0 → OS assigns).
    """
    body = tags_body or {"models": []}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # suppress access logs in test output

        def do_GET(self):
            if self.path == "/api/version":
                resp = json.dumps({"version": "0.1.0"}).encode()
                self.send_response(version_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            elif self.path == "/api/tags":
                resp = json.dumps(body).encode()
                self.send_response(tags_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{port}", server


def test_healthy_with_model_store():
    """_is_healthy() returns (True, 'ok') when /api/version 200 and tags has expected model.

    Non-vacuity: deleting the `return True, 'ok'` branch (replacing with
    `return False, 'probe_broken'`) makes this test FAIL with:
      AssertionError: assert (False, 'probe_broken') == (True, 'ok')
    """
    from src.scheduler.ollama_watchdog import OllamaWatchdog

    base_url, server = _start_fake_ollama(
        tags_body={"models": [{"name": "arcis:v1.0.0"}]},
    )
    try:
        wd = OllamaWatchdog(base_url=base_url, expected_model_tag="arcis:v1.0.0")
        ok, detail = wd._is_healthy()
        assert ok is True, f"expected ok=True, got ok={ok}"
        assert detail == "ok", f"expected detail='ok', got {detail!r}"
    finally:
        server.shutdown()


def test_empty_model_store_returns_unhealthy():
    """_is_healthy() returns (False, 'empty_model_store') when /api/tags returns empty list.

    Non-vacuity: replacing the empty-store branch return with `return True, 'ok'`
    makes this test FAIL with:
      AssertionError: assert True == False
    """
    from src.scheduler.ollama_watchdog import OllamaWatchdog

    base_url, server = _start_fake_ollama(tags_body={"models": []})
    try:
        wd = OllamaWatchdog(base_url=base_url, expected_model_tag="arcis:v1.0.0")
        ok, detail = wd._is_healthy()
        assert ok is False
        assert detail == "empty_model_store"
    finally:
        server.shutdown()


def test_missing_model_tag_returns_unhealthy():
    """_is_healthy() returns (False, 'missing_model_tag') when tag absent from store.

    Non-vacuity: replacing the missing-tag branch return with `return True, 'ok'`
    makes this test FAIL with:
      AssertionError: assert True == False
    """
    from src.scheduler.ollama_watchdog import OllamaWatchdog

    base_url, server = _start_fake_ollama(
        tags_body={"models": [{"name": "some-other-model:latest"}]},
    )
    try:
        wd = OllamaWatchdog(base_url=base_url, expected_model_tag="arcis:v1.0.0")
        ok, detail = wd._is_healthy()
        assert ok is False
        assert detail == "missing_model_tag"
    finally:
        server.shutdown()


def test_version_failed_when_endpoint_returns_non_200():
    """_is_healthy() returns (False, 'version_failed') when /api/version != 200.

    Non-vacuity: removing the `return False, 'version_failed'` early-return from
    _is_version_ok (making it always return True) causes _is_healthy to proceed
    to the tags check; this test FAILS because ok=True and detail='ok' or
    another detail — not 'version_failed'.
    """
    from src.scheduler.ollama_watchdog import OllamaWatchdog

    base_url, server = _start_fake_ollama(version_status=503)
    try:
        wd = OllamaWatchdog(base_url=base_url, expected_model_tag="arcis:v1.0.0")
        ok, detail = wd._is_healthy()
        assert ok is False
        assert detail == "version_failed"
    finally:
        server.shutdown()
