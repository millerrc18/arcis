"""Exponential backoff retry utility.

Called by: data_enrichment.news, data_enrichment.insiders, data_enrichment.fundamentals,
           data_enrichment.macro, data_collection.*
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_retry.py
"""

import logging
import random
import time

logger = logging.getLogger(__name__)


def retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """Call fn with exponential backoff on failure.

    Args:
        fn: Callable to execute (no arguments — use functools.partial or lambda)
        max_retries: Maximum number of attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Result of fn(), or None if all retries exhausted
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except exceptions as exc:
            if attempt == max_retries - 1:
                logger.warning("[RETRY] %s failed after %d attempts: %s",
                               fn.__name__ if hasattr(fn, '__name__') else 'fn',
                               max_retries, exc)
                return None
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = delay * random.uniform(-0.2, 0.2)
            actual_delay = max(0.1, delay + jitter)
            logger.warning("[RETRY] %s attempt %d/%d failed: %s — retrying in %.1fs",
                           fn.__name__ if hasattr(fn, '__name__') else 'fn',
                           attempt + 1, max_retries, exc, actual_delay)
            time.sleep(actual_delay)
    return None
