"""T12 — watchlist_service via_cli email-routing tests (#115 Sprint).

Validates DD-13 + DD-25 + DA-MAJ-8 for morning-watchlist path.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


def test_generate_morning_watchlist_has_via_cli_kwarg():
    from src.services.watchlist_service import generate_morning_watchlist
    sig = inspect.signature(generate_morning_watchlist)
    assert "via_cli" in sig.parameters
    assert sig.parameters["via_cli"].default is False


def test_scheduled_call_enqueues_via_aggregator():
    from src.services import watchlist_service
    src = inspect.getsource(watchlist_service)
    assert "enqueue_for_email_digest" in src
    assert "morning_watchlist" in src
    assert "email:preopen" in src or "preopen" in src


def test_via_cli_true_calls_send_directly():
    from src.services import watchlist_service
    src = inspect.getsource(watchlist_service)
    assert "send_email(" in src
    assert "via_cli" in src


def test_explicit_email_arg_calls_send_directly():
    from src.services import watchlist_service
    src = inspect.getsource(watchlist_service)
    assert "send_email_flag" in src and "via_cli" in src


def test_aggregator_importerror_falls_back():
    from src.services import watchlist_service
    src = inspect.getsource(watchlist_service)
    assert "ImportError" in src
    assert "logger.critical" in src or "critical(" in src


def test_watchlist_scheduled_path_calls_enqueue():
    """Functional: invoke generate_morning_watchlist with via_cli=False AND
    send_email_flag=False; verify enqueue path is taken with source_tag=email:preopen."""
    from src.services import watchlist_service

    fake_ohlcv = {"AAPL": MagicMock()}
    fake_spy = MagicMock()
    fake_spy.empty = False

    with patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=fake_ohlcv), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=fake_spy), \
         patch("src.features.engine.compute_all_features", return_value={"AAPL": {}}), \
         patch("src.ranking.ranker.rank_universe", return_value=[]), \
         patch("src.ranking.ranker.get_top_candidates",
               return_value={"packet_worthy": [], "watchlist": []}), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.universe.company_names.get_company_name", return_value="Apple"), \
         patch("src.llm.watchlist_writer.generate_watchlist_narrative",
               return_value="narrative"), \
         patch("src.packets.watchlist.build_morning_watchlist",
               return_value="watchlist body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enqueue, \
         patch("src.email.notifier.send_email") as mock_send:

        result = watchlist_service.generate_morning_watchlist(
            {}, send_email_flag=False, via_cli=False
        )

        mock_send.assert_not_called()
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs or {}
        args = mock_enqueue.call_args.args or ()
        event_type = args[0] if args else kwargs.get("event_type")
        assert event_type == "morning_watchlist"
        assert kwargs.get("source_tag") == "email:preopen"


def test_watchlist_via_cli_true_calls_send_directly():
    """via_cli=True → send_email called, enqueue NOT called."""
    from src.services import watchlist_service

    fake_ohlcv = {"AAPL": MagicMock()}
    fake_spy = MagicMock()
    fake_spy.empty = False

    with patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=fake_ohlcv), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=fake_spy), \
         patch("src.features.engine.compute_all_features", return_value={"AAPL": {}}), \
         patch("src.ranking.ranker.rank_universe", return_value=[]), \
         patch("src.ranking.ranker.get_top_candidates",
               return_value={"packet_worthy": [], "watchlist": []}), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.universe.company_names.get_company_name", return_value="Apple"), \
         patch("src.llm.watchlist_writer.generate_watchlist_narrative",
               return_value="narrative"), \
         patch("src.packets.watchlist.build_morning_watchlist",
               return_value="watchlist body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enqueue, \
         patch("src.email.notifier.send_email", return_value=True) as mock_send:

        result = watchlist_service.generate_morning_watchlist(
            {}, send_email_flag=True, via_cli=True
        )

        mock_send.assert_called_once()
        mock_enqueue.assert_not_called()
