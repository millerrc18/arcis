"""Tests for src.platform.rigor.cscv — Combinatorially Symmetric CV / PBO.

Non-negotiable quality gates for Sprint 2:
  - test_pbo_rejects_overfit_strategy — seeded PnL with known IS/OOS
    divergence returns PBO > 0.8
  - test_pbo_accepts_stable_strategy — seeded stable performer returns
    PBO < 0.2
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from src.platform.rigor.cscv import pbo_from_pnl_matrix


def _seeded_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def test_pbo_rejects_overfit_strategy():
    """Seeded overfit pattern: N=16 configs where each config has
    block-localized alpha in 2 of the 16 blocks, and anti-alpha in
    the opposite 8 blocks. CSCV detects this because the IS-winner
    owes its IS-selection to its lucky 2 blocks; those blocks are
    unlikely to all land in OOS, so the IS-winner tends to be in the
    bottom half of the OOS ranking. With this strong IS/OOS inversion,
    PBO should be >0.8 (i.e., the IS-winner lands below OOS median in
    >80% of the C(16,8)=12,870 splits)."""
    rng = _seeded_rng(42)
    T, N = 256, 16
    noise_sigma = 0.005
    block_size = T // N   # 16 observations per block
    alpha = 0.06          # 12× noise sigma — signal dominates within each block

    pnl_arr = rng.normal(0, noise_sigma, size=(T, N))
    # Each config j gets strong +alpha in two consecutive blocks and
    # -alpha in the diametrically opposite two blocks.  The IS-winner
    # exploits its lucky blocks; those same blocks are absent from OOS.
    for j in range(N):
        pos_start = (j * 2) % N
        neg_start = (pos_start + 8) % N
        for b in [pos_start, (pos_start + 1) % N]:
            row_s = b * block_size
            row_e = min((b + 1) * block_size, T)
            pnl_arr[row_s:row_e, j] += alpha
        for b in [neg_start, (neg_start + 1) % N]:
            row_s = b * block_size
            row_e = min((b + 1) * block_size, T)
            pnl_arr[row_s:row_e, j] -= alpha

    pnl = pd.DataFrame(pnl_arr, columns=[f"c{i}" for i in range(N)])
    out = pbo_from_pnl_matrix(pnl, S=16)
    assert "PBO" in out
    assert out["PBO"] > 0.8, f"expected PBO > 0.8 on block-localized overfit, got {out['PBO']}"


def test_pbo_accepts_stable_strategy():
    """Stable strategy: one config with consistent alpha, others pure noise.
    The IS-winner should be the same config across most splits AND it
    should OOS-outperform median in most splits, so PBO should be <0.2."""
    rng = _seeded_rng(7)
    T, N = 256, 16
    pnl_arr = rng.normal(0, 0.01, size=(T, N))
    # Config 0 has consistent alpha across the full sample
    pnl_arr[:, 0] += 0.002
    pnl = pd.DataFrame(pnl_arr, columns=[f"c{i}" for i in range(N)])
    out = pbo_from_pnl_matrix(pnl, S=16)
    assert out["PBO"] < 0.2, f"expected PBO < 0.2 on stable performer, got {out['PBO']}"


def test_pbo_handles_S16_T256_paper_canonical():
    """The canonical S=16 configuration must work on a modest T. For
    T=256 (S divides evenly), no warnings and a defined PBO in [0,1]."""
    rng = _seeded_rng(1)
    pnl = pd.DataFrame(rng.normal(0, 0.01, size=(256, 8)),
                       columns=[f"c{i}" for i in range(8)])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = pbo_from_pnl_matrix(pnl, S=16)
    # No S-truncation warning at T=256, S=16
    assert not any("S=" in str(x.message) for x in w)
    assert 0.0 <= out["PBO"] <= 1.0


def test_pbo_returns_logit_distribution_and_degradation():
    """Output dict must include logit_distribution (list[float]) and
    performance_degradation_points (list of (IS_metric, OOS_metric))."""
    rng = _seeded_rng(3)
    pnl = pd.DataFrame(rng.normal(0, 0.01, size=(256, 8)),
                       columns=[f"c{i}" for i in range(8)])
    out = pbo_from_pnl_matrix(pnl, S=16)
    assert "logit_distribution" in out
    assert isinstance(out["logit_distribution"], list)
    assert len(out["logit_distribution"]) > 0
    assert "performance_degradation_points" in out
    assert isinstance(out["performance_degradation_points"], list)


def test_pbo_warns_when_T_below_S_times_16_threshold():
    """If T < 256 (S=16 × 16), emit warning. Module adjusts S = T // 16
    with at-least-2 floor."""
    rng = _seeded_rng(5)
    pnl = pd.DataFrame(rng.normal(0, 0.01, size=(100, 8)),
                       columns=[f"c{i}" for i in range(8)])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = pbo_from_pnl_matrix(pnl, S=16)
    assert any("S=" in str(x.message) or "T<" in str(x.message)
               for x in w), "expected truncation warning"
    assert 0.0 <= out["PBO"] <= 1.0
