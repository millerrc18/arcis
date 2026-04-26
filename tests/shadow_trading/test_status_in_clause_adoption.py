"""Sprint 0 / Wave 1b STATUS-CONST regression guards.

Locks in the migration of `status = 'closed'` / `status = 'open'` literal
filters in `src/shadow_trading/` to the canonical TERMINAL_STATUSES /
ACTIVE_STATUSES helpers from `_status_sql.py`. Pre-fix sites:

  - state.py:27-31 — multi-status SUM CASE undercounted non-`closed`
    terminal statuses (rejected, failed, exit_abandoned,
    needs_manual_review) and non-`open` active statuses (pending,
    exit_pending, exit_failed, submission_uncertain).
  - exit_reconciliation.py:38 — only reconciled literal `'closed'` rows;
    skipped failed/rejected/exit_abandoned/needs_manual_review.
  - reconcile_state.py:28 — health proxy missed reconcile-loop touches
    on submission_uncertain / exit_failed / exit_pending rows.

The two `status = 'open'` sites in `bracket_monitor.py` and the two in
`reconcile.py:247,495` are STATUS-NARROW by design (orphan / bracket
checks must not pick up `pending` / `submission_uncertain` rows the
broker has not received yet). Those sites are EXEMPT from the coverage
guard via the documented `# STATUS-NARROW:` comment, mirroring the
existing escape hatch in tests/test_tier_1_hardening.py.

CLAUDE.md: "Status constants are canonical — use TERMINAL_STATUSES and
ACTIVE_STATUSES from src/shadow_trading/models.py in queries. Never
hardcode `status != 'closed'`."
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHADOW_DIR = ROOT / "src" / "shadow_trading"


# ---------------------------------------------------------------------------
# 1. Coverage test: zero hardcoded SELECT-side `status = 'closed' / 'open'`
# ---------------------------------------------------------------------------


def _shadow_trading_py_files() -> list[pathlib.Path]:
    """Return every .py file directly under src/shadow_trading/."""
    return sorted(p for p in SHADOW_DIR.glob("*.py") if p.is_file())


def _line_in_active_docstring(src_lines: list[str], line_no: int) -> bool:
    """Heuristic: is the 1-indexed line_no inside an unbalanced triple-quote?"""
    before = "\n".join(src_lines[: line_no - 1])
    return before.count('"""') % 2 == 1 or before.count("'''") % 2 == 1


_BAD_PATTERNS = (
    # `status = 'X'` or `status='X'` (with optional spaces)
    re.compile(
        r"status\s*=\s*['\"](?:closed|open|exit_pending|exit_failed|"
        r"submission_uncertain|pending|rejected|failed|exit_abandoned|"
        r"needs_manual_review)['\"]"
    ),
    # `status IN ('X', 'Y')` with literal members
    re.compile(r"status\s+IN\s*\(\s*['\"][a-z_]+['\"]"),
)


def test_no_hardcoded_status_filter_in_shadow_trading():
    """Every `status = 'X'` / `status IN ('X', ...)` in src/shadow_trading/
    that lives inside a SQL string literal must either:
      (a) be migrated to terminal_in_clause() / active_in_clause(), or
      (b) carry a `# STATUS-NARROW:` comment within 12 lines that
          documents why the literal is intentionally narrow.
    """
    violations: list[str] = []
    for path in _shadow_trading_py_files():
        # _status_sql.py is the helper itself — it mentions the canonical
        # values in its docstring/example. Skip.
        if path.name == "_status_sql.py":
            continue
        src = path.read_text(encoding="utf-8")
        src_lines = src.splitlines()
        for line_no, line in enumerate(src_lines, start=1):
            stripped = line.lstrip()
            # Skip pure comments — these can mention status values in prose.
            if stripped.startswith("#"):
                continue
            # Skip docstring-marker-only lines.
            if re.match(r'^\s*"""|^\s*\'\'\'', line):
                continue
            # Skip lines inside an active docstring.
            if _line_in_active_docstring(src_lines, line_no):
                continue
            # Skip `SET status = 'X'` (UPDATE assignment, not a filter).
            if re.search(r"\bSET\s+status\s*=", line, re.IGNORECASE):
                continue
            for pat in _BAD_PATTERNS:
                if pat.search(line):
                    # Window: must look like SQL (WHERE / SELECT / FROM /
                    # AND / OR / UPDATE / JOIN within ~5 prior lines).
                    window = "\n".join(src_lines[max(0, line_no - 6) : line_no])
                    if not re.search(
                        r"\b(WHERE|SELECT|FROM|UPDATE|JOIN|AND|OR)\b",
                        window,
                        re.IGNORECASE,
                    ):
                        break
                    # Documented escape hatch: STATUS-NARROW within 12 lines.
                    escape_window = "\n".join(
                        src_lines[max(0, line_no - 13) : line_no]
                    )
                    if re.search(r"#\s*STATUS-NARROW\s*:", escape_window):
                        break
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{line_no}: "
                        f"{line.strip()}"
                    )
                    break

    assert not violations, (
        f"Found {len(violations)} hardcoded SELECT-side status filter(s) in "
        "src/shadow_trading/. Migrate to terminal_in_clause() / "
        "active_in_clause() from src.shadow_trading._status_sql, or document "
        "with `# STATUS-NARROW:` comment within 12 lines:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. Behavioral test for state.py — full TERMINAL/ACTIVE vocabulary counted
# ---------------------------------------------------------------------------


def _create_shadow_trades_table(conn: sqlite3.Connection) -> None:
    """Minimal shadow_trades schema sufficient for the cohort-count query."""
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            quarantined INTEGER DEFAULT 0,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def _insert_minimal(conn: sqlite3.Connection, trade_id: str, status: str,
                    quarantined: int = 0, updated_at: str | None = None) -> None:
    if updated_at is None:
        updated_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, ticker, status, quarantined, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (trade_id, "AAPL", status, quarantined, updated_at),
    )
    conn.commit()


def test_state_cohort_counts_full_terminal_and_active_vocabulary(tmp_path, monkeypatch):
    """Pre-fix this test would FAIL: literal `status='open'` and `status='closed'`
    miss `pending` / `exit_pending` / `exit_failed` / `submission_uncertain`
    in the open bucket and `rejected` / `failed` / `exit_abandoned` /
    `needs_manual_review` in the closed bucket.
    """
    from src.shadow_trading.models import ACTIVE_STATUSES, TERMINAL_STATUSES

    db_file = tmp_path / "test_state_cohort.sqlite3"
    with sqlite3.connect(db_file) as conn:
        _create_shadow_trades_table(conn)
        # Insert ONE row per active status and ONE row per terminal status
        active_sorted = sorted(ACTIVE_STATUSES)
        terminal_sorted = sorted(TERMINAL_STATUSES)
        idx = 0
        for s in active_sorted:
            _insert_minimal(conn, f"a{idx}", s)
            idx += 1
        for s in terminal_sorted:
            _insert_minimal(conn, f"t{idx}", s)
            idx += 1
        # Plus one quarantined active row to verify the COALESCE bucket.
        _insert_minimal(conn, "qx", "open", quarantined=1)

    # Re-import state.py with patched DB_PATH so the module-level
    # sqlite3.connect(DB_PATH) call hits our temp DB.
    monkeypatch.setattr("src.shadow_trading.state.DB_PATH", str(db_file))
    from src.shadow_trading.state import _shadow_cohort_counts

    result = _shadow_cohort_counts()
    assert "value" in result, f"got error result: {result!r}"
    counts = result["value"]

    # All active statuses counted in `open`. All terminal statuses counted
    # in `closed`. Pre-fix `open` would equal 1 (just `open`) and `closed`
    # would equal 1 (just `closed`).
    expected_open = len(active_sorted) + 1  # +1 for the quarantined `open`
    expected_closed = len(terminal_sorted)
    expected_total = expected_open + expected_closed
    assert counts["open"] == expected_open, (
        f"open bucket undercounted: got {counts['open']}, expected "
        f"{expected_open} (all ACTIVE_STATUSES + 1 quarantined). Pre-fix "
        f"this would be 2 (just literal 'open' rows)."
    )
    assert counts["closed"] == expected_closed, (
        f"closed bucket undercounted: got {counts['closed']}, expected "
        f"{expected_closed} (all TERMINAL_STATUSES). Pre-fix this would "
        f"be 1 (just literal 'closed' row)."
    )
    assert counts["quarantined"] == 1
    assert counts["total"] == expected_total


# ---------------------------------------------------------------------------
# 3. Behavioral test for exit_reconciliation.py — all terminal trades scanned
# ---------------------------------------------------------------------------


def _create_full_shadow_trades_table(conn: sqlite3.Connection) -> None:
    """The exit_reconciliation query reads more columns; create the
    superset schema used by the existing tests/scheduler/test_exit_reconciliation.py.
    """
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            exit_reason TEXT,
            actual_exit_time TEXT,
            actual_exit_price REAL,
            actual_entry_time TEXT,
            actual_entry_price REAL,
            entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            target_2 REAL,
            duration_days INTEGER,
            timeout_days INTEGER,
            direction TEXT DEFAULT 'long',
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()


def _now_iso(offset_hours: float = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=offset_hours)
    return dt.isoformat()


def _insert_terminal_row(conn: sqlite3.Connection, trade_id: str, status: str,
                         exit_reason: str = "stop_loss") -> None:
    """Insert a terminal-status row that should appear in the 24h window."""
    conn.execute(
        """
        INSERT INTO shadow_trades (
            trade_id, ticker, status, exit_reason, actual_exit_time,
            actual_exit_price, actual_entry_time, actual_entry_price,
            entry_price, stop_price, target_1, target_2,
            duration_days, timeout_days, direction, quarantined
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade_id, "AAPL", status, exit_reason,
            _now_iso(1),     # exit 1h ago = inside 24h window
            105.0,           # actual_exit_price triggers stop_loss anomaly
            _now_iso(25),
            100.0,
            100.0,
            96.0,            # stop_price; with exit_price=105 anomalous (>96.96)
            110.0,
            120.0,
            1, 15, "long", 0,
        ),
    )
    conn.commit()


def test_exit_reconciliation_scans_all_terminal_statuses():
    """Pre-fix `WHERE status = 'closed'` would skip `rejected`, `failed`,
    `exit_abandoned`, and `needs_manual_review` rows even when their
    actual_exit_time is inside the 24h window. After fix, all
    TERMINAL_STATUSES are scanned and anomaly counts include them.

    Behavioral assertion: insert ONE anomalous stop_loss row per terminal
    status. Expect `total_closed` to equal len(TERMINAL_STATUSES) and
    `anomaly_count` to equal the same.
    """
    from src.shadow_trading.exit_reconciliation import run_exit_reconciliation
    from src.shadow_trading.models import TERMINAL_STATUSES

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_full_shadow_trades_table(conn)

    terminal_sorted = sorted(TERMINAL_STATUSES)
    for i, s in enumerate(terminal_sorted):
        _insert_terminal_row(conn, f"x{i}", s, exit_reason="stop_loss")

    result = run_exit_reconciliation(conn=conn)

    # Pre-fix: total_closed would be 1 (just the literal 'closed' row).
    assert result["total_closed"] == len(terminal_sorted), (
        f"total_closed {result['total_closed']} != len(TERMINAL_STATUSES) "
        f"{len(terminal_sorted)}. Pre-fix this was 1 — only literal 'closed' "
        f"rows passed the filter."
    )
    assert result["anomaly_count"] == len(terminal_sorted)
    # Each row should be flagged because exit_price=105 > 96 * 1.01.
    flagged_set = set(result["flagged_trade_ids"])
    expected_set = {f"x{i}" for i in range(len(terminal_sorted))}
    assert flagged_set == expected_set


# ---------------------------------------------------------------------------
# 4. Behavioral test for reconcile_state.py — broadened proxy
# ---------------------------------------------------------------------------


def test_reconcile_state_health_proxy_picks_up_non_open_active_rows(tmp_path, monkeypatch):
    """Pre-fix `MAX(updated_at) WHERE status='open'` would return None when
    the only active rows were `submission_uncertain` / `exit_pending` /
    `exit_failed`, even though the reconcile loop just touched them.
    After fix, the proxy uses ACTIVE_STATUSES and surfaces the loop
    activity correctly.
    """
    db_file = tmp_path / "test_reconcile_state.sqlite3"
    with sqlite3.connect(db_file) as conn:
        _create_shadow_trades_table(conn)
        # Only non-`open` active rows exist — pre-fix this returned None.
        recent_ts = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        _insert_minimal(conn, "u1", "submission_uncertain", updated_at=recent_ts)
        _insert_minimal(conn, "u2", "exit_failed", updated_at=recent_ts)

    monkeypatch.setattr("src.shadow_trading.reconcile_state.DB_PATH", str(db_file))
    from src.shadow_trading.reconcile_state import _most_recent_reconcile_touch

    most_recent = _most_recent_reconcile_touch()
    assert most_recent == recent_ts, (
        f"reconcile-state proxy missed non-`open` active rows: got "
        f"{most_recent!r}, expected {recent_ts!r}. Pre-fix this returned "
        f"None because the proxy hardcoded `status='open'`."
    )
