"""EOD options chain snapshot collector via yfinance.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: universe/sp100.py
Owns tables: options_chains
Config keys: none
Tests: none

Captures full options chains for the universe, filtered to
expirations <=6 months out and strikes within +/-30% of spot.
"""

import logging
import math
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

from src.universe.sp100 import to_yfinance_ticker

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS options_chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    bid REAL,
    ask REAL,
    last_price REAL,
    volume INTEGER,
    open_interest INTEGER,
    implied_volatility REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    in_the_money INTEGER,
    underlying_price REAL
);

CREATE INDEX IF NOT EXISTS idx_options_chains_ticker_date
    ON options_chains(ticker, collected_at);
CREATE INDEX IF NOT EXISTS idx_options_chains_collected
    ON options_chains(collected_at);
CREATE INDEX IF NOT EXISTS idx_options_chains_expiration
    ON options_chains(ticker, expiration);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def collect_options_chains(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> dict:
    """Collect EOD options chain snapshots for all tickers.

    Returns: {"tickers_collected": int, "contracts_stored": int, "errors": int}
    """
    _init_table(db_path)
    now = datetime.now(ET)
    collected_at = now.isoformat()
    max_expiration = now + timedelta(days=180)

    tickers_collected = 0
    contracts_stored = 0
    errors = 0

    for ticker in tickers:
        try:
            stock = yf.Ticker(to_yfinance_ticker(ticker))

            # Get available expirations
            try:
                expirations = stock.options
            except Exception:
                logger.debug("No options data for %s", ticker)
                continue

            if not expirations:
                continue

            # Get current price
            hist = stock.history(period="1d")
            if hist.empty:
                logger.debug("No price data for %s, skipping options", ticker)
                continue
            underlying_price = float(hist["Close"].iloc[-1])

            # Validate underlying_price (#125)
            if underlying_price is None or math.isnan(underlying_price) or underlying_price <= 0:
                logger.warning("[OPTIONS] %s: invalid underlying_price (%.4s), skipping",
                               ticker, underlying_price)
                continue

            strike_low = underlying_price * 0.70
            strike_high = underlying_price * 1.30

            rows = []
            for exp in expirations:
                # Filter to ≤6 months out
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                if exp_date > max_expiration.replace(tzinfo=None):
                    continue

                try:
                    chain = stock.option_chain(exp)
                except Exception as e:
                    logger.debug("Failed to get chain for %s %s: %s", ticker, exp, e)
                    continue

                for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                    if df is None or df.empty:
                        continue

                    # Filter strikes to ±30% of spot
                    mask = (df["strike"] >= strike_low) & (df["strike"] <= strike_high)
                    filtered = df[mask]

                    for _, row in filtered.iterrows():
                        rows.append((
                            collected_at,
                            ticker,
                            exp,
                            float(row.get("strike", 0)),
                            opt_type,
                            _safe_float(row.get("bid")),
                            _safe_float(row.get("ask")),
                            _safe_float(row.get("lastPrice")),
                            _safe_int(row.get("volume")),
                            _safe_int(row.get("openInterest")),
                            _safe_float(row.get("impliedVolatility")),
                            _safe_float(row.get("delta")),
                            _safe_float(row.get("gamma")),
                            _safe_float(row.get("theta")),
                            _safe_float(row.get("vega")),
                            1 if row.get("inTheMoney", False) else 0,
                            underlying_price,
                        ))

            if rows:
                with sqlite3.connect(db_path) as conn:
                    conn.executemany(
                        """INSERT INTO options_chains
                        (collected_at, ticker, expiration, strike, option_type,
                         bid, ask, last_price, volume, open_interest,
                         implied_volatility, delta, gamma, theta, vega,
                         in_the_money, underlying_price)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        rows,
                    )
                contracts_stored += len(rows)
                tickers_collected += 1

            logger.info("[OPTIONS] %s: %d contracts stored", ticker, len(rows))

        except Exception as e:
            logger.warning("[OPTIONS] Error collecting %s: %s", ticker, e)
            errors += 1

        # Rate limit: be respectful to yfinance
        time.sleep(0.5)

    result = {
        "tickers_collected": tickers_collected,
        "contracts_stored": contracts_stored,
        "errors": errors,
    }
    logger.info("[OPTIONS] Collection complete: %s", result)
    return result


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else int(f)
    except (ValueError, TypeError):
        return None
