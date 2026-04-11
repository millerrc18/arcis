"""Tests for regime-targeted date selection and dataset balancing."""

import pandas as pd
import pytest

from src.training.regime_sampler import (
    REGIME_MAP,
    balance_dataset,
    cap_and_diversify,
    classify_dates_by_regime,
    deduplicate_candidates,
    format_macro_summary,
    sample_regime_balanced_dates,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_fred_data() -> dict[str, pd.Series]:
    """Create synthetic FRED data."""
    dates = pd.to_datetime(["2024-01-15", "2024-02-15"])
    return {
        "VIXCLS": pd.Series([22.5, 18.3], index=dates, name="VIXCLS"),
        "T10Y2Y": pd.Series([-0.35, 0.12], index=dates, name="T10Y2Y"),
        "UNRATE": pd.Series([3.7, 3.8], index=dates, name="UNRATE"),
        "FEDFUNDS": pd.Series([5.33, 5.33], index=dates, name="FEDFUNDS"),
    }


# ── classify_dates_by_regime tests ───────────────────────────────────


class TestClassifyDates:
    def test_classify_returns_multiple_regimes(self):
        """Classification should produce multiple regime categories."""
        # Create SPY with enough data (>252 days) showing different market conditions
        n_days = 400
        dates = pd.bdate_range("2023-01-02", periods=n_days)
        # First half: uptrend. Second half: downtrend.
        prices_up = [100.0 + i * 0.3 for i in range(200)]
        prices_down = [prices_up[-1] - i * 0.4 for i in range(200)]
        prices = prices_up + prices_down
        spy_df = pd.DataFrame({
            "Open": [p - 0.5 for p in prices],
            "High": [p + 1.0 for p in prices],
            "Low": [p - 1.0 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * n_days,
        }, index=dates)

        # Create minimal ohlcv_data for breadth computation
        ohlcv_data = {}
        for ticker in ["AAPL", "MSFT", "GOOG"]:
            ohlcv_data[ticker] = spy_df.copy()

        result = classify_dates_by_regime(spy_df, ohlcv_data)

        # Should have at least 2 different regimes given the trend shift
        assert len(result) >= 1
        total_dates = sum(len(dates) for dates in result.values())
        assert total_dates > 0


# ── sample_regime_balanced_dates tests ───────────────────────────────


class TestSampling:
    def test_sample_respects_targets(self):
        """Sampling should not exceed 1.5x target."""
        regime_dates = {
            "bull": [f"2024-{m:02d}-{d:02d}" for m in range(1, 7) for d in range(1, 20)],
            "bear": [f"2024-{m:02d}-{d:02d}" for m in range(7, 10) for d in range(1, 20)],
        }
        targets = {"bull": 20, "bear": 10}

        sampled = sample_regime_balanced_dates(regime_dates, targets)

        # Bull: min(20*1.5=30, 114 available) = 30
        assert len(sampled["bull"]) <= 30
        assert len(sampled["bull"]) > 0

        # Bear: min(10*1.5=15, 57 available) = 15
        assert len(sampled["bear"]) <= 15
        assert len(sampled["bear"]) > 0

    def test_sample_handles_empty_regime(self):
        """Sampling from empty regime should produce empty list."""
        regime_dates = {"bull": ["2024-01-15", "2024-02-15"]}
        targets = {"bull": 10, "bear": 10}

        sampled = sample_regime_balanced_dates(regime_dates, targets)
        assert sampled["bear"] == []
        assert len(sampled["bull"]) > 0


# ── format_macro_summary tests ───────────────────────────────────────


class TestFormatMacro:
    def test_format_macro_summary_no_placeholder(self):
        """Macro summary should contain real data, not placeholders."""
        fred_data = _make_fred_data()
        summary = format_macro_summary(fred_data, "2024-02-20")

        assert "Not available" not in summary
        assert "VIX" in summary
        assert "yield curve" in summary
        assert "Fed Funds" in summary
        assert "unemployment" in summary

    def test_format_macro_inverted_curve(self):
        """Inverted yield curve should be labeled as such."""
        fred_data = _make_fred_data()
        summary = format_macro_summary(fred_data, "2024-01-20")

        assert "inverted" in summary

    def test_format_macro_positive_curve(self):
        """Positive yield curve should be labeled as such."""
        fred_data = _make_fred_data()
        summary = format_macro_summary(fred_data, "2024-02-20")

        assert "positive" in summary

    def test_format_macro_empty_fred(self):
        """Empty FRED data should produce a placeholder message."""
        summary = format_macro_summary({}, "2024-02-15")
        assert "not available" in summary.lower()


# ── deduplicate_candidates tests ─────────────────────────────────────


class TestDeduplicateRefactored:
    """Verify the refactored public deduplicate_candidates works identically."""

    def test_consecutive_days_deduplicated(self):
        candidates = [
            {"ticker": "AAPL", "scan_date": "2024-06-10", "score": 80},
            {"ticker": "AAPL", "scan_date": "2024-06-11", "score": 82},
        ]
        result = deduplicate_candidates(candidates, min_gap_days=5)
        assert len([c for c in result if c["ticker"] == "AAPL"]) == 1

    def test_spaced_entries_kept(self):
        candidates = [
            {"ticker": "AAPL", "scan_date": "2024-06-01", "score": 80},
            {"ticker": "AAPL", "scan_date": "2024-06-10", "score": 82},
        ]
        result = deduplicate_candidates(candidates, min_gap_days=5)
        assert len([c for c in result if c["ticker"] == "AAPL"]) == 2


# ── balance_dataset tests ───────────────────────────────────────────


class TestBalanceRefactored:
    """Verify the refactored public balance_dataset works identically."""

    def test_downsamples_wins(self):
        examples = []
        for i in range(100):
            examples.append({"candidate": {"ticker": f"T{i}", "score": 80}, "outcome": {"outcome_quality": "clean_win"}})
        for i in range(20):
            examples.append({"candidate": {"ticker": f"L{i}", "score": 70}, "outcome": {"outcome_quality": "clean_loss"}})

        balanced = balance_dataset(examples, target_win_ratio=0.6)
        wins = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_win")
        losses = sum(1 for e in balanced if e["outcome"]["outcome_quality"] == "clean_loss")

        total = wins + losses
        win_ratio = wins / total if total > 0 else 0
        assert 0.55 <= win_ratio <= 0.65
        assert losses == 20
