"""GPU identity + placement smoke test — gates the dual-GPU live cutover (T7).

Operator-runnable (python scripts/gpu_placement_smoke.py); exits nonzero on ANY failure.
DO NOT run this script in development — it invokes nvidia-smi and Ollama,
which require real GPU hardware. Use the mocked unit tests (tests/test_gpu_placement_smoke.py)
for CI.

Two-phase gate:
1. MAJOR-5 identity check: index0 must be the RTX 3090 (24 GB), index1 must be the
   RTX 3060. If a BIOS/driver reseat flipped the indices, fail immediately — running
   training on the 12 GB card would OOM.
2. Placement check: launch Ollama under CUDA_VISIBLE_DEVICES=1 (GPU1 pin), load the
   model, query nvidia-smi compute-apps, and assert the model's VRAM is on GPU1 (the
   3060), NOT GPU0.

Exit codes:
    0 — all checks passed
    1 — at least one check failed (details printed to stderr)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path when invoked directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants — configurable via environment overrides
# ---------------------------------------------------------------------------

_OLLAMA_EXE = os.environ.get("OLLAMA_EXE") or "ollama"
_OLLAMA_MODELS_PATH = os.environ.get(
    "OLLAMA_MODELS", r"C:\Users\mille\.ollama\models"
)
_MODEL_TAG = os.environ.get("SMOKE_MODEL_TAG", "halcyon-v1")
_GPU1_DEVICE = "1"
_STARTUP_SLEEP_SEC = int(os.environ.get("SMOKE_STARTUP_SLEEP", "8"))


# ---------------------------------------------------------------------------
# Phase 1 — identity check
# ---------------------------------------------------------------------------

def _query_gpu_identities() -> list[dict]:
    """Run nvidia-smi --query-gpu and return a list of {index, name, uuid} dicts."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi --query-gpu failed (rc={result.returncode}): {result.stdout}{result.stderr}"
        )
    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        gpus.append({"index": int(parts[0]), "name": parts[1], "uuid": parts[2]})
    return gpus


def check_identity(gpus: list[dict]) -> tuple[bool, str]:
    """Assert index0=3090 and index1=3060.

    Returns (ok, message).
    """
    if not gpus:
        return False, "nvidia-smi returned no GPU entries"

    by_index = {g["index"]: g for g in gpus}

    gpu0 = by_index.get(0)
    gpu1 = by_index.get(1)

    if gpu0 is None:
        return False, "No GPU at index 0 reported by nvidia-smi"
    if gpu1 is None:
        return False, "No GPU at index 1 reported by nvidia-smi"

    if "3090" not in gpu0["name"]:
        return False, (
            f"MAJOR-5 IDENTITY FLIP: index0 is '{gpu0['name']}' (expected RTX 3090). "
            f"Index1 is '{gpu1['name']}'. Training would land on the wrong card. "
            "Resolve BIOS/driver index assignment before proceeding."
        )

    if "3060" not in gpu1["name"]:
        return False, (
            f"MAJOR-5: index1 is '{gpu1['name']}' (expected RTX 3060). "
            "Unexpected GPU configuration."
        )

    return True, (
        f"Identity OK: GPU0={gpu0['name']}, GPU1={gpu1['name']}"
    )


# ---------------------------------------------------------------------------
# Phase 2 — placement check
# ---------------------------------------------------------------------------

def _launch_ollama_gpu1() -> subprocess.Popen:
    """Launch `ollama serve` pinned to GPU1 via CUDA_VISIBLE_DEVICES=1."""
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = _GPU1_DEVICE
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["OLLAMA_NUM_PARALLEL"] = "2"
    env["OLLAMA_MODELS"] = _OLLAMA_MODELS_PATH

    kwargs: dict = {"env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen([_OLLAMA_EXE, "serve"], **kwargs)
    return proc


def _query_compute_apps() -> list[dict]:
    """Run nvidia-smi --query-compute-apps and return list of {gpu_index, pid, name, mem_mb}."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi --query-compute-apps failed (rc={result.returncode}): "
            f"{result.stdout}{result.stderr}"
        )
    apps = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        apps.append({
            "gpu_index_or_uuid": parts[0],
            "pid": parts[1],
            "name": parts[2],
            "mem": parts[3],
        })
    return apps


def _query_compute_apps_by_index() -> list[dict]:
    """Run nvidia-smi --query-compute-apps using gpu index field."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_name,pid,process_name,used_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi compute-apps query failed (rc={result.returncode})"
        )
    apps = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        apps.append({
            "gpu_name": parts[0],
            "pid": parts[1],
            "name": parts[2],
            "mem": parts[3],
        })
    return apps


def _query_per_gpu_compute_apps() -> list[dict]:
    """Return compute apps with physical GPU index via per-index nvidia-smi query."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_bus_id,pid,process_name,used_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi compute-apps failed (rc={result.returncode})"
        )

    apps = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        apps.append({
            "bus_id": parts[0],
            "pid": parts[1],
            "name": parts[2],
            "mem": parts[3],
        })
    return apps


def _query_compute_apps_indexed() -> list[dict]:
    """Query nvidia-smi compute apps with GPU index in the output (index,pid,name,mem)."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_index,pid,process_name,used_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi --query-compute-apps failed (rc={result.returncode})"
        )
    apps = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpu_idx = int(parts[0])
        except ValueError:
            continue
        apps.append({
            "gpu_index": gpu_idx,
            "pid": parts[1],
            "name": parts[2],
            "mem": parts[3],
        })
    return apps


def check_placement(apps: list[dict]) -> tuple[bool, str]:
    """Assert at least one Ollama-related process is on GPU1, none on GPU0.

    Returns (ok, message).
    """
    ollama_apps = [a for a in apps if "ollama" in a.get("name", "").lower()]

    if not ollama_apps:
        return False, (
            "No Ollama compute-app entries found in nvidia-smi output. "
            "Model may not be loaded, or Ollama did not start correctly."
        )

    on_gpu0 = [a for a in ollama_apps if a.get("gpu_index") == 0]
    on_gpu1 = [a for a in ollama_apps if a.get("gpu_index") == 1]

    if on_gpu0:
        return False, (
            f"PLACEMENT FAIL: Ollama VRAM detected on GPU0 (RTX 3090). "
            f"Entry: {on_gpu0[0]}. Model must run on GPU1 (RTX 3060) only."
        )

    if not on_gpu1:
        return False, (
            f"PLACEMENT FAIL: Ollama not detected on GPU1. All entries: {ollama_apps}"
        )

    return True, f"Placement OK: Ollama on GPU1. Entry: {on_gpu1[0]}"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_smoke() -> int:
    """Run both phases. Returns 0 on full pass, 1 on any failure."""
    failures: list[str] = []

    # ── Phase 1: identity ────────────────────────────────────────────────────
    try:
        gpus = _query_gpu_identities()
        ok, msg = check_identity(gpus)
        if ok:
            print(f"[PASS] Phase 1 — {msg}", flush=True)
        else:
            print(f"[FAIL] Phase 1 — {msg}", file=sys.stderr, flush=True)
            failures.append(msg)
            # Identity failure is fatal — skip placement check to avoid misleading
            # results when GPUs are mis-indexed.
            return 1
    except Exception as exc:
        msg = f"Phase 1 exception: {exc}"
        print(f"[FAIL] {msg}", file=sys.stderr, flush=True)
        failures.append(msg)
        return 1

    # ── Phase 2: placement ───────────────────────────────────────────────────
    proc = None
    try:
        proc = _launch_ollama_gpu1()
        print(f"[INFO] Launched ollama serve on GPU1 (pid={proc.pid}), "
              f"waiting {_STARTUP_SLEEP_SEC}s ...", flush=True)
        time.sleep(_STARTUP_SLEEP_SEC)

        apps = _query_compute_apps_indexed()
        ok, msg = check_placement(apps)
        if ok:
            print(f"[PASS] Phase 2 — {msg}", flush=True)
        else:
            print(f"[FAIL] Phase 2 — {msg}", file=sys.stderr, flush=True)
            failures.append(msg)
    except Exception as exc:
        msg = f"Phase 2 exception: {exc}"
        print(f"[FAIL] {msg}", file=sys.stderr, flush=True)
        failures.append(msg)
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass

    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(run_smoke())
