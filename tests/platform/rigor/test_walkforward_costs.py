"""Tests for R4 — transaction-cost application."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.platform.rigor.walkforward_costs import (
    apply_per_side_cost,
    apply_per_side_cost_batch,
    pnl_gross_vs_net,
    round_trip_cost_bps,
)


@dataclass
class FakeTrade:
    entry_price: float
    exit_price: float
    shares: int | None = 100
    pnl_pct: float | None = None
    pnl_dollars: float | None = None


def test_cost_applied_to_entry_and_exit():
    """0.5 bp per side moves entry up + exit down, net pnl_pct < gross."""
    t = FakeTrade(entry_price=100.0, exit_price=101.0)
    adj = apply_per_side_cost(t, per_side_bps=0.5)
    assert adj.entry_price > 100.0
    assert adj.exit_price < 101.0
    # Gross pnl = 1% = 0.01; net after 1bp total should be ≈ 0.99% - delta.
    assert adj.pnl_pct < 0.01
    assert adj.pnl_pct > 0.0


def test_cost_respects_per_side_half_bp():
    t = FakeTrade(entry_price=100.0, exit_price=100.0)
    adj = apply_per_side_cost(t, per_side_bps=0.5)
    # Entry moves +0.5 bp = 100.005; exit moves -0.5 bp = 99.995.
    assert abs(adj.entry_price - 100.005) < 1e-9
    assert abs(adj.exit_price - 99.995) < 1e-9
    assert adj.pnl_pct < 0  # pure cost, no alpha


def test_cost_applies_pnl_dollars_when_shares_present():
    t = FakeTrade(entry_price=50.0, exit_price=55.0, shares=100)
    adj = apply_per_side_cost(t, per_side_bps=0.5)
    expected = 100 * (adj.exit_price - adj.entry_price)
    assert adj.pnl_dollars is not None
    assert abs(adj.pnl_dollars - expected) < 1e-6


def test_cost_rejects_negative_bps():
    t = FakeTrade(entry_price=100.0, exit_price=100.0)
    with pytest.raises(ValueError, match=">="):
        apply_per_side_cost(t, per_side_bps=-0.1)


def test_cost_passthrough_when_prices_missing():
    """If entry or exit is None, return input unchanged (no silent zero)."""
    t = {"entry_price": None, "exit_price": None}
    adj = apply_per_side_cost(t, per_side_bps=0.5)
    assert adj["entry_price"] is None


def test_cost_input_not_mutated():
    """Returns a new trade — the input object must remain untouched."""
    t = FakeTrade(entry_price=100.0, exit_price=110.0)
    _ = apply_per_side_cost(t, per_side_bps=0.5)
    assert t.entry_price == 100.0
    assert t.exit_price == 110.0
    assert t.pnl_pct is None


def test_batch_order_preserved():
    ts = [
        FakeTrade(entry_price=100.0, exit_price=101.0),
        FakeTrade(entry_price=200.0, exit_price=199.0),
        FakeTrade(entry_price=50.0, exit_price=55.0),
    ]
    adj = apply_per_side_cost_batch(ts, per_side_bps=0.5)
    assert len(adj) == 3
    assert adj[0].entry_price > 100
    assert adj[1].exit_price < 199
    assert adj[2].entry_price > 50


def test_batch_accepts_dicts():
    ts = [
        {"entry_price": 100.0, "exit_price": 101.0, "shares": 10},
    ]
    adj = apply_per_side_cost_batch(ts, per_side_bps=0.5)
    assert adj[0]["entry_price"] > 100
    assert adj[0]["pnl_pct"] < 0.01
    assert "pnl_dollars" in adj[0]


def test_round_trip_cost_is_2x_per_side():
    assert round_trip_cost_bps(0.5) == 1.0
    assert round_trip_cost_bps(2.0) == 4.0


def test_pnl_gross_vs_net_identity():
    """Applying the scalar pnl_gross_vs_net to a trade's gross pnl_pct must
    yield the same net pnl_pct as apply_per_side_cost on a like trade."""
    # Start with a trade where gross = 1%.
    entry = 100.0
    exit_ = 101.0  # 1% gross
    bps = 0.5
    trade = FakeTrade(entry_price=entry, exit_price=exit_)
    adj = apply_per_side_cost(trade, per_side_bps=bps)
    gross = (exit_ - entry) / entry  # 0.01
    net = pnl_gross_vs_net(gross, bps)
    assert abs(net - adj.pnl_pct) < 1e-10


def test_gross_is_strictly_gt_net_for_positive_pnl():
    """R4 guard: any reported pnl that accidentally omits cost is gross > net.
    This inequality check in callers catches the regression."""
    gross = 0.05
    net = pnl_gross_vs_net(gross, per_side_bps=0.5)
    assert net < gross


def test_zero_bps_is_identity():
    trade = FakeTrade(entry_price=100.0, exit_price=110.0)
    adj = apply_per_side_cost(trade, per_side_bps=0.0)
    assert adj.entry_price == 100.0
    assert adj.exit_price == 110.0
