"""Shadow trade data model."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo


@dataclass
class ShadowTrade:
    trade_id: str = field(default_factory=lambda: str(uuid4()))
    recommendation_id: Optional[str] = None
    ticker: str = ""
    direction: str = "long"
    status: str = "pending"  # pending / open / closed / expired / cancelled
    entry_price: float = 0.0  # target from packet
    stop_price: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    planned_shares: int = 0
    planned_allocation: float = 0.0
    actual_entry_price: Optional[float] = None
    actual_entry_time: Optional[str] = None
    actual_exit_price: Optional[float] = None
    actual_exit_time: Optional[str] = None
    exit_reason: Optional[str] = None  # target_1_hit / target_2_hit / stop_hit / timeout / manual
    pnl_dollars: Optional[float] = None
    pnl_pct: Optional[float] = None
    max_favorable_excursion: Optional[float] = None
    max_adverse_excursion: Optional[float] = None
    duration_days: Optional[int] = None
    earnings_adjacent: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(ZoneInfo("America/New_York")).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(ZoneInfo("America/New_York")).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "recommendation_id": self.recommendation_id,
            "ticker": self.ticker,
            "direction": self.direction,
            "status": self.status,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "planned_shares": self.planned_shares,
            "planned_allocation": self.planned_allocation,
            "actual_entry_price": self.actual_entry_price,
            "actual_entry_time": self.actual_entry_time,
            "actual_exit_price": self.actual_exit_price,
            "actual_exit_time": self.actual_exit_time,
            "exit_reason": self.exit_reason,
            "pnl_dollars": self.pnl_dollars,
            "pnl_pct": self.pnl_pct,
            "max_favorable_excursion": self.max_favorable_excursion,
            "max_adverse_excursion": self.max_adverse_excursion,
            "duration_days": self.duration_days,
            "earnings_adjacent": 1 if self.earnings_adjacent else 0,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
