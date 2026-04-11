"""Regime-targeted date selection and dataset balancing utilities.

Called by: scripts.export_backfill_prompts, training.backfill
Calls: features.regime, training.historical_data
Owns tables: none
Config keys: none
Tests: tests/test_regime_sampler.py

Provides stratified sampling by market regime for backfill prompt
generation, plus dataset balancing helpers shared with the automated
backfill pipeline.
"""

import logging
import random
from collections import Counter, defaultdict

import pandas as pd

logger = logging.getLogger(__name__)

# Map 5 regime_label values from features.regime to target categories.
# Priority ordering: high_vol > bear > recovery > range > bull.
REGIME_MAP = {
    "volatile_downtrend": "bear",
    "calm_downtrend": "bear",
    "volatile_uptrend": "high_vol",
    "transitional": "recovery",
    "calm_uptrend": "bull",
}

# When regime_label is missing or unrecognized, fall back to this.
DEFAULT_REGIME = "range"


def classify_dates_by_regime(spy_df: pd.DataFrame, ohlcv_data: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Classify each trading day by market regime using SPY data.

    Computes market regime for each trading day (with sufficient history)
    and groups dates by the mapped regime category.

    Returns:
        {"bull": ["2021-03-15", ...], "bear": [...], ...}
    """
    from src.features.regime import compute_market_regime

    dates = [d.strftime("%Y-%m-%d") for d in spy_df.index]
    regime_dates: dict[str, list[str]] = defaultdict(list)

    for date_str in dates:
        cutoff = pd.Timestamp(date_str)
        spy_slice = spy_df[spy_df.index <= cutoff]
        if len(spy_slice) < 252:
            continue

        # Slice ohlcv_data for breadth computation
        ohlcv_slice = {}
        for ticker, df in ohlcv_data.items():
            sliced = df[df.index <= cutoff]
            if len(sliced) >= 50:
                ohlcv_slice[ticker] = sliced

        try:
            regime_data = compute_market_regime(spy_slice, ohlcv_slice)
            regime_label = regime_data.get("regime_label", "")
            category = REGIME_MAP.get(regime_label, DEFAULT_REGIME)
            regime_dates[category].append(date_str)
        except Exception as e:
            logger.debug("Failed to classify regime for %s: %s", date_str, e)
            continue

    for category, dates_list in regime_dates.items():
        logger.info("[REGIME] %s: %d trading days", category, len(dates_list))

    return dict(regime_dates)


def sample_regime_balanced_dates(
    regime_dates: dict[str, list[str]],
    targets: dict[str, int],
) -> dict[str, list[str]]:
    """Sample dates from each regime to hit target counts.

    Uses 1.5x oversampling to account for dates that won't produce
    qualifying setups. Shuffles within each regime for diversity.

    Args:
        regime_dates: Output of classify_dates_by_regime().
        targets: {"bull": 120, "bear": 80, ...} — target example counts.

    Returns:
        {"bull": [sampled dates], "bear": [sampled dates], ...}
    """
    sampled = {}
    for regime, target in targets.items():
        available = regime_dates.get(regime, [])
        # 1.5x oversampling — not all dates produce qualifying setups
        sample_size = min(int(target * 1.5), len(available))
        if sample_size == 0:
            logger.warning("[REGIME] No dates available for regime '%s'", regime)
            sampled[regime] = []
            continue

        random.shuffle(available)
        sampled[regime] = available[:sample_size]
        logger.info("[REGIME] Sampled %d/%d dates for '%s' (target: %d)",
                    sample_size, len(available), regime, target)

    return sampled


def format_macro_summary(
    fred_data: dict,
    scan_date: str,
) -> str:
    """Format FRED values into natural language macro context.

    Uses point-in-time lookups to produce a macro summary paragraph
    suitable for embedding in prompt files.

    Args:
        fred_data: Output of fetch_fred_history().
        scan_date: ISO date string for point-in-time lookup.

    Returns:
        Human-readable macro context string.
    """
    from src.training.historical_data import get_fred_value_as_of

    vix = get_fred_value_as_of(fred_data, "VIXCLS", scan_date)
    spread = get_fred_value_as_of(fred_data, "T10Y2Y", scan_date)
    unemployment = get_fred_value_as_of(fred_data, "UNRATE", scan_date)
    fed_funds = get_fred_value_as_of(fred_data, "FEDFUNDS", scan_date)

    parts = []
    if vix is not None:
        label = "elevated" if vix > 25 else "moderate" if vix > 18 else "low"
        parts.append(f"VIX at {vix:.1f} ({label} volatility)")
    if spread is not None:
        if spread < 0:
            parts.append(f"yield curve inverted ({spread:+.2f}% 10Y-2Y spread)")
        else:
            parts.append(f"yield curve positive ({spread:+.2f}% 10Y-2Y spread)")
    if fed_funds is not None:
        parts.append(f"Fed Funds rate at {fed_funds:.2f}%")
    if unemployment is not None:
        parts.append(f"unemployment at {unemployment:.1f}%")

    if not parts:
        return "Macro data not available for this date"

    return ". ".join(parts) + "."


# ── Helpers moved from backfill.py ─────────────────────────────────────


def deduplicate_candidates(candidates: list[dict], min_gap_days: int = 5) -> list[dict]:
    """Remove consecutive-day entries for the same ticker.

    If the same ticker qualifies on consecutive days, keep only the first
    occurrence. Require at least min_gap_days trading days between entries
    for the same ticker.
    """
    last_seen: dict[str, str] = {}  # ticker -> last scan_date
    result = []

    # Sort by scan_date, then score descending
    candidates.sort(key=lambda x: (x["scan_date"], -x["score"]))

    for c in candidates:
        ticker = c["ticker"]
        scan_date = c["scan_date"]

        if ticker in last_seen:
            last_date = pd.Timestamp(last_seen[ticker])
            current_date = pd.Timestamp(scan_date)
            gap = (current_date - last_date).days
            if gap < min_gap_days:
                continue

        last_seen[ticker] = scan_date
        result.append(c)

    return result


def balance_dataset(
    examples: list[dict], target_win_ratio: float = 0.6
) -> list[dict]:
    """Balance win/loss ratio by downsampling the majority class.

    Aims for roughly 60/40 win/loss. Losing trades are more instructionally
    valuable and should be proportionally overrepresented vs natural frequency.
    """
    wins = [e for e in examples if e["outcome"]["outcome_quality"] == "clean_win"]
    losses = [e for e in examples if e["outcome"]["outcome_quality"] == "clean_loss"]
    other = [e for e in examples if e["outcome"]["outcome_quality"] not in ("clean_win", "clean_loss")]

    if not losses:
        return examples

    # Target: wins should be target_win_ratio of (wins + losses)
    target_wins = int(len(losses) * target_win_ratio / (1 - target_win_ratio))

    if len(wins) > target_wins:
        random.shuffle(wins)
        wins = wins[:target_wins]

    return wins + losses + other


def cap_and_diversify(
    examples: list[dict],
    max_examples: int,
    max_per_ticker: int = 30,
) -> list[dict]:
    """Cap total examples and ensure diversity.

    Prioritize:
    - Higher scores first
    - Diverse tickers (no more than max_per_ticker per ticker)
    - Even distribution across the time period
    """
    # First cap per-ticker
    ticker_counts: Counter = Counter()
    ticker_capped = []
    # Sort by score descending
    examples.sort(key=lambda x: -x["candidate"]["score"])

    for ex in examples:
        ticker = ex["candidate"]["ticker"]
        if ticker_counts[ticker] >= max_per_ticker:
            continue
        ticker_counts[ticker] += 1
        ticker_capped.append(ex)

    if len(ticker_capped) <= max_examples:
        return ticker_capped

    # Distribute evenly across time periods (months)
    by_month: defaultdict[str, list] = defaultdict(list)
    for ex in ticker_capped:
        month_key = ex["candidate"]["scan_date"][:7]  # YYYY-MM
        by_month[month_key].append(ex)

    months = sorted(by_month.keys())
    per_month = max(1, max_examples // len(months))
    result = []

    for month in months:
        month_examples = by_month[month]
        month_examples.sort(key=lambda x: -x["candidate"]["score"])
        result.extend(month_examples[:per_month])

    # If still under cap, fill from remaining
    if len(result) < max_examples:
        used = {(e["candidate"]["ticker"], e["candidate"]["scan_date"]) for e in result}
        remaining = [e for e in ticker_capped
                     if (e["candidate"]["ticker"], e["candidate"]["scan_date"]) not in used]
        remaining.sort(key=lambda x: -x["candidate"]["score"])
        result.extend(remaining[:max_examples - len(result)])

    return result[:max_examples]
