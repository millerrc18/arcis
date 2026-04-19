"""Regression guard for composite-primary-key ON CONFLICT mismatch.

The bug: sync_config.generate_sync_tables extracted only `primary_key[0]`
from composite PKs, so Postgres ON CONFLICT saw only the first column.
Postgres has a unique constraint on the FULL composite — ON CONFLICT
(ticker) never matched it, and every cycle logged "no unique or exclusion
constraint matching the ON CONFLICT specification". Three tables affected:
minute_bars, correlation_matrices, factor_loadings.
"""
from __future__ import annotations

from src.schema.registry import TABLES
from src.schema.sync_config import generate_sync_tables


def test_composite_pk_tables_have_full_conflict_col():
    """Every sync'd composite-PK table must emit a conflict_col that names
    the full tuple, not just the first column."""
    cfg = generate_sync_tables()
    offenders = []
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        if not (isinstance(table.primary_key, list) and len(table.primary_key) > 1):
            continue
        entry = cfg.get(name, {})
        expected = ", ".join(table.primary_key)
        actual = entry.get("conflict_col")
        if actual != expected and not table.sync_conflict_col:
            offenders.append(
                f"{name}: expected conflict_col={expected!r}, got {actual!r}"
            )
    assert not offenders, (
        "Composite-PK tables missing full conflict_col:\n  " + "\n  ".join(offenders)
    )


def test_minute_bars_conflict_col_matches_composite_pk():
    """Smoke test: minute_bars specifically (the one that fired every sync
    cycle in production arcis.log)."""
    cfg = generate_sync_tables()
    assert cfg["minute_bars"]["conflict_col"] == "ticker, timestamp"


def test_correlation_matrices_conflict_col_matches_composite_pk():
    """correlation_matrices has a 5-column PK. The conflict_col must list all
    five — any subset won't match the Postgres unique constraint."""
    cfg = generate_sync_tables()
    assert cfg["correlation_matrices"]["conflict_col"] == (
        "date, method, strategy_a, strategy_b, window_days"
    )


def test_factor_loadings_conflict_col_matches_composite_pk():
    """factor_loadings has a 4-column PK."""
    cfg = generate_sync_tables()
    assert cfg["factor_loadings"]["conflict_col"] == (
        "date, strategy_id, factor, window_days"
    )


def test_explicit_sync_conflict_col_takes_precedence():
    """If a TableDef sets sync_conflict_col explicitly, the generator must
    use it as-is rather than the composite-PK fallback."""
    # All composites currently rely on the fallback; verify that the
    # fallback-vs-explicit precedence logic works by checking one non-
    # composite table with an explicit sync_conflict_col (if any).
    cfg = generate_sync_tables()
    for name, table in TABLES.items():
        if table.sync_to_postgres and table.sync_conflict_col:
            assert cfg[name]["conflict_col"] == table.sync_conflict_col, (
                f"{name}: explicit sync_conflict_col should win over fallback"
            )


def test_single_column_pk_does_not_get_conflict_col():
    """Non-composite PKs should not emit a conflict_col — the `pk` field
    already carries enough info for the upsert path."""
    cfg = generate_sync_tables()
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        if isinstance(table.primary_key, str) or (
            isinstance(table.primary_key, list) and len(table.primary_key) == 1
        ):
            if not table.sync_conflict_col:
                assert "conflict_col" not in cfg[name], (
                    f"{name}: single-column PK must not emit conflict_col"
                )
