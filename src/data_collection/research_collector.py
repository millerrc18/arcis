"""Research intelligence collector -- discovers and scores papers/posts nightly.

Called by: scheduler/watch.py
Calls: data_collection/research_sources.py, llm/client.py
Owns tables: none (writes to research_papers)
Config keys: none
Tests: none

Table: research_papers
Schedule: Nightly in overnight pipeline (collector #13)

Sources: arXiv, SSRN, HuggingFace daily papers, Reddit, GitHub trending,
         Anthropic/OpenAI blogs.

Relevance scoring: First attempts Ollama (zero API cost), falls back to
keyword-based scoring if Ollama is unavailable (e.g., during training when
VRAM is handed off to PyTorch). Papers scoring >= 0.4 are stored; lower
scores are discarded as irrelevant. Stored papers are reviewed in the
weekly synthesis digest (research_synthesizer.py, Sundays 6 PM).

Deduplication is by external_id (e.g., "arxiv:2401.12345"). The 0.5s
sleep between Ollama calls prevents saturating inference during overnight
data collection when other collectors are also running.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.data_collection.result import CollectorResult
from src.utils.db import connect_db, engine_aware_upsert
from src.data_collection.research_sources import (
    RELEVANCE_KEYWORDS,
    crawl_ai_blogs,
    crawl_arxiv,
    crawl_github_trending,
    crawl_huggingface,
    crawl_reddit,
    crawl_ssrn,
)

logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")

RELEVANCE_PROMPT = """Rate how relevant this paper/post is to an AI-powered equity swing trading system that:
- Fine-tunes Qwen3 8B via QLoRA for trade commentary generation
- Uses pullback-in-uptrend strategy on S&P 100 stocks (2-15 day holds)
- Has a self-blinding training pipeline with DPO preference optimization
- Monitors market regimes and adapts position sizing
- Is building toward walk-forward validated, statistically proven edge

Score 0.0 to 1.0 where:
0.0 = completely irrelevant
0.3 = tangentially related (general ML or general finance)
0.6 = moderately relevant (touches one of our focus areas)
0.8 = highly relevant (directly applicable technique or finding)
1.0 = critical (must-read, directly impacts our architecture)

Respond with ONLY a JSON object: {{"score": 0.X, "reason": "one sentence why"}}

TITLE: {title}
ABSTRACT: {abstract}
"""
# ── Deduplication ────────────────────────────────────────────────────


def is_duplicate(external_id: str, db_path: str) -> bool:
    """Check if paper already exists in database."""
    try:
        with connect_db(db_path) as conn:
            return conn.execute(
                'SELECT 1 FROM research_papers WHERE external_id = ?', (external_id,)
            ).fetchone() is not None
    except Exception:
        return False


# ── Relevance Scoring ────────────────────────────────────────────────


def score_relevance(title: str, abstract: str) -> tuple[float, str]:
    """Score paper relevance using Ollama (zero API cost)."""
    try:
        from src.llm.client import generate
        prompt = RELEVANCE_PROMPT.format(title=title, abstract=(abstract or "")[:1000])
        response = generate(prompt, "You are a research relevance scorer. Respond only with JSON.", temperature=0.1)

        if response:
            # Try to parse JSON from response
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 0.3))
                reason = data.get("reason", "")
                return max(0.0, min(1.0, score)), reason
    except Exception as e:
        logger.debug("[RESEARCH] Relevance scoring failed: %s", e)

    # Default: keyword-based scoring
    logger.info("[RESEARCH] LLM relevance scoring unavailable, falling back to keyword scoring for: %s", title[:80])
    text = (title + " " + (abstract or "")).lower()
    hits = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text)
    default_score = min(0.9, 0.2 + hits * 0.1)
    return default_score, "keyword-based score (LLM unavailable)"


# ── Storage ──────────────────────────────────────────────────────────


def _store_paper(paper: dict, score: float, reason: str,
                 db_path: str) -> None:
    """Store a paper in the research_papers table."""
    now = datetime.now(TZ).isoformat()
    try:
        with connect_db(db_path) as conn:
            engine_aware_upsert(
                conn,
                "research_papers",
                {
                    "source": paper.get("source", ""),
                    "external_id": paper.get("external_id", ""),
                    "title": paper.get("title", ""),
                    "authors": paper.get("authors", ""),
                    "abstract": paper.get("abstract", ""),
                    "url": paper.get("url", ""),
                    "published_date": paper.get("published_date", ""),
                    "relevance_score": score,
                    "relevance_reason": reason,
                    "collected_at": now,
                },
                action="ignore",
            )
    except Exception as e:
        logger.warning("[RESEARCH] Failed to store paper: %s", e)


# ── Main Collector ───────────────────────────────────────────────────


def collect_research_papers(db_path: str = DB_PATH) -> CollectorResult:
    """Nightly research paper collection. Returns a CollectorResult.

    primary_count is papers stored (total_new); per-source new-paper counts and
    total_crawled go in metadata (all int counts).
    """
    results = {}
    all_papers = []

    from src.data_collection.research_sources import _SOURCE_CACHE

    for name, crawler in [
        ("arxiv", crawl_arxiv),
        ("ssrn", crawl_ssrn),
        ("huggingface", crawl_huggingface),
        ("reddit", crawl_reddit),
        ("github", crawl_github_trending),
        ("ai_blogs", crawl_ai_blogs),
    ]:
        try:
            papers = crawler()
            # #303: Cache successful results for graceful degradation
            _SOURCE_CACHE[name] = papers
            new_papers = [p for p in papers if not is_duplicate(p.get("external_id", ""), db_path)]
            all_papers.extend(new_papers)
            results[name] = len(new_papers)
            logger.info("[RESEARCH] %s: %d new papers", name, len(new_papers))
        except Exception as e:
            # #303: Serve stale data from cache on failure
            cached = _SOURCE_CACHE.get(name, [])
            if cached:
                logger.warning("[RESEARCH] %s crawl failed: %s — serving %d cached papers", name, e, len(cached))
                new_papers = [p for p in cached if not is_duplicate(p.get("external_id", ""), db_path)]
                all_papers.extend(new_papers)
                results[name] = len(new_papers)
            else:
                logger.warning("[RESEARCH] %s crawl failed: %s — no cache available", name, e)
                results[name] = 0

    # Score relevance and store
    stored = 0
    for paper in all_papers:
        score, reason = score_relevance(paper["title"], paper.get("abstract", ""))
        if score >= 0.4:
            _store_paper(paper, score, reason, db_path)
            stored += 1
        time.sleep(0.5)  # Rate limit Ollama calls

    logger.info("[RESEARCH] Collection complete: %d stored, %d crawled from %d sources",
                stored, len(all_papers), len(results))

    return CollectorResult.ok_from_count(
        "research_papers",
        stored,
        total_crawled=len(all_papers),
        **results,
    )
