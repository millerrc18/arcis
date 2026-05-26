"""arcis_config.yaml loader — tooling-side single source of truth.

Per #104 (v0.36.57): all tools under src/tools/ MUST read paths, ports,
service names, and safety windows via this module — NOT hardcode them.
Drift between hardcoded values and arcis_config.yaml is the failure mode
this loader prevents.

Why a dedicated loader (not src/config/__init__.py):
    The app-side loader couples to .env loading and FastAPI startup.
    Tools need to load their config in isolation (e.g., during pytest
    collection BEFORE any app import), so this loader is intentionally
    lean — pyyaml + pydantic, no app dependencies.

Called by: every tool in src/tools/<subpackage>/
Calls: pyyaml.safe_load, pydantic validation
Owns tables: none
Config keys: see config/arcis_config.yaml
Tests: tests/tools/test_config.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


# ── Default config location ─────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "arcis_config.yaml"


# ── Errors ─────────────────────────────────────────────────────────


class ArcisConfigError(RuntimeError):
    """Raised when arcis_config.yaml cannot be loaded or fails schema validation.

    A dedicated error class (not raw FileNotFoundError / ValidationError) so
    tool callers can catch ONE thing and surface a uniform error to the agent.
    """


# ── Schema models ──────────────────────────────────────────────────


class PathsConfig(BaseModel):
    """`paths:` section. All values stored as pathlib.Path."""

    db_canonical: Path
    logs_runtime: Path
    logs_service: Path
    ollama_models: Path
    watchdog_heartbeat: Path = Path("C:/arcis/halcyon-lab/data/watchdog.txt")
    worktrees: dict[str, Path]


class CloudApiPortRange(BaseModel):
    """`ports.cloud_api:` range — ephemeral port range for the dashboard."""

    range_start: int
    range_end: int


class PortsConfig(BaseModel):
    """`ports:` section. `forbidden` is the operator's no-go set."""

    pg_prod: int
    pg_test: int
    ollama: int
    cloud_api: CloudApiPortRange
    adhoc_http: int
    forbidden: list[int] = Field(default_factory=list)


class ServicesConfig(BaseModel):
    """NSSM service names — see reference_watch_loop_management."""

    watch_loop: str
    ollama_watchdog: str
    dashboard: str


class SafetyWindow(BaseModel):
    """A single safety window — operator-declared range when mutations are blocked."""

    start_et: str
    end_et: str
    reason: str

    @field_validator("start_et", "end_et")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        # Compact validation: "HH:MM" 24h format. Keeps error messages clear
        # vs a regex that produces opaque match failures.
        if len(v) != 5 or v[2] != ":":
            raise ValueError(f"expected HH:MM, got {v!r}")
        hh, mm = v.split(":")
        if not (hh.isdigit() and mm.isdigit()):
            raise ValueError(f"expected HH:MM, got {v!r}")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError(f"out-of-range time: {v!r}")
        return v


class PgConfig(BaseModel):
    """Postgres safety signatures — mirrors src/simulation/lifecycle/prod_guard.py."""

    prod_dsn_signatures: list[str]
    test_dsn: str


class NormalizeRule(BaseModel):
    """How to normalize a single parsed field before comparison.

    Four independent knobs (any combination, all optional):
      - tolerance: absolute numeric tolerance (e.g., 0.5 for gpu_temp_c drift
        within half a degree). Applies to fields that successfully parse as float.
      - mask_regex: regex pattern that, if it matches the *string form* of a
        value, replaces the value with the literal '<MASKED>' before comparison.
        Used for timestamp / hostname / instance-id fields that are expected to
        drift on every run.
      - ignore: bool — when True, the field is dropped entirely from the
        normalized snapshot. Use sparingly; an ignored field can never alert.
      - at_capture_redact (DA2 — RECORDING-TIME sanitization): list[str] of regex
        patterns. When recording (NOT verifying), each matched span in the raw
        stdout is replaced with '<REDACTED>' BEFORE the baseline JSON is
        committed. Use for absolute file paths, usernames, hostnames, MAC
        addresses, or any operator-PII that would otherwise be persisted to the
        repo via the baseline commit. This is the inverse of mask_regex: mask
        normalizes at compare-time; at_capture_redact prevents the secret from
        ever being written. Defaults to empty list (no redaction). Applies to
        the WHOLE raw stdout (pre-parse), so callers must compose regexes
        carefully — anything covered by the regex is gone from the baseline
        forever.
    """

    tolerance: float | None = None
    mask_regex: str | None = None
    ignore: bool = False
    at_capture_redact: list[str] = Field(default_factory=list)


class ContractDef(BaseModel):
    """A single named contract — what to invoke, how to parse, how to normalize.

    The `cmd` field is the LITERAL argv passed to nvidia-smi (or another CLI).
    Drift in `cmd` IS itself a contract change — ContractCheck does not
    auto-update cmd; the operator must explicitly re-record.

    `parse_fields` names the positional CSV columns (in the same order as
    --query-gpu emits them) so that ContractCheck can map columns to names.
    For non-CSV contracts (e.g., a 'git --version' string), parse_fields=[]
    signals 'whole-stdout string compare'.
    """

    cmd: list[str]
    description: str
    timeout_s: int = 10
    parse_fields: list[str] = Field(default_factory=list)
    normalize: dict[str, NormalizeRule] = Field(default_factory=dict)


class ContractsConfig(BaseModel):
    """`contracts:` section — keyed by contract name.

    Empty by default. Tier 3's #107 effort seeds it with one entry:
    `nvidia-smi-watchloop` pinning the watchloop's nvidia-smi invocation.
    """

    # The model is just a dict[str, ContractDef] but wrapping in BaseModel
    # gives us validation + a clear named type for the rest of the codebase.
    entries: dict[str, ContractDef] = Field(default_factory=dict)


class ArcisConfig(BaseModel):
    """Top-level tooling config — the object returned by `load_arcis_config()`."""

    paths: PathsConfig
    ports: PortsConfig
    services: ServicesConfig
    safety_windows: dict[str, SafetyWindow]
    pg: PgConfig
    contracts: dict[str, ContractDef] = Field(default_factory=dict)


# ── Loader ─────────────────────────────────────────────────────────


def load_arcis_config(path: Optional[Path] = None) -> ArcisConfig:
    """Load and validate config/arcis_config.yaml (or a custom path).

    Args:
        path: Optional override for testing. Defaults to the canonical
              config/arcis_config.yaml at the repo root.

    Returns:
        Fully-validated ArcisConfig object.

    Raises:
        ArcisConfigError: if the file is missing, unreadable, malformed,
                          or fails schema validation. Wraps the underlying
                          FileNotFoundError / yaml.YAMLError / pydantic
                          ValidationError so callers catch ONE class.
    """
    target = path if path is not None else _DEFAULT_CONFIG_PATH

    if not target.exists():
        raise ArcisConfigError(
            f"arcis_config.yaml not found at {target!s}. "
            "Tools require this file to resolve paths/ports/services."
        )

    try:
        # Windows-UTF-8 gotcha (feedback_windows_utf8_encoding) — be explicit.
        with target.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ArcisConfigError(f"arcis_config.yaml at {target!s} is malformed YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ArcisConfigError(
            f"arcis_config.yaml at {target!s} must contain a top-level mapping, got {type(raw).__name__}"
        )

    try:
        return ArcisConfig(**raw)
    except ValidationError as e:
        raise ArcisConfigError(
            f"arcis_config.yaml at {target!s} failed schema validation:\n{e}"
        ) from e
