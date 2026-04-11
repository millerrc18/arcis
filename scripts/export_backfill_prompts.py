"""Export regime-targeted prompt files for manual backfill generation.

Usage:
    python scripts/export_backfill_prompts.py
    python scripts/export_backfill_prompts.py --lookback-years 5 --max-per-regime 180 --pass-count 130
    python scripts/export_backfill_prompts.py --output-dir training_data/prompts

This is the core deliverable of the manual backfill sprint. It:
1. Downloads historical data via fetch_historical_universe(lookback_years=5)
2. Fetches FRED history via fetch_fred_history()
3. Classifies all dates by regime via classify_dates_by_regime()
4. Samples dates to hit regime targets via sample_regime_balanced_dates()
5. Scans each date for qualifying setups (score >= 70 for TRADE, 45-69 for PASS)
6. Exports individual prompt files to training_data/prompts/{regime}/
7. Exports sealed outcomes to training_data/outcomes/outcomes.json
8. Generates training_data/progress.json
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.training.historical_data import fetch_fred_history, fetch_historical_universe
from src.training.historical_scanner import (
    compute_outcome,
    generate_backfill_example,
    scan_historical_date,
    scan_historical_date_pass,
)
from src.training.regime_sampler import (
    classify_dates_by_regime,
    format_macro_summary,
    sample_regime_balanced_dates,
)

DEFAULT_TARGETS = {
    "bull": 120,
    "bear": 80,
    "high_vol": 80,
    "range": 70,
    "recovery": 60,
}


def export_prompt_file(
    output_dir: str,
    regime: str,
    prompt_id: int,
    candidate: dict,
    example: dict,
    example_type: str,
) -> str:
    """Write a single prompt file for manual generation."""
    ticker = candidate["ticker"]
    scan_date = candidate["scan_date"]
    score = candidate["score"]

    regime_dir = os.path.join(output_dir, regime)
    os.makedirs(regime_dir, exist_ok=True)

    filename = f"{prompt_id:03d}_{ticker}_{scan_date}.md"
    filepath = os.path.join(regime_dir, filename)

    content = f"""# Setup {prompt_id:03d} | {ticker} | {scan_date} | Regime: {regime.upper()} | Score: {score:.0f} | Type: {example_type}

## System Prompt
{example['instruction']}

## Feature Data
{example['input_text']}

---
SAVE THE RESPONSE AS: results/{prompt_id:03d}_{ticker}_{scan_date}.md
"""
    with open(filepath, "w") as f:
        f.write(content)

    return filename


def main():
    parser = argparse.ArgumentParser(description="Export backfill prompts for manual generation")
    parser.add_argument("--lookback-years", type=int, default=5, help="Years of historical data (default: 5)")
    parser.add_argument("--max-per-regime", type=int, default=180, help="Max prompts per regime (default: 180)")
    parser.add_argument("--pass-count", type=int, default=130, help="Target PASS example count (default: 130)")
    parser.add_argument("--output-dir", type=str, default="training_data/prompts", help="Output directory")
    args = parser.parse_args()

    # Scale targets if max-per-regime differs from default
    scale = args.max_per_regime / 180.0
    targets = {k: int(v * scale) for k, v in DEFAULT_TARGETS.items()}

    logger.info("=== EXPORT BACKFILL PROMPTS ===")
    logger.info("Lookback: %d years | Max/regime: %d | PASS target: %d",
                args.lookback_years, args.max_per_regime, args.pass_count)
    logger.info("Regime targets: %s", targets)

    # Step 1: Download historical data
    logger.info("\n[1/8] Downloading historical data...")
    data = fetch_historical_universe(lookback_years=args.lookback_years)
    spy_df = data["spy"]
    logger.info("  Got %d tickers, %s to %s", len(data["tickers"]), data["start_date"], data["end_date"])

    # Step 2: Fetch FRED history
    logger.info("\n[2/8] Fetching FRED macro history...")
    fred_data = fetch_fred_history()
    logger.info("  Got %d FRED series", len(fred_data))

    # Step 3: Classify dates by regime
    logger.info("\n[3/8] Classifying trading days by regime...")
    regime_dates = classify_dates_by_regime(spy_df, data["tickers"])

    # Step 4: Sample dates
    logger.info("\n[4/8] Sampling regime-balanced dates...")
    sampled_dates = sample_regime_balanced_dates(regime_dates, targets)

    # Step 5-6: Scan dates and export prompts
    logger.info("\n[5/8] Scanning for qualifying setups and exporting prompts...")
    os.makedirs(args.output_dir, exist_ok=True)
    outcomes_dir = os.path.join(os.path.dirname(args.output_dir), "outcomes")
    os.makedirs(outcomes_dir, exist_ok=True)

    prompt_id = 1
    outcomes = {}
    progress = {}
    total_exported = 0

    for regime, dates in sampled_dates.items():
        regime_count = 0
        regime_target = targets.get(regime, 100)
        logger.info("\n  Scanning %s (%d dates, target %d)...", regime, len(dates), regime_target)

        for scan_date in dates:
            if regime_count >= args.max_per_regime:
                break

            candidates = scan_historical_date(data, scan_date, fred_data=fred_data)
            for candidate in candidates[:3]:  # Top 3 per date to avoid flood
                if regime_count >= args.max_per_regime:
                    break

                # Compute outcome for sealed file
                outcome = compute_outcome(
                    data, candidate["ticker"], candidate["scan_date"],
                    candidate["entry_price"], candidate["stop_price"],
                    candidate["target_1"], candidate["target_2"],
                )
                if outcome is None:
                    continue

                example = generate_backfill_example(candidate, outcome)
                filename = export_prompt_file(
                    args.output_dir, regime, prompt_id, candidate, example, "TRADE"
                )

                # Store outcome (sealed — keyed by prompt_id)
                outcomes[str(prompt_id)] = {
                    "prompt_id": prompt_id,
                    "ticker": candidate["ticker"],
                    "scan_date": candidate["scan_date"],
                    "regime": regime,
                    "type": "trade",
                    "outcome": outcome,
                }

                prompt_id += 1
                regime_count += 1
                total_exported += 1

        progress[regime] = {
            "target": regime_target,
            "exported": regime_count,
            "completed": 0,
            "imported": 0,
        }
        logger.info("  %s: exported %d prompts", regime, regime_count)

    # Step 7: Export PASS examples
    logger.info("\n[6/8] Scanning for PASS examples (score 45-69)...")
    pass_count = 0
    pass_regime = "pass"
    all_dates = []
    for dates in sampled_dates.values():
        all_dates.extend(dates)

    # Shuffle to spread PASS examples across regimes
    import random
    random.shuffle(all_dates)

    for scan_date in all_dates:
        if pass_count >= args.pass_count:
            break

        pass_candidates = scan_historical_date_pass(data, scan_date, fred_data=fred_data)
        for candidate in pass_candidates[:2]:  # Max 2 PASS per date
            if pass_count >= args.pass_count:
                break

            example = generate_backfill_example(candidate, outcome=None)
            filename = export_prompt_file(
                args.output_dir, pass_regime, prompt_id, candidate, example, "PASS"
            )

            outcomes[str(prompt_id)] = {
                "prompt_id": prompt_id,
                "ticker": candidate["ticker"],
                "scan_date": candidate["scan_date"],
                "regime": pass_regime,
                "type": "pass",
                "outcome": None,
            }

            prompt_id += 1
            pass_count += 1
            total_exported += 1

    progress[pass_regime] = {
        "target": 90,
        "exported": pass_count,
        "completed": 0,
        "imported": 0,
    }
    logger.info("  PASS: exported %d prompts", pass_count)

    # Step 8: Write outcomes and progress files
    logger.info("\n[7/8] Writing sealed outcomes file...")
    outcomes_path = os.path.join(outcomes_dir, "outcomes.json")
    with open(outcomes_path, "w") as f:
        json.dump(outcomes, f, indent=2)
    logger.info("  Wrote %d outcomes to %s", len(outcomes), outcomes_path)

    logger.info("\n[8/8] Writing progress tracker...")
    progress_path = os.path.join(os.path.dirname(args.output_dir), "progress.json")
    with open(progress_path, "w") as f:
        json.dump(progress, f, indent=2)
    logger.info("  Wrote progress to %s", progress_path)

    # Summary
    logger.info("\n=== EXPORT COMPLETE ===")
    logger.info("Total prompts exported: %d", total_exported)
    for regime, info in progress.items():
        logger.info("  %-12s %d/%d exported", regime, info["exported"], info["target"])
    logger.info("\nNext step: copy prompt files into Claude/ChatGPT, save responses to results/")


if __name__ == "__main__":
    main()
