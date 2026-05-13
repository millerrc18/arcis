"""Sprint 5 Wave C7a.4 / T20 — STRATEGY CONTEXT header preamble tests.

Covers:
1. strategy_id FK join populates strategy_status + strategy_parent_name in
   header preamble.
2. demoted/abstain status surfaces in the rendered preamble.
3. NULL-strategy_id fallback shows "(unassigned - legacy trade)".

These tests bypass network/Ollama — they exercise enrich_strategy_context
against a synthetic SQLite fixture, then drive _build_feature_prompt directly.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.data_enrichment.enricher import enrich_strategy_context
from src.llm.packet_writer import _build_feature_prompt
from tests.conftest import init_test_db


@pytest.fixture
def strategy_db(tmp_path):
    db = str(tmp_path / "strategy_test.sqlite3")
    init_test_db(db, ["strategy_registry"])
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO strategy_registry (strategy_id, display_name, spec_source, "
            "current_status, current_spec_hash, created_at, last_status_change) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("pullback_v2", "Pullback v2 (Active)", "inline", "production",
             "hash-prod", now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO strategy_registry (strategy_id, display_name, spec_source, "
            "current_status, current_spec_hash, created_at, last_status_change) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mr_demoted_v1", "Mean Reversion v1 (Demoted)", "inline", "deprecated",
             "hash-dep", now_iso, now_iso),
        )
        conn.commit()
    return db


class TestEnrichStrategyContext:
    def test_strategy_fk_join_populates_header(self, strategy_db):
        feat = {"strategy_id": "pullback_v2"}
        enrich_strategy_context(feat, db_path=strategy_db)
        assert feat.get("strategy_status") == "production"
        assert feat.get("strategy_parent_name") == "Pullback v2 (Active)"

    def test_demoted_status_renders_in_preamble(self, strategy_db):
        feat = {"strategy_id": "mr_demoted_v1"}
        enrich_strategy_context(feat, db_path=strategy_db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "=== STRATEGY CONTEXT ===" in prompt
        assert "mr_demoted_v1" in prompt
        assert "deprecated" in prompt
        assert "Mean Reversion v1 (Demoted)" in prompt
        # Preamble appears BEFORE TECHNICAL DATA in the prompt
        idx_strategy = prompt.index("=== STRATEGY CONTEXT ===")
        idx_technical = prompt.index("=== TECHNICAL DATA ===")
        assert idx_strategy < idx_technical


class TestStrategyContextNullFallback:
    def test_null_strategy_id_legacy_fallback(self, tmp_path):
        """NULL strategy_id (legacy trade) renders the unassigned fallback line."""
        db = str(tmp_path / "empty.sqlite3")
        init_test_db(db, ["strategy_registry"])
        feat = {}  # no strategy_id set
        enrich_strategy_context(feat, db_path=db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "=== STRATEGY CONTEXT ===" in prompt
        assert "(unassigned - legacy trade)" in prompt
