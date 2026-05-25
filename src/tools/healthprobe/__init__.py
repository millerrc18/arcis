# Purpose: HealthProbe subpackage — composite read-only health check.
# Called by: operator agents, src/tools/healthprobe/__main__.py
# Calls: src.tools.healthprobe.core
# Owns tables: none
# Config keys: services.*, ports.*, paths.*
# Tests: tests/tools/test_healthprobe_integration.py

from src.tools.healthprobe.core import HealthProbeError, check

__all__ = [
    "check",
    "HealthProbeError",
]
