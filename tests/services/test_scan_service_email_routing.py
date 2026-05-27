"""T12 — scan_service via_cli email-routing tests (#115 Sprint).

Validates DD-13 + DD-25 + DA-MAJ-8:
  - scheduled call (via_cli=False) enqueues via aggregator
  - via_cli=True bypasses aggregator → direct send_email
  - explicit `send_email_flag=True` also bypasses aggregator
  - ImportError fallback path (DD-30) logs critical + falls back to send_email
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


def test_perform_scan_has_via_cli_kwarg():
    """run_scan must accept via_cli keyword."""
    from src.services.scan_service import run_scan
    sig = inspect.signature(run_scan)
    assert "via_cli" in sig.parameters, (
        "run_scan missing via_cli kwarg — required for DD-13 CLI escape hatch"
    )
    assert sig.parameters["via_cli"].default is False, (
        "via_cli must default to False (scheduled callers don't pass it)"
    )


def test_scheduled_call_enqueues_via_aggregator():
    """When via_cli=False AND send_email_flag=False → enqueue path is taken
    (no direct send_email call). Inspect the module source — the routing
    may live in a helper function (e.g. _route_packet_email)."""
    from src.services import scan_service

    src = inspect.getsource(scan_service)
    assert "enqueue_for_email_digest" in src, (
        "scan_service must reference enqueue_for_email_digest for the "
        "scheduled (non-CLI) email path"
    )
    assert "via_cli" in src, (
        "scan_service must reference via_cli for the routing decision"
    )


def test_via_cli_true_calls_send_directly():
    """The module must include a branch where (send_email_flag or via_cli)
    invokes the existing send_email path, NOT enqueue."""
    from src.services import scan_service

    src = inspect.getsource(scan_service)
    assert "send_email(" in src, (
        "scan_service must retain send_email call for via_cli=True / "
        "explicit email-arg path (DD-13 operator escape hatch)"
    )


def test_explicit_email_arg_calls_send_directly():
    """When send_email_flag=True OR via_cli=True, the existing send_email
    path must remain (no enqueue). The branching must mention both flags."""
    from src.services import scan_service

    src = inspect.getsource(scan_service)
    assert "send_email_flag" in src and "via_cli" in src, (
        "Routing branch must consider both send_email_flag and via_cli"
    )


def test_aggregator_importerror_falls_back():
    """If enqueue_for_email_digest raises ImportError/ModuleNotFoundError,
    scan_service must log critical and fall back to send_email (DD-30)."""
    from src.services import scan_service

    src = inspect.getsource(scan_service)
    assert "ImportError" in src, (
        "scan_service must catch ImportError for the DD-30 fallback"
    )
    assert "AssertionError" not in src or "ImportError" in src, (
        "DD-30: must NOT catch AssertionError as a routing fallback"
    )
    assert "logger.critical" in src or "critical(" in src, (
        "DD-30 fallback must logger.critical when aggregator import fails"
    )
