"""Deterministic FakeLLM at the llm.client boundary (Task 6).

This fake stands in for ``src.llm.client`` — the module the scan/packet path
calls via ``generate`` (XML-tagged prose + conviction) and ``generate_structured``
(parsed JSON). It returns canned, seeded output so no Ollama call is made and
identical seeds reproduce identical packets (spec §7.2).

Two surfaces:

  * ``generate_candidates()`` emits scan-candidate dicts shaped like the
    ``packet_worthy`` rows the council / governor consume
    (``src.services.scan_service`` builds dicts with ``ticker``, ``score``,
    ``features``). A candidate-volume knob (``n_candidates``) and an optional
    ``scores`` list let scenarios dial how many candidates clear, and at what
    score, so the governor gates can be driven deterministically.

  * ``generate`` / ``generate_structured`` mirror the client's text/JSON return
    shapes for callers that go through ``llm.packet_writer`` — ``generate``
    returns the XML-tagged ``<why_now>/<analysis>/<metadata>`` packet text that
    ``_parse_llm_response`` expects.

Content faults (empty responses, malformed conviction, prompt-leak) are
deliberately NOT injected here — that is Task 10.

T6 spike — ranker preconditions:
  Features emitted by ``generate_candidates`` are tuned so the real
  ``src.ranking.ranker._score_ticker`` produces scores >= 70 (the default
  packet_worthy threshold, ranker.py:114-116) AND all candidate scores are
  DISTINCT (no ties at threshold), guaranteeing stable ranker sort for inv9
  determinism.  The feature VALUES used (documented here for future tuners):

    idx % 3 == 0  →  strong_outperformer + vol=0.7  →  score 95
    idx % 3 == 1  →  outperformer        + vol=0.7  →  score 85
    idx % 3 == 2  →  strong_outperformer + vol=1.2  →  score 80

  All three combos share: trend_state="uptrend" (+20), pullback_depth_pct=-5.0
  (+25, in the -8 to -3 sweet-spot at ranker.py:513-514), dist_to_sma20_pct=-2.0
  (+10, in the -5 to -1 range at ranker.py:519-520).  The tie-free spread comes
  from varying relative_strength_state (+25 / +15 at ranker.py:501-502) and
  volume_ratio_20d (< 0.8 → +15 at ranker.py:524-525; >= 0.8 → 0).

  NOTE: the per-candidate score spread cycles through 3 buckets (95/85/80) when
  n_candidates > 3.  Tickers with the same bucket-score are assigned to different
  tickers (via _TICKER_POOL cycling) — same-bucket ties are possible when
  n_candidates > 3, but the T6 spike tests use n_candidates=3 where all scores
  are unique.  T9 must also use n_candidates <= 3 or rely on the ``scores`` knob
  to guarantee a tie-free feature set.

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: nothing (pure stdlib). Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_fake_market_llm.py
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Optional

_TICKER_POOL = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "AVGO", "NFLX", "CRM", "ADBE", "QCOM", "INTC", "ORCL",
]


class FakeLLM:
    """Seeded canned-packet generator standing in for src.llm.client."""

    def __init__(
        self,
        *,
        seed: int = 0,
        n_candidates: int = 0,
        scores: Optional[list[float]] = None,
    ) -> None:
        self._seed = seed
        self._n_candidates = n_candidates
        self._scores = scores
        self.calls: Counter = Counter()

    # Per-candidate feature buckets (idx % 3) — tuned so real ranker scores each
    # above 70 (packet_worthy threshold) with NO ties when n_candidates <= 3.
    # See module docstring for the full scoring arithmetic.
    _CANDIDATE_BUCKETS = [
        # bucket 0: score 95 (strong_outperformer + low volume)
        {"relative_strength_state": "strong_outperformer", "volume_ratio_20d": 0.7},
        # bucket 1: score 85 (outperformer + low volume)
        {"relative_strength_state": "outperformer", "volume_ratio_20d": 0.7},
        # bucket 2: score 80 (strong_outperformer + normal volume)
        {"relative_strength_state": "strong_outperformer", "volume_ratio_20d": 1.2},
    ]

    def generate_candidates(self) -> list[dict]:
        """Return ``n_candidates`` scan-candidate dicts (ticker/score/features).

        Feature values are tuned so the real ``rank_universe`` scores each
        candidate above 70 (packet_worthy threshold) with no ties when
        n_candidates <= 3.  See class docstring for scoring arithmetic.
        """
        rng = random.Random(self._seed)
        candidates: list[dict] = []
        for idx in range(self._n_candidates):
            ticker = _TICKER_POOL[idx % len(_TICKER_POOL)]
            if self._scores is not None:
                score = self._scores[idx % len(self._scores)]
            else:
                score = round(rng.uniform(50.0, 100.0), 2)
            bucket = self._CANDIDATE_BUCKETS[idx % len(self._CANDIDATE_BUCKETS)]
            candidates.append({
                "ticker": ticker,
                "score": score,
                "features": {
                    "current_price": round(rng.uniform(20.0, 500.0), 2),
                    "trend_state": "uptrend",
                    "relative_strength_state": bucket["relative_strength_state"],
                    "pullback_depth_pct": -5.0,
                    "dist_to_sma20_pct": -2.0,
                    "volume_ratio_20d": bucket["volume_ratio_20d"],
                    "_score": score,
                },
            })
        return candidates

    def generate(self, prompt: str, system_prompt: str, **kwargs) -> str:
        """Return the canned XML-tagged packet text (shape of client.generate)."""
        self.calls["generate"] += 1
        rng = random.Random(self._seed)
        conviction = rng.randint(1, 10)
        return (
            "<why_now>Seeded simulator setup; mechanical signal triggered.</why_now>\n"
            "<analysis>Deterministic canned analysis for the lifecycle "
            "simulator; no live model was called.</analysis>\n"
            "<metadata>\n"
            f"Conviction: {conviction}\n"
            "Direction: LONG\n"
            "Time Horizon: swing\n"
            "Key Risk: simulated regime shift.\n"
            "Expected Holding Period: 5 days\n"
            "</metadata>"
        )

    def generate_structured(self, prompt: str, system_prompt: str,
                            response_schema: dict, **kwargs) -> dict:
        """Return canned candidate packets (shape of client.generate_structured)."""
        self.calls["generate_structured"] += 1
        return {"candidates": self.generate_candidates()}
