"""Hold-over exit-criteria tripwire tests for handover_check (#115 T17).

DA-MAJ-7 + DA-MAJ-11 + DA-MAJ-13. Pins the real handover_check tripwire
logic that gates PR 2 (old digest_builder retirement). PR 2 merge is
gated on this returning status='PASS'.

# COMPENSATION INVENTORY (DA-MAJ-13):
# - tests/email/test_digest_builder.py has 10 tests as of commit 1192b18d.
# - PR 1 (T17) adds 8 tests in this file + 4 in test_email_digest_holiday.py
#   = 12 new tests across both files.
# - PR 2 will delete digest_builder.py + its 10 tests.
# - Net floor delta: PR 1 +12, PR 2 -10, final +2 (>= 0 required).
# - Floor stays intact post-PR-2.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE notifications_digest_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_tag TEXT NOT NULL DEFAULT 'unknown',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            flushed_at TIMESTAMP,
            flush_status TEXT NOT NULL DEFAULT 'pending',
            flush_attempts INTEGER NOT NULL DEFAULT 0,
            flush_error TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            sent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT
        )
    """)
    conn.commit()
    return conn


def _seed_passing_baseline(conn, *, now=None):
    """Insert the rows that should make all tripwires PASS:
    - 0 abandoned rows in past 7d
    - 5 preopen + 5 postclose dispatches in past 7 weekdays
    - 1 weekly dispatch in past 7 days
    """
    if now is None:
        now = datetime.now(timezone.utc)
    # 5 preopen dispatches over past 5 weekdays
    for i in range(5):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO notifications_sent (event_type, channel, sent_at, "
            "status) VALUES (?, ?, ?, ?)",
            (f"digest_preopen_{i}", "email", ts, "ok"),
        )
    # 5 postclose dispatches
    for i in range(5):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO notifications_sent (event_type, channel, sent_at, "
            "status) VALUES (?, ?, ?, ?)",
            (f"digest_postclose_{i}", "email", ts, "ok"),
        )
    # 1 weekly
    ts = (now - timedelta(days=2)).isoformat()
    conn.execute(
        "INSERT INTO notifications_sent (event_type, channel, sent_at, "
        "status) VALUES (?, ?, ?, ?)",
        ("digest_weekly_x", "email", ts, "ok"),
    )
    conn.commit()


def _patch_handover_conn(monkeypatch, conn):
    """Patch handover_check to use the supplied connection."""
    from src.notifications import email_digest

    def _fake_connect(*a, **kw):
        return conn

    monkeypatch.setattr(
        email_digest, "_open_handover_conn", _fake_connect,
        raising=False,
    )


# ── (1) all tripwires pass ───────────────────────────────────────────────

def test_handover_check_passes_when_all_tripwires_pass(monkeypatch, tmp_path):
    """DA-MAJ-7: with a clean baseline (0 abandoned, 5 preopen, 5
    postclose, 1 weekly in past 7d), handover_check returns
    status='PASS' and all tripwires evaluate True."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "off", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    result = email_digest.handover_check()
    assert result["status"] == "PASS", (
        f"expected PASS, got {result['status']!r}; tripwires: "
        f"{result['tripwires']}"
    )
    tw = result["tripwires"]
    assert tw["abandoned_rows_under_threshold"] is True
    assert tw["preopen_flushed_5_weekdays"] is True
    assert tw["postclose_flushed_5_weekdays"] is True
    assert tw["weekly_flushed_within_window"] is True


# ── (2) fail on too many abandoned rows ───────────────────────────────────

def test_handover_check_fails_on_abandoned_rows(monkeypatch, tmp_path):
    """DA-MAJ-7: with 10+ abandoned rows in the past window, the
    abandoned-tripwire flips False and status='FAIL'."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    now = datetime.now(timezone.utc)
    # Insert 12 abandoned rows in past 7d → above the < 10 threshold
    for _ in range(12):
        ts = (now - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO notifications_digest_queue (event_type, severity, "
            "payload_json, source_tag, flush_status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("abandoned_evt", "low", "{}", "email:preopen", "abandoned", ts),
        )
    conn.commit()
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "off", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    result = email_digest.handover_check()
    assert result["status"] == "FAIL", (
        f"expected FAIL with 12 abandoned rows, got {result['status']!r}"
    )
    assert result["tripwires"]["abandoned_rows_under_threshold"] is False


# ── (3) fail when preopen flushed < 5 weekdays ────────────────────────────

def test_handover_check_fails_when_preopen_under_5_weekdays(
    monkeypatch, tmp_path,
):
    """DA-MAJ-7: with only 3 preopen dispatches in past 7 days, the
    preopen-tripwire flips False and status='FAIL'."""
    from src.notifications import email_digest

    conn = _make_conn()
    now = datetime.now(timezone.utc)
    # Only 3 preopen
    for i in range(3):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO notifications_sent (event_type, channel, sent_at, "
            "status) VALUES (?, ?, ?, ?)",
            (f"digest_preopen_{i}", "email", ts, "ok"),
        )
    # Full postclose + weekly
    for i in range(5):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO notifications_sent (event_type, channel, sent_at, "
            "status) VALUES (?, ?, ?, ?)",
            (f"digest_postclose_{i}", "email", ts, "ok"),
        )
    ts = (now - timedelta(days=2)).isoformat()
    conn.execute(
        "INSERT INTO notifications_sent (event_type, channel, sent_at, "
        "status) VALUES (?, ?, ?, ?)",
        ("digest_weekly_x", "email", ts, "ok"),
    )
    conn.commit()
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "off", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    result = email_digest.handover_check()
    assert result["status"] == "FAIL"
    assert result["tripwires"]["preopen_flushed_5_weekdays"] is False
    assert result["tripwires"]["postclose_flushed_5_weekdays"] is True


# ── (4) DA-MAJ-11 row-ID inclusion check with compare_window ──────────────

def test_compare_window_old_vs_new_rowid_inclusion(monkeypatch, tmp_path):
    """DA-MAJ-11: when compare_window='7d' is passed, handover_check
    inspects shadow files in shadow_output_dir and confirms every
    shadow_trade.id mentioned in OLD eod overnight window appears in
    the NEW postclose Mon 17:00 ET OR NEW preopen Tue 07:30 ET shadow
    file.

    For unit-test purposes we use the simpler invariant: the
    `row_id_inclusion_check` key exists in the tripwires dict (not
    None) when compare_window is supplied, AND is None when not.
    """
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    # Create matching old/new shadow files: row ID 42 appears in BOTH
    # old eod AND new postclose, so inclusion is satisfied.
    (tmp_path / "eod-2026-05-26.html").write_text(
        "shadow_trade.id=42\n", encoding="utf-8",
    )
    (tmp_path / "postclose-2026-05-26.html").write_text(
        "shadow_trade.id=42\n", encoding="utf-8",
    )

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "shadow", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    # WITHOUT compare_window → row_id_inclusion_check is None
    r_no_compare = email_digest.handover_check()
    assert r_no_compare["tripwires"].get("row_id_inclusion_check") is None, (
        f"row_id_inclusion_check MUST be None when compare_window not given, "
        f"got {r_no_compare['tripwires'].get('row_id_inclusion_check')!r}"
    )

    # WITH compare_window='7d' → row_id_inclusion_check is True (or False).
    r_compare = email_digest.handover_check(compare_window="7d")
    assert r_compare["tripwires"].get("row_id_inclusion_check") is True, (
        f"DA-MAJ-11: matching shadow_trade.id=42 in both old eod and new "
        f"postclose should yield row_id_inclusion_check=True, got "
        f"{r_compare['tripwires'].get('row_id_inclusion_check')!r}"
    )


# ── (5) compare_window with missing row → False ──────────────────────────

def test_compare_window_detects_missing_row_id(monkeypatch, tmp_path):
    """DA-MAJ-11: a shadow_trade.id present in OLD eod but absent from
    BOTH new postclose AND new preopen → row_id_inclusion_check=False
    AND status='FAIL'."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    # ID 99 in OLD eod but NEITHER new postclose NOR new preopen.
    (tmp_path / "eod-2026-05-26.html").write_text(
        "shadow_trade.id=99\n", encoding="utf-8",
    )
    (tmp_path / "postclose-2026-05-26.html").write_text("(no ids)\n", encoding="utf-8")
    (tmp_path / "preopen-2026-05-27.html").write_text("(no ids)\n", encoding="utf-8")

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "shadow", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    r = email_digest.handover_check(compare_window="7d")
    assert r["tripwires"]["row_id_inclusion_check"] is False
    assert r["status"] == "FAIL"


# ── (6) shadow_files_present tripwire ────────────────────────────────────

def test_handover_check_shadow_files_present_when_shadow_mode(
    monkeypatch, tmp_path,
):
    """DA-MAJ-7: when mode='shadow', shadow_files_present tripwire must
    be set. True if at least one shadow file exists in the directory;
    False if directory is empty."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "shadow", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    # Case A: empty dir → False
    r_empty = email_digest.handover_check()
    assert r_empty["tripwires"]["shadow_files_present"] is False

    # Case B: with a shadow file → True
    (tmp_path / "preopen-2026-05-26.html").write_text("x", encoding="utf-8")
    r_present = email_digest.handover_check()
    assert r_present["tripwires"]["shadow_files_present"] is True


# ── (7) shadow_files_present check skipped when not shadow mode ─────────

def test_handover_check_shadow_files_skipped_when_not_shadow_mode(
    monkeypatch, tmp_path,
):
    """When mode != 'shadow', the shadow_files_present tripwire is skipped
    (set to True / N/A so it doesn't gate). The check is only meaningful
    in shadow mode."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "off", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    r = email_digest.handover_check()
    # mode='off' + nothing in shadow dir → still PASS (shadow check skipped).
    assert r["tripwires"]["shadow_files_present"] is True, (
        "shadow_files_present should be True (skipped) when mode != 'shadow'"
    )
    assert r["status"] == "PASS"


# ── (8) details dict contains per-tripwire detail strings ────────────────

def test_handover_check_details_contains_per_tripwire_strings(
    monkeypatch, tmp_path,
):
    """handover_check returns a 'details' dict with diagnostic strings
    explaining each tripwire's outcome — used by the CLI to print
    per-tripwire status lines on PASS or FAIL."""
    from src.notifications import email_digest

    conn = _make_conn()
    _seed_passing_baseline(conn)
    _patch_handover_conn(monkeypatch, conn)

    fake_cfg = {
        "email": {
            "dual_write_hold_over": {
                "mode": "off", "shadow_output_dir": str(tmp_path),
            }
        }
    }
    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_cfg, raising=False,
    )

    r = email_digest.handover_check()
    assert "details" in r
    details = r["details"]
    for k in (
        "abandoned_rows_under_threshold",
        "preopen_flushed_5_weekdays",
        "postclose_flushed_5_weekdays",
        "weekly_flushed_within_window",
    ):
        assert k in details, f"missing detail for {k}"
        assert isinstance(details[k], str)
