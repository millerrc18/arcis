"""Derived per-ticker options metrics computed from raw chain snapshots.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: none
Owns tables: options_metrics
Config keys: none
Tests: none

Must run AFTER collect_options_chains().
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS options_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    iv_rank REAL,
    iv_percentile REAL,
    put_call_volume_ratio REAL,
    put_call_oi_ratio REAL,
    atm_iv_30d REAL,
    iv_skew REAL,
    unusual_volume_flag INTEGER,
    max_unusual_volume_ratio REAL,
    total_call_volume INTEGER,
    total_put_volume INTEGER,
    total_call_oi INTEGER,
    total_put_oi INTEGER
);

CREATE INDEX IF NOT EXISTS idx_options_metrics_ticker_date
    ON options_metrics(ticker, collected_date);
CREATE INDEX IF NOT EXISTS idx_options_metrics_date
    ON options_metrics(collected_date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def compute_options_metrics(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> dict:
    """Compute derived options metrics from today's chain snapshots.

    Returns: {"tickers_computed": int, "unusual_flags": int}
    """
    _init_table(db_path)
    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    tickers_computed = 0
    unusual_flags = 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        for ticker in tickers:
            try:
                # Get today's chain data
                rows = conn.execute(
                    """SELECT * FROM options_chains
                    WHERE ticker = ? AND collected_at >= ?
                    ORDER BY expiration, strike""",
                    (ticker, today_str),
                ).fetchall()

                if not rows:
                    continue

                underlying_price = rows[0]["underlying_price"]
                if not underlying_price:
                    continue

                # Split calls and puts
                calls = [r for r in rows if r["option_type"] == "call"]
                puts = [r for r in rows if r["option_type"] == "put"]

                # Total volumes and OI
                total_call_vol = sum(r["volume"] or 0 for r in calls)
                total_put_vol = sum(r["volume"] or 0 for r in puts)
                total_call_oi = sum(r["open_interest"] or 0 for r in calls)
                total_put_oi = sum(r["open_interest"] or 0 for r in puts)

                # Put/call ratios
                pc_vol_ratio = None
                if total_call_vol > 0:
                    pc_vol_ratio = round(total_put_vol / total_call_vol, 4)

                pc_oi_ratio = None
                if total_call_oi > 0:
                    pc_oi_ratio = round(total_put_oi / total_call_oi, 4)

                # Find nearest 30-DTE expiration
                target_dte = now + timedelta(days=30)
                expirations = sorted(set(r["expiration"] for r in rows))
                best_exp = min(
                    expirations,
                    key=lambda e: abs(
                        (datetime.strptime(e, "%Y-%m-%d") - target_dte.replace(tzinfo=None)).days
                    ),
                )

                # ATM IV for ~30 DTE
                exp_calls = [r for r in calls if r["expiration"] == best_exp]
                atm_iv = _find_atm_iv(exp_calls, underlying_price)

                # IV skew: approximate 25-delta put IV minus 25-delta call IV
                exp_puts = [r for r in puts if r["expiration"] == best_exp]
                iv_skew = _compute_iv_skew(exp_calls, exp_puts, underlying_price)

                # Unusual volume: any strike where volume > 3x OI
                unusual_flag = 0
                max_vol_oi_ratio = 0.0
                for r in rows:
                    vol = r["volume"] or 0
                    oi = r["open_interest"] or 0
                    if oi > 0 and vol > 3 * oi:
                        unusual_flag = 1
                        ratio = vol / oi
                        if ratio > max_vol_oi_ratio:
                            max_vol_oi_ratio = ratio

                if unusual_flag:
                    unusual_flags += 1

                # IV rank: requires historical ATM IV data
                iv_rank, iv_percentile = _compute_iv_rank(
                    conn, ticker, atm_iv, today_str
                )

                conn.execute(
                    """INSERT INTO options_metrics
                    (collected_at, collected_date, ticker,
                     iv_rank, iv_percentile, put_call_volume_ratio,
                     put_call_oi_ratio, atm_iv_30d, iv_skew,
                     unusual_volume_flag, max_unusual_volume_ratio,
                     total_call_volume, total_put_volume,
                     total_call_oi, total_put_oi)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        now.isoformat(),
                        today_str,
                        ticker,
                        iv_rank,
                        iv_percentile,
                        pc_vol_ratio,
                        pc_oi_ratio,
                        atm_iv,
                        iv_skew,
                        unusual_flag,
                        round(max_vol_oi_ratio, 2) if max_vol_oi_ratio > 0 else None,
                        total_call_vol,
                        total_put_vol,
                        total_call_oi,
                        total_put_oi,
                    ),
                )
                tickers_computed += 1

            except Exception as e:
                logger.warning("[OPTIONS_METRICS] Error computing %s: %s", ticker, e)

    result = {"tickers_computed": tickers_computed, "unusual_flags": unusual_flags}
    logger.info("[OPTIONS_METRICS] Computation complete: %s", result)
    return result


def _find_atm_iv(calls: list, underlying_price: float) -> float | None:
    """Find the ATM implied volatility from a list of call options."""
    if not calls:
        return None
    # Find the call closest to spot price
    best = min(calls, key=lambda r: abs(r["strike"] - underlying_price))
    return best["implied_volatility"]


def _compute_iv_skew(
    calls: list, puts: list, underlying_price: float
) -> float | None:
    """Approximate 25-delta IV skew (OTM put IV - OTM call IV).

    Uses strikes at ~5% OTM as proxy for 25-delta.
    """
    if not calls or not puts:
        return None

    # 25-delta put is roughly 5% OTM (below spot)
    put_target = underlying_price * 0.95
    # 25-delta call is roughly 5% OTM (above spot)
    call_target = underlying_price * 1.05

    best_put = min(puts, key=lambda r: abs(r["strike"] - put_target))
    best_call = min(calls, key=lambda r: abs(r["strike"] - call_target))

    put_iv = best_put["implied_volatility"]
    call_iv = best_call["implied_volatility"]

    if put_iv is not None and call_iv is not None:
        return round(put_iv - call_iv, 4)
    return None


def _compute_iv_rank(
    conn: sqlite3.Connection,
    ticker: str,
    current_iv: float | None,
    today_str: str,
) -> tuple[float | None, float | None]:
    """Compute IV rank and IV percentile from historical ATM IV data.

    IV Rank = (current - 1yr low) / (1yr high - 1yr low) * 100
    IV Percentile = % of days in past year with lower IV
    Requires ≥20 days of historical data.
    """
    if current_iv is None:
        return None, None

    # Get historical ATM IV values from past year
    rows = conn.execute(
        """SELECT atm_iv_30d FROM options_metrics
        WHERE ticker = ? AND collected_date < ? AND atm_iv_30d IS NOT NULL
        ORDER BY collected_date DESC
        LIMIT 252""",
        (ticker, today_str),
    ).fetchall()

    historical_ivs = [r[0] for r in rows if r[0] is not None]

    if len(historical_ivs) < 20:
        return None, None

    iv_min = min(historical_ivs)
    iv_max = max(historical_ivs)

    # IV Rank
    if iv_max == iv_min:
        iv_rank = 50.0
    else:
        iv_rank = round((current_iv - iv_min) / (iv_max - iv_min) * 100, 1)

    # IV Percentile
    days_below = sum(1 for iv in historical_ivs if iv < current_iv)
    iv_percentile = round(days_below / len(historical_ivs) * 100, 1)

    return iv_rank, iv_percentile
