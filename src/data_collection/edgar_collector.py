"""SEC EDGAR filing collector.

Called by: scheduler/watch.py
Calls: features/filing_nlp.py
Owns tables: edgar_filings
Config keys: none
Tests: tests/test_data_collectors.py

Collects 10-K, 10-Q, and 8-K filings for the S&P 100 universe.
Stores filing metadata + parsed section text.

API: https://data.sec.gov (no key required, 10 req/sec limit)
User-Agent: Arcis halcyonlabai@gmail.com
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
SEC_HEADERS = {"User-Agent": "Arcis halcyonlabai@gmail.com"}
MAX_TEXT_BYTES = 5 * 1024 * 1024  # 5MB limit per filing

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS edgar_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    cik TEXT NOT NULL,
    form_type TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT UNIQUE NOT NULL,
    filing_url TEXT,
    description TEXT,
    full_text TEXT,
    sections_json TEXT,
    word_count INTEGER,
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edgar_ticker_date
    ON edgar_filings(ticker, filing_date);
"""

# CIK lookup cache (populated from SEC)
_cik_cache: dict[str, str] = {}


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def _load_cik_lookup() -> dict[str, str]:
    """Load ticker → CIK mapping from SEC company_tickers.json."""
    global _cik_cache
    if _cik_cache:
        return _cik_cache

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for _key, entry in data.items():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            if ticker and cik:
                _cik_cache[ticker] = cik.zfill(10)  # Pad to 10 digits

        logger.info("[EDGAR] Loaded CIK mapping for %d tickers", len(_cik_cache))
    except Exception as e:
        logger.warning("[EDGAR] Failed to load CIK lookup: %s", e)

    return _cik_cache


def _get_cik(ticker: str) -> str | None:
    """Get CIK for a ticker, handling BRK.B → BRK-B style variations."""
    lookup = _load_cik_lookup()
    cik = lookup.get(ticker)
    if not cik:
        # Try common ticker variations
        cik = lookup.get(ticker.replace(".", "-"))
    if not cik:
        cik = lookup.get(ticker.replace("-", "."))
    return cik


def _normalize_accession(raw: str) -> str:
    """Normalize accession number to dashed format: 0001193125-21-123456.

    Handles both '0001193125-21-123456' and '000119312521123456' inputs.
    """
    stripped = raw.replace("-", "")
    if len(stripped) == 18:
        return f"{stripped[:10]}-{stripped[10:12]}-{stripped[12:]}"
    # If not 18 digits, return as-is (already dashed or unusual format)
    return raw


def _fetch_filings_from_submissions(
    cik: str, form_type: str, since_date: str
) -> list[dict]:
    """Fall back to the EDGAR submissions API for filing metadata."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        descriptions = recent.get("primaryDocDescription", [])

        filings = []
        for i, form in enumerate(forms):
            if form != form_type:
                continue
            filing_date = dates[i] if i < len(dates) else ""
            if filing_date < since_date:
                continue

            accession = accessions[i] if i < len(accessions) else ""
            desc = descriptions[i] if i < len(descriptions) else ""

            filings.append({
                "form_type": form,
                "filing_date": filing_date,
                "accession_number": _normalize_accession(accession),
                "description": desc,
                "accession_raw": accession,
            })

        return filings
    except Exception as e:
        logger.debug("[EDGAR] Submissions API failed for CIK %s: %s", cik, e)
        return []


def _fetch_filing_text(cik: str, accession: str) -> str | None:
    """Download full text of a filing. Returns None if too large or on error."""
    # Build the filing URL from CIK and accession number
    acc_formatted = accession.replace("-", "")
    acc_dashes = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}" if "-" not in accession and len(accession) >= 18 else accession

    try:
        # Try the index page to find the primary document
        index_url = f"https://data.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_formatted}/"
        resp = requests.get(index_url, headers=SEC_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        # Find the primary .htm or .txt document
        text = resp.text
        # Look for the main filing document (usually the largest .htm file)
        doc_pattern = re.findall(r'href="([^"]+\.(?:htm|txt))"', text)
        if not doc_pattern:
            return None

        # Take the first .htm file (usually the filing itself)
        primary_doc = doc_pattern[0]
        doc_url = f"{index_url}{primary_doc}"

        time.sleep(0.2)  # Rate limit

        doc_resp = requests.get(doc_url, headers=SEC_HEADERS, timeout=30)
        if doc_resp.status_code != 200:
            return None

        content = doc_resp.text
        if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
            logger.debug("[EDGAR] Filing too large, skipping: %s", acc_formatted)
            return None

        # Strip HTML tags for cleaner text
        clean = re.sub(r"<[^>]+>", " ", content)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    except Exception as e:
        logger.debug("[EDGAR] Failed to fetch filing text %s: %s", acc_formatted, e)
        return None


def _parse_sections(text: str, form_type: str) -> dict[str, str]:
    """Extract key sections from filing text using regex.

    For 10-K: Item 1 (Business), Item 7 (MD&A), Item 8 (Financial Statements)
    For 10-Q: Item 2 (MD&A)
    For 8-K: All items
    """
    if not text:
        return {}

    sections = {}
    if form_type == "10-K":
        patterns = {
            "item_1": r"(?i)item\s+1[.\s]+business(.*?)(?=item\s+1[a-z]|item\s+2|\Z)",
            "item_7": r"(?i)item\s+7[.\s]+management.s\s+discussion(.*?)(?=item\s+7a|item\s+8|\Z)",
            "item_8": r"(?i)item\s+8[.\s]+financial\s+statements(.*?)(?=item\s+9|\Z)",
        }
    elif form_type == "10-Q":
        patterns = {
            "item_2": r"(?i)item\s+2[.\s]+management.s\s+discussion(.*?)(?=item\s+3|item\s+4|\Z)",
        }
    else:
        # 8-K: capture all items
        patterns = {
            "all_items": r"(?i)(item\s+\d+\.?\d*.*?)(?=item\s+\d+\.?\d*\s|\Z)",
        }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.DOTALL)
        if match:
            section_text = match.group(1).strip()
            # Truncate very long sections to 50K chars
            sections[key] = section_text[:50000]

    return sections


def _ensure_nlp_columns(conn: sqlite3.Connection) -> bool:
    """Check that NLP sentiment columns exist; add them if missing.

    Returns True if columns are available, False on failure.
    """
    cols = {c[1] for c in conn.execute("PRAGMA table_info(edgar_filings)").fetchall()}
    needed = ["sentiment_polarity", "sentiment_negative_count",
              "sentiment_uncertainty_count", "cautionary_phrases"]
    missing = [c for c in needed if c not in cols]
    if not missing:
        return True
    try:
        for col in missing:
            conn.execute(f"ALTER TABLE edgar_filings ADD COLUMN {col} TEXT")  # noqa: S608
        return True
    except Exception as e:
        logger.warning("[EDGAR] Cannot add NLP columns: %s", e)
        return False


def _run_nlp_scoring(conn: sqlite3.Connection, accession: str, full_text: str) -> None:
    """Score filing text for sentiment and cautionary phrases.

    Checks columns exist before UPDATE to avoid OperationalError (#127).
    """
    if not _ensure_nlp_columns(conn):
        return

    from src.features.filing_nlp import (
        score_filing_sentiment,
        detect_cautionary_phrases,
    )
    sentiment = score_filing_sentiment(full_text)
    cautions = detect_cautionary_phrases(full_text)
    conn.execute(
        """UPDATE edgar_filings SET
            sentiment_polarity = ?,
            sentiment_negative_count = ?,
            sentiment_uncertainty_count = ?,
            cautionary_phrases = ?
        WHERE accession_number = ?""",
        (
            sentiment.get("polarity"),
            sentiment.get("negative_count"),
            sentiment.get("uncertainty_count", 0),
            json.dumps([c["phrase"] for c in cautions]) if cautions else None,
            accession,
        ),
    )


def collect_new_filings(
    tickers: list[str],
    lookback_days: int = 730,
    db_path: str = DB_PATH,
) -> dict:
    """Collect new SEC EDGAR filings for the given tickers.

    First run: collects last 2 years. Subsequent runs: since last collection.

    Returns: {"tickers_processed": int, "filings_stored": int}
    """
    _init_table(db_path)

    now = datetime.now(ET)
    collected_at = now.isoformat()

    # Determine since_date from last collection or lookback
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT MAX(filing_date) FROM edgar_filings").fetchone()
        if row and row[0]:
            since_date = row[0]
        else:
            since_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    form_types = ["10-K", "10-Q", "8-K"]
    tickers_processed = 0
    filings_stored = 0

    with sqlite3.connect(db_path) as conn:
        for ticker in tickers:
            try:
                cik = _get_cik(ticker)
                if not cik:
                    logger.debug("[EDGAR] No CIK found for %s", ticker)
                    continue

                filings = _fetch_filings_from_submissions(cik, form_types[0], since_date)
                for ft in form_types[1:]:
                    filings.extend(_fetch_filings_from_submissions(cik, ft, since_date))
                    time.sleep(0.2)

                for filing in filings:
                    accession = filing.get("accession_number", "")
                    if not accession:
                        continue

                    # Check if we already have this filing
                    exists = conn.execute(
                        "SELECT 1 FROM edgar_filings WHERE accession_number = ?",
                        (accession,),
                    ).fetchone()
                    if exists:
                        continue

                    # Fetch full text (optional — may be large)
                    full_text = _fetch_filing_text(cik, accession)
                    word_count = len(full_text.split()) if full_text else None

                    # Parse sections
                    form = filing.get("form_type", "8-K")
                    sections = _parse_sections(full_text, form) if full_text else {}

                    filing_url = f"https://data.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession.replace('-', '')}/"

                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO edgar_filings
                            (ticker, cik, form_type, filing_date, accession_number,
                             filing_url, description, full_text, sections_json,
                             word_count, collected_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                ticker,
                                cik,
                                form,
                                filing.get("filing_date", ""),
                                accession,
                                filing_url,
                                filing.get("description", ""),
                                full_text,
                                json.dumps(sections) if sections else None,
                                word_count,
                                collected_at,
                            ),
                        )
                        filings_stored += 1

                        # Run NLP sentiment scoring on the filing text
                        if full_text and len(full_text) > 100:
                            try:
                                _run_nlp_scoring(conn, accession, full_text)
                            except ImportError:
                                pass  # pysentiment2 not installed
                            except Exception as nlp_err:
                                logger.debug("[EDGAR] NLP scoring failed for %s: %s", accession, nlp_err)

                    except sqlite3.IntegrityError:
                        pass  # Duplicate accession number

                tickers_processed += 1

            except Exception as e:
                logger.warning("[EDGAR] Failed for %s: %s", ticker, e)

            # Rate limit: 5 req/sec (conservative)
            time.sleep(0.2)

    result = {
        "tickers_processed": tickers_processed,
        "filings_stored": filings_stored,
    }
    logger.info("[EDGAR] Collection complete: %s", result)
    return result
