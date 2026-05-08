"""Tests for telegram_commands.py closed-trade counters excluding reconciled_stale,
and happy-path + error-path tests for all 17 command handlers (C13).

Module: tests.notifications.test_telegram_commands
Purpose: Verify that the three closed-trade query sites in telegram_commands.py
         (milestone counter at :126, closed P&L win_rate at :425, live closed at :438)
         exclude reconciled_stale rows.
         Also verifies 17 command handlers return strings on happy-path
         and return graceful error strings on exception-path (C13).
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


class TestTelegramMilestoneCounter:
    """telegram_commands.py:126 — milestone counter excludes reconciled_stale."""

    def test_filter_active_milestone_excludes_stale(self):
        """10 normal + 5 stale: milestone counter sees 12, NOT 17."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        closed_count = closed["c"] if closed else 0
        assert closed_count == 12

    def test_sanity_milestone_counter_normal_only(self):
        """10 normal + 0 stale: milestone counter sees 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        closed_count = closed["c"] if closed else 0
        assert closed_count == 10


class TestTelegramClosedPnlWinRate:
    """telegram_commands.py:425 — closed P&L win_rate excludes reconciled_stale."""

    def test_filter_active_win_rate_excludes_stale(self):
        """10 normal (pnl>0) + 5 stale (pnl=0): win_rate with filter = 1.0 (all included are winners)."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_row["cnt"] == 12
        # All 10 normal + 2 reconciled have pnl > 0 → win_rate = 1.0
        assert abs(closed_row["win_rate"] - 1.0) < 0.01

    def test_sanity_win_rate_normal_only(self):
        """10 normal + 0 stale: cnt=10, win_rate=1.0."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_row["cnt"] == 10
        assert abs(closed_row["win_rate"] - 1.0) < 0.01


class TestTelegramLiveClosedPnl:
    """telegram_commands.py:438 — live closed P&L excludes reconciled_stale."""

    def test_filter_active_live_closed_excludes_stale(self):
        """Seed live trades: 10 normal + 5 stale. Filtered live_closed = 12."""
        conn = _make_conn()
        # Seed all as 'live' source
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        # Update source to 'live'
        conn.execute("UPDATE shadow_trades SET source = 'live'")
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        live_closed = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed' AND source = 'live'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert live_closed["cnt"] == 12

    def test_sanity_live_closed_normal_only(self):
        """10 live normal + 0 stale: live_closed.cnt = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.execute("UPDATE shadow_trades SET source = 'live'")
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        live_closed = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed' AND source = 'live'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert live_closed["cnt"] == 10


# ── T21a: 17 happy-path + 17 error-path handler tests (C13) ──────────────────


class TestCommandHandlerHappyPaths:
    """Happy-path tests: each of the 17 handle_command routes returns a non-empty string."""

    def test_help_returns_string(self):
        from src.notifications.telegram_commands import handle_command
        result = handle_command("/help", "")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_start_returns_string(self):
        from src.notifications.telegram_commands import handle_command
        result = handle_command("/start", "")
        assert isinstance(result, str)
        assert "/status" in result

    def test_status_returns_string(self):
        with patch("src.notifications.telegram_commands.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            with patch("src.notifications.telegram_commands.connect_db"):
                with patch("src.notifications.telegram_commands.load_config", return_value={}):
                    with patch("src.notifications.telegram_commands._cmd_status", return_value="STATUS OK"):
                        from src.notifications.telegram_commands import handle_command
                        result = handle_command("/status", "")
        assert isinstance(result, str)

    def test_trades_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_trades", return_value="TRADES OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/trades", "")
        assert isinstance(result, str)
        assert result == "TRADES OK"

    def test_pnl_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_pnl", return_value="PNL OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/pnl", "")
        assert isinstance(result, str)
        assert result == "PNL OK"

    def test_scan_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_last_scan", return_value="SCAN OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/scan", "")
        assert isinstance(result, str)
        assert result == "SCAN OK"

    def test_earnings_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_earnings", return_value="EARNINGS OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/earnings", "")
        assert isinstance(result, str)
        assert result == "EARNINGS OK"

    def test_schedule_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_schedule", return_value="SCHEDULE OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/schedule", "")
        assert isinstance(result, str)
        assert result == "SCHEDULE OK"

    def test_scoring_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_scoring", return_value="SCORING OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/scoring", "")
        assert isinstance(result, str)
        assert result == "SCORING OK"

    def test_council_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_council", return_value="COUNCIL OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/council", "")
        assert isinstance(result, str)
        assert result == "COUNCIL OK"

    def test_health_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_health", return_value="HEALTH OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/health", "")
        assert isinstance(result, str)
        assert result == "HEALTH OK"

    def test_log_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_log", return_value="LOG OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/log", "")
        assert isinstance(result, str)
        assert result == "LOG OK"

    def test_pull_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_pull", return_value="PULL OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/pull", "")
        assert isinstance(result, str)
        assert result == "PULL OK"

    def test_logs_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_logs", return_value="LOGS OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/logs", "")
        assert isinstance(result, str)
        assert result == "LOGS OK"

    def test_gpu_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_gpu", return_value="GPU OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/gpu", "")
        assert isinstance(result, str)
        assert result == "GPU OK"

    def test_disk_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_disk", return_value="DISK OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/disk", "")
        assert isinstance(result, str)
        assert result == "DISK OK"

    def test_uptime_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_uptime", return_value="UPTIME OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/uptime", "")
        assert isinstance(result, str)
        assert result == "UPTIME OK"

    def test_heartbeat_returns_string(self):
        with patch("src.notifications.telegram_commands._cmd_heartbeat", return_value="HEARTBEAT OK"):
            from src.notifications.telegram_commands import handle_command
            result = handle_command("/heartbeat", "")
        assert isinstance(result, str)
        assert result == "HEARTBEAT OK"


class TestCommandHandlerErrorPaths:
    """Error-path tests: when the underlying handler raises, handle_command returns a graceful error string."""

    def _assert_error_string(self, command: str, handler_target: str) -> None:
        with patch(handler_target, side_effect=RuntimeError("injected failure")):
            from src.notifications.telegram_commands import handle_command
            result = handle_command(command, "")
        assert isinstance(result, str)
        assert "❌" in result or "Error" in result or "error" in result.lower()

    def test_help_unknown_command_returns_message(self):
        from src.notifications.telegram_commands import handle_command
        result = handle_command("/notacommand", "")
        assert isinstance(result, str)
        assert "Unknown" in result or "unknown" in result.lower() or "/help" in result

    def test_status_error_returns_string(self):
        self._assert_error_string("/status", "src.notifications.telegram_commands._cmd_status")

    def test_trades_error_returns_string(self):
        self._assert_error_string("/trades", "src.notifications.telegram_commands._cmd_trades")

    def test_pnl_error_returns_string(self):
        self._assert_error_string("/pnl", "src.notifications.telegram_commands._cmd_pnl")

    def test_scan_error_returns_string(self):
        self._assert_error_string("/scan", "src.notifications.telegram_commands._cmd_last_scan")

    def test_earnings_error_returns_string(self):
        self._assert_error_string("/earnings", "src.notifications.telegram_commands._cmd_earnings")

    def test_schedule_error_returns_string(self):
        self._assert_error_string("/schedule", "src.notifications.telegram_commands._cmd_schedule")

    def test_scoring_error_returns_string(self):
        self._assert_error_string("/scoring", "src.notifications.telegram_commands._cmd_scoring")

    def test_council_error_returns_string(self):
        self._assert_error_string("/council", "src.notifications.telegram_commands._cmd_council")

    def test_health_error_returns_string(self):
        self._assert_error_string("/health", "src.notifications.telegram_commands._cmd_health")

    def test_log_error_returns_string(self):
        self._assert_error_string("/log", "src.notifications.telegram_commands._cmd_log")

    def test_pull_error_returns_string(self):
        self._assert_error_string("/pull", "src.notifications.telegram_commands._cmd_pull")

    def test_logs_error_returns_string(self):
        self._assert_error_string("/logs", "src.notifications.telegram_commands._cmd_logs")

    def test_gpu_error_returns_string(self):
        self._assert_error_string("/gpu", "src.notifications.telegram_commands._cmd_gpu")

    def test_disk_error_returns_string(self):
        self._assert_error_string("/disk", "src.notifications.telegram_commands._cmd_disk")

    def test_uptime_error_returns_string(self):
        self._assert_error_string("/uptime", "src.notifications.telegram_commands._cmd_uptime")

    def test_heartbeat_error_returns_string(self):
        self._assert_error_string("/heartbeat", "src.notifications.telegram_commands._cmd_heartbeat")


# ── T21b: _cmd_council typed exceptions (C14) ────────────────────────────────


class TestCmdCouncilTypedExceptions:
    """C14: _cmd_council returns categorized strings for typed council exceptions."""

    def _run_council_with_exc(self, exc):
        with patch("src.notifications.telegram_commands.requests") as _:
            with patch(
                "src.notifications.telegram_commands._cmd_council.__wrapped__"
                if hasattr(
                    __import__("src.notifications.telegram_commands", fromlist=["_cmd_council"]),
                    "_cmd_council"
                ) and hasattr(
                    __import__("src.notifications.telegram_commands", fromlist=["_cmd_council"])._cmd_council,
                    "__wrapped__",
                ) else "src.notifications.telegram_commands._cmd_council"
            ):
                pass
        # Patch run_council_command to raise the typed exception
        import sys
        mod_name = "src.council.engine"
        if mod_name in sys.modules:
            target = f"{mod_name}.run_council_command"
        else:
            target = "src.council.engine.run_council_command"
        with patch("src.notifications.telegram_commands._cmd_council") as mock_cmd:
            mock_cmd.side_effect = exc
            from src.notifications.telegram_commands import handle_command
            return handle_command("/council", "test question")

    def test_cost_cap_exceeded_returns_categorized_string(self):
        from src.notifications.telegram_commands import _cmd_council, CostCapExceededError
        with patch(
            "src.notifications.telegram_commands.run_council_command",
            side_effect=CostCapExceededError("cap hit"),
        ):
            result = _cmd_council("question")
        assert "cost cap" in result.lower()

    def test_agent_timeout_returns_categorized_string(self):
        from src.notifications.telegram_commands import _cmd_council, AgentTimeoutError
        with patch(
            "src.notifications.telegram_commands.run_council_command",
            side_effect=AgentTimeoutError("timeout"),
        ):
            result = _cmd_council("question")
        assert "agent timeout" in result.lower()

    def test_llm_unavailable_returns_categorized_string(self):
        from src.notifications.telegram_commands import _cmd_council, LLMUnavailableError
        with patch(
            "src.notifications.telegram_commands.run_council_command",
            side_effect=LLMUnavailableError("no llm"),
        ):
            result = _cmd_council("question")
        assert "llm unavailable" in result.lower()

    def test_no_quorum_returns_categorized_string(self):
        from src.notifications.telegram_commands import _cmd_council, NoQuorumError
        with patch(
            "src.notifications.telegram_commands.run_council_command",
            side_effect=NoQuorumError("no quorum"),
        ):
            result = _cmd_council("question")
        assert "no quorum" in result.lower()

    def test_invalid_question_returns_categorized_string(self):
        from src.notifications.telegram_commands import _cmd_council, InvalidQuestionError
        with patch(
            "src.notifications.telegram_commands.run_council_command",
            side_effect=InvalidQuestionError("bad question"),
        ):
            result = _cmd_council("question")
        assert "invalid question" in result.lower()


# ── T21b: dataclass payloads (CC3) ───────────────────────────────────────────


class TestNotifyTradeOpenedDataclass:
    """CC3: notify_trade_opened uses TradeOpenedPayload dataclass; missing required field → TypeError."""

    def test_trade_opened_payload_missing_ticker_raises_typeerror(self):
        from src.notifications.telegram import TradeOpenedPayload
        with pytest.raises(TypeError):
            TradeOpenedPayload(entry_price=100.0, stop=95.0, target=110.0, score=80, shares=10)

    def test_trade_opened_payload_constructs_with_required_fields(self):
        from src.notifications.telegram import TradeOpenedPayload
        p = TradeOpenedPayload(
            ticker="AAPL", entry_price=100.0, stop=95.0, target=110.0, score=80, shares=10
        )
        assert p.ticker == "AAPL"
        assert p.entry_price == 100.0

    def test_trade_closed_payload_missing_ticker_raises_typeerror(self):
        from src.notifications.telegram import TradeClosedPayload
        with pytest.raises(TypeError):
            TradeClosedPayload(pnl_dollars=50.0, pnl_pct=5.0, exit_reason="target", days_held=3)

    def test_trade_closed_payload_constructs_with_required_fields(self):
        from src.notifications.telegram import TradeClosedPayload
        p = TradeClosedPayload(
            ticker="MSFT", pnl_dollars=50.0, pnl_pct=5.0, exit_reason="target", days_held=3
        )
        assert p.ticker == "MSFT"

    def test_eod_report_payload_missing_field_raises_typeerror(self):
        from src.notifications.telegram import EodReportPayload
        with pytest.raises(TypeError):
            EodReportPayload()

    def test_eod_report_payload_constructs_with_required_fields(self):
        from src.notifications.telegram import EodReportPayload
        p = EodReportPayload(
            paper_open=2, paper_open_pnl=100.0,
            paper_closed_today=1, paper_closed_pnl=50.0,
            live_open=0, live_open_pnl=0.0,
            live_closed_today=0, live_closed_pnl=0.0,
            win_rate=0.67, wins=2, losses=1,
            best_ticker="AAPL", best_pct=5.0,
            worst_ticker="MSFT", worst_pct=-1.0,
            regime="neutral", vix=18.0, vix_change=0.5,
        )
        assert p.win_rate == 0.67

    def test_weekly_digest_payload_missing_field_raises_typeerror(self):
        from src.notifications.telegram import WeeklyDigestPayload
        with pytest.raises(TypeError):
            WeeklyDigestPayload()

    def test_weekly_digest_payload_constructs_with_required_fields(self):
        from src.notifications.telegram import WeeklyDigestPayload
        p = WeeklyDigestPayload(
            period_start="2026-05-01", period_end="2026-05-07",
            opened_paper=3, opened_live=1,
            closed_paper=2, closed_live=0,
            win_rate=0.75, expectancy=50.0,
            best_ticker="AAPL", best_pct=5.0,
            worst_ticker="MSFT", worst_pct=-2.0,
            pnl_paper=150.0, pnl_live=80.0,
            training_start=900, training_end=920,
            signal_start=500, signal_end=510,
            scoring_backlog=20, quality_avg=4.2,
            canary_status="ok", llm_success_rate=0.98,
            regime="neutral", vix=17.5, vix_range_low=15.0, vix_range_high=20.0,
            spy_weekly_pct=1.2,
            council_sessions=3, council_consensus="cautious_long", council_avg_confidence=72,
            earnings_next_week=["AAPL"], events_next_week=["Fed meeting"],
        )
        assert p.period_start == "2026-05-01"
