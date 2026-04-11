"""Tests for IB activation validation and stability tracking.

Covers:
1. validate_ib_gateway.py refuses live port 4001
2. daily_ib_health table registered in schema registry
3. daily_ib_health table created in SQLite by create_all_tables
4. IB digest section skipped when shadow_mode and paper_routing are off
5. IB digest section enabled when shadow_mode is on
"""

import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest


def test_validate_refuses_live_port():
    """validate_ib_gateway.py must refuse port 4001."""
    result = subprocess.run(
        [sys.executable, "scripts/validate_ib_gateway.py", "--port", "4001"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "LIVE" in result.stdout or "LIVE" in result.stderr


def test_daily_ib_health_table_in_registry():
    """daily_ib_health table must be registered in schema."""
    from src.schema.registry import TABLES
    assert "daily_ib_health" in TABLES
    table = TABLES["daily_ib_health"]
    col_names = [c.name for c in table.columns]
    assert "date" in col_names
    assert "uptime_pct" in col_names
    assert "trade_count" in col_names
    assert "error_count" in col_names
    assert "reconnect_count" in col_names
    assert table.primary_key == "date"


def test_daily_ib_health_table_created(tmp_path):
    """daily_ib_health table created by create_all_tables."""
    from src.schema.sqlite import create_all_tables
    db_path = str(tmp_path / "test.db")
    create_all_tables(db_path)
    conn = sqlite3.connect(db_path)
    # Verify table exists and accepts inserts
    conn.execute(
        "INSERT INTO daily_ib_health (date, uptime_pct, trade_count) VALUES (?, ?, ?)",
        ("2026-04-11", 98.5, 3),
    )
    row = conn.execute("SELECT * FROM daily_ib_health WHERE date = '2026-04-11'").fetchone()
    assert row is not None
    conn.close()


def test_ib_digest_section_skipped_when_disabled():
    """IB digest section not included when shadow_mode and paper_routing are off."""
    from src.email.digest_builder import _ib_enabled
    with patch("src.email.digest_builder.load_config", return_value={"live_trading": {}}):
        assert _ib_enabled() is False


def test_ib_digest_section_enabled_when_shadow_mode():
    """IB digest section included when shadow_mode is true."""
    from src.email.digest_builder import _ib_enabled
    config = {"live_trading": {"ib": {"shadow_mode": True}}}
    with patch("src.email.digest_builder.load_config", return_value=config):
        assert _ib_enabled() is True
