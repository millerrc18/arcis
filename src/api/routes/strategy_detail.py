"""Local API routes for per-strategy trade detail analytics.

Called by: api.app
Calls: src.utils.db.connect_db
Owns tables: none (reads shadow_trades, recommendations)
Config keys: none
Tests: tests/api/test_route_parity.py

Endpoints:
    GET /strategy-detail/{strategy_type}  - Per-strategy trade breakdown
"""

import logging
import sqlite3
from contextlib import closing

from fastapi import APIRouter

from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["strategy"])
logger = logging.getLogger(__name__)

_QUERY = (
    "SELECT st.ticker, st.actual_entry_time as entry_date, "
    "st.actual_exit_time as exit_date, "
    "st.pnl_pct, st.pnl_dollars, st.exit_reason, "
    "st.duration_days, r.priority_score as score, "
    "st.regime_at_entry as regime "
    "FROM shadow_trades st "
    "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
    "WHERE st.status = 'closed' AND st.strategy_type = ? "
    "AND COALESCE(st.quarantined, 0) = 0 "
    "ORDER BY st.actual_exit_time ASC"
)


def _win_rate(wins, total):
    return round(wins / total, 3) if total else 0


def _build_score_bands(trade_list):
    bands = {"0-39": [], "40-59": [], "60-79": [], "80-100": []}
    for t in trade_list:
        s = int(t.get("score") or 0)
        if s >= 80:
            bands["80-100"].append(t)
        elif s >= 60:
            bands["60-79"].append(t)
        elif s >= 40:
            bands["40-59"].append(t)
        else:
            bands["0-39"].append(t)
    out = {}
    for band, tlist in bands.items():
        if not tlist:
            out[band] = {"trades": 0, "wins": 0, "win_rate": 0, "avg_pnl": 0}
            continue
        wins = sum(1 for t in tlist if float(t.get("pnl_dollars") or 0) > 0)
        avg_pnl = sum(float(t.get("pnl_pct") or 0) for t in tlist) / len(tlist)
        out[band] = {
            "trades": len(tlist), "wins": wins,
            "win_rate": _win_rate(wins, len(tlist)),
            "avg_pnl": round(avg_pnl, 2),
        }
    return out


def _build_regime_breakdown(trade_list):
    by_regime: dict = {}
    for t in trade_list:
        by_regime.setdefault(t.get("regime") or "unknown", []).append(t)
    out = {}
    for k, v in by_regime.items():
        wins = sum(1 for t in v if float(t.get("pnl_dollars") or 0) > 0)
        out[k] = {
            "trades": len(v),
            "win_rate": _win_rate(wins, len(v)),
            "avg_pnl": round(
                sum(float(t.get("pnl_pct") or 0) for t in v) / len(v), 2
            ),
        }
    return out


def _build_drawdown_series(trade_list):
    peak = 0.0
    series = []
    for i, t in enumerate(trade_list):
        cum = t["cumulative_pnl"]
        peak = max(peak, cum)
        dd_pct = round((peak - cum) / max(peak, 1) * 100, 1) if peak > 0 else 0
        series.append({"trade_num": i + 1, "cumulative_pnl": cum, "drawdown_pct": dd_pct})
    return series


@router.get("/strategy-detail/{strategy_type}")
def strategy_detail(strategy_type: str):
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(_QUERY, (strategy_type,)).fetchall()

        if not rows:
            return {"trades": [], "by_score_band": {}, "by_regime": {},
                    "hold_distribution": [], "drawdown_series": []}

        trade_list = [dict(r) for r in rows]
        cumulative = 0
        for t in trade_list:
            cumulative += float(t.get("pnl_dollars") or 0)
            t["cumulative_pnl"] = round(cumulative, 2)

        hold_counts: dict[int, int] = {}
        for t in trade_list:
            days = int(t.get("duration_days") or 0)
            hold_counts[days] = hold_counts.get(days, 0) + 1

        return {
            "trades": trade_list,
            "by_score_band": _build_score_bands(trade_list),
            "by_regime": _build_regime_breakdown(trade_list),
            "hold_distribution": [{"days": d, "count": c} for d, c in sorted(hold_counts.items())],
            "drawdown_series": _build_drawdown_series(trade_list),
        }
    except Exception as exc:
        logger.error("[API] strategy_detail failed for %s: %s", strategy_type, exc, exc_info=True)
        return {"trades": [], "by_score_band": {}, "by_regime": {},
                "hold_distribution": [], "drawdown_series": []}
