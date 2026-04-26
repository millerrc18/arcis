"""Configuration loader for the Systematic Equity Research.

Called by: api.routes.actions, api.routes.scan, api.routes.shadow, api.routes.system, cli.commands, data_collection.analyst_collector, data_collection.insider_collector, data_collection.macro_collector, data_collection.short_interest_collector, email.notifier, evaluation.auditor, evaluation.backtester, evaluation.cto_report, evaluation.system_validator, llm.client, llm.grammar_client, llm.postmortem_writer, main, notifications.telegram, packets.eod_recap, ranking.ranker, risk.governor, scheduler.premarket, scheduler.vram_manager, scheduler.watch, shadow_trading.alpaca_adapter, shadow_trading.executor, training.ab_evaluation, training.bootstrap, training.claude_client, training.data_collector, training.historical_scanner, training.trainer
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_config_tech_debt.py

Config loading precedence:
1. config/settings.local.yaml (gitignored, contains real API keys)
2. config/settings.example.yaml (checked in, placeholder values)

The config is cached after first load for performance — most modules import
load_config() at module level. Use reload_config() after writing to the
YAML file (e.g., from the /config PUT endpoint).

DB_PATH is a module-level constant (not in the YAML) because it's needed
before YAML loads (e.g., for schema validation at import time). Override
via ARCIS_DB_PATH env var for testing or multi-instance setups.

Env var precedence: Individual modules (telegram, collectors) check
os.environ FIRST, then fall back to YAML values. This lets Render set
tokens via env vars without duplicating them in the YAML file.

Known issue #132: If settings.local.yaml is missing, the system falls back to
settings.example.yaml which has placeholder API keys. The validate_config()
function detects common placeholder patterns and logs warnings, but doesn't
crash — this allows tests to run without real API keys.
"""

import logging
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env file BEFORE any os.environ lookups. This ensures API keys
# in .env are available regardless of how the code is invoked (CLI,
# direct import, one-liner, etc.). Duplicate of the call in main.py
# and watch.py, but load_dotenv() is idempotent — safe to call multiple times.
load_dotenv()

# Central database path constant — must be set via ARCIS_DB_PATH env var.
# This is the single source of truth for the SQLite path. Every module
# imports DB_PATH from here rather than hardcoding the filename.
#
# Sprint 0 Wave 1d (DB-STUB-CFG, T6, cluster-02 Critical #1, 2026-04-26):
# Removed the repo-root stub fallback. CLAUDE.md mandate (#642) prohibits
# writes to <halcyon-lab>/ai_research_desk.sqlite3 — that location is a
# stub and was removed. The canonical path is C:/arcis/data/ai_research_desk.sqlite3
# and must be supplied via the ARCIS_DB_PATH env var (loaded from .env by
# the load_dotenv() call above). If the var is missing, fail fast rather
# than silently writing to the forbidden stub location.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH_ENV = os.environ.get("ARCIS_DB_PATH")
if not _DB_PATH_ENV:
    raise RuntimeError(
        "ARCIS_DB_PATH not set; expected canonical "
        "C:/arcis/data/ai_research_desk.sqlite3 (set in .env at repo root). "
        "Stub fallback to halcyon-lab/ai_research_desk.sqlite3 was removed "
        "per CLAUDE.md #642 (Sprint 0 Wave 1d / DB-STUB-CFG)."
    )
DB_PATH = _DB_PATH_ENV

_config_cache: dict | None = None

_logger = logging.getLogger(__name__)

# Detects common placeholder patterns from settings.example.yaml (#132).
# Matches: "your-api-key", "YOUR_KEY_HERE", "placeholder", "example", ""
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
