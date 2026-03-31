"""Shadow ledger performance metrics.

Called by: evaluation.scorecard, services.shadow_service
Calls: evaluation.metrics
Owns tables: none
Config keys: none
Tests: tests/test_shadow_metrics.py
"""


def compute_shadow_metrics(trades: list[dict]) -> dict:
    """Compute performance metrics from a list of closed shadow trades.

    Args:
        trades: List of closed shadow trade dicts.

    Returns:
        Dict with performance metrics.
    """
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_gain": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "avg_duration_days": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "earnings_adjacent_trades": 0,
            "earnings_adjacent_pnl": 0.0,
            "normal_trades_pnl": 0.0,
        }

    total = len(trades)
    pnls = [t.get("pnl_dollars", 0) or 0 for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total * 100) if total > 0 else 0

    avg_gain = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    total_pnl = sum(pnls)
    try:
        from src.evaluation.metrics import expectancy as calc_expectancy
        expectancy = calc_expectancy(pnls)
    except Exception:
        expectancy = total_pnl / total if total > 0 else 0.0

    # Max drawdown (cumulative)
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Duration
    durations = [t.get("duration_days", 0) or 0 for t in trades]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # MFE/MAE
    mfes = [t.get("max_favorable_excursion", 0) or 0 for t in trades]
    maes = [t.get("max_adverse_excursion", 0) or 0 for t in trades]
    avg_mfe = sum(mfes) / len(mfes) if mfes else 0.0
    avg_mae = sum(maes) / len(maes) if maes else 0.0

    # Earnings-adjacent breakdown
    earnings_trades = [t for t in trades if t.get("earnings_adjacent")]
    normal_trades = [t for t in trades if not t.get("earnings_adjacent")]
    earnings_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in earnings_trades)
    normal_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in normal_trades)

    return {
        "total_trades": total,
        "wins": win_count,
        "losses": loss_count,
        "win_rate": round(win_rate, 1),
        "avg_gain": round(avg_gain, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "avg_duration_days": round(avg_duration, 1),
        "avg_mfe": round(avg_mfe, 2),
        "avg_mae": round(avg_mae, 2),
        "earnings_adjacent_trades": len(earnings_trades),
        "earnings_adjacent_pnl": round(earnings_pnl, 2),
        "normal_trades_pnl": round(normal_pnl, 2),
    }
