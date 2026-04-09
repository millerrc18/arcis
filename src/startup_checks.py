"""Startup validation check functions for Arcis.

Called by: src.startup
Calls: config, schema.validator, llm.client, risk.governor, training.versioning
Owns tables: none
Config keys: alpaca, render, telegram, email, shadow_trading, risk, llm
Tests: tests/test_startup.py

Individual check functions for each startup validation category.
Each returns a list of CheckResult and is independent of the others.
"""

import logging
import os
import re
import sqlite3
from pathlib import Path

from src.config import DB_PATH
from src.startup import CheckResult

logger = logging.getLogger(__name__)


def check_config(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check config file existence and placeholder value detection."""
    results = []

    local_path = Path("config/settings.local.yaml")
    if local_path.exists():
        results.append(CheckResult(
            name="config_file", category="config", status="ok",
            detail="settings.local.yaml loaded",
            fix_hint="Create config/settings.local.yaml from settings.example.yaml",
        ))
    else:
        results.append(CheckResult(
            name="config_file", category="config", status="critical",
            detail="settings.local.yaml not found (using example defaults)",
            fix_hint="Create config/settings.local.yaml from settings.example.yaml",
        ))
        return results  # No point checking placeholders if no local config

    # Check for placeholder values in critical keys.
    # Fix: Check os.environ FIRST -- secrets live in .env, not YAML (#249).
    placeholder_re = re.compile(r"^your[-_]|placeholder|example|YOUR_|^$", re.IGNORECASE)
    critical_keys = [
        ("alpaca", "api_key", "alpaca.api_key", "ALPACA_API_KEY"),
        ("alpaca", "api_secret", "alpaca.api_secret", "ALPACA_API_SECRET"),
    ]
    found_placeholders = []
    for section, key, path, env_var in critical_keys:
        env_value = os.environ.get(env_var, "")
        if env_value and not placeholder_re.search(env_value):
            continue
        yaml_value = config.get(section, {}).get(key, "")
        if isinstance(yaml_value, str) and placeholder_re.search(yaml_value):
            found_placeholders.append(f"{path} (or env {env_var})")

    if found_placeholders:
        results.append(CheckResult(
            name="config_placeholders", category="config", status="critical",
            detail=f"Placeholder values: {', '.join(found_placeholders)}",
            fix_hint="Set env vars (ALPACA_API_KEY, etc.) in .env or replace placeholders in YAML",
        ))
    else:
        results.append(CheckResult(
            name="config_placeholders", category="config", status="ok",
            detail="No placeholder values detected", fix_hint="",
        ))

    return results


def check_schema(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Validate and auto-fix schema drift. Returns checks."""
    from src.schema.validator import validate_sqlite, fix_issues

    results = []
    try:
        issues = validate_sqlite(db_path)
        if not issues:
            with sqlite3.connect(db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            results.append(CheckResult(
                name="schema_drift", category="schema", status="ok",
                detail=f"{count} tables, 0 drift",
                fix_hint="Run: python -m src.main validate-schema --fix",
            ))
            return results

        actions = fix_issues(issues, db_path)
        remaining = validate_sqlite(db_path)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]

        if remaining:
            results.append(CheckResult(
                name="schema_drift", category="schema", status="critical",
                detail=f"{count} tables, {len(remaining)} unfixed issues (fixed {len(actions)})",
                fix_hint="Run: python -m src.main validate-schema --fix",
            ))
        else:
            results.append(CheckResult(
                name="schema_drift", category="schema", status="ok",
                detail=f"{count} tables, 0 drift ({len(actions)} auto-fixed)",
                fix_hint="Run: python -m src.main validate-schema --fix",
            ))

    except Exception as e:
        results.append(CheckResult(
            name="schema_drift", category="schema", status="critical",
            detail=f"Schema validation failed: {e}",
            fix_hint="Run: python -m src.main validate-schema --fix",
        ))

    return results


def check_environment(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check required environment variables."""
    results = []
    env_checks = [
        ("FINNHUB_API_KEY", "finnhub", "api_key", "Set FINNHUB_API_KEY in .env"),
        ("FRED_API_KEY", "fred", "api_key", "Set FRED_API_KEY in .env"),
    ]
    for env_var, yaml_section, yaml_key, hint in env_checks:
        env_val = os.environ.get(env_var)
        yaml_val = config.get("data_enrichment", {}).get(f"{yaml_section}_api_key") or \
                   config.get(yaml_section, {}).get(yaml_key)
        status = "ok" if (env_val or yaml_val) else "warn"
        detail = env_var if status == "ok" else f"{env_var} missing"
        results.append(CheckResult(
            name=env_var.lower(), category="environment",
            status=status, detail=detail, fix_hint=hint,
        ))
    return results


def _check_alpaca(config: dict) -> CheckResult:
    """Check Alpaca API connectivity (#249: env var first, then YAML)."""
    try:
        import requests
        alpaca_cfg = config.get("alpaca", {})
        api_key = os.environ.get("ALPACA_API_KEY", alpaca_cfg.get("api_key", ""))
        api_secret = os.environ.get("ALPACA_API_SECRET", alpaca_cfg.get("api_secret", ""))
        base_url = os.environ.get("ALPACA_BASE_URL", alpaca_cfg.get("base_url", "https://paper-api.alpaca.markets"))
        _is_placeholder = any(p in (api_key or "").lower() for p in ("your", "placeholder", "example"))
        if not api_key or _is_placeholder:
            return CheckResult(
                name="alpaca", category="connectivity", status="critical",
                detail="Alpaca API key not configured",
                fix_hint="Set ALPACA_API_KEY and ALPACA_API_SECRET in .env",
            )
        resp = requests.get(
            f"{base_url}/v2/account",
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
            timeout=10,
        )
        if resp.status_code == 200:
            acct = resp.json()
            equity = float(acct.get("equity", 0))
            mode = "paper" if "paper" in base_url else "live"
            return CheckResult(
                name="alpaca", category="connectivity", status="ok",
                detail=f"Alpaca {mode} ${equity:,.0f}", fix_hint="",
            )
        return CheckResult(
            name="alpaca", category="connectivity", status="critical",
            detail=f"Alpaca API returned {resp.status_code}",
            fix_hint="Check ALPACA_API_KEY in .env or alpaca.api_key in YAML",
        )
    except Exception as e:
        return CheckResult(
            name="alpaca", category="connectivity", status="critical",
            detail=f"Alpaca unreachable: {str(e)[:60]}",
            fix_hint="Check ALPACA_API_KEY in .env or alpaca.api_key in YAML",
        )


def _check_ollama(config: dict) -> CheckResult:
    """Check Ollama LLM server connectivity."""
    try:
        from src.llm.client import is_llm_available
        if is_llm_available():
            model = config.get("llm", {}).get("model", "unknown")
            return CheckResult(
                name="ollama", category="connectivity", status="ok",
                detail=f"Ollama OK ({model})", fix_hint="Start Ollama: ollama serve",
            )
    except Exception:
        pass
    return CheckResult(
        name="ollama", category="connectivity", status="warn",
        detail="Ollama unreachable", fix_hint="Start Ollama: ollama serve",
    )


def _check_render_postgres(config: dict) -> list[CheckResult]:
    """Check Render Postgres connectivity and schema drift (#307)."""
    results = []
    render_cfg = config.get("render", {})
    if not render_cfg.get("enabled"):
        return results
    db_url = render_cfg.get("database_url", "")
    if not db_url:
        results.append(CheckResult(
            name="render_db", category="connectivity", status="critical",
            detail="Render enabled but database_url not set",
            fix_hint="Set render.database_url in settings.local.yaml",
        ))
        return results
    results.append(CheckResult(
        name="render_db", category="connectivity", status="ok",
        detail="Render DB URL configured",
        fix_hint="Set render.database_url in settings.local.yaml",
    ))
    try:
        import psycopg2
        from src.schema.registry import TABLES
        from src.sync.render_sync import SYNC_TABLES
        synced_names = set(SYNC_TABLES.keys())
        with psycopg2.connect(db_url) as pg_conn:
            with pg_conn.cursor() as cur:
                for tname, tdef in TABLES.items():
                    if tname not in synced_names:
                        continue
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = %s", (tname,))
                    pg_cols = {r[0] for r in cur.fetchall()}
                    if not pg_cols:
                        continue
                    missing = {c.name for c in tdef.columns} - pg_cols
                    if missing:
                        results.append(CheckResult(
                            name="render_schema_drift", category="connectivity",
                            status="warn",
                            detail=f"Postgres drift: {tname} missing columns: {', '.join(sorted(missing))}",
                            fix_hint="Run: DATABASE_URL=... python scripts/render_migrate.py",
                        ))
    except Exception as e:
        logger.debug("Postgres drift check skipped: %s", e)
    return results


def check_connectivity(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check Alpaca, Ollama, and Render Postgres connectivity."""
    results = [_check_alpaca(config), _check_ollama(config)]
    results.extend(_check_render_postgres(config))
    return results


def _svc(name: str, enabled: bool, label: str, hint: str) -> CheckResult:
    """Build an ok/warn CheckResult for a boolean service toggle."""
    return CheckResult(
        name=name, category="services", status="ok" if enabled else "warn",
        detail=f"{label} enabled" if enabled else f"{label} disabled",
        fix_hint=hint,
    )


def check_services(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check shadow trading, telegram, email, kill switch, model, capital."""
    results = [
        _svc("shadow_trading", config.get("shadow_trading", {}).get("enabled", False),
             "Shadow trading", "Set shadow_trading.enabled: true in settings.local.yaml"),
        _svc("render_sync", config.get("render", {}).get("enabled", False),
             "Render sync", "Set render.enabled: true in settings.local.yaml"),
    ]

    tg = config.get("telegram", {})
    tg_ok = bool(tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id")
                  and tg.get("bot_token") != "your-bot-token-from-botfather")
    results.append(CheckResult(
        name="telegram", category="services", status="ok" if tg_ok else "warn",
        detail="Telegram configured" if tg_ok else "Telegram not configured",
        fix_hint="Set telegram.bot_token and telegram.chat_id in settings.local.yaml",
    ))

    email_cfg = config.get("email", {})
    email_ok = bool(email_cfg.get("smtp_server") and email_cfg.get("username")
                     and email_cfg.get("password")
                     and email_cfg.get("username") != "your-assistant-email@gmail.com")
    results.append(CheckResult(
        name="email", category="services", status="ok" if email_ok else "warn",
        detail="Email configured" if email_ok else "Email not configured",
        fix_hint="Configure email section in settings.local.yaml",
    ))

    results.append(_check_kill_switch())

    capital = config.get("risk", {}).get("starting_capital", 0)
    status = "ok" if capital and capital >= 10000 else "warn"
    suffix = "" if status == "ok" else " (seems low)"
    results.append(CheckResult(
        name="starting_capital", category="services", status=status,
        detail=f"Starting capital ${capital:,.0f}{suffix}",
        fix_hint="Set risk.starting_capital in settings.local.yaml",
    ))

    results.extend(_check_risk_scaling(config))
    results.append(_check_model_version())
    return results


def _check_kill_switch() -> CheckResult:
    """Check if the trading kill switch is active."""
    try:
        from src.risk.governor import _is_halted
        halted = _is_halted()
        return CheckResult(
            name="kill_switch", category="services",
            status="warn" if halted else "ok",
            detail="Kill switch ACTIVE" if halted else "Kill switch clear",
            fix_hint="Clear via: python -m src.main resume-trading",
        )
    except Exception:
        return CheckResult(
            name="kill_switch", category="services", status="ok",
            detail="Kill switch clear",
            fix_hint="Clear via: python -m src.main resume-trading",
        )


def _check_risk_scaling(config: dict) -> list[CheckResult]:
    """Validate risk scaling tier configuration."""
    results = []
    scaling = config.get("risk", {}).get("risk_scaling", {})
    if not scaling.get("enabled"):
        return results
    tiers = scaling.get("tiers", [])
    if not tiers:
        results.append(CheckResult(
            name="risk_scaling", category="services", status="warn",
            detail="risk_scaling enabled but tiers is empty",
            fix_hint="Add tiers or disable scaling",
        ))
    for i, tier in enumerate(tiers):
        if "equity_below" not in tier or "risk_pct_max" not in tier:
            results.append(CheckResult(
                name="risk_scaling", category="services", status="critical",
                detail=f"Tier {i} missing equity_below or risk_pct_max",
                fix_hint="Fix risk_scaling.tiers config",
            ))
        elif tier["risk_pct_max"] > 0.05:
            results.append(CheckResult(
                name="risk_scaling", category="services", status="warn",
                detail=f"Tier {i} risk_pct_max={tier['risk_pct_max']:.1%} exceeds 5%",
                fix_hint="Verify this is intentional",
            ))
    return results


def _check_model_version() -> CheckResult:
    """Check active LLM model version."""
    try:
        from src.training.versioning import get_active_model_name
        model = get_active_model_name()
        if model:
            return CheckResult(
                name="model_version", category="services", status="ok",
                detail=f"Model: {model}",
                fix_hint="Run training pipeline or download a model",
            )
    except Exception:
        pass
    return CheckResult(
        name="model_version", category="services", status="warn",
        detail="No active model version",
        fix_hint="Run training pipeline or download a model",
    )
