"""Regression-locks for the v0.36.13 training pipeline fixes.

Tests 1-6 validate:
1. No SELECT st.*, r.* column collision
2. UNMEASURED exit reasons classified correctly
3. UNMEASURED trades skipped before LLM is called
4. Primary INSERT includes outcome_type
5. Contrastive INSERT writes None for outcome_type
6. Dashboard COALESCE reordered (outcome_type first)
"""

import gc
import sqlite3
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Test 1: Explicit SELECT — no star collision
# ---------------------------------------------------------------------------

def test_explicit_select_no_star_collision():
    """SELECT st.*, r.* must not appear; explicit aliases must be present."""
    dc_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "training", "data_collector.py"
    )
    with open(dc_path, encoding="utf-8") as f:
        source = f.read()

    assert "SELECT st.*, r.*" not in source, (
        "Column collision: SELECT st.*, r.* still present in data_collector.py"
    )
    assert "scan_created_at" in source, (
        "Explicit alias scan_created_at not found — explicit column list missing"
    )
    assert "r.enriched_prompt" in source, (
        "r.enriched_prompt not in explicit column list"
    )
    assert "r.trend_state" in source, (
        "r.trend_state not in explicit column list"
    )


# ---------------------------------------------------------------------------
# Test 2: UNMEASURED exit reasons classified correctly
# ---------------------------------------------------------------------------

def test_unmeasured_exit_reasons_classified():
    """Each exit reason in _UNMEASURED_EXIT_REASONS must return UNMEASURED."""
    from src.training.data_collector import _classify_outcome, _UNMEASURED_EXIT_REASONS

    for reason in _UNMEASURED_EXIT_REASONS:
        result = _classify_outcome({"exit_reason": reason, "pnl_dollars": 0})
        assert result == "UNMEASURED", (
            f"exit_reason={reason!r} should return UNMEASURED, got {result!r}"
        )

    # Real LOSS must still return LOSS
    result = _classify_outcome({"exit_reason": "stop_loss", "pnl_dollars": -100})
    assert result == "LOSS", f"stop_loss trade should be LOSS, got {result!r}"


# ---------------------------------------------------------------------------
# Test 3: UNMEASURED trades skipped before LLM is called
# ---------------------------------------------------------------------------

def test_unmeasured_trades_skipped_before_llm():
    """Trade with exit_reason=reconciled_stale must never reach generate_training_example."""
    from src.training.versioning import init_training_tables

    # Build in-memory SQLite DB with required tables
    db_conn = sqlite3.connect(":memory:")
    db_conn.row_factory = sqlite3.Row

    # init_training_tables creates training_examples; we also need shadow_trades
    # and recommendations stubs
    db_conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            quarantined INTEGER,
            actual_exit_time TEXT,
            recommendation_id TEXT,
            exit_reason TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            duration_days INTEGER,
            max_favorable_excursion REAL,
            max_adverse_excursion REAL,
            setup_type TEXT,
            setup_confidence REAL,
            regime_at_entry TEXT,
            vix_at_entry REAL,
            ranking_at_entry INTEGER,
            realized_sector TEXT,
            actual_entry_price REAL,
            entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            target_2 REAL
        )
    """)
    db_conn.execute("""
        CREATE TABLE recommendations (
            recommendation_id TEXT PRIMARY KEY,
            enriched_prompt TEXT,
            price_at_recommendation REAL,
            trend_state TEXT,
            pullback_depth_pct REAL,
            created_at TEXT
        )
    """)
    db_conn.execute("""
        CREATE TABLE training_examples (
            example_id TEXT PRIMARY KEY,
            created_at TEXT,
            source TEXT,
            ticker TEXT,
            recommendation_id TEXT,
            feature_snapshot TEXT,
            trade_outcome TEXT,
            outcome_type TEXT,
            instruction TEXT,
            input_text TEXT,
            output_text TEXT
        )
    """)

    # Insert a single closed trade with reconciled_stale exit
    db_conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, quarantined, actual_exit_time,
         recommendation_id, exit_reason, pnl_dollars, pnl_pct, duration_days,
         max_favorable_excursion, max_adverse_excursion,
         setup_type, regime_at_entry)
        VALUES
        ('t001', 'AAPL', 'closed', 0, '2026-01-10T16:00:00',
         NULL, 'reconciled_stale', 0.0, 0.0, 5,
         100.0, -50.0,
         'pullback_in_trend', 'bull')
    """)
    db_conn.commit()

    # Write db to a temp file so data_collector can open it
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    disk_conn = sqlite3.connect(tmp_path)
    for line in db_conn.iterdump():
        disk_conn.execute(line)
    disk_conn.commit()
    disk_conn.close()
    db_conn.close()

    try:
        mock_gen = MagicMock(return_value=None)
        with patch("src.training.data_collector.generate_training_example", mock_gen), \
             patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"):
            from src.training.data_collector import (
                collect_training_examples_from_closed_trades_detailed,
            )
            result = collect_training_examples_from_closed_trades_detailed(tmp_path)

        mock_gen.assert_not_called(), (
            "generate_training_example was called for a reconciled_stale trade — "
            "UNMEASURED guard must fire before the LLM call"
        )
    finally:
        gc.collect()
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test 4: Primary INSERT includes outcome_type
# ---------------------------------------------------------------------------

def test_primary_insert_includes_outcome_type():
    """The primary INSERT into training_examples must include outcome_type column."""
    import tempfile, os

    # Build temp DB with required tables
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    conn = sqlite3.connect(tmp_path)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            quarantined INTEGER,
            actual_exit_time TEXT,
            recommendation_id TEXT,
            exit_reason TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            duration_days INTEGER,
            max_favorable_excursion REAL,
            max_adverse_excursion REAL,
            setup_type TEXT,
            setup_confidence REAL,
            regime_at_entry TEXT,
            vix_at_entry REAL,
            ranking_at_entry INTEGER,
            realized_sector TEXT,
            actual_entry_price REAL,
            entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            target_2 REAL
        )
    """)
    conn.execute("""
        CREATE TABLE recommendations (
            recommendation_id TEXT PRIMARY KEY,
            enriched_prompt TEXT,
            price_at_recommendation REAL,
            trend_state TEXT,
            pullback_depth_pct REAL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE training_examples (
            example_id TEXT PRIMARY KEY,
            created_at TEXT,
            source TEXT,
            ticker TEXT,
            recommendation_id TEXT,
            feature_snapshot TEXT,
            trade_outcome TEXT,
            outcome_type TEXT,
            instruction TEXT,
            input_text TEXT,
            output_text TEXT
        )
    """)
    # A LOSS trade (negative pnl, non-unmeasured exit reason)
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, quarantined, actual_exit_time,
         recommendation_id, exit_reason, pnl_dollars, pnl_pct, duration_days,
         max_favorable_excursion, max_adverse_excursion,
         setup_type, regime_at_entry)
        VALUES
        ('t002', 'TSLA', 'closed', 0, '2026-01-11T16:00:00',
         NULL, 'stop_loss', -150.0, -3.0, 3,
         50.0, -200.0,
         'pullback_in_trend', 'bull')
    """)
    conn.commit()
    conn.close()

    stage1_resp = (
        "<why_now>Setup context</why_now>"
        "<analysis>Detailed analysis here.</analysis>"
        "<metadata>Conviction: 4\nDirection: LONG</metadata>"
    )

    try:
        call_count = [0]

        def fake_gen(system, user, **kwargs):
            call_count[0] += 1
            return stage1_resp

        with patch("src.training.data_collector.generate_training_example", side_effect=fake_gen), \
             patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.should_halt_batch",
                   return_value=(False, 100.0, None)), \
             patch("src.training.data_collector.alert_training_halt"):
            from src.training.data_collector import (
                collect_training_examples_from_closed_trades_detailed,
            )
            result = collect_training_examples_from_closed_trades_detailed(tmp_path)

        # Verify the row was written with outcome_type
        check_conn = sqlite3.connect(tmp_path)
        check_conn.row_factory = sqlite3.Row
        rows = check_conn.execute(
            "SELECT outcome_type FROM training_examples WHERE source LIKE 'blinded_%'"
        ).fetchall()
        check_conn.close()

        assert len(rows) >= 1, "Expected at least one blinded training example to be inserted"
        for row in rows:
            assert row["outcome_type"] == "LOSS", (
                f"Expected outcome_type='LOSS' in primary INSERT, got {row['outcome_type']!r}"
            )
    finally:
        gc.collect()
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test 5: Contrastive INSERT writes None for outcome_type
# ---------------------------------------------------------------------------

def test_contrastive_insert_writes_null_outcome_type():
    """The contrastive INSERT must have outcome_type in column list with None value."""
    import tempfile, os

    # Check that _emit_contrastive_example SQL includes outcome_type
    dc_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "training", "data_collector.py"
    )
    with open(dc_path, encoding="utf-8") as f:
        source = f.read()

    # Find the _emit_contrastive_example function body and verify outcome_type is in its INSERT
    contrastive_fn_start = source.find("def _emit_contrastive_example(")
    assert contrastive_fn_start != -1, "_emit_contrastive_example function not found"
    # Find the next function def after _emit_contrastive_example to bound the search
    next_fn = source.find("\ndef ", contrastive_fn_start + 1)
    contrastive_body = source[contrastive_fn_start:next_fn if next_fn != -1 else len(source)]
    # Check specifically in the INSERT SQL column list (between INSERT and VALUES)
    insert_start = contrastive_body.find("INSERT INTO training_examples")
    assert insert_start != -1, "INSERT INTO training_examples not found in _emit_contrastive_example"
    values_start = contrastive_body.find("VALUES", insert_start)
    assert values_start != -1, "VALUES clause not found in contrastive INSERT"
    insert_columns_block = contrastive_body[insert_start:values_start]
    assert "outcome_type" in insert_columns_block, (
        "outcome_type column missing from _emit_contrastive_example INSERT column list"
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    conn = sqlite3.connect(tmp_path)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            quarantined INTEGER,
            actual_exit_time TEXT,
            recommendation_id TEXT,
            exit_reason TEXT,
            pnl_dollars REAL,
            pnl_pct REAL,
            duration_days INTEGER,
            max_favorable_excursion REAL,
            max_adverse_excursion REAL,
            setup_type TEXT,
            setup_confidence REAL,
            regime_at_entry TEXT,
            vix_at_entry REAL,
            ranking_at_entry INTEGER,
            realized_sector TEXT,
            actual_entry_price REAL,
            entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            target_2 REAL
        )
    """)
    conn.execute("""
        CREATE TABLE recommendations (
            recommendation_id TEXT PRIMARY KEY,
            enriched_prompt TEXT,
            price_at_recommendation REAL,
            trend_state TEXT,
            pullback_depth_pct REAL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE training_examples (
            example_id TEXT PRIMARY KEY,
            created_at TEXT,
            source TEXT,
            ticker TEXT,
            recommendation_id TEXT,
            feature_snapshot TEXT,
            trade_outcome TEXT,
            outcome_type TEXT,
            instruction TEXT,
            input_text TEXT,
            output_text TEXT
        )
    """)
    # WIN trade (positive pnl, non-unmeasured exit reason) to trigger contrastive
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, quarantined, actual_exit_time,
         recommendation_id, exit_reason, pnl_dollars, pnl_pct, duration_days,
         max_favorable_excursion, max_adverse_excursion,
         setup_type, regime_at_entry)
        VALUES
        ('t003', 'NVDA', 'closed', 0, '2026-01-12T16:00:00',
         NULL, 'target_1_hit', 300.0, 4.5, 4,
         350.0, -80.0,
         'pullback_in_trend', 'bull')
    """)
    conn.commit()
    conn.close()

    stage1_resp = (
        "<why_now>Win context</why_now>"
        "<analysis>Win analysis here.</analysis>"
        "<metadata>Conviction: 8\nDirection: LONG</metadata>"
    )

    try:
        with patch("src.training.data_collector.generate_training_example",
                   return_value=stage1_resp), \
             patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.should_halt_batch",
                   return_value=(False, 100.0, None)), \
             patch("src.training.data_collector.alert_training_halt"):
            from src.training.data_collector import (
                collect_training_examples_from_closed_trades_detailed,
            )
            result = collect_training_examples_from_closed_trades_detailed(tmp_path)

        check_conn = sqlite3.connect(tmp_path)
        check_conn.row_factory = sqlite3.Row
        rows = check_conn.execute(
            "SELECT source, outcome_type FROM training_examples"
        ).fetchall()
        check_conn.close()

        contrastive_rows = [r for r in rows if "contrastive" in (r["source"] or "")]
        assert len(contrastive_rows) >= 1, (
            "Expected at least one contrastive training example to be inserted"
        )
        for row in contrastive_rows:
            assert row["outcome_type"] is None, (
                f"Contrastive INSERT outcome_type must be None, got {row['outcome_type']!r}"
            )
    finally:
        gc.collect()
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test 6: Dashboard COALESCE reordered
# ---------------------------------------------------------------------------

def test_dashboard_coalesce_reordered():
    """COALESCE(outcome_type, outcome, trade_outcome) must appear; old order must not."""
    tr_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "api", "cloud_routes", "training.py"
    )
    with open(tr_path, encoding="utf-8") as f:
        source = f.read()

    assert "COALESCE(outcome_type, outcome, trade_outcome)" in source, (
        "New COALESCE order not found: expected COALESCE(outcome_type, outcome, trade_outcome)"
    )
    assert "COALESCE(trade_outcome, outcome_type, outcome)" not in source, (
        "Old COALESCE order still present: COALESCE(trade_outcome, outcome_type, outcome)"
    )
