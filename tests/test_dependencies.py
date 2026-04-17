"""Regression tests for runtime dependencies that must be declared in
requirements.txt.

Each test imports a dependency that production code uses directly. If any
of these fail on a clean-deploy `pip install -r requirements.txt`, it means
the dep was never declared and fed_collector / analytics / simulation cache
will crash at first import.

Called by: pytest
Calls: none
Owns tables: none
Config keys: none
Tests: self (this IS the test file)
"""
from __future__ import annotations


def test_pyarrow_importable() -> None:
    """Regression for #462: src/simulation/cache.py uses pd.read_parquet / to_parquet.

    pandas requires pyarrow (or fastparquet) for parquet IO. Without pyarrow
    declared, `pd.read_parquet(...)` fails on clean deploy.
    """
    import pyarrow  # noqa: F401


def test_scipy_importable() -> None:
    """Regression for #460: src/evaluation/statistics.py uses `from scipy import stats`."""
    import scipy  # noqa: F401


def test_numpy_importable() -> None:
    """Regression for #460: src/evaluation/*, features/regime, simulation/monte_carlo use numpy."""
    import numpy  # noqa: F401
