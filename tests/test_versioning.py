"""Tests for model versioning."""

import os
import sqlite3
import tempfile

from src.training.versioning import (
    get_active_model_name,
    get_active_model_version,
    get_model_history,
    get_next_semver,
    init_training_tables,
    register_model_version,
    rollback_model,
    update_config_model,
)


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def test_get_active_model_name_returns_base_when_empty():
    db = _tmp_db()
    init_training_tables(db)
    assert get_active_model_name(db) == "base"


def test_register_model_version_creates_active():
    db = _tmp_db()
    init_training_tables(db)
    vid = register_model_version("halcyon-v1", 100, 80, 20, "/path/model.gguf", db)
    assert vid is not None
    active = get_active_model_version(db)
    assert active is not None
    assert active["version_name"] == "halcyon-v1"
    assert active["status"] == "active"
    assert active["training_examples_count"] == 100


def test_register_retires_previous():
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1", 100, 80, 20, "/path/v1.gguf", db)
    register_model_version("halcyon-v2", 200, 150, 50, "/path/v2.gguf", db)

    active = get_active_model_version(db)
    assert active["version_name"] == "halcyon-v2"

    history = get_model_history(db)
    statuses = {h["version_name"]: h["status"] for h in history}
    assert statuses["halcyon-v1"] == "retired"
    assert statuses["halcyon-v2"] == "active"


def test_rollback_restores_previous():
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1", 100, 80, 20, "/path/v1.gguf", db)
    register_model_version("halcyon-v2", 200, 150, 50, "/path/v2.gguf", db)

    restored = rollback_model(db)
    assert restored is not None
    assert restored["version_name"] == "halcyon-v1"

    active = get_active_model_version(db)
    assert active["version_name"] == "halcyon-v1"


def test_rollback_returns_none_when_no_previous():
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1", 100, 80, 20, "/path/v1.gguf", db)
    restored = rollback_model(db)
    assert restored is None


def test_get_model_history_order():
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1", 100, 80, 20, "/path/v1.gguf", db)
    register_model_version("halcyon-v2", 200, 150, 50, "/path/v2.gguf", db)
    register_model_version("halcyon-v3", 300, 200, 100, "/path/v3.gguf", db)

    history = get_model_history(db)
    names = [h["version_name"] for h in history]
    assert names == ["halcyon-v3", "halcyon-v2", "halcyon-v1"]


# ── Semver auto-versioning tests ──────────────────────────────────────

def test_next_semver_no_versions():
    """First version should be halcyon-v1.0.0."""
    db = _tmp_db()
    init_training_tables(db)
    assert get_next_semver(db) == "halcyon-v1.0.0"


def test_next_semver_increments_minor():
    """After v1.0.0, next should be v1.1.0."""
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1.0.0", 969, 0, 0, "test.gguf", db)
    assert get_next_semver(db) == "halcyon-v1.1.0"


def test_next_semver_increments_from_higher():
    """After v1.3.0, next should be v1.4.0."""
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1.3.0", 2000, 0, 0, "test.gguf", db)
    assert get_next_semver(db) == "halcyon-v1.4.0"


def test_next_semver_handles_old_style():
    """Old-style halcyon-v3 should produce v1.3.0."""
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v3", 500, 0, 0, "test.gguf", db)
    assert get_next_semver(db) == "halcyon-v1.3.0"


def test_next_semver_preserves_patch_zero():
    """Minor increment should always reset patch to 0."""
    db = _tmp_db()
    init_training_tables(db)
    register_model_version("halcyon-v1.2.3", 1000, 0, 0, "test.gguf", db)
    assert get_next_semver(db) == "halcyon-v1.3.0"


# ── Config update tests ──────────────────────────────────────────────

def test_update_config_model_from_halcyonlatest():
    """Config should update from halcyonlatest to semver."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w") as f:
        f.write("llm:\n  model: halcyonlatest\n  temperature: 0.7\n")
    result = update_config_model("halcyon-v1.0.0", path)
    assert result is True
    with open(path) as f:
        content = f.read()
    assert "halcyon-v1.0.0" in content
    assert "halcyonlatest" not in content
    assert "temperature: 0.7" in content
    os.unlink(path)


def test_update_config_model_semver_to_semver():
    """Config should update from one semver to another."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w") as f:
        f.write("llm:\n  model: halcyon-v1.0.0\n  base_url: http://localhost:11434\n")
    result = update_config_model("halcyon-v1.1.0", path)
    assert result is True
    with open(path) as f:
        content = f.read()
    assert "halcyon-v1.1.0" in content
    assert "halcyon-v1.0.0" not in content
    assert "base_url" in content
    os.unlink(path)


def test_update_config_model_missing_file():
    """Missing config should return False, not crash."""
    result = update_config_model("halcyon-v1.0.0", "/nonexistent/settings.yaml")
    assert result is False


def test_update_config_model_no_model_field():
    """Config without a model field should return False."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w") as f:
        f.write("llm:\n  temperature: 0.7\n")
    result = update_config_model("halcyon-v1.0.0", path)
    assert result is False
    os.unlink(path)


def test_update_config_model_quoted_value():
    """Config with quoted model value should work."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w") as f:
        f.write('llm:\n  model: "halcyonlatest"\n')
    result = update_config_model("halcyon-v1.0.0", path)
    assert result is True
    with open(path) as f:
        content = f.read()
    assert "halcyon-v1.0.0" in content
    os.unlink(path)
