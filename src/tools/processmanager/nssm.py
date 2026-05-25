"""NSSM subprocess wrappers for ProcessManager.

Pure subprocess helpers: nssm_status (POSITIVE state-map), nssm_start/stop/restart
(timeout=15), DA2 wait-and-verify protocol with sustained-running flap detection.

Called by: src.tools.processmanager.core
Calls: src.tools._subprocess, src.tools._config
Owns tables: none
Config keys: services.*, paths.watchdog_heartbeat
Tests: tests/tools/test_processmanager_integration.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.tools import _subprocess
from src.tools._config import load_arcis_config


class ServiceState(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    PAUSED = "PAUSED"
    PAUSE_PENDING = "PAUSE_PENDING"
    CONTINUE_PENDING = "CONTINUE_PENDING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RestartResult:
    restarted: bool
    verified: bool
    elapsed_s: float
    log_evidence: str | None
    state: ServiceState


class ProcessManagerError(RuntimeError):
    pass


class NssmCommandFailedError(ProcessManagerError):
    pass


_STATE_MAP = [
    ("SERVICE_RUNNING",          ServiceState.RUNNING),
    ("SERVICE_START_PENDING",    ServiceState.STARTING),
    ("SERVICE_STOP_PENDING",     ServiceState.STOPPING),
    ("SERVICE_CONTINUE_PENDING", ServiceState.CONTINUE_PENDING),
    ("SERVICE_PAUSE_PENDING",    ServiceState.PAUSE_PENDING),
    ("SERVICE_PAUSED",           ServiceState.PAUSED),
    ("SERVICE_STOPPED",          ServiceState.STOPPED),
]


def nssm_status(service: str) -> ServiceState:
    """POSITIVE substring match in _STATE_MAP order; first match wins."""
    result = _subprocess.run(
        [_subprocess.resolve_exe("nssm"), "status", service],
        timeout=15,
    )
    if result.returncode != 0:
        raise NssmCommandFailedError(
            f"nssm status exit {result.returncode}: {result.stderr.strip()}"
        )
    stdout = result.stdout
    for needle, state in _STATE_MAP:
        if needle in stdout:
            return state
    return ServiceState.UNKNOWN


def nssm_start(service: str) -> ServiceState:
    result = _subprocess.run(
        [_subprocess.resolve_exe("nssm"), "start", service],
        timeout=15,
    )
    if result.returncode != 0:
        raise NssmCommandFailedError(
            f"nssm start exit {result.returncode}: {result.stderr.strip()}"
        )
    return nssm_status(service)


def nssm_stop(service: str) -> ServiceState:
    result = _subprocess.run(
        [_subprocess.resolve_exe("nssm"), "stop", service],
        timeout=15,
    )
    if result.returncode != 0:
        raise NssmCommandFailedError(
            f"nssm stop exit {result.returncode}: {result.stderr.strip()}"
        )
    return nssm_status(service)


def nssm_restart(service: str) -> None:
    result = _subprocess.run(
        [_subprocess.resolve_exe("nssm"), "restart", service],
        timeout=15,
    )
    if result.returncode != 0:
        raise NssmCommandFailedError(
            f"nssm restart exit {result.returncode}: {result.stderr.strip()}"
        )


def _resolve_log_evidence_path(full_name: str, *, config_path: Path | None = None) -> Path:
    """Return the log/heartbeat path for the service. NEVER use db_canonical.parent."""
    cfg = load_arcis_config(path=config_path)
    if full_name == cfg.services.watch_loop:
        return cfg.paths.watchdog_heartbeat
    if full_name == cfg.services.dashboard:
        return cfg.paths.logs_runtime / "arcis-dashboard.log"
    if full_name == cfg.services.ollama_watchdog:
        return cfg.paths.logs_runtime / "arcis-ollama-watchdog.log"
    from src.tools.processmanager.core import UnknownServiceError
    raise UnknownServiceError(f"No log evidence path configured for {full_name!r}")


def _poll_log_evidence(log_path: Path, restart_start_walltime: float) -> str | None:
    """Poll log_path for mtime >= restart_start_walltime within 5s. Returns path str or None."""
    LOG_EVIDENCE_WINDOW_S = 5.0
    log_deadline = time.monotonic() + LOG_EVIDENCE_WINDOW_S
    while time.monotonic() < log_deadline:
        if log_path.exists():
            if log_path.stat().st_mtime >= restart_start_walltime:
                return str(log_path)
        time.sleep(0.5)
    return None


def _restart_and_verify(
    full_name: str,
    *,
    restart_start_walltime: float,
    config_path: Path | None = None,
) -> RestartResult:
    """DA2 SUSTAINED-RUNNING wait-and-verify protocol per DD-16.

    NSSM AppRestartDelay flap detection via consecutive_running counter reset on any
    non-RUNNING state. Overall deadline 33s (30s initial + 3s sustained window).
    """
    restart_start_monotonic = time.monotonic()
    nssm_restart(full_name)

    INITIAL_DEADLINE_S = 30.0
    SUSTAINED_WINDOW_S = 3.0
    POLL_INTERVAL_S = 1.0
    REQUIRED_CONSECUTIVE = 3
    overall_deadline = restart_start_monotonic + INITIAL_DEADLINE_S + SUSTAINED_WINDOW_S
    consecutive_running = 0
    last_state = ServiceState.UNKNOWN

    while time.monotonic() < overall_deadline:
        time.sleep(POLL_INTERVAL_S)
        last_state = nssm_status(full_name)
        if last_state == ServiceState.RUNNING:
            consecutive_running += 1
            if consecutive_running >= REQUIRED_CONSECUTIVE:
                break
        else:
            consecutive_running = 0

    elapsed_s = time.monotonic() - restart_start_monotonic

    if consecutive_running < REQUIRED_CONSECUTIVE:
        return RestartResult(
            restarted=True, verified=False, elapsed_s=elapsed_s,
            log_evidence=None, state=last_state,
        )

    log_path = _resolve_log_evidence_path(full_name, config_path=config_path)
    log_evidence_seen = _poll_log_evidence(log_path, restart_start_walltime)

    return RestartResult(
        restarted=True,
        verified=log_evidence_seen is not None,
        elapsed_s=time.monotonic() - restart_start_monotonic,
        log_evidence=log_evidence_seen,
        state=last_state,
    )
