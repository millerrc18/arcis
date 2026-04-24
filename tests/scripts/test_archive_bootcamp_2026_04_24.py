"""Failing test scaffold for scripts/archive_bootcamp_2026_04_24.py.

TDD RED phase — the target script does NOT exist yet (T2 implements it).
All eight tests are expected to fail at commit time, most likely via
ImportError when the `from scripts.archive_bootcamp_2026_04_24 import ...`
line at the top of each test body tries to resolve a module that has not
been authored. Once T2 lands the script, these same tests should pass
without modification.

References (Friday Bootcamp Archive Sprint, SD#42):
  - docs/sprints/friday_archive_sprint_evaluation.md §6 (seed values,
    mocking requirements — authoritative)
  - docs/sprints/friday_archive_sprint_research.md §2 (schema context)

Determinism:
  - All timestamps are fixed literals.
  - No datetime.utcnow(), uuid.uuid4(), time.time(), or random.
  - Fixture writes exclusively to tmp_path.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Deterministic seed literals (Pass 1 §6)
# ---------------------------------------------------------------------------

TS_ENTRY = "2026-04-01T14:30:00Z"
TS_EXIT = "2026-04-03T20:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_source_db(tmp_path) -> Path:
    """Build a minimal, deterministic source DB per Pass 1 §6.

    Schema is built via src.schema.sqlite.create_all_tables (the registry
    is the single source of truth — never raw CREATE TABLE here). Rows
    are hardcoded literals so two fixture builds produce byte-identical
    DB files after VACUUM normalizes page layout.
    """
    from src.schema.sqlite import create_all_tables

    db_path = tmp_path / "source_fixture.sqlite3"
    create_all_tables(str(db_path))

    with sqlite3.connect(str(db_path)) as conn:
        # shadow_trades — 2 rows: one closed SPY, one open AAPL.
        # Status strings match TERMINAL_STATUSES / ACTIVE_STATUSES in
        # src/shadow_trading/models.py (closed ∈ TERMINAL, open ∈ ACTIVE).
        # Note: spec §6 originally used "active" as a placeholder literal,
        # but "active" is NOT in ACTIVE_STATUSES — the coherent value from
        # the canonical constants is "open". Corrected by T2 (archive script
        # implementation) to match the authoritative constants.
        conn.execute(
            "INSERT INTO shadow_trades ("
            "trade_id, ticker, direction, status, "
            "entry_price, stop_price, target_1, "
            "actual_entry_price, actual_entry_time, "
            "actual_exit_price, actual_exit_time, "
            "pnl_dollars, pnl_pct, "
            "created_at, updated_at, source, broker"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "TEST-TRADE-001", "SPY", "long", "closed",
                500.00, 475.00, 525.00,
                500.00, TS_ENTRY,
                525.00, TS_EXIT,
                25.00, 5.00,
                TS_ENTRY, TS_EXIT, "paper", "alpaca",
            ),
        )
        conn.execute(
            "INSERT INTO shadow_trades ("
            "trade_id, ticker, direction, status, "
            "entry_price, stop_price, target_1, "
            "actual_entry_price, actual_entry_time, "
            "created_at, updated_at, source, broker"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "TEST-TRADE-002", "AAPL", "long", "open",
                180.00, 171.00, 189.00,
                180.00, TS_ENTRY,
                TS_ENTRY, TS_ENTRY, "paper", "alpaca",
            ),
        )

        # training_examples — 1 row.
        conn.execute(
            "INSERT INTO training_examples ("
            "example_id, created_at, source, ticker, "
            "instruction, input_text, output_text, "
            "quality_score, quarantined"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "TEST-EX-001", TS_ENTRY, "test_fixture", "SPY",
                "Analyze the following setup.",
                "SPY pullback to 20MA, RSI 35.",
                "Buy SPY at 500, stop 475, target 525.",
                0.85, 0,
            ),
        )

        # bracket_health — 1 row referencing the active trade.
        conn.execute(
            "INSERT INTO bracket_health ("
            "check_id, trade_id, ticker, "
            "stop_leg_status, target_leg_status, "
            "bracket_intact, checked_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "TEST-CHK-001", "TEST-TRADE-002", "AAPL",
                "active", "active",
                1, TS_ENTRY,
            ),
        )

        # sync_state — 1 row (quiescent-state).
        conn.execute(
            "INSERT INTO sync_state (table_name, last_synced_at) "
            "VALUES (?, ?)",
            ("shadow_trades", TS_ENTRY),
        )
        conn.commit()

        # Normalize page layout so byte-identity checks between archive
        # and source aren't thrown off by page-layout noise (§6 spec).
        conn.execute("VACUUM")

    return db_path


@pytest.fixture
def mock_watch_loop_halted(monkeypatch):
    """Stub ALL FOUR preflight detection mechanisms to "clean" (no watch loop).

    Per Pass 1 §6, the archive preflight has four independent signals
    that AND together. Tests must mock every one — mocking three of four
    is the exact flakiness failure mode the intake fact warned about.

    The target script does not exist yet (TDD red phase), so these
    patches target the most likely import paths. T2 developer should
    adjust if the real script uses different attribute names; the test
    file should otherwise remain stable.
    """
    # 1. data/watch.lock — patch Path.exists to return False for any
    #    path whose name is "watch.lock". This is conservative: any
    #    code path that does `Path(".../watch.lock").exists()` will see
    #    "absent" regardless of what is actually on disk.
    _real_exists = Path.exists

    def _fake_exists(self):
        if self.name == "watch.lock":
            return False
        return _real_exists(self)

    monkeypatch.setattr(Path, "exists", _fake_exists)

    # 2. psutil.process_iter — patch to return empty iterator so any
    #    python+watch scan sees nothing. Import defensively: if the
    #    script doesn't use psutil, patching it costs nothing.
    try:
        import psutil

        monkeypatch.setattr(psutil, "process_iter", lambda *a, **kw: iter(()))
    except ImportError:
        pass

    # 3. nssm status ArcisWatchLoop — patch subprocess.run to return a
    #    completed-process object whose stdout contains SERVICE_STOPPED
    #    for any invocation referencing nssm + ArcisWatchLoop. All other
    #    subprocess.run calls pass through to the real implementation so
    #    downstream machinery (e.g. VACUUM shell-outs, if any) still work.
    _real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "nssm" in cmd_str.lower() and "ArcisWatchLoop" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout="SERVICE_STOPPED", stderr="",
            )
        return _real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # 4. RenderSyncThread presence — patch threading.enumerate() to
    #    exclude anything whose name contains render_sync. Per Pass 1
    #    §3.2, the render sync thread is a daemon inside the watch
    #    loop; transitively, mocks 1-3 already cover this, but we
    #    stub explicitly to be defense-in-depth.
    import threading

    _real_enumerate = threading.enumerate

    def _fake_enumerate():
        return [
            t for t in _real_enumerate()
            if "render_sync" not in (t.name or "").lower()
            and "rendersync" not in (t.name or "").lower().replace("_", "")
        ]

    monkeypatch.setattr(threading, "enumerate", _fake_enumerate)

    return {
        "lockfile_absent": True,
        "process_scan_clean": True,
        "nssm_stopped": True,
        "render_sync_absent": True,
    }


# ---------------------------------------------------------------------------
# Tests — 8 exactly, names verbatim from sprint spec.
# Each test imports from scripts.archive_bootcamp_2026_04_24 (not yet
# implemented) — import failure is the TDD red-phase signal.
# ---------------------------------------------------------------------------


def test_preflight_fails_if_archive_target_exists(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """When the archive target path already exists, preflight must abort
    with a non-zero exit code (expected: 1). The archive script refuses
    to overwrite an existing archive file to prevent silent data loss."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    existing_archive = tmp_path / "archive.sqlite3"
    existing_archive.write_bytes(b"")  # pre-existing file blocks archive

    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(existing_archive),
    ])
    assert exit_code == 1


def test_preflight_fails_if_source_missing(
    tmp_path, mock_watch_loop_halted,
):
    """When the source DB path does not exist on disk, preflight must
    abort with a non-zero exit code (expected: 1). The archive script
    refuses to create an empty or bogus archive from a missing source."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    missing_source = tmp_path / "does_not_exist.sqlite3"
    archive_path = tmp_path / "archive.sqlite3"

    exit_code = main([
        "--apply",
        "--source", str(missing_source),
        "--archive-path", str(archive_path),
    ])
    assert exit_code == 1


def test_preflight_fails_if_watch_loop_running(
    tmp_path, seeded_source_db, monkeypatch,
):
    """When the watch loop is detected as running (any of the four
    detection mechanisms trips), preflight must abort with a non-zero
    exit code (expected: 1). This test deliberately does NOT use the
    mock_watch_loop_halted fixture — instead it simulates a RUNNING
    watch loop via the lockfile signal, and expects abort."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    # Create a fake watch.lock file to trip the preflight.
    lock_dir = tmp_path / "data"
    lock_dir.mkdir(exist_ok=True)
    lockfile = lock_dir / "watch.lock"
    lockfile.write_text("18896")  # fake PID

    # Point any lockfile probe at our tmp_path via env override.
    monkeypatch.setenv("ARCIS_DATA_DIR", str(lock_dir))

    archive_path = tmp_path / "archive.sqlite3"
    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
    ])
    assert exit_code == 1


def test_archive_produces_verifiable_copy(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """After --apply completes successfully, the archive file must exist,
    be a valid SQLite database, and contain the same row counts in the
    four seeded tables as the source DB (shadow_trades=2,
    training_examples=1, bracket_health=1, sync_state=1)."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    archive_path = tmp_path / "archive.sqlite3"
    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
    ])
    assert exit_code == 0, "expected successful archive"
    assert archive_path.exists(), "archive file must be created"

    # Verify row-count parity.
    expected = {
        "shadow_trades": 2,
        "training_examples": 1,
        "bracket_health": 1,
        "sync_state": 1,
    }
    with sqlite3.connect(str(archive_path)) as conn:
        for table, expected_count in expected.items():
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()
            assert row[0] == expected_count, (
                f"{table}: archive has {row[0]} rows, expected {expected_count}"
            )


def test_fresh_db_has_all_tables_zero_rows(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """After --apply completes, the script must also produce a "fresh"
    successor DB at the configured path with the full registry schema
    applied but zero rows in every table. This is the new working DB
    the watch loop will begin writing to post-cutover."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401
    from src.schema.registry import TABLES

    archive_path = tmp_path / "archive.sqlite3"
    fresh_path = tmp_path / "fresh.sqlite3"

    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
        "--fresh-path", str(fresh_path),
    ])
    assert exit_code == 0
    assert fresh_path.exists(), "fresh DB must be created"

    # Every registry table must exist and have zero rows.
    with sqlite3.connect(str(fresh_path)) as conn:
        existing_tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for tname in TABLES:
            assert tname in existing_tables, (
                f"fresh DB missing table {tname}"
            )
            count = conn.execute(
                f"SELECT COUNT(*) FROM {tname}"
            ).fetchone()[0]
            assert count == 0, (
                f"fresh DB table {tname} should be empty, has {count} rows"
            )


def test_manifest_written_correctly(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """After --apply, a manifest file must be written alongside the
    archive, containing at minimum: archive sha256, source path, row
    counts per counted table, and the archive-time timestamp. The
    manifest must be valid JSON (atomic write per Pass 1 §7 Risk 1)."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    archive_path = tmp_path / "archive.sqlite3"
    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
    ])
    assert exit_code == 0

    # Manifest lives adjacent to the archive, same basename + .manifest.json
    manifest_path = archive_path.with_suffix(".manifest.json")
    assert manifest_path.exists(), "manifest file must be written"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "sha256" in manifest, "manifest must record archive sha256"
    assert "row_counts" in manifest, "manifest must record row counts"
    # The 4 seeded tables must be represented.
    for table in ("shadow_trades", "training_examples",
                   "bracket_health", "sync_state"):
        assert table in manifest["row_counts"], (
            f"manifest row_counts must include {table}"
        )


def test_dry_run_writes_nothing(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """--dry-run must exit 0 without writing the archive, the fresh DB,
    or the manifest. It should only print the plan. The source DB must
    be untouched (byte-identical before and after)."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    archive_path = tmp_path / "archive.sqlite3"
    fresh_path = tmp_path / "fresh.sqlite3"
    manifest_path = archive_path.with_suffix(".manifest.json")

    # Snapshot source bytes before dry-run.
    source_bytes_before = seeded_source_db.read_bytes()

    exit_code = main([
        "--dry-run",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
        "--fresh-path", str(fresh_path),
    ])
    assert exit_code == 0, "dry-run should succeed"

    # No output files may exist.
    assert not archive_path.exists(), (
        "dry-run must NOT write the archive file"
    )
    assert not fresh_path.exists(), (
        "dry-run must NOT write the fresh DB file"
    )
    assert not manifest_path.exists(), (
        "dry-run must NOT write the manifest"
    )

    # Source untouched byte-for-byte.
    source_bytes_after = seeded_source_db.read_bytes()
    assert source_bytes_before == source_bytes_after, (
        "dry-run must not modify the source DB"
    )


def test_apply_writes_expected_files(
    tmp_path, seeded_source_db, mock_watch_loop_halted,
):
    """--apply must write all three artifacts: archive DB, fresh DB, and
    manifest JSON. Each must exist and be non-empty. This is the
    end-to-end smoke test that complements the more specific tests
    above (archive contents, fresh-DB schema, manifest structure)."""
    from scripts.archive_bootcamp_2026_04_24 import main  # noqa: F401

    archive_path = tmp_path / "archive.sqlite3"
    fresh_path = tmp_path / "fresh.sqlite3"
    manifest_path = archive_path.with_suffix(".manifest.json")

    exit_code = main([
        "--apply",
        "--source", str(seeded_source_db),
        "--archive-path", str(archive_path),
        "--fresh-path", str(fresh_path),
    ])
    assert exit_code == 0, "apply should succeed"

    for path, label in (
        (archive_path, "archive"),
        (fresh_path, "fresh DB"),
        (manifest_path, "manifest"),
    ):
        assert path.exists(), f"--apply must produce {label} at {path}"
        assert path.stat().st_size > 0, f"{label} must be non-empty"
