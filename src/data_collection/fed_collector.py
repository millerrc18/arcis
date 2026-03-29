"""FOMC & Fed communications collector.

Scrapes Federal Reserve website for FOMC statements, minutes,
Beige Book summaries, and Fed speeches. Stores full text for
future NLP analysis.

All sources are free and public (federalreserve.gov).
"""

import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"
FED_BASE = "https://www.federalreserve.gov"
FED_HEADERS = {
    "User-Agent": "Halcyon Lab halcyonlabai@gmail.com",
    "Accept": "text/html",
}

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS fed_communications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comm_type TEXT NOT NULL,
    title TEXT,
    date TEXT NOT NULL,
    speaker TEXT,
    url TEXT,
    full_text TEXT,
    word_count INTEGER,
    collected_at TEXT NOT NULL,
    UNIQUE(comm_type, date, title)
);

CREATE INDEX IF NOT EXISTS idx_fed_comm_type_date
    ON fed_communications(comm_type, date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


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


def _collect_fomc_statements(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect FOMC press releases / statements."""
    stored = 0
    url = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
    soup = _fetch_page(url)
    if not soup:
        return 0

    # Find links to statements (press releases)
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True).lower()

        if "statement" not in text and "press release" not in text:
            continue
        if not href.startswith("/"):
            continue

        # Extract date from URL pattern like /newsevents/pressreleases/monetary20240131a.htm
        date_match = re.search(r"(\d{8})", href)
        if not date_match:
            continue

        raw_date = date_match.group(1)
        filing_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        if filing_date < since_date:
            continue

        full_url = f"{FED_BASE}{href}"

        # Check if already collected
        exists = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = 'statement' AND date = ?",
            (filing_date,),
        ).fetchone()
        if exists:
            continue

        # Fetch full text
        time.sleep(0.5)
        page_soup = _fetch_page(full_url)
        if not page_soup:
            continue

        full_text = _extract_text(page_soup)
        word_count = len(full_text.split()) if full_text else 0

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fed_communications
                (comm_type, title, date, speaker, url, full_text, word_count, collected_at)
                VALUES ('statement', ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    f"FOMC Statement {filing_date}",
                    filing_date,
                    full_url,
                    full_text,
                    word_count,
                    collected_at,
                ),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass

    return stored


def _collect_fomc_minutes(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect FOMC meeting minutes."""
    stored = 0
    url = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
    soup = _fetch_page(url)
    if not soup:
        return 0

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True).lower()

        if "minutes" not in text:
            continue
        if not href.startswith("/"):
            continue

        date_match = re.search(r"(\d{8})", href)
        if not date_match:
            continue

        raw_date = date_match.group(1)
        filing_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        if filing_date < since_date:
            continue

        full_url = f"{FED_BASE}{href}"

        exists = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = 'minutes' AND date = ?",
            (filing_date,),
        ).fetchone()
        if exists:
            continue

        time.sleep(0.5)
        page_soup = _fetch_page(full_url)
        if not page_soup:
            continue

        full_text = _extract_text(page_soup)
        word_count = len(full_text.split()) if full_text else 0

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fed_communications
                (comm_type, title, date, speaker, url, full_text, word_count, collected_at)
                VALUES ('minutes', ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    f"FOMC Minutes {filing_date}",
                    filing_date,
                    full_url,
                    full_text,
                    word_count,
                    collected_at,
                ),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass

    return stored


def _collect_beige_book(
    conn: sqlite3.Connection, since_date: str, collected_at: str
) -> int:
    """Collect Beige Book summaries."""
    stored = 0
    url = f"{FED_BASE}/monetarypolicy/beige-book-default.htm"
    soup = _fetch_page(url)
    if not soup:
        return 0

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "beigebook" not in href.lower() and "beige-book" not in href.lower():
            continue
        if not href.startswith("/"):
            continue

        date_match = re.search(r"(\d{8})", href)
        if not date_match:
            continue

        raw_date = date_match.group(1)
        filing_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        if filing_date < since_date:
            continue

        full_url = f"{FED_BASE}{href}"

        exists = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = 'beige_book' AND date = ?",
            (filing_date,),
        ).fetchone()
        if exists:
            continue

        time.sleep(0.5)
        page_soup = _fetch_page(full_url)
        if not page_soup:
            continue

        full_text = _extract_text(page_soup)
        word_count = len(full_text.split()) if full_text else 0

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fed_communications
                (comm_type, title, date, speaker, url, full_text, word_count, collected_at)
                VALUES ('beige_book', ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    f"Beige Book {filing_date}",
                    filing_date,
                    full_url,
                    full_text,
                    word_count,
                    collected_at,
                ),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass

    return stored


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
        # Find date and speaker
        date_el = item.find("time") or item.find(class_="itemDate")
        title_el = item.find("a", href=True)

        if not date_el or not title_el:
            continue

        date_text = date_el.get_text(strip=True)
        # Parse date like "March 15, 2024"
        try:
            parsed_date = datetime.strptime(date_text, "%B %d, %Y")
            filing_date = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

        if filing_date < since_date:
            continue

        href = title_el.get("href", "")
        title = title_el.get_text(strip=True)
        if not href:
            continue

        full_url = f"{FED_BASE}{href}" if href.startswith("/") else href

        # Try to extract speaker from surrounding text
        speaker = None
        parent_text = item.get_text(separator="|", strip=True)
        parts = parent_text.split("|")
        for part in parts:
            part = part.strip()
            if part and part != title and part != date_text and len(part) < 100:
                speaker = part
                break

        exists = conn.execute(
            "SELECT 1 FROM fed_communications WHERE comm_type = 'speech' AND date = ? AND title = ?",
            (filing_date, title),
        ).fetchone()
        if exists:
            continue

        time.sleep(0.5)
        page_soup = _fetch_page(full_url)
        if not page_soup:
            continue

        full_text = _extract_text(page_soup)
        word_count = len(full_text.split()) if full_text else 0

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fed_communications
                (comm_type, title, date, speaker, url, full_text, word_count, collected_at)
                VALUES ('speech', ?, ?, ?, ?, ?, ?, ?)""",
                (title, filing_date, speaker, full_url, full_text, word_count, collected_at),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass

    return stored


def collect_fed_communications(
    lookback_days: int = 730,
    db_path: str = DB_PATH,
) -> dict:
    """Collect all Fed communications since last collection or lookback.

    Returns: {"statements": int, "minutes": int, "beige_book": int, "speeches": int}
    """
    _init_table(db_path)

    now = datetime.now(ET)
    collected_at = now.isoformat()

    # Determine since_date
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM fed_communications").fetchone()
        if row and row[0]:
            since_date = row[0]
        else:
            since_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    result = {"statements": 0, "minutes": 0, "beige_book": 0, "speeches": 0}

    with sqlite3.connect(db_path) as conn:
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
