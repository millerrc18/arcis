"""Tests for #115 T11 — reports.py morning watchlist email routing + F-MAJ-1 deletion.

DD-20 revised: in shadow / time_aligned mode, the original send_email
(operator inbox) must continue to fire alongside the queue enqueue. Only
in mode='off' does the queue become the sole consumer.

DD-30 revised: aggregator import failure surfaces as ImportError. The
fallback is FIREHOSE MODE — log CRITICAL, best-effort Telegram alert,
then revert to immediate send_email so operator visibility is never lost.

F-MAJ-1: src/scheduler/reports.py:run_saturday_reports was a dead duplicate
of src/scheduler/overnight.py:run_saturday_reports (the live version called
by watch.py). The dead copy is DELETED in this task.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest


def _shadow_config(mode: str = "off") -> dict:
    return {"email": {"dual_write_hold_over": {"mode": mode}}}


def _patch_pipeline_deps():
    """Patch the side-effecting pipeline imports used inside run_morning_watchlist."""
    import pandas as pd

    # Build a tiny non-empty SPY DataFrame so the empty-spy guard does not return early.
    spy_df = pd.DataFrame({"close": [400.0, 401.0]})

    return [
        patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={}),
        patch("src.data_ingestion.market_data.fetch_spy_benchmark", return_value=spy_df),
        patch("src.features.engine.compute_all_features", return_value={}),
        patch("src.ranking.ranker.rank_universe", return_value={}),
        patch(
            "src.ranking.ranker.get_top_candidates",
            return_value={"packet_worthy": [], "watchlist": []},
        ),
        patch("src.universe.sp100.get_sp100_universe", return_value=[]),
        patch(
            "src.llm.watchlist_writer.generate_watchlist_narrative",
            return_value="narrative",
        ),
        patch(
            "src.packets.watchlist.build_morning_watchlist",
            return_value="body text",
        ),
        patch("src.scheduler.reports.safe_send"),
    ]


# ── (a) morning_watchlist routes to digest when via_cli=False ─────────────


def test_morning_watchlist_without_via_cli_enqueues_to_preopen():
    """via_cli=False AND email_mode='digest' → enqueue (preopen), no send_email."""
    from src.scheduler import reports

    deps = _patch_pipeline_deps()
    with patch(
        "src.scheduler.reports.load_config",
        create=True,
        return_value=_shadow_config("off"),
    ), patch(
        "src.notifications.email_digest.enqueue_for_email_digest"
    ) as mock_enq, patch(
        "src.email.notifier.send_email"
    ) as mock_send:
        for d in deps:
            d.start()
        try:
            reports.run_morning_watchlist({}, email_mode="digest", via_cli=False)
        finally:
            for d in deps:
                d.stop()

    assert mock_enq.call_count == 1, "morning watchlist should enqueue to preopen tier"
    call = mock_enq.call_args
    assert call.args[0] == "morning_watchlist"
    assert call.kwargs.get("severity") == "normal"
    assert call.kwargs.get("source_tag") == "email:preopen"
    payload = call.kwargs.get("payload") or {}
    assert "subject" in payload
    assert "body" in payload
    assert "date_str" in payload
    # mode='off' → no immediate send_email.
    assert mock_send.call_count == 0


# ── (b) via_cli=True → bypass aggregator, send directly ─────────────────


def test_morning_watchlist_with_via_cli_calls_send_directly():
    """via_cli=True → keep send_email path (operator forced manual send)."""
    from src.scheduler import reports

    deps = _patch_pipeline_deps()
    with patch(
        "src.notifications.email_digest.enqueue_for_email_digest"
    ) as mock_enq, patch(
        "src.email.notifier.send_email"
    ) as mock_send:
        for d in deps:
            d.start()
        try:
            reports.run_morning_watchlist({}, email_mode="digest", via_cli=True)
        finally:
            for d in deps:
                d.stop()

    assert mock_send.call_count == 1
    assert mock_enq.call_count == 0


# ── (c) full_stream back-compat ─────────────────────────────────────────


def test_morning_watchlist_email_mode_full_stream_still_emails():
    """email_mode='full_stream' → send_email regardless of via_cli (transitional config)."""
    from src.scheduler import reports

    deps = _patch_pipeline_deps()
    with patch(
        "src.notifications.email_digest.enqueue_for_email_digest"
    ) as mock_enq, patch(
        "src.email.notifier.send_email"
    ) as mock_send:
        for d in deps:
            d.start()
        try:
            reports.run_morning_watchlist({}, email_mode="full_stream", via_cli=False)
        finally:
            for d in deps:
                d.stop()

    assert mock_send.call_count == 1
    assert mock_enq.call_count == 0


# ── (d) F-MAJ-1: dead duplicate has been deleted ────────────────────────


def test_run_saturday_reports_in_reports_py_does_not_exist():
    """F-MAJ-1: reports.run_saturday_reports MUST be deleted (live ver lives in overnight.py)."""
    from src.scheduler import reports

    assert not hasattr(reports, "run_saturday_reports"), (
        "reports.run_saturday_reports is dead duplicate of overnight.run_saturday_reports "
        "and MUST be deleted (F-MAJ-1)"
    )


# ── (e) F-MAJ-1: no callers in src/ ─────────────────────────────────────


def test_no_callers_of_deleted_function():
    """AST-scan src/ for any caller of the deleted symbol — must be 0."""
    src_dir = Path(__file__).resolve().parents[2] / "src"
    bad_imports: list[str] = []
    bad_attrs: list[str] = []

    for py_file in src_dir.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # `from src.scheduler.reports import run_saturday_reports`
            if isinstance(node, ast.ImportFrom):
                if node.module == "src.scheduler.reports":
                    for alias in node.names:
                        if alias.name == "run_saturday_reports":
                            bad_imports.append(str(py_file))
            # `reports.run_saturday_reports` attribute access
            if isinstance(node, ast.Attribute) and node.attr == "run_saturday_reports":
                # Only flag if the value is a Name == 'reports' (the reports module)
                if isinstance(node.value, ast.Name) and node.value.id == "reports":
                    bad_attrs.append(str(py_file))

    assert not bad_imports, (
        f"Found `from src.scheduler.reports import run_saturday_reports` in: {bad_imports}"
    )
    assert not bad_attrs, (
        f"Found `reports.run_saturday_reports` attribute access in: {bad_attrs}"
    )
