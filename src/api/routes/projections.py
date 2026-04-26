"""Local API routes for revenue projection analytics.

Called by: api.app
Calls: src.utils.db.connect_db, src.analytics.canonical_sharpe.raw_sharpe,
  src.shadow_trading.alpaca_adapter.get_account_info
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/api/test_route_parity.py, tests/api/test_projections.py

Endpoints:
    GET /projections/live  - Live projection metrics (Sharpe, win rate, drawdown)
"""

import logging
import sqlite3
import statistics
from contextlib import closing

from fastapi import APIRouter

from src.analytics.canonical_sharpe import raw_sharpe
from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["projections"])
logger = logging.getLogger(__name__)

# PR #690 I6: fallback equity baseline used by the drawdown computation when
# the live Alpaca account is unreachable (test environments, missing creds,
# broker outage). Naming this constant — instead of inlining `100000` — makes
# the fallback path auditable and lets the response surface a `equitySource`
# field so the dashboard can distinguish live equity from the normalized
# baseline. Cluster-07 sprint 0 also flagged the same hardcoded magic number
# diverging across surfaces (cloud_routes/trades.py:429 uses 100,
# routes/live.py:110-111 uses 100_000); this module pins the source of truth
# for projections to Alpaca's live equity, with the named constant as the
# only fallback.
_NORMALIZED_BASELINE_EQUITY = 100_000.0


def _resolve_equity_baseline() -> tuple[float, str]:
    """Return (equity, source) used as the drawdown starting baseline.

    Source is one of:
      - 'alpaca_account': live equity from `get_account_info()` (preferred)
      - 'normalized_baseline': fallback constant when Alpaca is unreachable

    Mirrors the Alpaca-equity surface used by `src/api/routes/live.py:110-111`
    and `src/api/cloud_routes/trades.py:429-432`. Per PR #690 I6, the previous
    code hardcoded $100K with no relationship to real account state — quoting
    operator: "the actual paper account equity comes from Alpaca elsewhere;
    this constant has no relationship to real account state."
    """
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        equity = acct.get("equity")
        if equity is not None:
            return float(equity), "alpaca_account"
    except Exception as exc:  # noqa: BLE001 — broker outage / creds / network
        logger.warning(
            "[PROJECTIONS_EQUITY_FALLBACK] Alpaca get_account_info failed — "
            "using normalized $%s baseline for drawdown: %s",
            _NORMALIZED_BASELINE_EQUITY, exc,
        )
    return _NORMALIZED_BASELINE_EQUITY, "normalized_baseline"


@router.get("/projections/live")
def projections_live():
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                "AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY actual_exit_time ASC"
            ).fetchall()

        if not rows:
            return {"trades": 0}

        pnl_pcts = [float(r["pnl_pct"] or 0) for r in rows]
        pnl_dollars = [float(r["pnl_dollars"] or 0) for r in rows]
        wins = [pnl for pnl in pnl_dollars if pnl > 0]
        losses = [pnl for pnl in pnl_dollars if pnl <= 0]
        avg_return = statistics.mean(pnl_pcts) if pnl_pcts else 0
        # PR #690 B5: replace non-canonical (mean/std with no annualization) with
        # canonical_sharpe.raw_sharpe — single source of truth per F-2/Track-1.5.
        # raw_sharpe returns None when undefined (n<2 or zero variance); we coerce
        # to 0.0 to preserve the response contract (numeric `sharpe` field).
        # TODO(#690): when src.data_ingestion.risk_free_rate is wired across all 6
        # rf-deferred sites (kpis.py, stage1_baseline_recompute.py, cpcv.py,
        # promotion_gate.py, mc_permutation.py, block_bootstrap.py) swap to
        # rf_adjusted_excess_sharpe with a per-trade rf vector. Tracked as
        # PR-690 review I1 follow-up.
        sharpe = raw_sharpe(pnl_pcts) or 0.0

        # PR #690 I6: pull live equity from Alpaca rather than hardcoded $100K.
        # `equitySource` is surfaced in the response so the dashboard / operator
        # can tell whether the drawdown is computed against live equity or the
        # normalized fallback constant.
        starting_equity, equity_source = _resolve_equity_baseline()
        cumulative = starting_equity
        peak = cumulative
        max_dd = 0
        for pnl in pnl_dollars:
            cumulative += pnl
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0
        return {
            "trades": len(rows),
            "winRate": round(len(wins) / len(rows), 3),
            "sharpe": round(sharpe, 3),
            "profitFactor": round(pf, 2),
            "maxDD": round(max_dd, 1),
            "netPnl": round(sum(pnl_dollars), 2),
            "avgReturn": round(avg_return, 3),
            "equitySource": equity_source,
            "startingEquity": round(starting_equity, 2),
        }
    except Exception as exc:
        logger.error("[API] projections/live failed: %s", exc)
        return {"trades": 0, "error": str(exc)}
