"""Data integrity assertions for critical data boundaries.

Called by: services.scan_service
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_data_integrity.py

Logs and skips bad data rather than crashing the pipeline.
"""

import logging
import math

logger = logging.getLogger(__name__)


def validate_features(ticker: str, features: dict) -> bool:
    """Validate feature dict before passing to ranker. Returns False if invalid."""
    try:
        for key, val in features.items():
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                logger.warning("[INTEGRITY] NaN/Inf in features for %s: %s=%s", ticker, key, val)
                return False

        price = features.get("current_price", 0)
        if not isinstance(price, (int, float)) or price <= 0:
            logger.warning("[INTEGRITY] Invalid price for %s: %s", ticker, price)
            return False

        return True
    except Exception as exc:
        logger.warning("[INTEGRITY] Feature validation error for %s: %s", ticker, exc)
        return False


def validate_trade_entry(ticker: str, entry_price: float, stop_price: float,
                         targets: list | None) -> bool:
    """Validate trade parameters before opening a position."""
    try:
        if not entry_price or entry_price <= 0:
            logger.warning("[INTEGRITY] Invalid entry price for %s: %s", ticker, entry_price)
            return False
        if not stop_price or stop_price <= 0:
            logger.warning("[INTEGRITY] Invalid stop price for %s: %s", ticker, stop_price)
            return False
        if targets is None or len(targets) == 0:
            logger.warning("[INTEGRITY] No targets for %s", ticker)
            return False
        if stop_price >= entry_price:
            logger.warning("[INTEGRITY] Stop >= entry for %s: stop=%s entry=%s",
                          ticker, stop_price, entry_price)
            return False
        return True
    except Exception as exc:
        logger.warning("[INTEGRITY] Trade validation error for %s: %s", ticker, exc)
        return False


def validate_universe(universe: list[str]) -> list[str]:
    """Filter out invalid tickers from universe. Returns cleaned list."""
    valid = []
    for t in universe:
        if isinstance(t, str) and 0 < len(t) <= 6 and t.isalpha():
            valid.append(t)
        else:
            logger.warning("[INTEGRITY] Invalid ticker in universe: %s", t)
    if not valid:
        logger.error("[INTEGRITY] Empty universe after validation!")
    return valid
