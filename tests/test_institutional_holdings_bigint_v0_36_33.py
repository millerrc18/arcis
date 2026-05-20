"""Regression-lock for v0.36.33 — institutional_holdings.total_shares BIGINT.

Background
==========

v0.36.25 fixed the institutional_ownership collector URL (`/stock/ownership`).
With real data flowing, the collector failed nightly on 2026-05-19:

    [COLLECT] institutional_ownership: FAILED -- {'error': 'integer out of range'}

`institutional_holdings.total_shares` was declared `INTEGER` (PG int32, max
2,147,483,647). The collector sums `share` across all institutional holders
of a ticker (`_aggregate_holders`, institutional_ownership_collector.py:73-81).
For a megacap, the aggregate exceeds 2.1B — e.g. AAPL has ~8000 institutional
holders; Vanguard alone holds ~374M shares.

SQLite never hit this (dynamic typing — INTEGER affinity stores full int64).
PG's strict `integer` overflowed.

The fix
=======

`total_shares` → `BIGINT` (PG int64, max 9.2e18). Added `BIGINT` to the
registry's PG type map. PG column migrated via ALTER COLUMN.
"""
from __future__ import annotations


def test_total_shares_is_bigint_in_registry():
    """institutional_holdings.total_shares must be BIGINT, not INTEGER."""
    from src.schema.registry import TABLES

    table = TABLES["institutional_holdings"]
    col = next((c for c in table.columns if c.name == "total_shares"), None)
    assert col is not None, "total_shares column missing from registry"
    assert col.type.upper() == "BIGINT", (
        f"total_shares is {col.type!r}, must be BIGINT. INTEGER (PG int32, "
        "max 2.1B) overflows on aggregate institutional share counts for "
        "megacaps. See v0.36.33."
    )


def test_bigint_maps_to_pg_bigint():
    """The PG type map must translate BIGINT → BIGINT (not silently drop to INTEGER)."""
    from src.schema.postgres import _TYPE_MAP

    assert _TYPE_MAP.get("BIGINT") == "BIGINT", (
        f"_TYPE_MAP['BIGINT'] = {_TYPE_MAP.get('BIGINT')!r}, must be 'BIGINT'. "
        "Without this, a BIGINT ColumnDef would map to an unknown/default PG type."
    )


def test_aggregate_holders_can_exceed_int32():
    """The collector's _aggregate_holders must produce a total_shares that can
    exceed int32 — proving the overflow scenario is real (not hypothetical)."""
    from src.data_collection.institutional_ownership_collector import _aggregate_holders

    # Simulate a megacap: 10 holders each with 300M shares = 3B total > 2.1B int32 max
    holders = [{"share": 300_000_000, "filingDate": "2026-03-31"} for _ in range(10)]
    row = _aggregate_holders(holders, "AAPL")

    assert row["total_shares"] == 3_000_000_000, (
        f"Expected 3B total_shares, got {row['total_shares']}"
    )
    assert row["total_shares"] > 2_147_483_647, (
        "The test scenario must exceed int32 max to prove the overflow is real."
    )
