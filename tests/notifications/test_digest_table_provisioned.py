"""Test-Determinism #128 T2 — notifications_digest_queue provisioned for the
quiet-hours digest path.

Verify-by-mutation target for T2. T1 (commit 250dca01) added the deterministic
policy clock + the `freeze_quiet_hours` fixture, and its verify-by-mutation
proved the gap: under `freeze_quiet_hours`, driving safe_send routes the event
to the digest branch (telegram.py:786) which calls the UNPATCHED
`_get_digest_db_conn()` -> connect_db() -> SQLite. The test SQLite DB does not
provision `notifications_digest_queue`, so `DigestQueue.enqueue`
(digest_queue.py:84) raises `sqlite3.OperationalError: no such table:
notifications_digest_queue`.

T2 fixes this at the notifications shared SQLite bootstrap (the autouse
`_provision_digest_db` fixture in tests/notifications/conftest.py): it
registry-drives creation of `notifications_digest_queue` into a temp SQLite DB
and routes the unpatched digest connection there. This test exercises that
path with NO per-test `_get_digest_db_conn` patch and NO manual table creation
— so it FAILS (no such table) without the fixture and PASSES with it.

Sibling-search: the digest branch touches ONLY notifications_digest_queue
(enqueue/flush/recover in digest_queue.py reference no other table). The SEND
branch writes notifications_sent / notifications_dedup via _do_dispatch, which
is not exercised here.
"""

from src.notifications import safe_send
from src.notifications.telegram import TradeOpenedPayload


def _make_notif_config():
    from src.notifications.policy import NotificationsConfig

    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=True,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
    )


def test_quiet_hours_digest_enqueues_without_manual_db_patch(
    freeze_quiet_hours, monkeypatch, notifications_digest_conn
):
    """Under freeze_quiet_hours, safe_send -> digest enqueues a row using the
    SHARED (autouse-provisioned) digest DB — no manual _get_digest_db_conn
    patch, no manual CREATE TABLE.

    This is the T2 verify-by-mutation: reverting the conftest provisioning makes
    the digest INSERT hit `no such table: notifications_digest_queue` (the exact
    T1 error). With provisioning, the row lands.
    """
    payload = TradeOpenedPayload(
        ticker="AAPL", entry_price=100.0, stop=95.0, target=110.0, score=80, shares=10
    )
    cfg = _make_notif_config()

    # is_telegram_enabled + config patched; the CLOCK comes from freeze_quiet_hours
    # (03:00 ET) via the T1 _now_et_for_safe_send pin, so the policy gate returns
    # verdict='digest'. _get_digest_db_conn is intentionally NOT patched here —
    # the autouse conftest fixture routes it at a provisioned temp SQLite DB.
    monkeypatch.setattr(
        "src.notifications.telegram.is_telegram_enabled", lambda: True
    )
    monkeypatch.setattr(
        "src.notifications.telegram._load_config_for_safe_send", lambda: cfg
    )

    result = safe_send("trade_opened", payload=payload)

    assert result is True
    rows = notifications_digest_conn.execute(
        "SELECT event_type, severity, payload_json FROM notifications_digest_queue"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "trade_opened"
