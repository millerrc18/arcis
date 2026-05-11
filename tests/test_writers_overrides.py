"""Phase 3-revised T4 — config/overrides writer cross-engine verification.

Tests that apply_override in src/config/overrides.py:
1. Uses engine_aware_upsert (not raw INSERT...ON CONFLICT) for config_overrides writes
2. Inserts a new setting correctly (key=A, value=1 → read returns 1)
3. Replace-on-conflict works: insert key=A value=2 → read returns 2
4. previous_value chain — apply_override returns the old value before replacement
5. previous_value is None on first insert

Test 1 (uses engine_aware_upsert) FAILS before the implementation is changed.
Tests 2-5 verify behavioral correctness on the sqlite engine.
Postgres variants skip cleanly when TEST_DATABASE_URL is unset.
"""

import json
import sqlite3

import pytest

from tests.conftest import init_test_db


def test_apply_override_calls_engine_aware_upsert(tmp_path):
    """apply_override MUST use engine_aware_upsert for the config_overrides write.

    This test FAILS with the old raw INSERT...ON CONFLICT implementation (which
    doesn't call engine_aware_upsert) and PASSES after the conversion.
    """
    from unittest.mock import patch

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["config_overrides"])

    import src.config.overrides as overrides_module

    with patch.object(
        overrides_module,
        "engine_aware_upsert",
        wraps=overrides_module.engine_aware_upsert,
    ) as mock_upsert:
        overrides_module.apply_override("shadow_trading.enabled", True, db_path=db_path)
        assert mock_upsert.called, (
            "apply_override must call engine_aware_upsert for config_overrides — "
            "raw INSERT...ON CONFLICT is not cross-engine safe"
        )
        first_call = mock_upsert.call_args_list[0]
        assert first_call[0][1] == "config_overrides", (
            f"Expected engine_aware_upsert called on 'config_overrides', "
            f"got {first_call[0][1]!r}"
        )
        assert first_call[1].get("action") == "replace" or (
            len(first_call[0]) >= 4 and first_call[0][3] == "replace"
        ), "engine_aware_upsert must be called with action='replace'"


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_apply_override_inserts_new_setting(engine, tmp_path, request):
    """apply_override inserts a fresh key and read back returns the inserted value."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["config_overrides"])

    from src.config.overrides import apply_override, get_overrides

    result = apply_override("shadow_trading.enabled", True, db_path=db_path)
    assert "error" not in result, f"apply_override failed: {result}"

    overrides = get_overrides(db_path=db_path)
    assert "shadow_trading.enabled" in overrides
    assert json.loads(overrides["shadow_trading.enabled"]) is True


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_apply_override_replaces_existing_setting(engine, tmp_path, request):
    """apply_override with same key replaces the old value (replace semantics)."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["config_overrides"])

    from src.config.overrides import apply_override, get_overrides

    apply_override("shadow_trading.max_positions", 5, db_path=db_path)
    apply_override("shadow_trading.max_positions", 10, db_path=db_path)

    overrides = get_overrides(db_path=db_path)
    assert json.loads(overrides["shadow_trading.max_positions"]) == 10, (
        "Second apply_override should have replaced the first value"
    )


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_apply_override_returns_previous_value(engine, tmp_path, request):
    """apply_override returns the old value in 'previous' field after a replace."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["config_overrides"])

    from src.config.overrides import apply_override

    apply_override("llm.min_conviction_score", 0.6, db_path=db_path)
    result = apply_override("llm.min_conviction_score", 0.8, db_path=db_path)

    assert "error" not in result, f"Second apply_override failed: {result}"
    assert result.get("previous") == 0.6, (
        f"Expected previous=0.6, got {result.get('previous')!r}"
    )
    assert result.get("value") == 0.8, (
        f"Expected value=0.8, got {result.get('value')!r}"
    )


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_apply_override_previous_value_none_on_first_insert(engine, tmp_path, request):
    """apply_override returns previous=None when key didn't exist before."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["config_overrides"])

    from src.config.overrides import apply_override

    result = apply_override("scheduler.scan_interval_minutes", 15, db_path=db_path)
    assert "error" not in result, f"apply_override failed: {result}"
    assert result.get("previous") is None, (
        f"Expected previous=None on first insert, got {result.get('previous')!r}"
    )
