"""NSSM-seam boundary-touch tests — HealthProbe service-name + filename contract.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: HealthProbe's _HEARTBEAT_SOURCES and _LOG_SOURCES lambdas derive REAL
file paths from the REAL ArcisConfig. The contract is that:
  1. Each configured service name resolves to a non-None path getter.
  2. The watchdog_heartbeat path comes from cfg.paths.watchdog_heartbeat (not
     hard-coded), so a config drift would be caught.
  3. ArcisDashboard and ArcisOllamaWatchdog have NO heartbeat source (no real
     heartbeat file exists) -- they are port-monitored via _PORT_SOURCES (v0.36.80).
  4. The _verdict_matrix maps (STOPPED, *, *) -> DOWN reliably.

These are non-vacuous because they drive the REAL config loading path and
the REAL dict lookups in core.py — not mocks. Non-vacuity proved by:
  1. Renamed cfg.paths.watchdog_heartbeat -> cfg.paths.bogus_hb in a scratch
     edit of the lambda in core.py: test_watchloop_heartbeat_path_matches_config
     FAILED (AttributeError / path mismatch).
  2. Re-adding a heartbeat source for ArcisDashboard/ArcisOllamaWatchdog (the
     false-STALE regression v0.36.80 removed) fails test_*_has_no_heartbeat_source.
  3. Changed _service_verdict STOPPED branch to return "DEGRADED":
     test_verdict_stopped_service_is_down FAILED (AssertionError: 'DEGRADED' != 'DOWN').
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations

import pytest


def test_watchloop_heartbeat_path_matches_config():
    """_HEARTBEAT_SOURCES['ArcisWatchLoop'] getter returns cfg.paths.watchdog_heartbeat.

    Non-vacuity: replacing the getter lambda with one that returns a wrong path
    causes this test to fail with an AssertionError on the path comparison.
    """
    from src.tools._config import load_arcis_config
    from src.tools.healthprobe.core import _HEARTBEAT_SOURCES

    cfg = load_arcis_config()
    getter, mode = _HEARTBEAT_SOURCES["ArcisWatchLoop"]
    derived_path = getter(cfg)
    expected_path = cfg.paths.watchdog_heartbeat

    assert derived_path == expected_path, (
        f"WatchLoop heartbeat path mismatch: "
        f"core.py derives {derived_path!r}, config reports {expected_path!r}"
    )
    assert mode == "iso", f"WatchLoop heartbeat mode must be 'iso', got {mode!r}"


def test_ollama_has_no_heartbeat_source_uses_port():
    """ArcisOllamaWatchdog has NO heartbeat source -- it is port-monitored (ports.ollama).

    v0.36.80: the prior 'ollama_watchdog.out.log' heartbeat target does not
    exist (real files are ollama-daemon.out / ollama-watchdog.log, both
    event-only and days-stale when healthy), so a heartbeat-mtime check produced
    a false STALE/DEGRADED. Ollama liveness is its listening port, not a
    heartbeat file. Non-vacuity: re-adding a heartbeat source for this service
    (the regression v0.36.80 removed) fails the first assert.
    """
    from src.tools.healthprobe.core import _HEARTBEAT_SOURCES, _PORT_SOURCES

    assert "ArcisOllamaWatchdog" not in _HEARTBEAT_SOURCES, (
        "ArcisOllamaWatchdog must NOT have a heartbeat source (no real heartbeat "
        "file exists); it is port-monitored"
    )
    assert _PORT_SOURCES.get("ArcisOllamaWatchdog") is not None, (
        "ArcisOllamaWatchdog liveness must come from a port getter"
    )


def test_dashboard_has_no_heartbeat_source_uses_port():
    """ArcisDashboard has NO heartbeat source -- it is port-monitored (ports.cloud_api).

    v0.36.80: there is no dashboard heartbeat file at all; liveness is the HTTP
    port, not a (nonexistent) 'dashboard-stdout.log' mtime. Non-vacuity: re-adding
    a heartbeat source for this service fails the first assert.
    """
    from src.tools.healthprobe.core import _HEARTBEAT_SOURCES, _PORT_SOURCES

    assert "ArcisDashboard" not in _HEARTBEAT_SOURCES, (
        "ArcisDashboard must NOT have a heartbeat source (no heartbeat file "
        "exists); it is port-monitored"
    )
    assert _PORT_SOURCES.get("ArcisDashboard") is not None, (
        "ArcisDashboard liveness must come from a port getter"
    )


def test_verdict_stopped_service_is_down():
    """_service_verdict(STOPPED, *, *) must return 'DOWN'.

    Non-vacuity: changing the STOPPED branch to return 'DEGRADED' causes this
    test to FAIL with AssertionError: 'DEGRADED' != 'DOWN'.
    """
    from src.tools.healthprobe.core import _service_verdict
    from src.tools.processmanager.nssm import ServiceState

    verdict = _service_verdict("ArcisWatchLoop", ServiceState.STOPPED, None, None)
    assert verdict == "DOWN", f"STOPPED must map to DOWN, got {verdict!r}"


def test_verdict_running_stale_heartbeat_is_degraded():
    """_service_verdict(RUNNING, heartbeat_fresh=False, *) must return 'DEGRADED'.

    Non-vacuity: removing the `if heartbeat_fresh is False: return 'DEGRADED'`
    check causes this test to FAIL with AssertionError: 'OK' != 'DEGRADED'.
    """
    from src.tools.healthprobe.core import _service_verdict
    from src.tools.processmanager.nssm import ServiceState

    verdict = _service_verdict("ArcisWatchLoop", ServiceState.RUNNING, False, None)
    assert verdict == "DEGRADED", f"RUNNING+stale must be DEGRADED, got {verdict!r}"
