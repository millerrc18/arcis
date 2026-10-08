"""EDGAR SC TO-I (issuer tender offer) ingestion for odd-lot harvesting.

Fetches tender offer filings from SEC EDGAR, downloads offer documents,
and identifies filings with odd-lot priority provisions (Rule 13e-4(f)(3)(i)).

SEC EDGAR requires a User-Agent header identifying the requester.
Rate limit: max 10 requests/second.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

EDGAR_BASE = "https://www.sec.gov"
EFTS_BASE = "https://efts.sec.gov/LATEST"
DATA_BASE = "https://data.sec.gov"


class EdgarError(Exception):
    """Base for EDGAR client errors."""


class EdgarConfigError(EdgarError):
    """Missing or invalid configuration (fail-closed)."""


class EdgarNetworkError(EdgarError):
    """Network or HTTP error (not swallowed)."""


class EdgarParseError(EdgarError):
    """Response parsing failed."""


def _user_agent() -> str:
    """Get SEC-compliant User-Agent from env. Fail-closed if not set."""
    ua = os.environ.get("ARCIS_SEC_USER_AGENT", "")
    if not ua or "@" not in ua:
        raise EdgarConfigError(
            "ARCIS_SEC_USER_AGENT must be set to a valid contact "
            "(e.g., 'ARCIS Research admin@example.com'). "
            "SEC fair-access policy requires real identification."
        )
    return ua


# Odd-lot indicators — tight patterns only (Rule 13e-4 odd-lot priority)
# Removed: "de minimis" and "not more than N shares" (ordinary boilerplate)
ODDLOT_PATTERNS = [
    r"odd.?lot",
    r"fewer than 100 shares",
    r"less than 100 shares",
    r"odd-lot holders?.*priorit",
    r"priorit.*odd-lot holders?",
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
    """GET with SEC-compliant headers and retry.

    Raises:
        EdgarConfigError: if User-Agent not configured
        EdgarNetworkError: on HTTP/network failure (after retries)
    """
    ua = _user_agent()  # fail-closed if not configured
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", ua)
            req.add_header("Accept-Encoding", "gzip")
            req.add_header("Host", urllib.parse.urlparse(url).netloc)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data: bytes = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            # Don't retry 4xx (client errors); retry 5xx
            if 400 <= e.code < 500:
                raise EdgarNetworkError(f"HTTP {e.code} for {url}") from e
            last_error = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    raise EdgarNetworkError(f"Failed after {retries} attempts: {url}") from last_error


def _process_hits(
    hits: list[dict[str, Any]],
    form: str,
    exclude_amendments: bool,
    filings: list[TenderFiling],
) -> None:
    """Process one page of EFTS hits into filings."""
    for hit in hits:
        src: dict[str, Any] = hit.get("_source", {})
        if not src:
            raise EdgarParseError(f"EFTS hit missing '_source': {str(hit)[:200]}")
        returned_form = str(src.get("form", form))
        if exclude_amendments and returned_form.endswith("/A"):
            continue
        ciks = src.get("ciks", [])
        cik = str(ciks[0]).lstrip("0") if ciks else ""
        accession = str(src.get("adsh", "")).replace("-", "")
        if not accession:
            raise EdgarParseError(f"EFTS hit missing accession: {str(src)[:200]}")
        if any(f.accession == accession for f in filings):
            continue
        disp = src.get("display_names", [""])
        company = str(disp[0]) if disp else str(src.get("c_name", ""))
        filings.append(TenderFiling(
            cik=cik, company=company, form=returned_form,
            filing_date=str(src.get("file_date", "")),
            accession=accession,
        ))


def _search_form(
    form: str,
    start_date: str,
    end_date: str,
    exclude_amendments: bool,
    page_size: int,
) -> list[TenderFiling]:
    """Search one form, paginating EFTS results."""
    filings: list[TenderFiling] = []
    offset = 0
    max_pages = 50  # fail-closed: refuse silent truncation
    for _ in range(max_pages):
        params = {
            "q": f'form:"{form}"',
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
            "forms": form,
            "from": str(offset),
            "size": str(page_size),
        }
        url = f"{EFTS_BASE}/search-index?{urllib.parse.urlencode(params)}"
        raw = _request(url)
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            raise EdgarParseError(f"Invalid JSON from EFTS: {e}") from e

        if "hits" not in data:
            raise EdgarParseError(f"EFTS missing 'hits': {str(data)[:200]}")
        hits_data = data["hits"]
        if "hits" not in hits_data or "total" not in hits_data:
            raise EdgarParseError("EFTS missing hits/total keys")
        hits = hits_data["hits"]
        total_obj = hits_data["total"]
        if not isinstance(total_obj, dict) or "value" not in total_obj:
            raise EdgarParseError(
                f"EFTS total missing 'value': {str(total_obj)[:200]}"
            )
        total = total_obj["value"]
        if not isinstance(total, int) or total < 0:
            raise EdgarParseError(f"EFTS total invalid: {total!r}")
        if not hits:
            break

        _process_hits(hits, form, exclude_amendments, filings)
        offset += len(hits)
        if offset >= total:
            break
        time.sleep(0.2)
    else:
        raise EdgarParseError(
            f"EFTS returned >{max_pages * page_size} results for {form}; "
            "refusing silent truncation. Narrow the date range."
        )
    return filings


def search_tender_offers(
    start_date: str,
    end_date: str | None = None,
    forms: list[str] | None = None,
    exclude_amendments: bool = True,
    page_size: int = 100,
) -> list[TenderFiling]:
    """Search EDGAR full-text for issuer tender offer filings.

    Raises:
        EdgarNetworkError: on API failure (not swallowed)
        EdgarParseError: on invalid JSON response
    """
    forms = forms or ISSUER_TENDER_FORMS
    end_date = end_date or datetime.now(UTC).strftime("%Y-%m-%d")

    filings: list[TenderFiling] = []
    for form in forms:
        if exclude_amendments and form.endswith("/A"):
            continue
        filings.extend(_search_form(
            form, start_date, end_date, exclude_amendments, page_size
        ))
    return filings




def get_filing_index(cik: str, accession: str) -> dict[str, Any]:
    """Fetch the filing index JSON for a given accession number."""
    cik_padded = cik.zfill(10)
    acc_nodash = accession.replace("-", "")
    url = f"{EDGAR_BASE}/Archives/edgar/data/{cik_padded}/{acc_nodash}/index.json"
    raw = _request(url)
    try:
        result: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EdgarParseError(f"Invalid JSON in filing index: {e}") from e
    return result


def find_primary_document(index: dict[str, Any]) -> str:
    """Find the primary offer document (usually EX-99.1 or the TO itself)."""
    items: list[dict[str, Any]] = index.get("directory", {}).get("item", [])
    # Prefer offer to purchase exhibits, then the main filing
    for item in items:
        name = str(item.get("name", "")).lower()
        if "offer" in name and name.endswith((".htm", ".html", ".txt")):
            return str(item["name"])
    for item in items:
        name = str(item.get("name", ""))
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
        Filings with has_oddlot populated; has_oddlot=None with
        oddlot_evidence=["ERROR: <reason>"] if fetch failed (explicit,
        not silent).

    Raises:
        EdgarNetworkError: if the initial search fails
    """
    from datetime import timedelta

    end = datetime.now(UTC)
    start = end - timedelta(days=days_back)
    filings = search_tender_offers(
        start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    )

    for f in filings:
        try:
            index = get_filing_index(f.cik, f.accession)
            doc = find_primary_document(index)
            if not doc:
                f.has_oddlot = None
                f.oddlot_evidence = ["ERROR: no primary document found"]
                continue
            f.primary_doc_url = (
                f"{EDGAR_BASE}/Archives/edgar/data/"
                f"{f.cik.zfill(10)}/{f.accession}/{doc}"
            )
            text = fetch_document_text(f.cik, f.accession, doc)
            has_it, evidence = check_oddlot_provision(text)
            f.has_oddlot = has_it
            f.oddlot_evidence = evidence[:3]
        except EdgarError as e:
            # Typed errors: record explicitly, don't swallow
            f.has_oddlot = None
            f.oddlot_evidence = [f"ERROR: {type(e).__name__}: {e}"]
        time.sleep(0.3)

    return filings
