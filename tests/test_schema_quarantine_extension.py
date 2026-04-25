"""T1.05 — verify quarantined column exists on attribution_trades + walkforward_trades.

Per audit-2026-04-27 §F-1, the `quarantined` flag on shadow_trades is extended
to attribution_trades and walkforward_trades so analytics filters
(`COALESCE(quarantined, 0) = 0`) work consistently across all three tables.
"""

from src.schema.registry import TABLES


def _column_names(table_name: str) -> list[str]:
    table = next(t for t in TABLES.values() if t.name == table_name)
    return [c.name for c in table.columns]


def _column_def(table_name: str, column_name: str):
    table = next(t for t in TABLES.values() if t.name == table_name)
    return next(c for c in table.columns if c.name == column_name)


def test_attribution_trades_has_quarantined_column():
    assert "quarantined" in _column_names("attribution_trades")


def test_attribution_trades_quarantined_column_shape():
    col = _column_def("attribution_trades", "quarantined")
    assert col.type == "INTEGER"
    assert col.default == "0"


def test_walkforward_trades_has_quarantined_column():
    assert "quarantined" in _column_names("walkforward_trades")


def test_walkforward_trades_quarantined_column_shape():
    col = _column_def("walkforward_trades", "quarantined")
    assert col.type == "INTEGER"
    assert col.default == "0"


def test_shadow_trades_quarantined_unchanged():
    """Sanity check that the existing shadow_trades column is still present
    with its expected shape — guards against accidental regression on the
    canonical column we're mirroring."""
    col = _column_def("shadow_trades", "quarantined")
    assert col.type == "INTEGER"
    assert col.default == "0"
