"""Regression-lock for v0.36.31 — F-2: model-win-rate precheck small-sample guard.

Background (W21 lifecycle audit, finding F-2, CRITICAL)
======================================================

`src/evaluation/auditor.py::_check_model_win_rate` fired a CRITICAL flag
when a model version had `trades >= 2 AND win_rate == 0`. Line 509:
`if trades < 2 or win_rate > 0: continue`.

This is the deterministic-precheck twin of the v0.36.27 bug. v0.36.27 added
`_LLM_AUDIT_MIN_SAMPLE=10` to gate the LLM *narrative*, but
`_append_deterministic_prechecks` runs unconditionally (auditor.py:120-148),
so this precheck was never gated. A 2-loss day for any model version
(arcis:v1.0.0 had exactly this on 2026-05-18 per CHANGELOG) fires CRITICAL
→ entry suppression → trading desk dark on noise → false-CRITICAL Telegram.

The same small-sample-extrapolation class as v0.36.22 (drawdown, guarded at
N=50) and v0.36.27 (LLM narrative, guarded at N=10).

The fix
=======

`_MODEL_WIN_RATE_MIN_SAMPLE = 10` (mirrors v0.36.27). The precheck only
fires when `trades >= 10 AND win_rate == 0` — a real signal of a broken
model, not 2-trade noise.
"""
from __future__ import annotations

import pytest


def _run_check(trades: int, win_rate: float) -> list[dict]:
    """Run _check_model_win_rate against a single model version."""
    from src.evaluation.auditor import _check_model_win_rate
    flags: list[dict] = []
    cto_data = {
        "by_model_version": {
            "arcis:v1.0.0": {"trades": trades, "win_rate": win_rate},
        }
    }
    _check_model_win_rate(flags, cto_data)
    return flags


def test_two_losses_does_not_fire_critical():
    """trades=2, win_rate=0 → NO flag (the 2026-05-18 false-positive case)."""
    flags = _run_check(trades=2, win_rate=0.0)
    assert flags == [], (
        "model_win_rate fired CRITICAL on a 2-trade sample. This is the F-2 "
        "small-sample bug — same class as v0.36.22 and v0.36.27. Must require "
        "at least _MODEL_WIN_RATE_MIN_SAMPLE trades."
    )


def test_nine_losses_does_not_fire_critical():
    """trades=9 (one below threshold) → still no flag."""
    flags = _run_check(trades=9, win_rate=0.0)
    assert flags == [], (
        f"model_win_rate fired on trades=9, below the min-sample threshold."
    )


def test_ten_zero_winrate_fires_critical():
    """trades=10 (at threshold) + win_rate=0 → flag (real broken-model signal)."""
    from src.evaluation.auditor import _MODEL_WIN_RATE_MIN_SAMPLE
    flags = _run_check(trades=_MODEL_WIN_RATE_MIN_SAMPLE, win_rate=0.0)
    assert len(flags) == 1, (
        f"Expected 1 CRITICAL flag at trades={_MODEL_WIN_RATE_MIN_SAMPLE}, "
        f"win_rate=0, got {len(flags)}."
    )
    assert flags[0]["severity"] == "critical"
    assert flags[0]["metric"] == "model_win_rate"


def test_high_sample_nonzero_winrate_does_not_fire():
    """trades=20, win_rate=0.3 → no flag (win_rate > 0)."""
    flags = _run_check(trades=20, win_rate=0.3)
    assert flags == [], "Non-zero win rate should never flag regardless of sample."


def test_min_sample_constant_matches_llm_guard():
    """The new constant should mirror v0.36.27's value for consistency
    across deterministic + narrative sample guards."""
    from src.evaluation.auditor import _MODEL_WIN_RATE_MIN_SAMPLE, _LLM_AUDIT_MIN_SAMPLE
    assert _MODEL_WIN_RATE_MIN_SAMPLE == _LLM_AUDIT_MIN_SAMPLE == 10, (
        "Sample-size guards should be consistent. If you intentionally diverge, "
        "document why in the auditor module."
    )
