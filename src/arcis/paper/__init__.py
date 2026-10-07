"""Step P paper trading lane: three-account execution experiment.

Three Alpaca paper accounts run the frozen incumbent's signals with
identical selection but different execution:
- A: prereg baseline (D-020: limit = signal close, open+buffer fills)
- B: market-on-open entries
- C: 2x adverse buffer (calibration)

For slippage-buffer calibration + D-020 validation, NOT edge discovery.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PaperConfig:
    """Alpaca paper account configuration."""

    name: str  # "A", "B", or "C"
    api_key: str
    api_secret: str
    base_url: str = "https://paper-api.alpaca.markets"


@dataclass(frozen=True)
class Signal:
    """One trading signal from the frozen incumbent."""

    symbol: str
    signal_date: date
    limit: float  # D-029 default: signal-day close
    stop: float
    target: float
    shares: int


@dataclass
class FillRecord:
    """Recorded fill for calibration analysis."""

    symbol: str
    signal_date: str
    account: str
    order_id: str
    fill_price: float
    fill_qty: int
    fill_time: str
    signal_price: float  # limit price from the signal
    slippage_bp: float  # (fill - signal) / signal * 10000


class AlpacaPaper:
    """Minimal Alpaca paper trading client (REST)."""

    def __init__(self, config: PaperConfig):
        self.config = config

    def _request(self, method: str, path: str,
                 body: dict[str, Any] | None = None) -> Any:
        url = self.config.base_url + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("APCA-API-KEY-ID", self.config.api_key)
        req.add_header("APCA-API-SECRET-KEY", self.config.api_secret)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def get_account(self) -> dict[str, Any]:
        """Get account info (equity, buying power, etc.)."""
        return self._request("GET", "/v2/account")

    def place_order(self, symbol: str, qty: int, side: str = "buy",
                    order_type: str = "limit", limit_price: float | None = None,
                    time_in_force: str = "day") -> dict[str, Any]:
        """Place an order. Returns the order object."""
        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price is not None:
            body["limit_price"] = limit_price
        return self._request("POST", "/v2/orders", body)

    def get_orders(self, status: str = "all",
                   limit: int = 100) -> list[dict[str, Any]]:
        """Get orders."""
        return self._request(
            "GET", f"/v2/orders?status={status}&limit={limit}")

    def get_positions(self) -> list[dict[str, Any]]:
        """Get open positions."""
        return self._request("GET", "/v2/positions")


def signal_to_order(signal: Signal, account: str, buffer: float) -> dict[str, Any]:
    """Translate a signal to an order per the account's execution rule.

    A: limit = signal.close (D-029 default), D-020 fills
    B: market-on-open (no limit)
    C: limit = signal.close, but 2x buffer (for calibration)
    """
    if account == "A":
        return {
            "symbol": signal.symbol,
            "qty": signal.shares,
            "side": "buy",
            "type": "limit",
            "limit_price": round(signal.limit, 2),
        }
    elif account == "B":
        return {
            "symbol": signal.symbol,
            "qty": signal.shares,
            "side": "buy",
            "type": "market",
        }
    elif account == "C":
        # 2x buffer: limit is more aggressive (higher for buys)
        # The buffer is applied at fill time in the simulator; here we
        # just use a more aggressive limit to test fill rates.
        # Round to 2 decimals (Alpaca rejects excessive precision).
        return {
            "symbol": signal.symbol,
            "qty": signal.shares,
            "side": "buy",
            "type": "limit",
            "limit_price": round(signal.limit * 1.001, 2),
        }
    else:
        raise ValueError(f"unknown account: {account}")
