"""Integration tests for src/tools/healthprobe — HealthProbe Tier 2 tool.

Covers:
  (a) ALL HEALTHY: RUNNING + fresh ISO heartbeat + connect_ex=0 + 0 errors -> overall='OK'
  (b) WATCH_LOOP STALE: ISO heartbeat 120s old (>60s threshold) + RUNNING -> 'DEGRADED'
  (c) OLLAMA PORT NOT LISTENING: connect_ex non-zero for 11434 + RUNNING -> 'DEGRADED'
  (d) DASHBOARD STOPPED: nssm_status returns STOPPED -> verdict='DOWN' + overall='DOWN'
  (e) HEARTBEAT FILE MISSING: path doesn't exist -> heartbeat_fresh=False, reason='file_missing'
  (f) HEARTBEAT GARBAGE: file contains 'not-a-timestamp' -> reason='parse_error'
  (g) --stale-seconds 600 CLI override: previously-stale 120s now passes -> verdict='OK'
  (h) CLI subprocess on forced cfg load failure: --json writes envelope + exit 1

Verify-by-mutation comments embedded in each test per spec.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_fake_cfg(
    tmp_path: Path,
    *,
    heartbeat_path: Path | None = None,
    logs_runtime: Path | None = None,
    cloud_api_range_start: int = 8000,
    ollama_port: int = 11434,
):
    """Build a minimal fake ArcisConfig for test injection."""
    from src.tools._config import load_arcis_config

    real_cfg = load_arcis_config()
    hb = heartbeat_path or (tmp_path / "watchdog.txt")
    lr = logs_runtime or (tmp_path / "logs")

    class FakePaths:
        db_canonical = real_cfg.paths.db_canonical
        watchdog_heartbeat = hb
        logs_runtime = lr
        logs_service = real_cfg.paths.logs_service
        ollama_models = real_cfg.paths.ollama_models
        worktrees = real_cfg.paths.worktrees

    class FakeCloudApi:
        range_start = cloud_api_range_start

    class FakePorts:
        pg_prod = real_cfg.ports.pg_prod
        pg_test = real_cfg.ports.pg_test
        ollama = ollama_port
        cloud_api = FakeCloudApi()
        adhoc_http = real_cfg.ports.adhoc_http
        forbidden = real_cfg.ports.forbidden

    class FakeCfg:
        paths = FakePaths()
        ports = FakePorts()
        services = real_cfg.services
        safety_windows = real_cfg.safety_windows
        pg = real_cfg.pg

    return FakeCfg()


def _build_check(log_path: Path, fake_cfg):
    """Factory: create a check function with test-isolated log_path + cfg override.

    Mirrors T2 dbquery _build_query factory pattern.
    """
    from src.tools._safety import safe_op
    from src.tools.healthprobe.core import _check_impl

    @safe_op(name="healthprobe", mutates=False, log_path=log_path)
    def _check(*, services=None, stale_seconds=None):
        return _check_impl(services=services, stale_seconds=stale_seconds, cfg=fake_cfg)

    return _check


def _now_utc():
    return datetime.now(timezone.utc)


def _iso_ts(dt: datetime) -> str:
    return dt.isoformat()


# ── (a) ALL HEALTHY ──────────────────────────────────────────────────────────


def test_all_healthy_returns_ok(tmp_path):
    """(a) ALL HEALTHY: RUNNING + fresh ISO heartbeat (now) + connect_ex=0 + 0 errors -> overall='OK'.

    Verify-by-mutation: Remove tz=UTC fallback in _check_heartbeat ->
    tz-naive timestamps wrongly fail -> test (a) fails.

    Verify-by-mutation (path): Hardcode heartbeat path as Path('data/watchdog.txt')
    -> tests (a)(b)(e)(f) fail in CI (cwd != NSSM AppDirectory).
    """
    from src.tools.processmanager.nssm import ServiceState
    import src.tools.healthprobe.checks as checks_mod

    log = tmp_path / "exec.log"

    # Write fresh ISO heartbeat
    hb = tmp_path / "watchdog.txt"
    now = _now_utc()
    hb.write_text(_iso_ts(now), encoding="utf-8")

    # Create empty log files so error-count scan doesn't fail
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    assert result["overall"] == "OK", f"Expected OK, got {result['overall']!r}: {result}"
    for svc, sh in result["services"].items():
        assert sh["verdict"] == "OK", f"Service {svc} verdict: {sh['verdict']}"
    assert "as_of_et" in result


# ── (b) WATCH_LOOP STALE ─────────────────────────────────────────────────────


def test_watchloop_stale_heartbeat_returns_degraded(tmp_path):
    """(b) WATCH_LOOP STALE: ISO heartbeat 120s old (>60s threshold) + RUNNING -> 'DEGRADED'.

    Verify-by-mutation: Remove worst-of overall aggregation (return 'OK' always)
    -> test (b) overall check fails.
    """
    from src.tools.processmanager.nssm import ServiceState
    import src.tools.healthprobe.checks as checks_mod

    log = tmp_path / "exec.log"

    # Write stale ISO heartbeat (120s old, threshold is 60s)
    hb = tmp_path / "watchdog.txt"
    stale_time = _now_utc() - timedelta(seconds=120)
    hb.write_text(_iso_ts(stale_time), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["verdict"] == "DEGRADED", f"Expected DEGRADED, got {wl['verdict']!r}"
    assert wl["heartbeat_fresh"] is False
    assert wl["heartbeat_reason"] is not None
    assert "age=120s>threshold=60s" in wl["heartbeat_reason"] or "120" in wl["heartbeat_reason"]
    assert result["overall"] == "DEGRADED"


# ── (c) OLLAMA PORT NOT LISTENING ─────────────────────────────────────────────


def test_ollama_port_not_listening_returns_degraded(tmp_path):
    """(c) OLLAMA PORT NOT LISTENING: connect_ex returns non-zero for 11434 + RUNNING -> 'DEGRADED'.

    Verify-by-mutation: Remove worst-of aggregation -> overall stays 'OK' and test fails.
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    hb = tmp_path / "watchdog.txt"
    hb.write_text(_iso_ts(_now_utc()), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    def fake_check_port(port, host="127.0.0.1"):
        # Only ollama port (11434) fails
        return port != 11434

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", side_effect=fake_check_port):
            result = fn()

    ollama = result["services"]["ArcisOllamaWatchdog"]
    assert ollama["verdict"] == "DEGRADED", f"Expected DEGRADED, got {ollama['verdict']!r}"
    assert ollama["port_listening"] is False
    assert result["overall"] in ("DEGRADED", "DOWN")


# ── (d) DASHBOARD STOPPED ─────────────────────────────────────────────────────


def test_dashboard_stopped_returns_down(tmp_path):
    """(d) DASHBOARD STOPPED: nssm_status returns STOPPED for ArcisDashboard -> verdict='DOWN' + overall='DOWN'.

    Verify-by-mutation: Remove worst-of overall aggregation (return 'OK' always)
    -> test (d) overall fails.
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    hb = tmp_path / "watchdog.txt"
    hb.write_text(_iso_ts(_now_utc()), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    def fake_nssm_status(service):
        if service == "ArcisDashboard":
            return ServiceState.STOPPED
        return ServiceState.RUNNING

    with patch("src.tools.healthprobe.checks.nssm_status", side_effect=fake_nssm_status):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    dash = result["services"]["ArcisDashboard"]
    assert dash["verdict"] == "DOWN", f"Expected DOWN, got {dash['verdict']!r}"
    assert result["overall"] == "DOWN", f"Expected overall DOWN, got {result['overall']!r}"


# ── (e) HEARTBEAT FILE MISSING ────────────────────────────────────────────────


def test_heartbeat_file_missing_returns_degraded(tmp_path):
    """(e) HEARTBEAT FILE MISSING: watchdog_heartbeat path doesn't exist -> heartbeat_fresh=False, reason='file_missing'.

    Verify-by-mutation: Hardcode heartbeat path as Path('data/watchdog.txt')
    -> tests (a)(b)(e)(f) fail in CI (cwd != NSSM AppDirectory).
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    # Deliberately point to non-existent heartbeat path
    hb = tmp_path / "nonexistent_watchdog.txt"
    assert not hb.exists(), "Test setup error: heartbeat file should not exist"

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["heartbeat_fresh"] is False
    assert wl["heartbeat_reason"] == "file_missing"
    assert wl["verdict"] == "DEGRADED"


# ── (f) HEARTBEAT GARBAGE ─────────────────────────────────────────────────────


def test_heartbeat_garbage_returns_parse_error(tmp_path):
    """(f) HEARTBEAT GARBAGE: file contains 'not-a-timestamp' -> reason='parse_error', verdict='DEGRADED'.

    Verify-by-mutation: Hardcode heartbeat path as Path('data/watchdog.txt')
    -> tests (a)(b)(e)(f) fail in CI.
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    hb = tmp_path / "watchdog.txt"
    hb.write_text("not-a-timestamp", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["heartbeat_fresh"] is False
    assert wl["heartbeat_reason"] == "parse_error"
    assert wl["verdict"] == "DEGRADED"


# ── (g) --stale-seconds 600 CLI override ──────────────────────────────────────


def test_stale_seconds_override_makes_previously_stale_ok(tmp_path):
    """(g) --stale-seconds 600 CLI override: previously-stale (120s) now passes -> verdict='OK'.

    The 120s-old heartbeat normally triggers DEGRADED (threshold=60s default).
    With stale_seconds=600, it's still fresh enough -> verdict='OK'.

    Verify-by-mutation: Remove stale_seconds parameter from _check_impl ->
    test (g) fails (verdict remains DEGRADED).
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    hb = tmp_path / "watchdog.txt"
    stale_time = _now_utc() - timedelta(seconds=120)
    hb.write_text(_iso_ts(stale_time), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-dashboard.log").write_text("", encoding="utf-8")
    (logs_dir / "arcis-ollama-watchdog.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn(stale_seconds=600)

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["verdict"] == "OK", (
        f"Expected OK with stale_seconds=600 for 120s-old heartbeat, got {wl['verdict']!r}. "
        "stale_seconds override must propagate to _check_heartbeat."
    )
    # Without override, threshold would be 60s -> would fail. With 600s, 120 < 600 -> OK.


# ── (h) CLI subprocess on forced cfg load failure ─────────────────────────────


def test_cli_json_cfg_load_failure_returns_error_envelope(tmp_path):
    """(h) CLI subprocess on forced cfg load failure: --json writes envelope + exit 1.

    Monkeypatches load_arcis_config to raise ArcisConfigError.
    Verify-by-mutation: Remove try/except in core.check() -> error propagates
    uncaught and test fails (exit code != 1 or non-JSON output).
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m", "src.tools.healthprobe",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **__import__("os").environ,
            # force config load failure by pointing to nonexistent file
            "ARCIS_CONFIG_PATH_OVERRIDE": str(tmp_path / "nonexistent_config.yaml"),
        },
    )

    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}. stdout={result.stdout!r}"
    try:
        envelope = json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout is not JSON: {result.stdout!r} -- {e}")

    assert "error" in envelope, f"Expected 'error' key in envelope: {envelope}"
    assert "type" in envelope["error"]
    assert "message" in envelope["error"]
    assert "tool" in envelope["error"]
