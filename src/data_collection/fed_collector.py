"""FOMC & Fed communications collector.

Called by: scheduler/watch.py
Calls: none
Owns tables: fed_communications
Config keys: none
Tests: tests/test_data_collectors.py

API: Federal Reserve website (federalreserve.gov), free, public
Table: fed_communications
Schedule: Nightly in overnight pipeline

Scrapes Federal Reserve website for FOMC statements, minutes,
Beige Book summaries, and Fed speeches. Stores full text for
future NLP analysis (sentiment scoring, hawkish/dovish classification).

All sources are free and public. Rate limiting is via time.sleep(0.5)
between page fetches to be respectful to the Fed's servers.

The collector uses _already_collected() to deduplicate by (comm_type, date)
for statements/minutes/beige_book, and by (comm_type, date, title) for
speeches (multiple speeches can occur on the same day).
"""

import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.config import DB_PATH
from src.utils.db import DBIntegrityError, connect_db, engine_aware_upsert

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FED_BASE = "https://www.federalreserve.gov"
FED_HEADERS = {
    "User-Agent": "Arcis halcyonlabai@gmail.com",
    "Accept": "text/html",
}

# Table creation handled by src/schema/registry.py


def _fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch and parse an HTML page from the Fed website."""
    try:
        resp = requests.get(url, headers=FED_HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.debug("[FED] Failed to fetch %s: %s", url, e)
        return None


def _extract_text(soup: BeautifulSoup) -> str:
    """Extract clean text from a Fed page, stripping navigation etc."""
    # Look for the main content area
    content = soup.find("div", {"id": "article"}) or soup.find("div", class_="col-xs-12")
    if content:
        text = content.get_text(separator=" ", strip=True)
    else:
        text = soup.get_text(separator=" ", strip=True)

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_href_date(href: str) -> str | None:
    """Extract a YYYY-MM-DD date from a Fed archive href.

    Tries multiple patterns in order:
      1. 8 consecutive digits not followed by another digit (legacy archive
         format, e.g. fomcminutes20260128.htm). The negative lookahead
         prevents matching within longer digit runs (hash fragments, etc.).
      2. /YYYY/MMDD.htm (alternate current format).
    Month and day components are validated to reject false-positive tokens.
    Returns None if no pattern matches or the components are out of range.
    """
    match = re.search(r"(\d{4})(\d{2})(\d{2})(?!\d)", href)
    if match:
        yyyy, mm, dd = match.group(1), match.group(2), match.group(3)
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return f"{yyyy}-{mm}-{dd}"

    match = re.search(r"/(\d{4})/(\d{2})(\d{2})", href)
    if match:
        yyyy, mm, dd = match.group(1), match.group(2), match.group(3)
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return f"{yyyy}-{mm}-{dd}"

    return None


def _already_collected(
    conn: sqlite3.Connection,
    comm_type: str,
    filing_date: str,
    title: str | None = None,
) -> bool:
    """Return True when the same communication is already stored."""
    if title is None:
        row = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = ? AND date = ?",
            (comm_type, filing_date),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = ? AND date = ? AND title = ?",
            (comm_type, filing_date, title),
        ).fetchone()
    return bool(row)


def _fetch_article_payload(full_url: str) -> tuple[str, int] | None:
    """Fetch and return article text plus word count."""
    time.sleep(0.5)
    page_soup = _fetch_page(full_url)
    if not page_soup:
        return None
    full_text = _extract_text(page_soup)
    return full_text, len(full_text.split()) if full_text else 0


def _store_fed_item(
    conn: sqlite3.Connection,
    *,
    comm_type: str,
    title: str,
    filing_date: str,
    speaker: str | None,
    full_url: str,
    full_text: str,
    word_count: int,
    collected_at: str,
) -> int:
    """Insert one Fed communication row and return 1 when stored."""
    try:
        engine_aware_upsert(
            conn,
            "fed_communications",
            {
                "comm_type": comm_type,
                "title": title,
                "date": filing_date,
                "speaker": speaker,
                "url": full_url,
                "full_text": full_text,
                "word_count": word_count,
                "collected_at": collected_at,
            },
            action="ignore",
        )
        return 1
    except DBIntegrityError:
        return 0


def _collect_link_archive(
    conn: sqlite3.Connection,
    *,
    url: str,
    comm_type: str,
    since_date: str,
    collected_at: str,
    link_filter,
    title_builder,
) -> int:
    """Collect Fed archive pages whose dates are embedded in the href."""
    soup = _fetch_page(url)
    if not soup:
        return 0

    stored = 0
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True).lower()
        if not link_filter(href, text):
            continue
        filing_date = _parse_href_date(href)
        if not filing_date or filing_date < since_date or _already_collected(conn, comm_type, filing_date):
            continue

        full_url = f"{FED_BASE}{href}"
        payload = _fetch_article_payload(full_url)
        if not payload:
            continue
        full_text, word_count = payload
        stored += _store_fed_item(
            conn,
            comm_type=comm_type,
            title=title_builder(filing_date),
            filing_date=filing_date,
            speaker=None,
            full_url=full_url,
            full_text=full_text,
            word_count=word_count,
            collected_at=collected_at,
        )
    return stored


def _collect_fomc_statements(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect FOMC press releases / statements."""
    return _collect_link_archive(
        conn,
        url=f"{FED_BASE}/monetarypolicy/fomccalendars.htm",
        comm_type="statement",
        since_date=since_date,
        collected_at=collected_at,
        link_filter=lambda href, text: href.startswith("/newsevents/pressreleases/monetary"),
        title_builder=lambda filing_date: f"FOMC Statement {filing_date}",
    )


def _collect_fomc_minutes(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect FOMC meeting minutes."""
    return _collect_link_archive(
        conn,
        url=f"{FED_BASE}/monetarypolicy/fomccalendars.htm",
        comm_type="minutes",
        since_date=since_date,
        collected_at=collected_at,
        link_filter=lambda href, text: "fomcminutes" in href and href.endswith(".htm"),
        title_builder=lambda filing_date: f"FOMC Minutes {filing_date}",
    )


def _collect_beige_book(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect Beige Book summaries."""
    return _collect_link_archive(
        conn,
        url=f"{FED_BASE}/monetarypolicy/beige-book-default.htm",
        comm_type="beige_book",
        since_date=since_date,
        collected_at=collected_at,
        link_filter=lambda href, _text: href.startswith("/")
        and ("beigebook" in href.lower() or "beige-book" in href.lower()),
        title_builder=lambda filing_date: f"Beige Book {filing_date}",
    )


def _parse_speech_item(item) -> tuple[str, str, str | None, str] | None:
    """Extract title, date, speaker, and URL metadata from a speech item."""
    date_el = item.find("time") or item.find(class_="itemDate")
    title_el = item.find("a", href=True)
    if not date_el or not title_el:
        return None

    date_text = date_el.get_text(strip=True)
    try:
        filing_date = datetime.strptime(date_text, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None

    href = title_el.get("href", "")
    if not href:
        return None

    title = title_el.get_text(strip=True)
    full_url = f"{FED_BASE}{href}" if href.startswith("/") else href
    speaker = None
    parent_text = item.get_text(separator="|", strip=True)
    for part in parent_text.split("|"):
        candidate = part.strip()
        if candidate and candidate != title and candidate != date_text and len(candidate) < 100:
            speaker = candidate
            break

    return title, filing_date, speaker, full_url


def _collect_speeches(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect recent Fed speeches."""
    stored = 0
    url = f"{FED_BASE}/newsevents/speech.htm"
    soup = _fetch_page(url)
    if not soup:
        return 0

    for item in soup.find_all("div", class_="row"):
        parsed = _parse_speech_item(item)
        if not parsed:
            continue
        title, filing_date, speaker, full_url = parsed
        if filing_date < since_date or _already_collected(conn, "speech", filing_date, title):
            continue
        payload = _fetch_article_payload(full_url)
        if not payload:
            continue
        full_text, word_count = payload
        stored += _store_fed_item(
            conn,
            comm_type="speech",
            title=title,
            filing_date=filing_date,
            speaker=speaker,
            full_url=full_url,
            full_text=full_text,
            word_count=word_count,
            collected_at=collected_at,
        )

    return stored


def collect_fed_communications(
    lookback_days: int = 730,
    db_path: str = DB_PATH,
) -> dict:
    """Collect all Fed communications since last collection or lookback.

    Returns: {"statements": int, "minutes": int, "beige_book": int, "speeches": int}
    """
    now = datetime.now(ET)
    collected_at = now.isoformat()

    # Determine since_date
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM fed_communications").fetchone()
        if row and row[0]:
            since_date = row[0]
        else:
            since_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    result = {"statements": 0, "minutes": 0, "beige_book": 0, "speeches": 0}

    with connect_db(db_path) as conn:
        try:
            result["statements"] = _collect_fomc_statements(conn, since_date, collected_at)
        except Exception as e:
            logger.warning("[FED] FOMC statements failed: %s", e)

        try:
            result["minutes"] = _collect_fomc_minutes(conn, since_date, collected_at)
        except Exception as e:
            logger.warning("[FED] FOMC minutes failed: %s", e)

        try:
            result["beige_book"] = _collect_beige_book(conn, since_date, collected_at)
        except Exception as e:
            logger.warning("[FED] Beige Book failed: %s", e)

        try:
            result["speeches"] = _collect_speeches(conn, since_date, collected_at)
        except Exception as e:
            logger.warning("[FED] Speeches failed: %s", e)

    total = sum(result.values())
    logger.info("[FED] Collection complete: %d total items %s", total, result)
    return result
