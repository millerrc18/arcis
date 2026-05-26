"""System metrics collector — GPU, CPU, RAM, disk, Ollama health.

Called by: scheduler.watch (every 5 scans), api.routes.system
Calls: nvidia-smi (subprocess), psutil, requests (Ollama API)
Owns tables: system_metrics
Config keys: none
Tests: tests/test_system_metrics.py

Every sub-collector is wrapped in try/except and returns None values on
failure so the top-level snapshot never crashes the watch loop.
"""

import logging
import subprocess
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import psutil
import requests

from src.config import DB_PATH
from src.utils.db import connect_db, engine_aware_upsert

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Sub-collectors
# ---------------------------------------------------------------------------

def _collect_gpu_metrics() -> dict:
    """Query nvidia-smi for GPU utilization, VRAM, temp, power."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return _gpu_none()

        rows = result.stdout.strip().splitlines()
        parts = [p.strip() for p in rows[0].split(",")]
        return {
            "gpu_util_pct": float(parts[0]),
            "gpu_vram_used_mb": float(parts[1]),
            "gpu_vram_total_mb": float(parts[2]),
            "gpu_temp_c": float(parts[3]),
            "gpu_power_w": float(parts[4]),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("GPU metrics unavailable: %s", exc)
        return _gpu_none()
    except (ValueError, IndexError) as exc:
        logger.warning("nvidia-smi parse error: %s", exc)
        return _gpu_none()


def _gpu_none() -> dict:
    return {
        "gpu_util_pct": None,
        "gpu_vram_used_mb": None,
        "gpu_vram_total_mb": None,
        "gpu_temp_c": None,
        "gpu_power_w": None,
    }


def _collect_cpu_ram_metrics() -> dict:
    """Collect CPU and RAM usage via psutil."""
    try:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {
            "cpu_pct": cpu_pct,
            "ram_used_mb": round(mem.used / (1024 * 1024), 1),
            "ram_total_mb": round(mem.total / (1024 * 1024), 1),
        }
    except Exception as exc:
        logger.debug("CPU/RAM metrics failed: %s", exc)
        return {"cpu_pct": None, "ram_used_mb": None, "ram_total_mb": None}


def _collect_disk_metrics() -> dict:
    """Collect disk usage via psutil."""
    try:
        usage = psutil.disk_usage("/")
        return {
            "disk_used_gb": round(usage.used / (1024 ** 3), 2),
            "disk_total_gb": round(usage.total / (1024 ** 3), 2),
        }
    except Exception as exc:
        logger.debug("Disk metrics failed: %s", exc)
        return {"disk_used_gb": None, "disk_total_gb": None}


def _collect_ollama_status() -> dict:
    """Check Ollama health by hitting /api/tags."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            model_name = models[0]["name"] if models else None
            return {"ollama_status": "running", "ollama_model": model_name}
        return {"ollama_status": "error", "ollama_model": None}
    except Exception as exc:
        logger.debug("Ollama status check failed: %s", exc)
        return {"ollama_status": "error", "ollama_model": None}


def _collect_process_metrics() -> dict:
    """Collect current Python process RSS memory."""
    try:
        proc = psutil.Process()
        rss_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
        return {"python_rss_mb": rss_mb}
    except Exception as exc:
        logger.debug("Process metrics failed: %s", exc)
        return {"python_rss_mb": None}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _store_snapshot(snapshot: dict, db_path: str = DB_PATH) -> None:
    """INSERT a snapshot row into system_metrics.

    Dispatches through `engine_aware_upsert(action='replace')` so SQLite
    callers use native `INSERT OR REPLACE` and PG callers get
    `INSERT ... ON CONFLICT (snapshot_id) DO UPDATE` — both reach the same
    one-row-per-snapshot_id invariant. The audit at
    docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
    classifies system_metrics as `in_place_update` (no incoming FKs, no
    triggers, no rowid dependencies); production also generates a fresh
    UUID per call so REPLACE is dead-code in production (see §6.1 of the
    audit doc — follow-up tracked separately under Sprint 5 backlog).
    """
    cols = [
        "snapshot_id", "timestamp",
        "gpu_util_pct", "gpu_vram_used_mb", "gpu_vram_total_mb",
        "gpu_temp_c", "gpu_power_w",
        "cpu_pct", "ram_used_mb", "ram_total_mb",
        "disk_used_gb", "disk_total_gb",
        "ollama_status", "ollama_model",
        "python_rss_mb",
    ]
    row_dict = {c: snapshot.get(c) for c in cols}

    with connect_db(db_path) as conn:  # timeout upgraded to 30s via connect_db per CLAUDE.md
        engine_aware_upsert(conn, "system_metrics", row_dict, action="replace")
        conn.commit()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect_system_snapshot(db_path: str = DB_PATH) -> dict:
    """Collect all system metrics and store to DB. Returns the snapshot dict."""
    snapshot: dict = {}

    # Merge all sub-collector results
    snapshot.update(_collect_gpu_metrics())
    snapshot.update(_collect_cpu_ram_metrics())
    snapshot.update(_collect_disk_metrics())
    snapshot.update(_collect_ollama_status())
    snapshot.update(_collect_process_metrics())

    # Add identity fields
    snapshot["snapshot_id"] = str(uuid.uuid4())
    snapshot["timestamp"] = datetime.now(ET).isoformat()

    # Persist
    try:
        _store_snapshot(snapshot, db_path)
    except Exception as exc:
        logger.warning("Failed to store system metrics snapshot: %s", exc)

    return snapshot
