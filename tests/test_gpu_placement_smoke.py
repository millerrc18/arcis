"""Tests for scripts/gpu_placement_smoke.py — GPU identity + placement smoke (T7).

All subprocess calls are mocked. No real nvidia-smi or ollama is invoked.

Covers:
  - PASS case: index0=3090, placement shows model VRAM on GPU1 => exit 0
  - identity-flip-must-fail: index0=3060 (3090 became index1) => nonzero exit (MAJOR-5 guard)
  - placement-fail: model VRAM shows on GPU0 => nonzero exit
"""

import importlib
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock nvidia-smi outputs
# ---------------------------------------------------------------------------

_NVIDIASMI_QUERY_GPU_PASS = (
    "0, NVIDIA GeForce RTX 3090, GPU-aaaa-1111\n"
    "1, NVIDIA GeForce RTX 3060, GPU-bbbb-2222\n"
)

_NVIDIASMI_QUERY_GPU_FLIPPED = (
    "0, NVIDIA GeForce RTX 3060, GPU-bbbb-2222\n"
    "1, NVIDIA GeForce RTX 3090, GPU-aaaa-1111\n"
)

# Compute-apps output: model process is on GPU 1 (3060) — placement PASS
_NVIDIASMI_COMPUTE_APPS_GPU1 = (
    "1, 1234, ollama, 4096 MiB\n"
)

# Compute-apps output: model process is on GPU 0 (3090) — placement FAIL
_NVIDIASMI_COMPUTE_APPS_GPU0 = (
    "0, 1234, ollama, 4096 MiB\n"
)

# Compute-apps output: no processes
_NVIDIASMI_COMPUTE_APPS_EMPTY = ""


def _make_run_result(stdout: str, returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


def _import_smoke():
    """Import scripts.gpu_placement_smoke, reloading each time for isolation."""
    import importlib
    import sys
    # Remove cached module so each test imports fresh
    for key in list(sys.modules.keys()):
        if "gpu_placement_smoke" in key:
            del sys.modules[key]

    # scripts/ is a package with __init__.py; add repo root to path if needed
    from pathlib import Path
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import scripts.gpu_placement_smoke as mod
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_module_cache():
    """Ensure each test gets a freshly imported module."""
    yield
    for key in list(sys.modules.keys()):
        if "gpu_placement_smoke" in key:
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Test: PASS case
# ---------------------------------------------------------------------------

def test_pass_case_exit_zero():
    """Index0=3090, placement on GPU1 => run() returns 0."""
    mod = _import_smoke()

    def _fake_run(args, **kwargs):
        args_str = " ".join(str(a) for a in args)
        if "--query-gpu" in args_str and "compute-apps" not in args_str:
            return _make_run_result(_NVIDIASMI_QUERY_GPU_PASS)
        if "compute-apps" in args_str or "--query-compute-apps" in args_str:
            return _make_run_result(_NVIDIASMI_COMPUTE_APPS_GPU1)
        return _make_run_result("")

    with patch("scripts.gpu_placement_smoke.subprocess.run", side_effect=_fake_run):
        with patch("scripts.gpu_placement_smoke.subprocess.Popen") as mock_popen:
            with patch("scripts.gpu_placement_smoke.time.sleep"):
                proc = MagicMock()
                proc.pid = 1234
                mock_popen.return_value = proc
                exit_code = mod.run_smoke()

    assert exit_code == 0, f"Expected exit 0 but got {exit_code}"


# ---------------------------------------------------------------------------
# Test: identity-flip-must-fail (MAJOR-5 regression lock)
# ---------------------------------------------------------------------------

def test_identity_flip_fails():
    """Index0=3060, index1=3090 (GPUs flipped) => run() returns nonzero (MAJOR-5 guard)."""
    mod = _import_smoke()

    def _fake_run(args, **kwargs):
        args_str = " ".join(str(a) for a in args)
        if "--query-gpu" in args_str and "compute-apps" not in args_str:
            return _make_run_result(_NVIDIASMI_QUERY_GPU_FLIPPED)
        if "compute-apps" in args_str or "--query-compute-apps" in args_str:
            return _make_run_result(_NVIDIASMI_COMPUTE_APPS_GPU1)
        return _make_run_result("")

    with patch("scripts.gpu_placement_smoke.subprocess.run", side_effect=_fake_run):
        with patch("scripts.gpu_placement_smoke.subprocess.Popen") as mock_popen:
            with patch("scripts.gpu_placement_smoke.time.sleep"):
                proc = MagicMock()
                proc.pid = 1234
                mock_popen.return_value = proc
                exit_code = mod.run_smoke()

    assert exit_code != 0, (
        "MAJOR-5: identity flip (3060 at index0) must cause nonzero exit, "
        f"but got exit code {exit_code}"
    )


# ---------------------------------------------------------------------------
# Test: placement-fail — model VRAM on GPU0
# ---------------------------------------------------------------------------

def test_placement_fail_on_gpu0():
    """Index0=3090 (identity OK), but model VRAM shows on GPU0 => nonzero exit."""
    mod = _import_smoke()

    def _fake_run(args, **kwargs):
        args_str = " ".join(str(a) for a in args)
        if "--query-gpu" in args_str and "compute-apps" not in args_str:
            return _make_run_result(_NVIDIASMI_QUERY_GPU_PASS)
        if "compute-apps" in args_str or "--query-compute-apps" in args_str:
            return _make_run_result(_NVIDIASMI_COMPUTE_APPS_GPU0)
        return _make_run_result("")

    with patch("scripts.gpu_placement_smoke.subprocess.run", side_effect=_fake_run):
        with patch("scripts.gpu_placement_smoke.subprocess.Popen") as mock_popen:
            with patch("scripts.gpu_placement_smoke.time.sleep"):
                proc = MagicMock()
                proc.pid = 1234
                mock_popen.return_value = proc
                exit_code = mod.run_smoke()

    assert exit_code != 0, (
        f"Placement on GPU0 must cause nonzero exit, but got {exit_code}"
    )
