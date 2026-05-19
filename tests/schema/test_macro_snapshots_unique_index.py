"""Regression-lock for macro_snapshots upsert-key UNIQUE index (v0.36.23).

Pre-fix the registry declared `idx_macro_snapshots_series` on
`(series_id, collected_date)` with `unique=False`, but the macro_collector
calls `engine_aware_upsert(action='ignore')` which generates
`INSERT ... ON CONFLICT (series_id, collected_date) DO NOTHING` against PG.

PostgreSQL requires the ON CONFLICT target columns to be backed by a UNIQUE
constraint or PRIMARY KEY. With a non-unique index, every macro indicator
(UNRATE, T10Y2Y, VIXCLS, WALCL, M2SL, ...) failed with:
    "no unique or exclusion constraint matching the ON CONFLICT specification"

The bare INSERT path then silently created duplicate rows (233 dupes
accumulated by 2026-05-19, mostly from same-day collector re-runs).

Post-fix: the IndexDef is marked unique=True. This regression-lock asserts
that contract so a future refactor doesn't accidentally drop the uniqueness
constraint and re-introduce the bug.
"""
from __future__ import annotations

from src.schema.registry import TABLES


def test_macro_snapshots_upsert_index_is_unique():
    """idx_macro_snapshots_series must be UNIQUE to back ON CONFLICT (series_id, collected_date)."""
    table = TABLES["macro_snapshots"]

    upsert_index = next(
        (ix for ix in table.indexes if ix.name == "idx_macro_snapshots_series"),
        None,
    )
    assert upsert_index is not None, (
        "idx_macro_snapshots_series is missing from the registry — "
        "the macro_collector's ON CONFLICT target requires it."
    )

    assert upsert_index.columns == ["series_id", "collected_date"], (
        f"idx_macro_snapshots_series columns mismatch: {upsert_index.columns!r}. "
        "Must match the upsert sync_conflict_col exactly."
    )

    assert upsert_index.unique is True, (
        "idx_macro_snapshots_series must be UNIQUE — without it, PG's "
        "INSERT ... ON CONFLICT (series_id, collected_date) DO NOTHING raises "
        "'no unique or exclusion constraint matching the ON CONFLICT "
        "specification' and the macro collector falls back to bare INSERTs "
        "that silently create duplicates. See v0.36.23 incident."
    )


def test_macro_snapshots_sync_conflict_matches_unique_index():
    """sync_conflict_col on the table must be backed by a matching UNIQUE index/PK."""
    table = TABLES["macro_snapshots"]
    conflict_cols = [c.strip() for c in (table.sync_conflict_col or "").split(",")]
    assert conflict_cols == ["series_id", "collected_date"], (
        f"sync_conflict_col mismatch: {conflict_cols!r}"
    )

    # Find a UNIQUE index (or PK) covering exactly those columns
    has_unique = any(
        ix.unique and ix.columns == conflict_cols
        for ix in table.indexes
    )
    assert has_unique, (
        f"sync_conflict_col {conflict_cols!r} has no matching UNIQUE index. "
        "Every table with a multi-column sync_conflict_col must have a UNIQUE "
        "index on those exact columns, or PG ON CONFLICT will fail at runtime."
    )
