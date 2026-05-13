"""T12 — #110 security fold-in tests for _load_notifications_config.

+4 tests:
  - nested bypass_severity in routing_overrides raises
  - unknown routing_override key raises with key path
  - escalation_after_attempts key accepted (positive case)
  - string (not dict) routing_override value raises
"""

import os
import textwrap
import tempfile

import pytest


def _write_yaml(content: str) -> str:
    """Write YAML string to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


class TestNestedBypassSeverityUnderRoutingOverrides:
    def test_nested_bypass_severity_under_routing_overrides_raises(self):
        """YAML with notifications.routing_overrides.X.bypass_severity raises NotificationsConfigError."""
        from src.notifications.errors import NotificationsConfigError
        from src.notifications.telegram import _load_notifications_config

        yaml_str = textwrap.dedent("""\
            notifications:
              default_routing:
                telegram: true
                email: false
              digest_low: true
              quiet_hours_start: "22:00"
              quiet_hours_end: "06:00"
              quiet_digest: true
              mute_event_types: []
              routing_overrides:
                scan_complete:
                  telegram: true
                  bypass_severity: high
              cadence_minutes_per_event_type: {}
              retry:
                attempts: 3
                backoff_seconds: [1, 5, 15]
              digest_flush_minutes: 60
        """)
        path = _write_yaml(yaml_str)
        try:
            with pytest.raises(NotificationsConfigError, match="bypass_severity"):
                _load_notifications_config(path)
        finally:
            os.unlink(path)


class TestUnknownRoutingOverrideKeyRaises:
    def test_unknown_routing_override_key_raises_specific_path(self):
        """Typo 'telgram' in routing_overrides raises NotificationsConfigError with key path."""
        from src.notifications.errors import NotificationsConfigError
        from src.notifications.telegram import _load_notifications_config

        yaml_str = textwrap.dedent("""\
            notifications:
              default_routing:
                telegram: true
                email: false
              digest_low: true
              quiet_hours_start: "22:00"
              quiet_hours_end: "06:00"
              quiet_digest: true
              mute_event_types: []
              routing_overrides:
                scan_complete:
                  telgram: true
              cadence_minutes_per_event_type: {}
              retry:
                attempts: 3
                backoff_seconds: [1, 5, 15]
              digest_flush_minutes: 60
        """)
        path = _write_yaml(yaml_str)
        try:
            with pytest.raises(NotificationsConfigError) as exc_info:
                _load_notifications_config(path)
            assert "telgram" in str(exc_info.value)
            assert "scan_complete" in str(exc_info.value)
        finally:
            os.unlink(path)


class TestRoutingOverridesEscalationAfterAttemptsAccepted:
    def test_routing_overrides_escalation_after_attempts_key_accepted(self):
        """escalation_after_attempts is a valid key — should NOT raise."""
        from src.notifications.telegram import _load_notifications_config

        yaml_str = textwrap.dedent("""\
            notifications:
              default_routing:
                telegram: true
                email: false
              digest_low: true
              quiet_hours_start: "22:00"
              quiet_hours_end: "06:00"
              quiet_digest: true
              mute_event_types: []
              routing_overrides:
                manual_intervention_drift:
                  telegram: true
                  email: true
                  escalation_after_attempts: 3
              cadence_minutes_per_event_type: {}
              retry:
                attempts: 3
                backoff_seconds: [1, 5, 15]
              digest_flush_minutes: 60
        """)
        path = _write_yaml(yaml_str)
        try:
            config = _load_notifications_config(path)
            assert config.routing_overrides["manual_intervention_drift"]["escalation_after_attempts"] == 3
        finally:
            os.unlink(path)


class TestMalformedRoutingOverridesTypeRaises:
    def test_malformed_routing_overrides_type_raises(self):
        """String instead of dict for routing override raises NotificationsConfigError."""
        from src.notifications.errors import NotificationsConfigError
        from src.notifications.telegram import _load_notifications_config

        yaml_str = textwrap.dedent("""\
            notifications:
              default_routing:
                telegram: true
                email: false
              digest_low: true
              quiet_hours_start: "22:00"
              quiet_hours_end: "06:00"
              quiet_digest: true
              mute_event_types: []
              routing_overrides:
                scan_complete: "not-a-dict"
              cadence_minutes_per_event_type: {}
              retry:
                attempts: 3
                backoff_seconds: [1, 5, 15]
              digest_flush_minutes: 60
        """)
        path = _write_yaml(yaml_str)
        try:
            with pytest.raises(NotificationsConfigError, match="must be a dict"):
                _load_notifications_config(path)
        finally:
            os.unlink(path)
