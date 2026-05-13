"""Tests for CC3 payload wiring: notify_* functions accept payload dataclasses.

Module: tests.notifications.test_telegram_payload_wiring
Purpose: Verify that notify_trade_opened / notify_trade_closed / notify_eod_report /
         notify_weekly_digest accept typed payload dataclasses (not positional kwargs)
         and pass the correct message text to send_telegram.
         Also verifies the full safe_send -> notify_*(payload) -> send_telegram chain.
Called by: pytest
Owns tables: none
Config keys: none
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


def _make_notif_config():
    from src.notifications.policy import NotificationsConfig
    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=False,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
        digest_flush_minutes=60,
    )


def _now_midday():
    return datetime(2026, 5, 12, 12, 0, tzinfo=ET)


# -- Helper payload factories ----------------------------------------------------------------

def _trade_opened_payload():
    from src.notifications.telegram import TradeOpenedPayload
    return TradeOpenedPayload(
        ticker="AAPL",
        entry_price=150.0,
        stop=145.0,
        target=160.0,
        score=82,
        shares=10,
        setup_type="pullback",
        setup_confidence=0.85,
        source="paper",
    )


def _trade_closed_payload():
    from src.notifications.telegram import TradeClosedPayload
    return TradeClosedPayload(
        ticker="MSFT",
        pnl_dollars=75.0,
        pnl_pct=3.5,
        exit_reason="target",
        days_held=4,
        source="paper",
    )


def _eod_report_payload():
    from src.notifications.telegram import EodReportPayload
    return EodReportPayload(
        paper_open=3,
        paper_open_pnl=200.0,
        paper_closed_today=1,
        paper_closed_pnl=75.0,
        live_open=0,
        live_open_pnl=0.0,
        live_closed_today=0,
        live_closed_pnl=0.0,
        win_rate=0.67,
        wins=2,
        losses=1,
        best_ticker="AAPL",
        best_pct=5.0,
        worst_ticker="MSFT",
        worst_pct=-1.0,
        regime="neutral",
        vix=18.0,
        vix_change=0.5,
    )


def _weekly_digest_payload():
    from src.notifications.telegram import WeeklyDigestPayload
    return WeeklyDigestPayload(
        period_start="May 01",
        period_end="May 07",
        opened_paper=3,
        opened_live=1,
        closed_paper=2,
        closed_live=0,
        win_rate=0.75,
        expectancy=50.0,
        best_ticker="AAPL",
        best_pct=5.0,
        worst_ticker="MSFT",
        worst_pct=-2.0,
        pnl_paper=150.0,
        pnl_live=80.0,
        training_start=900,
        training_end=920,
        signal_start=500,
        signal_end=510,
        scoring_backlog=20,
        quality_avg=4.2,
        canary_status="STABLE",
        llm_success_rate=0.98,
        regime="neutral",
        vix=17.5,
        vix_range_low=15.0,
        vix_range_high=20.0,
        spy_weekly_pct=1.2,
        council_sessions=3,
        council_consensus="cautious_long",
        council_avg_confidence=72,
        earnings_next_week=["AAPL"],
        events_next_week=["Fed meeting"],
    )


# -- notify_trade_opened payload wiring -------------------------------------------------------

class TestNotifyTradeOpenedPayloadWiring:
    """notify_trade_opened(payload) accepts a TradeOpenedPayload and calls send_telegram."""

    def test_accepts_payload_object(self):
        """notify_trade_opened called with a TradeOpenedPayload returns True (send mocked)."""
        from src.notifications.telegram import notify_trade_opened
        payload = _trade_opened_payload()
        with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
            result = notify_trade_opened(payload)
        assert result is True
        mock_send.assert_called_once()

    def test_payload_ticker_appears_in_message(self):
        """notify_trade_opened message body contains the payload's ticker."""
        from src.notifications.telegram import notify_trade_opened
        payload = _trade_opened_payload()
        captured = {}
        def fake_send(msg, parse_mode="HTML"):
            captured["msg"] = msg
            return True
        with patch("src.notifications.telegram.send_telegram", side_effect=fake_send):
            notify_trade_opened(payload)
        assert "AAPL" in captured["msg"]

    def test_payload_entry_price_appears_in_message(self):
        """notify_trade_opened message body contains the entry price from payload."""
        from src.notifications.telegram import notify_trade_opened
        payload = _trade_opened_payload()
        captured = {}
        def fake_send(msg, parse_mode="HTML"):
            captured["msg"] = msg
            return True
        with patch("src.notifications.telegram.send_telegram", side_effect=fake_send):
            notify_trade_opened(payload)
        assert "150.00" in captured["msg"]

    def test_positional_args_rejected(self):
        """notify_trade_opened no longer accepts positional kwargs; calling with ticker=str raises TypeError."""
        from src.notifications.telegram import notify_trade_opened
        with pytest.raises(TypeError):
            notify_trade_opened(
                ticker="AAPL", entry_price=150.0, stop=145.0,
                target=160.0, score=82, shares=10
            )


# -- notify_trade_closed payload wiring -------------------------------------------------------

class TestNotifyTradeClosedPayloadWiring:
    """notify_trade_closed(payload) accepts a TradeClosedPayload and calls send_telegram."""

    def test_accepts_payload_object(self):
        """notify_trade_closed called with a TradeClosedPayload returns True (send mocked)."""
        from src.notifications.telegram import notify_trade_closed
        payload = _trade_closed_payload()
        with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
            result = notify_trade_closed(payload)
        assert result is True
        mock_send.assert_called_once()

    def test_payload_ticker_appears_in_message(self):
        """notify_trade_closed message body contains the payload's ticker."""
        from src.notifications.telegram import notify_trade_closed
        payload = _trade_closed_payload()
        captured = {}
        def fake_send(msg, parse_mode="HTML"):
            captured["msg"] = msg
            return True
        with patch("src.notifications.telegram.send_telegram", side_effect=fake_send):
            notify_trade_closed(payload)
        assert "MSFT" in captured["msg"]

    def test_positional_args_rejected(self):
        """notify_trade_closed no longer accepts positional kwargs; raises TypeError."""
        from src.notifications.telegram import notify_trade_closed
        with pytest.raises(TypeError):
            notify_trade_closed(
                ticker="MSFT", pnl_dollars=75.0, pnl_pct=3.5,
                exit_reason="target", days_held=4
            )


# -- notify_eod_report payload wiring ---------------------------------------------------------

class TestNotifyEodReportPayloadWiring:
    """notify_eod_report(payload) accepts an EodReportPayload and calls send_telegram."""

    def test_accepts_payload_object(self):
        """notify_eod_report called with an EodReportPayload returns True (send mocked)."""
        from src.notifications.telegram import notify_eod_report
        payload = _eod_report_payload()
        with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
            result = notify_eod_report(payload)
        assert result is True
        mock_send.assert_called_once()

    def test_payload_best_ticker_appears_in_message(self):
        """notify_eod_report message body contains best_ticker from payload."""
        from src.notifications.telegram import notify_eod_report
        payload = _eod_report_payload()
        captured = {}
        def fake_send(msg, parse_mode="HTML"):
            captured["msg"] = msg
            return True
        with patch("src.notifications.telegram.send_telegram", side_effect=fake_send):
            notify_eod_report(payload)
        assert "AAPL" in captured["msg"]

    def test_positional_args_rejected(self):
        """notify_eod_report no longer accepts positional kwargs; raises TypeError."""
        from src.notifications.telegram import notify_eod_report
        with pytest.raises(TypeError):
            notify_eod_report(
                paper_open=3, paper_open_pnl=200.0,
                paper_closed_today=1, paper_closed_pnl=75.0,
                live_open=0, live_open_pnl=0.0,
                live_closed_today=0, live_closed_pnl=0.0,
                win_rate=0.67, wins=2, losses=1,
                best_ticker="AAPL", best_pct=5.0,
                worst_ticker="MSFT", worst_pct=-1.0,
                regime="neutral", vix=18.0, vix_change=0.5,
            )


# -- notify_weekly_digest payload wiring ------------------------------------------------------

class TestNotifyWeeklyDigestPayloadWiring:
    """notify_weekly_digest(payload) accepts a WeeklyDigestPayload and calls send_telegram."""

    def test_accepts_payload_object(self):
        """notify_weekly_digest called with a WeeklyDigestPayload returns True (send mocked)."""
        from src.notifications.telegram import notify_weekly_digest
        payload = _weekly_digest_payload()
        with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
            result = notify_weekly_digest(payload)
        assert result is True
        mock_send.assert_called_once()

    def test_payload_period_appears_in_message(self):
        """notify_weekly_digest message body contains period dates from payload."""
        from src.notifications.telegram import notify_weekly_digest
        payload = _weekly_digest_payload()
        captured = {}
        def fake_send(msg, parse_mode="HTML"):
            captured["msg"] = msg
            return True
        with patch("src.notifications.telegram.send_telegram", side_effect=fake_send):
            notify_weekly_digest(payload)
        assert "May 01" in captured["msg"]

    def test_positional_args_rejected(self):
        """notify_weekly_digest no longer accepts positional kwargs; raises TypeError."""
        from src.notifications.telegram import notify_weekly_digest
        with pytest.raises(TypeError):
            notify_weekly_digest(
                period_start="May 01", period_end="May 07",
                opened_paper=3, opened_live=1,
                closed_paper=2, closed_live=0,
                win_rate=0.75, expectancy=50.0,
                best_ticker="AAPL", best_pct=5.0,
                worst_ticker="MSFT", worst_pct=-2.0,
                pnl_paper=150.0, pnl_live=80.0,
                training_start=900, training_end=920,
                signal_start=500, signal_end=510,
                scoring_backlog=20, quality_avg=4.2,
                canary_status="STABLE", llm_success_rate=0.98,
                regime="neutral", vix=17.5,
                vix_range_low=15.0, vix_range_high=20.0,
                spy_weekly_pct=1.2,
                council_sessions=3, council_consensus="cautious_long",
                council_avg_confidence=72,
                earnings_next_week=["AAPL"], events_next_week=["Fed"],
            )


# -- safe_send -> notify_*(payload) -> send_telegram chain ------------------------------------

class TestSafeSendPayloadChain:
    """End-to-end: safe_send -> notify_*(payload) -> send_telegram API mock."""

    def test_safe_send_trade_closed_full_chain(self):
        """safe_send('trade_closed', payload=...) routes through notify_trade_closed(payload) to send_telegram."""
        from src.notifications.telegram import TradeClosedPayload
        payload = _trade_closed_payload()
        cfg = _make_notif_config()
        now = _now_midday()
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg), \
             patch("src.notifications.telegram._now_et_for_safe_send", return_value=now), \
             patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send, \
             patch("src.notifications.telegram._write_notification_sent"):
            from src.notifications.telegram import safe_send
            result = safe_send("trade_closed", payload=payload)
        assert result is True
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "MSFT" in msg

    def test_safe_send_trade_opened_full_chain(self):
        """safe_send('trade_opened', payload=...) routes through notify_trade_opened(payload) to send_telegram."""
        from src.notifications.telegram import TradeOpenedPayload
        payload = _trade_opened_payload()
        cfg = _make_notif_config()
        now = _now_midday()
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg), \
             patch("src.notifications.telegram._now_et_for_safe_send", return_value=now), \
             patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send, \
             patch("src.notifications.telegram._write_notification_sent"):
            from src.notifications.telegram import safe_send
            result = safe_send("trade_opened", payload=payload)
        assert result is True
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "AAPL" in msg

    def test_safe_send_eod_report_full_chain(self):
        """safe_send('eod_report', payload=...) routes through notify_eod_report(payload) to send_telegram."""
        payload = _eod_report_payload()
        cfg = _make_notif_config()
        now = _now_midday()
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg), \
             patch("src.notifications.telegram._now_et_for_safe_send", return_value=now), \
             patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send, \
             patch("src.notifications.telegram._write_notification_sent"):
            from src.notifications.telegram import safe_send
            result = safe_send("eod_report", payload=payload)
        assert result is True
        mock_send.assert_called_once()

    def test_safe_send_weekly_digest_full_chain(self):
        """safe_send('weekly_digest', payload=...) routes through notify_weekly_digest(payload) to send_telegram."""
        payload = _weekly_digest_payload()
        cfg = _make_notif_config()
        now = _now_midday()
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch("src.notifications.telegram._load_config_for_safe_send", return_value=cfg), \
             patch("src.notifications.telegram._now_et_for_safe_send", return_value=now), \
             patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send, \
             patch("src.notifications.telegram._write_notification_sent"):
            from src.notifications.telegram import safe_send
            result = safe_send("weekly_digest", payload=payload)
        assert result is True
        mock_send.assert_called_once()


# -- Existing dataclass construction tests (regression guard) ---------------------------------

class TestDataclassConstructionRegression:
    """Regression: original T21b construction tests must still pass after wiring."""

    def test_trade_opened_payload_missing_ticker_raises_typeerror(self):
        from src.notifications.telegram import TradeOpenedPayload
        with pytest.raises(TypeError):
            TradeOpenedPayload(entry_price=100.0, stop=95.0, target=110.0, score=80, shares=10)

    def test_trade_closed_payload_missing_ticker_raises_typeerror(self):
        from src.notifications.telegram import TradeClosedPayload
        with pytest.raises(TypeError):
            TradeClosedPayload(pnl_dollars=50.0, pnl_pct=5.0, exit_reason="target", days_held=3)

    def test_eod_report_payload_missing_all_raises_typeerror(self):
        from src.notifications.telegram import EodReportPayload
        with pytest.raises(TypeError):
            EodReportPayload()

    def test_weekly_digest_payload_missing_all_raises_typeerror(self):
        from src.notifications.telegram import WeeklyDigestPayload
        with pytest.raises(TypeError):
            WeeklyDigestPayload()
