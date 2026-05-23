"""Tests for the FakeMarketData + FakeLLM boundary fakes (Task 6).

FakeMarketData stands in for ``src.simulation.cache.fetch_cached_ohlcv`` — it
emits a pandas DataFrame with the same OHLCV column shape (Open, High, Low,
Close, Volume) indexed by date, seeded so identical seeds yield identical bars.

FakeLLM stands in for ``src.llm.client`` generate/generate_structured — it
returns canned/seeded candidate packets shaped like the scan candidate dicts
the council/governor consume (``ticker``, ``score``, ``features``), with a
candidate-volume knob so scenarios can drive the governor gates.

Fault injection (gaps/halts/regime + rejections) is deliberately NOT exercised
here — that is Task 10.
"""

import pandas as pd

from src.simulation.lifecycle.fakes import FakeLLM, FakeMarketData

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


# ── FakeMarketData: column shape ─────────────────────────────────────────


def test_market_data_matches_cache_column_shape():
    md = FakeMarketData(seed=42)
    bars = md.fetch_cached_ohlcv("AAPL", "2026-01-01", "2026-01-10")
    assert isinstance(bars, pd.DataFrame)
    assert list(bars.columns) == _OHLCV_COLUMNS
    assert len(bars) > 0
    # OHLC invariant: high >= low, and high/low bracket open/close
    assert (bars["High"] >= bars["Low"]).all()
    assert (bars["High"] >= bars["Open"]).all()
    assert (bars["High"] >= bars["Close"]).all()
    assert (bars["Low"] <= bars["Open"]).all()
    assert (bars["Low"] <= bars["Close"]).all()
    assert (bars["Volume"] > 0).all()


# ── FakeMarketData: determinism ──────────────────────────────────────────


def test_market_data_same_seed_identical_bars():
    md_a = FakeMarketData(seed=7)
    md_b = FakeMarketData(seed=7)
    bars_a = md_a.fetch_cached_ohlcv("MSFT", "2026-02-01", "2026-02-15")
    bars_b = md_b.fetch_cached_ohlcv("MSFT", "2026-02-01", "2026-02-15")
    pd.testing.assert_frame_equal(bars_a, bars_b)


def test_market_data_different_seed_differs():
    bars_a = FakeMarketData(seed=1).fetch_cached_ohlcv("NVDA", "2026-03-01", "2026-03-10")
    bars_b = FakeMarketData(seed=2).fetch_cached_ohlcv("NVDA", "2026-03-01", "2026-03-10")
    assert not bars_a["Close"].equals(bars_b["Close"])


def test_market_data_per_ticker_independent_but_deterministic():
    md = FakeMarketData(seed=99)
    aapl = md.fetch_cached_ohlcv("AAPL", "2026-01-01", "2026-01-10")
    msft = md.fetch_cached_ohlcv("MSFT", "2026-01-01", "2026-01-10")
    # different tickers, same seed/window → different series
    assert not aapl["Close"].equals(msft["Close"])
    # re-fetching the same ticker yields the identical series
    aapl_again = md.fetch_cached_ohlcv("AAPL", "2026-01-01", "2026-01-10")
    pd.testing.assert_frame_equal(aapl, aapl_again)


# ── FakeLLM: determinism ─────────────────────────────────────────────────


def test_llm_same_seed_identical_candidates():
    llm_a = FakeLLM(seed=11, n_candidates=5)
    llm_b = FakeLLM(seed=11, n_candidates=5)
    assert llm_a.generate_candidates() == llm_b.generate_candidates()


def test_llm_candidate_shape_matches_scan_candidate():
    llm = FakeLLM(seed=3, n_candidates=2)
    candidates = llm.generate_candidates()
    for cand in candidates:
        assert set(["ticker", "score", "features"]).issubset(cand.keys())
        assert isinstance(cand["ticker"], str)
        assert isinstance(cand["score"], (int, float))
        assert isinstance(cand["features"], dict)


# ── FakeLLM: candidate-volume knob ───────────────────────────────────────


def test_llm_candidate_volume_knob():
    assert len(FakeLLM(seed=1, n_candidates=0).generate_candidates()) == 0
    assert len(FakeLLM(seed=1, n_candidates=1).generate_candidates()) == 1
    assert len(FakeLLM(seed=1, n_candidates=12).generate_candidates()) == 12


def test_llm_score_knob_drives_candidate_scores():
    llm = FakeLLM(seed=5, n_candidates=3, scores=[90.0, 80.0, 70.0])
    candidates = llm.generate_candidates()
    assert [c["score"] for c in candidates] == [90.0, 80.0, 70.0]


def test_llm_generate_returns_canned_packet_text():
    llm = FakeLLM(seed=8, n_candidates=1)
    text = llm.generate("prompt", "system")
    assert isinstance(text, str)
    assert "<why_now>" in text and "<metadata>" in text
    # same seed → identical canned text
    assert FakeLLM(seed=8, n_candidates=1).generate("prompt", "system") == text


# ── FakeLLM.calls counter (T3 follow-up / T8 prereq, spec §2.4) ──────────


def test_llm_generate_increments_calls_counter():
    """Counter consumed by provenance guard (T8) — proves generate was invoked."""
    llm = FakeLLM(seed=1, n_candidates=1)
    assert llm.calls["generate"] == 0
    llm.generate("prompt", "system")
    assert llm.calls["generate"] == 1
    llm.generate("prompt", "system")
    assert llm.calls["generate"] == 2


def test_llm_generate_structured_increments_calls_counter():
    """generate_structured also increments its own counter key for symmetry."""
    llm = FakeLLM(seed=1, n_candidates=1)
    assert llm.calls["generate_structured"] == 0
    llm.generate_structured("prompt", "system", {})
    assert llm.calls["generate_structured"] == 1


# ── FakeMarketData.fetch_ohlcv ───────────────────────────────────────────


def test_fetch_ohlcv_returns_dict_keyed_by_universe():
    md = FakeMarketData(seed=42)
    universe = ["AAPL", "MSFT", "NVDA"]
    result = md.fetch_ohlcv(universe)
    assert isinstance(result, dict)
    assert set(result.keys()) == set(universe)


def test_fetch_ohlcv_each_frame_nonempty_with_ohlcv_columns():
    md = FakeMarketData(seed=1)
    universe = ["AAPL", "GOOG"]
    result = md.fetch_ohlcv(universe)
    for ticker, df in result.items():
        assert isinstance(df, pd.DataFrame), f"{ticker} value is not a DataFrame"
        assert len(df) > 0, f"{ticker} DataFrame is empty"
        assert list(df.columns) == _OHLCV_COLUMNS, f"{ticker} columns mismatch"


def test_fetch_ohlcv_close_always_positive():
    md = FakeMarketData(seed=77)
    universe = ["SPY", "AAPL", "TSLA"]
    result = md.fetch_ohlcv(universe)
    for ticker, df in result.items():
        assert (df["Close"] > 0).all(), f"{ticker} has Close <= 0"


def test_fetch_ohlcv_same_seed_frame_equal():
    universe = ["AAPL", "MSFT"]
    md_a = FakeMarketData(seed=13)
    md_b = FakeMarketData(seed=13)
    result_a = md_a.fetch_ohlcv(universe)
    result_b = md_b.fetch_ohlcv(universe)
    for ticker in universe:
        pd.testing.assert_frame_equal(result_a[ticker], result_b[ticker])


def test_fetch_ohlcv_counter_increments():
    md = FakeMarketData(seed=5)
    assert md.calls["fetch_ohlcv"] == 0
    md.fetch_ohlcv(["AAPL"])
    assert md.calls["fetch_ohlcv"] == 1
    md.fetch_ohlcv(["AAPL", "MSFT"])
    assert md.calls["fetch_ohlcv"] == 2


# ── FakeMarketData.fetch_spy_benchmark ──────────────────────────────────


def test_fetch_spy_benchmark_nonempty():
    md = FakeMarketData(seed=0)
    spy = md.fetch_spy_benchmark()
    assert isinstance(spy, pd.DataFrame)
    assert not spy.empty


def test_fetch_spy_benchmark_close_positive():
    md = FakeMarketData(seed=0)
    spy = md.fetch_spy_benchmark()
    assert (spy["Close"] > 0).all()


def test_fetch_spy_benchmark_same_seed_frame_equal():
    md_a = FakeMarketData(seed=99)
    md_b = FakeMarketData(seed=99)
    pd.testing.assert_frame_equal(md_a.fetch_spy_benchmark(), md_b.fetch_spy_benchmark())


def test_fetch_spy_counter_increments():
    md = FakeMarketData(seed=3)
    assert md.calls["fetch_spy"] == 0
    md.fetch_spy_benchmark()
    assert md.calls["fetch_spy"] == 1
    md.fetch_spy_benchmark()
    assert md.calls["fetch_spy"] == 2
