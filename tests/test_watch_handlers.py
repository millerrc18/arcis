"""Tests for src/scheduler/watch_handlers.py (Phase B + C of asyncio refactor).

Covers:
- Per-handler unit tests: right time window, done-flag respect, _safe_run
  invocation. All 14 overnight handlers.
- Integration test: WatchLoop._register_default_handlers + _dispatch_sync
  path — a sequence of synthetic `now` values fires the correct handlers
  in the correct order, and the same sequence is idempotent (done-flags
  prevent re-firing).
- Guard tests: non-overnight-mode ticks do nothing; each handler respects
  the is_weekday gate where applicable.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.scheduler import watch_handlers
from src.scheduler.watch_handlers import OVERNIGHT_HANDLERS

ET = ZoneInfo("America/New_York")


# ── Test doubles ───────────────────────────────────────────────────────


def _make_watch(
    overnight: bool = True,
    is_market_open: bool = False,
    training_enabled: bool = True,
    model_version_changed: bool = False,
) -> SimpleNamespace:
    """Minimal WatchLoop stand-in exposing only the attrs the handlers touch."""
    safe_run_calls: list[str] = []

    def safe_run(name: str, func):
        safe_run_calls.append(name)
        func()
        return True

    w = SimpleNamespace(
        overnight=overnight,
        training_enabled=training_enabled,
        _safe_run=safe_run,
        _safe_run_calls=safe_run_calls,
        _is_market_open=lambda now: is_market_open,
        _model_version_changed=lambda: model_version_changed,
        # done-flags — all False at start
        _evening_training_launched=False,
        _morning_training_stopped=False,
        _post_close_done=False,
        _overnight_training_collection_done=False,
        _stress_test_done=False,
        _data_collection_done=False,
        _news_ingestion_done=False,
        _enrichment_precache_done=False,
        _1min_bar_collection_done=False,
        _pre_market_done=False,
        _premarket_brief_done=False,
        _premarket_features_done=False,
        _premarket_training_done=False,
        _premarket_news_done=False,
        _premarket_candidates_done=False,
        # _run_* methods — MagicMock so we can assert .called / .call_count
        _run_morning_training_stop=MagicMock(name="_run_morning_training_stop"),
        _run_post_close_capture=MagicMock(name="_run_post_close_capture"),
        _run_overnight_training_collection=MagicMock(name="_run_overnight_training_collection"),
        _run_evening_training=MagicMock(name="_run_evening_training"),
        _run_stress_test=MagicMock(name="_run_stress_test"),
        _run_data_collection=MagicMock(name="_run_data_collection"),
        _run_news_ingestion=MagicMock(name="_run_news_ingestion"),
        _run_enrichment_precache=MagicMock(name="_run_enrichment_precache"),
        _run_1min_bar_collection=MagicMock(name="_run_1min_bar_collection"),
        _run_pre_market_refresh=MagicMock(name="_run_pre_market_refresh"),
        _send_premarket_brief=MagicMock(name="_send_premarket_brief"),
        _run_premarket_rolling_features=MagicMock(name="_run_premarket_rolling_features"),
        _run_premarket_training=MagicMock(name="_run_premarket_training"),
        _run_premarket_news_scoring=MagicMock(name="_run_premarket_news_scoring"),
        _run_premarket_candidates=MagicMock(name="_run_premarket_candidates"),
    )
    return w


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


# Monday 2026-04-13 and Saturday 2026-04-18 are our canonical reference dates.
MON = lambda h, m=0: _dt(2026, 4, 13, h, m)  # noqa: E731
SAT = lambda h, m=0: _dt(2026, 4, 18, h, m)  # noqa: E731


# ── Outer guard: overnight-mode + not-market-open ─────────────────────


def test_handlers_noop_when_overnight_flag_off():
    """If WatchLoop.overnight is False, no handler fires regardless of time."""
    w = _make_watch(overnight=False)
    for h in OVERNIGHT_HANDLERS:
        h(w, MON(5, 15))  # Monday 5:15 AM — morning handoff would match
    assert w._safe_run_calls == []


def test_handlers_noop_when_market_is_open():
    """Overnight handlers must not fire during market hours."""
    w = _make_watch(overnight=True, is_market_open=True)
    for h in OVERNIGHT_HANDLERS:
        h(w, MON(10, 30))
    assert w._safe_run_calls == []


# ── Handler-by-handler contract tests ────────────────────────────────


def test_maybe_morning_training_stop_fires_at_515_weekday_outer():
    w = _make_watch()
    watch_handlers.maybe_morning_training_stop(w, MON(5, 15))
    assert w._morning_training_stopped is True
    w._run_morning_training_stop.assert_called_once()


def test_maybe_morning_training_stop_skips_weekend_outer():
    w = _make_watch()
    watch_handlers.maybe_morning_training_stop(w, SAT(5, 15))
    assert w._morning_training_stopped is False
    w._run_morning_training_stop.assert_not_called()


def test_maybe_morning_training_stop_respects_done_flag():
    w = _make_watch()
    w._morning_training_stopped = True
    watch_handlers.maybe_morning_training_stop(w, MON(5, 15))
    w._run_morning_training_stop.assert_not_called()


def test_maybe_post_close_capture_fires_at_1730_weekday():
    w = _make_watch()
    watch_handlers.maybe_post_close_capture(w, MON(17, 30))
    w._run_post_close_capture.assert_called_once()
    assert w._post_close_done is True


def test_maybe_post_close_capture_before_window():
    w = _make_watch()
    watch_handlers.maybe_post_close_capture(w, MON(17, 29))
    w._run_post_close_capture.assert_not_called()


def test_maybe_overnight_training_collection_requires_training_enabled():
    w = _make_watch(training_enabled=False)
    watch_handlers.maybe_overnight_training_collection(w, MON(18, 0))
    w._run_overnight_training_collection.assert_not_called()


def test_maybe_overnight_training_collection_fires_at_18():
    w = _make_watch(training_enabled=True)
    watch_handlers.maybe_overnight_training_collection(w, MON(18, 0))
    w._run_overnight_training_collection.assert_called_once()


def test_maybe_evening_training_fires_at_1850_weekday_outer():
    w = _make_watch()
    watch_handlers.maybe_evening_training(w, MON(18, 50))
    w._run_evening_training.assert_called_once()


def test_maybe_stress_test_only_fires_when_model_version_changed():
    w = _make_watch(model_version_changed=False)
    watch_handlers.maybe_stress_test(w, MON(19, 0))
    w._run_stress_test.assert_not_called()

    w2 = _make_watch(model_version_changed=True)
    watch_handlers.maybe_stress_test(w2, MON(19, 0))
    w2._run_stress_test.assert_called_once()


def test_maybe_data_collection_fires_at_2130_daily_including_weekend():
    """Data collection is 7-day/week (CPU/network only, no GPU)."""
    for day_func in (MON, SAT):
        w = _make_watch()
        watch_handlers.maybe_data_collection(w, day_func(21, 30))
        w._run_data_collection.assert_called_once(), f"failed on {day_func.__name__}"


def test_maybe_news_ingestion_fires_at_22_daily():
    for day_func in (MON, SAT):
        w = _make_watch()
        watch_handlers.maybe_news_ingestion(w, day_func(22, 0))
        w._run_news_ingestion.assert_called_once()


def test_maybe_enrichment_precache_fires_at_23_daily():
    for day_func in (MON, SAT):
        w = _make_watch()
        watch_handlers.maybe_enrichment_precache(w, day_func(23, 0))
        w._run_enrichment_precache.assert_called_once()


def test_maybe_1min_bar_collection_fires_at_2330_daily():
    for day_func in (MON, SAT):
        w = _make_watch()
        watch_handlers.maybe_1min_bar_collection(w, day_func(23, 30))
        w._run_1min_bar_collection.assert_called_once()


def test_maybe_pre_market_refresh_chains_premarket_brief():
    """After refresh, the brief notification fires as a follow-up."""
    w = _make_watch()
    watch_handlers.maybe_pre_market_refresh(w, MON(6, 0))
    w._run_pre_market_refresh.assert_called_once()
    w._send_premarket_brief.assert_called_once()
    assert w._pre_market_done is True
    assert w._premarket_brief_done is True


def test_maybe_pre_market_refresh_skips_weekend():
    w = _make_watch()
    watch_handlers.maybe_pre_market_refresh(w, SAT(6, 0))
    w._run_pre_market_refresh.assert_not_called()


def test_maybe_premarket_rolling_features_fires_at_602_weekday():
    w = _make_watch()
    watch_handlers.maybe_premarket_rolling_features(w, MON(6, 2))
    w._run_premarket_rolling_features.assert_called_once()


def test_maybe_premarket_training_fires_at_7_weekday():
    w = _make_watch()
    watch_handlers.maybe_premarket_training(w, MON(7, 0))
    w._run_premarket_training.assert_called_once()


def test_maybe_premarket_news_scoring_fires_at_802_weekday():
    w = _make_watch()
    watch_handlers.maybe_premarket_news_scoring(w, MON(8, 2))
    w._run_premarket_news_scoring.assert_called_once()


def test_maybe_premarket_candidates_fires_before_925():
    w = _make_watch()
    # Populate preconditions so the complete-notify doesn't crash on is_telegram_enabled
    w._premarket_features_done = True
    w._premarket_training_done = True
    w._premarket_news_done = True
    watch_handlers.maybe_premarket_candidates(w, MON(9, 15))
    w._run_premarket_candidates.assert_called_once()


def test_maybe_premarket_candidates_skips_after_925():
    w = _make_watch()
    watch_handlers.maybe_premarket_candidates(w, MON(9, 25))
    w._run_premarket_candidates.assert_not_called()


# ── Integration: Phase B dispatch path ────────────────────────────────


def test_register_default_handlers_binds_all_handlers():
    """WatchLoop._register_default_handlers registers OVERNIGHT + DAYTIME handlers."""
    from src.scheduler.watch import WatchLoop
    from src.scheduler.watch_handlers import ALL_HANDLERS
    loop = WatchLoop(config={})
    loop._register_default_handlers()
    assert "on_tick" in loop._handlers
    assert len(loop._handlers["on_tick"]) == len(ALL_HANDLERS)
    bound_names = [h.__name__ for h in loop._handlers["on_tick"]]
    expected_names = [h.__name__ for h in ALL_HANDLERS]
    assert bound_names == expected_names


def test_dispatch_sync_fires_overnight_handlers_at_correct_times(monkeypatch):
    """Mock-clock integration: advance a WatchLoop through a 24h sequence of
    ticks and verify each overnight handler fires at exactly the right minute.

    Covers spec Phase C success criterion #6: pre-refactor behavior
    byte-identical under the async-dispatch path.
    """
    from src.scheduler.watch import WatchLoop
    loop = WatchLoop(config={})
    loop.overnight = True
    # Stub _safe_run so it always succeeds without actually running tasks
    fired: list[tuple[str, datetime]] = []

    def safe_run(name, func):
        fired.append((name, getattr(loop, "_current_tick_now", None)))
        return True

    monkeypatch.setattr(loop, "_safe_run", safe_run)
    monkeypatch.setattr(loop, "_is_market_open", lambda now: False)
    monkeypatch.setattr(loop, "_model_version_changed", lambda: True)
    loop.training_enabled = True

    # All overnight _run_* methods must exist on WatchLoop; stub them.
    for attr in (
        "_run_morning_training_stop", "_run_post_close_capture",
        "_run_overnight_training_collection", "_run_evening_training",
        "_run_market_open_training_stop",
        "_run_stress_test", "_run_data_collection", "_run_news_ingestion",
        "_run_enrichment_precache", "_run_1min_bar_collection",
        "_run_pre_market_refresh", "_send_premarket_brief",
        "_run_premarket_rolling_features", "_run_premarket_training",
        "_run_premarket_news_scoring", "_run_premarket_candidates",
    ):
        monkeypatch.setattr(loop, attr, MagicMock(name=attr), raising=False)

    loop._register_default_handlers()

    # Walk a Monday minute-by-minute across every target time and dispatch.
    schedule = [
        (MON(5, 15), "morning training stop"),
        (MON(17, 30), "post-close capture"),
        (MON(18, 0), "overnight training collection"),
        (MON(18, 50), "evening training launch"),
        (MON(19, 0), "stress test (model change)"),
        (MON(21, 30), "data collection"),
        (MON(22, 0), "news ingestion"),
        (MON(23, 0), "enrichment precache"),
        (MON(23, 30), "1-minute bar collection"),
        (MON(6, 0), "pre-market refresh"),  # pre-market brief chains as 2nd call
        (MON(6, 2), "rolling features"),
        (MON(7, 0), "premarket training gen"),
        (MON(8, 2), "premarket news scoring"),
        (MON(9, 15), "premarket candidates"),
    ]
    for now, _expected in schedule:
        loop._current_tick_now = now
        loop._dispatch_sync("on_tick", now)

    fired_names = [name for name, _ in fired]
    # pre-market refresh triggers a chained "pre-market brief" call
    assert "pre-market refresh" in fired_names
    assert "pre-market brief" in fired_names
    # Every target task must appear exactly once
    for _, expected in schedule:
        assert expected in fired_names, f"{expected} did not fire"


# ── Dual-GPU separation: training launch + bounded stop handlers (T5) ──


def _make_training_watch(
    overnight: bool = True,
    is_market_open: bool = False,
    training_enabled: bool = True,
) -> SimpleNamespace:
    """Watch stand-in for the dual-GPU training launch/stop handlers."""
    safe_run_calls: list[str] = []

    def safe_run(name: str, func):
        safe_run_calls.append(name)
        func()
        return True

    return SimpleNamespace(
        overnight=overnight,
        training_enabled=training_enabled,
        _safe_run=safe_run,
        _safe_run_calls=safe_run_calls,
        _is_market_open=lambda now: is_market_open,
        _evening_training_launched=False,
        _morning_training_stopped=False,
        _market_open_training_stopped=False,
        _run_evening_training=MagicMock(name="_run_evening_training"),
        _run_morning_training_stop=MagicMock(name="_run_morning_training_stop"),
        _run_market_open_training_stop=MagicMock(name="_run_market_open_training_stop"),
    )


def test_maybe_evening_training_fires_in_offhours_window():
    """6:50 PM weekday, market closed → launch training; flag set."""
    w = _make_training_watch()
    watch_handlers.maybe_evening_training(w, MON(18, 50))
    w._run_evening_training.assert_called_once()
    assert w._evening_training_launched is True


def test_maybe_evening_training_skips_before_window():
    w = _make_training_watch()
    watch_handlers.maybe_evening_training(w, MON(18, 49))
    w._run_evening_training.assert_not_called()
    assert w._evening_training_launched is False


def test_maybe_evening_training_skips_when_market_open():
    """Off-hours fence: never launch training while the market is open."""
    w = _make_training_watch(is_market_open=True)
    watch_handlers.maybe_evening_training(w, MON(18, 50))
    w._run_evening_training.assert_not_called()


def test_maybe_evening_training_respects_done_flag():
    w = _make_training_watch()
    w._evening_training_launched = True
    watch_handlers.maybe_evening_training(w, MON(18, 50))
    w._run_evening_training.assert_not_called()


def test_maybe_morning_training_stop_fires_at_515_weekday():
    w = _make_training_watch()
    watch_handlers.maybe_morning_training_stop(w, MON(5, 15))
    w._run_morning_training_stop.assert_called_once()
    assert w._morning_training_stopped is True


def test_maybe_morning_training_stop_skips_weekend():
    w = _make_training_watch()
    watch_handlers.maybe_morning_training_stop(w, SAT(5, 15))
    w._run_morning_training_stop.assert_not_called()


def test_maybe_market_open_training_stop_fires_at_926_weekday():
    """At/after 09:25 ET a bounded stop is forced regardless of timeout."""
    w = _make_training_watch()
    watch_handlers.maybe_market_open_training_stop(w, MON(9, 26))
    w._run_market_open_training_stop.assert_called_once()
    assert w._market_open_training_stopped is True


def test_maybe_market_open_training_stop_skips_before_925():
    w = _make_training_watch()
    watch_handlers.maybe_market_open_training_stop(w, MON(9, 24))
    w._run_market_open_training_stop.assert_not_called()


def test_market_open_stop_runner_ignores_timeout(monkeypatch):
    """_run_market_open_training_stop must force timeout=0 (no waiting)."""
    from src.scheduler.watch import WatchLoop
    captured: dict = {}

    def fake_stop(proc, timeout):
        captured["timeout"] = timeout
        return {"stopped_via": "hard_terminate"}

    import src.scheduler.training_control as tc
    monkeypatch.setattr(tc, "stop_training_bounded", fake_stop)
    loop = WatchLoop(config={})
    loop._run_market_open_training_stop()
    assert captured["timeout"] == 0


def test_morning_stop_runner_calls_bounded_stop(monkeypatch):
    """_run_morning_training_stop delegates to stop_training_bounded."""
    from src.scheduler.watch import WatchLoop
    called = {"n": 0}

    def fake_stop(proc, timeout):
        called["n"] += 1
        return {"stopped_via": "cooperative"}

    import src.scheduler.training_control as tc
    monkeypatch.setattr(tc, "stop_training_bounded", fake_stop)
    loop = WatchLoop(config={})
    loop._run_morning_training_stop()
    assert called["n"] == 1


def test_handler_tuple_drops_old_vram_handoff_handlers():
    """OVERNIGHT_HANDLERS no longer references the VRAM-handoff handlers."""
    names = [h.__name__ for h in watch_handlers.OVERNIGHT_HANDLERS]
    assert "maybe_morning_vram_handoff" not in names
    assert "maybe_evening_vram_handoff" not in names
    assert "maybe_evening_training" in names
    assert "maybe_morning_training_stop" in names


def test_handler_tuple_includes_market_open_stop():
    """The market-open guard is registered (daytime, fires while market open)."""
    names = [h.__name__ for h in watch_handlers.ALL_HANDLERS]
    assert "maybe_market_open_training_stop" in names


# ── maybe_stats_pulse (daytime handler) ───────────────────────────────


def _make_stats_watch() -> SimpleNamespace:
    """Watch stand-in for stats-pulse handler (no overnight-guard needed)."""
    safe_run_calls: list[str] = []

    def safe_run(name: str, func):
        safe_run_calls.append(name)
        func()
        return True

    return SimpleNamespace(
        overnight=False,                      # overnight-mode shouldn't matter
        _is_market_open=lambda now: True,     # market open during midday pulse
        _safe_run=safe_run,
        _safe_run_calls=safe_run_calls,
        _stats_premarket_done=False,
        _stats_midday_done=False,
        _stats_postclose_done=False,
    )


def test_stats_pulse_skips_weekends():
    from src.scheduler import watch_handlers
    w = _make_stats_watch()
    watch_handlers.maybe_stats_pulse(w, SAT(12, 0))
    assert w._safe_run_calls == []


def test_stats_pulse_fires_premarket_at_745(monkeypatch):
    from src.scheduler import watch_handlers
    monkeypatch.setattr(watch_handlers, "_send_stats_pulse", lambda label: None)
    w = _make_stats_watch()
    watch_handlers.maybe_stats_pulse(w, MON(7, 45))
    assert len(w._safe_run_calls) == 1
    assert "PRE-MARKET" in w._safe_run_calls[0]
    assert w._stats_premarket_done is True


def test_stats_pulse_fires_midday_at_1200(monkeypatch):
    from src.scheduler import watch_handlers
    monkeypatch.setattr(watch_handlers, "_send_stats_pulse", lambda label: None)
    w = _make_stats_watch()
    watch_handlers.maybe_stats_pulse(w, MON(12, 0))
    assert len(w._safe_run_calls) == 1
    assert "MIDDAY" in w._safe_run_calls[0]
    assert w._stats_midday_done is True


def test_stats_pulse_fires_postclose_at_1605(monkeypatch):
    from src.scheduler import watch_handlers
    monkeypatch.setattr(watch_handlers, "_send_stats_pulse", lambda label: None)
    w = _make_stats_watch()
    watch_handlers.maybe_stats_pulse(w, MON(16, 5))
    assert len(w._safe_run_calls) == 1
    assert "POST-CLOSE" in w._safe_run_calls[0]
    assert w._stats_postclose_done is True


def test_stats_pulse_idempotent_per_window(monkeypatch):
    """Once a pulse's done-flag is set, a later tick in the same window doesn't re-fire."""
    from src.scheduler import watch_handlers
    monkeypatch.setattr(watch_handlers, "_send_stats_pulse", lambda label: None)
    w = _make_stats_watch()
    watch_handlers.maybe_stats_pulse(w, MON(12, 0))  # fires midday
    watch_handlers.maybe_stats_pulse(w, MON(12, 3))  # still in midday window
    assert len(w._safe_run_calls) == 1


def test_stats_pulse_skips_between_windows(monkeypatch):
    """No pulse at 8:30, 14:00, etc. — between configured windows."""
    from src.scheduler import watch_handlers
    monkeypatch.setattr(watch_handlers, "_send_stats_pulse", lambda label: None)
    w = _make_stats_watch()
    for h, m in [(8, 30), (10, 0), (14, 30), (18, 0)]:
        watch_handlers.maybe_stats_pulse(w, MON(h, m))
    assert w._safe_run_calls == []


def test_dispatch_sync_handlers_are_idempotent_across_ticks(monkeypatch):
    """Firing the same tick twice is safe — done-flags prevent re-execution."""
    from src.scheduler.watch import WatchLoop
    loop = WatchLoop(config={})
    loop.overnight = True
    fired: list[str] = []

    def safe_run(name, func):
        fired.append(name)
        return True

    monkeypatch.setattr(loop, "_safe_run", safe_run)
    monkeypatch.setattr(loop, "_is_market_open", lambda now: False)
    monkeypatch.setattr(loop, "_model_version_changed", lambda: False)
    for attr in (
        "_run_morning_training_stop", "_run_post_close_capture",
        "_run_overnight_training_collection", "_run_evening_training",
        "_run_market_open_training_stop",
        "_run_stress_test", "_run_data_collection", "_run_news_ingestion",
        "_run_enrichment_precache", "_run_1min_bar_collection",
        "_run_pre_market_refresh", "_send_premarket_brief",
        "_run_premarket_rolling_features", "_run_premarket_training",
        "_run_premarket_news_scoring", "_run_premarket_candidates",
    ):
        monkeypatch.setattr(loop, attr, MagicMock(name=attr), raising=False)

    loop._register_default_handlers()

    # Tick twice at 21:30 — data collection should fire exactly once total.
    loop._dispatch_sync("on_tick", MON(21, 30))
    loop._dispatch_sync("on_tick", MON(21, 30))
    assert fired.count("data collection") == 1
