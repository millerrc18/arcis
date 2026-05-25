# Purpose: ProcessManager subpackage — NSSM service control (read + mutate).
# Called by: operator agents, src/tools/processmanager/__main__.py
# Calls: src.tools.processmanager.core
# Owns tables: none
# Config keys: services.*, paths.watchdog_heartbeat, safety_windows.no_restart_overnight
# Tests: tests/tools/test_processmanager_integration.py

from src.tools.processmanager.core import (
    ServiceState,
    RestartResult,
    start,
    status,
    stop,
    restart,
)
from src.tools._subprocess import NssmMissingError  # noqa
from src.tools.processmanager.nssm import NssmCommandFailedError
from src.tools.processmanager.core import UnknownServiceError

__all__ = [
    "ServiceState",
    "RestartResult",
    "status",
    "start",
    "stop",
    "restart",
    "NssmMissingError",
    "NssmCommandFailedError",
    "UnknownServiceError",
]
