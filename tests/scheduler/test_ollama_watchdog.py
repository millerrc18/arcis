"""Tests for the ArcisOllamaWatchdog lifecycle owner (dual-GPU separation T6).

Behavioral coverage:
- ollama exe resolution mirrors the per-user glob + OLLAMA_EXE/OLLAMA_PATH override
  and does NOT depend on %LOCALAPPDATA% expansion.
- Single-owner pre-flight terminates a faked pre-existing Ollama (PID-scoped,
  never /im name-kill, never a non-ollama PID) OR adopts a healthy GPU1 instance.
- Launch env pins CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID,
  OLLAMA_NUM_PARALLEL=2.
"""

import subprocess

import pytest

from src.scheduler import ollama_watchdog as ow


# ── ollama exe resolution ────────────────────────────────────────────────

def test_resolve_ollama_exe_honors_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_EXE", r"D:\custom\ollama.exe")
    monkeypatch.delenv("OLLAMA_PATH", raising=False)
    assert ow.resolve_ollama_exe() == r"D:\custom\ollama.exe"


def test_resolve_ollama_exe_honors_ollama_path_override(monkeypatch):
    monkeypatch.delenv("OLLAMA_EXE", raising=False)
    monkeypatch.setenv("OLLAMA_PATH", r"E:\alt\ollama.exe")
    assert ow.resolve_ollama_exe() == r"E:\alt\ollama.exe"


def test_resolve_ollama_exe_uses_per_user_glob_not_localappdata(monkeypatch):
    """Resolution must use the C:\\Users\\*\\... glob, NOT %LOCALAPPDATA%.

    Under LocalSystem %LOCALAPPDATA% points at the systemprofile, so the
    watchdog must glob the per-user install path (mirrors ollama_watchdog.ps1).
    """
    monkeypatch.delenv("OLLAMA_EXE", raising=False)
    monkeypatch.delenv("OLLAMA_PATH", raising=False)
    # No LOCALAPPDATA set — resolution must still succeed via the glob.
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(ow.shutil, "which", lambda _name: None)

    captured = {}

    def fake_glob(pattern):
        captured["pattern"] = pattern
        return [r"C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe"]

    monkeypatch.setattr(ow.glob, "glob", fake_glob)
    resolved = ow.resolve_ollama_exe()
    assert resolved == r"C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe"
    assert "Users" in captured["pattern"]
    assert "AppData" in captured["pattern"]
    assert "LOCALAPPDATA" not in captured["pattern"]


def test_resolve_ollama_exe_prefers_path_lookup(monkeypatch):
    monkeypatch.delenv("OLLAMA_EXE", raising=False)
    monkeypatch.delenv("OLLAMA_PATH", raising=False)
    monkeypatch.setattr(ow.shutil, "which", lambda _name: r"C:\onpath\ollama.exe")
    assert ow.resolve_ollama_exe() == r"C:\onpath\ollama.exe"


# ── single-owner pre-flight ──────────────────────────────────────────────

def _make_watchdog(monkeypatch, exe=r"C:\fake\ollama.exe"):
    monkeypatch.setattr(ow, "resolve_ollama_exe", lambda: exe)
    return ow.OllamaWatchdog(base_url="http://127.0.0.1:11434")


def test_preflight_terminates_preexisting_ollama_pid_scoped(monkeypatch):
    """A faked pre-existing (unhealthy) Ollama is terminated by PID, never /im."""
    wd = _make_watchdog(monkeypatch)

    # Not healthy -> cannot adopt -> must terminate the existing owner.
    monkeypatch.setattr(wd, "_is_healthy", lambda: False)
    monkeypatch.setattr(wd, "_ollama_pids", lambda: [4321])

    stop_calls = []
    monkeypatch.setattr(wd, "_graceful_stop", lambda: stop_calls.append("stop"))

    killed = []
    monkeypatch.setattr(wd, "_kill_pid", lambda pid: killed.append(pid))

    wd.preflight()

    assert stop_calls == ["stop"]
    assert killed == [4321], "must PID-terminate the residual ollama, by PID only"


def test_preflight_never_name_kills(monkeypatch):
    """The kill path must never shell out to taskkill /im (operator invariant)."""
    wd = _make_watchdog(monkeypatch)
    monkeypatch.setattr(wd, "_is_healthy", lambda: False)
    monkeypatch.setattr(wd, "_ollama_pids", lambda: [777])
    monkeypatch.setattr(wd, "_graceful_stop", lambda: None)

    runs = []

    def fake_run(cmd, *a, **k):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ow.subprocess, "run", fake_run)
    wd.preflight()

    for cmd in runs:
        joined = " ".join(str(c) for c in cmd).lower()
        assert "/im" not in joined, f"name-kill detected: {cmd}"


def test_preflight_adopts_healthy_existing_instance(monkeypatch):
    """If a healthy instance is already up, ADOPT it: no kill, no relaunch."""
    wd = _make_watchdog(monkeypatch)
    monkeypatch.setattr(wd, "_is_healthy", lambda: True)

    killed = []
    monkeypatch.setattr(wd, "_kill_pid", lambda pid: killed.append(pid))
    launched = []
    monkeypatch.setattr(wd, "_launch", lambda: launched.append(True))

    adopted = wd.ensure_owner()

    assert adopted is True
    assert killed == []
    assert launched == []


def test_ensure_owner_launches_when_none_present(monkeypatch):
    """No existing owner -> preflight is a no-op kill-wise, then launch happens."""
    wd = _make_watchdog(monkeypatch)
    # First health check (preflight) false, no pids; after launch -> healthy.
    health_seq = iter([False, True])
    monkeypatch.setattr(wd, "_is_healthy", lambda: next(health_seq))
    monkeypatch.setattr(wd, "_ollama_pids", lambda: [])
    monkeypatch.setattr(wd, "_graceful_stop", lambda: None)

    launched = []
    monkeypatch.setattr(wd, "_launch", lambda: launched.append(True))

    adopted = wd.ensure_owner()

    assert adopted is False
    assert launched == [True]


# ── launch env pinning ───────────────────────────────────────────────────

def test_launch_env_pins_gpu1(monkeypatch):
    wd = _make_watchdog(monkeypatch)

    captured = {}

    def fake_popen(cmd, *a, **k):
        captured["cmd"] = cmd
        captured["env"] = k.get("env")

        class _P:
            pid = 9999
        return _P()

    monkeypatch.setattr(ow.subprocess, "Popen", fake_popen)
    wd._launch()

    env = captured["env"]
    assert env is not None
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert env["OLLAMA_NUM_PARALLEL"] == "2"
    # serve subcommand present
    assert "serve" in [str(c) for c in captured["cmd"]]
    assert wd._launched_pid == 9999


def test_kill_pid_uses_pid_not_name(monkeypatch):
    """_kill_pid must target the PID via taskkill /pid, never /im."""
    wd = _make_watchdog(monkeypatch)
    runs = []

    def fake_run(cmd, *a, **k):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ow.subprocess, "run", fake_run)
    monkeypatch.setattr(ow.platform, "system", lambda: "Windows")
    wd._kill_pid(1234)

    assert runs, "expected a kill subprocess call"
    first = " ".join(str(c) for c in runs[0]).lower()
    assert "1234" in first
    assert "/im" not in first


def test_emit_health_signal_uses_gpu_health_ollama_ok(monkeypatch):
    """Health signal emits the NEW metric key gpu_health_ollama_ok (T8 rename)."""
    wd = _make_watchdog(monkeypatch)
    calls = []
    monkeypatch.setattr(
        ow, "upsert_daily_metric",
        lambda name, value, details=None: calls.append((name, value)),
    )
    wd._emit_health_signal(ok=True)

    assert calls, "expected a metric write"
    names = [c[0] for c in calls]
    assert "gpu_health_ollama_ok" in names
    assert "vram_handoff_inference_ok" not in names


def test_main_entrypoint_exists():
    assert callable(ow.main)
