# Diagnostic Dashboard v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `/diagnostics` page that lets the operator kick off regime and forensic diagnostic runs from the cloud dashboard, persists each run in `diagnostic_runs` + `diagnostic_run_plots` tables, and renders report markdown + plots inline via react-markdown.

**Architecture:** Extend the Sprint 4C command-queue pattern (`src/commands/executor.py`) with two new handlers that subprocess-invoke the existing diagnostic scripts. Because `render_sync` is tables-only, reports and plots are stored as TEXT/base64 rows (not files). Dashboard reads Postgres via 6 REST endpoints; polling is TanStack Query with `refetchInterval=5000` while any run is active.

**Tech Stack:** Python 3.12, FastAPI, SQLite (raw sqlite3), React 19, Tailwind 4, TanStack Query, react-markdown@9, remark-gfm@4.

---

## Sprint artifacts (read these first)

- Design spec: `docs/superpowers/specs/2026-04-18-diagnostic-dashboard-design.md`
- Pass 1 eval: `docs/sprints/diagnostic_dashboard_v1_evaluation.md`
- Pass 2 research: `docs/sprints/diagnostic_dashboard_v1_pass2_research.md`
- Decisions log: `docs/sprints/diagnostic_dashboard_v1_decisions.md`

---

## Task 1: Add `diagnostic_runs` + `diagnostic_run_plots` to schema registry

**Files:**
- Modify: `src/schema/registry.py` (append before `# User Data` section; use existing `_register(TableDef(...))` pattern)
- Test: `tests/test_schema.py` (existing — verify the new tables are included in drift checks)

**Context:** Schema registry is single source of truth; no `CREATE TABLE` allowed elsewhere (CI-enforced by `test_no_create_table_in_source`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_schema.py` (locate the area that lists known tables):

```python
def test_diagnostic_runs_in_registry():
    """diagnostic_runs must be registered with correct columns and sync config."""
    from src.schema.registry import TABLES
    assert "diagnostic_runs" in TABLES
    td = TABLES["diagnostic_runs"]
    names = [c.name for c in td.columns]
    for expected in [
        "run_id", "diagnostic_type", "status", "trigger_source", "triggered_by",
        "cohort_n", "started_at", "completed_at", "exit_code", "report_markdown",
        "summary_json", "stderr_tail", "payload_json", "created_at", "updated_at",
    ]:
        assert expected in names, f"Missing column: {expected}"
    assert td.primary_key == "run_id"
    assert td.sync_to_postgres is True
    assert td.sync_mode == "incremental"
    assert td.sync_time_column == "updated_at"


def test_diagnostic_run_plots_in_registry():
    """diagnostic_run_plots sibling table must be registered."""
    from src.schema.registry import TABLES
    assert "diagnostic_run_plots" in TABLES
    td = TABLES["diagnostic_run_plots"]
    names = [c.name for c in td.columns]
    for expected in ["plot_id", "run_id", "filename", "content_b64", "sort_order", "created_at"]:
        assert expected in names
    assert td.primary_key == "plot_id"
    assert td.sync_to_postgres is True
```

- [ ] **Step 2: Run test to verify it fails**

`python -m pytest tests/test_schema.py::test_diagnostic_runs_in_registry tests/test_schema.py::test_diagnostic_run_plots_in_registry -v`
Expected: FAIL with `assert "diagnostic_runs" in TABLES`.

- [ ] **Step 3: Add TableDefs to registry.py**

In `src/schema/registry.py`, find the `# User Data (1 table)` section header (~line 1466). Insert BEFORE it:

```python
# ---------------------------------------------------------------------------
# Diagnostics (2 tables)
# ---------------------------------------------------------------------------

# diagnostic_runs: every regime / forensic diagnostic invocation.
# Written by: src.commands.executor handlers + src.api.cloud_routes.diagnostics
# at queue submission time. Dashboard reads Postgres side.
_register(TableDef(
    name="diagnostic_runs",
    description="Regime and forensic diagnostic run metadata + report markdown",
    columns=[
        ColumnDef("run_id", "TEXT", nullable=False),
        ColumnDef("diagnostic_type", "TEXT", nullable=False,
                  description="'regime' | 'forensic'"),
        ColumnDef("status", "TEXT", nullable=False,
                  description="'queued' | 'running' | 'completed' | 'failed'"),
        ColumnDef("trigger_source", "TEXT", nullable=False, default="'dashboard'",
                  description="'dashboard' | 'cli'"),
        ColumnDef("triggered_by", "TEXT", default="'system'",
                  description="Operator email or 'system'"),
        ColumnDef("cohort_n", "INTEGER",
                  description="Closed trades at run start"),
        ColumnDef("started_at", "TEXT",
                  description="Set when status -> 'running'"),
        ColumnDef("completed_at", "TEXT",
                  description="Set when status -> terminal"),
        ColumnDef("exit_code", "INTEGER",
                  description="Subprocess exit code"),
        ColumnDef("report_markdown", "TEXT",
                  description="Full report body; set on completion"),
        ColumnDef("summary_json", "TEXT", default="'{}'",
                  description="Extracted headline fields"),
        ColumnDef("stderr_tail", "TEXT",
                  description="Last 2KB of stderr on failure"),
        ColumnDef("payload_json", "TEXT", default="'{}'",
                  description="Original submission payload"),
        ColumnDef("created_at", "TEXT", nullable=False),
        # updated_at bumps on every row modification; drives incremental sync.
        ColumnDef("updated_at", "TEXT", nullable=False),
    ],
    primary_key="run_id",
    indexes=[
        IndexDef("idx_diagnostic_runs_type_status",
                 ["diagnostic_type", "status"]),
        IndexDef("idx_diagnostic_runs_created_at", ["created_at"]),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="updated_at",
    sync_pk="run_id",
))

# diagnostic_run_plots: one row per PNG plot, base64-encoded.
# Avoids a multi-MB single-row update when a run completes.
_register(TableDef(
    name="diagnostic_run_plots",
    description="Base64-encoded PNG plots from diagnostic runs",
    columns=[
        ColumnDef("plot_id", "TEXT", nullable=False),
        ColumnDef("run_id", "TEXT", nullable=False),
        ColumnDef("filename", "TEXT", nullable=False),
        ColumnDef("content_b64", "TEXT", nullable=False),
        ColumnDef("sort_order", "INTEGER", default="0"),
        ColumnDef("created_at", "TEXT", nullable=False),
    ],
    primary_key="plot_id",
    indexes=[
        IndexDef("idx_diagnostic_run_plots_run_id", ["run_id"]),
    ],
    foreign_keys=[
        ForeignKeyDef("run_id", "diagnostic_runs", "run_id"),
    ],
    sync_to_postgres=True,
    sync_mode="incremental",
    sync_time_column="created_at",
    sync_pk="plot_id",
))
```

- [ ] **Step 4: Run tests and validate schema**

```bash
python -m pytest tests/test_schema.py::test_diagnostic_runs_in_registry tests/test_schema.py::test_diagnostic_run_plots_in_registry -v
python -m src.main validate-schema --fix
```

Expected: both tests pass; validate-schema creates the tables in local SQLite.

- [ ] **Step 5: Update cloud TABLE_WHITELIST**

In `src/api/cloud_routes/core.py:496-510`, find the `TABLE_WHITELIST` list used by `/api/system/table-counts`. Add `"diagnostic_runs"` and `"diagnostic_run_plots"` to the end of the list.

- [ ] **Step 6: Commit**

```bash
git add src/schema/registry.py src/api/cloud_routes/core.py tests/test_schema.py
git commit -m "feat(schema): add diagnostic_runs + diagnostic_run_plots tables

Sibling-table layout for diagnostic pipeline outputs: run metadata
in diagnostic_runs, base64 plots in diagnostic_run_plots. Uses
sync_time_column='updated_at' so status transitions propagate via
existing incremental sync to Postgres.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Summary extractor — regime parser

**Files:**
- Create: `src/diagnostics/summary_extractor.py`
- Create: `tests/diagnostics/fixtures/regime_report_sample.md`
- Create: `tests/diagnostics/test_summary_extractor.py`

**Why:** Handlers need structured summary fields (`decision`, `n_total`, `mean_excess`) to populate `diagnostic_runs.summary_json`. Regex parsing the `## Executive Summary` section is the D03 approach.

- [ ] **Step 1: Build a fixture from the real regime report generator**

Run the existing diagnostic in "peek" mode or synthesize a sample. Fastest path: copy the current `docs/diagnostics/regime-*.md` output head (executive summary only) into a fixture.

Create `tests/diagnostics/fixtures/regime_report_sample.md`:

```markdown
# Regime Diagnostic Report

Generated: 2026-04-18

## Executive Summary

**Decision:** CONTAMINATED

**N = 88**

Mean excess return: -0.0012

Aggregate 95% CI: [-0.0045, 0.0021]

Cell(s) Technology-Afternoon survive FDR correction (q=0.10), indicating non-uniform excess return.

## A1: VIX Regression

(rest of report omitted for fixture)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/diagnostics/test_summary_extractor.py`:

```python
"""Tests for summary_extractor — regex parser for diagnostic reports."""

from pathlib import Path

import pytest

from src.diagnostics.summary_extractor import (
    parse_regime_report,
    parse_forensic_report,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# ── regime ──────────────────────────────────────────────────────────

def test_parse_regime_report_happy_path():
    md = _load("regime_report_sample.md")
    summary = parse_regime_report(md)
    assert summary["decision"] == "CONTAMINATED"
    assert summary["n_total"] == 88
    assert summary["mean_excess"] == pytest.approx(-0.0012)
    assert "Technology-Afternoon" in summary["rationale"]


def test_parse_regime_report_missing_decision_falls_back():
    md = "## Executive Summary\n\nN = 88\n\nMean excess return: -0.0012\n"
    summary = parse_regime_report(md)
    assert "raw_executive_summary" in summary
    assert "decision" in summary["parse_errors"]


def test_parse_regime_report_no_exec_summary_returns_fallback():
    md = "# Report\n\nNothing useful here."
    summary = parse_regime_report(md)
    assert summary["parse_errors"] == ["no_executive_summary"]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/diagnostics/test_summary_extractor.py -v
```

Expected: FAIL with `ModuleNotFoundError: src.diagnostics.summary_extractor`.

- [ ] **Step 4: Implement `src/diagnostics/summary_extractor.py`**

```python
"""Regex parser for diagnostic report `## Executive Summary` sections.

Returns a summary dict for diagnostic_runs.summary_json. On parse failure,
stores raw executive-summary text + error list for UI fallback.

Called by: src.diagnostics.dashboard_runner
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_summary_extractor.py
"""

from __future__ import annotations

import re


EXEC_SUMMARY_RE = re.compile(
    r"##\s*Executive Summary\s*\n(?P<body>.+?)(?=\n##\s|\Z)",
    re.DOTALL,
)


def _extract_exec_summary(md: str) -> str | None:
    match = EXEC_SUMMARY_RE.search(md)
    return match.group("body").strip() if match else None


def _fallback(body: str | None, errors: list[str]) -> dict:
    return {
        "raw_executive_summary": (body or "")[:2000],
        "parse_errors": errors,
    }


# ── regime ──────────────────────────────────────────────────────────

_REGIME_DECISION_RE = re.compile(r"\*\*Decision:\*\*\s+(\w+)")
_REGIME_N_RE = re.compile(r"\*\*N\s*=\s*(\d+)\*\*")
_REGIME_MEAN_RE = re.compile(r"Mean excess return:\s*(-?[\d\.]+)")


def parse_regime_report(md: str) -> dict:
    """Parse a regime diagnostic report's executive summary."""
    body = _extract_exec_summary(md)
    if body is None:
        return _fallback(None, ["no_executive_summary"])

    errors: list[str] = []
    summary: dict = {}

    m = _REGIME_DECISION_RE.search(body)
    if m:
        summary["decision"] = m.group(1)
    else:
        errors.append("decision")

    m = _REGIME_N_RE.search(body)
    if m:
        summary["n_total"] = int(m.group(1))
    else:
        errors.append("n_total")

    m = _REGIME_MEAN_RE.search(body)
    if m:
        summary["mean_excess"] = float(m.group(1))
    else:
        errors.append("mean_excess")

    summary["rationale"] = body
    if errors:
        fallback = _fallback(body, errors)
        summary.update(fallback)
    return summary


# ── forensic ────────────────────────────────────────────────────────

def parse_forensic_report(md: str) -> dict:
    """Parse a forensic audit report's executive summary."""
    body = _extract_exec_summary(md)
    if body is None:
        return _fallback(None, ["no_executive_summary"])

    errors: list[str] = []
    summary: dict = {"raw_executive_summary": body[:2000]}

    n_match = re.search(r"Analyzed\s+\*\*(\d+)\*\*", body)
    if n_match:
        summary["n_total"] = int(n_match.group(1))
    else:
        errors.append("n_total")

    # "### 3 Most Surprising Findings" — findings are bullet points that follow
    findings_match = re.search(
        r"###\s*3 Most Surprising Findings\s*\n+(.+?)(?=\n###|\Z)",
        body,
        re.DOTALL,
    )
    if findings_match:
        summary["findings_raw"] = findings_match.group(1).strip()
    else:
        errors.append("findings")

    if errors:
        summary["parse_errors"] = errors
    return summary
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/diagnostics/test_summary_extractor.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/diagnostics/summary_extractor.py tests/diagnostics/test_summary_extractor.py tests/diagnostics/fixtures/regime_report_sample.md
git commit -m "feat(diagnostics): regex summary extractor for regime reports

Parses ## Executive Summary section to extract decision, N, and
mean excess return. Fallback path captures raw text + error list
when fields are missing, so the UI can still render partial data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Summary extractor — forensic parser + fixture

**Files:**
- Modify: `src/diagnostics/summary_extractor.py` (already contains `parse_forensic_report`; this task verifies it)
- Create: `tests/diagnostics/fixtures/forensic_report_sample.md`
- Modify: `tests/diagnostics/test_summary_extractor.py`

- [ ] **Step 1: Create the forensic fixture**

`tests/diagnostics/fixtures/forensic_report_sample.md`:

```markdown
# Forensic Trade Audit — 2026-04-18

## Executive Summary

Analyzed **88** closed trades (60 non-quarantined, 28 quarantined from April 10 cascade).

### 3 Most Surprising Findings

- The bootcamp cohort shows 2.3× the excess return of the production cohort, driven by holding-period asymmetry rather than setup quality.
- Sector rotation is statistically indistinguishable from random for the 88-trade sample.
- Afternoon entries underperform morning entries by 85 bps, but the effect is underpowered at N=88.

## Question 1: Are we reading fundamentals correctly?

(rest of report)
```

- [ ] **Step 2: Add forensic test cases**

Append to `tests/diagnostics/test_summary_extractor.py`:

```python
# ── forensic ────────────────────────────────────────────────────────

def test_parse_forensic_report_happy_path():
    md = _load("forensic_report_sample.md")
    summary = parse_forensic_report(md)
    assert summary["n_total"] == 88
    assert "bootcamp cohort" in summary["findings_raw"]
    assert "raw_executive_summary" in summary
    assert "parse_errors" not in summary


def test_parse_forensic_report_missing_findings():
    md = "## Executive Summary\n\nAnalyzed **42** trades.\n\n## Other section\n"
    summary = parse_forensic_report(md)
    assert summary["n_total"] == 42
    assert summary["parse_errors"] == ["findings"]


def test_parse_forensic_report_no_exec_summary():
    md = "Nothing here"
    summary = parse_forensic_report(md)
    assert summary["parse_errors"] == ["no_executive_summary"]
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/diagnostics/test_summary_extractor.py -v
```

Expected: 6 tests pass (3 regime + 3 forensic).

- [ ] **Step 4: Commit**

```bash
git add tests/diagnostics/test_summary_extractor.py tests/diagnostics/fixtures/forensic_report_sample.md
git commit -m "test(diagnostics): forensic summary-extractor fixtures and cases

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Dashboard runner — orchestration helper

**Files:**
- Create: `src/diagnostics/dashboard_runner.py`
- Create: `tests/diagnostics/test_dashboard_runner.py`

**Why:** Keeps executor handlers tight (<30 lines each) and centralizes lifecycle: temp-dir → subprocess → read report → scan plots → encode → SQLite transaction. Tested against an in-memory DB with a mocked subprocess.

- [ ] **Step 1: Write the failing test**

`tests/diagnostics/test_dashboard_runner.py`:

```python
"""Tests for dashboard_runner — orchestrates diagnostic script execution."""

import base64
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.diagnostics.dashboard_runner import run_diagnostic
from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite with diagnostic_runs + diagnostic_run_plots."""
    path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(str(path))
    for name in ("diagnostic_runs", "diagnostic_run_plots"):
        for stmt in generate_create_sql(TABLES[name]):
            conn.execute(stmt)
    # Seed a queued row (simulates API-side insert)
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "created_at, updated_at, payload_json) VALUES "
        "('run-001', 'regime', 'queued', 'dashboard', 'test@example.com', "
        "'2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00', '{}')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_runner_transitions_running_then_completed(db, tmp_path, monkeypatch):
    # Arrange: subprocess writes a report and a fake plot
    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def fake_subprocess(cmd, **kwargs):
        Path(report_path).write_text(
            "## Executive Summary\n\n**Decision:** CONTAMINATED\n\n"
            "**N = 42**\n\nMean excess return: 0.0015\n",
            encoding="utf-8",
        )
        (plot_dir / "vix_regression.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess)

    from src.diagnostics.summary_extractor import parse_regime_report

    # Act
    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=["--db", "dummy.sqlite3"],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )

    # Assert: run row transitioned, plots inserted
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, exit_code, summary_json FROM diagnostic_runs WHERE run_id = 'run-001'"
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] == 0
    assert "CONTAMINATED" in row[2]

    plots = conn.execute(
        "SELECT filename, content_b64 FROM diagnostic_run_plots WHERE run_id = 'run-001'"
    ).fetchall()
    assert len(plots) == 1
    assert plots[0][0] == "vix_regression.png"
    assert plots[0][1] == base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode("ascii")
    conn.close()


def test_runner_records_failure_on_nonzero_exit(db, tmp_path, monkeypatch):
    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def failing_subprocess(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="Boom" * 1000
        )

    monkeypatch.setattr(subprocess, "run", failing_subprocess)
    from src.diagnostics.summary_extractor import parse_regime_report

    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=[],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, stderr_tail FROM diagnostic_runs WHERE run_id = 'run-001'"
    ).fetchone()
    assert row[0] == "failed"
    # Only last 2KB kept
    assert len(row[1]) <= 2048
    conn.close()


def test_runner_records_failure_on_timeout(db, tmp_path, monkeypatch):
    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def timeout_subprocess(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 900)

    monkeypatch.setattr(subprocess, "run", timeout_subprocess)
    from src.diagnostics.summary_extractor import parse_regime_report

    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=[],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )
    assert result["status"] == "failed"
    assert "Timed out" in result["stderr_tail"]
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/diagnostics/test_dashboard_runner.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/diagnostics/dashboard_runner.py`**

```python
"""Runs diagnostic scripts for the cloud dashboard and persists results.

Orchestrates the full lifecycle: subprocess invocation, report read,
plot scanning + base64 encoding, SQLite writes for status transitions
and plot inserts. Handlers in src.commands.executor delegate here.

Called by: src.commands.executor (via _handle_run_regime_diagnostic, etc.)
Calls: src.diagnostics.summary_extractor
Owns tables: diagnostic_runs, diagnostic_run_plots (writes)
Config keys: none
Tests: tests/diagnostics/test_dashboard_runner.py
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
STDERR_TAIL_BYTES = 2048


def _now_iso() -> str:
    return datetime.now(ET).isoformat()


def _update_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    exit_code: int | None = None,
    report_markdown: str | None = None,
    summary_json: str | None = None,
    stderr_tail: str | None = None,
) -> None:
    """Merge-style UPDATE/INSERT on diagnostic_runs."""
    now = _now_iso()
    # Try INSERT first; if row exists (API pre-seeded it), UPDATE instead.
    existing = conn.execute(
        "SELECT run_id FROM diagnostic_runs WHERE run_id = ?", (run_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO diagnostic_runs "
            "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
            "started_at, completed_at, exit_code, report_markdown, summary_json, "
            "stderr_tail, created_at, updated_at) "
            "VALUES (?, 'unknown', ?, 'dashboard', 'system', ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, status, started_at, completed_at, exit_code,
             report_markdown, summary_json, stderr_tail, now, now),
        )
    else:
        sets = ["status = ?", "updated_at = ?"]
        params: list = [status, now]
        for col, val in [
            ("started_at", started_at),
            ("completed_at", completed_at),
            ("exit_code", exit_code),
            ("report_markdown", report_markdown),
            ("summary_json", summary_json),
            ("stderr_tail", stderr_tail),
        ]:
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        params.append(run_id)
        conn.execute(
            f"UPDATE diagnostic_runs SET {', '.join(sets)} WHERE run_id = ?",
            tuple(params),
        )


def _insert_plots(conn: sqlite3.Connection, run_id: str, plot_dir: Path) -> int:
    """Scan plot_dir for PNGs, base64-encode each, and insert rows."""
    now = _now_iso()
    png_files = sorted(plot_dir.glob("*.png"))
    for idx, png_path in enumerate(png_files):
        content = png_path.read_bytes()
        b64 = base64.b64encode(content).decode("ascii")
        conn.execute(
            "INSERT INTO diagnostic_run_plots "
            "(plot_id, run_id, filename, content_b64, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, png_path.name, b64, idx, now),
        )
    return len(png_files)


def run_diagnostic(
    *,
    run_id: str,
    script_path: str,
    script_args: list[str],
    report_parser: Callable[[str], dict],
    report_path: str,
    plot_dir: str,
    db_path: str,
    timeout_s: int = 900,
) -> dict:
    """Execute a diagnostic script and persist the result.

    Lifecycle:
      queued (seeded by API) -> running -> completed | failed

    Returns a summary dict suitable for command_results.result_json.
    """
    import json as _json

    started = _now_iso()
    with sqlite3.connect(db_path) as conn:
        _update_run_status(conn, run_id, status="running", started_at=started)
        conn.commit()

    cmd = [sys.executable, script_path, "--output", report_path,
           "--plot-dir", plot_dir] + list(script_args)
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        stderr_tail = f"Timed out after {timeout_s}s"
        with sqlite3.connect(db_path) as conn:
            _update_run_status(
                conn, run_id, status="failed",
                completed_at=_now_iso(),
                exit_code=-1, stderr_tail=stderr_tail,
            )
            conn.commit()
        return {"status": "failed", "exit_code": -1, "stderr_tail": stderr_tail}

    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "")[-STDERR_TAIL_BYTES:]
        with sqlite3.connect(db_path) as conn:
            _update_run_status(
                conn, run_id, status="failed",
                completed_at=_now_iso(),
                exit_code=completed.returncode, stderr_tail=stderr_tail,
            )
            conn.commit()
        return {"status": "failed", "exit_code": completed.returncode,
                "stderr_tail": stderr_tail}

    # Success path: read report, parse summary, insert plots
    report_markdown = Path(report_path).read_text(encoding="utf-8")
    summary = report_parser(report_markdown)
    summary_json = _json.dumps(summary)

    with sqlite3.connect(db_path) as conn:
        plot_count = _insert_plots(conn, run_id, Path(plot_dir))
        _update_run_status(
            conn, run_id, status="completed",
            completed_at=_now_iso(), exit_code=0,
            report_markdown=report_markdown,
            summary_json=summary_json,
        )
        conn.commit()

    logger.info(
        "[DIAG] run %s completed (%d plots, summary keys=%s)",
        run_id, plot_count, list(summary.keys()),
    )
    return {"status": "completed", "exit_code": 0, "summary": summary,
            "plot_count": plot_count}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/diagnostics/test_dashboard_runner.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/diagnostics/dashboard_runner.py tests/diagnostics/test_dashboard_runner.py
git commit -m "feat(diagnostics): dashboard_runner orchestration helper

Centralizes subprocess + report-parse + plot-encode + SQLite lifecycle
writes for dashboard-triggered diagnostic runs. Handles success,
non-zero exit, and timeout cases; truncates stderr to 2KB on failure.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Executor handlers — regime + forensic

**Files:**
- Modify: `src/commands/executor.py` (add 2 handlers + register in `COMMAND_HANDLERS`)
- Create: `tests/test_diagnostic_handlers.py`

- [ ] **Step 1: Write failing tests**

`tests/test_diagnostic_handlers.py`:

```python
"""Tests for executor-level run-regime-diagnostic + run-forensic-audit handlers."""

import sqlite3
from unittest.mock import patch

import pytest

from src.commands.executor import COMMAND_HANDLERS
from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(str(path))
    for name in ("diagnostic_runs", "diagnostic_run_plots"):
        for stmt in generate_create_sql(TABLES[name]):
            conn.execute(stmt)
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "created_at, updated_at, payload_json) VALUES "
        "('r-1', 'regime', 'queued', 'dashboard', 'op@x.com', "
        "'2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00', '{}')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_run_regime_diagnostic_handler_registered():
    assert "run-regime-diagnostic" in COMMAND_HANDLERS
    assert "run-forensic-audit" in COMMAND_HANDLERS


def test_run_regime_diagnostic_invokes_runner(db, monkeypatch):
    captured = {}
    def fake_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "exit_code": 0, "summary": {"decision": "PENDING"}}

    monkeypatch.setattr("src.diagnostics.dashboard_runner.run_diagnostic", fake_runner)
    monkeypatch.setattr("src.config.DB_PATH", db)

    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    payload = {"run_id": "r-1", "db_path": db, "exclude_quarantined": True}
    result = handler(payload, config={})

    assert result["status"] == "completed"
    assert captured["run_id"] == "r-1"
    assert "--exclude-quarantined" in captured["script_args"]
    assert "regime_diagnostic_v1.py" in captured["script_path"]


def test_run_forensic_audit_invokes_runner(db, monkeypatch):
    captured = {}
    def fake_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "exit_code": 0, "summary": {"n_total": 88}}

    monkeypatch.setattr("src.diagnostics.dashboard_runner.run_diagnostic", fake_runner)
    monkeypatch.setattr("src.config.DB_PATH", db)

    handler = COMMAND_HANDLERS["run-forensic-audit"]
    payload = {"run_id": "r-1", "db_path": db}
    result = handler(payload, config={})
    assert result["status"] == "completed"
    assert "forensic_trade_audit_v1.py" in captured["script_path"]
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_diagnostic_handlers.py -v
```

Expected: handler registration test fails (`"run-regime-diagnostic" not in COMMAND_HANDLERS`).

- [ ] **Step 3: Add handlers to `src/commands/executor.py`**

Insert ABOVE the `COMMAND_HANDLERS` dict (around line 277):

```python
def _handle_run_regime_diagnostic(payload: dict, config: dict) -> dict:
    """Run the regime diagnostic script via dashboard_runner."""
    from src.diagnostics.dashboard_runner import run_diagnostic
    from src.diagnostics.summary_extractor import parse_regime_report

    run_id = payload.get("run_id")
    if not run_id:
        return {"error": "Missing run_id in payload"}

    db_path = payload.get("db_path") or LOCAL_DB
    args: list[str] = []
    if payload.get("exclude_quarantined"):
        args.append("--exclude-quarantined")
    if payload.get("bootstrap_n"):
        args.extend(["--bootstrap-n", str(int(payload["bootstrap_n"]))])
    args.extend(["--db", db_path])

    report_path = f"docs/diagnostics/regime-{run_id}.md"
    plot_dir = f"docs/diagnostics/regime-{run_id}/"
    from pathlib import Path
    Path(plot_dir).mkdir(parents=True, exist_ok=True)

    return run_diagnostic(
        run_id=run_id,
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=args,
        report_parser=parse_regime_report,
        report_path=report_path,
        plot_dir=plot_dir,
        db_path=LOCAL_DB,
    )


def _handle_run_forensic_audit(payload: dict, config: dict) -> dict:
    """Run the forensic trade audit script via dashboard_runner."""
    from src.diagnostics.dashboard_runner import run_diagnostic
    from src.diagnostics.summary_extractor import parse_forensic_report

    run_id = payload.get("run_id")
    if not run_id:
        return {"error": "Missing run_id in payload"}

    args: list[str] = []
    report_path = f"docs/diagnostics/forensic-audit-{run_id}.md"
    plot_dir = f"docs/diagnostics/forensic-audit-{run_id}/"
    from pathlib import Path
    Path(plot_dir).mkdir(parents=True, exist_ok=True)

    return run_diagnostic(
        run_id=run_id,
        script_path="scripts/diagnostics/forensic_trade_audit_v1.py",
        script_args=args,
        report_parser=parse_forensic_report,
        report_path=report_path,
        plot_dir=plot_dir,
        db_path=LOCAL_DB,
    )
```

Then add to `COMMAND_HANDLERS` dict:

```python
    "run-regime-diagnostic": _handle_run_regime_diagnostic,
    "run-forensic-audit": _handle_run_forensic_audit,
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_diagnostic_handlers.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Run the full executor test suite to verify no regression**

```bash
python -m pytest tests/test_executor_import.py tests/test_diagnostic_handlers.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/commands/executor.py tests/test_diagnostic_handlers.py
git commit -m "feat(executor): run-regime-diagnostic + run-forensic-audit handlers

Two new COMMAND_HANDLERS entries that delegate to dashboard_runner.
Each handler assembles the subprocess args from payload (exclude-
quarantined, bootstrap-n) and uses run_id as the filesystem namespace
to prevent same-day collisions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Cloud routes — `src/api/cloud_routes/diagnostics.py`

**Files:**
- Create: `src/api/cloud_routes/diagnostics.py`
- Modify: `src/api/cloud_app.py` (or the equivalent router-registration file — find it first)
- Create: `tests/api/test_diagnostic_routes.py`

- [ ] **Step 1: Locate the router mount point**

```bash
grep -n "include_router\|create_router" src/api/cloud_app.py src/api/cloud_routes/__init__.py 2>&1 | head -30
```

Read the file and identify where existing routers (analytics, core, council, etc.) are registered. The new diagnostics router plugs in at the same place.

- [ ] **Step 2: Write failing tests**

`tests/api/test_diagnostic_routes.py`:

```python
"""Tests for /api/diagnostic-runs/* cloud endpoints."""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.diagnostics import create_router


ET = ZoneInfo("America/New_York")


def _noop_auth():
    return True


@pytest.fixture
def app(tmp_path):
    """Build a minimal FastAPI with fake runtime stubs."""
    runtime = MagicMock()
    runtime.et = ET
    runtime.logger = MagicMock()

    storage: dict = {"runs": {}, "plots": {}, "pending_commands": {}}

    def query_one(sql, params=()):
        if "FROM diagnostic_runs WHERE diagnostic_type" in sql:
            dt = params[0]
            for r in storage["runs"].values():
                if r["diagnostic_type"] == dt and r["status"] in ("queued", "running"):
                    return r
            return None
        if "FROM diagnostic_runs WHERE run_id" in sql:
            return storage["runs"].get(params[0])
        return None

    def query(sql, params=()):
        if "FROM diagnostic_runs" in sql:
            return list(storage["runs"].values())[:params[-1] if params else 50]
        if "FROM diagnostic_run_plots" in sql:
            return storage["plots"].get(params[0], [])
        return []

    class FakeCursor:
        def execute(self, sql, params):
            if "INSERT INTO pending_commands" in sql:
                storage["pending_commands"][params[0]] = params
            elif "INSERT INTO diagnostic_runs" in sql:
                storage["runs"][params[0]] = {
                    "run_id": params[0],
                    "diagnostic_type": params[1],
                    "status": "queued",
                    "trigger_source": "dashboard",
                    "triggered_by": params[2],
                    "payload_json": params[3],
                    "created_at": params[4],
                    "updated_at": params[4],
                }

        def __enter__(self): return self
        def __exit__(self, *a): return False

    class FakePg:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    runtime.get_pg = lambda readonly=False: FakePg()
    runtime.query = query
    runtime.query_one = query_one

    app = FastAPI()
    app.include_router(create_router(runtime, verify_auth=_noop_auth))
    app.state._storage = storage
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_submit_regime_run_returns_202(client, app):
    resp = client.post("/api/diagnostic-runs/regime", json={})
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    assert data["run_id"] in app.state._storage["runs"]
    assert app.state._storage["runs"][data["run_id"]]["diagnostic_type"] == "regime"


def test_submit_forensic_run_returns_202(client, app):
    resp = client.post("/api/diagnostic-runs/forensic", json={})
    assert resp.status_code == 202


def test_submit_regime_run_409_if_already_running(client, app):
    run_id = str(uuid.uuid4())
    app.state._storage["runs"][run_id] = {
        "run_id": run_id, "diagnostic_type": "regime", "status": "running",
    }
    resp = client.post("/api/diagnostic-runs/regime", json={})
    assert resp.status_code == 409
    assert "already" in resp.json()["detail"].lower()


def test_list_runs_returns_recent(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
    }
    app.state._storage["runs"]["r-2"] = {
        "run_id": "r-2", "diagnostic_type": "forensic", "status": "running",
    }
    resp = client.get("/api/diagnostic-runs")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2


def test_get_run_not_found_returns_404(client):
    resp = client.get("/api/diagnostic-runs/nonexistent")
    assert resp.status_code == 404


def test_get_run_report_returns_markdown(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
        "report_markdown": "# Report\n\n## Executive Summary\n\n**Decision:** PENDING\n",
    }
    resp = client.get("/api/diagnostic-runs/r-1/report")
    assert resp.status_code == 200
    assert "**Decision:** PENDING" in resp.json()["markdown"]


def test_get_run_plots_returns_base64(client, app):
    app.state._storage["runs"]["r-1"] = {"run_id": "r-1", "diagnostic_type": "regime"}
    app.state._storage["plots"]["r-1"] = [
        {"filename": "a.png", "content_b64": "abc123", "sort_order": 0},
    ]
    resp = client.get("/api/diagnostic-runs/r-1/plots")
    assert resp.status_code == 200
    assert len(resp.json()["plots"]) == 1
    assert resp.json()["plots"][0]["content_b64"] == "abc123"


def test_list_with_type_filter(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
    }
    app.state._storage["runs"]["r-2"] = {
        "run_id": "r-2", "diagnostic_type": "forensic", "status": "completed",
    }
    resp = client.get("/api/diagnostic-runs?type=regime")
    assert resp.status_code == 200
```

- [ ] **Step 3: Run to verify fail**

```bash
python -m pytest tests/api/test_diagnostic_routes.py -v
```

Expected: `ModuleNotFoundError: src.api.cloud_routes.diagnostics`.

- [ ] **Step 4: Implement `src/api/cloud_routes/diagnostics.py`**

```python
"""Cloud routes for diagnostic runs: POST to kick off, GET to list/inspect.

Endpoints (all under /api/diagnostic-runs):
    POST  /regime           - Submit a regime diagnostic run
    POST  /forensic         - Submit a forensic audit run
    GET   /                 - List runs (filterable by type, status)
    GET   /{run_id}         - Single run metadata
    GET   /{run_id}/report  - Full markdown report text
    GET   /{run_id}/plots   - Base64 PNG plots for a run

Called by: api.cloud_app (via include_router)
Calls: sync.render_sync (indirectly via pending_commands insert)
Owns tables: diagnostic_runs, diagnostic_run_plots (writes queued rows;
             running/completed transitions happen on the local machine)
Config keys: none
Tests: tests/api/test_diagnostic_routes.py
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel


class RegimePayload(BaseModel):
    exclude_quarantined: bool = False
    bootstrap_n: int | None = None


class ForensicPayload(BaseModel):
    pass


def create_router(runtime, verify_auth):
    """Build the /api/diagnostic-runs/* router."""
    router = APIRouter()

    def _check_dedup(diagnostic_type: str) -> None:
        """Raise 409 if a run of the same type is queued or running."""
        existing = runtime.query_one(
            "SELECT run_id, status FROM diagnostic_runs "
            "WHERE diagnostic_type = %s AND status IN ('queued', 'running') "
            "ORDER BY created_at DESC LIMIT 1",
            (diagnostic_type,),
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A {diagnostic_type} diagnostic is already "
                    f"{existing['status']} (run_id={existing['run_id']})"
                ),
            )

    def _submit_diagnostic(diagnostic_type: str, payload: dict, triggered_by: str) -> dict:
        run_id = str(uuid.uuid4())
        now = datetime.now(runtime.et)
        expires_at = (now + timedelta(minutes=5)).isoformat()
        payload_with_run_id = {**payload, "run_id": run_id}
        payload_json = json.dumps(payload_with_run_id)

        try:
            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO diagnostic_runs "
                        "(run_id, diagnostic_type, status, trigger_source, "
                        "triggered_by, payload_json, created_at, updated_at) "
                        "VALUES (%s, %s, 'queued', 'dashboard', %s, %s, %s, %s)",
                        (run_id, diagnostic_type, triggered_by,
                         payload_json, now.isoformat(), now.isoformat()),
                    )
                    cur.execute(
                        "INSERT INTO pending_commands "
                        "(command_id, command_type, command_name, payload_json, "
                        "status, priority, created_at, expires_at, created_by) "
                        "VALUES (%s, %s, %s, %s, 'pending', 5, %s, %s, %s)",
                        (run_id, "diagnostic",
                         f"run-{diagnostic_type}-" + ("diagnostic" if diagnostic_type == "regime" else "audit"),
                         payload_json, now.isoformat(), expires_at, triggered_by),
                    )
                    conn.commit()
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Diagnostic submission failed: %s", exc)
            raise HTTPException(status_code=503, detail="Database unavailable")

        return {"run_id": run_id, "command_id": run_id, "status": "queued"}

    @router.post("/api/diagnostic-runs/regime",
                 dependencies=[Depends(verify_auth)], status_code=202)
    def submit_regime(body: RegimePayload, response: Response):
        _check_dedup("regime")
        result = _submit_diagnostic(
            "regime",
            body.model_dump(exclude_none=True),
            triggered_by="dashboard",
        )
        return result

    @router.post("/api/diagnostic-runs/forensic",
                 dependencies=[Depends(verify_auth)], status_code=202)
    def submit_forensic(body: ForensicPayload | None = None):
        _check_dedup("forensic")
        payload = body.model_dump(exclude_none=True) if body else {}
        result = _submit_diagnostic(
            "forensic", payload, triggered_by="dashboard",
        )
        return result

    @router.get("/api/diagnostic-runs", dependencies=[Depends(verify_auth)])
    def list_runs(limit: int = 20,
                  type: str | None = None,
                  status: str | None = None):
        limit = min(max(limit, 1), 100)
        clauses: list[str] = ["1=1"]
        params: list = []
        if type and type != "all":
            clauses.append("diagnostic_type = %s")
            params.append(type)
        if status and status != "all":
            clauses.append("status = %s")
            params.append(status)
        params.append(limit)
        where = " AND ".join(clauses)
        runs = runtime.query(
            f"SELECT run_id, diagnostic_type, status, trigger_source, "
            f"triggered_by, cohort_n, started_at, completed_at, "
            f"summary_json, created_at FROM diagnostic_runs "
            f"WHERE {where} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return {"runs": runs, "count": len(runs)}

    @router.get("/api/diagnostic-runs/{run_id}",
                dependencies=[Depends(verify_auth)])
    def get_run(run_id: str):
        row = runtime.query_one(
            "SELECT * FROM diagnostic_runs WHERE run_id = %s", (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        # Strip the heavy field from the single-run response body
        row.pop("report_markdown", None)
        return row

    @router.get("/api/diagnostic-runs/{run_id}/report",
                dependencies=[Depends(verify_auth)])
    def get_run_report(run_id: str):
        row = runtime.query_one(
            "SELECT report_markdown, status FROM diagnostic_runs WHERE run_id = %s",
            (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        if not row.get("report_markdown"):
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id} has no report yet (status={row.get('status')})",
            )
        return Response(
            content=json.dumps({"markdown": row["report_markdown"]}),
            media_type="application/json",
            headers={"Cache-Control": "private, max-age=300"},
        )

    @router.get("/api/diagnostic-runs/{run_id}/plots",
                dependencies=[Depends(verify_auth)])
    def get_run_plots(run_id: str):
        row = runtime.query_one(
            "SELECT run_id FROM diagnostic_runs WHERE run_id = %s", (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        plots = runtime.query(
            "SELECT filename, content_b64, sort_order FROM diagnostic_run_plots "
            "WHERE run_id = %s ORDER BY sort_order",
            (run_id,),
        )
        return {"plots": plots, "count": len(plots)}

    return router
```

- [ ] **Step 5: Register the router in `src/api/cloud_app.py`**

Locate where other routers are included (look for `include_router` calls near the top of the app factory). Add:

```python
from src.api.cloud_routes.diagnostics import create_router as _create_diagnostics_router

app.include_router(_create_diagnostics_router(runtime, verify_auth))
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/api/test_diagnostic_routes.py -v
```

Expected: 8 tests pass.

- [ ] **Step 7: Run full test suite for regression check**

```bash
python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: no new failures; pass count maintained.

- [ ] **Step 8: Commit**

```bash
git add src/api/cloud_routes/diagnostics.py src/api/cloud_app.py tests/api/test_diagnostic_routes.py
git commit -m "feat(api): /api/diagnostic-runs/* cloud endpoints

Six REST endpoints for kickoff + history + detail views. POST
submissions insert both pending_commands and diagnostic_runs(queued)
in a single Postgres transaction; dedup enforced per diagnostic_type.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Install frontend deps (react-markdown, remark-gfm)

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json` (auto)

- [ ] **Step 1: Install deps**

```bash
cd frontend && npm install react-markdown@^9 remark-gfm@^4
```

- [ ] **Step 2: Verify installation**

```bash
cd frontend && node -e "console.log(require('react-markdown/package.json').version, require('remark-gfm/package.json').version)"
```

Expected: `9.x.y 4.x.y`.

- [ ] **Step 3: Smoke-build**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: build succeeds (no new code uses the deps yet; this just verifies they don't break the bundle).

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add react-markdown + remark-gfm for inline report rendering

Operator-approved new dependencies for diagnostic dashboard v1.
Both are small, no native deps, React 19 compatible.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Frontend API methods

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: Append methods to the `api` object**

Locate the end of the `api` object (around line 100+) and add BEFORE the closing brace:

```javascript
  // Diagnostic runs
  triggerRegimeDiagnostic: (opts = {}) => fetchApi('/diagnostic-runs/regime', {
    method: 'POST',
    body: JSON.stringify(opts),
  }),
  triggerForensicAudit: () => fetchApi('/diagnostic-runs/forensic', {
    method: 'POST',
    body: JSON.stringify({}),
  }),
  getDiagnosticRuns: (params = {}) => {
    const q = new URLSearchParams(params)
    return fetchApi(`/diagnostic-runs?${q}`)
  },
  getDiagnosticRun: (runId) => fetchApi(`/diagnostic-runs/${runId}`),
  getDiagnosticRunReport: (runId) => fetchApi(`/diagnostic-runs/${runId}/report`),
  getDiagnosticRunPlots: (runId) => fetchApi(`/diagnostic-runs/${runId}/plots`),
```

- [ ] **Step 2: Verify import path**

Open `frontend/src/api.js` and confirm `api` is `export const api = { … }`. The new methods should be inside that object.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat(frontend): api.js methods for diagnostic-runs endpoints

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: DiagnosticKickoffButtons component

**Files:**
- Create: `frontend/src/components/DiagnosticKickoffButtons.jsx`

- [ ] **Step 1: Write the component**

```jsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

function typeIsActive(runs, type) {
  return runs.some(r => r.diagnostic_type === type
    && (r.status === 'queued' || r.status === 'running'))
}

export default function DiagnosticKickoffButtons({ runs = [], onError }) {
  const qc = useQueryClient()
  const regimeActive = typeIsActive(runs, 'regime')
  const forensicActive = typeIsActive(runs, 'forensic')

  const regimeMut = useMutation({
    mutationFn: (opts) => api.triggerRegimeDiagnostic(opts),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagnostic-runs'] }),
    onError: (err) => onError?.(err.message || 'Failed to start regime run'),
  })

  const forensicMut = useMutation({
    mutationFn: () => api.triggerForensicAudit(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagnostic-runs'] }),
    onError: (err) => onError?.(err.message || 'Failed to start forensic run'),
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="border rounded p-4">
        <h3 className="font-medium mb-1">Regime Diagnostic</h3>
        <p className="text-xs text-gray-500 mb-3">
          CONTAMINATED / NULL / PENDING decision based on VIX regression,
          day clustering, sector rotation, entry-time, holding-period.
          Takes 3–5 minutes.
        </p>
        <button
          onClick={() => regimeMut.mutate({ exclude_quarantined: false })}
          disabled={regimeActive || regimeMut.isPending}
          className={`w-full py-2 rounded text-sm font-medium ${
            regimeActive || regimeMut.isPending
              ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {regimeActive ? 'Running…' : 'Run Regime Diagnostic'}
        </button>
      </div>

      <div className="border rounded p-4">
        <h3 className="font-medium mb-1">Forensic Trade Audit</h3>
        <p className="text-xs text-gray-500 mb-3">
          8-question forensic with bootcamp counterfactual. Takes 2–3 minutes.
        </p>
        <button
          onClick={() => forensicMut.mutate()}
          disabled={forensicActive || forensicMut.isPending}
          className={`w-full py-2 rounded text-sm font-medium ${
            forensicActive || forensicMut.isPending
              ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {forensicActive ? 'Running…' : 'Run Forensic Audit'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DiagnosticKickoffButtons.jsx
git commit -m "feat(frontend): DiagnosticKickoffButtons component

Two-button panel with type-matched dedup disabling.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: DiagnosticRunTable component

**Files:**
- Create: `frontend/src/components/DiagnosticRunTable.jsx`

- [ ] **Step 1: Write the component**

```jsx
import StatusBadge from './StatusBadge'

const STATUS_VARIANT = {
  queued: 'neutral',
  running: 'info',
  completed: 'success',
  failed: 'danger',
}

function parseDecision(summaryJson) {
  if (!summaryJson) return '—'
  try {
    const s = typeof summaryJson === 'string' ? JSON.parse(summaryJson) : summaryJson
    return s.decision || `N=${s.n_total ?? '—'}`
  } catch {
    return '—'
  }
}

export default function DiagnosticRunTable({ runs = [], onSelect, selectedId }) {
  if (runs.length === 0) {
    return (
      <p className="text-sm text-gray-500 p-4 bg-gray-50 rounded">
        No diagnostic runs yet. Click a button above to start one.
      </p>
    )
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-gray-100">
        <tr>
          <th className="text-left p-2">When</th>
          <th className="text-left p-2">Type</th>
          <th className="text-left p-2">Status</th>
          <th className="text-left p-2">Cohort N</th>
          <th className="text-left p-2">Decision / Finding</th>
          <th className="text-left p-2">Triggered by</th>
        </tr>
      </thead>
      <tbody>
        {runs.map(r => (
          <tr
            key={r.run_id}
            onClick={() => onSelect?.(r.run_id)}
            className={`cursor-pointer hover:bg-gray-50 border-t ${
              selectedId === r.run_id ? 'bg-blue-50' : ''
            }`}
          >
            <td className="p-2 text-xs">
              {r.created_at?.slice(0, 19).replace('T', ' ')}
            </td>
            <td className="p-2 capitalize">{r.diagnostic_type}</td>
            <td className="p-2">
              <StatusBadge
                text={r.status}
                variant={STATUS_VARIANT[r.status] || 'neutral'}
              />
            </td>
            <td className="p-2">{r.cohort_n ?? '—'}</td>
            <td className="p-2 font-mono text-xs">{parseDecision(r.summary_json)}</td>
            <td className="p-2 text-xs text-gray-600">{r.triggered_by}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DiagnosticRunTable.jsx
git commit -m "feat(frontend): DiagnosticRunTable history component

Mirrors StrategyResearch.jsx table pattern. Row click selects
for detail view; summary_json.decision is surfaced in the table.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: DiagnosticRunDetail component

**Files:**
- Create: `frontend/src/components/DiagnosticRunDetail.jsx`

- [ ] **Step 1: Write the component**

```jsx
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api'

export default function DiagnosticRunDetail({ runId }) {
  const { data: run } = useQuery({
    queryKey: ['diagnostic-run', runId],
    queryFn: () => api.getDiagnosticRun(runId),
    enabled: !!runId,
  })

  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ['diagnostic-run-report', runId],
    queryFn: () => api.getDiagnosticRunReport(runId),
    enabled: !!runId && run?.status === 'completed',
    staleTime: 5 * 60 * 1000,
  })

  const { data: plots } = useQuery({
    queryKey: ['diagnostic-run-plots', runId],
    queryFn: () => api.getDiagnosticRunPlots(runId),
    enabled: !!runId && run?.status === 'completed',
    staleTime: 5 * 60 * 1000,
  })

  if (!runId) return null
  if (!run) return <p className="text-sm text-gray-500">Loading…</p>

  if (run.status === 'queued') {
    return (
      <div className="p-4 bg-yellow-50 rounded">
        <p className="text-sm">Queued — waiting for local machine to pick up.</p>
      </div>
    )
  }
  if (run.status === 'running') {
    return (
      <div className="p-4 bg-blue-50 rounded">
        <p className="text-sm">
          Running — started {run.started_at?.slice(11, 19)}. Refreshing every 5s.
        </p>
      </div>
    )
  }
  if (run.status === 'failed') {
    return (
      <div className="p-4 bg-red-50 rounded">
        <p className="text-sm font-medium text-red-700 mb-1">Failed</p>
        <pre className="text-xs text-red-800 whitespace-pre-wrap">
          {run.stderr_tail || '(no stderr captured)'}
        </pre>
      </div>
    )
  }

  return (
    <div className="bg-white">
      {reportLoading && <p className="text-sm">Loading report…</p>}
      {report?.markdown && (
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {report.markdown}
          </ReactMarkdown>
        </div>
      )}
      {plots?.plots && plots.plots.length > 0 && (
        <section className="mt-6">
          <h3 className="font-medium mb-2">Plots</h3>
          <div className="space-y-4">
            {plots.plots.map(p => (
              <figure key={p.filename} className="border rounded p-2">
                <img
                  src={`data:image/png;base64,${p.content_b64}`}
                  alt={p.filename}
                  className="max-w-full"
                />
                <figcaption className="text-xs text-gray-500 mt-1">
                  {p.filename}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DiagnosticRunDetail.jsx
git commit -m "feat(frontend): DiagnosticRunDetail inline report+plots viewer

Uses react-markdown + remark-gfm for GFM table rendering; plots
inline via data:image/png;base64. Handles queued/running/failed
states with appropriate empty-state UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Diagnostics page

**Files:**
- Create: `frontend/src/pages/Diagnostics.jsx`

- [ ] **Step 1: Write the page**

```jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import DiagnosticKickoffButtons from '../components/DiagnosticKickoffButtons'
import DiagnosticRunTable from '../components/DiagnosticRunTable'
import DiagnosticRunDetail from '../components/DiagnosticRunDetail'

function anyActive(runs) {
  return runs.some(r => r.status === 'queued' || r.status === 'running')
}

export default function Diagnostics() {
  const [selectedId, setSelectedId] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['diagnostic-runs'],
    queryFn: () => api.getDiagnosticRuns({ limit: 20 }),
    refetchInterval: (query) => {
      const runs = query?.state?.data?.runs || []
      return anyActive(runs) ? 5000 : 30000
    },
  })
  const runs = data?.runs || []

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-1">Diagnostics</h1>
      <p className="text-sm text-gray-500 mb-6">
        Kick off regime and forensic runs against the current closed-trade cohort.
        Runs persist in <code>diagnostic_runs</code>; reports + plots render inline below.
      </p>

      {errorMsg && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700 flex justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-red-500 hover:text-red-700">×</button>
        </div>
      )}

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Start a run</h2>
        <DiagnosticKickoffButtons runs={runs} onError={setErrorMsg} />
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Recent runs</h2>
        {isLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : (
          <DiagnosticRunTable
            runs={runs}
            onSelect={setSelectedId}
            selectedId={selectedId}
          />
        )}
      </section>

      {selectedId && (
        <section className="mb-8 border-l-4 border-blue-500 pl-4">
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-lg font-medium">Run detail</h2>
            <button
              onClick={() => setSelectedId(null)}
              className="text-xs text-gray-600 hover:text-gray-900"
            >
              Close
            </button>
          </div>
          <DiagnosticRunDetail runId={selectedId} />
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Diagnostics.jsx
git commit -m "feat(frontend): Diagnostics page composition

Three sections: kickoff, history table, expand-on-click detail.
Polling cadence dynamic: 5s while any run active, 30s otherwise.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Route + nav

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Add import + route to App.jsx**

Near the other page imports (around line 35), add:

```javascript
import Diagnostics from './pages/Diagnostics'
```

Inside the `<Routes>` block (after `/research-platform` route around line 128), add:

```jsx
<Route path="/diagnostics" element={<ErrorBoundary><Diagnostics /></ErrorBoundary>} />
```

- [ ] **Step 2: Add nav item in Layout.jsx**

Open `frontend/src/components/Layout.jsx`. In the lucide-react import line (line 6), add `Microscope`:

```javascript
import { LayoutDashboard, FileText, TrendingUp, Brain, BarChart3, Settings, Map, BookOpen, Users, Activity, Menu, X, DollarSign, ShieldCheck, ScrollText, Network, Database, FlaskConical, Zap, TestTube2, Cpu, Monitor, Target, GitCompare, Gauge, Search, Microscope } from 'lucide-react'
```

In the Intelligence group (lines 19-29), add AFTER Velocity and BEFORE Research Platform:

```javascript
    { to: '/diagnostics', icon: Microscope, label: 'Diagnostics' },
```

- [ ] **Step 3: Smoke-check build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds, no new warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/Layout.jsx
git commit -m "feat(frontend): /diagnostics route + Intelligence nav item

Microscope icon in the Intelligence group, after Velocity.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: End-to-end smoke test

**Files:**
- Create: `tests/test_diagnostic_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
"""End-to-end smoke test: API submission -> handler execution -> report stored.

Uses a fake subprocess to avoid the 3-5 min real diagnostic runtime.
Verifies the complete data flow from dashboard endpoint to
diagnostic_runs row transition.
"""

import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.commands.executor import COMMAND_HANDLERS
from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(str(path))
    for name in ("diagnostic_runs", "diagnostic_run_plots", "pending_commands",
                 "command_results"):
        for stmt in generate_create_sql(TABLES[name]):
            conn.execute(stmt)
    # Simulate: API already inserted queued row
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "payload_json, created_at, updated_at) VALUES "
        "('smoke-1', 'regime', 'queued', 'dashboard', 'test@local', "
        "'{}', '2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_end_to_end_regime_run(db, tmp_path, monkeypatch):
    """API-submitted regime run → handler → completed row with plots."""

    def fake_subprocess(cmd, **kwargs):
        # Find --output and --plot-dir in cmd
        output = plot_dir = None
        for i, arg in enumerate(cmd):
            if arg == "--output": output = cmd[i + 1]
            if arg == "--plot-dir": plot_dir = cmd[i + 1]
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            "## Executive Summary\n\n**Decision:** PENDING\n\n"
            "**N = 88**\n\nMean excess return: 0.0005\n",
            encoding="utf-8",
        )
        Path(plot_dir).mkdir(parents=True, exist_ok=True)
        (Path(plot_dir) / "p1.png").write_bytes(b"fake1")
        (Path(plot_dir) / "p2.png").write_bytes(b"fake2")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess)
    monkeypatch.setattr("src.commands.executor.LOCAL_DB", db)

    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    result = handler({"run_id": "smoke-1", "db_path": db}, config={})

    assert result["status"] == "completed"
    assert result["plot_count"] == 2

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, summary_json FROM diagnostic_runs WHERE run_id='smoke-1'"
    ).fetchone()
    assert row[0] == "completed"
    summary = json.loads(row[1])
    assert summary["decision"] == "PENDING"
    assert summary["n_total"] == 88

    plot_count = conn.execute(
        "SELECT COUNT(*) FROM diagnostic_run_plots WHERE run_id='smoke-1'"
    ).fetchone()[0]
    assert plot_count == 2
    conn.close()
```

- [ ] **Step 2: Run test**

```bash
python -m pytest tests/test_diagnostic_smoke.py -v
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_diagnostic_smoke.py
git commit -m "test: end-to-end diagnostic handler smoke test

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Docs + CHANGELOG

**Files:**
- Modify: `docs/MASTER.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CHANGELOG.md**

Add entry at top:

```markdown
## [Unreleased] v0.25.0 — Diagnostic Dashboard v1

### Added
- `/diagnostics` dashboard page with kickoff buttons for regime + forensic runs
- `diagnostic_runs` and `diagnostic_run_plots` tables for run metadata + base64 plot storage
- Six `/api/diagnostic-runs/*` endpoints: submit (regime/forensic), list, get, report, plots
- Two new executor handlers: `run-regime-diagnostic`, `run-forensic-audit`
- `src/diagnostics/dashboard_runner.py` orchestration helper
- `src/diagnostics/summary_extractor.py` regex parser for Executive Summary sections
- `react-markdown@9` + `remark-gfm@4` for inline markdown rendering

### Changed
- `TABLE_WHITELIST` in `cloud_routes/core.py` extended with new diagnostic tables
```

- [ ] **Step 2: Update MASTER.md**

Locate the tables section and add `diagnostic_runs` + `diagnostic_run_plots` to the table-count section. Add a brief description of the `/diagnostics` page near the existing pages list. Keep additions under 20 lines.

- [ ] **Step 3: Verify schema/registry numbers**

`grep -c "_register(TableDef" src/schema/registry.py` — compare against MASTER.md's stated table count. Update if needed.

- [ ] **Step 4: Commit**

```bash
git add docs/MASTER.md CHANGELOG.md
git commit -m "docs: v0.25.0 changelog + MASTER.md for diagnostic dashboard

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Full test suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run full pytest**

```bash
python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: pass count ≥ 1339 per CLAUDE.md; no new failures vs. baseline.

- [ ] **Step 2: Run guardrail tests**

```bash
python -m pytest tests/test_schema.py tests/test_repo_structure.py -v
```

Expected: `test_no_create_table_in_source`, `test_no_alter_table_in_source`, file-length checks all pass.

- [ ] **Step 3: Run ruff lint**

```bash
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/ --check
```

Expected: clean.

- [ ] **Step 4: Run Postgres migrate (DRY or real)**

```bash
# Only run if DATABASE_URL is available; otherwise note the required command
DATABASE_URL=$(python -c "import yaml; cfg=yaml.safe_load(open('config/settings.local.yaml')); print(cfg['render']['database_url'])") python scripts/render_migrate.py
```

Expected: two new tables created in Postgres; sync tables list updated.

If DATABASE_URL is not available in the environment, document in the PR body that the operator must run this before deploying.

- [ ] **Step 5: No commit needed** — verification task.

---

## Self-review

### Spec coverage check

| Spec section | Task(s) |
|---|---|
| §3.1 `diagnostic_runs` schema | Task 1 |
| §3.2 `diagnostic_run_plots` schema | Task 1 |
| §4.1–§4.6 API endpoints | Task 6 |
| §5.1 backend modules | Tasks 2, 3, 4, 5, 6 |
| §5.2 frontend modules | Tasks 7–13 |
| §6 summary extraction | Tasks 2, 3 |
| §7 error handling | Task 4 (handler level), Task 6 (API level), Task 11 (frontend level) |
| §8 testing | Tasks 1, 2, 3, 4, 5, 6, 14, 16 |
| §9 file manifest | All tasks |
| §10 non-goals | enforced by absence |
| §11 R1–R7 matrix | verified by task outputs |

### Placeholder scan

Searched for TBD/TODO/FIXME/"similar to Task N"/"add appropriate…" — none found.

### Type consistency check

- `run_id` is TEXT everywhere ✓
- `status` values are `queued|running|completed|failed` everywhere ✓
- `diagnostic_type` values are `regime|forensic` everywhere ✓
- Handler function names: `_handle_run_regime_diagnostic`, `_handle_run_forensic_audit` (used consistently in tests and registration)
- Command names in `COMMAND_HANDLERS`: `run-regime-diagnostic`, `run-forensic-audit` (match API route command assembly)
- `pending_commands.command_name` stored as `run-regime-diagnostic` — matches what the executor dispatches on ✓

No inconsistencies.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-18-diagnostic-dashboard.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Operator has pre-authorized inline execution and bypass of mid-sprint check-ins, so proceeding with **Inline Execution** via `superpowers:executing-plans`.
