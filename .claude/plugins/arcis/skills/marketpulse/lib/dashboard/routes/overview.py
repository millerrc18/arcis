"""Overview page route -- landing page with market stats and movers."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templating import templates
from ..services.chart_service import (
    movers_to_template_data,
    overview_stats,
    volume_distribution_chart,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(tags=["overview"])


@router.get("/", response_class=HTMLResponse)
async def overview_page(request: Request) -> HTMLResponse:
    """Render the overview / landing page.

    Shows stat cards, top movers, volume distribution, and sector
    performance -- all derived from cached data.
    """
    from ...cache import CacheManager
    from ...client import PolygonClient
    from ...db import get_config, get_session_factory, init_db, Base
    from ...analytics.summary import daily_summary, biggest_movers, volume_analysis

    # Initialize stack
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await init_db(Base.metadata)

    # Create a CacheManager (we only need read access, no client needed)
    # Use a dummy client since we're only reading cached data
    from unittest.mock import MagicMock
    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    # Get cache status
    cache_status = await cm.get_cache_status()
    stats = overview_stats(cache_status)

    # Template context defaults
    context = {
        "active_page": "overview",
        "stats": stats,
        "movers": None,
        "volume_chart": None,
        "sector_data": None,
        "marquee_tickers": None,
    }

    # If we have cached data, run analytics
    if cache_status.get("total_bars", 0) > 0:
        try:
            # Load recent bars for analytics (last 30 days, all tickers)
            today = date.today()
            from_date = today - timedelta(days=60)

            # Get all cached tickers from coverage table
            from sqlalchemy import select, func
            from ...models import Coverage
            async with sf() as session:
                stmt = select(func.distinct(Coverage.ticker))
                result = await session.execute(stmt)
                all_tickers = [row[0] for row in result.fetchall()]

            if all_tickers:
                df = await cm.get_bars_df(
                    tickers=all_tickers,
                    timespan="1day",
                    from_date=from_date,
                    to_date=today,
                    max_rows=50_000,
                )

                if not df.empty:
                    # Daily summary for marquee
                    summary = daily_summary(df)
                    if summary.summaries:
                        # Get the most recent date
                        latest_date = max(s.date for s in summary.summaries)

                        # Movers for that date
                        movers_result = biggest_movers(df, date_str=latest_date, n=5)
                        context["movers"] = movers_to_template_data(movers_result)

                        # Marquee: all tickers with their latest return
                        latest_summaries = [s for s in summary.summaries if s.date == latest_date]
                        context["marquee_tickers"] = [
                            {"ticker": s.ticker, "return_pct": s.daily_return}
                            for s in sorted(latest_summaries, key=lambda x: abs(x.daily_return), reverse=True)[:10]
                        ]

                    # Volume distribution
                    vol_result = volume_analysis(df)
                    context["volume_chart"] = volume_distribution_chart(vol_result)

                    # Sector performance (try to load sector map)
                    try:
                        from ...analytics.types import load_sector_map
                        from ...analytics.sectors import sector_rotation
                        sector_map = load_sector_map()
                        if sector_map:
                            rotation = sector_rotation(df, sector_map)
                            context["sector_data"] = [
                                {"sector": s.sector, "avg_return": s.avg_return, "ticker_count": s.ticker_count}
                                for s in rotation.sectors
                            ]
                    except Exception:
                        logger.debug("Could not load sector data", exc_info=True)

        except Exception:
            logger.warning("Could not load analytics for overview", exc_info=True)

    return templates.TemplateResponse(request, "overview.html", context)
