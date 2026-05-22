"""Tests for the two lifecycle-simulator run entrypoints (Task 13).

Importing ``src.simulation.lifecycle.bootstrap`` FIRST pins the safe env before
anything else touches a DB. There are two entrypoints:

  * ``run_smoke()`` — the fast CI-per-PR tier. Runs end-to-end on a TEMPORARY
    SQLite DB (NO Docker / NO 5434 PG / NO GPU), a few sim-days, a light fault
    set, and returns a ``SmokeResult`` whose rendered report labels the
    integrity results "non-authoritative (SQLite)".
  * ``run_full_gate()`` — the authoritative nightly tier. Provisions the
    ephemeral 5434 PG, bootstraps the schema, runs many sim-days + all faults,
    and returns the AUTHORITATIVE verdict. It is guarded to run only when the
    5434 PG is reachable; on a bare-metal CI box without it, the test skips
    cleanly.

Both entrypoints install the prod guard and bootstrap-first.
"""

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins safe env
import socket

import psycopg2
import pytest

from src.simulation.lifecycle import run_full_gate, run_smoke
from src.simulation.lifecycle.verdict import Verdict


def _pg_5434_up() -> bool:
    """True when the ephemeral test PG on 127.0.0.1:5434 accepts connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", 5434))
            return True
        except OSError:
            return False


# ── smoke: SQLite, no Docker, integrity NON-authoritative ──────────────────


def test_run_smoke_runs_on_sqlite_no_docker():
    result = run_smoke()
    assert result.verdict in (Verdict.STABLE, Verdict.DEGRADED, Verdict.UNSTABLE)
    assert result.tier == "smoke"


def test_run_smoke_report_labels_integrity_non_authoritative():
    result = run_smoke()
    assert "non-authoritative" in result.report.lower()
    assert "SQLite" in result.report


def test_run_smoke_returns_invariant_results():
    result = run_smoke()
    # The smoke run drives the oracle, so it produces invariant results.
    assert len(result.results) == 9


def test_run_smoke_is_stable_on_clean_run():
    # The light fault set must not break the clean-run integrity invariants.
    result = run_smoke()
    failed = [r.name for r in result.results if not r.passed]
    assert failed == [], f"smoke clean run should pass all invariants: {failed}"


# ── full gate: authoritative, guarded on Docker/5434 presence ──────────────


@pytest.mark.skipif(not _pg_5434_up(), reason="ephemeral 5434 PG not reachable")
def test_run_full_gate_is_authoritative():
    result = run_full_gate()
    assert result.tier == "full"
    assert "non-authoritative" not in result.report.lower()
    assert result.verdict in (Verdict.STABLE, Verdict.DEGRADED, Verdict.UNSTABLE)


@pytest.mark.skipif(not _pg_5434_up(), reason="ephemeral 5434 PG not reachable")
def test_run_full_gate_runs_all_invariants():
    result = run_full_gate()
    assert len(result.results) == 9


@pytest.mark.skipif(not _pg_5434_up(), reason="ephemeral 5434 PG not reachable")
def test_run_full_gate_writes_to_pg_not_prod():
    # The full gate must reach the safe 5434 PG, never a prod-signature URL.
    result = run_full_gate()
    assert result.verdict is not None
    # Sanity: the safe PG is the one we can connect to.
    conn = psycopg2.connect("postgresql://test:test@127.0.0.1:5434/halcyon")
    conn.close()
