"""Tests for audit data-quality filter exclusions (v0.36.13).

Module: tests.evaluation.test_audit_data_quality_filters
Purpose: Verify that the four false-positive audit alerts are suppressed after
         applying the data-quality exclusion filters described in the v0.36.13
         spec (Task T2).

Called by: pytest
Owns tables: none (uses in-memory SQLite fixtures)
Config keys: none
"""

import sqlite3
import tempfile
import os

import pytest


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _make_mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _setup_training_examples_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            quality_score_auto REAL
        )
    """)
    conn.commit()


def _setup_shadow_trades_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shadow_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'closed',
            regime_at_entry TEXT,
            duration_days REAL,
            exit_reason TEXT,
            recommendation_id TEXT,
            pnl_pct REAL,
            pnl_dollars REAL,
            llm_conviction REAL,
            quarantined INTEGER DEFAULT 0
        )
    """)
    conn.commit()


def _db_from_conn(conn: sqlite3.Connection, tmp_dir: str) -> str:
    """Write in-memory DB to a temp file and return path."""
    db_path = os.path.join(tmp_dir, "test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


# ── Alert 1: Quadrant distribution excludes contrastive_* ──────────────────

class TestQuadrantExcludesContrastive:
    """_compute_training_status quadrant block must filter out contrastive_* rows
    and rows with NULL quality_score_auto."""

    def test_quadrant_excludes_contrastive_and_null_quality(self, tmp_path):
        """2 blinded_win + 1 blinded_loss + 3 contrastive_win + 2 contrastive_loss
        + 1 blinded_loss(q=NULL) → sum of quadrants == 3, not 9."""
        conn = _make_mem_db()
        _setup_training_examples_table(conn)

        rows = [
            ("blinded_win", 4.0),    # good process + good outcome
            ("blinded_win", 4.0),    # good process + good outcome
            ("blinded_loss", 3.5),   # good process + bad outcome
            # Below: contrastive rows — must be excluded
            ("contrastive_win", 4.0),
            ("contrastive_win", 4.0),
            ("contrastive_win", 4.0),
            ("contrastive_loss", 3.0),
            ("contrastive_loss", 3.0),
            # NULL quality — must be excluded
            ("blinded_loss", None),
        ]
        conn.executemany(
            "INSERT INTO training_examples (source, quality_score_auto) VALUES (?, ?)",
            rows,
        )
        conn.commit()

        db_path = _db_from_conn(conn, str(tmp_path))

        # Import the helper being tested
        from src.evaluation.cto_report import _compute_training_status

        result = _compute_training_status(7, db_path)
        quadrants = result["training_data_quality"]["quadrant_distribution"]

        total = sum(quadrants.values())
        assert total == 3, (
            f"Expected 3 quadrant rows (2 blinded_win + 1 blinded_loss), got {total}. "
            f"Quadrants: {quadrants}"
        )
        assert quadrants["good_process_good_outcome"] == 2
        assert quadrants["good_process_bad_outcome"] == 1
        assert quadrants["bad_process_good_outcome"] == 0
        assert quadrants["bad_process_bad_outcome"] == 0


# ── Alert 2: Regime classification excludes NULL rows ──────────────────────

class TestRegimePercentExcludesNull:
    """Regime audit check must skip NULL regime_at_entry rows from the
    percentage denominator and report them as a separate field."""

    def test_regime_null_excluded_from_denominator(self, tmp_path):
        """5 GREEN + 3 NULL + 1 BEAR → denominator is 6, not 9.
        NULL count is reported separately. 0/6 unknown → no alert fire."""
        conn = _make_mem_db()
        _setup_shadow_trades_table(conn)

        rows = [
            ("GREEN",),
            ("GREEN",),
            ("GREEN",),
            ("GREEN",),
            ("GREEN",),
            (None,),   # NULL — must be excluded from denominator
            (None,),   # NULL
            (None,),   # NULL
            ("BEAR",),
        ]
        conn.executemany(
            "INSERT INTO shadow_trades (status, regime_at_entry) VALUES ('closed', ?)",
            rows,
        )
        conn.commit()

        db_path = _db_from_conn(conn, str(tmp_path))

        from src.evaluation.auditor import _check_regime_classification

        result = _check_regime_classification(db_path)

        assert result["denominator"] == 6, (
            f"Expected denominator=6 (5 GREEN + 1 BEAR, NULL excluded), got {result['denominator']}"
        )
        assert result["null_count"] == 3, (
            f"Expected null_count=3, got {result['null_count']}"
        )
        assert result["unknown_fraction"] == 0.0, (
            f"Expected 0% unknown fraction (no 'unknown' rows), got {result['unknown_fraction']}"
        )

    def test_regime_null_count_reported_as_separate_field(self, tmp_path):
        """The NULL count must be a separate observability field, not folded into
        the unknown bucket."""
        conn = _make_mem_db()
        _setup_shadow_trades_table(conn)

        conn.execute(
            "INSERT INTO shadow_trades (status, regime_at_entry) VALUES ('closed', NULL)"
        )
        conn.commit()

        db_path = _db_from_conn(conn, str(tmp_path))

        from src.evaluation.auditor import _check_regime_classification

        result = _check_regime_classification(db_path)
        assert "null_count" in result, "null_count must be present as separate field"
        assert result["null_count"] == 1


# ── Alert 3: Hold-period excludes sentinel-999 and unmeasurable exits ───────

class TestAvgHoldExcludesSentinelAndUnmeasurable:
    """All three avg_hold call paths must use _measurable_hold_durations,
    which excludes duration_days==999 and unmeasurable exit_reason values."""

    def _make_trades(self) -> list[dict]:
        """2 real + 3 unknown-999-sentinel + 1 manual-336."""
        return [
            {"duration_days": 2, "exit_reason": "target_1",
             "pnl_dollars": 100, "pnl_pct": 1.0,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
            {"duration_days": 2, "exit_reason": "target_1",
             "pnl_dollars": 100, "pnl_pct": 1.0,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
            {"duration_days": 999, "exit_reason": "unknown",
             "pnl_dollars": 0, "pnl_pct": 0.0,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
            {"duration_days": 999, "exit_reason": "unknown",
             "pnl_dollars": 0, "pnl_pct": 0.0,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
            {"duration_days": 999, "exit_reason": "unknown",
             "pnl_dollars": 0, "pnl_pct": 0.0,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
            {"duration_days": 336, "exit_reason": "manual",
             "pnl_dollars": 50, "pnl_pct": 0.5,
             "max_favorable_excursion": 0, "max_adverse_excursion": 0},
        ]

    def test_cto_report_execution_analysis_avg_hold(self):
        """cto_report line ~440 (_compute_execution_analysis) must exclude
        sentinel+unmeasurable rows, returning avg_hold == 2.0."""
        from src.evaluation.cto_report import _compute_execution_analysis

        result = _compute_execution_analysis(self._make_trades())
        assert result["avg_hold_period_days"] == 2.0, (
            f"Expected avg_hold=2.0, got {result['avg_hold_period_days']}. "
            "Sentinel-999 and manual rows must be excluded."
        )

    def test_cto_report_fund_metrics_avg_hold(self):
        """cto_report line ~756 (_compute_fund_metrics) must exclude
        sentinel+unmeasurable rows, returning avg_hold_period_days == 2.0."""
        from src.evaluation.cto_report import _compute_fund_metrics

        trades = self._make_trades()
        # fund_metrics needs trade_summary as second arg; build minimal
        trade_summary = {
            "max_drawdown_pct": 0,
            "max_drawdown_dollars": 0,
        }
        result = _compute_fund_metrics(trades, trade_summary)
        assert result["avg_hold_period_days"] == 2.0, (
            f"Expected avg_hold_period_days=2.0, got {result['avg_hold_period_days']}. "
            "Sentinel-999 and manual rows must be excluded."
        )

    def test_model_monitor_compute_metrics_avg_hold(self):
        """model_monitor._compute_metrics must exclude sentinel+unmeasurable
        rows, returning avg_holding_days == 2.0."""
        from src.evaluation.model_monitor import _compute_metrics

        result = _compute_metrics(self._make_trades())
        assert result["avg_holding_days"] == 2.0, (
            f"Expected avg_holding_days=2.0, got {result['avg_holding_days']}. "
            "Sentinel-999 and manual rows must be excluded."
        )

    def test_measurable_hold_durations_helper_exported(self):
        """_measurable_hold_durations must be importable from cto_report."""
        from src.evaluation.cto_report import _measurable_hold_durations  # noqa: F401


# ── Alert 4: Confidence calibration excludes orphans and unmeasurable ────────

class TestCalibrationExcludesOrphansAndUnmeasurable:
    """_compute_confidence_calibration must exclude trades with no
    recommendation_id and trades with unmeasurable exit_reason, and must
    report the exclusion counts in the returned dict."""

    def _make_recs(self) -> list[dict]:
        return [
            {"recommendation_id": "rec-1", "llm_conviction": 8},
            {"recommendation_id": "rec-2", "llm_conviction": 8},
            {"recommendation_id": "rec-3", "llm_conviction": 5},
        ]

    def _make_trades(self) -> list[dict]:
        return [
            # 3 orphans (no recommendation_id) — must be excluded
            {"recommendation_id": None, "exit_reason": "stop_loss",
             "pnl_pct": -2.0, "pnl_dollars": -50},
            {"recommendation_id": None, "exit_reason": "stop_loss",
             "pnl_pct": -2.0, "pnl_dollars": -50},
            {"recommendation_id": None, "exit_reason": "timeout",
             "pnl_pct": 0.5, "pnl_dollars": 10},
            # 2 real trades with conviction — must feed the buckets
            {"recommendation_id": "rec-1", "exit_reason": "stop_loss",
             "pnl_pct": -2.0, "pnl_dollars": -50},
            {"recommendation_id": "rec-2", "exit_reason": "stop_loss",
             "pnl_pct": -2.0, "pnl_dollars": -50},
            # 1 trade with rec_id but unmeasurable exit — must be excluded
            {"recommendation_id": "rec-3", "exit_reason": "reconciled_stale",
             "pnl_pct": 0.0, "pnl_dollars": 0},
        ]

    def test_only_measurable_trades_feed_buckets(self):
        """Only 2 trades (rec-1 + rec-2, stop_loss) must feed the conviction
        bands. Orphans and reconciled_stale must be excluded."""
        from src.evaluation.cto_report import _compute_confidence_calibration

        result = _compute_confidence_calibration(self._make_trades(), self._make_recs())

        total = result["total_with_conviction"]
        assert total == 2, (
            f"Expected 2 measurable trades in calibration, got {total}. "
            "Orphans (no rec_id) and reconciled_stale must be excluded."
        )

    def test_exclusion_counts_in_returned_dict(self):
        """Returned dict must contain exclusion-count fields for operator
        visibility."""
        from src.evaluation.cto_report import _compute_confidence_calibration

        result = _compute_confidence_calibration(self._make_trades(), self._make_recs())

        assert "excluded_no_recommendation_id" in result, (
            "Result must report excluded_no_recommendation_id count"
        )
        assert result["excluded_no_recommendation_id"] == 3, (
            f"Expected 3 excluded_no_recommendation_id, got {result['excluded_no_recommendation_id']}"
        )
        assert "excluded_unmeasurable_exit" in result, (
            "Result must report excluded_unmeasurable_exit count"
        )
        assert result["excluded_unmeasurable_exit"] == 1, (
            f"Expected 1 excluded_unmeasurable_exit (reconciled_stale), "
            f"got {result['excluded_unmeasurable_exit']}"
        )
