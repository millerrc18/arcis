"""AST scanner: two-way runtime-coverage invariants for `_FEATURE_MATRIX`.

Sprint 5 Wave C7b.6 / T26.

Closes the "stuck on shelf" class — a feature is defined in
`src/data_enrichment/finnhub_plan.py::_FEATURE_MATRIX` but never gated
at any runtime call site, so the matrix lies about what the plan actually
unlocks.

Two invariants, both expressed as AST scans of `src/`:

1. Forward — every feature in `_FEATURE_MATRIX['fundamental-1']` must
   have at least one `finnhub_plan_supports(<feature>, ...)` call site
   in `src/`, OR be in `_UNWIRED_FORWARD_ALLOWLIST` with rationale.

2. Reverse — every feature referenced by a
   `finnhub_plan_supports(<feat>, ...)` call must exist in
   `_FEATURE_MATRIX['fundamental-1']` ∪ `_FEATURE_MATRIX['free']`, OR
   be in `_REVERSE_INVARIANT_ALLOWLIST`. Catches the "gate calls a
   feature that's not in the matrix, so the gate is permanently False"
   class (e.g. `analyst_collector.py:146` `price_target` site).

Self-tests at the bottom exercise the invariant logic against synthetic
matrices / call-site sets — proves the scanner detects the failure mode
it's designed to catch (independent of current real matrix state).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.data_enrichment.finnhub_plan import _FEATURE_MATRIX

SRC_ROOT = Path(__file__).parent.parent / "src"


# ---------------------------------------------------------------------------
# Allowlists — narrow, documented, with rationale per entry.
# Adding new entries here is operator-visible (PR review surface).
# ---------------------------------------------------------------------------

# Features in `_FEATURE_MATRIX['fundamental-1']` that have NO runtime
# `finnhub_plan_supports(<feature>, ...)` call site. Preserved in the
# matrix for documentation value (what the paid plan unlocks for the
# operator's downgrade-ceremony reference) but currently unwired.
# When a runtime caller is added for any entry, REMOVE it from this set
# (forward invariant then enforces real coverage).
_UNWIRED_FORWARD_ALLOWLIST: set[str] = {
    "company_executive",   # No collector / enricher yet — reserved for future C-suite tracking surface.
    "filings",             # Superseded by filings_sentiment (Wave C7b.2). Kept in matrix for completeness.
    "fund_ownership",      # Mutual-fund concentration; no collector wired (separate from institutional_ownership).
    "stock_ownership",     # Overlaps with institutional_ownership (Wave C7b.1); reserved for distinct shape later.
}

# `finnhub_plan_supports(<feat>, ...)` call sites that pass a feature
# NOT in any plan matrix. These calls always return False (feature
# unknown ⇒ never in `_FEATURE_MATRIX.get(plan, set())`). Resolution
# deferred to post-Sprint-5 per operator decision 2026-05-13.
_REVERSE_INVARIANT_ALLOWLIST: set[str] = set()
# price_target removed — added to _FEATURE_MATRIX['fundamental-1'] in Sprint 6 Wave A (WA2).


# ---------------------------------------------------------------------------
# AST scanner
# ---------------------------------------------------------------------------


def _scan_plan_supports_call_sites(src_root: Path) -> set[str]:
    """Walk `src_root` and return every string-literal feature passed to
    `finnhub_plan_supports()` as the first positional argument.

    Detection:
      - `finnhub_plan_supports("X", ...)` → adds "X" to the set
      - `finnhub_plan_supports(<non-literal>, ...)` → ignored (dynamic
        dispatch is out of scope; AST scanner cannot evaluate
        expression results without execution)

    Both `Name` (direct call) and `Attribute` (`module.finnhub_plan_supports`)
    forms are matched.
    """
    features: set[str] = set()
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Skip files with syntax issues or non-UTF8 content (none expected;
            # tolerated for forward-compat robustness).
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name != "finnhub_plan_supports":
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                features.add(arg0.value)
    return features


# ---------------------------------------------------------------------------
# Forward invariant
# ---------------------------------------------------------------------------


def test_forward_every_fundamental_1_feature_has_runtime_caller():
    """For every feature in `_FEATURE_MATRIX['fundamental-1']`, assert at
    least one `finnhub_plan_supports(<feature>, ...)` call site exists
    in `src/` — OR the feature is in `_UNWIRED_FORWARD_ALLOWLIST` with
    documented rationale.

    Prevents the "feature defined in matrix but no runtime caller"
    stuck-on-shelf class.
    """
    matrix = _FEATURE_MATRIX["fundamental-1"]
    callers = _scan_plan_supports_call_sites(SRC_ROOT)
    missing = matrix - callers - _UNWIRED_FORWARD_ALLOWLIST
    assert not missing, (
        f"{len(missing)} fundamental-1 feature(s) in _FEATURE_MATRIX have NO "
        f"`finnhub_plan_supports(<feature>, ...)` runtime caller: "
        f"{sorted(missing)}\n\n"
        f"Resolution options:\n"
        f"  (a) Add a `finnhub_plan_supports(<feature>, config)` gate at the "
        f"runtime call site in src/data_collection/ or src/data_enrichment/, OR\n"
        f"  (b) Add the feature to `_UNWIRED_FORWARD_ALLOWLIST` in this test "
        f"file with a one-line rationale comment."
    )


# ---------------------------------------------------------------------------
# Reverse invariant
# ---------------------------------------------------------------------------


def test_reverse_every_plan_supports_call_references_matrix_feature():
    """For every `finnhub_plan_supports(<feat>, ...)` call site in
    `src/`, assert `<feat>` is in `_FEATURE_MATRIX['fundamental-1']` ∪
    `_FEATURE_MATRIX['free']`, OR is in `_REVERSE_INVARIANT_ALLOWLIST`.

    Prevents the "gate calls a feature not in matrix, so gate is
    permanently False" silent-disable class.
    """
    known_features = (
        _FEATURE_MATRIX["fundamental-1"] | _FEATURE_MATRIX["free"]
    )
    callers = _scan_plan_supports_call_sites(SRC_ROOT)
    orphans = callers - known_features - _REVERSE_INVARIANT_ALLOWLIST
    assert not orphans, (
        f"{len(orphans)} `finnhub_plan_supports()` call site(s) reference "
        f"features NOT in `_FEATURE_MATRIX`: {sorted(orphans)}\n\n"
        f"These calls always return False because the feature is unknown "
        f"to every plan in the matrix. Resolution options:\n"
        f"  (a) Add the feature to `_FEATURE_MATRIX` in "
        f"src/data_enrichment/finnhub_plan.py (the right plan tier), OR\n"
        f"  (b) Rename the call-site argument to an existing matrix feature, OR\n"
        f"  (c) Add the feature to `_REVERSE_INVARIANT_ALLOWLIST` in this "
        f"test file with rationale (only when deferred resolution is acceptable)."
    )


# ---------------------------------------------------------------------------
# Self-tests — prove the invariant logic catches the failure modes it
# claims to. These do NOT touch the real `_FEATURE_MATRIX` or `src/`;
# they exercise the diff logic in isolation.
# ---------------------------------------------------------------------------


def test_self_forward_invariant_flags_missing_caller():
    """Self-test: forward-invariant diff correctly flags a matrix entry
    that has no caller and is not in the allowlist."""
    matrix = {"a", "b", "synthetic_missing"}
    callers = {"a", "b"}
    allowlist: set[str] = set()
    missing = matrix - callers - allowlist
    assert missing == {"synthetic_missing"}, (
        "Self-test broken: forward-invariant diff should flag "
        "'synthetic_missing' (in matrix, no caller, no allowlist)"
    )


def test_self_reverse_invariant_flags_orphan_call():
    """Self-test: reverse-invariant diff correctly flags a call that
    references a feature not in any matrix and not in allowlist."""
    matrix_features = {"a", "b"}
    callers = {"a", "b", "synthetic_orphan"}
    allowlist: set[str] = set()
    orphans = callers - matrix_features - allowlist
    assert orphans == {"synthetic_orphan"}, (
        "Self-test broken: reverse-invariant diff should flag "
        "'synthetic_orphan' (in call sites, not in any matrix, no allowlist)"
    )


def test_self_allowlist_silences_both_invariants():
    """Self-test: allowlists correctly suppress both forward and
    reverse invariant failures."""
    # Forward — matrix entry with no caller is silenced by forward allowlist
    matrix = {"a", "deferred"}
    callers = {"a"}
    fwd_allow = {"deferred"}
    assert (matrix - callers - fwd_allow) == set(), (
        "Self-test broken: forward allowlist should silence 'deferred'"
    )
    # Reverse — orphan call is silenced by reverse allowlist
    matrix_features = {"a"}
    callers2 = {"a", "deferred_orphan"}
    rev_allow = {"deferred_orphan"}
    assert (callers2 - matrix_features - rev_allow) == set(), (
        "Self-test broken: reverse allowlist should silence 'deferred_orphan'"
    )


# ---------------------------------------------------------------------------
# AST scanner self-test — proves the call-site extractor works against
# a small synthetic source tree fixture.
# ---------------------------------------------------------------------------


def test_self_ast_scanner_extracts_literal_feature_args(tmp_path):
    """Self-test: `_scan_plan_supports_call_sites` correctly extracts
    string-literal feature args from `finnhub_plan_supports(...)` calls
    and ignores non-literal args."""
    synthetic = tmp_path / "synthetic"
    synthetic.mkdir()
    (synthetic / "callsite.py").write_text(
        "from src.data_enrichment.finnhub_plan import finnhub_plan_supports\n"
        "x = finnhub_plan_supports('extracted_feature', config)\n"
        "y = finnhub_plan_supports('another_feature')\n"
        "z = finnhub_plan_supports(some_var)\n"  # non-literal → ignored
        "w = unrelated_function('not_extracted')\n",  # different fn → ignored
        encoding="utf-8",
    )
    found = _scan_plan_supports_call_sites(synthetic)
    assert found == {"extracted_feature", "another_feature"}, (
        f"AST scanner extracted wrong set: {found!r}"
    )


# ---------------------------------------------------------------------------
# WA2 — price_target in fundamental-1 matrix (Sprint 6 Wave A)
# ---------------------------------------------------------------------------


def test_price_target_supported_on_fundamental_1():
    """price_target must be in _FEATURE_MATRIX['fundamental-1'] so the
    analyst_collector gate at :146 can activate on paid plans.
    Sprint 6 Wave A item 1 (WA2) — source PR #1085 review.
    """
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports
    assert finnhub_plan_supports(
        "price_target",
        {"data_enrichment": {"finnhub_plan": "fundamental-1"}},
    ) is True, (
        "price_target must be supported on fundamental-1 plan. "
        "Add 'price_target' to _FEATURE_MATRIX['fundamental-1'] in "
        "src/data_enrichment/finnhub_plan.py."
    )
