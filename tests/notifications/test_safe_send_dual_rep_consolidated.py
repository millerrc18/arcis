"""T12 — dual-representation consolidation tests.

Verifies that _EVENT_MAP is the single source of truth and _KNOWN_EVENT_TYPES
is derived from it (not a separate hardcoded set).
"""


class TestEventMapNonEmpty:
    def test_event_map_is_non_empty_at_module_import(self):
        """_EVENT_MAP is non-empty at import time."""
        from src.notifications.telegram import _EVENT_MAP
        assert isinstance(_EVENT_MAP, dict)
        assert len(_EVENT_MAP) > 0


class TestKnownEventTypesEqualsEventMapKeys:
    def test_known_event_types_equals_frozenset_of_event_map_keys(self):
        """_KNOWN_EVENT_TYPES is exactly frozenset(_EVENT_MAP) — single source of truth."""
        from src.notifications.telegram import _EVENT_MAP, _KNOWN_EVENT_TYPES
        assert _KNOWN_EVENT_TYPES == frozenset(_EVENT_MAP.keys())
