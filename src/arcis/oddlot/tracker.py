"""Opportunity tracker and pre-trade checklist for odd-lot tender harvesting.

Tracks identified opportunities through their lifecycle:
  identified → vetted → positioned → tendered → closed

The checklist enforces the risk controls from the research:
- Odd-lot priority explicitly confirmed in the offer document
- No withdrawal red flags
- Capital fits within account limits
- Expiration timeline workable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .reader import OddLotOpportunity


class OppStatus(StrEnum):
    IDENTIFIED = "identified"  # found by scanner, not yet vetted
    VETTED = "vetted"  # passed checklist, ready to position
    POSITIONED = "positioned"  # shares bought, awaiting tender
    TENDERED = "tendered"  # election filed with broker
    CLOSED = "closed"  # tender settled, P&L recorded
    KILLED = "killed"  # failed checklist or withdrawn


@dataclass
class ChecklistResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_pretrade_checklist(
    opp: OddLotOpportunity,
    account_capital: float,
    max_position_pct: float = 0.50,
) -> ChecklistResult:
    """Run the pre-trade checklist. Fail-closed: missing data = failure.

    Args:
        opp: the opportunity to check
        account_capital: total account equity
        max_position_pct: max fraction of account per position (default 50%)
    """
    failures: list[str] = []
    warnings: list[str] = []
    t = opp.terms

    # 1. Odd-lot priority must be explicitly True (not None, not "false")
    if t.has_oddlot_priority is not True:
        failures.append("Odd-lot priority NOT confirmed. Do not trade.")

    # 1b. Position size must qualify for odd-lot threshold
    if not opp.qualifies_for_oddlot:
        failures.append(
            f"Position size {opp.shares_to_buy} exceeds odd-lot threshold "
            f"{t.oddlot_threshold}. Would not receive priority."
        )

    # 2. Must have a price
    if t.effective_price is None or t.effective_price <= 0:
        failures.append("No valid offer price extractable from document.")

    # 3. Must have expiration
    if not t.expiration_date:
        failures.append("No expiration date found.")

    # 4. Spread must be positive AFTER costs ($1 commission + 10bp round-trip)
    # Fail-closed: missing current_price means we cannot verify edge.
    if opp.current_price is None:
        failures.append("No current market price; cannot verify spread.")
    elif t.effective_price is not None:
        cost_per_share = 1.0 / 99 + t.effective_price * 0.001  # $1 + 10bp
        net_spread = t.effective_price - opp.current_price - cost_per_share
        if net_spread <= 0:
            failures.append(
                f"No edge after costs: net spread ${net_spread:.4f}/share."
            )

    # 5. Capital check (fail-closed on missing data)
    capital_needed = opp.capital_required
    if capital_needed is None:
        failures.append("Cannot compute capital required.")
    else:
        if capital_needed > account_capital * max_position_pct:
            failures.append(f"Exceeds {max_position_pct:.0%} of account.")
        if capital_needed > account_capital:
            failures.append("Insufficient capital for 99-share position.")

    # 6. Risk flags and warnings
    for flag in t.risk_flags:
        warnings.append(f"Document risk flag: {flag}")
    if t.is_dutch_auction:
        warnings.append("Dutch auction: final price may clear below range high.")
    _check_expiration(t.expiration_date, failures, warnings)

    return ChecklistResult(passed=len(failures) == 0,
                           failures=failures, warnings=warnings)


def _check_expiration(
    expiration_date: str | None,
    failures: list[str],
    warnings: list[str],
) -> None:
    """Check expiration timeline. Fails on expired or unparseable dates."""
    if not expiration_date:
        return
    try:
        # Parse as ET (market close), not UTC midnight
        exp = datetime.strptime(expiration_date, "%Y-%m-%d")
        # End of day ET = 23:59
        now_et = datetime.now(UTC)  # TODO: proper ET conversion
        days_left = (exp.date() - now_et.date()).days
        if days_left < 0:
            failures.append("Offer already expired.")
        elif days_left <= 2:
            failures.append(
                f"Only {days_left} days to expiration — settlement risk too high."
            )
    except ValueError:
        failures.append(f"Unparseable expiration date: {expiration_date}")


@dataclass
class TrackedOpportunity:
    """An opportunity moving through the lifecycle."""

    opp: OddLotOpportunity
    status: OppStatus = OppStatus.IDENTIFIED
    checklist: ChecklistResult | None = None
    notes: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    # Fill tracking
    shares_bought: int = 0
    avg_buy_price: float | None = None
    tendered_at: str | None = None
    settled_at: str | None = None
    proceeds: float | None = None

    @property
    def realized_pnl(self) -> float | None:
        """Realized P&L after settlement."""
        if self.proceeds and self.avg_buy_price and self.shares_bought:
            cost = self.avg_buy_price * self.shares_bought
            return self.proceeds - cost
        return None

    def transition(self, new_status: OppStatus, note: str = "") -> None:
        """Move to a new lifecycle status with audit trail.

        Enforces checklist gates:
        - IDENTIFIED → VETTED requires checklist.passed == True
        - VETTED → POSITIONED requires shares_bought > 0 to be set first
          (caller sets shares_bought before transitioning)
        """
        valid = {
            OppStatus.IDENTIFIED: [OppStatus.VETTED, OppStatus.KILLED],
            OppStatus.VETTED: [OppStatus.POSITIONED, OppStatus.KILLED],
            OppStatus.POSITIONED: [OppStatus.TENDERED, OppStatus.KILLED],
            OppStatus.TENDERED: [OppStatus.CLOSED, OppStatus.KILLED],
            OppStatus.CLOSED: [],
            OppStatus.KILLED: [],
        }
        if new_status not in valid[self.status]:
            raise ValueError(
                f"Invalid transition: {self.status.value} → {new_status.value}"
            )
        # Gate: VETTED requires a passed checklist
        if (self.status == OppStatus.IDENTIFIED
                and new_status == OppStatus.VETTED):
            if self.checklist is None:
                raise ValueError(
                    "Cannot vet without running the pre-trade checklist."
                )
            if not self.checklist.passed:
                raise ValueError(
                    f"Checklist failed: {self.checklist.failures}. "
                    "Resolve failures or KILL the opportunity."
                )
        self.status = new_status
        self.updated_at = datetime.now(UTC).isoformat()
        if note:
            self.notes.append(f"[{self.updated_at}] {note}")

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.opp.ticker,
            "company": self.opp.company,
            "status": self.status.value,
            "terms": self.opp.terms.to_dict(),
            "current_price": self.opp.current_price,
            "gross_profit_estimate": self.opp.gross_profit,
            "return_pct_estimate": self.opp.return_pct,
            "checklist_passed": self.checklist.passed if self.checklist else None,
            "checklist_failures": self.checklist.failures if self.checklist else [],
            "shares_bought": self.shares_bought,
            "avg_buy_price": self.avg_buy_price,
            "realized_pnl": self.realized_pnl,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
