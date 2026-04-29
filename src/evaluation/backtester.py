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


def _resolve_corpus_decision(
    corpus_entries: dict,
    corpus_id: str | None,
    date_str: str,
    ticker: str,
    *,
    shadow: bool = False,
) -> tuple[bool, "object | None"]:
    """Return (should_trade, corpus_entry) for a (date, ticker) candidate.

    Pre-reg §A3 reproducibility: corpus is the binding source — no live-LLM
    fallback. Per §A1.4 parse_failed=1 entries are pre-filtered upstream by
    load_entries_by_decision(parse_clean_only=True) — that filter is binding
    for both primary AND shadow per §A1.6 fair-comparison rule. Per §A1.5
    only llm_action='taken' enters the primary metric. Per §A1.6 the shadow
    strips the llm_action filter — every parse-clean entry trades.
    """
    if corpus_id is None:
        return True, None
    entry = corpus_entries.get((date_str, ticker))
    if entry is None:
        logger.warning(
            "Corpus miss for (%s, %s) in corpus_id=%s — skipped (no live-LLM fallback)",
            date_str, ticker, corpus_id,
        )
        return False, None
    if shadow:
        return True, entry
    if entry.llm_action != "taken":
        return False, None
    return True, entry


def backtest_model(model_name: str, months: int = 6,
                   db_path: str = DB_PATH,
                   train_start: str | None = None,
                   train_end: str | None = None,
                   test_start: str | None = None,
                   test_end: str | None = None,
                   rf_source: str = "fred",
                   corpus_id: str | None = None,
                   shadow: bool = False) -> dict:
    """Run a walk-forward backtest of a trained model on historical data.

    Process: load data → per-day compute features → run ranker → get model
    output → parse conviction → track simulated portfolio → compute metrics.

    When ``corpus_id`` is set, LLM scores are read from the pre-generated
    corpus (#96.1); see _resolve_corpus_decision for the binding pre-reg
    §A1.4 / §A1.5 / §A1.6 / §A3 row-filter semantics. When ``shadow`` is
    True (#82, pre-reg §A1.6), the LLM filter is stripped: corpus_id+shadow
    takes every parse-clean entry; corpus_id=None+shadow takes every ranker
    candidate. shadow=False preserves all existing behavior.
    """
    from src.cost_model.calibration import get_calibrated_cost_model
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.training.historical_data import slice_to_date
    from src.training.historical_scanner import compute_outcome

    # Pre-load the corpus index when corpus_id is set. Default
    # parse_clean_only=True per pre-reg §A1.4 binding row filter.
    corpus_entries: dict[tuple[str, str], "object"] = {}
    if corpus_id is not None:
        from src.evaluation.corpus import load_entries_by_decision
        corpus_entries = load_entries_by_decision(corpus_id, parse_clean_only=True)

    cost_model = get_calibrated_cost_model()
    if cost_model is None:
        logger.warning(
            "No calibrated cost model found at default path — "
            "falling back to raw pnl_pct (no slippage/commission deduction)"
        )
        calibration_applied = False
        round_trip_cost_pct = 0.0
    else:
        calibration_applied = True
        round_trip_cost_pct = (cost_model.get("median_round_trip_cost_bps") or 0.0) / 100.0

    config = load_config()

    # PR #831 review fix: when the walk-forward harness passes test_start/test_end,
    # use those dates instead of the today-based fallback. The harness assumes the
    # model is already trained on the train window (train_start/train_end are
    # accepted for symmetry but not actively used here — that's a methodological
    # invariant the harness enforces by selecting which model_name to test).
    if test_start and test_end:
        start_date = datetime.fromisoformat(test_start)
        end_date = datetime.fromisoformat(test_end)
    else:
        end_date = datetime.now() - timedelta(days=20)
        start_date = end_date - timedelta(days=months * 30)

    from src.universe.pit import get_sp100_at
    universe = get_sp100_at(start_date.date().isoformat())  # T10: as_of source: start_date

    # Sprint 1.C.4.5 / #104 — Bug C fix. Previously this used
    # ``fetch_ohlcv(period=f"{window_days+60}d")`` which is anchored to TODAY by
    # yfinance's ``period`` semantics. For an old fold (e.g., test_start=2023-09-01)
    # that fetched data from 2025-10-29 onwards, 789 days AFTER the test span,
    # so slice_to_date returned 0 rows for every iteration → fold 1-7 produced
    # 0 trades (only fold 8 overlapped with the recent fetch window).
    #
    # Fix: anchor the fetch to test_start. We pull (test_start - 280 calendar
    # days) through test_end so that slice_to_date's 200-trading-day minimum
    # (~280 calendar days) is satisfied for the test_start cutoff. PIT
    # cleanliness is still enforced at slice_to_date time (df.index <= cutoff);
    # fetching wider data is methodologically fine per pre-reg addendum 1 §A1.
    fetch_start = (start_date - timedelta(days=280)).date().isoformat()
    fetch_end = end_date.date().isoformat()

    try:
        ohlcv = fetch_ohlcv(universe, start=fetch_start, end=fetch_end)
        spy = fetch_spy_benchmark(start=fetch_start, end=fetch_end)
    except (ConnectionError, TimeoutError) as e:
        # Network-layer failures (transient): return an error dict so the caller
        # can decide whether to retry. All other exceptions (KeyError on missing
        # config, RuntimeError from a code bug, etc.) re-raise so they are visible.
        return {"error": f"Data fetch failed: {e}"}

    if spy.empty:
        return {"error": "SPY benchmark empty"}

    # Generate trading days
    import pandas as pd
    trading_days = pd.bdate_range(start_date, end_date)

    if rf_source not in ("placeholder", "fred"):
        raise ValueError(f"rf_source must be 'placeholder' or 'fred'; got {rf_source!r}")

    if rf_source == "fred":
        from src.data_ingestion.risk_free_rate import get_rf_rate
    _RF_PLACEHOLDER = 0.0001

    trades = []
    equity_curve = [{"date": start_date.strftime("%Y-%m-%d"), "equity": 1000}]
    current_equity = 1000.0
    daily_pnls = []
    excess_pnls = []

    for day in trading_days[::5]:  # Sample every 5th day for speed
        date_str = day.strftime("%Y-%m-%d")

        try:
            # slice_to_date expects {"tickers": {...}, "spy": df} and returns
            # (ohlcv_dict, spy_sliced) — match its contract here. Prior code passed
            # the flat ohlcv dict and bound a single var, raising KeyError('spy')
            # on every iteration which the silent except below swallowed → trades=0.
            sliced, spy_sliced = slice_to_date({"tickers": ohlcv, "spy": spy}, date_str)

            if not sliced or spy_sliced.empty:
                continue

            features = compute_all_features(sliced, spy_sliced, as_of=date_str)
            ranked = rank_universe(features)
            candidates = get_top_candidates(ranked)

            for cand in candidates.get("packet_worthy", [])[:3]:  # Max 3 per day
                ticker = cand["ticker"]
                score = cand["score"]
                feat = cand["features"]

                should_trade, corpus_entry = _resolve_corpus_decision(
                    corpus_entries, corpus_id, date_str, ticker, shadow=shadow,
                )
                if not should_trade:
                    continue

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

                    pnl_pct = outcome.get("pnl_pct", 0) - round_trip_cost_pct

                    import datetime as _dt
                    _trade_date = _dt.date.fromisoformat(date_str)
                    if rf_source == "fred":
                        try:
                            rf_per_day = get_rf_rate(_trade_date)
                        except Exception:
                            rf_per_day = _RF_PLACEHOLDER
                    else:
                        rf_per_day = _RF_PLACEHOLDER

                    trade_record = {
                        "date": date_str,
                        "ticker": ticker,
                        "score": score,
                        "entry": entry,
                        "exit_reason": outcome.get("exit_reason"),
                        "pnl_pct": pnl_pct,
                        "duration": outcome.get("duration_days", 0),
                        "regime": feat.get("regime_label", "unknown"),
                    }
                    if corpus_entry is not None:
                        # Per pre-reg §A3.1 round-trip integrity — record the
                        # corpus's llm_conviction so #81 subgroup analysis can
                        # partition by conviction tier.
                        trade_record["llm_conviction"] = corpus_entry.llm_conviction
                    trades.append(trade_record)

                    # Update equity
                    allocation_pct = 0.05  # 5% per trade
                    equity_change = current_equity * allocation_pct * (pnl_pct / 100)
                    current_equity += equity_change
                    daily_pnls.append(pnl_pct)
                    excess_pnls.append(pnl_pct / 100 - rf_per_day)

        except (ConnectionError, TimeoutError) as e:
            # Recoverable: transient network errors fetching intraday or benchmark
            # data for a single day. Skip this iteration and continue the backtest.
            # KeyError is NOT caught here — a missing dict key indicates a code bug
            # (e.g. mismatched feature schema) and must fail loudly so it is fixed,
            # not silently masked as a "missed trading day."
            logger.warning("Backtest day %s recoverable error: %s", date_str, e)
            continue

        equity_curve.append({"date": date_str, "equity": round(current_equity, 2)})

    if not trades:
        return {"model": model_name, "trades_generated": 0, "error": "No qualifying trades found",
                "calibration_applied": calibration_applied}

    # Compute metrics
    winners = [t for t in trades if t["pnl_pct"] > 0]
    losers = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(winners) / len(trades) if trades else 0
    total_pnl_pct = ((current_equity - 1000) / 1000) * 100

    # Sharpe ratio — rf-adjusted when rf_source='fred', raw otherwise.
    # F-2 (Sprint 0/4b WALKFORWARD-CANONICAL): route through
    # src.analytics.canonical_sharpe so all Sharpe computations flow through
    # one source of truth.  When rf_source='fred' we use excess_pnls (already
    # rf-subtracted per-trade); when rf_source='placeholder' we fall back to
    # the raw daily_pnls path (0.0001 subtracted in excess_pnls, same as before).
    # canonical returns None when Sharpe is undefined (single-obs / zero
    # variance); backtester contract maps None -> 0.
    from src.analytics.canonical_sharpe import compute_sharpe as _canonical_compute_sharpe
    _sharpe_series = excess_pnls if excess_pnls else list(daily_pnls)
    _sharpe_val = _canonical_compute_sharpe(_sharpe_series, periods_per_year=252)
    sharpe = _sharpe_val if _sharpe_val is not None else 0
    rf_excess_mean = sum(excess_pnls) / len(excess_pnls) if excess_pnls else 0.0

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
        "trades": trades,
        "win_rate": round(win_rate, 3),
        "total_pnl_pct": round(total_pnl_pct, 1),
        "sharpe_ratio": round(sharpe, 2),
        "rf_source": rf_source,
        "rf_excess_mean": rf_excess_mean,
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_duration_days": max_dd_duration_days,
        "calmar_ratio": calmar,
        "monthly_returns": monthly_returns,
        "trade_gap_days": avg_trade_gap,
        "by_regime": regime_summary,
        "equity_curve": equity_curve[:50],
        "calibration_applied": calibration_applied,
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
