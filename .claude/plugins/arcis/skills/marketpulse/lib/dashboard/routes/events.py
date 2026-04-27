"""Events route -- detection and impact analysis."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


@router.get("/events", response_class=HTMLResponse)
async def events_page(request: Request) -> HTMLResponse:
    """Render the events detection and impact analysis page."""
    cached_tickers: list[str] = []
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

    return templates.TemplateResponse(request, "events.html", {
        "active_page": "events",
        "cached_tickers": cached_tickers,
    })


@router.get("/api/detect-events", response_class=HTMLResponse)
async def detect_events(
    request: Request,
    event_type: str = Query("volume_spikes"),
    tickers: str = Query(""),
    from_date: str = Query(""),
    to_date: str = Query(""),
    threshold: float = Query(2.0),
) -> HTMLResponse:
    """Detect events and return an HTML partial with results table."""
    if not tickers or not from_date or not to_date:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
            "Please select tickers and a date range.</p>"
        )

    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager
        from ...client import PolygonClient

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = MagicMock(spec=PolygonClient)
        cm = CacheManager(config, client, sf)

        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)

        df = await cm.get_bars_df(
            tickers=ticker_list, timespan="1min",
            from_date=start, to_date=end, max_rows=500_000,
        )

        if df.empty:
            return HTMLResponse(
                '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
                "No cached data for the selected range. Pull data first.</p>"
            )

        from ...analytics import volume_spikes, price_gaps, anomaly_detection

        if event_type == "volume_spikes":
            result = volume_spikes(df, threshold=threshold)
        elif event_type == "price_gaps":
            result = price_gaps(df, threshold=threshold)
        elif event_type == "anomaly_detection":
            result = anomaly_detection(df, threshold=threshold)
        else:
            return HTMLResponse(
                f'<p class="text-sm text-red-500 py-4">Unknown event type: {event_type}</p>'
            )

        from ..services.chart_service import events_table_data
        rows = events_table_data(result, event_type)

        if not rows:
            return HTMLResponse(
                '<p class="text-sm text-gray-500 dark:text-slate-400 py-4">'
                "No events detected with the current threshold.</p>"
            )

        columns = ["ticker", "date", "type", "magnitude", "detail"]
        headers_html = "".join(
            f'<th class="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-slate-400 '
            f'uppercase tracking-wider">{h}</th>'
            for h in columns
        )
        rows_html = ""
        for row in rows:
            cells = "".join(
                f'<td class="px-4 py-3 text-sm text-gray-900 dark:text-slate-200 whitespace-nowrap">'
                f'{row.get(col, "")}</td>'
                for col in columns
            )
            rows_html += f'<tr class="border-b border-gray-200 dark:border-slate-700">{cells}</tr>'

        return HTMLResponse(
            f'<div class="overflow-x-auto">'
            f'<p class="text-sm text-gray-600 dark:text-slate-400 mb-2">'
            f'{len(rows)} events detected</p>'
            f'<table class="min-w-full divide-y divide-gray-200 dark:divide-slate-700">'
            f"<thead><tr>{headers_html}</tr></thead>"
            f"<tbody>{rows_html}</tbody></table></div>"
        )

    except Exception as exc:
        logger.warning("Event detection error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 py-4">Detection error: {exc}</p>'
        )


@router.get("/api/event-impact", response_class=HTMLResponse)
async def event_impact_api(
    request: Request,
    ticker: str = Query(""),
    event_date: str = Query(""),
    pre_days: int = Query(5),
    post_days: int = Query(5),
) -> HTMLResponse:
    """Run event impact analysis and return chart partial."""
    if not ticker or not event_date:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
            "Please select a ticker and event date.</p>"
        )

    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager
        from ...client import PolygonClient

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = MagicMock(spec=PolygonClient)
        cm = CacheManager(config, client, sf)

        event_dt = date.fromisoformat(event_date)
        buffer = max(pre_days, post_days) + 10
        start = event_dt - timedelta(days=buffer * 2)
        end = event_dt + timedelta(days=buffer * 2)

        df = await cm.get_bars_df(
            tickers=[ticker.strip().upper()], timespan="1min",
            from_date=start, to_date=end, max_rows=500_000,
        )

        if df.empty:
            return HTMLResponse(
                '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
                "No cached data for this ticker around the event date.</p>"
            )

        from ...analytics import event_impact
        result = event_impact(
            df, ticker=ticker.strip().upper(),
            event_date=event_date, pre_days=pre_days, post_days=post_days,
        )

        from ..services.chart_service import event_impact_chart_data
        chart = event_impact_chart_data(result)

        return HTMLResponse(
            f'<div id="impact-chart" style="width:100%;height:400px;"></div>'
            f"<script>"
            f"(function() {{"
            f"  var d = {json.dumps(chart)};"
            f"  Plotly.newPlot('impact-chart', d.traces, d.layout, {{responsive:true}});"
            f"}})()"
            f"</script>"
        )

    except Exception as exc:
        logger.warning("Impact analysis error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 py-4">Impact analysis error: {exc}</p>'
        )
