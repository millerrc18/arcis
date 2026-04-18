"""SEC EDGAR filing collector.

Called by: scheduler/watch.py
Calls: features/filing_nlp.py
Owns tables: edgar_filings
Config keys: none
Tests: tests/test_data_collectors.py

API: SEC EDGAR (https://data.sec.gov), free, no key required
Rate limit: 10 req/sec (SEC fair access policy), we use 5 req/sec conservatively

Collects 10-K, 10-Q, and 8-K filings for the S&P 100 universe.
First run: last 2 years; subsequent runs: incremental from last filing_date.

Known issues:
  - #126: Accession numbers come in two formats; _normalize_accession() canonicalizes.
  - #127: NLP columns added post-schema; _ensure_nlp_columns() guards the UPDATE.

User-Agent: SEC requires a descriptive User-Agent with contact email.
"""

import html
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

# Table creation: src/schema/registry.py  |  CIK lookup cache (populated from SEC)
_cik_cache: dict[str, str] = {}


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


def _lookup_primary_document(cik: str, accession: str) -> tuple[str, str] | None:
    """Look up primaryDocument via submissions API; return (filename, archives_base) or None."""
    acc_formatted = accession.replace("-", "")
    acc_dashes = (
        f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
        if "-" not in accession and len(accession) >= 18
        else accession
    )
    cik_stripped = cik.lstrip("0") or "0"
    archives_pfx = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_formatted}"
    try:
        sub_resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=15
        )
        if sub_resp.status_code != 200:
            logger.warning("[EDGAR] Submissions API HTTP %s for CIK %s", sub_resp.status_code, cik)
            return None
        recent = sub_resp.json().get("filings", {}).get("recent", {})
        accs = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        for i, acc in enumerate(accs):
            if acc == acc_dashes and i < len(docs):
                return docs[i], archives_pfx
    except Exception as e:
        logger.warning("[EDGAR] Submissions lookup failed %s / %s: %s", cik, accession, e)
        return None
    logger.warning("[EDGAR] Could not resolve primaryDocument for %s / %s", cik, acc_dashes)
    return None


# In-memory cache for index.json responses (keyed by accession_number)
_index_json_cache: dict[str, dict] = {}


def _lookup_primary_document_via_index(
    cik: str, accession: str, form_type: str = ""
) -> tuple[str, str] | None:
    """Look up primaryDocument via EDGAR index.json (last-resort fallback).

    GET https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/index.json

    Returns (filename, archives_base_url) or None.
    """
    if accession in _index_json_cache:
        index_data = _index_json_cache[accession]
    else:
        acc_clean = accession.replace("-", "")
        cik_int = str(int(cik))  # strip leading zeros
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/index.json"

        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
            if resp.status_code != 200:
                logger.warning("[EDGAR] index.json HTTP %s for %s", resp.status_code, url)
                return None
            index_data = resp.json()
            _index_json_cache[accession] = index_data
        except Exception as e:
            logger.warning("[EDGAR] index.json fetch failed for %s: %s", accession, e)
            return None

    items = index_data.get("directory", {}).get("item", [])
    acc_clean = accession.replace("-", "")
    cik_int = str(int(cik))
    archives_base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}"

    # Filter for .htm/.html files
    htm_items = [
        it for it in items
        if it.get("name", "").lower().endswith((".htm", ".html"))
    ]

    if not htm_items:
        logger.warning("[EDGAR] No .htm files in index.json for %s", accession)
        return None

    # Prefer items whose type matches the form_type
    form_base = form_type.replace("/A", "")  # "10-K/A" -> "10-K"
    typed = [it for it in htm_items if it.get("type", "") == form_base]
    if typed:
        return typed[0]["name"], archives_base

    # Fallback: first .htm file (primary document is listed first in SEC convention)
    return htm_items[0]["name"], archives_base


def _fetch_filing_text(cik: str, accession: str) -> str | None:
    """Download full text of a filing. Returns None if too large or on error.

    Fix (Task 0): filing documents live on www.sec.gov/Archives (NOT
    data.sec.gov). Uses _lookup_primary_document to resolve the filename.
    """
    acc_formatted = accession.replace("-", "")

    result = _lookup_primary_document(cik, accession)
    if not result:
        return None
    primary_doc, archives_base = result

    doc_url = f"{archives_base}/{primary_doc}"
    time.sleep(0.2)  # Rate limit

    try:
        doc_resp = requests.get(doc_url, headers=SEC_HEADERS, timeout=30)
        if doc_resp.status_code != 200:
            logger.warning(
                "[EDGAR] Filing fetch returned HTTP %s for %s",
                doc_resp.status_code, doc_url,
            )
            return None

        content = doc_resp.text
        if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
            logger.debug("[EDGAR] Filing too large, skipping: %s", acc_formatted)
            return None

        # Strip HTML tags and decode entities (&#8217; -> ', etc.)
        clean = re.sub(r"<[^>]+>", " ", content)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    except Exception as e:
        logger.warning("[EDGAR] Failed to fetch filing text %s: %s", acc_formatted, e)
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
    # _sep: handles period, space, colon, em-dash, en-dash, hyphen between item number and title
    # _apos: handles apostrophe variants (', \u2019, or residual HTML entities)
    _sep = r"[\s.:\u2014\u2013\-]+"
    _apos = r".{1,6}s"  # "Management's" — apostrophe may be 1-6 chars
    if form_type in ("10-K", "10-K/A"):
        patterns = {
            "item_1": rf"(?i)item\s+1{_sep}business(.*?)(?=item\s+1[a-z]|item\s+2|\Z)",
            "item_1a": rf"(?i)item\s+1a{_sep}risk\s+factors(.*?)(?=item\s+1b|item\s+2|\Z)",
            "item_7": rf"(?i)item\s+7{_sep}management{_apos}\s+discussion(.*?)(?=item\s+7a|item\s+8|\Z)",
            "item_8": rf"(?i)item\s+8{_sep}financial\s+statements(.*?)(?=item\s+9|\Z)",
        }
    elif form_type in ("10-Q", "10-Q/A"):
        patterns = {
            "item_2": rf"(?i)item\s+2{_sep}management{_apos}\s+discussion(.*?)(?=item\s+3|item\s+4|\Z)",
        }
    else:
        # 8-K: capture all items
        patterns = {
            "all_items": r"(?i)(item\s+\d+\.?\d*.*?)(?=item\s+\d+\.?\d*\s|\Z)",
        }

    for key, pattern in patterns.items():
        # findall returns all matches; pick the longest to skip ToC entries
        # (ToC entries match but capture only a page number like "5")
        all_matches = re.findall(pattern, text, re.DOTALL)
        if all_matches:
            section_text = max(all_matches, key=len).strip()
            # Truncate very long sections to 50K chars
            sections[key] = section_text[:50000]

    return sections


def _ensure_nlp_columns(conn: sqlite3.Connection) -> bool:
    """Check that NLP sentiment columns exist (schema handled by registry).

    Returns True if columns are available, False otherwise.
    """
    cols = {c[1] for c in conn.execute("PRAGMA table_info(edgar_filings)").fetchall()}
    needed = ["sentiment_polarity", "sentiment_negative_count",
              "sentiment_uncertainty_count", "cautionary_phrases"]
    missing = [c for c in needed if c not in cols]
    if missing:
        logger.warning("[EDGAR] NLP columns missing — registry schema may need update: %s", missing)
        return False
    return True


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
