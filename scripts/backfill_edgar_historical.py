"""Historical EDGAR backfill for Lazy Prices validation.

Backfills edgar_filings with full_text and sections_json for S&P 100
10-K/10-Q filings from a date range. Two-phase: discover metadata,
then fetch full text.

Rate limit: 5 req/sec (conservative under SEC's 10/sec).
Expected runtime: ~60-80 min for S&P 100 2019-2023.

Run:
    python scripts/backfill_edgar_historical.py --start 2019-01-01 --end 2023-12-31
    python scripts/backfill_edgar_historical.py --start 2019-01-01 --end 2023-12-31 --ticker AAPL --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from src.config import DB_PATH
from src.data_collection.edgar_collector import (
    _get_cik,
    _load_cik_lookup,
    _normalize_accession,
    _parse_sections,
    _lookup_primary_document_via_index,
    _index_json_cache,
    MAX_TEXT_BYTES,
)
from src.universe.sp100 import get_sp100_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edgar_backfill")

SEC_HEADERS = {"User-Agent": "Halcyon Lab backfill halcyonlabai@gmail.com"}
RATE_LIMIT = 0.2  # 5 req/sec
FORM_TYPES = ["10-K", "10-K/A", "10-Q", "10-Q/A"]


def _sec_get(url: str, timeout: int = 15) -> requests.Response | None:
    """GET with rate limiting and Retry-After support. Returns None on failure after retries."""
    for attempt in range(4):  # initial + 3 retries
        time.sleep(RATE_LIMIT)
        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429, 503):
                retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.warning(
                    "[BACKFILL] HTTP %s on %s — retrying in %ds",
                    resp.status_code, url, retry_after,
                )
                time.sleep(retry_after)
                continue
            logger.warning("[BACKFILL] HTTP %s on %s", resp.status_code, url)
            return None
        except Exception as e:
            logger.warning("[BACKFILL] Request failed %s: %s", url, e)
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
    return None


def _extract_filings_from_page(
    page: dict,
    form_types: list[str],
    start_date: str,
    end_date: str,
    doc_cache: dict[str, str],
) -> list[dict]:
    """Extract matching filings from a submissions page (recent or paginated)."""
    forms = page.get("form", [])
    dates = page.get("filingDate", [])
    accessions = page.get("accessionNumber", [])
    descriptions = page.get("primaryDocDescription", [])
    primary_docs = page.get("primaryDocument", [])

    filings = []
    for i, form in enumerate(forms):
        if form not in form_types:
            continue
        filing_date = dates[i] if i < len(dates) else ""
        if not (start_date <= filing_date <= end_date):
            continue

        accession = _normalize_accession(accessions[i]) if i < len(accessions) else ""
        if not accession:
            continue

        # Cache primaryDocument from submissions response
        if i < len(primary_docs) and primary_docs[i]:
            doc_cache[accession] = primary_docs[i]

        filings.append({
            "form_type": form,
            "filing_date": filing_date,
            "accession_number": accession,
            "description": descriptions[i] if i < len(descriptions) else "",
        })

    return filings


def discover_filings_for_ticker(
    cik: str,
    ticker: str,
    form_types: list[str],
    start_date: str,
    end_date: str,
) -> tuple[list[dict], dict[str, str]]:
    """Discover all filings for a ticker in date range, including paginated history.

    Returns (filings_list, primaryDocument_cache).
    """
    doc_cache: dict[str, str] = {}

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = _sec_get(url)
    if not resp:
        logger.warning("[BACKFILL] Cannot fetch submissions for %s (CIK %s)", ticker, cik)
        return [], doc_cache

    data = resp.json()

    # Extract from recent filings
    recent = data.get("filings", {}).get("recent", {})
    filings = _extract_filings_from_page(recent, form_types, start_date, end_date, doc_cache)

    # Follow pagination for historical filings
    for file_ref in data.get("filings", {}).get("files", []):
        page_url = f"https://data.sec.gov/submissions/{file_ref['name']}"
        page_resp = _sec_get(page_url)
        if not page_resp:
            continue
        page_data = page_resp.json()
        filings.extend(
            _extract_filings_from_page(page_data, form_types, start_date, end_date, doc_cache)
        )

    logger.info(
        "[BACKFILL] %s: discovered %d filings, cached %d primaryDocs",
        ticker, len(filings), len(doc_cache),
    )
    return filings, doc_cache


def phase1_discover(
    tickers: list[str],
    start_date: str,
    end_date: str,
    db_path: str,
    dry_run: bool = False,
) -> dict[str, str]:
    """Phase 1: Discover filing metadata and insert into DB. Returns merged doc_cache."""
    _load_cik_lookup()
    merged_doc_cache: dict[str, str] = {}
    total_discovered = 0
    total_inserted = 0

    conn = sqlite3.connect(db_path)

    for i, ticker in enumerate(tickers, 1):
        cik = _get_cik(ticker)
        if not cik:
            logger.warning("[BACKFILL] No CIK for %s — skipping", ticker)
            continue

        filings, doc_cache = discover_filings_for_ticker(
            cik, ticker, FORM_TYPES, start_date, end_date,
        )
        merged_doc_cache.update(doc_cache)
        total_discovered += len(filings)

        if dry_run:
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        changes_before = conn.total_changes
        for filing in filings:
            accession = filing["accession_number"]
            cik_int = str(int(cik))
            acc_clean = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO edgar_filings
                    (ticker, cik, form_type, filing_date, accession_number,
                     filing_url, description, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ticker, cik, filing["form_type"], filing["filing_date"],
                        accession, filing_url, filing["description"], now_iso,
                    ),
                )
            except sqlite3.IntegrityError:
                pass
        inserted = conn.total_changes - changes_before

        # Commit after each ticker
        conn.commit()
        total_inserted += inserted
        logger.info(
            "[BACKFILL] Phase 1 progress: %d/%d tickers | %s: %d filings, %d new",
            i, len(tickers), ticker, len(filings), inserted,
        )

    conn.close()
    logger.info(
        "[BACKFILL] Phase 1 complete: discovered=%d, inserted=%d",
        total_discovered, total_inserted,
    )
    return merged_doc_cache


def _resolve_document(
    cik: str,
    accession: str,
    form_type: str,
    doc_cache: dict[str, str],
) -> tuple[str | None, str]:
    """Resolve the primary document filename. Returns (url, resolution_path)."""
    acc_clean = accession.replace("-", "")
    cik_int = str(int(cik))
    archives_base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}"

    # Fast path: cached from Phase 1 submissions data
    if accession in doc_cache:
        filename = doc_cache[accession]
        return f"{archives_base}/{filename}", "cache"

    # Last resort: index.json
    result = _lookup_primary_document_via_index(cik, accession, form_type)
    if result:
        filename, _ = result
        return f"{archives_base}/{filename}", "index.json"

    return None, "failed"


def _fetch_and_store(
    conn: sqlite3.Connection,
    row: dict,
    doc_cache: dict[str, str],
    stats: dict,
) -> None:
    """Fetch full text for a single filing, parse sections, store in DB."""
    cik = row["cik"]
    accession = row["accession_number"]
    form_type = row["form_type"]

    doc_url, path = _resolve_document(cik, accession, form_type, doc_cache)
    if not doc_url:
        logger.debug("[BACKFILL] Could not resolve document for %s: %s", accession, path)
        stats["fail"] += 1
        stats["fail_reasons"][f"resolve_{path}"] = stats["fail_reasons"].get(f"resolve_{path}", 0) + 1
        return

    resp = _sec_get(doc_url, timeout=30)
    if not resp:
        stats["fail"] += 1
        stats["fail_reasons"]["http_error"] = stats["fail_reasons"].get("http_error", 0) + 1
        return

    content = resp.text
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        logger.debug("[BACKFILL] Filing too large, skipping: %s", accession)
        stats["fail"] += 1
        stats["fail_reasons"]["too_large"] = stats["fail_reasons"].get("too_large", 0) + 1
        return

    # Strip HTML tags and decode entities (&#8217; -> ', &#8220; -> ", etc.)
    import html
    clean = re.sub(r"<[^>]+>", " ", content)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    if not clean or len(clean) < 100:
        stats["fail"] += 1
        stats["fail_reasons"]["empty_after_strip"] = stats["fail_reasons"].get("empty_after_strip", 0) + 1
        return

    # Parse sections
    sections = _parse_sections(clean, form_type)
    word_count = len(clean.split())

    conn.execute(
        """UPDATE edgar_filings SET
            full_text = ?, sections_json = ?, word_count = ?
        WHERE accession_number = ?""",
        (clean, json.dumps(sections) if sections else None, word_count, accession),
    )
    stats["success"] += 1
    stats["resolution_paths"][path] = stats["resolution_paths"].get(path, 0) + 1


def phase2_fetch(
    start_date: str,
    end_date: str,
    db_path: str,
    doc_cache: dict[str, str],
    limit: int | None = None,
) -> dict:
    """Phase 2: Fetch full text for filings missing sections_json."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    q = """SELECT cik, accession_number, form_type, ticker, filing_date
           FROM edgar_filings
           WHERE filing_date BETWEEN ? AND ?
           AND sections_json IS NULL
           ORDER BY filing_date"""
    params: list = [start_date, end_date]
    if limit:
        q += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(q, params).fetchall()
    total = len(rows)
    logger.info("[BACKFILL] Phase 2 target: %d filings to fetch", total)

    stats = {
        "success": 0,
        "fail": 0,
        "skip": 0,
        "total": total,
        "resolution_paths": {},
        "fail_reasons": {},
    }

    for i, row in enumerate(rows, 1):
        _fetch_and_store(conn, dict(row), doc_cache, stats)

        if i % 100 == 0:
            conn.commit()
            logger.info(
                "[BACKFILL] Phase 2 progress: %d/%d (success=%d, fail=%d)",
                i, total, stats["success"], stats["fail"],
            )

    conn.commit()
    conn.close()

    coverage = stats["success"] / total * 100 if total else 0
    stats["coverage_pct"] = round(coverage, 1)
    logger.info(
        "[BACKFILL] Phase 2 complete: success=%d, fail=%d, coverage=%.1f%%",
        stats["success"], stats["fail"], coverage,
    )

    if coverage < 90 and total > 50:
        logger.error(
            "[BACKFILL] COVERAGE BELOW 90%% (%.1f%%) — investigate before full run!",
            coverage,
        )

    return stats


def write_audit_report(
    start_date: str,
    end_date: str,
    phase2_stats: dict,
    db_path: str,
    tickers: list[str],
) -> str:
    """Write end-of-run audit report to docs/audits/."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "audits", f"edgar-backfill-{today}.md",
    )

    conn = sqlite3.connect(db_path)

    # Coverage by year
    year_stats = {}
    for year in range(int(start_date[:4]), int(end_date[:4]) + 1):
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN sections_json IS NOT NULL THEN 1 ELSE 0 END) as populated
            FROM edgar_filings
            WHERE filing_date BETWEEN ? AND ?""",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchone()
        total, populated = row[0], row[1] or 0
        year_stats[year] = {"total": total, "populated": populated,
                           "pct": round(populated / total * 100, 1) if total else 0}

    # Coverage by ticker (bottom 20)
    ticker_stats = []
    for ticker in tickers:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN sections_json IS NOT NULL THEN 1 ELSE 0 END) as populated
            FROM edgar_filings
            WHERE ticker = ? AND filing_date BETWEEN ? AND ?""",
            (ticker, start_date, end_date),
        ).fetchone()
        total, populated = row[0], row[1] or 0
        pct = round(populated / total * 100, 1) if total else 0
        ticker_stats.append({"ticker": ticker, "total": total, "populated": populated, "pct": pct})

    ticker_stats.sort(key=lambda x: x["pct"])

    # Form type counts
    form_counts = conn.execute(
        """SELECT form_type, COUNT(*) FROM edgar_filings
           WHERE filing_date BETWEEN ? AND ?
           GROUP BY form_type ORDER BY COUNT(*) DESC""",
        (start_date, end_date),
    ).fetchall()

    conn.close()

    # Build report
    lines = [
        f"# EDGAR Historical Backfill Audit — {today}\n",
        f"**Date range:** {start_date} to {end_date}",
        f"**Tickers:** {len(tickers)} (S&P 100)",
        f"**Total attempted:** {phase2_stats['total']}",
        f"**Success:** {phase2_stats['success']}",
        f"**Fail:** {phase2_stats['fail']}",
        f"**Coverage:** {phase2_stats.get('coverage_pct', 0)}%\n",
        "## Coverage by Year\n",
        "| Year | Total | Populated | Coverage |",
        "|------|-------|-----------|----------|",
    ]
    for year, ys in sorted(year_stats.items()):
        lines.append(f"| {year} | {ys['total']} | {ys['populated']} | {ys['pct']}% |")

    lines.extend([
        "\n## Bottom 20 Tickers by Coverage\n",
        "| Ticker | Total | Populated | Coverage |",
        "|--------|-------|-----------|----------|",
    ])
    for ts in ticker_stats[:20]:
        lines.append(f"| {ts['ticker']} | {ts['total']} | {ts['populated']} | {ts['pct']}% |")

    lines.extend([
        "\n## Form Types\n",
        "| Form | Count |",
        "|------|-------|",
    ])
    for form, count in form_counts:
        lines.append(f"| {form} | {count} |")

    lines.extend([
        "\n## Resolution Paths\n",
        "| Path | Count |",
        "|------|-------|",
    ])
    for path, count in sorted(phase2_stats.get("resolution_paths", {}).items(),
                              key=lambda x: -x[1]):
        lines.append(f"| {path} | {count} |")

    lines.extend([
        "\n## Top Failure Reasons\n",
        "| Reason | Count |",
        "|--------|-------|",
    ])
    for reason, count in sorted(phase2_stats.get("fail_reasons", {}).items(),
                                key=lambda x: -x[1])[:20]:
        lines.append(f"| {reason} | {count} |")

    report = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    logger.info("[BACKFILL] Audit report written to %s", report_path)
    return report_path


def main() -> int:
    p = argparse.ArgumentParser(description="Historical EDGAR backfill for Lazy Prices validation")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--db-path", default=DB_PATH)
    p.add_argument("--ticker", default=None, help="Single ticker for smoke testing")
    p.add_argument("--limit", type=int, default=None, help="Cap on filings to fetch in Phase 2")
    p.add_argument("--dry-run", action="store_true", help="Discover only, don't fetch text")
    args = p.parse_args()

    start_date = args.start
    end_date = args.end

    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = get_sp100_universe()

    logger.info(
        "[BACKFILL] Starting: %d tickers, %s to %s, dry_run=%s",
        len(tickers), start_date, end_date, args.dry_run,
    )

    # Phase 1: Discover
    doc_cache = phase1_discover(tickers, start_date, end_date, args.db_path, args.dry_run)

    if args.dry_run:
        logger.info("[BACKFILL] Dry run complete. Exiting.")
        return 0

    # Phase 2: Fetch full text
    stats = phase2_fetch(start_date, end_date, args.db_path, doc_cache, args.limit)

    # Audit report
    report_path = write_audit_report(start_date, end_date, stats, args.db_path, tickers)
    print(f"\nAudit report: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
