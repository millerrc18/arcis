"""Analytics route -- interactive analysis workbench."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analytics"])

ANALYSIS_TYPES = [
    ("daily_summary", "Daily Summary"),
    ("volatility", "Volatility (Vol Surface)"),
    ("correlation", "Correlation (Pairwise)"),
    ("intraday", "Intraday Patterns"),
    ("day_of_week", "Day-of-Week Effects"),
    ("monthly", "Monthly Seasonality"),
]


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request) -> HTMLResponse:
    """Render the analytics workbench page."""
    cached_tickers = []
    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...models import Coverage
        from sqlalchemy import select

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        async with sf() as session:
            result = await session.execute(select(Coverage.ticker).distinct())
            cached_tickers = sorted([row[0] for row in result.fetchall()])
    except Exception:
        logger.warning("Failed to load cached tickers", exc_info=True)

    today = date.today()
    return templates.TemplateResponse(request, "analytics.html", {
        "active_page": "analytics",
        "analysis_types": ANALYSIS_TYPES,
        "cached_tickers": cached_tickers,
        "default_from": (today - timedelta(days=30)).isoformat(),
        "default_to": today.isoformat(),
    })


@router.get("/api/analysis-form", response_class=HTMLResponse)
async def analysis_form_partial(
    request: Request,
    analysis_type: str = Query("daily_summary"),
) -> HTMLResponse:
    """HTMX partial: returns form fields specific to the selected analysis type."""
    single_ticker = analysis_type in ("intraday", "day_of_week", "monthly")
    needs_multi = analysis_type in ("correlation",)
    return templates.TemplateResponse(request, "partials/analysis_form.html", {
        "analysis_type": analysis_type,
        "single_ticker": single_ticker,
        "needs_multi": needs_multi,
    })


@router.post("/api/run-analysis", response_class=HTMLResponse)
async def run_analysis(
    request: Request,
    analysis_type: str = Form("daily_summary"),
    ticker: str = Form(""),
    from_date: str = Form(""),
    to_date: str = Form(""),
    timespan: str = Form("1day"),
) -> HTMLResponse:
    """HTMX partial: runs the selected analysis and returns chart + table."""
    if not ticker or not from_date or not to_date:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400">Please fill in all fields.</p>'
        )

    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager
        from ...client import PolygonClient
        from ..services.chart_service import (
            volatility_chart_data,
            correlation_heatmap_data,
            pattern_chart_data,
        )

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = MagicMock(spec=PolygonClient)
        cm = CacheManager(config, client, sf)

        tickers = [t.strip().upper() for t in ticker.split(",") if t.strip()]
        start_dt = date.fromisoformat(from_date)
        end_dt = date.fromisoformat(to_date)

        df = await cm.get_bars_df(
            tickers=tickers, timespan=timespan,
            from_date=start_dt, to_date=end_dt, max_rows=100_000,
        )

        if df.empty:
            return HTMLResponse(
                '<p class="text-sm text-yellow-600 dark:text-yellow-400">No data found.</p>'
            )

        chart_data = None
        chart_type = None
        table_rows = []
        table_headers = []

        if analysis_type == "daily_summary":
            from ...analytics import daily_summary
            result = daily_summary(df)
            d = result.to_dict()
            table_headers = ["ticker", "date", "open", "close", "daily_return", "volume"]
            table_rows = d.get("summaries", [])

        elif analysis_type == "volatility":
            from ...analytics import vol_surface
            result = vol_surface(df)
            chart_data = volatility_chart_data(result)
            chart_type = "line"
            d = result.to_dict()
            table_headers = ["ticker", "window_days", "annualized_vol"]
            table_rows = d.get("points", [])

        elif analysis_type == "correlation":
            from ...analytics import pairwise_correlation
            result = pairwise_correlation(df)
            chart_data = correlation_heatmap_data(result)
            chart_type = "heatmap"
            d = result.to_dict()
            table_headers = ["ticker_a", "ticker_b", "correlation"]
            table_rows = d.get("pairs", [])

        elif analysis_type in ("intraday", "day_of_week", "monthly"):
            single_ticker = tickers[0]
            if analysis_type == "intraday":
                from ...analytics import intraday_patterns
                result = intraday_patterns(df, ticker=single_ticker)
            elif analysis_type == "day_of_week":
                from ...analytics import day_of_week_effects
                result = day_of_week_effects(df, ticker=single_ticker)
            else:
                from ...analytics import monthly_seasonality
                result = monthly_seasonality(df, ticker=single_ticker)

            chart_data = pattern_chart_data(result, analysis_type)
            chart_type = "grouped_bar"
            d = result.to_dict()
            list_key = next((k for k, v in d.items() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
            if list_key:
                table_rows = d[list_key]
                table_headers = list(table_rows[0].keys()) if table_rows else []

        return templates.TemplateResponse(request, "partials/analysis_result.html", {
            "chart_data": chart_data,
            "chart_type": chart_type,
            "table_headers": table_headers,
            "table_rows": table_rows,
            "analysis_type": analysis_type,
        })

    except Exception as exc:
        logger.warning("Analysis error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 dark:text-red-400">Error: {exc}</p>'
        )
