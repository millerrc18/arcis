"""Config override system for dashboard-editable settings.

Merges YAML config with dashboard overrides from SQLite.
Only whitelisted keys can be changed from the dashboard.

Called by: scheduler.watch, commands.executor
Calls: config
Owns tables: config_overrides
Config keys: none
Tests: tests/test_config_tech_debt.py
"""

import json
import logging
import sqlite3
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import _scalar, connect_db, engine_aware_upsert

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
LOCAL_DB = DB_PATH

# Keys that can be edited from the dashboard.
# Format: "section.subsection.key" -> maps to config dict path.
WHITELISTED_KEYS = {
    "shadow_trading.max_positions",
    "shadow_trading.enabled",
    "shadow_trading.timeout_days.default",
    "shadow_trading.timeout_days.pullback",
    "risk.planned_risk_pct_min",
    "risk.planned_risk_pct_max",
    "llm.min_conviction_score",
    "llm.enabled",
    "scheduler.scan_interval_minutes",
}

# Keys that must NEVER be editable from the dashboard.
BLOCKED_PREFIXES = ("api_key", "db_path", "database_url", "render.", "secret")


def _get_nested(d: dict, key_path: str, default=None):
    """Get a value from a nested dict using dot notation."""
    parts = key_path.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part, default)
        else:
            return default
    return current


def _set_nested(d: dict, key_path: str, value) -> None:
    """Set a value in a nested dict using dot notation."""
    parts = key_path.split(".")
    current = d
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def get_overrides(db_path: str = LOCAL_DB) -> dict[str, str]:
    """Read all config overrides from SQLite."""
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT setting_key, setting_value FROM config_overrides").fetchall()
            return {row["setting_key"]: row["setting_value"] for row in rows}
    except Exception as exc:
        logger.error("Failed to read config overrides: %s", exc)
        return {}


def get_effective_config(yaml_config: dict, db_path: str = LOCAL_DB) -> dict:
    """Merge settings.yaml with dashboard overrides.

    Overrides win for whitelisted keys only.
    """
    config = deepcopy(yaml_config)
    overrides = get_overrides(db_path)

    for key, json_value in overrides.items():
        if key not in WHITELISTED_KEYS:
            logger.warning("Skipping non-whitelisted override: %s", key)
            continue

        try:
            value = json.loads(json_value)
        except (json.JSONDecodeError, TypeError):
            value = json_value

        _set_nested(config, key, value)
        logger.debug("Applied override: %s = %s", key, value)

    return config


def apply_override(
    key: str,
    value,
    db_path: str = LOCAL_DB,
) -> dict:
    """Apply a single config override from the dashboard.

    Returns dict with status and details.
    """
    if key not in WHITELISTED_KEYS:
        return {"error": f"Key '{key}' is not editable from dashboard"}

    if any(key.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return {"error": f"Key '{key}' is blocked for security reasons"}

    json_value = json.dumps(value)
    now = datetime.now(ET).isoformat()

    try:
        with connect_db(db_path) as conn:
            # Get previous value
            row = conn.execute(
                "SELECT setting_value FROM config_overrides WHERE setting_key = ?",
                (key,),
            ).fetchone()
            previous = row[0] if row else None

            engine_aware_upsert(conn, "config_overrides", {
                "setting_key": key,
                "setting_value": json_value,
                "previous_value": previous,
                "updated_at": now,
                "updated_by": "dashboard",
            }, action="replace")
            conn.commit()

        logger.info("Config override applied: %s = %s", key, value)
        return {
            "message": f"Setting '{key}' updated",
            "key": key,
            "value": value,
            "previous": json.loads(previous) if previous else None,
        }
    except Exception as exc:
        logger.error("Failed to apply override: %s", exc)
        return {"error": str(exc)}


def clear_all_overrides(db_path: str = LOCAL_DB) -> dict:
    """Remove all dashboard overrides, reverting to YAML defaults."""
    try:
        with connect_db(db_path) as conn:
            _row = conn.execute("SELECT COUNT(*) FROM config_overrides").fetchone()
            count = _scalar(_row)
            conn.execute("DELETE FROM config_overrides")
            conn.commit()
        logger.info("Cleared %d config overrides", count)
        return {"message": f"Cleared {count} overrides", "count": count}
    except Exception as exc:
        logger.error("Failed to clear overrides: %s", exc)
        return {"error": str(exc)}


def get_settings_with_sources(yaml_config: dict, db_path: str = LOCAL_DB) -> list[dict]:
    """Return whitelisted settings with their source (yaml or override).

    Used by the Settings API to show which values are overridden.
    """
    overrides = get_overrides(db_path)
    settings = []

    for key in sorted(WHITELISTED_KEYS):
        yaml_value = _get_nested(yaml_config, key)

        if key in overrides:
            try:
                override_value = json.loads(overrides[key])
            except (json.JSONDecodeError, TypeError):
                override_value = overrides[key]
            settings.append({
                "key": key,
                "value": override_value,
                "yaml_default": yaml_value,
                "source": "dashboard",
            })
        else:
            settings.append({
                "key": key,
                "value": yaml_value,
                "yaml_default": yaml_value,
                "source": "yaml",
            })

    return settings
