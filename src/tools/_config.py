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


class ArcisConfig(BaseModel):
    """Top-level tooling config — the object returned by `load_arcis_config()`."""

    paths: PathsConfig
    ports: PortsConfig
    services: ServicesConfig
    safety_windows: dict[str, SafetyWindow]
    pg: PgConfig


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
