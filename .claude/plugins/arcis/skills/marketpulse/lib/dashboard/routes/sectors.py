"""Sectors route -- sector analysis for index constituents."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sectors"])


@router.get("/sectors", response_class=HTMLResponse)
async def sectors_page(request: Request) -> HTMLResponse:
    """Render the sectors analysis page."""
    indices = []
    try:
        from ...indices import IndexManager
        idx_mgr = IndexManager()
        indices = [(i.short_name, i.name) for i in idx_mgr.list_indices()]
    except Exception:
        logger.warning("Failed to load indices", exc_info=True)

    today = date.today()
    return templates.TemplateResponse(request, "sectors.html", {
        "active_page": "sectors",
        "indices": indices,
        "default_from": (today - timedelta(days=30)).isoformat(),
        "default_to": today.isoformat(),
    })


@router.post("/api/sector-data", response_class=HTMLResponse)
async def sector_data_partial(
    request: Request,
    index_name: str = Form(""),
    from_date: str = Form(""),
    to_date: str = Form(""),
) -> HTMLResponse:
    """HTMX partial: runs sector analysis and returns 3 chart panels."""
    if not index_name or not from_date or not to_date:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400">Select an index and date range.</p>'
        )

    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager
        from ...client import PolygonClient
        from ...indices import IndexManager
        from ...analytics import sector_rotation, sector_heatmap, relative_strength
        from ...analytics.types import load_sector_map
        from ..services.chart_service import sector_rotation_chart_data, sector_heatmap_chart_data

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = MagicMock(spec=PolygonClient)
        cm = CacheManager(config, client, sf)

        idx_mgr = IndexManager(config)
        index = idx_mgr.get_index(index_name)
        tickers = index.tickers
        sector_map = load_sector_map(index_name)

        start_dt = date.fromisoformat(from_date)
        end_dt = date.fromisoformat(to_date)

        df = await cm.get_bars_df(
            tickers=tickers, timespan="1day",
            from_date=start_dt, to_date=end_dt, max_rows=500_000,
        )

        if df.empty:
            return HTMLResponse(
                '<p class="text-sm text-yellow-600 dark:text-yellow-400">'
                f'No cached data for {index_name}. Pull data first.</p>'
            )

        rotation = sector_rotation(df, sector_map)
        heatmap = sector_heatmap(df, sector_map)
        strength = relative_strength(df, sector_map)

        rotation_chart = sector_rotation_chart_data(rotation)
        heatmap_chart = sector_heatmap_chart_data(heatmap)

        # Relative strength as line chart series
        rs_series = [
            {"name": t.ticker, "x": ["RS"], "y": [t.rs_ratio]}
            for t in strength.tickers[:20]
        ]

        return templates.TemplateResponse(request, "partials/chart_result.html", {
            "chart_id": "sector-rotation-chart",
            "chart_data": rotation_chart,
            "chart_type": "mini_bar",
            "chart_opts": {},
        })

    except Exception as exc:
        logger.warning("Sector analysis error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 dark:text-red-400">Error: {exc}</p>'
        )
