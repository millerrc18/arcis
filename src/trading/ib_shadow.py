"""IB Shadow Logger — logs what IB would have done for each Alpaca trade.

Called by: shadow_trading.executor (post-trade hook)
Calls: trading.ib_broker, schema.registry
Owns tables: ib_shadow_log
Config keys: live_trading.ib.shadow_mode
Tests: tests/test_ib_shadow.py

Shadow mode connects to IB Gateway and validates each trade's parameters
(contract, buying power, order structure) without submitting orders.
If Gateway is down, logs ib_connected=0 and continues.

CRITICAL: This module must NEVER:
  - Call placeOrder() on the IB client
  - Block Alpaca execution in any code path
  - Raise exceptions that propagate to the executor
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class IBShadowLogger:
    """Non-blocking shadow logger for IB trade comparison."""

    def __init__(self, config: dict):
        self._config = config
        self._broker = None

    def _get_broker(self):
        """Lazy init IB broker for shadow validation."""
        if self._broker is None:
            try:
                from src.trading.ib_broker import IBBroker
                ib_cfg = self._config.get("live_trading", {}).get("ib", {})
                self._broker = IBBroker(
                    host=ib_cfg.get("host", "127.0.0.1"),
                    port=ib_cfg.get("port", 4002),
                    client_id=ib_cfg.get("client_id", 1) + 10,  # Offset to avoid conflicts
                    timeout=ib_cfg.get("timeout", 5),
                )
            except Exception as e:
                logger.debug("[IB-SHADOW] Failed to create IBBroker: %s", e)
        return self._broker

    def log_shadow_trade(
        self,
        trade_id: str,
        ticker: str,
        quantity: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
        alpaca_order_id: str = "",
        alpaca_fill_price: float = 0.0,
        db_path: str = DB_PATH,
    ) -> None:
        """Log what IB would have done for this trade.

        Steps:
        1. Connect to IB Gateway (or log failure)
        2. Validate contract (qualifyContracts)
        3. Check buying power
        4. Construct bracket order params (without submitting)
        5. Store everything in ib_shadow_log
        """
        shadow_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()
        ib_connected = 0
        ib_contract_valid = 0
        ib_buying_power = None
        ib_would_accept = 0
        ib_order_params = None
        ib_error = None

        try:
            broker = self._get_broker()
            if broker is None:
                ib_error = "IBBroker creation failed"
            else:
                # Step 1: Check connection
                try:
                    broker._ensure_connected()
                    ib_connected = 1
                except Exception as e:
                    ib_error = f"Connection failed: {e}"

                if ib_connected:
                    # Step 2: Validate contract
                    try:
                        contract = broker._make_contract(ticker)
                        broker._ib.qualifyContracts(contract)
                        ib_contract_valid = 1
                    except Exception as e:
                        ib_error = f"Contract invalid: {e}"

                    # Step 3: Check buying power
                    try:
                        acct = broker.get_account()
                        ib_buying_power = acct.buying_power
                        required = entry_price * quantity
                        ib_would_accept = 1 if ib_buying_power >= required else 0
                    except Exception as e:
                        ib_error = (ib_error or "") + f" | Account check failed: {e}"

                    # Step 4: Construct order params (DO NOT SUBMIT)
                    ib_order_params = json.dumps({
                        "action": "BUY",
                        "quantity": quantity,
                        "take_profit": round(target_price, 2),
                        "stop_loss": round(stop_price, 2),
                        "order_type": "MKT",
                        "tif": "GTC",
                    })

        except Exception as e:
            ib_error = f"Shadow logging error: {e}"
            logger.warning("[IB-SHADOW] Unexpected error: %s", e)

        # Step 5: Store to database (always, even on failure)
        try:
            with connect_db(db_path) as conn:
                conn.execute(
                    """INSERT INTO ib_shadow_log
                       (shadow_id, created_at, trade_id, ticker, action, quantity,
                        entry_price, stop_price, target_price, ib_connected,
                        ib_contract_valid, ib_buying_power, ib_would_accept,
                        ib_order_params, ib_error, alpaca_order_id, alpaca_fill_price)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shadow_id, created_at, trade_id, ticker, "BUY", quantity,
                     entry_price, stop_price, target_price, ib_connected,
                     ib_contract_valid, ib_buying_power, ib_would_accept,
                     ib_order_params, ib_error, alpaca_order_id, alpaca_fill_price),
                )
                conn.commit()
            logger.info("[IB-SHADOW] Logged shadow trade for %s: connected=%d, valid=%d, accept=%d",
                        ticker, ib_connected, ib_contract_valid, ib_would_accept)
        except Exception as e:
            logger.warning("[IB-SHADOW] Failed to write shadow log: %s", e)
