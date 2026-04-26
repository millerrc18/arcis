"""Shared fixtures for tests/scripts/.

Per CLAUDE.md: "Mock all external APIs in tests — no network calls from
pytest (Alpaca, Finnhub, yfinance, FRED, Ollama)". The Stage-1 baseline
recompute script wires the FRED DTB3 adapter (PR #690 review item I1);
this autouse fixture stubs FRED out so existing tests don't make real
HTTP calls. Tests that explicitly want FRED-success behavior should
re-patch `src.data_ingestion.risk_free_rate.get_rf_rate` inside the test
body — `unittest.mock.patch` as a context manager wins over the autouse
patch on the same target.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_fred_for_scripts():
    """Force FRED to raise so tests fall back to RF_PERIOD_CONSTANT.

    Mirrors the alpaca mock pattern in tests/conftest.py — external APIs
    are mocked by default; per-test patches override when needed. This is
    a MOCK-EXTERNAL-API fixture, not a failure-suppress fixture.
    """
    with patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=KeyError("test default — no FRED in pytest"),
    ):
        yield
