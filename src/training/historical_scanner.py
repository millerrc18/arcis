"""Historical scanner with outcome tracking and training example generation.

Called by: training.backfill, scripts.export_backfill_prompts
Calls: config, data_enrichment.news, features.engine, features.regime, llm.prompts, ranking.ranker, training.historical_data, training.regime_sampler, universe.company_names
Owns tables: none
Config keys: data_enrichment, finnhub_api_key, include_news_in_backfill
Tests: tests/test_backfill.py, tests/test_leakage_detector.py

Runs the scoring engine against point-in-time historical data, tracks
real trade outcomes, and builds training examples from real setups.
"""

import logging

import pandas as pd

from src.features.engine import compute_features
from src.llm.prompts import BLINDED_ANALYSIS_PROMPT, PASS_ANALYSIS_PROMPT
from src.ranking.ranker import _score_ticker
from src.training.historical_data import slice_to_date
from src.universe.company_names import get_company_name

logger = logging.getLogger(__name__)

# Normal thresholds (not bootcamp) — we want quality setups
PACKET_WORTHY_THRESHOLD = 70
WATCHLIST_THRESHOLD = 45


def _scan_date_core(
    data: dict, scan_date: str, fred_data: dict | None = None,
    min_score: float = 70, max_score: float = 100,
    qualification: str = "packet_worthy", fetch_news: bool = True,
) -> list[dict]:
    """Shared scanning logic for TRADE and PASS examples.

    Slices data to scan_date, computes regime + features for every
    ticker, filters by [min_score, max_score] band.
    """
    ohlcv_dict, spy_df = slice_to_date(data, scan_date)

    if spy_df.empty or len(spy_df) < 200:
        return []

    # Compute market regime ONCE for this date
    regime = {}
    try:
        from src.features.regime import compute_market_regime
        regime = compute_market_regime(spy_df, ohlcv_dict)
    except Exception as e:
        logger.debug("Failed to compute market regime for %s: %s", scan_date, e)

    candidates = []
    for ticker, df in ohlcv_dict.items():
        try:
            features = compute_features(ticker, df, spy_df)
            features["earnings_date"] = None
            features["hold_overlaps_earnings"] = False
            features["days_to_earnings"] = None
            features["event_risk_level"] = "none"
            features.update(regime)

            # Enrichment — use real FRED data when available
            features["insider_summary"] = "Not available for historical scan"
            if fred_data:
                from src.training.regime_sampler import format_macro_summary
                features["macro_summary"] = format_macro_summary(fred_data, scan_date)
                features["fundamental_summary"] = (
                    f"Historical scan for {get_company_name(ticker)} ({ticker}) "
                    f"in the {features.get('sector', 'unknown')} sector"
                )
            else:
                features["fundamental_summary"] = "Not available for historical scan"
                features["macro_summary"] = "Not available for historical scan"

            # News: attempt fetch for TRADE examples, skip for PASS
            if fetch_news:
                try:
                    from src.config import load_config
                    cfg = load_config()
                    enrichment_cfg = cfg.get("data_enrichment", {})
                    if enrichment_cfg.get("include_news_in_backfill", True):
                        from src.data_enrichment.news import fetch_historical_news, format_news_summary
                        finnhub_key = enrichment_cfg.get("finnhub_api_key")
                        news_data = fetch_historical_news(
                            ticker, as_of_date=scan_date,
                            finnhub_api_key=finnhub_key,
                        )
                        features["news_summary"] = format_news_summary(news_data)
                        features["news_sentiment"] = (news_data or {}).get("news_sentiment", "no_news")
                    else:
                        features["news_summary"] = "News data not available for historical scan"
                        features["news_sentiment"] = "no_news"
                except Exception as e:
                    features["news_summary"] = "News data not available for historical scan"
                    features["news_sentiment"] = "no_news"
                    logger.debug("Historical news failed for %s on %s: %s", ticker, scan_date, e)
            else:
                features["news_summary"] = "News data not available for historical scan"
                features["news_sentiment"] = "no_news"

            score = _score_ticker(features)
            if score < min_score or score > max_score:
                continue

            entry_price = features["current_price"]
            atr = features["atr_14"]

            candidates.append({
                "scan_date": scan_date,
                "ticker": ticker,
                "score": score,
                "qualification": qualification,
                "features": features,
                "entry_price": round(entry_price, 2),
                "stop_price": round(entry_price - (2 * atr), 2),
                "target_1": round(entry_price + (1.5 * atr), 2),
                "target_2": round(entry_price + (3 * atr), 2),
            })
        except Exception as e:
            logger.debug("Failed to compute features for %s on %s: %s",
                         ticker, scan_date, e)
            continue

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def scan_historical_date(data: dict, scan_date: str, fred_data: dict | None = None) -> list[dict]:
    """Run the full scan pipeline as-of a specific date.

    Simulates what the system would have produced on that date,
    using ONLY data available on or before that date.

    Args:
        data: Output of fetch_historical_universe().
        scan_date: ISO date string.
        fred_data: Optional output of fetch_fred_history(). When provided,
            real FRED macro data replaces placeholder text.

    Returns:
        List of qualified candidates with features, scores, and price levels.
    """
    return _scan_date_core(
        data, scan_date, fred_data=fred_data,
        min_score=PACKET_WORTHY_THRESHOLD, max_score=100,
        qualification="packet_worthy", fetch_news=True,
    )


def scan_historical_date_pass(
    data: dict, scan_date: str, fred_data: dict | None = None,
    min_score: float = 45, max_score: float = 69,
) -> list[dict]:
    """Scan for PASS examples — setups that score 45-69 (below threshold).

    Same scanning logic as scan_historical_date() but captures the middle
    band of scores: interesting enough to appear on the scanner but not
    qualifying for a trade recommendation.

    Returns:
        List of below-threshold candidates with features and scores.
    """
    return _scan_date_core(
        data, scan_date, fred_data=fred_data,
        min_score=min_score, max_score=max_score,
        qualification="pass", fetch_news=False,
    )


def compute_outcome(
    data: dict,
    ticker: str,
    entry_date: str,
    entry_price: float,
    stop_price: float,
    target_1: float,
    target_2: float,
    max_hold_days: int = 15,
) -> dict | None:
    """Track what actually happened after a historical entry.

    Simulates the shadow trade logic: check each subsequent day for
    stop hit, target hit, or timeout.

    Returns:
        Outcome dict, or None if insufficient future data exists.
    """
    ticker_df = data["tickers"].get(ticker)
    if ticker_df is None:
        return None

    entry_ts = pd.Timestamp(entry_date)
    future = ticker_df[ticker_df.index > entry_ts]

    if len(future) < 2:
        return None

    # Limit to max_hold_days trading days
    hold_data = future.iloc[:max_hold_days]

    exit_date = None
    exit_price = None
    exit_reason = None

    # Track MFE and MAE
    max_favorable = 0.0
    max_adverse = 0.0

    for i, (date, row) in enumerate(hold_data.iterrows()):
        day_high = float(row["High"])
        day_low = float(row["Low"])
        day_close = float(row["Close"])

        # Update MFE/MAE using intraday prices
        favorable = day_high - entry_price
        adverse = entry_price - day_low
        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        # Check stop and target hits
        stop_hit = day_low <= stop_price
        t1_hit = day_high >= target_1
        t2_hit = day_high >= target_2

        # If stop and target hit on same day, assume stop hit first (conservative)
        if stop_hit and (t1_hit or t2_hit):
            exit_date = date.strftime("%Y-%m-%d")
            exit_price = stop_price
            exit_reason = "stop_hit"
            break
        elif stop_hit:
            exit_date = date.strftime("%Y-%m-%d")
            exit_price = stop_price
            exit_reason = "stop_hit"
            break
        elif t2_hit:
            exit_date = date.strftime("%Y-%m-%d")
            exit_price = target_2
            exit_reason = "target_2_hit"
            break
        elif t1_hit:
            exit_date = date.strftime("%Y-%m-%d")
            exit_price = target_1
            exit_reason = "target_1_hit"
            break

    # Timeout: neither stop nor target hit within max_hold_days
    if exit_reason is None:
        if len(hold_data) == 0:
            return None
        last_row = hold_data.iloc[-1]
        exit_date = hold_data.index[-1].strftime("%Y-%m-%d")
        exit_price = float(last_row["Close"])
        exit_reason = "timeout"

    pnl_dollars = round(exit_price - entry_price, 2)
    pnl_pct = round(pnl_dollars / entry_price * 100, 2)

    # Duration in trading days
    entry_ts_date = pd.Timestamp(entry_date)
    exit_ts_date = pd.Timestamp(exit_date)
    # Count trading days between entry and exit
    trading_days = len(ticker_df[(ticker_df.index > entry_ts_date) &
                                  (ticker_df.index <= exit_ts_date)])

    # Classify outcome quality
    outcome_quality = _classify_outcome_quality(
        exit_reason, max_favorable, max_adverse
    )

    return {
        "exit_date": exit_date,
        "exit_price": round(exit_price, 2),
        "exit_reason": exit_reason,
        "pnl_dollars": pnl_dollars,
        "pnl_pct": pnl_pct,
        "duration_days": trading_days,
        "max_favorable_excursion": round(max_favorable, 2),
        "max_adverse_excursion": round(-max_adverse, 2),
        "outcome_quality": outcome_quality,
    }


def _classify_outcome_quality(
    exit_reason: str, mfe: float, mae: float
) -> str:
    """Classify outcome quality based on exit reason and excursions.

    - clean_win: target hit, MFE > 2x MAE
    - clean_loss: stop hit, MAE > 2x MFE
    - messy: target or stop hit but MFE and MAE both significant
    - timeout: neither target nor stop hit
    """
    if exit_reason == "timeout":
        return "timeout"

    if exit_reason in ("target_1_hit", "target_2_hit"):
        if mae == 0 or mfe > 2 * mae:
            return "clean_win"
        return "messy"

    if exit_reason == "stop_hit":
        if mfe == 0 or mae > 2 * mfe:
            return "clean_loss"
        return "messy"

    return "messy"


def generate_backfill_example(candidate: dict, outcome: dict | None = None) -> dict:
    """Build training example from a historical scan + outcome.

    Input_text matches _build_feature_prompt() format — NO outcome data.
    For PASS examples (outcome=None), uses PASS_ANALYSIS_PROMPT.
    """
    features = candidate["features"]
    ticker = candidate["ticker"]
    company_name = get_company_name(ticker)
    is_pass = outcome is None

    # Build input_text in the same multi-source format as _build_feature_prompt()
    input_text = f"""=== TECHNICAL DATA ===
Ticker: {ticker} ({company_name})
Current Price: ${features.get('current_price', 0):.2f}
Trend State: {features.get('trend_state', 'n/a')} | SMA50 slope: {features.get('sma50_slope', 'n/a')} | SMA200 slope: {features.get('sma200_slope', 'n/a')}
Price vs SMA50: {features.get('price_vs_sma50_pct', 0):.1f}% | Price vs SMA200: {features.get('price_vs_sma200_pct', 0):.1f}%
Relative Strength: {features.get('relative_strength_state', 'n/a')}
RS vs SPY — 1m: {features.get('rs_vs_spy_1m', 0):.1f}% | 3m: {features.get('rs_vs_spy_3m', 0):.1f}% | 6m: {features.get('rs_vs_spy_6m', 0):.1f}%
Pullback Depth: {features.get('pullback_depth_pct', 0):.1f}% from 50-day high
ATR(14): ${features.get('atr_14', 0):.2f} ({features.get('atr_pct', 0):.1f}% of price)
Volume Ratio: {features.get('volume_ratio_20d', 0):.2f}x 20-day average
Distance to SMA20: {features.get('dist_to_sma20_pct', 0):.1f}%

=== MARKET REGIME ===
Market Trend: {features.get('market_trend', 'n/a')} | SPY RSI(14): {features.get('spy_rsi_14', 'n/a')}
Volatility: {features.get('volatility_regime', 'n/a')} ({features.get('vix_proxy', 0):.1f}% realized vol)
SPY: {features.get('spy_20d_return', 0):+.1f}% (20d) | {features.get('spy_drawdown_from_high', 0):.1f}% from 52-week high
Breadth: {features.get('market_breadth_label', 'n/a')} ({features.get('market_breadth_pct', 0):.0f}% above 50d MA)
Regime: {features.get('regime_label', 'n/a')}

=== SECTOR CONTEXT ===
Sector: {features.get('sector', 'n/a')} | Rank: {features.get('sector_rs_rank', 'n/a')} | Sector Avg Score: {features.get('sector_avg_score', 0):.0f}

=== FUNDAMENTAL SNAPSHOT ===
{features.get('fundamental_summary', 'Not available for historical scan')}

=== INSIDER ACTIVITY ===
{features.get('insider_summary', 'Not available for historical scan')}

=== RECENT NEWS ===
{features.get('news_summary', 'News data not available for historical scan')}

=== MACRO CONTEXT ===
{features.get('macro_summary', 'Not available for historical scan')}

=== TRADE PARAMETERS ===
Score: {candidate['score']:.0f}/100
Entry: ${candidate['entry_price']:.2f} | Stop: ${candidate['stop_price']:.2f} | Target 1: ${candidate['target_1']:.2f} | Target 2: ${candidate['target_2']:.2f}
Event Risk: none"""

    # NOTE: Outcome is NOT appended to input_text — self-blinding pipeline
    # ensures Claude never sees the outcome during generation.

    if is_pass:
        instruction = PASS_ANALYSIS_PROMPT.format(date=candidate["scan_date"])
        metadata = {
            "scan_date": candidate["scan_date"],
            "ticker": ticker,
            "score": candidate["score"],
            "entry_price": candidate["entry_price"],
            "outcome_quality": "pass",
        }
    else:
        instruction = BLINDED_ANALYSIS_PROMPT.format(date=candidate["scan_date"])
        metadata = {
            "scan_date": candidate["scan_date"],
            "ticker": ticker,
            "score": candidate["score"],
            "entry_price": candidate["entry_price"],
            "exit_price": outcome["exit_price"],
            "exit_reason": outcome["exit_reason"],
            "pnl_pct": outcome["pnl_pct"],
            "duration_days": outcome["duration_days"],
            "outcome_quality": outcome["outcome_quality"],
        }

    return {
        "instruction": instruction,
        "input_text": input_text,
        "output_text": None,
        "metadata": metadata,
    }
