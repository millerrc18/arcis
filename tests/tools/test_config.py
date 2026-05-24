"""Tests for src.tools._config — arcis_config.yaml loader.

Verifies the loader returns typed config objects with the values from
config/arcis_config.yaml. Per #104 boundary-touch discipline: tests
actually parse the real YAML (not a mock) and assert specific values,
so a future hand-edit to the YAML schema that breaks the parser is
caught immediately.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Smoke + happy-path ────────────────────────────────────────────────


def test_load_arcis_config_default_path_returns_typed_config():
    """Loader called with no arguments reads config/arcis_config.yaml from repo root."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    # Smoke: returned object exposes the four required top-level sections.
    assert cfg.paths is not None
    assert cfg.ports is not None
    assert cfg.services is not None
    assert cfg.safety_windows is not None
    assert cfg.pg is not None


def test_load_arcis_config_paths_are_path_objects():
    """Path values are returned as pathlib.Path, not raw strings."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert isinstance(cfg.paths.db_canonical, Path)
    assert isinstance(cfg.paths.logs_runtime, Path)
    assert isinstance(cfg.paths.logs_service, Path)
    assert isinstance(cfg.paths.ollama_models, Path)
    assert isinstance(cfg.paths.worktrees["main"], Path)
    assert isinstance(cfg.paths.worktrees["dualgpu"], Path)


def test_load_arcis_config_ports_match_yaml_values():
    """Port values match what's declared in arcis_config.yaml."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert cfg.ports.pg_prod == 5433
    assert cfg.ports.pg_test == 5434
    assert cfg.ports.ollama == 11434
    assert cfg.ports.cloud_api.range_start == 8000
    assert cfg.ports.cloud_api.range_end == 8100
    assert cfg.ports.adhoc_http == 8765
    assert 8080 in cfg.ports.forbidden


def test_load_arcis_config_services_match_yaml_values():
    """NSSM service names match reference_watch_loop_management."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert cfg.services.watch_loop == "ArcisWatchLoop"
    assert cfg.services.ollama_watchdog == "ArcisOllamaWatchdog"
    assert cfg.services.dashboard == "ArcisDashboard"


def test_load_arcis_config_safety_windows_includes_no_restart_overnight():
    """The 21:30–22:30 ET overnight window from feedback_no_restart_during_overnight_window."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert "no_restart_overnight" in cfg.safety_windows
    window = cfg.safety_windows["no_restart_overnight"]
    assert window.start_et == "21:30"
    assert window.end_et == "22:30"
    assert "redundant overnight re-launch" in window.reason


def test_load_arcis_config_pg_signatures_match_prod_guard():
    """Prod DSN signatures must match src/simulation/lifecycle/prod_guard.py's _PROD_SIGNATURES.

    Drift between the two = simulator and tools disagree on what 'prod' means,
    which is the failure mode this single-source-of-truth file prevents.
    """
    from src.simulation.lifecycle.prod_guard import _PROD_SIGNATURES
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert set(cfg.pg.prod_dsn_signatures) == set(_PROD_SIGNATURES)


def test_load_arcis_config_pg_test_dsn_is_5434():
    """Canonical test DSN points to the 5434 ephemeral PG."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert "5434" in cfg.pg.test_dsn
    assert "test:test" in cfg.pg.test_dsn


# ── Custom path + isolation ──────────────────────────────────────────


def test_load_arcis_config_accepts_custom_path(tmp_path):
    """Loader accepts an explicit path — for testing in isolation."""
    from src.tools._config import load_arcis_config

    custom_yaml = tmp_path / "custom.yaml"
    custom_yaml.write_text(
        """
paths:
  db_canonical: /tmp/custom.sqlite3
  logs_runtime: /tmp/logs
  logs_service: /tmp/logs-svc
  ollama_models: /tmp/ollama
  worktrees:
    main: /tmp/main
    dualgpu: /tmp/dualgpu
ports:
  pg_prod: 9999
  pg_test: 9998
  ollama: 9997
  cloud_api: {range_start: 7000, range_end: 7100}
  adhoc_http: 6765
  forbidden: [7777]
services:
  watch_loop: TestWatchLoop
  ollama_watchdog: TestOllamaWatchdog
  dashboard: TestDashboard
safety_windows:
  test_window:
    start_et: "10:00"
    end_et: "11:00"
    reason: "test"
pg:
  prod_dsn_signatures: ["test_sig"]
  test_dsn: "postgresql://test@127.0.0.1:9998/test"
""",
        encoding="utf-8",
    )

    cfg = load_arcis_config(path=custom_yaml)

    assert cfg.ports.pg_prod == 9999
    assert cfg.services.watch_loop == "TestWatchLoop"
    assert cfg.paths.db_canonical == Path("/tmp/custom.sqlite3")


# ── Validation / failure modes ───────────────────────────────────────


def test_load_arcis_config_missing_required_field_raises(tmp_path):
    """A YAML missing a required top-level section fails validation."""
    from src.tools._config import load_arcis_config, ArcisConfigError

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("paths:\n  db_canonical: /tmp/x", encoding="utf-8")

    with pytest.raises(ArcisConfigError):
        load_arcis_config(path=bad_yaml)


def test_load_arcis_config_missing_file_raises(tmp_path):
    """A missing file produces a clear error (not a silent fallback)."""
    from src.tools._config import load_arcis_config, ArcisConfigError

    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(ArcisConfigError) as exc_info:
        load_arcis_config(path=missing)

    assert "does-not-exist" in str(exc_info.value)
