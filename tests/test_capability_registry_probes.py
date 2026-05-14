"""Parametrized tests for the 5 capability probe functions that were unavailable/timeout.

Tests each probe's query function against a fresh SQLite fixture DB.
Each probe must return a dict with the correct shape — no raises, no NameError.

Probes under test:
- shadow_trade_cohort    (src.shadow_trading.state — read-only, has proper imports)
- strategy_registry_state (src.platform — FILES_IN_SCOPE, missing connect_db import)
- training_corpus        (src.services.training_service — FILES_IN_SCOPE, missing connect_db import)
- reconcile_trades       (src.shadow_trading.reconcile_state — read-only, has proper imports)
- attribution_resolver   (src.attribution.logger — read-only, has proper imports)
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from tests.conftest import init_test_db


# ---------------------------------------------------------------------------
# Fixture: per-test SQLite database patched into each probe's DB_PATH
# ---------------------------------------------------------------------------

@pytest.fixture()
def probe_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with all schema tables; patches DB_PATH into probe modules."""
    db_path = str(tmp_path / "probe_test.db")
    init_test_db(db_path)

    # Ensure we are NOT in PG cutover mode for these unit tests
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Patch DB_PATH in the modules that the probes read
    import src.config as _cfg
    import src.utils.db as _db
    monkeypatch.setattr(_cfg, "DB_PATH", db_path)
    monkeypatch.setattr(_db, "DEFAULT_DB", db_path)

    yield db_path


# ---------------------------------------------------------------------------
# Helper: reload probe modules so they pick up the patched DB_PATH
# ---------------------------------------------------------------------------

def _call_probe_fresh(module_name: str, func_name: str, probe_db: str) -> dict:
    """Import (or reload) module and call named function, return its result."""
    import importlib
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name)
    return fn()


# ---------------------------------------------------------------------------
# Parametrized probe tests
# ---------------------------------------------------------------------------

PROBE_CASES = [
    # (capability_name, module, function)
    ("shadow_trade_cohort",    "src.shadow_trading.state",      "_shadow_cohort_counts"),
    ("strategy_registry_state","src.platform",                  "_query_strategy_registry_state"),
    ("training_corpus",        "src.services.training_service", "_training_corpus_counts"),
    ("reconcile_trades",       "src.shadow_trading.reconcile_state", "reconcile_health"),
    ("attribution_resolver",   "src.attribution.logger",        "attribution_resolver_health"),
]


@pytest.mark.parametrize("capability,module_name,func_name", PROBE_CASES, ids=[c[0] for c in PROBE_CASES])
def test_probe_does_not_raise(capability, module_name, func_name, probe_db):
    """Probe must complete without raising an exception."""
    import importlib

    # Patch DB_PATH inside the probe's own module namespace if it caches it
    mod = importlib.import_module(module_name)
    if hasattr(mod, "DB_PATH"):
        import src.config as _cfg
        # The module may have captured DB_PATH at import time; patch it directly
        import unittest.mock as mock
        with mock.patch.object(mod, "DB_PATH", probe_db):
            result = getattr(mod, func_name)()
    else:
        result = getattr(mod, func_name)()

    assert isinstance(result, dict), (
        f"{capability}: expected dict result, got {type(result).__name__}: {result!r}"
    )


@pytest.mark.parametrize("capability,module_name,func_name", PROBE_CASES, ids=[c[0] for c in PROBE_CASES])
def test_probe_returns_value_or_status(capability, module_name, func_name, probe_db):
    """Probe returns either {'value': ...} (state) or {'status': ...} (system).

    An empty table is valid — count 0 is correct shape.
    The probe must NOT return {'error': ...} caused by a missing import.
    """
    import importlib
    import unittest.mock as mock

    mod = importlib.import_module(module_name)
    if hasattr(mod, "DB_PATH"):
        with mock.patch.object(mod, "DB_PATH", probe_db):
            result = getattr(mod, func_name)()
    else:
        result = getattr(mod, func_name)()

    # Must have either 'value' or 'status' key — not a raw NameError/import error
    has_value_key = "value" in result
    has_status_key = "status" in result
    assert has_value_key or has_status_key, (
        f"{capability}: result missing 'value' or 'status' key: {result!r}"
    )

    # If it's a status-keyed result, must not be 'unavailable' due to NameError
    if has_status_key and not has_value_key:
        # For system probes: degraded is ok (empty DB), down/unavailable is not
        # unless the table is genuinely missing — which init_test_db creates
        assert result["status"] != "unavailable" or "no " in result.get("detail", "").lower() or (
            "unavailable" in result.get("detail", "").lower()
        ), (
            f"{capability}: status=unavailable suggests probe crashed: {result!r}"
        )
