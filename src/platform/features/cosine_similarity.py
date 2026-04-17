"""YoY cosine similarity for 10-K / 10-Q section comparisons.

Called by: src.platform.backtest_engine (via signal_eval providers),
           src.platform.shadow_harness (Sprint 4).
Calls: sqlite3, sklearn.feature_extraction.text, sklearn.metrics.pairwise.
Owns tables: none (read-only from edgar_filings).
Tests: tests/platform/test_lazy_prices.py.

Pure function — no DB writes. Reads sections_json from edgar_filings for
a given accession and its prior-year same-form predecessor, computes
TF-IDF cosine similarity.
"""

from __future__ import annotations

import json
import sqlite3

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as _sk_cos


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


def cosine_similarity_yoy(
    ticker: str, accession: str, section_key: str, db_path: str,
) -> float | None:
    """Cosine similarity of section `section_key` between the filing at
    `accession` and its prior-year same-form predecessor.

    Returns None if either side is missing or the section is empty.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT form_type, sections_json FROM edgar_filings "
            "WHERE accession_number = ?",
            (accession,),
        ).fetchone()
        if row is None or not row[1]:
            return None
        form_type, cur_json = row
        prior_acc = _prior_year_accession(
            conn, ticker, accession, form_type,
        )
        if prior_acc is None:
            return None
        prior_row = conn.execute(
            "SELECT sections_json FROM edgar_filings "
            "WHERE accession_number = ?",
            (prior_acc,),
        ).fetchone()
        if prior_row is None or not prior_row[0]:
            return None
    finally:
        conn.close()
    cur_sections = json.loads(cur_json)
    prior_sections = json.loads(prior_row[0])
    cur_text = cur_sections.get(section_key, "").strip()
    prior_text = prior_sections.get(section_key, "").strip()
    if not cur_text or not prior_text:
        return None
    vec = TfidfVectorizer().fit_transform([prior_text, cur_text])
    return float(_sk_cos(vec[0:1], vec[1:2])[0][0])
