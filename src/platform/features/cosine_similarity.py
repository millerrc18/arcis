"""YoY cosine similarity for 10-K / 10-Q section comparisons.

Called by: src.platform.backtest_engine (via signal_eval providers),
           src.platform.shadow_harness (Sprint 4).
Calls: sqlite3, sklearn.feature_extraction.text, sklearn.metrics.pairwise.
Owns tables: none (read-only from edgar_filings).
Config keys: none.
Tests: tests/platform/test_lazy_prices.py.

Pure function — no DB writes. Reads sections_json from edgar_filings for
a given accession and its prior-year same-form predecessor, computes
TF-IDF cosine similarity.

Hotfix v0.24.0-alpha2.1: When sections_json is NULL, falls back to parsing
section text from full_text via the same regex used by edgar_collector.
This supports the production DB state where backfill_edgar_fulltext.py
populated full_text but sections_json was never derived from it.
"""

from __future__ import annotations

import json
import re
import sqlite3

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as _sk_cos


def _parse_section_from_fulltext(full_text: str, form_type: str, section_key: str) -> str:
    """Extract a single section from full_text using section-header regexes.

    Returns the section text, or "" if not found or full_text is empty.
    This is the fallback path for rows where sections_json is NULL.

    SEC filings often repeat item headers in the TOC and in forward-looking
    disclaimers before the actual section body. This function iterates all
    matches and returns the FIRST match whose body content is substantial
    (> 200 characters after stripping whitespace) to skip TOC entries.
    """
    if not full_text:
        return ""

    # Section header patterns (lookahead stops at the next sibling item)
    patterns: dict[str, tuple[str, str]] = {}
    if form_type == "10-K":
        patterns = {
            "item_1": (
                r"(?i)item\s+1[.\s]+business",
                r"(?i)item\s+(?:1[a-z]|2)\b",
            ),
            "item_1a": (
                r"(?i)item\s+1a[.\s]*(?:risk\s+factors)?",
                r"(?i)item\s+(?:1b|1c|2)\b",
            ),
            "item_7": (
                r"(?i)item\s+7[.\s]*(?:management.s\s+discussion)?",
                r"(?i)item\s+(?:7a|8)\b",
            ),
            "item_8": (
                r"(?i)item\s+8[.\s]*(?:financial\s+statements)?",
                r"(?i)item\s+9\b",
            ),
        }
    elif form_type == "10-Q":
        patterns = {
            "item_2": (
                r"(?i)item\s+2[.\s]*(?:management.s\s+discussion)?",
                r"(?i)item\s+(?:3|4)\b",
            ),
        }

    entry = patterns.get(section_key)
    if not entry:
        return ""
    header_pat, stop_pat = entry

    # Patterns for bodies that are forward-looking disclaimer references, not
    # the actual section body. These appear in SEC filings as cross-references
    # like "Item 1A of this Form 10-K under the heading Risk Factors."
    _REF_PREFIX_RE = re.compile(r"(?i)^\s*(of this form|see item|as described|incorporated|under the heading)")

    # Find all start positions for this section header
    starts = [m.end() for m in re.finditer(header_pat, full_text)]
    for body_start in starts:
        # Find the next stop (next sibling item), or end of doc
        stop_match = re.search(stop_pat, full_text[body_start:], re.DOTALL)
        if stop_match:
            body = full_text[body_start: body_start + stop_match.start()]
        else:
            body = full_text[body_start:]
        body = body.strip()
        # Skip TOC entries (very short), and cross-reference lines that start
        # with "of this Form 10-K" or similar forward-looking boilerplate.
        if len(body) < 200 or _REF_PREFIX_RE.match(body):
            continue
        return body[:50000]
    return ""


def _get_sections(row_data: tuple, form_type: str, section_key: str) -> str:
    """Extract section text from a DB row (sections_json, full_text) tuple.

    Tries sections_json first; falls back to parsing full_text when NULL.
    row_data is (sections_json, full_text).
    """
    sections_json_str, full_text = row_data
    if sections_json_str:
        try:
            sections = json.loads(sections_json_str)
            text = sections.get(section_key, "").strip()
            if text:
                return text
        except (json.JSONDecodeError, AttributeError):
            pass
    # Fallback: parse from full_text (backfill_edgar_fulltext.py populated this
    # but did not derive sections_json from it)
    return _parse_section_from_fulltext(full_text or "", form_type, section_key)


def _prior_year_accession(
    conn: sqlite3.Connection, ticker: str,
    current_accession: str, form_type: str,
) -> str | None:
    row = conn.execute(
        "SELECT filing_date FROM edgar_filings WHERE accession_number = ?",
        (current_accession,),
    ).fetchone()
    if row is None:
        return None
    cur_date = row[0]
    prior = conn.execute(
        """SELECT accession_number FROM edgar_filings
           WHERE ticker = ? AND form_type = ?
             AND filing_date < ?
             AND filing_date >= date(?, '-400 days')
             AND filing_date <= date(?, '-300 days')
           ORDER BY filing_date DESC LIMIT 1""",
        (ticker, form_type, cur_date, cur_date, cur_date),
    ).fetchone()
    return prior[0] if prior else None


def _has_full_text_column(conn: sqlite3.Connection) -> bool:
    """Return True if edgar_filings has a full_text column."""
    cols = {c[1] for c in conn.execute("PRAGMA table_info(edgar_filings)").fetchall()}
    return "full_text" in cols


def cosine_similarity_yoy(
    ticker: str, accession: str, section_key: str, db_path: str,
) -> float | None:
    """Cosine similarity of section `section_key` between the filing at
    `accession` and its prior-year same-form predecessor.

    Returns None if either side is missing or the section is empty.
    Falls back to full_text parsing when sections_json is NULL (hotfix
    v0.24.0-alpha2.1: backfill_edgar_fulltext.py populates full_text but
    does not derive sections_json from it).
    """
    conn = sqlite3.connect(db_path)
    try:
        # Check once whether full_text column exists (test fixtures may omit it)
        use_full_text = _has_full_text_column(conn)
        select_cols = (
            "form_type, sections_json, full_text"
            if use_full_text
            else "form_type, sections_json, NULL"
        )
        row = conn.execute(
            f"SELECT {select_cols} FROM edgar_filings "
            "WHERE accession_number = ?",
            (accession,),
        ).fetchone()
        if row is None:
            return None
        form_type = row[0]
        cur_text = _get_sections((row[1], row[2]), form_type, section_key)
        if not cur_text:
            return None
        prior_acc = _prior_year_accession(
            conn, ticker, accession, form_type,
        )
        if prior_acc is None:
            return None
        prior_row = conn.execute(
            f"SELECT sections_json, {'full_text' if use_full_text else 'NULL'} "
            "FROM edgar_filings WHERE accession_number = ?",
            (prior_acc,),
        ).fetchone()
        if prior_row is None:
            return None
        prior_text = _get_sections((prior_row[0], prior_row[1]), form_type, section_key)
        if not prior_text:
            return None
    finally:
        conn.close()
    vec = TfidfVectorizer().fit_transform([prior_text, cur_text])
    return float(_sk_cos(vec[0:1], vec[1:2])[0][0])
