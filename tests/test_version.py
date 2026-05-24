"""Tests for version constant and FastAPI version wiring (T2 P2).

Verifies:
- src.version.VERSION matches the current release header
- src.api.app.app.version equals bare semver derived from VERSION
- src.api.cloud_app.app.version equals bare semver derived from VERSION

The version-lock tests assert hardcoded literals on purpose: bumping VERSION
without updating these (and therefore the CHANGELOG, per src/version.py's
companion docstring) is exactly the drift this file catches. Update the
literals as part of every release PR.
"""
import os

import pytest


_EXPECTED_VERSION = "v0.36.61"
_EXPECTED_BARE_SEMVER = "0.36.61"


def test_version_constant():
    from src.version import VERSION
    assert VERSION == _EXPECTED_VERSION


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
    assert app.version == _EXPECTED_BARE_SEMVER


def test_cloud_app_version_matches_version_constant():
    from src.api.cloud_app import app as cloud_app
    from src.version import VERSION
    assert cloud_app.version == VERSION.lstrip("v")


def test_cloud_app_version_is_bare_semver():
    from src.api.cloud_app import app as cloud_app
    assert cloud_app.version == _EXPECTED_BARE_SEMVER
