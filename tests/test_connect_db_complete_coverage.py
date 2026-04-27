"""Sprint 0.C / C.1: every src/* + scripts/* sqlite3.connect site must
either route through src.utils.db.connect_db OR be on the allowlist.

Allowlist entries must include a comment explaining why."""

import re
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

# (file, line_no, reason) tuples — each entry requires an explicit reason
_ALLOWLIST: list[tuple[str, int, str]] = [
    ("src/utils/db.py", 41, "definition site — this IS connect_db()"),
    # scheduler/watch.py: _backup_database uses .backup() API which requires two raw
    # connections opened simultaneously (src and dst). connect_db returns a single conn;
    # the Online Backup API must hold both connections at once.
    ("src/scheduler/watch.py", 1059, "backup API: src conn for sqlite3.backup() — needs raw pair"),
    ("src/scheduler/watch.py", 1060, "backup API: dst conn for sqlite3.backup() — needs raw pair"),
    # schema/sqlite.py: retry-index path opens a short-lived raw conn inside a low-level
    # schema bootstrap function. The conn.close() call pattern is intentional for this
    # immediate-commit-and-close index-creation path; connect_db context manager would
    # suppress the OperationalError on __exit__ differently.
    ("src/schema/sqlite.py", 166, "schema bootstrap retry-index path — short-lived raw conn for index CREATE IF NOT EXISTS"),
    # src/features/engine_helpers.py:61 is a comment explaining why connect_db is used
    # (referencing the old raw sqlite3.connect pattern for historical context).
    ("src/features/engine_helpers.py", 61, "comment text referencing old sqlite3.connect pattern — not a live call"),
    # scripts/archive_bootcamp_2026_04_24.py: uses URI mode (mode=ro, mode=rw) which
    # connect_db does not support. Read-only and URI-format connections are intentional.
    ("scripts/archive_bootcamp_2026_04_24.py", 187, "URI mode=ro — connect_db does not support uri=True"),
    ("scripts/archive_bootcamp_2026_04_24.py", 224, "URI mode=ro — connect_db does not support uri=True"),
    ("scripts/archive_bootcamp_2026_04_24.py", 354, "URI mode=ro — connect_db does not support uri=True"),
    ("scripts/archive_bootcamp_2026_04_24.py", 395, "archive script: migrates legacy DB, short-lived one-off tool"),
    ("scripts/archive_bootcamp_2026_04_24.py", 529, "creates empty stub DB for test fixture — intentional init"),
    ("scripts/archive_bootcamp_2026_04_24.py", 548, "URI mode=ro — connect_db does not support uri=True"),
    # scripts/recover_from_postgres.py: line 207 is a string literal inside print()
    # showing the operator how to verify manual recovery — not a live call site.
    ("scripts/recover_from_postgres.py", 207, "string literal in print() — operator help text, not a live call"),
    # src/sync/render_sync.py: all sqlite3.connect calls use explicit timeout=10 (intentional
    # 10s cap for the sync daemon — shorter than connect_db's 30s default to avoid
    # blocking the background sync thread during write bursts). The _sqlite_conn helper
    # wraps this pattern; direct calls inside fetch/push helpers follow #258 design.
    ("src/sync/render_sync.py", 81, "sync daemon helper: intentional 10s timeout to avoid blocking background thread"),
    ("src/sync/render_sync.py", 142, "#258: intentional 10s busy timeout for sync fetch helper"),
    ("src/sync/render_sync.py", 167, "#258: intentional 10s busy timeout for sync fetch helper"),
    ("src/sync/render_sync.py", 195, "#258: intentional 10s busy timeout for sync fetch helper"),
    ("src/sync/render_sync.py", 213, "#258: intentional 10s busy timeout for sync fetch helper"),
    ("src/sync/render_sync.py", 574, "#258: intentional 10s busy timeout for sync pull_commands helper"),
    ("src/sync/render_sync.py", 623, "#258: intentional 10s busy timeout for sync pull_commands helper"),
    # scripts/statusline.py: intentionally uses a short 2s timeout for a non-blocking
    # terminal status bar display. connect_db default is 30s which would block the shell.
    ("scripts/statusline.py", 154, "intentional 2s timeout for non-blocking terminal status bar"),
    # scripts/cleanup_overshoot_zombies_2026_04_21.py: explicit 30s timeout, one-off
    # cleanup script for a specific incident — not part of production code path.
    ("scripts/cleanup_overshoot_zombies_2026_04_21.py", 187, "one-off cleanup script with explicit 30s timeout matching connect_db default"),
    ("scripts/cleanup_overshoot_zombies_2026_04_21.py", 219, "one-off cleanup script with explicit 30s timeout matching connect_db default"),
    # scripts/reconcile_2026_04_20.py: explicit 30s timeout, one-off reconcile script.
    ("scripts/reconcile_2026_04_20.py", 149, "one-off reconcile script with explicit 30s timeout matching connect_db default"),
    # scripts/scrub_validation_leaks.py: explicit 10s timeout, one-off data-scrub script.
    ("scripts/scrub_validation_leaks.py", 27, "one-off data-scrub script with explicit 10s timeout"),
    # scripts/archive_bootcamp_2026_04_24.py line 508: comment text inside a docstring
    # that mentions sqlite3.connect as part of documentation — not a live call.
    ("scripts/archive_bootcamp_2026_04_24.py", 508, "comment/docstring text mentioning sqlite3.connect — not a live call"),
    # scripts/recover_from_postgres.py: uses raw connect then immediately sets WAL mode
    # (PRAGMA journal_mode=WAL) and a conservative 5s busy_timeout for the recovery
    # import loop. The 5s timeout is intentionally shorter than connect_db's 30s to
    # avoid blocking during the long sequential row-by-row import from Postgres.
    ("scripts/recover_from_postgres.py", 96, "recovery script: WAL mode setup + intentional 5s busy_timeout (shorter than connect_db 30s) for long Postgres import loop"),
]


def _scan_raw_connect_sites():
    """Yield (filepath, line_no, line_text) for every raw sqlite3.connect."""
    for py in REPO.rglob("*.py"):
        # Compute path relative to REPO to apply directory filters correctly.
        try:
            rel_parts = py.relative_to(REPO).parts
        except ValueError:
            continue
        if any(p in rel_parts for p in ("__pycache__", ".venv", "tests")):
            continue
        try:
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bsqlite3\.connect\b", line):
                    yield (str(py.relative_to(REPO)).replace("\\", "/"), i, line.strip())
        except UnicodeDecodeError:
            continue


def test_no_raw_sqlite3_connect_outside_allowlist():
    sites = list(_scan_raw_connect_sites())
    allowed = {(f, ln) for f, ln, _ in _ALLOWLIST}
    violations = [(f, ln, line) for f, ln, line in sites if (f, ln) not in allowed]
    if violations:
        msg = f"{len(violations)} raw sqlite3.connect sites outside allowlist:\n" + "\n".join(
            f"  {f}:{ln}  {line}" for f, ln, line in violations[:40]
        )
        pytest.fail(msg)
