"""MIN7 integration test: validates event_map is populated at module-import-time
so that _load_notifications_config can validate routing_overrides keys.
(T10 Sprint 5 Wave D D1)
"""

import yaml
import pathlib
import pytest


def test_event_map_load_order(tmp_path):
    """Import src.main (which triggers module-level event_map population in telegram.py),
    then call _load_notifications_config with a sample config referencing known event
    types. Validation must pass without NotificationsConfigError.

    This test guards against a T15-style ordering bug where event_map might be
    lazy-extended after the validator runs.
    """
    import src.main  # noqa: F401 — triggers module-level initialization
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

    # Should not raise — event_map is fully populated at import time
    try:
        result = _load_notifications_config(str(yaml_path))
    except NotificationsConfigError as e:
        pytest.fail(f"_load_notifications_config raised unexpectedly: {e}")

    assert result is not None
