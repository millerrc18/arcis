"""Tests that llm_conviction_reason and llm_timeout_days are wired from the
packet through to log_recommendation in scan_service and mr_scan_service.

Strategy: inspect the call sites at the module level using AST/source analysis
and verify that log_recommendation's signature in store.py accepts the new kwargs.
Also verify TradePacket carries the new field.
"""

import ast
import inspect
import textwrap

import pytest

from src.schemas import TradePacket, PositionSizing
from src.journal.store import log_recommendation


def _make_packet(conviction_reason=None, timeout_days=None):
    sizing = PositionSizing(
        allocation_dollars=5000.0,
        allocation_pct=5.0,
        estimated_risk_dollars=250.0,
    )
    packet = TradePacket(
        ticker="AAPL",
        company_name="Apple Inc.",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Price pulled back to 50-day MA.",
        entry_zone="185-187",
        stop_invalidation="181",
        targets="195/202",
        expected_hold_period="5-10 days",
        confidence=7,
        event_risk="Normal",
        position_sizing=sizing,
        deeper_analysis="Paragraph one.\n\nParagraph two.",
        llm_conviction=8,
        llm_conviction_reason=conviction_reason,
        llm_timeout_days=timeout_days,
    )
    return packet


class TestLogRecommendationSignature:
    def test_log_recommendation_accepts_llm_conviction_reason(self):
        """store.log_recommendation signature has llm_conviction_reason param."""
        sig = inspect.signature(log_recommendation)
        assert "llm_conviction_reason" in sig.parameters, (
            "log_recommendation missing llm_conviction_reason parameter"
        )

    def test_log_recommendation_accepts_llm_timeout_days(self):
        """store.log_recommendation signature has llm_timeout_days param."""
        sig = inspect.signature(log_recommendation)
        assert "llm_timeout_days" in sig.parameters, (
            "log_recommendation missing llm_timeout_days parameter"
        )

    def test_llm_conviction_reason_defaults_to_none(self):
        """llm_conviction_reason default is None (won't block trades when absent)."""
        sig = inspect.signature(log_recommendation)
        param = sig.parameters["llm_conviction_reason"]
        assert param.default is None

    def test_llm_timeout_days_defaults_to_none(self):
        """llm_timeout_days default is None (won't block trades when absent)."""
        sig = inspect.signature(log_recommendation)
        param = sig.parameters["llm_timeout_days"]
        assert param.default is None


class TestTradePacketFields:
    def test_trade_packet_has_llm_conviction_reason(self):
        """TradePacket carries llm_conviction_reason field."""
        packet = _make_packet(conviction_reason="Earnings risk.", timeout_days=14)
        assert packet.llm_conviction_reason == "Earnings risk."

    def test_trade_packet_has_llm_timeout_days(self):
        """TradePacket carries llm_timeout_days field."""
        packet = _make_packet(conviction_reason=None, timeout_days=14)
        assert packet.llm_timeout_days == 14

    def test_trade_packet_llm_fields_default_to_none(self):
        """Both new TradePacket fields default to None."""
        sizing = PositionSizing(
            allocation_dollars=5000.0, allocation_pct=5.0, estimated_risk_dollars=250.0
        )
        packet = TradePacket(
            ticker="TSLA", company_name="Tesla", recommendation="BUY",
            setup_type="pullback", why_now="Setup.", entry_zone="200",
            stop_invalidation="190", targets="210/220",
            expected_hold_period="5-10 days", confidence=7,
            event_risk="Normal", position_sizing=sizing, deeper_analysis="Analysis.",
        )
        assert packet.llm_conviction_reason is None
        assert packet.llm_timeout_days is None


class TestScanServiceCallSite:
    """Verify scan_service.py log_recommendation call passes both new fields."""

    def _get_log_recommendation_calls(self, source_path: str) -> list[ast.Call]:
        """Extract all log_recommendation(...) AST call nodes from a source file."""
        with open(source_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name == "log_recommendation":
                    calls.append(node)
        return calls

    def _kwarg_names(self, call_node: ast.Call) -> set[str]:
        return {kw.arg for kw in call_node.keywords if kw.arg is not None}

    def test_scan_service_passes_llm_conviction_reason(self):
        """scan_service.py log_recommendation call includes llm_conviction_reason kwarg."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "services", "scan_service.py"
        )
        calls = self._get_log_recommendation_calls(path)
        assert calls, "No log_recommendation call found in scan_service.py"
        kwarg_sets = [self._kwarg_names(c) for c in calls]
        assert any("llm_conviction_reason" in kws for kws in kwarg_sets), (
            f"llm_conviction_reason not passed in any log_recommendation call. "
            f"Found kwargs: {kwarg_sets}"
        )

    def test_scan_service_passes_llm_timeout_days(self):
        """scan_service.py log_recommendation call includes llm_timeout_days kwarg."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "services", "scan_service.py"
        )
        calls = self._get_log_recommendation_calls(path)
        kwarg_sets = [self._kwarg_names(c) for c in calls]
        assert any("llm_timeout_days" in kws for kws in kwarg_sets), (
            f"llm_timeout_days not passed in any log_recommendation call. "
            f"Found kwargs: {kwarg_sets}"
        )

    def test_mr_scan_service_passes_llm_conviction_reason(self):
        """mr_scan_service.py log_recommendation call includes llm_conviction_reason kwarg."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "services", "mr_scan_service.py"
        )
        calls = self._get_log_recommendation_calls(path)
        assert calls, "No log_recommendation call found in mr_scan_service.py"
        kwarg_sets = [self._kwarg_names(c) for c in calls]
        assert any("llm_conviction_reason" in kws for kws in kwarg_sets), (
            f"llm_conviction_reason not passed in mr_scan_service. Found kwargs: {kwarg_sets}"
        )

    def test_mr_scan_service_passes_llm_timeout_days(self):
        """mr_scan_service.py log_recommendation call includes llm_timeout_days kwarg."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "services", "mr_scan_service.py"
        )
        calls = self._get_log_recommendation_calls(path)
        kwarg_sets = [self._kwarg_names(c) for c in calls]
        assert any("llm_timeout_days" in kws for kws in kwarg_sets), (
            f"llm_timeout_days not passed in mr_scan_service. Found kwargs: {kwarg_sets}"
        )
