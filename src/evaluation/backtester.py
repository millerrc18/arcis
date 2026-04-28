"""Walk-forward model backtesting framework.

Called by: cli.commands
Calls: config, data_ingestion.market_data, features.engine, packets.template, ranking.ranker, shadow_trading.executor, training.backfill, universe.pit
Owns tables: none
Config keys: none
Tests: tests/test_backtester.py

Evaluates a trained model on historical data it wasn't trained on.
Different from the backfill which creates training data — this evaluates
a trained model's quality on unseen history.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DB_PATH, load_config

logger = logging.getLogger(__name__)


def backtest_model(model_name: str, months: int = 6,
                   db_path: str = DB_PATH) -> dict:
    """Run a walk-forward backtest of a trained model on historical data.

    Process:
    1. Load historical data
    2. For each trading day: compute features, run ranker, get model output
    3. Parse conviction, track simulated portfolio
    4. Compute portfolio-level metrics
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.training.historical_data import slice_to_date
    from src.training.historical_scanner import compute_outcome

    config = load_config()
    end_date = datetime.now() - timedelta(days=20)
    start_date = end_date - timedelta(days=months * 30)

    from src.universe.pit import get_sp100_at
    universe = get_sp100_at(start_date.date().isoformat())  # T10: as_of source: start_date at line 41

    try:
        ohlcv = fetch_ohlcv(universe, period=f"{months * 30 + 60}d")
        spy = fetch_spy_benchmark(period=f"{months * 30 + 60}d")
    except Exception as e:
        return {"error": f"Data fetch failed: {e}"}

    if spy.empty:
        return {"error": "SPY benchmark empty"}

    # Generate trading days
    import pandas as pd
    trading_days = pd.bdate_range(start_date, end_date)

    trades = []
    equity_curve = [{"date": start_date.strftime("%Y-%m-%d"), "equity": 1000}]
    current_equity = 1000.0
    daily_pnls = []

    for day in trading_days[::5]:  # Sample every 5th day for speed
        date_str = day.strftime("%Y-%m-%d")

        try:
            sliced = slice_to_date(ohlcv, date_str)
            spy_sliced = spy[spy.index <= date_str] if not spy.empty else spy

            if not sliced or spy_sliced.empty:
                continue

            features = compute_all_features(sliced, spy_sliced)
            ranked = rank_universe(features)
            candidates = get_top_candidates(ranked)

            for cand in candidates.get("packet_worthy", [])[:3]:  # Max 3 per day
                ticker = cand["ticker"]
                score = cand["score"]
                feat = cand["features"]

                # Compute outcome
                if ticker in ohlcv:
                    from src.packets.template import build_packet_from_features
                    packet = build_packet_from_features(ticker, feat, config)
                    if packet is None:
                        # #621 — upstream feature pipeline returned price<=0;
                        # builder refused. Skip this candidate.
                        continue

                    from src.shadow_trading.executor import _parse_price
                    entry = _parse_price(packet.entry_zone)
                    stop = _parse_price(packet.stop_invalidation)
                    target_parts = packet.targets.split("/")
                    target_1 = _parse_price(target_parts[0]) if target_parts else 0

                    if entry <= 0:
                        continue

                    outcome = compute_outcome(ohlcv[ticker], date_str, entry, stop, target_1)
                    if outcome is None:
                        continue

                    pnl_pct = outcome.get("pnl_pct", 0)
                    trades.append({
                        "date": date_str,
                        "ticker": ticker,
                        "score": score,
                        "entry": entry,
                        "exit_reason": outcome.get("exit_reason"),
                        "pnl_pct": pnl_pct,
                        "duration": outcome.get("duration_days", 0),
                        "regime": feat.get("regime_label", "unknown"),
                    })

                    # Update equity
                    allocation_pct = 0.05  # 5% per trade
                    equity_change = current_equity * allocation_pct * (pnl_pct / 100)
                    current_equity += equity_change
                    daily_pnls.append(pnl_pct)

        except Exception as e:
            logger.debug("Backtest day %s error: %s", date_str, e)
            continue

        equity_curve.append({"date": date_str, "equity": round(current_equity, 2)})

    if not trades:
        return {"model": model_name, "trades_generated": 0, "error": "No qualifying trades found"}

    # Compute metrics
    winners = [t for t in trades if t["pnl_pct"] > 0]
    losers = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(winners) / len(trades) if trades else 0
    total_pnl_pct = ((current_equity - 1000) / 1000) * 100

    # Sharpe ratio
    # F-2 (Sprint 0/4b WALKFORWARD-CANONICAL): route through
    # src.platform.metrics.compute_sharpe (which delegates to
    # src.analytics.canonical_sharpe.raw_sharpe at periods_per_year=252)
    # so all Sharpe computations flow through one source of truth.
    # Mathematically equivalent to the prior parallel
    # `mean/std(ddof=1) * sqrt(252)` formula; canonical returns None
    # when Sharpe is undefined (single-obs / zero variance) and the
    # backtester contract is 0 — so we map None -> 0.
    from src.platform.metrics import compute_sharpe as _canonical_compute_sharpe
    _sharpe_val = _canonical_compute_sharpe(list(daily_pnls), periods_per_year=252)
    sharpe = _sharpe_val if _sharpe_val is not None else 0

    # Max drawdown
    peak = 1000
    max_dd = 0
    for point in equity_curve:
        eq = point["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # By regime
    by_regime = {}
    for t in trades:
        regime = t.get("regime", "unknown")
        if regime not in by_regime:
            by_regime[regime] = {"trades": 0, "wins": 0, "pnl_sum": 0}
        by_regime[regime]["trades"] += 1
        by_regime[regime]["pnl_sum"] += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            by_regime[regime]["wins"] += 1

    regime_summary = {}
    for regime, data in by_regime.items():
        regime_summary[regime] = {
            "trades": data["trades"],
            "win_rate": round(data["wins"] / data["trades"], 2) if data["trades"] else 0,
            "pnl": round(data["pnl_sum"], 1),
        }

    # Extended metrics (Sprint 7)
    max_dd_pct = round(-max_dd * 100, 1)

    # Max drawdown duration
    max_dd_duration_days = 0
    current_dd_start = 0
    peak_eq = equity_curve[0]["equity"] if equity_curve else 0
    for i, point in enumerate(equity_curve):
        eq = point["equity"]
        if eq >= peak_eq:
            peak_eq = eq
            current_dd_start = i
        else:
            dd_dur = i - current_dd_start
            if dd_dur > max_dd_duration_days:
                max_dd_duration_days = dd_dur

    # Calmar ratio (annualized return / max drawdown)
    test_days = max((end_date - start_date).days, 1)
    ann_return = (total_pnl_pct / 100) * (365 / test_days) * 100
    calmar = round(ann_return / abs(max_dd_pct), 2) if max_dd_pct != 0 else 0

    # Monthly returns
    monthly_returns = {}
    for t in trades:
        month = t.get("date", "")[:7]
        if month:
            monthly_returns[month] = monthly_returns.get(month, 0) + t["pnl_pct"]

    # Trade gap days (average days between trades)
    trade_gaps = []
    sorted_trades = sorted(trades, key=lambda x: x.get("date", ""))
    for i in range(1, len(sorted_trades)):
        try:
            d1 = datetime.strptime(sorted_trades[i - 1]["date"][:10], "%Y-%m-%d")
            d2 = datetime.strptime(sorted_trades[i]["date"][:10], "%Y-%m-%d")
            trade_gaps.append((d2 - d1).days)
        except (ValueError, KeyError):
            pass
    avg_trade_gap = round(sum(trade_gaps) / len(trade_gaps), 1) if trade_gaps else 0

    return {
        "model": model_name,
        "test_period": {"start": start_date.strftime("%Y-%m-%d"), "end": end_date.strftime("%Y-%m-%d")},
        "trades_generated": len(trades),
        "win_rate": round(win_rate, 3),
        "total_pnl_pct": round(total_pnl_pct, 1),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_duration_days": max_dd_duration_days,
        "calmar_ratio": calmar,
        "monthly_returns": monthly_returns,
        "trade_gap_days": avg_trade_gap,
        "by_regime": regime_summary,
        "equity_curve": equity_curve[:50],
    }


def compare_models(model_a: str, model_b: str, months: int = 3) -> dict:
    """Run the same backtest on two models and compare results."""
    result_a = backtest_model(model_a, months=months)
    result_b = backtest_model(model_b, months=months)

    winner = "tie"
    wr_a = result_a.get("win_rate", 0)
    wr_b = result_b.get("win_rate", 0)
    sharpe_a = result_a.get("sharpe_ratio", 0)
    sharpe_b = result_b.get("sharpe_ratio", 0)

    if sharpe_b > sharpe_a + 0.1:
        winner = model_b
    elif sharpe_a > sharpe_b + 0.1:
        winner = model_a

    return {
        "model_a": result_a,
        "model_b": result_b,
        "winner": winner,
        "win_rate_delta": round(wr_b - wr_a, 3),
        "sharpe_delta": round(sharpe_b - sharpe_a, 2),
    }
