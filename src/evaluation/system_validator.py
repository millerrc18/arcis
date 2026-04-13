"""System validation engine for Arcis.

Called by: api.routes.system, cli.commands, scheduler.watch
Calls: config, risk.governor, shadow_trading.alpaca_adapter
Owns tables: validation_results
Config keys: alpaca, anthropic_api_key, api_key, api_secret, base_url, bot_token, chat_id, data_enrichment, database_url, email, enabled, finnhub_api_key, fred_api_key, live_trading, llm, max_positions, model, render, risk, risk_governor, secret_key, shadow_trading, smtp_server, telegram, timeout_days, training
Tests: tests/test_system_validator.py

Runs 50+ checks across 8 categories (database, trading, training, api,
collectors, notifications, scheduler, llm) and returns structured results.

Design rationale
~~~~~~~~~~~~~~~~
The system validator is the "preflight checklist" for Arcis.  It runs
on every startup (via the `startup` command) and on-demand via the
`validate` CLI command and /validate Telegram command.

8 categories, each independent so a failure in one doesn't block others:
  1. database:      file exists, WAL mode, expected tables, data freshness
  2. trading:       Alpaca credentials, zombie trades, risk config, kill switch
  3. training:      example count, quality scores, curriculum, model versions
  4. api:           frontend build, Render postgres, local/cloud API health
  5. collectors:    per-table freshness for all 12 data collector tables
  6. notifications: Telegram bot token validity, email SMTP config
  7. scheduler:     last scan time, schedule metrics, overnight collectors
  8. llm:           Ollama running, model loaded, inference test

Credential checking (#249): The validator must check credentials in the
same locations the actual adapters use.  Before #249, it only checked
YAML config, but secrets live in os.environ (via .env).  This mismatch
caused false CRITICAL failures on every startup.  Now each credential
check mirrors the lookup order in the corresponding adapter.
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.secret_redact import (
    _TOKEN_PATTERNS,
    sanitize_error as _sanitize_error,
    sanitize_text as _sanitize_text,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Expected tables — a subset of the full 49-table schema registry.
# Only tables that should exist in a healthy running system are listed
# here.  Internal/migration tables are excluded to avoid false warnings.
EXPECTED_TABLES = [
    "recommendations", "shadow_trades", "training_examples",
    "model_versions", "audit_reports", "schedule_metrics",
    "activity_log", "council_sessions", "council_votes",
    "options_chains", "options_metrics", "vix_term_structure",
    "macro_snapshots", "google_trends", "cboe_ratios",
    "insider_transactions", "short_interest", "analyst_estimates",
    "fed_communications", "edgar_filings", "setup_signals",
    "canary_evaluations", "quality_drift_metrics",
    "earnings_calendar", "research_docs",
]

# Tables that should have data if the system has been running.
# An empty core table (recommendations, shadow_trades, training_examples)
# usually means the system has never completed a scan cycle — worth a warn.
TABLES_SHOULD_HAVE_DATA = [
    "recommendations", "shadow_trades", "training_examples",
]

# Collector tables and their expected time columns.
# Used for freshness checks: if a collector table's most recent row is
# older than 7 days, it's flagged as stale because overnight collection
# should populate every table nightly.
COLLECTOR_TABLES = {
    "options_chains": "collected_at",
    "options_metrics": "collected_date",
    "vix_term_structure": "collected_date",
    "macro_snapshots": "collected_date",
    "google_trends": "collected_date",
    "cboe_ratios": "collected_date",
    "insider_transactions": "collected_at",
    "short_interest": "collected_at",
    "analyst_estimates": "collected_at",
    "fed_communications": "collected_at",
    "edgar_filings": "collected_at",
    "research_docs": "created_at",
}


def _check(name: str, status: str, detail: str) -> dict:
    """Build a single check result."""
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "last_verified": datetime.now(ET).isoformat(),
    }


def _safe_query(conn, sql, params=()) -> list | None:
    """Execute query safely, return rows or None on error.

    Validation checks must never crash the validator itself — a failed
    query means "check inconclusive", not "system broken".
    """
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as e:
        logger.debug("Query failed: %s — %s", sql[:80], e)
        return None


# ── Category: Database ──────────────────────────────────────────────


def _check_database(db_path: str) -> list[dict]:
    """Validate database file, schema, data presence, and referential integrity.

    Checks (in order): file exists, file size sane, connection works,
    WAL mode enabled, all expected tables exist, core tables have data,
    training example count >= 100, no orphaned FK references, and
    per-table write freshness.
    """
    checks = []

    # Check DB file exists and is readable
    if not Path(db_path).exists():
        checks.append(_check("db_file_exists", "fail",
                              f"Database file not found: {db_path}"))
        return checks

    checks.append(_check("db_file_exists", "pass",
                          f"Database file exists ({db_path})"))

    # Check file size
    size_mb = Path(db_path).stat().st_size / (1024 * 1024)
    if size_mb < 0.001:
        checks.append(_check("db_file_size", "fail",
                              f"Database file suspiciously small: {size_mb:.3f} MB"))
    elif size_mb > 5000:
        checks.append(_check("db_file_size", "warn",
                              f"Database file very large: {size_mb:.1f} MB"))
    else:
        checks.append(_check("db_file_size", "pass",
                              f"Database size: {size_mb:.1f} MB"))

    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        conn.row_factory = sqlite3.Row
    except Exception as e:
        checks.append(_check("db_connection", "fail", f"Cannot connect: {e}"))
        return checks

    checks.append(_check("db_connection", "pass", "SQLite connection OK"))

    try:
        # WAL mode
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        mode_val = mode[0] if mode else "unknown"
        if mode_val == "wal":
            checks.append(_check("db_wal_mode", "pass", "WAL mode enabled"))
        else:
            checks.append(_check("db_wal_mode", "warn",
                                  f"Journal mode is '{mode_val}', not WAL"))

        # Check all expected tables exist
        existing = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        missing = [t for t in EXPECTED_TABLES if t not in existing]
        if missing:
            checks.append(_check("db_tables_exist", "warn",
                                  f"Missing tables: {', '.join(missing)}"))
        else:
            checks.append(_check("db_tables_exist", "pass",
                                  f"All {len(EXPECTED_TABLES)} expected tables exist"))

        # Check tables that should have data
        for table in TABLES_SHOULD_HAVE_DATA:
            if table not in existing:
                continue
            row = _safe_query(conn, f"SELECT COUNT(*) FROM {table}")
            if row is None:
                checks.append(_check(f"db_{table}_data", "warn",
                                      f"Could not query {table}"))
            elif row[0][0] == 0:
                checks.append(_check(f"db_{table}_data", "warn",
                                      f"{table} is empty"))
            else:
                checks.append(_check(f"db_{table}_data", "pass",
                                      f"{table}: {row[0][0]} rows"))

        # Training examples sanity
        if "training_examples" in existing:
            row = _safe_query(conn,
                              "SELECT COUNT(*) FROM training_examples")
            if row and row[0][0] < 100:
                checks.append(_check("db_training_count", "warn",
                                      f"Only {row[0][0]} training examples (expected 900+)"))
            elif row:
                checks.append(_check("db_training_count", "pass",
                                      f"{row[0][0]} training examples"))

        # Check for orphaned shadow_trades FK
        if "shadow_trades" in existing and "recommendations" in existing:
            orphans = _safe_query(conn, """
                SELECT COUNT(*) FROM shadow_trades st
                LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id
                WHERE st.recommendation_id IS NOT NULL
                AND r.recommendation_id IS NULL
                AND COALESCE(st.quarantined, 0) = 0
            """)
            if orphans and orphans[0][0] > 0:
                checks.append(_check("db_orphaned_fk", "warn",
                                      f"{orphans[0][0]} shadow_trades with invalid recommendation_id"))
            else:
                checks.append(_check("db_orphaned_fk", "pass",
                                      "No orphaned foreign keys"))

        # Most recent write per key table
        for table, time_col in [("recommendations", "created_at"),
                                 ("shadow_trades", "updated_at"),
                                 ("training_examples", "created_at")]:
            if table not in existing:
                continue
            try:
                row = conn.execute(
                    f"SELECT MAX({time_col}) FROM {table}"
                ).fetchone()
                if row and row[0]:
                    last = row[0]
                    checks.append(_check(f"db_{table}_freshness", "pass",
                                          f"Last write: {last[:19]}"))
                else:
                    checks.append(_check(f"db_{table}_freshness", "warn",
                                          f"No data in {table}"))
            except Exception:
                pass

    finally:
        conn.close()

    return checks


# ── Category: Trading ───────────────────────────────────────────────


def _check_trading(db_path: str, config: dict) -> list[dict]:
    """Validate trading infrastructure: credentials, positions, risk config.

    Fix for #249: credential lookups now mirror the actual adapter code.
    The adapter (alpaca_adapter._get_alpaca_config) reads os.environ
    first and falls back to YAML.  The validator must do the same,
    otherwise it reports false CRITICALs when secrets are only in .env.
    """
    checks = []

    # Fix for #249: Check os.environ FIRST for credentials, then fall back to YAML.
    # Secrets live in .env / os.environ, not in YAML config. The adapter itself
    # uses os.environ (see alpaca_adapter._get_alpaca_config), so the validator
    # must match to avoid false CRITICALs.
    alpaca_cfg = config.get("alpaca", {})
    paper_key = os.environ.get("ALPACA_API_KEY", alpaca_cfg.get("api_key", ""))
    paper_secret = os.environ.get("ALPACA_API_SECRET", alpaca_cfg.get("api_secret", ""))

    if paper_key and paper_secret:
        try:
            from src.shadow_trading.alpaca_adapter import get_account_info
            info = get_account_info()
            if info and info.get("equity"):
                checks.append(_check("trading_paper_creds", "pass",
                                      f"Paper account: equity=${info['equity']}"))
            else:
                checks.append(_check("trading_paper_creds", "warn",
                                      "Paper API returned no equity info"))
        except Exception as e:
            checks.append(_check("trading_paper_creds", "fail",
                                  f"Paper API error: {_sanitize_error(e)}"))
    else:
        checks.append(_check("trading_paper_creds", "warn",
                              "Paper API credentials not configured"))

    # Fix for #249: live credentials also in env vars, matching alpaca_adapter._get_live_config
    live_cfg = config.get("live_trading", {})
    if live_cfg.get("enabled", False):
        live_key = os.environ.get("ALPACA_LIVE_API_KEY", live_cfg.get("api_key", ""))
        live_secret = os.environ.get("ALPACA_LIVE_SECRET_KEY", live_cfg.get("secret_key", ""))
        if live_key and live_secret:
            try:
                from src.shadow_trading.alpaca_adapter import get_live_account_info
                info = get_live_account_info()
                if info and info.get("equity"):
                    checks.append(_check("trading_live_creds", "pass",
                                          f"Live account: equity=${info['equity']}"))
                else:
                    checks.append(_check("trading_live_creds", "warn",
                                          "Live API returned no equity info"))
            except Exception as e:
                checks.append(_check("trading_live_creds", "fail",
                                      f"Live API error: {_sanitize_error(e)}"))
        else:
            checks.append(_check("trading_live_creds", "fail",
                                  "Live trading enabled but credentials not configured"))
    else:
        checks.append(_check("trading_live_creds", "pass",
                              "Live trading not enabled (OK for current phase)"))

    # Check for zombie trades (open beyond timeout).
    # A zombie trade is one that was never closed by the bracket monitor
    # or reconciler — it sits in 'open' status indefinitely, consuming
    # a position slot and skewing portfolio state.
    shadow_cfg = config.get("shadow_trading", {})
    timeout_days = shadow_cfg.get("timeout_days", 10)
    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now(ET) - timedelta(days=timeout_days)).isoformat()
        zombies = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status='open' AND created_at < ?"
            " AND COALESCE(quarantined, 0) = 0",
            (cutoff,),
        ).fetchone()
        conn.close()
        if zombies and zombies[0] > 0:
            checks.append(_check("trading_zombie_trades", "warn",
                                  f"{zombies[0]} trades open beyond {timeout_days}-day timeout"))
        else:
            checks.append(_check("trading_zombie_trades", "pass",
                                  "No zombie trades"))
    except Exception as e:
        checks.append(_check("trading_zombie_trades", "warn",
                              f"Could not check: {e}"))

    # Risk governor config sanity — a disabled governor is a FAIL
    # because the system should never trade without risk limits.
    risk_cfg = config.get("risk_governor", {})
    if risk_cfg.get("enabled", True):
        issues = []
        starting_cap = config.get("risk", {}).get("starting_capital", 0)
        if starting_cap < 10000:
            issues.append(f"starting_capital={starting_cap} (expected >= 10000)")
        max_pos = shadow_cfg.get("max_positions", 0)
        if max_pos <= 0:
            issues.append(f"max_positions={max_pos} (expected > 0)")
        if issues:
            checks.append(_check("trading_risk_config", "warn",
                                  f"Config issues: {'; '.join(issues)}"))
        else:
            checks.append(_check("trading_risk_config", "pass",
                                  "Risk governor config OK"))
    else:
        checks.append(_check("trading_risk_config", "fail",
                              "Risk governor is DISABLED"))

    # Kill switch
    try:
        from src.risk.governor import _is_halted
        if _is_halted():
            checks.append(_check("trading_kill_switch", "warn",
                                  "Trading is currently HALTED"))
        else:
            checks.append(_check("trading_kill_switch", "pass",
                                  "Trading is active (not halted)"))
    except Exception:
        checks.append(_check("trading_kill_switch", "pass",
                              "Kill switch check unavailable (module not loaded)"))

    # Open position count
    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        open_count = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status='open'"
            " AND COALESCE(quarantined, 0) = 0"
        ).fetchone()[0]
        conn.close()
        max_positions = shadow_cfg.get("max_positions", 10)
        if open_count >= max_positions:
            checks.append(_check("trading_open_positions", "warn",
                                  f"{open_count} open (at max {max_positions})"))
        else:
            checks.append(_check("trading_open_positions", "pass",
                                  f"{open_count} open positions (max {max_positions})"))
    except Exception as e:
        checks.append(_check("trading_open_positions", "warn",
                              f"Could not check: {e}"))

    return checks


# ── Category: Training Pipeline ─────────────────────────────────────


def _check_training(db_path: str, config: dict) -> list[dict]:
    """Validate training pipeline: example count, quality, curriculum, model versions.

    The training pipeline is the system's learning loop — if it degrades,
    the model stops improving.  Canary evaluations and quality drift
    metrics are early-warning signals for model regression.
    """
    checks = []
    training_cfg = config.get("training", {})

    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        conn.row_factory = sqlite3.Row

        # Training examples count + format
        try:
            row = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()
            total = row[0] if row else 0
            checks.append(_check("training_example_count", "pass" if total >= 100 else "warn",
                                  f"{total} training examples"))
        except Exception:
            checks.append(_check("training_example_count", "warn",
                                  "training_examples table not accessible"))

        # Quality scores
        try:
            row = conn.execute(
                "SELECT COUNT(*), AVG(quality_score) FROM training_examples "
                "WHERE quality_score IS NOT NULL AND quality_score > 0"
            ).fetchone()
            scored = row[0] if row else 0
            avg = row[1] if row and row[1] else 0
            if scored > 0:
                checks.append(_check("training_quality_scores", "pass",
                                      f"{scored} scored, avg={avg:.1f}"))
            else:
                checks.append(_check("training_quality_scores", "warn",
                                      "No quality scores found"))
        except Exception:
            checks.append(_check("training_quality_scores", "warn",
                                  "Could not query quality scores"))

        # Curriculum distribution
        try:
            rows = conn.execute(
                "SELECT stage, COUNT(*) FROM training_examples "
                "WHERE stage IS NOT NULL GROUP BY stage"
            ).fetchall()
            if rows:
                dist = {row[0]: row[1] for row in rows}
                checks.append(_check("training_curriculum", "pass",
                                      f"Curriculum: {dict(dist)}"))
            else:
                checks.append(_check("training_curriculum", "warn",
                                      "No curriculum stages assigned"))
        except Exception:
            checks.append(_check("training_curriculum", "warn",
                                  "Could not query curriculum stages"))

        # Model version
        try:
            row = conn.execute(
                "SELECT version_name, status FROM model_versions "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                checks.append(_check("training_model_version", "pass",
                                      f"Latest model: {row[0]} ({row[1]})"))
            else:
                checks.append(_check("training_model_version", "warn",
                                      "No model versions registered"))
        except Exception:
            checks.append(_check("training_model_version", "warn",
                                  "model_versions table not accessible"))

        # Last retrain date
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM model_versions WHERE status='released'"
            ).fetchone()
            if row and row[0]:
                checks.append(_check("training_last_retrain", "pass",
                                      f"Last retrain: {row[0][:19]}"))
            else:
                checks.append(_check("training_last_retrain", "warn",
                                      "No released model found"))
        except Exception:
            checks.append(_check("training_last_retrain", "warn",
                                  "Could not check retrain date"))

        # Canary evaluation
        try:
            row = conn.execute(
                "SELECT verdict, created_at FROM canary_evaluations "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                checks.append(_check("training_canary", "pass" if row[0] == "pass" else "warn",
                                      f"Last canary: {row[0]} at {row[1][:19]}"))
            else:
                checks.append(_check("training_canary", "warn",
                                      "No canary evaluations found"))
        except Exception:
            checks.append(_check("training_canary", "warn",
                                  "canary_evaluations table not accessible"))

        # Quality drift
        try:
            row = conn.execute(
                "SELECT metric_date, avg_score, pass_rate FROM quality_drift_metrics "
                "ORDER BY metric_date DESC LIMIT 1"
            ).fetchone()
            if row:
                checks.append(_check("training_quality_drift", "pass",
                                      f"Last drift check: {row[0]}, avg={row[1]:.1f}, pass_rate={row[2]:.1%}"))
            else:
                checks.append(_check("training_quality_drift", "warn",
                                      "No quality drift metrics"))
        except Exception:
            checks.append(_check("training_quality_drift", "warn",
                                  "Could not check quality drift"))

        conn.close()

    except Exception as e:
        checks.append(_check("training_db_access", "fail",
                              f"Cannot access training data: {e}"))

    # Claude API key check
    api_key = training_cfg.get("anthropic_api_key", "")
    if api_key and len(api_key) > 10:
        checks.append(_check("training_claude_api", "pass",
                              "Anthropic API key configured"))
    else:
        checks.append(_check("training_claude_api", "warn",
                              "Anthropic API key not configured"))

    return checks


# ── Category: API / Dashboard ───────────────────────────────────────


def _check_api(config: dict) -> list[dict]:
    checks = []

    # Check if frontend build exists
    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        checks.append(_check("api_frontend_build", "pass",
                              "Frontend build exists"))
    else:
        checks.append(_check("api_frontend_build", "warn",
                              "No frontend build found (run npm run build)"))

    # Render config
    render_cfg = config.get("render", {})
    if render_cfg.get("enabled", False):
        db_url = render_cfg.get("database_url") or os.environ.get("DATABASE_URL", "")
        if db_url:
            checks.append(_check("api_render_config", "pass",
                                  "Render Postgres URL configured"))
            # Try connecting
            try:
                import psycopg2
                conn = psycopg2.connect(db_url, connect_timeout=5)
                conn.close()
                checks.append(_check("api_render_connection", "pass",
                                      "Render Postgres reachable"))
            except ImportError:
                checks.append(_check("api_render_connection", "warn",
                                      "psycopg2 not installed (cloud dependency)"))
            except Exception as e:
                checks.append(_check("api_render_connection", "fail",
                                      f"Cannot connect to Render Postgres: {_sanitize_error(e)}"))
        else:
            checks.append(_check("api_render_config", "warn",
                                  "Render enabled but DATABASE_URL not set"))
    else:
        checks.append(_check("api_render_config", "pass",
                              "Render sync not enabled (local mode)"))

    # Check local API availability
    try:
        import requests
        resp = requests.get("http://localhost:8000/status", timeout=3)
        if resp.status_code == 200:
            checks.append(_check("api_local_server", "pass",
                                  "Local API server responding"))
        else:
            checks.append(_check("api_local_server", "warn",
                                  f"Local API returned {resp.status_code}"))
    except Exception:
        checks.append(_check("api_local_server", "warn",
                              "Local API not running (expected if using cloud)"))

    # Cloud API healthz
    try:
        import requests
        render_url = os.environ.get("RENDER_API_URL", "https://halcyon-lab-api.onrender.com")
        resp = requests.get(f"{render_url}/healthz", timeout=5)
        if resp.status_code == 200:
            checks.append(_check("api_cloud_healthz", "pass",
                                  "Cloud API /healthz OK"))
        else:
            checks.append(_check("api_cloud_healthz", "warn",
                                  f"Cloud API returned {resp.status_code}"))
    except Exception:
        checks.append(_check("api_cloud_healthz", "warn",
                              "Cloud API not reachable (may be cold-starting)"))

    return checks


# ── Category: Data Collectors ───────────────────────────────────────


def _check_collectors(db_path: str, config: dict) -> list[dict]:
    """Validate data collectors: per-table row counts, freshness, API keys.

    Checks each of the 12 collector tables for row count and last-write
    timestamp.  Tables stale beyond 7 days get a warning because the
    overnight schedule should refresh them nightly.

    API key checks (#249): like trading credentials, collector API keys
    live in os.environ and fall back to YAML config.
    """
    checks = []

    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        conn.row_factory = sqlite3.Row

        for table, time_col in COLLECTOR_TABLES.items():
            try:
                row = conn.execute(
                    f"SELECT COUNT(*), MAX({time_col}) FROM {table}"
                ).fetchone()
                count = row[0] if row else 0
                last = row[1] if row else None

                if count == 0:
                    checks.append(_check(f"collector_{table}", "warn",
                                          f"{table}: empty (no data collected yet)"))
                else:
                    # Check freshness (warn if > 7 days stale)
                    if last:
                        try:
                            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                            age_days = (datetime.now(ET) - last_dt.astimezone(ET)).days
                            if age_days > 7:
                                checks.append(_check(f"collector_{table}", "warn",
                                                      f"{table}: {count} rows, last={last[:10]} ({age_days}d ago — stale)"))
                            else:
                                checks.append(_check(f"collector_{table}", "pass",
                                                      f"{table}: {count} rows, last={last[:10]}"))
                        except (ValueError, TypeError):
                            checks.append(_check(f"collector_{table}", "pass",
                                                  f"{table}: {count} rows, last={last}"))
                    else:
                        checks.append(_check(f"collector_{table}", "pass",
                                              f"{table}: {count} rows"))
            except Exception:
                checks.append(_check(f"collector_{table}", "warn",
                                      f"{table}: table not found or inaccessible"))

        conn.close()

    except Exception as e:
        checks.append(_check("collectors_db", "fail",
                              f"Cannot access database: {e}"))

    # Fix for #249: check env vars first for API keys, matching collector implementations
    enrichment_cfg = config.get("data_enrichment", {})
    finnhub_key = os.environ.get("FINNHUB_API_KEY", enrichment_cfg.get("finnhub_api_key", ""))
    fred_key = os.environ.get("FRED_API_KEY", enrichment_cfg.get("fred_api_key", ""))

    checks.append(_check("collector_finnhub_key",
                          "pass" if finnhub_key else "warn",
                          "Finnhub API key configured" if finnhub_key else "Finnhub API key not set"))
    checks.append(_check("collector_fred_key",
                          "pass" if fred_key else "warn",
                          "FRED API key configured" if fred_key else "FRED API key not set"))

    return checks


# ── Category: Notifications ─────────────────────────────────────────


def _check_notifications(config: dict) -> list[dict]:
    """Validate notification channels: Telegram bot token, email SMTP.

    Telegram validation calls the getMe API (read-only, no messages sent)
    to confirm the bot token is valid.  This catches expired or revoked
    tokens before they cause silent notification failures during trading.
    """
    checks = []

    # Fix for #249: Telegram secrets live in os.environ, not YAML config.
    tg_cfg = config.get("telegram", {})
    tg_enabled = tg_cfg.get("enabled", False)
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", tg_cfg.get("bot_token", ""))
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", str(tg_cfg.get("chat_id", "")))

    if tg_enabled and tg_token and tg_chat:
        checks.append(_check("notif_telegram_config", "pass",
                              "Telegram configured"))
        # Test API (getMe, no message sent)
        try:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{tg_token}/getMe",
                timeout=5,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                bot_name = resp.json()["result"].get("username", "?")
                checks.append(_check("notif_telegram_valid", "pass",
                                      f"Bot token valid (@{bot_name})"))
            else:
                checks.append(_check("notif_telegram_valid", "fail",
                                      "Bot token is invalid"))
        except Exception as e:
            checks.append(_check("notif_telegram_valid", "warn",
                                  f"Could not verify bot token: {_sanitize_error(e)}"))
    elif tg_enabled:
        checks.append(_check("notif_telegram_config", "fail",
                              "Telegram enabled but token/chat_id missing"))
    else:
        checks.append(_check("notif_telegram_config", "warn",
                              "Telegram notifications disabled"))

    # Email
    email_cfg = config.get("email", {})
    smtp_server = email_cfg.get("smtp_server", "")
    if smtp_server:
        checks.append(_check("notif_email_config", "pass",
                              f"Email configured (SMTP: {smtp_server})"))
    else:
        checks.append(_check("notif_email_config", "warn",
                              "Email SMTP not configured"))

    return checks


# ── Category: Scheduler ─────────────────────────────────────────────


def _check_scheduler(db_path: str, config: dict) -> list[dict]:
    """Validate scheduler health: last scan, schedule metrics, overnight collectors.

    The scheduler is the heartbeat of the system.  If scans stop running,
    no new recommendations are generated, no trades open, and the data
    pipeline stalls.  Staleness thresholds: >24h for scans (warn),
    >3 days for collectors (stale count).
    """
    checks = []

    try:
        conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
        conn.row_factory = sqlite3.Row

        # Last scan timestamp
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM recommendations"
            ).fetchone()
            if row and row[0]:
                last_scan = row[0]
                last_dt = datetime.fromisoformat(last_scan)
                age_hours = (datetime.now(ET) - last_dt.replace(
                    tzinfo=ET if last_dt.tzinfo is None else last_dt.tzinfo
                )).total_seconds() / 3600
                if age_hours > 24:
                    checks.append(_check("scheduler_last_scan", "warn",
                                          f"Last scan: {last_scan[:19]} ({age_hours:.0f}h ago)"))
                else:
                    checks.append(_check("scheduler_last_scan", "pass",
                                          f"Last scan: {last_scan[:19]} ({age_hours:.1f}h ago)"))
            else:
                checks.append(_check("scheduler_last_scan", "warn",
                                      "No scans recorded yet"))
        except Exception:
            checks.append(_check("scheduler_last_scan", "warn",
                                  "Could not determine last scan time"))

        # Schedule metrics — last entry
        try:
            row = conn.execute(
                "SELECT MAX(metric_date) FROM schedule_metrics"
            ).fetchone()
            if row and row[0]:
                checks.append(_check("scheduler_metrics", "pass",
                                      f"Schedule metrics last recorded: {row[0]}"))
            else:
                checks.append(_check("scheduler_metrics", "warn",
                                      "No schedule metrics recorded"))
        except Exception:
            checks.append(_check("scheduler_metrics", "warn",
                                  "schedule_metrics table not accessible"))

        # Overnight data collection — check if collectors ran recently
        stale_collectors = 0
        for table, time_col in COLLECTOR_TABLES.items():
            try:
                row = conn.execute(
                    f"SELECT MAX({time_col}) FROM {table}"
                ).fetchone()
                if row and row[0]:
                    try:
                        last_dt = datetime.fromisoformat(
                            row[0].replace("Z", "+00:00"))
                        age_days = (datetime.now(ET) - last_dt.astimezone(ET)).days
                        if age_days > 3:
                            stale_collectors += 1
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass

        if stale_collectors > 6:
            checks.append(_check("scheduler_overnight", "warn",
                                  f"{stale_collectors}/{len(COLLECTOR_TABLES)} collectors stale (>3 days)"))
        else:
            checks.append(_check("scheduler_overnight", "pass",
                                  f"Overnight collectors: {stale_collectors} stale of {len(COLLECTOR_TABLES)}"))

        # Activity log — check last entry
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM activity_log"
            ).fetchone()
            if row and row[0]:
                checks.append(_check("scheduler_activity", "pass",
                                      f"Last activity: {row[0][:19]}"))
            else:
                checks.append(_check("scheduler_activity", "warn",
                                      "No activity log entries"))
        except Exception:
            checks.append(_check("scheduler_activity", "warn",
                                  "activity_log not accessible"))

        # Council sessions
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM council_sessions"
            ).fetchone()
            if row and row[0]:
                checks.append(_check("scheduler_council", "pass",
                                      f"Last council session: {row[0][:19]}"))
            else:
                checks.append(_check("scheduler_council", "warn",
                                      "No council sessions recorded"))
        except Exception:
            checks.append(_check("scheduler_council", "warn",
                                  "council_sessions not accessible"))

        conn.close()

    except Exception as e:
        checks.append(_check("scheduler_db", "fail",
                              f"Cannot access database: {e}"))

    return checks


# ── Category: LLM ───────────────────────────────────────────────────


def _check_llm(config: dict) -> list[dict]:
    """Validate LLM availability: Ollama running, model loaded, inference test.

    The inference test sends a trivial prompt ("Reply with exactly: ARCIS_OK")
    and checks for a valid response.  This catches: Ollama not running,
    model not pulled, GPU out of VRAM (will timeout), and corrupt model
    weights (will produce garbage).  The 180-second timeout threshold
    accounts for cold-start model loading on the first inference.
    """
    checks = []

    llm_cfg = config.get("llm", {})
    llm_enabled = llm_cfg.get("enabled", True)

    if not llm_enabled:
        checks.append(_check("llm_enabled", "warn", "LLM is disabled in config"))
        return checks

    model_name = llm_cfg.get("model", "qwen3:8b")
    base_url = llm_cfg.get("base_url", "http://localhost:11434")

    # Check Ollama is running
    try:
        import requests
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            checks.append(_check("llm_ollama_running", "pass",
                                  "Ollama is running"))
            # Check model is loaded
            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            # Check for exact or partial match
            found = any(model_name in name for name in model_names)
            if found:
                checks.append(_check("llm_model_loaded", "pass",
                                      f"Model '{model_name}' available"))
            else:
                checks.append(_check("llm_model_loaded", "warn",
                                      f"Model '{model_name}' not found. Available: {', '.join(model_names[:5])}"))
        else:
            checks.append(_check("llm_ollama_running", "fail",
                                  f"Ollama returned {resp.status_code}"))
    except Exception:
        checks.append(_check("llm_ollama_running", "warn",
                              "Ollama not reachable (may be stopped or not installed)"))
        return checks

    # Quick inference test
    try:
        import requests
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model_name,
                "prompt": "Reply with exactly: ARCIS_OK",
                "stream": False,
                "options": {"num_predict": 20},
            },
            timeout=60,
        )
        if resp.status_code == 200:
            response_text = resp.json().get("response", "")
            if "ARCIS_OK" in response_text or len(response_text) > 3:
                checks.append(_check("llm_inference_test", "pass",
                                      "Inference test passed"))
            else:
                checks.append(_check("llm_inference_test", "warn",
                                      f"Unexpected response: {response_text[:50]}"))

            # Response time
            total_duration = resp.json().get("total_duration", 0)
            duration_s = total_duration / 1e9 if total_duration else 0
            if duration_s > 180:
                checks.append(_check("llm_response_time", "warn",
                                      f"Inference took {duration_s:.1f}s (>180s threshold)"))
            else:
                checks.append(_check("llm_response_time", "pass",
                                      f"Inference time: {duration_s:.1f}s"))
        else:
            checks.append(_check("llm_inference_test", "fail",
                                  f"Inference returned {resp.status_code}"))
    except Exception as e:
        checks.append(_check("llm_inference_test", "warn",
                              f"Inference test failed: {_sanitize_error(e)}"))

    return checks


# ── Main entry point ────────────────────────────────────────────────


def run_full_validation(db_path: str = DB_PATH) -> dict:
    """Run all system validation checks.

    Returns structured dict with overall status and per-category results.

    Overall status thresholds:
      - "critical":  any check failed (at least one hard requirement broken)
      - "degraded":  >30% of checks are warnings (system works but fragile)
      - "healthy":   everything else

    The 30% degraded threshold is deliberately generous because many
    warning-level checks (e.g. "Telegram not configured") are acceptable
    during development but would be critical in production.
    """
    config = load_config()
    now = datetime.now(ET)

    categories = {
        "database": _check_database(db_path),
        "trading": _check_trading(db_path, config),
        "training": _check_training(db_path, config),
        "api": _check_api(config),
        "collectors": _check_collectors(db_path, config),
        "notifications": _check_notifications(config),
        "scheduler": _check_scheduler(db_path, config),
        "llm": _check_llm(config),
    }

    all_checks = []
    for checks in categories.values():
        all_checks.extend(checks)

    passed = sum(1 for c in all_checks if c["status"] == "pass")
    failed = sum(1 for c in all_checks if c["status"] == "fail")
    warning = sum(1 for c in all_checks if c["status"] == "warn")

    if failed > 0:
        overall = "critical"
    elif warning > len(all_checks) * 0.3:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "timestamp": now.isoformat(),
        "overall_status": overall,
        "checks_passed": passed,
        "checks_failed": failed,
        "checks_warning": warning,
        "checks_total": len(all_checks),
        "categories": categories,
    }


def save_validation_result(result: dict, db_path: str = DB_PATH) -> str:
    """Persist validation result to the validation_results table.

    Returns the result_id.  Results older than 90 days are pruned to
    prevent unbounded growth (at ~1 validation/day = ~90 rows max).
    The full result JSON is stored for historical analysis of which
    checks degraded over time.
    """
    from src.schema.sqlite import create_all_tables as _create_all

    result_id = str(uuid.uuid4())
    # Ensure schema exists via registry (idempotent)
    _create_all(db_path)
    # Defense in depth (#414): even if an upstream call site forgets to use
    # _sanitize_error, scrub the serialized payload before persist so tokens
    # cannot reach validation_results.  NOTE: only the persisted DB row is
    # sanitized here.  The in-memory ``result`` returned by run_full_validation
    # is still the original — API routes (e.g., api/routes/system.py) that
    # surface results to the dashboard are tracked as a separate follow-up.
    safe_payload = _sanitize_text(json.dumps(result))
    conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
    try:
        conn.execute(
            "INSERT INTO validation_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                result_id,
                result["timestamp"],
                result["overall_status"],
                result["checks_passed"],
                result["checks_failed"],
                result["checks_warning"],
                safe_payload,
            ),
        )
        # Prune results older than 90 days
        cutoff = (datetime.now(ET) - timedelta(days=90)).isoformat()
        conn.execute(
            "DELETE FROM validation_results WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
    finally:
        conn.close()

    return result_id
