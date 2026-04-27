"""Regression-locks: get_system_status must return a single 'version' key
that equals src.version.VERSION (the declared single source of truth per
#631-15), not the get_app_version() fallback.

Issue #688 — The return dict had duplicate 'version' keys:
    "version": _ARCIS_VERSION,   # line 191 — src.version single source of truth
    ...
    "version": get_app_version(), # line 214 — silently overwrites line 191

Python silently discards the earlier key in a dict literal with duplicates,
so the dashboard received get_app_version() whose hardcoded fallback is the
stale string 'v0.16.12'. The fix: remove the duplicate get_app_version()
key, keeping only _ARCIS_VERSION.
"""

from __future__ import annotations

from unittest.mock import patch


def _get_status():
    """Return system_status dict with all external dependencies mocked."""
    from src.services.system_service import get_system_status

    config = {
        "email": {"smtp_server": "s", "username": "u", "password": "p"},
        "shadow_trading": {"enabled": False},
        "alpaca": {"api_key": "", "api_secret": "", "base_url": ""},
        "llm": {"enabled": False, "model": "test"},
        "training": {"enabled": False},
        "bootcamp": {"enabled": False},
    }
    with patch("src.llm.client.is_llm_available", return_value=False), \
         patch("src.training.versioning.get_active_model_name", return_value="base"), \
         patch("src.training.versioning.get_training_example_counts", return_value={"total": 0}):
        return get_system_status(config)


def test_version_equals_src_version_VERSION():
    """system_status['version'] must equal src.version.VERSION, not
    the get_app_version() dynamic fallback. Pre-fix this failed because
    the duplicate key caused Python to use get_app_version() instead.
    """
    from src.version import VERSION as _ARCIS_VERSION

    result = _get_status()

    assert result["version"] == _ARCIS_VERSION, (
        f"system_status['version'] must be src.version.VERSION={_ARCIS_VERSION!r}. "
        f"Got {result['version']!r}. Pre-fix the duplicate 'version' key in "
        f"get_system_status caused Python to use get_app_version() which has a "
        f"stale hardcoded fallback 'v0.16.12' (issue #688)."
    )


def test_version_is_not_get_app_version_fallback():
    """Specifically guard against the stale fallback string 'v0.16.12'
    that get_app_version() returns when env/VERSION file/git all miss.
    This would appear as the version value if the duplicate-key bug
    were re-introduced and get_app_version() fell through to its fallback.
    """
    result = _get_status()

    assert result["version"] != "v0.16.12", (
        "system_status['version'] must not be the stale fallback 'v0.16.12'. "
        "This value comes from get_app_version()._VERSION_FALLBACK, which means "
        "the duplicate 'version' key bug (issue #688) has been re-introduced."
    )


def test_no_duplicate_version_key_in_source():
    """Static check: get_system_status source must not contain two
    'version' string keys in the return dict. This catches any
    re-introduction of the duplicate-key pattern.
    """
    import inspect
    from src.services import system_service
    src = inspect.getsource(system_service.get_system_status)

    # Count literal 'version' key occurrences in the function body
    # (as dict key patterns like '"version":' or '"version" :')
    import re
    occurrences = re.findall(r'"version"\s*:', src)
    assert len(occurrences) <= 1, (
        f"get_system_status must have at most one '\"version\":' key in its "
        f"return dict. Found {len(occurrences)} occurrences — the duplicate "
        f"key bug (issue #688) has been re-introduced. Occurrences: {occurrences}"
    )
