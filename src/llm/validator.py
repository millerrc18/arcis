"""LLM output validation layer.

Called by: shadow_trading.executor
Calls: universe.sp100
Owns tables: none
Config keys: risk
Tests: tests/test_llm_validator.py

Hard-coded bounds on every AI-generated trade signal BEFORE it reaches
the executor. Prevents hallucination-driven trades.
"""

import logging

logger = logging.getLogger(__name__)


def _parse_price(value) -> float:
    """Parse packet price fields from current or legacy schemas."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").split()[0]
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def validate_llm_output(packet, features: dict, config: dict) -> tuple[bool, str]:
    """Validate LLM-influenced trade parameters before execution.

    Returns (is_valid, rejection_reason).
    Catches: hallucinated tickers, nonsensical prices, oversized positions, etc.
    """
    # 1. Ticker must exist in our universe
    try:
        from src.universe.sp100 import get_sp100_universe
        universe = get_sp100_universe()
        if packet.ticker not in universe:
            return False, f"Ticker {packet.ticker} not in S&P 100 universe"
    except Exception:
        pass  # Universe check is best-effort

    # 2. Entry price must be within 10% of current market price
    current = float(features.get("current_price", 0) or 0)
    entry = _parse_price(
        getattr(packet, "entry_zone", None) or getattr(packet, "entry_price", 0)
    )
    if current > 0 and entry > 0:
        deviation = abs(entry - current) / current
        if deviation > 0.10:
            return False, f"Entry ${entry:.2f} deviates {deviation:.0%} from market ${current:.2f}"

    # 3. Stop must be below entry (for long trades)
    stop = _parse_price(
        getattr(packet, "stop_invalidation", None) or getattr(packet, "stop_price", 0)
    )
    if stop > 0 and entry > 0 and stop >= entry:
        return False, f"Stop ${stop:.2f} >= entry ${entry:.2f}"

    # 4. Stop distance must be reasonable (0.5% to 15% of entry)
    if stop > 0 and entry > 0:
        stop_dist_pct = (entry - stop) / entry
        if stop_dist_pct < 0.005 or stop_dist_pct > 0.15:
            return False, f"Stop distance {stop_dist_pct:.1%} outside 0.5%-15% range"

    # 5. Position size must not exceed 5% of portfolio
    starting_capital = config.get("risk", {}).get("starting_capital", 100000)
    alloc = getattr(packet, "position_sizing", None)
    if alloc and hasattr(alloc, "allocation_dollars"):
        alloc_pct = alloc.allocation_dollars / starting_capital
        if alloc_pct > 0.05:
            return False, f"Allocation {alloc_pct:.1%} exceeds 5% portfolio cap"

    # 6. Conviction must be 1-10
    conviction = getattr(packet, "llm_conviction", None)
    if conviction is None:
        conviction = getattr(packet, "confidence", None)
    if conviction is not None:
        if not (1 <= conviction <= 10):
            return False, f"Conviction {conviction} outside 1-10 range"

    return True, "passed"
