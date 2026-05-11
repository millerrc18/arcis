"""Tests for `_store_paper` in src/data_collection/research_collector.py.

Sprint 5 §J5/§J6 Phase 1 T1.2 — verifies the migration of the
`INSERT OR IGNORE INTO research_papers ...` SQL site at
src/data_collection/research_collector.py:121 to
`engine_aware_upsert(conn, 'research_papers', row_dict, action='ignore')`.

Parametrized over both engines using the `parametrized_conn` fixture from
tests/conftest.py — the postgres variant skips cleanly when
`TEST_DATABASE_URL` is unset.

Test coverage:

1. First call to _store_paper lands the row on both engines.
2. Duplicate call (same primary-key id) is ignored on both engines — the
   original row's values are preserved (no exception, no overwrite).
"""

import sqlite3
from contextlib import contextmanager

import pytest

from src.data_collection import research_collector
from src.utils.db import PostgresConnectionWrapper, engine_aware_upsert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_research_papers(conn) -> int:
    cur = conn.execute("SELECT COUNT(*) AS c FROM research_papers")
    row = cur.fetchone()
    if hasattr(row, "keys") and "c" in row.keys():
        return row["c"]
    return row[0]


def _select_research_paper_by_external_id(conn, external_id):
    cur = conn.execute(
        "SELECT * FROM research_papers WHERE external_id = ?", (external_id,)
    )
    return cur.fetchone()


@contextmanager
def _passthrough_connect(conn):
    """Yield `conn` from a context manager without closing it on exit.

    Used by tests that monkeypatch `connect_db` so the test fixture stays
    alive across multiple `_store_paper` calls.
    """
    yield conn


# ---------------------------------------------------------------------------
# Test 1 — _store_paper lands a new row via the engine-aware wrapper
# ---------------------------------------------------------------------------


def test_store_paper_inserts_row(parametrized_conn, monkeypatch):
    """T1.2 #1: First call to _store_paper lands a row on both engines via
    the engine_aware_upsert wrapper.

    Verifies that `_store_paper` writes through the engine_aware_upsert
    wrapper (not bare `INSERT OR IGNORE` SQL) — the wrapper is engine-agnostic
    so the same call produces the right INSERT on SQLite and PG. The wrapper
    call is intercepted to assert that the migrated code path is exercised
    (not just any SQL path that happens to land a row).
    """
    conn = parametrized_conn

    # Patch connect_db inside research_collector to yield the fixture conn.
    monkeypatch.setattr(
        research_collector,
        "connect_db",
        lambda _db_path: _passthrough_connect(conn),
    )

    # Wrap engine_aware_upsert so we can assert it was called with the right
    # table + action. The wrapper still runs the underlying call so the row
    # actually lands in the fixture DB.
    calls = []
    real_upsert = engine_aware_upsert

    def _spy_upsert(c, table, row_dict, action="replace"):
        calls.append((table, dict(row_dict), action))
        return real_upsert(c, table, row_dict, action=action)

    monkeypatch.setattr(research_collector, "engine_aware_upsert", _spy_upsert)

    paper = {
        "source": "arxiv",
        "external_id": "arxiv:2026.00001",
        "title": "A Test Paper on Pullback Strategies",
        "authors": "Researcher A, Researcher B",
        "abstract": "We study pullback-in-uptrend trading.",
        "url": "https://arxiv.org/abs/2026.00001",
        "published_date": "2026-05-11",
    }
    research_collector._store_paper(paper, 0.75, "test reason", "ignored_db_path")
    conn.commit()

    # Assert the wrapper was called — fails on pre-migration code that uses
    # bare `INSERT OR IGNORE` SQL.
    assert len(calls) == 1, (
        "_store_paper must call engine_aware_upsert exactly once "
        f"(saw {len(calls)} calls)"
    )
    table, row_dict, action = calls[0]
    assert table == "research_papers"
    assert action == "ignore"
    assert row_dict["external_id"] == "arxiv:2026.00001"
    assert row_dict["source"] == "arxiv"
    assert row_dict["title"] == "A Test Paper on Pullback Strategies"
    assert row_dict["relevance_score"] == 0.75
    assert row_dict["relevance_reason"] == "test reason"

    # Verify the row actually landed in the DB.
    assert _count_research_papers(conn) == 1
    row = _select_research_paper_by_external_id(conn, "arxiv:2026.00001")
    assert row is not None
    assert row["source"] == "arxiv"
    assert row["title"] == "A Test Paper on Pullback Strategies"
    assert row["relevance_score"] == 0.75
    assert row["relevance_reason"] == "test reason"


# ---------------------------------------------------------------------------
# Test 2 — duplicate primary key is ignored (no crash, original preserved)
# ---------------------------------------------------------------------------


def test_engine_aware_upsert_research_papers_duplicate_id_ignored(parametrized_conn):
    """T1.2 #2: action='ignore' preserves the existing row when the
    primary-key (id) collides, on both SQLite and PG.

    This exercises the engine_aware_upsert call shape that the migrated
    `_store_paper` produces, verifying that ON CONFLICT (id) DO NOTHING /
    INSERT OR IGNORE preserves the original row on both engines.
    """
    conn = parametrized_conn

    row1 = {
        "id": 1000001,
        "source": "arxiv",
        "external_id": "arxiv:2026.00002",
        "title": "Original Title",
        "authors": "Author One",
        "abstract": "Original abstract.",
        "url": "https://arxiv.org/abs/2026.00002",
        "published_date": "2026-05-11",
        "relevance_score": 0.5,
        "relevance_reason": "first",
        "collected_at": "2026-05-11T00:00:00",
    }
    engine_aware_upsert(conn, "research_papers", row1, action="ignore")
    conn.commit()

    row2 = {
        "id": 1000001,  # same PK → conflict
        "source": "arxiv",
        "external_id": "arxiv:2026.00002",
        "title": "Overwriting Title",  # would overwrite if action!=ignore
        "authors": "Author Two",
        "abstract": "Different abstract.",
        "url": "https://arxiv.org/abs/2026.00002",
        "published_date": "2026-05-11",
        "relevance_score": 0.9,
        "relevance_reason": "second",
        "collected_at": "2026-05-11T01:00:00",
    }
    engine_aware_upsert(conn, "research_papers", row2, action="ignore")
    conn.commit()

    assert _count_research_papers(conn) == 1
    cur = conn.execute("SELECT * FROM research_papers WHERE id = ?", (1000001,))
    row = cur.fetchone()
    assert row is not None
    # Original row preserved — ignore semantics on both engines.
    assert row["title"] == "Original Title"
    assert row["relevance_reason"] == "first"
    assert row["relevance_score"] == 0.5
