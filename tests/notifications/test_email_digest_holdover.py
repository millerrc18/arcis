"""Hold-over mode tests for email_digest dual-write (#115 T16).

DD-20 revised: ``email.dual_write_hold_over.mode`` is one of:
  - 'shadow'       — new flush_tier writes shadow files to disk; OLD
                     digest_builder paths CONTINUE to fire send_email
                     (operator inbox UNCHANGED). DA-CRIT-1 critical default.
  - 'time_aligned' — new flush_tier sends real email; OLD midday + evening
                     SUPPRESSED; OLD premarket + EOD still fire (aligned
                     wall-clock with new preopen/postclose).
  - 'off'          — new flush_tier sends real email; OLD branches FULLY
                     suppressed.

This file pins the holdover-mode-per-mode behavior at the boundary between
flush_tier and the scheduler's legacy digest_builder branches.

Aggregator-failure tests (DA-MAJ-10 / DA-MIN-19) confirm that callers
correctly classify ImportError (caught + critical log + fallback) vs
AssertionError (NOT swallowed — bubbles up loudly).
"""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


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
    conn.commit()
    return conn


def _make_watch_loop(*, holdover_mode: str):
    """WatchLoop scaffolded for hold-over mode-specific tests.

    Mirrors tests/scheduler/test_watch_email_digest_schedule.py::_make_watch_loop
    but takes only the holdover mode as the variable input.
    """
    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._hourly_alert_sent = False
    wl.email_mode = "digest"

    wl.config = {
        "email": {
            "tier_times": {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": False},
                "postclose": {"enabled": True, "send_when_empty": False},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "holidays": {
                "skip_preopen_on_market_holidays": True,
                "skip_postclose_on_market_holidays": True,
            },
            "dual_write_hold_over": {
                "enabled": True,
                "mode": holdover_mode,
                "shadow_output_dir": "tmp/digest-shadow",
            },
            "digest_times": {
                "premarket": "07:30",
                "midday": "12:00",
                "eod": "16:15",
                "evening": "20:00",
            },
        },
    }

    wl._digest_preopen_done = False
    wl._digest_postclose_done = False
    wl._digest_weekly_done = False
    wl._digest_premarket_done = False
    wl._digest_midday_done = False
    wl._digest_eod_done = False
    wl._digest_evening_done = False

    wl._clock = lambda: datetime.now(ET)
    return wl


def _flush_tier_config(tmp_path, *, mode: str, send_when_empty: bool = True) -> dict:
    """Build the minimal config that flush_tier reads from load_config()."""
    return {
        "email": {
            "tier_times": {
                "preopen": "07:30", "postclose": "17:00", "weekly": "Sun 18:00",
            },
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": send_when_empty},
                "postclose": {"enabled": True, "send_when_empty": send_when_empty},
                "weekly": {"enabled": True, "send_when_empty": send_when_empty},
            },
            "dual_write_hold_over": {
                "enabled": True,
                "mode": mode,
                "shadow_output_dir": str(tmp_path),
            },
            "holidays": {
                "skip_preopen_on_market_holidays": False,
                "skip_postclose_on_market_holidays": False,
            },
        }
    }


# ── (1) DA-CRIT-1: shadow mode writes to disk, not email ────────────────

def test_holdover_shadow_mode_writes_to_disk_not_email(tmp_path, monkeypatch):
    """DA-CRIT-1: In mode='shadow', flush_tier MUST write the rendered
    digest to <shadow_output_dir>/<tier>-YYYY-MM-DD.{html,txt} and MUST NOT
    invoke send_email from inside flush_tier.
    """
    from src.notifications import email_digest

    fake_config = _flush_tier_config(tmp_path, mode="shadow")
    sentinel = {"send_called": 0}

    def _fake_send_email(*args, **kwargs):
        sentinel["send_called"] += 1
        return True

    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_config, raising=False,
    )
    monkeypatch.setattr(
        email_digest, "send_email", _fake_send_email, raising=False,
    )

    conn = _make_conn()
    email_digest.flush_tier("preopen", conn=conn)

    # send_email NOT called from inside flush_tier
    assert sentinel["send_called"] == 0, (
        f"DA-CRIT-1 violated: flush_tier called send_email "
        f"{sentinel['send_called']} time(s) in shadow mode"
    )

    # Shadow file(s) written to disk
    written = (
        list(tmp_path.glob("preopen-*.html"))
        + list(tmp_path.glob("preopen-*.txt"))
    )
    assert len(written) >= 1, (
        f"No shadow files written to {tmp_path} in shadow mode"
    )


# ── (2) DA-CRIT-1: shadow mode does NOT increase inbox count ─────────────

def test_holdover_shadow_mode_does_not_increase_inbox_count(tmp_path, monkeypatch):
    """DA-CRIT-1: Across all three tiers (preopen, postclose, weekly) the
    inbox count (send_email call count from flush_tier) MUST be 0 in
    shadow mode. The old digest_builder paths (which DO email in shadow
    mode) are not in scope here — the test pins the new aggregator
    boundary only.
    """
    from src.notifications import email_digest

    fake_config = _flush_tier_config(tmp_path, mode="shadow")
    send_count = {"n": 0}

    def _fake_send_email(*args, **kwargs):
        send_count["n"] += 1
        return True

    monkeypatch.setattr(
        email_digest, "load_config", lambda: fake_config, raising=False,
    )
    monkeypatch.setattr(
        email_digest, "send_email", _fake_send_email, raising=False,
    )

    conn = _make_conn()
    for tier in ("preopen", "postclose", "weekly"):
        email_digest.flush_tier(tier, conn=conn)

    assert send_count["n"] == 0, (
        f"DA-CRIT-1: flush_tier increased inbox count by {send_count['n']} "
        f"in shadow mode — operator inbox MUST stay unchanged"
    )


# ── (3) time_aligned mode suppresses OLD midday + evening ────────────────

def test_holdover_time_aligned_mode_suppresses_midday_and_evening():
    """DD-20 revised: In mode='time_aligned', the OLD digest_builder midday
    (12:00) and evening (20:00) branches MUST be suppressed. They sit
    OUTSIDE the wall-clock alignment of the new preopen/postclose tiers,
    so the operator inbox shrinks by 2 emails/weekday.
    """
    # Midday window
    wl_mid = _make_watch_loop(holdover_mode="time_aligned")
    wl_mid._clock = lambda: datetime(2026, 5, 26, 12, 1, tzinfo=ET)
    with patch("src.notifications.email_digest.flush_tier"), \
         patch("src.email.notifier.send_email") as mock_send_mid, \
         patch(
             "src.email.digest_builder.build_midday_digest",
             return_value=("subj", "body"),
         ), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl_mid._check_digest_schedule()
    assert not mock_send_mid.called, (
        "OLD midday send_email fired despite mode='time_aligned' "
        "(DD-20 revised — midday MUST be suppressed)"
    )

    # Evening window
    wl_eve = _make_watch_loop(holdover_mode="time_aligned")
    wl_eve._clock = lambda: datetime(2026, 5, 26, 20, 1, tzinfo=ET)
    with patch("src.notifications.email_digest.flush_tier"), \
         patch("src.email.notifier.send_email") as mock_send_eve, \
         patch(
             "src.email.digest_builder.build_evening_digest",
             return_value=("subj", "body"),
         ), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl_eve._check_digest_schedule()
    assert not mock_send_eve.called, (
        "OLD evening send_email fired despite mode='time_aligned' "
        "(DD-20 revised — evening MUST be suppressed)"
    )


# ── (4) off mode → only new path fires ───────────────────────────────────

def test_holdover_off_mode_only_new_path_fires():
    """DD-20 revised: In mode='off', the new flush_tier path fires (real
    send_email inside it) and ALL legacy digest_builder branches are
    suppressed. We test by exercising the 07:30 window — the new path
    fires (flush_tier called), and the OLD path's send_email (which
    would render build_premarket_digest) does NOT.
    """
    wl = _make_watch_loop(holdover_mode="off")
    wl._clock = lambda: datetime(2026, 5, 26, 7, 32, tzinfo=ET)

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch(
             "src.email.digest_builder.build_premarket_digest",
             return_value=("subj", "body"),
         ), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert preopen_calls, (
        f"flush_tier('preopen') did NOT fire in mode='off'. Calls: "
        f"{mock_flush.call_args_list}"
    )

    assert not mock_send.called, (
        "OLD digest_builder send_email fired in mode='off' — DD-20 revised "
        "requires OLD branches FULLY suppressed in off mode"
    )


# ── (5) Legacy old_path_enabled flag maps to mode (config-level) ─────────

def test_old_path_enabled_legacy_flag_maps_to_mode(tmp_path, monkeypatch):
    """The legacy boolean ``old_path_enabled`` MUST be mapped to the new
    ``mode`` field by load_config when ``mode`` is absent:
      - old_path_enabled=True  → mode='shadow'  (operator inbox unchanged)
      - old_path_enabled=False → mode='off'     (new path only)

    Per src/config/__init__.py:278-290.
    """
    import yaml

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setenv("ARCIS_CONFIG_DIR", str(cfg_dir))

    import src.config as cfg_mod
    cfg_mod._config_cache = None
    cfg_mod._old_path_enabled_warning_emitted = False

    # Case 1: old_path_enabled=True → mode='shadow'
    (cfg_dir / "settings.local.yaml").write_text(
        yaml.safe_dump({
            "email": {"dual_write_hold_over": {"old_path_enabled": True}},
        }),
        encoding="utf-8",
    )
    cfg = cfg_mod.reload_config()
    assert cfg["email"]["dual_write_hold_over"]["mode"] == "shadow", (
        f"old_path_enabled=True must map to mode='shadow', got "
        f"{cfg['email']['dual_write_hold_over']['mode']!r}"
    )

    # Reset sentinel for case 2.
    cfg_mod._old_path_enabled_warning_emitted = False

    # Case 2: old_path_enabled=False → mode='off'
    (cfg_dir / "settings.local.yaml").write_text(
        yaml.safe_dump({
            "email": {"dual_write_hold_over": {"old_path_enabled": False}},
        }),
        encoding="utf-8",
    )
    cfg = cfg_mod.reload_config()
    assert cfg["email"]["dual_write_hold_over"]["mode"] == "off", (
        f"old_path_enabled=False must map to mode='off', got "
        f"{cfg['email']['dual_write_hold_over']['mode']!r}"
    )

    # Cleanup
    cfg_mod._config_cache = None


# ── (6) DA-MAJ-10: aggregator ImportError → fallback + critical log ──────

def test_aggregator_importerror_falls_back_with_critical_log(caplog):
    """DA-MAJ-10 / DD-30 revised: When the aggregator's ImportError fires
    inside a caller (e.g., recap_service), the caller MUST:
      (1) catch (ImportError, ModuleNotFoundError),
      (2) log a CRITICAL-level message,
      (3) fall back to direct send_email.

    Pattern verified at src/services/recap_service.py:27-39.
    """
    import sys

    caplog.set_level(logging.CRITICAL, logger="src.services.recap_service")

    # Force enqueue_for_email_digest to raise ImportError when imported
    # inside the caller's try/except (simulates module-load drift).
    import src.notifications.email_digest as ed

    def _raise_import_error(*args, **kwargs):
        raise ImportError("simulated module-load drift")

    with patch.object(ed, "enqueue_for_email_digest", _raise_import_error), \
         patch("src.email.notifier.send_email") as mock_send_email:
        from src.services.recap_service import _route_email_or_enqueue
        _route_email_or_enqueue(
            event_type="eod_recap_email",
            subject="[TEST] Recap",
            body="<body>",
            source_tag="email:postclose",
            via_cli=False,
            send_email_flag=False,
        )

    # send_email was invoked as the fallback (after ImportError caught)
    assert mock_send_email.called, (
        "recap_service did NOT fall back to send_email after aggregator "
        "ImportError — DA-MAJ-10 contract violated"
    )

    # A CRITICAL-level log was emitted (the call site uses logger.critical)
    critical_records = [
        r for r in caplog.records
        if r.levelno == logging.CRITICAL and "email_digest" in r.message
    ]
    assert critical_records, (
        f"expected CRITICAL log mentioning 'email_digest' on ImportError "
        f"fallback path; got records: "
        f"{[(r.levelname, r.message) for r in caplog.records]}"
    )


# ── (7) DA-MIN-19: AssertionError is NOT swallowed ───────────────────────

def test_aggregator_assertionerror_is_not_swallowed():
    """DA-MIN-19 / DD-30 revised: AssertionError raised by the aggregator
    (e.g., a render-time invariant) MUST propagate out of the caller's
    try/except. Callers explicitly catch only (ImportError,
    ModuleNotFoundError) — AssertionError should NOT be silenced.

    Per src/services/recap_service.py:32 (`except (ImportError,
    ModuleNotFoundError) as err:`).
    """
    import src.notifications.email_digest as ed

    def _raise_assertion_error(*args, **kwargs):
        raise AssertionError("simulated render-time invariant failure")

    with patch.object(ed, "enqueue_for_email_digest", _raise_assertion_error), \
         patch("src.email.notifier.send_email") as mock_send_email:
        from src.services.recap_service import _route_email_or_enqueue
        with pytest.raises(AssertionError, match="render-time invariant"):
            _route_email_or_enqueue(
                event_type="eod_recap_email",
                subject="[TEST] Recap",
                body="<body>",
                source_tag="email:postclose",
                via_cli=False,
                send_email_flag=False,
            )

    # AssertionError must propagate — send_email MUST NOT have been the
    # fallback (because the AssertionError was not caught).
    assert not mock_send_email.called, (
        "send_email fallback fired despite AssertionError — DA-MIN-19 "
        "violated: AssertionError MUST surface, not be swallowed as a "
        "drift fallback"
    )
