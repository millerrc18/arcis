"""Feature importance tracking with trend detection.

Called by: cli.commands, evaluation.cto_report
Calls: journal.store
Owns tables: none
Config keys: none
Tests: tests/test_feature_importance.py

Computes which features most strongly predict trade outcomes.
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def compute_feature_importance(days: int = 30,
                               db_path: str = DB_PATH) -> dict:
    """Compute which features most strongly predict trade outcomes.

    Uses closed trades from the last N days. For each feature,
    computes correlation with P&L and win probability.
    """
    from src.journal.store import get_closed_shadow_trades, get_recommendations_in_period

    closed = get_closed_shadow_trades(days=days, db_path=db_path)
    recommendations = get_recommendations_in_period(days=days, db_path=db_path)

    if not closed:
        return {"period_days": days, "closed_trades": 0, "features": []}

    # Build recommendation lookup
    rec_map = {r.get("recommendation_id"): r for r in recommendations}

    # Collect feature values and outcomes
    feature_data = defaultdict(lambda: {"values": [], "pnls": [], "wins": []})
    categorical_data = defaultdict(lambda: defaultdict(lambda: {"total": 0, "wins": 0, "pnls": []}))

    for t in closed:
        rec_id = t.get("recommendation_id")
        rec = rec_map.get(rec_id, {})
        pnl = t.get("pnl_pct", 0) or 0
        won = 1 if float(t.get("pnl_dollars") or 0) > 0 else 0

        # Numeric features
        numeric_features = {
            "pullback_depth_pct": rec.get("pullback_depth_pct"),
            "atr": rec.get("atr"),
            "priority_score": rec.get("priority_score"),
            "confidence_score": rec.get("confidence_score"),
            "llm_conviction": rec.get("llm_conviction"),
        }

        for name, val in numeric_features.items():
            if val is not None:
                feature_data[name]["values"].append(float(val))
                feature_data[name]["pnls"].append(pnl)
                feature_data[name]["wins"].append(won)

        # Categorical features
        cat_features = {
            "trend_state": rec.get("trend_state"),
            "relative_strength_state": rec.get("relative_strength_state"),
            "volume_state": rec.get("volume_state"),
            "event_risk_flag": rec.get("event_risk_flag"),
            "market_regime": rec.get("market_regime"),
        }

        for name, val in cat_features.items():
            if val:
                categorical_data[name][val]["total"] += 1
                categorical_data[name][val]["wins"] += won
                categorical_data[name][val]["pnls"].append(pnl)

    # Compute correlations for numeric features
    features_result = []
    for name, data in feature_data.items():
        if len(data["values"]) < 5:
            continue

        corr = _pearson_correlation(data["values"], data["pnls"])
        abs_corr = abs(corr)

        if abs_corr > 0.3:
            power = "strong"
        elif abs_corr > 0.15:
            power = "moderate"
        else:
            power = "weak"

        # Find optimal range (by quartile win rate)
        optimal_range = _find_optimal_range(data["values"], data["wins"])

        # Win rate in optimal range vs outside
        wr_in = 0
        wr_out = 0
        in_count = 0
        out_count = 0
        if optimal_range:
            for i, v in enumerate(data["values"]):
                if optimal_range["min"] <= v <= optimal_range["max"]:
                    in_count += 1
                    wr_in += data["wins"][i]
                else:
                    out_count += 1
                    wr_out += data["wins"][i]

        features_result.append({
            "name": name,
            "correlation_with_pnl": round(corr, 3),
            "predictive_power": power,
            "optimal_range": optimal_range,
            "win_rate_in_range": round(wr_in / in_count, 2) if in_count > 0 else 0,
            "win_rate_outside": round(wr_out / out_count, 2) if out_count > 0 else 0,
            "sample_size": len(data["values"]),
        })

    # Sort by absolute correlation
    features_result.sort(key=lambda x: abs(x["correlation_with_pnl"]), reverse=True)

    # Categorical feature analysis (regime importance)
    regime_importance = {}
    for name, categories in categorical_data.items():
        best_cat = None
        best_wr = 0
        worst_cat = None
        worst_wr = 1
        overall_corr = 0

        for cat, data in categories.items():
            wr = data["wins"] / data["total"] if data["total"] > 0 else 0
            if wr > best_wr:
                best_wr = wr
                best_cat = cat
            if wr < worst_wr:
                worst_wr = wr
                worst_cat = cat

        regime_importance[name] = {
            "best": best_cat,
            "best_win_rate": round(best_wr, 2),
            "worst": worst_cat,
            "worst_win_rate": round(worst_wr, 2),
            "spread": round(best_wr - worst_wr, 2),
        }

    # Trend detection: compare last 14 days vs full period
    declining = []
    emerging = []
    if days >= 14:
        for name in feature_data:
            recent_data = defaultdict(lambda: {"values": [], "pnls": []})
            # This is simplified — would need date filtering on the actual trades
            # For now, use the last 1/3 of data as "recent"
            n = len(feature_data[name]["values"])
            if n < 10:
                continue
            split = n * 2 // 3
            recent_vals = feature_data[name]["values"][split:]
            recent_pnls = feature_data[name]["pnls"][split:]
            old_vals = feature_data[name]["values"][:split]
            old_pnls = feature_data[name]["pnls"][:split]

            recent_corr = _pearson_correlation(recent_vals, recent_pnls) if len(recent_vals) >= 5 else 0
            old_corr = _pearson_correlation(old_vals, old_pnls) if len(old_vals) >= 5 else 0

            if abs(old_corr) > 0.2 and abs(recent_corr) < 0.1:
                declining.append(f"{name} was predictive ({old_corr:.2f}) but has lost significance ({recent_corr:.2f})")
            elif abs(old_corr) < 0.1 and abs(recent_corr) > 0.2:
                emerging.append(f"{name} is newly predictive ({recent_corr:.2f}) in recent trades")

    return {
        "period_days": days,
        "closed_trades": len(closed),
        "features": features_result,
        "regime_importance": regime_importance,
        "declining_features": declining,
        "emerging_features": emerging,
    }


def _pearson_correlation(x: list, y: list) -> float:
    """Compute Pearson correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = sum((xi - mean_x) ** 2 for xi in x)
    denom_y = sum((yi - mean_y) ** 2 for yi in y)

    denominator = (denom_x * denom_y) ** 0.5
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _find_optimal_range(values: list, wins: list) -> dict | None:
    """Find the value range with the highest win rate."""
    if len(values) < 5:
        return None

    # Sort by value and split into quartiles
    paired = sorted(zip(values, wins))
    n = len(paired)
    q_size = max(n // 4, 1)

    best_wr = 0
    best_range = None

    for i in range(0, n - q_size + 1, max(1, q_size // 2)):
        chunk = paired[i:i + q_size]
        wr = sum(w for _, w in chunk) / len(chunk)
        if wr > best_wr:
            best_wr = wr
            best_range = {"min": round(chunk[0][0], 2), "max": round(chunk[-1][0], 2)}

    return best_range
