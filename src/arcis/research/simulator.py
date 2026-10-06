"""Bracket simulator implementing the preregistered execution rules.

Primary specification: PREREG §1.1, R05 (research-log), SCOPE D-020 (which
supersedes R05 rule 3), SCOPE D-009 / I-15 (conservative is primary).

Cost accounting (R06 conservative, no double-count):
- Fill prices embed the adverse buffer (R05/D-020): that IS the realized
  adverse selection, so R06's "do not separately add adverse-selection bps
  after using realized post-fill returns" applies.
- total_trade_cost is called with exit_type="passive" (zero execution
  add-on) for commissions + SEC/TAF/CAT only.
- The R06 mechanical execution loss beyond the embedded half-spread is an
  explicit add-on: +2.0 bp on stop exits, 0.5*spread + 1.0 bp on time
  (marketable/MOC-modeled) exits, 0 on passive entry/target fills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from arcis.research import costs as cost_model
from arcis.research.panel import Bar, Panel, PanelError

TICK_DOLLARS = 0.01
MAX_HOLD_SESSIONS = 15


@dataclass(frozen=True)
class BracketSpec:
    """One simulated bracket trade."""

    symbol: str
    signal_date: date       # t: signal computed on t's close
    entry_session: date     # t+1: the buy-limit session
    limit: float            # buy limit (D-029: default = signal close)
    stop: float             # stop-market trigger (below entry)
    target: float           # take-profit limit (above entry)
    shares: int
    events: dict[date, str] = field(default_factory=dict)  # session -> note


@dataclass(frozen=True)
class Fill:
    session: date
    price: float
    kind: str  # "entry" | "target" | "stop" | "time"
    gap: bool
    buffer: float  # adverse buffer embedded in the price ($/share)


@dataclass(frozen=True)
class TradeResult:
    spec: BracketSpec
    entry: Fill | None
    exit: Fill | None
    unfilled_reason: str | None  # "no_bar" | "touch_only" | "no_trade_through" | "corporate_action"
    ambiguous_bar: bool          # stop-first applied on a both-reachable bar
    corporate_action: bool       # any event session touched
    entry_cost: dict[str, float]
    exit_cost: dict[str, float]
    execution_addon_dollars: float  # R06 mechanical loss beyond embedded buffer
    pnl_dollars: float
    return_pct: float  # vs entry notional


def trailing_median_spread(panel: Panel, symbol: str, session: date,
                           sessions: int = 21) -> float:
    """21-session trailing median of the conservative spread proxy (fraction).

    Needs sessions+1 bars ending at `session`. Fail-closed on short history.
    """
    bars = panel.trailing(symbol, session, sessions + 1)
    proxies = [
        cost_model.spread_proxy_conservative(
            [b0.high, b1.high], [b0.low, b1.low], [b0.close, b1.close],
            b1.close)
        for b0, b1 in zip(bars, bars[1:], strict=False)
    ]
    return median(proxies)


def adverse_buffer(spread_frac: float, price: float) -> float:
    """R05 rule 10: larger of one tick and the estimated half-spread ($/sh)."""
    return max(TICK_DOLLARS, 0.5 * spread_frac * price)


def _validate_spec(panel: Panel, spec: BracketSpec) -> None:
    if spec.shares <= 0:
        raise PanelError(f"shares must be positive, got {spec.shares}")
    for name, px in (("limit", spec.limit), ("stop", spec.stop),
                     ("target", spec.target)):
        if px <= 0:
            raise PanelError(f"{name} must be positive, got {px}")
    if not spec.stop < spec.limit < spec.target:
        raise PanelError(
            f"need stop < limit < target, got {spec.stop}, {spec.limit}, "
            f"{spec.target}")
    if not panel.is_session(spec.entry_session):
        raise PanelError(f"{spec.entry_session} is not a session")
    if spec.entry_session <= spec.signal_date:
        raise PanelError("entry session must be after the signal date")


def _try_entry(panel: Panel, spec: BracketSpec,
               buffer: float) -> tuple[Fill | None, str | None, bool]:
    """Entry-session logic. Returns (fill, unfilled_reason, corp_action)."""
    bar = panel.bar(spec.symbol, spec.entry_session)
    if bar is None:
        return None, "no_bar", False
    corp = spec.entry_session in spec.events
    if corp:
        return None, "corporate_action", True
    if bar.open <= spec.limit:
        # D-020: fill at open + buffer, never above the limit.
        price = min(bar.open + buffer, spec.limit)
        return Fill(spec.entry_session, price, "entry",
                    gap=bar.open < spec.limit, buffer=buffer), None, False
    if bar.low < spec.limit:
        # Strict trade-through: fill at the limit, no price improvement.
        return Fill(spec.entry_session, spec.limit, "entry",
                    gap=False, buffer=buffer), None, False
    reason = "touch_only" if bar.low == spec.limit else "no_trade_through"
    return None, reason, False


def _stop_fill(session: date, bar: Bar, spec: BracketSpec,
               buffer: float) -> tuple[Fill, bool]:
    """Stop-market fill on a bar whose low reached the stop."""
    if bar.open < spec.stop:
        return Fill(session, bar.open - buffer, "stop", True, buffer), True
    return Fill(session, spec.stop - buffer, "stop", False, buffer), False


def _holding_session(panel: Panel, spec: BracketSpec, session: date,
                     buffer: float, is_last: bool,
                     ) -> tuple[Fill | None, bool]:
    """One holding-day event check. Returns (exit_fill, ambiguous)."""
    bar = panel.bar(spec.symbol, session)
    if bar is None:
        return None, False  # halted/dark session: skip, don't count
    stop_hit = bar.low <= spec.stop
    target_hit = bar.high >= spec.target
    if stop_hit and target_hit:
        # Stop-first: deliberate lower bound; report the ambiguity.
        fill, gap = _stop_fill(session, bar, spec, buffer)
        return fill, True
    if stop_hit:
        fill, gap = _stop_fill(session, bar, spec, buffer)
        return fill, False
    if target_hit:
        # Fill at target even when the open gaps above it (R05 rule 13).
        return Fill(session, spec.target, "target", False, buffer), False
    if is_last:
        # 15th session: MOC modeled at the close (flagged in the result).
        return Fill(session, bar.close, "time", False, buffer), False
    return None, False


def _cost_leg(notional: float, shares: int, is_sell: bool, session: date,
              panel: Panel, commission_model: str) -> dict[str, float]:
    """Commissions + regulatory fees only (execution add-on is separate)."""
    charge = panel.charge_date(session) if is_sell else None
    return cost_model.total_trade_cost(
        notional=notional, shares=shares, is_sell=is_sell, as_of=session,
        spread=0.0, exit_type="passive", commission_model=commission_model,
        charge_date=charge)


def _holding_period(panel: Panel, spec: BracketSpec, entry: Fill,
                    buffer: float, corp: bool) -> tuple[Fill, bool, bool]:
    """Run the holding loop. Returns (exit_fill, ambiguous, corp_action)."""
    bar0 = panel.bar(spec.symbol, spec.entry_session)
    assert bar0 is not None
    ambiguous = False
    if bar0.low <= spec.stop:
        # Entry-day stop: traversal entry -> stop is implied.
        day0_fill, _ = _stop_fill(spec.entry_session, bar0, spec, buffer)
        return day0_fill, False, corp
    held, session = 1, spec.entry_session
    while True:
        try:
            session = panel.next_session(session)
        except PanelError as exc:
            raise PanelError(
                f"{spec.symbol}: position open at calendar end") from exc
        if panel.bar(spec.symbol, session) is None:
            corp = corp or session in spec.events
            continue  # halted session: skip, don't count toward the 15
        held += 1
        corp = corp or session in spec.events
        fill, amb = _holding_session(
            panel, spec, session, buffer, held >= MAX_HOLD_SESSIONS)
        ambiguous = ambiguous or amb
        if fill is not None:
            return fill, ambiguous, corp
        if held > MAX_HOLD_SESSIONS + 5:
            raise PanelError(f"{spec.symbol}: exceeded session scan bound")


def _settle(panel: Panel, spec: BracketSpec, entry: Fill, exit_fill: Fill,
            spread_frac: float, cost_model_name: str,
            commission_model: str
            ) -> tuple[dict[str, float], dict[str, float], float, float,
                       float]:
    """Costs, P&L, and return for a completed trade."""
    entry_notional = entry.price * spec.shares
    exit_notional = exit_fill.price * spec.shares
    entry_cost = _cost_leg(entry_notional, spec.shares, False,
                           entry.session, panel, commission_model)
    exit_cost = _cost_leg(exit_notional, spec.shares, True,
                          exit_fill.session, panel, commission_model)
    # R06 mechanical execution loss beyond the embedded half-spread.
    if cost_model_name == "conservative":
        stop_bp, time_bp = 0.00020, 0.00010
    elif cost_model_name == "central":
        stop_bp, time_bp = 0.00005, 0.000025
    else:
        raise PanelError(f"unknown cost model: {cost_model_name}")
    addon = 0.0
    if exit_fill.kind == "stop":
        addon = stop_bp * exit_notional
    elif exit_fill.kind == "time":
        addon = (0.5 * spread_frac + time_bp) * exit_notional
    total = (entry_cost["total_dollars"] + exit_cost["total_dollars"] + addon)
    pnl = exit_notional - entry_notional - total
    ret = pnl / entry_notional * 100 if entry_notional else 0.0
    return entry_cost, exit_cost, addon, pnl, ret


def simulate_trade(panel: Panel, spec: BracketSpec, buffer: float,
                   spread_frac: float, cost_model_name: str = "conservative",
                   commission_model: str = "modern") -> TradeResult:
    """Run one bracket trade. `buffer` ($/sh) and `spread_frac` are explicit.

    Use trailing_median_spread + adverse_buffer to estimate them, or pass
    hand values for synthetic known-answer tests.
    """
    _validate_spec(panel, spec)
    entry, reason, corp = _try_entry(panel, spec, buffer)
    if entry is None:
        return TradeResult(spec, None, None, reason, False, corp,
                           {}, {}, 0.0, 0.0, 0.0)
    exit_fill, ambiguous, corp = _holding_period(
        panel, spec, entry, buffer, corp)
    entry_cost, exit_cost, addon, pnl, ret = _settle(
        panel, spec, entry, exit_fill, spread_frac,
        cost_model_name, commission_model)
    return TradeResult(spec, entry, exit_fill, None, ambiguous, corp,
                       entry_cost, exit_cost, addon, pnl, ret)
