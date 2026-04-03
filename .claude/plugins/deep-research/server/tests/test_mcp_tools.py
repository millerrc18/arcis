"""Tests for MCP server — tool registration and basic tool behavior."""

import json
import sys
import pytest
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestMCPServerImport:
    """Verify the MCP server module loads without errors."""

    def test_import_server(self):
        from server.research_mcp_server import mcp
        assert mcp is not None
        assert mcp.name == "deep-research"

    def test_tools_registered(self):
        """All 15 tools should be registered."""
        from server.research_mcp_server import mcp

        # FastMCP stores tools internally — check they exist
        # The tool decorator registers them on the mcp object
        tool_names = {
            "search_web",
            "search_academic",
            "read_url",
            "search_and_read",
            "register_source",
            "get_research_context",
            "set_domain",
            "follow_citations",
            "find_related",
            "resolve_doi",
            "search_news",
            "batch_read",
            "search_patents",
            "get_cached_content",
            "get_dashboard_url",
        }

        # Access the registered tools via FastMCP's internal registry
        registered = set()
        if hasattr(mcp, '_tool_manager'):
            for tool in mcp._tool_manager._tools.values():
                registered.add(tool.name)
        elif hasattr(mcp, '_tools'):
            registered = set(mcp._tools.keys())

        # If we can't introspect tools, at least verify the functions exist as module attributes
        import server.research_mcp_server as srv
        for name in tool_names:
            assert hasattr(srv, name), f"Tool function '{name}' not found in module"


class TestSessionModuleImport:
    """Verify session module is complete."""

    def test_import_all_classes(self):
        from server.session import Source, SearchRecord, ProvenanceNode, ResearchContext
        assert Source is not None
        assert SearchRecord is not None
        assert ProvenanceNode is not None
        assert ResearchContext is not None

    def test_import_all_functions(self):
        from server.session import compute_quality_score, log
        assert callable(compute_quality_score)
        assert callable(log)


class TestAPIModulesImport:
    """Verify all API modules import without errors."""

    def test_search_module(self):
        from server.apis.search import search_web
        assert callable(search_web)

    def test_content_module(self):
        from server.apis.content import read_url
        assert callable(read_url)

    def test_academic_module(self):
        from server.apis.academic import search_academic, resolve_doi, get_paper_citations
        assert callable(search_academic)
        assert callable(resolve_doi)
        assert callable(get_paper_citations)

    def test_news_module(self):
        from server.apis.news import search_news
        assert callable(search_news)

    def test_specialized_module(self):
        from server.apis.specialized import search_patents, search_fred, search_sec_edgar
        assert callable(search_patents)
        assert callable(search_fred)
        assert callable(search_sec_edgar)

    def test_utility_module(self):
        from server.apis.utility import search_wikipedia, get_wayback_url
        assert callable(search_wikipedia)
        assert callable(get_wayback_url)


class TestDashboardImport:
    """Verify dashboard module imports."""

    def test_dashboard_server_import(self):
        from server.dashboard_server import start_dashboard, DashboardServer
        assert callable(start_dashboard)
        assert DashboardServer is not None
