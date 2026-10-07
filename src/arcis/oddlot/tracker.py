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
from datetime import datetime, timezone
from enum import Enum

from .reader import OfferTerms, OddLotOpportunity


class OppStatus(str, Enum):
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
    """Run the pre-trade checklist. All failures must be resolved before trading.

    Args:
        opp: the opportunity to check
        account_capital: total account equity
        max_position_pct: max fraction of account per position (default 50%)
    """
    failures: list[str] = []
    warnings: list[str] = []

    t = opp.terms

    # 1. Odd-lot priority must be explicitly confirmed
    if not t.has_oddlot_priority:
        failures.append(
            "Odd-lot priority NOT confirmed in offer document. Do not trade."
        )

    # 2. Must have a price
    if not t.effective_price:
        failures.append("No offer price extractable from document.")

    # 3. Must have expiration
    if not t.expiration_date:
        failures.append("No expiration date found.")

    # 4. Spread must be positive after estimated costs
    # Assume $1 commission + 5bp slippage each way as conservative estimate
    if opp.gross_spread_per_share and opp.gross_spread_per_share <= 0:
        failures.append(
            f"Negative spread: offer {t.effective_price} vs market "
            f"{opp.current_price}. No edge."
        )

    # 5. Capital check
    capital_needed = opp.capital_required
    if capital_needed and capital_needed > account_capital * max_position_pct:
        failures.append(
            f"Capital required ${capital_needed:,.2f} exceeds "
            f"{max_position_pct:.0%} of account (${account_capital:,.2f})."
        )
    if capital_needed and capital_needed > account_capital:
        failures.append("Insufficient capital for 99-share position.")

    # 6. Risk flags from document reading
    for flag in t.risk_flags:
        warnings.append(f"Document risk flag: {flag}")

    # 7. Dutch auction warning (price uncertainty)
    if t.is_dutch_auction:
        warnings.append(
            "Dutch auction: final price may clear below the range high. "
            f"Using range low ${t.price_range_low} for profit estimate."
        )

    # 8. Expiration timeline sanity
    if t.expiration_date:
        try:
            exp = datetime.strptime(t.expiration_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            now = datetime.now(timezone.utc)
            days_left = (exp - now).days
            if days_left < 0:
                failures.append("Offer already expired.")
            elif days_left < 3:
                warnings.append(
                    f"Only {days_left} days to expiration — settlement risk."
                )
        except ValueError:
            warnings.append(f"Could not parse expiration: {t.expiration_date}")

    return ChecklistResult(
        passed=len(failures) == 0,
        failures=failures,
        warnings=warnings,
    )


@dataclass
class TrackedOpportunity:
    """An opportunity moving through the lifecycle."""

    opp: OddLotOpportunity
    status: OppStatus = OppStatus.IDENTIFIED
    checklist: ChecklistResult | None = None
    notes: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
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
        """Move to a new lifecycle status with audit trail."""
        # Validate transitions
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
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if note:
            self.notes.append(f"[{self.updated_at}] {note}")

    def to_dict(self) -> dict:
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
