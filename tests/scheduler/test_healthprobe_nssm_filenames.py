"""NSSM-seam boundary-touch tests — HealthProbe service-name + filename contract.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: HealthProbe's _HEARTBEAT_SOURCES and _LOG_SOURCES lambdas derive REAL
file paths from the REAL ArcisConfig. The contract is that:
  1. Each configured service name resolves to a non-None path getter.
  2. The watchdog_heartbeat path comes from cfg.paths.watchdog_heartbeat (not
     hard-coded), so a config drift would be caught.
  3. The "mtime" mode services (OllamaWatchdog, Dashboard) resolve filenames
     that contain the expected stem (ollama_watchdog.out.log, dashboard-stdout.log).
  4. The _verdict_matrix maps (STOPPED, *, *) -> DOWN reliably.

These are non-vacuous because they drive the REAL config loading path and
the REAL dict lookups in core.py — not mocks. Non-vacuity proved by:
  1. Renamed cfg.paths.watchdog_heartbeat -> cfg.paths.bogus_hb in a scratch
     edit of the lambda in core.py: test_watchloop_heartbeat_path_matches_config
     FAILED (AttributeError / path mismatch).
  2. Changed _HEARTBEAT_SOURCES["ArcisOllamaWatchdog"] getter to return
     cfg.paths.logs_runtime / "wrong.log": test_ollama_log_filename_correct FAILED
     (AssertionError: 'ollama_watchdog.out.log' not in 'wrong.log').
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


def test_ollama_log_filename_correct():
    """_HEARTBEAT_SOURCES['ArcisOllamaWatchdog'] derives a path ending in ollama_watchdog.out.log.

    Non-vacuity: changing the filename in the getter to 'wrong.log' causes
    this test to FAIL with AssertionError on the name check.
    """
    from src.tools._config import load_arcis_config
    from src.tools.healthprobe.core import _HEARTBEAT_SOURCES

    cfg = load_arcis_config()
    getter, mode = _HEARTBEAT_SOURCES["ArcisOllamaWatchdog"]
    derived_path = getter(cfg)

    assert derived_path.name == "ollama_watchdog.out.log", (
        f"Ollama heartbeat path has wrong filename: {derived_path.name!r}"
    )
    assert mode == "mtime", f"Ollama heartbeat mode must be 'mtime', got {mode!r}"


def test_dashboard_log_filename_correct():
    """_HEARTBEAT_SOURCES['ArcisDashboard'] derives a path ending in dashboard-stdout.log.

    Non-vacuity: changing the filename in the getter causes an AssertionError.
    """
    from src.tools._config import load_arcis_config
    from src.tools.healthprobe.core import _HEARTBEAT_SOURCES

    cfg = load_arcis_config()
    getter, mode = _HEARTBEAT_SOURCES["ArcisDashboard"]
    derived_path = getter(cfg)

    assert derived_path.name == "dashboard-stdout.log", (
        f"Dashboard heartbeat path has wrong filename: {derived_path.name!r}"
    )
    assert mode == "mtime", f"Dashboard heartbeat mode must be 'mtime', got {mode!r}"


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
