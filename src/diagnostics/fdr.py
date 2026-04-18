"""Benjamini-Hochberg FDR correction.

Called by: diagnostics.analyses
Calls: numpy
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np


def benjamini_hochberg(
    p_values: np.ndarray, q: float = 0.10,
) -> tuple[np.ndarray, list[bool]]:
    """Apply Benjamini-Hochberg FDR correction.

    Returns (adjusted_p_values, survived) where survived[i] is True
    if the i-th test survives at FDR level q.
    """
    p_values = np.asarray(p_values, dtype=float)
    m = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]

    # Adjusted p-values (step-up)
    adjusted = np.empty(m)
    adjusted[sorted_idx[-1]] = sorted_p[-1]
    for i in range(m - 2, -1, -1):
        rank = i + 1
        adj = sorted_p[i] * m / rank
        adjusted[sorted_idx[i]] = min(adj, adjusted[sorted_idx[i + 1]])
    adjusted = np.clip(adjusted, 0, 1)

    survived = [bool(adjusted[i] <= q) for i in range(m)]
    return adjusted, survived
