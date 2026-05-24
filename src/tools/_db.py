"""Thin psycopg2 context-manager helper for all Tier-1 tools.

Called by: src/tools/db_query/, src/tools/trading_state/ (T2, T6, T7)
Calls: psycopg2 directly — NO src.config, src.utils.db, src.schema.registry
Owns tables: none
Config keys: none (DSN is caller-supplied per spec §4.9 network-discipline)
Tests: tests/tools/test_db_helper.py
       tests/tools/test_config.py:99 (prod_dsn_signatures parity — pre-existing)

Decorator contract verified at: src/tools/_safety.py:146-147
(SafetyError subclasses skip 'error' event in @safe_op classifier — DA7 §4.7)

FORBIDDEN IMPORTS: src.config, src.utils.db, src.schema.registry, load_dotenv,
os.environ.get('DATABASE_URL'), os.getenv('DATABASE_URL') — per spec §2.2.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extensions
import psycopg2.extras


class DBHelperError(RuntimeError):
    """Raised on psycopg2 connect failure — wraps psycopg2.Error for callers."""


@contextmanager
def pg_connect(
    dsn: str,
    *,
    read_only: bool = False,
    isolation_level: Optional[str] = None,
    timeout: int = 10,
    named_cursor: Optional[str] = None,
):
    """Yield (conn, cursor). Always uses RealDictCursor and connect_timeout.

    read_only=True → conn.set_session(readonly=True) — PG-enforced.
    isolation_level='REPEATABLE READ' → conn.set_session(isolation_level=...).
    named_cursor='name' → server-side cursor (required for itersize streaming).
    On exception, rolls back before re-raising. Always closes conn on exit.
    """
    try:
        conn = psycopg2.connect(dsn, connect_timeout=timeout)
    except psycopg2.Error as exc:
        raise DBHelperError(f"pg_connect failed: {exc}") from exc

    try:
        if isolation_level is not None:
            conn.set_session(isolation_level=isolation_level)
        if read_only:
            conn.set_session(readonly=True)

        if named_cursor is not None:
            cur = conn.cursor(named_cursor, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            yield conn, cur
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
