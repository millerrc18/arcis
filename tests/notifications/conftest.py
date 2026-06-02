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

`_provision_digest_db` (autouse) closes it: it creates an IN-MEMORY SQLite DB
with the digest table generated FROM THE SCHEMA REGISTRY
(src.schema.sqlite.generate_create_sql(TABLES["notifications_digest_queue"]) —
registry-driven, NO hardcoded DDL, per CLAUDE.md's CREATE TABLE ban) and routes
the otherwise-unpatched `telegram._get_digest_db_conn` to it. Any notifications
test that drives the digest branch without its own connection patch now lands
the row in a provisioned table instead of crashing on the missing one.

Why in-memory (NOT a temp file under tmp_path): an in-memory connection has
zero filesystem footprint, so this autouse fixture cannot pollute the per-test
`tmp_path` that sibling tests inspect —
test_email_digest_handover.py::test_handover_check_shadow_files_present_when_shadow_mode
points shadow_output_dir at tmp_path and asserts the directory is EMPTY, which a
temp-file DB anywhere under tmp_path would break. In-memory also matches the
precedent in test_safe_send_wiring.py and test_email_digest_handover.py.

Seam scope (sibling-search): the ONLY module-level connect_db() seam on the
quiet-hours digest path a test can hit UNPATCHED is telegram._get_digest_db_conn
(the WRITE/enqueue path). The email-digest READER that self-opens a connection
(email_digest_handover._open_handover_conn) is already patched per-test by
test_email_digest_handover.py::_patch_handover_conn; email_digest.flush_tier /
build_and_send_digest take an injected `conn` and never self-open. So only the
write seam needs provisioning here.

Sibling-search: the digest enqueue/flush/recover path references ONLY
`notifications_digest_queue` (grep of digest_queue.py). The SEND branch's
`notifications_sent` / `notifications_dedup` writes are not on the digest path,
so they are out of scope for this digest-table provisioning. Tests that need
the full schema continue to use the `schema_db` / `init_test_db` helpers in
tests/conftest.py.
"""

import sqlite3

import pytest

from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql


@pytest.fixture(autouse=True)
def _provision_digest_db(monkeypatch):
    """Provision `notifications_digest_queue` for the unpatched digest write path.

    Registry-driven: the table DDL comes from
    generate_create_sql(TABLES["notifications_digest_queue"]) executed on a
    fresh in-memory SQLite connection. That connection is exposed to safe_send
    by patching telegram._get_digest_db_conn (the documented test seam), so a
    digest-routed safe_send call that does NOT patch the connection itself
    still writes to a provisioned table.

    Tests that DO patch _get_digest_db_conn (e.g. test_safe_send_wiring.py)
    override this at function scope and are unaffected. The connection is also
    published as the `notifications_digest_conn` fixture for assertions.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(generate_create_sql(TABLES["notifications_digest_queue"]))
    conn.commit()
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
