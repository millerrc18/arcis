"""Structural regression tests for connect_db() discipline (Sprint 0.B/B2.3).

Closes: #692, #693, #694

Asserts that the three in-scope files (simulation/engine.py, startup.py,
startup_checks.py, shadow_trading/executor.py) do NOT use raw
sqlite3.connect() — they must call src.utils.db.connect_db() instead.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""

import ast
import re
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw_connect_lines(filepath: str) -> list[str]:
    """Return lines in *filepath* that contain a raw sqlite3.connect() call.

    Excludes:
    - Comment lines (stripped starts with #)
    - Lines inside the connect_db() helper itself (utils/db.py)
    """
    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    hits = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Match both `sqlite3.connect(` and `_sqlite3.connect(`
        if re.search(r"(?:_?sqlite3)\.connect\(", line):
            hits.append(f"{filepath}:{lineno}: {stripped}")
    return hits


# ── #692 — simulation/engine.py ───────────────────────────────────────────────

def test_simulation_engine_no_raw_sqlite3_connect():
    """simulation/engine.py must not use raw sqlite3.connect() — closes #692."""
    hits = _raw_connect_lines("src/simulation/engine.py")
    assert not hits, (
        "simulation/engine.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_simulation_engine_imports_connect_db():
    """simulation/engine.py must import connect_db from src.utils.db."""
    text = Path("src/simulation/engine.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "simulation/engine.py does not import connect_db from src.utils.db"
    )


# ── #693 — startup.py ─────────────────────────────────────────────────────────

def test_startup_no_raw_sqlite3_connect():
    """startup.py must not use raw sqlite3.connect() — closes #693 (site 1)."""
    hits = _raw_connect_lines("src/startup.py")
    assert not hits, (
        "startup.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_startup_imports_connect_db():
    """startup.py must import connect_db from src.utils.db."""
    text = Path("src/startup.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "startup.py does not import connect_db from src.utils.db"
    )


# ── #693 — startup_checks.py ──────────────────────────────────────────────────

def test_startup_checks_no_raw_sqlite3_connect():
    """startup_checks.py must not use raw sqlite3.connect() — closes #693 (sites 2+3)."""
    hits = _raw_connect_lines("src/startup_checks.py")
    assert not hits, (
        "startup_checks.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_startup_checks_imports_connect_db():
    """startup_checks.py must import connect_db from src.utils.db."""
    text = Path("src/startup_checks.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "startup_checks.py does not import connect_db from src.utils.db"
    )


# ── #694 — shadow_trading/executor.py ─────────────────────────────────────────

def test_executor_no_raw_sqlite3_connect_duplicate_check():
    """executor.py must not use raw sqlite3.connect() for dup-check — closes #694.

    Scans executor.py for raw sqlite3.connect() calls. The historical
    import alias `import sqlite3 as _sqlite3` is also checked.
    """
    hits = _raw_connect_lines("src/shadow_trading/executor.py")
    assert not hits, (
        "executor.py contains raw sqlite3.connect() calls — "
        "use connect_db() from src.utils.db:\n" + "\n".join(hits)
    )


def test_executor_imports_connect_db():
    """executor.py must import connect_db from src.utils.db."""
    text = Path("src/shadow_trading/executor.py").read_text(encoding="utf-8")
    assert "from src.utils.db import" in text and "connect_db" in text, (
        "executor.py does not import connect_db from src.utils.db"
    )
