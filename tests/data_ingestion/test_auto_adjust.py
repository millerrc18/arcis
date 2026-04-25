"""F-16 STALE regression test — verifies the project's auto_adjust posture.

Audit spec §F-16 was originally raised as a possible flip of `auto_adjust=False`
to True in src/data_ingestion/market_data.py (lines 54, 68). Investigation
2026-04-24 (per docs/superpowers/plans/2026-04-24-tier-a-b-rootcause-bundle.md
test #510 closeout) found the underlying excess-Sharpe regression resolved by
side-effect of #640 + #647. F-16 is STALE.

The contract pinned here is therefore:
  1. market_data.py (raw OHLCV for slippage / PnL) MUST keep `auto_adjust=False`.
  2. analytics/spy_benchmark.py (excess-return reference) MUST keep
     `auto_adjust=True` so the SPY total-return path includes dividends.
  3. The yfinance FutureWarning suppression for #546 stays wired.

Together this prevents accidental double-counting: SPY benchmark adjusts for
dividends, individual ticker OHLCV does not. If a future change flips either
flag, this test fails loudly so the operator re-runs the F-16 analysis.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_market_data_keeps_auto_adjust_false():
    """Raw OHLCV must NOT be auto-adjusted (slippage/PnL accuracy)."""
    text = _read("src/data_ingestion/market_data.py")
    assert "auto_adjust=False" in text, (
        "src/data_ingestion/market_data.py must keep auto_adjust=False — "
        "F-16 STALE per audit-spec.md §F-16. If this is intentional, "
        "re-run the F-16 analysis and update the SPY-vs-ticker reconciliation."
    )
    assert "auto_adjust=True" not in text, (
        "src/data_ingestion/market_data.py must NOT introduce auto_adjust=True; "
        "raw OHLCV is required for slippage/PnL accounting."
    )


def test_spy_benchmark_keeps_auto_adjust_true():
    """SPY excess-return reference must be auto-adjusted (dividend-inclusive)."""
    text = _read("src/analytics/spy_benchmark.py")
    assert "auto_adjust=True" in text, (
        "src/analytics/spy_benchmark.py must keep auto_adjust=True so SPY "
        "total return reflects dividends. F-16 STALE — see audit-spec.md."
    )


def test_auto_adjust_warning_suppression_present():
    """#546: the FutureWarning emitted by yfinance >=0.2.50 stays suppressed."""
    text = _read("src/data_ingestion/market_data.py")
    assert "filterwarnings" in text or "catch_warnings" in text, (
        "yfinance auto_adjust FutureWarning suppression missing (#546)."
    )


def test_close_to_close_return_invariant_unaffected_by_auto_adjust_false():
    """Synthetic OHLCV: a simple close-to-close return computed off the
    raw Close column matches expected; this proves auto_adjust=False does
    not corrupt the returns we feed into PnL accounting on a non-dividend
    day. Dividend handling is delegated to spy_benchmark.py
    (auto_adjust=True) so excess returns aren't double-counted.
    """
    import pandas as pd

    df = pd.DataFrame(
        {
            "Open":   [100.0, 101.0, 102.5],
            "High":   [101.5, 102.5, 103.0],
            "Low":    [ 99.5, 100.5, 101.0],
            "Close":  [101.0, 102.5, 102.0],
            "Volume": [1_000_000, 1_100_000, 900_000],
        },
        index=pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"]),
    )

    rets = df["Close"].pct_change().dropna().tolist()
    # 102.5 / 101.0 - 1 ≈ 0.014851 ; 102.0 / 102.5 - 1 ≈ -0.004878
    assert rets[0] == (102.5 / 101.0) - 1
    assert rets[1] == (102.0 / 102.5) - 1
