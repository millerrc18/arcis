"""Regression-lock tests for watch-loop scheduler wiring (T7).

T7: write_heartbeat() is called during each watch-loop iteration.
"""

from unittest.mock import MagicMock, call, patch


def _make_watch_loop():
    """Return a WatchLoop instance with minimal mocked config."""
    with patch("src.scheduler.watch.load_config") as mock_cfg, \
         patch("src.scheduler.watch.is_llm_available", return_value=False), \
         patch("src.scheduler.watch.GuardedScorer"), \
         patch("src.scheduler.watch.WatchLoop._acquire_lock"):
        mock_cfg.return_value = {
            "schedule": {
                "morning_hour": 8,
                "eod_hour": 16,
                "scan_interval": 30,
                "market_open_hour": 9,
                "market_open_minute": 30,
                "market_close_hour": 16,
            },
            "risk": {"starting_capital": 100000},
            "shadow_trading": {"enabled": False},
            "training": {},
        }
        from src.scheduler.watch import WatchLoop
        return WatchLoop(mock_cfg.return_value)


def test_write_heartbeat_called_in_iteration():
    """write_heartbeat() is invoked during the watch-loop iteration heartbeat block.

    Drives one iteration of _run_sync_body's main while-loop body by patching
    _dispatch_sync to flip _shutdown_requested after the first call, then
    asserts write_heartbeat was called at least once.
    """
    loop = _make_watch_loop()

    shutdown_sentinel = [False]

    def flip_shutdown(*args, **kwargs):
        # After first call, signal shutdown so the loop exits
        loop._shutdown_requested = True

    with patch("src.scheduler.watch.Path") as mock_path_cls, \
         patch("src.notifications.platform_events.write_heartbeat") as mock_wh, \
         patch("src.scheduler.watch.signal"), \
         patch("src.scheduler.watch.WatchLoop._acquire_lock"), \
         patch("time.sleep"):

        # Path(...).mkdir / write_text are no-ops
        mock_path_cls.return_value = MagicMock()

        # Stub out all the periodic sub-tasks
        loop._dispatch_sync = MagicMock(side_effect=flip_shutdown)
        loop._print_status_heartbeat = MagicMock()
        loop._reset_daily_state = MagicMock()

        try:
            loop._run_sync_body()
        except Exception:
            pass  # Exceptions after the iteration are acceptable

    mock_wh.assert_called()
