"""Weekly research intelligence synthesis via Claude API.

Called by: scheduler/watch.py
Calls: notifications/telegram.py
Owns tables: none
Config keys: none
Tests: none

Runs Sunday 6 PM ET. Reads high-relevance papers from the past week,
sends to Claude Sonnet for structured analysis, stores digest.
Cost: ~$0.50/week.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

SYNTHESIS_PROMPT = """You are the research intelligence analyst for Halcyon Lab, an AI-powered autonomous equity trading system.

SYSTEM CONTEXT:
- Qwen3 8B fine-tuned via QLoRA, 978 training examples growing to 10K
- Pullback-in-uptrend strategy on S&P 100, expanding to breakout
- Self-blinding training pipeline with DPO preference optimization
- Walk-forward validation framework, targeting 50-trade gate then 200-trade milestone
- Wyoming LLC formation planned for Phase 2 (mid-2026)
- Solo operator, RTX 3060 12GB, ~$150/mo infrastructure budget

THIS WEEK'S PAPERS ({count} papers, relevance >= 0.6):
{papers_block}

Produce a structured digest with exactly 4 sections. For each finding, reference the specific paper by title. Be concrete — "consider changing X to Y" not "this could be useful."

<actionable>
[Findings that suggest specific changes to Halcyon's architecture, training pipeline, strategy, or infrastructure. Include paper title, what it found, and the specific change to consider.]
</actionable>

<threats>
[Competitive developments, open-source releases, or market structure changes that could erode Halcyon's moat. Include what to monitor.]
</threats>

<techniques>
[New methods, hyperparameters, or architectures relevant to our stack. Include paper title and how it applies.]
</techniques>

<regulatory>
[SEC, FINRA, or exchange rule changes affecting algorithmic or AI-assisted trading. Include what action is needed and by when.]
</regulatory>

If a section has no relevant items this week, say "Nothing notable this week."
"""


def run_weekly_synthesis(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Run weekly research synthesis. Returns digest metadata."""
    now = datetime.now(ET)
    week_end = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # Get high-relevance papers from this week
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT title, authors, abstract, url, source, relevance_score, relevance_reason "
                "FROM research_papers WHERE relevance_score >= 0.6 "
                "AND collected_at >= ? ORDER BY relevance_score DESC",
                (week_start,),
            ).fetchall()
    except Exception as e:
        logger.error("[SYNTHESIS] Failed to query papers: %s", e)
        return {"error": str(e)}

    papers = [dict(r) for r in rows]
    if not papers:
        logger.info("[SYNTHESIS] No high-relevance papers this week, skipping synthesis")
        return {"papers_reviewed": 0, "skipped": True}

    # Build papers block
    papers_block = ""
    for i, p in enumerate(papers[:30], 1):  # Cap at 30 to control token cost
        papers_block += (
            f"\n---\nPaper {i}: {p['title']}\n"
            f"Source: {p['source']} | Score: {p['relevance_score']:.2f}\n"
            f"Reason: {p.get('relevance_reason', 'N/A')}\n"
            f"Abstract: {(p.get('abstract') or 'N/A')[:500]}\n"
        )

    prompt = SYNTHESIS_PROMPT.format(count=len(papers), papers_block=papers_block)

    # Call Claude API for synthesis
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        digest_text = response.content[0].text
    except ImportError:
        logger.warning("[SYNTHESIS] anthropic package not installed, skipping synthesis")
        return {"papers_reviewed": len(papers), "error": "anthropic not installed"}
    except Exception as e:
        logger.error("[SYNTHESIS] Claude API call failed: %s", e)
        return {"papers_reviewed": len(papers), "error": str(e)}

    # Count actionable items
    import re
    actionable_section = re.search(r'<actionable>(.*?)</actionable>', digest_text, re.DOTALL)
    actionable_count = 0
    if actionable_section:
        text = actionable_section.group(1)
        if "nothing notable" not in text.lower():
            actionable_count = max(1, len(re.findall(r'(?:^|\n)\s*[-•*]\s', text)))

    # Extract threats
    threats_section = re.search(r'<threats>(.*?)</threats>', digest_text, re.DOTALL)
    threats_json = json.dumps(threats_section.group(1).strip() if threats_section else "")

    # Extract opportunities/techniques
    techniques_section = re.search(r'<techniques>(.*?)</techniques>', digest_text, re.DOTALL)
    opportunities_json = json.dumps(techniques_section.group(1).strip() if techniques_section else "")

    # Store digest
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO research_digests
                   (week_start, week_end, papers_reviewed, actionable_count,
                    digest_text, threats, opportunities, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (week_start, week_end, len(papers), actionable_count,
                 digest_text, threats_json, opportunities_json, now.isoformat()),
            )
    except Exception as e:
        logger.error("[SYNTHESIS] Failed to store digest: %s", e)

    # Send Telegram notification
    try:
        from src.notifications.telegram import send_telegram
        summary = digest_text[:800] if len(digest_text) > 800 else digest_text
        msg = (
            f"📚 <b>WEEKLY RESEARCH DIGEST</b>\n\n"
            f"Papers reviewed: {len(papers)}\n"
            f"Actionable findings: {actionable_count}\n\n"
            f"{summary}"
        )
        send_telegram(msg)
    except Exception:
        pass

    logger.info("[SYNTHESIS] Digest complete: %d papers reviewed, %d actionable",
                len(papers), actionable_count)

    return {
        "papers_reviewed": len(papers),
        "actionable_count": actionable_count,
        "week_start": week_start,
        "week_end": week_end,
    }
