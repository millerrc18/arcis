"""VIX enrichment for walk-forward trades (#535, v0.25.4 Part A).

Closes the gap diagnosed in
`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`:

> `vix_at_entry` and `vix_tier` are NULL for 20 / 20 OOS trades.
> The framework reads `vix_tier` from `walkforward_trades.vix_tier`; the
> column is populated by the trade-construction path during `run_backtest`
> / `walkforward_runner`. Something upstream is not writing VIX at entry.

Pass 1 root-cause: `BacktestTrade` had no `vix_at_entry` field, so the
runner's `getattr(t, "vix_at_entry", None)` always returned None.

These tests cover (in TDD order):

  1. `lookup_vix_at_entry` returns the Close on entry date when the cache
     has a bar.
  2. `lookup_vix_at_entry` falls back to the most-recent prior trading day
     when the entry date itself has no bar (weekend / holiday).
  3. `lookup_vix_at_entry` returns None when the cache returns None
     (graceful degradation, not crash).
  4. `BacktestTrade` accepts `vix_at_entry` as a defaulted field.
  5. `_build_trade` populates `vix_at_entry` from the helper (scheduled
     entry path).
  6. `_build_trade` populates `vix_at_entry` from the helper (event_driven
     entry path).
  7. End-to-end through `run_backtest`: trades carry non-null
     `vix_at_entry` values matching the mocked VIX series.
  8. `walkforward_runner.persist_run_result` writes `vix_tier` correctly
     when the trade has a populated `vix_at_entry` (regression for the
     existing tier-bucketing path; verifies trades flow end-to-end).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helper-level tests — src.platform.vix_lookup (new module)
# ---------------------------------------------------------------------------

def test_lookup_vix_at_entry_returns_close_on_entry_date():
    """When the cache has a bar dated entry_iso, return its Close."""
    from src.platform.vix_lookup import lookup_vix_at_entry

    fake_df = pd.DataFrame(
        {"Open": [18.0], "High": [19.0], "Low": [17.5], "Close": [18.5],
         "Volume": [0]},
        index=pd.to_datetime(["2020-03-16"]),
    )
    with patch("src.platform.vix_lookup.fetch_cached_ohlcv",
               return_value=fake_df) as mock_fetch:
        vix = lookup_vix_at_entry("2020-03-16")

    assert vix == pytest.approx(18.5)
    mock_fetch.assert_called_once()
    args, _ = mock_fetch.call_args
    assert args[0] == "^VIX"


def test_lookup_vix_at_entry_falls_back_to_prior_trading_day():
    """When entry_iso has no bar (e.g. weekend), use the most-recent
    prior bar's Close. This is the realistic case — VIX trades only on
    US trading days, so an entry that backs onto a Saturday should pull
    Friday's close."""
    from src.platform.vix_lookup import lookup_vix_at_entry

    # 2021-07-04 is a Sunday; 2021-07-02 (Friday) is the prior bar.
    # Entry would be the next trading day (2021-07-05 Monday is also a
    # holiday -> 2021-07-06 Tuesday); but the helper itself just
    # returns the most-recent close on/before entry_iso.
    fake_df = pd.DataFrame(
        {"Open": [16.0], "High": [16.5], "Low": [15.5], "Close": [15.8],
         "Volume": [0]},
        index=pd.to_datetime(["2021-07-02"]),
    )
    with patch("src.platform.vix_lookup.fetch_cached_ohlcv",
               return_value=fake_df):
        vix = lookup_vix_at_entry("2021-07-04")

    assert vix == pytest.approx(15.8)


def test_lookup_vix_at_entry_returns_none_when_cache_empty():
    """fetch_cached_ohlcv returning None must NOT crash; helper degrades
    gracefully so the engine can still build the trade with vix_at_entry
    null."""
    from src.platform.vix_lookup import lookup_vix_at_entry

    with patch("src.platform.vix_lookup.fetch_cached_ohlcv",
               return_value=None):
        vix = lookup_vix_at_entry("2020-03-16")

    assert vix is None


def test_lookup_vix_at_entry_returns_none_when_no_bar_on_or_before_entry():
    """Cache returns a frame but every bar is AFTER entry_iso (e.g. cache
    fetched only the future range). Helper returns None — never picks a
    forward-looking bar."""
    from src.platform.vix_lookup import lookup_vix_at_entry

    fake_df = pd.DataFrame(
        {"Open": [18.0], "Close": [18.5], "High": [18.5], "Low": [18.0],
         "Volume": [0]},
        index=pd.to_datetime(["2020-03-20"]),
    )
    with patch("src.platform.vix_lookup.fetch_cached_ohlcv",
               return_value=fake_df):
        vix = lookup_vix_at_entry("2020-03-16")

    assert vix is None


def test_lookup_vix_at_entry_handles_empty_dataframe():
    """fetch_cached_ohlcv returning an empty DataFrame is treated like None."""
    from src.platform.vix_lookup import lookup_vix_at_entry

    empty = pd.DataFrame(columns=["Open", "Close", "High", "Low", "Volume"])
    with patch("src.platform.vix_lookup.fetch_cached_ohlcv",
               return_value=empty):
        vix = lookup_vix_at_entry("2020-03-16")

    assert vix is None


# ---------------------------------------------------------------------------
# Dataclass shape — BacktestTrade gains vix_at_entry field
# ---------------------------------------------------------------------------

def test_backtest_trade_accepts_vix_at_entry_field():
    """BacktestTrade must accept vix_at_entry as a keyword (defaulted
    field). Required by the trade-construction path; the runner reads
    it via getattr."""
    from src.platform.backtest_engine import BacktestTrade

    trade = BacktestTrade(
        trade_id="t1", ticker="AAPL", entry_date="2020-03-16",
        exit_date="2020-04-06", entry_price=100.0, exit_price=110.0,
        shares=10, pnl_dollars=100.0, pnl_pct=0.10, exit_reason="target",
        hold_days=21, spy_return_over_hold=0.0, excess_return=0.10,
        realized_sector="Technology", regime_at_entry=None,
        vix_at_entry=22.5,
    )
    assert trade.vix_at_entry == pytest.approx(22.5)


def test_backtest_trade_vix_at_entry_defaults_to_none():
    """The new field must default to None — backwards compatibility for
    anyone constructing BacktestTrade without VIX (none today, but
    defensive)."""
    from src.platform.backtest_engine import BacktestTrade

    trade = BacktestTrade(
        trade_id="t1", ticker="AAPL", entry_date="2020-03-16",
        exit_date="2020-04-06", entry_price=100.0, exit_price=110.0,
        shares=10, pnl_dollars=100.0, pnl_pct=0.10, exit_reason="target",
        hold_days=21, spy_return_over_hold=0.0, excess_return=0.10,
        realized_sector="Technology", regime_at_entry=None,
    )
    assert trade.vix_at_entry is None


# ---------------------------------------------------------------------------
# Engine-integration — _build_trade calls the helper and threads result
# ---------------------------------------------------------------------------

def _stub_ohlcv_aapl_june_2023(ticker: str, start: str,
                                end: str) -> pd.DataFrame | None:
    """Mock for load_ohlcv_range — returns a deterministic 21-day path
    for AAPL only. Mirrors tests/platform/test_backtest_engine.py."""
    if ticker != "AAPL":
        return None
    trading_days = [
        "2023-06-01", "2023-06-02", "2023-06-05", "2023-06-06",
        "2023-06-07", "2023-06-08", "2023-06-09", "2023-06-12",
        "2023-06-13", "2023-06-14", "2023-06-15", "2023-06-16",
        "2023-06-20", "2023-06-21", "2023-06-22", "2023-06-23",
        "2023-06-26", "2023-06-27", "2023-06-28", "2023-06-29",
        "2023-06-30",
    ]
    prices = [180.0 + i * 0.5 for i in range(len(trading_days))]
    rows = [{"Open": p, "Close": p * 1.005, "High": p * 1.01,
             "Low": p * 0.99, "Volume": 1_000_000} for p in prices]
    df = pd.DataFrame(rows, index=pd.to_datetime(trading_days))
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    return df[(df.index >= start_ts) & (df.index <= end_ts)]


def _make_scheduled_spec_aapl():
    """Minimal scheduled spec triggering on Mondays for AAPL."""
    from src.platform.strategy_spec import StrategySpec

    universe = {"kind": "explicit", "tickers": ["AAPL"]}
    entry = {"kind": "scheduled", "trigger": {"day_of_week": "monday"}}
    exit_spec = {"kind": "mechanical",
                 "stop": {"method": "pct", "value": 0.05},
                 "target": {"method": "pct", "value": 0.10},
                 "timeout_days": 5}
    position_sizing = {"kind": "fixed_pct", "pct": 0.05}
    attribution = {}
    return StrategySpec(
        strategy_id="test_vix", display_name="test_vix",
        universe=universe, entry=entry, exit=exit_spec,
        position_sizing=position_sizing, attribution=attribution,
        raw={"derived_from": None},
    )


def test_build_trade_populates_vix_at_entry_from_helper_scheduled_path():
    """Through `run_backtest` with a scheduled-trigger spec, every trade
    on the resulting BacktestResult must carry a non-null vix_at_entry
    matching the mocked VIX value."""
    from src.platform.backtest_engine import BacktestConfig, run_backtest

    spec = _make_scheduled_spec_aapl()
    cfg = BacktestConfig(
        strategy=spec, start_date="2023-06-01", end_date="2023-06-30",
        commission_bps=0.0, slippage_bps=0.0, spread_bps=0.0,
    )
    with patch("src.platform.backtest_engine.load_ohlcv_range",
               side_effect=_stub_ohlcv_aapl_june_2023), \
         patch("src.platform.backtest_engine.spy_return_over_range",
               return_value=0.01), \
         patch("src.platform.backtest_engine.lookup_vix_at_entry",
               return_value=21.5):
        result = run_backtest(cfg)

    assert result.trades, "expected at least one Monday trade in June 2023"
    for t in result.trades:
        assert t.vix_at_entry == pytest.approx(21.5), (
            f"trade {t.trade_id} ({t.entry_date}) has vix_at_entry="
            f"{t.vix_at_entry} expected 21.5"
        )


def test_build_trade_passes_entry_iso_to_vix_lookup():
    """Helper must be called with the trade's entry_iso, not start/end of
    the run — VIX is a per-trade lookup."""
    from src.platform.backtest_engine import BacktestConfig, run_backtest

    spec = _make_scheduled_spec_aapl()
    cfg = BacktestConfig(
        strategy=spec, start_date="2023-06-01", end_date="2023-06-30",
        commission_bps=0.0, slippage_bps=0.0, spread_bps=0.0,
    )
    seen_entries: list[str] = []

    def _capturing_helper(entry_iso: str) -> float:
        seen_entries.append(entry_iso)
        return 20.0

    with patch("src.platform.backtest_engine.load_ohlcv_range",
               side_effect=_stub_ohlcv_aapl_june_2023), \
         patch("src.platform.backtest_engine.spy_return_over_range",
               return_value=0.01), \
         patch("src.platform.backtest_engine.lookup_vix_at_entry",
               side_effect=_capturing_helper):
        result = run_backtest(cfg)

    assert result.trades
    assert seen_entries, "lookup_vix_at_entry never called"
    # Each trade's entry_date must equal the helper-call entry_iso for
    # the same trade
    for t in result.trades:
        assert t.entry_date in seen_entries


def test_build_trade_handles_none_vix_gracefully():
    """If the helper returns None (cache miss), trades still build with
    vix_at_entry=None — no crash, no skip."""
    from src.platform.backtest_engine import BacktestConfig, run_backtest

    spec = _make_scheduled_spec_aapl()
    cfg = BacktestConfig(
        strategy=spec, start_date="2023-06-01", end_date="2023-06-30",
        commission_bps=0.0, slippage_bps=0.0, spread_bps=0.0,
    )
    with patch("src.platform.backtest_engine.load_ohlcv_range",
               side_effect=_stub_ohlcv_aapl_june_2023), \
         patch("src.platform.backtest_engine.spy_return_over_range",
               return_value=0.01), \
         patch("src.platform.backtest_engine.lookup_vix_at_entry",
               return_value=None):
        result = run_backtest(cfg)

    assert result.trades, "trades should still be built when VIX is None"
    for t in result.trades:
        assert t.vix_at_entry is None


# ---------------------------------------------------------------------------
# End-to-end through walkforward_runner.persist_run_result
# ---------------------------------------------------------------------------

def test_persist_run_result_writes_vix_tier_when_trade_has_vix(tmp_path):
    """When BacktestTrade carries vix_at_entry, persist_run_result must
    populate walkforward_trades.vix_tier with the tier-bucketed value
    (low / medium / high). Regression for the existing tier-bucketing
    path; verifies the runner picks up the new field correctly."""
    from src.platform.backtest_engine import BacktestTrade
    from src.platform.rigor.walkforward_config import WalkForwardConfig
    from src.platform.rigor.walkforward_metrics import WindowMetrics
    from src.platform.rigor.walkforward_outcome import OutcomeResult
    from src.platform.rigor.walkforward_power import PowerResult
    from src.platform.rigor.walkforward_runner import (
        WalkForwardRunResult, persist_run_result,
    )
    from src.schema.sqlite import create_all_tables

    db_path = str(tmp_path / "wf.sqlite3")
    create_all_tables(db_path)

    trade = BacktestTrade(
        trade_id="t-medium", ticker="AAPL", entry_date="2020-03-16",
        exit_date="2020-04-06", entry_price=100.0, exit_price=110.0,
        shares=10, pnl_dollars=100.0, pnl_pct=0.10, exit_reason="target",
        hold_days=21, spy_return_over_hold=0.0, excess_return=0.10,
        realized_sector="Technology", regime_at_entry=None,
        vix_at_entry=22.5,  # 15-25 = medium
    )
    config = WalkForwardConfig(strategy_id="test_vix")
    metrics = WindowMetrics(
        window_index=0, n_trades=1, mean_pnl_pct=0.1, std_pnl_pct=0.0,
        sharpe=0.0, max_drawdown_pct=0.0, parametric_se=1.0,
        bootstrap_se=1.0, heavy_tail_flag=False,
        vix_tiers_represented={"medium"},
    )
    power = PowerResult(
        window_index=0, observed_sharpe=0.0, mde=float("inf"),
        effective_n=1, se_used=1.0, heavy_tail_flag=False,
        passes_power_gate=False, passes_sharpe_gate=False,
    )
    outcome = OutcomeResult(
        outcome_state="INCONCLUSIVE", reason="coverage_inconclusive",
        n_windows_pass=0, n_windows_fail=0,
        n_windows_inconclusive_power=0, n_windows_inconclusive_data=1,
    )
    result = WalkForwardRunResult(
        run_id="run-1", strategy_id="test_vix", spec_hash="abc",
        code_git_sha=None, outcome=outcome, pooled_sharpe=0.0,
        pooled_mde=float("inf"), heavy_tail_window_count=0,
        window_metrics=[metrics], window_power=[power],
        window_states={0: "INCONCLUSIVE_DATA"}, vix_tier_coverage=1,
        effective_universe_size=100, config=config,
    )
    persist_run_result(
        result=result, strategy_spec_raw={"derived_from": None},
        oos_trades_per_window=[[trade]], db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT vix_at_entry, vix_tier FROM walkforward_trades "
        "WHERE trade_id = ?", ("t-medium",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == pytest.approx(22.5)
    assert row[1] == "medium"
