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

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: nothing (pure stdlib). Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_fake_market_llm.py
"""

from __future__ import annotations

import random
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

    def generate_candidates(self) -> list[dict]:
        """Return ``n_candidates`` scan-candidate dicts (ticker/score/features)."""
        rng = random.Random(self._seed)
        candidates: list[dict] = []
        for idx in range(self._n_candidates):
            ticker = _TICKER_POOL[idx % len(_TICKER_POOL)]
            if self._scores is not None:
                score = self._scores[idx % len(self._scores)]
            else:
                score = round(rng.uniform(50.0, 100.0), 2)
            candidates.append({
                "ticker": ticker,
                "score": score,
                "features": {
                    "current_price": round(rng.uniform(20.0, 500.0), 2),
                    "trend_state": "uptrend",
                    "relative_strength_state": "strong",
                    "_score": score,
                },
            })
        return candidates

    def generate(self, prompt: str, system_prompt: str, **kwargs) -> str:
        """Return the canned XML-tagged packet text (shape of client.generate)."""
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
        return {"candidates": self.generate_candidates()}
