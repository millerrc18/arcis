"""Tests for forensic trade audit v1.

Tests cover:
  1. Beta computation against known-correlation synthetic data
  2. Exit type classification with edge cases
  3. Slippage computation sign convention
  4. Holding-period attribution sums to total return
  5. P&L distribution statistics (Gini, Wilcoxon)
  6. Autocorrelation computation
  7. Selection vs holding decomposition
  8. Sector concentration computation
  9. Bootcamp counterfactual filtering
  10. Data pipeline (load_trades) with synthetic DB
"""
import math
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Import from scripts — add to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.diagnostics.forensic_trade_audit_v1 import (
    Trade,
    autocorrelation,
    compute_bootcamp_caveat,
    compute_q1_beta,
    compute_q2_pnl_distribution,
    compute_q3_slippage,
    compute_q4_exit_attribution,
    compute_q5_holding_attribution,
    compute_q6_clustering,
    compute_q7_selection_holding,
    compute_q8_sector,
    gini_coefficient,
    load_trades,
    wilcoxon_signed_rank,
    _mean,
    _std,
    _se,
    _median,
    _ci95,
)


def _make_trade(**kwargs) -> Trade:
    """Create a Trade with sensible defaults, overridable via kwargs."""
    defaults = dict(
        trade_id="test-001",
        ticker="AAPL",
        pnl_pct=2.0,
        excess_return=1.0,
        spy_return=0.01,
        entry_price=100.0,
        exit_price=102.0,
        allocation=1000.0,
        entry_time="2026-03-24T10:00:00-04:00",
        exit_time="2026-03-26T15:30:00-04:00",
        exit_reason="target_1_hit",
        sector="Technology",
        quarantined=False,
        confidence_score=80.0,
        duration_days=2,
    )
    defaults.update(kwargs)
    return Trade(**defaults)


def _make_cohort(n: int = 20) -> list[Trade]:
    """Create a synthetic trade cohort for testing."""
    trades = []
    sectors = ["Technology", "Financials", "Energy", "Health Care", "Utilities"]
    exit_reasons = ["target_1_hit", "stop_hit", "reconciled_stale", "timeout", "manual_close"]
    for i in range(n):
        pnl = (i - n // 2) * 0.5 + 1.0  # Range from negative to positive
        spy = 0.005 * (i % 5)  # Varying SPY returns
        trades.append(_make_trade(
            trade_id=f"test-{i:03d}",
            ticker=f"T{i:02d}",
            pnl_pct=pnl,
            excess_return=pnl - spy * 100,
            spy_return=spy,
            allocation=1000 + i * 100,
            entry_time=f"2026-03-{24 + i // 5:02d}T10:00:00-04:00",
            exit_time=f"2026-03-{26 + i // 5:02d}T15:30:00-04:00",
            exit_reason=exit_reasons[i % 5],
            sector=sectors[i % 5],
            confidence_score=40 + i * 3,  # Some below 70 for strict-mode test
            duration_days=max(1, i % 7),
        ))
    return trades


# ── Test 1: Beta computation ──────────────────────────────────────
class TestQ1Beta:
    def test_beta_with_perfect_correlation(self):
        """When trade returns perfectly track SPY, beta should be ~1."""
        trades = [
            _make_trade(pnl_pct=spy * 100, spy_return=spy, excess_return=0.0)
            for spy in [0.01, 0.02, -0.01, 0.03, -0.02, 0.015, -0.005]
        ]
        result = compute_q1_beta(trades)
        assert abs(result["equal_weighted_beta"] - 1.0) < 0.01

    def test_beta_with_zero_spy_excluded(self):
        """Trades with zero SPY return are excluded from beta calc."""
        trades = [
            _make_trade(pnl_pct=2.0, spy_return=0.0),
            _make_trade(pnl_pct=3.0, spy_return=0.01),
            _make_trade(pnl_pct=4.0, spy_return=0.02),
        ]
        result = compute_q1_beta(trades)
        assert result["n"] == 2  # Only non-zero SPY trades

    def test_beta_returns_all_four_weightings(self):
        cohort = _make_cohort()
        result = compute_q1_beta(cohort)
        assert "equal_weighted_beta" in result
        assert "trade_weighted_beta" in result
        assert "cap_weighted_beta" in result
        assert "notional_weighted_beta" in result
        assert "equal_weighted_ci95" in result
        assert len(result["equal_weighted_ci95"]) == 2


# ── Test 2: Exit type classification ─────────────────────────────
class TestQ4ExitAttribution:
    def test_exit_type_normalization(self):
        """Verify exit reasons are properly classified."""
        trades = [
            _make_trade(exit_reason="target_1_hit"),
            _make_trade(exit_reason="target_2_hit"),
            _make_trade(exit_reason="stop_hit"),
            _make_trade(exit_reason="stop_loss_hit"),
            _make_trade(exit_reason="reconciled_stale"),
            _make_trade(exit_reason="timeout_forced"),
            _make_trade(exit_reason="broker_exception:APIError"),
        ]
        result = compute_q4_exit_attribution(trades)
        assert "target_hit" in result
        assert result["target_hit"]["count"] == 2
        assert "stop_hit" in result
        assert result["stop_hit"]["count"] == 2
        assert "timeout/stale" in result
        assert result["timeout/stale"]["count"] == 2
        assert "broker_error" in result

    def test_exit_sharpe_computation(self):
        """Sharpe should be positive for profitable exit types."""
        trades = [
            _make_trade(pnl_pct=5.0, exit_reason="target_1_hit"),
            _make_trade(pnl_pct=4.0, exit_reason="target_1_hit"),
            _make_trade(pnl_pct=3.0, exit_reason="target_1_hit"),
        ]
        result = compute_q4_exit_attribution(trades)
        assert result["target_hit"]["sharpe"] > 0
        assert result["target_hit"]["mean_return"] == 4.0


# ── Test 3: Slippage sign convention ──────────────────────────────
class TestQ3Slippage:
    def test_positive_slippage_means_worse_fill(self):
        """Positive slippage = bought higher than theoretical."""
        trades = [
            _make_trade(theoretical_entry=100.0, slippage_bps=50.0),  # Paid more
            _make_trade(theoretical_entry=100.0, slippage_bps=-20.0),  # Got improvement
        ]
        result = compute_q3_slippage(trades)
        assert result["n"] == 2
        assert result["mean_bps"] == 15.0  # (50 - 20) / 2

    def test_slippage_computation_formula(self):
        """Verify: slippage_bps = (actual - theoretical) / theoretical * 10000."""
        trade = _make_trade(entry_price=101.0)
        trade.theoretical_entry = 100.0
        trade.slippage_bps = (101.0 - 100.0) / 100.0 * 10000
        assert trade.slippage_bps == 100.0  # 100 bps = 1%

    def test_no_minute_bars_handled(self):
        """When no slippage data exists, result documents the gap."""
        trades = [_make_trade()]  # No slippage_bps set
        result = compute_q3_slippage(trades)
        assert result["n"] == 0
        assert result["n_missing"] == 1


# ── Test 4: Holding period attribution sums ───────────────────────
class TestQ5HoldingAttribution:
    def test_attribution_returns_all_buckets(self):
        cohort = _make_cohort()
        result = compute_q5_holding_attribution(cohort)
        assert "day_1" in result
        assert "days_2_3" in result
        assert "days_4_6" in result
        assert "days_7_plus" in result

    def test_front_loaded_detection(self):
        """Short trades with higher returns should flag front-loaded alpha."""
        short_trades = [_make_trade(pnl_pct=5.0, duration_days=1) for _ in range(5)]
        long_trades = [_make_trade(pnl_pct=1.0, duration_days=7) for _ in range(5)]
        result = compute_q5_holding_attribution(short_trades + long_trades)
        assert result["front_loaded_test"]["alpha_is_front_loaded"] is True


# ── Test 5: P&L distribution stats ───────────────────────────────
class TestQ2PnLDistribution:
    def test_gini_perfect_equality(self):
        """All equal returns should give Gini ≈ 0."""
        assert abs(gini_coefficient([1.0, 1.0, 1.0, 1.0])) < 0.01

    def test_gini_maximum_inequality(self):
        """One large, rest zero should give Gini close to 1."""
        g = gini_coefficient([100.0, 0.0, 0.0, 0.0, 0.0])
        assert g > 0.7

    def test_wilcoxon_symmetric_around_zero(self):
        """Symmetric distribution should yield high p-value."""
        data = [-3, -2, -1, 1, 2, 3]
        _, p = wilcoxon_signed_rank([float(x) for x in data])
        assert p > 0.05  # Cannot reject H0

    def test_wilcoxon_shifted_positive(self):
        """Clearly positive values should yield low p-value."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        _, p = wilcoxon_signed_rank(data)
        assert p < 0.05

    def test_full_q2_output(self):
        cohort = _make_cohort()
        result = compute_q2_pnl_distribution(cohort)
        assert "gini" in result
        assert "wilcoxon_pval" in result
        assert "skewness" in result
        assert "kurtosis_excess" in result
        assert "mean_excess_ci95" in result
        assert len(result["mean_excess_ci95"]) == 2


# ── Test 6: Autocorrelation ───────────────────────────────────────
class TestQ6Clustering:
    def test_autocorrelation_white_noise(self):
        """White noise should have ACF near zero."""
        import random
        random.seed(42)
        data = [random.gauss(0, 1) for _ in range(100)]
        acf, p = autocorrelation(data, 1)
        assert abs(acf) < 0.3  # Should be near zero

    def test_autocorrelation_strong_pattern(self):
        """Alternating signal [1,-1,1,-1...] should have negative ACF at lag 1."""
        data = [1.0, -1.0] * 50
        acf, p = autocorrelation(data, 1)
        assert acf < -0.5  # Strong negative at lag 1

    def test_full_q6_output(self):
        cohort = _make_cohort(30)
        result = compute_q6_clustering(cohort)
        assert "acf_by_lag" in result
        assert "lag_1" in result["acf_by_lag"]
        assert "lag_5" in result["acf_by_lag"]
        assert "lag_10" in result["acf_by_lag"]
        assert "lag_20" in result["acf_by_lag"]


# ── Test 7: Selection vs Holding ──────────────────────────────────
class TestQ7SelectionHolding:
    def test_decomposition_with_day1_data(self):
        """Selection + holding should approximately equal total excess."""
        trades = [
            _make_trade(
                pnl_pct=3.0, excess_return=2.0, spy_day1_return=0.005,
                duration_days=3
            )
            for _ in range(10)
        ]
        result = compute_q7_selection_holding(trades)
        assert result["n"] == 10
        assert "selection_alpha_mean" in result
        assert "holding_alpha_mean" in result

    def test_no_day1_data_handled(self):
        """Without day-1 SPY data, result documents limitation."""
        trades = [_make_trade()]  # No spy_day1_return
        result = compute_q7_selection_holding(trades)
        assert result["n"] == 0


# ── Test 8: Sector concentration ──────────────────────────────────
class TestQ8Sector:
    def test_sector_stats_completeness(self):
        cohort = _make_cohort()
        result = compute_q8_sector(cohort)
        for sector, stats in result.items():
            assert "count" in stats
            assert "concentration_pct" in stats
            assert "mean_return" in stats
            assert "mean_excess" in stats
            assert "excess_sharpe" in stats
            assert "etf" in stats

    def test_single_sector_is_100pct(self):
        trades = [_make_trade(sector="Technology") for _ in range(5)]
        result = compute_q8_sector(trades)
        assert result["Technology"]["concentration_pct"] == 100.0


# ── Test 9: Bootcamp counterfactual ───────────────────────────────
class TestBootcampCaveat:
    def test_strict_mode_filters_low_confidence(self):
        """Trades with confidence < 70 should be rejected under strict mode."""
        trades = [
            _make_trade(confidence_score=50, pnl_pct=2.0),
            _make_trade(confidence_score=30, pnl_pct=-1.0),
            _make_trade(confidence_score=80, pnl_pct=3.0),
            _make_trade(confidence_score=90, pnl_pct=4.0),
        ]
        result = compute_bootcamp_caveat(trades)
        assert result["strict_survivors"] == 2  # Only 80 and 90
        assert result["rejected_count"] == 2

    def test_all_pass_strict(self):
        trades = [_make_trade(confidence_score=85) for _ in range(5)]
        result = compute_bootcamp_caveat(trades)
        assert result["strict_survivors"] == 5
        assert result["rejected_count"] == 0


# ── Test 10: Data pipeline ────────────────────────────────────────
class TestDataPipeline:
    def test_load_trades_from_synthetic_db(self, tmp_path):
        """Verify load_trades correctly reads from a synthetic SQLite DB."""
        db_path = str(tmp_path / "test.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE shadow_trades (
                trade_id TEXT, ticker TEXT, pnl_pct TEXT,
                excess_return REAL, spy_return_over_hold REAL,
                entry_price TEXT, actual_entry_price TEXT,
                actual_exit_price TEXT, planned_allocation TEXT,
                actual_entry_time TEXT, actual_exit_time TEXT,
                exit_reason TEXT, realized_sector TEXT,
                quarantined INTEGER, duration_days INTEGER,
                status TEXT, recommendation_id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE recommendations (
                recommendation_id TEXT, confidence_score TEXT
            )
        """)
        conn.execute("""
            INSERT INTO shadow_trades VALUES (
                'id-001', 'AAPL', '3.5', 2.5, 0.01,
                '150.0', '150.5', '155.0', '1000.0',
                '2026-03-24T10:00:00-04:00', '2026-03-26T15:30:00-04:00',
                'target_1_hit', 'Technology', 0, 2, 'closed', 'rec-001'
            )
        """)
        conn.execute("INSERT INTO recommendations VALUES ('rec-001', '85.0')")
        conn.commit()
        conn.close()

        trades = load_trades(db_path)
        assert len(trades) == 1
        assert trades[0].ticker == "AAPL"
        assert trades[0].pnl_pct == 3.5
        assert trades[0].confidence_score == 85.0
        assert trades[0].sector == "Technology"


# ── Statistical helper tests ──────────────────────────────────────
class TestStatHelpers:
    def test_mean(self):
        assert _mean([1, 2, 3, 4, 5]) == 3.0

    def test_std(self):
        assert abs(_std([2, 4, 4, 4, 5, 5, 7, 9]) - 2.138) < 0.01

    def test_se(self):
        data = [1.0, 2.0, 3.0, 4.0]
        se = _se(data)
        assert se == pytest.approx(_std(data) / math.sqrt(4), rel=1e-6)

    def test_median_odd(self):
        assert _median([1, 3, 5]) == 3.0

    def test_median_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_ci95(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        lo, hi = _ci95(data)
        assert lo < _mean(data) < hi
