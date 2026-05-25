# Purpose: DBQuery subpackage — read-only SELECT/WITH tool against test PG.
# Called by: operator agents, src/tools/dbquery/__main__.py
# Calls: src.tools.dbquery.core
# Owns tables: none
# Config keys: pg.test_dsn
# Tests: tests/tools/test_dbquery_integration.py

from src.tools.dbquery.core import DBQueryError, WriteNotPermittedError, query, query_with_truncated

__all__ = ["query", "query_with_truncated", "WriteNotPermittedError", "DBQueryError"]
