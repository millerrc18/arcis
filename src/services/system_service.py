"""System service for preflight checks and config management.

Called by: api.routes.system, cli.commands
Calls: llm.client, risk.governor, training.versioning
Owns tables: none
Config keys: alpaca, api_key, api_secret, base_url, bootcamp, bot_token, chat_id, email, enabled, live_trading, llm, model, password, phase, shadow_trading, smtp_server, telegram, training, username
Tests: tests/test_services.py
"""
import logging
import sqlite3
from pathlib import Path

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)


def get_system_status(config: dict) -> dict:
    """Run preflight checks and return system status."""
    from src.llm.client import is_llm_available
    from src.training.versioning import get_active_model_name, get_training_example_counts

    # Config
    config_loaded = bool(config)
    local_config_exists = Path("config/settings.local.yaml").exists()
    config_source = "local" if local_config_exists else "example"

    # Email
    email_cfg = config.get("email", {})
    email_configured = bool(
        email_cfg.get("smtp_server") and
        email_cfg.get("username") and
        email_cfg.get("password") and
        email_cfg.get("username") != "your-assistant-email@gmail.com"
    )

    # Alpaca
    alpaca_connected = False
    alpaca_equity = None
    try:
        import requests
        alpaca_cfg = config.get("alpaca", {})
        api_key = alpaca_cfg.get("api_key", "")
        api_secret = alpaca_cfg.get("api_secret", "")
        base_url = alpaca_cfg.get("base_url", "https://paper-api.alpaca.markets")
        if api_key and api_key != "YOUR_PAPER_API_KEY":
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
                alpaca_connected = True
                alpaca_equity = float(acct.get("equity", 0))
    except Exception as e:
        logger.debug("Alpaca connection check failed: %s", e)

    # Shadow trading
    shadow_trading_enabled = config.get("shadow_trading", {}).get("enabled", False)
    live_trading_enabled = config.get("live_trading", {}).get("enabled", False)

    # Telegram
    telegram_cfg = config.get("telegram", {})
    telegram_enabled = bool(telegram_cfg.get("enabled", False))
    telegram_configured = bool(
        telegram_enabled
        and telegram_cfg.get("bot_token")
        and telegram_cfg.get("chat_id")
        and telegram_cfg.get("bot_token") != "your-bot-token-from-botfather"
        and telegram_cfg.get("chat_id") != "your-chat-id"
    )

    # Kill switch
    kill_switch_halted = False
    try:
        from src.risk.governor import _is_halted

        kill_switch_halted = _is_halted()
    except Exception as e:
        logger.debug("Kill switch status check failed: %s", e)

    # Ollama/LLM
    ollama_available = is_llm_available()
    llm_cfg = config.get("llm", {})
    llm_enabled = llm_cfg.get("enabled", False)
    llm_model = llm_cfg.get("model", "qwen3:8b")

    # Model version
    model_version = get_active_model_name()

    # Journal
    journal_recs = 0
    journal_trades = 0
    try:
        db_path = Path(DB_PATH)
        if db_path.exists():
            with connect_db(str(db_path)) as conn:
                journal_recs = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
                journal_trades = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(quarantined, 0) = 0").fetchone()[0]
    except Exception as e:
        logger.debug("Journal DB query failed: %s", e)

    # Training
    training_cfg = config.get("training", {})
    training_enabled = training_cfg.get("enabled", False)
    training_examples = 0
    if training_enabled:
        try:
            t_counts = get_training_example_counts()
            training_examples = t_counts["total"]
        except Exception as e:
            logger.debug("Training example count failed: %s", e)

    # Bootcamp
    bootcamp_cfg = config.get("bootcamp", {})
    bootcamp_enabled = bootcamp_cfg.get("enabled", False)
    bootcamp_phase = bootcamp_cfg.get("phase", 1) if bootcamp_enabled else None

    # IB / live broker connection status
    ib_connected = False
    live_broker = config.get("live_trading", {}).get("broker", "alpaca")
    try:
        from src.trading.broker_factory import get_live_broker
        _broker = get_live_broker(config)
        ib_connected = _broker.is_connected()
    except Exception as _broker_err:
        ib_connected = False
        # Route through log_and_persist so the failure appears in
        # BrokerExceptionsPanel (PR #690 O1). Live-broker probe failure is
        # non-fatal for status — operator sees ib_connected=False.
        from src.shadow_trading.broker_exception_logger import log_and_persist
        log_and_persist(
            ticker="(all)",
            operation="get_live_broker",
            broker=live_broker,
            exc=_broker_err,
            recoverable=True,
        )

    from src.version import VERSION as _ARCIS_VERSION
    return {
        "version": _ARCIS_VERSION,  # #631-15: single source of truth (src/version.py)
        "config_loaded": config_loaded,
        "config_source": config_source,
        "email_configured": email_configured,
        "alpaca_connected": alpaca_connected,
        "alpaca_equity": alpaca_equity,
        "shadow_trading_enabled": shadow_trading_enabled,
        "live_trading_enabled": live_trading_enabled,
        "telegram_enabled": telegram_enabled,
        "telegram_configured": telegram_configured,
        "kill_switch_halted": kill_switch_halted,
        "ollama_available": ollama_available,
        "llm_enabled": llm_enabled,
        "llm_model": llm_model,
        "model_version": model_version,
        "journal_recommendations": journal_recs,
        "journal_shadow_trades": journal_trades,
        "training_enabled": training_enabled,
        "training_examples": training_examples,
        "bootcamp_enabled": bootcamp_enabled,
        "bootcamp_phase": bootcamp_phase,
        "ib_connected": ib_connected,
        "live_broker": live_broker,
    }
