"""ContractCheck v1 — record, verify, and diff nvidia-smi (and future CLI) baselines.

Purpose: Guard against silent drift in pinned external-CLI invocations. Records
         a timestamped JSON baseline from a live subprocess call, then verifies
         subsequent calls against that baseline. Detects both value drift (calibrated
         per-field tolerances) and shape drift ([N/A] sentinels where floats were
         expected — the v0.36.29 north-star regression class).

Called by: src.tools.contractcheck.__main__ (CLI surface), operator agents
Calls: src.tools._config.load_arcis_config, src.tools._subprocess.run,
       src.tools._subprocess.resolve_exe, src.tools._safety.safe_op
Owns tables: none
Config keys: contracts (arcis_config.yaml)
Tests: tests/tools/test_contractcheck.py (T6)
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.tools._config import ContractDef, load_arcis_config
from src.tools._safety import safe_op
from src.tools._subprocess import NvidiaSmiMissingError, resolve_exe
from src.tools import _subprocess


# ── Error hierarchy ──────────────────────────────────────────────────


class ContractCheckError(RuntimeError):
    """Root error for all ContractCheck failures."""


class ContractNotConfiguredError(ContractCheckError):
    """Raised when the requested contract name is not present in arcis_config.yaml."""


class BaselineNotFoundError(ContractCheckError):
    """Raised when latest_ref.txt is missing or references a nonexistent file."""


class BaselineCorruptError(ContractCheckError):
    """Raised when a baseline JSON fails to parse or is missing required fields."""


class ContractInvocationError(ContractCheckError):
    """Raised when the contracted subprocess returns non-zero or times out."""


# ── Constants ────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS_DIR = _REPO_ROOT / "data" / "contracts"
_REQUIRED_BASELINE_FIELDS = frozenset(
    ["contract", "recorded_at", "cmd", "returncode", "stdout", "stderr", "parsed_fields", "parse_ok"]
)


# ── Internal helpers ─────────────────────────────────────────────────


def _timestamp_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + ".json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _contract_dir(name: str) -> Path:
    return _CONTRACTS_DIR / name


def _parse_fields(stdout: str, parse_fields: list[str]) -> tuple[dict, bool]:
    if not parse_fields:
        return {"stdout": stdout.strip()}, True
    parts = [p.strip() for p in stdout.strip().split(",")]
    if len(parts) != len(parse_fields):
        raw = {name: parts[i] if i < len(parts) else None for i, name in enumerate(parse_fields)}
        return raw, False
    result: dict = {}
    parse_ok = True
    for name, raw_val in zip(parse_fields, parts):
        try:
            result[name] = float(raw_val)
        except (ValueError, TypeError):
            result[name] = raw_val
            parse_ok = False
    return result, parse_ok


def _apply_at_capture_redact(text: str, contract: ContractDef) -> tuple[str, int]:
    redacted = text
    count = 0
    for rule in contract.normalize.values():
        for pattern in rule.at_capture_redact:
            redacted = re.sub(pattern, "<REDACTED>", redacted)
            count += 1
    return redacted, count


def _build_normalization_applied(contract: ContractDef, redact_count: int) -> dict:
    applied: dict[str, str] = {}
    for field_name, rule in contract.normalize.items():
        parts = []
        if rule.tolerance is not None:
            parts.append(f"tolerance={rule.tolerance}")
        if rule.mask_regex is not None:
            parts.append(f"mask_regex={rule.mask_regex!r}")
        if rule.ignore:
            parts.append("ignore=True")
        if rule.at_capture_redact:
            parts.append(f"at_capture_redact: {len(rule.at_capture_redact)} patterns applied")
        if parts:
            applied[field_name] = ", ".join(parts)
    if redact_count > 0 and not any("at_capture_redact" in v for v in applied.values()):
        applied["_global"] = f"at_capture_redact: {redact_count} patterns applied"
    return applied


def _normalize_value(value, mask_regex: str | None):
    if mask_regex is not None and re.search(mask_regex, str(value)):
        return "<MASKED>"
    return value


def _compare_field(baseline_val, live_val, rule) -> str:
    """Return match | tolerance | mismatch | shape_change."""
    if rule is not None and rule.ignore:
        return "match"
    if rule is not None:
        baseline_val = _normalize_value(baseline_val, rule.mask_regex)
        live_val = _normalize_value(live_val, rule.mask_regex)
    if baseline_val == live_val:
        return "match"
    if rule is not None and rule.tolerance is not None:
        try:
            if abs(float(baseline_val) - float(live_val)) <= rule.tolerance:
                return "tolerance"
            return "mismatch"
        except (ValueError, TypeError):
            return "shape_change"
    # No tolerance: check shape — if one is float-parseable and the other isn't
    b_ok = _is_float(baseline_val)
    l_ok = _is_float(live_val)
    return "shape_change" if b_ok != l_ok else "mismatch"


def _is_float(v) -> bool:
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False


def _invoke_contract(contract: ContractDef) -> tuple[str, str, int]:
    resolve_exe(contract.cmd[0])
    result = _subprocess.run(contract.cmd, timeout=contract.timeout_s)
    if result.returncode != 0:
        raise ContractInvocationError(
            f"Contract cmd {contract.cmd!r} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout, result.stderr, result.returncode


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, path)


def _load_baseline(name: str, filename: str) -> dict:
    baseline_path = _contract_dir(name) / filename
    if not baseline_path.exists():
        raise BaselineNotFoundError(f"Baseline file not found: {baseline_path!s}")
    try:
        with baseline_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise BaselineCorruptError(f"Baseline JSON at {baseline_path!s} is malformed: {e}") from e
    missing = _REQUIRED_BASELINE_FIELDS - set(data.keys())
    if missing:
        raise BaselineCorruptError(
            f"Baseline at {baseline_path!s} is missing required fields: {sorted(missing)}"
        )
    return data


def _load_latest_baseline(name: str) -> tuple[dict, Path]:
    latest_ref = _contract_dir(name) / "latest_ref.txt"
    if not latest_ref.exists():
        raise BaselineNotFoundError(f"No latest_ref.txt for contract '{name}': run `record` first.")
    filename = latest_ref.read_text(encoding="utf-8").strip()
    if not filename:
        raise BaselineNotFoundError(f"latest_ref.txt for contract '{name}' is empty.")
    return _load_baseline(name, filename), _contract_dir(name) / filename


def _fields_diff(baseline_fields: dict, live_fields: dict, normalize: dict) -> tuple[dict, str]:
    fields: dict[str, dict] = {}
    has_drift = False
    for field_name in sorted(set(baseline_fields) | set(live_fields)):
        rule = normalize.get(field_name)
        if rule is not None and rule.ignore:
            continue
        b_val = baseline_fields.get(field_name)
        l_val = live_fields.get(field_name)
        status = _compare_field(b_val, l_val, rule)
        fields[field_name] = {"baseline": b_val, "live": l_val, "status": status}
        if status in ("mismatch", "shape_change"):
            has_drift = True
    return fields, "DRIFT" if has_drift else "PASS"


def _redact_parsed(parsed: dict, contract: ContractDef) -> dict:
    result = {}
    for k, v in parsed.items():
        if isinstance(v, str):
            rv, _ = _apply_at_capture_redact(v, contract)
            result[k] = rv
        else:
            result[k] = v
    return result


# ── Public API ───────────────────────────────────────────────────────


@safe_op(name="contractcheck", mutates=False)
def record(name: str, *, config_path: Optional[Path] = None) -> Path:
    """Invoke contract `name`, write a new timestamped baseline, update latest_ref.txt.

    Returns the absolute Path of the newly written baseline JSON.
    Raises:
      - ContractNotConfiguredError: name is not present in arcis_config.yaml's contracts.
      - NvidiaSmiMissingError: the contracted exe is not on PATH.
      - ContractInvocationError: subprocess returned non-zero or timed out.
    """
    cfg = load_arcis_config(path=config_path)
    if name not in cfg.contracts:
        raise ContractNotConfiguredError(
            f"Contract '{name}' not found in arcis_config.yaml. "
            f"Available: {sorted(cfg.contracts.keys())}"
        )
    contract = cfg.contracts[name]
    stdout, stderr, returncode = _invoke_contract(contract)

    # DA2: apply at_capture_redact BEFORE writing
    redacted_stdout, redact_count = _apply_at_capture_redact(stdout, contract)
    parsed_fields, parse_ok = _parse_fields(redacted_stdout, contract.parse_fields)
    parsed_fields = _redact_parsed(parsed_fields, contract)
    normalization_applied = _build_normalization_applied(contract, redact_count)

    baseline: dict = {
        "contract": name,
        "recorded_at": _iso_now(),
        "cmd": contract.cmd,
        "description": contract.description,
        "timeout_s": contract.timeout_s,
        "returncode": returncode,
        "stdout": redacted_stdout,
        "stderr": stderr,
        "parsed_fields": parsed_fields,
        "parse_ok": parse_ok,
        "normalization_applied": normalization_applied,
        "tool_version": "v1",
    }

    timestamp_filename = _timestamp_filename()
    contract_dir = _contract_dir(name)
    baseline_path = contract_dir / timestamp_filename
    _atomic_write(baseline_path, json.dumps(baseline, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(contract_dir / "latest_ref.txt", timestamp_filename)
    return baseline_path.resolve()


@safe_op(name="contractcheck", mutates=False)
def verify(name: str, *, config_path: Optional[Path] = None) -> dict:
    """Invoke contract `name`, compare against latest_ref baseline, return diff dict.

    Returns a dict with keys: contract, baseline_path, baseline_timestamp,
    live_invocation_ok, fields, verdict.
    Raises BaselineNotFoundError if no latest_ref exists for this contract.
    Does NOT raise on field drift — drift is signaled via verdict='DRIFT'.
    Raises ContractNotConfiguredError if name is not configured.
    """
    cfg = load_arcis_config(path=config_path)
    if name not in cfg.contracts:
        raise ContractNotConfiguredError(
            f"Contract '{name}' not found in arcis_config.yaml. "
            f"Available: {sorted(cfg.contracts.keys())}"
        )
    contract = cfg.contracts[name]
    baseline_data, baseline_path = _load_latest_baseline(name)

    try:
        stdout, _stderr, _rc = _invoke_contract(contract)
    except Exception:
        return {
            "contract": name,
            "baseline_path": str(baseline_path.resolve()),
            "baseline_timestamp": baseline_data.get("recorded_at", ""),
            "live_invocation_ok": False,
            "fields": {},
            "verdict": "INVOCATION_FAILED",
        }

    # DA2: re-apply at_capture_redact to live stdout before comparison
    redacted_live, _ = _apply_at_capture_redact(stdout, contract)
    live_parsed, _ = _parse_fields(redacted_live, contract.parse_fields)
    live_parsed = _redact_parsed(live_parsed, contract)

    fields, verdict = _fields_diff(baseline_data.get("parsed_fields", {}), live_parsed, contract.normalize)
    return {
        "contract": name,
        "baseline_path": str(baseline_path.resolve()),
        "baseline_timestamp": baseline_data.get("recorded_at", ""),
        "live_invocation_ok": True,
        "fields": fields,
        "verdict": verdict,
    }


@safe_op(name="contractcheck", mutates=False)
def diff(
    name: str,
    baseline_a: str,
    baseline_b: str,
    *,
    config_path: Optional[Path] = None,
) -> dict:
    """Compare two recorded baselines (by filename) within data/contracts/<name>/.

    Useful for operator forensics: what changed between two recordings?
    Same return shape as verify() but with baseline_a / baseline_b as keys.
    Raises BaselineNotFoundError, BaselineCorruptError, ContractNotConfiguredError.
    """
    cfg = load_arcis_config(path=config_path)
    if name not in cfg.contracts:
        raise ContractNotConfiguredError(
            f"Contract '{name}' not found in arcis_config.yaml. "
            f"Available: {sorted(cfg.contracts.keys())}"
        )
    contract = cfg.contracts[name]
    data_a = _load_baseline(name, baseline_a)
    data_b = _load_baseline(name, baseline_b)
    fields_a = data_a.get("parsed_fields", {})
    fields_b = data_b.get("parsed_fields", {})

    fields: dict[str, dict] = {}
    has_drift = False
    for field_name in sorted(set(fields_a) | set(fields_b)):
        rule = contract.normalize.get(field_name)
        if rule is not None and rule.ignore:
            continue
        val_a = fields_a.get(field_name)
        val_b = fields_b.get(field_name)
        status = _compare_field(val_a, val_b, rule)
        fields[field_name] = {"baseline_a": val_a, "baseline_b": val_b, "status": status}
        if status in ("mismatch", "shape_change"):
            has_drift = True

    return {
        "contract": name,
        "baseline_a": baseline_a,
        "baseline_b": baseline_b,
        "baseline_a_timestamp": data_a.get("recorded_at", ""),
        "baseline_b_timestamp": data_b.get("recorded_at", ""),
        "fields": fields,
        "verdict": "DRIFT" if has_drift else "PASS",
    }
