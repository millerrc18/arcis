"""T8: poll/sweep/gaps, the OS lock, clock checks, and heartbeat."""
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import formatdate
from pathlib import Path

import pytest

from arcis.recorder.client import Article, FetchedArticle
from arcis.recorder.config import Config
from arcis.recorder.errors import ClockError, LockError, UniverseError
from arcis.recorder.runner import (
    check_clock,
    exclusive_lock,
    gaps,
    poll,
    read_heartbeat,
    sweep,
    write_heartbeat,
)
from arcis.recorder.universe import build_universe


def make_config(tmp_path: Path, symbols=("AAPL", "MSFT")) -> Config:
    return Config(
        data_root=tmp_path / "data",
        alpaca_base_url="https://data.alpaca.markets",
        alpaca_api_key="k",
        alpaca_api_secret="s",
        universe_name="sp500",
        universe_source="test",
        symbols=list(symbols),
        rate_limit={"max_requests_per_minute": 200, "max_requests_per_day": 50000},
        retry={"max_attempts": 2, "base_delay_seconds": 0.01, "max_delay_seconds": 0.05},
    )


def write_snapshot(tmp_path: Path, config: Config, day: date) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "sp500.csv").write_text("symbol\n" + "".join(s + "\n" for s in config.symbols))
    build_universe(config, day, config_dir)


def fetched(article_id: int, created_at: str, symbols: list[str]) -> FetchedArticle:
    raw = {
        "id": article_id,
        "headline": "h",
        "summary": "s",
        "content": None,
        "author": "a",
        "created_at": created_at,
        "updated_at": created_at,
        "url": "https://example.com",
        "source": "TestWire",
        "symbols": symbols,
        "images": [],
    }
    return FetchedArticle(raw=raw, article=Article(**raw))


class FakeClient:
    """Test double for AlpacaNewsClient."""

    def __init__(self, articles: list[FetchedArticle], server_date: str | None = "now"):
        self._articles = articles
        if server_date == "now":
            self.last_server_date: str | None = formatdate(timeval=None, usegmt=True)
        else:
            self.last_server_date = server_date
        self.closed = False

    def fetch_news(self, symbols, start, end, max_pages=50):
        return iter(self._articles)

    def close(self):
        self.closed = True


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


# --- lock ---


def test_exclusive_lock_refuses_second_holder(tmp_path):
    lock = tmp_path / "recorder.lock"
    with exclusive_lock(lock), pytest.raises(LockError), exclusive_lock(lock):
        pass


def test_exclusive_lock_released_after_exit(tmp_path):
    lock = tmp_path / "recorder.lock"
    with exclusive_lock(lock):
        pass
    with exclusive_lock(lock):
        pass


# --- clock ---


def test_check_clock_ok_with_fresh_date():
    check_clock(formatdate(timeval=None, usegmt=True))


def test_check_clock_rejects_stale_date():
    stale = formatdate(timeval=(datetime.now(UTC) - timedelta(minutes=10)).timestamp(), usegmt=True)
    with pytest.raises(ClockError, match="skew"):
        check_clock(stale)


def test_check_clock_rejects_missing_date():
    with pytest.raises(ClockError):
        check_clock(None)


# --- poll ---


def test_poll_stores_under_each_tagged_symbol(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    articles = [fetched(1, "2026-10-02T10:00:00Z", ["AAPL", "MSFT"])]
    summary = poll(config, client_factory=lambda c: FakeClient(articles), now=NOW)
    assert summary["pairs_stored"] == 2
    for symbol in ("AAPL", "MSFT"):
        path = tmp_path / "data" / "articles" / symbol / "2026-10-02.jsonl"
        assert path.is_file()
        assert json.loads(path.read_text().splitlines()[0])["id"] == 1


def test_poll_skips_symbols_outside_universe(tmp_path):
    config = make_config(tmp_path, symbols=("AAPL",))
    write_snapshot(tmp_path, config, NOW.date())
    articles = [fetched(1, "2026-10-02T10:00:00Z", ["AAPL", "GOOG"])]
    summary = poll(config, client_factory=lambda c: FakeClient(articles), now=NOW)
    assert summary["pairs_stored"] == 1
    assert not (tmp_path / "data" / "articles" / "GOOG").exists()


def test_poll_writes_heartbeat_atomically(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    poll(config, client_factory=lambda c: FakeClient([]), now=NOW)
    hb = read_heartbeat(tmp_path / "data")
    assert hb is not None
    assert hb["last_poll_at"] == NOW.isoformat()
    assert hb["symbols_configured"] == 2
    assert not (tmp_path / "data" / "heartbeat.tmp").exists()


def test_poll_refuses_on_clock_skew_and_leaves_heartbeat(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    stale = formatdate(timeval=(datetime.now(UTC) - timedelta(minutes=10)).timestamp(), usegmt=True)
    articles = [fetched(1, "2026-10-02T10:00:00Z", ["AAPL"])]
    with pytest.raises(ClockError):
        poll(config, client_factory=lambda c: FakeClient(articles, server_date=stale), now=NOW)
    # Nothing stored, no heartbeat written.
    assert not (tmp_path / "data" / "articles").exists()
    assert read_heartbeat(tmp_path / "data") is None


def test_poll_refuses_when_snapshot_missing(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(UniverseError):
        poll(config, client_factory=lambda c: FakeClient([]), now=NOW)


def test_poll_refuses_when_lock_held(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    with exclusive_lock(tmp_path / "data" / "recorder.lock"), pytest.raises(LockError):
        poll(config, client_factory=lambda c: FakeClient([]), now=NOW)


def test_poll_deduplicates_across_runs(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    articles = [fetched(1, "2026-10-02T10:00:00Z", ["AAPL"])]
    first = poll(config, client_factory=lambda c: FakeClient(articles), now=NOW)
    second = poll(config, client_factory=lambda c: FakeClient(articles), now=NOW)
    assert first["pairs_stored"] == 1
    assert second["pairs_stored"] == 0


# --- sweep ---


def test_sweep_backfills_range(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    articles = [fetched(1, "2026-09-28T10:00:00Z", ["AAPL"])]
    summary = sweep(
        config,
        date(2026, 9, 28),
        date(2026, 9, 29),
        client_factory=lambda c: FakeClient(articles),
        now=NOW,
    )
    assert summary["pairs_stored"] == 1
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-09-28.jsonl"
    assert path.is_file()
    # Sweep does not touch the heartbeat.
    assert read_heartbeat(tmp_path / "data") is None


def test_sweep_rejects_inverted_range(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(ValueError):
        sweep(config, date(2026, 9, 29), date(2026, 9, 28), now=NOW)


# --- gaps ---


def test_gaps_reports_missing_days_and_heartbeat_age(tmp_path):
    config = make_config(tmp_path)
    write_snapshot(tmp_path, config, NOW.date())
    articles = [fetched(1, "2026-10-02T10:00:00Z", ["AAPL"])]
    poll(config, client_factory=lambda c: FakeClient(articles), now=NOW)
    report = gaps(tmp_path / "data", days=3, now=NOW)
    assert report["last_poll_at"] == NOW.isoformat()
    assert report["poll_age_hours"] == 0
    assert report["days"]["2026-10-02"] == 1
    assert "2026-10-01" in report["missing_days"]


def test_gaps_with_no_heartbeat(tmp_path):
    report = gaps(tmp_path / "data", days=2, now=NOW)
    assert report["last_poll_at"] is None
    assert report["poll_age_hours"] is None
    assert len(report["missing_days"]) == 2


def test_write_heartbeat_is_atomic(tmp_path):
    write_heartbeat(tmp_path, {"a": 1})
    assert json.loads((tmp_path / "heartbeat.json").read_text()) == {"a": 1}
    assert not (tmp_path / "heartbeat.tmp").exists()
