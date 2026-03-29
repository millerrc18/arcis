"""Tests for the historical backfill training data pipeline."""

import pandas as pd
import pytest

from src.training.historical_data import slice_to_date
from src.training.historical_scanner import (
    _classify_outcome_quality,
    compute_outcome,
    generate_backfill_example,
)
from src.training.backfill import (
    _balance_dataset,
    _deduplicate_candidates,
    estimate_backfill_cost,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_ohlcv(n_days: int, start_price: float = 100.0,
                start_date: str = "2024-01-02",
                daily_change: float = 0.0) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with known prices."""
    dates = pd.bdate_range(start=start_date, periods=n_days)
    prices = [start_price + i * daily_change for i in range(n_days)]
    data = {
        "Open": [p - 0.5 for p in prices],
        "High": [p + 1.0 for p in prices],
        "Low": [p - 1.0 for p in prices],
        "Close": prices,
        "Volume": [1_000_000] * n_days,
    }
    return pd.DataFrame(data, index=dates)


def _make_data_dict(tickers: list[str], n_days: int = 300,
                    start_price: float = 100.0) -> dict:
    """Create a full data dict as returned by fetch_historical_universe()."""
    spy_df = _make_ohlcv(n_days, start_price=400.0, daily_change=0.1)
    tickers_dict = {}
    for ticker in tickers:
        tickers_dict[ticker] = _make_ohlcv(n_days, start_price=start_price,
                                           daily_change=0.05)
    return {
        "spy": spy_df,
        "tickers": tickers_dict,
        "start_date": spy_df.index[0].strftime("%Y-%m-%d"),
        "end_date": spy_df.index[-1].strftime("%Y-%m-%d"),
    }


# ── Point-in-time slicing tests ──────────────────────────────────────


class TestSliceToDate:
    """Verify that slice_to_date returns only data up to the specified date."""

    def test_no_future_data_leaks(self):
        """Core anti-lookahead test: sliced data must not contain future dates."""
        data = _make_data_dict(["AAPL", "MSFT"], n_days=300)
        as_of = "2024-06-15"

        ohlcv_dict, spy_sliced = slice_to_date(data, as_of)

        cutoff = pd.Timestamp(as_of)
        # SPY must not have future data
        assert spy_sliced.index.max() <= cutoff

        # Each ticker must not have future data
        for ticker, df in ohlcv_dict.items():
            assert df.index.max() <= cutoff, \
                f"{ticker} has data after {as_of}: {df.index.max()}"

    def test_skips_tickers_with_insufficient_data(self):
        """Tickers with fewer than 200 rows as-of the date should be skipped."""
        data = _make_data_dict(["AAPL"], n_days=300)
        # Slice very early — only ~50 trading days of data available
        as_of = "2024-03-15"

        ohlcv_dict, spy_sliced = slice_to_date(data, as_of)

        # AAPL should be excluded (< 200 rows by March)
        assert "AAPL" not in ohlcv_dict

    def test_preserves_all_data_up_to_date(self):
        """All data up to and including the as-of date should be present."""
        data = _make_data_dict(["AAPL"], n_days=300)
        as_of = "2024-12-15"

        ohlcv_dict, spy_sliced = slice_to_date(data, as_of)

        if "AAPL" in ohlcv_dict:
            # Should have data starting from Jan 2024
            assert ohlcv_dict["AAPL"].index.min() == data["tickers"]["AAPL"].index.min()


# ── Outcome computation tests ────────────────────────────────────────


class TestComputeOutcome:
    """Verify outcome tracking with known price sequences."""

    def test_stop_hit(self):
        """Stop should trigger when low breaches stop price."""
        # Create data where price drops immediately
        dates = pd.bdate_range("2024-06-01", periods=20)
        prices = [100.0] + [100.0 - i * 2 for i in range(1, 20)]
        df = pd.DataFrame({
            "Open": prices,
            "High": [p + 0.5 for p in prices],
            "Low": [p - 0.5 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * 20,
        }, index=dates)

        data = {
            "tickers": {"TEST": df},
            "spy": df.copy(),
        }

        outcome = compute_outcome(
            data, "TEST", "2024-06-03",
            entry_price=100.0, stop_price=95.0,
            target_1=105.0, target_2=110.0,
        )

        assert outcome is not None
        assert outcome["exit_reason"] == "stop_hit"
        assert outcome["exit_price"] == 95.0
        assert outcome["pnl_dollars"] < 0

    def test_target_1_hit(self):
        """Target should trigger when high reaches target_1."""
        # Create data where price rises steadily
        dates = pd.bdate_range("2024-06-01", periods=20)
        prices = [100.0] + [100.0 + i * 1.5 for i in range(1, 20)]
        df = pd.DataFrame({
            "Open": prices,
            "High": [p + 1.0 for p in prices],
            "Low": [p - 0.5 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * 20,
        }, index=dates)

        data = {
            "tickers": {"TEST": df},
            "spy": df.copy(),
        }

        outcome = compute_outcome(
            data, "TEST", "2024-06-03",
            entry_price=100.0, stop_price=95.0,
            target_1=105.0, target_2=110.0,
        )

        assert outcome is not None
        assert outcome["exit_reason"] in ("target_1_hit", "target_2_hit")
        assert outcome["pnl_dollars"] > 0

    def test_timeout(self):
        """Timeout should occur when neither stop nor target hit."""
        # Create data where price stays flat
        dates = pd.bdate_range("2024-06-01", periods=20)
        prices = [100.0] * 20
        df = pd.DataFrame({
            "Open": prices,
            "High": [p + 0.2 for p in prices],
            "Low": [p - 0.2 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * 20,
        }, index=dates)

        data = {
            "tickers": {"TEST": df},
            "spy": df.copy(),
        }

        outcome = compute_outcome(
            data, "TEST", "2024-06-03",
            entry_price=100.0, stop_price=90.0,
            target_1=115.0, target_2=120.0,
            max_hold_days=10,
        )

        assert outcome is not None
        assert outcome["exit_reason"] == "timeout"

    def test_mfe_mae_tracking(self):
        """MFE and MAE should reflect actual intraday extremes."""
        dates = pd.bdate_range("2024-06-01", periods=10)
        # Price goes up then down: entry at 100, peak at 108 high, trough at 96 low
        closes = [100, 103, 106, 108, 105, 100, 97, 95, 93, 91]
        highs = [101, 105, 108, 110, 107, 102, 99, 97, 95, 93]
        lows = [99, 101, 104, 106, 103, 98, 95, 93, 91, 89]

        df = pd.DataFrame({
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000] * 10,
        }, index=dates)

        data = {"tickers": {"TEST": df}, "spy": df.copy()}

        outcome = compute_outcome(
            data, "TEST", "2024-06-03",
            entry_price=100.0, stop_price=88.0,
            target_1=115.0, target_2=120.0,
            max_hold_days=8,
        )

        assert outcome is not None
        # MFE should be positive (best unrealized gain)
        assert outcome["max_favorable_excursion"] > 0
        # MAE should be negative (worst unrealized loss)
        assert outcome["max_adverse_excursion"] <= 0

    def test_same_day_stop_and_target_assumes_stop(self):
        """When stop and target hit on same day, assume stop (conservative)."""
        dates = pd.bdate_range("2024-06-01", periods=5)
        df = pd.DataFrame({
            "Open": [100, 100, 100, 100, 100],
            "High": [101, 101, 110, 101, 101],  # Day 3 high hits target
            "Low": [99, 99, 94, 99, 99],         # Day 3 low hits stop
            "Close": [100, 100, 100, 100, 100],
            "Volume": [1_000_000] * 5,
        }, index=dates)

        data = {"tickers": {"TEST": df}, "spy": df.copy()}

        outcome = compute_outcome(
            data, "TEST", "2024-06-03",
            entry_price=100.0, stop_price=95.0,
            target_1=108.0, target_2=115.0,
        )

        assert outcome is not None
        assert outcome["exit_reason"] == "stop_hit"
        assert outcome["exit_price"] == 95.0

    def test_returns_none_for_insufficient_data(self):
        """Should return None if not enough future data."""
        dates = pd.bdate_range("2024-06-01", periods=3)
        df = pd.DataFrame({
            "Open": [100, 100, 100],
            "High": [101, 101, 101],
            "Low": [99, 99, 99],
            "Close": [100, 100, 100],
            "Volume": [1_000_000] * 3,
        }, index=dates)

        data = {"tickers": {"TEST": df}, "spy": df.copy()}

        # Entry on last day — no future data
        outcome = compute_outcome(
            data, "TEST", "2024-06-05",
            entry_price=100.0, stop_price=95.0,
            target_1=105.0, target_2=110.0,
        )

        assert outcome is None


# ── Outcome quality classification tests ─────────────────────────────


class TestOutcomeQuality:
    """Verify outcome quality labels."""

    def test_clean_win(self):
        assert _classify_outcome_quality("target_1_hit", mfe=10.0, mae=3.0) == "clean_win"

    def test_clean_loss(self):
        assert _classify_outcome_quality("stop_hit", mfe=1.0, mae=5.0) == "clean_loss"

    def test_messy_win(self):
        """Win with significant adverse excursion = messy."""
        assert _classify_outcome_quality("target_1_hit", mfe=5.0, mae=4.0) == "messy"

    def test_messy_loss(self):
        """Loss with significant favorable excursion = messy."""
        assert _classify_outcome_quality("stop_hit", mfe=4.0, mae=5.0) == "messy"

    def test_timeout(self):
        assert _classify_outcome_quality("timeout", mfe=2.0, mae=2.0) == "timeout"

    def test_target_2_clean_win(self):
        assert _classify_outcome_quality("target_2_hit", mfe=15.0, mae=2.0) == "clean_win"


# ── Deduplication tests ──────────────────────────────────────────────


class TestDeduplication:
    """Verify deduplication of consecutive entries for the same ticker."""

    def test_consecutive_days_deduplicated(self):
        """Same ticker on consecutive days should keep only the first."""
        candidates = [
            {"ticker": "AAPL", "scan_date": "2024-06-10", "score": 80},
            {"ticker": "AAPL", "scan_date": "2024-06-11", "score": 82},
            {"ticker": "AAPL", "scan_date": "2024-06-12", "score": 79},
            {"ticker": "MSFT", "scan_date": "2024-06-10", "score": 75},
            {"ticker": "MSFT", "scan_date": "2024-06-11", "score": 77},
        ]

        result = _deduplicate_candidates(candidates, min_gap_days=5)

        aapl_entries = [c for c in result if c["ticker"] == "AAPL"]
        msft_entries = [c for c in result if c["ticker"] == "MSFT"]

        assert len(aapl_entries) == 1
        assert len(msft_entries) == 1

    def test_spaced_entries_kept(self):
        """Same ticker with sufficient gap should be kept."""
        candidates = [
            {"ticker": "AAPL", "scan_date": "2024-06-01", "score": 80},
            {"ticker": "AAPL", "scan_date": "2024-06-10", "score": 82},
            {"ticker": "AAPL", "scan_date": "2024-06-20", "score": 78},
        ]

        result = _deduplicate_candidates(candidates, min_gap_days=5)
        aapl_entries = [c for c in result if c["ticker"] == "AAPL"]

        # All three should be kept (>5 day gaps)
        assert len(aapl_entries) == 3

    def test_different_tickers_independent(self):
        """Different tickers should be deduplicated independently."""
        candidates = [
            {"ticker": "AAPL", "scan_date": "2024-06-10", "score": 80},
            {"ticker": "MSFT", "scan_date": "2024-06-10", "score": 75},
            {"ticker": "GOOG", "scan_date": "2024-06-10", "score": 72},
        ]

        result = _deduplicate_candidates(candidates, min_gap_days=5)
        assert len(result) == 3


# ── Dataset balancing tests ──────────────────────────────────────────


class TestDatasetBalancing:
    """Verify win/loss ratio balancing."""

    def test_downsamples_wins_when_imbalanced(self):
        """Too many wins should be downsampled to ~60/40 ratio."""
        examples = []
        # 100 wins, 20 losses
        for i in range(100):
            examples.append({
                "candidate": {"ticker": f"T{i}", "score": 80},
                "outcome": {"outcome_quality": "clean_win"},
            })
        for i in range(20):
            examples.append({
                "candidate": {"ticker": f"L{i}", "score": 70},
                "outcome": {"outcome_quality": "clean_loss"},
            })

        balanced = _balance_dataset(examples, target_win_ratio=0.6)

        wins = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_win")
        losses = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_loss")

        # Should be approximately 60/40
        total = wins + losses
        win_ratio = wins / total if total > 0 else 0
        assert 0.55 <= win_ratio <= 0.65, f"Win ratio {win_ratio:.2f} not near 0.60"
        # All losses should be preserved
        assert losses == 20

    def test_preserves_when_already_balanced(self):
        """If already balanced, don't change anything."""
        examples = []
        for i in range(60):
            examples.append({
                "candidate": {"ticker": f"T{i}", "score": 80},
                "outcome": {"outcome_quality": "clean_win"},
            })
        for i in range(40):
            examples.append({
                "candidate": {"ticker": f"L{i}", "score": 70},
                "outcome": {"outcome_quality": "clean_loss"},
            })

        balanced = _balance_dataset(examples, target_win_ratio=0.6)

        wins = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_win")
        losses = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_loss")

        assert wins == 60
        assert losses == 40


# ── Cost estimation tests ────────────────────────────────────────────


class TestCostEstimation:
    def test_cost_estimation(self):
        cost = estimate_backfill_cost(1000)
        # Self-blinding pipeline: 2 API calls per example
        # Stage 1: 1000 * 600 * 1.0 / 1M = 0.60 input + 1000 * 800 * 5.0 / 1M = 4.00 output
        # Stage 2: 1000 * 1400 * 1.0 / 1M = 1.40 input + 1000 * 800 * 5.0 / 1M = 4.00 output
        # Total = 0.60 + 4.00 + 1.40 + 4.00 = 10.0
        assert cost == 10.0

    def test_zero_examples(self):
        assert estimate_backfill_cost(0) == 0.0


# ── Training example generation tests ────────────────────────────────


class TestGenerateBackfillExample:
    def test_example_structure(self):
        """Verify the training example has the expected structure."""
        candidate = {
            "scan_date": "2024-06-15",
            "ticker": "AAPL",
            "score": 85.0,
            "entry_price": 185.50,
            "stop_price": 181.50,
            "target_1": 188.50,
            "target_2": 191.50,
            "features": {
                "current_price": 185.50,
                "trend_state": "uptrend",
                "sma50_slope": "positive",
                "sma200_slope": "positive",
                "price_vs_sma50_pct": 3.5,
                "price_vs_sma200_pct": 12.1,
                "relative_strength_state": "outperformer",
                "rs_vs_spy_1m": 2.1,
                "rs_vs_spy_3m": 5.3,
                "rs_vs_spy_6m": 8.7,
                "pullback_depth_pct": -4.2,
                "atr_14": 2.0,
                "atr_pct": 1.08,
                "volume_ratio_20d": 0.75,
                "dist_to_sma20_pct": -1.5,
            },
        }
        outcome = {
            "exit_date": "2024-06-28",
            "exit_price": 192.30,
            "exit_reason": "target_1_hit",
            "pnl_dollars": 6.80,
            "pnl_pct": 3.66,
            "duration_days": 9,
            "max_favorable_excursion": 8.20,
            "max_adverse_excursion": -2.10,
            "outcome_quality": "clean_win",
        }

        example = generate_backfill_example(candidate, outcome)

        assert example["output_text"] is None
        assert "AAPL" in example["input_text"]
        # Self-blinding: outcome should NOT be in input_text
        assert "target_1_hit" not in example["input_text"]
        assert "ACTUAL OUTCOME" not in example["input_text"]
        assert example["metadata"]["ticker"] == "AAPL"
        assert example["metadata"]["pnl_pct"] == 3.66
        assert example["metadata"]["outcome_quality"] == "clean_win"

    def test_input_format_matches_packet_writer(self):
        """Input text should contain the same fields as _build_feature_prompt."""
        candidate = {
            "scan_date": "2024-06-15",
            "ticker": "MSFT",
            "score": 75.0,
            "entry_price": 420.0,
            "stop_price": 415.0,
            "target_1": 423.75,
            "target_2": 427.5,
            "features": {
                "current_price": 420.0,
                "trend_state": "strong_uptrend",
                "sma50_slope": "positive",
                "sma200_slope": "positive",
                "price_vs_sma50_pct": 2.0,
                "price_vs_sma200_pct": 15.0,
                "relative_strength_state": "strong_outperformer",
                "rs_vs_spy_1m": 3.0,
                "rs_vs_spy_3m": 6.0,
                "rs_vs_spy_6m": 10.0,
                "pullback_depth_pct": -5.0,
                "atr_14": 2.5,
                "atr_pct": 0.6,
                "volume_ratio_20d": 0.6,
                "dist_to_sma20_pct": -2.0,
            },
        }
        outcome = {
            "exit_date": "2024-06-28",
            "exit_price": 415.0,
            "exit_reason": "stop_hit",
            "pnl_dollars": -5.0,
            "pnl_pct": -1.19,
            "duration_days": 9,
            "max_favorable_excursion": 3.0,
            "max_adverse_excursion": -6.0,
            "outcome_quality": "clean_loss",
        }

        example = generate_backfill_example(candidate, outcome)
        text = example["input_text"]

        # Verify key fields are present
        assert "Ticker: MSFT" in text
        assert "Current Price:" in text
        assert "Trend State:" in text
        assert "Relative Strength:" in text
        assert "Pullback Depth:" in text
        assert "ATR(14):" in text
        assert "Volume Ratio:" in text
        assert "Score:" in text
        # Self-blinding: outcome should NOT be in input_text
        assert "=== ACTUAL OUTCOME ===" not in text
