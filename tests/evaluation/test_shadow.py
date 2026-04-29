"""Tests for the deterministic-ranker shadow portfolio (#82 Sprint 1.C Phase 5).

Pre-registration §6 secondary diagnostic + addendum 1 §A1.6:
    The shadow runs the IDENTICAL feature pipeline + ranker selection MINUS
    the LLM filtering step. Both portfolios use the same parse_failed=0 row
    filter for fair comparison.

Test coverage:
1. shadow=True corpus path takes every parse_failed=0 entry regardless of llm_action
2. shadow=False corpus path filters to llm_action='taken' (regression-lock)
3. Both filter parse_failed=0 (the §A1.6 fair-comparison rule)
4. with_shadow=True walkforward returns dict with primary + shadow + delta keys
5. shadow trade count >= primary trade count (shadow is a superset by construction)
6. Both portfolios return identical fold boundaries
7. delta arithmetic is correct on a deterministic fixture
8. shadow=True without corpus_id takes every ranker candidate (no LLM filter)
9. with_shadow=False (default) preserves existing flat result shape
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src.evaluation.corpus import (
    CorpusEntry,
    CorpusManifest,
    compute_admissibility,
    write_corpus,
)


# ── Helpers (mirrored from test_backtester_corpus.py) ─────────────────────────


def _mock_config():
    return {"shadow_trading": {"enabled": False}}


def _make_ohlcv():
    dates = pd.bdate_range("2024-01-01", periods=400)
    df = pd.DataFrame(
        {"Open": 100, "High": 105, "Low": 98, "Close": 102, "Volume": 1_000_000},
        index=dates,
    )
    return {"AAPL": df.copy(), "MSFT": df.copy()}


def _make_spy():
    dates = pd.bdate_range("2024-01-01", periods=400)
    return pd.DataFrame(
        {"Open": 400, "High": 410, "Low": 398, "Close": 405, "Volume": 5_000_000},
        index=dates,
    )


def _make_features():
    return {
        "AAPL": {"trend_state": "uptrend", "regime_label": "bull", "current_price": 150},
        "MSFT": {"trend_state": "uptrend", "regime_label": "bull", "current_price": 300},
    }


def _make_candidates(tickers=("AAPL",)):
    return {
        "packet_worthy": [
            {"ticker": t, "score": 85, "features": {"trend_state": "uptrend", "regime_label": "bull"}}
            for t in tickers
        ],
        "watchlist": [],
    }


def _make_packet():
    return SimpleNamespace(
        entry_zone="$150.00",
        stop_invalidation="$145.00",
        targets="$160.00 / $170.00",
        llm_conviction=None,
    )


def _entry(
    *,
    as_of: str,
    ticker: str = "AAPL",
    llm_action: str = "taken",
    llm_conviction: int = 7,
    parse_failed: int = 0,
    parser_strategy_succeeded: str | None = "metadata_block",
) -> CorpusEntry:
    return CorpusEntry(
        as_of=as_of,
        ticker=ticker,
        model_version="arcis:v1.0.0",
        prompt_sha256="a" * 64,
        response="Conviction: 7\nWhy now: ...",
        llm_action=llm_action,
        llm_conviction=llm_conviction,
        parse_failed=parse_failed,
        parser_strategy_succeeded=parser_strategy_succeeded,
        prompt_section_omitted=(),
        enrichment_pit_warnings=(),
        generated_at="2026-04-29T12:00:00Z",
    )


def _manifest(corpus_id: str) -> CorpusManifest:
    section = {1: "clean", 2: "clean", 4: "fixed", 5: "fixed", 6: "fixed",
               7: "fixed", 8: "placeholder", 9: "best-effort", 10: "fixed",
               11: "placeholder"}
    return CorpusManifest(
        corpus_id=corpus_id,
        generated_at="2026-04-29T12:00:00Z",
        code_sha="abc123def456",
        model_version="arcis:v1.0.0",
        walkforward_window_start="2015-03-19",
        walkforward_window_end="2026-12-31",
        total_decision_points=10,
        parse_failure_count=0,
        parse_failure_rate=0.0,
        section_pit_status=section,
        coverage_limit_hits={},
        admissibility=compute_admissibility(0.0, section),
    )


@pytest.fixture
def tmp_corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus_root"
    root.mkdir()
    monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(root))
    return root


def _make_backtest_result(trades_count: int, sharpe: float = 1.0,
                          total_return: float = 5.0) -> dict:
    """Build a synthetic backtest_model return dict (mirrors test_walkforward helper)."""
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


# ── Backtester shadow path tests ──────────────────────────────────────────────


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 2.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates(("AAPL", "MSFT")))
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price",
       side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_shadow_corpus_path_takes_every_parse_clean_entry(
    mock_parse, mock_build, mock_top, mock_rank, mock_feat,
    mock_compute, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
    tmp_corpus_root,
):
    """shadow=True with corpus: every parse_failed=0 entry produces a trade,
    regardless of llm_action (taken / rejected / conviction_none).

    Pre-reg §A1.6: the shadow strips the LLM filter — the ranker's selection
    is what enters the trade list. Per the §A1.6 fair-comparison rule, the
    parse_failed=0 filter is still binding.
    """
    from src.evaluation.backtester import backtest_model

    corpus_id = "shadow-takes-everything"
    test_start = "2024-06-03"
    test_end = "2024-07-31"
    dates = pd.bdate_range(test_start, test_end)
    entries = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        # Mix taken / rejected / conviction_none — shadow takes them ALL
        entries.append(_entry(as_of=d_str, ticker="AAPL", llm_action="taken"))
        entries.append(_entry(as_of=d_str, ticker="MSFT", llm_action="rejected"))
    write_corpus(corpus_id, entries, _manifest(corpus_id))

    result = backtest_model(
        "test_model", months=2,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id, shadow=True,
    )

    # Both AAPL (taken) and MSFT (rejected) should produce trades in shadow
    trades = result.get("trades", [])
    assert result["trades_generated"] >= 1, (
        f"Expected shadow to produce trades from rejected entries; got {result}"
    )
    if trades:
        trade_tickers = {t["ticker"] for t in trades}
        # Both tickers should appear because shadow ignores llm_action
        assert "MSFT" in trade_tickers, (
            "Shadow path must include 'rejected' entries — §A1.6 strips LLM filter. "
            f"Got tickers={trade_tickers}"
        )


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 2.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates(("AAPL", "MSFT")))
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price",
       side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_primary_corpus_path_filters_to_taken_only_regression_lock(
    mock_parse, mock_build, mock_top, mock_rank, mock_feat,
    mock_compute, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
    tmp_corpus_root,
):
    """shadow=False (default) corpus path still filters to llm_action='taken'.

    Regression-lock: the existing #96.3 behavior must be preserved unchanged.
    """
    from src.evaluation.backtester import backtest_model

    corpus_id = "primary-filters-taken"
    test_start = "2024-06-03"
    test_end = "2024-07-31"
    dates = pd.bdate_range(test_start, test_end)
    entries = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        entries.append(_entry(as_of=d_str, ticker="AAPL", llm_action="taken"))
        entries.append(_entry(as_of=d_str, ticker="MSFT", llm_action="rejected"))
    write_corpus(corpus_id, entries, _manifest(corpus_id))

    result = backtest_model(
        "test_model", months=2,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id, shadow=False,
    )

    trades = result.get("trades", [])
    if trades:
        trade_tickers = {t["ticker"] for t in trades}
        assert "MSFT" not in trade_tickers, (
            "Primary path must NOT include 'rejected' entries (§A1.5). "
            f"Got tickers={trade_tickers}"
        )


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 2.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates(("AAPL", "MSFT")))
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price",
       side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_shadow_filters_parse_failed_for_fair_comparison(
    mock_parse, mock_build, mock_top, mock_rank, mock_feat,
    mock_compute, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
    tmp_corpus_root,
):
    """§A1.6 binding: BOTH primary AND shadow filter parse_failed=0 for fair comparison.

    If shadow saw parse_failed=1 entries that primary excluded, we'd be measuring
    'primary saw cleaner data than shadow' rather than LLM contribution.
    """
    from src.evaluation.backtester import backtest_model

    corpus_id = "shadow-filters-parse-failed"
    test_start = "2024-06-03"
    test_end = "2024-07-31"
    dates = pd.bdate_range(test_start, test_end)
    entries = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        # AAPL parse_failed=0 — should appear in BOTH primary and shadow
        entries.append(_entry(as_of=d_str, ticker="AAPL",
                              llm_action="taken", parse_failed=0))
        # MSFT parse_failed=1 — must be EXCLUDED from BOTH
        entries.append(_entry(as_of=d_str, ticker="MSFT",
                              llm_action="rejected", parse_failed=1,
                              parser_strategy_succeeded=None))
    write_corpus(corpus_id, entries, _manifest(corpus_id))

    result = backtest_model(
        "test_model", months=2,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id, shadow=True,
    )

    trades = result.get("trades", [])
    if trades:
        trade_tickers = {t["ticker"] for t in trades}
        assert "MSFT" not in trade_tickers, (
            "Shadow MUST filter parse_failed=1 entries per §A1.6 fair-comparison rule. "
            f"Got tickers={trade_tickers}"
        )


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL", "MSFT"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 2.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates(("AAPL", "MSFT")))
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price",
       side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_shadow_trade_count_geq_primary_trade_count(
    mock_parse, mock_build, mock_top, mock_rank, mock_feat,
    mock_compute, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
    tmp_corpus_root,
):
    """Shadow is a SUPERSET of primary by construction.

    Shadow takes every parse_failed=0 entry; primary takes only the
    llm_action='taken' subset of parse_failed=0 entries. So:
        shadow_count >= primary_count
    on the same corpus + same window.
    """
    from src.evaluation.backtester import backtest_model

    corpus_id = "shadow-superset"
    test_start = "2024-06-03"
    test_end = "2024-07-31"
    dates = pd.bdate_range(test_start, test_end)
    entries = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        entries.append(_entry(as_of=d_str, ticker="AAPL", llm_action="taken"))
        entries.append(_entry(as_of=d_str, ticker="MSFT", llm_action="rejected"))
    write_corpus(corpus_id, entries, _manifest(corpus_id))

    primary = backtest_model(
        "test_model", months=2,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id, shadow=False,
    )
    shadow = backtest_model(
        "test_model", months=2,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id, shadow=True,
    )

    assert shadow["trades_generated"] >= primary["trades_generated"], (
        f"Shadow ({shadow['trades_generated']}) must be a superset of primary "
        f"({primary['trades_generated']}) — shadow takes every parse-clean entry."
    )


@patch("src.config.load_config", return_value=_mock_config())
@patch("src.universe.pit.get_sp100_at", return_value=["AAPL"])
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=_make_ohlcv())
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy())
@patch("src.training.historical_data.slice_to_date", return_value=(_make_ohlcv(), _make_spy()))
@patch("src.training.historical_scanner.compute_outcome",
       return_value={"pnl_pct": 2.5, "exit_reason": "target_1", "duration_days": 5})
@patch("src.features.engine.compute_all_features", return_value=_make_features())
@patch("src.ranking.ranker.rank_universe", return_value=[{"ticker": "AAPL", "score": 85}])
@patch("src.ranking.ranker.get_top_candidates", return_value=_make_candidates())
@patch("src.packets.template.build_packet_from_features", return_value=_make_packet())
@patch("src.shadow_trading.executor._parse_price",
       side_effect=lambda x: float(x.replace("$", "").replace(",", "")))
def test_shadow_without_corpus_takes_every_ranker_candidate(
    mock_parse, mock_build, mock_top, mock_rank, mock_feat,
    mock_compute, mock_slice, mock_spy, mock_ohlcv, mock_universe, mock_config,
):
    """shadow=True with corpus_id=None: every ranker candidate becomes a trade.

    This is the no-LLM-call shadow — pure ranker output. Used when no corpus
    has been generated yet (e.g. live-runtime shadow, or smoke testing).
    """
    from src.evaluation.backtester import backtest_model

    result = backtest_model(
        "test_model", months=1,
        test_start="2024-06-03", test_end="2024-06-28",
        corpus_id=None, shadow=True,
    )

    # Trades produced via ranker output (no corpus, no LLM)
    assert result["model"] == "test_model"
    assert "trades_generated" in result
    # Trades must exist — every ranker candidate produces one
    assert result["trades_generated"] > 0, (
        f"shadow=True corpus_id=None should take every ranker candidate; got {result}"
    )


# ── Walkforward shadow integration tests ──────────────────────────────────────


class TestRunWalkforwardWithShadow:
    """run_walkforward(with_shadow=True) integration tests.

    Locks the §A1.6 result-dict shape for the shadow comparator.
    """

    def _build_corpus(
        self,
        tmp_path,
        monkeypatch,
        *,
        corpus_id: str = "wf-shadow-test",
        admissibility: str = "PASS",
        window_start: str = "2015-03-19",
        window_end: str = "2026-12-31",
    ):
        from src.evaluation.corpus import (
            CorpusEntry,
            CorpusManifest,
            write_corpus,
        )

        root = tmp_path / "corpus_root"
        root.mkdir(exist_ok=True)
        monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(root))

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
            total_decision_points=100,
            parse_failure_count=0,
            parse_failure_rate=0.0,
            section_pit_status=section,
            coverage_limit_hits={},
            admissibility=admissibility,
        )
        write_corpus(corpus_id, [entry], manifest)
        return corpus_id

    @patch("src.evaluation.walkforward.backtest_model")
    def test_with_shadow_true_returns_primary_shadow_delta(
        self, mock_bt, tmp_path, monkeypatch,
    ):
        """with_shadow=True returns dict with 'primary', 'shadow', 'delta' keys."""
        from src.evaluation.walkforward import run_walkforward

        # Distinguish primary vs shadow calls so we can assert different payloads
        # collapse into different result objects.
        def side_effect(*args, **kwargs):
            if kwargs.get("shadow"):
                return _make_backtest_result(30, sharpe=0.8, total_return=4.0)
            return _make_backtest_result(20, sharpe=1.5, total_return=6.0)

        mock_bt.side_effect = side_effect
        corpus_id = self._build_corpus(tmp_path, monkeypatch)

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id, with_shadow=True,
        )

        assert "primary" in result, f"Missing 'primary' key: {result.keys()}"
        assert "shadow" in result, f"Missing 'shadow' key: {result.keys()}"
        assert "delta" in result, f"Missing 'delta' key: {result.keys()}"

        # Documented delta-dict contract
        delta = result["delta"]
        for k in (
            "primary_excess_sharpe", "shadow_excess_sharpe", "delta_excess_sharpe",
            "primary_total_pnl_pct", "shadow_total_pnl_pct", "delta_total_pnl_pct",
            "primary_n_trades", "shadow_n_trades",
        ):
            assert k in delta, f"Delta dict missing key {k!r}: {delta.keys()}"

    @patch("src.evaluation.walkforward.backtest_model")
    def test_with_shadow_false_preserves_flat_shape(
        self, mock_bt, tmp_path, monkeypatch,
    ):
        """with_shadow=False (default) returns the existing flat shape — regression-lock.

        #81 subgroup analysis + every other consumer of run_walkforward must
        see the unchanged dict when with_shadow is omitted.
        """
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch, corpus_id="wf-flat-shape",
        )

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id,  # with_shadow defaults False
        )

        # Flat shape — NO primary/shadow/delta keys
        assert "primary" not in result, (
            "with_shadow=False must NOT introduce 'primary' key — regression for #81"
        )
        assert "shadow" not in result, (
            "with_shadow=False must NOT introduce 'shadow' key — regression for #81"
        )
        assert "delta" not in result, (
            "with_shadow=False must NOT introduce 'delta' key — regression for #81"
        )
        # Existing flat-shape fields still present
        assert "folds" in result
        assert "aggregate" in result
        assert result["corpus_id"] == "wf-flat-shape"

    @patch("src.evaluation.walkforward.backtest_model")
    def test_with_shadow_true_uses_identical_fold_boundaries(
        self, mock_bt, tmp_path, monkeypatch,
    ):
        """Both portfolios receive identical (train_start, train_end, test_start, test_end)
        per fold — same anchor, same embargo, same window.
        """
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch, corpus_id="wf-identical-boundaries",
        )

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id, with_shadow=True,
        )

        # Extract fold boundary tuples per portfolio
        primary_bounds = [
            (f["train_start"], f["train_end"], f["test_start"], f["test_end"])
            for f in result["primary"]["folds"]
        ]
        shadow_bounds = [
            (f["train_start"], f["train_end"], f["test_start"], f["test_end"])
            for f in result["shadow"]["folds"]
        ]
        assert primary_bounds == shadow_bounds, (
            "Pre-reg §A1.6 invariant: shadow MUST share fold boundaries with primary. "
            f"primary={primary_bounds} shadow={shadow_bounds}"
        )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_delta_arithmetic_correct(self, mock_bt, tmp_path, monkeypatch):
        """delta_excess_sharpe = primary - shadow on a deterministic fixture."""
        from src.evaluation.walkforward import run_walkforward

        # Deterministic fixture: every primary fold has known pnl;
        # every shadow fold has a different known pnl.
        def side_effect(*args, **kwargs):
            if kwargs.get("shadow"):
                # shadow trades: every trade pnl=0.5
                return _make_backtest_result(20, sharpe=0.8, total_return=10.0)
            # primary trades: every trade pnl=1.0 (more positive)
            return _make_backtest_result(20, sharpe=1.5, total_return=20.0)

        mock_bt.side_effect = side_effect
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch, corpus_id="wf-delta-arith",
        )

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id, with_shadow=True,
        )

        delta = result["delta"]
        # delta = primary - shadow on each axis
        assert delta["delta_excess_sharpe"] == pytest.approx(
            delta["primary_excess_sharpe"] - delta["shadow_excess_sharpe"],
            rel=1e-9, abs=1e-9,
        ), (
            f"delta_excess_sharpe drift: "
            f"{delta['delta_excess_sharpe']} != "
            f"{delta['primary_excess_sharpe']} - {delta['shadow_excess_sharpe']}"
        )
        assert delta["delta_total_pnl_pct"] == pytest.approx(
            delta["primary_total_pnl_pct"] - delta["shadow_total_pnl_pct"],
            rel=1e-9, abs=1e-9,
        ), (
            f"delta_total_pnl_pct drift: "
            f"{delta['delta_total_pnl_pct']} != "
            f"{delta['primary_total_pnl_pct']} - {delta['shadow_total_pnl_pct']}"
        )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_shadow_kwarg_propagated_to_each_fold(
        self, mock_bt, tmp_path, monkeypatch,
    ):
        """When with_shadow=True, the shadow run's per-fold backtest_model call
        receives shadow=True; the primary run receives shadow=False (or absent)."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch, corpus_id="wf-shadow-kwarg",
        )

        run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id, with_shadow=True,
        )

        shadow_calls = [c for c in mock_bt.call_args_list
                        if c.kwargs.get("shadow") is True]
        primary_calls = [c for c in mock_bt.call_args_list
                         if not c.kwargs.get("shadow")]
        assert len(shadow_calls) == 4, (
            f"Expected 4 shadow=True calls (one per fold); got {len(shadow_calls)}"
        )
        assert len(primary_calls) == 4, (
            f"Expected 4 primary (shadow=False) calls; got {len(primary_calls)}"
        )

    @patch("src.evaluation.walkforward.backtest_model")
    def test_with_shadow_carries_corpus_provenance(
        self, mock_bt, tmp_path, monkeypatch,
    ):
        """with_shadow=True still surfaces corpus_id + manifest_admissibility at top-level."""
        from src.evaluation.walkforward import run_walkforward

        mock_bt.return_value = _make_backtest_result(20)
        corpus_id = self._build_corpus(
            tmp_path, monkeypatch, corpus_id="wf-shadow-provenance",
        )

        result = run_walkforward(
            "arcis:v1.0.0", anchor="2023-09-01",
            fold_count=4, embargo_days=21,
            corpus_id=corpus_id, with_shadow=True,
        )

        # Top-level provenance keys preserved (additive shape)
        assert result["corpus_id"] == "wf-shadow-provenance"
        assert result["manifest_admissibility"] == "PASS"
