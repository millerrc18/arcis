"""Integration tests for src/tools/healthprobe — HealthProbe Tier 2 tool.

Covers:
  (a) ALL HEALTHY: RUNNING + fresh ISO heartbeat + connect_ex=0 + 0 errors -> overall='OK'
  (b) WATCH_LOOP STALE: ISO heartbeat 1500s old (>900s threshold) + RUNNING -> 'DEGRADED'
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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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
    """(b) WATCH_LOOP STALE: ISO heartbeat 1500s old (>900s threshold) + RUNNING -> 'DEGRADED'.

    Updated from 120s (old 60s threshold) to 1500s (new 900s threshold) per #122.
    The WatchLoop threshold was bumped 60->900s to avoid false-positive wedge
    diagnoses during normal 14-min LLM scan cycles (feedback_wedge_vs_long_iteration).

    Verify-by-mutation: Remove worst-of overall aggregation (return 'OK' always)
    -> test (b) overall check fails.
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    # Write stale ISO heartbeat (1500s old, threshold is 900s)
    hb = tmp_path / "watchdog.txt"
    stale_time = _now_utc() - timedelta(seconds=1500)
    hb.write_text(_iso_ts(stale_time), encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["verdict"] == "DEGRADED", f"Expected DEGRADED, got {wl['verdict']!r}"
    assert wl["heartbeat_fresh"] is False
    assert wl["heartbeat_reason"] is not None
    assert "1500" in wl["heartbeat_reason"]
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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

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


# ── (i) NssmMissingError absorption per spec §3.2 ────────────────────────────


def test_check_with_nssm_missing_absorbs_to_down_verdict(tmp_path):
    """(i) _check_service_state raises NssmMissingError -> absorbed into DOWN verdict.

    Per spec §3.2: HealthProbe absorbs per-service failures and NEVER raises
    just because a service is down. Without the try/except wrapper in
    _check_service_state, NssmMissingError would propagate out of check() uncaught,
    violating the spec.

    Verify-by-mutation: Remove try/except in _check_service_state (checks.py:20-22)
    -> NssmMissingError propagates -> pytest.raises catches it -> test FAILS.
    """
    from src.tools._subprocess import NssmMissingError

    log = tmp_path / "exec.log"

    hb = tmp_path / "watchdog.txt"
    hb.write_text("alive", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    def raise_nssm_missing(service):
        raise NssmMissingError("nssm not on PATH")

    with patch("src.tools.healthprobe.checks.nssm_status", side_effect=raise_nssm_missing):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    # MUST NOT raise — per spec §3.2 contract
    assert result["overall"] == "DOWN", (
        f"Expected overall DOWN when nssm is missing, got {result['overall']!r}"
    )
    for svc, sh in result["services"].items():
        assert sh["verdict"] == "DOWN", (
            f"Service {svc}: expected verdict DOWN (state=UNKNOWN -> DOWN), got {sh['verdict']!r}"
        )


# ── (j) Heartbeat path is a directory -> not_a_file reason ───────────────────


def test_heartbeat_path_is_directory_returns_not_a_file(tmp_path):
    """(j) Heartbeat path is a directory (not a file) -> reason='not_a_file'.

    KC2 gap: prior code only checked path.exists(), which is True for directories.
    path.is_file() check distinguishes directory from missing file.

    Verify-by-mutation: Remove `if not path.is_file(): return False, 'not_a_file'`
    -> directory path.exists() is True, code proceeds to read_text/stat,
       which raises IsADirectoryError -> caught by bare except -> reason='parse_error'.
       Test fails because 'parse_error' != 'not_a_file'.
    """
    from src.tools.processmanager.nssm import ServiceState

    log = tmp_path / "exec.log"

    # Make the heartbeat path a DIRECTORY (not a file)
    hb_dir = tmp_path / "watchdog_dir"
    hb_dir.mkdir()
    assert hb_dir.is_dir()

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "arcis.log").write_text("", encoding="utf-8")
    (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
    (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

    fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb_dir, logs_runtime=logs_dir)
    fn = _build_check(log, fake_cfg)

    with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
        with patch("src.tools.healthprobe.checks._check_port", return_value=True):
            result = fn()

    wl = result["services"]["ArcisWatchLoop"]
    assert wl["heartbeat_fresh"] is False
    assert wl["heartbeat_reason"] == "not_a_file", (
        f"Expected 'not_a_file', got {wl['heartbeat_reason']!r}. "
        "If 'parse_error': path.is_file() check not added to _check_heartbeat."
    )


# ── (k) TestHeartbeatFilenameMapping ─────────────────────────────────────────


class TestHeartbeatFilenameMapping:
    """(k) Verify _HEARTBEAT_SOURCES maps services to ACTUAL NSSM-produced filenames.

    NSSM writes:
      ArcisDashboard    -> dashboard-stdout.log
      ArcisOllamaWatchdog -> ollama_watchdog.out.log

    Old wrong names were:
      arcis-dashboard.log
      arcis-ollama-watchdog.log

    Verify-by-mutation proof in test_heartbeat_filename_mapping_reverts_to_degraded_with_old_names.
    """

    def _make_logs_dir(self, tmp_path: Path, *, fresh: bool):
        """Create logs dir with CORRECT new filenames at either fresh or stale mtimes."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(exist_ok=True)
        (logs_dir / "arcis.log").write_text("", encoding="utf-8")

        if fresh:
            # Write correct new filenames with fresh content (mtime = now)
            (logs_dir / "dashboard-stdout.log").write_text("alive", encoding="utf-8")
            (logs_dir / "ollama_watchdog.out.log").write_text("alive", encoding="utf-8")
        else:
            # Write ONLY old wrong filenames (so correct names are absent -> stale)
            import time
            old_ts = 9999  # epoch seconds — unambiguously stale
            (logs_dir / "arcis-dashboard.log").write_text("old", encoding="utf-8")
            (logs_dir / "arcis-ollama-watchdog.log").write_text("old", encoding="utf-8")
            # Backdate their mtime to be clearly stale
            for name in ("arcis-dashboard.log", "arcis-ollama-watchdog.log"):
                p = logs_dir / name
                import os
                os.utime(p, (old_ts, old_ts))

        return logs_dir

    def test_correct_filenames_yield_ok_verdict(self, tmp_path):
        """(k1) CORRECT new filenames present at fresh mtime -> verdict OK for ArcisDashboard and ArcisOllamaWatchdog.

        Verify-by-mutation: change _HEARTBEAT_SOURCES to use old names ->
        dashboard-stdout.log/ollama_watchdog.out.log not found -> heartbeat_fresh=False -> DEGRADED.
        Test MUST fail when names are wrong.
        """
        from src.tools.processmanager.nssm import ServiceState

        log = tmp_path / "exec.log"
        hb = tmp_path / "watchdog.txt"
        hb.write_text(_iso_ts(_now_utc()), encoding="utf-8")

        logs_dir = self._make_logs_dir(tmp_path, fresh=True)
        fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
        fn = _build_check(log, fake_cfg)

        with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
            with patch("src.tools.healthprobe.checks._check_port", return_value=True):
                result = fn()

        dash = result["services"]["ArcisDashboard"]
        ollama = result["services"]["ArcisOllamaWatchdog"]

        assert dash["heartbeat_fresh"] is True, (
            f"ArcisDashboard heartbeat_fresh expected True, got {dash['heartbeat_fresh']!r}. "
            f"reason={dash['heartbeat_reason']!r}. "
            "NSSM writes 'dashboard-stdout.log' — _HEARTBEAT_SOURCES must reference that name."
        )
        assert dash["verdict"] == "OK", f"ArcisDashboard verdict: {dash['verdict']!r}"

        assert ollama["heartbeat_fresh"] is True, (
            f"ArcisOllamaWatchdog heartbeat_fresh expected True, got {ollama['heartbeat_fresh']!r}. "
            f"reason={ollama['heartbeat_reason']!r}. "
            "NSSM writes 'ollama_watchdog.out.log' — _HEARTBEAT_SOURCES must reference that name."
        )
        assert ollama["verdict"] == "OK", f"ArcisOllamaWatchdog verdict: {ollama['verdict']!r}"

    def test_heartbeat_filename_mapping_reverts_to_degraded_with_old_names(self, tmp_path):
        """(k2) VERIFY-BY-MUTATION proof: old filenames only -> DEGRADED for both services.

        This test creates ONLY the old wrong filenames (arcis-dashboard.log,
        arcis-ollama-watchdog.log) at stale mtimes, while the correct new filenames
        are absent. After the fix, _HEARTBEAT_SOURCES reads the new names ->
        file_missing -> heartbeat_fresh=False -> DEGRADED.

        If this test passes: the fix correctly ignores old filenames.
        If this test fails: either the code still uses old names (not fixed) or
        the new files were accidentally created (test setup error).
        """
        from src.tools.processmanager.nssm import ServiceState

        log = tmp_path / "exec.log"
        hb = tmp_path / "watchdog.txt"
        hb.write_text(_iso_ts(_now_utc()), encoding="utf-8")

        logs_dir = self._make_logs_dir(tmp_path, fresh=False)

        # Confirm: new filenames must NOT exist (test setup invariant)
        assert not (logs_dir / "dashboard-stdout.log").exists(), (
            "Test setup error: dashboard-stdout.log must not exist for mutation test"
        )
        assert not (logs_dir / "ollama_watchdog.out.log").exists(), (
            "Test setup error: ollama_watchdog.out.log must not exist for mutation test"
        )

        fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
        fn = _build_check(log, fake_cfg)

        with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
            with patch("src.tools.healthprobe.checks._check_port", return_value=True):
                result = fn()

        dash = result["services"]["ArcisDashboard"]
        ollama = result["services"]["ArcisOllamaWatchdog"]

        assert dash["heartbeat_fresh"] is False, (
            f"ArcisDashboard: expected heartbeat_fresh=False when only old filenames present, "
            f"got True. _HEARTBEAT_SOURCES is still pointing at old filename."
        )
        assert dash["verdict"] == "DEGRADED", f"ArcisDashboard should be DEGRADED: {dash['verdict']!r}"

        assert ollama["heartbeat_fresh"] is False, (
            f"ArcisOllamaWatchdog: expected heartbeat_fresh=False when only old filenames present, "
            f"got True. _HEARTBEAT_SOURCES is still pointing at old filename."
        )
        assert ollama["verdict"] == "DEGRADED", f"ArcisOllamaWatchdog should be DEGRADED: {ollama['verdict']!r}"


# ── (l) TestStaleThresholdNoiseFloor ─────────────────────────────────────────


class TestStaleThresholdNoiseFloor:
    """(l) Verify ArcisWatchLoop staleness threshold is 900s (not 60s).

    Rationale: during normal 14-minute LLM scan cycles, the old 60s threshold
    caused 2 false-positive wedge diagnoses (feedback_wedge_vs_long_iteration,
    2026-05-26). 900s gives operator and live-monitor agent room to distinguish
    "normal long iteration" from "actually wedged."

    Verify-by-mutation: temporarily revert ArcisWatchLoop: 60 in _DEFAULT_STALENESS
    -> test_840s_old_watchloop_is_ok MUST fail (840 > 60 -> DEGRADED).
    This proves the test is not vacuous (feedback_vacuous_test_pattern).
    """

    def _setup(self, tmp_path: Path, *, age_seconds: int):
        """Write a heartbeat file age_seconds old plus supporting log files."""
        hb = tmp_path / "watchdog.txt"
        stale_time = _now_utc() - timedelta(seconds=age_seconds)
        hb.write_text(_iso_ts(stale_time), encoding="utf-8")

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(exist_ok=True)
        (logs_dir / "arcis.log").write_text("", encoding="utf-8")
        (logs_dir / "dashboard-stdout.log").write_text("", encoding="utf-8")
        (logs_dir / "ollama_watchdog.out.log").write_text("", encoding="utf-8")

        return hb, logs_dir

    def test_840s_old_watchloop_is_ok(self, tmp_path):
        """(l-a) 840s-old heartbeat (14 min) is OK under the new 900s threshold.

        A normal LLM scan cycle can last ~14 minutes. With 900s threshold, a
        heartbeat that is 840s (14 min) old must be treated as fresh (RUNNING -> OK).

        Verify-by-mutation: revert ArcisWatchLoop to 60 in _DEFAULT_STALENESS
        -> 840 > 60 -> DEGRADED -> this assertion fails.
        """
        from src.tools.processmanager.nssm import ServiceState

        log = tmp_path / "exec.log"
        hb, logs_dir = self._setup(tmp_path, age_seconds=840)
        fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
        fn = _build_check(log, fake_cfg)

        with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
            with patch("src.tools.healthprobe.checks._check_port", return_value=True):
                result = fn(services=["ArcisWatchLoop"])

        wl = result["services"]["ArcisWatchLoop"]
        assert wl["verdict"] == "OK", (
            f"ArcisWatchLoop with 840s-old heartbeat should be OK under 900s threshold, "
            f"got {wl['verdict']!r}. heartbeat_reason={wl['heartbeat_reason']!r}. "
            "Verify ArcisWatchLoop: 900 in _DEFAULT_STALENESS."
        )
        assert wl["heartbeat_fresh"] is True, (
            f"heartbeat_fresh must be True for 840s-old file with 900s threshold."
        )

    def test_1500s_old_watchloop_is_degraded(self, tmp_path):
        """(l-b) 1500s-old heartbeat (25 min) is DEGRADED (1500 > 900 threshold).

        A heartbeat that is 25 minutes old is genuinely stale — the loop is wedged.
        Must yield DEGRADED regardless of threshold bump.

        Verify-by-mutation: bump threshold to 9999 in _DEFAULT_STALENESS
        -> 1500 < 9999 -> OK -> this assertion fails.
        """
        from src.tools.processmanager.nssm import ServiceState

        log = tmp_path / "exec.log"
        hb, logs_dir = self._setup(tmp_path, age_seconds=1500)
        fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
        fn = _build_check(log, fake_cfg)

        with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
            with patch("src.tools.healthprobe.checks._check_port", return_value=True):
                result = fn(services=["ArcisWatchLoop"])

        wl = result["services"]["ArcisWatchLoop"]
        assert wl["verdict"] == "DEGRADED", (
            f"ArcisWatchLoop with 1500s-old heartbeat should be DEGRADED, "
            f"got {wl['verdict']!r}."
        )
        assert wl["heartbeat_fresh"] is False
        assert "1500" in (wl["heartbeat_reason"] or ""), (
            f"Reason should mention age 1500s, got: {wl['heartbeat_reason']!r}"
        )

    def test_900s_boundary_is_ok(self, tmp_path):
        """(l-c) Exactly 900s old is at-threshold — boundary is inclusive-OK (age == threshold passes).

        _check_heartbeat uses `age_s > max_age_s` (strict greater-than),
        so age == 900 is NOT stale.
        """
        from src.tools.processmanager.nssm import ServiceState

        log = tmp_path / "exec.log"
        hb, logs_dir = self._setup(tmp_path, age_seconds=900)
        fake_cfg = _make_fake_cfg(tmp_path, heartbeat_path=hb, logs_runtime=logs_dir)
        fn = _build_check(log, fake_cfg)

        with patch("src.tools.healthprobe.checks.nssm_status", return_value=ServiceState.RUNNING):
            with patch("src.tools.healthprobe.checks._check_port", return_value=True):
                result = fn(services=["ArcisWatchLoop"])

        wl = result["services"]["ArcisWatchLoop"]
        # age_s > max_age_s -> 900 > 900 is False -> fresh=True
        assert wl["heartbeat_fresh"] is True, (
            f"Exactly 900s old should be fresh (strict >), got fresh={wl['heartbeat_fresh']!r}, "
            f"reason={wl['heartbeat_reason']!r}"
        )
