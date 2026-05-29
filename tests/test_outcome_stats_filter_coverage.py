"""Static-analysis test: enforce outcome_stats_filter_sql on shadow_trades outcome aggregations.

Background:
    Wave 4 H5 (PR #933) expanded outcome_stats_filter_sql() to many sibling sites in src/.
    Post-merge sweeps found the expansion was still incomplete — most recently issue #482
    found sites in src/scheduler/reports.py. This test catches such regressions at PR-time
    via static text scan rather than a 4th sibling-search round.

    The canonical filter (outcome_stats_filter_sql from src/shadow_trading/exit_reason.py)
    excludes rows with exit_reason='reconciled_stale' (synthetic closures that have no real
    broker fill and pnl_dollars=0). Including these rows in win-rate, pnl-sum, or expectancy
    computations corrupts outcome statistics.

Detection logic:
    Scan each .execute() call block in src/ Python files. Flag blocks that:
      1. Contain FROM shadow_trades
      2. Contain an outcome-stat aggregation: SUM or AVG on pnl_dollars or pnl_pct,
         or SUM(CASE WHEN pnl_dollars ...) win-count pattern
      3. Do NOT contain outcome_stats_filter_sql
      4. Do NOT query only active/open positions (reconciled_stale is terminal-only)

    Uses paren-depth tracking to isolate each .execute() call from its neighbours,
    preventing false positives from adjacent queries in the same function.

Allowlist:
    Some sites legitimately compute financial metrics on terminal rows WITHOUT needing the
    outcome-stats filter — drawdown calculations, equity-curve tracking, risk-governor loss
    limits, and intraday P&L displays. These are explicitly allow-listed below with rationale.
    Any NEW exemption must be added here with a PR citation, not left unannotated.

    Alternatively, add a  # outcome-stats-filter: exempt-<reason>  comment near the FROM
    shadow_trades line in the source file to suppress detection for that site.

Operator memory ref: feedback_review_sibling_search — when a bug is found at file:line,
grep the file for the same anti-pattern at other lines.

Called by: CI test suite (test/outcome-stats-filter-coverage-enforcement)
Calls: none (static scan — no imports from src/)
Owns tables: none
Config keys: none
Tests: self
"""
from __future__ import annotations

import re
import tempfile
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Matches FROM shadow_trades (case-insensitive)
_FROM_SHADOW = re.compile(r"FROM\s+shadow_trades", re.IGNORECASE)

# Marks the start of an .execute( call
_EXECUTE_START = re.compile(r"\.execute\s*\(")

# Outcome-stat aggregation patterns on pnl_dollars or pnl_pct.
# These aggregate real financial outcomes and MUST exclude reconciled_stale rows.
#   SUM(pnl_dollars), COALESCE(SUM(pnl_dollars), ...), AVG(pnl_dollars), AVG(pnl_pct)
#   SUM(CASE WHEN pnl_dollars ...) — win-count pattern
_OUTCOME_STAT_AGG = re.compile(
    r"\b(?:SUM|AVG)\s*\(\s*(?:COALESCE\s*\(\s*)?(?:pnl_dollars|pnl_pct)"
    r"|SUM\s*\(\s*CASE\s+WHEN\s+pnl_dollars",
    re.IGNORECASE,
)

# The canonical filter call
_FILTER_CALL = re.compile(r"outcome_stats_filter_sql", re.IGNORECASE)

# Active-only patterns: queries restricted to open/active positions don't need the filter
# because reconciled_stale is a terminal exit_reason and can only appear in closed rows.
#   - literal status='open'
#   - use of _a_frag variable (from active_in_clause())
_ACTIVE_ONLY = re.compile(
    r"status\s*=\s*['\"]open['\"]"  # hardcoded status='open'
    r"|_a_frag",                     # parameterised active_in_clause() reference
    re.IGNORECASE,
)

# Exempt-marker comment: place near the FROM shadow_trades line to suppress this check.
# Use: # outcome-stats-filter: exempt-<reason>
_EXEMPT_MARKER = re.compile(r"#\s*outcome-stats-filter\s*:\s*exempt", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Explicit allow-list for sites that don't need the filter for legitimate reasons.
# Format: ("path/relative/to/repo/root", line_number_of_FROM_shadow_trades, "rationale")
# Line numbers are 1-based and refer to the FROM shadow_trades line.
# ---------------------------------------------------------------------------
ALLOWLIST: list[tuple[str, int, str]] = [
    # risk/governor.py — compute_equity_from_trades():
    # SUM(pnl_dollars) to derive current equity (starting_capital + total_pnl).
    # Equity accounting must reflect ALL bookkeeping closures including synthetic stale ones
    # — skipping them would silently undercount drawdown. Task #482 owns the fix decision.
    ("src/risk/governor.py", 394, "#482: equity curve includes all terminal rows by design"),

    # risk/governor.py — check_trade() intraday loss-limit guard:
    # SUM(pnl_dollars) filtered to today's trades for intraday realized-loss limit.
    # The loss limit is a risk guard, not an outcome stat. Needs all today's realized P&L
    # including synthetic closures to avoid false negatives in the risk governor.
    # Task #482 owns the fix decision.
    ("src/risk/governor.py", 906, "#482: intraday loss-limit guard needs all today's realized P&L"),

    # scheduler/reports.py — send_weekly_digest() win-rate + expectancy query:
    # Uses terminal_in_clause() and AVG(pnl_dollars). Missing filter — task #482 scope.
    ("src/scheduler/reports.py", 670, "#482: weekly digest win-rate/expectancy — filter missing, tracked in #482"),

    # scheduler/reports.py — send_weekly_digest() paper P&L sum:
    # SUM(pnl_dollars) for this week's paper trades. Missing filter — task #482 scope.
    ("src/scheduler/reports.py", 692, "#482: weekly digest paper pnl sum — filter missing, tracked in #482"),

    # scheduler/reports.py — send_weekly_digest() live P&L sum:
    # SUM(pnl_dollars) for this week's live trades. Missing filter — task #482 scope.
    ("src/scheduler/reports.py", 699, "#482: weekly digest live pnl sum — filter missing, tracked in #482"),

    # scheduler/watch.py — _get_live_stats() today-pnl banner display:
    # SUM(pnl_dollars) for today's closed P&L in the console banner.
    # Intraday display intentionally shows all closed P&L including synthetic closures
    # so the operator sees the full accounting picture. Task #482 owns the fix decision.
    ("src/scheduler/watch.py", 776, "#482: watch banner today-pnl display — all closures intentional"),

    # scheduler/watch.py — telegram daily summary notification:
    # SUM(pnl_dollars) for today_pnl sent to Telegram. Same rationale as watch.py:776.
    ("src/scheduler/watch.py", 2049, "#482: telegram daily summary pnl — all closures intentional"),

    # shadow_trading/executor.py — drawdown-adjusted risk — outer SUM:
    # SUM(pnl_dollars) to compute current equity for drawdown percentage.
    # Drawdown accounting MUST include all closures (including synthetic stale ones) to avoid
    # silently understating drawdown depth. Financial accounting context, not outcome reporting.
    ("src/shadow_trading/executor.py", 698, "drawdown calc includes all closures by design — understating DD is worse"),

    # shadow_trading/executor.py — drawdown window function inner FROM:
    # Second FROM shadow_trades in the same drawdown block (the MAX(running_pnl) window query).
    # Same rationale as executor.py:698.
    ("src/shadow_trading/executor.py", 706, "drawdown window-func inner FROM — same drawdown block as line 698"),

    # shadow_trading/reconciliation_engine.py — _check_close_milestones() expectancy notification:
    # AVG(pnl_dollars) computed for 1/10/25/50-trade milestone Telegram notifications.
    # Missing filter — task #482 scope. These milestone messages are informational;
    # they report to the operator after a milestone trade count is reached.
    # Previously in executor.py (line 2836) before refactor into reconciliation_engine.py.
    ("src/shadow_trading/reconciliation_engine.py", 161, "#482: milestone notification expectancy — filter missing, tracked in #482"),
]

# Build O(1) lookup: (posix_rel_path, line_no)
_ALLOWLIST_SET: set[tuple[str, int]] = {
    (str(Path(rel).as_posix()), lineno) for rel, lineno, _ in ALLOWLIST
}


# ---------------------------------------------------------------------------
# Scanner helpers
# ---------------------------------------------------------------------------

def _iter_execute_blocks(lines: list[str]):
    """Yield (start_lineno_1based, block_text) for each .execute( call block.

    Tracks parenthesis depth to isolate each execute() call from its neighbours
    in the same function, preventing cross-query false positives.

    The yielded block_text includes up to 4 lines before the .execute( call so that
    exempt-marker comments placed immediately above the call are included in the check.
    """
    i = 0
    while i < len(lines):
        m = _EXECUTE_START.search(lines[i])
        if not m:
            i += 1
            continue

        depth = 0
        start_lineno = i + 1  # 1-based (points to the .execute( line itself)
        block_lines: list[str] = []
        j = i
        while j < len(lines) and j < i + 35:  # cap at 35 lines per block
            line = lines[j]
            for ch in line:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth <= 0:
                        break
            block_lines.append(line)
            if depth <= 0:
                break
            j += 1

        # Prepend up to 4 lines before the execute call for exempt-marker detection
        prefix_start = max(0, i - 4)
        prefix_lines = lines[prefix_start:i]
        full_block_text = "\n".join(prefix_lines + block_lines)
        yield start_lineno, full_block_text, block_lines
        i = j + 1


def _scan_src_for_violations(src_root: Path) -> list[tuple[str, int, str]]:
    """Walk src_root and return list of (rel_path_posix, line_no, snippet) violations.

    A violation is an .execute() call block that:
    - Queries FROM shadow_trades
    - Contains an outcome-stat aggregation (SUM/AVG on pnl_dollars or pnl_pct)
    - Does NOT call outcome_stats_filter_sql
    - Is NOT restricted to active/open positions
    - Is NOT in the ALLOWLIST
    - Does NOT have an exempt-marker comment
    """
    violations: list[tuple[str, int, str]] = []

    for py_file in sorted(src_root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            source_lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        rel_posix = py_file.relative_to(src_root.parent).as_posix()

        for start_lineno, block_text, execute_block_lines in _iter_execute_blocks(source_lines):
            if not _FROM_SHADOW.search(block_text):
                continue
            if not _OUTCOME_STAT_AGG.search(block_text):
                continue
            if _FILTER_CALL.search(block_text):
                continue
            if _ACTIVE_ONLY.search(block_text):
                continue
            if _EXEMPT_MARKER.search(block_text):
                continue

            # Find which line in the execute block (not prefix) has FROM shadow_trades
            from_offset = 0
            for k, bline in enumerate(execute_block_lines):
                if _FROM_SHADOW.search(bline):
                    from_offset = k
                    break

            from_lineno = start_lineno + from_offset
            if (rel_posix, from_lineno) in _ALLOWLIST_SET:
                continue

            snippet = (
                execute_block_lines[from_offset]
                if from_offset < len(execute_block_lines) else ""
            ).strip()[:120]
            violations.append((rel_posix, from_lineno, snippet))

    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_shadow_trades_outcome_aggregations_use_filter():
    """No shadow_trades outcome-stat aggregation in src/ may omit outcome_stats_filter_sql.

    If this test fails, either:
      a) Add outcome_stats_filter_sql() to the query (preferred — closes the bug), OR
      b) Add the site to ALLOWLIST in this test file with a rationale comment + issue cite.
      c) Add a  # outcome-stats-filter: exempt-<reason>  comment near the FROM line.

    Do NOT weaken this test or add catch-all exemptions.
    """
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"

    violations = _scan_src_for_violations(src_root)

    if violations:
        lines = [
            "shadow_trades outcome aggregations missing outcome_stats_filter_sql():",
            "",
        ]
        for rel_path, line_no, snippet in violations:
            lines.append(f"  {rel_path}:{line_no}: {snippet}")
        lines += [
            "",
            "Fix: add outcome_stats_filter_sql() to each query, OR add an ALLOWLIST entry",
            "in tests/test_outcome_stats_filter_coverage.py with a rationale comment.",
        ]
        raise AssertionError("\n".join(lines))


def test_scanner_catches_regression_fixture():
    """The scanner must detect a synthetic violation in an inline fixture.

    This test verifies the detection logic is not vacuously true — a file
    containing a FROM shadow_trades + SUM(pnl_dollars) without the filter
    must appear in the violations list.
    """
    # Synthetic violation: outcome-stat aggregation on closed rows without filter
    bad_code = textwrap.dedent("""
        import sqlite3
        def get_stats(conn):
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "AVG(pnl_dollars) as expectancy "
                "FROM shadow_trades WHERE status = 'closed' "
                "AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            return row
    """)

    # Compliant code: same query WITH the filter
    good_code = textwrap.dedent("""
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        import sqlite3
        def get_stats(conn):
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "AVG(pnl_dollars) as expectancy "
                f"FROM shadow_trades WHERE status = 'closed' "
                f"AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            ).fetchone()
            return row
    """)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        src_fake = tmp_root / "src" / "fake_module"
        src_fake.mkdir(parents=True)
        (src_fake / "bad_query.py").write_text(bad_code, encoding="utf-8")
        (src_fake / "good_query.py").write_text(good_code, encoding="utf-8")

        violations = _scan_src_for_violations(tmp_root / "src")

    violation_paths = {v[0] for v in violations}

    # The bad file must be detected
    assert any("bad_query.py" in p for p in violation_paths), (
        f"Scanner failed to detect regression fixture. violations={violations}"
    )

    # The good file must NOT be flagged
    assert not any("good_query.py" in p for p in violation_paths), (
        f"Scanner incorrectly flagged compliant file. violations={violations}"
    )


def test_active_only_queries_not_flagged():
    """Queries restricted to open/active positions must not be flagged.

    reconciled_stale is a terminal exit_reason — it can only appear in closed rows.
    Queries on active positions legitimately include SUM(pnl_dollars) (unrealized P&L)
    without needing outcome_stats_filter_sql.
    """
    active_code = textwrap.dedent("""
        import sqlite3
        def get_open_pnl(conn):
            row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as pnl "
                "FROM shadow_trades WHERE status = 'open' "
                "AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            return row
    """)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        src_fake = tmp_root / "src" / "fake_active"
        src_fake.mkdir(parents=True)
        (src_fake / "active_query.py").write_text(active_code, encoding="utf-8")

        violations = _scan_src_for_violations(tmp_root / "src")

    assert not violations, (
        f"Scanner incorrectly flagged active-only query. violations={violations}"
    )


def test_exempt_marker_suppresses_detection():
    """A  # outcome-stats-filter: exempt-<reason>  comment near the FROM line suppresses detection."""
    code_with_marker = textwrap.dedent("""
        import sqlite3
        def get_equity(conn):
            # outcome-stats-filter: exempt-equity-accounting
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) "
                "FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            return row[0]
    """)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        src_fake = tmp_root / "src" / "fake_exempt"
        src_fake.mkdir(parents=True)
        (src_fake / "exempt_query.py").write_text(code_with_marker, encoding="utf-8")

        violations = _scan_src_for_violations(tmp_root / "src")

    assert not violations, (
        f"Exempt marker did not suppress detection. violations={violations}"
    )


def test_allowlist_entries_reference_real_from_lines():
    """Every ALLOWLIST entry must refer to a line that actually contains FROM shadow_trades.

    This prevents stale allowlist entries accumulating after refactors move the code.
    """
    repo_root = Path(__file__).resolve().parent.parent

    stale: list[str] = []
    for rel_path, line_no, rationale in ALLOWLIST:
        abs_path = repo_root / rel_path
        if not abs_path.exists():
            stale.append(f"{rel_path}:{line_no} — file does not exist")
            continue
        file_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line_no < 1 or line_no > len(file_lines):
            stale.append(
                f"{rel_path}:{line_no} — line number out of range "
                f"(file has {len(file_lines)} lines)"
            )
            continue
        actual_line = file_lines[line_no - 1]
        if not _FROM_SHADOW.search(actual_line):
            stale.append(
                f"{rel_path}:{line_no} — line does not contain FROM shadow_trades. "
                f"Actual: {actual_line.strip()!r}"
            )

    if stale:
        raise AssertionError(
            "Stale ALLOWLIST entries (update line numbers or remove if query was fixed):\n"
            + "\n".join(f"  {s}" for s in stale)
        )
