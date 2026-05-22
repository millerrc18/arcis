"""On-tick handlers extracted from WatchLoop._run_sync_body.

Phase B of `sprint-asyncio-handler-refactor.md`: the 14 overnight-schedule
tasks that used to live in the `elif self.overnight and not self._is_market_open(now):`
branch inside the monolithic `_run_sync_body`. Each function takes
`(watch, now)`, checks its time-window + done-flag condition, and calls
`watch._safe_run(...)` if the window matches.

Module-level functions — not methods — so `watch.py` does not keep
accumulating more handler code. Each handler is idempotent by design
(the done-flag inside each condition ensures at-most-once-per-day
execution, matching the pre-refactor behavior byte-for-byte).

Called by: scheduler.watch.WatchLoop._register_default_handlers
Calls: scheduler.watch.WatchLoop._safe_run
Owns tables: none
Config keys: none (reads watch.overnight, watch.training_enabled)
Tests: tests/test_watch_handlers.py
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.notifications import safe_send

if TYPE_CHECKING:
    from src.scheduler.watch import WatchLoop

logger = logging.getLogger(__name__)


def _is_overnight_window(watch: "WatchLoop", now: datetime) -> bool:
    """True iff the overnight branch should consider any tasks this tick.

    Matches the pre-refactor outer guard
    `elif self.overnight and not self._is_market_open(now):`.
    """
    return watch.overnight and not watch._is_market_open(now)


# ── Overnight schedule — 14 handlers ────────────────────────────────────


def maybe_morning_training_stop(watch: "WatchLoop", now: datetime) -> None:
    """5:15 AM weekdays — stop the overnight GPU0 training subprocess."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 5 and now.minute >= 15
            and not watch._morning_training_stop_done):
        if watch._safe_run("morning training stop", watch._run_morning_training_stop):
            watch._morning_training_stop_done = True


def maybe_post_close_capture(watch: "WatchLoop", now: datetime) -> None:
    """5:30 PM weekdays — capture post-close snapshots before overnight work."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 17 and now.minute >= 30
            and not watch._post_close_done):
        if watch._safe_run("post-close capture", watch._run_post_close_capture):
            watch._post_close_done = True


def maybe_overnight_training_collection(watch: "WatchLoop", now: datetime) -> None:
    """6:00 PM weekdays — collect training examples before the evening training launch."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 18 and watch.training_enabled
            and not watch._overnight_training_collection_done):
        if watch._safe_run("overnight training collection",
                           watch._run_overnight_training_collection):
            watch._overnight_training_collection_done = True


def _in_evening_training_window(now: datetime) -> bool:
    """True iff now (tz-aware ET) is in the 18:30-04:00 ET launch window.

    The window wraps past midnight, so it matches >= 18:30 OR < 04:00.
    """
    after_1830 = now.hour > 18 or (now.hour == 18 and now.minute >= 30)
    before_0400 = now.hour < 4
    return after_1830 or before_0400


def maybe_evening_training_launch(watch: "WatchLoop", now: datetime) -> None:
    """18:30-04:00 ET, market closed — launch the overnight GPU0 training run."""
    if not _is_overnight_window(watch, now):
        return
    if _in_evening_training_window(now) and not watch._evening_training_done:
        if watch._safe_run("evening training launch", watch._run_evening_training_launch):
            watch._evening_training_done = True


def maybe_stress_test(watch: "WatchLoop", now: datetime) -> None:
    """7 PM weekdays — re-run stress test if the active model version changed."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 19 and not watch._stress_test_done
            and watch._model_version_changed()):
        if watch._safe_run("stress test (model change)", watch._run_stress_test):
            watch._stress_test_done = True


def maybe_data_collection(watch: "WatchLoop", now: datetime) -> None:
    """9:30 PM — comprehensive data collection (7 days/week; CPU/network only)."""
    if not _is_overnight_window(watch, now):
        return
    if (now.hour == 21 and now.minute >= 30
            and not watch._data_collection_done):
        if watch._safe_run("data collection", watch._run_data_collection):
            watch._data_collection_done = True


def maybe_news_ingestion(watch: "WatchLoop", now: datetime) -> None:
    """10 PM — full-universe news pull (7 days/week; Monday pre-market uses weekend news)."""
    if not _is_overnight_window(watch, now):
        return
    if now.hour == 22 and not watch._news_ingestion_done:
        if watch._safe_run("news ingestion", watch._run_news_ingestion):
            watch._news_ingestion_done = True


def maybe_enrichment_precache(watch: "WatchLoop", now: datetime) -> None:
    """11 PM — pre-fetch fundamentals, insider data, macro (7 days/week)."""
    if not _is_overnight_window(watch, now):
        return
    if now.hour == 23 and not watch._enrichment_precache_done:
        if watch._safe_run("enrichment precache", watch._run_enrichment_precache):
            watch._enrichment_precache_done = True


def maybe_1min_bar_collection(watch: "WatchLoop", now: datetime) -> None:
    """11:30 PM — 1-minute OHLCV bars for S&P 100 (Phase 6 intraday foundation)."""
    if not _is_overnight_window(watch, now):
        return
    if (now.hour == 23 and now.minute >= 30
            and not watch._1min_bar_collection_done):
        if watch._safe_run("1-minute bar collection",
                           watch._run_1min_bar_collection):
            watch._1min_bar_collection_done = True


def maybe_pre_market_refresh(watch: "WatchLoop", now: datetime) -> None:
    """6 AM weekdays — quick pre-market check; also fires the pre-market brief."""
    if not _is_overnight_window(watch, now):
        return
    if not (now.weekday() < 5 and now.hour == 6 and not watch._pre_market_done):
        return
    if watch._safe_run("pre-market refresh", watch._run_pre_market_refresh):
        watch._pre_market_done = True
        if not watch._premarket_brief_done:
            if watch._safe_run("pre-market brief", watch._send_premarket_brief):
                watch._premarket_brief_done = True


def maybe_premarket_rolling_features(watch: "WatchLoop", now: datetime) -> None:
    """6:02 AM weekdays — rolling features kicks off after the 6:00 refresh."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 6 and now.minute >= 2
            and not watch._premarket_features_done):
        if watch._safe_run("rolling features",
                           watch._run_premarket_rolling_features):
            watch._premarket_features_done = True


def maybe_premarket_training(watch: "WatchLoop", now: datetime) -> None:
    """7 AM weekdays — generate pre-market training data."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 7
            and not watch._premarket_training_done):
        if watch._safe_run("premarket training gen",
                           watch._run_premarket_training):
            watch._premarket_training_done = True


def maybe_premarket_news_scoring(watch: "WatchLoop", now: datetime) -> None:
    """8:02 AM weekdays — pre-market news relevance scoring."""
    if not _is_overnight_window(watch, now):
        return
    if (now.weekday() < 5 and now.hour == 8 and now.minute >= 2
            and not watch._premarket_news_done):
        if watch._safe_run("premarket news scoring",
                           watch._run_premarket_news_scoring):
            watch._premarket_news_done = True


def maybe_premarket_candidates(watch: "WatchLoop", now: datetime) -> None:
    """9:00-9:24 AM weekdays — build pre-market candidate list + complete-notify."""
    if not _is_overnight_window(watch, now):
        return
    if not (now.weekday() < 5 and now.hour == 9 and now.minute < 25
            and not watch._premarket_candidates_done):
        return
    if watch._safe_run("premarket candidates", watch._run_premarket_candidates):
        watch._premarket_candidates_done = True
        if (watch._premarket_features_done and watch._premarket_training_done
                and watch._premarket_news_done):
            _notify_premarket_complete(watch)


def _notify_premarket_complete(watch: "WatchLoop") -> None:
    """Telegram ping after the 4 pre-market tasks finish — best-effort, swallows errors."""
    safe_send(
        "premarket_complete",
        features_done=watch._premarket_features_done,
        training_gen=0,
        news_scored=0,
        candidates=0,
    )


# ── Market-hours / daytime pulses ──────────────────────────────────────


def maybe_stats_pulse(watch: "WatchLoop", now: datetime) -> None:
    """3× daily trading-stats pulse — pre-market (7:45), midday (12:00),
    post-close (16:05). Weekdays only. Each window has its own done-flag
    so the pulse fires at most once per window per day.

    Safe to skip quietly on rare edge cases (empty DB, no closed trades) —
    `notify_trading_stats_update` returns without sending in that case.
    """
    if now.weekday() >= 5:
        return
    schedule = [
        ("_stats_premarket_done", 7, 45, 8, 0, "PRE-MARKET"),
        ("_stats_midday_done", 12, 0, 12, 5, "MIDDAY"),
        ("_stats_postclose_done", 16, 5, 16, 10, "POST-CLOSE"),
    ]
    for flag, h_start, m_start, h_end, m_end, label in schedule:
        if getattr(watch, flag, True):
            continue  # already done today or flag missing
        fires = (
            (now.hour, now.minute) >= (h_start, m_start)
            and (now.hour, now.minute) < (h_end, m_end)
        )
        if not fires:
            continue
        if watch._safe_run(f"stats pulse ({label})",
                           lambda lbl=label: _send_stats_pulse(lbl)):
            setattr(watch, flag, True)
        return  # one pulse per tick


def _send_stats_pulse(label: str) -> None:
    """Compute stats + send via Telegram. Extracted so _safe_run wraps it."""
    from src.journal.stats import compute_all_window_stats
    from src.notifications.telegram import notify_trading_stats_update, is_telegram_enabled
    if not is_telegram_enabled():
        return
    stats = compute_all_window_stats()
    notify_trading_stats_update(stats, label=label)


# ── Canonical handler lists — consumed by WatchLoop._register_default_handlers ──

OVERNIGHT_HANDLERS = [
    maybe_morning_training_stop,
    maybe_post_close_capture,
    maybe_overnight_training_collection,
    maybe_evening_training_launch,
    maybe_stress_test,
    maybe_data_collection,
    maybe_news_ingestion,
    maybe_enrichment_precache,
    maybe_1min_bar_collection,
    maybe_pre_market_refresh,
    maybe_premarket_rolling_features,
    maybe_premarket_training,
    maybe_premarket_news_scoring,
    maybe_premarket_candidates,
]

def maybe_walkforward_reconciler(watch: "WatchLoop", now: datetime) -> None:
    """Hourly during market hours (11–15 ET, weekdays) — find and auto-fire orphan backtests."""
    if now.weekday() >= 5:
        return
    if not watch._is_market_open(now):
        return
    if now.hour not in (11, 12, 13, 14, 15):
        return
    watch._safe_run(
        "walkforward reconciler",
        watch._run_walkforward_reconciler,
    )


def maybe_market_open_training_stop(watch: "WatchLoop", now: datetime) -> None:
    """>= 09:25 ET hard-ceiling safety net — stop training before market open.

    Daytime handler: fires regardless of overnight mode so a loop restarted
    after 09:20 (with the done-flag freshly False) still trips the ceiling and
    stops any GPU0 training that overran the morning stop.
    """
    if (now.hour, now.minute) >= (9, 25) and not watch._market_open_stop_done:
        if watch._safe_run("market-open training stop",
                           watch._run_market_open_training_stop):
            watch._market_open_stop_done = True


DAYTIME_HANDLERS = [
    maybe_stats_pulse,
    maybe_walkforward_reconciler,
    maybe_market_open_training_stop,
]

ALL_HANDLERS = OVERNIGHT_HANDLERS + DAYTIME_HANDLERS
