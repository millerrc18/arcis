"""Risk governor — hard limits enforced before every trade.

The risk governor is the LAST check before an order is placed.
It cannot be overridden by the trading logic. If any limit is
breached, the trade is rejected with an explanation.
"""

import logging
from pathlib import Path

from src.config import load_config

logger = logging.getLogger(__name__)

_HALT_FILE = "data/trading_halted"


def _get_halt_path() -> Path:
    """Resolve the kill-switch file path from config, falling back to the legacy path."""
    try:
        cfg = load_config()
    except Exception as exc:
        logger.debug("[RISK] Could not load config for halt path: %s", exc)
        cfg = {}

    configured = cfg.get("risk_governor", {}).get("kill_switch_file")
    return Path(configured or _HALT_FILE)


def _global_halt(halt: bool):
    """Set or clear the global trading halt. Uses a file flag so it persists across restarts."""
    halt_path = _get_halt_path()
    if halt:
        halt_path.parent.mkdir(parents=True, exist_ok=True)
        halt_path.touch()
    else:
        halt_path.unlink(missing_ok=True)


def _is_halted() -> bool:
    """Check if trading is globally halted."""
    return _get_halt_path().exists()


def drawdown_adjusted_risk(base_risk_pct: float, current_dd_pct: float,
                           max_dd_pct: float = 20.0) -> float:
    """Thorp-style graduated drawdown reduction.

    At 0% DD:  100% of base risk
    At 5% DD:   75% of base risk
    At 10% DD:  50% of base risk
    At 15% DD:  25% of base risk
    At 20% DD:   0% — stop trading entirely
    """
    if current_dd_pct <= 0:
        return base_risk_pct
    scale = max(0.0, 1.0 - (current_dd_pct / max_dd_pct))
    return base_risk_pct * scale


def compute_current_drawdown(db_path: str = "ai_research_desk.sqlite3",
                              starting_capital: float = 100000) -> float:
    """Compute current drawdown percentage from peak equity."""
    import sqlite3
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT pnl_dollars FROM shadow_trades WHERE status = 'closed' "
                "AND pnl_dollars IS NOT NULL ORDER BY actual_exit_time ASC"
            ).fetchall()
        if not rows:
            return 0.0
        cumulative = 0.0
        peak = starting_capital
        for (pnl,) in rows:
            cumulative += (pnl or 0)
            current = starting_capital + cumulative
            peak = max(peak, current)
        current_equity = starting_capital + cumulative
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - current_equity) / peak * 100)
    except Exception as e:
        logger.error("[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)", e)
        return 15.0  # Assume 15% drawdown on error → reduced position sizing


class RiskGovernor:
    """Hard risk limits enforced before every trade."""

    def __init__(self, config: dict):
        risk_cfg = config.get("risk_governor", {})
        self.max_daily_loss_pct = risk_cfg.get("max_daily_loss_pct", 0.03)
        self.max_position_pct = risk_cfg.get("max_position_pct", 0.10)
        self.max_open_positions = risk_cfg.get("max_open_positions", 10)
        self.max_sector_concentration_pct = risk_cfg.get("max_sector_pct", 0.30)
        self.max_correlated_positions = risk_cfg.get("max_correlated", 3)
        self.volatility_halt_threshold = risk_cfg.get("vol_halt_pct", 35.0)
        self.enabled = risk_cfg.get("enabled", True)

    def check_trade(self, ticker: str, allocation_dollars: float,
                    features: dict, portfolio: dict,
                    traffic_light_multiplier: float = 1.0,
                    event_risk_multiplier: float = 1.0) -> dict:
        """Evaluate whether a proposed trade passes all risk checks.

        Args:
            ticker: Stock to trade
            allocation_dollars: Proposed allocation
            features: Full enriched features (includes regime, sector, etc.)
            portfolio: Current portfolio state (open trades, equity, daily P&L)

        Returns:
            dict with 'approved' bool, 'checks' list, and optional 'rejection_reason'.
        """
        checks = []

        if not self.enabled:
            return {
                "approved": True,
                "checks": [{"name": "governor_disabled", "passed": True, "detail": "Risk governor disabled"}],
                "effective_allocation_dollars": allocation_dollars,
                "effective_multiplier": 1.0,
            }

        # 0. Traffic Light sizing
        if traffic_light_multiplier < 1.0:
            original_alloc = allocation_dollars
            allocation_dollars = allocation_dollars * traffic_light_multiplier
            checks.append({
                "name": "traffic_light",
                "passed": True,
                "detail": f"Traffic Light x{traffic_light_multiplier:.1f}: ${original_alloc:.0f} -> ${allocation_dollars:.0f}",
            })
            logger.info("[RISK] Traffic Light: x%.1f on %s ($%.0f -> $%.0f)",
                        traffic_light_multiplier, ticker, original_alloc, allocation_dollars)

        # 0b. Event risk sizing
        if event_risk_multiplier <= 0:
            checks.append({
                "name": "event_risk",
                "passed": False,
                "detail": "Event risk hard block active",
            })
            return self._reject(checks, "Event risk hard block: no new entries")

        if event_risk_multiplier < 1.0:
            original_alloc = allocation_dollars
            allocation_dollars = allocation_dollars * event_risk_multiplier
            checks.append({
                "name": "event_risk",
                "passed": True,
                "detail": f"Event risk x{event_risk_multiplier:.2f}: ${original_alloc:.0f} -> ${allocation_dollars:.0f}",
            })
            logger.info("[RISK] Event risk: x%.2f on %s ($%.0f -> $%.0f)",
                        event_risk_multiplier, ticker, original_alloc, allocation_dollars)

        # 1. Emergency halt
        halted = _is_halted()
        checks.append({
            "name": "emergency_halt",
            "passed": not halted,
            "detail": "Trading halted via kill switch" if halted else "No halt active",
        })
        if halted:
            return self._reject(checks, "Emergency halt: trading is halted via kill switch")

        # 2. Daily loss limit
        equity = portfolio.get("equity", 0)
        daily_pnl_pct = portfolio.get("daily_pnl_pct", 0) or 0
        daily_loss_exceeded = equity > 0 and daily_pnl_pct < -self.max_daily_loss_pct
        checks.append({
            "name": "daily_loss",
            "passed": not daily_loss_exceeded,
            "detail": f"Daily P&L: {daily_pnl_pct:+.1%} (limit: {-self.max_daily_loss_pct:.1%})",
        })
        if daily_loss_exceeded:
            return self._reject(checks, f"Daily loss limit: portfolio down {daily_pnl_pct:.1%} exceeds {self.max_daily_loss_pct:.0%} limit")

        # 3. Position size
        if equity > 0:
            position_pct = allocation_dollars / equity
            size_ok = position_pct <= self.max_position_pct
        else:
            position_pct = 0
            size_ok = True
        checks.append({
            "name": "position_size",
            "passed": size_ok,
            "detail": f"${allocation_dollars:.0f} = {position_pct:.1%} of ${equity:.0f} (limit: {self.max_position_pct:.0%})",
        })
        if not size_ok:
            return self._reject(checks, f"Position size: ${allocation_dollars:.0f} is {position_pct:.1%} of equity, exceeds {self.max_position_pct:.0%} limit")

        # 4. Maximum positions (use bootcamp limit if enabled)
        open_count = portfolio.get("open_count", 0)
        effective_limit = self.max_open_positions
        try:
            from src.config import load_config
            full_cfg = load_config()
            bootcamp = full_cfg.get("bootcamp", {})
            if bootcamp.get("enabled", False):
                effective_limit = bootcamp.get("max_positions", 50)
        except Exception as e:
            logger.debug("[RISK] Bootcamp config check failed: %s — using default limit", e)
        positions_ok = open_count < effective_limit
        checks.append({
            "name": "max_positions",
            "passed": positions_ok,
            "detail": f"{open_count} of {effective_limit} positions open",
        })
        if not positions_ok:
            return self._reject(checks, f"Position count: {open_count} open positions at limit of {effective_limit}")

        # 5. Sector concentration (VIX-adaptive)
        from src.universe.sectors import SECTOR_MAP
        ticker_sector = features.get("sector") or SECTOR_MAP.get(ticker, "Unknown")
        sector_exposure = portfolio.get("sector_exposure", {})
        current_sector_pct = sector_exposure.get(ticker_sector, 0)
        new_sector_pct = current_sector_pct + (allocation_dollars / equity if equity > 0 else 0)
        max_sector = self.max_sector_concentration_pct
        vix = features.get("vix_proxy", 0) or 0
        if vix > 25:
            max_sector = min(max_sector, 0.15)
            logger.info("[RISK] High VIX (%.1f) — sector cap tightened to 15%%", vix)
        sector_ok = new_sector_pct <= max_sector
        checks.append({
            "name": "sector_concentration",
            "passed": sector_ok,
            "detail": f"{ticker_sector}: {current_sector_pct:.0%} + this trade = {new_sector_pct:.0%} (limit: {max_sector:.0%})",
        })
        if not sector_ok:
            return self._reject(checks, f"Sector concentration: {ticker_sector} would be {new_sector_pct:.0%}, exceeds {max_sector:.0%} limit")

        # 6. Correlation check (same-sector count)
        open_positions = portfolio.get("open_positions", [])
        same_sector_count = sum(1 for p in open_positions if p.get("sector") == ticker_sector)
        corr_ok = same_sector_count < self.max_correlated_positions
        checks.append({
            "name": "correlation",
            "passed": corr_ok,
            "detail": f"{same_sector_count} {ticker_sector} positions open (limit: {self.max_correlated_positions})",
        })
        if not corr_ok:
            return self._reject(checks, f"Correlation: {same_sector_count} {ticker_sector} positions already open, max {self.max_correlated_positions}")

        # 7. Volatility circuit breaker
        vix_proxy = features.get("vix_proxy", 0) or 0
        vol_ok = vix_proxy <= self.volatility_halt_threshold
        checks.append({
            "name": "volatility_halt",
            "passed": vol_ok,
            "detail": f"VIX proxy: {vix_proxy:.1f}% (halt at {self.volatility_halt_threshold:.0f}%)",
        })
        if not vol_ok:
            return self._reject(checks, f"Volatility circuit breaker: VIX proxy at {vix_proxy:.1f}% exceeds {self.volatility_halt_threshold:.0f}% threshold")

        # 8. Duplicate check
        open_tickers = [p.get("ticker") for p in open_positions]
        dup_ok = ticker not in open_tickers
        checks.append({
            "name": "duplicate",
            "passed": dup_ok,
            "detail": f"{'Already have open trade for ' + ticker if not dup_ok else 'No duplicate'}",
        })
        if not dup_ok:
            return self._reject(checks, f"Duplicate: already have an open trade for {ticker}")

        return {
            "approved": True,
            "checks": checks,
            "effective_allocation_dollars": allocation_dollars,
            "effective_multiplier": traffic_light_multiplier * event_risk_multiplier,
        }

    def _reject(self, checks: list, reason: str) -> dict:
        return {
            "approved": False,
            "checks": checks,
            "rejection_reason": reason,
            "effective_allocation_dollars": 0.0,
            "effective_multiplier": 0.0,
        }


def get_portfolio_state(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Get current portfolio state for risk checks."""
    from src.journal.store import get_open_shadow_trades
    from src.universe.sectors import SECTOR_MAP

    open_trades = get_open_shadow_trades(db_path)

    # Try to get equity from Alpaca, fall back to config starting_capital
    config = load_config()
    starting_capital = config.get("risk", {}).get("starting_capital", 100000)
    equity = float(starting_capital)
    cash = float(starting_capital)
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        equity = acct.get("equity", float(starting_capital))
        cash = acct.get("cash", float(starting_capital))
    except Exception as e:
        logger.debug("Alpaca account unreachable, using config starting_capital: %s", e)

    # Build position list with sectors
    positions = []
    daily_pnl = 0.0
    for t in open_trades:
        ticker = t.get("ticker", "")
        sector = SECTOR_MAP.get(ticker, "Unknown")
        entry_price = t.get("actual_entry_price") or t.get("entry_price", 0)
        shares = t.get("planned_shares", 1)
        allocation = entry_price * shares

        # Try to get unrealized P&L
        unrealized = 0.0
        try:
            from src.shadow_trading.executor import _get_current_price_safe
            current = _get_current_price_safe(ticker)
            if current and entry_price > 0:
                unrealized = (current - entry_price) * shares
        except Exception as e:
            logger.debug("Could not get current price for %s: %s", ticker, e)

        positions.append({
            "ticker": ticker,
            "sector": sector,
            "allocation": allocation,
            "unrealized_pnl": unrealized,
        })
        daily_pnl += unrealized

    # Sector exposure
    sector_totals = {}
    for p in positions:
        sector_totals[p["sector"]] = sector_totals.get(p["sector"], 0) + p["allocation"]
    sector_exposure = {s: v / equity if equity > 0 else 0 for s, v in sector_totals.items()}

    daily_pnl_pct = daily_pnl / equity if equity > 0 else 0

    return {
        "equity": equity,
        "cash": cash,
        "open_positions": positions,
        "open_count": len(open_trades),
        "sector_exposure": sector_exposure,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
    }
