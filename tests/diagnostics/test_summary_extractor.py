"""Tests for summary_extractor — regex parser for diagnostic reports."""

from pathlib import Path

import pytest

from src.diagnostics.summary_extractor import (
    parse_regime_report,
    parse_forensic_report,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# ── regime ──────────────────────────────────────────────────────────

def test_parse_regime_report_happy_path():
    md = _load("regime_report_sample.md")
    summary = parse_regime_report(md)
    assert summary["decision"] == "CONTAMINATED"
    assert summary["n_total"] == 88
    assert summary["mean_excess"] == pytest.approx(-0.0012)
    assert "Technology-Afternoon" in summary["rationale"]


def test_parse_regime_report_missing_decision_falls_back():
    md = (
        "## Executive Summary\n\n"
        "**N = 88**\n\nMean excess return: -0.0012\n"
    )
    summary = parse_regime_report(md)
    assert "raw_executive_summary" in summary
    assert "decision" in summary["parse_errors"]


def test_parse_regime_report_no_exec_summary_returns_fallback():
    md = "# Report\n\nNothing useful here."
    summary = parse_regime_report(md)
    assert summary["parse_errors"] == ["no_executive_summary"]
