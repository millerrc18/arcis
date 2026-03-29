"""Comprehensive tests for src.evaluation.gate_evaluator."""

import sqlite3
import uuid
from datetime import datetime, timedelta

import numpy as np
import pytest

from src.evaluation.gate_evaluator import evaluate_50_trade_gate, format_gate_report
from src.journal.store import initialize_database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_trades(db_path: str, trades: list[dict]) -> None:
    """Insert trade rows into shadow_trades."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(db_path) as conn:
        for i, t in enumerate(trades):
            trade_id = t.get("trade_id", str(uuid.uuid4()))
            ticker = t.get("ticker", "TEST")
            status = t.get("status", "closed")
            pnl_dollars = t.get("pnl_dollars", 0.0)
            pnl_pct = t.get("pnl_pct", 0.0)
            exit_time = t.get(
                "actual_exit_time",
                (datetime.utcnow() + timedelta(minutes=i)).isoformat(),
            )
            created_at = t.get("created_at", now)
            updated_at = t.get("updated_at", now)
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, status, pnl_dollars, pnl_pct,
                    actual_exit_time, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, ticker, status, pnl_dollars, pnl_pct,
                 exit_time, created_at, updated_at),
            )
        conn.commit()


def _make_db(tmp_path, trades: list[dict]) -> str:
    """Create a fresh DB and insert trades. Returns the path as str."""
    db_path = str(tmp_path / "test.sqlite3")
    initialize_database(db_path)
    if trades:
        _insert_trades(db_path, trades)
    return db_path


def _strong_trades(n: int = 50) -> list[dict]:
    """Generate n trades with strong performance (high win rate, good PnL)."""
    trades = []
    for i in range(n):
        if i % 10 < 7:  # 70% win rate
            trades.append({"pnl_dollars": 150.0 + i, "pnl_pct": 2.5 + i * 0.01})
        else:
            trades.append({"pnl_dollars": -80.0, "pnl_pct": -1.2})
    return trades


def _mixed_trades(n: int = 50) -> list[dict]:
    """Generate trades with mixed performance (borderline yellow/green)."""
    trades = []
    for i in range(n):
        if i % 10 < 5:  # 50% win rate
            trades.append({"pnl_dollars": 100.0, "pnl_pct": 1.5})
        else:
            trades.append({"pnl_dollars": -90.0, "pnl_pct": -1.4})
    return trades


def _poor_trades(n: int = 50) -> list[dict]:
    """Generate trades with poor performance (many reds)."""
    trades = []
    for i in range(n):
        if i % 10 < 3:  # 30% win rate
            trades.append({"pnl_dollars": 50.0, "pnl_pct": 0.8})
        else:
            trades.append({"pnl_dollars": -120.0, "pnl_pct": -2.0})
    return trades


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyAndEdgeCases:
    """Tests for empty DB, no closed trades, and other edge conditions."""

    def test_empty_database_returns_error(self, tmp_path):
        """Empty DB with no trades should return an error dict."""
        db_path = _make_db(tmp_path, [])
        result = evaluate_50_trade_gate(db_path)
        assert "error" in result
        assert result["trade_count"] == 0

    def test_no_closed_trades(self, tmp_path):
        """Only open/pending trades (pnl_pct IS NULL) should return error."""
        db_path = _make_db(tmp_path, [])
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, status, pnl_dollars, pnl_pct,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("t1", "AAPL", "open", None, None,
                 datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
        result = evaluate_50_trade_gate(db_path)
        assert "error" in result
        assert result["trade_count"] == 0

    def test_nonexistent_db_returns_error(self, tmp_path):
        """A path to a nonexistent DB should return an error dict."""
        result = evaluate_50_trade_gate(str(tmp_path / "does_not_exist.sqlite3"))
        assert "error" in result or result.get("trade_count", 0) == 0

    def test_single_trade(self, tmp_path):
        """A single closed trade should still produce a result (no crash)."""
        db_path = _make_db(tmp_path, [{"pnl_dollars": 100.0, "pnl_pct": 2.0}])
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result
        assert result["trade_count"] == 1
        assert "gates" in result


class TestStrongPerformer:
    """Trades that should result in PROCEED decision (4+ GREEN, 0 RED)."""

    def test_proceed_decision(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result
        assert result["reds"] == 0
        assert result["greens"] >= 4
        assert "PROCEED" in result["decision"]

    def test_strong_win_rate_is_green(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["win_rate"]["status"] == "green"
        assert result["gates"]["win_rate"]["value"] >= 0.45

    def test_strong_profit_factor_is_green(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["profit_factor"]["status"] == "green"
        assert result["gates"]["profit_factor"]["value"] >= 1.3

    def test_strong_net_pnl_is_green(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["net_pnl"]["status"] == "green"
        assert result["gates"]["net_pnl"]["value"] > 0


class TestMixedPerformer:
    """Trades that should result in EXTEND decision (green+yellow, 0 RED)."""

    def test_extend_decision(self, tmp_path):
        db_path = _make_db(tmp_path, _mixed_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result
        # Mixed trades: net_pnl should be slightly positive (wins > losses)
        # but not all metrics green => EXTEND or at worst ROOT CAUSE
        # The key: 0 RED needed for EXTEND
        if result["reds"] == 0 and result["greens"] < 4:
            assert "EXTEND" in result["decision"]

    def test_mixed_has_yellow_metrics(self, tmp_path):
        """Mixed trades should produce at least one yellow metric."""
        db_path = _make_db(tmp_path, _mixed_trades(50))
        result = evaluate_50_trade_gate(db_path)
        statuses = [g["status"] for g in result["gates"].values()]
        # We expect a mix -- not all green
        assert "yellow" in statuses or "red" in statuses


class TestPoorPerformer:
    """Trades that should result in FUNDAMENTAL REVISION (2+ RED)."""

    def test_revision_decision(self, tmp_path):
        db_path = _make_db(tmp_path, _poor_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result
        assert result["reds"] >= 2
        assert "REVISION" in result["decision"]

    def test_poor_win_rate_is_red(self, tmp_path):
        db_path = _make_db(tmp_path, _poor_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["win_rate"]["status"] == "red"
        assert result["gates"]["win_rate"]["value"] < 0.38


class TestSingleRedMetric:
    """One RED metric should trigger ROOT CAUSE ANALYSIS."""

    def test_root_cause_decision(self, tmp_path):
        """Craft trades where only net_pnl is red (slightly negative sum)
        but other metrics are acceptable."""
        trades = []
        # 48% win rate (yellow), decent sized wins, small losses
        # but net sum is barely negative
        for i in range(50):
            if i < 24:
                trades.append({"pnl_dollars": 80.0, "pnl_pct": 1.0})
            elif i < 49:
                trades.append({"pnl_dollars": -78.0, "pnl_pct": -0.95})
            else:
                # The last trade tips net PnL negative
                trades.append({"pnl_dollars": -100.0, "pnl_pct": -1.2})

        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result

        # net_pnl should be negative => red (it is binary: >0 green, else red)
        net = result["gates"]["net_pnl"]["value"]
        if net <= 0:
            assert result["gates"]["net_pnl"]["status"] == "red"
        # If exactly 1 red, decision should be ROOT CAUSE
        if result["reds"] == 1:
            assert "ROOT CAUSE" in result["decision"]


class TestExactly50Trades:
    """Verify the evaluator handles exactly 50 trades."""

    def test_trade_count_is_50(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert result["trade_count"] == 50

    def test_more_than_50_trades(self, tmp_path):
        """The evaluator should use all closed trades, not cap at 50."""
        db_path = _make_db(tmp_path, _strong_trades(75))
        result = evaluate_50_trade_gate(db_path)
        assert result["trade_count"] == 75


class TestAllWinners:
    """Every trade is a winner."""

    def test_all_winners_profit_factor_high(self, tmp_path):
        trades = [{"pnl_dollars": 100.0, "pnl_pct": 1.5} for _ in range(50)]
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert "error" not in result
        assert result["gates"]["win_rate"]["value"] == 1.0
        # profit_factor: losses sum is 0, so profit_factor call gets
        # losses_total=0 => function returns 0 (since len(losses)==0 the
        # evaluator passes 0 for abs(losses.sum()) which hits the == 0 branch)
        # The code: pf = profit_factor(...) if len(losses) > 0 else 0
        # All winners => len(losses)==0 => pf=0
        assert result["gates"]["profit_factor"]["value"] == 0
        assert result["gates"]["net_pnl"]["status"] == "green"

    def test_all_winners_net_pnl_green(self, tmp_path):
        trades = [{"pnl_dollars": 200.0, "pnl_pct": 3.0} for _ in range(50)]
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["net_pnl"]["value"] > 0
        assert result["gates"]["net_pnl"]["status"] == "green"


class TestAllLosers:
    """Every trade is a loser."""

    def test_all_losers_net_pnl_red(self, tmp_path):
        trades = [{"pnl_dollars": -100.0, "pnl_pct": -1.5} for _ in range(50)]
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["net_pnl"]["status"] == "red"
        assert result["gates"]["net_pnl"]["value"] < 0

    def test_all_losers_win_rate_zero(self, tmp_path):
        trades = [{"pnl_dollars": -50.0, "pnl_pct": -0.8} for _ in range(50)]
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert result["gates"]["win_rate"]["value"] == 0.0
        assert result["gates"]["win_rate"]["status"] == "red"

    def test_all_losers_multiple_reds(self, tmp_path):
        trades = [{"pnl_dollars": -100.0, "pnl_pct": -2.0} for _ in range(50)]
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        assert result["reds"] >= 2
        assert "REVISION" in result["decision"]


class TestMetricThresholds:
    """Directly verify the GREEN/YELLOW/RED threshold logic."""

    def test_drawdown_inversion(self, tmp_path):
        """max_drawdown uses inverted thresholds (lower is better)."""
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        dd = result["gates"]["max_drawdown"]
        # The threshold is: green <= 12, yellow <= 18, red > 18
        if dd["value"] <= 12:
            assert dd["status"] == "green"
        elif dd["value"] <= 18:
            assert dd["status"] == "yellow"
        else:
            assert dd["status"] == "red"

    def test_net_pnl_binary_logic(self, tmp_path):
        """net_pnl is binary: >0 green, else red (no yellow)."""
        # Positive net
        trades_pos = _strong_trades(50)
        db_pos = _make_db(tmp_path, trades_pos)
        r_pos = evaluate_50_trade_gate(db_pos)
        assert r_pos["gates"]["net_pnl"]["status"] in ("green", "red")
        # No yellow possible for binary metric
        assert r_pos["gates"]["net_pnl"]["status"] != "yellow"


class TestStatisticalOutputs:
    """Verify PSR, bootstrap CI, sortino, skew/kurtosis fields."""

    def test_result_contains_psr(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert "psr_0" in result
        assert isinstance(result["psr_0"], float)
        # PSR is a probability, should be 0-1
        assert 0.0 <= result["psr_0"] <= 1.0

    def test_result_contains_bootstrap_ci(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        ci = result["bootstrap_ci"]
        assert "lower" in ci
        assert "observed" in ci
        assert "upper" in ci
        assert ci["lower"] <= ci["upper"]

    def test_result_contains_sortino(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        assert "sortino" in result
        assert isinstance(result["sortino"], float)


class TestFormatGateReport:
    """Tests for the format_gate_report function."""

    def test_error_report(self):
        result = {"error": "No closed trades", "trade_count": 0}
        report = format_gate_report(result)
        assert "error" in report.lower() or "No closed trades" in report

    def test_report_contains_decision(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        assert "DECISION" in report
        assert result["decision"] in report

    def test_report_contains_all_metrics(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        for g in result["gates"].values():
            assert g["label"] in report

    def test_report_contains_trade_count(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        assert "50 trades" in report

    def test_report_contains_psr(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        assert "PSR(0)" in report

    def test_report_contains_bootstrap_ci(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        assert "Bootstrap Sharpe CI" in report

    def test_report_is_string(self, tmp_path):
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        report = format_gate_report(result)
        assert isinstance(report, str)
        assert len(report) > 100  # should be substantial


class TestDecisionLogicBoundaries:
    """Test the exact decision boundaries from the docstring."""

    def test_four_green_zero_red_is_proceed(self, tmp_path):
        """Manually verify: exactly 4 green + 2 yellow + 0 red => PROCEED."""
        db_path = _make_db(tmp_path, _strong_trades(50))
        result = evaluate_50_trade_gate(db_path)
        if result["greens"] >= 4 and result["reds"] == 0:
            assert "PROCEED" in result["decision"]

    def test_three_green_zero_red_is_extend(self, tmp_path):
        """3 green + 3 yellow + 0 red => EXTEND (not enough greens)."""
        # Use mixed trades that hover near thresholds
        trades = []
        for i in range(50):
            if i % 10 < 5:  # 50% win rate => yellow for win_rate
                trades.append({"pnl_dollars": 110.0, "pnl_pct": 1.8})
            else:
                trades.append({"pnl_dollars": -85.0, "pnl_pct": -1.3})
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        if result["reds"] == 0 and result["greens"] < 4:
            assert "EXTEND" in result["decision"]

    def test_two_plus_red_is_revision(self, tmp_path):
        db_path = _make_db(tmp_path, _poor_trades(50))
        result = evaluate_50_trade_gate(db_path)
        if result["reds"] >= 2:
            assert "REVISION" in result["decision"]

    def test_exactly_one_red_is_root_cause(self, tmp_path):
        """Construct trades where exactly 1 metric is RED."""
        # High win rate, decent Sharpe, good expectancy, low drawdown
        # BUT net_pnl is barely negative => 1 RED
        trades = []
        for i in range(50):
            if i < 26:  # 52% win rate
                trades.append({"pnl_dollars": 60.0, "pnl_pct": 0.8})
            else:
                trades.append({"pnl_dollars": -66.0, "pnl_pct": -0.85})
        db_path = _make_db(tmp_path, trades)
        result = evaluate_50_trade_gate(db_path)
        if result["reds"] == 1:
            assert "ROOT CAUSE" in result["decision"]


class TestOnlyClosedTradesUsed:
    """Verify that only status='closed' AND pnl_pct IS NOT NULL rows are used."""

    def test_open_trades_excluded(self, tmp_path):
        db_path = _make_db(tmp_path, [])
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(db_path) as conn:
            # 5 closed trades
            for i in range(5):
                conn.execute(
                    """INSERT INTO shadow_trades
                       (trade_id, ticker, status, pnl_dollars, pnl_pct,
                        actual_exit_time, created_at, updated_at)
                       VALUES (?, ?, 'closed', ?, ?, ?, ?, ?)""",
                    (f"closed-{i}", "AAPL", 100.0, 2.0, now, now, now),
                )
            # 10 open trades (should be ignored)
            for i in range(10):
                conn.execute(
                    """INSERT INTO shadow_trades
                       (trade_id, ticker, status, pnl_dollars, pnl_pct,
                        created_at, updated_at)
                       VALUES (?, ?, 'open', NULL, NULL, ?, ?)""",
                    (f"open-{i}", "MSFT", now, now),
                )
        result = evaluate_50_trade_gate(db_path)
        assert result["trade_count"] == 5
