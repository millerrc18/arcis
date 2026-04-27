"""Price Charts route -- interactive candlestick/line charting."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["charts"])


async def _get_cached_tickers() -> list[str]:
    """Return sorted list of tickers with cached data."""
    from ...db import get_config, get_session_factory, init_db, Base
    from ...models import Coverage

    from sqlalchemy import select

    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await init_db(Base.metadata)

    async with sf() as session:
        result = await session.execute(select(Coverage.ticker).distinct())
        return sorted([row[0] for row in result.fetchall()])


@router.get("/charts", response_class=HTMLResponse)
async def charts_page(request: Request) -> HTMLResponse:
    """Render the price charts page with controls."""
    cached_tickers = []
    try:
        cached_tickers = await _get_cached_tickers()
    except Exception:
        logger.warning("Failed to load cached tickers", exc_info=True)

    today = date.today()
    default_from = (today - timedelta(days=30)).isoformat()
    default_to = today.isoformat()

    return templates.TemplateResponse(request, "charts.html", {
        "active_page": "charts",
        "cached_tickers": cached_tickers,
        "default_from": default_from,
        "default_to": default_to,
    })


@router.get("/api/chart-data", response_class=HTMLResponse)
async def chart_data_partial(
    request: Request,
    ticker: str = Query(""),
    from_date: str = Query(""),
    to_date: str = Query(""),
    timespan: str = Query("1day"),
    chart_type: str = Query("candlestick"),
) -> HTMLResponse:
    """HTMX partial: returns chart div with Plotly render script."""
    if not ticker or not from_date or not to_date:
        return HTMLResponse('<p class="text-sm text-gray-500 dark:text-slate-400">Select a ticker and date range.</p>')

    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager
        from ...client import PolygonClient
        from ..services.chart_service import candlestick_chart_data

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = MagicMock(spec=PolygonClient)
        cm = CacheManager(config, client, sf)

        start_dt = date.fromisoformat(from_date)
        end_dt = date.fromisoformat(to_date)

        df = await cm.get_bars_df(
            tickers=[ticker],
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
            max_rows=50_000,
        )

        if df.empty:
            return HTMLResponse(
                '<p class="text-sm text-yellow-600 dark:text-yellow-400">'
                f'No data for {ticker} in this range. Pull data first.</p>'
            )

        chart = candlestick_chart_data(df, ticker)

        return templates.TemplateResponse(request, "partials/chart_result.html", {
            "chart_id": "price-chart",
            "chart_data": chart,
            "chart_type": chart_type,
            "chart_opts": {"title": f"{ticker} - {timespan}"},
        })

    except Exception as exc:
        logger.warning("Chart data error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 dark:text-red-400">Error: {exc}</p>'
        )
