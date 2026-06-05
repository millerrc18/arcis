"""Sprint 0.C / C.1: every src/* + scripts/* sqlite3.connect site must
either route through src.utils.db.connect_db OR be on the allowlist.

Allowlist entries are CONTENT-KEYED — (file, code_snippet, reason) — not
line-pinned. A site is allowed when its file matches and the snippet is a
substring of the line. This deliberately replaces the old (file, line_no)
allowlist, which drifted RED on every unrelated edit to a scanned file
(reference: line-pinned-allowlist-fragility; #1192). Editing code elsewhere in
a file no longer shifts these entries; only changing the actual sqlite3.connect
call text requires a re-review (which is correct). `test_no_dead_allowlist_entries`
guards the other direction — every entry must still match a real site, so the
allowlist cannot rot (this is how the old `engine_helpers.py:61` entry went
stale and dead).

Each entry requires an explicit reason. Snippets are chosen to be distinctive
within their file.
"""

import re
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

# (file, snippet, reason) — snippet is a distinctive substring of the
# sqlite3.connect line; matched as a substring so unrelated edits don't drift it.
_ALLOWLIST: list[tuple[str, str, str]] = [
    # src/utils/db.py: connect_db() itself — the definition site.
    ("src/utils/db.py", "call sqlite3.connect directly", "definition site — docstring comment referencing sqlite3.connect"),
    ("src/utils/db.py", "sqlite3.connect(effective_path, timeout=BUSY_TIMEOUT_MS", "definition site — connect_db() SQLite path(s) (force_sqlite + normal)"),
    # scheduler/watch.py: _backup_database uses the Online Backup API, which needs two
    # raw connections (src + dst) held simultaneously; connect_db returns a single conn.
    ("src/scheduler/watch.py", "src = sqlite3.connect(DB_PATH)", "backup API: src conn for sqlite3.backup() — needs raw pair"),
    ("src/scheduler/watch.py", "dst = sqlite3.connect(str(backup_path))", "backup API: dst conn for sqlite3.backup() — needs raw pair"),
    # schema/sqlite.py: the explicit SQLite-engine entry points (bypass PG shim by design).
    ("src/schema/sqlite.py", "sqlite3.connect(db_path, timeout=30.0)", "_sqlite_only_connect definition — SQLite-only entry point bypasses PG shim by design"),
    ("src/schema/sqlite.py", "conn_retry = sqlite3.connect(db_path)", "schema bootstrap retry-index path — short-lived raw conn for index CREATE IF NOT EXISTS"),
    # src/tools/tradingstate/core.py: explicit SQLite fallback snapshot (tools-layer).
    ("src/tools/tradingstate/core.py", "sqlite3.connect(str(sqlite_path), timeout=5)", "SQLite fallback snapshot — tools-layer explicit fallback path with intentional 5s timeout"),
    # scripts/_clean_slate/sqlite_retire.py: archive-then-empty of the legacy SQLite DB
    # during the clean-slate wipe (#95). URI mode=ro for the read-only archive check;
    # raw connect for the one-off archive copy + the live source conn.
    ("scripts/_clean_slate/sqlite_retire.py", 'sqlite3.connect(f"file:{db_path}?mode=ro"', "clean-slate retire: URI mode=ro read-only archive check — connect_db does not support uri=True"),
    ("scripts/_clean_slate/sqlite_retire.py", "sqlite3.connect(str(src))", "clean-slate retire: one-off archive copy + live source conn for archive-then-empty"),
    # scripts/archive_bootcamp_2026_04_24.py: legacy-DB archive tool — URI ro + one-offs.
    ("scripts/archive_bootcamp_2026_04_24.py", 'sqlite3.connect(f"file:{source_path}?mode=ro"', "URI mode=ro — connect_db does not support uri=True"),
    ("scripts/archive_bootcamp_2026_04_24.py", 'sqlite3.connect(f"file:{db_path}?mode=ro"', "URI mode=ro — connect_db does not support uri=True"),
    ("scripts/archive_bootcamp_2026_04_24.py", "sqlite3.connect(str(source_path))", "archive script: migrates legacy DB, short-lived one-off tool"),
    ("scripts/archive_bootcamp_2026_04_24.py", "with sqlite3.connect(...)", "comment/docstring text mentioning sqlite3.connect — not a live call"),
    ("scripts/archive_bootcamp_2026_04_24.py", "sqlite3.connect(str(fresh_path)).close()", "creates empty stub DB for test fixture — intentional init"),
    ("scripts/archive_bootcamp_2026_04_24.py", 'sqlite3.connect(f"file:{fresh_path}?mode=ro"', "URI mode=ro verify — connect_db does not support uri=True"),
    # scripts/recover_from_postgres.py: recovery import loop + operator help text.
    ("scripts/recover_from_postgres.py", "sq = sqlite3.connect(LOCAL_DB)", "recovery script: WAL mode setup + intentional 5s busy_timeout for long Postgres import loop"),
    ("scripts/recover_from_postgres.py", "c=sqlite3.connect('", "string literal in print() — operator help text, not a live call"),
    # scripts/statusline.py: non-blocking terminal status bar — short 2s timeout.
    ("scripts/statusline.py", "sqlite3.connect(str(DB), timeout=2)", "intentional 2s timeout for non-blocking terminal status bar"),
    # one-off incident / maintenance scripts (not production code path).
    ("scripts/cleanup_overshoot_zombies_2026_04_21.py", "sqlite3.connect(args.db, timeout=30.0)", "one-off cleanup script with explicit 30s timeout matching connect_db default"),
    ("scripts/reconcile_2026_04_20.py", "sqlite3.connect(db_path, timeout=30)", "one-off reconcile script with explicit 30s timeout matching connect_db default"),
    ("scripts/scrub_validation_leaks.py", "sqlite3.connect(db_path, timeout=10)", "one-off data-scrub script with explicit 10s timeout"),
    # audit / diagnostic / migration scripts: URI ro inspection or one-way migration.
    ("scripts/audit_db_sync.py", "sqlite3.connect(_sqlite_ro_uri(db_path)", "audit script: URI mode=ro — connect_db does not support uri=True"),
    ("scripts/audit_schema_drift.py", "conn = sqlite3.connect(db_path)", "one-off schema audit script — direct sqlite_master introspection"),
    ("scripts/sqlite_to_pg_migrate.py", "sqlite3.connect(sqlite_path)", "migration script: opens source SQLite for one-way Postgres migration"),
    ("scripts/sqlite_to_pg_migrate.py", "sqlite3.connect(source_path)", "migration script: opens source SQLite for one-way Postgres migration"),
    ("logs/cutover-smoke-monitor.py", 'sqlite3.connect(f"file:{SQLITE}?mode=ro"', "monitoring script: URI mode=ro — connect_db does not support uri=True"),
    ("scripts/diagnostics/attribution_readout.py", 'sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro"', "diagnostic script: URI mode=ro — connect_db does not support uri=True"),
]


def _scan_raw_connect_sites():
    """Yield (filepath, line_no, line_text) for every raw sqlite3.connect."""
    for py in REPO.rglob("*.py"):
        # Compute path relative to REPO to apply directory filters correctly.
        try:
            rel_parts = py.relative_to(REPO).parts
        except ValueError:
            continue
        if any(p in rel_parts for p in ("__pycache__", ".venv", "tests", ".claude")):
            continue
        try:
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bsqlite3\.connect\b", line):
                    yield (str(py.relative_to(REPO)).replace("\\", "/"), i, line.strip())
        except UnicodeDecodeError:
            continue


def _is_allowed(filepath: str, line_text: str) -> bool:
    return any(
        filepath == af and snippet in line_text
        for af, snippet, _reason in _ALLOWLIST
    )


def test_no_raw_sqlite3_connect_outside_allowlist():
    sites = list(_scan_raw_connect_sites())
    violations = [
        (f, ln, line) for f, ln, line in sites if not _is_allowed(f, line)
    ]
    if violations:
        msg = f"{len(violations)} raw sqlite3.connect sites outside allowlist:\n" + "\n".join(
            f"  {f}:{ln}  {line}" for f, ln, line in violations[:40]
        )
        pytest.fail(msg)


def test_no_dead_allowlist_entries():
    """Every allowlist entry must still match at least one real site — prevents
    the allowlist from rotting (how the old engine_helpers.py:61 entry went dead
    after its source line changed)."""
    sites = list(_scan_raw_connect_sites())
    dead = []
    for af, snippet, _reason in _ALLOWLIST:
        if not any(af == f and snippet in line for f, _ln, line in sites):
            dead.append(f"{af}  ::  {snippet!r}")
    if dead:
        pytest.fail(
            f"{len(dead)} allowlist entries match no live sqlite3.connect site "
            f"(stale — remove or fix):\n" + "\n".join(f"  {d}" for d in dead)
        )
