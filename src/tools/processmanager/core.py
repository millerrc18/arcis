"""ProcessManager core entry points — status/start/stop/restart + service-alias resolver.

Decorated entry points with @safe_op + @safety_window. Delegates subprocess work
to nssm.py. Service aliases resolved from arcis_config.yaml services section.

Called by: src.tools.processmanager.__init__, operator agents
Calls: src.tools._safety, src.tools._config, src.tools.processmanager.nssm
Owns tables: none
Config keys: services.*, safety_windows.no_restart_overnight
Tests: tests/tools/test_processmanager_integration.py
"""

from __future__ import annotations

import time
from pathlib import Path

from src.tools._config import load_arcis_config
from src.tools._safety import SafetyWindowError, safe_op, safety_window
from src.tools.processmanager.nssm import (
    NssmCommandFailedError,
    RestartResult,
    ServiceState,
    _restart_and_verify,
    nssm_start,
    nssm_status,
    nssm_stop,
)


class ProcessManagerError(RuntimeError):
    pass


class UnknownServiceError(ProcessManagerError):
    pass


def _resolve_service_name(service: str, *, config_path: Path | None = None) -> str:
    """Accepts alias ('watch'/'watch_loop'/'ArcisWatchLoop') OR full NSSM name."""
    cfg = load_arcis_config(path=config_path)
    aliases = {
        "watch": cfg.services.watch_loop,
        "watch_loop": cfg.services.watch_loop,
        "ollama": cfg.services.ollama_watchdog,
        "ollama_watchdog": cfg.services.ollama_watchdog,
        "dashboard": cfg.services.dashboard,
    }
    nssm_names = {cfg.services.watch_loop, cfg.services.ollama_watchdog, cfg.services.dashboard}
    if service in nssm_names:
        return service
    if service in aliases:
        return aliases[service]
    raise UnknownServiceError(
        f"Unknown service alias: {service!r}. "
        f"Known: {sorted(aliases) + sorted(nssm_names)}"
    )


def _status_impl(service: str, *, config_path: Path | None = None) -> ServiceState:
    full_name = _resolve_service_name(service, config_path=config_path)
    return nssm_status(full_name)


def _start_impl(service: str, *, config_path: Path | None = None) -> ServiceState:
    full_name = _resolve_service_name(service, config_path=config_path)
    return nssm_start(full_name)


def _stop_impl(service: str, *, config_path: Path | None = None) -> ServiceState:
    full_name = _resolve_service_name(service, config_path=config_path)
    return nssm_stop(full_name)


def _restart_impl(service: str, *, config_path: Path | None = None) -> RestartResult:
    full_name = _resolve_service_name(service, config_path=config_path)
    restart_start_walltime = time.time()
    return _restart_and_verify(
        full_name,
        restart_start_walltime=restart_start_walltime,
        config_path=config_path,
    )


@safe_op(name="processmanager", mutates=False)
def status(service: str) -> ServiceState:
    return _status_impl(service)


@safe_op(name="processmanager", mutates=True)
def start(service: str, *, confirm: bool = False) -> ServiceState:
    return _start_impl(service)


@safe_op(name="processmanager", mutates=True)
def stop(service: str, *, confirm: bool = False) -> ServiceState:
    return _stop_impl(service)


@safe_op(name="processmanager", mutates=True)
@safety_window("no_restart_overnight")
def restart(service: str, *, confirm: bool = False, emergency: bool = False) -> RestartResult:
    return _restart_impl(service)
