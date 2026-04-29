"""Tests for src/attribution/logger.py — two-phase alpha attribution."""

import sqlite3
from unittest.mock import patch

import pytest

from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES


@pytest.fixture
def db_path(tmp_path):
    """Create temp DB with attribution_trades table."""
    path = str(tmp_path / "test.sqlite3")
    with sqlite3.connect(path) as conn:
        conn.executescript(generate_create_sql(TABLES["attribution_trades"]))
    return path


def _get_row(db_path, attr_id):
    """Helper: fetch a single attribution row by ID."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM attribution_trades WHERE attribution_id = ?",
            (attr_id,),
        ).fetchone()


# ── Phase 1: log_attribution_before_llm ──────────────────────────────


class TestLogBeforeLLM:
    def test_inserts_row_returns_uuid(self, db_path):
        from src.attribution.logger import log_attribution_before_llm

        attr_id = log_attribution_before_llm(
            ticker="AAPL", ranker_score=85.0,
            entry_price=150.0, stop_price=145.0, target_price=165.0,
            db_path=db_path,
        )

        assert attr_id is not None
        assert isinstance(attr_id, str)
        assert len(attr_id) == 36  # UUID format

        row = _get_row(db_path, attr_id)
        assert row is not None
        assert row["ticker"] == "AAPL"
        assert row["ranker_score"] == 85.0
        assert row["llm_action"] == "pending"
        assert row["ranker_only_outcome"] == "pending"
        assert row["ranker_only_entry"] == 150.0
        assert row["ranker_only_stop"] == 145.0
        assert row["ranker_only_target"] == 165.0

    def test_graceful_on_bad_db(self, tmp_path):
        """Returns an ID even if DB write fails (never crashes)."""
        from src.attribution.logger import log_attribution_before_llm

        bad_path = str(tmp_path / "nonexistent_dir" / "bad.db")
        attr_id = log_attribution_before_llm(
            ticker="MSFT", ranker_score=70.0,
            entry_price=400.0, stop_price=390.0, target_price=420.0,
            db_path=bad_path,
        )
        # Should still return an ID (graceful failure)
        assert attr_id is not None


# ── Phase 2: log_attribution_after_llm ───────────────────────────────


class TestLogAfterLLM:
    def _setup_pending_row(self, db_path, attr_id="test-attr-001"):
        """Insert a pending attribution row for Phase 2 tests."""
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO attribution_trades "
                "(attribution_id, ticker, scan_timestamp, ranker_score, "
                "llm_action, ranker_only_entry, ranker_only_stop, "
                "ranker_only_target, ranker_only_outcome, created_at) "
                "VALUES (?, 'AAPL', '2026-04-01T10:00:00', 80.0, "
                "'pending', 150.0, 145.0, 160.0, 'pending', '2026-04-01T10:00:00')",
                (attr_id,),
            )
            conn.commit()

    def test_updates_action_and_conviction(self, db_path):
        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path)
        log_attribution_after_llm(
            "test-attr-001", llm_action="taken",
            llm_conviction=8, db_path=db_path,
        )

        row = _get_row(db_path, "test-attr-001")
        assert row["llm_action"] == "taken"
        assert row["llm_conviction"] == 8
        assert row["pair_type"] == "both_taken"

    def test_pair_type_mapping(self, db_path):
        from src.attribution.logger import log_attribution_after_llm

        cases = {
            "taken": "both_taken",
            "rejected": "llm_rejected",
            "parse_failed": "llm_rejected",
            "conviction_none": "llm_rejected",
        }
        for i, (action, expected_pair) in enumerate(cases.items()):
            attr_id = f"test-attr-{i:03d}"
            self._setup_pending_row(db_path, attr_id=attr_id)
            log_attribution_after_llm(attr_id, llm_action=action, db_path=db_path)

            row = _get_row(db_path, attr_id)
            assert row["pair_type"] == expected_pair, (
                f"Action '{action}' should map to pair_type '{expected_pair}', "
                f"got '{row['pair_type']}'"
            )

    def test_rejects_non_canonical_action(self, db_path):
        """Writer must raise on non-canonical llm_action (#846 regression).

        Bootcamp archive accumulated 80 'buy' + 147 'skip' rows because
        scan_service.py wrote non-canonical labels. The §4 t-test in
        attribution_readout silently excluded them. This guard makes the
        bug surface at write time instead of contaminating the table.
        """
        import pytest as _pytest

        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path)
        for bad in ("buy", "skip", "BUY", "Taken", "", "unknown"):
            with _pytest.raises(ValueError, match="not canonical"):
                log_attribution_after_llm(
                    "test-attr-001", llm_action=bad, db_path=db_path,
                )


# ── simulate_mechanical_outcome ──────────────────────────────────────


class TestSimulateMechanical:
    def test_win_on_target_hit(self):
        from src.attribution.logger import simulate_mechanical_outcome

        ohlcv = [
            {"High": 155, "Low": 148, "Close": 152},
            {"High": 158, "Low": 151, "Close": 157},
            {"High": 162, "Low": 155, "Close": 161},  # Target 160 hit
        ]
        outcome, exit_price, days = simulate_mechanical_outcome(
            entry_price=150, stop_price=145, target_price=160,
            timeout_days=7, ohlcv=ohlcv,
        )
        assert outcome == "win"
        assert exit_price == 160
        assert days == 3

    def test_loss_on_stop_hit(self):
        from src.attribution.logger import simulate_mechanical_outcome

        ohlcv = [
            {"High": 152, "Low": 149, "Close": 150},
            {"High": 148, "Low": 144, "Close": 146},  # Stop 145 hit
        ]
        outcome, exit_price, days = simulate_mechanical_outcome(
            entry_price=150, stop_price=145, target_price=160,
            timeout_days=7, ohlcv=ohlcv,
        )
        assert outcome == "loss"
        assert exit_price == 145
        assert days == 2

    def test_stop_checked_before_target(self):
        """If both stop and target hit on same bar, stop wins (conservative)."""
        from src.attribution.logger import simulate_mechanical_outcome

        ohlcv = [
            {"High": 162, "Low": 144, "Close": 150},  # Both hit
        ]
        outcome, exit_price, days = simulate_mechanical_outcome(
            entry_price=150, stop_price=145, target_price=160,
            timeout_days=7, ohlcv=ohlcv,
        )
        assert outcome == "loss"
        assert exit_price == 145

    def test_timeout_when_no_hit(self):
        from src.attribution.logger import simulate_mechanical_outcome

        ohlcv = [
            {"High": 153, "Low": 148, "Close": 151},
            {"High": 154, "Low": 147, "Close": 152},
            {"High": 155, "Low": 149, "Close": 153},
        ]
        outcome, exit_price, days = simulate_mechanical_outcome(
            entry_price=150, stop_price=140, target_price=170,
            timeout_days=3, ohlcv=ohlcv,
        )
        assert outcome == "timeout"
        assert exit_price == 153  # Last close
        assert days == 3

    def test_empty_ohlcv(self):
        from src.attribution.logger import simulate_mechanical_outcome

        outcome, exit_price, days = simulate_mechanical_outcome(
            entry_price=150, stop_price=145, target_price=160,
            timeout_days=7, ohlcv=[],
        )
        assert outcome == "timeout"
        assert exit_price == 150
        assert days == 0


# ── resolve_pending_outcomes ─────────────────────────────────────────


class TestResolvePendingOutcomes:
    @patch("yfinance.download")
    def test_resolves_pending_row(self, mock_download, db_path):
        import pandas as pd
        from src.attribution.logger import resolve_pending_outcomes

        # Insert a pending row
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO attribution_trades "
                "(attribution_id, ticker, scan_timestamp, ranker_score, "
                "llm_action, ranker_only_entry, ranker_only_stop, "
                "ranker_only_target, ranker_only_outcome, created_at) "
                "VALUES ('resolve-1', 'MSFT', '2026-03-25T10:00:00', 75.0, "
                "'taken', 400.0, 390.0, 420.0, 'pending', '2026-03-25T10:00:00')"
            )
            conn.commit()

        # Mock yfinance to return data where target is hit
        mock_download.return_value = pd.DataFrame({
            "High": [405.0, 410.0, 425.0],
            "Low": [395.0, 398.0, 405.0],
            "Close": [403.0, 408.0, 420.0],
        })

        resolved = resolve_pending_outcomes(db_path=db_path)
        assert resolved == 1

        row = _get_row(db_path, "resolve-1")
        assert row["ranker_only_outcome"] == "win"
        assert row["ranker_only_pnl_pct"] is not None


# ── get_attribution_stats ────────────────────────────────────────────


class TestGetAttributionStats:
    def test_empty_table(self, db_path):
        from src.attribution.logger import get_attribution_stats

        stats = get_attribution_stats(db_path=db_path)
        assert stats["total_pairs"] == 0
        assert stats["statistical_power"] == "insufficient"

    def test_with_data(self, db_path):
        from src.attribution.logger import get_attribution_stats

        with sqlite3.connect(db_path) as conn:
            for i in range(5):
                action = "taken" if i < 3 else "rejected"
                pair = "both_taken" if i < 3 else "llm_rejected"
                outcome = "win" if i < 2 else "loss"
                conn.execute(
                    "INSERT INTO attribution_trades "
                    "(attribution_id, ticker, ranker_score, llm_action, "
                    "pair_type, ranker_only_outcome, created_at) "
                    "VALUES (?, 'TEST', 80.0, ?, ?, ?, ?)",
                    (f"stat-{i}", action, pair, outcome,
                     "2026-04-01T10:00:00"),
                )
            conn.commit()

        stats = get_attribution_stats(db_path=db_path)
        assert stats["total_pairs"] == 5
        assert stats["by_action"]["taken"] == 3
        assert stats["by_action"]["rejected"] == 2
        assert stats["by_pair_type"]["both_taken"] == 3
        assert stats["ranker_only"]["resolved"] == 5
        assert stats["ranker_only"]["wins"] == 2
        assert stats["statistical_power"] == "insufficient"


# ── link_trade_outcome ──────────────────────────────────────────────


class TestLinkTradeOutcome:
    def test_links_outcome_to_attribution(self, db_path):
        from src.attribution.logger import log_attribution_before_llm, log_attribution_after_llm, link_trade_outcome
        attr_id = log_attribution_before_llm("AAPL", 85.0, 150.0, 147.0, 154.0, db_path=db_path)
        log_attribution_after_llm(attr_id, "taken", llm_conviction=7, recommendation_id="rec-123", db_path=db_path)
        result = link_trade_outcome("rec-123", "win", 3.5, db_path=db_path)
        assert result is True
        row = _get_row(db_path, attr_id)
        assert row["llm_portfolio_outcome"] == "win"
        assert row["llm_portfolio_pnl_pct"] == 3.5

    def test_returns_false_for_missing_rec(self, db_path):
        from src.attribution.logger import link_trade_outcome
        result = link_trade_outcome("nonexistent-rec", "loss", -2.0, db_path=db_path)
        assert result is False

    def test_handles_loss_outcome(self, db_path):
        from src.attribution.logger import log_attribution_before_llm, log_attribution_after_llm, link_trade_outcome
        attr_id = log_attribution_before_llm("MSFT", 70.0, 300.0, 294.0, 309.0, db_path=db_path)
        log_attribution_after_llm(attr_id, "taken", llm_conviction=5, recommendation_id="rec-456", db_path=db_path)
        result = link_trade_outcome("rec-456", "loss", -4.2, db_path=db_path)
        assert result is True
        row = _get_row(db_path, attr_id)
        assert row["llm_portfolio_outcome"] == "loss"
        assert row["llm_portfolio_pnl_pct"] == -4.2


class TestAttributionFailureIsolation:
    """Attribution calls must never crash the scan or executor."""

    def test_phase1_failure_does_not_crash(self, db_path):
        from src.attribution.logger import log_attribution_before_llm
        # Should not raise — returns UUID even if DB insert fails (error logged)
        result = log_attribution_before_llm("AAPL", 85.0, 150.0, 147.0, 154.0, db_path="/nonexistent/path.db")
        assert isinstance(result, str)  # UUID returned, insert silently failed

    def test_link_outcome_failure_does_not_crash(self, db_path):
        from src.attribution.logger import link_trade_outcome
        result = link_trade_outcome("any-rec", "win", 5.0, db_path="/nonexistent/path.db")
        assert result is False


# ── parse_failed column (#850) ───────────────────────────────────────────────


class TestParseFailed:
    """Tests for the parse_failed boolean column on attribution_trades (#850).

    Verifies that log_attribution_after_llm accepts and persists the
    parse_failed flag, distinguishing parser-failure conviction=5 rows from
    real medium-conviction takes.
    """

    def _setup_pending_row(self, db_path, attr_id="pf-attr-001"):
        """Insert a pending attribution row for parse_failed tests."""
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO attribution_trades "
                "(attribution_id, ticker, scan_timestamp, ranker_score, "
                "llm_action, ranker_only_entry, ranker_only_stop, "
                "ranker_only_target, ranker_only_outcome, created_at) "
                "VALUES (?, 'AAPL', '2026-04-28T10:00:00', 80.0, "
                "'pending', 150.0, 145.0, 160.0, 'pending', '2026-04-28T10:00:00')",
                (attr_id,),
            )
            conn.commit()

    def test_parse_failed_true_persisted(self, db_path):
        """Writer persists parse_failed=True (1 in SQLite INTEGER column)."""
        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path, "pf-true-001")
        log_attribution_after_llm(
            "pf-true-001",
            llm_action="taken",
            llm_conviction=5,
            parse_failed=True,
            db_path=db_path,
        )

        row = _get_row(db_path, "pf-true-001")
        assert row["parse_failed"] == 1

    def test_parse_failed_false_persisted(self, db_path):
        """Writer persists parse_failed=False (0) — the default clean-parse case."""
        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path, "pf-false-001")
        log_attribution_after_llm(
            "pf-false-001",
            llm_action="taken",
            llm_conviction=7,
            parse_failed=False,
            db_path=db_path,
        )

        row = _get_row(db_path, "pf-false-001")
        assert row["parse_failed"] == 0

    def test_parse_failed_default_is_false(self, db_path):
        """parse_failed defaults to False when omitted — no breaking change."""
        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path, "pf-default-001")
        log_attribution_after_llm(
            "pf-default-001",
            llm_action="taken",
            llm_conviction=8,
            db_path=db_path,
        )

        row = _get_row(db_path, "pf-default-001")
        assert row["parse_failed"] == 0

    def test_non_canonical_action_still_rejected_with_parse_failed(self, db_path):
        """Validator still rejects non-canonical actions even when parse_failed is passed."""
        import pytest as _pytest
        from src.attribution.logger import log_attribution_after_llm

        self._setup_pending_row(db_path, "pf-invalid-001")
        with _pytest.raises(ValueError, match="not canonical"):
            log_attribution_after_llm(
                "pf-invalid-001",
                llm_action="buy",
                llm_conviction=5,
                parse_failed=True,
                db_path=db_path,
            )
