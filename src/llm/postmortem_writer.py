"""LLM-enhanced postmortem writer with template fallback."""

import logging

from src.llm.client import is_llm_available, generate
from src.llm.prompts import POSTMORTEM_SYSTEM_PROMPT
from src.config import load_config

logger = logging.getLogger(__name__)


def enhance_postmortem_with_llm(trade: dict, rule_based_postmortem: str) -> str:
    """Enhance a postmortem with LLM-written analysis.

    If LLM is disabled or unavailable, returns the rule_based_postmortem unchanged.

    Args:
        trade: Dict with trade data (entry, exit, PnL, MFE/MAE, etc.).
        rule_based_postmortem: The template-based postmortem text.

    Returns:
        LLM-enhanced postmortem string, or the original rule-based one.
    """
    config = load_config()
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False):
        return rule_based_postmortem

    if not is_llm_available():
        logger.warning("[LLM] Ollama not reachable — fallback to rule-based postmortem")
        return rule_based_postmortem

    prompt = f"""Ticker: {trade.get('ticker', 'N/A')}
Entry: ${trade.get('entry_price', 0):.2f} on {trade.get('entry_date', 'N/A')}
Exit: ${trade.get('exit_price', 0):.2f} on {trade.get('exit_date', 'N/A')}
Exit Reason: {trade.get('exit_reason', 'N/A')}
P&L: ${trade.get('pnl', 0):.2f} ({trade.get('pnl_pct', 0):.1f}%)
Duration: {trade.get('duration_days', 0)} days
MFE: ${trade.get('mfe', 0):.2f} | MAE: ${trade.get('mae', 0):.2f}
Stop: ${trade.get('stop_price', 0):.2f} | Target 1: ${trade.get('target_1', 0):.2f} | Target 2: ${trade.get('target_2', 0):.2f}
ATR at entry: ${trade.get('atr_at_entry', 0):.2f}
Original thesis: {trade.get('thesis_text', 'N/A')}"""

    response = generate(prompt, POSTMORTEM_SYSTEM_PROMPT)

    if response:
        logger.info("[LLM] Enhanced postmortem for %s", trade.get('ticker', 'N/A'))
        logger.info("  [LLM] Enhanced postmortem for %s", trade.get('ticker', 'N/A'))
        return response

    logger.warning("[LLM] Postmortem generation failed — fallback to rule-based")
    return rule_based_postmortem
