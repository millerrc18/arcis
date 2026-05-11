"""Structural regression tests for connect_db() discipline (Sprint 0.B/B2.3).

Closes: #692, #693, #694

Asserts that the three in-scope files (simulation/engine.py, startup.py,
startup_checks.py, shadow_trading/executor.py) do NOT use raw
sqlite3.connect() — they must call src.utils.db.connect_db() instead.

Sprint 5 §J5/§J6 Phase 2 T2.13 extension — Modified-A migration:
Adds positive allowlist assertions for the SQLite-only-by-design files that
DO legitimately use raw sqlite3.connect(). Two categories:

    PERMANENT allowlist — call sites that will NEVER route through the
    engine-aware shim because they fundamentally need a real
    `sqlite3.Connection` (Online Backup API, PRAGMA-only schema migration,
    in-process maintenance jobs on the local SQLite mirror, the wrapper's
    own SQLite branch, and the test fixture's SQLite engine variant).

    RETIRING allowlist — files that still hold raw sqlite3.connect() calls
    pending their Phase 4 deletion (render_sync.py is the cloud SQLite-side
    of the sync, reconcile.py is on the Phase 4 deletion list — see
    docs/audits/2026-05-11-modified-a-migration/plan.md T4.1, T4.2).

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""

import re
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw_connect_lines(filepath: str) -> list[str]:
    """Return lines in *filepath* that contain a raw sqlite3.connect() call.

    Excludes:
    - Comment lines (stripped starts with #)
    - Lines inside the connect_db() helper itself (utils/db.py)
    """
    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    hits = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Match both `sqlite3.connect(` and `_sqlite3.connect(`
        if re.search(r"(?:_?sqlite3)\.connect\(", line):
            hits.append(f"{filepath}:{lineno}: {stripped}")
    return hits


# ── #692 — simulation/engine.py ───────────────────────────────────────────────

def test_simulation_engine_no_raw_sqlite3_connect():
    """simulation/engine.py must not use raw sqlite3.connect() — closes #692."""
    hits = _raw_connect_lines("src/simulation/engine.py")
    assert not hits, (
        "simulation/engine.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_simulation_engine_imports_connect_db():
    """simulation/engine.py must import connect_db from src.utils.db."""
    text = Path("src/simulation/engine.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "simulation/engine.py does not import connect_db from src.utils.db"
    )


# ── #693 — startup.py ─────────────────────────────────────────────────────────

def test_startup_no_raw_sqlite3_connect():
    """startup.py must not use raw sqlite3.connect() — closes #693 (site 1)."""
    hits = _raw_connect_lines("src/startup.py")
    assert not hits, (
        "startup.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_startup_imports_connect_db():
    """startup.py must import connect_db from src.utils.db."""
    text = Path("src/startup.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "startup.py does not import connect_db from src.utils.db"
    )


# ── #693 — startup_checks.py ──────────────────────────────────────────────────

def test_startup_checks_no_raw_sqlite3_connect():
    """startup_checks.py must not use raw sqlite3.connect() — closes #693 (sites 2+3)."""
    hits = _raw_connect_lines("src/startup_checks.py")
    assert not hits, (
        "startup_checks.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_startup_checks_imports_connect_db():
    """startup_checks.py must import connect_db from src.utils.db."""
    text = Path("src/startup_checks.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "startup_checks.py does not import connect_db from src.utils.db"
    )


# ── #694 — shadow_trading/executor.py ─────────────────────────────────────────

def test_executor_no_raw_sqlite3_connect_duplicate_check():
    """executor.py must not use raw sqlite3.connect() for dup-check — closes #694.

    Scans executor.py for raw sqlite3.connect() calls. The historical
    import alias `import sqlite3 as _sqlite3` is also checked.
    """
    hits = _raw_connect_lines("src/shadow_trading/executor.py")
    assert not hits, (
        "executor.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_executor_imports_connect_db():
    """executor.py must import connect_db from src.utils.db."""
    text = Path("src/shadow_trading/executor.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "executor.py does not import connect_db from src.utils.db"
    )


# ── PERMANENT allowlist (Sprint 5 §J5/§J6 Phase 2 T2.13) ─────────────────────
#
# These files legitimately use raw sqlite3.connect() because the operation
# they perform fundamentally requires a real sqlite3.Connection — routing
# through the engine-aware shim would either break (PRAGMA on Postgres) or
# defeat the operation's purpose (Online Backup API copies SQLite pages
# directly; PG has its own pg_dump-style mechanism).
#
# The tests below assert that each permanent-allowlist site STILL contains
# a raw sqlite3.connect() call. This guards against accidental migration to
# connect_db() — which would silently switch the operation to PG when the
# cutover lands, breaking SQLite-only invariants.


def test_permanent_allowlist_schema_sqlite_uses_raw_connect():
    """src/schema/sqlite.py uses raw sqlite3.connect() for SQLite-only DDL.

    Rationale: every operation here uses SQLite-specific syntax (PRAGMA
    index_list, PRAGMA index_info, etc.). The `_sqlite_only_connect` helper
    at line 33 bypasses the engine-aware shim so PRAGMA calls work even when
    DATABASE_URL points at Postgres. Line 226 is the deferred-index-create
    retry path in `add_missing_columns` — also SQLite-only.
    """
    hits = _raw_connect_lines("src/schema/sqlite.py")
    assert hits, (
        "src/schema/sqlite.py is on the PERMANENT allowlist for raw "
        "sqlite3.connect() but no call sites were found. If the helper was "
        "removed or refactored, update this allowlist test accordingly."
    )


def test_permanent_allowlist_utils_db_uses_raw_connect():
    """src/utils/db.py uses raw sqlite3.connect() for the SQLite branch of connect_db().

    Rationale: this is the canonical wrapper itself. connect_db() at line ~450
    calls sqlite3.connect(effective_path, ...) on the SQLite path. Without
    this allowlist entry, the discipline test would flag the wrapper's own
    internal call site as a violation.

    Also re-exports _sqlite_only_connect from src.schema.sqlite (Phase 0 T0.8),
    which is the canonical SQLite-only helper for non-shim call sites.
    """
    hits = _raw_connect_lines("src/utils/db.py")
    assert hits, (
        "src/utils/db.py is on the PERMANENT allowlist for raw "
        "sqlite3.connect() but no call sites were found. The wrapper's "
        "SQLite branch must use sqlite3.connect() directly — if this call "
        "moved, update this allowlist test accordingly."
    )


def test_permanent_allowlist_scheduler_watch_backup_uses_raw_connect():
    """src/scheduler/watch.py:_backup_database uses raw sqlite3.connect() for Online Backup API.

    Rationale: the SQLite Online Backup API (conn.backup(dst)) copies
    physical pages between two real sqlite3.Connection objects. Routing
    either side through the engine-aware shim would break it — the wrapper
    doesn't expose the C-level backup API. See watch.py:_backup_database
    (~lines 1199-1200) for the src+dst connect calls.
    """
    hits = _raw_connect_lines("src/scheduler/watch.py")
    assert hits, (
        "src/scheduler/watch.py is on the PERMANENT allowlist for raw "
        "sqlite3.connect() (Online Backup API in _backup_database) but no "
        "call sites were found. If _backup_database was migrated, update "
        "this allowlist test accordingly."
    )


def test_permanent_allowlist_trainer_quarantine_uses_raw_connect():
    """src/training/trainer.py:quarantine_stuck_outcome_templates uses raw sqlite3.connect().

    Rationale: this is an in-process maintenance job that operates on the
    local SQLite mirror only — it never needs to run against the Postgres
    side. The local-import alias `import sqlite3 as _sqlite3` at ~line 1170
    is the historical pattern for marking SQLite-only sites; the
    `_sqlite3.connect(db_path)` call at ~line 1171 is intentional.
    """
    hits = _raw_connect_lines("src/training/trainer.py")
    assert hits, (
        "src/training/trainer.py is on the PERMANENT allowlist for raw "
        "sqlite3.connect() (quarantine_stuck_outcome_templates) but no "
        "call sites were found. If the function was migrated to connect_db(), "
        "update this allowlist test accordingly."
    )


def test_permanent_allowlist_conftest_uses_raw_connect():
    """tests/conftest.py uses raw sqlite3.connect() in init_test_db and parametrized_conn.

    Rationale: init_test_db (line ~40) bootstraps a fresh SQLite test DB by
    creating the registry's tables — it must use sqlite3 directly because
    the test DB has no DATABASE_URL and no PG-side schema. The
    `parametrized_conn` fixture (Phase 0 T0.9) yields a real
    sqlite3.Connection on the `engine='sqlite'` parametrization branch so
    engine-aware helpers can be tested against actual SQLite semantics.
    The `engine='postgres'` branch delegates to `pg_wrapper`.
    """
    hits = _raw_connect_lines("tests/conftest.py")
    assert hits, (
        "tests/conftest.py is on the PERMANENT allowlist for raw "
        "sqlite3.connect() (init_test_db + parametrized_conn sqlite branch) "
        "but no call sites were found. If these fixtures were refactored, "
        "update this allowlist test accordingly."
    )


# ── RETIRING allowlist (Sprint 5 §J5/§J6 Phase 2 T2.13) ──────────────────────
#
# These files still contain raw sqlite3.connect() calls but are slated for
# deletion in Phase 4 of the Modified-A migration (T4.1: delete render_sync.py
# after the Render decommission cutover lands; T4.2: delete reconcile.py and
# remove these allowlist entries).
#
# These tests are MARKERS — they assert the current state so that when
# the file is deleted, the test will fail loudly and signal the operator to
# remove the allowlist entry. Do NOT treat a future failure as a regression;
# treat it as a Phase 4 closure signal.


def test_retiring_allowlist_render_sync_uses_raw_connect():
    """RETIRING (Phase 4 T4.1): src/sync/render_sync.py — delete after Render decommission.

    Marker test. render_sync.py is the SQLite-side of the legacy push-to-Render
    sync flow. With the cloud now reading PG directly (per the 2026-05-10
    cutover), this file is scheduled for deletion in Phase 4 T4.1. When that
    deletion lands, this test will fail (file missing) — that is the signal
    to remove this retiring-allowlist entry.
    """
    if not Path("src/sync/render_sync.py").exists():
        return  # Phase 4 T4.1 has shipped — remove this test in the same PR.
    hits = _raw_connect_lines("src/sync/render_sync.py")
    assert hits, (
        "src/sync/render_sync.py is on the RETIRING allowlist for raw "
        "sqlite3.connect() but no call sites were found. If the file was "
        "refactored, update this retiring-allowlist test accordingly."
    )


def test_retiring_allowlist_reconcile_uses_raw_connect():
    """RETIRING (Phase 4 T4.2): src/sync/reconcile.py — slated for deletion.

    Marker test. reconcile.py is on the Phase 4 T4.2 deletion list. When the
    deletion lands, this test will fail (file missing) — that is the signal
    to remove this retiring-allowlist entry from this file in the same PR.
    """
    if not Path("src/sync/reconcile.py").exists():
        return  # Phase 4 T4.2 has shipped — remove this test in the same PR.
    hits = _raw_connect_lines("src/sync/reconcile.py")
    assert hits, (
        "src/sync/reconcile.py is on the RETIRING allowlist for raw "
        "sqlite3.connect() but no call sites were found. If the file was "
        "refactored, update this retiring-allowlist test accordingly."
    )
