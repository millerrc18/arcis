"""#582 — model_versions writes must leave an audit trail.

Pre-fix, src/training/versioning.py's rollback_model() and promote_model()
silently UPDATEd model_versions.status without writing anything to
activity_log. The operator who manually rolled back arcis:v1.0.0 on
2026-03-25 left zero audit trail; investigation 4 weeks later couldn't
answer "who/when/why."

Post-fix, every state mutation in versioning.py emits an activity_log
entry so the chain of custody is reconstructible.
"""
import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _opt_in_writes(monkeypatch):
    """Allow log_activity writes within these tests; tests pass tmp paths
    so the runtime guard from #647 doesn't fire."""
    monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")


def _seed(tmp_path):
    db_path = str(tmp_path / "test_versioning.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_path, ["model_versions", "activity_log"])
    return db_path


def test_rollback_model_writes_activity_log(tmp_path):
    """rollback_model must record a model_rollback event in activity_log."""
    db_path = _seed(tmp_path)

    # Seed an active and a retired version
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'active', '2026-04-20T00:00:00')",
            ("v-active", "arcis:test_active"),
        )
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'retired', '2026-04-15T00:00:00')",
            ("v-retired", "arcis:test_retired"),
        )
        conn.commit()

    from src.training.versioning import rollback_model
    rollback_model(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type, detail FROM activity_log "
            "WHERE event_type LIKE 'model_%' ORDER BY id"
        ).fetchall()
    assert len(events) >= 1
    assert any(
        "rollback" in e[0].lower() or "rollback" in (e[1] or "").lower()
        for e in events
    ), f"Expected a rollback event in activity_log; got {events}"


def test_promote_evaluation_model_writes_activity_log(tmp_path):
    """promote_evaluation_model must record a model_promote event in activity_log."""
    db_path = _seed(tmp_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'evaluation', '2026-04-20T00:00:00')",
            ("v-eval", "arcis:test_eval"),
        )
        conn.commit()

    from src.training.versioning import promote_evaluation_model
    promote_evaluation_model(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type, detail FROM activity_log "
            "WHERE event_type LIKE 'model_%' ORDER BY id"
        ).fetchall()
    assert len(events) >= 1
    assert any(
        "promote" in e[0].lower() or "promote" in (e[1] or "").lower()
        for e in events
    ), f"Expected a model_promote event in activity_log; got {events}"


def test_reject_evaluation_model_writes_activity_log(tmp_path):
    """reject_evaluation_model must record a model_reject event in activity_log."""
    db_path = _seed(tmp_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at) "
            "VALUES (?, ?, 'evaluation', '2026-04-20T00:00:00')",
            ("v-eval", "arcis:test_eval"),
        )
        conn.commit()

    from src.training.versioning import reject_evaluation_model
    reject_evaluation_model(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type, detail FROM activity_log "
            "WHERE event_type LIKE 'model_%' ORDER BY id"
        ).fetchall()
    assert len(events) >= 1
    assert any(
        "reject" in e[0].lower() or "reject" in (e[1] or "").lower()
        for e in events
    ), f"Expected a model_reject event in activity_log; got {events}"


def test_register_model_version_writes_activity_log(tmp_path):
    """register_model_version must record a model_register event in activity_log."""
    db_path = _seed(tmp_path)

    from src.training.versioning import register_model_version
    register_model_version(
        version_name="arcis:test_register",
        examples_count=100,
        synthetic_count=10,
        outcome_count=5,
        model_file_path="/tmp/test.bin",
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type, detail FROM activity_log "
            "WHERE event_type LIKE 'model_%' ORDER BY id"
        ).fetchall()
    assert len(events) >= 1
    assert any(
        "register" in e[0].lower() or "register" in (e[1] or "").lower()
        for e in events
    ), f"Expected a model_register event in activity_log; got {events}"


def test_versioning_state_mutators_all_log():
    """Coupling: every state-changing function in versioning.py must
    contain a log_activity call. Static-analysis check on source.

    Mutators (state writes): rollback_model, promote_evaluation_model,
    reject_evaluation_model, register_model_version (#660).
    Read-only functions like get_active_model_version are exempt.
    """
    import inspect
    import re
    from src.training import versioning

    mutators = [
        "rollback_model",
        "promote_evaluation_model",
        "reject_evaluation_model",
        "register_model_version",
    ]
    for name in mutators:
        fn = getattr(versioning, name, None)
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert re.search(r"log_activity\s*\(", src), (
            f"versioning.{name} mutates model_versions but does not call "
            f"log_activity. Add an audit-trail entry — see #660."
        )
