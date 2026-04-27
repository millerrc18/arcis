"""Smoke test and regression-lock tests for src.services.recap_service."""
import logging
from unittest.mock import patch


def test_module_imports():
    """Verify module imports without error."""
    import src.services.recap_service  # noqa: F401


# ── B2.1 / #689 — shadow-data bare except-pass regression-lock ──────────────


def test_fetch_shadow_data_exception_is_logged_not_swallowed(caplog):
    """#689 — _fetch_shadow_data_for_recap must log (not silently swallow) failures.

    Before the fix the block was bare `except Exception: pass` — any ImportError,
    sqlite3.OperationalError, or runtime bug in get_shadow_data_for_recap()
    disappeared without trace, and the EOD recap email was sent without shadow
    data with no operator alert.

    After the fix (PR #690 / B2.1) the exception is routed through
    log_and_persist so it surfaces in the BrokerExceptionsPanel.  We verify
    that log_and_persist is called when get_shadow_data_for_recap raises.
    """
    from src.services.recap_service import _fetch_shadow_data_for_recap

    config = {"shadow_trading": {"enabled": True}}

    with patch(
        "src.packets.eod_recap.get_shadow_data_for_recap",
        side_effect=ImportError("eod_recap module broken"),
    ), patch(
        "src.shadow_trading.broker_exception_logger.log_and_persist"
    ) as mock_log:
        result = _fetch_shadow_data_for_recap(config)

    assert result is None, "_fetch_shadow_data_for_recap must return None on failure"
    assert mock_log.called, (
        "log_and_persist must be called when get_shadow_data_for_recap raises — "
        "bare except: pass was silently swallowing the error"
    )


def test_fetch_shadow_data_returns_none_when_disabled():
    """When shadow_trading.enabled is False, return None without calling eod_recap."""
    from src.services.recap_service import _fetch_shadow_data_for_recap

    with patch(
        "src.packets.eod_recap.get_shadow_data_for_recap"
    ) as mock_get:
        result = _fetch_shadow_data_for_recap({"shadow_trading": {"enabled": False}})

    assert result is None
    mock_get.assert_not_called()


def test_fetch_shadow_data_runtime_error_is_logged(caplog):
    """#689 — Runtime exceptions from get_shadow_data_for_recap must be persisted.

    sqlite3.OperationalError (schema drift) and arbitrary RuntimeErrors from
    the shadow data fetch must all be routed through log_and_persist.
    """
    import sqlite3 as _sqlite3

    from src.services.recap_service import _fetch_shadow_data_for_recap

    config = {"shadow_trading": {"enabled": True}}

    with patch(
        "src.packets.eod_recap.get_shadow_data_for_recap",
        side_effect=_sqlite3.OperationalError("no such table: shadow_trades"),
    ), patch(
        "src.shadow_trading.broker_exception_logger.log_and_persist"
    ) as mock_log:
        result = _fetch_shadow_data_for_recap(config)

    assert result is None
    assert mock_log.called, (
        "log_and_persist must be called for sqlite3.OperationalError — "
        "schema-drift failures were silently swallowed before the fix"
    )
