# Purpose: TradingState subpackage — exports state() + TradingStateError.
# Called by: src/tools/tradingstate/__main__.py (Task 7), external callers
# Calls: src.tools.tradingstate.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_tradingstate_integration.py
#
# __main__.py and render.py are deferred to Task 7 per sub-module-when-needed pattern.

from src.tools.tradingstate.core import TradingStateError, state

__all__ = ["state", "TradingStateError"]
