"""Per-desk Alpaca TradingClient factory.

Called by: src.shadow_trading.alpaca_adapter._get_trading_client,
           src.platform.shadow_harness, src.scheduler.watch (startup verify).
Calls: alpaca.trading.client.TradingClient, src.config.load_config, os.environ.
Owns tables: none.
Config keys: desks.{desk}.alpaca_key_env, desks.{desk}.alpaca_secret_env,
             desks.{desk}.enabled.
Tests: tests/shadow_trading/test_alpaca_clients.py.

Cached per desk. Threadsafe via module-level lock.
verify_accounts_distinct() asserts that 'swing' and 'research' desks
resolve to different Alpaca account_numbers — catches the
"both desks pointing at same paper account" mis-config bug. Skipped
safely if either desk is not configured or not enabled.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from alpaca.trading.client import TradingClient

from src.config import load_config

logger = logging.getLogger(__name__)

_CLIENT_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def get_client(desk: str) -> TradingClient:
    """Return a TradingClient for the named desk. Cached per desk.

    Reads desks.{desk}.alpaca_key_env + alpaca_secret_env from config,
    resolves env var values, constructs TradingClient(paper=True) with
    client.desk_tag = desk for downstream guardrail assertions.
    """
    if desk in _CLIENT_CACHE:
        return _CLIENT_CACHE[desk]
    cfg = load_config()
    desks_cfg = cfg.get("desks", {})
    desk_cfg = desks_cfg.get(desk)
    if not desk_cfg:
        raise ValueError(f"unknown desk: {desk!r}; check desks.* config section")
    key_var = desk_cfg.get("alpaca_key_env")
    sec_var = desk_cfg.get("alpaca_secret_env")
    if not key_var or not sec_var:
        raise ValueError(
            f"desk {desk!r} missing alpaca_key_env / alpaca_secret_env in config"
        )
    api_key = os.environ.get(key_var)
    api_sec = os.environ.get(sec_var)
    if not api_key or not api_sec:
        raise RuntimeError(
            f"desk {desk!r} env var {key_var} or {sec_var} not set; "
            "operator must export credentials before watch loop starts"
        )
    client = TradingClient(api_key=api_key, secret_key=api_sec, paper=True)
    client.desk_tag = desk
    with _CACHE_LOCK:
        _CLIENT_CACHE[desk] = client
    return client


def verify_accounts_distinct() -> None:
    """Raise if swing and research resolve to the same Alpaca account.

    MUST be called at watch-loop startup before any desk-aware Alpaca
    operation runs. Prevents the "both desks share a paper account"
    silent cross-contamination bug.

    Skips safely if either desk isn't configured (pre-account-setup
    phase) or research desk is disabled.
    """
    cfg = load_config()
    desks_cfg = cfg.get("desks", {})
    swing_cfg = desks_cfg.get("swing")
    research_cfg = desks_cfg.get("research")
    if not swing_cfg or not research_cfg:
        logger.info(
            "[ALPACA] verify_accounts_distinct skipped — swing or research "
            "desk not configured yet"
        )
        return
    if not research_cfg.get("enabled", False):
        logger.info(
            "[ALPACA] verify_accounts_distinct skipped — research desk disabled"
        )
        return
    swing_acct = get_client("swing").get_account().account_number
    research_acct = get_client("research").get_account().account_number
    if swing_acct == research_acct:
        raise RuntimeError(
            f"swing and research desks resolved to the same Alpaca "
            f"account ({swing_acct}). Either they are mis-configured "
            f"(same key/secret env vars) or pointing at the same paper "
            f"account. Aborting — fix config before any shadow-trading."
        )
    logger.info(
        "[ALPACA] verify_accounts_distinct OK: swing=%s research=%s",
        swing_acct, research_acct,
    )
