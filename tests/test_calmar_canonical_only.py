"""CI guardrail: no ad-hoc Calmar formulas allowed outside the canonical helper.

Sprint 3 T1 — D3 follow-up from spec §3.5.

Greps src/ for ad-hoc Calmar patterns. Any new occurrence outside the
allowlisted sites must fail this test. Allowlisted sites are tracked
as #SP4-calmar-debt and must be migrated in Sprint 4.

Allowlist (currently correct hand-rolled sites per deep report 2026-05-06):
  - src/evaluation/cto_report.py:738   calmar = (mean_r * 150) / max_dd_pct
  - src/simulation/engine.py:439       calmar = annualized_return / max_dd
  - src/evaluation/backtester.py:343   calmar = round(ann_return / abs(max_dd_pct), 2)

Non-Calmar (profit_factor computation, not drawdown-based):
  - src/evaluation/hshs_live.py:116    profit_factor = gross_profit / gross_loss
"""
from __future__ import annotations

import os
import re
import subprocess


_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")

# Allowlisted ad-hoc calmar sites. Key = (relative_path, line_number).
# These are correct per the 2026-05-06 deep report. Tracked as #SP4-calmar-debt.
_ALLOWLIST = {
    # cto_report.py: calmar = (mean_r * 150) / max_dd_pct — correct, annualizes 150 periods
    ("src/evaluation/cto_report.py", 738),
    # engine.py: calmar = annualized_return / max_dd — correct, max_dd is already a pct here
    ("src/simulation/engine.py", 439),
    # backtester.py: calmar = round(ann_return / abs(max_dd_pct), 2) — correct
    ("src/evaluation/backtester.py", 343),
}


def _get_repo_root() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__),
    )
    return result.stdout.strip()


def _grep_src(pattern: str) -> list[tuple[str, int, str]]:
    """Return list of (relative_path, line_number, line_text) for matches."""
    repo_root = _get_repo_root()
    src_abs = os.path.normpath(os.path.join(repo_root, "src"))

    result = subprocess.run(
        ["git", "grep", "-n", pattern, "--", "src/"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    matches = []
    for line in result.stdout.splitlines():
        # Format: src/path/file.py:123:line_content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            rel_path = parts[0].replace("\\", "/")
            try:
                lineno = int(parts[1])
            except ValueError:
                continue
            matches.append((rel_path, lineno, parts[2]))
    return matches


def test_no_new_calmar_formulas_outside_allowlist():
    """Any ad-hoc Calmar formula outside the allowlist must fail CI.

    Checks two patterns:
    1. calmar.*max_dd or max_dd.*calmar (Calmar assignment with drawdown variable)
    2. / max_dd on lines that assign to calmar (direct ad-hoc Calmar division)

    Lines that call the canonical helper (_canonical_calmar or calmar_ratio() calls)
    are excluded — they are correct usages, not violations.
    The canonical definition in src/evaluation/statistics.py is exempt.
    The allowlisted sites are tracked as #SP4-calmar-debt.
    """
    all_violations: list[str] = []

    # Pattern 1: calmar assignment with max_dd (catches: calmar = x / max_dd, etc.)
    for rel_path, lineno, line_text in _grep_src(r"calmar.*max_dd\|max_dd.*calmar"):
        norm_path = rel_path.replace("\\", "/")
        if norm_path == "src/evaluation/statistics.py":
            continue
        if (norm_path, lineno) in _ALLOWLIST:
            continue
        # Exclude lines that correctly call the canonical helper
        if "_canonical_calmar(" in line_text or "calmar_ratio(" in line_text:
            continue
        all_violations.append(f"{norm_path}:{lineno}: {line_text.strip()}")

    # Pattern 2: direct ad-hoc calmar division — line assigns to calmar AND divides
    for rel_path, lineno, line_text in _grep_src(r"calmar.*/ max_dd"):
        norm_path = rel_path.replace("\\", "/")
        if norm_path == "src/evaluation/statistics.py":
            continue
        if (norm_path, lineno) in _ALLOWLIST:
            continue
        # Exclude canonical helper call sites
        if "_canonical_calmar(" in line_text or "calmar_ratio(" in line_text:
            continue
        all_violations.append(f"{norm_path}:{lineno}: {line_text.strip()}")

    assert all_violations == [], (
        "New ad-hoc Calmar formula(s) detected outside the allowlist:\n"
        + "\n".join(all_violations)
        + "\n\nMigrate to: from src.evaluation.statistics import calmar_ratio"
        + "\nOr add to allowlist with #SP4-calmar-debt justification."
    )


def test_allowlisted_sites_still_exist():
    """Allowlisted sites must still exist — catches stale allowlist entries.

    If a site is migrated (Sprint 4), remove it from _ALLOWLIST here.
    A stale allowlist entry is worse than nothing — it hides future violations.
    """
    repo_root = _get_repo_root()

    missing: list[str] = []
    for rel_path, lineno, *_ in _ALLOWLIST:
        abs_path = os.path.join(repo_root, rel_path.replace("/", os.sep))
        if not os.path.exists(abs_path):
            missing.append(f"{rel_path}:{lineno} — file not found")
            continue
        with open(abs_path, encoding="utf-8") as f:
            lines = f.readlines()
        # Allow ±2 line tolerance for minor edits
        window = lines[max(0, lineno - 3): lineno + 1]
        window_text = "".join(window)
        if not any("calmar" in l.lower() or "/ max_dd" in l for l in window):
            missing.append(
                f"{rel_path}:{lineno} — calmar/drawdown code no longer at this line "
                f"(window: {window_text!r})"
            )

    assert missing == [], (
        "Stale allowlist entries — remove them from _ALLOWLIST:\n"
        + "\n".join(missing)
    )


def test_no_ad_hoc_calmar_in_analytics_py():
    """Regression lock: analytics.py must not contain / 100000 * 100 pattern near calmar."""
    repo_root = _get_repo_root()
    analytics_path = os.path.join(
        repo_root, "src", "api", "cloud_routes", "analytics.py"
    )
    with open(analytics_path, encoding="utf-8") as f:
        content = f.read()

    # The exact bug pattern: ann_ret / (max_dd / 100000 * 100)
    assert "/ 100000 * 100" not in content, (
        "analytics.py still contains the ad-hoc formula '/ 100000 * 100'. "
        "This is the E5 Calmar 1000x overshoot bug. Fix: use calmar_ratio() from "
        "src.evaluation.statistics."
    )
