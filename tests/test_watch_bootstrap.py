import logging
import sqlite3
from datetime import datetime, timezone

from src.data_collection.research_synthesizer import run_weekly_synthesis
from src.scheduler.watch import WatchLoop


def test_ensure_all_tables_creates_council_sync_tables(tmp_path, monkeypatch):
    """Verify the schema registry defines the expected council and activity tables.

    Post schema registry migration, table DDL is centralized in
    src/schema/registry.py rather than in _ensure_all_tables.
    """
    from src.schema.registry import TABLES
    assert "council_sessions" in TABLES
    assert "council_votes" in TABLES
    assert "activity_log" in TABLES
    assert "api_costs" in TABLES


def test_weekly_synthesis_skips_cleanly_without_api_key(tmp_path, monkeypatch, caplog):
    db_path = tmp_path / "research.db"

    from tests.conftest import init_test_db
    init_test_db(str(db_path), ["research_papers"])

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO research_papers
               (title, authors, abstract, url, source, relevance_score,
                relevance_reason, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Test Paper",
                "A. Author",
                "Useful abstract",
                "https://example.com/paper",
                "arxiv",
                0.75,
                "Relevant to training loop",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    monkeypatch.setattr(
        "src.data_collection.research_synthesizer.load_config",
        lambda: {"training": {"anthropic_api_key": ""}, "api": {"models": {}}},
    )

    with caplog.at_level(logging.WARNING):
        result = run_weekly_synthesis(str(db_path))

    assert result["papers_reviewed"] == 1
    assert result["actionable_count"] == 0
    assert result["skipped"] is True
    assert result["error"] == "anthropic api key not configured"
    assert "Anthropic API key not configured" in caplog.text
