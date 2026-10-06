"""Bracket simulator implementing the preregistered execution rules.

Primary specification: PREREG §1.1, R05 (research-log), SCOPE D-020 (which
supersedes R05 rule 3), SCOPE D-009 / I-15 (conservative is primary).

Cost accounting (R06, conservative primary — no double-count):
- Fill prices embed the adverse buffer (R05 rule 10 / D-020): that IS the
  realized adverse selection, so R06's "do not separately add
  adverse-selection bps after using realized post-fill returns" applies.
- total_trade_cost runs with exit_type="passive" (zero execution add-on)
  for commissions + SEC/TAF/CAT only.
- R06 time-of-day spread multipliers scale the spread estimate:
  conservative open 3.0 / regular 1.5 / close 2.0;
  central open 1.5 / regular 1.0 / close 1.25.
- The predeclared entry buffer (R05-10) is max(tick, 0.5 × spread ×
  open-mult × limit).
- Marketable exits add R06's extra beyond the half-spread: +1.0 bp
  (conservative) / +0.25 bp (central) on stop and time exits; the time
  (MOC-modeled) exit additionally embeds 0.5 × spread × close-mult.

Corporate actions (PREREG §1.1):
- Splits (R05-20): open orders are cancelled and reissued at the
  ratio-adjusted quantity and price; the trade is flagged. ``splits``
  maps ex-date -> ratio (e.g. 2.0 for a 2-for-1 split).
- Ordinary dividends (R05-21): bracket prices are NOT reduced (Alpaca
  DNR). A stop fill on an ex-div date is simulated normally and flagged
  via ``exdiv_stop`` for separate reporting.
- Special events (R05-22): no new entries from the session before the
  event through its resolution. Use ``expand_blackouts`` to build the
  ``blackouts`` set; ``events`` still flags/reports.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from statistics import median

from arcis.research import costs as cost_model
from arcis.research.panel import Bar, Panel, PanelError

TICK_DOLLARS = 0.01
MAX_HOLD_SESSIONS = 15

# R06 time-of-day spread multipliers: (open, regular, close).
TOD_MULT = {
    "conservative": {"open": 3.0, "regular": 1.5, "close": 2.0},
    "central": {"open": 1.5, "regular": 1.0, "close": 1.25},
}
# R06 marketable-exit loss beyond the half-spread, as a fraction.
EXIT_EXTRA_BP = {"conservative": 0.00010, "central": 0.000025}


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
    blackouts: frozenset[date] = frozenset()  # no-entry sessions (R05-22)
    splits: dict[date, float] = field(default_factory=dict)  # ex-date->ratio
    exdiv_dates: frozenset[date] = frozenset()


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
    unfilled_reason: str | None  # "no_bar" | "halted" | "touch_only" |
    # "no_trade_through" | "corporate_action"
    ambiguous_bar: bool          # stop-first applied on a both-reachable bar
    corporate_action: bool       # any event/blackout session touched
    late_time_exit: bool         # MOC cutoff missed; next executable price
    exdiv_stop: bool             # stop fill on an ex-div date (report sep.)
    split_adjusted: bool         # levels reissued around a split (R05-20)
    sessions_held: int           # counted sessions (halts excluded)
    entry_cost: dict[str, float]
    exit_cost: dict[str, float]
    execution_addon_dollars: float  # R06 loss beyond the embedded buffer
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


def estimate_buffer(spread_frac: float, price: float,
                    cost_model_name: str = "conservative") -> float:
    """R05-10 predeclared buffer: max(tick, 0.5 × spread × open-mult × price)."""
    if cost_model_name not in TOD_MULT:
        raise PanelError(f"unknown cost model: {cost_model_name}")
    mult = TOD_MULT[cost_model_name]["open"]
    return max(TICK_DOLLARS, 0.5 * spread_frac * mult * price)


def expand_blackouts(event_dates: set[date], panel: Panel,
                     resolutions: dict[date, date] | None = None
                     ) -> frozenset[date]:
    """R05-22: no-entry sessions from before an event through resolution.

    Blacks out the session before each event date, the event date itself,
    and (when a resolution date is given) every session through it.
    """
    resolutions = resolutions or {}
    out: set[date] = set()
    for t in event_dates:
        with suppress(PanelError):
            out.add(panel.prev_session(t))  # first session: nothing before
        end = resolutions.get(t, t)
        s = t
        while True:
            out.add(s)
            if s >= end:
                break
            s = panel.next_session(s)
    return frozenset(out)


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
    for ratio in spec.splits.values():
        if ratio <= 0:
            raise PanelError(f"split ratio must be positive, got {ratio}")


@dataclass
class _LiveLevels:
    """Mutable working copy of the bracket levels (splits adjust them)."""

    limit: float
    stop: float
    target: float
    shares: int

    def apply_split(self, ratio: float) -> None:
        """R05-20: cancel/reissue at the ratio-adjusted quantity and price.

        Fractional shares fail closed: a split that does not divide the
        share count evenly raises instead of inventing cash-in-lieu.
        """
        new_shares = self.shares * ratio
        if abs(new_shares - round(new_shares)) > 1e-9:
            raise PanelError(
                f"split ratio {ratio} on {self.shares} shares would create "
                f"fractional shares ({new_shares}); cash-in-lieu is not "
                "modelled")
        self.limit /= ratio
        self.stop /= ratio
        self.target /= ratio
        self.shares = max(1, int(round(new_shares)))


def _try_entry(panel: Panel, spec: BracketSpec, lv: _LiveLevels,
               buffer: float) -> tuple[Fill | None, str | None, bool, bool]:
    """Entry-session logic.

    Returns (fill, unfilled_reason, corporate_action, split_adjusted).
    """
    split_adj = False
    if spec.entry_session in spec.splits:
        # R05-20: split on the entry session -> reissue at adjusted levels.
        lv.apply_split(spec.splits[spec.entry_session])
        split_adj = True
    if spec.entry_session in spec.blackouts:
        return None, "corporate_action", True, split_adj
    bar = panel.bar(spec.symbol, spec.entry_session)
    if bar is None:
        if panel.is_halt(spec.symbol, spec.entry_session):
            return None, "halted", False, split_adj
        raise PanelError(
            f"{spec.symbol}: missing bar for {spec.entry_session} "
            "(not a declared halt)")
    corp = spec.entry_session in spec.events
    if corp:
        return None, "corporate_action", True, split_adj
    if bar.open <= lv.limit:
        # D-020: fill at open + buffer, never above the limit.
        price = min(bar.open + buffer, lv.limit)
        return Fill(spec.entry_session, price, "entry",
                    gap=bar.open < lv.limit, buffer=buffer), None, False, \
            split_adj
    if bar.low < lv.limit:
        # Strict trade-through: fill at the limit, no price improvement.
        return Fill(spec.entry_session, lv.limit, "entry",
                    gap=False, buffer=buffer), None, False, split_adj
    reason = "touch_only" if bar.low == lv.limit else "no_trade_through"
    return None, reason, False, split_adj


def _stop_fill(session: date, bar: Bar, stop: float,
               buffer: float) -> tuple[Fill, bool]:
    """Stop-market fill on a bar whose low reached the stop."""
    if bar.open < stop:
        return Fill(session, bar.open - buffer, "stop", True, buffer), True
    return Fill(session, stop - buffer, "stop", False, buffer), False


def _holding_session(panel: Panel, symbol: str, lv: _LiveLevels,
                     session: date, buffer: float, is_last: bool,
                     ) -> tuple[Fill | None, bool]:
    """One holding-day event check. Returns (exit_fill, ambiguous)."""
    bar = panel.bar(symbol, session)
    if bar is None:
        # Caller guarantees declared halts are skipped before this call.
        raise PanelError(f"{symbol}: missing bar for {session}")
    stop_hit = bar.low <= lv.stop
    # PREREG §1.1: take-profit fills only if the high is STRICTLY above
    # the target. A high exactly equal to the target is not a fill.
    target_hit = bar.high > lv.target
    if stop_hit and target_hit:
        # Stop-first: deliberate lower bound; report the ambiguity.
        fill, gap = _stop_fill(session, bar, lv.stop, buffer)
        return fill, True
    if stop_hit:
        fill, gap = _stop_fill(session, bar, lv.stop, buffer)
        return fill, False
    if target_hit:
        # Fill at target even when the open gaps above it (R05 rule 13).
        return Fill(session, lv.target, "target", False, buffer), False
    if is_last:
        # 15th session: MOC modeled at the close (R05-18).
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
                    lv: _LiveLevels, buffer: float, corp: bool, split_adj: bool
                    ) -> tuple[Fill, Fill, bool, bool, bool, bool, bool, int]:
    """Run the holding loop.

    Returns (entry_fill, exit_fill, ambiguous, corp_action, late_time_exit,
    exdiv_stop, split_adjusted, sessions_held).
    """
    bar0 = panel.bar(spec.symbol, spec.entry_session)
    if bar0 is None:
        raise PanelError(f"{spec.symbol}: missing entry bar")
    ambiguous = False
    if bar0.low <= lv.stop:
        # Entry-day stop: traversal entry -> stop is implied.
        day0_fill, _ = _stop_fill(spec.entry_session, bar0, lv.stop, buffer)
        exdiv = spec.entry_session in spec.exdiv_dates
        return entry, day0_fill, False, corp, False, exdiv, split_adj, 1
    held, cal_elapsed, session = 1, 0, spec.entry_session
    while True:
        try:
            session = panel.next_session(session)
        except PanelError as exc:
            raise PanelError(
                f"{spec.symbol}: position open at calendar end") from exc
        cal_elapsed += 1
        if panel.bar(spec.symbol, session) is None:
            if not panel.is_halt(spec.symbol, session):
                raise PanelError(
                    f"{spec.symbol}: missing bar for {session} "
                    "(not a declared halt)")
            corp = corp or session in spec.events
            continue  # declared halt: skip, don't count toward the 15
        if session in spec.splits:
            # R05-20: reissue at the ratio-adjusted quantity and price.
            # The entry Fill keeps its original price; _settle uses
            # spec.shares (pre-split) for entry_notional.
            lv.apply_split(spec.splits[session])
            split_adj = True
        held += 1
        corp = corp or session in spec.events
        fill, amb = _holding_session(
            panel, spec.symbol, lv, session, buffer, held >= MAX_HOLD_SESSIONS)
        ambiguous = ambiguous or amb
        if fill is not None:
            # R05-18: if the 15th-session MOC cutoff was missed (a halt
            # pushed the exit past 15 calendar sessions), flag it.
            late = (fill.kind == "time"
                    and cal_elapsed > MAX_HOLD_SESSIONS - 1)
            exdiv = fill.kind == "stop" and session in spec.exdiv_dates
            return entry, fill, ambiguous, corp, late, exdiv, split_adj, held
        if held > MAX_HOLD_SESSIONS + 5:
            raise PanelError(f"{spec.symbol}: exceeded session scan bound")


def _settle(panel: Panel, spec: BracketSpec, lv: _LiveLevels, entry: Fill,
            exit_fill: Fill, spread_frac: float, cost_model_name: str,
            commission_model: str
            ) -> tuple[dict[str, float], dict[str, float], float, float,
                       float]:
    """Costs, P&L, and return for a completed trade."""
    if cost_model_name not in TOD_MULT:
        raise PanelError(f"unknown cost model: {cost_model_name}")
    # Entry notional uses pre-split shares (spec.shares); the entry Fill
    # keeps its original price. Exit uses post-split shares (lv.shares).
    entry_notional = entry.price * spec.shares
    exit_notional = exit_fill.price * lv.shares
    entry_cost = _cost_leg(entry_notional, spec.shares, False,
                           entry.session, panel, commission_model)
    exit_cost = _cost_leg(exit_notional, lv.shares, True,
                          exit_fill.session, panel, commission_model)
    # R06 marketable-exit loss beyond the embedded half-spread. The stop
    # fill already embeds the predeclared buffer; the time (MOC) fill does
    # not, so it also embeds 0.5 × spread × close-TOD-multiplier.
    extra_bp = EXIT_EXTRA_BP[cost_model_name]
    close_mult = TOD_MULT[cost_model_name]["close"]
    addon = 0.0
    if exit_fill.kind == "stop":
        addon = extra_bp * exit_notional
    elif exit_fill.kind == "time":
        addon = (0.5 * spread_frac * close_mult + extra_bp) * exit_notional
    total = (entry_cost["total_dollars"] + exit_cost["total_dollars"] + addon)
    pnl = exit_notional - entry_notional - total
    ret = pnl / entry_notional * 100 if entry_notional else 0.0
    return entry_cost, exit_cost, addon, pnl, ret


def _empty_result(spec: BracketSpec, reason: str | None, corp: bool,
                  split_adj: bool) -> TradeResult:
    return TradeResult(spec, None, None, reason, False, corp, False, False,
                       split_adj, 0, {}, {}, 0.0, 0.0, 0.0)


def simulate_trade(panel: Panel, spec: BracketSpec, buffer: float,
                   spread_frac: float, cost_model_name: str = "conservative",
                   commission_model: str = "modern") -> TradeResult:
    """Run one bracket trade. `buffer` ($/sh) and `spread_frac` are explicit.

    Use trailing_median_spread + estimate_buffer to derive them, or pass
    hand values for synthetic known-answer tests.
    """
    _validate_spec(panel, spec)
    lv = _LiveLevels(limit=spec.limit, stop=spec.stop,
                     target=spec.target, shares=spec.shares)
    entry, reason, corp, split_adj = _try_entry(panel, spec, lv, buffer)
    if entry is None:
        return _empty_result(spec, reason, corp, split_adj)
    entry, exit_fill, ambiguous, corp, late, exdiv, split_adj, held = \
        _holding_period(panel, spec, entry, lv, buffer, corp, split_adj)
    entry_cost, exit_cost, addon, pnl, ret = _settle(
        panel, spec, lv, entry, exit_fill, spread_frac,
        cost_model_name, commission_model)
    return TradeResult(spec, entry, exit_fill, None, ambiguous, corp, late,
                       exdiv, split_adj, held, entry_cost, exit_cost,
                       addon, pnl, ret)
