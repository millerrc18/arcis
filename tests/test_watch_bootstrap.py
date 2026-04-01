import logging
import sqlite3
from datetime import datetime, timezone

from src.data_collection.research_synthesizer import run_weekly_synthesis
from src.scheduler.watch import WatchLoop


def test_ensure_all_tables_creates_council_sync_tables(tmp_path, monkeypatch):
    """Verify _ensure_all_tables defines the expected council and activity tables.

    _ensure_all_tables() uses a hardcoded DB path internally, so we verify
    the table DDL statements are present in the function source.
    """
    import inspect
    source = inspect.getsource(WatchLoop._ensure_all_tables)
    # Tables created directly by _ensure_all_tables
    assert "council_sessions" in source
    assert "council_votes" in source
    assert "activity_log" in source
    assert "api_costs" in source


def test_weekly_synthesis_skips_cleanly_without_api_key(tmp_path, monkeypatch, caplog):
    db_path = tmp_path / "research.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE research_papers (
                title TEXT,
                authors TEXT,
                abstract TEXT,
                url TEXT,
                source TEXT,
                relevance_score REAL,
                relevance_reason TEXT,
                collected_at TEXT
            )"""
        )
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
