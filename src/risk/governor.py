"""Risk governor — hard limits enforced before every trade.

Called by: api.routes.system, cli.commands, evaluation.auditor, evaluation.system_validator, services.system_service, shadow_trading.executor
Calls: config, journal.store, shadow_trading.alpaca_adapter, shadow_trading.executor, universe.sectors
Owns tables: none
Config keys: bootcamp, enabled, max_correlated, max_daily_loss_pct, max_open_positions, max_position_pct, max_sector_pct, risk, risk_governor, vol_halt_pct
Tests: tests/test_auditor.py, tests/test_risk_governor.py

The risk governor is the LAST check before an order is placed.
It cannot be overridden by the trading logic. If any limit is
breached, the trade is rejected with an explanation.

Design rationale
~~~~~~~~~~~~~~~~
This module implements a strict "deny by default" posture inspired by
Ed Thorp's position-sizing discipline in *A Man for All Markets*.  Every
check is intentionally conservative: false rejections are cheap (we skip
one trade), false approvals are expensive (we take uncontrolled risk).

The 8 checks form a layered defense:
  0a. Traffic Light — regime-based position scaling (from council)
  0b. Event Risk — earnings / macro event hard blocks
  1.  Kill Switch — global halt file, atomic writes (#106)
  2.  Daily Loss — realized-only P&L cap (#109)
  3.  Position Size — single-name concentration cap
  4.  Max Positions — portfolio breadth limit (bootcamp-aware)
  5.  Sector Concentration — VIX-adaptive sector cap
  6.  Correlation — same-sector count limit
  7.  Volatility — VIX circuit breaker
  8.  Duplicate — one position per ticker at a time

The graduated drawdown function (drawdown_adjusted_risk) implements
Ed Thorp's proportional bet reduction: as drawdown deepens, position
sizes shrink linearly to zero at max_dd_pct.  This prevents the
catastrophic "doubling down to recover" behavior that blows up accounts.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config

# All risk timestamps use Eastern Time because US equity markets
# operate on ET and daily loss limits reset at midnight ET.
_ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

# Kill switch is a file-based flag rather than a DB column so it works
# even when the database is corrupt or locked.  The sentinel file path
# is configurable for tests (#47: kill switch was contaminating test
# runs because all tests shared the default path).
_DEFAULT_HALT_FILE = "data/trading_halted"
_HALT_FILE = _DEFAULT_HALT_FILE


def _get_halt_path() -> Path:
    """Resolve the kill-switch file path from config, with test overrides supported.

    Tests override _HALT_FILE to an isolated tmpdir path (#47) so the
    kill-switch check doesn't bleed between test cases or interfere with
    the real halt file.
    """
    if _HALT_FILE != _DEFAULT_HALT_FILE:
        return Path(_HALT_FILE)

    try:
        cfg = load_config()
    except Exception as exc:
        logger.debug("[RISK] Could not load config for halt path: %s", exc)
        cfg = {}

    configured = cfg.get("risk_governor", {}).get("kill_switch_file")
    return Path(configured or _DEFAULT_HALT_FILE)


def _global_halt(halt: bool, source: str = "unknown", reason: str = ""):
    """Set or clear the global trading halt atomically.

    Uses atomic file rename (os.replace) so the halt file is never
    partially written.  This fixes #106: without atomicity, a crash
    mid-write could leave a truncated file that _is_halted() misreads.
    Writes JSON with timestamp so staleness detection can warn when a
    halt file lingers beyond 48 hours (likely forgotten).
    """
    halt_path = _get_halt_path()
    if halt:
        halt_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "halted_at": datetime.now(_ET).isoformat(),
            "source": source,
            "reason": reason,
        }
        tmp_path = str(halt_path) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, str(halt_path))
        logger.warning("[RISK] Trading HALTED by %s: %s", source, reason)
        _log_halt_event("halt", source, reason)
    else:
        if halt_path.exists():
            halt_path.unlink(missing_ok=True)
        logger.warning("[RISK] Trading RESUMED")
        _log_halt_event("resume", source, reason)


def _is_halted() -> bool:
    """Check if trading is globally halted. Warns if halt file is stale (>48h).

    Fail-safe design: if the halt file exists but is unreadable (corrupt
    JSON, missing keys), we STILL honor the halt.  The risk of
    accidentally blocking trades is far lower than the risk of trading
    when a human intended to halt.
    """
    halt_path = _get_halt_path()
    if not halt_path.exists():
        return False
    try:
        data = json.loads(halt_path.read_text())
        halted_at = datetime.fromisoformat(data["halted_at"])
        age_hours = (datetime.now(_ET) - halted_at).total_seconds() / 3600
        if age_hours > 48:
            logger.warning(
                "[RISK] Stale halt file detected (%.0fh old) — still honoring halt. "
                "Resume trading explicitly if this is unintended.", age_hours
            )
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("[RISK] Halt file exists but unreadable — honoring halt")
    return True


def _halt_info() -> dict | None:
    """Return halt metadata (timestamp, source, reason) or None if not halted."""
    halt_path = _get_halt_path()
    if not halt_path.exists():
        return None
    try:
        return json.loads(halt_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {"halted_at": "unknown", "source": "unknown", "reason": ""}


def _log_halt_event(event_type: str, source: str, reason: str):
    """Log halt/resume to activity_log for audit trail.

    This is a best-effort write: if the activity logger is unavailable
    (e.g. DB locked), we still complete the halt/resume operation.
    Logging must never block the kill switch from functioning.
    """
    try:
        from src.utils.activity_logger import log_activity
        log_activity(
            f"kill_switch_{event_type}",
            f"source={source}, reason={reason}",
        )
    except Exception as exc:
        logger.warning("[RISK] Failed to log halt event: %s", exc)


def drawdown_adjusted_risk(base_risk_pct: float, current_dd_pct: float,
                           max_dd_pct: float = 20.0) -> float:
    """Ed Thorp's graduated drawdown reduction (proportional bet sizing).

    From *A Man for All Markets* and the Kelly Criterion literature:
    as drawdown deepens, reduce bet size linearly so that at the maximum
    tolerable drawdown the system stops trading entirely.  This avoids
    the "martingale trap" of increasing size to recover losses.

    At 0% DD:  100% of base risk   (full Kelly fraction)
    At 5% DD:   75% of base risk
    At 10% DD:  50% of base risk   (half Kelly)
    At 15% DD:  25% of base risk
    At 20% DD:   0% — stop trading entirely

    The 20% max drawdown default is conservative for a paper-trading
    phase; it will be reviewed when transitioning to live capital.
    """
    if current_dd_pct <= 0:
        return base_risk_pct
    scale = max(0.0, 1.0 - (current_dd_pct / max_dd_pct))
    return base_risk_pct * scale


def compute_current_drawdown(db_path: str = DB_PATH,
                              starting_capital: float = 100000) -> float:
    """Compute current drawdown percentage from peak equity.

    Uses only realized (closed) P&L because unrealized values fluctuate
    tick-to-tick and would cause the drawdown signal to oscillate,
    leading to inconsistent position sizing within a single scan cycle.
    """
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
        # Fail-conservative: assume 15% drawdown on error so the Thorp
        # scaling reduces position sizes rather than trading at full size
        # when we cannot verify the actual drawdown state.
        logger.error("[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)", e)
        return 15.0


def get_current_equity(config: dict | None = None,
                       db_path: str = DB_PATH) -> float:
    """Compute current equity from starting capital + realized P&L.
    Uses only closed-trade P&L (not unrealized) to prevent equity
    oscillation during market hours from affecting position sizing.
    """
    if config is None:
        config = load_config()
    starting_capital = config.get("risk", {}).get("starting_capital", 100000)
    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) "
                "FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            total_pnl = float(row[0]) if row else 0
        return starting_capital + total_pnl
    except Exception as e:
        logger.warning("[RISK] Equity computation failed: %s — using starting_capital", e)
        return starting_capital


def get_effective_risk_pct(config: dict | None = None,
                           db_path: str = DB_PATH) -> tuple[float, str]:
    """Get the risk percentage for the current equity tier.
    Returns (effective_risk_pct, tier_label).
    If scaling is disabled or tiers are empty, returns (planned_risk_pct_max, "static").
    """
    if config is None:
        config = load_config()
    risk_cfg = config.get("risk", {})
    base = risk_cfg.get("planned_risk_pct_max", 0.02)

    scaling = risk_cfg.get("risk_scaling", {})
    if not scaling.get("enabled", False):
        return base, "static"

    tiers = scaling.get("tiers", [])
    if not tiers:
        return base, "static"

    equity = get_current_equity(config, db_path)

    sorted_tiers = sorted(tiers, key=lambda t: t["equity_below"])
    for tier in sorted_tiers:
        if equity < tier["equity_below"]:
            label = f"<${tier['equity_below']:,.0f} ({tier['risk_pct_max']:.1%})"
            return tier["risk_pct_max"], label

    last = sorted_tiers[-1]
    label = f">=${last['equity_below']:,.0f} ({last['risk_pct_max']:.1%})"
    return last["risk_pct_max"], label


def check_tier_transition(config: dict, db_path: str = DB_PATH) -> dict | None:
    """Detect if equity has crossed a tier boundary since last EOD check.
    Stores last known tier in the activity_log table. Returns transition dict if changed.
    """
    import sqlite3
    import json
    current_pct, current_label = get_effective_risk_pct(config, db_path)
    equity = get_current_equity(config, db_path)

    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT detail FROM activity_log "
                "WHERE event_type = 'tier_check' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

        prev_label = None
        if row and row[0]:
            prev = json.loads(row[0])
            prev_label = prev.get("tier_label")

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) "
                "VALUES ('tier_check', ?, datetime('now'))",
                (json.dumps({"tier_label": current_label, "equity": equity, "risk_pct": current_pct}),),
            )

        if prev_label and prev_label != current_label:
            return {
                "equity": equity,
                "prev_tier": prev_label,
                "new_tier": current_label,
                "new_risk_pct": current_pct,
            }
    except Exception as e:
        logger.debug("[RISK] Tier transition check failed: %s", e)

    return None


class RiskGovernor:
    """Hard risk limits enforced before every trade.

    Every default threshold is intentionally tight for the paper-trading
    phase.  The philosophy: prove the system works under constraints
    first, then loosen limits with evidence.  Thresholds are YAML-
    configurable so they can be tightened/loosened without code changes.
    """

    def __init__(self, config: dict):
        risk_cfg = config.get("risk_governor", {})
        # 3% daily loss limit — prevents a single bad day from blowing
        # through the Thorp drawdown curve.  Uses realized P&L only (#109).
        self.max_daily_loss_pct = risk_cfg.get("max_daily_loss_pct", 0.03)
        # 10% single-position cap — no single name can dominate the book.
        self.max_position_pct = risk_cfg.get("max_position_pct", 0.10)
        # 10 open positions max — keeps the portfolio manageable for a
        # system that monitors bracket orders individually.
        self.max_open_positions = risk_cfg.get("max_open_positions", 10)
        # 30% sector cap — prevents over-concentration in one sector;
        # tightens to 15% when VIX > 25 (correlations spike in stress).
        self.max_sector_concentration_pct = risk_cfg.get("max_sector_pct", 0.30)
        # 3 correlated positions — even within the sector cap, limits
        # same-sector names because sector ETF correlation is ~0.7+.
        self.max_correlated_positions = risk_cfg.get("max_correlated", 3)
        # VIX 35 circuit breaker — at this level, equity correlations
        # approach 1.0 and diversification breaks down.
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

        # Coerce inputs — upstream can produce strings, tuples, or numpy scalars
        from src.utils.type_safety import safe_numeric
        allocation_dollars = safe_numeric(allocation_dollars, default=0)
        traffic_light_multiplier = safe_numeric(traffic_light_multiplier, default=1.0)
        event_risk_multiplier = safe_numeric(event_risk_multiplier, default=1.0)

        if allocation_dollars <= 0:
            return self._reject(checks, "Zero or negative allocation")

        if not self.enabled:
            return {
                "approved": True,
                "checks": [{"name": "governor_disabled", "passed": True, "detail": "Risk governor disabled"}],
                "effective_allocation_dollars": allocation_dollars,
                "effective_multiplier": 1.0,
            }

        # -- Check 0a: Traffic Light sizing --
        # The council's regime assessment produces a multiplier (0.0-1.0)
        # that scales down position size in unfavorable regimes.  Applied
        # first so all subsequent checks see the reduced allocation.
        # Persistence note (#144): traffic light state is session-scoped,
        # so a stale council session could leave a stale multiplier.
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

        # -- Check 0b: Event risk sizing --
        # A multiplier of 0 means "hard block" (e.g. earnings tomorrow),
        # a value between 0 and 1 means "reduce size" (e.g. FOMC day).
        # This is separate from Traffic Light because event risk is
        # calendar-driven, not regime-driven.
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

        # -- Check 1: Emergency halt (kill switch) --
        # File-based global halt so it works even if DB is corrupt.
        # Atomic writes via os.replace (#106).  This is the one check
        # that a human can trigger from any terminal with a simple
        # `touch data/trading_halted` as a last resort.
        halted = _is_halted()
        checks.append({
            "name": "emergency_halt",
            "passed": not halted,
            "detail": "Trading halted via kill switch" if halted else "No halt active",
        })
        if halted:
            return self._reject(checks, "Emergency halt: trading is halted via kill switch")

        # -- Check 2: Daily loss limit (3% default) --
        # Uses REALIZED (closed) trades from today only (#109).
        # Earlier versions included unrealized P&L, which caused
        # the governor to block trades during normal intraday
        # fluctuations — a whipsaw that reduced opportunity.
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

        # -- Check 3: Position size (10% of equity default) --
        # Caps any single position to prevent one name from dominating
        # the portfolio.  This is a hard cap on the *proposed* allocation
        # after Traffic Light and Event Risk scaling have been applied.
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

        # -- Check 4: Maximum open positions --
        # In bootcamp mode the limit comes from bootcamp config (higher,
        # to encourage trade volume for training data).  In production
        # it uses the tighter risk_governor limit.
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

        # -- Check 5: Sector concentration (VIX-adaptive) --
        # Default 30% cap tightens to 15% when VIX > 25 because
        # intra-sector correlations spike during volatility regimes.
        # This prevents the portfolio from being a disguised sector bet.
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

        # -- Check 6: Correlation check (same-sector count) --
        # Even if total sector $ exposure is under the cap, having too
        # many names in one sector creates correlated drawdown risk.
        # 3-name limit per sector keeps diversification meaningful.
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

        # -- Check 7: Volatility circuit breaker (VIX 35 default) --
        # At VIX > 35, equity markets enter "correlation one" regime
        # where all stocks move together.  No edge is exploitable here,
        # so we stop entering new positions entirely.
        vix_proxy = features.get("vix_proxy", 0) or 0
        vol_ok = vix_proxy <= self.volatility_halt_threshold
        checks.append({
            "name": "volatility_halt",
            "passed": vol_ok,
            "detail": f"VIX proxy: {vix_proxy:.1f}% (halt at {self.volatility_halt_threshold:.0f}%)",
        })
        if not vol_ok:
            return self._reject(checks, f"Volatility circuit breaker: VIX proxy at {vix_proxy:.1f}% exceeds {self.volatility_halt_threshold:.0f}% threshold")

        # -- Check 8: Duplicate position check --
        # We allow only one open position per ticker because bracket
        # orders and reconciliation logic assume a 1:1 ticker-to-trade
        # mapping.  Multiple positions in the same name would confuse
        # stop/target tracking and P&L attribution.
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


def get_portfolio_state(db_path: str = DB_PATH) -> dict:
    """Get current portfolio state for risk checks.

    Builds a portfolio snapshot that the RiskGovernor.check_trade() method
    uses for its 8 checks.  Uses current market prices for sector
    exposure (#145) but realized-only P&L for the daily loss limit (#109).
    Falls back to config starting_capital when Alpaca is unreachable so
    the governor can still make conservative decisions offline.
    """
    from src.journal.store import get_open_shadow_trades
    from src.universe.sectors import SECTOR_MAP

    open_trades = get_open_shadow_trades(db_path)

    # Try to get equity from Alpaca, fall back to config starting_capital.
    # Fallback ensures the governor works during Alpaca outages — using
    # starting_capital is conservative because actual equity may be higher.
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

    # Build position list with sectors — use current price for allocation (#145)
    positions = []
    for t in open_trades:
        ticker = t.get("ticker", "")
        sector = SECTOR_MAP.get(ticker, "Unknown")
        entry_price = float(t.get("actual_entry_price") or t.get("entry_price") or 0)
        shares = float(t.get("planned_shares") or 1)

        # Use current price for sector exposure if available (#145)
        current_price = entry_price
        try:
            from src.shadow_trading.executor import _get_current_price_safe
            fetched = _get_current_price_safe(ticker)
            if fetched and fetched > 0:
                current_price = fetched
        except Exception as e:
            logger.debug("Could not get current price for %s: %s", ticker, e)

        allocation = current_price * shares
        unrealized = (current_price - entry_price) * shares if entry_price > 0 else 0.0

        positions.append({
            "ticker": ticker,
            "sector": sector,
            "allocation": allocation,
            "unrealized_pnl": unrealized,
        })

    # Daily P&L: use REALIZED (closed) trades from today only (#109).
    # Including unrealized P&L caused the daily loss check to trigger
    # during normal intraday volatility, blocking valid entries.
    # Realized-only gives a stable signal that resets cleanly each day.
    import sqlite3 as _sq3
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    _today_str = _dt.now(_ZI("America/New_York")).strftime("%Y-%m-%d")
    daily_pnl = 0.0
    try:
        with _sq3.connect(db_path) as _conn:
            _rows = _conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_dollars IS NOT NULL "
                "AND actual_exit_time >= ?",
                (_today_str,),
            ).fetchone()
            daily_pnl = float(_rows[0]) if _rows else 0.0
    except Exception as e:
        logger.debug("[RISK] Realized daily P&L query failed: %s", e)

    # Sector exposure — uses current prices (#145)
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
