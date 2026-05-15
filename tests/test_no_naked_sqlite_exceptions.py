"""Lint: no naked `except sqlite3.X` in src/ — use engine-agnostic DBError tuples.

Context: 2026-05-15 v0.36.7 council Round 1 crash. `gather_risk_data`
wrapped a buggy SQL in `try/except sqlite3.Error`. When PG raised
`psycopg2.errors.GroupingError` (which inherits from `psycopg2.Error`,
not `sqlite3.Error`), the exception escaped the wrapper and crashed
the council session. The wrapper's intent was "swallow DB errors and
degrade gracefully" — but post-cutover, half the DB errors are PG-class.

Survey found 45 sites across 15 files with this gap. v0.36.8 introduced
`DBError` / `DBOperationalError` / `DBIntegrityError` tuples in
`src/utils/db.py` that span both engines' error hierarchies. This test
enforces that no `src/` file uses the engine-specific forms outside of
the explicitly-allowlisted engine-specific files.

Allowlist:
  - `src/utils/db.py` — the module that DEFINES DBError; imports sqlite3
    as a building block.
  - `src/schema/sqlite.py` — SQLite-engine-specific schema applier;
    never runs against PG so its `except sqlite3.OperationalError`
    catches are correct as-is.

Any other site introducing `except sqlite3.X` will fail this test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ALLOWLIST_FILES = frozenset({
    "src/utils/db.py",
    "src/schema/sqlite.py",
})

# Pattern: `except` followed by optional whitespace and an optional `(`,
# then `sqlite3.` followed by a capitalized identifier (the exception class).
# Matches all forms: `except sqlite3.Error:`, `except sqlite3.Error as exc:`,
# `except (sqlite3.OperationalError, TypeError, ValueError):` etc.
NAKED_SQLITE_EXCEPT_RE = re.compile(
    r"\bexcept\b\s*\(?\s*sqlite3\.(Error|DatabaseError|OperationalError|"
    r"IntegrityError|ProgrammingError|InterfaceError|InternalError|DataError|"
    r"NotSupportedError)\b"
)


def _walk_src_files():
    """Yield (rel_path, full_text) for every src/ python file outside the allowlist."""
    src_root = Path(__file__).parent.parent / "src"
    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(src_root.parent).as_posix()
        if rel in ALLOWLIST_FILES:
            continue
        try:
            yield rel, path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue


def test_no_naked_sqlite_exceptions_in_src():
    """No `except sqlite3.X:` outside the allowlist — use DBError tuples instead.

    Migration map (apply at each offending site):
      except sqlite3.Error          → except DBError
      except sqlite3.OperationalError → except DBOperationalError
      except sqlite3.IntegrityError   → except DBIntegrityError
    Plus add the import:
      from src.utils.db import DBError, DBOperationalError, DBIntegrityError
    """
    offenders: list[str] = []
    for rel, text in _walk_src_files():
        for line_no, line in enumerate(text.splitlines(), start=1):
            if NAKED_SQLITE_EXCEPT_RE.search(line):
                offenders.append(f"{rel}:{line_no}: {line.strip()}")

    assert not offenders, (
        f"Found {len(offenders)} naked `except sqlite3.X` sites in src/.\n"
        "Each one is a place where PG-specific errors (psycopg2.errors.*) "
        "will silently escape the wrapper and crash the enclosing loop — "
        "the exact bug class behind the 2026-05-15 council Round 1 crash.\n\n"
        "Migrate using the engine-agnostic tuples from src.utils.db:\n"
        "  except sqlite3.Error            → except DBError\n"
        "  except sqlite3.OperationalError → except DBOperationalError\n"
        "  except sqlite3.IntegrityError   → except DBIntegrityError\n\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_db_error_tuples_exist_and_include_psycopg2():
    """`src.utils.db` must export DBError / DBOperationalError / DBIntegrityError tuples."""
    import sqlite3
    import psycopg2
    from src.utils.db import DBError, DBOperationalError, DBIntegrityError

    # DBError must catch both sqlite3 base and psycopg2 base
    assert sqlite3.Error in DBError, "DBError must include sqlite3.Error"
    assert psycopg2.Error in DBError, "DBError must include psycopg2.Error"

    assert sqlite3.OperationalError in DBOperationalError
    assert psycopg2.OperationalError in DBOperationalError

    assert sqlite3.IntegrityError in DBIntegrityError
    assert psycopg2.IntegrityError in DBIntegrityError
