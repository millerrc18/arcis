"""Regression guards for Tier 1 hardening (#619, #578, #437, #482, #436).

Each test prevents the corresponding bug pattern from re-emerging via
source-scan assertions (similar to tests/test_dep_health_hardening.py).
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #619 — RotatingFileHandler must specify encoding="utf-8"
# ---------------------------------------------------------------------------


def test_log_config_file_handler_uses_utf8_encoding(tmp_path):
    """#619 — RotatingFileHandler must specify encoding='utf-8' so emoji
    and CJK characters are written to the log file instead of being
    silently dropped via the cp1252 fallback on Windows.

    Behavioral test: configure logging to a tmp file, emit an emoji
    record, then read the file as utf-8 and assert the emoji round-trips.
    On Windows without encoding='utf-8', this raises UnicodeEncodeError
    inside logging.handleError() and the record is dropped.
    """
    import logging

    from src.log_config import setup_logging

    log_file = tmp_path / "test.log"
    setup_logging(level="INFO", log_file=str(log_file))

    logger = logging.getLogger("tier1.utf8.test")
    # ❌ is ❌ (cross mark) — fails to encode under cp1252
    logger.error("emoji marker ❌ here")

    # Force flush all root handlers so the file is written before we read.
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass

    text = log_file.read_text(encoding="utf-8")
    assert "❌" in text, (
        "Emoji was dropped — RotatingFileHandler likely missing encoding='utf-8' "
        "(cp1252 fallback on Windows silently discards records with non-encodable chars)"
    )


def test_log_config_source_declares_utf8_on_file_handler():
    """Source-scan guard: the literal RotatingFileHandler(...) call in
    src/log_config.py must include encoding="utf-8" so future edits don't
    silently regress the behavioral fix above."""
    src = _read("src/log_config.py")
    # Match RotatingFileHandler( ... ) across newlines
    match = re.search(r"RotatingFileHandler\s*\((.*?)\)", src, re.DOTALL)
    assert match, "RotatingFileHandler call not found in src/log_config.py"
    args = match.group(1)
    assert 'encoding="utf-8"' in args or "encoding='utf-8'" in args, (
        "RotatingFileHandler must explicitly pass encoding='utf-8' (#619)"
    )


# ---------------------------------------------------------------------------
# #578 — connect_db migration: journal/store.py + training/versioning.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["src/journal/store.py", "src/training/versioning.py"],
)
def test_uses_connect_db_helper_not_raw_sqlite3(path):
    """#578 — every DB connection in journal/store.py and training/versioning.py
    must go through src.utils.db.connect_db so busy_timeout=30s and
    row_factory=Row apply consistently. Raw sqlite3.connect(...) is a code
    smell that re-introduces the 'database is locked' regression we saw on
    2026-04-19 (118 errors traced to MS Access holding the file lock and
    a writer using the 5s default timeout).
    """
    src = _read(path)
    # Strip the import line — we still need `import sqlite3` at the top
    # for type hints / sqlite3.Row references, but no .connect() calls.
    body_only = re.sub(r"^import sqlite3\b.*$", "", src, flags=re.MULTILINE)
    matches = re.findall(r"\bsqlite3\.connect\b", body_only)
    assert not matches, (
        f"{path} contains {len(matches)} raw sqlite3.connect call(s); "
        f"use connect_db(db_path) from src.utils.db instead (#578)"
    )


@pytest.mark.parametrize(
    "path",
    ["src/journal/store.py", "src/training/versioning.py"],
)
def test_imports_connect_db(path):
    """If a file is migrated to connect_db, it must actually import the helper."""
    src = _read(path)
    assert "from src.utils.db import connect_db" in src, (
        f"{path} must import connect_db from src.utils.db (#578)"
    )


# ---------------------------------------------------------------------------
# #437 + #482 — status string consolidation
# ---------------------------------------------------------------------------


def test_status_sql_helper_exists_and_returns_canonical_constants():
    """The helper must derive its values from TERMINAL_STATUSES /
    ACTIVE_STATUSES, not hardcoded copies. This guards against the helper
    drifting from the canonical constants over time."""
    from src.shadow_trading._status_sql import (
        active_in_clause,
        terminal_in_clause,
    )
    from src.shadow_trading.models import ACTIVE_STATUSES, TERMINAL_STATUSES

    t_frag, t_params = terminal_in_clause()
    a_frag, a_params = active_in_clause()

    assert set(t_params) == set(TERMINAL_STATUSES)
    assert set(a_params) == set(ACTIVE_STATUSES)
    # Placeholder count matches param count (parameterized, not interpolated)
    assert t_frag.count("?") == len(t_params)
    assert a_frag.count("?") == len(a_params)
    # Sorted for stable query-plan / cache-key behavior
    assert list(t_params) == sorted(t_params)
    assert list(a_params) == sorted(a_params)


@pytest.mark.parametrize(
    "path",
    [
        "src/shadow_trading/executor.py",
        "src/shadow_trading/reconcile.py",
        "src/risk/governor.py",
        "src/scheduler/reports.py",
    ],
)
def test_no_hardcoded_status_filter_predicates(path):
    """#437 + #482 — SQL filter predicates that compare shadow_trades.status
    against literal string(s) must use the helper from _status_sql.py.

    Targets the patterns:
      - status = 'closed' / "closed"
      - status='open' / "open"
      - status IN ('open', 'exit_pending')

    Skips:
      - SET status = 'X'  (assignment, not filter)
      - INSERT ... 'X' ... (value, not filter)
      - status="X" as Python kwarg (caught by dataclass init)
      - status ==  Python comparison (not SQL)
    """
    src = _read(path)
    # SQL filter predicates only — must be inside a string literal that
    # contains "WHERE" or "AND" before the status check, OR be an `IN (...)`
    # clause with quoted status values.
    bad_patterns = [
        # `status = 'X'` or `status='X'` (with optional space)
        r"status\s*=\s*['\"](?:closed|open|exit_pending|exit_failed|"
        r"submission_uncertain|pending|rejected|failed|exit_abandoned|"
        r"needs_manual_review)['\"]",
        # `status IN (...)` with literals
        r"status\s+IN\s*\(\s*['\"][a-z_]+['\"]",
    ]
    violations: list[str] = []
    src_lines = src.splitlines()
    for line_no, line in enumerate(src_lines, start=1):
        stripped = line.lstrip()
        # Skip SET status = ... (assignment in UPDATE)
        if re.search(r"\bSET\s+status\s*=", line, re.IGNORECASE):
            continue
        # Skip pure-comment lines and docstring-marker lines. These can
        # legitimately mention status values without being SQL.
        if stripped.startswith("#"):
            continue
        if re.match(r'^\s*"""|^\s*\'\'\'', line):
            continue
        # Skip lines that look like they're inside an active docstring —
        # heuristic: most-recent triple-quote pair is unbalanced (i.e.,
        # this line is between """ and the next """).
        before = "\n".join(src_lines[:line_no - 1])
        triple_double = before.count('"""')
        triple_single = before.count("'''")
        if triple_double % 2 == 1 or triple_single % 2 == 1:
            continue
        for pat in bad_patterns:
            if re.search(pat, line):
                # Only count if the line is part of a SQL string literal
                # (heuristic: it contains SQL keywords or is inside a
                # multi-line string with WHERE/SELECT in the previous
                # ~5 lines)
                window = "\n".join(src_lines[max(0, line_no - 6):line_no])
                if not re.search(
                    r"\b(WHERE|SELECT|FROM|UPDATE|JOIN|AND|OR)\b",
                    window,
                    re.IGNORECASE,
                ):
                    break
                # Escape hatch: a `# STATUS-NARROW:` comment within the
                # preceding 12 lines documents that the literal status is
                # intentionally narrow (e.g., recovery paths that must
                # not broaden). The comment itself can be multi-line, so
                # we look back generously. The comment must explain why.
                escape_window = "\n".join(src_lines[max(0, line_no - 13):line_no])
                if re.search(r"#\s*STATUS-NARROW\s*:", escape_window):
                    break
                violations.append(f"{path}:{line_no}: {line.strip()}")
                break
    assert not violations, (
        f"Found {len(violations)} hardcoded status filter predicate(s) in "
        f"{path}. Use terminal_in_clause() / active_in_clause() from "
        f"src.shadow_trading._status_sql instead (#437, #482):\n"
        + "\n".join(violations)
    )
