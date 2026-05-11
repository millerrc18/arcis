"""Tests for check_cutover_gate_consistency in src/startup_checks.py.

SP5 §J cutover-rectification T7 — truth-table tests for the 4 env-var combos
plus a registration check verifying the function is wired into STARTUP_CATEGORIES.

Imports use `src.startup` (the re-export surface) rather than `src.startup_checks`
directly to avoid the circular import: startup_checks -> src.startup -> startup_checks.
This matches the pattern used in test_startup_checks_introspection.py.
"""

import os
from unittest.mock import patch

import pytest


class TestCutoverGateConsistency:
    def test_critical_when_gate_on_and_no_pg_url(self):
        """ARCIS_PG_CUTOVER_ENABLED=1 with no DATABASE_URL -> critical."""
        from src.startup import check_cutover_gate_consistency

        env = {"ARCIS_PG_CUTOVER_ENABLED": "1", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=True):
            results = check_cutover_gate_consistency({}, db_path="ignored")

        assert len(results) == 1
        r = results[0]
        assert r.status == "critical"
        assert "does not start with 'postgres'" in r.detail

    def test_warn_when_gate_off_and_pg_url_set(self):
        """No ARCIS_PG_CUTOVER_ENABLED + DATABASE_URL=postgresql://... -> warn."""
        from src.startup import check_cutover_gate_consistency

        env = {"DATABASE_URL": "postgresql://host/db"}
        with patch.dict(os.environ, env, clear=True):
            results = check_cutover_gate_consistency({}, db_path="ignored")

        assert len(results) == 1
        r = results[0]
        assert r.status == "warn"

    def test_ok_when_both_consistent_postgres(self):
        """Both ARCIS_PG_CUTOVER_ENABLED=1 AND DATABASE_URL=postgresql://... -> ok."""
        from src.startup import check_cutover_gate_consistency

        env = {
            "ARCIS_PG_CUTOVER_ENABLED": "1",
            "DATABASE_URL": "postgresql://host/db",
        }
        with patch.dict(os.environ, env, clear=True):
            results = check_cutover_gate_consistency({}, db_path="ignored")

        assert len(results) == 1
        r = results[0]
        assert r.status == "ok"

    def test_ok_when_both_off(self):
        """Neither gate nor pg url set -> ok (consistent SQLite-only state)."""
        from src.startup import check_cutover_gate_consistency

        with patch.dict(os.environ, {}, clear=True):
            results = check_cutover_gate_consistency({}, db_path="ignored")

        assert len(results) == 1
        r = results[0]
        assert r.status == "ok"

    def test_check_registered_in_startup_categories(self):
        """check_cutover_gate_consistency must appear in STARTUP_CATEGORIES."""
        from src.startup import STARTUP_CATEGORIES, check_cutover_gate_consistency

        registered_fns = [fn for _label, fn in STARTUP_CATEGORIES]
        assert check_cutover_gate_consistency in registered_fns
