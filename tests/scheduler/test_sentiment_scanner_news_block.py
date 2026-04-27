"""Regression-locks: sentiment_scanner news block must not silently log a
successful refresh when no Finnhub news fetch was performed.

Issue #686 — The Tier 3 news block imported `_fetch_finnhub_news` (which
does not exist in enricher.py), causing the import to always raise
ImportError. The except clause appended nothing to summary["refreshed"]
and recorded no staleness — BUT the lines that appended "news" and called
`_record_staleness` were INSIDE the try block AFTER the import, so if the
import somehow succeeded on a future code change they would fire without
an actual API call.

Fix: remove the entire dead block. This test asserts:
1. `run_sentiment_refresh` never appends "news" to summary["refreshed"]
   (no stub for Finnhub news is wired in this scheduler).
2. `_record_staleness` is never called with source="news".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _run_with_mocks() -> dict:
    """Run sentiment refresh with all external I/O mocked out."""
    import pandas as pd
    from src.scheduler.sentiment_scanner import run_sentiment_refresh

    spy_df = pd.DataFrame(
        {"Close": [400.0]},
        index=pd.bdate_range("2025-06-01", periods=1),
    )
    regime = {"regime_label": "bull", "market_breadth_pct": 60.0}

    with patch("yfinance.download", return_value=spy_df), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=spy_df), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={}), \
         patch("src.features.regime.compute_market_regime", return_value=regime), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.data_enrichment.staleness.record_fetch") as mock_staleness:
        summary = run_sentiment_refresh({})

    return summary, mock_staleness


def test_news_not_in_refreshed_list():
    """After the dead-block removal, 'news' must NOT appear in
    summary['refreshed']. Pre-fix: the block was dead (import always
    raised ImportError and was caught), so 'news' was never appended.
    This test locks that behaviour — if someone re-introduces the dead
    block by accident, the test will catch it IF the block gets wired
    incorrectly.
    """
    summary, _ = _run_with_mocks()
    assert "news" not in summary["refreshed"], (
        f"'news' must not appear in summary['refreshed'] — no Finnhub news "
        f"fetch is wired in sentiment_scanner. Got: {summary['refreshed']}"
    )


def test_staleness_not_called_for_news():
    """record_fetch must never be called with source='news' from
    sentiment_scanner.run_sentiment_refresh — there is no actual news
    fetch to record. Pre-fix (and post-fix): the ImportError caused the
    staleness call to never execute; post-fix the block is gone entirely.
    """
    _, mock_staleness = _run_with_mocks()
    news_calls = [
        call for call in mock_staleness.call_args_list
        if call.args and call.args[0] == "news"
    ]
    assert news_calls == [], (
        f"record_fetch must not be called with source='news' — no Finnhub "
        f"news fetch is performed. Got calls: {mock_staleness.call_args_list}"
    )


def test_no_finnhub_news_import_in_sentiment_scanner():
    """The dead import of `_fetch_finnhub_news` from enricher must not
    appear in the sentiment_scanner module source. This is a static
    check that ensures the dead block is actually removed from the file.
    """
    import inspect
    from src.scheduler import sentiment_scanner
    src = inspect.getsource(sentiment_scanner)
    assert "_fetch_finnhub_news" not in src, (
        "Dead import `_fetch_finnhub_news` must be removed from "
        "sentiment_scanner.py — the function does not exist in enricher.py "
        "and the import always raised ImportError (issue #686)."
    )
