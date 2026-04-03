"""Tests for session.py — quality scoring, dedup, provenance, cache, events."""

import math
import pytest
from server.session import (
    Source,
    SearchRecord,
    ProvenanceNode,
    ResearchContext,
    compute_quality_score,
    _compute_domain_tier,
    _compute_recency_score,
    _compute_citation_impact,
    _content_hash,
)


# ── Domain Tier Scoring ──────────────────────────────────────────────


class TestDomainTier:
    def test_authoritative_domains(self):
        assert _compute_domain_tier("https://www.nature.com/articles/123") == 1.0
        assert _compute_domain_tier("https://nist.gov/standards") == 1.0
        assert _compute_domain_tier("https://ieee.org/paper") == 1.0

    def test_expert_domains(self):
        assert _compute_domain_tier("https://arxiv.org/abs/2401.12345") == 0.8
        assert _compute_domain_tier("https://ssrn.com/abstract=123") == 0.8

    def test_professional_domains(self):
        assert _compute_domain_tier("https://reuters.com/article") == 0.6
        assert _compute_domain_tier("https://www.bbc.com/news") == 0.6

    def test_community_domains(self):
        assert _compute_domain_tier("https://stackoverflow.com/q/123") == 0.4
        assert _compute_domain_tier("https://en.wikipedia.org/wiki/Test") == 0.4

    def test_general_domains(self):
        assert _compute_domain_tier("https://reddit.com/r/test") == 0.2

    def test_tld_fallbacks(self):
        assert _compute_domain_tier("https://mit.edu/research") == 1.0
        assert _compute_domain_tier("https://whitehouse.gov") == 1.0
        assert _compute_domain_tier("https://example.org") == 0.6

    def test_unknown_domain(self):
        assert _compute_domain_tier("https://randomsite.com/page") == 0.3


# ── Citation Impact ───────────────────────────────────────────────────


class TestCitationImpact:
    def test_zero_citations(self):
        assert _compute_citation_impact(0) == 0.0

    def test_negative_citations(self):
        assert _compute_citation_impact(-5) == 0.0

    def test_single_citation(self):
        score = _compute_citation_impact(1)
        assert 0.0 < score < 0.2

    def test_moderate_citations(self):
        score = _compute_citation_impact(100)
        assert 0.6 < score < 0.8

    def test_high_citations(self):
        score = _compute_citation_impact(1000)
        assert score == 1.0

    def test_very_high_citations_capped(self):
        assert _compute_citation_impact(100000) == 1.0

    def test_monotonically_increasing(self):
        scores = [_compute_citation_impact(n) for n in [1, 10, 50, 100, 500, 1000]]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1], f"Score at {i} not less than {i+1}"


# ── Recency Score ─────────────────────────────────────────────────────


class TestRecencyScore:
    def test_unknown_date(self):
        assert _compute_recency_score("", "general") == 0.5

    def test_invalid_date(self):
        assert _compute_recency_score("not-a-date", "general") == 0.5

    def test_recent_date_high_score(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        score = _compute_recency_score(today, "general")
        assert score > 0.9

    def test_old_date_decayed(self):
        score = _compute_recency_score("2010-01-01", "software-ai")  # 1-year half-life
        assert score < 0.01  # ~15 years with 1-year half-life

    def test_year_only_format(self):
        score = _compute_recency_score("2024", "general")
        assert 0.0 < score <= 1.0

    def test_domain_half_life_affects_decay(self):
        # Same date, different domains
        fast = _compute_recency_score("2020-01-01", "software-ai")  # 1-year half-life
        slow = _compute_recency_score("2020-01-01", "aerospace-engineering")  # 5-year half-life
        assert fast < slow  # Fast-decay domain should have lower score


# ── Composite Quality Score ───────────────────────────────────────────


class TestCompositeQualityScore:
    def test_high_quality_academic(self):
        source = Source(
            url="https://nature.com/articles/123",
            title="Test Paper",
            source_type="academic",
            citation_count=200,
            quality_rating=5,
            date="2024-01-01",
        )
        score = compute_quality_score(source, "general")
        assert score > 0.7

    def test_low_quality_reddit(self):
        source = Source(
            url="https://reddit.com/r/test/post",
            title="Random Post",
            source_type="web",
            quality_rating=1,
        )
        score = compute_quality_score(source, "general")
        assert score < 0.3

    def test_no_metadata_gets_neutral(self):
        source = Source(
            url="https://unknown-site.xyz/page",
            title="Unknown",
            source_type="web",
        )
        score = compute_quality_score(source, "general")
        assert 0.1 < score < 0.6

    def test_score_in_valid_range(self):
        source = Source(url="https://example.com", title="T", source_type="web")
        score = compute_quality_score(source, "general")
        assert 0.0 <= score <= 1.0


# ── Content Hash ──────────────────────────────────────────────────────


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content(self):
        assert _content_hash("hello") != _content_hash("world")

    def test_length(self):
        assert len(_content_hash("test")) == 16


# ── Source Registration & Deduplication ────────────────────────────────


class TestSourceRegistration:
    def test_register_new_source(self):
        ctx = ResearchContext()
        result = ctx.register_source("https://example.com", "Test", "web")
        assert result["duplicate"] is False
        assert "quality_score" in result
        assert len(ctx.source_registry) == 1

    def test_url_dedup(self):
        ctx = ResearchContext()
        ctx.register_source("https://example.com/page", "Test", "web")
        result = ctx.register_source("https://example.com/page", "Test Again", "web")
        assert result["duplicate"] is True
        assert len(ctx.source_registry) == 1

    def test_url_normalization(self):
        ctx = ResearchContext()
        ctx.register_source("https://example.com/page/", "Test", "web")
        result = ctx.register_source("https://example.com/page", "Test Again", "web")
        assert result["duplicate"] is True

    def test_content_hash_dedup(self):
        ctx = ResearchContext()
        content = "This is some article content that is reasonably long."
        ctx.register_source("https://site-a.com", "A", "web", cached_content=content)
        result = ctx.register_source("https://site-b.com", "B", "web", cached_content=content)
        assert result["duplicate"] is True

    def test_different_content_not_deduped(self):
        ctx = ResearchContext()
        ctx.register_source("https://a.com", "A", "web", cached_content="content one")
        result = ctx.register_source("https://b.com", "B", "web", cached_content="content two")
        assert result["duplicate"] is False
        assert len(ctx.source_registry) == 2

    def test_quality_score_computed(self):
        ctx = ResearchContext()
        result = ctx.register_source(
            "https://nature.com/article",
            "Good Paper",
            "academic",
            quality_rating=5,
            citation_count=100,
        )
        assert result["quality_score"] > 0.5

    def test_quality_scores_dict_updated(self):
        ctx = ResearchContext()
        ctx.register_source("https://example.com", "T", "web")
        assert "https://example.com" in ctx.quality_scores

    def test_doi_field(self):
        ctx = ResearchContext()
        ctx.register_source("https://doi.org/10.1234", "T", "academic", doi="10.1234")
        assert ctx.source_registry[0].doi == "10.1234"


# ── Search Recording ──────────────────────────────────────────────────


class TestSearchRecording:
    def test_record_search(self):
        ctx = ResearchContext()
        ctx.record_search("test query", "tavily", 10, ["https://a.com"])
        assert len(ctx.search_history) == 1
        assert ctx.search_history[0].query == "test query"
        assert ctx.search_history[0].engine == "tavily"

    def test_api_usage_tracking(self):
        ctx = ResearchContext()
        ctx.record_search("q1", "tavily")
        ctx.record_search("q2", "tavily")
        ctx.record_search("q3", "exa")
        assert ctx.api_usage["tavily"] == 2
        assert ctx.api_usage["exa"] == 1


# ── Provenance Graph ─────────────────────────────────────────────────


class TestProvenanceGraph:
    def test_add_provenance_node(self):
        ctx = ResearchContext()
        node_id = ctx.add_provenance("search", agent_id="searcher-1")
        assert node_id == "prov_1"
        assert len(ctx.provenance_graph) == 1
        assert ctx.provenance_graph[0].event_type == "search"

    def test_sequential_node_ids(self):
        ctx = ResearchContext()
        id1 = ctx.add_provenance("search")
        id2 = ctx.add_provenance("read")
        id3 = ctx.add_provenance("follow_citation")
        assert id1 == "prov_1"
        assert id2 == "prov_2"
        assert id3 == "prov_3"

    def test_provenance_with_metadata(self):
        ctx = ResearchContext()
        ctx.add_provenance(
            "search",
            agent_id="searcher-1",
            inputs=["prov_0"],
            outputs=["src_1", "src_2"],
            metadata={"query": "test"},
        )
        node = ctx.provenance_graph[0]
        assert node.inputs == ["prov_0"]
        assert node.outputs == ["src_1", "src_2"]
        assert node.metadata["query"] == "test"

    def test_provenance_serialization(self):
        ctx = ResearchContext()
        ctx.add_provenance("search", agent_id="s1")
        d = ctx.provenance_graph[0].to_dict()
        assert "node_id" in d
        assert "event_type" in d
        assert "timestamp" in d


# ── Citation Graph ────────────────────────────────────────────────────


class TestCitationGraph:
    def test_update_citation_graph(self):
        ctx = ResearchContext()
        ctx.update_citation_graph("paper1", cited_by=["paper2", "paper3"])
        assert ctx.citation_graph["paper1"]["cited_by"] == ["paper2", "paper3"]

    def test_update_references(self):
        ctx = ResearchContext()
        ctx.update_citation_graph("paper1", references=["paper0"])
        assert ctx.citation_graph["paper1"]["references"] == ["paper0"]

    def test_accumulate_citations(self):
        ctx = ResearchContext()
        ctx.update_citation_graph("paper1", cited_by=["paper2"])
        ctx.update_citation_graph("paper1", cited_by=["paper3"])
        assert ctx.citation_graph["paper1"]["cited_by"] == ["paper2", "paper3"]


# ── Content Cache ─────────────────────────────────────────────────────


class TestContentCache:
    def test_cache_on_register(self):
        ctx = ResearchContext()
        ctx.register_source("https://a.com", "A", "web", cached_content="some content")
        assert ctx.get_cached_content("https://a.com") == "some content"

    def test_cache_miss(self):
        ctx = ResearchContext()
        assert ctx.get_cached_content("https://notcached.com") is None

    def test_cache_url_normalization(self):
        ctx = ResearchContext()
        ctx.register_source("https://a.com/page/", "A", "web", cached_content="content")
        assert ctx.get_cached_content("https://a.com/page") == "content"


# ── Event Emission ────────────────────────────────────────────────────


class TestEventEmission:
    def test_event_listener_called(self):
        ctx = ResearchContext()
        events = []
        ctx.add_event_listener(lambda e: events.append(e))
        ctx.register_source("https://a.com", "A", "web")
        assert len(events) == 1
        assert events[0]["type"] == "source_registered"

    def test_search_event(self):
        ctx = ResearchContext()
        events = []
        ctx.add_event_listener(lambda e: events.append(e))
        ctx.record_search("test", "tavily", 5)
        assert len(events) == 1
        assert events[0]["type"] == "search_executed"

    def test_phase_event(self):
        ctx = ResearchContext()
        events = []
        ctx.add_event_listener(lambda e: events.append(e))
        ctx.set_phase("GATHER")
        assert events[0]["type"] == "phase_transition"
        assert events[0]["data"]["phase"] == "GATHER"

    def test_finding_event(self):
        ctx = ResearchContext()
        events = []
        ctx.add_event_listener(lambda e: events.append(e))
        ctx.add_finding({"claim": "test", "confidence": 4})
        assert events[0]["type"] == "finding_added"

    def test_remove_listener(self):
        ctx = ResearchContext()
        events = []
        listener = lambda e: events.append(e)
        ctx.add_event_listener(listener)
        ctx.remove_event_listener(listener)
        ctx.register_source("https://a.com", "A", "web")
        assert len(events) == 0

    def test_broken_listener_doesnt_crash(self):
        ctx = ResearchContext()
        ctx.add_event_listener(lambda e: 1 / 0)  # Will raise ZeroDivisionError
        # Should not raise
        ctx.register_source("https://a.com", "A", "web")


# ── Context Retrieval ─────────────────────────────────────────────────


class TestGetContext:
    def test_all_section(self):
        ctx = ResearchContext()
        ctx.domain = "trading"
        ctx.depth = "deep"
        ctx.query = "test query"
        ctx.register_source("https://a.com", "A", "web")
        ctx.record_search("q", "tavily")
        ctx.add_provenance("search")
        ctx.add_finding({"claim": "x"})

        result = ctx.get_context("all")
        assert "sources" in result
        assert "searches" in result
        assert "citation_graph" in result
        assert "provenance" in result
        assert "findings" in result
        assert result["domain"] == "trading"
        assert result["depth"] == "deep"
        assert result["query"] == "test query"

    def test_sources_section(self):
        ctx = ResearchContext()
        ctx.register_source("https://a.com", "A", "web")
        result = ctx.get_context("sources")
        assert result["source_count"] == 1
        assert "searches" not in result

    def test_searches_section(self):
        ctx = ResearchContext()
        ctx.record_search("q", "tavily")
        result = ctx.get_context("searches")
        assert result["search_count"] == 1
        assert "sources" not in result

    def test_provenance_section(self):
        ctx = ResearchContext()
        ctx.add_provenance("search")
        result = ctx.get_context("provenance")
        assert len(result["provenance"]) == 1

    def test_registered_urls(self):
        ctx = ResearchContext()
        ctx.register_source("https://a.com", "A", "web")
        ctx.register_source("https://b.com", "B", "web")
        urls = ctx.get_registered_urls()
        assert set(urls) == {"https://a.com", "https://b.com"}


# ── Domain Setting ────────────────────────────────────────────────────


class TestDomainSetting:
    def test_set_domain(self):
        ctx = ResearchContext()
        result = ctx.set_domain("trading", ["ssrn.com", "quantconnect.com"])
        assert result["domain"] == "trading"
        assert ctx.preferred_sources == ["ssrn.com", "quantconnect.com"]

    def test_default_domain(self):
        ctx = ResearchContext()
        assert ctx.domain == "general"


# ── Source & SearchRecord Serialization ────────────────────────────────


class TestSerialization:
    def test_source_to_dict(self):
        s = Source(url="https://a.com", title="T", source_type="web", quality_score=0.75)
        d = s.to_dict()
        assert d["url"] == "https://a.com"
        assert d["quality_score"] == 0.75
        assert "cached_content" not in d  # Should not expose cached content

    def test_source_with_doi(self):
        s = Source(url="https://a.com", title="T", source_type="academic", doi="10.1234")
        d = s.to_dict()
        assert d["doi"] == "10.1234"

    def test_search_record_to_dict(self):
        sr = SearchRecord(query="q", engine="tavily", timestamp="2024-01-01T00:00:00Z")
        d = sr.to_dict()
        assert d["query"] == "q"
        assert d["engine"] == "tavily"
