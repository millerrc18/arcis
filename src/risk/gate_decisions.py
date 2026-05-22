"""Register the risk-governor gates as DECISIONs + the governor SYSTEM.

The risk governor's `check_trade` runs an ordered series of pre-trade gates
(traffic_light, event_risk, ... duplicate). Each gate is a strategic decision
about when NOT to take a trade, so each is surfaced as a capability-registry
DECISION named `gate_<emitted_name>`, driven en-bloc from the authoritative
`GOVERNOR_GATES` tuple in `src.risk.governor` (the definition list — Convention
C's oracle). Hand-authoring 11 decorator blocks is error-prone; a metadata
table + loop keeps the gate<->DECISION binding explicit and self-checking.

Also registered here:
- `risk_governor` SYSTEM: health = governor enabled + config sane. Degrades,
  never raises, in a bare/unconfigured worktree (no .env) per design §4.1.
- `decision_drawdown_adjusted_risk` DECISION: Ed Thorp proportional bet
  reduction (`governor.py:drawdown_adjusted_risk`), a strategic sizing fact.

Import-light: only `date`, the `register_*` callables, and the GOVERNOR_GATES
tuple are imported at module top. Heavy governor state is lazy-imported inside
the health function so bootstrap stays cycle-free.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_decision / register_system,
       src.risk.governor.GOVERNOR_GATES
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py (Convention C),
       tests/test_capability_registry_integration.py (end-to-end via bootstrap)
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_decision, register_system
from src.risk.governor import GOVERNOR_GATES

_TODAY = date(2026, 5, 21)

# gate_name -> (decision_text, rationale, revisit_trigger, description)
_GATE_META: dict[str, tuple[str, str, str, str]] = {
    "traffic_light": (
        "Scale or block a trade when the regime traffic-light multiplier "
        "drops below 1.0.",
        "The traffic-light synthesizes regime signals (VIX, breadth) into a "
        "single risk multiplier; sizing down in unfavorable regimes preserves "
        "capital for higher-conviction conditions.",
        "Regime classifier is recalibrated or the multiplier-to-action mapping "
        "is revised.",
        "Risk-governor gate 'traffic_light' in check_trade: regime multiplier "
        "scales or blocks the trade.",
    ),
    "event_risk": (
        "Block or reduce a trade when a known event (earnings, FOMC) sits "
        "inside the holding window.",
        "Event-driven gaps are fat-tailed and not in the strategy's edge; "
        "avoiding them removes a source of uncompensated variance.",
        "Event calendar coverage changes or an event-aware strategy is added.",
        "Risk-governor gate 'event_risk' in check_trade: blocks trades exposed "
        "to scheduled high-impact events.",
    ),
    "deterministic_audit": (
        "Block trading when the deterministic pre-trade audit fails its "
        "invariant checks.",
        "A failed deterministic audit means the system's own state is "
        "internally inconsistent; trading on inconsistent state risks "
        "compounding the error.",
        "Audit invariant set is expanded or the two-layer staleness behavior "
        "changes.",
        "Risk-governor gate 'deterministic_audit' in check_trade: blocks trades "
        "when the deterministic audit fails.",
    ),
    "emergency_halt": (
        "Reject all trades while the emergency kill-switch is engaged.",
        "A manual or automated emergency halt is the operator's last line of "
        "defense; it must hard-block entries regardless of other signals.",
        "Kill-switch trigger conditions or the resume protocol change.",
        "Risk-governor gate 'emergency_halt' in check_trade: rejects trades "
        "while the kill switch is engaged.",
    ),
    "daily_loss": (
        "Halt new entries once the realized daily loss breaches its limit.",
        "A daily-loss circuit breaker caps the worst-case single-session "
        "drawdown and prevents revenge trading after a bad open.",
        "Daily-loss limit is retuned or moved from realized to mark-to-market.",
        "Risk-governor gate 'daily_loss' in check_trade: halts entries past the "
        "daily realized-loss limit.",
    ),
    "position_size": (
        "Reject a trade whose position size exceeds the per-position risk cap.",
        "Bounding single-position size limits idiosyncratic blow-up risk and "
        "keeps the portfolio inside its risk budget.",
        "Per-position sizing model (fixed-fractional vs. volatility-scaled) is "
        "changed.",
        "Risk-governor gate 'position_size' in check_trade: rejects oversized "
        "positions.",
    ),
    "max_positions": (
        "Reject a new entry when the open-position count is at its ceiling.",
        "Capping concurrent positions bounds gross exposure and keeps "
        "monitoring/exit workload tractable.",
        "Capital base grows enough to justify a higher concurrency ceiling.",
        "Risk-governor gate 'max_positions' in check_trade: blocks new entries "
        "at the open-position ceiling.",
    ),
    "sector_concentration": (
        "Reject a trade that would push sector exposure past its concentration "
        "limit.",
        "Sector caps prevent a single macro/sector shock from dominating "
        "portfolio P&L — diversification of risk, not just names.",
        "Sector taxonomy or the concentration threshold is revised.",
        "Risk-governor gate 'sector_concentration' in check_trade: blocks "
        "sector over-concentration.",
    ),
    "correlation": (
        "Reject a trade too correlated with existing open positions.",
        "Highly correlated positions behave as one larger position under "
        "stress; the correlation gate keeps true diversification intact.",
        "Correlation lookback window or the correlation threshold is retuned.",
        "Risk-governor gate 'correlation' in check_trade: blocks entries highly "
        "correlated with open positions.",
    ),
    "volatility_halt": (
        "Halt entries when market volatility exceeds the governor's ceiling.",
        "Extreme-volatility regimes widen spreads and gap risk beyond the "
        "strategy's modeled edge; standing aside is the conservative choice.",
        "Volatility ceiling is recalibrated or made regime-conditional.",
        "Risk-governor gate 'volatility_halt' in check_trade: halts entries in "
        "extreme-volatility regimes.",
    ),
    "duplicate": (
        "Reject a trade that duplicates an already-open position in the same "
        "symbol/side.",
        "Duplicate entries unintentionally double exposure and complicate exit "
        "bracket management; one position per symbol/side keeps accounting "
        "clean.",
        "Strategy intentionally supports scaling into an existing position.",
        "Risk-governor gate 'duplicate' in check_trade: rejects duplicate "
        "open positions for the same symbol/side.",
    ),
}

# F-min-2: completeness check — a missing/extra key fails loudly at import with
# a precise message, never a bare KeyError deep inside the registration loop.
assert set(_GATE_META) == set(GOVERNOR_GATES), (
    "_GATE_META keys must exactly match GOVERNOR_GATES. "
    f"missing={set(GOVERNOR_GATES) - set(_GATE_META)} "
    f"extra={set(_GATE_META) - set(GOVERNOR_GATES)}"
)

for _gate in GOVERNOR_GATES:
    _text, _why, _revisit, _desc = _GATE_META[_gate]
    register_decision(
        name=f"gate_{_gate}",
        description=_desc,
        category="risk-governor",
        version="1.0",
        maintainer="ai_session",
        introduced_in="v0.36.49",
        last_reviewed_date=_TODAY,
        decision_text=_text,
        rationale=_why,
        revisit_trigger=_revisit,
    )


def _risk_governor_health() -> dict:
    """Health of the risk governor: enabled + config readable.

    Degrade-not-raise: in a bare/unconfigured worktree (no .env, no governor
    config) this returns a degraded status dict rather than propagating, so the
    bare-env health-executes test (design §7) passes.
    """
    try:
        from src.risk.governor import RiskGovernor
        governor = RiskGovernor()
        enabled = bool(getattr(governor, "enabled", True))
    except Exception as exc:  # noqa: BLE001 — bare-env tolerant per design §4.1
        return {
            "status": "degraded",
            "detail": f"governor config unavailable: {exc}",
        }
    if enabled:
        return {
            "status": "ok",
            "detail": "risk governor enabled; deny-by-default gates active",
        }
    return {
        "status": "degraded",
        "detail": "risk governor disabled — pre-trade gates not enforced",
    }


register_system(
    name="risk_governor",
    description=(
        "Pre-trade risk governor: runs the ordered GOVERNOR_GATES checks in "
        "check_trade (traffic_light, event_risk, emergency_halt, daily_loss, "
        "position_size, ... duplicate) and denies by default on failure. "
        "Health proxy: governor enabled + config readable."
    ),
    category="risk-governor",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.36.49",
    last_reviewed_date=_TODAY,
    expected_runtime="synchronous per trade evaluation",
)(_risk_governor_health)


register_decision(
    name="decision_drawdown_adjusted_risk",
    description=(
        "Ed Thorp graduated drawdown reduction (proportional bet sizing) in "
        "governor.drawdown_adjusted_risk: scale base risk down linearly as "
        "drawdown deepens, reaching 0% at the max-tolerable drawdown."
    ),
    category="risk-governor",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.36.49",
    last_reviewed_date=_TODAY,
    decision_text=(
        "Reduce position risk proportionally to current drawdown: 100% of base "
        "risk at 0% DD, 50% at 10% DD, 0% (stop trading) at the 20% max-DD "
        "default."
    ),
    rationale=(
        "Per A Man for All Markets / Kelly literature, cutting bet size as "
        "drawdown deepens avoids the martingale trap of increasing size to "
        "recover losses, and guarantees the system stops before ruin."
    ),
    revisit_trigger=(
        "Transition from paper to live capital (the 20% max-DD default is "
        "conservative for paper trading and will be reviewed), or a switch to "
        "full-Kelly/fractional-Kelly sizing policy."
    ),
)
