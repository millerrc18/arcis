"""Assert that _fetch_dtb3_observations uses a 5-second timeout on FRED HTTP calls.

Performance fix-up for sp5-wave-c-54: the T1 wire-up activates the FRED rf-rate
path per /api/kpis request. A 15-second blocking timeout is unacceptable on a
dashboard endpoint; 5 seconds is safe because the fallback to RF_PERIOD_CONSTANT
in src/methods/_rf_vector.py:90-98 is graceful.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch


def test_fred_request_uses_timeout_5() -> None:
    """requests.get must be called with timeout=5."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "observations": [{"value": "4.20", "date": "2024-01-02"}]
    }

    with patch("src.data_ingestion.risk_free_rate.requests") as mock_requests:
        mock_requests.get.return_value = mock_response

        from src.data_ingestion import risk_free_rate
        risk_free_rate._cache_clear()
        risk_free_rate._fetch_dtb3_observations("test-key", dt.date(2024, 1, 2))

        call_kwargs = mock_requests.get.call_args
        assert call_kwargs is not None, "requests.get was not called"
        timeout_val = call_kwargs.kwargs.get("timeout", call_kwargs[1].get("timeout") if len(call_kwargs) > 1 else None)
        assert timeout_val == 5, (
            f"Expected timeout=5 but got timeout={timeout_val}. "
            "A 15-second blocking FRED call is unacceptable on a dashboard endpoint."
        )
