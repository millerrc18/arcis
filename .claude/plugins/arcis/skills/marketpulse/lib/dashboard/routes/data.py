"""Data management page -- pull, jobs, cache status, export routes."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse

from ..templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["data"])

# In-memory job tracking (dashboard is single-user, single-process)
_jobs: dict[str, dict[str, Any]] = {}


@router.get("/data", response_class=HTMLResponse)
async def data_page(request: Request) -> HTMLResponse:
    """Render the data management page with cache status."""
    from ...db import get_config, get_session_factory, init_db, Base
    from ...cache import CacheManager
    from ...client import PolygonClient

    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await init_db(Base.metadata)

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    cache_status = await cm.get_cache_status()

    # Get per-ticker details
    ticker_details: list[dict] = []
    if cache_status.get("total_bars", 0) > 0:
        try:
            from sqlalchemy import text

            async with sf() as session:
                result = await session.execute(text(
                    "SELECT ticker, timespan, MIN(timestamp) as first_bar, "
                    "MAX(timestamp) as last_bar, COUNT(*) as bar_count "
                    "FROM bars GROUP BY ticker, timespan ORDER BY ticker, timespan"
                ))
                for row in result.fetchall():
                    ticker_details.append({
                        "ticker": row[0],
                        "timespan": row[1],
                        "first_bar": str(row[2])[:10],
                        "last_bar": str(row[3])[:10],
                        "bar_count": f"{row[4]:,}",
                    })
        except Exception:
            logger.warning("Failed to load ticker details", exc_info=True)

    return templates.TemplateResponse(request, "data.html", {
        "active_page": "data",
        "cache_status": cache_status,
        "ticker_details": ticker_details,
        "jobs": _jobs,
    })


@router.post("/api/pull", response_class=HTMLResponse)
async def pull_data(
    request: Request,
    tickers: str = Form(""),
    from_date: str = Form(""),
    to_date: str = Form(""),
    timespan: str = Form("1min"),
) -> HTMLResponse:
    """Start a background data pull and return a job row partial."""
    if not tickers or not from_date or not to_date:
        return HTMLResponse(
            '<tr><td colspan="5" class="px-4 py-3 text-sm text-yellow-600 dark:text-yellow-400">'
            "Please fill in all fields.</td></tr>"
        )

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "id": job_id,
        "tickers": ticker_list,
        "from": from_date,
        "to": to_date,
        "timespan": timespan,
        "status": "running",
        "progress": 0,
        "current_ticker": ticker_list[0] if ticker_list else "",
        "started": time.time(),
        "error": None,
    }

    # Launch background task
    asyncio.create_task(_run_pull(job_id, ticker_list, start, end, timespan))

    return _render_job_row(_jobs[job_id])


async def _run_pull(
    job_id: str,
    tickers: list[str],
    start: date,
    end: date,
    timespan: str,
) -> None:
    """Background task to pull data for each ticker."""
    job = _jobs[job_id]
    try:
        from ...db import get_config, get_session_factory, init_db, Base
        from ...cache import CacheManager, BatchEngine
        from ...client import PolygonClient

        config = get_config()
        config.ensure_dirs()
        sf = get_session_factory(config)
        await init_db(Base.metadata)

        client = PolygonClient(config)
        cm = CacheManager(config, client, sf)
        engine = BatchEngine(cm, sf)

        def on_progress(current_ticker: str, completed: int, total: int) -> None:
            job["current_ticker"] = current_ticker
            job["progress"] = int((completed / total) * 100) if total else 0

        await engine.pull(
            tickers=tickers,
            from_date=start,
            to_date=end,
            timespan=timespan,
            on_progress=on_progress,
        )

        job["status"] = "complete"
        job["progress"] = 100
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        logger.warning("Pull job %s failed: %s", job_id, exc, exc_info=True)


@router.get("/api/jobs/{job_id}", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str) -> HTMLResponse:
    """Return updated job row partial for HTMX polling."""
    job = _jobs.get(job_id)
    if not job:
        return HTMLResponse(
            '<tr><td colspan="5" class="px-4 py-3 text-sm text-red-500">'
            f"Job {job_id} not found.</td></tr>"
        )
    return _render_job_row(job)


def _render_job_row(job: dict) -> HTMLResponse:
    """Render a single job row as HTML."""
    elapsed = int(time.time() - job["started"])
    elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"
    tickers_str = ", ".join(job["tickers"][:3])
    if len(job["tickers"]) > 3:
        tickers_str += f" +{len(job['tickers']) - 3}"

    status_badge = {
        "running": '<span class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 '
                   'dark:bg-blue-900 dark:text-blue-300">Running</span>',
        "complete": '<span class="px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-700 '
                    'dark:bg-green-900 dark:text-green-300">Complete</span>',
        "error": '<span class="px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-700 '
                 'dark:bg-red-900 dark:text-red-300">Error</span>',
    }.get(job["status"], "")

    progress_bar = ""
    if job["status"] == "running":
        progress_bar = (
            f'<div class="w-full bg-gray-200 dark:bg-slate-600 rounded-full h-1.5 mt-1">'
            f'<div class="bg-sky-500 h-1.5 rounded-full" style="width:{job["progress"]}%"></div>'
            f"</div>"
        )

    # HTMX polling: keep polling if still running
    poll_attrs = ""
    if job["status"] == "running":
        poll_attrs = (
            f'hx-get="/api/jobs/{job["id"]}" hx-trigger="every 2s" '
            f'hx-swap="outerHTML"'
        )

    error_info = ""
    if job["error"]:
        error_info = f'<div class="text-xs text-red-500 mt-1">{job["error"]}</div>'

    return HTMLResponse(
        f'<tr id="job-{job["id"]}" {poll_attrs} '
        f'class="border-b border-gray-200 dark:border-slate-700">'
        f'<td class="px-4 py-3 text-sm text-gray-900 dark:text-slate-200">{job["id"]}</td>'
        f'<td class="px-4 py-3 text-sm text-gray-900 dark:text-slate-200">{tickers_str}</td>'
        f'<td class="px-4 py-3 text-sm">{status_badge}{progress_bar}{error_info}</td>'
        f'<td class="px-4 py-3 text-sm text-gray-500 dark:text-slate-400">'
        f'{job["current_ticker"]}</td>'
        f'<td class="px-4 py-3 text-sm text-gray-500 dark:text-slate-400">{elapsed_str}</td>'
        f"</tr>"
    )


@router.get("/api/export/{fmt}", response_model=None)
async def export_data(request: Request, fmt: str, tickers: str = ""):
    """Export cached data as Excel, CSV, or Parquet download."""
    from ...db import get_config, get_session_factory, init_db, Base
    from ...cache import CacheManager
    from ...client import PolygonClient
    from ...models import Coverage
    from sqlalchemy import select

    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await init_db(Base.metadata)

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    # Resolve tickers -- use provided list or all cached tickers
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        async with sf() as session:
            result = await session.execute(select(Coverage.ticker).distinct())
            ticker_list = [row[0] for row in result.fetchall()]

    if not ticker_list:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
            "No cached data to export.</p>"
        )

    try:
        df = await cm.get_bars_df(
            tickers=ticker_list,
            timespan="1day",
            from_date=date(2000, 1, 1),
            to_date=date.today(),
            max_rows=500_000,
        )
    except Exception as exc:
        logger.warning("Export data load error: %s", exc, exc_info=True)
        return HTMLResponse(
            f'<p class="text-sm text-red-500 py-4">Export error: {exc}</p>'
        )

    if df.empty:
        return HTMLResponse(
            '<p class="text-sm text-yellow-600 dark:text-yellow-400 py-4">'
            "No data to export.</p>"
        )

    from ...export import to_excel, to_csv, to_parquet

    tmp_dir = Path(tempfile.mkdtemp())

    if fmt == "excel":
        out = to_excel(df, path=tmp_dir / "marketpulse_export.xlsx")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        out = to_csv(df, path=tmp_dir / "marketpulse_export.csv")
        media_type = "text/csv"
    elif fmt == "parquet":
        out = to_parquet(df, path=tmp_dir / "marketpulse_export.parquet")
        media_type = "application/octet-stream"
    else:
        return HTMLResponse(
            f'<p class="text-sm text-red-500 py-4">Unknown format: {fmt}</p>'
        )

    return FileResponse(
        path=str(out),
        media_type=media_type,
        filename=out.name,
    )
