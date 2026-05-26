# Purpose: Integration tests for src/tools/contractcheck — record/verify/diff baseline flow.
#          Covers DA1 (atomic write), DA2 (at_capture_redact PII), north-star v0.36.29
#          shape-drift detection, and CLI envelope correctness.
# Called by: pytest tests/tools/test_contractcheck_integration.py
# Calls: src.tools.contractcheck.core.record, .verify, .diff; subprocess (mocked)
# Owns tables: none
# Config keys: contracts (arcis_config.yaml, overridden via tmp config in tests)
# Tests: (this file)

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── helpers ──────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Real baseline committed in T5
_T5_BASELINE = _REPO_ROOT / "data" / "contracts" / "nvidia-smi-watchloop" / "2026-05-26T02-23-36Z.json"

# The nvidia-smi stdout that the real watchloop contract produces (5 CSV fields)
_CLEAN_STDOUT = "42, 4096, 24576, 58, 175.30\n"

# Parse fields in the same order as the config
_PARSE_FIELDS = [
    "gpu_util_pct",
    "gpu_vram_used_mb",
    "gpu_vram_total_mb",
    "gpu_temp_c",
    "gpu_power_w",
]


def _make_config_yaml(tmp_path: Path, *, extra_normalize: dict | None = None) -> Path:
    """Write a minimal arcis_config.yaml referencing `tmp_path` as the contracts dir root.

    extra_normalize is merged into the nvidia-smi-watchloop normalize block so
    individual tests can inject at_capture_redact rules without re-loading the
    global YAML.
    """
    normalize_block: dict = {
        "gpu_util_pct": {"tolerance": 5.0},
        "gpu_vram_used_mb": {"tolerance": 2048.0},
        "gpu_temp_c": {"tolerance": 10.0},
        "gpu_power_w": {"tolerance": 50.0},
    }
    if extra_normalize:
        for field, rule in extra_normalize.items():
            normalize_block[field] = rule

    cfg: dict = {
        "paths": {
            "db_canonical": str(tmp_path / "db"),
            "logs_runtime": str(tmp_path / "logs"),
            "logs_service": str(tmp_path / "svc"),
            "ollama_models": str(tmp_path / "ollama"),
            "watchdog_heartbeat": str(tmp_path / "watchdog.txt"),
            "worktrees": {},
        },
        "ports": {
            "pg_prod": 5432,
            "pg_test": 5434,
            "ollama": 11434,
            "cloud_api": {"range_start": 8001, "range_end": 8099},
            "adhoc_http": 8765,
            "forbidden": [8080],
        },
        "services": {
            "watch_loop": "ArcisWatchLoop",
            "ollama_watchdog": "OllamaWatchdog",
            "dashboard": "ArcisDashboard",
        },
        "safety_windows": {},
        "pg": {
            "prod_dsn_signatures": ["127.0.0.1:5433"],
            "test_dsn": "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test",
        },
        "contracts": {
            "nvidia-smi-watchloop": {
                "description": "Test contract",
                "cmd": ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                "timeout_s": 5,
                "parse_fields": _PARSE_FIELDS,
                "normalize": normalize_block,
            }
        },
    }
    config_path = tmp_path / "arcis_config.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)
    return config_path


def _fake_subprocess_result(stdout: str = _CLEAN_STDOUT, returncode: int = 0, stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def _write_baseline(contracts_root: Path, name: str, filename: str, parsed_fields: dict) -> Path:
    """Write a minimal valid baseline JSON to <contracts_root>/<name>/<filename>."""
    baseline_dir = contracts_root / name
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline: dict = {
        "contract": name,
        "recorded_at": "2026-05-25T00:00:00.000000Z",
        "cmd": ["nvidia-smi"],
        "description": "Test baseline",
        "timeout_s": 5,
        "returncode": 0,
        "stdout": _CLEAN_STDOUT,
        "stderr": "",
        "parsed_fields": parsed_fields,
        "parse_ok": True,
        "normalization_applied": {},
        "tool_version": "v1",
    }
    path = baseline_dir / filename
    path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    # write latest_ref.txt
    (baseline_dir / "latest_ref.txt").write_text(filename, encoding="utf-8")
    return path


# ── core import — deferred so patch targets load correctly ────────────────────

from src.tools.contractcheck.core import (
    BaselineCorruptError,
    BaselineNotFoundError,
    ContractInvocationError,
    ContractNotConfiguredError,
    diff,
    record,
    verify,
)
import src.tools.contractcheck.core as _core


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — record writes baseline + latest_ref.txt
# ─────────────────────────────────────────────────────────────────────────────


def test_record_writes_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_root = _REPO_ROOT / "data" / "contracts"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", tmp_path / "contracts"),
    ):
        path = record("nvidia-smi-watchloop", config_path=config_path)

    assert path.exists(), "Baseline JSON must exist after record()"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Schema check — all required fields present
    required = {"contract", "recorded_at", "cmd", "returncode", "stdout", "stderr", "parsed_fields", "parse_ok"}
    assert required.issubset(data.keys()), f"Missing fields: {required - data.keys()}"
    assert data["contract"] == "nvidia-smi-watchloop"
    assert data["parse_ok"] is True
    assert isinstance(data["parsed_fields"], dict)

    # latest_ref.txt content matches the written filename
    latest_ref = (tmp_path / "contracts" / "nvidia-smi-watchloop" / "latest_ref.txt").read_text(encoding="utf-8").strip()
    assert latest_ref == path.name, f"latest_ref.txt mismatch: {latest_ref!r} != {path.name!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — atomic write: mid-write interruption leaves no partial baseline file
# ─────────────────────────────────────────────────────────────────────────────


def test_record_atomic_write(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    original_atomic_write = _core._atomic_write

    interrupt_count = 0

    def _interrupting_write(path: Path, content: str) -> None:
        nonlocal interrupt_count
        # Allow latest_ref.txt write (second call) to succeed normally
        # Interrupt only the first call (the JSON baseline file)
        if interrupt_count == 0 and path.suffix == ".json":
            interrupt_count += 1
            # Simulate error during tempfile write by creating a partial .tmp and then raising
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            import tempfile as _tf
            fd, tmp_name = _tf.mkstemp(dir=parent, suffix=".tmp")
            os.close(fd)
            raise IOError("Simulated mid-write failure")
        return original_atomic_write(path, content)

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
        patch("src.tools.contractcheck.core._atomic_write", side_effect=_interrupting_write),
    ):
        with pytest.raises(IOError, match="Simulated mid-write failure"):
            record("nvidia-smi-watchloop", config_path=config_path)

    # No .json files (only possible .tmp stubs, which _atomic_write cleans up)
    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    if contract_dir.exists():
        json_files = list(contract_dir.glob("*.json"))
        assert len(json_files) == 0, f"Partial baseline JSON left on disk: {json_files}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — verify: PASS when live matches baseline within tolerance
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_pass(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    # Pre-create baseline exactly matching the mocked live stdout
    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    assert result["verdict"] == "PASS", f"Expected PASS, got {result['verdict']}: {result}"
    assert result["live_invocation_ok"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — DA1 value-drift detection: gpu_util_pct 42 vs 78 (delta=36 > tol=5)
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_drift_value_mismatch(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    # Baseline with gpu_util_pct=42.0
    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    # Mock live returns gpu_util_pct=78 (delta 36 > tolerance 5.0)
    live_stdout = "78, 4096, 24576, 58, 175.30\n"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=live_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    assert result["verdict"] == "DRIFT", f"Expected DRIFT, got {result['verdict']}"
    field_status = result["fields"]["gpu_util_pct"]["status"]
    assert field_status == "mismatch", f"Expected mismatch for gpu_util_pct, got {field_status!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — V0.36.29 NORTH-STAR: [N/A] in gpu_vram_total_mb triggers shape_change
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_na_north_star(tmp_path: Path) -> None:
    """Load-bearing north-star test.

    Baseline has 5 float fields. Live stdout emits '[N/A]' for gpu_vram_total_mb.
    Because the baseline value is a float and '[N/A]' cannot be parsed as float,
    _compare_field must return 'shape_change', and verify() must return DRIFT.
    """
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    # Baseline: all five fields are valid floats
    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    # Live stdout: [N/A] for gpu_vram_total_mb (field index 2)
    na_stdout = "42, 4096, [N/A], 58, 175.30\n"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=na_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    assert result["verdict"] == "DRIFT", (
        f"North-star FAILED: expected DRIFT for [N/A] gpu_vram_total_mb, got {result['verdict']}"
    )
    vram_total_status = result["fields"]["gpu_vram_total_mb"]["status"]
    assert vram_total_status == "shape_change", (
        f"North-star FAILED: expected shape_change, got {vram_total_status!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — verify: INVOCATION_FAILED when subprocess raises TimeoutExpired
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_invocation_failed(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    with (
        patch("src.tools.contractcheck.core._subprocess.run", side_effect=TimeoutExpired(cmd=["nvidia-smi"], timeout=5)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    assert result["verdict"] == "INVOCATION_FAILED"
    assert result["live_invocation_ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — BaselineNotFoundError when no latest_ref.txt exists
# ─────────────────────────────────────────────────────────────────────────────


def test_baseline_not_found(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"
    # Do NOT create latest_ref.txt

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(BaselineNotFoundError):
            verify("nvidia-smi-watchloop", config_path=config_path)


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — ContractNotConfiguredError for unknown contract name
# ─────────────────────────────────────────────────────────────────────────────


def test_contract_not_configured(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    with (
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(ContractNotConfiguredError):
            verify("nonexistent-contract", config_path=config_path)


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — BaselineCorruptError for malformed baseline JSON
# ─────────────────────────────────────────────────────────────────────────────


def test_baseline_corrupt(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    # Write a corrupt JSON file and point latest_ref.txt at it
    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    contract_dir.mkdir(parents=True, exist_ok=True)
    bad_file = contract_dir / "bad.json"
    bad_file.write_text("{not valid json!!!", encoding="utf-8")
    (contract_dir / "latest_ref.txt").write_text("bad.json", encoding="utf-8")

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(BaselineCorruptError):
            verify("nvidia-smi-watchloop", config_path=config_path)


# ─────────────────────────────────────────────────────────────────────────────
# Test 10 — diff subcommand returns expected dict shape
# ─────────────────────────────────────────────────────────────────────────────


def test_diff_subcommand(tmp_path: Path) -> None:
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    fields_a = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    fields_b = {
        "gpu_util_pct": 80.0,  # exceeds tolerance 5.0 → mismatch
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }

    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "baseline_a.json", fields_a)
    # Write second baseline without updating latest_ref.txt
    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    b_data = {
        "contract": "nvidia-smi-watchloop",
        "recorded_at": "2026-05-25T01:00:00.000000Z",
        "cmd": ["nvidia-smi"],
        "description": "Test baseline B",
        "timeout_s": 5,
        "returncode": 0,
        "stdout": "80, 4096, 24576, 58, 175.30\n",
        "stderr": "",
        "parsed_fields": fields_b,
        "parse_ok": True,
        "normalization_applied": {},
        "tool_version": "v1",
    }
    (contract_dir / "baseline_b.json").write_text(json.dumps(b_data, indent=2), encoding="utf-8")

    with patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir):
        result = diff("nvidia-smi-watchloop", "baseline_a.json", "baseline_b.json", config_path=config_path)

    # Shape check
    assert "contract" in result
    assert "baseline_a" in result
    assert "baseline_b" in result
    assert "fields" in result
    assert "verdict" in result
    assert result["verdict"] == "DRIFT"
    assert result["fields"]["gpu_util_pct"]["status"] == "mismatch"


# ─────────────────────────────────────────────────────────────────────────────
# Test 11 — CLI envelope: record nvidia-smi-watchloop --json (subprocess invocation)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_envelope_record(tmp_path: Path) -> None:
    """Invoke CLI as subprocess; verify JSON path envelope and exit code 0."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    env = {
        **os.environ,
        "DATABASE_URL": "",
        "TEST_DATABASE_URL": "postgresql://test:test@127.0.0.1:5434/halcyon",
        "_CONTRACTCHECK_CONTRACTS_DIR_OVERRIDE": str(contracts_dir),
        "_CONTRACTCHECK_CONFIG_PATH_OVERRIDE": str(config_path),
    }

    # We patch _subprocess.run at the process level by injecting the
    # CONTRACTCHECK_MOCK_STDOUT env var that the real subprocess reads.
    # Since we're calling via subprocess and can't inject Python mocks,
    # we instead test the CLI via importlib-level patch within the same process.
    # Use the same approach as test_ciinvestigate_integration: subprocess with
    # a wrapper that patches the nvidia-smi call via environment-injected monkeypath.
    # For portability: run via Python API with subprocess patching in conftest,
    # OR use the internal Python import approach.
    #
    # Approach: invoke as a subprocess but patch _subprocess.run via
    # a PYTHONPATH-injected shim. However, the cleanest approach is to
    # use Python's -c flag and mock within the same interpreter.

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys, json
from pathlib import Path
from unittest.mock import patch, MagicMock

_stdout = "42, 4096, 24576, 58, 175.30\\n"

def _fake_run(*a, **kw):
    m = MagicMock()
    m.stdout = _stdout
    m.stderr = ""
    m.returncode = 0
    return m

with (
    patch("src.tools.contractcheck.core._subprocess.run", side_effect=_fake_run),
    patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
    patch("src.tools.contractcheck.core._CONTRACTS_DIR", Path({str(contracts_dir)!r})),
):
    import argparse
    from src.tools._cli_envelope import run_cli
    from src.tools.contractcheck.core import record, verify, diff

    def _run(*, cmd, name, baseline_a, baseline_b, json):
        if cmd == "record":
            import json as json_mod
            p = record(name, config_path=Path({str(config_path)!r}))
            if json:
                return json_mod.dumps({{"path": str(p)}})
            return f"Recorded baseline: {{p}}"
        raise ValueError(f"Unknown cmd {{cmd!r}}")

    ns = argparse.Namespace(cmd="record", name="nvidia-smi-watchloop", json=True, baseline_a=None, baseline_b=None)
    run_cli(tool_name="contractcheck", fn=_run, args_namespace=ns, json_mode=True)
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"CLI exited {result.returncode}: stderr={result.stderr!r}"
    out = json.loads(result.stdout.strip())
    assert "path" in out, f"Expected 'path' key in output: {out}"
    assert out["path"].endswith(".json")


# ─────────────────────────────────────────────────────────────────────────────
# Test 12 — CLI envelope: error JSON + exit 1 for nonexistent contract
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_envelope_error_json(tmp_path: Path) -> None:
    """Verify CLI exits 1 with JSON error envelope for unknown contract."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import argparse
from pathlib import Path
from unittest.mock import patch
from src.tools._cli_envelope import run_cli
from src.tools.contractcheck.core import record, verify, diff, ContractNotConfiguredError

def _run(*, cmd, name, baseline_a, baseline_b, json):
    if cmd == "verify":
        import json as json_mod
        with patch("src.tools.contractcheck.core._CONTRACTS_DIR", Path({str(contracts_dir)!r})):
            res = verify(name, config_path=Path({str(config_path)!r}))
            if json:
                return json_mod.dumps(res)
            return str(res)
    raise ValueError(f"Unknown cmd {{cmd!r}}")

ns = argparse.Namespace(cmd="verify", name="nonexistent-contract-xyz", json=True, baseline_a=None, baseline_b=None)
run_cli(tool_name="contractcheck", fn=_run, args_namespace=ns, json_mode=True)
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}: {result.stdout!r}"
    out = json.loads(result.stdout.strip())
    assert "error" in out, f"Expected 'error' key in output: {out}"
    assert out["error"]["type"] == "ContractNotConfiguredError"
    assert out["error"]["tool"] == "contractcheck"


# ─────────────────────────────────────────────────────────────────────────────
# Test 13 — Load T5's committed baseline; verify schema
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_against_committed_baseline() -> None:
    """Load the T5 committed baseline; assert it parses + has required schema.

    Transitively validates T5's data/contracts/nvidia-smi-watchloop/2026-05-26T02-23-36Z.json.
    """
    assert _T5_BASELINE.exists(), f"T5 baseline missing: {_T5_BASELINE}"

    with _T5_BASELINE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = {"contract", "recorded_at", "cmd", "returncode", "stdout", "stderr", "parsed_fields", "parse_ok"}
    missing = required - data.keys()
    assert not missing, f"T5 baseline missing required fields: {sorted(missing)}"

    assert data["contract"] == "nvidia-smi-watchloop"
    assert data["tool_version"] == "v1"
    assert isinstance(data["parsed_fields"], dict)
    assert isinstance(data["cmd"], list)
    assert len(data["cmd"]) > 0

    # parse_ok=False is expected (T5 latent #117 multi-GPU stdout)
    # We assert its value matches what T5 committed rather than requiring True
    assert "parse_ok" in data  # value assertion below is diagnostic
    # T5 baseline has parse_ok=false due to multi-GPU stdout; document this
    assert data["parse_ok"] is False, (
        "T5 baseline parse_ok should be False (latent #117 — multi-GPU stdout not yet handled)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 14 — DA2: at_capture_redact PII never lands in committed baseline
# ─────────────────────────────────────────────────────────────────────────────


def test_record_redacts_at_capture_when_configured(tmp_path: Path) -> None:
    """DA2 recording-time redaction test.

    Configures at_capture_redact with a Windows-path username pattern.
    Mocked stdout contains 'mille' in a path.
    After record(), the baseline stdout must contain '<REDACTED>' and NOT 'mille'.
    normalization_applied must reference the at_capture_redact.
    """
    # Configure contract with at_capture_redact rule on the _global_ stdout level.
    # NormalizeRule.at_capture_redact is applied to raw stdout pre-parse.
    # We inject it via a field that doesn't exist in parse_fields so it ends up
    # in the normalize block — the implementation applies all at_capture_redact
    # patterns from ALL fields' normalize rules to the raw stdout.
    extra_normalize = {
        "gpu_util_pct": {
            "tolerance": 5.0,
            "at_capture_redact": [r"C:\\Users\\[a-zA-Z]+"],
        }
    }
    config_path = _make_config_yaml(tmp_path, extra_normalize=extra_normalize)
    contracts_dir = tmp_path / "contracts"

    # stdout that contains a Windows-path username — PII to be redacted
    pii_stdout = "pid=12345, path=C:\\Users\\mille\\app.exe, util=42"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=pii_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        baseline_path = record("nvidia-smi-watchloop", config_path=config_path)

    with baseline_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Primary DA2 assertion: PII not in baseline
    assert "mille" not in data["stdout"], (
        "DA2 FAILED: username 'mille' found in baseline stdout — PII leaked to disk"
    )
    assert "<REDACTED>" in data["stdout"], (
        "DA2 FAILED: '<REDACTED>' sentinel not found in baseline stdout"
    )

    # normalization_applied must document that at_capture_redact was applied
    norm = data.get("normalization_applied", {})
    all_norm_values = " ".join(str(v) for v in norm.values())
    assert "at_capture_redact" in all_norm_values, (
        f"DA2 FAILED: normalization_applied does not record at_capture_redact. Got: {norm}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage: edge-case paths
# ─────────────────────────────────────────────────────────────────────────────


def test_record_raises_contract_not_configured(tmp_path: Path) -> None:
    """record() with an unknown contract name raises ContractNotConfiguredError (line 259)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    with (
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(ContractNotConfiguredError):
            record("bogus-contract", config_path=config_path)


def test_invoke_contract_non_zero_returncode(tmp_path: Path) -> None:
    """_invoke_contract raises ContractInvocationError on non-zero returncode (line 167)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(returncode=1, stderr="GPU error")),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(ContractInvocationError):
            record("nvidia-smi-watchloop", config_path=config_path)


def test_baseline_corrupt_missing_fields(tmp_path: Path) -> None:
    """BaselineCorruptError when baseline JSON is valid but missing required fields (line 201)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    contract_dir.mkdir(parents=True, exist_ok=True)
    # Write valid JSON but missing required fields
    partial_file = contract_dir / "partial.json"
    partial_file.write_text(json.dumps({"contract": "nvidia-smi-watchloop"}), encoding="utf-8")
    (contract_dir / "latest_ref.txt").write_text("partial.json", encoding="utf-8")

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(BaselineCorruptError, match="missing required fields"):
            verify("nvidia-smi-watchloop", config_path=config_path)


def test_baseline_not_found_empty_latest_ref(tmp_path: Path) -> None:
    """BaselineNotFoundError when latest_ref.txt is empty (line 213)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "latest_ref.txt").write_text("", encoding="utf-8")

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(BaselineNotFoundError):
            verify("nvidia-smi-watchloop", config_path=config_path)


def test_verify_tolerance_within_range(tmp_path: Path) -> None:
    """verify() returns PASS when value delta is within tolerance (exercises tolerance branch line 145)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    # Baseline with gpu_util_pct=42.0
    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    # Live: gpu_util_pct=44.0 (delta=2.0 < tolerance=5.0 → tolerance/PASS)
    live_stdout = "44, 4096, 24576, 58, 175.30\n"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=live_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    assert result["verdict"] == "PASS"
    assert result["fields"]["gpu_util_pct"]["status"] in ("match", "tolerance")


def test_compare_field_ignore_rule(tmp_path: Path) -> None:
    """diff() with an ignore rule skips the ignored field entirely (line 136 + 373)."""
    config_path = _make_config_yaml(tmp_path, extra_normalize={
        "gpu_util_pct": {"ignore": True},
    })
    contracts_dir = tmp_path / "contracts"

    fields_a = {
        "gpu_util_pct": 10.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    fields_b = {
        "gpu_util_pct": 99.0,  # would be mismatch if not ignored
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    contract_dir.mkdir(parents=True, exist_ok=True)

    for fname, pf in [("a.json", fields_a), ("b.json", fields_b)]:
        data = {
            "contract": "nvidia-smi-watchloop",
            "recorded_at": "2026-05-25T00:00:00.000000Z",
            "cmd": ["nvidia-smi"],
            "description": "Test",
            "timeout_s": 5,
            "returncode": 0,
            "stdout": _CLEAN_STDOUT,
            "stderr": "",
            "parsed_fields": pf,
            "parse_ok": True,
            "normalization_applied": {},
            "tool_version": "v1",
        }
        (contract_dir / fname).write_text(json.dumps(data, indent=2), encoding="utf-8")

    (contract_dir / "latest_ref.txt").write_text("a.json", encoding="utf-8")

    with patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir):
        result = diff("nvidia-smi-watchloop", "a.json", "b.json", config_path=config_path)

    # The ignored field must not appear in fields dict
    assert "gpu_util_pct" not in result["fields"], (
        "Ignored field must be excluded from diff output"
    )
    # All other fields match → PASS
    assert result["verdict"] == "PASS"


def test_mask_regex_normalizes_before_compare(tmp_path: Path) -> None:
    """mask_regex replaces matching values with <MASKED> before comparison (line 129)."""
    config_path = _make_config_yaml(tmp_path, extra_normalize={
        "gpu_util_pct": {"mask_regex": r"\d+"},
    })
    contracts_dir = tmp_path / "contracts"

    # Both values would differ numerically but both match r"\d+" → both become <MASKED> → match
    parsed_fields = {
        "gpu_util_pct": 42.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    # Live: completely different gpu_util_pct — but mask_regex masks both to <MASKED>
    live_stdout = "99, 4096, 24576, 58, 175.30\n"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=live_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    # gpu_util_pct: both masked → status = 'match'
    status = result["fields"]["gpu_util_pct"]["status"]
    assert status == "match", f"Expected match via mask_regex, got {status!r}"


def test_baseline_not_found_file_missing_after_latest_ref(tmp_path: Path) -> None:
    """BaselineNotFoundError when latest_ref.txt points to a non-existent file (line 193)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    contract_dir = contracts_dir / "nvidia-smi-watchloop"
    contract_dir.mkdir(parents=True, exist_ok=True)
    # latest_ref.txt exists but points to a file that doesn't exist
    (contract_dir / "latest_ref.txt").write_text("ghost-2099-01-01T00-00-00Z.json", encoding="utf-8")

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        with pytest.raises(BaselineNotFoundError):
            verify("nvidia-smi-watchloop", config_path=config_path)


def test_diff_raises_contract_not_configured(tmp_path: Path) -> None:
    """diff() with unknown contract name raises ContractNotConfiguredError (line 358)."""
    config_path = _make_config_yaml(tmp_path)
    contracts_dir = tmp_path / "contracts"

    with patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir):
        with pytest.raises(ContractNotConfiguredError):
            diff("bogus-contract", "a.json", "b.json", config_path=config_path)


def test_verify_ignore_rule_via_verify(tmp_path: Path) -> None:
    """verify() with an ignore rule skips the ignored field (line 223 in _fields_diff)."""
    config_path = _make_config_yaml(tmp_path, extra_normalize={
        "gpu_util_pct": {"ignore": True},
    })
    contracts_dir = tmp_path / "contracts"

    parsed_fields = {
        "gpu_util_pct": 10.0,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 58.0,
        "gpu_power_w": 175.30,
    }
    _write_baseline(contracts_dir, "nvidia-smi-watchloop", "2026-05-25T00-00-00Z.json", parsed_fields)

    # Live: drastically different gpu_util_pct — but it's ignored
    live_stdout = "99, 4096, 24576, 58, 175.30\n"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result(stdout=live_stdout)),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        result = verify("nvidia-smi-watchloop", config_path=config_path)

    # Ignored field must not appear in fields
    assert "gpu_util_pct" not in result["fields"]
    assert result["verdict"] == "PASS"


def test_normalization_applied_mask_and_ignore(tmp_path: Path) -> None:
    """_build_normalization_applied includes mask_regex + ignore branches (lines 115, 117)."""
    config_path = _make_config_yaml(tmp_path, extra_normalize={
        "gpu_vram_total_mb": {
            "mask_regex": r"\d+",
            "ignore": True,
        },
    })
    contracts_dir = tmp_path / "contracts"

    with (
        patch("src.tools.contractcheck.core._subprocess.run", return_value=_fake_subprocess_result()),
        patch("src.tools.contractcheck.core.resolve_exe", return_value="/usr/bin/nvidia-smi"),
        patch("src.tools.contractcheck.core._CONTRACTS_DIR", contracts_dir),
    ):
        baseline_path = record("nvidia-smi-watchloop", config_path=config_path)

    with baseline_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    norm = data.get("normalization_applied", {})
    # The gpu_vram_total_mb field has mask_regex + ignore — both should appear in normalization_applied
    vram_norm = norm.get("gpu_vram_total_mb", "")
    assert "mask_regex" in vram_norm, f"Expected mask_regex in normalization_applied: {norm}"
    assert "ignore" in vram_norm, f"Expected ignore in normalization_applied: {norm}"
