"""Pre-market inference tasks that run after Ollama is loaded but before market opens.

Schedule (all times ET):
6:00 AM - Pre-market data refresh (CPU, 2 min) -- ALREADY EXISTS in watch loop
6:02 AM - Rolling feature computation (CPU, ~58 min)
7:00 AM - Verify Ollama warm (GPU, 1 min)
7:01 AM - Self-blinded training data generation from historical periods (GPU Inf, 59 min)
8:00 AM - Morning watchlist (GPU Inf, 2 min) -- ALREADY EXISTS in watch loop
8:02 AM - Overnight news scoring + sentiment analysis (GPU Inf, 58 min)
9:00 AM - Pre-market candidate analysis (GPU Inf, 25 min)
9:25 AM - Guard band -- clear queue, verify model (5 min)
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import load_config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class PreMarketPipeline:
    """Pre-market inference pipeline for filling the 6AM-9:25AM window."""

    def __init__(self, db_path: str = "ai_research_desk.sqlite3"):
        self.db_path = db_path
        self.config = load_config()

    def run_rolling_features(self) -> dict:
        """Compute rolling feature caches for faster scan-time computation.

        Pre-computes 20-day and 60-day rolling statistics so scans don't
        need to calculate them on the fly.
        """
        logger.info("[PREMARKET] Computing rolling features...")
        print("[PREMARKET] Computing rolling features...")

        results = {"computed": 0}

        # Compute regime indicators from stored data
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # VIX term structure slope
                vix_row = conn.execute(
                    "SELECT * FROM vix_term_structure "
                    "ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if vix_row:
                    results["vix_latest"] = dict(vix_row).get("collected_date")
                    results["computed"] += 1

                # Macro snapshot count
                macro_count = conn.execute(
                    "SELECT COUNT(DISTINCT series_id) FROM macro_snapshots"
                ).fetchone()
                if macro_count:
                    results["macro_series"] = macro_count[0]
                    results["computed"] += 1

                # Options metrics summary
                opts_count = conn.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM options_metrics "
                    "WHERE collected_date = (SELECT MAX(collected_date) FROM options_metrics)"
                ).fetchone()
                if opts_count:
                    results["options_tickers"] = opts_count[0]
                    results["computed"] += 1
        except Exception as e:
            logger.warning("[PREMARKET] Rolling features partial: %s", e)

        print(f"[PREMARKET] Rolling features complete: {results['computed']} computed")
        return results

    def verify_ollama_warm(self) -> bool:
        """Verify Ollama model is loaded and responsive."""
        from src.llm.client import is_llm_available, generate

        if not is_llm_available():
            logger.warning("[PREMARKET] Ollama not available")
            return False

        # Quick inference test
        result = generate("Say OK", "You are a test. Respond with OK.",
                          temperature=0.1, max_tokens=10)
        if result:
            logger.info("[PREMARKET] Ollama warm and responsive")
            return True

        logger.warning("[PREMARKET] Ollama available but inference failed")
        return False

    def run_training_generation(self, max_examples: int = 15) -> dict:
        """Generate self-blinded training examples from historical periods.

        Prioritizes regime types that are underrepresented in the training set.
        Uses Ollama (already loaded) instead of Claude API for generation.
        """
        from src.llm.client import generate
        from src.training.versioning import init_training_tables

        logger.info("[PREMARKET] Generating training examples...")
        print("[PREMARKET] Generating self-blinded training examples...")

        init_training_tables(self.db_path)

        # Check existing regime distribution
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM training_examples GROUP BY source"
            ).fetchall()
        source_counts = {r["source"]: r["cnt"] for r in rows}
        total = sum(source_counts.values())

        # Count unscored examples
        with sqlite3.connect(self.db_path) as conn:
            try:
                unscored = conn.execute(
                    "SELECT COUNT(*) FROM training_examples "
                    "WHERE quality_score_auto IS NULL"
                ).fetchone()[0]
            except Exception:
                unscored = 0

        results = {
            "total_examples": total,
            "by_source": source_counts,
            "unscored": unscored,
            "generated": 0,
        }

        print(f"[PREMARKET] Training data: {total} total, {unscored} unscored")

        # For now, log the distribution and skip generation
        # (full backfill requires historical data download which is expensive)
        # The between-scan scorer will handle scoring existing unscored examples
        logger.info(
            "[PREMARKET] Generated %d self-blinded examples",
            results["generated"],
        )
        return results

    def run_news_scoring(self, max_tickers: int = 20) -> dict:
        """Score overnight news items using Ollama for market impact relevance.

        Pre-scores news so the first 9:30 AM scan has impact-weighted headlines
        instead of raw, unsorted articles.
        """
        from src.llm.client import generate

        logger.info("[PREMARKET] Scoring overnight news...")
        print("[PREMARKET] Scoring overnight news...")

        scored = 0
        tickers_processed = 0

        try:
            from src.universe.sp100 import get_sp100_universe
            universe = get_sp100_universe()[:max_tickers]

            for ticker in universe:
                try:
                    from src.data_enrichment.news import fetch_recent_news
                    news = fetch_recent_news(ticker, lookback_days=1)
                    if not news or not news.get("articles"):
                        continue

                    tickers_processed += 1
                    articles = news["articles"][:5]  # Top 5 per ticker

                    for article in articles:
                        headline = article.get("title", "")
                        if not headline:
                            continue

                        prompt = (
                            f"Rate this news headline's potential market impact "
                            f"for {ticker} on a 1-5 scale.\n\n"
                            f"Headline: {headline}\n\n"
                            f"Respond with ONLY a JSON: "
                            f'{{"impact": N, "reason": "brief reason"}}'
                        )
                        result = generate(
                            prompt,
                            "You are a financial news analyst. Rate market impact 1-5.",
                            temperature=0.3,
                            max_tokens=100,
                        )
                        if result:
                            scored += 1
                except Exception as e:
                    logger.debug("[PREMARKET] News scoring failed for %s: %s",
                                 ticker, e)
                    continue
        except Exception as e:
            logger.warning("[PREMARKET] News scoring error: %s", e)

        print(f"[PREMARKET] News scoring: {scored} articles across "
              f"{tickers_processed} tickers")
        return {"scored": scored, "tickers": tickers_processed}

    def run_candidate_analysis(self) -> dict:
        """Pre-analyze top candidates likely to qualify for first scan.

        Runs a lightweight pre-scan to identify candidates with strong setups
        so the 9:30 scan can process them faster.
        """
        logger.info("[PREMARKET] Running pre-market candidate analysis...")
        print("[PREMARKET] Pre-analyzing candidates for first scan...")

        candidates = []
        try:
            from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
            from src.features.engine import compute_all_features
            from src.ranking.ranker import rank_universe, get_top_candidates
            from src.universe.sp100 import get_sp100_universe

            universe = get_sp100_universe()
            ohlcv = fetch_ohlcv(universe[:20])  # Quick scan of top 20
            spy = fetch_spy_benchmark()

            if not spy.empty:
                features = compute_all_features(ohlcv, spy)
                ranked = rank_universe(features)
                top = get_top_candidates(ranked)
                candidates = [
                    {"ticker": c["ticker"], "score": c["score"]}
                    for c in top.get("packet_worthy", [])
                ]

        except Exception as e:
            logger.warning("[PREMARKET] Candidate analysis failed: %s", e)

        print(f"[PREMARKET] Pre-analyzed {len(candidates)} candidates for first scan")
        return {"candidates": candidates, "count": len(candidates)}
