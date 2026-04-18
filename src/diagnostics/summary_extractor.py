"""Regex parser for diagnostic report ``## Executive Summary`` sections.

Returns a summary dict for diagnostic_runs.summary_json. On parse
failure, stores raw executive-summary text + error list for UI fallback.

Called by: src.diagnostics.dashboard_runner
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_summary_extractor.py
"""

from __future__ import annotations

import re


EXEC_SUMMARY_RE = re.compile(
    r"##\s*Executive Summary\s*\n(?P<body>.+?)(?=\n##\s|\Z)",
    re.DOTALL,
)


def _extract_exec_summary(md: str) -> str | None:
    match = EXEC_SUMMARY_RE.search(md)
    return match.group("body").strip() if match else None


def _fallback(body: str | None, errors: list[str]) -> dict:
    return {
        "raw_executive_summary": (body or "")[:2000],
        "parse_errors": errors,
    }


# ── regime ──────────────────────────────────────────────────────────

_REGIME_DECISION_RE = re.compile(r"\*\*Decision:\*\*\s+(\w+)")
_REGIME_N_RE = re.compile(r"\*\*N\s*=\s*(\d+)\*\*")
_REGIME_MEAN_RE = re.compile(r"Mean excess return:\s*(-?[\d\.]+)")


def parse_regime_report(md: str) -> dict:
    """Parse a regime diagnostic report's executive summary."""
    body = _extract_exec_summary(md)
    if body is None:
        return _fallback(None, ["no_executive_summary"])

    errors: list[str] = []
    summary: dict = {}

    m = _REGIME_DECISION_RE.search(body)
    if m:
        summary["decision"] = m.group(1)
    else:
        errors.append("decision")

    m = _REGIME_N_RE.search(body)
    if m:
        summary["n_total"] = int(m.group(1))
    else:
        errors.append("n_total")

    m = _REGIME_MEAN_RE.search(body)
    if m:
        summary["mean_excess"] = float(m.group(1))
    else:
        errors.append("mean_excess")

    summary["rationale"] = body
    if errors:
        summary.update(_fallback(body, errors))
    return summary


# ── forensic ────────────────────────────────────────────────────────

_FORENSIC_N_RE = re.compile(r"Analyzed\s+\*\*(\d+)\*\*")
_FORENSIC_FINDINGS_RE = re.compile(
    r"###\s*3 Most Surprising Findings\s*\n+(.+?)(?=\n###|\Z)",
    re.DOTALL,
)


def parse_forensic_report(md: str) -> dict:
    """Parse a forensic audit report's executive summary."""
    body = _extract_exec_summary(md)
    if body is None:
        return _fallback(None, ["no_executive_summary"])

    errors: list[str] = []
    summary: dict = {"raw_executive_summary": body[:2000]}

    n_match = _FORENSIC_N_RE.search(body)
    if n_match:
        summary["n_total"] = int(n_match.group(1))
    else:
        errors.append("n_total")

    findings_match = _FORENSIC_FINDINGS_RE.search(body)
    if findings_match:
        summary["findings_raw"] = findings_match.group(1).strip()
    else:
        errors.append("findings")

    if errors:
        summary["parse_errors"] = errors
    return summary
