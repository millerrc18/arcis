"""Conviction-on-trade wiring: insert_shadow_trade denormalizes the source
recommendation's confidence_score / llm_conviction onto the trade row
(rec_confidence_score / rec_llm_conviction) so conviction-vs-outcome calibration
is queryable without a recommendations join (2026-06-12).

Unit tests mock connect_db (hermetic); one integration test round-trips through
the real insert path + schema.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.journal import store


# ── helper unit tests (hermetic) ────────────────────────────────────────────

def test_attach_conviction_populates_from_recommendation(monkeypatch):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value.execute.return_value.fetchone.return_value = {
        "confidence_score": 8.0, "llm_conviction": 7,
    }
    monkeypatch.setattr("src.journal.store.connect_db", lambda *a, **k: fake_conn)
    trade = {"recommendation_id": "rec-1"}
    store._attach_recommendation_conviction(trade, db_path=":memory:")
    assert trade["rec_confidence_score"] == 8.0
    assert trade["rec_llm_conviction"] == 7


def test_attach_conviction_noop_without_rec_id(monkeypatch):
    called = []
    monkeypatch.setattr("src.journal.store.connect_db",
                        lambda *a, **k: called.append(1) or MagicMock())
    trade = {"recommendation_id": None}
    store._attach_recommendation_conviction(trade, db_path=":memory:")
    assert "rec_confidence_score" not in trade
    assert not called, "must not query the DB when there is no recommendation_id"


def test_attach_conviction_noop_when_already_set(monkeypatch):
    called = []
    monkeypatch.setattr("src.journal.store.connect_db",
                        lambda *a, **k: called.append(1) or MagicMock())
    trade = {"recommendation_id": "rec-1", "rec_confidence_score": 9.0}
    store._attach_recommendation_conviction(trade, db_path=":memory:")
    assert trade["rec_confidence_score"] == 9.0  # not overwritten
    assert not called


def test_attach_conviction_defensive_on_db_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr("src.journal.store.connect_db", boom)
    trade = {"recommendation_id": "rec-1"}
    # must NOT raise — a conviction lookup failure can never break an insert
    store._attach_recommendation_conviction(trade, db_path=":memory:")
    assert "rec_confidence_score" not in trade  # left NULL


def test_attach_conviction_noop_when_recommendation_missing(monkeypatch):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value.execute.return_value.fetchone.return_value = None
    monkeypatch.setattr("src.journal.store.connect_db", lambda *a, **k: fake_conn)
    trade = {"recommendation_id": "nope"}
    store._attach_recommendation_conviction(trade, db_path=":memory:")
    assert "rec_confidence_score" not in trade


# ── integration round-trip (real insert path + schema) ──────────────────────

def test_insert_shadow_trade_persists_conviction_roundtrip(tmp_path, monkeypatch):
    """Hermetic round-trip: a recommendation's confidence flows onto the inserted
    trade row. Disables the cutover gate + uses a temp SQLite so the test can
    never touch a live PG (the ambient connect_db routes to prod when cutover is on).
    """
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    db = str(tmp_path / "conv.sqlite3")

    from src.schema import sqlite as sqlite_schema
    from src.utils.db import connect_db
    sqlite_schema.create_all_tables(db)

    rec_id = "rec-roundtrip-1"
    with connect_db(db) as conn:
        conn.execute(
            "INSERT INTO recommendations "
            "(recommendation_id, created_at, ticker, confidence_score, llm_conviction) "
            "VALUES (?, ?, ?, ?, ?)",
            (rec_id, "2026-06-12T00:00:00", "TESTX", 8.5, 7),
        )
        conn.commit()

    tid = store.insert_shadow_trade({
        "recommendation_id": rec_id, "ticker": "TESTX",
        "direction": "long", "planned_shares": 1,
        # NOT NULL columns normally filled by ShadowTrade.to_dict():
        "created_at": "2026-06-12T00:00:00", "updated_at": "2026-06-12T00:00:00",
        "quarantined": 0, "instrumentation_version": 1,
    }, db_path=db)

    with connect_db(db) as conn:
        row = conn.execute(
            "SELECT rec_confidence_score, rec_llm_conviction "
            "FROM shadow_trades WHERE trade_id = ?", (tid,),
        ).fetchone()
    assert row is not None
    assert float(row["rec_confidence_score"]) == 8.5
    assert int(row["rec_llm_conviction"]) == 7
