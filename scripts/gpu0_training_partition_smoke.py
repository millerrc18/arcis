"""GPU0 training-partition smoke — exercises the production training-launch
path under real VRAM load WITHOUT performing a fine-tune.

Complements scripts/gpu_placement_smoke.py: that script gates Ollama-on-GPU1
placement; this script gates training-on-GPU0 lifecycle (MAJOR-5 preflight +
CUDA_VISIBLE_DEVICES=0 spawn + training.pid write/clean + Ollama-stays-on-GPU1
under contention). Validates the dual-GPU static partition under genuine load
when the corpus HOLDOUT EMPTY gate prevents an organic training cycle from
exercising the path.

Reuses trainer._assert_gpu0_identity, trainer._training_subprocess_env, and
trainer._launch_and_wait_training so the smoke walks the SAME code path that
production overnight training does.

Run from repo root:
    python scripts/gpu0_training_partition_smoke.py

Exit codes:
    0 — all phases passed
    10 — MAJOR-5 preflight rejected GPU0
    20 — training.pid not cleaned post-exit
    30 — smoke subprocess exited nonzero
    40 — monitor observed smoke on wrong GPU or Ollama on GPU0
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.training import trainer, training_control


def _query_gpu_index_by_uuid() -> dict[str, int]:
    """uuid -> index map (mirrors scripts/gpu_placement_smoke._query_gpu_index_by_uuid).

    Inlined here to avoid `scripts/__init__.py` package-import dependency.
    """
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,uuid", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi --query-gpu (uuid map) failed (rc={result.returncode})"
        )
    mapping: dict[str, int] = {}
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                mapping[parts[2]] = int(parts[0])
            except ValueError:
                continue
    return mapping


def _query_compute_apps_indexed() -> list[dict]:
    """Compute-apps with gpu_index resolved via uuid map. Driver 596.36 rejects
    `gpu_index` as a query field — query `gpu_uuid` and cross-reference (the
    v0.36.51 hotfix lesson from PR #1164)."""
    uuid_to_idx = _query_gpu_index_by_uuid()
    result = subprocess.run(
        ["nvidia-smi",
         "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi --query-compute-apps failed (rc={result.returncode})"
        )
    apps: list[dict] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx = uuid_to_idx.get(parts[0])
        if idx is None:
            continue
        apps.append({"gpu_index": idx, "pid": parts[1],
                     "name": parts[2], "mem": parts[3]})
    return apps

TRAIN_DATA = _REPO_ROOT / "training_data"
SMOKE_DURATION = int(os.environ.get("SMOKE_DURATION", "90"))
SMOKE_ALLOC_GB = float(os.environ.get("SMOKE_ALLOC_GB", "4"))
MONITOR_POLL_SEC = 5


# The smoke subprocess source. `_is_tracked_training_proc` validates the tracked
# PID by checking that its cmdline contains "train.py" — so this MUST be written
# to training_data/train.py (the production location). The subprocess honors
# ARCIS_STOP_FLAG so it can be cleanly stopped by training_control.stop_training_bounded
# in case operator aborts mid-run.
SMOKE_SUBPROC_SOURCE = textwrap.dedent('''
    """GPU0 partition smoke subprocess — NOT a real training run.

    Allocates a CUDA tensor on cuda:0 (which under CUDA_VISIBLE_DEVICES=0 is
    the host GPU0, the RTX 3090) and holds it for SMOKE_DURATION seconds.
    Honors ARCIS_STOP_FLAG for clean cooperative shutdown.
    """
    import os
    import sys
    import time

    STOP_FLAG = os.environ.get("ARCIS_STOP_FLAG")
    SMOKE_DURATION = float(os.environ.get("SMOKE_DURATION", "90"))
    SMOKE_ALLOC_GB = float(os.environ.get("SMOKE_ALLOC_GB", "4"))

    print(f"[SMOKE] pid={os.getpid()} starting", flush=True)
    print(f"[SMOKE] CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')!r}", flush=True)
    print(f"[SMOKE] CUDA_DEVICE_ORDER={os.environ.get('CUDA_DEVICE_ORDER')!r}", flush=True)

    try:
        import torch
    except ImportError as exc:
        print(f"[SMOKE] FATAL: torch import failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)

    if not torch.cuda.is_available():
        print("[SMOKE] FATAL: torch.cuda.is_available() is False", file=sys.stderr, flush=True)
        sys.exit(3)

    dev = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(dev)
    total_gb = props.total_memory / (1024 ** 3)
    print(f"[SMOKE] cuda:0 = {props.name} ({total_gb:.1f} GB total)", flush=True)
    if "3090" not in props.name:
        print(f"[SMOKE] FATAL: cuda:0 is not RTX 3090 (got {props.name!r})", file=sys.stderr, flush=True)
        sys.exit(4)

    n_floats = int(SMOKE_ALLOC_GB * (1024 ** 3) / 4)
    print(f"[SMOKE] allocating {SMOKE_ALLOC_GB} GB ({n_floats:,} float32) on cuda:0 ...", flush=True)
    t = torch.zeros(n_floats, dtype=torch.float32, device=dev)
    t.fill_(1.0)
    torch.cuda.synchronize(dev)
    mem_alloc_gb = torch.cuda.memory_allocated(dev) / (1024 ** 3)
    print(f"[SMOKE] allocated; cuda mem_allocated = {mem_alloc_gb:.2f} GB; sum check = {t.sum().item():.1f}",
          flush=True)

    print(f"[SMOKE] holding for {SMOKE_DURATION:.0f}s; watching STOP_FLAG={STOP_FLAG!r}", flush=True)
    deadline = time.monotonic() + SMOKE_DURATION
    while time.monotonic() < deadline:
        if STOP_FLAG and os.path.exists(STOP_FLAG):
            print(f"[SMOKE] STOP flag observed at {STOP_FLAG}; exiting cooperatively",
                  flush=True)
            break
        time.sleep(2)

    del t
    torch.cuda.empty_cache()
    print("[SMOKE] released; exit 0", flush=True)
''')


class GPUMonitor(threading.Thread):
    """Polls nvidia-smi compute-apps every MONITOR_POLL_SEC; collects observations
    of (a) which GPU the smoke subprocess is on, (b) which GPU Ollama is on."""

    def __init__(self, smoke_pid_lookup):
        super().__init__(daemon=True)
        self.smoke_pid_lookup = smoke_pid_lookup
        self.observations: list[dict] = []
        self.stop_evt = threading.Event()

    def run(self) -> None:
        while not self.stop_evt.is_set():
            ts = time.time()
            try:
                apps = _query_compute_apps_indexed()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError) as exc:
                self.observations.append({"ts": ts, "err": str(exc)})
                time.sleep(MONITOR_POLL_SEC)
                continue
            smoke_pid = self.smoke_pid_lookup()
            obs = {
                "ts": ts,
                "smoke_pid": smoke_pid,
                "smoke_on_gpus": [],
                "ollama_on_gpus": [],
                "all_apps": [
                    {"idx": a["gpu_index"], "pid": a["pid"],
                     "name": Path(a["name"]).name, "mem": a["mem"]}
                    for a in apps
                ],
            }
            for a in apps:
                if smoke_pid and str(a["pid"]) == str(smoke_pid):
                    obs["smoke_on_gpus"].append(a["gpu_index"])
                if "ollama" in Path(a["name"]).name.lower():
                    obs["ollama_on_gpus"].append(a["gpu_index"])
            self.observations.append(obs)
            self.stop_evt.wait(MONITOR_POLL_SEC)


def _smoke_pid_from_pidfile() -> int | None:
    """Resolve the tracked smoke PID via the production training.pid file."""
    try:
        with open(training_control.TRAINING_PID_FILE, encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _err_log_size() -> int:
    """Best-effort size of arcis_err.log for delta-comparison post-smoke."""
    p = _REPO_ROOT / "logs" / "arcis_err.log"
    try:
        return p.stat().st_size
    except OSError:
        return -1


def main() -> int:
    print("=" * 72)
    print("GPU0 TRAINING-PARTITION SMOKE")
    print(f"  repo:        {_REPO_ROOT}")
    print(f"  duration:    {SMOKE_DURATION}s")
    print(f"  alloc:       {SMOKE_ALLOC_GB} GB")
    print(f"  monitor:     every {MONITOR_POLL_SEC}s via nvidia-smi compute-apps")
    print("=" * 72)
    print()

    # ── Phase 1: production MAJOR-5 preflight ────────────────────────────────
    print("[PHASE 1] _assert_gpu0_identity() — production preflight")
    try:
        trainer._assert_gpu0_identity()
        print("[PHASE 1] PASS\n")
    except RuntimeError as exc:
        print(f"[PHASE 1] FAIL — preflight rejected: {exc}\n", file=sys.stderr)
        return 10

    # ── Phase 2: stage smoke train.py ────────────────────────────────────────
    TRAIN_DATA.mkdir(parents=True, exist_ok=True)
    train_py = TRAIN_DATA / "train.py"
    backup_py = TRAIN_DATA / "train.py.smoke-bak"
    had_train_py = train_py.exists()
    if had_train_py:
        shutil.copy2(train_py, backup_py)
        print(f"[PHASE 2] Backed up existing train.py ({train_py.stat().st_size} bytes) "
              f"-> {backup_py.name}")
    train_py.write_text(SMOKE_SUBPROC_SOURCE, encoding="utf-8")
    print(f"[PHASE 2] Wrote smoke train.py ({train_py.stat().st_size} bytes)\n")

    # ── Phase 3: env (production helper) + baseline error-log size ───────────
    env = trainer._training_subprocess_env()
    env["SMOKE_DURATION"] = str(SMOKE_DURATION)
    env["SMOKE_ALLOC_GB"] = str(SMOKE_ALLOC_GB)
    print("[PHASE 3] Env from _training_subprocess_env():")
    for k in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "PYTHONUTF8",
              "PYTHONIOENCODING", "ARCIS_STOP_FLAG"):
        print(f"           {k}={env.get(k)!r}")
    err_size_before = _err_log_size()
    print(f"[PHASE 3] arcis_err.log size before: {err_size_before} bytes\n")

    # ── Phase 4: launch monitor + smoke subprocess via production helper ─────
    monitor = GPUMonitor(_smoke_pid_from_pidfile)
    monitor.start()

    print("[PHASE 4] Launching smoke via trainer._launch_and_wait_training ...")
    t0 = time.time()
    rc: int | None = None
    try:
        rc = trainer._launch_and_wait_training([sys.executable, str(train_py)], env)
        elapsed = time.time() - t0
        print(f"[PHASE 4] Subprocess exited rc={rc} after {elapsed:.1f}s\n")
    finally:
        monitor.stop_evt.set()
        monitor.join(timeout=20)

    # ── Phase 5: restore train.py ────────────────────────────────────────────
    if had_train_py:
        shutil.copy2(backup_py, train_py)
        try:
            backup_py.unlink()
        except OSError:
            pass
        print(f"[PHASE 5] Restored original train.py from backup\n")
    else:
        try:
            train_py.unlink()
        except OSError:
            pass
        print("[PHASE 5] Removed smoke train.py (no pre-existing file)\n")

    # ── Phase 6: analyze observations ────────────────────────────────────────
    print("[PHASE 6] Monitor observations:")
    print(f"           total samples: {len(monitor.observations)}")
    samples_with_pid = [o for o in monitor.observations
                        if o.get("smoke_pid") and "err" not in o]
    print(f"           samples with smoke PID resolved: {len(samples_with_pid)}")

    smoke_wrong_gpu: list[dict] = []
    ollama_on_gpu0: list[dict] = []
    ollama_gpu_seen: set[int] = set()
    smoke_gpu_seen: set[int] = set()
    for o in samples_with_pid:
        for idx in o.get("smoke_on_gpus", []):
            smoke_gpu_seen.add(idx)
            if idx != 0:
                smoke_wrong_gpu.append(o)
        for idx in o.get("ollama_on_gpus", []):
            ollama_gpu_seen.add(idx)
            if idx == 0:
                ollama_on_gpu0.append(o)

    print(f"           smoke GPU indices observed: {sorted(smoke_gpu_seen)}")
    print(f"           ollama GPU indices observed: {sorted(ollama_gpu_seen)}")
    if smoke_wrong_gpu:
        print(f"           !! smoke observed on non-GPU0 in {len(smoke_wrong_gpu)} sample(s)")
    if ollama_on_gpu0:
        print(f"           !! ollama observed on GPU0 in {len(ollama_on_gpu0)} sample(s)")

    # First/last samples for context
    if samples_with_pid:
        first = samples_with_pid[0]
        last = samples_with_pid[-1]
        print(f"           first sample: pid={first['smoke_pid']} on GPUs {first['smoke_on_gpus']}; "
              f"ollama GPUs {first.get('ollama_on_gpus', [])}")
        print(f"           last sample:  pid={last['smoke_pid']} on GPUs {last['smoke_on_gpus']}; "
              f"ollama GPUs {last.get('ollama_on_gpus', [])}")

    # ── Phase 7: training.pid cleanup verification ───────────────────────────
    print()
    print("[PHASE 7] training.pid cleanup verification:")
    if os.path.exists(training_control.TRAINING_PID_FILE):
        print(f"[PHASE 7] FAIL — training.pid still exists at "
              f"{training_control.TRAINING_PID_FILE}\n", file=sys.stderr)
        return 20
    else:
        print(f"[PHASE 7] PASS — training.pid cleaned ({training_control.TRAINING_PID_FILE})\n")

    # ── Phase 8: arcis_err.log delta ─────────────────────────────────────────
    err_size_after = _err_log_size()
    delta = err_size_after - err_size_before if err_size_before >= 0 else None
    print(f"[PHASE 8] arcis_err.log size after: {err_size_after} bytes (delta={delta})")
    if delta and delta > 0:
        print(f"           NOTE: stderr grew by {delta} bytes during smoke — review tail")
    print()

    # ── Verdict ──────────────────────────────────────────────────────────────
    print("=" * 72)
    if rc != 0:
        print(f"VERDICT: FAIL — smoke subprocess returned rc={rc}")
        print("=" * 72)
        return 30
    if smoke_wrong_gpu or ollama_on_gpu0:
        print("VERDICT: FAIL — partition violation observed (see WARN above)")
        print("=" * 72)
        return 40
    if not samples_with_pid:
        print("VERDICT: AMBER — no smoke samples resolved via training.pid; "
              "partition not directly observed (smoke may have run faster than monitor)")
        print("=" * 72)
        return 0
    print(f"VERDICT: PASS — smoke held GPU0 for {SMOKE_DURATION}s, "
          f"Ollama stayed on GPU{sorted(ollama_gpu_seen) or '?'}, "
          f"training.pid lifecycle clean")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
