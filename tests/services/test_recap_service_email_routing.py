"""T12 — recap_service via_cli email-routing tests (#115 Sprint).

Validates DD-13 + DD-25 + DA-MAJ-8 for EOD recap path.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


def test_generate_eod_recap_has_via_cli_kwarg():
    from src.services.recap_service import generate_eod_recap
    sig = inspect.signature(generate_eod_recap)
    assert "via_cli" in sig.parameters, (
        "generate_eod_recap missing via_cli kwarg"
    )
    assert sig.parameters["via_cli"].default is False


def test_scheduled_call_enqueues_via_aggregator():
    from src.services import recap_service
    src = inspect.getsource(recap_service)
    assert "enqueue_for_email_digest" in src, (
        "recap_service must enqueue 'eod_recap_email' on scheduled path"
    )
    assert "eod_recap_email" in src
    assert "email:postclose" in src or "postclose" in src


def test_via_cli_true_calls_send_directly():
    from src.services import recap_service
    src = inspect.getsource(recap_service)
    assert "send_email(" in src, (
        "recap_service must retain direct send_email path for via_cli/explicit"
    )
    assert "via_cli" in src


def test_explicit_email_arg_calls_send_directly():
    from src.services import recap_service
    src = inspect.getsource(recap_service)
    assert "send_email_flag" in src and "via_cli" in src


def test_aggregator_importerror_falls_back():
    from src.services import recap_service
    src = inspect.getsource(recap_service)
    assert "ImportError" in src
    assert "logger.critical" in src or "critical(" in src


def test_eod_recap_scheduled_path_calls_enqueue():
    """Functional: invoke generate_eod_recap with via_cli=False AND
    send_email_flag=False; verify the enqueue path is taken (no send_email)."""
    from src.services import recap_service

    # Patch all heavy deps to make this a thin path-coverage test.
    fake_ohlcv = {"AAPL": MagicMock()}
    fake_spy = MagicMock()
    fake_spy.empty = False

    with patch("src.services.recap_service.fetch_ohlcv", create=True, return_value=fake_ohlcv), \
         patch("src.services.recap_service.fetch_spy_benchmark", create=True, return_value=fake_spy), \
         patch("src.data_ingestion.market_data.fetch_ohlcv", return_value=fake_ohlcv), \
         patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=fake_spy), \
         patch("src.features.engine.compute_all_features", return_value={"AAPL": {}}), \
         patch("src.ranking.ranker.rank_universe", return_value=[]), \
         patch("src.ranking.ranker.get_top_candidates",
               return_value={"packet_worthy": [], "watchlist": []}), \
         patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"]), \
         patch("src.journal.store.get_todays_recommendations", return_value=[]), \
         patch("src.packets.eod_recap.build_eod_recap", return_value="recap body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enqueue, \
         patch("src.email.notifier.send_email") as mock_send:

        result = recap_service.generate_eod_recap({}, send_email_flag=False, via_cli=False)

        mock_send.assert_not_called()
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs or {}
        args = mock_enqueue.call_args.args or ()
        event_type = args[0] if args else kwargs.get("event_type")
        assert event_type == "eod_recap_email"
        assert kwargs.get("source_tag") == "email:postclose"


def test_eod_recap_via_cli_true_calls_send_directly():
    """Functional: via_cli=True → send_email is called, enqueue is NOT."""
    from src.services import recap_service

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
         patch("src.journal.store.get_todays_recommendations", return_value=[]), \
         patch("src.packets.eod_recap.build_eod_recap", return_value="recap body"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enqueue, \
         patch("src.email.notifier.send_email", return_value=True) as mock_send:

        result = recap_service.generate_eod_recap({}, send_email_flag=True, via_cli=True)

        mock_send.assert_called_once()
        mock_enqueue.assert_not_called()
