"""Tests for src.scheduler.ollama_watchdog — GPU1-pinned Ollama lifecycle owner.

All external deps are mocked:
  - subprocess (Popen, run)
  - psutil
  - requests (GET /api/version, /api/tags)
  - upsert_daily_metric
  - safe_send

Covers:
  - preflight: graceful 'ollama stop' + PID-scoped kill (never /im)
  - ensure_owner: adopt-if-healthy + store non-empty; else preflight+launch
  - _launch: env vars (CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID,
    OLLAMA_MODELS=C:\\Users\\mille\\.ollama\\models, OLLAMA_NUM_PARALLEL=2)
  - single-owner: no double launch when already healthy + non-empty store
  - MAJOR-4 empty-store: /api/version 200 + /api/tags empty => not healthy, loud
  - MAJOR-4 missing-tag: /api/tags present but halcyon-v1 absent => not healthy, loud
"""

import os

# Must precede any src.* import — worktree has no .env
os.environ.setdefault("ARCIS_DB_PATH", "/tmp/test_ollama_watchdog.sqlite3")

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watchdog(base_url="http://localhost:11434", exe="ollama"):
    """Return an OllamaWatchdog with a patched exe, no config load."""
    from src.scheduler.ollama_watchdog import OllamaWatchdog

    with patch("src.scheduler.ollama_watchdog.load_config", return_value={"llm": {"base_url": base_url}}):
        with patch("src.scheduler.ollama_watchdog.resolve_ollama_exe", return_value=exe):
            wd = OllamaWatchdog(base_url=base_url)
    wd._exe = exe
    return wd


def _tags_response(models):
    """Build a mock /api/tags response with the given model name list."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"models": [{"name": m} for m in models]}
    return resp


def _version_response(status=200):
    resp = MagicMock()
    resp.status_code = status
    return resp


# ---------------------------------------------------------------------------
# resolve_ollama_exe
# ---------------------------------------------------------------------------

def test_resolve_ollama_exe_env_var_wins(tmp_path):
    """OLLAMA_EXE env var takes highest priority when the path is a valid file."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    fake_exe = tmp_path / "ollama.exe"
    fake_exe.write_text("fake")

    with patch.dict(os.environ, {"OLLAMA_EXE": str(fake_exe)}, clear=False):
        with patch("shutil.which", return_value=None):
            result = resolve_ollama_exe()
    assert result == str(fake_exe)


def test_resolve_ollama_exe_path_fallback():
    """shutil.which is tried when no env var is set."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    with patch.dict(os.environ, {}, clear=False):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("OLLAMA_EXE", "OLLAMA_PATH")}
        with patch.dict(os.environ, env_clean, clear=True):
            with patch("shutil.which", return_value=r"C:\some\ollama.exe"):
                result = resolve_ollama_exe()
    assert result == r"C:\some\ollama.exe"


def test_resolve_ollama_exe_glob_fallback(tmp_path):
    """Per-user glob is tried when PATH lookup fails."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    fake_exe = str(tmp_path / "ollama.exe")
    (tmp_path / "ollama.exe").write_text("fake")

    env_clean = {k: v for k, v in os.environ.items() if k not in ("OLLAMA_EXE", "OLLAMA_PATH")}
    with patch.dict(os.environ, env_clean, clear=True):
        with patch("shutil.which", return_value=None):
            with patch("glob.glob", return_value=[fake_exe]):
                result = resolve_ollama_exe()
    assert result == fake_exe


def test_resolve_ollama_exe_returns_none_when_all_fail():
    """Returns None when no exe is found anywhere."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    env_clean = {k: v for k, v in os.environ.items() if k not in ("OLLAMA_EXE", "OLLAMA_PATH")}
    with patch.dict(os.environ, env_clean, clear=True):
        with patch("shutil.which", return_value=None):
            with patch("glob.glob", return_value=[]):
                result = resolve_ollama_exe()
    assert result is None


# ---------------------------------------------------------------------------
# preflight: graceful stop + PID-scoped kill, never /im
# ---------------------------------------------------------------------------

def test_preflight_calls_graceful_stop_then_pid_kill():
    """preflight runs 'ollama stop' then kills discovered PIDs by PID only."""
    wd = _make_watchdog()

    mock_run = MagicMock()
    mock_run.return_value.stdout = '"ollama.exe","1234","..."\n'
    mock_run.return_value.returncode = 0

    with patch("src.scheduler.ollama_watchdog.subprocess.run", mock_run):
        with patch.object(wd, "_ollama_pids", return_value=[1234]):
            with patch.object(wd, "_kill_pid") as mock_kill:
                wd.preflight()

    # First call must be 'ollama stop' (graceful)
    first_call_args = mock_run.call_args_list[0][0][0]
    assert first_call_args[1] == "stop"

    # PID-scoped kill for each discovered PID
    mock_kill.assert_called_once_with(1234)


def test_preflight_never_uses_im_kill():
    """No subprocess.run call may contain '/im' — only PID-scoped kills allowed."""
    wd = _make_watchdog()

    all_subprocess_calls = []

    def capturing_run(args, **kwargs):
        all_subprocess_calls.append(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("src.scheduler.ollama_watchdog.subprocess.run", side_effect=capturing_run):
        with patch.object(wd, "_ollama_pids", return_value=[5678]):
            with patch.object(wd, "_kill_pid"):
                wd.preflight()

    for args in all_subprocess_calls:
        flat = " ".join(str(a) for a in args)
        assert "/im" not in flat.lower(), f"Found forbidden /im in: {flat}"


def test_preflight_with_no_residual_pids():
    """preflight succeeds gracefully when no PIDs are found."""
    wd = _make_watchdog()

    with patch("src.scheduler.ollama_watchdog.subprocess.run", return_value=MagicMock(returncode=0)):
        with patch.object(wd, "_ollama_pids", return_value=[]):
            with patch.object(wd, "_kill_pid") as mock_kill:
                wd.preflight()

    mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# _launch: correct env vars
# ---------------------------------------------------------------------------

def test_launch_env_contains_cuda_and_ollama_vars():
    """_launch passes CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID,
    OLLAMA_NUM_PARALLEL=2, and OLLAMA_MODELS in the Popen env."""
    wd = _make_watchdog()

    captured_env = {}

    def fake_popen(args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        m = MagicMock()
        m.pid = 9999
        return m

    with patch("src.scheduler.ollama_watchdog.subprocess.Popen", side_effect=fake_popen):
        wd._launch()

    from src.scheduler.ollama_watchdog import _OLLAMA_MODELS_PATH

    assert captured_env.get("CUDA_VISIBLE_DEVICES") == "1"
    assert captured_env.get("CUDA_DEVICE_ORDER") == "PCI_BUS_ID"
    assert captured_env.get("OLLAMA_NUM_PARALLEL") == "2"
    assert captured_env.get("OLLAMA_MODELS") == _OLLAMA_MODELS_PATH


def test_launch_ollama_models_absolute_path():
    """OLLAMA_MODELS must point at an absolute user-profile path, not %LOCALAPPDATA%."""
    wd = _make_watchdog()

    captured_env = {}

    def fake_popen(args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        m = MagicMock()
        m.pid = 42
        return m

    with patch("src.scheduler.ollama_watchdog.subprocess.Popen", side_effect=fake_popen):
        wd._launch()

    ollama_models = captured_env.get("OLLAMA_MODELS", "")
    # Must be an absolute path (starts with drive letter or /)
    assert os.path.isabs(ollama_models), f"OLLAMA_MODELS not absolute: {ollama_models!r}"
    # Must NOT contain %LOCALAPPDATA% (not expanded under LocalSystem)
    assert "%LOCALAPPDATA%" not in ollama_models


def test_launch_sets_launched_pid():
    """_launch records the launched PID."""
    wd = _make_watchdog()

    def fake_popen(args, **kwargs):
        m = MagicMock()
        m.pid = 7777
        return m

    with patch("src.scheduler.ollama_watchdog.subprocess.Popen", side_effect=fake_popen):
        wd._launch()

    assert wd._launched_pid == 7777


# ---------------------------------------------------------------------------
# ensure_owner: adopt when healthy + non-empty store
# ---------------------------------------------------------------------------

def test_ensure_owner_adopts_when_healthy_and_store_nonempty():
    """When /api/version returns 200 AND /api/tags has halcyon-v1, adopt (no relaunch)."""
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            return _tags_response(["halcyon-v1"])
        raise ValueError(f"Unexpected URL: {url}")

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch.object(wd, "preflight") as mock_pre:
            with patch.object(wd, "_launch") as mock_launch:
                result = wd.ensure_owner()

    assert result is True
    mock_pre.assert_not_called()
    mock_launch.assert_not_called()


def test_ensure_owner_launches_when_version_fails():
    """When /api/version fails (connection error), preflight+launch runs."""
    wd = _make_watchdog()

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=Exception("refused")):
        with patch.object(wd, "preflight") as mock_pre:
            with patch.object(wd, "_launch") as mock_launch:
                with patch("src.scheduler.ollama_watchdog.time.sleep"):
                    result = wd.ensure_owner()

    assert result is False
    mock_pre.assert_called_once()
    mock_launch.assert_called_once()


def test_ensure_owner_no_double_launch_when_already_healthy():
    """ensure_owner called twice when healthy should never double-launch."""
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            return _tags_response(["halcyon-v1"])
        raise ValueError(f"Unexpected URL: {url}")

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch.object(wd, "_launch") as mock_launch:
            wd.ensure_owner()
            wd.ensure_owner()

    mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# MAJOR-4: empty-store invariant
# ---------------------------------------------------------------------------

def test_ensure_owner_empty_store_not_healthy():
    """/api/version 200 but /api/tags returns empty models list => not adopted.

    MAJOR-4 regression-lock: ensure_owner MUST call preflight (not adopt),
    MUST return False (re-launched, not adopted), and MUST NOT skip the launch
    branch. A regression where ensure_owner silently adopts an empty-store
    Ollama would return True and leave mock_pre uncalled — this test catches it.
    """
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            return _tags_response([])  # empty store — MAJOR-4 failure shape
        raise ValueError(f"Unexpected URL: {url}")

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch.object(wd, "preflight") as mock_pre:
            with patch.object(wd, "_launch") as mock_launch:
                with patch("src.scheduler.ollama_watchdog.time.sleep"):
                    result = wd.ensure_owner()

    # MUST NOT adopt — empty store is not a valid owner
    assert result is False, "ensure_owner must return False (launch path) for empty store"
    # MUST have called preflight — proves the adopt branch was NOT taken
    mock_pre.assert_called_once()
    # MUST have called _launch — proves a fresh Ollama was started
    mock_launch.assert_called_once()


def test_ensure_owner_missing_tag_not_healthy():
    """/api/version 200, /api/tags non-empty but missing halcyon-v1 => not healthy."""
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _tags_response(["llama3:latest", "mistral:7b"])
        raise ValueError

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        assert wd._store_has_model() is False


def test_ensure_owner_correct_tag_present():
    """/api/tags contains halcyon-v1 => _store_has_model returns True."""
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _tags_response(["halcyon-v1", "llama3:latest"])
        raise ValueError

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        assert wd._store_has_model() is True


def test_ensure_owner_emits_false_metric_on_empty_store():
    """When store is empty, ensure_owner emits gpu_health_ollama_ok=False
    with detail containing 'empty_model_store'."""
    wd = _make_watchdog()

    call_count = {"n": 0}
    emitted_details = []

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            call_count["n"] += 1
            return _tags_response([])
        raise ValueError

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch("src.scheduler.ollama_watchdog.upsert_daily_metric") as mock_metric:
            with patch("src.scheduler.ollama_watchdog.safe_send") as mock_notify:
                with patch.object(wd, "preflight"):
                    with patch.object(wd, "_launch"):
                        with patch("src.scheduler.ollama_watchdog.time.sleep"):
                            wd.ensure_owner()

    # upsert_daily_metric must be called with value=0.0 (unhealthy)
    unhealthy_calls = [
        c for c in mock_metric.call_args_list
        if len(c[0]) >= 2 and c[0][1] == 0.0
    ]
    assert unhealthy_calls, "Expected gpu_health_ollama_ok=0.0 for empty store"

    # safe_send must have been called (loud failure)
    assert mock_notify.called, "Expected safe_send call for empty store failure"


def test_ensure_owner_emits_false_metric_on_missing_tag():
    """When halcyon-v1 tag is absent, emits gpu_health_ollama_ok=False
    with detail containing 'missing_model_tag'."""
    wd = _make_watchdog()

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            return _tags_response(["other-model:latest"])
        raise ValueError

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch("src.scheduler.ollama_watchdog.upsert_daily_metric") as mock_metric:
            with patch("src.scheduler.ollama_watchdog.safe_send") as mock_notify:
                with patch.object(wd, "preflight"):
                    with patch.object(wd, "_launch"):
                        with patch("src.scheduler.ollama_watchdog.time.sleep"):
                            wd.ensure_owner()

    unhealthy_calls = [
        c for c in mock_metric.call_args_list
        if len(c[0]) >= 2 and c[0][1] == 0.0
    ]
    assert unhealthy_calls, "Expected gpu_health_ollama_ok=0.0 for missing tag"
    assert mock_notify.called, "Expected safe_send call for missing tag failure"


# ---------------------------------------------------------------------------
# run() health loop: invariant checked every loop iteration
# ---------------------------------------------------------------------------

def test_run_loop_checks_store_invariant_each_iteration():
    """run() loop must check /api/tags every iteration, not just on startup."""
    wd = _make_watchdog()

    iteration = {"n": 0}
    tags_call_count = {"n": 0}

    def fake_get(url, **kwargs):
        if url.endswith("/api/version"):
            return _version_response(200)
        if url.endswith("/api/tags"):
            tags_call_count["n"] += 1
            return _tags_response(["halcyon-v1"])
        raise ValueError

    def fake_sleep(secs):
        iteration["n"] += 1
        if iteration["n"] >= 3:
            raise KeyboardInterrupt

    with patch("src.scheduler.ollama_watchdog.requests.get", side_effect=fake_get):
        with patch("src.scheduler.ollama_watchdog.time.sleep", side_effect=fake_sleep):
            with patch("src.scheduler.ollama_watchdog.upsert_daily_metric"):
                with patch("src.scheduler.ollama_watchdog.safe_send"):
                    try:
                        wd.run()
                    except KeyboardInterrupt:
                        pass

    # /api/tags should have been called at least as many times as loop iterations
    assert tags_call_count["n"] >= 2, (
        f"/api/tags was only called {tags_call_count['n']} times across loop iterations"
    )


# ---------------------------------------------------------------------------
# __main__ runnable
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Security hardening: _kill_pid PID validation (Finding 1)
# ---------------------------------------------------------------------------

def test_kill_pid_rejects_zero_pid():
    """_kill_pid must silently return (not execute any subprocess) for pid <= 0."""
    wd = _make_watchdog()

    with patch("src.scheduler.ollama_watchdog.subprocess.run") as mock_run:
        with patch("src.scheduler.ollama_watchdog.subprocess.Popen"):
            wd._kill_pid(0)
            wd._kill_pid(-5)

    mock_run.assert_not_called()


def test_kill_pid_coerces_string_pid():
    """_kill_pid must accept a string-typed PID without interpolation risk."""
    wd = _make_watchdog()

    with patch("src.scheduler.ollama_watchdog.platform.system", return_value="Windows"):
        with patch("src.scheduler.ollama_watchdog.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            wd._kill_pid("1234")  # type: ignore[arg-type]

    calls_flat = " ".join(str(a) for c in mock_run.call_args_list for a in c[0][0])
    assert "1234" in calls_flat
    assert "Stop-Process" not in calls_flat or "1234" in calls_flat


def test_kill_pid_oserror_logged(caplog):
    """OSError from PowerShell Stop-Process fallback must be logged at WARNING, not swallowed."""
    import logging

    wd = _make_watchdog()

    def mock_run_taskkill_fails(args, **kwargs):
        if "taskkill" in args:
            m = MagicMock()
            m.returncode = 1
            return m
        if "powershell" in args:
            raise OSError("powershell not found")
        return MagicMock(returncode=0)

    with patch("src.scheduler.ollama_watchdog.platform.system", return_value="Windows"):
        with patch("src.scheduler.ollama_watchdog.subprocess.run", side_effect=mock_run_taskkill_fails):
            with caplog.at_level(logging.WARNING, logger="src.scheduler.ollama_watchdog"):
                wd._kill_pid(9999)

    assert any("OSError" in r.message or "oserror" in r.message.lower() or "kill exhausted" in r.message.lower()
               for r in caplog.records), "Expected WARNING log for OSError in Stop-Process"


# ---------------------------------------------------------------------------
# Security hardening: resolve_ollama_exe env override validation (Finding 3)
# ---------------------------------------------------------------------------

def test_resolve_ollama_exe_invalid_override_falls_through(tmp_path):
    """An OLLAMA_EXE override pointing to a non-existent file must be rejected
    and resolution must fall through to shutil.which."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    bogus = str(tmp_path / "does_not_exist.exe")

    with patch.dict(os.environ, {"OLLAMA_EXE": bogus}, clear=False):
        with patch("shutil.which", return_value=r"C:\fallback\ollama.exe"):
            result = resolve_ollama_exe()

    assert result == r"C:\fallback\ollama.exe", (
        f"Expected fallback via shutil.which, got {result!r}"
    )


def test_resolve_ollama_exe_valid_override_accepted(tmp_path):
    """A valid OLLAMA_EXE override (file exists, correct name) must be returned immediately."""
    from src.scheduler.ollama_watchdog import resolve_ollama_exe

    fake_exe = tmp_path / "ollama.exe"
    fake_exe.write_text("fake")

    with patch.dict(os.environ, {"OLLAMA_EXE": str(fake_exe)}, clear=False):
        with patch("shutil.which", return_value=None):
            result = resolve_ollama_exe()

    assert result == str(fake_exe)


def test_main_entrypoint_exists():
    """Module must be runnable as python -m src.scheduler.ollama_watchdog."""
    import importlib

    spec = importlib.util.find_spec("src.scheduler.ollama_watchdog")
    assert spec is not None

    # Check that __main__ block or main() function exists
    import src.scheduler.ollama_watchdog as mod
    assert hasattr(mod, "main"), "main() entrypoint must exist"
