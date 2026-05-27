"""T12 — via_cli propagation tests (DD-25 + DA-MAJ-8).

Verifies via_cli kwarg is wired through the public entry points of the three
services. Per DD-25 + DA-MAJ-8, when an operator runs the CLI with
via_cli=True, that flag governs the email-routing decision in the same module
(no helper-level propagation needed because each service's email-routing
branch lives in the public function itself).
"""
from __future__ import annotations

import inspect


def test_run_scan_signature_has_via_cli():
    from src.services.scan_service import run_scan
    sig = inspect.signature(run_scan)
    assert "via_cli" in sig.parameters
    assert sig.parameters["via_cli"].default is False
    # via_cli should be keyword-friendly with a boolean annotation.
    # scan_service uses `from __future__ import annotations`, so annotations
    # come through as strings — accept either form.
    p = sig.parameters["via_cli"]
    assert p.annotation in (bool, "bool", inspect.Parameter.empty)


def test_generate_eod_recap_signature_has_via_cli():
    from src.services.recap_service import generate_eod_recap
    sig = inspect.signature(generate_eod_recap)
    assert "via_cli" in sig.parameters
    assert sig.parameters["via_cli"].default is False


def test_generate_morning_watchlist_signature_has_via_cli():
    from src.services.watchlist_service import generate_morning_watchlist
    sig = inspect.signature(generate_morning_watchlist)
    assert "via_cli" in sig.parameters
    assert sig.parameters["via_cli"].default is False


def test_via_cli_propagates_to_routing_branch_in_scan_service():
    """The email-routing branch in scan_service must check via_cli — i.e.
    via_cli affects the decision inside the public function or a helper in
    the same module (DD-25: propagates to ALL internal helpers in the
    same module)."""
    from src.services import scan_service
    src = inspect.getsource(scan_service)
    # The conditional must reference via_cli (the propagation point).
    assert "via_cli" in src
    # And it must guard the send_email path:
    # we expect something like: if send_email_flag or via_cli:
    assert "or via_cli" in src or "via_cli or" in src or "via_cli=" in src

    # Verify run_scan actually passes via_cli to the helper (DD-25
    # propagation): the public function must thread via_cli through to its
    # internal helper.
    run_scan_src = inspect.getsource(scan_service.run_scan)
    assert "via_cli=via_cli" in run_scan_src, (
        "run_scan must propagate via_cli to its email-routing helper"
    )
