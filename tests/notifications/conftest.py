"""Notifications-package test fixtures.

Test-Determinism #128 T2 — provision `notifications_digest_queue` for the
quiet-hours -> digest path.

Background (Class-A "night-flake", docs/audits/2026-05-30-test-determinism):
T1 (commit 250dca01) added the deterministic policy clock and the
`freeze_quiet_hours` fixture. Under that fixture the notification policy gate
returns verdict='digest', so safe_send (src/notifications/telegram.py:786)
takes the digest branch:

    with _get_digest_db_conn() as conn:
        DigestQueue(conn, config=config).enqueue(...)

`_get_digest_db_conn()` defaults to `connect_db()` -> SQLite at ARCIS_DB_PATH.
The test SQLite DB does not provision `notifications_digest_queue`, so the
enqueue INSERT (src/notifications/digest_queue.py:84) raises
`sqlite3.OperationalError: no such table: notifications_digest_queue`. T1's
verify-by-mutation surfaced exactly this gap.

`_provision_digest_db` (autouse) closes it: it creates a temp SQLite DB with
the digest table via the schema registry (tests.conftest.init_test_db ->
src.schema.sqlite.generate_create_sql(TABLES["notifications_digest_queue"]) —
registry-driven, NO hardcoded DDL, per CLAUDE.md's CREATE TABLE ban) and
routes the otherwise-unpatched `_get_digest_db_conn` to it. Any notifications
test that drives the digest branch without its own connection patch now lands
the row in a provisioned DB instead of crashing on the missing table.

Sibling-search: the digest enqueue/flush/recover path references ONLY
`notifications_digest_queue` (grep of digest_queue.py). The SEND branch's
`notifications_sent` / `notifications_dedup` writes are not on the digest path,
so they are out of scope for this digest-table provisioning. Tests that need
the full schema continue to use the `schema_db` / `init_test_db` helpers in
tests/conftest.py.
"""

import sqlite3

import pytest

from tests.conftest import init_test_db


@pytest.fixture(autouse=True)
def _provision_digest_db(tmp_path, monkeypatch):
    """Provision `notifications_digest_queue` for the unpatched digest path.

    Registry-driven: init_test_db emits the table from
    TABLES["notifications_digest_queue"] via generate_create_sql. The temp DB's
    connection is exposed to safe_send by patching telegram._get_digest_db_conn
    (the documented test seam), so a digest-routed safe_send call that does NOT
    patch the connection itself still writes to a provisioned table.

    Tests that DO patch _get_digest_db_conn (e.g. test_safe_send_wiring.py)
    override this at function scope and are unaffected. The shared connection is
    also published as the `notifications_digest_conn` fixture for assertions.
    """
    db_path = str(tmp_path / "notifications_digest.sqlite3")
    init_test_db(db_path, tables=["notifications_digest_queue"])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # _get_digest_db_conn is used as a context manager (`with ... as conn`).
    # sqlite3.Connection's __exit__ commits/rolls back but does NOT close, so
    # the same connection stays usable for post-call assertions in the test.
    monkeypatch.setattr(
        "src.notifications.telegram._get_digest_db_conn", lambda: conn
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def notifications_digest_conn(_provision_digest_db):
    """Expose the autouse-provisioned digest DB connection for assertions."""
    return _provision_digest_db
