"""EDGAR SC TO-I (issuer tender offer) ingestion for odd-lot harvesting.

Fetches tender offer filings from SEC EDGAR, downloads offer documents,
and identifies filings with odd-lot priority provisions (Rule 13e-4(f)(3)(i)).

SEC EDGAR requires a User-Agent header identifying the requester.
Rate limit: max 10 requests/second.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone


EDGAR_BASE = "https://www.sec.gov"
EFTS_BASE = "https://efts.sec.gov/LATEST"
DATA_BASE = "https://data.sec.gov"

# SEC requires identifying User-Agent
USER_AGENT = "ARCIS Research contact@arcis.local"

# Odd-lot indicators in offer documents
ODDLOT_PATTERNS = [
    r"odd.?lot",
    r"fewer than 100 shares",
    r"less than 100 shares",
    r"not more than \d+ shares",
    r"de minimis",
    r"small.?lot",
]

# Tender offer form types (issuer side)
ISSUER_TENDER_FORMS = ["SC TO-I", "SC TO-I/A"]


@dataclass
class TenderFiling:
    """A single tender offer filing from EDGAR."""

    cik: str
    company: str
    form: str
    filing_date: str
    accession: str
    primary_doc_url: str = ""
    has_oddlot: bool | None = None  # None = not yet checked
    oddlot_evidence: list[str] = field(default_factory=list)


def _request(url: str, retries: int = 3) -> bytes:
    """GET with SEC-compliant headers and retry."""
    import gzip

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", USER_AGENT)
            req.add_header("Accept-Encoding", "gzip")
            req.add_header("Host", urllib.parse.urlparse(url).netloc)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                # Decompress if gzipped
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                elif data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return data
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def search_tender_offers(
    start_date: str,
    end_date: str | None = None,
    forms: list[str] | None = None,
    exclude_amendments: bool = True,
) -> list[TenderFiling]:
    """Search EDGAR full-text for issuer tender offer filings in a date range.

    Args:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD (defaults to today)
        forms: form types to include (defaults to SC TO-I and amendments)
        exclude_amendments: if True, only return initial SC TO-I (not /A)

    Returns:
        List of TenderFiling (metadata only; documents not yet fetched)
    """
    forms = forms or ISSUER_TENDER_FORMS
    end_date = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    filings: list[TenderFiling] = []
    for form in forms:
        if exclude_amendments and form.endswith("/A"):
            continue
        # EFTS JSON search API
        q = f'form:"{form}"'
        params = {
            "q": q,
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
            "forms": form,
        }
        url = f"{EFTS_BASE}/search-index?{urllib.parse.urlencode(params)}"
        try:
            raw = _request(url)
            data = json.loads(raw)
        except Exception:
            continue

        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            returned_form = src.get("form", form)
            # Filter amendments if requested (check returned form, not query)
            if exclude_amendments and returned_form.endswith("/A"):
                continue
            filings.append(
                TenderFiling(
                    cik=src.get("cik", "").lstrip("0") or src.get("cik", ""),
                    company=src.get("display_names", [""])[0]
                    if src.get("display_names")
                    else src.get("c_name", ""),
                    form=returned_form,
                    filing_date=src.get("file_date", ""),
                    accession=src.get("adsh", "").replace("-", ""),
                )
            )
        time.sleep(0.2)  # stay well under rate limit

    return filings


def get_filing_index(cik: str, accession: str) -> dict:
    """Fetch the filing index JSON for a given accession number."""
    cik_padded = cik.zfill(10)
    acc_nodash = accession.replace("-", "")
    url = f"{EDGAR_BASE}/Archives/edgar/data/{cik_padded}/{acc_nodash}/index.json"
    raw = _request(url)
    return json.loads(raw)


def find_primary_document(index: dict) -> str:
    """Find the primary offer document (usually EX-99.1 or the TO itself)."""
    items = index.get("directory", {}).get("item", [])
    # Prefer offer to purchase exhibits, then the main filing
    for item in items:
        name = item.get("name", "").lower()
        if "offer" in name and name.endswith((".htm", ".html", ".txt")):
            return item["name"]
    for item in items:
        name = item.get("name", "")
        if name.endswith((".htm", ".html")) and "index" not in name.lower():
            return name
    return ""


def fetch_document_text(cik: str, accession: str, doc_name: str) -> str:
    """Download a filing document and return raw text."""
    cik_padded = cik.zfill(10)
    acc_nodash = accession.replace("-", "")
    url = (
        f"{EDGAR_BASE}/Archives/edgar/data/{cik_padded}/{acc_nodash}/{doc_name}"
    )
    raw = _request(url)
    # Strip HTML tags for text search (crude but effective for pattern matching)
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def check_oddlot_provision(text: str) -> tuple[bool, list[str]]:
    """Check document text for odd-lot priority provisions.

    Returns:
        (has_oddlot, evidence_snippets)
    """
    evidence = []
    for pattern in ODDLOT_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 200)
            snippet = text[start:end].strip()
            evidence.append(snippet)
            if len(evidence) >= 5:
                break
        if len(evidence) >= 5:
            break
    return (len(evidence) > 0, evidence)


def scan_recent_offers(days_back: int = 30) -> list[TenderFiling]:
    """End-to-end: find recent issuer tender offers and flag odd-lot provisions.

    Args:
        days_back: how far back to search

    Returns:
        Filings with has_oddlot populated
    """
    from datetime import timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    filings = search_tender_offers(
        start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    )

    for f in filings:
        try:
            index = get_filing_index(f.cik, f.accession)
            doc = find_primary_document(index)
            if not doc:
                continue
            f.primary_doc_url = (
                f"{EDGAR_BASE}/Archives/edgar/data/"
                f"{f.cik.zfill(10)}/{f.accession}/{doc}"
            )
            text = fetch_document_text(f.cik, f.accession, doc)
            has_it, evidence = check_oddlot_provision(text)
            f.has_oddlot = has_it
            f.oddlot_evidence = evidence[:3]
        except Exception:
            f.has_oddlot = None
        time.sleep(0.3)

    return filings
