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

Ranker / T9 precondition tests (Task 6 spike)
=============================================
Three additional groups exercise build-time preconditions that Task 9 depends on:

(a) ranker_yields_candidate — import the real ``src.ranking.ranker.rank_universe``
    and ``get_top_candidates``; build a features dict from FakeLLM.generate_candidates()
    output; assert >=1 packet_worthy candidate is returned.  This is the critical
    build-spike: if the ranker filters everything, T9 can't drive an organic scan.

    Tuning note: FakeLLM.generate_candidates() emits features including
    ``pullback_depth_pct``, ``dist_to_sma20_pct``, and ``volume_ratio_20d`` with
    values chosen so the real ranker's ``_score_ticker`` produces scores >= 70
    (the default packet_worthy threshold).  The feature VALUES used are:
      - trend_state="uptrend"             → +20 pts
      - relative_strength_state varies    → +15 to +25 pts (per-ticker spread, no ties)
      - pullback_depth_pct=-5.0           → +25 pts (in the -8 to -3 sweet spot)
      - dist_to_sma20_pct=-2.0           → +10 pts (in the -5 to -1 range)
      - volume_ratio_20d varies           → +0 or +15 pts (creates per-ticker unique scores)
    Resulting scores: 95, 85, 80 — all above the 70 threshold, with no ties.

(b) ranker_tiebreak_stable — two independent calls with the SAME seeded
    FakeLLM instance return the same top candidate (ticker, score).  Because the
    fakes emit distinct per-ticker scores (no ties at threshold), this effectively
    verifies the ranker's sort is stable under the fake data.  The unstable
    tie-break (Python dict-insertion-order dependency when scores are equal) is a
    KNOWN LIMITATION documented in the concerns section of the T6 status report —
    it's a finding for T13 but does NOT affect T9 because the fakes are tie-free.

(c) executor_insert_covers_inv9_columns (docstring-level assertion, no DB required)
    The inv9 snapshot at ``_checks_db.py:139-145`` hashes 7 columns per
    shadow_trades row: recommendation_id, ticker, status, actual_shares,
    order_type, exit_reason, pnl_dollars.
    ``executor.open_shadow_trade`` writes all 7 via ``insert_shadow_trade``:
      - recommendation_id: passed directly at executor.py:817 (ShadowTrade init)
      - ticker: executor.py:819
      - status: executor.py:820 ('pending' → set to 'open'/'rejected'/etc.)
      - actual_shares: set at executor.py:874-878 (fill path) or rejection paths
        (NOTE: the column is ``planned_shares`` at creation; ``actual_shares`` is
        populated by the close/fill flow.  At open time the inv9-hashed value will
        be None/0 — this is expected: inv9 captures the full lifecycle snapshot
        AFTER the sim completes, not at open time.)
      - order_type: executor.py:881-882 (bracket) or rejection fallbacks
      - exit_reason: populated on close; NULL at open (expected for open trades)
      - pnl_dollars: populated on close; NULL at open (expected for open trades)
    All 7 columns are registered in the schema registry (src/schema/registry.py)
    and written by the executor/close paths before T9's inv9 check fires.

(d) reconcile_seam_identity (docstring-level assertion, no DB required)
    ``reconcile_all_paper_trades`` (reconcile_dispatch.py:27-66) calls
    ``reconcile_paper_trades`` (reconcile.py), which imports
    ``get_all_positions`` and ``get_live_positions`` from
    ``src.shadow_trading.alpaca_adapter`` (reconcile.py:46-50).
    ``executor.open_shadow_trade`` calls ``_get_trading_client`` from
    ``src.shadow_trading.alpaca_adapter`` (executor.py:983-984) for the
    standalone stop-loss fallback, and ``place_bracket_order`` from the same
    module (executor.py:881) for the bracket path.
    BOTH reconcile and executor funnel through ``src.shadow_trading.alpaca_adapter``
    — so ``wiring.install_organic_patches``'s alpaca patch intercepts calls from
    both code paths, satisfying the consistency invariant for monitor→exit→reconcile.
    Reconcile does NOT import ``_get_trading_client`` directly (it uses higher-level
    ``get_all_positions`` / ``get_live_positions`` which internally call
    ``_get_trading_client``), but the routing is through the same adapter module.
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


# ── T6 spike: Ranker precondition tests ─────────────────────────────────


def test_ranker_yields_at_least_one_candidate_from_fake_features():
    """(T6-a) rank_universe produces >=1 packet_worthy candidate from FakeLLM features.

    Uses the real prod ranker (src.ranking.ranker.rank_universe + get_top_candidates).
    FakeLLM.generate_candidates() now emits features tuned to score >= 70 (default
    packet_worthy threshold).  See module docstring for tuning rationale.
    """
    from src.ranking.ranker import rank_universe, get_top_candidates

    llm = FakeLLM(seed=42, n_candidates=3)
    candidates = llm.generate_candidates()
    assert len(candidates) == 3, "FakeLLM must emit 3 candidates for this test"

    # Build the features dict rank_universe expects: ticker -> feature dict
    features = {c["ticker"]: c["features"] for c in candidates}

    ranked = rank_universe(features)
    result = get_top_candidates(ranked)
    packet_worthy = result["packet_worthy"]

    assert len(packet_worthy) >= 1, (
        f"rank_universe returned 0 packet_worthy candidates from FakeLLM features. "
        f"Ranked scores: {[(r['ticker'], r['score']) for r in ranked]}. "
        "Tune FakeLLM feature VALUES (trend_state, relative_strength_state, "
        "pullback_depth_pct, dist_to_sma20_pct, volume_ratio_20d) to clear threshold=70."
    )


def test_ranker_tiebreak_stable_across_two_seeded_runs():
    """(T6-b) Two independent rank_universe calls with same FakeLLM seed return same top candidate.

    Because FakeLLM generates distinct per-ticker scores (no ties at threshold),
    the ranker's sort is deterministic — same top candidate (ticker, score) both runs.
    Tie-break INSTABILITY with equal scores is a known finding (T13): when scores tie,
    the Python dict insertion-order determines the winner, which is seam-observable.
    The fakes sidestep this by design (distinct scores).
    """
    from src.ranking.ranker import rank_universe, get_top_candidates

    llm = FakeLLM(seed=42, n_candidates=3)

    # Run 1
    candidates_1 = llm.generate_candidates()
    features_1 = {c["ticker"]: c["features"] for c in candidates_1}
    ranked_1 = rank_universe(features_1)
    top_1 = get_top_candidates(ranked_1)["packet_worthy"][0]

    # Run 2 — fresh instance, same seed
    llm2 = FakeLLM(seed=42, n_candidates=3)
    candidates_2 = llm2.generate_candidates()
    features_2 = {c["ticker"]: c["features"] for c in candidates_2}
    ranked_2 = rank_universe(features_2)
    top_2 = get_top_candidates(ranked_2)["packet_worthy"][0]

    assert top_1["ticker"] == top_2["ticker"], (
        f"Tie-break unstable: run1 top={top_1['ticker']} run2 top={top_2['ticker']}. "
        "FakeLLM must produce distinct per-ticker scores so no ties exist at threshold."
    )
    assert top_1["score"] == top_2["score"], (
        f"Score mismatch: run1={top_1['score']} run2={top_2['score']}. "
        "Same seed must produce same scores."
    )


def test_fake_llm_candidates_have_distinct_scores():
    """(T6-b support) FakeLLM n_candidates=3 produces 3 candidates with all-distinct scores.

    This guarantees no ties exist at the packet_worthy threshold — required for
    ranker tie-break stability (T6-b) and inv9 determinism (T9).
    """
    llm = FakeLLM(seed=42, n_candidates=3)
    candidates = llm.generate_candidates()
    scores = [c["score"] for c in candidates]
    assert len(scores) == len(set(scores)), (
        f"FakeLLM produced tied scores: {scores}. "
        "All candidate scores must be distinct to guarantee tie-free ranker output."
    )
