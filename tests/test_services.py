"""Tests for all 7 service modules under src/services/.

All service modules use lazy imports (from X import Y inside function bodies),
so patches target the *defining* module, not the service module namespace.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from src.platform.strategy_spec import StrategySpec


# ===================================================================
# Shared helpers
# ===================================================================

def _make_spy_df():
    dates = pd.bdate_range("2025-06-01", periods=60)
    return pd.DataFrame(
        {"Open": 400, "High": 410, "Low": 398, "Close": 405, "Volume": 5_000_000},
        index=dates,
    )


def _make_empty_spy():
    return pd.DataFrame()


def _make_packet():
    return SimpleNamespace(
        ticker="AAPL",
        entry_zone="$150.00",
        stop_invalidation="$145.00",
        targets="$160.00 / $170.00",
        llm_conviction=None,
    )


def _make_features():
    return {
        "AAPL": {
            "ticker": "AAPL",
            "current_price": 150.0,
            "trend_state": "uptrend",
            "atr_14": 5.0,
        },
    }


def _scan_config():
    return {
        "shadow_trading": {"enabled": False},
        "email": {},
        "llm": {"enabled": False},
        "_pre_llm_portfolio_snapshot": {},
    }


def _scan_strategy(raw=None):
    return StrategySpec(
        strategy_id="incumbent_v1",
        display_name="Incumbent",
        universe={"tickers": ["AAPL"]},
        entry={"kind": "scheduled"},
        exit={
            "kind": "mechanical",
            "timeout_days": 7,
            "stop": {"atr_multiple": 2.0},
            "targets": [
                {"name": "target_1", "atr_multiple": 1.5},
                {"name": "target_2", "atr_multiple": 3.0},
            ],
        },
        position_sizing={"method": "fixed_pct_equity", "pct": 0.1},
        attribution={"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        raw=raw or {},
        source="test",
    )


# ===================================================================
# 1. scan_service
# ===================================================================


@patch("src.universe.company_names.get_company_name", return_value="Apple Inc.")
@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
@patch("src.ranking.ranker.get_top_candidates", return_value={"packet_worthy": [], "watchlist": []})
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "MSFT"])
def test_scan_basic_run(mock_uni, mock_ohlcv, mock_spy, mock_feat, mock_rank,
                        mock_top, mock_model, mock_name):
    from src.services.scan_service import run_scan

    result = run_scan(_scan_config(), dry_run=True)

    assert "timestamp" in result
    assert result["tickers_scanned"] == 2
    assert result["packets_generated"] == 0
    assert result["model_version"] == "model_v3"
    assert isinstance(result["packet_worthy"], list)
    assert isinstance(result["watchlist"], list)


@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_empty_spy())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
def test_scan_empty_spy_aborts(mock_uni, mock_ohlcv, mock_spy, mock_model):
    from src.services.scan_service import run_scan

    result = run_scan(_scan_config(), dry_run=True)

    assert result["packet_worthy"] == []
    assert result["packets_generated"] == 0


def test_scan_with_packet_worthy_dry_run():
    from src.services.scan_service import run_scan

    with (
        patch("src.universe.company_names.get_company_name", return_value="Apple Inc."),
        patch("src.training.versioning.get_active_model_name", return_value="model_v3"),
        patch("src.packets.template.render_packet", return_value="RENDERED"),
        patch("src.llm.packet_writer._build_feature_prompt", return_value="prompt text"),
        patch("src.llm.packet_writer.enhance_packet_with_llm", return_value=_make_packet()),
        patch("src.packets.template.build_packet_from_features", return_value=_make_packet()),
        patch("src.features.enrichment.attach_post_scan_features"),
        patch("src.data_enrichment.enricher.enrich_features", return_value=_make_features()),
        patch(
            "src.ranking.ranker.get_top_candidates",
            return_value={
                "packet_worthy": [
                    {
                        "ticker": "AAPL",
                        "score": 90,
                        "qualification": "packet_worthy",
                        "features": {"trend_state": "uptrend", "current_price": 150.0},
                        "earnings_risk": False,
                    }
                ],
                "watchlist": [],
            },
        ),
        patch("src.ranking.ranker.rank_universe", return_value=[]),
        patch("src.features.engine.compute_all_features", return_value=_make_features()),
        patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df()),
        patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()}),
        patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]),
    ):
        result = run_scan(_scan_config(), dry_run=True)

    assert result["packets_generated"] == 1
    assert result["packet_worthy"][0]["ticker"] == "AAPL"
    assert result["packets_emailed"] == 0  # dry_run so no email


def test_scan_strategy_wires_strategy_and_attribution_hooks():
    from src.services.scan_service import run_scan

    strategy = _scan_strategy(raw={"hooks": {"attribution": ["log_before_llm", "log_after_llm"]}})
    with (
        patch("src.universe.company_names.get_company_name", return_value="Apple Inc."),
        patch("src.training.versioning.get_active_model_name", return_value="model_v3"),
        patch("src.packets.template.render_packet", return_value="RENDERED"),
        patch("src.llm.packet_writer._build_feature_prompt", return_value="prompt text"),
        patch("src.llm.packet_writer.enhance_packet_with_llm", return_value=_make_packet()),
        patch("src.packets.template.build_packet_from_features", return_value=_make_packet()) as mock_build,
        patch("src.attribution.logger.log_attribution_after_llm") as mock_after,
        patch("src.attribution.logger.log_attribution_before_llm", return_value="attr-1") as mock_before,
        patch(
            "src.ranking.ranker.get_top_candidates",
            return_value={
                "packet_worthy": [
                    {
                        "ticker": "AAPL",
                        "score": 90,
                        "qualification": "packet_worthy",
                        "features": {"trend_state": "uptrend", "current_price": 150.0},
                        "earnings_risk": False,
                    }
                ],
                "watchlist": [],
            },
        ),
        patch("src.ranking.ranker.rank_universe", return_value=[]) as mock_rank,
        patch("src.features.enrichment.attach_post_scan_features") as mock_post_scan,
        patch("src.data_enrichment.enricher.enrich_features", return_value=_make_features()) as mock_enrich,
        patch("src.features.engine.compute_all_features", return_value=_make_features()) as mock_feat,
        patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df()) as mock_spy,
        patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()}),
        patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]),
    ):
        result = run_scan(_scan_config(), dry_run=True, strategy=strategy)

    assert result["packets_generated"] == 1
    feat_args, feat_kwargs = mock_feat.call_args
    assert feat_kwargs == {"strategy": strategy}
    assert list(feat_args[0]) == ["AAPL"]
    assert feat_args[1].equals(mock_spy.return_value)
    mock_enrich.assert_called_once_with(_make_features(), _scan_config(), strategy=strategy)
    mock_post_scan.assert_called_once()
    assert mock_post_scan.call_args.kwargs.get("strategy") == strategy
    mock_rank.assert_called_once_with(_make_features(), strategy=strategy)
    mock_build.assert_called_once_with("AAPL", {"trend_state": "uptrend", "current_price": 150.0, "_score": 90, "signal_price": 150.0}, _scan_config(), strategy=strategy)
    mock_before.assert_called_once()
    mock_after.assert_called_once()


def test_scan_strategy_without_attribution_hooks_skips_logging():
    from src.services.scan_service import run_scan

    strategy = _scan_strategy()
    with (
        patch("src.universe.company_names.get_company_name", return_value="Apple Inc."),
        patch("src.training.versioning.get_active_model_name", return_value="model_v3"),
        patch("src.packets.template.render_packet", return_value="RENDERED"),
        patch("src.llm.packet_writer._build_feature_prompt", return_value="prompt text"),
        patch("src.llm.packet_writer.enhance_packet_with_llm", return_value=_make_packet()),
        patch("src.packets.template.build_packet_from_features", return_value=_make_packet()),
        patch("src.attribution.logger.log_attribution_after_llm") as mock_after,
        patch("src.attribution.logger.log_attribution_before_llm", return_value="attr-1") as mock_before,
        patch(
            "src.ranking.ranker.get_top_candidates",
            return_value={
                "packet_worthy": [
                    {
                        "ticker": "AAPL",
                        "score": 90,
                        "qualification": "packet_worthy",
                        "features": {"trend_state": "uptrend", "current_price": 150.0},
                        "earnings_risk": False,
                    }
                ],
                "watchlist": [],
            },
        ),
        patch("src.ranking.ranker.rank_universe", return_value=[]),
        patch("src.features.enrichment.attach_post_scan_features"),
        patch("src.data_enrichment.enricher.enrich_features", return_value=_make_features()),
        patch("src.features.engine.compute_all_features", return_value=_make_features()),
        patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df()),
        patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()}),
        patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]),
    ):
        result = run_scan(_scan_config(), dry_run=True, strategy=strategy)

    assert result["packets_generated"] == 1
    mock_before.assert_not_called()
    mock_after.assert_not_called()


# -------------------------------------------------------------------
# #627 — pre-LLM filter tests
# -------------------------------------------------------------------


@patch("src.universe.company_names.get_company_name", return_value="Apple Inc.")
@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
@patch("src.packets.template.render_packet", return_value="RENDERED")
@patch("src.llm.packet_writer._build_feature_prompt", return_value="prompt text")
@patch("src.llm.packet_writer.enhance_packet_with_llm")
@patch("src.packets.template.build_packet_from_features")
@patch("src.shadow_trading.executor._check_paper_buying_power_allocation", return_value=True)
@patch("src.ranking.ranker.get_top_candidates")
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"BK": pd.DataFrame()})
@patch("src.universe.sp100.get_sp100_universe", return_value=["BK"])
def test_event_risk_hard_block_skips_llm(
    mock_uni, mock_ohlcv, mock_spy, mock_feat, mock_rank, mock_top,
    mock_bp, mock_build, mock_enhance, mock_prompt, mock_render, mock_model, mock_name
):
    """#627 — candidate with event_risk_multiplier=0 must not call enhance_packet_with_llm."""
    mock_top.return_value = {
        "packet_worthy": [
            {
                "ticker": "BK",
                "score": 88,
                "qualification": "packet_worthy",
                "features": {
                    "trend_state": "uptrend",
                    "sector": "Financials",
                    "event_risk_multiplier": 0.0,
                    "current_price": 100.0,
                },
                "earnings_risk": True,
            }
        ],
        "watchlist": [],
    }

    def _build_side(ticker, *a, **kw):
        return SimpleNamespace(
            ticker=ticker,
            entry_zone="$100.00",
            stop_invalidation="$95.00",
            targets="$110.00",
            position_sizing=SimpleNamespace(allocation_dollars=5000.0),
            llm_conviction=None,
        )

    mock_build.side_effect = _build_side
    mock_enhance.return_value = _make_packet()

    from src.services.scan_service import run_scan
    result = run_scan(_scan_config(), dry_run=True)

    mock_enhance.assert_not_called(), "LLM must not be called for event-risk hard-block candidates"


@patch("src.universe.company_names.get_company_name", return_value="Apple Inc.")
@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
@patch("src.packets.template.render_packet", return_value="RENDERED")
@patch("src.llm.packet_writer._build_feature_prompt", return_value="prompt text")
@patch("src.llm.packet_writer.enhance_packet_with_llm")
@patch("src.packets.template.build_packet_from_features")
@patch("src.shadow_trading.executor._check_paper_buying_power_allocation", return_value=True)
@patch("src.ranking.ranker.get_top_candidates")
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"BK": pd.DataFrame(), "AAPL": pd.DataFrame()})
@patch("src.universe.sp100.get_sp100_universe", return_value=["BK", "AAPL"])
def test_sector_concentration_pre_filter_skips_llm(
    mock_uni, mock_ohlcv, mock_spy, mock_feat, mock_rank, mock_top,
    mock_bp, mock_build, mock_enhance, mock_prompt, mock_render, mock_model, mock_name
):
    """#627 — candidate that would breach sector cap must not call enhance_packet_with_llm.

    Financials at 32% of portfolio + this trade would breach 30% cap.
    BK (Financials) should be pre-filtered; AAPL (Technology) should proceed to LLM.
    """
    mock_top.return_value = {
        "packet_worthy": [
            {
                "ticker": "BK",
                "score": 88,
                "qualification": "packet_worthy",
                "features": {
                    "trend_state": "uptrend",
                    "sector": "Financials",
                    "event_risk_multiplier": 1.0,
                    "current_price": 100.0,
                },
                "earnings_risk": False,
            },
            {
                "ticker": "AAPL",
                "score": 85,
                "qualification": "packet_worthy",
                "features": {
                    "trend_state": "uptrend",
                    "sector": "Technology",
                    "event_risk_multiplier": 1.0,
                    "current_price": 150.0,
                },
                "earnings_risk": False,
            },
        ],
        "watchlist": [],
    }

    def _build_side(ticker, *a, **kw):
        pkt = SimpleNamespace(
            ticker=ticker,
            entry_zone="$100.00",
            stop_invalidation="$95.00",
            targets="$110.00",
            position_sizing=SimpleNamespace(allocation_dollars=5000.0),
            llm_conviction=None,
        )
        return pkt

    mock_build.side_effect = _build_side
    mock_enhance.side_effect = lambda pkt, *a, **kw: pkt

    from src.services.scan_service import run_scan

    config = dict(_scan_config())
    config["risk"] = {
        "max_sector_pct": 0.30,
        "starting_capital": 15000,
    }
    config["_pre_llm_portfolio_snapshot"] = {
        "equity": 15000.0,
        "sector_exposure": {"Financials": 0.32},
    }

    result = run_scan(config, dry_run=True)

    called_tickers = [c.args[0].ticker for c in mock_enhance.call_args_list]
    assert "BK" not in called_tickers, "Financials over cap — BK must be pre-filtered before LLM"
    assert "AAPL" in called_tickers, "AAPL (Technology) should reach LLM"


# ===================================================================
# 2. shadow_service
# ===================================================================


@patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0)
@patch("src.journal.store.get_open_shadow_trades", return_value=[
    {
        "trade_id": "t1", "ticker": "AAPL", "actual_entry_price": 150.0,
        "entry_price": 150.0, "stop_price": 145, "target_1": 160, "target_2": 170,
        "planned_shares": 10, "status": "open", "direction": "long",
        "created_at": "2025-06-01",
    },
])
def test_shadow_status_basic(mock_trades, mock_price):
    from src.services.shadow_service import get_shadow_status

    config = {"shadow_trading": {"timeout_days": 15}}
    result = get_shadow_status(config)

    assert result["open_count"] == 1
    trade = result["open_trades"][0]
    assert trade["ticker"] == "AAPL"
    assert trade["current_price"] == 155.0
    assert trade["pnl_dollars"] == 5.0
    assert trade["pnl_pct"] > 0
    assert result["total_unrealized_pnl"] == 50.0  # 5 * 10 shares


@patch("src.shadow_trading.executor._get_current_price_safe", return_value=None)
@patch("src.journal.store.get_open_shadow_trades", return_value=[
    {"trade_id": "t2", "ticker": "XYZ", "entry_price": 0, "status": "open",
     "created_at": "2025-06-01"},
])
def test_shadow_status_no_price(mock_trades, mock_price):
    from src.services.shadow_service import get_shadow_status

    result = get_shadow_status({"shadow_trading": {}})

    trade = result["open_trades"][0]
    assert trade["pnl_dollars"] is None
    assert trade["pnl_pct"] is None


@patch("src.journal.store.get_open_shadow_trades", return_value=[])
def test_shadow_status_empty(mock_trades):
    from src.services.shadow_service import get_shadow_status

    result = get_shadow_status({"shadow_trading": {}})

    assert result["open_count"] == 0
    assert result["total_unrealized_pnl"] is None


@patch("src.shadow_trading.metrics.compute_shadow_metrics", return_value={
    "total_trades": 5, "wins": 3, "losses": 2, "win_rate": 0.6,
    "avg_gain": 4.0, "avg_loss": -2.0, "expectancy": 1.6, "total_pnl": 8.0,
})
@patch("src.journal.store.get_closed_shadow_trades", return_value=[
    {"trade_id": "c1", "ticker": "AAPL", "pnl_pct": 5.0, "exit_reason": "target_1",
     "created_at": "2025-05-01"},
])
def test_shadow_history(mock_closed, mock_metrics):
    from src.services.shadow_service import get_shadow_history

    result = get_shadow_history(days=30)

    assert len(result["trades"]) == 1
    assert result["metrics"]["win_rate"] == 0.6


@patch("src.journal.store.get_closed_shadow_trades", return_value=[])
def test_shadow_history_empty(mock_closed):
    from src.services.shadow_service import get_shadow_history

    result = get_shadow_history(days=7)

    assert result["trades"] == []
    assert result["metrics"]["total_trades"] == 0


@patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[])
@patch("src.shadow_trading.alpaca_adapter.get_account_info", return_value={"equity": 100_000, "buying_power": 200_000})
def test_shadow_account(mock_acct, mock_pos):
    from src.services.shadow_service import get_shadow_account

    result = get_shadow_account()

    assert result["account"]["equity"] == 100_000
    assert isinstance(result["positions"], list)


# ===================================================================
# 3. system_service
# ===================================================================


@patch("src.training.versioning.get_training_example_counts", return_value={"total": 500})
@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
@patch("src.llm.client.is_llm_available", return_value=True)
def test_system_status_basic(mock_llm, mock_model, mock_train):
    from src.services.system_service import get_system_status

    config = {
        "email": {"smtp_server": "smtp.gmail.com", "username": "me@gmail.com",
                   "password": "secret"},
        "shadow_trading": {"enabled": True},
        "alpaca": {"api_key": "", "api_secret": "", "base_url": ""},
        "llm": {"enabled": True, "model": "qwen3:8b"},
        "training": {"enabled": True},
        "bootcamp": {"enabled": False},
    }
    result = get_system_status(config)

    assert result["config_loaded"] is True
    assert result["email_configured"] is True
    assert result["ollama_available"] is True
    assert result["llm_enabled"] is True
    assert result["model_version"] == "model_v3"
    assert result["shadow_trading_enabled"] is True
    assert result["training_enabled"] is True
    assert result["training_examples"] == 500
    assert result["bootcamp_enabled"] is False
    assert result["bootcamp_phase"] is None


@patch("src.training.versioning.get_training_example_counts", return_value={"total": 0})
@patch("src.training.versioning.get_active_model_name", return_value="base")
@patch("src.llm.client.is_llm_available", return_value=False)
def test_system_status_empty_config(mock_llm, mock_model, mock_train):
    from src.services.system_service import get_system_status

    result = get_system_status({})

    assert result["config_loaded"] is False
    assert result["email_configured"] is False
    assert result["alpaca_connected"] is False
    assert result["shadow_trading_enabled"] is False
    assert result["training_enabled"] is False


# ===================================================================
# 4. training_service
# ===================================================================


@patch("src.training.trainer.check_model_performance", return_value={"action": "none", "status": "ok"})
@patch("src.training.trainer.should_train", return_value=(False, "not enough data"))
@patch("src.training.versioning.get_new_examples_since", return_value=25)
@patch("src.training.versioning.get_training_example_counts", return_value={
    "total": 500, "synthetic_claude": 200, "outcome_win": 180, "outcome_loss": 120,
})
@patch("src.training.versioning.get_active_model_version", return_value={
    "version_id": 3, "version_name": "model_v3", "created_at": "2025-05-01", "status": "active",
})
@patch("src.training.versioning.get_active_model_name", return_value="model_v3")
def test_training_status(mock_name, mock_ver, mock_counts, mock_new, mock_should, mock_perf):
    from src.services.training_service import get_training_status

    result = get_training_status()

    assert result["model_name"] == "model_v3"
    assert result["dataset_total"] == 500
    assert result["dataset_synthetic"] == 200
    assert result["new_since_last_train"] == 25
    assert result["train_queued"] is False
    assert "Passing" in result["rollback_status"]


@patch("src.training.trainer.check_model_performance", return_value={"action": "waiting", "trades_needed": 10})
@patch("src.training.trainer.should_train", return_value=(True, "50 new examples"))
@patch("src.training.versioning.get_training_example_counts", return_value={"total": 100})
@patch("src.training.versioning.get_active_model_version", return_value=None)
@patch("src.training.versioning.get_active_model_name", return_value="base")
def test_training_status_no_active_version(mock_name, mock_ver, mock_counts, mock_should, mock_perf):
    from src.services.training_service import get_training_status

    result = get_training_status()

    assert result["active_version"] is None
    assert result["new_since_last_train"] == 100  # falls back to total
    assert result["train_queued"] is True
    assert "Watching" in result["rollback_status"]


@patch("src.training.versioning.get_performance_by_version", return_value=[
    {"version_name": "model_v1", "trade_count": 10, "win_rate": 0.6, "expectancy": 1.2},
])
@patch("src.training.versioning.get_model_history", return_value=[
    {"version_id": 1, "version_name": "model_v1", "created_at": "2025-04-01",
     "training_examples_count": 200, "synthetic_examples_count": 100,
     "outcome_examples_count": 100, "status": "active"},
])
def test_training_history(mock_hist, mock_perf):
    from src.services.training_service import get_training_history

    result = get_training_history()

    assert len(result["versions"]) == 2  # model_v1 + base
    assert result["versions"][0]["version_name"] == "model_v1"
    assert result["versions"][0]["win_rate"] == 0.6
    assert result["versions"][-1]["version_name"] == "base"


@patch("src.training.report.generate_training_report", return_value="## Training Report\nAll good.")
def test_training_report(mock_report):
    from src.services.training_service import get_training_report

    result = get_training_report()
    assert "Training Report" in result


@patch("src.training.bootstrap.estimate_bootstrap_cost", return_value=2.50)
@patch("src.training.bootstrap.generate_synthetic_training_data", return_value=100)
def test_run_bootstrap(mock_gen, mock_cost):
    from src.services.training_service import run_bootstrap

    result = run_bootstrap(count=100)

    assert result["count_created"] == 100
    assert result["estimated_cost"] == 2.50


@patch("src.training.trainer.run_fine_tune", return_value={"version": "model_v4", "status": "ok"})
def test_run_fine_tune_service(mock_ft):
    from src.services.training_service import run_fine_tune_service

    result = run_fine_tune_service()
    assert result["version"] == "model_v4"


@patch("src.training.versioning.rollback_model", return_value={"rolled_back_to": "model_v2"})
def test_rollback_model_service(mock_rb):
    from src.services.training_service import rollback_model_service

    result = rollback_model_service()
    assert result["rolled_back_to"] == "model_v2"


# ===================================================================
# 5. review_service
# ===================================================================


@patch("src.journal.store.get_recommendations_pending_review", return_value=[
    {"recommendation_id": "r1", "ticker": "AAPL", "score": 85},
    {"recommendation_id": "r2", "ticker": "MSFT", "score": 72},
])
def test_get_pending_reviews(mock_pending):
    from src.services.review_service import get_pending_reviews

    result = get_pending_reviews()
    assert len(result) == 2
    assert result[0]["ticker"] == "AAPL"


@patch("src.journal.store.get_recommendations_pending_review", return_value=[])
def test_get_pending_reviews_empty(mock_pending):
    from src.services.review_service import get_pending_reviews

    assert get_pending_reviews() == []


@patch("src.journal.store.get_recommendation_by_id", return_value={"recommendation_id": "r1", "ticker": "AAPL"})
def test_get_recommendation(mock_get):
    from src.services.review_service import get_recommendation

    result = get_recommendation("r1")
    assert result["ticker"] == "AAPL"


@patch("src.journal.store.get_recommendation_by_id", return_value=None)
def test_get_recommendation_not_found(mock_get):
    from src.services.review_service import get_recommendation

    assert get_recommendation("nonexistent") is None


@patch("src.journal.store.update_recommendation_review")
def test_submit_review_success(mock_update):
    from src.services.review_service import submit_review

    assert submit_review("r1", {"action": "approved"}) is True
    mock_update.assert_called_once_with("r1", {"action": "approved"})


@patch("src.journal.store.update_recommendation_review", side_effect=Exception("DB error"))
def test_submit_review_failure(mock_update):
    from src.services.review_service import submit_review

    assert submit_review("r1", {"action": "approved"}) is False


@patch("src.journal.store.update_recommendation")
@patch("src.journal.store.get_recommendations_by_ticker", return_value=[
    {"recommendation_id": "r1"},
])
def test_mark_executed(mock_get, mock_update):
    from src.services.review_service import mark_executed

    assert mark_executed("aapl") is True
    mock_update.assert_called_once_with("r1", {"ryan_executed": 1})


@patch("src.journal.store.get_recommendations_by_ticker", return_value=[])
def test_mark_executed_no_recs(mock_get):
    from src.services.review_service import mark_executed

    assert mark_executed("XYZ") is False


@patch("src.evaluation.scorecard.generate_weekly_scorecard", return_value="## Scorecard\nWin rate: 60%")
def test_get_scorecard(mock_sc):
    from src.services.review_service import get_scorecard

    result = get_scorecard(weeks=2)
    assert "Scorecard" in result


@patch("src.evaluation.scorecard.generate_bootcamp_scorecard", return_value="## Bootcamp Report")
def test_get_bootcamp_report(mock_bc):
    from src.services.review_service import get_bootcamp_report

    result = get_bootcamp_report(days=14)
    assert "Bootcamp" in result


@patch("src.journal.store.get_recommendation_by_id", return_value={
    "lesson_tag": "position_sizing", "assistant_postmortem": "Too large",
})
@patch("src.journal.store.get_closed_shadow_trades", return_value=[
    {"trade_id": "t1", "ticker": "AAPL", "recommendation_id": "r1",
     "exit_reason": "stop", "pnl_dollars": -50, "actual_exit_time": "2025-06-10",
     "created_at": "2025-06-01"},
])
def test_get_postmortems(mock_closed, mock_rec):
    from src.services.review_service import get_postmortems

    result = get_postmortems(limit=5)
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["lesson_tag"] == "position_sizing"


@patch("src.journal.store.get_closed_shadow_trades", return_value=[])
def test_get_postmortems_empty(mock_closed):
    from src.services.review_service import get_postmortems

    assert get_postmortems() == []


@patch("src.journal.store.get_recommendation_by_id", return_value=None)
@patch("src.journal.store.get_closed_shadow_trades", return_value=[
    {"trade_id": "t2", "ticker": "GOOG", "recommendation_id": None,
     "exit_reason": "timeout", "pnl_dollars": 0, "created_at": "2025-06-01"},
])
def test_get_postmortems_no_recommendation(mock_closed, mock_rec):
    from src.services.review_service import get_postmortems

    result = get_postmortems()
    assert result[0]["lesson_tag"] == "n/a"
    assert result[0]["postmortem"] == "n/a"


@patch("src.journal.store.get_recommendation_by_id", return_value={"recommendation_id": "r5"})
def test_get_postmortem_detail(mock_rec):
    from src.services.review_service import get_postmortem_detail

    result = get_postmortem_detail("r5")
    assert result["recommendation_id"] == "r5"


# ===================================================================
# 6. recap_service
# ===================================================================


@patch("src.notifications.email_digest.enqueue_for_email_digest")
@patch("src.packets.eod_recap.build_eod_recap", return_value="EOD Recap body text")
@patch("src.journal.store.get_todays_recommendations", return_value=[
    {"ticker": "AAPL"}, {"ticker": "MSFT"},
])
@patch("src.ranking.ranker.get_top_candidates", return_value={
    "packet_worthy": [{"ticker": "AAPL"}],
    "watchlist": [{"ticker": "GOOG"}, {"ticker": "AMZN"}],
})
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "MSFT", "GOOG"])
def test_recap_basic(mock_uni, mock_ohlcv, mock_spy, mock_feat, mock_rank,
                     mock_top, mock_journal, mock_build, mock_enqueue):
    from src.services.recap_service import generate_eod_recap

    result = generate_eod_recap({"shadow_trading": {"enabled": False}})

    assert "timestamp" in result
    assert result["packets_today"] == 2
    assert result["watchlist_count"] == 2
    assert result["email_body"] == "EOD Recap body text"


@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_empty_spy())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
def test_recap_empty_spy(mock_uni, mock_ohlcv, mock_spy):
    from src.services.recap_service import generate_eod_recap

    result = generate_eod_recap({})

    assert result["packets_today"] == 0
    assert "ERROR" in result["email_body"]


@patch("src.notifications.email_digest.enqueue_for_email_digest")
@patch("src.packets.eod_recap.build_eod_recap", return_value="body")
@patch("src.journal.store.get_todays_recommendations", return_value=[])
@patch("src.ranking.ranker.get_top_candidates", return_value={"packet_worthy": [], "watchlist": []})
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
@patch("src.universe.sp100.get_sp100_universe", return_value=[])
def test_recap_no_journal_entries(mock_uni, mock_ohlcv, mock_spy, mock_feat,
                                   mock_rank, mock_top, mock_journal, mock_build, mock_enqueue):
    from src.services.recap_service import generate_eod_recap

    result = generate_eod_recap({"shadow_trading": {"enabled": False}})

    assert result["packets_today"] == 0
    assert result["watchlist_count"] == 0


# ===================================================================
# 7. watchlist_service
# ===================================================================


@patch("src.notifications.email_digest.enqueue_for_email_digest")
@patch("src.universe.company_names.get_company_name", return_value="Apple Inc.")
@patch("src.packets.watchlist.build_morning_watchlist", return_value="Morning watchlist body")
@patch("src.llm.watchlist_writer.generate_watchlist_narrative", return_value="Market is bullish today.")
@patch("src.ranking.ranker.get_top_candidates", return_value={
    "packet_worthy": [
        {"ticker": "AAPL", "score": 90, "qualification": "packet_worthy",
         "features": {"trend_state": "uptrend", "relative_strength_state": "strong",
                      "pullback_depth_pct": -3.0},
         "earnings_risk": False},
    ],
    "watchlist": [
        {"ticker": "GOOG", "score": 55, "qualification": "watchlist",
         "features": {"trend_state": "uptrend", "relative_strength_state": "neutral",
                      "pullback_depth_pct": -6.0},
         "earnings_risk": False},
    ],
})
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={"AAPL": pd.DataFrame()})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "GOOG"])
def test_watchlist_basic(mock_uni, mock_ohlcv, mock_spy, mock_feat, mock_rank,
                         mock_top, mock_narr, mock_build, mock_name, mock_enqueue):
    from src.services.watchlist_service import generate_morning_watchlist

    result = generate_morning_watchlist({"llm": {"enabled": True}})

    assert "timestamp" in result
    assert result["narrative"] == "Market is bullish today."
    assert len(result["packet_worthy"]) == 1
    assert result["packet_worthy"][0]["ticker"] == "AAPL"
    assert result["packet_worthy"][0]["company_name"] == "Apple Inc."
    assert len(result["watchlist"]) == 1
    assert result["email_body"] == "Morning watchlist body"
    assert "raw_candidates" in result


@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_empty_spy())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
@patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
def test_watchlist_empty_spy(mock_uni, mock_ohlcv, mock_spy):
    from src.services.watchlist_service import generate_morning_watchlist

    result = generate_morning_watchlist({})

    assert result["packet_worthy"] == []
    assert result["watchlist"] == []
    assert result["narrative"] is None
    assert "ERROR" in result["email_body"]


@patch("src.notifications.email_digest.enqueue_for_email_digest")
@patch("src.universe.company_names.get_company_name", return_value="N/A")
@patch("src.packets.watchlist.build_morning_watchlist", return_value="body")
@patch("src.llm.watchlist_writer.generate_watchlist_narrative", return_value=None)
@patch("src.ranking.ranker.get_top_candidates", return_value={"packet_worthy": [], "watchlist": []})
@patch("src.ranking.ranker.rank_universe", return_value=[])
@patch("src.features.engine.compute_all_features", return_value={})
@patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=_make_spy_df())
@patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
@patch("src.universe.sp100.get_sp100_universe", return_value=[])
def test_watchlist_no_candidates(mock_uni, mock_ohlcv, mock_spy, mock_feat,
                                  mock_rank, mock_top, mock_narr, mock_build, mock_name, mock_enqueue):
    from src.services.watchlist_service import generate_morning_watchlist

    result = generate_morning_watchlist({"llm": {"enabled": False}})

    assert result["packet_worthy"] == []
    assert result["watchlist"] == []
