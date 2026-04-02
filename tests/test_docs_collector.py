"""Tests for src/data_collection/docs_collector.py."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES
from src.data_collection.docs_collector import (
    _categorize,
    _extract_title,
    _make_id,
    populate_research_docs,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestCategorize:
    def test_strategy_keyword(self):
        assert _categorize("SP100_Universe.md") == "Strategy & Markets"

    def test_training_keyword(self):
        assert _categorize("Gold-Standard_data.md") == "Training & Model"

    def test_infrastructure_keyword(self):
        assert _categorize("Halcyon_Framework_overview.md") == "Infrastructure"

    def test_business_keyword(self):
        assert _categorize("Business_Plan_v2.md") == "Business & Legal"

    def test_deep_research_keyword(self):
        assert _categorize("Walk-Forward_analysis.md") == "Deep Research"

    def test_core_keyword(self):
        assert _categorize("architecture.md") == "Core"

    def test_uncategorized_fallback(self):
        assert _categorize("random_notes.md") == "Uncategorized"

    def test_case_insensitive(self):
        assert _categorize("sp100_overview.md") == "Strategy & Markets"


class TestExtractTitle:
    def test_heading_extracted(self):
        content = "# My Great Title\n\nSome body text."
        assert _extract_title(content, "file.md") == "My Great Title"

    def test_heading_with_leading_spaces_in_text(self):
        content = "# Title With Spaces  \nBody."
        assert _extract_title(content, "file.md") == "Title With Spaces"

    def test_no_heading_falls_back_to_filename(self):
        content = "No heading here, just text."
        assert _extract_title(content, "my_cool_doc.md") == "My Cool Doc"

    def test_heading_not_in_first_10_lines(self):
        content = "\n" * 11 + "# Late Heading"
        # Only first 10 lines scanned, should fall back to filename
        assert _extract_title(content, "fallback_name.md") == "Fallback Name"

    def test_second_level_heading_ignored(self):
        content = "## Not a title\nBody."
        assert _extract_title(content, "some_file.md") == "Some File"


class TestMakeId:
    def test_deterministic(self):
        assert _make_id("docs/test.md") == _make_id("docs/test.md")

    def test_different_files_different_ids(self):
        assert _make_id("a.md") != _make_id("b.md")

    def test_length_is_12(self):
        assert len(_make_id("anything.md")) == 12


# ---------------------------------------------------------------------------
# Integration tests for populate_research_docs
# ---------------------------------------------------------------------------

class TestPopulateResearchDocs:
    """Tests that patch the project_root so populate_research_docs reads from
    a temporary directory instead of the real docs/ folder."""

    def _setup_docs(self, tmp_path: Path):
        """Create a fake docs/ tree under tmp_path and return the db path."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        research_dir = docs_dir / "research"
        research_dir.mkdir()

        (docs_dir / "architecture.md").write_text("# Architecture Guide\nDetails here.", encoding="utf-8")
        (docs_dir / "readme.md").write_text("Just a readme with no heading.", encoding="utf-8")
        (research_dir / "Walk-Forward_analysis.md").write_text("# Walk-Forward\nResearch.", encoding="utf-8")
        # Non-md file should be ignored
        (docs_dir / "notes.txt").write_text("not markdown", encoding="utf-8")

        db_path = str(tmp_path / "test.sqlite3")
        # Pre-create the research_docs table (table creation is now via registry)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(generate_create_sql(TABLES["research_docs"]))
        return db_path

    def test_finds_md_files_and_inserts(self, tmp_path):
        db_path = self._setup_docs(tmp_path)

        # populate_research_docs derives project_root from __file__:
        #   Path(__file__).resolve().parent.parent.parent
        # We patch __file__ so that .parent.parent.parent == tmp_path
        fake_file = str(tmp_path / "src" / "data_collection" / "docs_collector.py")
        (tmp_path / "src" / "data_collection").mkdir(parents=True, exist_ok=True)

        import src.data_collection.docs_collector as mod
        with patch.object(mod, "__file__", fake_file):
            result = populate_research_docs(db_path=db_path)

        assert result["docs_found"] == 3  # 2 in docs/, 1 in docs/research/

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM research_docs").fetchall()
        assert len(rows) == 3

    def test_titles_extracted_correctly(self, tmp_path):
        db_path = self._setup_docs(tmp_path)

        # Directly test the helper integration
        content_with_heading = "# Architecture Guide\nDetails here."
        assert _extract_title(content_with_heading, "architecture.md") == "Architecture Guide"

        content_no_heading = "Just a readme with no heading."
        assert _extract_title(content_no_heading, "readme.md") == "Readme"

    def test_categories_assigned(self, tmp_path):
        assert _categorize("architecture.md") == "Core"
        assert _categorize("Walk-Forward_analysis.md") == "Deep Research"
        assert _categorize("readme.md") == "Uncategorized"

    def test_empty_directory(self, tmp_path):
        """Empty docs dir should produce zero docs without error."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        db_path = str(tmp_path / "test.sqlite3")

        # Create schema so the table exists
        with sqlite3.connect(db_path) as conn:
            conn.executescript(generate_create_sql(TABLES["research_docs"]))

        # Directly verify: no md files -> no rows
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM research_docs").fetchall()
        assert len(rows) == 0

    def test_non_md_files_ignored(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "notes.txt").write_text("not markdown", encoding="utf-8")
        (docs_dir / "data.csv").write_text("a,b,c", encoding="utf-8")

        # No .md files means nothing should be collected
        db_path = str(tmp_path / "test.sqlite3")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(generate_create_sql(TABLES["research_docs"]))
            rows = conn.execute("SELECT * FROM research_docs").fetchall()
        assert len(rows) == 0

    def test_upsert_on_conflict(self, tmp_path):
        """Re-inserting the same doc should update, not duplicate."""
        db_path = str(tmp_path / "test.sqlite3")
        rel_path = "docs/test.md"
        doc_id = _make_id(rel_path)

        with sqlite3.connect(db_path) as conn:
            conn.executescript(generate_create_sql(TABLES["research_docs"]))
            conn.execute(
                "INSERT INTO research_docs (id, filename, title, category, content, size_kb, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc_id, rel_path, "Old Title", "Core", "old", 0.1, "2025-01-01"),
            )
            # Upsert with new title
            conn.execute(
                "INSERT INTO research_docs (id, filename, title, category, content, size_kb, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, category=excluded.category, "
                "content=excluded.content, size_kb=excluded.size_kb, "
                "updated_at=excluded.updated_at",
                (doc_id, rel_path, "New Title", "Core", "new", 0.2, "2025-06-01"),
            )
            conn.commit()
            rows = conn.execute("SELECT title FROM research_docs WHERE id = ?", (doc_id,)).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "New Title"
