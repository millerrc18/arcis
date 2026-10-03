"""Recorder configuration: required/no-default pydantic model, YAML plus
environment secrets, and the data-root guard (I-7).

The process refuses to start when data_root is inside the repo checkout or
inside a cloud-sync folder (Dropbox, Google Drive, OneDrive, iCloud Drive).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, HttpUrl, SecretStr, ValidationError

import arcis
from arcis.recorder.errors import ConfigError

ENV_API_KEY = "ALPACA_API_KEY"
ENV_API_SECRET = "ALPACA_API_SECRET"

CLOUD_SYNC_DIRS = {"dropbox", "google drive", "onedrive", "icloud drive"}


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_requests_per_minute: int
    max_requests_per_day: int


class Retry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float


class Config(BaseModel):
    """All fields required, no defaults, extra="forbid"."""

    model_config = ConfigDict(extra="forbid")

    data_root: Path
    alpaca_base_url: HttpUrl
    alpaca_api_key: SecretStr
    alpaca_api_secret: SecretStr
    universe_name: Literal["sp500", "sp100"]
    universe_source: str
    symbols: list[str]
    rate_limit: RateLimit
    retry: Retry


def _repo_root() -> Path | None:
    """The checkout root when running from a git checkout, else None."""
    path = Path(arcis.__file__).resolve()
    for parent in path.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _guard_data_root(data_root: Path) -> None:
    resolved = data_root.resolve()
    if any(part.lower() in CLOUD_SYNC_DIRS for part in resolved.parts):
        raise ConfigError(
            f"data_root {resolved} is inside a cloud-sync folder; "
            "article text must not live in synced storage (I-7)"
        )
    repo = _repo_root()
    if repo is not None and (resolved == repo or repo in resolved.parents):
        raise ConfigError(
            f"data_root {resolved} is inside the repo checkout {repo}; "
            "article text must not live in the repo (I-7)"
        )


def load_config(config_path: Path, env: Mapping[str, str] | None = None) -> Config:
    """Load recorder.yaml and merge environment secrets. Raises ConfigError
    on any problem: missing file, bad YAML, missing secrets, validation
    failure, or a data_root that fails the guard."""
    env = os.environ if env is None else env
    if not config_path.is_file():
        raise ConfigError(
            f"config file not found: {config_path} "
            "(copy config/recorder.yaml.example and set data_root)"
        )
    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"config file is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("config file must contain a YAML mapping")
    document = dict(raw)
    for var, field in ((ENV_API_KEY, "alpaca_api_key"), (ENV_API_SECRET, "alpaca_api_secret")):
        value = env.get(var)
        if not value:
            raise ConfigError(f"environment variable {var} is not set")
        document[field] = value
    try:
        config = Config(**document)
    except ValidationError as e:
        raise ConfigError(f"invalid configuration: {e}") from e
    _guard_data_root(config.data_root)
    return config
