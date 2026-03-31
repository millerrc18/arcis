"""Google Trends market-wide sentiment collector.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: none
Owns tables: google_trends
Config keys: none
Tests: tests/test_data_collectors.py

Collects search interest for market sentiment terms (not per-ticker).
Per research: "Google Trends alpha is inverted for large caps."
Market-wide sentiment terms are more useful as regime/sentiment indicators.

Rate-limited: batches of 5 terms, 10s sleep between batches.
"""

import logging
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

MARKET_SENTIMENT_TERMS = [
    "stock market crash",
    "recession",
    "inflation",
    "interest rates",
    "fed rate cut",
    "bear market",
    "stock market bubble",
    "market correction",
]

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS google_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    search_interest REAL,
    interest_vs_90d_avg REAL,
    spike_flag INTEGER
);

CREATE INDEX IF NOT EXISTS idx_google_trends_ticker_date
    ON google_trends(ticker, collected_date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def collect_google_trends(
    tickers: list[str] | None = None,
    batch_size: int = 20,
    db_path: str = DB_PATH,
) -> dict:
    """Collect Google Trends data for market-wide sentiment terms.

    The tickers and batch_size params are accepted for backwards compatibility
    but ignored — we now collect fixed market sentiment terms instead.

    Returns: {"terms_collected": int, "spikes_detected": int}
    """
    _init_table(db_path)

    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("[TRENDS] pytrends not installed, skipping")
        return {"terms_collected": 0, "spikes_detected": 0, "error": "pytrends not installed"}

    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    terms_collected = 0
    spikes_detected = 0

    pytrends = TrendReq(hl="en-US", tz=300)

    # Process in sub-batches of 5 (Google Trends limit per request)
    for i in range(0, len(MARKET_SENTIMENT_TERMS), 5):
        batch = MARKET_SENTIMENT_TERMS[i : i + 5]

        try:
            pytrends.build_payload(batch, timeframe="today 3-m")
            interest = pytrends.interest_over_time()

            if interest is None or interest.empty:
                logger.debug("[TRENDS] No data returned for batch %s", batch)
                continue

            with sqlite3.connect(db_path) as conn:
                for term in batch:
                    if term not in interest.columns:
                        continue

                    series = interest[term]
                    if series.empty:
                        continue

                    current_value = float(series.iloc[-1])

                    # Compute 90-day average
                    avg_90d = float(series.mean()) if len(series) > 0 else None
                    vs_avg = None
                    if avg_90d and avg_90d > 0:
                        vs_avg = round(current_value / avg_90d, 4)

                    # Spike detection: > 2σ above 30-day mean
                    spike_flag = 0
                    if len(series) >= 7:
                        recent = series.tail(30)
                        mean_30d = float(recent.mean())
                        std_30d = float(recent.std())
                        if std_30d > 0 and current_value > mean_30d + 2 * std_30d:
                            spike_flag = 1
                            spikes_detected += 1

                    # Store with term as the "ticker" field for schema compatibility
                    conn.execute(
                        """INSERT INTO google_trends
                        (collected_at, collected_date, ticker,
                         search_interest, interest_vs_90d_avg, spike_flag)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            now.isoformat(),
                            today_str,
                            term,
                            current_value,
                            vs_avg,
                            spike_flag,
                        ),
                    )
                    terms_collected += 1

        except Exception as e:
            logger.warning("[TRENDS] Batch failed for %s: %s", batch, e)

        # Rate limit: 10s between batches
        if i + 5 < len(MARKET_SENTIMENT_TERMS):
            time.sleep(10)

    result = {"terms_collected": terms_collected, "spikes_detected": spikes_detected}
    logger.info("[TRENDS] Collection complete: %s", result)
    return result
