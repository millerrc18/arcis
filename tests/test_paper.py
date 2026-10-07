"""Tests for the Step P paper lane."""

import pytest

from arcis.paper import FillRecord, Signal, signal_to_order
from arcis.paper.calibration import (
    FillTracker,
    calibrate_buffer,
    validate_d020,
)


def _signal() -> Signal:
    from datetime import date
    return Signal(
        symbol="AAPL",
        signal_date=date(2026, 10, 5),
        limit=150.0,
        stop=145.0,
        target=160.0,
        shares=66,
    )


class TestSignalToOrder:
    def test_account_a_uses_limit(self):
        order = signal_to_order(_signal(), "A", 10.0)
        assert order["type"] == "limit"
        assert order["limit_price"] == 150.0
        assert order["qty"] == 66

    def test_account_b_uses_market(self):
        order = signal_to_order(_signal(), "B", 10.0)
        assert order["type"] == "market"
        assert "limit_price" not in order

    def test_account_c_uses_aggressive_limit(self):
        order = signal_to_order(_signal(), "C", 10.0)
        assert order["type"] == "limit"
        assert order["limit_price"] > 150.0

    def test_unknown_account_raises(self):
        with pytest.raises(ValueError, match="unknown account"):
            signal_to_order(_signal(), "Z", 10.0)


class TestFillTracker:
    def _fill(self, account: str, slippage_bp: float) -> FillRecord:
        return FillRecord(
            symbol="AAPL",
            signal_date="2026-10-05",
            account=account,
            order_id="abc123",
            fill_price=150.15,
            fill_qty=66,
            fill_time="2026-10-06T09:35:00",
            signal_price=150.0,
            slippage_bp=slippage_bp,
        )

    def test_record_and_retrieve(self):
        tracker = FillTracker()
        tracker.record(self._fill("A", 10.0))
        tracker.record(self._fill("B", 5.0))
        assert len(tracker.by_account("A")) == 1
        assert len(tracker.by_account("B")) == 1
        assert len(tracker.by_account("C")) == 0

    def test_fill_rate(self):
        tracker = FillTracker()
        tracker.record(self._fill("A", 10.0))
        assert tracker.fill_rate("A", 2) == 0.5
        assert tracker.fill_rate("A", 0) == 0.0

    def test_mean_slippage(self):
        tracker = FillTracker()
        tracker.record(self._fill("A", 10.0))
        tracker.record(self._fill("A", 20.0))
        assert tracker.mean_slippage_bp("A") == 15.0
        assert tracker.mean_slippage_bp("B") == 0.0


class TestCalibration:
    def test_calibrate_buffer(self):
        tracker = FillTracker()
        for bp in [5.0, 10.0, 15.0, 20.0, 100.0]:
            tracker.record(FillRecord(
                symbol="AAPL", signal_date="2026-10-05", account="A",
                order_id="x", fill_price=150.0, fill_qty=66,
                fill_time="t", signal_price=150.0, slippage_bp=bp,
            ))
        report = calibrate_buffer(tracker, "A", 5, buffer_bp=25.0)
        assert report.n_fills == 5
        assert report.fill_rate == 1.0
        assert report.mean_slippage_bp == 30.0
        # 4 of 5 within 25bp buffer
        assert report.buffer_adequate_pct == 80.0

    def test_validate_d020(self):
        tracker = FillTracker()
        result = validate_d020(tracker, "A")
        assert result.account == "A"
        assert result.n_checked == 0
