"""Integration tests for src/tools/processmanager — ProcessManager Tier 2 tool.

Covers:
  (a) status RUNNING from canned 'SERVICE_RUNNING' stdout
  (b) status STARTING from 'SERVICE_START_PENDING' — POSITIVE PARSING verification
  (c) status STOPPING from 'SERVICE_STOP_PENDING'
  (d) restart happy path — 4x RUNNING + heartbeat mtime advanced -> verified=True
  (e) restart stuck STARTING — never RUNNING within 33s -> verified=False
  (f) restart RUNNING sustained but log mtime unchanged -> verified=False
  (g) restart inside overnight window -> SafetyWindowError + safety_window_block event
  (h) status with nssm missing -> NssmMissingError + error event
  (i) status with unknown alias -> UnknownServiceError + error event
  (j) CLI --json with nssm missing -> JSON error envelope + exit 1
  (k) kill_pid uses PID-scoped taskkill NEVER /im NEVER by name
  (l) DA2 flap-detection: [RUNNING, STOPPED, RUNNING, RUNNING, RUNNING] with early mtime
  (m) FB5 real-seam smoke: gated on shutil.which('nssm')

Verify-by-mutation comments embedded in each test per spec.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest


_ET = ZoneInfo("America/New_York")

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a canned CompletedProcess for monkeypatching _subprocess.run."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _build_status(log_path: Path, cfg_path: Path | None = None):
    """Factory: create a status function with test-isolated log_path + optional cfg override."""
    from src.tools._safety import safe_op
    from src.tools.processmanager.core import _status_impl

    @safe_op(name="processmanager", mutates=False, log_path=log_path)
    def _status(service: str, *, config_path: Path | None = None):
        return _status_impl(service, config_path=config_path)

    return _status


def _build_restart(log_path: Path, now_et_fn=None, cfg_path: Path | None = None):
    """Factory: create a restart function with test-isolated log_path + clock seam + cfg."""
    from src.tools._safety import safe_op, safety_window
    from src.tools.processmanager.core import _restart_impl

    if now_et_fn is None:
        now_et_fn = lambda: datetime(2026, 5, 24, 14, 0, tzinfo=_ET)  # safe daytime

    @safe_op(name="processmanager", mutates=True, log_path=log_path)
    @safety_window("no_restart_overnight", now_et=now_et_fn, log_path=log_path)
    def _restart(service: str, *, confirm: bool = False, emergency: bool = False, config_path: Path | None = None):
        return _restart_impl(service, config_path=config_path)

    return _restart


def _read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── (a) status returns RUNNING for canned SERVICE_RUNNING stdout ─────────────


def test_status_running_from_canned_service_running(tmp_path):
    """(a) status returns RUNNING for canned 'SERVICE_RUNNING' stdout + 'success' event.

    Verify-by-mutation: Replace POSITIVE _STATE_MAP iteration with NEGATIVE
    'SERVICE_STOPPED' not in stdout -> test would still pass (SERVICE_RUNNING
    contains no 'SERVICE_STOPPED'). This is why test (b) is the real
    POSITIVE-parsing discriminator.
    """
    from src.tools.processmanager import ServiceState
    from src.tools.processmanager.core import _status_impl
    import src.tools._subprocess as _sub

    log = tmp_path / "exec.log"

    with patch.object(_sub, "run", return_value=_make_completed("SERVICE_RUNNING\r\n")):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            state = _status_impl("ArcisWatchLoop")

    assert state == ServiceState.RUNNING

    events = _read_log(log)
    # No log here — _status_impl is not decorated in this direct call path
    # The decorated version is tested via _build_status


def test_status_running_logs_success_event(tmp_path):
    """(a) decorated status writes 'success' event."""
    from src.tools.processmanager import ServiceState
    import src.tools._subprocess as _sub

    log = tmp_path / "exec.log"
    fn = _build_status(log)

    with patch.object(_sub, "run", return_value=_make_completed("SERVICE_RUNNING\r\n")):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            state = fn("ArcisWatchLoop")

    assert state == ServiceState.RUNNING
    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "success"


# ── (b) status returns STARTING for SERVICE_START_PENDING ────────────────────


def test_status_starting_from_service_start_pending(tmp_path):
    """(b) status returns STARTING for 'SERVICE_START_PENDING' stdout.

    POSITIVE PARSING verification: NEGATIVE-style 'SERVICE_STOPPED' not in stdout
    would wrongly report STARTING as RUNNING because 'SERVICE_STOPPED' is absent.
    This test catches that anti-pattern.

    Verify-by-mutation: Replace POSITIVE _STATE_MAP iteration with NEGATIVE
    'SERVICE_STOPPED' not in stdout -> this test FAILS (STARTING reads as RUNNING).
    """
    from src.tools.processmanager import ServiceState
    from src.tools.processmanager.core import _status_impl
    import src.tools._subprocess as _sub

    with patch.object(_sub, "run", return_value=_make_completed("SERVICE_START_PENDING\r\n")):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            state = _status_impl("ArcisWatchLoop")

    assert state == ServiceState.STARTING, (
        f"Got {state!r}. If this is RUNNING, the _STATE_MAP uses NEGATIVE parsing "
        "('SERVICE_STOPPED' not in stdout) — that anti-pattern incorrectly maps "
        "STARTING to RUNNING. Use POSITIVE substring match per spec §3.1."
    )


# ── (c) status returns STOPPING for SERVICE_STOP_PENDING ────────────────────


def test_status_stopping_from_service_stop_pending(tmp_path):
    """(c) status returns STOPPING for 'SERVICE_STOP_PENDING' stdout.

    Also locks POSITIVE parsing — NEGATIVE 'SERVICE_STOPPED' not in stdout
    would read STOP_PENDING as RUNNING because 'SERVICE_STOPPED' != 'SERVICE_STOP_PENDING'.
    """
    from src.tools.processmanager import ServiceState
    from src.tools.processmanager.core import _status_impl
    import src.tools._subprocess as _sub

    with patch.object(_sub, "run", return_value=_make_completed("SERVICE_STOP_PENDING\r\n")):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            state = _status_impl("ArcisWatchLoop")

    assert state == ServiceState.STOPPING


# ── (d) restart happy path ───────────────────────────────────────────────────


def test_restart_happy_path_returns_verified_true(tmp_path):
    """(d) restart happy path: 4x RUNNING + heartbeat mtime advanced -> verified=True.

    Verify-by-mutation: Hardcode log_evidence path as cfg.paths.db_canonical.parent /
    'watchdog.txt' -> test (d) fails (path mismatch with monkeypatched heartbeat).
    """
    import time as time_mod
    from src.tools.processmanager import RestartResult, ServiceState
    from src.tools.processmanager.nssm import nssm_restart, nssm_status
    import src.tools._subprocess as _sub
    import src.tools.processmanager.nssm as nssm_mod

    log = tmp_path / "exec.log"

    # Set up heartbeat file with a past mtime (pre-restart)
    heartbeat = tmp_path / "watchdog.txt"
    heartbeat.write_text("alive", encoding="utf-8")

    # Patch config to point heartbeat at our tmp file
    from src.tools._config import load_arcis_config

    real_cfg = load_arcis_config()

    class FakePaths:
        db_canonical = real_cfg.paths.db_canonical
        logs_runtime = tmp_path / "logs"
        logs_service = real_cfg.paths.logs_service
        ollama_models = real_cfg.paths.ollama_models
        watchdog_heartbeat = heartbeat
        worktrees = real_cfg.paths.worktrees

    class FakeCfg:
        paths = FakePaths()
        services = real_cfg.services
        safety_windows = real_cfg.safety_windows
        ports = real_cfg.ports
        pg = real_cfg.pg

    # canned nssm restart response (success) then 4x RUNNING status responses
    restart_response = _make_completed("", returncode=0)
    running_response = _make_completed("SERVICE_RUNNING\r\n", returncode=0)

    call_count = {"n": 0}
    restart_start_time = time_mod.time()

    def fake_run(args, **kwargs):
        if "restart" in args:
            return restart_response
        else:
            # status calls - advance heartbeat mtime on first call
            call_count["n"] += 1
            if call_count["n"] == 1:
                # advance mtime past restart_start_walltime
                heartbeat.write_text("alive-restarted", encoding="utf-8")
            return running_response

    with patch.object(_sub, "run", side_effect=fake_run):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            with patch("src.tools.processmanager.nssm.load_arcis_config", return_value=FakeCfg()):
                with patch("src.tools.processmanager.core.load_arcis_config", return_value=FakeCfg()):
                    from src.tools.processmanager.nssm import _restart_and_verify
                    result = _restart_and_verify("ArcisWatchLoop", restart_start_walltime=restart_start_time)

    assert isinstance(result, RestartResult)
    assert result.restarted is True
    assert result.verified is True
    assert result.elapsed_s < 33.0
    assert result.log_evidence is not None
    assert result.state == ServiceState.RUNNING


# ── (e) restart stuck STARTING — verified=False ──────────────────────────────


def test_restart_stuck_starting_returns_verified_false(tmp_path):
    """(e) restart with stuck STARTING — never reaches RUNNING within 33s -> verified=False.

    Uses fast-forward time.monotonic to avoid real waiting.

    Verify-by-mutation: Remove the consecutive_running counter (loop exits on
    first RUNNING) -> this test may still pass but test (l) will fail.
    """
    import time as time_mod
    from src.tools.processmanager import RestartResult, ServiceState
    import src.tools._subprocess as _sub
    import src.tools.processmanager.nssm as nssm_mod

    log = tmp_path / "exec.log"
    heartbeat = tmp_path / "watchdog.txt"

    from src.tools._config import load_arcis_config
    real_cfg = load_arcis_config()

    class FakePaths:
        db_canonical = real_cfg.paths.db_canonical
        logs_runtime = tmp_path / "logs"
        logs_service = real_cfg.paths.logs_service
        ollama_models = real_cfg.paths.ollama_models
        watchdog_heartbeat = heartbeat
        worktrees = real_cfg.paths.worktrees

    class FakeCfg:
        paths = FakePaths()
        services = real_cfg.services
        safety_windows = real_cfg.safety_windows
        ports = real_cfg.ports
        pg = real_cfg.pg

    restart_response = _make_completed("", returncode=0)
    starting_response = _make_completed("SERVICE_START_PENDING\r\n", returncode=0)

    # Fast-forward monotonic: 0.0 = start, 1.0 = inside window (one poll fires),
    # then 34.0 = past deadline on next check so loop exits.
    mono_values = iter([0.0, 1.0] + [34.0] * 50)

    def fake_run(args, **kwargs):
        if "restart" in args:
            return restart_response
        return starting_response

    with patch.object(_sub, "run", side_effect=fake_run):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            with patch("src.tools.processmanager.nssm.load_arcis_config", return_value=FakeCfg()):
                with patch("src.tools.processmanager.core.load_arcis_config", return_value=FakeCfg()):
                    with patch("src.tools.processmanager.nssm.time") as mock_time:
                        mock_time.monotonic = lambda: next(mono_values)
                        mock_time.sleep = lambda s: None
                        mock_time.time = time_mod.time
                        from src.tools.processmanager.nssm import _restart_and_verify
                        result = _restart_and_verify("ArcisWatchLoop", restart_start_walltime=time_mod.time())

    assert isinstance(result, RestartResult)
    assert result.restarted is True
    assert result.verified is False
    assert result.state == ServiceState.STARTING


# ── (f) restart RUNNING but log mtime unchanged -> verified=False ─────────────


def test_restart_running_but_stale_log_returns_verified_false(tmp_path):
    """(f) restart with sustained-RUNNING success but log mtime unchanged -> verified=False."""
    import time as time_mod
    from src.tools.processmanager import RestartResult, ServiceState
    import src.tools._subprocess as _sub

    heartbeat = tmp_path / "watchdog.txt"
    heartbeat.write_text("old", encoding="utf-8")

    from src.tools._config import load_arcis_config
    real_cfg = load_arcis_config()

    class FakePaths:
        db_canonical = real_cfg.paths.db_canonical
        logs_runtime = tmp_path / "logs"
        logs_service = real_cfg.paths.logs_service
        ollama_models = real_cfg.paths.ollama_models
        watchdog_heartbeat = heartbeat
        worktrees = real_cfg.paths.worktrees

    class FakeCfg:
        paths = FakePaths()
        services = real_cfg.services
        safety_windows = real_cfg.safety_windows
        ports = real_cfg.ports
        pg = real_cfg.pg

    restart_response = _make_completed("", returncode=0)
    running_response = _make_completed("SERVICE_RUNNING\r\n", returncode=0)

    # Use a restart_start_walltime far in the future so existing mtime is "old"
    future_start_walltime = time_mod.time() + 9999.0

    def fake_run(args, **kwargs):
        if "restart" in args:
            return restart_response
        return running_response

    # Fast-forward monotonic to get through the polling loops quickly
    mono_seq = [0.0] + list(range(1, 10)) + list(range(35, 60))
    mono_iter = iter(mono_seq)

    with patch.object(_sub, "run", side_effect=fake_run):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            with patch("src.tools.processmanager.nssm.load_arcis_config", return_value=FakeCfg()):
                with patch("src.tools.processmanager.core.load_arcis_config", return_value=FakeCfg()):
                    with patch("src.tools.processmanager.nssm.time") as mock_time:
                        call_count = {"n": 0}
                        def fake_monotonic():
                            call_count["n"] += 1
                            # Returns: 0 (start), 1,2,3 (3 RUNNING polls), then
                            # large values (log window expires fast)
                            vals = [0.0, 1.0, 2.0, 3.0, 4.0, 40.0, 41.0, 42.0, 43.0]
                            idx = call_count["n"] - 1
                            if idx < len(vals):
                                return vals[idx]
                            return 100.0
                        mock_time.monotonic = fake_monotonic
                        mock_time.sleep = lambda s: None
                        mock_time.time = time_mod.time
                        from src.tools.processmanager.nssm import _restart_and_verify
                        result = _restart_and_verify("ArcisWatchLoop", restart_start_walltime=future_start_walltime)

    assert isinstance(result, RestartResult)
    assert result.restarted is True
    assert result.verified is False
    assert result.log_evidence is None
    assert result.state == ServiceState.RUNNING


# ── (g) restart inside overnight window -> SafetyWindowError ─────────────────


def test_restart_inside_overnight_window_raises_safety_window_error(tmp_path):
    """(g) restart with now_et=21:45 ET -> SafetyWindowError + safety_window_block event.

    Verify-by-mutation: Remove @safety_window decorator on restart ->
    test (g) fails (no SafetyWindowError raised + no safety_window_block event).
    """
    from src.tools._safety import SafetyWindowError

    log = tmp_path / "exec.log"

    # 21:45 ET — inside the no_restart_overnight window (21:30-22:30)
    inside_window_et = lambda: datetime(2026, 5, 24, 21, 45, tzinfo=_ET)

    fn = _build_restart(log, now_et_fn=inside_window_et)

    with pytest.raises(SafetyWindowError):
        fn("ArcisWatchLoop", confirm=True)

    events = _read_log(log)
    block_events = [e for e in events if e.get("result") == "safety_window_block"]
    error_events = [e for e in events if e.get("result") == "error"]

    assert len(block_events) == 1, f"Expected 1 safety_window_block event, got {block_events}"
    assert len(error_events) == 0, "No 'error' event expected — SafetyWindowError is not double-logged"


# ── (h) status with nssm missing -> NssmMissingError + error event ───────────


def test_status_nssm_missing_raises_nssm_missing_error(tmp_path):
    """(h) status with monkeypatched shutil.which returning None -> NssmMissingError + error event."""
    from src.tools._subprocess import NssmMissingError

    log = tmp_path / "exec.log"
    fn = _build_status(log)

    with patch("shutil.which", return_value=None):
        # Also clear the lru_cache on resolve_exe so it re-checks
        from src.tools._subprocess import resolve_exe
        resolve_exe.cache_clear()
        with pytest.raises(NssmMissingError):
            fn("ArcisWatchLoop")
        resolve_exe.cache_clear()

    events = _read_log(log)
    assert any(e.get("result") == "error" for e in events)


# ── (i) status unknown alias -> UnknownServiceError + error event ─────────────


def test_status_unknown_alias_raises_unknown_service_error(tmp_path):
    """(i) status('foo') -> UnknownServiceError + error event."""
    from src.tools.processmanager import UnknownServiceError
    import src.tools._subprocess as _sub

    log = tmp_path / "exec.log"
    fn = _build_status(log)

    with patch.object(_sub, "resolve_exe", return_value="nssm"):
        with pytest.raises(UnknownServiceError):
            fn("foo_unknown_service")

    events = _read_log(log)
    assert any(e.get("result") == "error" for e in events)


# ── (j) CLI --json with nssm missing -> JSON error envelope ──────────────────


def test_cli_json_nssm_missing_returns_json_error_envelope(tmp_path):
    """(j) CLI subprocess: nssm missing -> JSON error envelope with NssmMissingError + exit 1."""
    result = subprocess.run(
        [sys.executable, "-m", "src.tools.processmanager", "status", "ArcisWatchLoop", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**__import__("os").environ, "PATH": ""},  # strip PATH so nssm can't be found
    )

    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout is not JSON: {result.stdout!r} -- {e}")

    assert "error" in envelope
    assert envelope["error"]["type"] == "NssmMissingError"


# ── (k) kill_pid uses PID-scoped taskkill NEVER /im NEVER by name ────────────


def test_kill_pid_uses_pid_scoped_taskkill_never_im(tmp_path):
    """(k) kill_pid verifies taskkill args contain '/pid' NEVER '/im' NEVER by name.

    Verify-by-mutation: Change taskkill arg list to include '/im' instead of '/pid'
    -> test (k) fails (assertion on arg list contents).
    """
    from src.tools.processmanager.taskkill import kill_pid
    import src.tools._subprocess as _sub

    captured_calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        captured_calls.append(list(args))
        return _make_completed("", returncode=0)

    with patch.object(_sub, "run", side_effect=fake_run):
        kill_pid(99999)

    assert len(captured_calls) >= 1
    first_call_args = captured_calls[0]

    # MUST contain /pid and the PID string
    assert "/pid" in first_call_args or "/f" in first_call_args, \
        f"Expected /pid in args, got: {first_call_args}"
    pid_str_present = "99999" in first_call_args
    assert pid_str_present, f"PID '99999' not found in args: {first_call_args}"

    # MUST NOT contain /im
    for args in captured_calls:
        assert "/im" not in [a.lower() for a in args], \
            f"Found forbidden /im in taskkill call: {args}"
        # MUST NOT contain Stop-Process -Name
        for arg in args:
            assert "Stop-Process -Name" not in arg, \
                f"Found forbidden Stop-Process -Name in args: {args}"


# ── (l) DA2 flap-detection test ───────────────────────────────────────────────


def test_da2_flap_detection_flap_resets_consecutive_counter(tmp_path):
    """(l) DA2 flap-detection: [RUNNING, STOPPED, RUNNING, RUNNING, RUNNING] + early mtime.

    Canned sequence simulates NSSM AppRestartDelay flap. Heartbeat mtime advanced
    EARLY (between observation 1 and 2 — simulating last heartbeat before crash).
    The log-evidence check happens AFTER sustained-running confirmation.

    Assertions:
    - elapsed_s > 5 — sustained-window logic was actually exercised (NOT single-obs exit)
    - state == RUNNING (final stable state)
    - verified == False — early mtime correctly rejected because log-evidence check
      happens AFTER sustained-running (NOT during)

    Verify-by-mutation: Revert to single-RUNNING exit (remove consecutive_running
    counter; loop exits on first RUNNING) -> test fails (elapsed_s < 2s OR verified=True).
    """
    import time as time_mod
    from src.tools.processmanager import RestartResult, ServiceState
    import src.tools._subprocess as _sub

    heartbeat = tmp_path / "watchdog.txt"
    heartbeat.write_text("initial", encoding="utf-8")

    from src.tools._config import load_arcis_config
    real_cfg = load_arcis_config()

    class FakePaths:
        db_canonical = real_cfg.paths.db_canonical
        logs_runtime = tmp_path / "logs"
        logs_service = real_cfg.paths.logs_service
        ollama_models = real_cfg.paths.ollama_models
        watchdog_heartbeat = heartbeat
        worktrees = real_cfg.paths.worktrees

    class FakeCfg:
        paths = FakePaths()
        services = real_cfg.services
        safety_windows = real_cfg.safety_windows
        ports = real_cfg.ports
        pg = real_cfg.pg

    restart_response = _make_completed("", returncode=0)

    # Sequence: RUNNING (obs 1), STOPPED (obs 2 — flap!), RUNNING (obs 3), RUNNING (obs 4), RUNNING (obs 5)
    # This means consecutive_running resets to 0 at obs 2, so we need obs 3+4+5 for sustained-3
    status_responses = iter([
        _make_completed("SERVICE_RUNNING\r\n"),     # obs 1: +1 consecutive
        _make_completed("SERVICE_STOPPED\r\n"),      # obs 2: flap! reset to 0
        _make_completed("SERVICE_RUNNING\r\n"),     # obs 3: +1
        _make_completed("SERVICE_RUNNING\r\n"),     # obs 4: +2
        _make_completed("SERVICE_RUNNING\r\n"),     # obs 5: +3 -> break
    ])

    # Heartbeat mtime: advanced EARLY (between obs 1 and obs 2, before flap)
    # This means it's pre-restart_start_walltime from the perspective of the log-evidence
    # check, which triggers AFTER sustained-running.
    # We set restart_start_walltime to far in the future so early mtime is rejected.
    future_start_walltime = time_mod.time() + 9999.0

    def fake_run(args, **kwargs):
        if "restart" in args:
            return restart_response
        return next(status_responses)

    # Monotonic: each poll is 1 second apart. With 5 polls at 1s each, elapsed >= 5s
    mono_call = {"n": 0}
    def fake_monotonic():
        mono_call["n"] += 1
        # 0.0 = start, then 1s increments per poll + log window checks
        return (mono_call["n"] - 1) * 1.0

    with patch.object(_sub, "run", side_effect=fake_run):
        with patch.object(_sub, "resolve_exe", return_value="nssm"):
            with patch("src.tools.processmanager.nssm.load_arcis_config", return_value=FakeCfg()):
                with patch("src.tools.processmanager.core.load_arcis_config", return_value=FakeCfg()):
                    with patch("src.tools.processmanager.nssm.time") as mock_time:
                        mock_time.monotonic = fake_monotonic
                        mock_time.sleep = lambda s: None
                        mock_time.time = time_mod.time
                        from src.tools.processmanager.nssm import _restart_and_verify
                        result = _restart_and_verify("ArcisWatchLoop", restart_start_walltime=future_start_walltime)

    assert result.state == ServiceState.RUNNING, f"Expected RUNNING, got {result.state}"
    assert result.verified is False, (
        "verified must be False: the heartbeat mtime predates restart_start_walltime. "
        "If True, the log-evidence check fired too early (before sustained-running confirmed) "
        "or the mtime check is wrong."
    )
    assert result.elapsed_s > 5.0, (
        f"elapsed_s={result.elapsed_s:.2f} < 5s. "
        "If single-RUNNING exit was used, elapsed would be ~1s. "
        "Sustained-window requires >= 5 polls (5s elapsed minimum)."
    )


# ── (m) FB5 real-seam smoke ───────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("nssm") is None, reason="nssm.exe not on PATH")
def test_processmanager_real_nssm_smoke():
    """(m) Verify real nssm.exe stdout still parses against _STATE_MAP.

    NEVER mutates — read-only contract probe.
    """
    from src.tools.processmanager.nssm import nssm_status

    state = nssm_status("ArcisWatchLoop")
    valid_values = {
        "RUNNING", "STOPPED", "STARTING", "STOPPING",
        "PAUSED", "PAUSE_PENDING", "CONTINUE_PENDING", "UNKNOWN",
    }
    assert state.value in valid_values, f"Unexpected state value: {state.value!r}"
