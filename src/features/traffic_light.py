"""Traffic Light regime overlay -- controls position sizing.

Called by: services.scan_service
Calls: none
Owns tables: traffic_light_state
Config keys: none
Tests: tests/test_traffic_light.py

Three indicators scored 0-2 each (0=green, 1=yellow, 2=red):
1. VIX Level: <20 → 0, 20-30 → 1, >30 → 2
2. S&P 200-DMA Trend: >3% above → 0, within 3% → 1, below → 2
3. HY Credit Spread Z-score: <0.5 → 0, 0.5-1.5 → 1, >1.5 → 2

Total score 0-6 maps to: GREEN (0-2), YELLOW (3-4), RED (5-6)
Multipliers: GREEN=1.0, YELLOW=0.5, RED=0.1 (minimal, never zero)
Persistence: must see same state 5 consecutive readings before switching.

Research: docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

STATE_TABLE = "traffic_light_state"


def _ensure_state_table(db_path: str = DB_PATH):
    """Seed the singleton row if missing; schema handled by registry."""
    try:
        with sqlite3.connect(db_path) as conn:
            # Ensure exactly one row
            existing = conn.execute(f"SELECT COUNT(*) FROM {STATE_TABLE}").fetchone()[0]
            if existing == 0:
                conn.execute(
                    f"INSERT INTO {STATE_TABLE} (id, current_regime) VALUES (1, 'GREEN')"
                )
            conn.commit()
    except Exception as e:
        logger.warning("[TRAFFIC] State table seed failed: %s", e)


def _classify_vix(vix: float | None) -> int:
    """VIX thresholds from research: <20 green, 20-30 yellow, >30 red."""
    if vix is None:
        return 0
    if vix < 20:
        return 0
    elif vix <= 30:
        return 1
    else:
        return 2


def _classify_trend(spy: pd.DataFrame | None) -> int:
    """Trend from research: >3% above 200-DMA = green, within 3% = yellow, below = red."""
    if spy is None or spy.empty or len(spy) < 200:
        return 1  # Missing data → yellow (conservative)
    try:
        close = spy["Close"] if "Close" in spy.columns else spy["close"]
        sma200 = close.rolling(200).mean()
        current = float(close.iloc[-1])
        sma_val = float(sma200.iloc[-1])

        if pd.isna(sma_val) or sma_val <= 0:
            return 1  # Missing data → yellow

        pct_above = (current - sma_val) / sma_val

        if pct_above > 0.03:
            return 0  # Green: >3% above 200-DMA
        elif pct_above >= 0.0:
            return 1  # Yellow: above but within 3%
        else:
            return 2  # Red: below 200-DMA
    except Exception as e:
        logger.warning("[TRAFFIC] Trend classification failed: %s", e)
        return 1  # Default yellow on error


def _classify_credit(db_path: str = DB_PATH) -> int:
    """Classify HY credit spread z-score from macro_snapshots."""
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT value FROM macro_snapshots "
                "WHERE series_id = 'BAMLH0A0HYM2' "
                "ORDER BY collected_date DESC LIMIT 252"
            ).fetchall()
        if not rows or len(rows) < 20:
            return 0  # No data, assume green
        values = [r[0] for r in rows if r[0] is not None]
        if not values:
            return 0
        current = values[0]
        mean = sum(values) / len(values)
        std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        if std <= 0:
            return 0
        z_score = (current - mean) / std
        if z_score < 0.5:
            return 0
        elif z_score <= 1.5:
            return 1
        else:
            return 2
    except Exception as e:
        logger.warning("[TRAFFIC] Credit spread classification failed: %s", e)
        return 0


def _score_to_regime(total_score: int) -> str:
    if total_score <= 2:
        return "GREEN"
    elif total_score <= 4:
        return "YELLOW"
    else:
        return "RED"


def _regime_to_multiplier(regime: str) -> float:
    """GREEN=full sizing, YELLOW=half, RED=minimal (never zero — always allow some trading)."""
    return {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.1}.get(regime, 1.0)


def compute_traffic_light(
    spy: pd.DataFrame | None = None,
    vix: float | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """Compute the Traffic Light regime overlay.

    Returns dict with: regime_label, total_score, vix_score, trend_score,
    credit_score, sizing_multiplier, persistence_applied.
    """
    _ensure_state_table(db_path)

    vix_score = _classify_vix(vix)
    trend_score = _classify_trend(spy)
    credit_score = _classify_credit(db_path)
    total_score = vix_score + trend_score + credit_score
    raw_regime = _score_to_regime(total_score)

    # Persistence filter with debounce (#144)
    persistence_applied = False
    final_regime = raw_regime
    try:
        with sqlite3.connect(db_path) as conn:
            state = conn.execute(
                f"SELECT current_regime, pending_regime, pending_count, last_transition_at "
                f"FROM {STATE_TABLE} WHERE id = 1"
            ).fetchone()
            if state:
                current, pending, count, last_transition_at = state

                # Debounce: ignore persistence if last transition <5 min ago (#144)
                _debounce_skip = False
                if last_transition_at:
                    try:
                        _last_t = datetime.fromisoformat(last_transition_at)
                        _elapsed = (datetime.now(ET) - _last_t).total_seconds()
                        if _elapsed < 300:
                            _debounce_skip = True
                            logger.debug(
                                "[TRAFFIC] Debounce: last transition %.0fs ago, skipping persistence",
                                _elapsed,
                            )
                    except (ValueError, TypeError):
                        pass

                if _debounce_skip:
                    final_regime = current
                    conn.execute(
                        f"UPDATE {STATE_TABLE} SET last_vix_score = ?, last_trend_score = ?, "
                        f"last_credit_score = ?, last_total_score = ?, updated_at = ? WHERE id = 1",
                        (vix_score, trend_score, credit_score, total_score, datetime.now(ET).isoformat()),
                    )
                    conn.commit()
                elif raw_regime == current:
                    # Same as current — reset pending
                    final_regime = current
                    conn.execute(
                        f"UPDATE {STATE_TABLE} SET pending_regime = NULL, pending_count = 0, "
                        f"last_vix_score = ?, last_trend_score = ?, last_credit_score = ?, "
                        f"last_total_score = ?, updated_at = ? WHERE id = 1",
                        (vix_score, trend_score, credit_score, total_score, datetime.now(ET).isoformat()),
                    )
                elif raw_regime == pending:
                    # Same as pending — increment count
                    new_count = int(count or 0) + 1
                    if new_count >= 5:
                        # Persistence threshold met (5 consecutive readings ≈ 2.5 hours)
                        final_regime = raw_regime
                        _now_iso = datetime.now(ET).isoformat()
                        conn.execute(
                            f"UPDATE {STATE_TABLE} SET current_regime = ?, pending_regime = NULL, "
                            f"pending_count = 0, last_vix_score = ?, last_trend_score = ?, "
                            f"last_credit_score = ?, last_total_score = ?, updated_at = ?, "
                            f"last_transition_at = ? WHERE id = 1",
                            (raw_regime, vix_score, trend_score, credit_score, total_score, _now_iso, _now_iso),
                        )
                    else:
                        # Not yet — keep current, update pending count
                        final_regime = current
                        persistence_applied = True
                        conn.execute(
                            f"UPDATE {STATE_TABLE} SET pending_count = ?, "
                            f"last_vix_score = ?, last_trend_score = ?, last_credit_score = ?, "
                            f"last_total_score = ?, updated_at = ? WHERE id = 1",
                            (new_count, vix_score, trend_score, credit_score, total_score, datetime.now(ET).isoformat()),
                        )
                else:
                    # New pending regime
                    final_regime = current
                    persistence_applied = True
                    conn.execute(
                        f"UPDATE {STATE_TABLE} SET pending_regime = ?, pending_count = 1, "
                        f"last_vix_score = ?, last_trend_score = ?, last_credit_score = ?, "
                        f"last_total_score = ?, updated_at = ? WHERE id = 1",
                        (raw_regime, vix_score, trend_score, credit_score, total_score, datetime.now(ET).isoformat()),
                    )
                conn.commit()
    except Exception as e:
        logger.warning("[TRAFFIC] Persistence filter failed: %s — using raw regime", e)
        final_regime = raw_regime

    return {
        "regime_label": final_regime,
        "total_score": total_score,
        "vix_score": vix_score,
        "trend_score": trend_score,
        "credit_score": credit_score,
        "sizing_multiplier": _regime_to_multiplier(final_regime),
        "persistence_applied": persistence_applied,
        "raw_regime": raw_regime,
    }
