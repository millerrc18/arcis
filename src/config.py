"""Configuration loader for the Systematic Equity Research.

Loads settings from config/settings.local.yaml, falling back to
config/settings.example.yaml if the local file does not exist.
Caches the config after first load.
"""

import sys
from pathlib import Path

import yaml

_config_cache: dict | None = None


def load_config() -> dict:
    """Load and return the application configuration dict (cached)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_dir = Path(__file__).resolve().parent.parent / "config"
    local_path = config_dir / "settings.local.yaml"
    example_path = config_dir / "settings.example.yaml"

    if local_path.exists():
        config_path = local_path
    elif example_path.exists():
        print(
            "WARNING: config/settings.local.yaml not found, "
            "falling back to config/settings.example.yaml",
            file=sys.stderr,
        )
        config_path = example_path
    else:
        print("ERROR: No configuration file found.", file=sys.stderr)
        return {}

    with open(config_path, "r") as f:
        _config_cache = yaml.safe_load(f) or {}

    return _config_cache


def get_config() -> dict:
    """Return the cached config (loads from disk if not cached yet)."""
    return load_config()


def reload_config() -> dict:
    """Force re-read of config from disk."""
    global _config_cache
    _config_cache = None
    return load_config()
