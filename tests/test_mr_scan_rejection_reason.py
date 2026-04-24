"""#511 — MR scan must capture WHY each candidate was rejected.

Pre-#511, mr_scan_service.py logged "Scan complete: 5 candidates, 0 trades
opened" with no per-candidate diagnostic. Operators couldn't tell whether
rejection was BP, position-cap, sector-cap, governor halt, dup-check, or
something else.

Post-fix, each candidate's rejection (if any) is captured in the result
list with a `rejection_reason` field, AND a [MR] log line per rejection
includes the reason.
"""
import logging
from unittest.mock import patch, MagicMock

import pytest


def test_rejection_reason_captured_in_result():
    """When open_shadow_trade rejects, the reason appears in the candidate result."""
    from src.services.mr_scan_service import run_mr_scan

    config = {
        "shadow_trading": {"enabled": True},
        "strategies": {
            "mean_reversion": {"enabled": True, "paper_only": True},
        },
    }
    fake_candidate = {
        "ticker": "AAPL",
        "score": 95,
        "features": {"current_price": 150.0, "rsi_2": 5, "atr_14": 1.5},
    }
    with patch("src.shadow_trading.executor.reset_scan_cycle_committed"), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": MagicMock()}), \
         patch("src.features.mean_reversion.scan_for_mr_candidates",
               return_value=[fake_candidate]), \
         patch("src.shadow_trading.executor._check_paper_buying_power_allocation",
               return_value=True), \
         patch("src.shadow_trading.executor.open_shadow_trade_with_reason",
               return_value=(None, "Position size: $4800 is 96% of equity, exceeds 10% limit")), \
         patch("src.packets.template.build_packet_from_features") as mock_packet, \
         patch("src.llm.packet_writer.enhance_packet_with_llm") as mock_enhance, \
         patch("src.journal.store.log_recommendation", return_value="rec-1"), \
         patch("src.training.versioning.get_active_model_name", return_value="v1.0.0"):
        mock_packet.return_value = MagicMock(position_sizing=MagicMock(allocation_dollars=100.0))
        mock_enhance.return_value = mock_packet.return_value

        result = run_mr_scan(config=config)

    assert result["trades_opened"] == 0
    rejected = [r for r in result["results"] if r["action"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["ticker"] == "AAPL"
    assert "Position size" in rejected[0]["rejection_reason"]


def test_rejection_logged_with_reason(caplog):
    """[MR] log line on rejection must include the rejection reason."""
    from src.services.mr_scan_service import run_mr_scan

    config = {
        "shadow_trading": {"enabled": True},
        "strategies": {
            "mean_reversion": {"enabled": True},
        },
    }
    fake_candidate = {"ticker": "MSFT", "score": 80, "features": {"current_price": 300.0, "rsi_2": 8}}
    with patch("src.shadow_trading.executor.reset_scan_cycle_committed"), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["MSFT"]), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"MSFT": MagicMock()}), \
         patch("src.features.mean_reversion.scan_for_mr_candidates",
               return_value=[fake_candidate]), \
         patch("src.shadow_trading.executor._check_paper_buying_power_allocation",
               return_value=True), \
         patch("src.shadow_trading.executor.open_shadow_trade_with_reason",
               return_value=(None, "Volatility circuit breaker: VIX proxy at 38.0% exceeds 35% threshold")), \
         patch("src.packets.template.build_packet_from_features") as mp, \
         patch("src.llm.packet_writer.enhance_packet_with_llm") as me, \
         patch("src.journal.store.log_recommendation", return_value="rec-2"), \
         patch("src.training.versioning.get_active_model_name", return_value="v1.0.0"):
        mp.return_value = MagicMock(position_sizing=MagicMock(allocation_dollars=100.0))
        me.return_value = mp.return_value

        with caplog.at_level(logging.INFO):
            run_mr_scan(config=config)

    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "MSFT" in msgs
    assert "Volatility circuit breaker" in msgs, (
        f"Expected rejection reason in log, got:\n{msgs}"
    )
