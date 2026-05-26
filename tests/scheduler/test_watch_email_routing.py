"""Tests for #115 T11 — watch.py email routing (EOD recap + action packets).

DD-20 revised: in shadow / time_aligned mode, the original send_email
(operator inbox) must continue to fire alongside the queue enqueue. Only
in mode='off' does the queue become the sole consumer.

DD-30 revised: aggregator import failure surfaces as ImportError. The
fallback is FIREHOSE MODE — log CRITICAL, best-effort Telegram alert,
then revert to immediate send_email so operator visibility is never lost.

This file targets:
- WatchLoop._run_eod_recap (~watch.py:1480 — pre-edit)
- WatchLoop._run_scan action-packet emit (~watch.py:921 — pre-edit)
"""
from __future__ import annotations

import builtins
import logging
from collections import deque
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _shadow_config(mode: str = "off") -> dict:
    return {"email": {"dual_write_hold_over": {"mode": mode}}}


def _make_watch_loop(email_mode: str = "full_stream"):
    """Construct a bare WatchLoop sufficient for the email-routing code paths."""
    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl.email_mode = email_mode
    wl.config = {}
    wl._daily_packets = []
    wl._last_reconcile_time = None
    wl._scan_number = 0
    wl._trades_managed_today = 0
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._last_scan_time = None
    return wl


# ── (f) EOD recap routes to postclose ───────────────────────────────────


def test_eod_recap_routes_to_postclose():
    """_run_eod_recap with email_mode != 'digest' → enqueue postclose, no send_email."""
    spy_df = pd.DataFrame({"close": [400.0, 401.0]})

    wl = _make_watch_loop(email_mode="full_stream")

    with patch(
        "src.scheduler.watch.load_config",
        return_value=_shadow_config("off"),
    ), patch(
        "src.data_ingestion.market_data.fetch_ohlcv", return_value={}
    ), patch(
        "src.data_ingestion.market_data.fetch_spy_benchmark", return_value=spy_df
    ), patch(
        "src.features.engine.compute_all_features", return_value={}
    ), patch(
        "src.ranking.ranker.rank_universe", return_value={}
    ), patch(
        "src.ranking.ranker.get_top_candidates",
        return_value={"packet_worthy": [], "watchlist": []},
    ), patch(
        "src.universe.sp100.get_sp100_universe", return_value=[]
    ), patch(
        "src.journal.store.get_todays_recommendations", return_value=[]
    ), patch(
        "src.packets.eod_recap.build_eod_recap", return_value="recap body"
    ), patch(
        "src.notifications.email_digest.enqueue_for_email_digest"
    ) as mock_enq, patch(
        "src.email.notifier.send_email"
    ) as mock_send:
        wl._run_eod_recap()

    assert mock_enq.call_count == 1
    call = mock_enq.call_args
    assert call.args[0] == "eod_recap_email"
    assert call.kwargs.get("severity") == "normal"
    assert call.kwargs.get("source_tag") == "email:postclose"
    payload = call.kwargs.get("payload") or {}
    assert "subject" in payload
    assert "body" in payload
    assert "date_str" in payload
    # mode='off' → no immediate send_email
    assert mock_send.call_count == 0


# ── (g) Action-packet routes to postclose ───────────────────────────────


def test_action_packet_routes_to_postclose():
    """full_stream action-packet emit → enqueue postclose, no send_email."""
    from src.scheduler.universe_scanner import ScanResult

    wl = _make_watch_loop(email_mode="full_stream")

    result = ScanResult(
        aborted=False,
        universe_count=1,
        features_count=1,
        packet_worthy_count=1,
        packets_rendered=[{"ticker": "AAPL", "rendered": "rendered body"}],
    )

    with patch(
        "src.scheduler.watch.load_config",
        return_value=_shadow_config("off"),
    ), patch(
        "src.scheduler.universe_scanner.run_universe_scan", return_value=result
    ), patch(
        "src.notifications.email_digest.enqueue_for_email_digest"
    ) as mock_enq, patch(
        "src.email.notifier.send_email"
    ) as mock_send, patch.object(
        wl, "_refresh_live_prices", create=True
    ), patch.object(
        wl, "_record_scan_metrics", create=True
    ), patch.object(
        wl, "_dispatch_action_packet_telegram", create=True
    ):
        # Stub out the post-emit code paths that the scan body executes after the
        # email branch — reconciliation + Telegram + journaling are out of scope here.
        with patch(
            "src.shadow_trading.reconcile_dispatch.reconcile_all_paper_trades",
            return_value={"swing": {"orphaned": [], "stale": [], "discrepancies": [], "backfilled": 0, "local_count": 0, "alpaca_count": 0}},
        ):
            try:
                wl._run_scan()
            except Exception:
                # Downstream side-effects (council, sync, etc.) are not in scope —
                # we only care that the email-routing branch executed before any
                # failure. Verified below by the mock assertions.
                pass

    # We must see at least one enqueue for the action_packet event_type.
    matching = [
        c for c in mock_enq.call_args_list
        if c.args and c.args[0] == "action_packet"
    ]
    assert matching, (
        f"action_packet enqueue not called; saw enqueue calls: {mock_enq.call_args_list}"
    )
    call = matching[0]
    assert call.kwargs.get("source_tag") == "email:postclose"
    assert call.kwargs.get("severity") == "normal"
    payload = call.kwargs.get("payload") or {}
    assert payload.get("ticker") == "AAPL"
    assert payload.get("rendered") == "rendered body"
    assert "subject" in payload
    # send_email MUST NOT fire in mode='off'.
    assert mock_send.call_count == 0


# ── (h) DD-30 REVISED — ImportError fallback (firehose mode) ─────────────


def test_aggregator_importerror_falls_back(caplog):
    """ImportError on email_digest import → CRITICAL log + safe_send + send_email."""
    spy_df = pd.DataFrame({"close": [400.0, 401.0]})

    real_import = builtins.__import__

    def _raise_on_email_digest(name, *args, **kwargs):
        if name == "src.notifications.email_digest" or name.endswith("email_digest"):
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    wl = _make_watch_loop(email_mode="full_stream")

    with caplog.at_level(logging.CRITICAL, logger="src.scheduler.watch"), patch(
        "src.scheduler.watch.load_config", return_value=_shadow_config("off")
    ), patch(
        "src.data_ingestion.market_data.fetch_ohlcv", return_value={}
    ), patch(
        "src.data_ingestion.market_data.fetch_spy_benchmark", return_value=spy_df
    ), patch(
        "src.features.engine.compute_all_features", return_value={}
    ), patch(
        "src.ranking.ranker.rank_universe", return_value={}
    ), patch(
        "src.ranking.ranker.get_top_candidates",
        return_value={"packet_worthy": [], "watchlist": []},
    ), patch(
        "src.universe.sp100.get_sp100_universe", return_value=[]
    ), patch(
        "src.journal.store.get_todays_recommendations", return_value=[]
    ), patch(
        "src.packets.eod_recap.build_eod_recap", return_value="recap body"
    ), patch(
        "src.scheduler.watch.safe_send"
    ) as mock_tg, patch(
        "src.email.notifier.send_email"
    ) as mock_send, patch.object(
        builtins, "__import__", side_effect=_raise_on_email_digest
    ):
        wl._run_eod_recap()

    critical_msgs = [r.message for r in caplog.records if r.levelno == logging.CRITICAL]
    assert any("FIREHOSE" in m.upper() for m in critical_msgs), (
        f"Expected FIREHOSE FALLBACK CRITICAL log; got: {critical_msgs}"
    )
    assert mock_tg.call_count >= 1, "safe_send Telegram fallback alert must be attempted"
    assert mock_send.call_count == 1, "send_email fallback must fire so operator still sees the alert"
