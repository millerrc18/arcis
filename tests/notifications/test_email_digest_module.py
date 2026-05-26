"""Tests for src/notifications/email_digest.py — the email-tier aggregator (#115 T5).

Covers the load-time invariant (EVENT_TO_TIER ⊆ EMAIL_TIER_EVENT_TYPES),
the KeyError-on-unmapped-event contract (DD-28), the 4-tuple render_digest
shape (DA-CRIT-2), shadow vs off mode dispatch (DA-CRIT-1), and the
handover_check skeleton (DA-MAJ-7).

Note on imports: email_digest performs a fail-fast subset check at module
load. We import it at the top of each test (not module top-level) so that
test (b) can re-import it after monkeypatching to trigger an ImportError.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from unittest.mock import patch

import pytest


# ── Shared fixture: in-memory sqlite connection mirroring notifications_digest_queue ──

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
    conn.execute("CREATE INDEX idx_digest_flush_status ON notifications_digest_queue (flush_status)")
    conn.execute("CREATE INDEX idx_digest_created_at ON notifications_digest_queue (created_at)")
    conn.commit()
    return conn


def _default_config():
    from src.notifications.policy import NotificationsConfig
    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=True,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
    )


# ── (a) EVENT_TO_TIER ⊆ EMAIL_TIER_EVENT_TYPES ──

def test_event_to_tier_keys_subset_of_event_map():
    """EVENT_TO_TIER's keys must all be in telegram.py's EMAIL_TIER_EVENT_TYPES."""
    from src.notifications.email_digest import EVENT_TO_TIER
    from src.notifications.telegram import EMAIL_TIER_EVENT_TYPES
    assert set(EVENT_TO_TIER.keys()).issubset(EMAIL_TIER_EVENT_TYPES), (
        f"EVENT_TO_TIER drift: keys not in EMAIL_TIER_EVENT_TYPES: "
        f"{set(EVENT_TO_TIER.keys()) - EMAIL_TIER_EVENT_TYPES}"
    )


# ── (b) module-load drift → ImportError (NOT AssertionError) ──

def test_module_load_drift_raises_importerror(monkeypatch):
    """Patch EMAIL_TIER_EVENT_TYPES to a smaller frozenset, reload email_digest;
    the module-load subset check MUST raise ImportError (DD-30 + DA-MIN-19),
    not bare AssertionError, so caller try/except (ImportError, ModuleNotFoundError)
    catches it correctly.
    """
    import sys

    # Sanity precondition: the module loads cleanly under normal state.
    sys.modules.pop("src.notifications.email_digest", None)
    importlib.import_module("src.notifications.email_digest")  # must succeed

    # Now patch the allowlist to an empty frozenset and force re-import.
    from src.notifications import telegram
    monkeypatch.setattr(telegram, "EMAIL_TIER_EVENT_TYPES", frozenset())
    sys.modules.pop("src.notifications.email_digest", None)

    with pytest.raises(ImportError) as exc_info:
        importlib.import_module("src.notifications.email_digest")
    # Must NOT be AssertionError — assertion semantics are reserved for
    # render-time failures that should crash loudly.
    assert not isinstance(exc_info.value, AssertionError)


# ── (c) unmapped event_type → KeyError (DD-28) ──

def test_enqueue_for_unmapped_event_type_raises_keyerror():
    """enqueue_for_email_digest('nonexistent', ...) raises KeyError per DD-28."""
    from src.notifications.email_digest import enqueue_for_email_digest

    conn = _make_conn()
    with pytest.raises(KeyError):
        enqueue_for_email_digest(
            "nonexistent_event",
            severity="alert",
            payload={"x": 1},
            conn=conn,
        )


# ── (d) audit_critical → preopen:critical-overflow tagged row in queue ──

def test_enqueue_routes_audit_critical_to_preopen_critical_overflow():
    """enqueue with source_tag='email:preopen:critical-overflow' writes a row
    with that source_tag (canonical for DD-34 digest replay)."""
    from src.notifications.email_digest import enqueue_for_email_digest

    conn = _make_conn()
    # Use _config injection — DigestQueue requires it.
    config = _default_config()
    row_id = enqueue_for_email_digest(
        "audit_critical",
        severity="critical",
        payload={"category": "risk", "description": "stop loss breach"},
        source_tag="email:preopen:critical-overflow",
        conn=conn,
        config=config,
    )
    assert row_id is not None and isinstance(row_id, int)
    rows = conn.execute(
        "SELECT id, event_type, severity, source_tag, flush_status "
        "FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "audit_critical"
    assert row["severity"] == "critical"
    assert row["source_tag"] == "email:preopen:critical-overflow"
    assert row["flush_status"] == "pending"


# ── (e) render_digest returns 4-tuple with overflow_ids (DA-CRIT-2) ──

def test_render_digest_returns_4_tuple_with_overflow_ids():
    """DA-CRIT-2: render_digest MUST return (subject, plain, html, overflow_ids:list)."""
    from src.notifications.email_digest import render_digest

    result = render_digest("preopen", rows=[])
    assert isinstance(result, tuple)
    assert len(result) == 4
    subject, plain, html, overflow_ids = result
    assert isinstance(subject, str)
    assert isinstance(plain, str)
    assert isinstance(html, str)
    assert isinstance(overflow_ids, list)


# ── (f) render with empty rows still returns a valid quadruple ──

def test_render_empty_tier_returns_no_op_marker():
    """Empty rows + no critical replays → still a 4-tuple with valid strings."""
    from src.notifications.email_digest import render_digest

    subject, plain, html, overflow_ids = render_digest("postclose", rows=[])
    assert subject  # non-empty
    assert plain    # non-empty
    assert html     # non-empty
    assert overflow_ids == []  # nothing to defer


# ── (g) shadow mode → _write_shadow_file used; send_email NOT called ──

def test_shadow_mode_writes_to_disk_not_email(tmp_path, monkeypatch):
    """DA-CRIT-1 hold-over: dual_write_hold_over.mode='shadow' writes the
    rendered digest to <output_dir>/<tier>-YYYY-MM-DD.html, and send_email
    is NOT invoked.
    """
    from src.notifications import email_digest

    # Build a minimal config that flush_tier can read.
    fake_config = {
        "email": {
            "tier_times": {"preopen": "07:30", "postclose": "17:00", "weekly": "Sun 18:00"},
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": True},
                "postclose": {"enabled": True, "send_when_empty": True},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "dual_write_hold_over": {
                "enabled": True,
                "mode": "shadow",
                "shadow_output_dir": str(tmp_path),
            },
            "holidays": {
                "skip_preopen_on_market_holidays": False,
                "skip_postclose_on_market_holidays": False,
            },
        }
    }

    sentinel = {"send_called": False}

    def _fake_send_email(*args, **kwargs):
        sentinel["send_called"] = True
        return True

    monkeypatch.setattr(email_digest, "load_config", lambda: fake_config, raising=False)
    monkeypatch.setattr(email_digest, "send_email", _fake_send_email, raising=False)

    conn = _make_conn()
    result = email_digest.flush_tier("preopen", conn=conn)
    # send_email NOT called in shadow mode
    assert sentinel["send_called"] is False
    # at least one shadow file should have been written
    written = list(tmp_path.glob("preopen-*.html")) + list(tmp_path.glob("preopen-*.txt"))
    assert len(written) >= 1, f"No shadow files in {tmp_path} after shadow flush"


# ── (h) off mode → send_email IS called ──

def test_off_mode_calls_send_email(tmp_path, monkeypatch):
    """dual_write_hold_over.mode='off' routes through _dispatch_tier; send_email called."""
    from src.notifications import email_digest

    fake_config = {
        "email": {
            "tier_times": {"preopen": "07:30", "postclose": "17:00", "weekly": "Sun 18:00"},
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": True},
                "postclose": {"enabled": True, "send_when_empty": True},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "dual_write_hold_over": {
                "enabled": False,
                "mode": "off",
                "shadow_output_dir": str(tmp_path),
            },
            "holidays": {
                "skip_preopen_on_market_holidays": False,
                "skip_postclose_on_market_holidays": False,
            },
        }
    }

    sentinel = {"send_called": False, "args": None}

    def _fake_send_email(subject, body, *args, **kwargs):
        sentinel["send_called"] = True
        sentinel["args"] = (subject, body, kwargs)
        return True

    monkeypatch.setattr(email_digest, "load_config", lambda: fake_config, raising=False)
    monkeypatch.setattr(email_digest, "send_email", _fake_send_email, raising=False)

    conn = _make_conn()
    email_digest.flush_tier("preopen", conn=conn)
    assert sentinel["send_called"] is True


# ── (i) handover_check returns PASS skeleton on clean data ──

def test_handover_check_returns_pass_on_clean_data():
    """Skeleton: handover_check returns {'status': 'PASS', 'tripwires': {...}}."""
    from src.notifications.email_digest import handover_check

    result = handover_check()
    assert isinstance(result, dict)
    assert result.get("status") == "PASS"
    assert "tripwires" in result
    assert isinstance(result["tripwires"], dict)
