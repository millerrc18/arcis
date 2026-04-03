"""Research session state management.

Maintains the ResearchContext for a single research session.
State is naturally session-scoped because stdio transport = one server process per session.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Source:
    """A discovered research source."""

    url: str
    title: str
    source_type: str  # web, academic, report, spec, news
    relevance_note: str = ""
    quality_rating: int = 3  # 1-5 agent assessment
    author: str = ""
    date: str = ""
    citation_count: int = 0
    content_hash: str = ""
    retrieved_at: str = ""
    found_by_agent: str = ""
    api_used: str = ""
    cached_content: str = ""
    quality_score: float = 0.0  # computed composite 0.0-1.0
    doi: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "url": self.url,
            "title": self.title,
            "source_type": self.source_type,
            "relevance_note": self.relevance_note,
            "quality_rating": self.quality_rating,
            "author": self.author,
            "date": self.date,
            "citation_count": self.citation_count,
            "retrieved_at": self.retrieved_at,
            "found_by_agent": self.found_by_agent,
            "api_used": self.api_used,
            "quality_score": self.quality_score,
        }
        if self.doi:
            d["doi"] = self.doi
        return d


@dataclass
class SearchRecord:
    """A record of a search executed during the session."""

    query: str
    engine: str
    timestamp: str
    result_count: int = 0
    top_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "engine": self.engine,
            "timestamp": self.timestamp,
            "result_count": self.result_count,
            "top_urls": self.top_urls,
        }


@dataclass
class ProvenanceNode:
    """A node in the research provenance DAG."""

    event_type: str  # decompose, search, read, follow_citation, lateral_discover, etc.
    timestamp: str
    agent_id: str = ""
    inputs: list[str] = field(default_factory=list)  # node IDs
    outputs: list[str] = field(default_factory=list)  # source IDs or finding IDs
    metadata: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metadata": self.metadata,
        }


# Domain-specific recency half-lives in years
RECENCY_HALF_LIVES: dict[str, float] = {
    "cybersecurity-compliance": 1.0,
    "software-ai": 1.0,
    "trading": 2.0,
    "market-intelligence": 2.0,
    "aerospace-engineering": 5.0,
    "manufacturing-quality": 5.0,
    "defense-regulatory": 2.0,
    "supply-chain": 3.0,
    "project-management": 3.0,
    "academic-scientific": 7.0,
    "medical-health": 3.0,
    "general": 3.0,
}

# Domain tier scoring for source quality
DOMAIN_TIERS: dict[str, float] = {
    # Authoritative (1.0)
    "nature.com": 1.0,
    "science.org": 1.0,
    "thelancet.com": 1.0,
    "nejm.org": 1.0,
    "gov": 1.0,
    "edu": 1.0,
    "ieee.org": 1.0,
    "acm.org": 1.0,
    "nist.gov": 1.0,
    # Expert (0.8)
    "arxiv.org": 0.8,
    "ssrn.com": 0.8,
    "springer.com": 0.8,
    "wiley.com": 0.8,
    "elsevier.com": 0.8,
    "sciencedirect.com": 0.8,
    "semanticscholar.org": 0.8,
    # Professional (0.6)
    "reuters.com": 0.6,
    "bloomberg.com": 0.6,
    "nytimes.com": 0.6,
    "wsj.com": 0.6,
    "bbc.com": 0.6,
    # Community (0.4)
    "stackoverflow.com": 0.4,
    "wikipedia.org": 0.4,
    "medium.com": 0.3,
    # General (0.2)
    "reddit.com": 0.2,
}


def _compute_domain_tier(url: str) -> float:
    """Score a URL's domain credibility."""
    url_lower = url.lower()
    for domain, score in DOMAIN_TIERS.items():
        if domain in url_lower:
            return score
    if ".gov" in url_lower or ".edu" in url_lower:
        return 1.0
    if ".org" in url_lower:
        return 0.6
    return 0.3


def _compute_recency_score(date_str: str, domain: str) -> float:
    """Exponential decay based on domain-specific half-life."""
    if not date_str:
        return 0.5
    try:
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                pub_date = datetime.strptime(date_str[:len(fmt.replace("%", "").replace("-", "") + date_str[:4])], fmt)
                break
            except (ValueError, IndexError):
                continue
        else:
            year = int(date_str[:4])
            pub_date = datetime(year, 6, 15)

        now = datetime.now()
        age_years = (now - pub_date).days / 365.25
        half_life = RECENCY_HALF_LIVES.get(domain, 3.0)
        return math.exp(-0.693 * age_years / half_life)
    except (ValueError, TypeError):
        return 0.5


def _compute_citation_impact(citation_count: int) -> float:
    """Normalized citation impact using log scale."""
    if citation_count <= 0:
        return 0.0
    return min(1.0, math.log10(citation_count + 1) / 3.0)


def compute_quality_score(source: Source, domain: str) -> float:
    """Compute composite quality score (0.0-1.0) for a source."""
    factors: list[tuple[float, float]] = []

    factors.append((0.30, _compute_domain_tier(source.url)))

    if source.citation_count > 0:
        factors.append((0.25, _compute_citation_impact(source.citation_count)))

    if source.date:
        factors.append((0.20, _compute_recency_score(source.date, domain)))

    if source.quality_rating:
        normalized_rating = (source.quality_rating - 1) / 4.0
        factors.append((0.25, normalized_rating))

    total_weight = sum(w for w, _ in factors)
    if total_weight == 0:
        return 0.5
    return sum(w * s for w, s in factors) / total_weight


def _content_hash(content: str) -> str:
    """SHA-256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class ResearchContext:
    """Session state for a research run.

    Maintains source registry, search history, quality scores,
    provenance graph, content cache, and domain configuration.
    """

    def __init__(self) -> None:
        self.domain: str = "general"
        self.depth: str = "moderate"
        self.query: str = ""
        self.current_phase: str = ""
        self.start_time: str = ""
        self.preferred_sources: list[str] = []
        self.source_registry: list[Source] = []
        self.search_history: list[SearchRecord] = []
        self.citation_graph: dict[str, dict[str, list[str]]] = {}
        self.provenance_graph: list[ProvenanceNode] = []
        self.api_usage: dict[str, int] = {}
        self.quality_scores: dict[str, float] = {}
        self.content_cache: dict[str, str] = {}  # url → cached content
        self.findings: list[dict[str, Any]] = []  # accumulated findings
        self._url_set: set[str] = set()
        self._content_hashes: set[str] = set()
        self._node_counter: int = 0
        # SSE event listeners
        self._event_listeners: list[Callable] = []

    def add_event_listener(self, listener: Callable) -> None:
        """Register a callback for SSE event emission."""
        self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable) -> None:
        """Remove an SSE event listener."""
        self._event_listeners = [l for l in self._event_listeners if l is not listener]

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an event to all registered listeners."""
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception:
                pass

    def set_phase(self, phase: str) -> None:
        """Update current phase and emit event."""
        self.current_phase = phase
        self._emit_event("phase_transition", {"phase": phase})

    def set_domain(self, domain: str, preferred_sources: list[str] | None = None) -> dict[str, Any]:
        """Set the active domain preset."""
        self.domain = domain
        if preferred_sources:
            self.preferred_sources = preferred_sources
        return {"domain": self.domain, "preferred_sources": self.preferred_sources}

    def register_source(
        self,
        url: str,
        title: str,
        source_type: str = "web",
        relevance_note: str = "",
        quality_rating: int = 3,
        author: str = "",
        date: str = "",
        citation_count: int = 0,
        found_by_agent: str = "",
        api_used: str = "",
        cached_content: str = "",
        doi: str = "",
    ) -> dict[str, Any]:
        """Register a discovered source. Deduplicates by URL and content hash."""
        normalized_url = url.rstrip("/")

        if normalized_url in self._url_set:
            return {"duplicate": True, "url": normalized_url, "message": "Source already registered (URL match)"}

        c_hash = ""
        if cached_content:
            c_hash = _content_hash(cached_content)
            if c_hash in self._content_hashes:
                return {"duplicate": True, "url": normalized_url, "message": "Source already registered (content match)"}

        source = Source(
            url=normalized_url,
            title=title,
            source_type=source_type,
            relevance_note=relevance_note,
            quality_rating=quality_rating,
            author=author,
            date=date,
            citation_count=citation_count,
            content_hash=c_hash,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            found_by_agent=found_by_agent,
            api_used=api_used,
            cached_content=cached_content,
            doi=doi,
        )

        source.quality_score = compute_quality_score(source, self.domain)

        self.source_registry.append(source)
        self._url_set.add(normalized_url)
        if c_hash:
            self._content_hashes.add(c_hash)
        self.quality_scores[normalized_url] = source.quality_score

        # Cache content for later retrieval
        if cached_content:
            self.content_cache[normalized_url] = cached_content

        # Emit SSE event
        self._emit_event("source_registered", {
            "url": normalized_url,
            "title": title,
            "source_type": source_type,
            "quality_score": round(source.quality_score, 3),
            "citation_count": citation_count,
        })

        return {
            "duplicate": False,
            "url": normalized_url,
            "quality_score": round(source.quality_score, 3),
            "source_index": len(self.source_registry) - 1,
        }

    def record_search(
        self, query: str, engine: str, result_count: int = 0, top_urls: list[str] | None = None
    ) -> None:
        """Record a search execution for history tracking."""
        self.search_history.append(
            SearchRecord(
                query=query,
                engine=engine,
                timestamp=datetime.now(timezone.utc).isoformat(),
                result_count=result_count,
                top_urls=top_urls or [],
            )
        )
        self.api_usage[engine] = self.api_usage.get(engine, 0) + 1

        self._emit_event("search_executed", {
            "query": query,
            "engine": engine,
            "result_count": result_count,
        })

    def add_provenance(
        self,
        event_type: str,
        agent_id: str = "",
        inputs: list[str] | None = None,
        outputs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a node to the provenance DAG. Returns the node ID."""
        self._node_counter += 1
        node_id = f"prov_{self._node_counter}"

        node = ProvenanceNode(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            inputs=inputs or [],
            outputs=outputs or [],
            metadata=metadata or {},
            node_id=node_id,
        )
        self.provenance_graph.append(node)
        return node_id

    def update_citation_graph(self, paper_id: str, cited_by: list[str] | None = None, references: list[str] | None = None) -> None:
        """Update the citation graph with new relationships."""
        if paper_id not in self.citation_graph:
            self.citation_graph[paper_id] = {"cited_by": [], "references": []}
        if cited_by:
            self.citation_graph[paper_id]["cited_by"].extend(cited_by)
        if references:
            self.citation_graph[paper_id]["references"].extend(references)

    def get_cached_content(self, url: str) -> str | None:
        """Retrieve cached content for a URL."""
        return self.content_cache.get(url.rstrip("/"))

    def add_finding(self, finding: dict[str, Any]) -> None:
        """Add a research finding."""
        self.findings.append(finding)
        self._emit_event("finding_added", finding)

    def get_context(self, section: str = "all") -> dict[str, Any]:
        """Return research context for agents."""
        result: dict[str, Any] = {}

        if section in ("sources", "all"):
            result["sources"] = [s.to_dict() for s in self.source_registry]
            result["source_count"] = len(self.source_registry)
            result["unique_domains"] = len(
                {s.url.split("/")[2] if len(s.url.split("/")) > 2 else s.url for s in self.source_registry}
            )

        if section in ("searches", "all"):
            result["searches"] = [s.to_dict() for s in self.search_history]
            result["search_count"] = len(self.search_history)

        if section in ("citations", "all"):
            result["citation_graph"] = self.citation_graph

        if section in ("provenance", "all"):
            result["provenance"] = [n.to_dict() for n in self.provenance_graph]

        if section in ("findings", "all"):
            result["findings"] = self.findings

        if section in ("all",):
            result["domain"] = self.domain
            result["depth"] = self.depth
            result["query"] = self.query
            result["current_phase"] = self.current_phase
            result["start_time"] = self.start_time
            result["api_usage"] = self.api_usage
            result["quality_scores"] = {
                url: round(score, 3) for url, score in self.quality_scores.items()
            }

        return result

    def get_registered_urls(self) -> list[str]:
        """Return all registered URLs for exclude_urls filtering."""
        return list(self._url_set)


def log(msg: str) -> None:
    """Log to stderr (required for stdio transport — stdout is MCP protocol)."""
    print(f"[deep-research] {msg}", file=sys.stderr, flush=True)
