"""Tests for the schema registry."""

import pytest
from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef, _register


def test_tables_dict_exists():
    assert isinstance(TABLES, dict)


def test_register_adds_table():
    table = TableDef(
        name="_test_table",
        description="Test",
        columns=[ColumnDef("id", "INTEGER", nullable=False)],
        primary_key="id",
    )
    _register(table)
    assert "_test_table" in TABLES
    del TABLES["_test_table"]
