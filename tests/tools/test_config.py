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


# ── Tier 3 foundation: ContractDef / NormalizeRule / ContractsConfig ─────────


def test_normalize_rule_defaults():
    """NormalizeRule has all-optional fields with correct defaults including DA2 at_capture_redact."""
    from src.tools._config import NormalizeRule

    rule = NormalizeRule()
    assert rule.tolerance is None
    assert rule.mask_regex is None
    assert rule.ignore is False
    assert rule.at_capture_redact == []


def test_normalize_rule_at_capture_redact_field_accepts_list():
    """DA2: at_capture_redact accepts a non-empty list of regex strings."""
    from src.tools._config import NormalizeRule

    rule = NormalizeRule(at_capture_redact=["C:\\\\Users\\\\[a-zA-Z]+", "hostname:[^,]+"])
    assert len(rule.at_capture_redact) == 2
    assert "C:\\\\Users\\\\[a-zA-Z]+" in rule.at_capture_redact


def test_contract_def_defaults():
    """ContractDef has correct defaults for optional fields."""
    from src.tools._config import ContractDef

    contract = ContractDef(
        cmd=["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
        description="test contract",
    )
    assert contract.timeout_s == 10
    assert contract.parse_fields == []
    assert contract.normalize == {}


def test_contracts_config_empty_default():
    """ContractsConfig entries defaults to empty dict."""
    from src.tools._config import ContractsConfig

    cfg = ContractsConfig()
    assert cfg.entries == {}


def test_arcis_config_contracts_field_defaults_to_empty_dict(tmp_path):
    """Backward compat: ArcisConfig.contracts defaults to {} when YAML has no contracts: section."""
    from src.tools._config import load_arcis_config

    yaml_content = """
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
"""
    yaml_path = tmp_path / "no_contracts.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")

    cfg = load_arcis_config(path=yaml_path)
    assert cfg.contracts == {}


def test_arcis_config_contracts_loads_from_yaml(tmp_path):
    """ArcisConfig.contracts section round-trips through YAML load with ContractDef fields."""
    from src.tools._config import load_arcis_config

    yaml_content = """
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
contracts:
  test-contract:
    cmd:
      - nvidia-smi
      - --query-gpu=utilization.gpu
      - --format=csv,noheader,nounits
    description: "test contract"
    timeout_s: 5
    parse_fields:
      - gpu_util_pct
    normalize:
      gpu_util_pct:
        tolerance: 5.0
"""
    yaml_path = tmp_path / "with_contracts.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")

    cfg = load_arcis_config(path=yaml_path)
    assert "test-contract" in cfg.contracts
    contract = cfg.contracts["test-contract"]
    assert contract.timeout_s == 5
    assert contract.parse_fields == ["gpu_util_pct"]
    assert contract.normalize["gpu_util_pct"].tolerance == 5.0


def test_nvidia_smi_watchloop_contract_in_real_config():
    """Real arcis_config.yaml contains nvidia-smi-watchloop with DA1 recalibrated tolerances."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()
    assert "nvidia-smi-watchloop" in cfg.contracts
    contract = cfg.contracts["nvidia-smi-watchloop"]
    assert contract.timeout_s == 5
    assert "gpu_util_pct" in contract.parse_fields
    assert "gpu_vram_used_mb" in contract.parse_fields
    # DA1 recalibrated tolerances
    assert contract.normalize["gpu_util_pct"].tolerance == 5.0
    assert contract.normalize["gpu_vram_used_mb"].tolerance == 2048.0
    assert contract.normalize["gpu_temp_c"].tolerance == 10.0
    assert contract.normalize["gpu_power_w"].tolerance == 50.0


def test_logs_runtime_is_repo_local():
    """logs_runtime must resolve to the repo-local canonical path (fix #119).

    Asserts cfg.paths.logs_runtime ends in 'halcyon-lab/logs' so that a
    hand-edit reverting to the stale 'C:/arcis/logs' is caught immediately.
    Does NOT require the directory to physically exist (CI worktrees lack it).
    """
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()
    # Normalise to forward-slashes for comparison regardless of OS
    path_str = cfg.paths.logs_runtime.as_posix()
    assert path_str.endswith("halcyon-lab/logs"), (
        f"logs_runtime should end with 'halcyon-lab/logs' but got: {path_str!r}. "
        "Expected 'C:/arcis/halcyon-lab/logs' (fix #119); stale value is 'C:/arcis/logs'."
    )
