"""PEAD (Post-Earnings Announcement Drift) enrichment signals.

Called by: data_enrichment/enricher.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_earnings_signals.py

Computes 5 earnings-related signals for pullback trade commentary:
1. Earnings proximity (days until next earnings)
2. Last surprise direction and magnitude
3. Revenue-EPS concordance
4. Analyst revision velocity (30-day trend)
5. Recommendation inconsistency flag (2.5-4.5x stronger signal per research)
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def compute_earnings_signals(
    ticker: str,
    db_path: str = DB_PATH,
) -> dict:
    """Compute all 5 PEAD enrichment signals for a ticker.

    Returns dict with:
    - earnings_proximity_days: int or None
    - last_surprise_pct: float or None
    - last_surprise_direction: "beat" | "miss" | "inline" | None
    - last_revenue_eps_concordant: bool or None
    - analyst_revision_velocity_30d: float or None (% change)
    - recommendation_inconsistency: bool or None
    - earnings_signal_strength: "strong" | "moderate" | "weak" | "none"
    - include_in_prompt: bool (True if within 30 days of earnings AND has signal data)
    """
    result = {
        "earnings_proximity_days": None,
        "last_surprise_pct": None,
        "last_surprise_direction": None,
        "last_revenue_eps_concordant": None,
        "analyst_revision_velocity_30d": None,
        "recommendation_inconsistency": None,
        "earnings_signal_strength": "none",
        "include_in_prompt": False,
    }

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            now = datetime.now(ET)

            # 1. Earnings proximity
            try:
                row = conn.execute(
                    "SELECT MIN(earnings_date) as next_date FROM earnings_calendar "
                    "WHERE ticker = ? AND earnings_date >= date('now')",
                    (ticker,),
                ).fetchone()
                if row and row["next_date"]:
                    next_dt = datetime.fromisoformat(row["next_date"])
                    result["earnings_proximity_days"] = (next_dt.date() - now.date()).days
            except Exception as e:  # Fix for #262: log instead of swallow
                logger.warning("[EARNINGS] %s signal failed for %s: %s", "earnings_proximity", ticker, e)

            # 2. Last surprise — uses schema columns: actual, estimate, surprise, metric
            # Fix: was querying non-existent eps_actual/eps_estimate columns.
            # Schema uses generic actual/estimate with metric='EPS' or 'Revenue'.
            try:
                row = conn.execute(
                    "SELECT actual, estimate, surprise FROM analyst_estimates "
                    "WHERE ticker = ? AND metric = 'EPS' AND actual IS NOT NULL "
                    "ORDER BY date DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                if row and row["estimate"] and row["estimate"] != 0:
                    surprise = row["surprise"] if row["surprise"] is not None else (
                        ((row["actual"] - row["estimate"]) / abs(row["estimate"])) * 100
                    )
                    result["last_surprise_pct"] = round(float(surprise), 1)
                    if surprise > 2:
                        result["last_surprise_direction"] = "beat"
                    elif surprise < -2:
                        result["last_surprise_direction"] = "miss"
                    else:
                        result["last_surprise_direction"] = "inline"
            except Exception as e:
                logger.warning("[EARNINGS] %s signal failed for %s: %s", "last_surprise", ticker, e)

            # 3. Revenue-EPS concordance
            # Fix: was querying non-existent revenue_actual/eps_actual columns.
            # Schema stores EPS and Revenue as separate rows with metric field.
            try:
                eps_row = conn.execute(
                    "SELECT actual, estimate FROM analyst_estimates "
                    "WHERE ticker = ? AND metric = 'EPS' AND actual IS NOT NULL "
                    "ORDER BY date DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                rev_row = conn.execute(
                    "SELECT actual, estimate FROM analyst_estimates "
                    "WHERE ticker = ? AND metric = 'Revenue' AND actual IS NOT NULL "
                    "ORDER BY date DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                if eps_row and rev_row and eps_row["estimate"] and rev_row["estimate"]:
                    rev_beat = float(rev_row["actual"] or 0) > float(rev_row["estimate"] or 0)
                    eps_beat = float(eps_row["actual"] or 0) > float(eps_row["estimate"] or 0)
                    result["last_revenue_eps_concordant"] = (rev_beat == eps_beat)
            except Exception as e:
                logger.warning("[EARNINGS] %s signal failed for %s: %s", "revenue_eps_concordance", ticker, e)

            # 4. Analyst revision velocity (30-day)
            # Fix: was querying non-existent eps_estimate column.
            try:
                rows = conn.execute(
                    "SELECT estimate, collected_at FROM analyst_estimates "
                    "WHERE ticker = ? AND metric = 'EPS' AND estimate IS NOT NULL "
                    "ORDER BY collected_at DESC LIMIT 10",
                    (ticker,),
                ).fetchall()
                if rows and len(rows) >= 2:
                    latest = float(rows[0]["estimate"])
                    oldest = float(rows[-1]["estimate"])
                    if oldest and oldest != 0:
                        velocity = ((latest - oldest) / abs(oldest)) * 100
                        result["analyst_revision_velocity_30d"] = round(velocity, 1)
            except Exception as e:
                logger.warning("[EARNINGS] %s signal failed for %s: %s", "analyst_revision_velocity", ticker, e)

            # 5. Recommendation inconsistency
            if result["last_surprise_direction"] == "beat" and result.get("analyst_revision_velocity_30d") is not None:
                if result["analyst_revision_velocity_30d"] < -2:
                    result["recommendation_inconsistency"] = True
                else:
                    result["recommendation_inconsistency"] = False
            elif result["last_surprise_direction"] == "miss" and result.get("analyst_revision_velocity_30d") is not None:
                if result["analyst_revision_velocity_30d"] > 2:
                    result["recommendation_inconsistency"] = True
                else:
                    result["recommendation_inconsistency"] = False

    except Exception as e:
        logger.warning("[EARNINGS] Signal computation failed for %s: %s", ticker, e)
        return result

    # Compute signal strength
    signals_present = sum([
        result["last_surprise_pct"] is not None,
        result["analyst_revision_velocity_30d"] is not None,
        result["recommendation_inconsistency"] is not None,
    ])

    if result["recommendation_inconsistency"]:
        result["earnings_signal_strength"] = "strong"
    elif signals_present >= 2:
        result["earnings_signal_strength"] = "moderate"
    elif signals_present >= 1:
        result["earnings_signal_strength"] = "weak"

    # Include in prompt if within 30 days and has signal data
    proximity = result["earnings_proximity_days"]
    if proximity is not None and proximity <= 30 and signals_present > 0:
        result["include_in_prompt"] = True

    return result
