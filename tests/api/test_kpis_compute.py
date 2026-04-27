"""Smoke tests for kpis_compute helpers (PR #696 split surface).

When kpis.py was split into kpis.py (FastAPI surface) + kpis_compute.py
(numerics) per #696, these are the import-and-smoke tests for the
extracted numerics. The full numerical lock-in lives in test_kpis.py
and test_kpis_se_units.py.
"""

from __future__ import annotations

import datetime as _dt

import pytest


def test_kpis_compute_module_imports():
    """Public surface of kpis_compute must import cleanly."""
    from src.api.cloud_routes import kpis_compute
    assert hasattr(kpis_compute, "_sharpe_t_stat_and_ci")
    assert hasattr(kpis_compute, "_sharpe_p_value")
    assert hasattr(kpis_compute, "_lo_2002_autocorr_factor")


def test_parse_iso_date_handles_none():
    from src.api.cloud_routes.kpis_compute import _parse_iso_date
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("") is None


def test_parse_iso_date_handles_valid():
    from src.api.cloud_routes.kpis_compute import _parse_iso_date
    result = _parse_iso_date("2026-04-27")
    assert result == _dt.date(2026, 4, 27)


def test_sharpe_p_value_signature():
    """Smoke: callable with documented (t_stat, n) signature."""
    from src.api.cloud_routes.kpis_compute import _sharpe_p_value
    p = _sharpe_p_value(0.0, 100)
    assert p is None or 0.0 <= p <= 1.0


def test_sample_autocorrelation_zero_for_constant_series():
    from src.api.cloud_routes.kpis_compute import _sample_autocorrelation
    result = _sample_autocorrelation([1.0] * 50, k=1)
    assert result == 0.0 or result is None or abs(result) < 1e-9


def test_lo_2002_autocorr_factor_signature():
    """Smoke: callable, returns numeric or None for typical input.

    Numerical correctness is locked in test_kpis.py / test_kpis_se_units.py.
    """
    from src.api.cloud_routes.kpis_compute import _lo_2002_autocorr_factor
    series = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01] * 20
    factor = _lo_2002_autocorr_factor(series, q=4)
    assert factor is None or isinstance(factor, (int, float))


def test_kpi_status_rf_sharpe_handles_none():
    from src.api.cloud_routes.kpis_compute import _kpi_status_rf_sharpe
    status = _kpi_status_rf_sharpe(None, None)
    assert isinstance(status, str)
