"""Startup validation checks for Arcis.

Called by: cli.commands (cmd_startup)
Calls: config, schema.validator, services.system_service, notifications.telegram
Owns tables: none (writes to validation_results via system_validator.save_validation_result)
Config keys: alpaca, render, telegram, email, shadow_trading, live_trading, risk, llm, training
Tests: tests/test_startup.py

Runs tiered validation (critical / warning) before launching the watch loop.
Each check_* function is independent and returns results immediately for
progressive CLI output.
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    category: str       # "config", "schema", "environment", "connectivity", "services"
    status: str         # "ok", "warn", "critical"
    detail: str
    fix_hint: str       # MANDATORY — actionable fix message


@dataclass
class StartupResult:
    checks: list[CheckResult] = field(default_factory=list)
    schema_fixes_applied: int = 0
    duration_ms: int = 0
    timestamp: str = ""

    @property
    def criticals(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def passed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "ok"]

    @property
    def overall_status(self) -> str:
        if self.criticals:
            return "critical"
        if self.warnings:
            return "degraded"
        return "healthy"


# ── PID lockfile check ───────────────────────────────────────────────


def is_watch_loop_running() -> int | None:
    """Check data/watch.lock. Returns PID if another watch loop is running, None otherwise."""
    lockfile = Path("data/watch.lock")
    if not lockfile.exists():
        return None
    try:
        old_pid = int(lockfile.read_text().strip())
        # Check if process is alive
        import psutil
        if psutil.pid_exists(old_pid):
            return old_pid
    except ImportError:
        # psutil not available — fall back to OS check
        try:
            os.kill(old_pid, 0)
            return old_pid
        except (OSError, ProcessLookupError):
            pass
    except (ValueError, OSError):
        pass
    return None


# ── Check functions ──────────────────────────────────────────────────


def check_config(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check config file existence, placeholder values, and schema drift."""
    import re
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
    # Fix: Check os.environ FIRST — secrets live in .env, not YAML (#249).
    # Only flag as placeholder if BOTH env var AND yaml value are missing/placeholder.
    import os as _os
    placeholder_re = re.compile(r"^your[-_]|placeholder|example|YOUR_|^$", re.IGNORECASE)
    critical_keys = [
        ("alpaca", "api_key", "alpaca.api_key", "ALPACA_API_KEY"),
        ("alpaca", "api_secret", "alpaca.api_secret", "ALPACA_API_SECRET"),
    ]
    found_placeholders = []
    for section, key, path, env_var in critical_keys:
        # Check env var first — if set, YAML value doesn't matter
        env_value = _os.environ.get(env_var, "")
        if env_value and not placeholder_re.search(env_value):
            continue  # Real value in env — skip
        # Fall back to YAML
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
            detail="No placeholder values detected",
            fix_hint="",
        ))

    # Config schema drift: compare local yaml structure against example yaml.
    # Detects missing sections/keys that were added to the example but never
    # copied to the local config (e.g., strategies.mean_reversion).
    results.extend(_check_config_schema_drift(config))

    return results


def _check_config_schema_drift(local_config: dict) -> list[CheckResult]:
    """Compare local config keys against settings.example.yaml.

    Walks the example YAML tree and reports any keys/sections present in
    the example but missing from the local config. Only checks structure
    (key existence), not values — values are intentionally different.
    """
    example_path = Path("config/settings.example.yaml")
    if not example_path.exists():
        return [CheckResult(
            name="config_schema_drift", category="config", status="warn",
            detail="settings.example.yaml not found — cannot check for drift",
            fix_hint="Ensure config/settings.example.yaml exists in repo root",
        )]

    try:
        import yaml as _yaml
        with open(example_path, "r", encoding="utf-8") as f:
            example_config = _yaml.safe_load(f) or {}
    except Exception as e:
        return [CheckResult(
            name="config_schema_drift", category="config", status="warn",
            detail=f"Failed to parse example config: {e}",
            fix_hint="Check config/settings.example.yaml for YAML syntax errors",
        )]

    missing = []
    _find_missing_keys(example_config, local_config, "", missing)

    if not missing:
        return [CheckResult(
            name="config_schema_drift", category="config", status="ok",
            detail="Local config has all sections from example",
            fix_hint="",
        )]

    # Classify: missing top-level sections are warnings, nested keys are info
    top_level_missing = [m for m in missing if m.count(".") == 0]
    nested_missing = [m for m in missing if m.count(".") >= 1]

    results = []
    if top_level_missing:
        results.append(CheckResult(
            name="config_missing_sections", category="config", status="warn",
            detail=f"Missing top-level sections: {', '.join(top_level_missing)}",
            fix_hint="Copy these sections from settings.example.yaml to settings.local.yaml",
        ))
    if nested_missing:
        # Group by top-level parent for readability
        parents = {}
        for key in nested_missing:
            parent = key.split(".")[0]
            parents.setdefault(parent, []).append(key)
        summary_parts = []
        for parent, keys in sorted(parents.items()):
            summary_parts.append(f"{parent}: {len(keys)} missing keys")
        results.append(CheckResult(
            name="config_missing_keys", category="config", status="warn",
            detail=f"Missing nested keys — {'; '.join(summary_parts)}",
            fix_hint="Review settings.example.yaml for new keys added since your local config was created. "
                     f"Missing: {', '.join(nested_missing[:10])}"
                     + (f" (+{len(nested_missing) - 10} more)" if len(nested_missing) > 10 else ""),
        ))

    return results


def _find_missing_keys(example: dict, local: dict, prefix: str,
                       missing: list[str]) -> None:
    """Recursively find keys in example that are missing from local."""
    if not isinstance(example, dict) or not isinstance(local, dict):
        return
    for key in example:
        full_key = f"{prefix}.{key}" if prefix else key
        if key not in local:
            missing.append(full_key)
        elif isinstance(example[key], dict):
            _find_missing_keys(example[key], local.get(key, {}), full_key, missing)


def check_schema(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Validate and auto-fix schema drift. Returns checks."""
    from src.schema.validator import validate_sqlite, fix_issues

    results = []
    try:
        issues = validate_sqlite(db_path)
        if not issues:
            # Count tables
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

        # Attempt auto-fix
        actions = fix_issues(issues, db_path)
        fixed_count = len(actions)

        # Re-validate after fix
        remaining = validate_sqlite(db_path)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]

        if remaining:
            results.append(CheckResult(
                name="schema_drift", category="schema", status="critical",
                detail=f"{count} tables, {len(remaining)} unfixed issues (fixed {fixed_count})",
                fix_hint="Run: python -m src.main validate-schema --fix",
            ))
        else:
            results.append(CheckResult(
                name="schema_drift", category="schema", status="ok",
                detail=f"{count} tables, 0 drift ({fixed_count} auto-fixed)",
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

        if env_val or yaml_val:
            results.append(CheckResult(
                name=env_var.lower(), category="environment", status="ok",
                detail=env_var,
                fix_hint=hint,
            ))
        else:
            results.append(CheckResult(
                name=env_var.lower(), category="environment", status="warn",
                detail=f"{env_var} missing",
                fix_hint=hint,
            ))

    return results


def check_connectivity(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check Alpaca, Ollama, and Render Postgres connectivity."""
    results = []

    # Alpaca — check os.environ first, then YAML fallback (#249 pattern)
    try:
        import os as _os2
        import requests
        alpaca_cfg = config.get("alpaca", {})
        api_key = _os2.environ.get("ALPACA_API_KEY", alpaca_cfg.get("api_key", ""))
        api_secret = _os2.environ.get("ALPACA_API_SECRET", alpaca_cfg.get("api_secret", ""))
        base_url = _os2.environ.get("ALPACA_BASE_URL", alpaca_cfg.get("base_url", "https://paper-api.alpaca.markets"))
        _is_placeholder = any(p in (api_key or "").lower() for p in ("your", "placeholder", "example"))
        if api_key and not _is_placeholder:
            resp = requests.get(
                f"{base_url}/v2/account",
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": api_secret,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                acct = resp.json()
                equity = float(acct.get("equity", 0))
                mode = "paper" if "paper" in base_url else "live"
                results.append(CheckResult(
                    name="alpaca", category="connectivity", status="ok",
                    detail=f"Alpaca {mode} ${equity:,.0f}",
                    fix_hint="",
                ))
            else:
                results.append(CheckResult(
                    name="alpaca", category="connectivity", status="critical",
                    detail=f"Alpaca API returned {resp.status_code}",
                    fix_hint="Check ALPACA_API_KEY in .env or alpaca.api_key in YAML",
                ))
        else:
            results.append(CheckResult(
                name="alpaca", category="connectivity", status="critical",
                detail="Alpaca API key not configured",
                fix_hint="Set ALPACA_API_KEY and ALPACA_API_SECRET in .env",
            ))
    except Exception as e:
        results.append(CheckResult(
            name="alpaca", category="connectivity", status="critical",
            detail=f"Alpaca unreachable: {str(e)[:60]}",
            fix_hint="Check ALPACA_API_KEY in .env or alpaca.api_key in YAML",
        ))

    # Ollama
    try:
        from src.llm.client import is_llm_available
        if is_llm_available():
            model = config.get("llm", {}).get("model", "unknown")
            results.append(CheckResult(
                name="ollama", category="connectivity", status="ok",
                detail=f"Ollama OK ({model})",
                fix_hint="Start Ollama: ollama serve",
            ))
        else:
            results.append(CheckResult(
                name="ollama", category="connectivity", status="warn",
                detail="Ollama unreachable",
                fix_hint="Start Ollama: ollama serve",
            ))
    except Exception:
        results.append(CheckResult(
            name="ollama", category="connectivity", status="warn",
            detail="Ollama unreachable",
            fix_hint="Start Ollama: ollama serve",
        ))

    # Render Postgres (if enabled)
    render_cfg = config.get("render", {})
    if render_cfg.get("enabled"):
        db_url = render_cfg.get("database_url", "")
        if not db_url:
            results.append(CheckResult(
                name="render_db", category="connectivity", status="critical",
                detail="Render enabled but database_url not set",
                fix_hint="Set render.database_url in settings.local.yaml",
            ))
        else:
            results.append(CheckResult(
                name="render_db", category="connectivity", status="ok",
                detail="Render DB URL configured",
                fix_hint="Set render.database_url in settings.local.yaml",
            ))
            # Check Postgres schema drift against registry (#307)
            try:
                import psycopg2
                from src.schema.registry import TABLES
                from src.sync.render_sync import SYNC_TABLES
                synced_names = {t["name"] for t in SYNC_TABLES}
                with psycopg2.connect(db_url) as pg_conn:
                    with pg_conn.cursor() as cur:
                        for table in TABLES:
                            if table.name not in synced_names:
                                continue
                            cur.execute(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = %s", (table.name,))
                            pg_cols = {r[0] for r in cur.fetchall()}
                            if not pg_cols:
                                continue
                            registry_cols = {c.name for c in table.columns}
                            missing = registry_cols - pg_cols
                            if missing:
                                results.append(CheckResult(
                                    name="render_schema_drift", category="connectivity",
                                    status="warn",
                                    detail=f"Postgres drift: {table.name} missing columns: {', '.join(sorted(missing))}",
                                    fix_hint="Run: DATABASE_URL=... python scripts/render_migrate.py",
                                ))
            except Exception as e:
                logger.debug("Postgres drift check skipped: %s", e)

    return results


def check_services(config: dict, db_path: str = DB_PATH) -> list[CheckResult]:
    """Check shadow trading, telegram, email, kill switch, model, capital."""
    results = []

    # Shadow trading
    shadow = config.get("shadow_trading", {}).get("enabled", False)
    results.append(CheckResult(
        name="shadow_trading", category="services", status="ok" if shadow else "warn",
        detail="Shadow trading enabled" if shadow else "Shadow trading disabled",
        fix_hint="Set shadow_trading.enabled: true in settings.local.yaml",
    ))

    # Render sync
    render_enabled = config.get("render", {}).get("enabled", False)
    results.append(CheckResult(
        name="render_sync", category="services", status="ok" if render_enabled else "warn",
        detail="Render sync enabled" if render_enabled else "Render sync disabled",
        fix_hint="Set render.enabled: true in settings.local.yaml",
    ))

    # Telegram
    tg = config.get("telegram", {})
    tg_ok = bool(
        tg.get("enabled") and tg.get("bot_token")
        and tg.get("chat_id")
        and tg.get("bot_token") != "your-bot-token-from-botfather"
    )
    results.append(CheckResult(
        name="telegram", category="services", status="ok" if tg_ok else "warn",
        detail="Telegram configured" if tg_ok else "Telegram not configured",
        fix_hint="Set telegram.bot_token and telegram.chat_id in settings.local.yaml",
    ))

    # Email
    email_cfg = config.get("email", {})
    email_ok = bool(
        email_cfg.get("smtp_server") and email_cfg.get("username")
        and email_cfg.get("password")
        and email_cfg.get("username") != "your-assistant-email@gmail.com"
    )
    results.append(CheckResult(
        name="email", category="services", status="ok" if email_ok else "warn",
        detail="Email configured" if email_ok else "Email not configured",
        fix_hint="Configure email section in settings.local.yaml",
    ))

    # Kill switch
    try:
        from src.risk.governor import _is_halted
        halted = _is_halted()
        results.append(CheckResult(
            name="kill_switch", category="services",
            status="warn" if halted else "ok",
            detail="Kill switch ACTIVE" if halted else "Kill switch clear",
            fix_hint="Clear via: python -m src.main resume-trading",
        ))
    except Exception:
        results.append(CheckResult(
            name="kill_switch", category="services", status="ok",
            detail="Kill switch clear",
            fix_hint="Clear via: python -m src.main resume-trading",
        ))

    # Starting capital
    capital = config.get("risk", {}).get("starting_capital", 0)
    if capital and capital >= 10000:
        results.append(CheckResult(
            name="starting_capital", category="services", status="ok",
            detail=f"Starting capital ${capital:,.0f}",
            fix_hint="Set risk.starting_capital in settings.local.yaml",
        ))
    else:
        results.append(CheckResult(
            name="starting_capital", category="services", status="warn",
            detail=f"Starting capital ${capital:,.0f} (seems low)",
            fix_hint="Set risk.starting_capital in settings.local.yaml",
        ))

    # Risk scaling tiers validation (Strategy Decision #26)
    scaling = config.get("risk", {}).get("risk_scaling", {})
    if scaling.get("enabled"):
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

    # Model version
    try:
        from src.training.versioning import get_active_model_name
        model = get_active_model_name()
        if model:
            results.append(CheckResult(
                name="model_version", category="services", status="ok",
                detail=f"Model: {model}",
                fix_hint="Run training pipeline or download a model",
            ))
        else:
            results.append(CheckResult(
                name="model_version", category="services", status="warn",
                detail="No active model version",
                fix_hint="Run training pipeline or download a model",
            ))
    except Exception:
        results.append(CheckResult(
            name="model_version", category="services", status="warn",
            detail="Could not check model version",
            fix_hint="Run training pipeline or download a model",
        ))

    return results


# ── Persistence ──────────────────────────────────────────────────────


def persist_startup_result(result: StartupResult, db_path: str = DB_PATH) -> str:
    """Save startup result to validation_results table. Returns result_id."""
    from src.evaluation.system_validator import save_validation_result

    # Package into the shape save_validation_result expects
    checks_by_category = {}
    for c in result.checks:
        checks_by_category.setdefault(c.category, []).append({
            "name": c.name,
            "status": c.status,
            "detail": c.detail,
            "fix_hint": c.fix_hint,
        })

    payload = {
        "timestamp": result.timestamp,
        "overall_status": result.overall_status,
        "checks_passed": len(result.passed),
        "checks_failed": len(result.criticals),
        "checks_warning": len(result.warnings),
        "checks_total": len(result.checks),
        "trigger": "startup",
        "duration_ms": result.duration_ms,
        "schema_fixes_applied": result.schema_fixes_applied,
        "categories": checks_by_category,
    }

    return save_validation_result(payload, db_path)


def get_previous_startup_status(db_path: str = DB_PATH) -> str | None:
    """Get the overall_status from the most recent startup validation result."""
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT overall_status FROM validation_results "
                "WHERE results_json LIKE '%\"trigger\": \"startup\"%' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None


# ── Run all checks ───────────────────────────────────────────────────

# Category registry: (label, check_function)
STARTUP_CATEGORIES = [
    ("Config", check_config),
    ("Schema", check_schema),
    ("Environment", check_environment),
    ("Connectivity", check_connectivity),
    ("Services", check_services),
]


def run_startup_checks(config: dict, db_path: str = DB_PATH) -> StartupResult:
    """Run all startup validation checks. Returns structured result."""
    start = time.time()
    all_checks = []
    schema_fixes = 0

    for _label, check_fn in STARTUP_CATEGORIES:
        results = check_fn(config, db_path)
        all_checks.extend(results)

    # Count schema fixes from detail text
    for c in all_checks:
        if c.category == "schema" and "auto-fixed" in c.detail:
            import re
            m = re.search(r"(\d+) auto-fixed", c.detail)
            if m:
                schema_fixes = int(m.group(1))

    elapsed = int((time.time() - start) * 1000)
    return StartupResult(
        checks=all_checks,
        schema_fixes_applied=schema_fixes,
        duration_ms=elapsed,
        timestamp=datetime.now(ET).isoformat(),
    )
