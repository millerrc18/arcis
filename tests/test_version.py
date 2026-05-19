"""Tests for version constant and FastAPI version wiring (T2 P2).

Verifies:
- src.version.VERSION is bumped to v0.36.26
- src.api.app.app.version equals bare semver 0.36.26 (derived from VERSION)
- src.api.cloud_app.app.version equals bare semver 0.36.26 (derived from VERSION)
"""
import os

import pytest


def test_version_constant():
    from src.version import VERSION
    assert VERSION == "v0.36.26"


def test_version_has_v_prefix():
    from src.version import VERSION
    assert VERSION.startswith("v")


def test_app_version_matches_version_constant():
    os.environ.setdefault("API_SECRET", "test-secret")
    from src.api.app import app
    from src.version import VERSION
    assert app.version == VERSION.lstrip("v")


def test_app_version_is_bare_semver():
    os.environ.setdefault("API_SECRET", "test-secret")
    from src.api.app import app
    assert app.version == "0.36.26"


def test_cloud_app_version_matches_version_constant():
    from src.api.cloud_app import app as cloud_app
    from src.version import VERSION
    assert cloud_app.version == VERSION.lstrip("v")


def test_cloud_app_version_is_bare_semver():
    from src.api.cloud_app import app as cloud_app
    assert cloud_app.version == "0.36.26"
