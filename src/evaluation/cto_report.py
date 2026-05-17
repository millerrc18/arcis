"""CTO performance report generator.

Called by: api.routes.actions, api.routes.system, cli.commands, evaluation.auditor, scheduler.watch
Calls: config, evaluation.feature_importance, evaluation.hshs_live, evaluation.metrics, journal.store, training.leakage_detector, training.validation, training.versioning, universe.sectors
Owns tables: none
Config keys: bootcamp, enabled, phase, risk
Tests: tests/test_confidence.py, tests/test_cto_report.py

Produces a comprehensive structured report for CTO analysis,
designed to be consumed by Claude for strategic recommendations.

Report structure
~~~~~~~~~~~~~~~~
The CTO report is the system's primary self-assessment artifact.  It
consolidates trade statistics, model performance, and training pipeline
health into a single JSON payload that the council and Telegram
notifications consume.

Key sections:
  - headline_kpis:           5 numbers that matter most (Sharpe, WR, DD,
                             confidence calibration, rubric score)
  - trade_summary:           aggregate P&L, win rate, expectancy, profit
                             factor, max consecutive losses (#254)
  - by_exit_reason:          which exits (stop, target, timeout) produce
                             the best/worst outcomes
  - by_score_band:           do high-priority-score picks actually win more?
  - by_sector / by_regime:   performance segmented by market context
  - execution_analysis:      MFE/MAE, hold period, target hit rate
  - confidence_calibration:  are high-conviction LLM picks actually better?
  - fund_metrics:            Sortino, Calmar, VaR, return skewness

The report uses defensive `or 0` patterns throughout because trade data
can have NULL P&L values (e.g. open trades, reconciled entries), and
None + float raises TypeError.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db
from src.utils.type_safety import safe_numeric

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# v0.36.13 audit filter — exit reasons that represent synthetic or
# operator-action closures rather than model-attributable outcomes.
# These rows are excluded from stat aggregations (avg hold, confidence
# calibration) so that sentinel values don't pollute real metrics.
#
# INTENTIONALLY NOT shared with src/training/data_collector.py's
# _UNMEASURED_EXIT_REASONS (Task 1 ownership). That set governs corpus
# exclusion; this set governs stat exclusion. The two may diverge in
# the future as the training pipeline and the audit pipeline evolve
# independently.
_UNMEASURABLE_EXIT_REASONS = frozenset({
    "unknown",
    "reconciled_stale",
    "manual",
    "qty_mismatch_partial_fill",
})


def _measurable_hold_durations(trades: list[dict]) -> list[float]:
    """v0.36.13 audit filter — exclude sentinel-999 + unmeasurable exits.

    Returns durations only from trades whose duration_days is real and whose
    exit_reason is a model-attributable outcome. The 11 unknown+999 +
    3 manual+999 sentinel rows in PG were polluting the avg from ~1.5d to
    137.7d (model_monitor) and triggering the 'avg hold 336 days' alert.
    """
    return [
        _num(t.get("duration_days"))
        for t in trades
        if t.get("duration_days") is not None
           and _num(t.get("duration_days")) != 999
           and (t.get("exit_reason") or "").lower() not in _UNMEASURABLE_EXIT_REASONS
    ]


def _num(val, default=0):
    """Coerce a value to float. Guards against SQLite returning strings for numeric columns."""
    return safe_numeric(val, default)


def _compute_hshs() -> dict:
    """Compute HSHS score for inclusion in CTO report."""
    try:
        from src.evaluation.hshs_live import compute_hshs
        return compute_hshs()
    except Exception as e:
        logger.warning("[CTO] HSHS computation failed: %s", e)
        return {"hshs": 0, "error": str(e)}


def generate_cto_report(days: int = 7, db_path: str = DB_PATH) -> dict:
    """Generate a comprehensive structured performance report for CTO analysis.

    Returns a dict (JSON-serializable) with all performance data.

    The report is intentionally wide rather than deep — it surfaces many
    dimensions of performance so that Claude (or a human) can spot which
    area needs attention.  Individual metrics are kept simple (win rate,
    not Bayesian posterior) because the audience is strategic, not quant.
    """
    now = datetime.now(ET)
    start_date = now - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")

    from src.journal.store import (
        get_closed_shadow_trades,
        get_open_shadow_trades,
        get_all_shadow_trades,
        get_recommendations_in_period,
    )
    from src.training.versioning import get_active_model_name, get_training_example_counts

    closed = get_closed_shadow_trades(days=days, db_path=db_path)
    open_trades = get_open_shadow_trades(db_path=db_path)
    all_trades = get_all_shadow_trades(days=days, db_path=db_path)
    recommendations = get_recommendations_in_period(days=days, db_path=db_path)

    # Count trading days (weekdays in period)
    trading_days = sum(
        1 for d in range(days)
        if (start_date + timedelta(days=d)).weekday() < 5
    )

    # System status
    model_name = get_active_model_name()
    try:
        t_counts = get_training_example_counts()
        dataset_size = t_counts.get("total", 0)
    except Exception:
        dataset_size = 0

    from src.config import load_config
    config = load_config()
    bootcamp_cfg = config.get("bootcamp", {})

    # Trade summary
    trade_summary = _compute_trade_summary(closed, open_trades, all_trades)

    # By exit reason
    by_exit_reason = _compute_by_exit_reason(closed)

    # By score band
    by_score_band = _compute_by_score_band(closed, recommendations)

    # By sector
    by_sector = _compute_by_sector(closed, recommendations)

    # By regime
    by_regime = _compute_by_regime(closed, recommendations)

    # By model version
    by_model = _compute_by_model_version(closed, recommendations)

    # Execution analysis
    execution = _compute_execution_analysis(closed)

    # Signal quality
    signal_quality = _compute_signal_quality(closed, recommendations)

    # Feature correlations
    feature_correlations = _compute_feature_correlations(closed, recommendations)

    # Training status
    training_status = _compute_training_status(days, db_path)

    # Confidence calibration
    confidence_calibration = _compute_confidence_calibration(closed, recommendations)

    # Fund-level metrics
    fund_metrics = _compute_fund_metrics(closed, trade_summary)

    # Build headline KPIs — the 5 numbers that matter most.
    # These are the metrics surfaced at the top of every Telegram digest
    # and the dashboard summary card.  Chosen because they each capture
    # a distinct axis: risk-adjusted return (Sharpe), raw accuracy (WR),
    # tail risk (DD), model judgment (calibration), and data quality (rubric).
    headline_kpis = {
        "sharpe_ratio": trade_summary.get("sharpe_ratio", 0),
        "win_rate": trade_summary.get("win_rate", 0),
        "max_drawdown_pct": trade_summary.get("max_drawdown_pct", 0),
        "confidence_calibration": confidence_calibration.get("correlation_with_outcomes", 0),
        "avg_rubric_score": training_status.get("training_data_quality", {}).get("average_process_score"),
    }

    # Save a metric snapshot for historical trending.
    # This persists headline KPIs to model_versions so we can plot
    # performance evolution across model releases.  Best-effort —
    # snapshot failure must never block the report from returning.
    try:
        from src.training.versioning import save_metric_snapshot
        snapshot = {
            **headline_kpis,
            "trades_closed": trade_summary.get("trades_closed", 0),
            "total_pnl": trade_summary.get("total_pnl", 0),
            "expectancy_dollars": trade_summary.get("expectancy_dollars", 0),
            "profit_factor": trade_summary.get("profit_factor", 0),
            "sortino_ratio": fund_metrics.get("sortino_ratio", 0),
            "calmar_ratio": fund_metrics.get("calmar_ratio", 0),
            "monthly_batting_avg": fund_metrics.get("monthly_batting_avg", 0),
            "var_95_pct": fund_metrics.get("var_95", 0),
            "total_return_pct": fund_metrics.get("total_return_pct", 0),
            "dataset_size": dataset_size,
        }
        save_metric_snapshot(snapshot, db_path)
    except Exception:
        pass  # Don't let snapshot failure block the report

    return {
        "report_period": {
            "start": start_str,
            "end": end_str,
            "trading_days": trading_days,
        },
        "headline_kpis": headline_kpis,
        "system_status": {
            "model_version": model_name,
            "dataset_size": dataset_size,
            "bootcamp_phase": bootcamp_cfg.get("phase", 0) if bootcamp_cfg.get("enabled") else None,
            "bootcamp_day": None,
        },
        "trade_summary": trade_summary,
        "by_exit_reason": by_exit_reason,
        "by_score_band": by_score_band,
        "by_sector": by_sector,
        "by_regime": by_regime,
        "by_model_version": by_model,
        "execution_analysis": execution,
        "signal_quality": signal_quality,
        "feature_correlations": feature_correlations,
        "training_status": training_status,
        "confidence_calibration": confidence_calibration,
        "fund_metrics": fund_metrics,
        "hshs": _compute_hshs(),
    }


def _compute_trade_summary(closed: list, open_trades: list, all_trades: list) -> dict:
    """Compute overall trade performance summary.

    Core metrics: win rate, Sharpe ratio (annualized from per-trade
    returns assuming ~150 trades/year), profit factor, expectancy,
    max drawdown (cumulative P&L peak-to-trough), and max consecutive
    losses (#254).

    The `or 0` guards on every pnl_dollars / pnl_pct access are
    defensive against NULL values from open or reconciled trades.
    """
    winners = [t for t in closed if _num(t.get("pnl_dollars")) > 0]
    losers = [t for t in closed if _num(t.get("pnl_dollars")) <= 0]

    win_rate = len(winners) / len(closed) if closed else 0
    avg_winner = sum(_num(t.get("pnl_pct")) for t in winners) / len(winners) if winners else 0
    avg_loser = sum(_num(t.get("pnl_pct")) for t in losers) / len(losers) if losers else 0

    total_pnl = sum(_num(t.get("pnl_dollars")) for t in closed)
    try:
        from src.evaluation.metrics import expectancy as calc_expectancy
        expectancy = calc_expectancy(_num(t.get("pnl_dollars")) for t in closed)
    except Exception:
        expectancy = total_pnl / len(closed) if closed else 0

    max_win = max(closed, key=lambda t: _num(t.get("pnl_pct"))) if closed else None
    max_loss = min(closed, key=lambda t: _num(t.get("pnl_pct"))) if closed else None

    # Sharpe ratio (annualized from per-trade returns)
    # F-2 / Sprint-0 wave-4a: route through canonical_sharpe.compute_sharpe.
    # periods_per_year=150 preserves the legacy "150 trades/year" trade-
    # frequency convention (~3 trades/week). Coerce None → 0 because
    # downstream JSON consumers and `round(sharpe, 2)` expect numeric.
    from src.analytics.canonical_sharpe import compute_sharpe
    pnl_pcts = [_num(t.get("pnl_pct")) for t in closed]
    sharpe = compute_sharpe(pnl_pcts, periods_per_year=150)
    if sharpe is None:
        sharpe = 0

    # Max drawdown (cumulative P&L peak-to-trough)
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in closed:
        # float() cast: pnl_dollars can be TEXT from SQLite (#195 pattern)
        cumulative += _num(t.get("pnl_dollars"))
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0

    # Profit factor (gross wins / gross losses)
    # float() casts prevent abs(str) TypeError when pnl_dollars is TEXT
    gross_wins = sum(_num(t.get("pnl_dollars")) for t in winners)
    gross_losses = abs(sum(_num(t.get("pnl_dollars")) for t in losers))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (float('inf') if gross_wins > 0 else 0)

    # Max consecutive losses (#254) — a key behavioral risk metric.
    # A long losing streak can trigger emotional overrides even in an
    # automated system (e.g. the operator manually halting or tweaking
    # parameters).  Tracking this helps calibrate expectations.
    max_consec_losses = 0
    current_streak = 0
    for t in closed:
        if _num(t.get("pnl_dollars")) <= 0:
            current_streak += 1
            max_consec_losses = max(max_consec_losses, current_streak)
        else:
            current_streak = 0

    return {
        "trades_opened": len(all_trades),
        "trades_closed": len(closed),
        "trades_open": len(open_trades),
        "win_rate": round(win_rate, 3),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_dollars": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "inf",
        "max_consecutive_losses": max_consec_losses,
        "avg_winner_pct": round(avg_winner, 1),
        "avg_loser_pct": round(avg_loser, 1),
        "expectancy_dollars": round(expectancy, 2),
        "total_pnl": round(total_pnl, 2),
        "max_single_win": {
            "ticker": max_win.get("ticker", ""),
            "pnl_pct": round(_num(max_win.get("pnl_pct")), 1),
            "duration": _num(max_win.get("duration_days")),
        } if max_win else None,
        "max_single_loss": {
            "ticker": max_loss.get("ticker", ""),
            "pnl_pct": round(_num(max_loss.get("pnl_pct")), 1),
            "duration": _num(max_loss.get("duration_days")),
        } if max_loss else None,
    }


def _compute_by_exit_reason(closed: list) -> dict:
    by_reason = defaultdict(lambda: {"count": 0, "pnls": []})
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnls"].append(_num(t.get("pnl_pct")))

    result = {}
    for reason, data in by_reason.items():
        avg = sum(data["pnls"]) / len(data["pnls"]) if data["pnls"] else 0
        result[reason] = {"count": data["count"], "avg_pnl": round(avg, 1)}
    return result


def _compute_by_score_band(closed: list, recommendations: list) -> dict:
    # Segment trades by priority score band to answer the question:
    # "Do higher-scored trades actually perform better?"  If not, the
    # scoring model needs recalibration.  Bands: 90-100, 80-89, 70-79, <70.
    # Map recommendation_id -> priority_score
    score_map = {r.get("recommendation_id"): _num(r.get("priority_score")) for r in recommendations}

    bands = {"90-100": [], "80-89": [], "70-79": [], "below_70": []}
    for t in closed:
        rec_id = t.get("recommendation_id")
        score = score_map.get(rec_id, 0)
        pnl = _num(t.get("pnl_pct"))
        won = 1 if _num(t.get("pnl_dollars")) > 0 else 0

        if score >= 90:
            bands["90-100"].append((pnl, won))
        elif score >= 80:
            bands["80-89"].append((pnl, won))
        elif score >= 70:
            bands["70-79"].append((pnl, won))
        else:
            bands["below_70"].append((pnl, won))

    result = {}
    for band, data in bands.items():
        if data:
            wr = sum(w for _, w in data) / len(data)
            avg = sum(p for p, _ in data) / len(data)
            result[band] = {"trades": len(data), "win_rate": round(wr, 2), "avg_pnl": round(avg, 1)}
        else:
            result[band] = {"trades": 0, "win_rate": 0, "avg_pnl": 0}
    return result


def _compute_by_sector(closed: list, recommendations: list) -> dict:
    from src.universe.sectors import SECTOR_MAP

    by_sector = defaultdict(lambda: {"trades": 0, "wins": 0})
    for t in closed:
        ticker = t.get("ticker", "")
        sector = SECTOR_MAP.get(ticker, "Unknown")
        by_sector[sector]["trades"] += 1
        if _num(t.get("pnl_dollars")) > 0:
            by_sector[sector]["wins"] += 1

    result = {}
    for sector, data in by_sector.items():
        wr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
        result[sector] = {"trades": data["trades"], "win_rate": round(wr, 2)}
    return result


def _compute_by_regime(closed: list, recommendations: list) -> dict:
    # Try to get regime from recommendation's market_regime column
    regime_map = {r.get("recommendation_id"): r.get("market_regime", "unknown") for r in recommendations}

    by_regime = defaultdict(lambda: {"trades": 0, "wins": 0})
    for t in closed:
        rec_id = t.get("recommendation_id")
        regime = regime_map.get(rec_id, "unknown") or "unknown"
        by_regime[regime]["trades"] += 1
        if _num(t.get("pnl_dollars")) > 0:
            by_regime[regime]["wins"] += 1

    result = {}
    for regime, data in by_regime.items():
        wr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
        result[regime] = {"trades": data["trades"], "win_rate": round(wr, 2)}
    return result


def _compute_by_model_version(closed: list, recommendations: list) -> dict:
    version_map = {r.get("recommendation_id"): r.get("model_version", "base") for r in recommendations}

    by_model = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": []})
    for t in closed:
        rec_id = t.get("recommendation_id")
        version = version_map.get(rec_id, "base") or "base"
        by_model[version]["trades"] += 1
        pnl = _num(t.get("pnl_dollars"))
        by_model[version]["pnls"].append(pnl)
        if pnl > 0:
            by_model[version]["wins"] += 1

    result = {}
    for ver, data in by_model.items():
        wr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
        exp = sum(data["pnls"]) / len(data["pnls"]) if data["pnls"] else 0
        result[ver] = {
            "trades": data["trades"],
            "win_rate": round(wr, 2),
            "expectancy": round(exp, 2),
        }
    return result


def _compute_execution_analysis(closed: list) -> dict:
    if not closed:
        return {
            "avg_stop_distance_atr": 0,
            "stops_that_then_reversed": 0,
            "targets_hit_pct": 0,
            "timeout_pct": 0,
            "avg_mfe_winners": 0,
            "avg_mae_losers": 0,
            "avg_hold_period_days": 0,
        }

    winners = [t for t in closed if _num(t.get("pnl_dollars")) > 0]
    losers = [t for t in closed if _num(t.get("pnl_dollars")) <= 0]
    targets = [t for t in closed if t.get("exit_reason", "").startswith("target")]
    timeouts = [t for t in closed if t.get("exit_reason") == "timeout"]

    avg_mfe_w = sum(_num(t.get("max_favorable_excursion")) for t in winners) / len(winners) if winners else 0
    avg_mae_l = sum(_num(t.get("max_adverse_excursion")) for t in losers) / len(losers) if losers else 0
    hold_durations = _measurable_hold_durations(closed)
    avg_hold = sum(hold_durations) / len(hold_durations) if hold_durations else 0

    return {
        "avg_stop_distance_atr": 2.0,  # Default per our setup
        "stops_that_then_reversed": 0,  # Would need post-exit data
        "targets_hit_pct": round(len(targets) / len(closed), 3) if closed else 0,
        "timeout_pct": round(len(timeouts) / len(closed), 3) if closed else 0,
        "avg_mfe_winners": round(avg_mfe_w, 2),
        "avg_mae_losers": round(avg_mae_l, 2),
        "avg_hold_period_days": round(avg_hold, 1),
    }


def _compute_signal_quality(closed: list, recommendations: list) -> dict:
    # Surfaces "high score losers" — trades where the model was confident
    # (score >= 80) but the trade lost money.  These are the most
    # informative training signals: the model's blind spots.
    score_map = {r.get("recommendation_id"): _num(r.get("priority_score")) for r in recommendations}

    high_score_losers = []
    for t in closed:
        rec_id = t.get("recommendation_id")
        score = score_map.get(rec_id, 0)
        pnl = _num(t.get("pnl_pct"))
        if score >= 80 and pnl < 0:
            high_score_losers.append({
                "ticker": t.get("ticker"),
                "score": score,
                "pnl_pct": round(pnl, 1),
                "exit_reason": t.get("exit_reason"),
            })

    return {
        "high_score_losers": high_score_losers[:10],
        "low_score_winners": [],  # Would require backfill data
    }


def _compute_feature_correlations(closed: list, recommendations: list) -> dict:
    """Compute win rate by feature state for key features."""
    feat_map = {}
    for r in recommendations:
        rec_id = r.get("recommendation_id")
        feat_map[rec_id] = {
            "trend_state": r.get("trend_state"),
            "relative_strength_state": r.get("relative_strength_state"),
            "pullback_depth_pct": r.get("pullback_depth_pct"),
            "volume_state": r.get("volume_state"),
        }

    # Trend state correlation
    trend_groups = defaultdict(lambda: {"total": 0, "wins": 0})
    rs_groups = defaultdict(lambda: {"total": 0, "wins": 0})
    pullback_groups = defaultdict(lambda: {"total": 0, "wins": 0})
    vol_groups = defaultdict(lambda: {"total": 0, "wins": 0})

    for t in closed:
        rec_id = t.get("recommendation_id")
        feats = feat_map.get(rec_id, {})
        won = 1 if _num(t.get("pnl_dollars")) > 0 else 0

        trend = feats.get("trend_state", "unknown")
        trend_groups[trend]["total"] += 1
        trend_groups[trend]["wins"] += won

        rs = feats.get("relative_strength_state", "unknown")
        rs_groups[rs]["total"] += 1
        rs_groups[rs]["wins"] += won

        pb = feats.get("pullback_depth_pct")
        if pb is not None:
            try:
                pb = float(pb)
            except (ValueError, TypeError):
                pb = None
        if pb is not None:
            if -7 <= pb <= -3:
                pb_label = "3_to_7_pct"
            elif -12 <= pb < -7:
                pb_label = "7_to_12_pct"
            else:
                pb_label = "other"
            pullback_groups[pb_label]["total"] += 1
            pullback_groups[pb_label]["wins"] += won

        vol = feats.get("volume_state")
        if vol:
            vol_groups[vol]["total"] += 1
            vol_groups[vol]["wins"] += won

    def _wr(group):
        result = {}
        for k, v in group.items():
            wr = v["wins"] / v["total"] if v["total"] > 0 else 0
            result[f"{k}_win_rate"] = round(wr, 2)
        return result

    return {
        "trend_state": _wr(trend_groups),
        "relative_strength": _wr(rs_groups),
        "pullback_depth": _wr(pullback_groups),
        "volume_contraction": _wr(vol_groups),
    }


def _compute_training_status(days: int, db_path: str) -> dict:
    # Training pipeline health: example counts, quality scores, leakage
    # detection, and Annie Duke quadrant distribution.  The quadrant
    # analysis (good process + good outcome, etc.) is from *Thinking in
    # Bets* — it separates decision quality from outcome quality to avoid
    # "resulting" (judging decisions only by their outcomes).
    try:
        from src.training.versioning import get_training_example_counts
        counts = get_training_example_counts(db_path)
    except Exception:
        counts = {"total": 0, "live": 0, "backfill": 0}

    # Training data quality metrics
    training_data_quality = {}
    try:
        from src.training.validation import validate_training_dataset
        validation = validate_training_dataset(db_path)
        training_data_quality["format_compliance"] = validation.get("format_breakdown", {})
        training_data_quality["average_process_score"] = validation.get("avg_quality_score")
    except Exception as e:
        logger.debug("Training data validation failed: %s", e)

    try:
        from src.training.leakage_detector import check_outcome_leakage
        leakage = check_outcome_leakage(db_path)
        training_data_quality["leakage_test_accuracy"] = leakage.get("balanced_accuracy")
    except Exception as e:
        logger.debug("Leakage detection failed: %s", e)

    # Annie Duke quadrant distribution from source tags
    try:
        import sqlite3 as _sqlite3
        with connect_db(db_path) as conn:  # timeout upgraded to 30s via connect_db
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT source, quality_score_auto FROM training_examples "
                "WHERE source IN ('blinded_win', 'blinded_loss', 'blinded_timeout', 'blinded_pass') "
                "AND quality_score_auto IS NOT NULL"
            ).fetchall()
        quadrants = {
            "good_process_good_outcome": 0,
            "good_process_bad_outcome": 0,
            "bad_process_good_outcome": 0,
            "bad_process_bad_outcome": 0,
        }
        for row in rows:
            source = row["source"] or ""
            score = row["quality_score_auto"]
            is_win = "win" in source
            is_good_process = score is not None and _num(score) >= 3.0
            if is_good_process and is_win:
                quadrants["good_process_good_outcome"] += 1
            elif is_good_process and not is_win:
                quadrants["good_process_bad_outcome"] += 1
            elif not is_good_process and is_win:
                quadrants["bad_process_good_outcome"] += 1
            elif not is_good_process and not is_win:
                quadrants["bad_process_bad_outcome"] += 1
        training_data_quality["quadrant_distribution"] = quadrants
    except Exception as e:
        logger.debug("Quadrant distribution computation failed: %s", e)

    return {
        "total_examples": counts.get("total", 0),
        "backfill_examples": counts.get("backfill", 0),
        "live_examples": counts.get("live", 0),
        "examples_this_period": 0,  # Would need date filtering
        "model_version_trend": "stable",
        "training_data_quality": training_data_quality,
    }


def _compute_confidence_calibration(closed: list, recommendations: list) -> dict:
    """Compute confidence calibration from LLM conviction scores.

    Answers the critical question: "When the model says 9/10 conviction,
    does it actually win more than when it says 3/10?"  If yes, the
    model has genuine judgment.  If not, conviction is noise.

    Three conviction bands (8-10, 5-7, 1-4) are compared on win rate
    and average P&L.  Overconfidence rate = % of high-conviction (8-10)
    trades that lost money.  Pearson correlation between conviction and
    P&L pct gives a single calibration metric.
    """
    conv_map = {r.get("recommendation_id"): r.get("llm_conviction") for r in recommendations}

    excluded_no_rec_id = sum(1 for t in closed if t.get("recommendation_id") is None)
    trades_with_rec_id = [t for t in closed if t.get("recommendation_id") is not None]
    measurable_trades = [
        t for t in trades_with_rec_id
        if (t.get("exit_reason") or "").lower() not in _UNMEASURABLE_EXIT_REASONS
    ]
    excluded_unmeasurable = len(trades_with_rec_id) - len(measurable_trades)

    bands = {"8-10": [], "5-7": [], "1-4": []}
    convictions = []
    pnls = []

    for t in measurable_trades:
        rec_id = t.get("recommendation_id")
        conv = _num(conv_map.get(rec_id))
        if conv is None:
            continue

        pnl = _num(t.get("pnl_pct"))
        won = 1 if _num(t.get("pnl_dollars")) > 0 else 0
        convictions.append(conv)
        pnls.append(pnl)

        if conv >= 8:
            bands["8-10"].append((pnl, won))
        elif conv >= 5:
            bands["5-7"].append((pnl, won))
        else:
            bands["1-4"].append((pnl, won))

    by_band = {}
    for band, data in bands.items():
        if data:
            wr = sum(w for _, w in data) / len(data)
            avg_pnl = sum(p for p, _ in data) / len(data)
            by_band[band] = {"trades": len(data), "win_rate": round(wr, 2), "avg_pnl": round(avg_pnl, 1)}
        else:
            by_band[band] = {"trades": 0, "win_rate": 0, "avg_pnl": 0}

    # Correlation
    correlation = 0.0
    if len(convictions) >= 5:
        from src.evaluation.feature_importance import _pearson_correlation
        correlation = _pearson_correlation([float(c) for c in convictions], pnls)

    # Calibration check: higher conviction should = higher win rate
    is_calibrated = True
    if by_band["8-10"]["trades"] >= 3 and by_band["1-4"]["trades"] >= 3:
        is_calibrated = by_band["8-10"]["win_rate"] > by_band["1-4"]["win_rate"]

    # Overconfidence rate
    high_conv_losers = sum(1 for p, w in bands["8-10"] if w == 0)
    overconfidence = high_conv_losers / len(bands["8-10"]) if bands["8-10"] else 0

    return {
        "by_conviction_band": by_band,
        "correlation_with_outcomes": round(correlation, 3),
        "is_calibrated": is_calibrated,
        "overconfidence_rate": round(overconfidence, 2),
        "total_with_conviction": len(convictions),
        "excluded_no_recommendation_id": excluded_no_rec_id,
        "excluded_unmeasurable_exit": excluded_unmeasurable,
    }


def _compute_fund_metrics(closed: list, trade_summary: dict) -> dict:
    """Compute fund-level performance metrics (Sortino, Calmar, VaR, etc.).

    These are institutional-grade metrics that would appear in a fund's
    factsheet.  Included even during paper trading so we can benchmark
    against them before committing real capital.

    Key metrics:
      - Sortino:  like Sharpe but only penalizes downside volatility
      - Calmar:   annualized return / max drawdown (risk/reward efficiency)
      - VaR 95%:  5th percentile of returns ("worst expected day")
      - Monthly batting avg: % of months with positive P&L
      - Skewness: positive = more big winners than losers (desirable)
    """
    pnl_pcts = [_num(t.get("pnl_pct")) for t in closed]
    pnl_dollars = [_num(t.get("pnl_dollars")) for t in closed]
    durations = _measurable_hold_durations(closed)

    if len(pnl_pcts) < 2:
        return {
            "sortino_ratio": None,
            "calmar_ratio": None,
            "var_95": None,
            "monthly_batting_avg": None,
            "avg_hold_period_days": None,
            "return_skewness": None,
            "best_trade_pct": None,
            "worst_trade_pct": None,
            "total_return_pct": None,
            "beta": None,
            "alpha": None,
        }

    mean_r = sum(pnl_pcts) / len(pnl_pcts)

    # Sortino ratio — only penalizes downside volatility.
    # Better than Sharpe for asymmetric return distributions because
    # we WANT upside volatility (big winners) — only downside hurts.
    # F-2 / Sprint-0 wave-4a: route through canonical compute_sortino_mar
    # (MAR=0, RMS-of-downside divisor) — preserves the legacy formula at
    # the canonical surface. periods_per_year=150 matches Sharpe parity.
    # `inf` and 0 sentinels at the call site reproduce the legacy contract
    # (no downside → +inf if profitable, else 0).
    from src.analytics.canonical_sharpe import compute_sortino_mar
    from src.evaluation.statistics import calmar_ratio
    downside = [r for r in pnl_pcts if r < 0]
    if not downside:
        sortino = float('inf') if mean_r > 0 else 0
    else:
        sortino_canonical = compute_sortino_mar(pnl_pcts, periods_per_year=150, mar=0.0)
        sortino = 0 if sortino_canonical is None else sortino_canonical

    # Calmar ratio — return / max drawdown
    max_dd_pct = trade_summary.get("max_drawdown_pct", 0)
    calmar = calmar_ratio(mean_r * 150, max_dd_pct)

    # VaR 95% — 5th percentile of returns
    sorted_pnl = sorted(pnl_pcts)
    var_idx = max(0, int(len(sorted_pnl) * 0.05) - 1)
    var_95 = sorted_pnl[var_idx] if sorted_pnl else 0

    # Monthly batting average — % of months with positive P&L
    monthly_pnl = defaultdict(float)
    for t in closed:
        month_key = (t.get("created_at") or "")[:7]
        if month_key:
            monthly_pnl[month_key] += _num(t.get("pnl_dollars"))
    positive_months = sum(1 for v in monthly_pnl.values() if v > 0)
    monthly_batting = (positive_months / len(monthly_pnl) * 100) if monthly_pnl else None

    # Average hold period
    avg_hold = sum(durations) / len(durations) if durations else 0

    # Return skewness
    if len(pnl_pcts) >= 3:
        std_r = (sum((r - mean_r) ** 2 for r in pnl_pcts) / (len(pnl_pcts) - 1)) ** 0.5
        if std_r > 0:
            skew = (sum((r - mean_r) ** 3 for r in pnl_pcts) / len(pnl_pcts)) / (std_r ** 3)
        else:
            skew = 0
    else:
        skew = None

    # Best / worst trade
    best = max(pnl_pcts) if pnl_pcts else None
    worst = min(pnl_pcts) if pnl_pcts else None

    # Total return (sum of all trade P&L as % of starting capital)
    total_pnl = sum(pnl_dollars)
    from src.config import load_config
    _cfg = load_config()
    starting_capital = _cfg.get("risk", {}).get("starting_capital", 100000)
    total_return_pct = (total_pnl / starting_capital) * 100

    return {
        "sortino_ratio": round(sortino, 2) if sortino != float('inf') else "inf",
        "calmar_ratio": round(calmar, 2),
        "var_95": round(var_95, 2),
        "monthly_batting_avg": round(monthly_batting, 1) if monthly_batting is not None else None,
        "avg_hold_period_days": round(avg_hold, 1),
        "return_skewness": round(skew, 2) if skew is not None else None,
        "best_trade_pct": round(best, 2) if best is not None else None,
        "worst_trade_pct": round(worst, 2) if worst is not None else None,
        "total_return_pct": round(total_return_pct, 2),
        "beta": None,
        "alpha": None,
    }


def format_cto_report(report: dict) -> str:
    """Format the CTO report as a readable text summary."""
    lines = []
    lines.append("=" * 60)
    lines.append(f" CTO PERFORMANCE REPORT")
    lines.append(f" Period: {report['report_period']['start']} to {report['report_period']['end']}")
    lines.append(f" Trading Days: {report['report_period']['trading_days']}")
    lines.append("=" * 60)
    lines.append("")

    status = report["system_status"]
    lines.append(f"MODEL: {status['model_version']} | Dataset: {status['dataset_size']} examples")
    lines.append("")

    # Headline KPIs — the 5 numbers that matter most
    kpis = report.get("headline_kpis", {})
    lines.append("HEADLINE KPIs:")
    lines.append(f"  Sharpe Ratio:     {kpis.get('sharpe_ratio', 0):>8.2f}   (target: > 0.5 Phase 1, > 1.0 Phase 3)")
    lines.append(f"  Win Rate:         {kpis.get('win_rate', 0):>8.1%}   (target: > 45%)")
    lines.append(f"  Max Drawdown:     {kpis.get('max_drawdown_pct', 0):>7.1f}%   (target: < 15%)")
    cal = kpis.get('confidence_calibration', 0)
    lines.append(f"  Confidence Cal:   {cal:>8.3f}   (target: > 0.3 = model has judgment)")
    rubric = kpis.get('avg_rubric_score')
    lines.append(f"  Avg Rubric Score: {rubric:>8.1f}/5  (target: > 3.5 = institutional quality)" if rubric else "  Avg Rubric Score:      n/a   (run score-training-data)")
    lines.append("")

    ts = report["trade_summary"]
    lines.append("TRADE SUMMARY:")
    lines.append(f"  Opened: {ts['trades_opened']} | Closed: {ts['trades_closed']} | Open: {ts['trades_open']}")
    lines.append(f"  Win Rate: {ts['win_rate']:.1%} | Sharpe: {ts.get('sharpe_ratio', 0):.2f} | Profit Factor: {ts.get('profit_factor', 0)}")
    lines.append(f"  Avg Winner: {ts['avg_winner_pct']:+.1f}% | Avg Loser: {ts['avg_loser_pct']:+.1f}%")
    lines.append(f"  Expectancy: ${ts['expectancy_dollars']:+.2f} | Total P&L: ${ts['total_pnl']:+.2f}")
    lines.append(f"  Max Drawdown: ${ts.get('max_drawdown_dollars', 0):.2f} ({ts.get('max_drawdown_pct', 0):.1f}%) | Max Consec Losses: {ts.get('max_consecutive_losses', 0)}")
    if ts.get("max_single_win"):
        lines.append(f"  Best: {ts['max_single_win']['ticker']} ({ts['max_single_win']['pnl_pct']:+.1f}%)")
    if ts.get("max_single_loss"):
        lines.append(f"  Worst: {ts['max_single_loss']['ticker']} ({ts['max_single_loss']['pnl_pct']:+.1f}%)")
    lines.append("")

    lines.append("BY EXIT REASON:")
    for reason, data in report["by_exit_reason"].items():
        lines.append(f"  {reason}: {data['count']} trades, avg {data['avg_pnl']:+.1f}%")
    lines.append("")

    lines.append("BY SCORE BAND:")
    for band, data in report["by_score_band"].items():
        lines.append(f"  {band}: {data['trades']} trades, WR {data['win_rate']:.0%}, avg {data['avg_pnl']:+.1f}%")
    lines.append("")

    lines.append("BY SECTOR:")
    for sector, data in sorted(report["by_sector"].items(), key=lambda x: -x[1]["trades"]):
        lines.append(f"  {sector}: {data['trades']} trades, WR {data['win_rate']:.0%}")
    lines.append("")

    exec_data = report["execution_analysis"]
    lines.append("EXECUTION:")
    lines.append(f"  Targets hit: {exec_data['targets_hit_pct']:.0%} | Timeout: {exec_data['timeout_pct']:.0%}")
    lines.append(f"  Avg MFE (winners): ${exec_data['avg_mfe_winners']:.2f} | Avg MAE (losers): ${exec_data['avg_mae_losers']:.2f}")
    lines.append(f"  Avg hold: {exec_data['avg_hold_period_days']:.1f} days")
    lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
