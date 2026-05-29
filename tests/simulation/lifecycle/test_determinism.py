"""Determinism hardening tests for the lifecycle simulator (Task 14, invariant 9).

Importing ``src.simulation.lifecycle.bootstrap`` FIRST pins PYTHONHASHSEED=0 and
the safe env before anything else touches a DB — that pin is what makes the
canonical snapshot hash (invariant 9) reproducible across runs.

The proof of invariant 9 (deterministic_reproducibility) is twofold:

  * EQUALITY — two seeded ``run_smoke()`` runs (same fixed seed, same fixed fill
    prices, same id-normalized snapshot with explicit ORDER BY on business keys)
    produce the IDENTICAL canonical hash. Any prod uuid / random is seeded, and
    SERIAL PKs + raw timestamps are excluded from the snapshot, so nothing
    nondeterministic leaks into the hash.

  * INEQUALITY — when the underlying BUSINESS data changes (a different row, a
    different value), the canonical hash MUST differ. A hash that stayed constant
    across a real data change would be useless as a determinism oracle.

These tests assert against the SAME ``canonical_snapshot_hash`` the Oracle's
invariant 9 emits, so they prove the production determinism check, not a proxy.
"""

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins hashseed
import sqlite3

import pytest

from src.schema.sqlite import create_all_tables
from src.simulation.lifecycle.entrypoints.smoke import run_smoke
from src.simulation.lifecycle.oracle._checks_db import canonical_snapshot_hash


_DETERMINISM_INVARIANT = "deterministic_reproducibility"


def _smoke_hash():
    """Run the fast SQLite smoke scenario; return its invariant-9 canonical hash."""
    result = run_smoke()
    inv9 = [r for r in result.results if r.name == _DETERMINISM_INVARIANT]
    assert len(inv9) == 1, "smoke run must emit exactly one determinism invariant"
    return inv9[0].detail


def _seeded_sqlite(db_path):
    """Create the registry schema on a temp SQLite DB and return a raw connection."""
    create_all_tables(db_path)
    conn = sqlite3.connect(db_path)
    return conn


def _insert_trade(conn, *, rec_id, trade_id, ticker, status, shares, order_type):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recommendations (recommendation_id, created_at, ticker) "
        "VALUES (?, ?, ?)",
        (rec_id, "2026-05-22T09:30:00", ticker),
    )
    cur.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, recommendation_id, ticker, status, actual_shares, "
        " order_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, rec_id, ticker, status, shares, order_type,
         "2026-05-22T09:30:00", "2026-05-22T09:30:00"),
    )
    conn.commit()


# ── EQUALITY: two seeded smoke runs hash identically (invariant 9) ─────────────


@pytest.mark.skip(reason="integration(authoritative-coverage:lifecycle-full-gate): runs the full organic-runner lifecycle scenario against the 5434 PG, exceeds the 60s per-PR pg-tests window; run_full_gate()/run_smoke() are authoritatively covered by the lifecycle-full-gate CI job")
def test_two_seeded_smoke_runs_produce_identical_canonical_hash():
    """Invariant 9: two fixed-seed run_smoke() runs hash identically."""
    first = _smoke_hash()
    second = _smoke_hash()
    assert first == second, (
        "two seeded smoke runs must produce the IDENTICAL canonical hash "
        f"(invariant 9 determinism): {first!r} != {second!r}"
    )


@pytest.mark.skip(reason="integration(authoritative-coverage:lifecycle-full-gate): runs the full organic-runner lifecycle scenario against the 5434 PG, exceeds the 60s per-PR pg-tests window; run_full_gate()/run_smoke() are authoritatively covered by the lifecycle-full-gate CI job")
def test_smoke_canonical_hash_is_a_real_sha256_digest():
    """The determinism detail is a 64-char hex SHA-256 (not an empty / placeholder)."""
    digest = _smoke_hash()
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ── INEQUALITY: a real BUSINESS data change MUST change the hash ───────────────


def test_canonical_hash_differs_when_business_data_differs(tmp_path):
    """Different snapshot-table data => different canonical hash (no false-stable)."""
    conn_a = _seeded_sqlite(str(tmp_path / "a.sqlite"))
    conn_b = _seeded_sqlite(str(tmp_path / "b.sqlite"))
    try:
        _insert_trade(
            conn_a, rec_id="rec-1", trade_id="t-1", ticker="AAPL",
            status="open", shares=10.0, order_type="paper",
        )
        # Same shape, DIFFERENT business value (ticker) — hash must differ.
        _insert_trade(
            conn_b, rec_id="rec-1", trade_id="t-1", ticker="MSFT",
            status="open", shares=10.0, order_type="paper",
        )
        hash_a = canonical_snapshot_hash(conn_a)
        hash_b = canonical_snapshot_hash(conn_b)
    finally:
        conn_a.close()
        conn_b.close()
    assert hash_a != hash_b, (
        "a real business-data change (ticker AAPL->MSFT) MUST change the "
        "canonical hash; an unchanged hash would make invariant 9 useless"
    )


def test_canonical_hash_identical_for_identical_business_data(tmp_path):
    """Two DBs with the SAME business rows hash identically — even with different
    SERIAL PKs / autoincrement rowids (those are excluded from the snapshot)."""
    conn_a = _seeded_sqlite(str(tmp_path / "a.sqlite"))
    conn_b = _seeded_sqlite(str(tmp_path / "b.sqlite"))
    try:
        # Insert an extra throwaway row in B first, then delete it, so B's
        # autoincrement rowids are OFFSET from A's. Identical business data
        # must still hash the same because the snapshot excludes surrogate PKs.
        _insert_trade(
            conn_b, rec_id="throwaway", trade_id="throwaway", ticker="ZZZ",
            status="open", shares=1.0, order_type="paper",
        )
        cur_b = conn_b.cursor()
        cur_b.execute("DELETE FROM shadow_trades WHERE trade_id = 'throwaway'")
        cur_b.execute("DELETE FROM recommendations WHERE recommendation_id = 'throwaway'")
        conn_b.commit()

        for conn in (conn_a, conn_b):
            _insert_trade(
                conn, rec_id="rec-1", trade_id="t-1", ticker="AAPL",
                status="open", shares=10.0, order_type="paper",
            )
        hash_a = canonical_snapshot_hash(conn_a)
        hash_b = canonical_snapshot_hash(conn_b)
    finally:
        conn_a.close()
        conn_b.close()
    assert hash_a == hash_b, (
        "identical business data must hash identically regardless of surrogate "
        "PK / autoincrement offset (invariant 9 id-normalization)"
    )
