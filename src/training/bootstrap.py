"""Synthetic training data bootstrapping via Claude API."""

import json
import logging
import random
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import load_config
from src.llm.prompts import TRAINING_EXAMPLE_PROMPT
from src.training.claude_client import generate_training_example
from src.training.ingestion_gate import (
    alert_training_halt,
    should_halt_batch,
    validate_training_example,
)
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def estimate_bootstrap_cost(n_examples: int) -> float:
    """Estimate cost in USD for generating N bootstrap examples.

    Haiku 4.5: $1/MTok input, $5/MTok output.
    ~500 input tokens + ~800 output tokens per example.
    """
    return n_examples * (500 * 1.0 / 1_000_000 + 800 * 5.0 / 1_000_000)


def generate_synthetic_training_data(
    n_examples: int,
    db_path: str = "ai_research_desk.sqlite3",
) -> int:
    """Generate synthetic training examples using real features and fake outcomes.

    Returns count of examples created.
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_features
    from src.universe.sp100 import get_sp100_universe

    config = load_config()
    init_training_tables(db_path)

    universe = get_sp100_universe()
    logger.info("[TRAINING] Fetching data for synthetic example generation...")

    # Fetch a batch of data once
    sample_tickers = random.sample(universe, min(n_examples, len(universe)))
    ohlcv_data = fetch_ohlcv(sample_tickers)
    spy = fetch_spy_benchmark()

    if spy.empty:
        logger.warning("[TRAINING] Could not fetch SPY benchmark.")
        return 0

    count = 0
    attempted = 0
    rejected = 0
    rejection_reasons: Counter[str] = Counter()
    for i in range(n_examples):
        ticker = random.choice(list(ohlcv_data.keys()))
        ohlcv = ohlcv_data.get(ticker)
        if ohlcv is None or len(ohlcv) < 200:
            continue

        try:
            features = compute_features(ticker, ohlcv, spy)
        except Exception:
            continue

        atr = features.get("atr_14", 1.0)
        price = features.get("current_price", 100.0)

        # Random outcome: win 60%, loss 30%, timeout 10%
        outcome_roll = random.random()
        if outcome_roll < 0.60:
            pnl_pct = random.uniform(1.0, 5.0)
            pnl_dollars = price * pnl_pct / 100
            mfe = pnl_dollars * random.uniform(1.0, 1.5)
            mae = atr * random.uniform(0.1, 0.5)
            exit_reason = "target_1_hit"
        elif outcome_roll < 0.90:
            pnl_pct = random.uniform(-3.0, -1.0)
            pnl_dollars = price * pnl_pct / 100
            mae = abs(pnl_dollars) * random.uniform(1.0, 1.3)
            mfe = atr * random.uniform(0.1, 0.4)
            exit_reason = "stop_hit"
        else:
            pnl_pct = random.uniform(-1.0, 1.0)
            pnl_dollars = price * pnl_pct / 100
            mfe = atr * random.uniform(0.2, 0.8)
            mae = atr * random.uniform(0.2, 0.8)
            exit_reason = "timeout"

        duration = random.randint(2, 15)

        feature_text = f"""Ticker: {ticker}
Current Price: ${price:.2f}
Trend State: {features.get('trend_state', 'n/a')}
Relative Strength: {features.get('relative_strength_state', 'n/a')}
Pullback Depth: {features.get('pullback_depth_pct', 0):.1f}% from 50-day high
ATR(14): ${atr:.2f} ({features.get('atr_pct', 0):.1f}% of price)
Volume Ratio: {features.get('volume_ratio_20d', 0):.2f}x 20-day average
Distance to SMA20: {features.get('dist_to_sma20_pct', 0):.1f}%"""

        outcome_text = f"""
=== ACTUAL OUTCOME ===
Exit Reason: {exit_reason}
P&L: ${pnl_dollars:.2f} ({pnl_pct:.1f}%)
Duration: {duration} days
MFE: ${mfe:.2f} | MAE: ${mae:.2f}"""

        full_prompt = feature_text + "\n" + outcome_text

        response = generate_training_example(TRAINING_EXAMPLE_PROMPT, full_prompt, purpose="bootstrap")
        if response is None:
            logger.warning("[TRAINING] Failed to generate synthetic for %s, skipping", ticker)
            continue
        attempted += 1

        is_valid, rejection_reason = validate_training_example(response, db_path)
        if not is_valid:
            rejected += 1
            rejection_reasons[rejection_reason] += 1
            logger.warning("[TRAINING] Rejected synthetic example for %s: %s", ticker, rejection_reason)
            halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
            if halt:
                alert_training_halt(compliance, rejected, attempted, top_reason)
                logger.error("[TRAINING] Halting bootstrap batch at %.1f%% compliance", compliance)
                break
            continue

        example_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO training_examples
                   (example_id, created_at, source, ticker, recommendation_id,
                    feature_snapshot, trade_outcome, instruction, input_text, output_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (example_id, created_at, "synthetic_claude", ticker, None,
                 feature_text, outcome_text, TRAINING_EXAMPLE_PROMPT,
                 full_prompt, response),
            )
            conn.commit()

        count += 1

        if count % 10 == 0:
            cost = estimate_bootstrap_cost(count)
            logger.info("  [TRAINING] Bootstrap progress: %d/%d (est. cost: $%.2f)", count, n_examples, cost)

        halt, compliance, top_reason = should_halt_batch(attempted, rejected, rejection_reasons)
        if halt:
            alert_training_halt(compliance, rejected, attempted, top_reason)
            logger.error("[TRAINING] Halting bootstrap batch at %.1f%% compliance", compliance)
            break

    return count
