"""Truth-table tests for src/notifications/policy.py (T10 Sprint 5 Wave D D1).

14 truth-table tests + validation tests.
"""

import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _make_config(
    default_routing=None,
    digest_low=True,
    quiet_hours_start="22:00",
    quiet_hours_end="06:00",
    quiet_digest=True,
    mute_event_types=None,
    routing_overrides=None,
    cadence_minutes_per_event_type=None,
    retry_attempts=3,
    retry_backoff_seconds=None,
):
    from src.notifications.policy import NotificationsConfig
    if default_routing is None:
        default_routing = {"telegram": True, "email": False}
    if mute_event_types is None:
        mute_event_types = []
    if routing_overrides is None:
        routing_overrides = {}
    if cadence_minutes_per_event_type is None:
        cadence_minutes_per_event_type = {}
    if retry_backoff_seconds is None:
        retry_backoff_seconds = [1, 5, 15]
    return NotificationsConfig(
        default_routing=default_routing,
        digest_low=digest_low,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        quiet_digest=quiet_digest,
        mute_event_types=mute_event_types,
        routing_overrides=routing_overrides,
        cadence_minutes_per_event_type=cadence_minutes_per_event_type,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def _dt(hour, minute=0):
    return datetime(2026, 5, 12, hour, minute, tzinfo=ET)


# ── Severity bypass (4 explicit Decision-20 lockdown cases) ──────────────────

def test_high_severity_sends_regardless_of_quiet_hours():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    # now = 23:00 — inside quiet window
    result = should_dispatch("system_event", "high", _dt(23, 0), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 1
    assert result.reason == "high_severity_bypass"


def test_critical_severity_sends_regardless_of_mute_list():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(mute_event_types=["system_event"])
    result = should_dispatch("system_event", "critical", _dt(14, 0), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 1
    assert result.reason == "high_severity_bypass"


def test_high_severity_sends_regardless_of_digest_low():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(digest_low=True)
    result = should_dispatch("system_event", "high", _dt(14, 0), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 1
    assert result.reason == "high_severity_bypass"


def test_critical_severity_sends_regardless_of_quiet_digest():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=True)
    # now = 23:30 — inside quiet window
    result = should_dispatch("system_event", "critical", _dt(23, 30), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 1
    assert result.reason == "high_severity_bypass"


# ── Mute list ────────────────────────────────────────────────────────────────

def test_event_type_in_mute_list_returns_mute():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(mute_event_types=["scan_complete"], quiet_hours_start="22:00", quiet_hours_end="06:00")
    # Midday — not quiet hours
    result = should_dispatch("scan_complete", "medium", _dt(14, 0), cfg)
    assert result.verdict == "mute"
    assert result.matched_rule == 2
    assert result.reason == "event_type_muted"
    assert result.channels == []


# ── Quiet hours ──────────────────────────────────────────────────────────────

def test_quiet_hours_normal_window_returns_digest():
    """Normal (non-cross-midnight) quiet window: start=12:00, end=13:00."""
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="12:00", quiet_hours_end="13:00", quiet_digest=True)
    # now=12:30 → inside quiet hours → quiet_digest=True → DIGEST
    result = should_dispatch("system_event", "medium", _dt(12, 30), cfg)
    assert result.verdict == "digest"
    assert result.matched_rule == 3
    assert result.reason == "quiet_hours_digest"


def test_quiet_hours_cross_midnight_returns_mute():
    """Cross-midnight quiet window: start=22:00, end=06:00; now=02:00 → inside."""
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", quiet_digest=False)
    result = should_dispatch("system_event", "medium", _dt(2, 0), cfg)
    assert result.verdict == "mute"
    assert result.matched_rule == 3
    assert result.reason == "quiet_hours_mute"
    assert result.channels == []


def test_quiet_hours_disabled_when_start_equals_end():
    """start == end → quiet hours disabled → falls through to default routing."""
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="22:00", digest_low=False)
    # 22:30 would be "in" quiet hours if enabled, but it's disabled
    result = should_dispatch("system_event", "medium", _dt(22, 30), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 5
    assert result.reason == "default_routing"


def test_quiet_hours_outside_window_returns_default_routing():
    """now=12:00, cross-midnight window 22:00-06:00 → outside → fallthrough."""
    from src.notifications.policy import should_dispatch
    cfg = _make_config(quiet_hours_start="22:00", quiet_hours_end="06:00", digest_low=False)
    result = should_dispatch("system_event", "medium", _dt(12, 0), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 5
    assert result.reason == "default_routing"


# ── Low-severity digest ──────────────────────────────────────────────────────

def test_low_severity_with_digest_low_true_returns_digest():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(digest_low=True, quiet_hours_start="22:00", quiet_hours_end="06:00")
    # Midday — not in quiet hours
    result = should_dispatch("system_event", "low", _dt(14, 0), cfg)
    assert result.verdict == "digest"
    assert result.matched_rule == 4
    assert result.reason == "low_severity_digest"


def test_low_severity_with_digest_low_false_returns_send():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(digest_low=False, quiet_hours_start="22:00", quiet_hours_end="06:00")
    result = should_dispatch("system_event", "low", _dt(14, 0), cfg)
    assert result.verdict == "send"
    assert result.matched_rule == 5
    assert result.reason == "default_routing"


# ── Channel resolution ───────────────────────────────────────────────────────

def test_default_routing_resolves_to_telegram_only():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(
        default_routing={"telegram": True, "email": False},
        digest_low=False,
    )
    result = should_dispatch("system_event", "medium", _dt(14, 0), cfg)
    assert result.verdict == "send"
    assert result.channels == ["telegram"]


def test_routing_overrides_event_type_specific():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(
        default_routing={"telegram": True, "email": False},
        routing_overrides={"manual_intervention_drift": {"telegram": True, "email": True}},
        digest_low=False,
    )
    result = should_dispatch("manual_intervention_drift", "medium", _dt(14, 0), cfg)
    assert result.verdict == "send"
    assert "telegram" in result.channels
    assert "email" in result.channels


def test_no_channels_when_verdict_is_mute():
    from src.notifications.policy import should_dispatch
    cfg = _make_config(mute_event_types=["scan_complete"])
    result = should_dispatch("scan_complete", "medium", _dt(14, 0), cfg)
    assert result.verdict == "mute"
    assert result.channels == []


# ── Config validation tests ───────────────────────────────────────────────────

def test_load_notifications_config_valid(tmp_path):
    """Happy-path: valid config loads without error."""
    import yaml
    from src.notifications.telegram import _load_notifications_config
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {
                "manual_intervention_drift": {
                    "telegram": True,
                    "email": True,
                    "escalation_after_attempts": 3,
                }
            },
            "cadence_minutes_per_event_type": {
                "manual_intervention_drift": 30,
                "alert_silence": 60,
            },
            "retry": {
                "attempts": 3,
                "backoff_seconds": [1, 5, 15],
            },
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    result = _load_notifications_config(str(yaml_path))
    assert result is not None


def test_unknown_event_type_in_routing_overrides_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {
                "totally_unknown_event_xyz": {"telegram": True, "email": False},
            },
            "cadence_minutes_per_event_type": {},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5, 15]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="unknown event_type"):
        _load_notifications_config(str(yaml_path))


def test_bypass_severity_key_raises(tmp_path):
    """Decision 20 lockdown: bypass_severity key must be rejected."""
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5, 15]},
            "bypass_severity": "low",
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="bypass_severity"):
        _load_notifications_config(str(yaml_path))


def test_invalid_time_string_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "25:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5, 15]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="quiet_hours"):
        _load_notifications_config(str(yaml_path))


def test_cadence_zero_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {"manual_intervention_drift": 0},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5, 15]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="cadence_minutes"):
        _load_notifications_config(str(yaml_path))


def test_cadence_too_large_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {"manual_intervention_drift": 1441},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5, 15]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="cadence_minutes"):
        _load_notifications_config(str(yaml_path))


def test_retry_attempts_too_large_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {},
            "retry": {"attempts": 11, "backoff_seconds": [1, 5, 15, 30, 60, 120, 240, 480, 960, 1920, 3840]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="retry.attempts"):
        _load_notifications_config(str(yaml_path))


def test_retry_backoff_length_mismatch_raises(tmp_path):
    import yaml
    from src.notifications.telegram import _load_notifications_config
    from src.notifications.errors import NotificationsConfigError
    cfg_data = {
        "notifications": {
            "default_routing": {"telegram": True, "email": False},
            "digest_low": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "06:00",
            "quiet_digest": True,
            "mute_event_types": [],
            "routing_overrides": {},
            "cadence_minutes_per_event_type": {},
            "retry": {"attempts": 3, "backoff_seconds": [1, 5]},
        }
    }
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(yaml.dump(cfg_data))
    with pytest.raises(NotificationsConfigError, match="backoff_seconds"):
        _load_notifications_config(str(yaml_path))
