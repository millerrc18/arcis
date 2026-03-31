"""Shadow trading ledger — re-exports from executor for backwards compatibility.

Called by: none
Calls: shadow_trading.executor
Owns tables: none
Config keys: none
Tests: none
"""

from src.shadow_trading.executor import open_shadow_trade, check_and_manage_open_trades

__all__ = ["open_shadow_trade", "check_and_manage_open_trades"]
