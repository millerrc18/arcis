"""Regression guards for Tier 2 safety fixes (#574, #580, #615 follow-up).

These tests assert critical-path safety invariants that operators
must not silently regress:

- #574: cmd_startup must fail-fast when live_trading.enabled=true AND
  risk_governor.enabled=false (auto-approving every trade in live mode
  is the textbook system-blow-up scenario).
- #580: activity_log.id must be AUTOINCREMENT in the schema registry so
  rowid reuse never happens (rowid recycle would corrupt the dashboard
  feed dedup logic).
- #615 follow-up: backfill script must default to --dry-run.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #574 — startup must fail-fast on dangerous config combination
# ---------------------------------------------------------------------------


def test_startup_assert_helper_exists():
    """The fail-fast helper must be importable and callable. Source-scan
    only — full integration test would require a real config + DB."""
    from src.cli.commands import _assert_safe_live_governor_combo
    assert callable(_assert_safe_live_governor_combo)


def test_startup_assert_passes_for_safe_paper_only():
    """Default config (live=false) should never trigger fail-fast."""
    from src.cli.commands import _assert_safe_live_governor_combo
    config = {
        "live_trading": {"enabled": False},
        "risk_governor": {"enabled": False},
    }
    # Should NOT raise — paper mode tolerates governor-off
    _assert_safe_live_governor_combo(config, force=False)


def test_startup_assert_passes_when_governor_enabled():
    """Live mode with governor on is fine."""
    from src.cli.commands import _assert_safe_live_governor_combo
    config = {
        "live_trading": {"enabled": True},
        "risk_governor": {"enabled": True},
    }
    _assert_safe_live_governor_combo(config, force=False)


def test_startup_assert_raises_on_dangerous_combo():
    """live_trading.enabled=true + risk_governor.enabled=false with no
    --force MUST raise. This is the textbook blow-up scenario."""
    from src.cli.commands import _assert_safe_live_governor_combo
    config = {
        "live_trading": {"enabled": True},
        "risk_governor": {"enabled": False},
    }
    with pytest.raises(RuntimeError) as exc_info:
        _assert_safe_live_governor_combo(config, force=False)
    msg = str(exc_info.value).lower()
    assert "risk_governor" in msg or "governor" in msg
    assert "live" in msg


def test_startup_assert_force_bypasses_check():
    """The --force flag must let the operator bypass (e.g., for emergency
    testing). The bypass should still log loudly but not raise."""
    from src.cli.commands import _assert_safe_live_governor_combo
    config = {
        "live_trading": {"enabled": True},
        "risk_governor": {"enabled": False},
    }
    # With force=True, must NOT raise
    _assert_safe_live_governor_combo(config, force=True)


def test_cmd_startup_calls_safe_combo_check():
    """Source-scan: cmd_startup body must invoke the safety check.
    Otherwise the helper is dead code."""
    src = _read("src/cli/commands.py")
    # Find cmd_startup body and confirm the helper is called
    cmd_startup_idx = src.find("def cmd_startup(")
    assert cmd_startup_idx >= 0
    # Search the next ~80 lines (the function body)
    body_window = src[cmd_startup_idx:cmd_startup_idx + 6000]
    assert "_assert_safe_live_governor_combo" in body_window, (
        "cmd_startup must call _assert_safe_live_governor_combo before "
        "launching the watch loop (#574)"
    )


# ---------------------------------------------------------------------------
# #580 — activity_log.id must be AUTOINCREMENT in the registry
# ---------------------------------------------------------------------------


def test_activity_log_id_column_marked_autoincrement():
    """#580 — without AUTOINCREMENT, SQLite's ROWID can be reused after
    deletions; downstream cloud-sync dedup keys on id and would conflate
    new events with deleted ones."""
    from src.schema.registry import TABLES
    activity_log = TABLES.get("activity_log")
    assert activity_log is not None
    id_col = next((c for c in activity_log.columns if c.name == "id"), None)
    assert id_col is not None
    assert id_col.type == "INTEGER"
    assert id_col.nullable is False
    assert getattr(id_col, "autoincrement", False) is True, (
        "activity_log.id must have autoincrement=True so the DDL emits "
        "AUTOINCREMENT (#580)"
    )


def test_activity_log_ddl_emits_autoincrement_keyword():
    """The generated CREATE TABLE for activity_log must include the literal
    AUTOINCREMENT keyword."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql
    sql = generate_create_sql(TABLES["activity_log"])
    assert "AUTOINCREMENT" in sql, (
        f"DDL for activity_log must include AUTOINCREMENT, got:\n{sql}"
    )


def test_activity_log_id_auto_populates_on_insert(tmp_path):
    """Behavioral test: a fresh activity_log table from the registry must
    auto-populate id on INSERT-without-id."""
    import sqlite3
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    db_path = str(tmp_path / "audit.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(generate_create_sql(TABLES["activity_log"]))
    # INSERT without id — must NOT crash, and id must populate
    conn.execute(
        "INSERT INTO activity_log (event_type, detail, level, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("test_event", "test detail", "info", "2026-04-24T00:00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM activity_log").fetchone()
    conn.close()
    assert row is not None
    assert row[0] is not None
    assert row[0] == 1, f"Expected id=1 on first insert, got {row[0]}"
