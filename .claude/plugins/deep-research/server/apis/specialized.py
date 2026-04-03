"""Specialized domain API wrappers.

FRED, SEC EDGAR, USPTO are free. Wolfram requires WOLFRAM_APP_ID.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from ..session import log

# Timeouts for specialized APIs
SPECIALIZED_TIMEOUT = 30.0


async def search_fred(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search FRED (Federal Reserve Economic Data) for economic time series.

    Uses FRED_API_KEY env var if set, otherwise falls back to DEMO_KEY.
    """
    api_key = os.environ.get("FRED_API_KEY", "DEMO_KEY")

    params: dict[str, Any] = {
        "search_text": query,
        "api_key": api_key,
        "file_type": "json",
        "limit": max_results,
    }

    try:
        async with httpx.AsyncClient(timeout=SPECIALIZED_TIMEOUT) as client:
            resp = await client.get(
                "https://api.stlouisfed.org/fred/series/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for series in data.get("seriess", []):
                series_id = series.get("id", "")
                result = {
                    "title": series.get("title", ""),
                    "url": f"https://fred.stlouisfed.org/series/{series_id}",
                    "snippet": series.get("notes", "")[:500] if series.get("notes") else "",
                    "date": series.get("last_updated", ""),
                    "relevance_score": series.get("popularity", 0) / 100.0,
                    "source_type": "economic_data",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": data.get("count", len(results)),
                "api_used": "fred",
            }
    except Exception as e:
        log(f"FRED error: {e}")
        return {
            "results": [],
            "total_count": 0,
            "api_used": "fred",
            "error": f"FRED search failed: {e}",
        }


async def search_sec_edgar(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search SEC EDGAR full-text search for company filings.

    Free, no API key required. SEC requires a User-Agent header for identification.
    """
    params: dict[str, Any] = {
        "q": query,
        "dateRange": "custom",
        "startdt": "2020-01-01",
        "forms": "10-K,10-Q,8-K",
        "from": 0,
        "size": max_results,
    }

    try:
        async with httpx.AsyncClient(timeout=SPECIALIZED_TIMEOUT) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
                headers={
                    "User-Agent": "deep-research deep-research@example.com",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for hit in data.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                form_type = source.get("forms", "")
                company = source.get("display_names", [""])[0] if source.get("display_names") else ""
                file_num = source.get("file_num", "")
                filing_date = source.get("file_date", "")

                # Construct filing URL
                accession = source.get("accession_no", "").replace("-", "")
                cik = source.get("entity_id", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}" if cik and accession else ""

                result = {
                    "title": f"{form_type} - {company}".strip(" -"),
                    "url": filing_url,
                    "snippet": source.get("file_description", "") or f"Filing {file_num} dated {filing_date}",
                    "date": filing_date,
                    "relevance_score": hit.get("_score", 0.0),
                    "source_type": "sec_filing",
                }
                results.append(result)

            total = data.get("hits", {}).get("total", {})
            total_count = total.get("value", len(results)) if isinstance(total, dict) else total

            return {
                "results": results[:max_results],
                "total_count": total_count,
                "api_used": "sec_edgar",
            }
    except Exception as e:
        log(f"SEC EDGAR error: {e}")
        return {
            "results": [],
            "total_count": 0,
            "api_used": "sec_edgar",
            "error": f"SEC EDGAR search failed: {e}",
        }


async def search_patents(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search USPTO patents via PatentsView API.

    Free, no API key required.
    """
    payload = {
        "q": {"_text_any": {"patent_abstract": query}},
        "f": [
            "patent_number",
            "patent_title",
            "patent_abstract",
            "patent_date",
            "inventor_first_name",
            "inventor_last_name",
        ],
        "o": {"per_page": max_results},
    }

    try:
        async with httpx.AsyncClient(timeout=SPECIALIZED_TIMEOUT) as client:
            resp = await client.post(
                "https://api.patentsview.org/patents/query",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for patent in data.get("patents", []):
                patent_number = patent.get("patent_number", "")
                patent_title = patent.get("patent_title", "")
                patent_abstract = patent.get("patent_abstract", "")
                patent_date = patent.get("patent_date", "")

                # Build inventors list
                inventors = []
                for inv in patent.get("inventors", []):
                    first = inv.get("inventor_first_name", "")
                    last = inv.get("inventor_last_name", "")
                    inventors.append(f"{first} {last}".strip())

                result = {
                    "title": patent_title,
                    "url": f"https://patents.google.com/patent/US{patent_number}",
                    "snippet": patent_abstract[:500] if patent_abstract else "",
                    "date": patent_date,
                    "relevance_score": 0.0,
                    "source_type": "patent",
                    "authors": inventors,
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": data.get("total_patent_count", len(results)),
                "api_used": "patentsview",
            }
    except Exception as e:
        log(f"PatentsView error: {e}")
        return {
            "results": [],
            "total_count": 0,
            "api_used": "patentsview",
            "error": f"Patent search failed: {e}",
        }


async def query_wolfram(query: str) -> dict[str, Any]:
    """Query Wolfram Alpha for computational/factual answers.

    Requires WOLFRAM_APP_ID env var.
    """
    app_id = os.environ.get("WOLFRAM_APP_ID")
    if not app_id:
        return {
            "answer": None,
            "pods": [],
            "api_used": "wolfram",
            "error": "WOLFRAM_APP_ID not configured.",
        }

    params: dict[str, Any] = {
        "input": query,
        "appid": app_id,
        "output": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=SPECIALIZED_TIMEOUT) as client:
            resp = await client.get(
                "https://api.wolframalpha.com/v2/query",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            query_result = data.get("queryresult", {})
            if not query_result.get("success"):
                return {
                    "answer": None,
                    "pods": [],
                    "api_used": "wolfram",
                    "error": "Wolfram Alpha could not interpret the query.",
                }

            pods = []
            answer = None
            for pod in query_result.get("pods", []):
                pod_title = pod.get("title", "")
                subpods = pod.get("subpods", [])
                pod_texts = []
                for subpod in subpods:
                    text = subpod.get("plaintext", "")
                    if text:
                        pod_texts.append(text)

                pod_entry = {
                    "title": pod_title,
                    "text": "\n".join(pod_texts),
                }
                pods.append(pod_entry)

                # Capture the primary result as the answer
                if pod.get("primary") and pod_texts:
                    answer = "\n".join(pod_texts)

            # Fallback: use the "Result" pod if no primary
            if answer is None:
                for pod in pods:
                    if pod["title"] in ("Result", "Results", "Solution", "Value"):
                        answer = pod["text"]
                        break

            return {
                "answer": answer,
                "pods": pods,
                "api_used": "wolfram",
            }
    except Exception as e:
        log(f"Wolfram Alpha error: {e}")
        return {
            "answer": None,
            "pods": [],
            "api_used": "wolfram",
            "error": f"Wolfram Alpha query failed: {e}",
        }
