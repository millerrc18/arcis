"""Typer CLI for MarketPulse -- pull bar data, manage jobs, inspect cache, analytics.

Commands
--------
- ``pull``              -- Fetch bar data for tickers or an index.
- ``jobs list``         -- List all fetch jobs.
- ``jobs status``       -- Show detailed status of a specific job.
- ``jobs resume``       -- Resume a paused/failed job.
- ``cache-status``      -- Show what data is cached.
- ``indices list``      -- List available indices and custom lists.
- ``indices refresh``   -- Re-scrape index constituents from Wikipedia.
- ``indices create``    -- Create a custom named ticker list.
- ``analyze summary``   -- Daily OHLCV summary.
- ``analyze movers``    -- Biggest gainers/losers for a date.
- ``analyze volume``    -- Volume statistics.
- ``analyze volatility``-- Realized volatility.
- ``analyze correlation``-- Pairwise return correlation.
- ``analyze patterns``  -- Intraday / day-of-week / monthly patterns.
- ``analyze sectors``   -- Sector rotation analysis.
- ``events detect``     -- Detect volume spikes, price gaps, or anomalies.
- ``events impact``     -- Analyse event impact on price/volume.
- ``export data``          -- Export cached bar data to Excel/CSV/Parquet.
- ``report daily``         -- Generate a daily market report.
- ``report period``        -- Generate a period analysis report.
- ``report correlation``   -- Generate a correlation analysis report.
- ``report event``         -- Generate an event study report.

Usage::

    python -m skills.marketpulse.lib.cli pull AAPL,MSFT --from 2022-01-03 --to 2022-01-31
    python -m skills.marketpulse.lib.cli pull SP500 --from 2022-01-03 --to 2022-01-31
    python -m skills.marketpulse.lib.cli cache-status
    python -m skills.marketpulse.lib.cli jobs list
    python -m skills.marketpulse.lib.cli indices list
    python -m skills.marketpulse.lib.cli analyze summary AAPL,MSFT --from 2022-06-01 --to 2022-06-30
    python -m skills.marketpulse.lib.cli events detect AAPL --from 2022-06-01 --to 2022-06-30
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskID
from rich.table import Table

import pandas as pd

from .analytics import (
    daily_summary,
    biggest_movers,
    volume_analysis,
    realized_volatility,
    pairwise_correlation,
    intraday_patterns,
    day_of_week_effects,
    monthly_seasonality,
    sector_rotation,
    volume_spikes,
    price_gaps,
    anomaly_detection,
    event_impact,
)
from .analytics.types import load_sector_map
from .cache import BatchEngine, CacheManager, TIMESPAN_MAP
from .client import PolygonClient
from .db import (
    Base,
    MarketPulseConfig,
    get_config,
    get_engine,
    get_session_factory,
    init_db,
    reset_config,
)
from .indices import IndexManager
from .models import FetchJob

# ---------------------------------------------------------------------------
# Load .env early
# ---------------------------------------------------------------------------

load_dotenv()

# ---------------------------------------------------------------------------
# Typer app and console
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="marketpulse",
    help="MarketPulse -- pull and cache stock bar data from Polygon.io.",
    no_args_is_help=True,
)

jobs_app = typer.Typer(
    name="jobs",
    help="Manage fetch jobs.",
    no_args_is_help=True,
)
app.add_typer(jobs_app, name="jobs")

indices_app = typer.Typer(
    name="indices",
    help="Manage index constituent lists.",
    no_args_is_help=True,
)
app.add_typer(indices_app, name="indices")

analyze_app = typer.Typer(
    name="analyze",
    help="Run analytics on cached bar data.",
    no_args_is_help=True,
)
app.add_typer(analyze_app, name="analyze")

events_app = typer.Typer(
    name="events",
    help="Detect and analyse market events.",
    no_args_is_help=True,
)
app.add_typer(events_app, name="events")

export_app = typer.Typer(
    name="export",
    help="Export cached bar data to Excel, CSV, or Parquet.",
    no_args_is_help=True,
)
app.add_typer(export_app, name="export")

report_app = typer.Typer(
    name="report",
    help="Generate pre-built analysis reports.",
    no_args_is_help=True,
)
app.add_typer(report_app, name="report")

console = Console()

VALID_TIMESPANS = list(TIMESPAN_MAP.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_api_key() -> str:
    """Return the Polygon API key or exit with a helpful message."""
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        console.print(
            "[bold red]Error:[/bold red] POLYGON_API_KEY is not set.\n"
            "Set it in your environment or in a .env file at the project root.\n"
            "  export POLYGON_API_KEY=your_key_here",
        )
        raise typer.Exit(code=1)
    return key


def _parse_date(value: str, label: str) -> date:
    """Parse a YYYY-MM-DD string or exit with a helpful message."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        console.print(
            f"[bold red]Error:[/bold red] Invalid {label} date '{value}'. "
            "Use YYYY-MM-DD format (e.g. 2022-06-01).",
        )
        raise typer.Exit(code=1)


async def _init_db_async() -> None:
    """Ensure SQLite tables exist."""
    # Import models so that Base.metadata has all tables registered.
    from . import models as _models  # noqa: F401

    await init_db(Base.metadata)


# ---------------------------------------------------------------------------
# pull command
# ---------------------------------------------------------------------------


@app.command()
def pull(
    tickers_or_index: str = typer.Argument(
        ...,
        help="Comma-separated tickers (AAPL,MSFT) or an index name (SP500).",
    ),
    from_date: str = typer.Option(
        ..., "--from", help="Start date (YYYY-MM-DD).",
    ),
    to_date: str = typer.Option(
        ..., "--to", help="End date (YYYY-MM-DD).",
    ),
    timespan: str = typer.Option(
        "1min",
        "--timespan",
        help=f"Bar size. Options: {', '.join(VALID_TIMESPANS)}.",
    ),
) -> None:
    """Pull bar data for tickers or an index."""
    api_key = _require_api_key()

    start_dt = _parse_date(from_date, "--from")
    end_dt = _parse_date(to_date, "--to")

    if start_dt > end_dt:
        console.print(
            "[bold red]Error:[/bold red] --from date must be before --to date.",
        )
        raise typer.Exit(code=1)

    if timespan not in TIMESPAN_MAP:
        console.print(
            f"[bold red]Error:[/bold red] Invalid timespan '{timespan}'. "
            f"Valid options: {', '.join(VALID_TIMESPANS)}.",
        )
        raise typer.Exit(code=1)

    # Check for index name or custom list
    reset_config()
    idx_mgr = IndexManager(get_config())
    if idx_mgr.is_index(tickers_or_index):
        index = idx_mgr.get_index(tickers_or_index)
        if not index.tickers:
            console.print(
                f"[bold red]Error:[/bold red] Index '{tickers_or_index.upper()}' has no tickers. "
                "Run 'marketpulse indices refresh' or create a custom list.",
            )
            raise typer.Exit(code=1)
        tickers = index.tickers
        console.print(
            f"Resolved [bold]{index.short_name}[/bold] ({index.name}): "
            f"{len(tickers)} tickers",
        )
    else:
        tickers = [t.strip().upper() for t in tickers_or_index.split(",") if t.strip()]

    if not tickers:
        console.print("[bold red]Error:[/bold red] No tickers provided.")
        raise typer.Exit(code=1)

    asyncio.run(
        _pull_async(api_key, tickers, start_dt, end_dt, timespan)
    )


async def _pull_async(
    api_key: str,
    tickers: list[str],
    start_dt: date,
    end_dt: date,
    timespan: str,
) -> None:
    """Async implementation of the pull command."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    t0 = time.monotonic()
    total_bars = 0

    async with PolygonClient(api_key) as client:
        cm = CacheManager(config, client, sf)
        engine = BatchEngine(cm, sf)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task_id = progress.add_task("Pulling tickers...", total=len(tickers))

            def on_progress(ticker: str, completed: int, total: int) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    description=f"Fetched {ticker}",
                )

            try:
                job = await engine.pull(
                    tickers=tickers,
                    from_date=start_dt,
                    to_date=end_dt,
                    timespan=timespan,
                    on_progress=on_progress,
                )
            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Interrupted.[/yellow] "
                    "Use 'jobs list' to find the job ID, then 'jobs resume <id>'.",
                )
                return

    elapsed = time.monotonic() - t0

    # Summary
    status_color = "green" if job.status == "completed" else "yellow"
    console.print(
        f"\n[bold {status_color}]Job {job.id}[/bold {status_color}] -- "
        f"status: {job.status}"
    )
    console.print(
        f"  Tickers fetched: {job.completed_tickers}/{job.total_tickers}"
    )
    console.print(f"  Timespan: {job.timespan}")
    console.print(f"  Date range: {job.from_date} to {job.to_date}")
    console.print(f"  Elapsed: {elapsed:.1f}s")

    if job.status == "paused":
        console.print(
            f"\n  Resume with: [bold]marketpulse jobs resume {job.id}[/bold]"
        )
    if job.error:
        console.print(f"  Error: {job.error}")

    # Clean up singletons so a second call in the same process works
    reset_config()


# ---------------------------------------------------------------------------
# cache-status command
# ---------------------------------------------------------------------------


@app.command("cache-status")
def cache_status(
    ticker: Optional[str] = typer.Argument(
        None,
        help="Ticker symbol for detailed coverage. Omit for summary.",
    ),
) -> None:
    """Show what bar data is currently cached."""
    _require_api_key()  # validates env is configured
    asyncio.run(_cache_status_async(ticker))


async def _cache_status_async(ticker: str | None) -> None:
    """Async implementation of cache-status."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    # We don't need a real Polygon client for cache-status.
    # Use a dummy -- CacheManager won't call it for status queries.
    from unittest.mock import MagicMock
    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    status = await cm.get_cache_status(ticker=ticker.upper() if ticker else None)

    if ticker is not None:
        # Per-ticker detail
        table = Table(title=f"Cache Coverage: {status['ticker']}")
        table.add_column("Timespan", style="cyan")
        table.add_column("Months Cached", style="green")

        tc = status.get("timespan_coverage", {})
        if not tc:
            console.print(f"[yellow]No cached data for {ticker.upper()}.[/yellow]")
        else:
            for ts, months in sorted(tc.items()):
                table.add_row(ts, ", ".join(months))
            console.print(table)
            console.print(f"  Total bars: {status['total_bars']:,}")
    else:
        # Summary
        table = Table(title="MarketPulse Cache Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")

        table.add_row("Tickers", str(status["total_tickers"]))
        table.add_row("Total bars", f"{status['total_bars']:,}")
        table.add_row("Partitions", str(status["total_partitions"]))
        console.print(table)

    reset_config()


# ---------------------------------------------------------------------------
# jobs subcommands
# ---------------------------------------------------------------------------


@jobs_app.command("list")
def jobs_list() -> None:
    """List all fetch jobs."""
    _require_api_key()
    asyncio.run(_jobs_list_async())


async def _jobs_list_async() -> None:
    """Async implementation of jobs list."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from unittest.mock import MagicMock
    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)
    engine = BatchEngine(cm, sf)

    jobs = await engine.list_jobs()

    if not jobs:
        console.print("[yellow]No fetch jobs found.[/yellow]")
        reset_config()
        return

    table = Table(title="Fetch Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Progress")
    table.add_column("Timespan")
    table.add_column("Date Range")
    table.add_column("Created")

    for job in jobs:
        status_style = {
            "completed": "green",
            "running": "blue",
            "paused": "yellow",
            "failed": "red",
            "pending": "dim",
        }.get(job.status, "white")

        table.add_row(
            job.id,
            f"[{status_style}]{job.status}[/{status_style}]",
            f"{job.completed_tickers}/{job.total_tickers}",
            job.timespan,
            f"{job.from_date} to {job.to_date}",
            job.created_at[:19],
        )

    console.print(table)
    reset_config()


@jobs_app.command("status")
def jobs_status(
    job_id: str = typer.Argument(..., help="Job ID to inspect."),
) -> None:
    """Show detailed status of a specific job."""
    _require_api_key()
    asyncio.run(_jobs_status_async(job_id))


async def _jobs_status_async(job_id: str) -> None:
    """Async implementation of jobs status."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from sqlalchemy import select

    async with sf() as session:
        result = await session.execute(
            select(FetchJob).where(FetchJob.id == job_id)
        )
        job = result.scalar_one_or_none()

    if job is None:
        console.print(f"[bold red]Error:[/bold red] Job '{job_id}' not found.")
        reset_config()
        raise typer.Exit(code=1)

    tickers_list = json.loads(job.tickers)

    table = Table(title=f"Job {job.id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    status_style = {
        "completed": "green",
        "running": "blue",
        "paused": "yellow",
        "failed": "red",
        "pending": "dim",
    }.get(job.status, "white")

    table.add_row("Status", f"[{status_style}]{job.status}[/{status_style}]")
    table.add_row("Progress", f"{job.completed_tickers}/{job.total_tickers}")
    table.add_row("Timespan", job.timespan)
    table.add_row("Date Range", f"{job.from_date} to {job.to_date}")
    table.add_row("Tickers", ", ".join(tickers_list))
    table.add_row("Created", job.created_at)

    if job.current_ticker:
        table.add_row("Current Ticker", job.current_ticker)
    if job.error:
        table.add_row("Error", f"[red]{job.error}[/red]")

    console.print(table)
    reset_config()


@jobs_app.command("resume")
def jobs_resume(
    job_id: str = typer.Argument(..., help="Job ID to resume."),
) -> None:
    """Resume a paused or failed job."""
    api_key = _require_api_key()
    asyncio.run(_jobs_resume_async(api_key, job_id))


async def _jobs_resume_async(api_key: str, job_id: str) -> None:
    """Async implementation of jobs resume."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    # Verify the job exists and is resumable
    from sqlalchemy import select

    async with sf() as session:
        result = await session.execute(
            select(FetchJob).where(FetchJob.id == job_id)
        )
        job = result.scalar_one_or_none()

    if job is None:
        console.print(f"[bold red]Error:[/bold red] Job '{job_id}' not found.")
        reset_config()
        raise typer.Exit(code=1)

    if job.status not in ("paused", "failed"):
        console.print(
            f"[bold red]Error:[/bold red] Job '{job_id}' has status '{job.status}'. "
            "Only paused or failed jobs can be resumed.",
        )
        reset_config()
        raise typer.Exit(code=1)

    t0 = time.monotonic()

    async with PolygonClient(api_key) as client:
        cm = CacheManager(config, client, sf)
        engine = BatchEngine(cm, sf)

        remaining = json.loads(job.tickers)[job.completed_tickers:]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "Resuming...", total=len(remaining)
            )

            def on_progress(ticker: str, completed: int, total: int) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    description=f"Fetched {ticker}",
                )

            resumed_job = await engine.resume(job_id, on_progress=on_progress)

    elapsed = time.monotonic() - t0

    status_color = "green" if resumed_job.status == "completed" else "yellow"
    console.print(
        f"\n[bold {status_color}]Job {resumed_job.id}[/bold {status_color}] -- "
        f"status: {resumed_job.status}"
    )
    console.print(
        f"  Tickers fetched: {resumed_job.completed_tickers}/{resumed_job.total_tickers}"
    )
    console.print(f"  Elapsed: {elapsed:.1f}s")

    if resumed_job.error:
        console.print(f"  Error: {resumed_job.error}")

    reset_config()


# ---------------------------------------------------------------------------
# indices subcommands
# ---------------------------------------------------------------------------


@indices_app.command("list")
def indices_list() -> None:
    """List all available indices and custom lists."""
    reset_config()
    idx_mgr = IndexManager(get_config())
    indices = idx_mgr.list_indices()
    if not indices:
        console.print("No indices found.")
        return
    table = Table(title="Available Indices")
    table.add_column("Name", style="bold")
    table.add_column("Full Name")
    table.add_column("Tickers", justify="right")
    table.add_column("Source")
    table.add_column("Updated")
    for idx in indices:
        table.add_row(
            idx.short_name, idx.name, str(idx.ticker_count),
            idx.source, idx.last_updated,
        )
    console.print(table)


@indices_app.command("refresh")
def indices_refresh(
    index_name: str = typer.Argument(..., help="Index to refresh (SP100, SP500, DOW30, NDX100)."),
) -> None:
    """Re-scrape index constituents from Wikipedia."""
    reset_config()
    idx_mgr = IndexManager(get_config())
    try:
        console.print(f"Refreshing [bold]{index_name.upper()}[/bold] from Wikipedia...")
        index = idx_mgr.refresh_index(index_name)
        console.print(
            f"[green]Done![/green] {index.short_name}: "
            f"{len(index.constituents)} tickers updated.",
        )
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@indices_app.command("create")
def indices_create(
    name: str = typer.Argument(..., help="Name for the custom list."),
    tickers: str = typer.Argument(..., help="Comma-separated tickers."),
) -> None:
    """Create a custom named ticker list."""
    reset_config()
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        console.print("[bold red]Error:[/bold red] No tickers provided.")
        raise typer.Exit(code=1)
    idx_mgr = IndexManager(get_config())
    index = idx_mgr.create_custom_list(name, ticker_list)
    console.print(
        f"[green]Created custom list '{name}'[/green] with "
        f"{len(index.constituents)} tickers.",
    )


# ---------------------------------------------------------------------------
# Shared analytics helper
# ---------------------------------------------------------------------------


async def _load_bars(
    tickers_str: str,
    from_date: str,
    to_date: str,
    timespan: str,
) -> pd.DataFrame:
    """Load cached bar data for analytics commands."""
    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    # Resolve index names
    idx_mgr = IndexManager(config)
    if idx_mgr.is_index(tickers_str.strip()):
        index = idx_mgr.get_index(tickers_str.strip())
        ticker_list = index.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    if not ticker_list:
        console.print("[bold red]Error:[/bold red] No tickers provided.")
        raise typer.Exit(code=1)

    from unittest.mock import MagicMock

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    start_dt = _parse_date(from_date, "--from")
    end_dt = _parse_date(to_date, "--to")

    df = await cm.get_bars_df(ticker_list, timespan, start_dt, end_dt)
    reset_config()
    return df


# ---------------------------------------------------------------------------
# analyze subcommands
# ---------------------------------------------------------------------------


@analyze_app.command("summary")
def analyze_summary(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show daily OHLCV summary for tickers."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = daily_summary(df)
        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("movers")
def analyze_movers(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    date: str = typer.Option(..., "--date", help="Date to check (YYYY-MM-DD)."),
    n: int = typer.Option(10, "--n", help="Number of top/bottom movers."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show biggest gainers and losers for a date."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, date, date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = biggest_movers(df, date, n)
        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("volume")
def analyze_volume(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show volume statistics for tickers."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = volume_analysis(df)
        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("volatility")
def analyze_volatility(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    window: str = typer.Option("1d", "--window", help="Window: '1d' or 'intraday'."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show realized volatility for tickers."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = realized_volatility(df, window=window)
        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("correlation")
def analyze_correlation(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show pairwise return correlation between tickers."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = pairwise_correlation(df)
        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("patterns")
def analyze_patterns(
    tickers: str = typer.Argument(..., help="Single ticker or comma-separated tickers."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    pattern_type: str = typer.Option(
        "intraday", "--type",
        help="Pattern type: 'intraday', 'day-of-week', or 'monthly'.",
    ),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show intraday, day-of-week, or monthly return patterns."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return

        # Resolve the first ticker for single-ticker pattern functions
        ticker = tickers.split(",")[0].strip().upper()

        if pattern_type == "intraday":
            result = intraday_patterns(df, ticker)
        elif pattern_type == "day-of-week":
            result = day_of_week_effects(df, ticker)
        elif pattern_type == "monthly":
            result = monthly_seasonality(df, ticker)
        else:
            console.print(
                f"[bold red]Error:[/bold red] Unknown pattern type '{pattern_type}'. "
                "Use 'intraday', 'day-of-week', or 'monthly'.",
            )
            raise typer.Exit(code=1)

        console.print(result.to_rich_table())

    asyncio.run(_run())


@analyze_app.command("sectors")
def analyze_sectors(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    index: str = typer.Option("SP500", "--index", help="Index for sector map (e.g. SP500)."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Show sector rotation analysis."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        sector_map = load_sector_map(index)
        result = sector_rotation(df, sector_map)
        console.print(result.to_rich_table())

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# events subcommands
# ---------------------------------------------------------------------------


@events_app.command("detect")
def events_detect(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    event_type: str = typer.Option(
        "volume_spikes", "--type",
        help="Event type: 'volume_spikes', 'price_gaps', or 'anomaly_detection'.",
    ),
    threshold: float = typer.Option(3.0, "--threshold", help="Detection threshold."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Detect market events in cached data."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return

        if event_type == "volume_spikes":
            result = volume_spikes(df, threshold=threshold)
        elif event_type == "price_gaps":
            result = price_gaps(df, threshold=threshold)
        elif event_type == "anomaly_detection":
            result = anomaly_detection(df, z_threshold=threshold)
        else:
            console.print(
                f"[bold red]Error:[/bold red] Unknown event type '{event_type}'. "
                "Use 'volume_spikes', 'price_gaps', or 'anomaly_detection'.",
            )
            raise typer.Exit(code=1)

        console.print(result.to_rich_table())

    asyncio.run(_run())


@events_app.command("impact")
def events_impact(
    ticker: str = typer.Argument(..., help="Single ticker symbol."),
    event_date: str = typer.Option(..., "--event-date", help="Event date (YYYY-MM-DD)."),
    from_date: str = typer.Option(..., "--from", help="Start of data range."),
    to_date: str = typer.Option(..., "--to", help="End of data range."),
    pre_days: int = typer.Option(5, "--pre", help="Days before event."),
    post_days: int = typer.Option(5, "--post", help="Days after event."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Analyse impact of an event on price/volume."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(ticker, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return
        result = event_impact(df, ticker.strip().upper(), event_date, pre_days, post_days)
        console.print(result.to_rich_table())

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# export subcommands
# ---------------------------------------------------------------------------


@export_app.command("data")
def export_data(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    format: str = typer.Option("excel", "--format", help="Output format: excel, csv, or parquet."),
    output: str = typer.Option("", "--output", help="Output file path. Empty = Desktop default."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Export cached bar data to a file."""
    _require_api_key()

    async def _run() -> None:
        df = await _load_bars(tickers, from_date, to_date, timespan)
        if df.empty:
            console.print("[yellow]No cached data found for the given parameters.[/yellow]")
            return

        from .export import to_excel, to_csv, to_parquet

        out_path = output if output else None

        if format == "excel":
            result = to_excel(df, path=out_path)
        elif format == "csv":
            result = to_csv(df, path=out_path)
        elif format == "parquet":
            result = to_parquet(df, path=out_path)
        else:
            console.print(
                f"[bold red]Error:[/bold red] Unknown format '{format}'. "
                "Use 'excel', 'csv', or 'parquet'.",
            )
            raise typer.Exit(code=1)

        console.print(f"[green]Exported to:[/green] {result}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# report subcommands
# ---------------------------------------------------------------------------


@report_app.command("daily")
def report_daily(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    date: str = typer.Option(..., "--date", help="Report date (YYYY-MM-DD)."),
    output: str = typer.Option("", "--output", help="Output file path."),
    index: str = typer.Option("", "--index", help="Index name for sector mapping (e.g. SP500)."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Generate a daily market report."""
    _require_api_key()
    asyncio.run(_report_daily_async(tickers, date, output, index, timespan))


async def _report_daily_async(
    tickers_str: str, date_str: str, output: str, index: str, timespan: str
) -> None:
    """Async implementation of daily report."""
    from .reports import daily_market_report

    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from unittest.mock import MagicMock

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    # Resolve tickers
    idx_mgr = IndexManager(config)
    if idx_mgr.is_index(tickers_str.strip()):
        index_obj = idx_mgr.get_index(tickers_str.strip())
        ticker_list = index_obj.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    report_dt = _parse_date(date_str, "--date")
    out_path = output if output else None
    idx_name = index if index else None

    try:
        result = await daily_market_report(
            cm, ticker_list, report_dt,
            timespan=timespan, index_name=idx_name, output=out_path,
        )
        console.print(f"[green]Report generated:[/green] {result}")
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    reset_config()


@report_app.command("period")
def report_period(
    tickers: str = typer.Argument(..., help="Comma-separated tickers or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    output: str = typer.Option("", "--output", help="Output file path."),
    index: str = typer.Option("", "--index", help="Index name for sector analytics."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Generate a period analysis report."""
    _require_api_key()
    asyncio.run(_report_period_async(tickers, from_date, to_date, output, index, timespan))


async def _report_period_async(
    tickers_str: str, from_date: str, to_date: str,
    output: str, index: str, timespan: str,
) -> None:
    """Async implementation of period report."""
    from .reports import period_analysis_report

    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from unittest.mock import MagicMock

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    idx_mgr = IndexManager(config)
    if idx_mgr.is_index(tickers_str.strip()):
        index_obj = idx_mgr.get_index(tickers_str.strip())
        ticker_list = index_obj.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    start_dt = _parse_date(from_date, "--from")
    end_dt = _parse_date(to_date, "--to")
    out_path = output if output else None
    idx_name = index if index else None

    try:
        result = await period_analysis_report(
            cm, ticker_list, start_dt, end_dt,
            timespan=timespan, index_name=idx_name, output=out_path,
        )
        console.print(f"[green]Report generated:[/green] {result}")
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    reset_config()


@report_app.command("correlation")
def report_correlation(
    tickers: str = typer.Argument(..., help="Comma-separated tickers (min 2) or index name."),
    from_date: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)."),
    to_date: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD)."),
    output: str = typer.Option("", "--output", help="Output file path."),
    index: str = typer.Option("", "--index", help="Index name for sector correlation."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Generate a correlation analysis report."""
    _require_api_key()
    asyncio.run(_report_correlation_async(tickers, from_date, to_date, output, index, timespan))


async def _report_correlation_async(
    tickers_str: str, from_date: str, to_date: str,
    output: str, index: str, timespan: str,
) -> None:
    """Async implementation of correlation report."""
    from .reports import correlation_report

    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from unittest.mock import MagicMock

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    idx_mgr = IndexManager(config)
    if idx_mgr.is_index(tickers_str.strip()):
        index_obj = idx_mgr.get_index(tickers_str.strip())
        ticker_list = index_obj.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    start_dt = _parse_date(from_date, "--from")
    end_dt = _parse_date(to_date, "--to")
    out_path = output if output else None
    idx_name = index if index else None

    try:
        result = await correlation_report(
            cm, ticker_list, start_dt, end_dt,
            timespan=timespan, index_name=idx_name, output=out_path,
        )
        console.print(f"[green]Report generated:[/green] {result}")
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    reset_config()


@report_app.command("event")
def report_event(
    ticker: str = typer.Argument(..., help="Single ticker symbol."),
    event_date: str = typer.Option(..., "--event-date", help="Event date (YYYY-MM-DD)."),
    from_date: str = typer.Option(..., "--from", help="Start of data range."),
    to_date: str = typer.Option(..., "--to", help="End of data range."),
    pre_days: int = typer.Option(5, "--pre", help="Days before event."),
    post_days: int = typer.Option(5, "--post", help="Days after event."),
    output: str = typer.Option("", "--output", help="Output file path."),
    timespan: str = typer.Option("1min", "--timespan", help="Bar size."),
) -> None:
    """Generate an event study report."""
    _require_api_key()
    asyncio.run(_report_event_async(
        ticker, event_date, from_date, to_date, pre_days, post_days, output, timespan,
    ))


async def _report_event_async(
    ticker: str, event_date: str, from_date: str, to_date: str,
    pre_days: int, post_days: int, output: str, timespan: str,
) -> None:
    """Async implementation of event study report."""
    from .reports import event_study_report

    reset_config()
    config = get_config()
    config.ensure_dirs()
    sf = get_session_factory(config)
    await _init_db_async()

    from unittest.mock import MagicMock

    dummy_client = MagicMock(spec=PolygonClient)
    cm = CacheManager(config, dummy_client, sf)

    event_dt = _parse_date(event_date, "--event-date")
    start_dt = _parse_date(from_date, "--from")
    end_dt = _parse_date(to_date, "--to")
    out_path = output if output else None

    try:
        result = await event_study_report(
            cm, ticker.strip().upper(), event_dt, start_dt, end_dt,
            pre_days=pre_days, post_days=post_days,
            timespan=timespan, output=out_path,
        )
        console.print(f"[green]Report generated:[/green] {result}")
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    reset_config()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
