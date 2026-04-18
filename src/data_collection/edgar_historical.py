"""EDGAR historical backfill helpers — primary document resolution.

Called by: scripts/backfill_edgar_historical.py, edgar_collector._fetch_filing_text
Calls: SEC EDGAR API (data.sec.gov, www.sec.gov)
Owns tables: none
Config keys: none
Tests: tests/test_backfill_edgar_historical.py

Extracted from edgar_collector.py to keep the main collector under
the 400-line guardrail. These functions handle primary document
resolution via the submissions API and the index.json fallback,
which were added for the historical EDGAR backfill (commits
bfa16ee, 8984e37, f8c70e6).
"""

import logging

import requests

logger = logging.getLogger(__name__)

SEC_HEADERS = {"User-Agent": "Arcis halcyonlabai@gmail.com"}


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
