"""Backtest attribution + section-score injection helpers.

Called by: src.platform.backtest_engine.
Calls: sqlite3 (for cosine score lookup), src.platform.features.cosine_similarity.
Owns tables: none (reads from edgar_filings for cosine scores).
Config keys: PLATFORM_EDGAR_DB (optional env override inherited from backtest_engine).
Tests: tests/platform/test_backtest_engine.py (covered via end-to-end tests).

Extracted from backtest_engine.py to resolve size guardrail violation
(was 432 lines; limit 400). No behavior change.
"""

from __future__ import annotations

import logging
import os

from src.platform.features.cosine_similarity import cosine_similarity_yoy

logger = logging.getLogger(__name__)


def _inject_cosine_scores(
    sections: dict,
    signal: list[dict],
    ticker: str,
    accession: str,
    db_path: str,
) -> dict:
    """Compute YoY cosine similarity for each cosine_similarity signal condition
    and inject the result under '<target>_cosine_yoy' so _evaluate_event_signal
    can read them.

    If a pre-computed value already exists in sections (e.g. from a test fixture
    that seeds sections_json directly), it is left untouched.  Live computation
    is only attempted when the key is absent.
    """
    live_db = os.environ.get("PLATFORM_EDGAR_DB", db_path)
    for condition in signal:
        if condition.get("metric") != "cosine_similarity":
            continue
        target = condition.get("target", "")
        key = f"{target}_cosine_yoy"
        if key in sections:
            continue  # already present (e.g. test fixture)
        try:
            cos = cosine_similarity_yoy(ticker, accession, target, live_db)
        except Exception as exc:
            logger.debug(
                "[PLATFORM] cosine_similarity_yoy failed %s/%s/%s: %s",
                ticker, accession, target, exc,
            )
            cos = None
        if cos is not None:
            sections[key] = cos
    return sections
