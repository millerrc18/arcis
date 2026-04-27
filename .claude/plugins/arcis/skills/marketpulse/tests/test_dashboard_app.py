"""Tests for the MarketPulse dashboard FastAPI app."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_MP_ROOT = Path(__file__).resolve().parent.parent
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a TestClient with mocked database initialization.

    Patches:
    - ``lib.db.get_config``        -- prevents real filesystem access in db module
    - ``lib.db.get_session_factory`` -- prevents real engine creation
    - ``lib.db.init_db``           -- prevents real SQLite creation
    - ``lib.cache.CacheManager``   -- intercepts overview route's lazy import
    """
    mock_config = MagicMock()
    mock_config.data_dir = Path("/tmp/mp-test")
    mock_config.ensure_dirs = MagicMock()

    with patch("lib.db.get_config", return_value=mock_config), \
         patch("lib.db.get_session_factory", return_value=MagicMock()), \
         patch("lib.db.init_db", new_callable=AsyncMock), \
         patch("lib.cache.CacheManager") as MockCM:

        cm_instance = MagicMock()
        cm_instance.get_cache_status = AsyncMock(return_value={
            "total_tickers": 0,
            "total_bars": 0,
            "total_partitions": 0,
        })
        MockCM.return_value = cm_instance

        from lib.dashboard.app import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture
def client_with_data():
    """TestClient fixture where CacheManager reports non-zero cached bars.

    This causes the overview route to enter the analytics branch, but
    since total_bars > 0 and the session returns no tickers, the
    analytics block exits gracefully (no movers/sector data rendered).
    """
    mock_config = MagicMock()
    mock_config.data_dir = Path("/tmp/mp-test")
    mock_config.ensure_dirs = MagicMock()

    # Async sessionmaker mock: sf() returns an async context manager
    # that yields an async session
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_sf = MagicMock()
    mock_sf.return_value = mock_ctx

    with patch("lib.db.get_config", return_value=mock_config), \
         patch("lib.db.get_session_factory", return_value=mock_sf), \
         patch("lib.db.init_db", new_callable=AsyncMock), \
         patch("lib.cache.CacheManager") as MockCM:

        cm_instance = MagicMock()
        cm_instance.get_cache_status = AsyncMock(return_value={
            "total_tickers": 5,
            "total_bars": 1000,
            "total_partitions": 10,
        })
        MockCM.return_value = cm_instance

        from lib.dashboard.app import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# TestAppStartup
# ---------------------------------------------------------------------------

class TestAppStartup:
    """Verify the FastAPI app mounts static files correctly."""

    def test_static_files_mount(self, client: TestClient) -> None:
        """GET /static/css/custom.css returns 200 and contains x-cloak style."""
        response = client.get("/static/css/custom.css")
        assert response.status_code == 200, (
            f"Expected 200 for custom.css, got {response.status_code}"
        )
        assert "x-cloak" in response.text, (
            "custom.css should contain '[x-cloak]' rule"
        )

    def test_static_js_mount(self, client: TestClient) -> None:
        """GET /static/js/charts.js returns 200 and contains createMiniBar."""
        response = client.get("/static/js/charts.js")
        assert response.status_code == 200, (
            f"Expected 200 for charts.js, got {response.status_code}"
        )
        assert "createMiniBar" in response.text, (
            "charts.js should define the createMiniBar function"
        )


# ---------------------------------------------------------------------------
# TestOverviewRoute
# ---------------------------------------------------------------------------

class TestOverviewRoute:
    """Tests for the GET / overview page."""

    def test_overview_returns_200(self, client: TestClient) -> None:
        """Overview page returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_overview_contains_marketpulse(self, client: TestClient) -> None:
        """Response HTML contains the 'MarketPulse' brand name."""
        response = client.get("/")
        assert response.status_code == 200
        assert "MarketPulse" in response.text

    def test_overview_contains_stat_cards(self, client: TestClient) -> None:
        """Overview page renders 'Tickers Cached' and 'Total Bars' stat card labels."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Tickers Cached" in response.text, (
            "Stat card label 'Tickers Cached' missing from overview HTML"
        )
        assert "Total Bars" in response.text, (
            "Stat card label 'Total Bars' missing from overview HTML"
        )

    def test_overview_has_sidebar_nav(self, client: TestClient) -> None:
        """Overview page renders all expected sidebar navigation links."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        for href in ('href="/"', 'href="/charts"', 'href="/analytics"',
                     'href="/sectors"', 'href="/events"', 'href="/data"'):
            assert href in html, f"Nav link {href!r} missing from sidebar"

    def test_overview_has_theme_toggle(self, client: TestClient) -> None:
        """Overview page includes Alpine.js dark-mode toggle logic."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "darkMode" in html, "Alpine.js 'darkMode' variable missing from page"
        assert "localStorage" in html, "'localStorage' reference missing from page"

    def test_overview_empty_state(self, client: TestClient) -> None:
        """With 0 cached bars, overview shows the empty-state message and /data link."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "No cached data yet" in html, (
            "Empty-state message 'No cached data yet.' missing when total_bars=0"
        )
        assert 'href="/data"' in html, (
            "Link to /data missing from empty-state section"
        )


# ---------------------------------------------------------------------------
# TestChartsRoute
# ---------------------------------------------------------------------------

class TestChartsRoute:
    """Tests for the GET /charts page."""

    def test_charts_returns_200(self, client: TestClient) -> None:
        """Charts page returns HTTP 200."""
        response = client.get("/charts")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_charts_contains_title(self, client: TestClient) -> None:
        """Charts page contains the page title."""
        response = client.get("/charts")
        assert response.status_code == 200
        assert "Price Charts" in response.text

    def test_charts_has_chart_container(self, client: TestClient) -> None:
        """Charts page has a chart container div."""
        response = client.get("/charts")
        assert response.status_code == 200
        assert "chart-container" in response.text or "plotly" in response.text.lower()

    def test_charts_has_controls(self, client: TestClient) -> None:
        """Charts page has ticker selector and timespan controls."""
        response = client.get("/charts")
        assert response.status_code == 200
        html = response.text
        assert "timespan" in html.lower() or "Timespan" in html


# ---------------------------------------------------------------------------
# TestAnalyticsRoute
# ---------------------------------------------------------------------------

class TestAnalyticsRoute:
    """Tests for the GET /analytics page."""

    def test_analytics_returns_200(self, client: TestClient) -> None:
        """Analytics page returns HTTP 200."""
        response = client.get("/analytics")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_analytics_contains_title(self, client: TestClient) -> None:
        """Analytics page contains the page title."""
        response = client.get("/analytics")
        assert response.status_code == 200
        assert "Analytics" in response.text

    def test_analytics_has_analysis_type_selector(self, client: TestClient) -> None:
        """Analytics page has an analysis type selector dropdown."""
        response = client.get("/analytics")
        assert response.status_code == 200
        html = response.text
        assert "analysis_type" in html or "analysis-type" in html

    def test_analytics_has_result_area(self, client: TestClient) -> None:
        """Analytics page has a result swap target."""
        response = client.get("/analytics")
        assert response.status_code == 200
        assert "analysis-result" in response.text or "result" in response.text.lower()


# ---------------------------------------------------------------------------
# TestSectorsRoute
# ---------------------------------------------------------------------------

class TestSectorsRoute:
    """Tests for the GET /sectors page."""

    def test_sectors_returns_200(self, client: TestClient) -> None:
        """Sectors page returns HTTP 200."""
        response = client.get("/sectors")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_sectors_contains_title(self, client: TestClient) -> None:
        """Sectors page contains the page title."""
        response = client.get("/sectors")
        assert response.status_code == 200
        assert "Sector" in response.text

    def test_sectors_has_index_selector(self, client: TestClient) -> None:
        """Sectors page has an index selector dropdown."""
        response = client.get("/sectors")
        assert response.status_code == 200
        html = response.text
        assert "index" in html.lower()


# ---------------------------------------------------------------------------
# TestEventsRoute
# ---------------------------------------------------------------------------

class TestEventsRoute:
    """Tests for the GET /events page."""

    def test_events_returns_200(self, client: TestClient) -> None:
        """Events page returns HTTP 200."""
        response = client.get("/events")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_events_contains_title(self, client: TestClient) -> None:
        """Events page contains the page title."""
        response = client.get("/events")
        assert response.status_code == 200
        assert "Event" in response.text

    def test_events_has_detection_form(self, client: TestClient) -> None:
        """Events page has a detection form with event type selector."""
        response = client.get("/events")
        assert response.status_code == 200
        html = response.text
        assert "event_type" in html or "event-type" in html

    def test_events_has_impact_section(self, client: TestClient) -> None:
        """Events page has an impact analysis section."""
        response = client.get("/events")
        assert response.status_code == 200
        assert "Impact" in response.text or "impact" in response.text


# ---------------------------------------------------------------------------
# TestDataRoute
# ---------------------------------------------------------------------------

class TestDataRoute:
    """Tests for the GET /data page."""

    def test_data_returns_200(self, client: TestClient) -> None:
        """Data page returns HTTP 200."""
        response = client.get("/data")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text[:300]}"
        )

    def test_data_contains_title(self, client: TestClient) -> None:
        """Data page contains the page title."""
        response = client.get("/data")
        assert response.status_code == 200
        assert "Data" in response.text

    def test_data_has_pull_form(self, client: TestClient) -> None:
        """Data page has a pull form with ticker input."""
        response = client.get("/data")
        assert response.status_code == 200
        html = response.text
        assert "pull" in html.lower() or "Pull" in html

    def test_data_has_cache_status(self, client: TestClient) -> None:
        """Data page has a cache status section."""
        response = client.get("/data")
        assert response.status_code == 200
        html = response.text
        assert "Cache" in html or "cache" in html

    def test_data_has_export_buttons(self, client: TestClient) -> None:
        """Data page has export buttons for Excel, CSV, and Parquet."""
        response = client.get("/data")
        assert response.status_code == 200
        html = response.text
        assert "Export" in html or "export" in html
