"""Configuration loader for the Systematic Equity Research.

Called by: api.routes.actions, api.routes.scan, api.routes.shadow, api.routes.system, cli.commands, data_collection.analyst_collector, data_collection.insider_collector, data_collection.macro_collector, data_collection.short_interest_collector, email.notifier, evaluation.auditor, evaluation.backtester, evaluation.cto_report, evaluation.system_validator, llm.client, llm.grammar_client, llm.postmortem_writer, main, notifications.telegram, packets.eod_recap, ranking.ranker, risk.governor, scheduler.premarket, scheduler.vram_manager, scheduler.watch, shadow_trading.alpaca_adapter, shadow_trading.executor, training.ab_evaluation, training.bootstrap, training.claude_client, training.data_collector, training.historical_scanner, training.trainer
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_config_tech_debt.py

Loads settings from config/settings.local.yaml, falling back to
config/settings.example.yaml if the local file does not exist.
Caches the config after first load.
"""

import logging
import os
import re
import sys
from pathlib import Path

import yaml

# Central database path constant — override via ARCIS_DB_PATH env var.
DB_PATH = os.environ.get("ARCIS_DB_PATH", "ai_research_desk.sqlite3")

_config_cache: dict | None = None

_logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"^your[-_]|placeholder|example|YOUR_|^$", re.IGNORECASE)

_CRITICAL_KEYS = [
    ("alpaca", "api_key"),
    ("alpaca", "secret_key"),
    ("finnhub", "api_key"),
    ("fred", "api_key"),
    ("anthropic", "api_key"),
    ("telegram", "bot_token"),
]


def validate_config(config: dict) -> list[str]:
    """Check critical config keys for placeholder values.

    Returns list of warning strings (key paths with placeholder values).
    Does not crash — returns empty list if config is missing sections.
    """
    warnings = []
    for section, key in _CRITICAL_KEYS:
        value = config.get(section, {}).get(key, None)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        if _PLACEHOLDER_RE.search(value) or value.strip() == "":
            warnings.append(f"{section}.{key} appears to be a placeholder")
    return warnings


def load_config() -> dict:
    """Load and return the application configuration dict (cached)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # __file__ is src/config/__init__.py, so parent.parent reaches project root
    config_dir = Path(__file__).resolve().parent.parent.parent / "config"
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

    with open(config_path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}

    # Validate config for placeholder keys
    config_warnings = validate_config(_config_cache)
    for w in config_warnings:
        _logger.warning("[CONFIG] %s", w)
    if config_path == example_path:
        _logger.warning("[CONFIG] Using example config — API keys are placeholders")

    return _config_cache


def get_config() -> dict:
    """Return the cached config (loads from disk if not cached yet)."""
    return load_config()


def reload_config() -> dict:
    """Force re-read of config from disk."""
    global _config_cache
    _config_cache = None
    return load_config()
