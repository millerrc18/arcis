"""W21 P1-NEW-3 regression-lock: cutover-gate WARN must dedup by NORMALIZED string.

Pre-fix `_warn_db_path_ignored_once` used `id(db_path)` (Python object memory
address) as the dedup key. Different callers passed freshly-instantiated
string objects with different ids → "once" check failed → 570 warnings/hour
in production logs (logs/arcis.log on 2026-05-18 09:30 timeframe).

Fix normalizes via `os.path.normpath() + .lower()` so:
  - Different str objects with the same value collapse to one key
  - Backslash + forward-slash variants of the same path collapse to one key
"""

import logging


def test_warn_fires_only_once_for_same_path_value():
    """Two calls with str-equal db_path values must log only once."""
    from src.utils.db import _warn_db_path_ignored_once, _DB_PATH_WARNED
    _DB_PATH_WARNED.clear()

    # Two distinct str instances with the same VALUE
    path_a = "C:/arcis/data/ai_research_desk.sqlite3"
    path_b = str(path_a)  # forces new object; id() differs

    logger = logging.getLogger("src.utils.db")
    records: list = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r)
    logger.addHandler(handler)
    try:
        logger.setLevel(logging.WARNING)
        _warn_db_path_ignored_once(path_a)
        _warn_db_path_ignored_once(path_b)
    finally:
        logger.removeHandler(handler)

    warn_records = [r for r in records if "overridden by Phase 3 cutover gate" in r.getMessage()]
    assert len(warn_records) == 1, (
        f"Expected exactly 1 warning for str-equal paths, got {len(warn_records)}"
    )


def test_warn_fires_only_once_for_backslash_and_forward_slash_variants():
    """`C:\\arcis\\...` and `C:/arcis/...` must collapse to one key."""
    from src.utils.db import _warn_db_path_ignored_once, _DB_PATH_WARNED
    _DB_PATH_WARNED.clear()

    backslash = r"C:\arcis\data\ai_research_desk.sqlite3"
    forward = "C:/arcis/data/ai_research_desk.sqlite3"

    logger = logging.getLogger("src.utils.db")
    records: list = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r)
    logger.addHandler(handler)
    try:
        logger.setLevel(logging.WARNING)
        _warn_db_path_ignored_once(backslash)
        _warn_db_path_ignored_once(forward)
    finally:
        logger.removeHandler(handler)

    warn_records = [r for r in records if "overridden by Phase 3 cutover gate" in r.getMessage()]
    assert len(warn_records) == 1, (
        f"Expected 1 warning for backslash + forward-slash variants of same "
        f"path; got {len(warn_records)}. Normalization not collapsing."
    )


def test_warn_fires_separately_for_different_paths():
    """Different paths still produce separate warnings."""
    from src.utils.db import _warn_db_path_ignored_once, _DB_PATH_WARNED
    _DB_PATH_WARNED.clear()

    logger = logging.getLogger("src.utils.db")
    records: list = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r)
    logger.addHandler(handler)
    try:
        logger.setLevel(logging.WARNING)
        _warn_db_path_ignored_once("C:/arcis/data/db1.sqlite3")
        _warn_db_path_ignored_once("C:/arcis/data/db2.sqlite3")
    finally:
        logger.removeHandler(handler)

    warn_records = [r for r in records if "overridden by Phase 3 cutover gate" in r.getMessage()]
    assert len(warn_records) == 2, (
        f"Expected 2 warnings for different paths, got {len(warn_records)}"
    )
