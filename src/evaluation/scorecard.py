"""Weekly and bootcamp scorecard generation.

Called by: services.review_service
Calls: journal.store, shadow_trading.metrics
Owns tables: none
Config keys: none
Tests: tests/test_scorecard.py
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.journal.store import (
    get_closed_shadow_trades,
    get_open_shadow_trades,
    get_all_shadow_trades,
    get_recommendations_in_period,
)
from src.config import DB_PATH
from src.shadow_trading.metrics import compute_shadow_metrics


def generate_weekly_scorecard(
    weeks_back: int = 1, db_path: str = DB_PATH
) -> str:
    """Generate a weekly scorecard covering the last N weeks."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    days = weeks_back * 7

    end_date = now
    start_date = now - timedelta(days=days)
    date_range = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"

    # Gather data
    closed = get_closed_shadow_trades(days=days, db_path=db_path)
    open_trades = get_open_shadow_trades(db_path=db_path)
    all_trades = get_all_shadow_trades(days=days, db_path=db_path)
    recommendations = get_recommendations_in_period(days=days, db_path=db_path)

    # Compute metrics
    metrics = compute_shadow_metrics(closed)

    # Count trades opened in period
    opened_in_period = [t for t in all_trades if t.get("status") in ("open", "closed")]

    # By exit reason
    by_reason = {}
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        if reason not in by_reason:
            by_reason[reason] = {"count": 0, "pnls": []}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnls"].append(t.get("pnl_dollars", 0) or 0)

    # Confidence and priority scores
    conf_scores = [r.get("confidence_score", 0) for r in recommendations if r.get("confidence_score")]
    pri_scores = [r.get("priority_score", 0) for r in recommendations if r.get("priority_score")]
    avg_conf = sum(conf_scores) / len(conf_scores) if conf_scores else 0
    avg_pri = sum(pri_scores) / len(pri_scores) if pri_scores else 0

    # Ryan-executed and graded trades
    executed = [r for r in recommendations if r.get("ryan_executed")]
    graded = [r for r in recommendations if r.get("user_grade")]
    grade_map = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    avg_grade_num = (
        sum(grade_map.get(r["user_grade"], 0) for r in graded) / len(graded)
        if graded else 0
    )
    grade_letters = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
    avg_grade = grade_letters.get(round(avg_grade_num), "n/a") if graded else "n/a"

    # Lesson tags
    lesson_tags = {}
    for r in recommendations:
        tag = r.get("lesson_tag")
        if tag:
            lesson_tags[tag] = lesson_tags.get(tag, 0) + 1

    # Watchlist count (distinct tickers with packet_type recommendations)
    watchlist_tickers = set(r.get("ticker") for r in recommendations)

    # MFE/MAE as percentages
    mfe_pcts = []
    mae_pcts = []
    for t in closed:
        entry = t.get("actual_entry_price") or t.get("entry_price", 0)
        mfe = t.get("max_favorable_excursion", 0) or 0
        mae = t.get("max_adverse_excursion", 0) or 0
        if entry > 0:
            mfe_pcts.append(mfe / entry * 100)
            mae_pcts.append(mae / entry * 100)

    avg_mfe_pct = sum(mfe_pcts) / len(mfe_pcts) if mfe_pcts else 0
    avg_mae_pct = sum(mae_pcts) / len(mae_pcts) if mae_pcts else 0
    mfe_mae_ratio = abs(metrics["avg_mfe"] / metrics["avg_mae"]) if metrics["avg_mae"] != 0 else 0

    # Hold period stats — v0.36.13 sibling-search sweep (operator memory
    # feedback_review_sibling_search 2026-04-26). Excludes sentinel
    # duration_days=999 (from the legacy 'unknown' backfill) and unmeasurable
    # exit reasons (reconciled_stale/unknown/manual/qty_mismatch_partial_fill)
    # using the cto_report helper. Pre-fix this list included 11 sentinel-999
    # trades that pushed the 'longest' value to 999 days on the weekly
    # scorecard, masking the real 1-7 day pullback distribution.
    from src.evaluation.cto_report import _measurable_hold_durations
    durations = _measurable_hold_durations(closed)
    shortest = min(durations) if durations else 0
    longest = max(durations) if durations else 0

    # Build output
    lines = []
    lines.append("=" * 55)
    lines.append(f" WEEKLY SCORECARD — {date_range}")
    lines.append("=" * 55)
    lines.append("")

    lines.append("ACTIVITY:")
    lines.append(f"  Scans run:              ~{len(recommendations)} (estimated from journal entries)")
    lines.append(f"  Packets generated:      {len(recommendations)}")
    lines.append(f"  Watchlist names:        {len(watchlist_tickers)}")
    lines.append(f"  Trades opened:          {len(opened_in_period)}")
    lines.append(f"  Trades closed:          {len(closed)}")
    lines.append(f"  Trades still open:      {len(open_trades)}")
    lines.append("")

    lines.append("SHADOW PERFORMANCE:")
    lines.append(f"  Win rate:               {metrics['win_rate']:.0f}%")
    lines.append(f"  Avg gain:               ${metrics['avg_gain']:.2f}")
    lines.append(f"  Avg loss:               ${metrics['avg_loss']:.2f}")
    lines.append(f"  Expectancy:             ${metrics['expectancy']:+.2f} per trade")
    lines.append(f"  Total P&L:              ${metrics['total_pnl']:+.2f}")
    lines.append(f"  Max drawdown:           ${metrics['max_drawdown']:.2f}")
    lines.append("")

    lines.append("BY EXIT REASON:")
    for reason in ["target_1_hit", "target_2_hit", "stop_hit", "timeout", "manual"]:
        data = by_reason.get(reason, {"count": 0, "pnls": []})
        avg_pnl = sum(data["pnls"]) / len(data["pnls"]) if data["pnls"] else 0
        lines.append(f"  {reason + ':':20s} {data['count']} trades, avg P&L ${avg_pnl:+.2f}")
    lines.append("")

    lines.append("EARNINGS-ADJACENT:")
    lines.append(f"  Total:                  {metrics['earnings_adjacent_trades']} trades")
    lines.append(f"  P&L:                    ${metrics['earnings_adjacent_pnl']:+.2f}")
    lines.append(f"  vs Normal trades P&L:   ${metrics['normal_trades_pnl']:+.2f}")
    lines.append("")

    lines.append("HOLD PERIOD:")
    lines.append(f"  Avg duration:           {metrics['avg_duration_days']:.1f} days")
    lines.append(f"  Shortest:               {shortest} days")
    lines.append(f"  Longest:                {longest} days")
    lines.append("")

    lines.append("EXCURSION ANALYSIS:")
    lines.append(f"  Avg MFE:                ${metrics['avg_mfe']:+.2f} ({avg_mfe_pct:+.1f}%)")
    lines.append(f"  Avg MAE:                ${metrics['avg_mae']:+.2f} ({avg_mae_pct:+.1f}%)")
    lines.append(f"  MFE/MAE ratio:          {mfe_mae_ratio:.1f}x")
    lines.append("")

    lines.append("QUALITY:")
    lines.append(f"  Avg confidence score:   {avg_conf:.1f}/10")
    lines.append(f"  Avg priority score:     {avg_pri:.1f}")
    lines.append(f"  Ryan-executed trades:   {len(executed)}")
    lines.append(f"  Avg user grade:         {avg_grade} (of {len(graded)} graded trades)")
    lines.append("")

    if lesson_tags:
        lines.append("TOP LESSONS THIS WEEK:")
        for tag, count in sorted(lesson_tags.items(), key=lambda x: -x[1]):
            lines.append(f"  {tag}: {count}")
    else:
        lines.append("TOP LESSONS THIS WEEK:")
        lines.append("  No lesson tags recorded yet.")
    lines.append("")

    lines.append("=" * 55)

    return "\n".join(lines)


def generate_bootcamp_scorecard(
    days: int = 30, db_path: str = DB_PATH
) -> str:
    """Generate a full bootcamp scorecard covering N days."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    start_date = now - timedelta(days=days)
    date_range = f"{start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"

    closed = get_closed_shadow_trades(days=days, db_path=db_path)
    open_trades = get_open_shadow_trades(db_path=db_path)
    recommendations = get_recommendations_in_period(days=days, db_path=db_path)

    metrics = compute_shadow_metrics(closed)

    lines = []
    lines.append("=" * 55)
    lines.append(f" BOOTCAMP SCORECARD — {date_range}")
    lines.append("=" * 55)
    lines.append("")

    lines.append("OVERALL PERFORMANCE:")
    lines.append(f"  Total trades closed:    {metrics['total_trades']}")
    lines.append(f"  Still open:             {len(open_trades)}")
    lines.append(f"  Win rate:               {metrics['win_rate']:.0f}%")
    lines.append(f"  Avg gain:               ${metrics['avg_gain']:.2f}")
    lines.append(f"  Avg loss:               ${metrics['avg_loss']:.2f}")
    lines.append(f"  Expectancy:             ${metrics['expectancy']:+.2f} per trade")
    lines.append(f"  Total P&L:              ${metrics['total_pnl']:+.2f}")
    lines.append(f"  Max drawdown:           ${metrics['max_drawdown']:.2f}")
    lines.append(f"  Avg hold:               {metrics['avg_duration_days']:.1f} days")
    lines.append(f"  Avg MFE:                ${metrics['avg_mfe']:+.2f}")
    lines.append(f"  Avg MAE:                ${metrics['avg_mae']:+.2f}")
    lines.append("")

    lines.append("RECOMMENDATIONS:")
    lines.append(f"  Total generated:        {len(recommendations)}")
    lines.append(f"  Distinct tickers:       {len(set(r.get('ticker') for r in recommendations))}")
    lines.append("")

    # Phase breakdown if enough data
    if days >= 20:
        lines.append("PHASE BREAKDOWN:")
        for phase_num, phase_label, start_offset, end_offset in [
            (1, "Days 1-10", days, max(days - 10, 0)),
            (2, "Days 11-20", max(days - 10, 0), max(days - 20, 0)),
            (3, "Days 21-30", max(days - 20, 0), 0),
        ]:
            phase_trades = [
                t for t in closed
                if _trade_in_day_range(t, now, start_offset, end_offset)
            ]
            phase_metrics = compute_shadow_metrics(phase_trades)
            lines.append(f"  Phase {phase_num} ({phase_label}):")
            lines.append(f"    Trades: {phase_metrics['total_trades']} | Win rate: {phase_metrics['win_rate']:.0f}% | Expectancy: ${phase_metrics['expectancy']:+.2f}")
        lines.append("")

    # Trend analysis
    if len(closed) >= 4:
        half = len(closed) // 2
        first_half = compute_shadow_metrics(closed[half:])
        second_half = compute_shadow_metrics(closed[:half])
        if first_half["expectancy"] != 0:
            improvement = second_half["expectancy"] - first_half["expectancy"]
            trend = "improving" if improvement > 0 else "declining" if improvement < 0 else "flat"
            lines.append(f"TREND: Performance is {trend} (expectancy change: ${improvement:+.2f})")
        else:
            lines.append("TREND: Insufficient data for trend analysis")
    else:
        lines.append("TREND: Insufficient data for trend analysis")

    lines.append("")
    lines.append("=" * 55)

    return "\n".join(lines)


def _trade_in_day_range(trade: dict, now: datetime, start_days_ago: int, end_days_ago: int) -> bool:
    """Check if a trade's exit time falls within a day range."""
    exit_time_str = trade.get("actual_exit_time") or trade.get("created_at", "")
    try:
        exit_time = datetime.fromisoformat(exit_time_str)
        start = now - timedelta(days=start_days_ago)
        end = now - timedelta(days=end_days_ago)
        return start <= exit_time <= end
    except (ValueError, TypeError):
        return False
