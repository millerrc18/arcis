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


# ─── Corpus-consumption integration tests (#96.4 Sprint 1.C Phase 4) ─────────


class TestRunWalkforwardCorpus:
    """run_walkforward(corpus_id=...) integration tests.

    Locks pre-reg §A3 admissibility gate semantics + result-dict contract:
    - admissible manifest succeeds, propagates corpus_id to each fold
    - non-admissible manifest raises BEFORE any fold runs (don't waste fold work)
    - manifest window must cover requested fold range or raise
    - result dict gains corpus_id, manifest_admissibility, parse_failed_excluded
    - corpus_id=None preserves original runtime behavior
    """

    def _build_corpus(
        self,
        tmp_path,
        monkeypatch,
        *,
        corpus_id: str = "wf-test-corpus",
        admissibility: str = "PASS",
        window_start: str = "2015-03-19",
        window_end: str = "2026-12-31",
        parse_failure_count: int = 0,
        total: int = 100,
    ):
        from src.evaluation.corpus import (
            CorpusEntry,
            CorpusManifest,
            write_corpus,
        )

        root = tmp_path / "corpus_root"
        root.mkdir(exist_ok=True)
        monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(root))

        # Single benign entry — the run_walkforward path delegates trade
        # production to backtest_model (which is mocked in these tests).
        # Manifest properties are what drive the admissibility / window gates.
        entry = CorpusEntry(
            as_of="2024-06-15",
            ticker="AAPL",
            model_version="arcis:v1.0.0",
            prompt_sha256="a" * 64,
            response="Conviction: 7",
            llm_action="taken",
            llm_conviction=7,
            parse_failed=0,
            parser_strategy_succeeded="metadata_block",
            generated_at="2026-04-29T12:00:00Z",
        )

        section = {1: "clean", 2: "clean", 4: "fixed", 5: "fixed", 6: "fixed",
                   7: "fixed", 8: "placeholder", 9: "best-effort", 10: "fixed",
                   11: "placeholder"}
        manifest = CorpusManifest(
            corpus_id=corpus_id,
            generated_at="2026-04-29T12:00:00Z",
            code_sha="abc123def456",
            model_version="arcis:v1.0.0",
            walkforward_window_start=window_start,
            walkforward_window_end=window_end,
            total_decision_points=total,
            parse_failure_count=parse_failure_count,
            parse_failure_rate=parse_failure_count / total if total else 0.0,
            section_pit_status=section,
            coverage_limit_hits={},
            admissibility=admissibility,
        )
        write_corpus(corpus_id, [entry], manifest)
        return corpus_id

    @patch("src.evaluation.walkforward.backtest_model")
    def test_admissible_corpus_succeeds(self, mock_bt, tmp_path, monkeypatch):
        """run_walkforward(corpus_id=...) with admissible manifest succeeds."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(tmp_path, monkeypatch)

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=8, embargo_days=21,
            corpus_id=corpus_id,
        )

        assert "folds" in result
        assert len(result["folds"]) == 8

    @patch("src.evaluation.walkforward.backtest_model")
    def test_inadmissible_corpus_raises_before_folds_run(
        self, mock_bt, tmp_path, monkeypatch
    ):
        """Pre-reg §A3 admissibility gate: non-admissible manifest blocks the harness.

        Critically, the gate fires BEFORE any backtest_model call so we don't
        waste fold work on a corpus that can't ground a primary-metric claim.
        """
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch,
            corpus_id="wf-inadmissible",
            admissibility="FAIL: parse_failure_rate=0.0700 exceeds §A1.4 ceiling of 0.05",
        )

        with pytest.raises(RuntimeError, match="not admissible"):
            run_walkforward(
                "arcis:v1.0.0", anchor="2023-09-01",
                fold_count=8, embargo_days=21,
                corpus_id=corpus_id,
            )

        # Critical: gate must fire BEFORE folds run
        assert mock_bt.call_count == 0, (
            f"Expected 0 backtest_model calls for inadmissible corpus, "
            f"got {mock_bt.call_count} (admissibility gate not blocking)"
        )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_window_too_narrow_raises(self, mock_bt, tmp_path, monkeypatch):
        """Manifest window must cover requested fold range or RuntimeError."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        # Manifest window ends 2024-01-01 — but folds run through 2026
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch,
            corpus_id="wf-narrow-window",
            window_start="2023-09-01",
            window_end="2024-01-01",
        )

        with pytest.raises(RuntimeError, match="window"):
            run_walkforward(
                "arcis:v1.0.0", anchor="2023-09-01",
                fold_count=8, embargo_days=21,
                corpus_id=corpus_id,
            )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_result_dict_includes_corpus_provenance(
        self, mock_bt, tmp_path, monkeypatch
    ):
        """Result dict gains corpus_id, manifest_admissibility, parse_failed_excluded."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch,
            corpus_id="wf-provenance",
            parse_failure_count=3,
            total=100,
        )

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id,
        )

        assert result["corpus_id"] == "wf-provenance"
        assert result["manifest_admissibility"] == "PASS"
        # parse_failed_excluded = parse_failure_count from the manifest
        assert result["parse_failed_excluded"] == 3

    @patch("src.evaluation.walkforward.backtest_model")
    def test_corpus_id_propagated_to_each_fold(
        self, mock_bt, tmp_path, monkeypatch
    ):
        """Each backtest_model call receives the corpus_id kwarg."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch,
            corpus_id="wf-propagate",
        )

        run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id,
        )

        for call in mock_bt.call_args_list:
            assert call.kwargs.get("corpus_id") == "wf-propagate", (
                f"backtest_model call missing or wrong corpus_id: {call.kwargs}"
            )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_corpus_id_none_preserves_runtime_behavior(self, mock_bt):
        """When corpus_id is omitted, no admissibility gate, no result keys, runtime unchanged."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
        )

        # Original behavior preserved; provenance fields default to None / 0
        assert result["corpus_id"] is None
        assert result["manifest_admissibility"] is None
        assert result["parse_failed_excluded"] == 0
        # Each backtest_model call receives corpus_id=None
        for call in mock_bt.call_args_list:
            assert call.kwargs.get("corpus_id") is None


# ─── Bug C 8-fold integration smoke (Sprint 1.C.4.5 / #104) ──────────────────
#
# When the backtester correctly anchors fetch_period_days to test_start (Bug C
# fix), every fold — not just the most recent — must be able to produce trades
# for synthetic OHLCV that covers the entire walk-forward window.


def _make_synthetic_5y_ohlcv_for_walkforward(
    tickers, *, start="2014-01-01", end="2026-04-29"
):
    """Build a long synthetic OHLCV series spanning the full walk-forward
    coverage (anchor train_start ~2015-03-19 through ~present).
    """
    import pandas as _pd

    dates = _pd.bdate_range(start, end)
    base_close = 100.0
    closes = [base_close * (1.0 + 0.0003) ** i for i in range(len(dates))]
    result = {}
    for ticker in tickers:
        df = _pd.DataFrame(
            {
                "Open": closes,
                "High": [c * 1.01 for c in closes],
                "Low": [c * 0.99 for c in closes],
                "Close": closes,
                "Volume": [1_000_000] * len(dates),
            },
            index=dates,
        )
        result[ticker] = df
    return result


def _make_period_aware_fetch(synthetic_data, *, today=None):
    """Mock fetch_ohlcv with yfinance period= semantics (today - period_days)
    and Path-1 start=/end= semantics. Mirrors the helper in test_backtester.py
    but kept local to avoid a cross-test-file shared-helper coupling.
    """
    import pandas as _pd

    if today is None:
        today = _pd.Timestamp("2026-04-29")
    today = _pd.Timestamp(today)

    def fetch(tickers, period="1y", start=None, end=None):
        if start is not None or end is not None:
            start_ts = _pd.Timestamp(start) if start else synthetic_data[next(iter(synthetic_data))].index.min()
            end_ts = _pd.Timestamp(end) if end else today
            return {
                t: synthetic_data[t][(synthetic_data[t].index >= start_ts) & (synthetic_data[t].index <= end_ts)]
                for t in tickers if t in synthetic_data
            }
        if period.endswith("d"):
            period_days = int(period[:-1])
        elif period.endswith("y"):
            period_days = int(period[:-1]) * 365
        else:
            period_days = 365
        start_ts = today - _pd.Timedelta(days=period_days)
        return {
            t: synthetic_data[t][(synthetic_data[t].index >= start_ts) & (synthetic_data[t].index <= today)]
            for t in tickers if t in synthetic_data
        }
    return fetch


def _make_period_aware_spy(synthetic_spy, *, today=None):
    import pandas as _pd
    if today is None:
        today = _pd.Timestamp("2026-04-29")
    today = _pd.Timestamp(today)

    def fetch_spy(period="1y", start=None, end=None):
        if start is not None or end is not None:
            start_ts = _pd.Timestamp(start) if start else synthetic_spy.index.min()
            end_ts = _pd.Timestamp(end) if end else today
            return synthetic_spy[(synthetic_spy.index >= start_ts) & (synthetic_spy.index <= end_ts)]
        if period.endswith("d"):
            period_days = int(period[:-1])
        elif period.endswith("y"):
            period_days = int(period[:-1]) * 365
        else:
            period_days = 365
        start_ts = today - _pd.Timedelta(days=period_days)
        return synthetic_spy[(synthetic_spy.index >= start_ts) & (synthetic_spy.index <= today)]
    return fetch_spy


def test_all_folds_produce_trades():
    """Bug C integration smoke: every fold in an 8-fold walk-forward must
    produce trades when the underlying synthetic OHLCV covers the full
    window. Pre-fix, fold 1-7 silently return 0 trades because
    fetch_period_days anchors at today; only fold 8 (which overlaps with the
    fetch window) has data. Post-fix, every fold sees data.

    We mock at the fetch boundary (fetch_ohlcv, fetch_spy_benchmark) only,
    then drive the real backtest_model + walkforward harness. compute_outcome
    is forced to a fixed positive return so we don't have to model the full
    OHLCV-to-pnl pipeline.
    """
    from unittest.mock import patch as _patch
    import pandas as _pd

    tickers = ["AAPL", "MSFT"]
    synth_ohlcv = _make_synthetic_5y_ohlcv_for_walkforward(tickers)
    synth_spy = _make_synthetic_5y_ohlcv_for_walkforward(["SPY"])["SPY"]

    fetch_side = _make_period_aware_fetch(synth_ohlcv)
    fetch_spy_side = _make_period_aware_spy(synth_spy)

    candidates_payload = {
        "packet_worthy": [
            {"ticker": "AAPL", "score": 85,
             "features": {"trend_state": "uptrend", "regime_label": "bull"}},
        ],
        "watchlist": [],
    }
    features_payload = {
        "AAPL": {"trend_state": "uptrend", "regime_label": "bull",
                 "current_price": 150},
        "MSFT": {"trend_state": "uptrend", "regime_label": "bull",
                 "current_price": 300},
    }
    from types import SimpleNamespace as _SN
    packet_payload = _SN(
        entry_zone="$150.00", stop_invalidation="$145.00",
        targets="$160.00 / $170.00", llm_conviction=None,
    )

    with _patch("src.config.load_config",
                return_value={"shadow_trading": {"enabled": False}}), \
         _patch("src.universe.pit.get_sp100_at", return_value=tickers), \
         _patch("src.data_ingestion.market_data.fetch_ohlcv",
                side_effect=fetch_side), \
         _patch("src.data_ingestion.market_data.fetch_spy_benchmark",
                side_effect=fetch_spy_side), \
         _patch("src.features.engine.compute_all_features",
                return_value=features_payload), \
         _patch("src.ranking.ranker.rank_universe",
                return_value=[{"ticker": "AAPL", "score": 85}]), \
         _patch("src.ranking.ranker.get_top_candidates",
                return_value=candidates_payload), \
         _patch("src.packets.template.build_packet_from_features",
                return_value=packet_payload), \
         _patch("src.shadow_trading.executor._parse_price",
                side_effect=lambda x: float(x.replace("$", "").replace(",", ""))), \
         _patch("src.training.historical_scanner.compute_outcome",
                return_value={"pnl_pct": 3.5, "exit_reason": "target_1",
                              "duration_days": 5}), \
         _patch("src.cost_model.calibration.get_calibrated_cost_model",
                return_value=None):
        from src.evaluation.walkforward import run_walkforward
        result = run_walkforward(
            "test_model", anchor="2023-09-01",
            fold_count=8, embargo_days=21,
        )

    assert len(result["folds"]) == 8

    # Every fold should have at least 1 trade (not just fold 8).
    # Pre-fix, only fold 8 (test span overlaps yfinance's last-N-days fetch)
    # had data. The integration smoke proves all 8 folds now see data.
    folds_with_zero_trades = [
        f["fold_idx"] for f in result["folds"] if f["trades_count"] == 0
    ]
    assert not folds_with_zero_trades, (
        f"Bug C: {len(folds_with_zero_trades)} of 8 folds produced 0 trades "
        f"(fold_idx={folds_with_zero_trades}). "
        f"Expected every fold to see data when fetch is anchored to test_start."
    )


# ─── Sprint 6 Wave B T2: canonical subtract_trading_days regression locks ─────


class TestCanonicalSubtractTradingDays:
    """Regression-locks verifying _single_fold_boundary and compute_fold_boundaries
    both delegate trading-day subtraction to the canonical
    src.scheduler.holidays.subtract_trading_days (Sprint 6 Wave B T2).
    """

    def test_compute_embargo_end_uses_canonical_subtract_trading_days(self):
        """_single_fold_boundary calls src.scheduler.holidays.subtract_trading_days
        with anchor=test_start and n=embargo_days (21 by default).

        Patches the canonical function and asserts it is called with the expected
        arguments when _single_fold_boundary computes the train_end embargo boundary.
        """
        from unittest.mock import patch, call
        from datetime import date, timedelta

        test_start_date = date(2024, 3, 1)
        expected_train_end = date(2024, 1, 31)

        with patch(
            "src.evaluation.walkforward.subtract_trading_days",
            return_value=expected_train_end,
        ) as mock_std:
            from src.evaluation.walkforward import _single_fold_boundary

            result = _single_fold_boundary(
                fold_idx=0,
                anchor_date=date(2024, 3, 1),
                train_anchor=date(2015, 3, 20),
                fold_calendar_days=90,
                embargo_days=21,
            )

        assert mock_std.called, (
            "src.scheduler.holidays.subtract_trading_days was not called — "
            "local _subtract_trading_days may still be in use"
        )
        call_args = mock_std.call_args
        assert call_args.kwargs.get("n") == 21 or (
            len(call_args.args) >= 2 and call_args.args[1] == 21
        ), f"subtract_trading_days was not called with n=21, got: {call_args}"

    def test_compute_fold_boundaries_uses_canonical_subtract_trading_days(self):
        """compute_fold_boundaries delegates all trading-day subtraction to the
        canonical src.scheduler.holidays.subtract_trading_days.

        Patches the canonical function and asserts it is called at least once
        per fold (one call per embargo computation in _single_fold_boundary).
        """
        from unittest.mock import patch
        from datetime import date

        fixed_return = date(2023, 10, 10)

        with patch(
            "src.evaluation.walkforward.subtract_trading_days",
            return_value=fixed_return,
        ) as mock_std:
            from src.evaluation.walkforward import compute_fold_boundaries

            folds = compute_fold_boundaries(
                anchor="2023-09-01",
                fold_count=4,
                embargo_days=21,
            )

        assert mock_std.call_count >= 4, (
            f"Expected at least 4 calls to subtract_trading_days (one per fold), "
            f"got {mock_std.call_count} — local helper may still be in use"
        )
        for call_args in mock_std.call_args_list:
            n_value = (
                call_args.kwargs.get("n")
                if call_args.kwargs.get("n") is not None
                else (call_args.args[1] if len(call_args.args) >= 2 else None)
            )
            assert n_value == 21, (
                f"Expected n=21 in all subtract_trading_days calls, "
                f"got n={n_value} in call {call_args}"
            )
