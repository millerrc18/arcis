"""Academic search API wrappers.

All APIs in this module are free and require no API keys.
Fallback order: Semantic Scholar -> OpenAlex -> arXiv -> PubMed
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from ..session import log

# Timeouts for academic APIs
ACADEMIC_TIMEOUT = 30.0


async def _search_semantic_scholar(
    query: str,
    max_results: int = 10,
    year_range: tuple[int, int] | None = None,
    fields_of_study: list[str] | None = None,
    min_citations: int = 0,
) -> dict[str, Any] | None:
    """Search via Semantic Scholar API (free, no key required)."""
    params: dict[str, Any] = {
        "query": query,
        "limit": max_results,
        "fields": "title,url,abstract,year,citationCount,authors,venue,externalIds,tldr",
    }

    if year_range:
        params["year"] = f"{year_range[0]}-{year_range[1]}"

    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("data", []):
                citation_count = r.get("citationCount", 0) or 0
                if citation_count < min_citations:
                    continue

                # Construct URL from paperId or DOI
                external_ids = r.get("externalIds") or {}
                doi = external_ids.get("DOI")
                paper_id = r.get("paperId", "")
                url = f"https://doi.org/{doi}" if doi else f"https://www.semanticscholar.org/paper/{paper_id}"

                # Prefer TLDR over abstract for snippet
                tldr = r.get("tldr")
                abstract = r.get("abstract") or ""
                snippet = tldr.get("text", "") if tldr else abstract

                authors = [a.get("name", "") for a in (r.get("authors") or [])]

                result = {
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": snippet[:500] if snippet else "",
                    "date": str(r.get("year", "")),
                    "relevance_score": 0.0,
                    "source_type": "academic",
                    "citation_count": citation_count,
                    "authors": authors,
                    "venue": r.get("venue", ""),
                    "doi": doi or "",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": data.get("total", len(results)),
                "api_used": "semantic_scholar",
            }
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            log(f"Semantic Scholar rate limited: {e}")
        else:
            log(f"Semantic Scholar error {e.response.status_code}: {e}")
        return None
    except Exception as e:
        log(f"Semantic Scholar error: {e}")
        return None


async def _search_openalex(
    query: str,
    max_results: int = 10,
    year_range: tuple[int, int] | None = None,
    fields_of_study: list[str] | None = None,
    min_citations: int = 0,
) -> dict[str, Any] | None:
    """Search via OpenAlex API (free, no key required)."""
    params: dict[str, Any] = {
        "search": query,
        "per_page": max_results,
        "sort": "relevance_score:desc",
        "mailto": "deep-research@example.com",
    }

    # Build filter string
    filters = []
    if year_range:
        filters.append(f"from_publication_date:{year_range[0]}-01-01")
        filters.append(f"to_publication_date:{year_range[1]}-12-31")
    if min_citations > 0:
        filters.append(f"cited_by_count:>{min_citations - 1}")
    if filters:
        params["filter"] = ",".join(filters)

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            resp = await client.get(
                "https://api.openalex.org/works",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("results", []):
                # Extract DOI or OpenAlex URL
                doi = r.get("doi") or ""
                url = doi if doi else r.get("id", "")

                # Abstract: OpenAlex returns inverted index, reconstruct if needed
                abstract_obj = r.get("abstract_inverted_index")
                abstract = ""
                if abstract_obj and isinstance(abstract_obj, dict):
                    # Reconstruct abstract from inverted index
                    word_positions: list[tuple[int, str]] = []
                    for word, positions in abstract_obj.items():
                        for pos in positions:
                            word_positions.append((pos, word))
                    word_positions.sort(key=lambda x: x[0])
                    abstract = " ".join(w for _, w in word_positions)

                # Extract authors
                authors = []
                for authorship in r.get("authorships", []):
                    author_info = authorship.get("author", {})
                    name = author_info.get("display_name", "")
                    if name:
                        authors.append(name)

                # Extract venue
                primary_loc = r.get("primary_location") or {}
                source = primary_loc.get("source") or {}
                venue = source.get("display_name", "")

                citation_count = r.get("cited_by_count", 0) or 0

                result = {
                    "title": r.get("title", "") or r.get("display_name", ""),
                    "url": url,
                    "snippet": abstract[:500] if abstract else "",
                    "date": r.get("publication_date", ""),
                    "relevance_score": r.get("relevance_score", 0.0) or 0.0,
                    "source_type": "academic",
                    "citation_count": citation_count,
                    "authors": authors,
                    "venue": venue,
                    "doi": doi.replace("https://doi.org/", "") if doi.startswith("https://doi.org/") else doi,
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": data.get("meta", {}).get("count", len(results)),
                "api_used": "openalex",
            }
    except Exception as e:
        log(f"OpenAlex error: {e}")
        return None


async def _search_arxiv(
    query: str,
    max_results: int = 10,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    """Search via arXiv API (free, no key required)."""
    params: dict[str, Any] = {
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
    }

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            resp = await client.get(
                "http://export.arxiv.org/api/query",
                params=params,
            )
            resp.raise_for_status()
            xml_text = resp.text

        # Parse Atom XML
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_text)

        results = []
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""

            summary_el = entry.find("atom:summary", ns)
            summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""

            published_el = entry.find("atom:published", ns)
            published = published_el.text[:10] if published_el is not None and published_el.text else ""

            # Filter by year range if specified
            if year_range and published:
                try:
                    pub_year = int(published[:4])
                    if pub_year < year_range[0] or pub_year > year_range[1]:
                        continue
                except ValueError:
                    pass

            # Get the abstract page link (rel=alternate)
            url = ""
            for link in entry.findall("atom:link", ns):
                if link.get("rel") == "alternate":
                    url = link.get("href", "")
                    break
            if not url:
                id_el = entry.find("atom:id", ns)
                url = id_el.text if id_el is not None and id_el.text else ""

            # Extract authors
            authors = []
            for author in entry.findall("atom:author", ns):
                name_el = author.find("atom:name", ns)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text)

            result = {
                "title": title,
                "url": url,
                "snippet": summary[:500] if summary else "",
                "date": published,
                "relevance_score": 0.0,
                "source_type": "academic",
                "citation_count": 0,
                "authors": authors,
                "venue": "arXiv",
                "doi": "",
            }
            results.append(result)

        return {
            "results": results[:max_results],
            "total_count": len(results),
            "api_used": "arxiv",
        }
    except Exception as e:
        log(f"arXiv error: {e}")
        return None


async def _search_pubmed(
    query: str,
    max_results: int = 10,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    """Search via PubMed E-Utilities API (free, no key required)."""
    # Step 1: search for IDs
    esearch_params: dict[str, Any] = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
    }
    if year_range:
        esearch_params["mindate"] = f"{year_range[0]}/01/01"
        esearch_params["maxdate"] = f"{year_range[1]}/12/31"
        esearch_params["datetype"] = "pdat"

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            # Get IDs
            resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params=esearch_params,
            )
            resp.raise_for_status()
            search_data = resp.json()

            id_list = search_data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                return {
                    "results": [],
                    "total_count": 0,
                    "api_used": "pubmed",
                }

            total_count = int(search_data.get("esearchresult", {}).get("count", 0))

            # Step 2: get summaries
            resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(id_list),
                    "retmode": "json",
                },
            )
            resp.raise_for_status()
            summary_data = resp.json()

            results = []
            result_entries = summary_data.get("result", {})
            for uid in id_list:
                article = result_entries.get(uid, {})
                if not article or uid == "uids":
                    continue

                # Extract authors
                authors = []
                for author in article.get("authors", []):
                    name = author.get("name", "")
                    if name:
                        authors.append(name)

                result = {
                    "title": article.get("title", ""),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "snippet": article.get("source", "") + " - " + article.get("title", ""),
                    "date": article.get("pubdate", ""),
                    "relevance_score": 0.0,
                    "source_type": "academic",
                    "citation_count": 0,
                    "authors": authors,
                    "venue": article.get("source", ""),
                    "doi": "",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": total_count,
                "api_used": "pubmed",
            }
    except Exception as e:
        log(f"PubMed error: {e}")
        return None


async def search_academic(
    query: str,
    max_results: int = 10,
    year_range: tuple[int, int] | None = None,
    fields_of_study: list[str] | None = None,
    min_citations: int = 0,
    detail_level: str = "summaries",
) -> dict[str, Any]:
    """Execute academic search with fallback chain: Semantic Scholar -> OpenAlex -> arXiv -> PubMed.

    Returns results dict or error dict.
    """
    for search_fn, name, supports_fields in [
        (_search_semantic_scholar, "Semantic Scholar", True),
        (_search_openalex, "OpenAlex", True),
        (_search_arxiv, "arXiv", False),
        (_search_pubmed, "PubMed", False),
    ]:
        log(f"Trying {name} for academic query: {query[:80]}...")
        if supports_fields:
            result = await search_fn(
                query=query,
                max_results=max_results,
                year_range=year_range,
                fields_of_study=fields_of_study,
                min_citations=min_citations,
            )
        else:
            result = await search_fn(
                query=query,
                max_results=max_results,
                year_range=year_range,
            )
        if result and result.get("results"):
            log(f"  -> {name} returned {len(result['results'])} results")
            return result
        elif result is None:
            log(f"  -> {name} skipped (error)")
        else:
            log(f"  -> {name} returned 0 results")

    return {
        "results": [],
        "total_count": 0,
        "api_used": "none",
        "error": "No academic search API returned results. Tried: Semantic Scholar, OpenAlex, arXiv, PubMed.",
    }


async def get_paper_citations(
    paper_id: str,
    direction: str = "both",
    max_results: int = 20,
) -> dict[str, Any]:
    """Get citations and/or references for a paper via Semantic Scholar.

    Args:
        paper_id: DOI, arXiv ID, or Semantic Scholar paper ID.
        direction: "cited_by", "references", or "both".
        max_results: Max results per direction.

    Returns:
        Dict with cited_by and/or references lists.
    """
    fields = "title,url,abstract,year,citationCount,authors,venue,externalIds"
    result: dict[str, Any] = {"paper_id": paper_id}

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            # Get papers that cite this one
            if direction in ("both", "cited_by"):
                try:
                    resp = await client.get(
                        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations",
                        params={"fields": fields, "limit": max_results},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    cited_by = []
                    for item in data.get("data", []):
                        citing = item.get("citingPaper", {})
                        if citing.get("title"):
                            cited_by.append({
                                "title": citing.get("title", ""),
                                "year": citing.get("year"),
                                "citation_count": citing.get("citationCount", 0),
                                "authors": [a.get("name", "") for a in (citing.get("authors") or [])],
                                "venue": citing.get("venue", ""),
                                "url": citing.get("url", ""),
                            })
                    result["cited_by"] = cited_by
                except Exception as e:
                    log(f"Semantic Scholar citations error: {e}")
                    result["cited_by"] = []

            # Get papers this one references
            if direction in ("both", "references"):
                try:
                    resp = await client.get(
                        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references",
                        params={"fields": fields, "limit": max_results},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    references = []
                    for item in data.get("data", []):
                        cited = item.get("citedPaper", {})
                        if cited.get("title"):
                            references.append({
                                "title": cited.get("title", ""),
                                "year": cited.get("year"),
                                "citation_count": cited.get("citationCount", 0),
                                "authors": [a.get("name", "") for a in (cited.get("authors") or [])],
                                "venue": cited.get("venue", ""),
                                "url": cited.get("url", ""),
                            })
                    result["references"] = references
                except Exception as e:
                    log(f"Semantic Scholar references error: {e}")
                    result["references"] = []

    except Exception as e:
        log(f"Semantic Scholar citation lookup error: {e}")
        if "cited_by" not in result:
            result["cited_by"] = []
        if "references" not in result:
            result["references"] = []

    return result


async def resolve_doi(doi: str) -> dict[str, Any]:
    """Resolve a DOI via CrossRef (metadata) and Unpaywall (open access URL).

    Returns:
        Dict with metadata, open_access_url, and api_used.
    """
    result: dict[str, Any] = {
        "metadata": {},
        "open_access_url": None,
        "api_used": "crossref+unpaywall",
    }

    try:
        async with httpx.AsyncClient(timeout=ACADEMIC_TIMEOUT) as client:
            # CrossRef metadata
            try:
                resp = await client.get(
                    f"https://api.crossref.org/works/{quote(doi, safe='')}",
                    headers={"User-Agent": "deep-research/1.0 (mailto:deep-research@example.com)"},
                )
                resp.raise_for_status()
                data = resp.json()
                message = data.get("message", {})

                # Extract structured metadata
                authors = []
                for author in message.get("author", []):
                    given = author.get("given", "")
                    family = author.get("family", "")
                    authors.append(f"{given} {family}".strip())

                result["metadata"] = {
                    "title": " ".join(message.get("title", [])),
                    "authors": authors,
                    "journal": " ".join(message.get("container-title", [])),
                    "publisher": message.get("publisher", ""),
                    "published_date": "-".join(
                        str(p) for p in message.get("published-print", message.get("published-online", {})).get("date-parts", [[]])[0]
                    ),
                    "doi": message.get("DOI", doi),
                    "type": message.get("type", ""),
                    "url": message.get("URL", f"https://doi.org/{doi}"),
                    "citation_count": message.get("is-referenced-by-count", 0),
                    "abstract": message.get("abstract", ""),
                }
            except Exception as e:
                log(f"CrossRef error for DOI {doi}: {e}")
                result["metadata"] = {"doi": doi, "error": str(e)}

            # Unpaywall open access
            try:
                resp = await client.get(
                    f"https://api.unpaywall.org/v2/{quote(doi, safe='')}",
                    params={"email": "deep-research@example.com"},
                )
                resp.raise_for_status()
                data = resp.json()
                best_oa = data.get("best_oa_location")
                if best_oa:
                    result["open_access_url"] = best_oa.get("url_for_pdf") or best_oa.get("url")
            except Exception as e:
                log(f"Unpaywall error for DOI {doi}: {e}")

    except Exception as e:
        log(f"DOI resolution error for {doi}: {e}")

    return result
