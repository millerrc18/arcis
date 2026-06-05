"""Tests for the graceful global PAUSE engine (T4 — Founder Console design D10).

Covers:
- set_pause / clear_pause / read_pause_state / is_paused round-trip through
  the single-row console_pause_state table.
- set_pause AND clear_pause each emit an activity_log audit entry.
- Non-vacuous gating: the watch-loop scan entry SHORT-CIRCUITS when paused and
  RUNS the scan body when not paused (proven by observing the real branch, not
  merely a mock call count).
- The executor new-trade entry (open_shadow_trade) is gated when paused.
- Monitoring / reconcile are NOT gated by pause (graceful = keep them alive).

All DB writers/readers patch connect_db so the function gets its own fresh PG
connection (closed on __exit__). A separate raw connection verifies state.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ── Skip whole module if TEST_DATABASE_URL is absent ─────────────────────────

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgres"),
    reason="integration(authoritative-coverage:pg-tests)",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pg_wrapper():
    """Return a fresh PostgresConnectionWrapper against the test PG."""
    import psycopg2
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _provision_table(wrapper) -> None:
    """Create console_pause_state if absent (single-row id=1 table)."""
    wrapper.execute("""
        CREATE TABLE IF NOT EXISTS console_pause_state (
            id INTEGER PRIMARY KEY,
            is_paused INTEGER NOT NULL DEFAULT 0,
            paused_at TEXT,
            paused_by TEXT,
            reason TEXT,
            resumed_at TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    wrapper.commit()


def _wipe_table(wrapper) -> None:
    wrapper.execute("DELETE FROM console_pause_state")
    wrapper.commit()


def _read_row(wrapper) -> dict | None:
    row = wrapper.execute(
        "SELECT * FROM console_pause_state WHERE id = 1"
    ).fetchone()
    return dict(row) if row is not None else None


@pytest.fixture(autouse=True)
def _clean_pause_table():
    """Provision + wipe before each test; wipe after."""
    w = _make_pg_wrapper()
    _provision_table(w)
    _wipe_table(w)
    w.close()

    yield

    w2 = _make_pg_wrapper()
    _wipe_table(w2)
    w2.close()


# ── State round-trip ────────────────────────────────────────────────────────

class TestPauseStateRoundTrip:

    def test_default_state_is_not_paused(self):
        from src.console import pause

        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper):
            state = pause.read_pause_state()
            assert state["is_paused"] is False
            assert pause.is_paused() is False

    def test_set_pause_writes_single_row(self):
        from src.console import pause

        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            pause.set_pause(reason="operator break", source="cli")

        verify = _make_pg_wrapper()
        row = _read_row(verify)
        count = verify.execute(
            "SELECT COUNT(*) FROM console_pause_state"
        ).fetchone()[0]
        verify.close()

        assert count == 1, "PAUSE must be a single-row (id=1) table"
        assert row is not None
        assert row["id"] == 1
        assert row["is_paused"] == 1
        assert row["paused_by"] == "cli"
        assert row["reason"] == "operator break"
        assert row["paused_at"] is not None
        assert row["resumed_at"] is None

    def test_set_then_clear_round_trip(self):
        from src.console import pause

        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            pause.set_pause(reason="r", source="cli")
            assert pause.is_paused() is True
            assert pause.read_pause_state()["is_paused"] is True

            pause.clear_pause(source="cli")
            assert pause.is_paused() is False
            state = pause.read_pause_state()
            assert state["is_paused"] is False
            assert state["resumed_at"] is not None

        # Still a single row after set+clear (upsert, never a 2nd insert).
        verify = _make_pg_wrapper()
        count = verify.execute(
            "SELECT COUNT(*) FROM console_pause_state"
        ).fetchone()[0]
        verify.close()
        assert count == 1


# ── Audit logging ───────────────────────────────────────────────────────────

class TestPauseAuditLog:

    def test_set_pause_audit_logs(self):
        from src.console import pause

        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity") as mock_log:
            pause.set_pause(reason="big news", source="api")

        assert mock_log.call_count == 1
        args, _ = mock_log.call_args
        # detail (2nd positional) names the action + source + reason
        detail = args[1]
        assert "api" in detail
        assert "big news" in detail

    def test_clear_pause_audit_logs(self):
        from src.console import pause

        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity") as mock_log:
            pause.clear_pause(source="dashboard")

        assert mock_log.call_count == 1
        args, _ = mock_log.call_args
        detail = args[1]
        assert "dashboard" in detail


# ── Non-vacuous scan gating ─────────────────────────────────────────────────

class TestWatchScanGate:
    """The scan entry must short-circuit when paused and run the body when not.

    Non-vacuous: we patch the FIRST real dependency the scan body imports
    (run_universe_scan). If the gate were removed, the body would import + call
    it. We assert it is NOT reached when paused, and IS reached when running —
    so each assertion provably fails if the gate is wrong.
    """

    def _make_loop(self):
        from src.scheduler.watch import WatchLoop
        loop = WatchLoop.__new__(WatchLoop)
        return loop

    def test_scan_short_circuits_when_paused(self):
        loop = self._make_loop()
        with patch("src.console.pause.is_paused", return_value=True), \
                patch("src.scheduler.universe_scanner.run_universe_scan") as mock_scan:
            loop._run_scan()
        mock_scan.assert_not_called()

    def test_scan_runs_body_when_not_paused(self):
        loop = self._make_loop()
        # Minimal state the body touches before bailing on an aborted scan.
        loop.config = {}
        loop._scan_number = 0
        result = MagicMock()
        result.aborted = True
        result.universe_count = 0
        loop._refresh_live_prices = MagicMock()
        loop._record_scan_metrics = MagicMock()

        with patch("src.console.pause.is_paused", return_value=False), \
                patch("src.scheduler.universe_scanner.run_universe_scan",
                      return_value=result) as mock_scan:
            loop._run_scan()

        # Gate let the body through → the real scan entry was reached.
        mock_scan.assert_called_once()


# ── Executor new-trade gating ───────────────────────────────────────────────

class TestExecutorTradeGate:

    def _packet(self):
        pkt = MagicMock()
        pkt.ticker = "AAPL"
        return pkt

    def test_open_shadow_trade_gated_when_paused(self):
        from src.shadow_trading import executor

        with patch("src.shadow_trading.executor.load_config",
                   return_value={"shadow_trading": {"enabled": True}}), \
                patch("src.console.pause.is_paused", return_value=True), \
                patch("src.llm.validator.validate_llm_output") as mock_validate:
            result = executor.open_shadow_trade(
                "rec-1", self._packet(), {}, db_path=":memory:"
            )

        assert result is None
        # Gate short-circuited BEFORE validation — proves we hit the branch,
        # not just that the function returned None for some other reason.
        mock_validate.assert_not_called()

    def test_open_shadow_trade_passes_gate_when_not_paused(self):
        from src.shadow_trading import executor

        # Not paused: the gate must let control proceed to validation, where
        # we reject so no real trade is opened. Proves the gate didn't block.
        with patch("src.shadow_trading.executor.load_config",
                   return_value={"shadow_trading": {"enabled": True}}), \
                patch("src.console.pause.is_paused", return_value=False), \
                patch("src.llm.validator.validate_llm_output",
                      return_value=(False, "rejected for test")) as mock_validate:
            result = executor.open_shadow_trade(
                "rec-1", self._packet(), {}, db_path=":memory:"
            )

        assert result is None
        mock_validate.assert_called_once()


# ── Monitoring / reconcile are NOT gated ────────────────────────────────────

class TestMonitoringNotGated:
    """Graceful pause must keep monitoring + reconcile alive.

    The gate lives only in _run_scan and open_shadow_trade. We assert the
    monitoring / reconcile entry points contain NO is_paused gate by exercising
    that they do not import/call the pause module. (Source-level guard: the
    pause import does not appear in the monitoring path.)
    """

    def test_reconcile_does_not_import_pause_gate(self):
        import inspect

        from src.shadow_trading import reconcile

        src = inspect.getsource(reconcile)
        assert "console.pause" not in src, (
            "reconcile must NOT be gated by graceful pause"
        )

    def test_check_and_manage_open_trades_not_pause_gated(self):
        import inspect

        from src.shadow_trading import order_lifecycle

        src = inspect.getsource(order_lifecycle.check_and_manage_open_trades)
        assert "is_paused" not in src and "console.pause" not in src, (
            "position monitoring must NOT be gated by graceful pause"
        )
