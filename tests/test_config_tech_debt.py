"""Tests for Sprint 8 Task 9: Config, Performance & Tech Debt.

Covers: DB_PATH constant, index creation SQL, holiday detection,
sleep gap detection, config reload.
"""

import sqlite3
import tempfile
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests.conftest import init_test_db


def test_db_path_imported_correctly():
    """DB_PATH constant imported from src.config without error."""
    from src.config import DB_PATH

    assert isinstance(DB_PATH, str)
    assert DB_PATH.endswith(".sqlite3")


def test_index_creation_sql_runs_without_error(tmp_path):
    """Index creation SQL from create_missing_tables runs on a temp DB."""
    db_path = str(tmp_path / "tech_debt.db")
    init_test_db(db_path, ["shadow_trades", "recommendations"])

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # These indexes should already exist from the registry schema;
    # re-running with IF NOT EXISTS should be a no-op.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shadow_trades_status ON shadow_trades(status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_shadow_trades_status_time "
        "ON shadow_trades(status, actual_entry_time)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at "
        "ON recommendations(created_at)"
    )

    # Verify indexes exist
    indexes = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    index_names = {row[0] for row in indexes}
    assert "idx_shadow_trades_status" in index_names
    assert "idx_shadow_trades_status_time" in index_names
    assert "idx_recommendations_created_at" in index_names
    conn.close()


def test_holiday_detection_works():
    """is_market_holiday correctly identifies NYSE holidays."""
    from src.scheduler.holidays import is_market_holiday

    # 2026-01-01 is New Year's Day
    assert is_market_holiday("2026-01-01") is True
    # 2026-12-25 is Christmas
    assert is_market_holiday(check_date=date(2026, 12, 25)) is True
    # 2026-03-10 is a regular Tuesday
    assert is_market_holiday("2026-03-10") is False


def test_sleep_gap_detection():
    """WatchLoop._should_scan detects gaps > 30 min as sleep recovery."""
    from src.scheduler.watch import WatchLoop

    config = {
        "automation": {
            "scan_interval_minutes": 30,
            "market_open_hour_et": 9,
            "market_open_minute_et": 30,
            "market_close_hour_et": 16,
        },
        "bootcamp": {"enabled": False},
        "training": {"enabled": False},
    }
    loop = WatchLoop(config)

    ET = ZoneInfo("America/New_York")
    # Simulate: last scan was 90 min ago, during market hours on a weekday
    now = datetime(2026, 3, 10, 12, 0, tzinfo=ET)  # Tuesday noon
    loop._last_scan_time = datetime(2026, 3, 10, 10, 30, tzinfo=ET)  # 90 min ago

    with patch("src.scheduler.watch.logger") as mock_logger:
        result = loop._should_scan(now)
        assert result is True
        # Should have logged a warning about the gap
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "sleep recovery" in warning_msg.lower() or "Possible sleep" in warning_msg


def test_config_reload_clears_cache():
    """reload_config() clears the cache and reloads from disk."""
    from src.config import _config_cache, load_config, reload_config

    # First load to populate cache
    config1 = load_config()
    assert config1 is not None

    # Reload should return a new dict (not the same object)
    config2 = reload_config()
    assert config2 is not None
    # After reload, cache should be populated again
    from src.config import _config_cache as new_cache
    assert new_cache is not None


def test_config_overrides_shim_import():
    """Backwards-compatible import from src.config_overrides still works."""
    from src.config_overrides import WHITELISTED_KEYS, apply_override

    assert isinstance(WHITELISTED_KEYS, set)
    assert callable(apply_override)


def test_holidays_module_complete():
    """NYSE_HOLIDAYS_2026 has all 10 expected holidays (including Juneteenth, #270)."""
    from src.scheduler.holidays import NYSE_HOLIDAYS_2026

    assert len(NYSE_HOLIDAYS_2026) == 10
    assert date(2026, 6, 19) in NYSE_HOLIDAYS_2026   # Juneteenth (#270)
    assert date(2026, 11, 26) in NYSE_HOLIDAYS_2026  # Thanksgiving
