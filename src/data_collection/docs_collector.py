"""Collect markdown documentation files into research_docs SQLite table for cloud sync.

Called by: scheduler/watch.py
Calls: none
Owns tables: research_docs
Config keys: none
Tests: tests/test_docs_collector.py
"""

import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

RESEARCH_DOCS_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_docs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    content TEXT NOT NULL,
    size_kb REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

# Category mapping based on filename keywords
DOC_CATEGORIES = {
    "Strategy & Markets": [
        "SP100", "Multi-Strategy", "Alternative_Data", "Market_Event",
        "Pullback", "Regime", "Optimal_Trading_Universe",
    ],
    "Training & Model": [
        "Training_Data", "Optimal_Training", "Gold-Standard", "Preventing_Model",
        "Prompt_Engineering", "GRPO", "Best_Local_LLM", "Halcyon_v2_Training",
    ],
    "Infrastructure": [
        "Halcyon_Framework", "Halcyon_Lab_Scaling", "Data_Infrastructure",
        "Optimal_24x7", "compute_schedule", "Market_Data_APIs",
        "AI_Council",
    ],
    "Business & Legal": [
        "Business_Plan", "From_Solo", "Brand_Identity", "Competitive",
        "Investor", "Options_Trading_Education",
    ],
    "Deep Research": [
        "AI-Powered_Options", "Walk-Forward", "SEC_EDGAR", "Advanced_Risk",
    ],
    "Core": [
        "architecture", "training-guide", "roadmap", "cli-reference",
        "deployment", "telegram-commands",
    ],
}


def _categorize(filename: str) -> str:
    """Determine category based on filename keywords."""
    for category, keywords in DOC_CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in filename.lower():
                return category
    return "Uncategorized"


def _extract_title(content: str, filename: str) -> str:
    """Extract title from first # heading, or derive from filename."""
    for line in content.split("\n")[:10]:
        match = re.match(r"^#\s+(.+)", line)
        if match:
            return match.group(1).strip()
    # Fallback: clean filename
    name = Path(filename).stem
    return name.replace("_", " ").replace("-", " ").title()


def _make_id(filename: str) -> str:
    """Create a stable ID from filename."""
    return hashlib.md5(filename.encode()).hexdigest()[:12]


def populate_research_docs(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Scan docs/ and docs/research/ for .md files and populate research_docs table."""
    project_root = Path(__file__).resolve().parent.parent.parent
    docs_dirs = [
        project_root / "docs",
        project_root / "docs" / "research",
    ]

    now = datetime.now(ET).isoformat()
    docs_found = []

    for docs_dir in docs_dirs:
        if not docs_dir.exists():
            logger.warning("Docs directory not found: %s", docs_dir)
            continue
        for fpath in sorted(docs_dir.iterdir()):
            if fpath.suffix.lower() != ".md" or fpath.is_dir():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                rel_path = str(fpath.relative_to(project_root))
                doc_id = _make_id(rel_path)
                title = _extract_title(content, fpath.name)
                category = _categorize(fpath.name)
                size_kb = round(fpath.stat().st_size / 1024, 1)
                docs_found.append({
                    "id": doc_id,
                    "filename": rel_path.replace("\\", "/"),
                    "title": title,
                    "category": category,
                    "content": content,
                    "size_kb": size_kb,
                    "updated_at": now,
                })
            except Exception as exc:
                logger.warning("Failed to read %s: %s", fpath, exc)

    # Write to SQLite
    try:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(RESEARCH_DOCS_SCHEMA)
            for doc in docs_found:
                conn.execute(
                    "INSERT INTO research_docs (id, filename, title, category, content, size_kb, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "title=excluded.title, category=excluded.category, "
                    "content=excluded.content, size_kb=excluded.size_kb, "
                    "updated_at=excluded.updated_at",
                    (doc["id"], doc["filename"], doc["title"], doc["category"],
                     doc["content"], doc["size_kb"], doc["updated_at"]),
                )
            conn.commit()
        logger.info("[DOCS] Populated %d research docs into database", len(docs_found))
    except Exception as exc:
        logger.error("[DOCS] Failed to populate research_docs: %s", exc)

    return {"docs_found": len(docs_found)}
