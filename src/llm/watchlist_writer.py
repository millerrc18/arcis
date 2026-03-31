"""LLM-enhanced morning watchlist narrative writer.

Called by: scheduler.watch, services.watchlist_service
Calls: llm.client, llm.prompts
Owns tables: none
Config keys: enabled, llm
Tests: tests/test_llm_writers.py
"""

import logging

from src.llm.client import is_llm_available, generate
from src.llm.prompts import WATCHLIST_NARRATIVE_PROMPT

logger = logging.getLogger(__name__)


def generate_watchlist_narrative(packet_worthy: list[dict], watchlist: list[dict],
                                config: dict) -> str | None:
    """Generate an LLM-written narrative summary for the morning watchlist.

    Args:
        packet_worthy: List of packet-worthy candidate dicts.
        watchlist: List of watchlist candidate dicts.
        config: Application config dict.

    Returns:
        Narrative string, or None if LLM unavailable.
    """
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False):
        return None

    if not is_llm_available():
        logger.warning("[LLM] Ollama not reachable — skipping watchlist narrative")
        return None

    # Build the prompt
    pw_lines = []
    for c in packet_worthy:
        feat = c["features"]
        pw_lines.append(
            f"  {c['ticker']} — score={c['score']:.0f}, "
            f"trend={feat.get('trend_state', 'n/a')}, "
            f"RS={feat.get('relative_strength_state', 'n/a')}"
        )

    wl_lines = []
    for c in watchlist:
        feat = c["features"]
        wl_lines.append(
            f"  {c['ticker']} — score={c['score']:.0f}, "
            f"trend={feat.get('trend_state', 'n/a')}, "
            f"RS={feat.get('relative_strength_state', 'n/a')}"
        )

    prompt = f"""Today's scan results:
Packet-worthy ({len(packet_worthy)} names):
{chr(10).join(pw_lines) if pw_lines else '  None'}

Watchlist ({len(watchlist)} names):
{chr(10).join(wl_lines) if wl_lines else '  None'}"""

    response = generate(prompt, WATCHLIST_NARRATIVE_PROMPT)

    if response:
        logger.info("[LLM] Generated watchlist narrative")
        logger.info("  [LLM] Generated watchlist narrative")
    else:
        logger.warning("[LLM] Failed to generate watchlist narrative")

    return response
