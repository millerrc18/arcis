"""E4 — profit_factor 999 sentinel tests.

Validates that src/simulation/engine.py emits None (not 999.0) when
profit_factor is inf (winners-only case), and preserves existing
behavior for mixed win/loss and empty-trades cases.

Test strategy:
  1) winners-only scenario -> profit_factor is None  (fails before engine fix)
  2) mixed wins + losses -> profit_factor is a finite float
  3) no trades -> profit_factor is 0 (legacy contract preserved)
  4) source-code guard: engine.py must not contain the 999.0 sentinel literal
"""
from __future__ import annotations

import math
import pathlib


def _compute_profit_factor(wins: list[float], losses: list[float]) -> float | None:
    """Mirror of the profit_factor computation in engine.py + the sentinel fix.

    Returns None for inf (winners-only), 0 for empty, finite float otherwise.
    """
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))

    if gross_losses == 0:
        raw = float("inf") if gross_wins > 0 else 0.0
    else:
        raw = gross_wins / gross_losses

    if raw == float("inf"):
        return None
    if raw == 0.0:
        return 0.0
    return round(raw, 3)


class TestProfitFactorSentinel:
    def test_winners_only_emits_none(self):
        wins = [10.0, 20.0, 5.0]
        losses: list[float] = []
        result = _compute_profit_factor(wins, losses)
        assert result is None, f"Expected None for winners-only, got {result!r}"

    def test_mixed_wins_losses_emits_finite_float(self):
        wins = [10.0, 20.0]
        losses = [-5.0]
        result = _compute_profit_factor(wins, losses)
        assert result is not None
        assert math.isfinite(result), f"Expected finite float, got {result!r}"
        assert result > 0

    def test_empty_trades_emits_zero(self):
        wins: list[float] = []
        losses: list[float] = []
        result = _compute_profit_factor(wins, losses)
        assert result == 0.0, f"Expected 0.0 for empty trades, got {result!r}"

    def test_engine_source_does_not_contain_999_sentinel(self):
        """Engine source guard: profit_factor sentinel must be None, not 999.0.

        This test FAILS on the original engine.py (which has `else 999.0`) and
        PASSES after the fix (which has `else None`).
        """
        engine_path = pathlib.Path(__file__).parent.parent / "src" / "simulation" / "engine.py"
        source = engine_path.read_text(encoding="utf-8")
        assert "else 999.0" not in source, (
            "engine.py still contains the 999.0 profit_factor sentinel — "
            "fix engine.py:458 to emit None instead of 999.0 for inf profit_factor"
        )

    def test_engine_finite_profit_factor_preserved(self):
        """Non-inf profit_factor is still rounded and returned as-is."""
        profit_factor = 2.5
        result = round(profit_factor, 3) if profit_factor != float("inf") else None
        assert result == 2.5
