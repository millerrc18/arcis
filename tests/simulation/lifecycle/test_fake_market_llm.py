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
