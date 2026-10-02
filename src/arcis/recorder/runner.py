"""Recording runs: poll (every 15 min via cron), sweep (backfill), gaps.

poll:
  - Takes an OS-exclusive lock on data_root/recorder.lock; refuses to run
    when another poll holds it.
  - Validates the config and today's universe snapshot (fail-closed).
  - Fetches the last 24h of news, checks the Alpaca Date header against
    local time (refuses when skew > 5 min), then stores each article under
    every configured symbol it is tagged with.
  - Writes heartbeat.json atomically on success; on failure the previous
    heartbeat is untouched and the process exits non-zero.

sweep: backfills an explicit [start, end] date range (catches up missed
windows after downtime).

gaps: reports coverage — heartbeat age and per-day article counts.
"""
from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from arcis.recorder.client import AlpacaNewsClient, FetchedArticle
from arcis.recorder.config import Config
from arcis.recorder.errors import ClockError, LockError
from arcis.recorder.store import NewsStore
from arcis.recorder.universe import validate_universe
from arcis.recorder.versioning import VersionIndex, version_hash

LOCK_NAME = "recorder.lock"
HEARTBEAT_NAME = "heartbeat.json"
POLL_WINDOW_HOURS = 24
MAX_CLOCK_SKEW_SECONDS = 300


@contextmanager
def exclusive_lock(lock_path: Path) -> Iterator[None]:
    """OS-exclusive lock; raises LockError if another poll holds it."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise LockError(f"another poll holds {lock_path}") from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def check_clock(server_date: str | None, max_skew_seconds: int = MAX_CLOCK_SKEW_SECONDS) -> None:
    """Refuse to record when the Alpaca clock skew exceeds the maximum."""
    if server_date is None:
        raise ClockError("no Date header captured from Alpaca; refusing to record")
    try:
        server_time = parsedate_to_datetime(server_date)
    except (TypeError, ValueError) as e:
        raise ClockError(f"unparseable Date header {server_date!r}: {e}") from e
    if server_time.tzinfo is None:
        server_time = server_time.replace(tzinfo=UTC)
    skew = abs((datetime.now(UTC) - server_time).total_seconds())
    if skew > max_skew_seconds:
        raise ClockError(f"clock skew {skew:.0f}s exceeds {max_skew_seconds}s; refusing to record")


def write_heartbeat(data_root: Path, payload: dict[str, Any]) -> None:
    target = data_root / HEARTBEAT_NAME
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.rename(tmp, target)


def read_heartbeat(data_root: Path) -> dict[str, Any] | None:
    path = data_root / HEARTBEAT_NAME
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def _store_fetched(
    config: Config,
    store: NewsStore,
    index: VersionIndex,
    fetched_list: list[FetchedArticle],
) -> int:
    """Store each article under every configured symbol it is tagged with.
    Returns the number of new (symbol, article) pairs stored."""
    universe = set(config.symbols)
    stored = 0
    for fetched in fetched_list:
        vhash = version_hash(fetched.raw)
        for symbol in fetched.article.symbols:
            if symbol in universe and store.append(symbol, fetched):
                index.append(symbol, fetched.article.id, vhash)
                stored += 1
    return stored


def poll(
    config: Config,
    client_factory: Callable[[Config], AlpacaNewsClient] = AlpacaNewsClient,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one poll. Returns a summary dict; raises on any failure."""
    now = now or datetime.now(UTC)
    validate_universe(config, now.date())
    store = NewsStore(config.data_root)
    index = VersionIndex(config.data_root)
    with exclusive_lock(config.data_root / LOCK_NAME):
        client = client_factory(config)
        try:
            end = now
            start = end - timedelta(hours=POLL_WINDOW_HOURS)
            fetched_list = list(client.fetch_news(config.symbols, start, end))
            check_clock(client.last_server_date)
            stored = _store_fetched(config, store, index, fetched_list)
            summary: dict[str, Any] = {
                "last_poll_at": end.isoformat(),
                "universe_date": now.date().isoformat(),
                "universe_name": config.universe_name,
                "symbols_configured": len(config.symbols),
                "articles_fetched": len(fetched_list),
                "pairs_stored": stored,
                "server_date": client.last_server_date,
            }
            write_heartbeat(config.data_root, summary)
            return summary
        finally:
            client.close()


def sweep(
    config: Config,
    start: date,
    end: date,
    client_factory: Callable[[Config], AlpacaNewsClient] = AlpacaNewsClient,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backfill [start, end] (inclusive dates). Does not touch the heartbeat."""
    now = now or datetime.now(UTC)
    if end < start:
        raise ValueError("sweep end must not precede start")
    validate_universe(config, now.date())
    store = NewsStore(config.data_root)
    index = VersionIndex(config.data_root)
    with exclusive_lock(config.data_root / LOCK_NAME):
        client = client_factory(config)
        try:
            window_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
            window_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
            fetched_list = list(client.fetch_news(config.symbols, window_start, window_end))
            check_clock(client.last_server_date)
            stored = _store_fetched(config, store, index, fetched_list)
            return {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "articles_fetched": len(fetched_list),
                "pairs_stored": stored,
            }
        finally:
            client.close()


def gaps(data_root: Path, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    """Report coverage: heartbeat age and per-day article counts."""
    now = now or datetime.now(UTC)
    heartbeat = read_heartbeat(data_root)
    last_poll_at = heartbeat.get("last_poll_at") if heartbeat else None
    poll_age_hours: float | None = None
    if last_poll_at:
        poll_age_hours = (now - datetime.fromisoformat(last_poll_at)).total_seconds() / 3600
    per_day: dict[str, int] = {}
    articles_dir = data_root / "articles"
    if articles_dir.is_dir():
        for jsonl in articles_dir.rglob("*.jsonl"):
            day = jsonl.stem  # YYYY-MM-DD
            with jsonl.open() as f:
                count = sum(1 for line in f if line.strip())
            per_day[day] = per_day.get(day, 0) + count
    days_list = [(now.date() - timedelta(days=i)).isoformat() for i in range(days)]
    missing = [d for d in days_list if per_day.get(d, 0) == 0]
    return {
        "last_poll_at": last_poll_at,
        "poll_age_hours": round(poll_age_hours, 2) if poll_age_hours is not None else None,
        "days": {d: per_day.get(d, 0) for d in days_list},
        "missing_days": missing,
    }
