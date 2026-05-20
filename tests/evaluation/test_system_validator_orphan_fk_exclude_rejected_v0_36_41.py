"""v0.36.41 — db_orphaned_fk must exclude rejected_* records.

A 'rejected_buying_power' shadow_trade (executor.py _check_paper_buying_power) is
recorded for dashboard visibility with the scan's recommendation_id, but the
recommendation row is only persisted for TAKEN trades — so every rejected record
has a DANGLING FK by design. They are not orphaned positions. On the live DB,
461/461 of the db_orphaned_fk warning was rejected_* records, masking the genuine
(zero, post-v0.36.40) signal. See docs/audits/2026-W21-orphan-source (phenomenon 3).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SRC = Path("src/evaluation/system_validator.py").read_text(encoding="utf-8")


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    return db


def _insert_trade(db, trade_id, order_type, rec_id):
    """Insert a shadow_trade with a dangling rec_id (recommendations is empty)."""
    from src.utils.db import connect_db
    with connect_db(db) as conn:
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, order_type, recommendation_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade_id, "AAPL", "rejected", order_type, rec_id,
             "2026-05-20T10:00:00-04:00", "2026-05-20T10:00:00-04:00"),
        )
        conn.commit()


def _orphan_fk_check(db):
    from src.evaluation.system_validator import _check_database
    checks = _check_database(db)
    return next((c for c in checks if c["name"] == "db_orphaned_fk"), None)


def test_rejected_record_with_dangling_fk_does_not_warn(tmp_db):
    """A rejected_buying_power row with a dangling rec_id must NOT trip db_orphaned_fk."""
    _insert_trade(tmp_db, "t-rej", "rejected_buying_power", "ghost-rec")
    check = _orphan_fk_check(tmp_db)
    assert check is not None
    assert check["status"] == "pass", f"rejected record wrongly counted as orphan: {check}"


def test_genuine_nonrejected_dangling_fk_still_warns(tmp_db):
    """A non-rejected (bracket) row with a dangling rec_id IS a genuine orphan — must warn."""
    _insert_trade(tmp_db, "t-real", "bracket", "ghost-rec-2")
    check = _orphan_fk_check(tmp_db)
    assert check is not None
    assert check["status"] == "warn", f"genuine dangling FK not surfaced: {check}"


def test_only_rejected_among_mixed_yields_pass(tmp_db):
    """With a rejected dangling row + a valid-FK taken row, the check passes (the
    rejected one is excluded, the valid one isn't dangling)."""
    from src.utils.db import connect_db
    # a taken trade whose rec_id DOES resolve
    with connect_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, created_at) "
            "VALUES (?, ?, ?)",
            ("real-rec", "MSFT", "2026-05-20T09:00:00-04:00"),
        )
        conn.commit()
    _insert_trade(tmp_db, "t-ok", "bracket", "real-rec")          # valid FK
    _insert_trade(tmp_db, "t-rej2", "rejected_buying_power", "ghost-3")  # dangling but rejected
    check = _orphan_fk_check(tmp_db)
    assert check is not None
    assert check["status"] == "pass", f"expected pass, got {check}"


def test_query_excludes_rejected_order_types_content_lock():
    """Regression-lock: the orphan-FK query must filter out rejected_* order_types."""
    assert "NOT LIKE 'rejected%'" in _SRC, (
        "db_orphaned_fk query must exclude rejected_* records "
        "(they have dangling FKs by design, not orphaned positions)"
    )
