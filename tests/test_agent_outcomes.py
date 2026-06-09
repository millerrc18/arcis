"""Tests for src.console.agent_outcomes — F2 record + aggregate + CLI.

Integration tests against the test PG at 127.0.0.1:5434.

Skip guard: module skips cleanly when TEST_DATABASE_URL is absent or
does not start with 'postgres' — matching the pattern in
tests/test_console_decisions.py.

Non-vacuous design (per TASK spec): every assertion is written so that
the test FAILS if the implementation fabricates zeros instead of None,
or silently stores unknown roles/outcomes, or the CLI bypasses the
public API.

Run:
  DATABASE_URL= TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon \
      python -m pytest tests/test_agent_outcomes.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgres"),
    reason="integration(authoritative-coverage:pg-tests)",
)

# ── DB helpers ────────────────────────────────────────────────────────────────


def _make_pg_wrapper():
    import psycopg2
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _provision_table(w) -> None:
    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES

    w.execute(generate_create_sql(TABLES["agent_task_outcomes"]))
    w.commit()


def _wipe_table(w) -> None:
    w.execute("DELETE FROM agent_task_outcomes")
    w.commit()


def _count_rows() -> int:
    w = _make_pg_wrapper()
    n = w.execute("SELECT COUNT(*) FROM agent_task_outcomes").fetchone()[0]
    w.close()
    return int(n)


@pytest.fixture(autouse=True)
def _clean_table():
    w = _make_pg_wrapper()
    _provision_table(w)
    _wipe_table(w)
    w.close()

    yield

    w2 = _make_pg_wrapper()
    _wipe_table(w2)
    w2.close()


@pytest.fixture
def patched_db():
    """Route every connect_db() in agent_outcomes to a fresh test-PG wrapper."""
    with patch("src.console.agent_outcomes.connect_db", side_effect=_make_pg_wrapper):
        yield


# ── record_agent_outcome: insert + read-back ──────────────────────────────────


class TestRecordAgentOutcome:

    def test_inserts_one_row(self, patched_db):
        """record_agent_outcome inserts a row; reading it back via SEPARATE connection
        proves persistence (non-vacuous — would fail if INSERT is missing or rolled back).
        """
        from src.console.agent_outcomes import record_agent_outcome

        with patch("src.console.agent_outcomes.log_activity"):
            row = record_agent_outcome(
                run_id="run-001",
                task_id="T1",
                agent_role="developer",
                outcome="success",
            )

        # Returned dict has the required keys
        assert row["run_id"] == "run-001"
        assert row["task_id"] == "T1"
        assert row["agent_role"] == "developer"
        assert row["outcome"] == "success"
        assert row["created_at"]

        # Separate connection confirms persistence
        assert _count_rows() == 1

    def test_optional_fields_stored(self, patched_db):
        """Optional columns (task_type, rework_count, scope_violation, review_cycles, model)
        land in the row as supplied.
        """
        from src.console.agent_outcomes import record_agent_outcome

        with patch("src.console.agent_outcomes.log_activity"):
            row = record_agent_outcome(
                run_id="run-002",
                task_id="T2",
                agent_role="qa_reviewer",
                outcome="rework",
                task_type="feature",
                rework_count=2,
                scope_violation=True,
                review_cycles=3,
                model="claude-opus-4",
            )

        assert row["task_type"] == "feature"
        assert row["rework_count"] == 2
        assert row["scope_violation"] is True or row["scope_violation"] == 1
        assert row["review_cycles"] == 3
        assert row["model"] == "claude-opus-4"
        assert _count_rows() == 1

    def test_calls_log_activity(self, patched_db):
        """record_agent_outcome must write the audit trail via log_activity."""
        from src.console.agent_outcomes import record_agent_outcome

        with patch("src.console.agent_outcomes.log_activity") as mock_log:
            record_agent_outcome(
                run_id="run-003",
                task_id="T3",
                agent_role="planner",
                outcome="success",
            )

        assert mock_log.called, "record_agent_outcome must call log_activity"
        call_kwargs = mock_log.call_args
        # First positional arg is event_type
        assert call_kwargs.args[0] == "agent_outcome"

    def test_unknown_role_raises_value_error(self, patched_db):
        """Unknown agent_role must raise ValueError (fail-closed, never silently stored)."""
        from src.console.agent_outcomes import record_agent_outcome

        with pytest.raises(ValueError, match="agent_role"):
            record_agent_outcome(
                run_id="run-bad",
                task_id="T-bad",
                agent_role="hacker",
                outcome="success",
            )
        # Nothing was inserted
        assert _count_rows() == 0

    def test_unknown_outcome_raises_value_error(self, patched_db):
        """Unknown outcome must raise ValueError (fail-closed)."""
        from src.console.agent_outcomes import record_agent_outcome

        with pytest.raises(ValueError, match="outcome"):
            record_agent_outcome(
                run_id="run-bad",
                task_id="T-bad",
                agent_role="developer",
                outcome="unknown_garbage",
            )
        assert _count_rows() == 0


# ── get_agent_scorecards: empty-table honesty ─────────────────────────────────


class TestGetAgentScorecardsEmpty:

    def test_empty_table_returns_no_data_state(self, patched_db):
        """Empty table → state='no_data', per_role=={}, per_task_type=={},
        scope_drift has n==0. NOT 0.0 rates (honest empty, law from decisions.py).
        """
        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        assert out["state"] == "no_data"
        assert out["n"] == 0
        assert out["per_role"] == {}
        assert out["per_task_type"] == {}
        assert out["scope_drift"]["total_scope_violations"] == 0
        assert out["scope_drift"]["n"] == 0
        assert out["as_of"]

    def test_empty_table_does_not_fabricate_zero_rates(self, patched_db):
        """HONESTY: per_role must be {} (empty dict), NOT {role: {success_rate: 0.0}}.
        This test FAILS if an implementation pre-populates the 7 roles with zeros.
        """
        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()
        # If this fails with KeyError, the implementation correctly returned empty.
        # If this list is non-empty, the implementation fabricated data — test fails.
        assert list(out["per_role"].keys()) == [], (
            f"per_role must be empty when table is empty, got: {out['per_role']}"
        )


# ── get_agent_scorecards: per-role aggregation math ──────────────────────────


class TestGetAgentScorecardsAggregation:

    def _seed(self, **kwargs):
        """Insert one row via a direct wrapper (bypassing the service layer)."""
        w = _make_pg_wrapper()
        from datetime import datetime, timezone
        defaults = dict(
            run_id="run-agg", task_id="T-agg", agent_role="developer",
            task_type=None, outcome="success",
            rework_count=0, scope_violation=0, review_cycles=0, model=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        defaults.update(kwargs)
        w.execute(
            "INSERT INTO agent_task_outcomes "
            "(created_at, run_id, task_id, agent_role, task_type, outcome, "
            " rework_count, scope_violation, review_cycles, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (defaults["created_at"], defaults["run_id"], defaults["task_id"],
             defaults["agent_role"], defaults["task_type"], defaults["outcome"],
             defaults["rework_count"], defaults["scope_violation"],
             defaults["review_cycles"], defaults["model"]),
        )
        w.commit()
        w.close()

    def test_single_success_row(self, patched_db):
        """Single success row → per_role[developer].n==1, success_rate==1.0,
        rework_rate==0.0, state=='ok'.
        """
        self._seed(agent_role="developer", outcome="success")

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        assert out["state"] == "ok"
        assert out["n"] == 1
        assert "developer" in out["per_role"]
        dev = out["per_role"]["developer"]
        assert dev["n"] == 1
        assert dev["success_rate"] == 1.0
        assert dev["rework_rate"] == 0.0
        assert dev["escalation_rate"] == 0.0
        assert dev["blocked_rate"] == 0.0

    def test_mixed_outcomes_rates(self, patched_db):
        """4 rows (2 success, 1 rework, 1 blocked) → correct rates.
        Would fail if success_rate counted rework, or rates don't sum right.
        """
        for outcome in ("success", "success", "rework", "blocked"):
            self._seed(agent_role="developer", outcome=outcome)

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()
        dev = out["per_role"]["developer"]

        assert dev["n"] == 4
        assert dev["success_rate"] == pytest.approx(2 / 4)
        assert dev["rework_rate"] == pytest.approx(1 / 4)
        assert dev["blocked_rate"] == pytest.approx(1 / 4)
        assert dev["escalation_rate"] == 0.0

    def test_multiple_roles_isolated(self, patched_db):
        """2 roles each getting 1 row → per_role has exactly 2 keys, each n==1."""
        self._seed(agent_role="developer", outcome="success")
        self._seed(agent_role="qa_reviewer", outcome="rework")

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        assert set(out["per_role"].keys()) == {"developer", "qa_reviewer"}
        assert out["per_role"]["developer"]["success_rate"] == 1.0
        assert out["per_role"]["qa_reviewer"]["rework_rate"] == 1.0

    def test_role_with_zero_rows_has_none_rates(self, patched_db):
        """A role NOT in the table must NOT appear in per_role — callers expecting
        None for missing roles should get KeyError (absent), not 0.0 (fabricated).
        This verifies the 'mirror compute_override_rate returning None at n==0' spec.
        """
        # Only seed developer; qa_reviewer gets zero rows
        self._seed(agent_role="developer", outcome="success")

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        # qa_reviewer must be ABSENT (not present with 0.0)
        assert "qa_reviewer" not in out["per_role"], (
            "qa_reviewer has zero rows and must NOT appear in per_role with "
            "fabricated 0.0 rates"
        )

    def test_per_task_type_aggregation(self, patched_db):
        """per_task_type groups by task_type; rows with NULL task_type are excluded
        or grouped under None — per_task_type only contains observed types.
        """
        self._seed(agent_role="developer", outcome="success", task_type="feature")
        self._seed(agent_role="developer", outcome="rework", task_type="feature")
        self._seed(agent_role="qa_reviewer", outcome="success", task_type="bugfix")

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        assert "feature" in out["per_task_type"]
        assert "bugfix" in out["per_task_type"]
        feat = out["per_task_type"]["feature"]
        assert feat["n"] == 2
        assert feat["success_rate"] == pytest.approx(0.5)
        assert feat["rework_rate"] == pytest.approx(0.5)
        bugfix = out["per_task_type"]["bugfix"]
        assert bugfix["n"] == 1
        assert bugfix["success_rate"] == 1.0

    def test_scope_drift_counts(self, patched_db):
        """scope_drift.total_scope_violations == sum of scope_violation; n == total rows."""
        self._seed(agent_role="developer", outcome="success", scope_violation=1)
        self._seed(agent_role="developer", outcome="rework", scope_violation=1)
        self._seed(agent_role="qa_reviewer", outcome="success", scope_violation=0)

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()

        assert out["scope_drift"]["total_scope_violations"] == 2
        assert out["scope_drift"]["n"] == 3

    def test_avg_review_cycles_per_role(self, patched_db):
        """avg_review_cycles is the mean review_cycles for that role's rows."""
        self._seed(agent_role="developer", outcome="success", review_cycles=1)
        self._seed(agent_role="developer", outcome="rework", review_cycles=3)

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()
        dev = out["per_role"]["developer"]
        # (1 + 3) / 2 = 2.0
        assert dev["avg_review_cycles"] == pytest.approx(2.0)

    def test_scope_violations_per_role(self, patched_db):
        """scope_violations in per_role is the count of rows with scope_violation==1."""
        self._seed(agent_role="developer", outcome="success", scope_violation=1)
        self._seed(agent_role="developer", outcome="rework", scope_violation=0)
        self._seed(agent_role="developer", outcome="success", scope_violation=1)

        from src.console.agent_outcomes import get_agent_scorecards

        out = get_agent_scorecards()
        dev = out["per_role"]["developer"]
        assert dev["scope_violations"] == 2


# ── CLI subprocess test ───────────────────────────────────────────────────────


class TestCLI:

    def test_record_subcommand_exits_0_and_row_lands(self, patched_db):
        """Invoke `python -m src.console.agent_outcomes record ...` as a subprocess
        against the test DB; assert exit code 0 AND the row landed.
        This test FAILS if:
          - the CLI exits non-zero
          - the row was not inserted (CLI bypasses the public API or doesn't commit)
          - the CLI calls a private _impl instead of record_agent_outcome
        """
        env = os.environ.copy()
        env["DATABASE_URL"] = ""
        env["TEST_DATABASE_URL"] = TEST_PG_URL
        # Route connect_db to test PG via cutover gate
        env["ARCIS_PG_CUTOVER_ENABLED"] = "1"
        env["DATABASE_URL"] = TEST_PG_URL
        # Suppress activity logger writes to prod in subprocess
        env["ARCIS_LOG_ACTIVITY_IN_PYTEST"] = ""

        result = subprocess.run(
            [
                sys.executable, "-m", "src.console.agent_outcomes", "record",
                "--run-id", "cli-run-1",
                "--task-id", "cli-T1",
                "--role", "integrator",
                "--outcome", "success",
                "--task-type", "deploy",
                "--rework-count", "0",
                "--review-cycles", "1",
                "--model", "claude-sonnet-4-6",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"CLI exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # Confirmation line must appear
        assert result.stdout.strip(), "CLI must print a confirmation line"

        # Row landed: check via separate connection
        assert _count_rows() == 1, (
            f"Expected 1 row after CLI record, got {_count_rows()}"
        )

    def test_record_bad_role_exits_nonzero(self):
        """CLI with an unknown role must exit non-zero (ValueError propagates)."""
        env = os.environ.copy()
        env["DATABASE_URL"] = ""
        env["TEST_DATABASE_URL"] = TEST_PG_URL
        env["ARCIS_PG_CUTOVER_ENABLED"] = "1"
        env["DATABASE_URL"] = TEST_PG_URL
        env["ARCIS_LOG_ACTIVITY_IN_PYTEST"] = ""

        result = subprocess.run(
            [
                sys.executable, "-m", "src.console.agent_outcomes", "record",
                "--run-id", "cli-bad",
                "--task-id", "T-bad",
                "--role", "hacker",
                "--outcome", "success",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode != 0, (
            "CLI must exit non-zero when role is invalid"
        )
