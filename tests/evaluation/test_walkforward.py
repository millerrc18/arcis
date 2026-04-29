"""Tests for the walk-forward harness (src/evaluation/walkforward.py).

Pre-registration §3 compliance tests.
"""
from __future__ import annotations

import math
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_backtest_result(trades_count: int, sharpe: float = 1.0, total_return: float = 5.0) -> dict:
    """Build a synthetic backtest_model return dict with the given trade count."""
    trades = [
        {
            "date": "2024-01-15",
            "ticker": f"TICK{i}",
            "pnl_pct": 1.0 if i % 2 == 0 else -0.5,
            "score": 0.8,
            "entry": 100.0,
            "exit_reason": "target",
            "duration": 5,
            "regime": "bull",
        }
        for i in range(trades_count)
    ]
    return {
        "model": "arcis:v1.0.0",
        "trades_generated": trades_count,
        "win_rate": 0.55,
        "total_pnl_pct": total_return,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": -5.0,
        "monthly_returns": {},
        "trade_gap_days": 5.0,
        "by_regime": {},
        "equity_curve": [],
        "trades": trades,
    }


# ─── tests ────────────────────────────────────────────────────────────────────

class TestComputeFoldBoundaries:
    """Tests for compute_fold_boundaries()."""

    def test_fold_boundaries_anchored_expanding(self):
        """Train start is always the same; train end advances each fold; no overlap."""
        from src.evaluation.walkforward import compute_fold_boundaries

        folds = compute_fold_boundaries("2023-09-01", fold_count=8, embargo_days=21)

        assert len(folds) == 8

        # Train start is always identical (anchored)
        first_train_start = folds[0]["train_start"]
        for fold in folds:
            assert fold["train_start"] == first_train_start, (
                f"Fold {fold['fold_idx']} train_start {fold['train_start']} "
                f"!= anchor {first_train_start}"
            )

        # Train end advances each fold
        for i in range(1, len(folds)):
            assert folds[i]["train_end"] > folds[i - 1]["train_end"], (
                f"Fold {i} train_end did not advance past fold {i-1}"
            )

        # No test overlap: test windows are successive and non-overlapping
        for i in range(1, len(folds)):
            assert folds[i]["test_start"] >= folds[i - 1]["test_end"], (
                f"Fold {i} test_start overlaps fold {i-1} test_end"
            )

        # Embargo gap: test_start >= train_end + embargo for every fold
        for fold in folds:
            train_end = date.fromisoformat(fold["train_end"])
            test_start = date.fromisoformat(fold["test_start"])
            # test_start must be strictly after train_end (by at least embargo days)
            assert test_start > train_end, (
                f"Fold {fold['fold_idx']}: test_start {test_start} not after train_end {train_end}"
            )

    def test_fold_boundaries_snap_to_trading_days(self):
        """All boundary dates must be NYSE trading days (not weekends or holidays)."""
        from src.evaluation.walkforward import compute_fold_boundaries
        from src.scheduler.holidays import is_market_holiday

        folds = compute_fold_boundaries("2023-09-01", fold_count=8, embargo_days=21)

        for fold in folds:
            for field in ("train_start", "train_end", "test_start", "test_end"):
                d = date.fromisoformat(fold[field])
                # Not a weekend
                assert d.weekday() < 5, (
                    f"Fold {fold['fold_idx']} {field}={d} is a weekend (weekday={d.weekday()})"
                )
                # Not a NYSE holiday
                assert not is_market_holiday(check_date=d), (
                    f"Fold {fold['fold_idx']} {field}={d} is an NYSE holiday"
                )

    def test_eight_folds_default(self):
        """Default fold count is 8."""
        from src.evaluation.walkforward import compute_fold_boundaries

        folds = compute_fold_boundaries("2023-09-01")
        assert len(folds) == 8

    def test_eight_folds_override(self):
        """fold_count parameter is respected."""
        from src.evaluation.walkforward import compute_fold_boundaries

        folds = compute_fold_boundaries("2023-09-01", fold_count=4, embargo_days=21)
        assert len(folds) == 4

    def test_total_coverage(self):
        """train_start[0] is anchor coverage start; test_end[-1] is near coverage end."""
        from src.evaluation.walkforward import compute_fold_boundaries

        folds = compute_fold_boundaries("2023-09-01", fold_count=8, embargo_days=21)

        # First fold train_start should be the coverage start (2015-03-19 per pre-reg §2)
        first_train_start = date.fromisoformat(folds[0]["train_start"])
        assert first_train_start >= date(2015, 3, 1), (
            f"Expected train_start on or after 2015-03-01, got {first_train_start}"
        )
        assert first_train_start <= date(2015, 4, 1), (
            f"Expected train_start before 2015-04-01, got {first_train_start}"
        )

        # Last fold test_end should be before or at coverage_end
        last_test_end = date.fromisoformat(folds[-1]["test_end"])
        assert last_test_end >= date(2026, 1, 1), (
            f"Expected last test_end in 2026, got {last_test_end}"
        )

    def test_embargo_gap_respected(self):
        """test_start must be at least `embargo_days` trading days after train_end."""
        from src.evaluation.walkforward import compute_fold_boundaries
        from src.scheduler.holidays import is_market_holiday

        folds = compute_fold_boundaries("2023-09-01", fold_count=8, embargo_days=21)

        for fold in folds:
            train_end = date.fromisoformat(fold["train_end"])
            test_start = date.fromisoformat(fold["test_start"])

            # Count trading days between train_end (exclusive) and test_start (inclusive)
            from datetime import timedelta
            cursor = train_end + timedelta(days=1)
            trading_days_gap = 0
            while cursor <= test_start:
                if cursor.weekday() < 5 and not is_market_holiday(check_date=cursor):
                    trading_days_gap += 1
                cursor += timedelta(days=1)

            assert trading_days_gap >= 21, (
                f"Fold {fold['fold_idx']}: embargo gap is {trading_days_gap} trading days, "
                f"expected >= 21 (train_end={train_end}, test_start={test_start})"
            )


class TestUnderpoweredFlag:
    """Tests for the underpowered fold flag (pre-reg §3.5)."""

    def test_underpowered_flag_at_15_trades(self):
        """Fold with 14 trades flagged True; 15 flagged False (threshold is <15)."""
        from src.evaluation.walkforward import _apply_underpowered_flag

        assert _apply_underpowered_flag(14) is True, "14 trades should be underpowered"
        assert _apply_underpowered_flag(15) is False, "15 trades should NOT be underpowered"
        assert _apply_underpowered_flag(0) is True, "0 trades should be underpowered"
        assert _apply_underpowered_flag(100) is False, "100 trades should NOT be underpowered"

    def test_aggregate_excludes_underpowered_folds(self):
        """primary_sharpe must NOT include underpowered folds in its computation."""
        from src.evaluation.walkforward import compute_aggregate

        # One powered fold with known Sharpe, one underpowered fold with different Sharpe
        folds = [
            {
                "fold_idx": 0,
                "underpowered": False,
                "trades_count": 20,
                "fold_sharpe": 2.0,
                "fold_return_total": 10.0,
                "trades": [{"pnl_pct": 1.0}] * 20,
            },
            {
                "fold_idx": 1,
                "underpowered": True,
                "trades_count": 5,
                "fold_sharpe": -5.0,  # Would drag down aggregate if included
                "fold_return_total": -20.0,
                "trades": [{"pnl_pct": -4.0}] * 5,
            },
        ]

        result = compute_aggregate(folds)

        # primary_sharpe should be based only on fold 0, ignoring fold 1
        # It will differ from a naive mean of both sharpes
        naive_mean = (2.0 + (-5.0)) / 2
        assert result["primary_sharpe"] != naive_mean, (
            "Aggregate should exclude underpowered fold, but seems to include it"
        )

        # The footnote should record the underpowered fold
        footnote = result["underpowered_footnote"]
        assert footnote["underpowered_fold_count"] == 1
        assert footnote["underpowered_trades_count"] == 5

    def test_underpowered_footnote_structure(self):
        """underpowered_footnote has required fields."""
        from src.evaluation.walkforward import compute_aggregate

        folds = [
            {
                "fold_idx": 0,
                "underpowered": False,
                "trades_count": 20,
                "fold_sharpe": 1.5,
                "fold_return_total": 8.0,
                "trades": [{"pnl_pct": 1.0}] * 20,
            },
        ]

        result = compute_aggregate(folds)
        footnote = result["underpowered_footnote"]
        assert "underpowered_fold_count" in footnote
        assert "underpowered_trades_count" in footnote


class TestRunWalkforward:
    """Tests for run_walkforward() — end-to-end with mocked backtest_model."""

    def _make_mock_backtest(self, trades_count: int = 20, sharpe: float = 1.2):
        """Return a mock that produces consistent synthetic backtest output."""
        return _make_backtest_result(trades_count, sharpe=sharpe)

    @patch("src.evaluation.walkforward.backtest_model")
    def test_output_structure(self, mock_bt):
        """run_walkforward returns dict with required top-level keys."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = self._make_mock_backtest(20)

        result = run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=8, embargo_days=21)

        assert result["anchor_date"] == "2023-09-01"
        assert result["fold_count"] == 8
        assert result["embargo_days"] == 21
        assert "folds" in result
        assert "aggregate" in result
        assert len(result["folds"]) == 8

    @patch("src.evaluation.walkforward.backtest_model")
    def test_fold_dict_structure(self, mock_bt):
        """Each fold dict has required fields."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = self._make_mock_backtest(20)

        result = run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=8, embargo_days=21)

        required_fields = {
            "fold_idx", "train_start", "train_end", "test_start", "test_end",
            "trades_count", "underpowered", "trades", "fold_sharpe", "fold_return_total",
        }
        for fold in result["folds"]:
            missing = required_fields - set(fold.keys())
            assert not missing, f"Fold {fold.get('fold_idx')} missing fields: {missing}"

    @patch("src.evaluation.walkforward.backtest_model")
    def test_aggregate_structure(self, mock_bt):
        """aggregate dict has required fields."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = self._make_mock_backtest(20)

        result = run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=8, embargo_days=21)

        agg = result["aggregate"]
        assert "primary_sharpe" in agg
        assert "primary_t_stat" in agg
        assert "primary_trades_count" in agg
        assert "underpowered_footnote" in agg

    @patch("src.evaluation.walkforward.backtest_model")
    def test_underpowered_folds_excluded_from_aggregate(self, mock_bt):
        """When some folds return few trades, they're excluded from primary aggregate."""
        from src.evaluation.walkforward import run_walkforward

        # Alternate: powered folds (20 trades) and one underpowered fold (5 trades)
        call_count = [0]

        def side_effect(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 3:  # 4th fold is underpowered
                return _make_backtest_result(5, sharpe=-3.0)
            return _make_backtest_result(20, sharpe=1.5)

        mock_bt.side_effect = side_effect

        result = run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=8, embargo_days=21)

        underpowered = [f for f in result["folds"] if f["underpowered"]]
        powered = [f for f in result["folds"] if not f["underpowered"]]

        assert len(underpowered) == 1, f"Expected 1 underpowered fold, got {len(underpowered)}"
        assert result["aggregate"]["underpowered_footnote"]["underpowered_fold_count"] == 1

        # primary_trades_count must only reflect powered folds
        expected_powered_trades = sum(f["trades_count"] for f in powered)
        assert result["aggregate"]["primary_trades_count"] == expected_powered_trades

    @patch("src.evaluation.walkforward.backtest_model")
    def test_backtest_model_called_per_fold(self, mock_bt):
        """backtest_model is called once per fold."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = self._make_mock_backtest(20)

        run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=8, embargo_days=21)

        assert mock_bt.call_count == 8, (
            f"Expected 8 backtest_model calls (one per fold), got {mock_bt.call_count}"
        )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_backtest_model_receives_date_kwargs(self, mock_bt):
        """backtest_model is called with train_start/train_end/test_start/test_end kwargs."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = self._make_mock_backtest(20)

        run_walkforward("arcis:v1.0.0", anchor="2023-09-01", fold_count=4, embargo_days=21)

        for call in mock_bt.call_args_list:
            kwargs = call.kwargs
            assert "train_start" in kwargs, "Missing train_start kwarg in backtest_model call"
            assert "train_end" in kwargs, "Missing train_end kwarg in backtest_model call"
            assert "test_start" in kwargs, "Missing test_start kwarg in backtest_model call"
            assert "test_end" in kwargs, "Missing test_end kwarg in backtest_model call"


class TestCLI:
    """Tests for the CLI entrypoint."""

    def test_cli_help(self):
        """--help exits 0 and mentions required args."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "src.evaluation.walkforward", "--help"],
            capture_output=True,
            text=True,
            cwd="C:/arcis/halcyon-lab/.claude/worktrees/agent-a560de5102ccfb77a",
        )
        assert result.returncode == 0, f"--help exited {result.returncode}: {result.stderr}"
        assert "--anchor" in result.stdout
        assert "--folds" in result.stdout
        assert "--embargo" in result.stdout
        assert "--model" in result.stdout
