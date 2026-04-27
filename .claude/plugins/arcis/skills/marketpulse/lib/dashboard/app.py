"""MarketPulse dashboard -- FastAPI application.

Entry points:
- CLI: ``python -m skills.marketpulse.lib.cli serve --port 8050``
- Direct: ``uvicorn skills.marketpulse.lib.dashboard.app:app --port 8050``
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..db import Base, get_config, get_session_factory, init_db

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup, clean up on shutdown."""
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await init_db(Base.metadata)
    logger.info("MarketPulse dashboard started (data_dir=%s)", config.data_dir)
    yield
    logger.info("MarketPulse dashboard shutting down")


app = FastAPI(
    title="MarketPulse Dashboard",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Import and include routers AFTER app creation to avoid circular imports
from .routes.overview import router as overview_router  # noqa: E402
from .routes.charts import router as charts_router  # noqa: E402
from .routes.analytics import router as analytics_router  # noqa: E402
from .routes.sectors import router as sectors_router  # noqa: E402
from .routes.events import router as events_router  # noqa: E402
from .routes.data import router as data_router  # noqa: E402

app.include_router(overview_router)
app.include_router(charts_router)
app.include_router(analytics_router)
app.include_router(sectors_router)
app.include_router(events_router)
app.include_router(data_router)
