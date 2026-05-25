"""HealthProbe core orchestrator — check() + verdict aggregation.

Per spec §3.2: composite read-only health check for the 3 NSSM services.
Verdict matrix: RUNNING+fresh+listening->OK; stale/no-port->DEGRADED;
STOPPED/UNKNOWN->DOWN. Overall = worst-of.

Called by: src.tools.healthprobe.__init__, src.tools.healthprobe.__main__
Calls: src.tools.healthprobe.checks, src.tools._config, src.tools._safety
Owns tables: none
Config keys: services.*, ports.*, paths.watchdog_heartbeat, paths.logs_runtime
Tests: tests/tools/test_healthprobe_integration.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import src.tools.healthprobe.checks as _checks
from src.tools._config import ArcisConfig, load_arcis_config
from src.tools._safety import safe_op
from src.tools.processmanager.nssm import ServiceState


_ET = ZoneInfo("America/New_York")

_DEFAULT_SERVICES = ["ArcisWatchLoop", "ArcisOllamaWatchdog", "ArcisDashboard"]

_DEFAULT_STALENESS: dict[str, int] = {
    "ArcisWatchLoop": 60,
    "ArcisOllamaWatchdog": 30,
    "ArcisDashboard": 300,
}

_HEARTBEAT_SOURCES: dict[str, tuple] = {
    "ArcisWatchLoop": (lambda cfg: cfg.paths.watchdog_heartbeat, "iso"),
    "ArcisDashboard": (lambda cfg: cfg.paths.logs_runtime / "arcis-dashboard.log", "mtime"),
    "ArcisOllamaWatchdog": (lambda cfg: cfg.paths.logs_runtime / "arcis-ollama-watchdog.log", "mtime"),
}

_PORT_SOURCES: dict[str, object] = {
    "ArcisWatchLoop": None,
    "ArcisDashboard": lambda cfg: cfg.ports.cloud_api.range_start,
    "ArcisOllamaWatchdog": lambda cfg: cfg.ports.ollama,
}

_LOG_SOURCES: dict[str, object] = {
    "ArcisWatchLoop": lambda cfg: cfg.paths.logs_runtime / "arcis.log",
    "ArcisDashboard": lambda cfg: cfg.paths.logs_runtime / "arcis-dashboard.log",
    "ArcisOllamaWatchdog": lambda cfg: cfg.paths.logs_runtime / "arcis-ollama-watchdog.log",
}


class HealthProbeError(RuntimeError):
    """Catastrophic failure (cfg load). Per-service failures absorbed into verdicts."""


_VERDICT_RANK = {"OK": 0, "DEGRADED": 1, "DOWN": 2}


def _service_verdict(
    service: str,
    state: ServiceState,
    heartbeat_fresh: bool | None,
    port_listening: bool | None,
) -> str:
    """Verdict matrix per spec §3.2."""
    if state in (ServiceState.STOPPED, ServiceState.UNKNOWN):
        return "DOWN"

    if state in (
        ServiceState.STARTING,
        ServiceState.STOPPING,
        ServiceState.PAUSED,
        ServiceState.PAUSE_PENDING,
        ServiceState.CONTINUE_PENDING,
    ):
        return "DEGRADED"

    # state == RUNNING
    if heartbeat_fresh is False:
        return "DEGRADED"

    if port_listening is False:
        return "DEGRADED"

    return "OK"


def _probe_service(
    service: str,
    cfg: ArcisConfig,
    stale_seconds: int | None,
) -> dict:
    """Run all 4 probes for one service and build ServiceHealth dict."""
    state = _checks._check_service_state(service)

    # Heartbeat
    hb_source = _HEARTBEAT_SOURCES.get(service)
    if hb_source is not None:
        hb_path_getter, hb_mode = hb_source
        hb_path = hb_path_getter(cfg)
        threshold = stale_seconds if stale_seconds is not None else _DEFAULT_STALENESS.get(service, 60)
        heartbeat_fresh, heartbeat_reason = _checks._check_heartbeat(hb_path, threshold, mode=hb_mode)
    else:
        heartbeat_fresh = None
        heartbeat_reason = None

    # Port
    port_getter = _PORT_SOURCES.get(service)
    if port_getter is not None:
        port = port_getter(cfg)
        port_listening = _checks._check_port(port)
    else:
        port_listening = None

    # Recent errors
    log_getter = _LOG_SOURCES.get(service)
    if log_getter is not None:
        log_path = log_getter(cfg)
        recent_error_count = _checks._check_recent_errors(log_path)
    else:
        recent_error_count = 0

    verdict = _service_verdict(service, state, heartbeat_fresh, port_listening)

    return {
        "service": service,
        "state": state.value,
        "heartbeat_fresh": heartbeat_fresh,
        "heartbeat_reason": heartbeat_reason,
        "port_listening": port_listening,
        "recent_error_count": recent_error_count,
        "verdict": verdict,
    }


def _check_impl(
    *,
    services: list[str] | None = None,
    stale_seconds: int | None = None,
    cfg: ArcisConfig | None = None,
) -> dict:
    """Implementation (unwrapped) — callable with injected cfg for tests."""
    if cfg is None:
        try:
            cfg = load_arcis_config()
        except Exception as exc:
            raise HealthProbeError(f"cannot load arcis config: {exc}") from exc

    service_list = services if services is not None else _DEFAULT_SERVICES

    results: dict[str, dict] = {}
    for svc in service_list:
        results[svc] = _probe_service(svc, cfg, stale_seconds)

    # Overall = worst-of
    worst = "OK"
    for sh in results.values():
        v = sh["verdict"]
        if _VERDICT_RANK.get(v, 0) > _VERDICT_RANK.get(worst, 0):
            worst = v

    return {
        "services": results,
        "overall": worst,
        "as_of_et": datetime.now(_ET).isoformat(),
    }


@safe_op(name="healthprobe", mutates=False)
def check(
    *,
    services: Optional[list[str]] = None,
    stale_seconds: Optional[int] = None,
    cfg: Optional[ArcisConfig] = None,
) -> dict:
    """Composite read-only health check for Arcis NSSM services.

    Args:
        services:      List of NSSM service names to probe. Defaults to
                       ['ArcisWatchLoop', 'ArcisOllamaWatchdog', 'ArcisDashboard'].
        stale_seconds: Override per-service heartbeat staleness threshold.
                       Applied uniformly when specified.
        cfg:           Optional pre-loaded ArcisConfig. If None, loads via
                       load_arcis_config() (respects ARCIS_CONFIG_PATH_OVERRIDE).

    Returns:
        ProbeResult dict with 'services', 'overall', 'as_of_et'.

    Raises:
        HealthProbeError: catastrophic failure (cfg load). Per-service
                         failures are absorbed into per-service verdicts.
    """
    return _check_impl(services=services, stale_seconds=stale_seconds, cfg=cfg)
