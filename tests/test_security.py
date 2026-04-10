"""Tests for security hardening fixes."""
from unittest.mock import patch, MagicMock


def test_local_api_binds_to_loopback():
    """Fix #348: local API must bind to 127.0.0.1, not 0.0.0.0."""
    with patch("uvicorn.run") as mock_run:
        from src.cli.commands import cmd_dashboard
        args = MagicMock()
        args.port = 8000
        try:
            cmd_dashboard(args)
        except SystemExit:
            pass
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        if call_kwargs.kwargs.get("host"):
            assert call_kwargs.kwargs["host"] == "127.0.0.1", \
                f"Local API must bind to 127.0.0.1, got {call_kwargs.kwargs['host']}"
        else:
            assert "0.0.0.0" not in str(call_kwargs), "Local API must not bind to 0.0.0.0"


def test_cloud_api_rejects_requests_without_secret():
    """Fix #349: cloud API must reject all requests when API_SECRET is empty."""
    import pytest
    with patch("src.api.cloud_app.API_SECRET", ""):
        from src.api.cloud_app import verify_auth
        with pytest.raises(RuntimeError, match="API_SECRET"):
            verify_auth(credentials=None)
