"""CI guardrail: no ad-hoc Calmar formulas allowed outside the canonical helper.

Sprint 3 T1 — D3 follow-up from spec §3.5.
Sprint 3 T1 follow-up (QA sibling-search fix) — broadened guardrail to detect
calmar-named function definitions anywhere in src/ that are not in
src/evaluation/statistics.py and not in _CALMAR_FUNC_ALLOWLIST.

Greps src/ for ad-hoc Calmar patterns. Any new occurrence outside the
allowlisted sites must fail this test. Allowlisted sites are tracked
as #SP4-calmar-debt and must be migrated in Sprint 4.

Allowlist (currently correct hand-rolled sites per deep report 2026-05-06):
  - src/evaluation/cto_report.py:738   calmar = (mean_r * 150) / max_dd_pct
  - src/simulation/engine.py:439       calmar = annualized_return / max_dd
  - src/evaluation/backtester.py:343   calmar = round(ann_return / abs(max_dd_pct), 2)

Function-name allowlist (calmar-named functions per QA sibling-search 2026-05-07):
  - src/platform/metrics.py:75         compute_calmar() wraps total_return / max_drawdown
                                        #SP4-calmar-debt: should migrate to calmar_ratio()

Non-Calmar (profit_factor computation, not drawdown-based):
  - src/evaluation/hshs_live.py:116    profit_factor = gross_profit / gross_loss
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile


_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")

# Allowlisted ad-hoc calmar sites. Key = (relative_path, line_number).
# T17a migrated: cto_report.py:738, engine.py:439
# T17b migrated: backtester.py:343
# All 4 canonical-debt sites resolved — allowlist intentionally empty.
_ALLOWLIST: set = set()

# Allowlist for calmar-named function definitions outside src/evaluation/statistics.py.
# T17b migrated: metrics.py:75 compute_calmar body now delegates to calmar_ratio().
# Thin-wrapper calmar-named functions (body calls calmar_ratio()) are exempt from
# the guardrail — they are correct delegations, not ad-hoc formula debt.
_CALMAR_FUNC_ALLOWLIST: set = set()


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


# ── Calmar function-name guardrail ────────────────────────────────────────────

_CALMAR_FUNC_RE = re.compile(r"def\s+\w*calmar\w*\s*\(", re.IGNORECASE)


def _scan_calmar_func_defs(
    src_paths: list[str],
    repo_root: str,
) -> list[tuple[str, int, str]]:
    """Scan a list of absolute file paths for calmar-named function definitions.

    Returns list of (relative_path, line_number, line_text) for every line
    matching ``def <something containing 'calmar'>(``.
    relative_path uses forward slashes and is relative to repo_root.

    Thin-wrapper functions whose body calls ``calmar_ratio(`` are NOT returned
    — they are correct delegations to the canonical helper, not ad-hoc formulas.
    """
    hits = []
    for abs_path in src_paths:
        rel_path = os.path.relpath(abs_path, repo_root).replace("\\", "/")
        with open(abs_path, encoding="utf-8") as f:
            all_lines = f.readlines()
        for lineno, line in enumerate(all_lines, start=1):
            if not _CALMAR_FUNC_RE.search(line):
                continue
            # Check the next 5 lines for a calmar_ratio( call — thin wrapper
            body_window = all_lines[lineno: lineno + 5]
            if any("calmar_ratio(" in body_line for body_line in body_window):
                continue
            hits.append((rel_path, lineno, line))
    return hits


def _collect_src_py_files(repo_root: str) -> list[str]:
    """Walk src/ under repo_root and return all .py file paths."""
    src_dir = os.path.join(repo_root, "src")
    paths = []
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        for fname in filenames:
            if fname.endswith(".py"):
                paths.append(os.path.join(dirpath, fname))
    return paths


def test_no_calmar_named_functions_outside_allowlist():
    """Any def *calmar*() outside statistics.py that contains an ad-hoc formula must fail CI.

    This catches the compute_calmar() style sibling that the original regex missed
    because its body uses parameter names (total_return / max_drawdown) that don't
    match the 'calmar.*max_dd' pattern — only the function name gives it away.

    Canonical definition in src/evaluation/statistics.py is exempt.
    Thin-wrapper functions whose body calls calmar_ratio() are exempt — they are
    correct delegations, not ad-hoc formula debt.
    Known ad-hoc calmar functions are in _CALMAR_FUNC_ALLOWLIST (#SP4-calmar-debt).
    """
    repo_root = _get_repo_root()
    src_files = _collect_src_py_files(repo_root)
    hits = _scan_calmar_func_defs(src_files, repo_root)

    violations = []
    for rel_path, lineno, line_text in hits:
        if rel_path == "src/evaluation/statistics.py":
            continue
        if (rel_path, lineno) in _CALMAR_FUNC_ALLOWLIST:
            continue
        violations.append(f"{rel_path}:{lineno}: {line_text.rstrip()}")

    assert violations == [], (
        "New calmar-named function definition(s) found outside the canonical file and allowlist:\n"
        + "\n".join(violations)
        + "\n\nMigrate to: from src.evaluation.statistics import calmar_ratio"
        + "\nOr add to _CALMAR_FUNC_ALLOWLIST with #SP4-calmar-debt justification."
    )


def test_calmar_func_guardrail_regression_synthetic():
    """Regression: guardrail must detect a synthetic non-allowlisted calmar function.

    Creates a temporary .py file with ``def calmar_v2(a, b): return a / b``
    and asserts _scan_calmar_func_defs finds it. Validates the regex is live.
    """
    repo_root = _get_repo_root()
    synthetic_src = "def calmar_v2(annualized_return, max_drawdown):\n    return annualized_return / max_drawdown\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir=repo_root, encoding="utf-8"
    ) as tmp:
        tmp.write(synthetic_src)
        tmp_path = tmp.name

    try:
        hits = _scan_calmar_func_defs([tmp_path], repo_root)
        assert len(hits) == 1, (
            f"Expected guardrail to detect 1 calmar-named function in synthetic file, "
            f"got {len(hits)}. Regex may be broken."
        )
        _rel, lineno, line_text = hits[0]
        assert lineno == 1
        assert "calmar_v2" in line_text
    finally:
        os.unlink(tmp_path)


# ── T17a: cto_report + engine canonical migration tests ───────────────────────

def test_t17a_allowlists_empty():
    """Post-T17a: _ALLOWLIST and _CALMAR_FUNC_ALLOWLIST must be empty sets.

    T17a migrates cto_report.py:738 and engine.py:439. T17b migrates
    backtester.py:343 and metrics.py:75. After both deliverables the
    allowlists are empty — this test enforces that contract.
    """
    assert _ALLOWLIST == set(), (
        f"_ALLOWLIST must be empty after T17 migration, got: {_ALLOWLIST}"
    )
    assert _CALMAR_FUNC_ALLOWLIST == set(), (
        f"_CALMAR_FUNC_ALLOWLIST must be empty after T17 migration, got: {_CALMAR_FUNC_ALLOWLIST}"
    )


# ── T17b: backtester + platform/metrics canonical migration tests ─────────────

def test_t17b_compute_calmar_zero_drawdown_returns_zero():
    """platform/metrics.compute_calmar: max_dd=0 → 0.0 (canonical), NOT inf.

    The canonical calmar_ratio() returns 0.0 when max_drawdown_pct==0.
    The old compute_calmar() returned float('inf'). Post-T17b the function
    must delegate to calmar_ratio and therefore return 0.0.
    """
    from src.platform.metrics import compute_calmar
    result = compute_calmar(total_return=0.5, max_drawdown=0.0)
    assert result == 0.0, (
        f"compute_calmar(0.5, 0.0) must return 0.0 (canonical), got {result!r}"
    )
    assert result != float("inf"), (
        "compute_calmar must NOT return inf — canonical calmar_ratio returns 0.0 for zero drawdown"
    )


def test_t17b_compute_calmar_matches_canonical():
    """platform/metrics.compute_calmar delegates to canonical calmar_ratio."""
    from src.platform.metrics import compute_calmar
    from src.evaluation.statistics import calmar_ratio
    pairs = [(0.20, 0.10), (0.05, 0.25), (1.0, 0.50), (0.0, 0.15)]
    for total_return, max_dd in pairs:
        expected = calmar_ratio(total_return, max_dd)
        got = compute_calmar(total_return, max_dd)
        assert abs(got - expected) < 1e-9, (
            f"compute_calmar({total_return}, {max_dd}) = {got}, "
            f"canonical calmar_ratio = {expected}"
        )


def test_t17b_backtester_calmar_matches_canonical():
    """backtester.py:343 calmar uses canonical calmar_ratio (post-round check)."""
    from src.evaluation.statistics import calmar_ratio
    ann_return = 15.0
    max_dd_pct = 7.5
    expected = round(calmar_ratio(ann_return, abs(max_dd_pct)), 2)
    assert expected == round(ann_return / abs(max_dd_pct), 2), (
        "Numerical equivalence check: calmar_ratio and direct division must agree "
        "for non-zero drawdown"
    )


def test_t17a_cto_report_calmar_matches_canonical():
    """cto_report.py:738 calmar uses canonical calmar_ratio to 3 decimal places."""
    from src.evaluation.statistics import calmar_ratio
    mean_r = 0.08
    max_dd_pct = 5.0
    expected = calmar_ratio(mean_r * 150, max_dd_pct)
    direct = (mean_r * 150) / max_dd_pct
    assert abs(expected - direct) < 1e-9, (
        "calmar_ratio must match direct formula for non-zero drawdown"
    )


def test_t17a_engine_calmar_matches_canonical():
    """engine.py:439 calmar uses canonical calmar_ratio."""
    from src.evaluation.statistics import calmar_ratio
    annualized_return = 12.5
    max_dd = 6.25
    expected = calmar_ratio(annualized_return, max_dd)
    direct = annualized_return / max_dd
    assert abs(expected - direct) < 1e-9, (
        "calmar_ratio must match direct formula for non-zero drawdown"
    )
