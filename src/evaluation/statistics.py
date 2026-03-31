"""Statistical validation functions for the walk-forward framework.

Called by: evaluation.gate_evaluator
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_statistics.py

Implements: Sharpe ratio with Lo (2002) SE correction, Bailey & Lopez de Prado PSR,
MinTRL, BCa bootstrap CI, binomial win rate test, t-test + Wilcoxon on expectancy,
profit factor, Calmar ratio, Sortino ratio, max drawdown.
"""

import numpy as np
from scipy import stats


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """Per-trade Sharpe ratio."""
    excess = returns - risk_free
    if len(excess) == 0 or excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std())


def sharpe_standard_error(sr: float, n: int, skew: float = 0.0,
                          kurtosis: float = 3.0) -> float:
    """Lo (2002) non-normal SE correction for Sharpe ratio."""
    if n <= 1:
        return float('inf')
    return float(np.sqrt((1 - skew * sr + (kurtosis - 1) / 4 * sr**2) / (n - 1)))


def probabilistic_sharpe_ratio(observed_sr: float, benchmark_sr: float, n: int,
                                skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Bailey & Lopez de Prado (2012) PSR.
    Returns probability that true Sharpe exceeds benchmark."""
    se = sharpe_standard_error(observed_sr, n, skew, kurtosis)
    if se == 0 or se == float('inf'):
        return 0.5
    z = (observed_sr - benchmark_sr) / se
    return float(stats.norm.cdf(z))


def minimum_track_record_length(observed_sr: float, benchmark_sr: float,
                                 skew: float = 0.0, kurtosis: float = 3.0,
                                 confidence: float = 0.95) -> int:
    """MinTRL: observations needed for PSR to exceed confidence threshold."""
    z_alpha = stats.norm.ppf(confidence)
    if observed_sr == benchmark_sr:
        return 999999
    numer = 1 - skew * observed_sr + (kurtosis - 1) / 4 * observed_sr**2
    denom = ((observed_sr - benchmark_sr) / z_alpha) ** 2
    return int(np.ceil(1 + numer / denom))


def bootstrap_sharpe_ci(returns: np.ndarray, n_bootstrap: int = 10000,
                         confidence: float = 0.95) -> tuple[float, float, float]:
    """BCa bootstrap confidence interval on Sharpe ratio.
    Returns (lower, observed, upper)."""
    observed = sharpe_ratio(returns)
    n = len(returns)
    if n < 5:
        return 0.0, observed, 0.0
    rng = np.random.default_rng(42)
    boot_sharpes = np.array([
        sharpe_ratio(rng.choice(returns, size=n, replace=True))
        for _ in range(n_bootstrap)
    ])
    alpha = (1 - confidence) / 2
    lower = float(np.percentile(boot_sharpes, alpha * 100))
    upper = float(np.percentile(boot_sharpes, (1 - alpha) * 100))
    return lower, observed, upper


def win_rate_test(wins: int, total: int, null_rate: float = 0.50) -> dict:
    """Exact binomial test for win rate significance."""
    if total == 0:
        return {"win_rate": 0, "p_value": 1.0, "significant_at_05": False,
                "null_rate": null_rate, "n": 0}
    p_value = float(stats.binomtest(wins, total, null_rate, alternative='greater').pvalue)
    return {
        "win_rate": wins / total,
        "p_value": p_value,
        "significant_at_05": p_value < 0.05,
        "null_rate": null_rate,
        "n": total,
    }


def expectancy_test(pnl_series: np.ndarray) -> dict:
    """One-sample t-test + Wilcoxon signed-rank on trade P&L."""
    if len(pnl_series) < 3:
        return {"mean_pnl": 0, "t_statistic": 0, "t_pvalue": 1.0,
                "wilcoxon_pvalue": 1.0, "significant_at_05": False, "n": len(pnl_series)}
    t_stat, t_pval = stats.ttest_1samp(pnl_series, 0)
    try:
        w_stat, w_pval = stats.wilcoxon(pnl_series, alternative='greater')
    except ValueError:
        w_pval = 1.0
    return {
        "mean_pnl": float(pnl_series.mean()),
        "t_statistic": float(t_stat),
        "t_pvalue": float(t_pval),
        "wilcoxon_pvalue": float(w_pval),
        "significant_at_05": t_pval < 0.05,
        "n": len(pnl_series),
    }


def profit_factor(wins_total: float, losses_total: float) -> float:
    """Gross profits / gross losses."""
    if losses_total == 0:
        return float('inf') if wins_total > 0 else 0.0
    return abs(wins_total / losses_total)


def calmar_ratio(annualized_return: float, max_drawdown_pct: float) -> float:
    """Annualized return / max drawdown."""
    if max_drawdown_pct == 0:
        return 0.0
    return annualized_return / abs(max_drawdown_pct)


def sortino_ratio(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """Sharpe variant using downside deviation only."""
    excess = returns - risk_free
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(excess.mean() / downside.std())


def max_drawdown(equity_curve: np.ndarray) -> tuple[float, int, int]:
    """Maximum drawdown from equity curve. Returns (dd_pct, peak_idx, trough_idx)."""
    if len(equity_curve) == 0:
        return 0.0, 0, 0
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak = 0
    max_dd_trough = 0
    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            peak_idx = i
        dd = (peak - val) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_peak = peak_idx
            max_dd_trough = i
    return float(max_dd), max_dd_peak, max_dd_trough
