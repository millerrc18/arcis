"""Regression-lock for v0.36.37 — F-20: FRED/macro failures must be visible.

`macro.py` logged all FRED fetch/parse failures at `logger.debug` (lines 100,
111, 137, 155). Production runs at INFO/WARNING, so a FRED outage produced
ZERO operator-visible signal — macro enrichment silently returned None, LLM
packets degraded, and nobody knew (12-hour silent-degradation class, sibling of
the v0.36.23 macro outage). Fix: promote these error paths to WARNING.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.data_enrichment.macro import _fetch_cpi_yoy, _fetch_series

_LOGGER = "src.data_enrichment.macro"


def test_fetch_series_retry_exhausted_logs_warning(caplog):
    with patch("src.data_enrichment.macro.retry_with_backoff", return_value=None), \
         caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _fetch_series("DGS10", "key")
    assert result is None
    assert any(r.levelno >= logging.WARNING and "DGS10" in r.getMessage()
               for r in caplog.records), "retry-exhausted FRED fetch must WARN"


def test_fetch_series_parse_error_logs_warning(caplog):
    bad = MagicMock()
    bad.raise_for_status.side_effect = Exception("HTTP 500")
    with patch("src.data_enrichment.macro.retry_with_backoff", return_value=bad), \
         caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _fetch_series("T10Y2Y", "key")
    assert result is None
    assert any(r.levelno >= logging.WARNING and "T10Y2Y" in r.getMessage()
               for r in caplog.records), "FRED parse error must WARN"


def test_cpi_yoy_retry_exhausted_logs_warning(caplog):
    with patch("src.data_enrichment.macro.retry_with_backoff", return_value=None), \
         caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _fetch_cpi_yoy("key")
    assert result is None
    assert any(r.levelno >= logging.WARNING and "CPI" in r.getMessage()
               for r in caplog.records), "CPI YoY retry-exhausted must WARN"


def test_cpi_yoy_parse_error_logs_warning(caplog):
    bad = MagicMock()
    bad.raise_for_status.side_effect = Exception("HTTP 500")
    with patch("src.data_enrichment.macro.retry_with_backoff", return_value=bad), \
         caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _fetch_cpi_yoy("key")
    assert result is None
    assert any(r.levelno >= logging.WARNING and "CPI" in r.getMessage()
               for r in caplog.records), "CPI YoY parse error must WARN"
