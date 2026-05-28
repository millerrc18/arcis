"""Structural lint: enforce point-in-time universe discipline (Sprint 1.A.1 / T10).

After Sprint 1.A.1 migrates backtest / simulation / training-backfill /
text-masking sites away from `get_sp100_universe()` to point-in-time
`pit.get_sp100_at()` or union `pit.get_all_historical_tickers()`, the
remaining `get_sp100_universe()` callers should be only **live-runtime**
sites that legitimately need today's universe.

This test AST-walks `src/` for `get_sp100_universe(` calls. Each call
site's *file* must appear in `_ALLOWLIST` with a one-line rationale,
or the test fails.

Pattern after PR #747 (allowlist + structural lint).

When a NEW caller is added, the developer adds the file to the allowlist
with rationale, OR migrates the caller to the appropriate PIT API.
Forgetting to do either fails the test at PR-review time, preventing
silent re-introduction of survivorship bias.

Definition site `src/universe/sp100.py` is excluded automatically because
the AST walker only flags `Call` nodes (function calls), not `FunctionDef`.

Tests: this file. Source of truth for the allowlist: this file's _ALLOWLIST.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Each entry: file path (relative to repo root) → one-line rationale.
# Live-runtime sites that legitimately need today's SP100 — keep on get_sp100_universe().
# When a new file is added here, include WHY the live universe is correct (not historical).
_ALLOWLIST: dict[str, str] = {
    # API + CLI + ad-hoc commands — operator-triggered, live market
    "src/api/routes/actions.py": "API endpoint, operator-triggered scan against today's market",
    "src/cli/commands_data.py": "CLI scan/universe/export commands — today's market (Phase 5 PR-C T13 split from commands.py)",
    "src/commands/executor.py": "Command queue executor — today's market",
    # LLM and platform — live universe matches what models / shadow-trade desks see today
    "src/llm/validator.py": "LLM ticker validation — checks tickers in current universe",
    "src/platform/data_loader.py": "Platform shadow-trading universe — today's market",
    # Scheduler — runtime services scan against the live market
    "src/scheduler/fundamentals_refresh.py": "Daily earnings refresh — today's market",
    "src/scheduler/overnight.py": "Overnight scan path — today's market",
    "src/scheduler/premarket.py": "Premarket scan — today's market",
    "src/scheduler/reports.py": "EOD/digest reports over today's universe",
    "src/scheduler/sentiment_scanner.py": "Daily sentiment scan — today's market",
    "src/scheduler/universe_scanner.py": "Generic universe scanner — today's market",
    "src/scheduler/watch.py": "Watch-loop scan — today's market",
    # Live trading services
    "src/services/mr_scan_service.py": "Mean-reversion scan — today's market",
    "src/services/recap_service.py": "EOD recap — today's market",
    "src/services/scan_service.py": "Pullback scan — today's market",
    "src/services/watchlist_service.py": "Watchlist build — today's market",
    # Training synthetic generator — survivorship bias undefined for fabricated outcomes
    "src/training/bootstrap.py": "Synthetic outcome generator — fake outcomes, no real market correlation",
    # Daily data collectors — collect T+1 data for today's universe, not historical
    "src/data_collection/short_volume_finra.py": "Daily FINRA REGSHO collector — filters CDN file for today's SP100; PIT raises UniverseDataMissing on T+1 anchors (W21 v0.36.20)",
}


def _normalize(p: Path, repo_root: Path) -> str:
    """Return the path relative to repo root with forward-slash separators."""
    return str(p.relative_to(repo_root)).replace("\\", "/")


def _find_caller_files(src_root: Path) -> dict[str, list[int]]:
    """AST-walk every .py under src/ and return {relpath: [line_numbers]} of every
    `get_sp100_universe(` call expression. The function definition itself is NOT
    counted (we look at `Call` nodes, not `FunctionDef`).
    """
    repo_root = src_root.parent
    callers: dict[str, list[int]] = {}
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (UnicodeDecodeError, SyntaxError):
            # Skip files we can't parse — they aren't real Python sources we care about
            continue

        rel = _normalize(py_file, repo_root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            # Match either bare `get_sp100_universe(...)` or `something.get_sp100_universe(...)`
            name: str | None = None
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            if name == "get_sp100_universe":
                callers.setdefault(rel, []).append(node.lineno)
    return callers


def test_get_sp100_universe_callers_match_allowlist():
    """Every `get_sp100_universe(...)` call site in src/ must be allowlisted with rationale.

    Failure modes:
      - A new caller not in _ALLOWLIST → migration miss; either migrate to PIT or
        add to allowlist with a rationale.
      - An allowlist entry with no calls → entry is stale, remove it.
    """
    repo_root = Path(__file__).parent.parent
    src_root = repo_root / "src"
    assert src_root.is_dir(), f"Expected src/ at {src_root}"

    callers = _find_caller_files(src_root)
    actual_files = set(callers.keys())
    allowed_files = set(_ALLOWLIST.keys())

    unallowed = actual_files - allowed_files
    stale = allowed_files - actual_files

    msg_parts = []
    if unallowed:
        msg_parts.append(
            "Unallowed `get_sp100_universe(` callers found "
            "(migrate to pit.get_sp100_at() or add to allowlist):\n"
            + "\n".join(
                f"  {f}:{','.join(str(ln) for ln in callers[f])}"
                for f in sorted(unallowed)
            )
        )
    if stale:
        msg_parts.append(
            "Stale allowlist entries (file no longer calls get_sp100_universe — remove):\n"
            + "\n".join(f"  {f}" for f in sorted(stale))
        )
    if msg_parts:
        pytest.fail("\n\n".join(msg_parts))


def test_allowlist_rationales_are_non_empty():
    """Each allowlist entry must have a non-empty rationale string explaining
    WHY this site needs today's universe instead of point-in-time."""
    bad = [f for f, rationale in _ALLOWLIST.items() if not rationale.strip()]
    assert not bad, f"Allowlist entries with empty rationale: {bad}"
