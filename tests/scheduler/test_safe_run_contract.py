"""Phase 5 PR-G T37 sentinel (c): the WatchLoop._safe_run -> CollectorResult
source-level contract (PR-D T19 flip regression guard).

PR-D / #72 / T19 (DD-15 r3) flipped ``WatchLoop._safe_run`` from returning a
bare ``bool`` to returning a ``CollectorResult`` so gating done-flag callers
branch on ``.is_healthy`` (CLAUDE.md §207) instead of object truthiness. The
behavioral side of that flip is exercised in
``tests/scheduler/test_safe_run_collector_result.py`` (it calls ``_safe_run``
and asserts the returned value's type/status/health).

This file is the *static contract* guard: it asserts, by AST inspection of
``src/scheduler/watch.py`` (no import, no execution), that the method's return
annotation is literally ``CollectorResult``. A revert of the annotation back to
``bool`` — the exact T19 regression — is caught here even if the runtime body
were also reverted in a way that happened to keep the behavioral tests' fakes
green. The two layers are complementary: behavior + declared contract.

Why AST not runtime: ``watch.py`` is a 2700+ line module whose import pulls a
heavy dependency graph; reading the annotation off the parsed tree keeps this
sentinel fast, hermetic, and free of DB/env coupling. It also pins the
*declared* contract independently of the implementation, which is what a
regression guard for an API flip should do.

Verify-by-mutation (Q5): the helper ``_safe_run_return_annotation`` returns the
annotation string for any (source, class, method) triple. The negative test
below feeds it a synthesized ``-> bool`` source and asserts the contract check
would FAIL — proving the sentinel is non-vacuous and would catch the revert.
There is no entry in config/known_violations.json for this contract; it must
hold on the real tree.
"""

import ast
from pathlib import Path

WATCH_PATH = Path("src/scheduler/watch.py")


def _safe_run_return_annotation(source: str, class_name: str, method_name: str) -> str | None:
    """Return the unparsed return-annotation of ``class_name.method_name`` in
    ``source``, or None if the method (or its annotation) is absent.

    Walks only top-level classes and their direct method defs — ``_safe_run``
    is a direct method of ``WatchLoop``. Handles both ``ast.Name`` annotations
    (``-> CollectorResult``) and ``ast.Constant`` string-forward-refs
    (``-> "CollectorResult"``) by unparsing and stripping surrounding quotes.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    if item.returns is None:
                        return None
                    rendered = ast.unparse(item.returns)
                    return rendered.strip().strip('"').strip("'")
    return None


def test_safe_run_declares_collector_result_return():
    """Sentinel (c): WatchLoop._safe_run is annotated ``-> CollectorResult``.

    This is the static half of the T19 contract flip (PR-D). It reads the
    return annotation directly off the AST of src/scheduler/watch.py without
    importing the module. A revert to ``-> bool`` (the pre-flip shape) fails
    this assertion.

    Verified non-vacuous (verify-by-mutation, Q5) in
    test_safe_run_contract_rule_detects_violation below: a synthesized
    ``-> bool`` source makes the same check FAIL, while the real-tree
    ``-> CollectorResult`` PASSES here.
    """
    annotation = _safe_run_return_annotation(
        WATCH_PATH.read_text(encoding="utf-8"), "WatchLoop", "_safe_run"
    )
    assert annotation == "CollectorResult", (
        f"WatchLoop._safe_run must be annotated `-> CollectorResult` (PR-D T19 "
        f"flip, DD-15 r3); got {annotation!r}. Reverting to `-> bool` reopens "
        f"the #623-class silent-failure regression — gating callers branch on "
        f".is_healthy, which a bool cannot carry."
    )


def test_safe_run_contract_rule_detects_violation():
    """Sentinel-of-the-sentinel: the annotation check FAILS on a ``-> bool``
    method and PASSES on a ``-> CollectorResult`` method.

    Verify-by-mutation (Q5): drives ``_safe_run_return_annotation`` with two
    synthesized in-memory sources — one declaring the pre-flip ``-> bool``
    shape, one declaring the post-flip ``-> CollectorResult`` shape — and
    asserts the contract predicate (``== "CollectorResult"``) rejects the
    former and accepts the latter. Never reads or writes the real watch.py.
    """
    reverted = (
        "class WatchLoop:\n"
        "    def _safe_run(self, name, func) -> bool:\n"
        "        return True\n"
    )
    assert _safe_run_return_annotation(reverted, "WatchLoop", "_safe_run") != "CollectorResult", (
        "Mutation check broken: a `-> bool` annotation must NOT satisfy the "
        "CollectorResult contract"
    )

    flipped = (
        "class WatchLoop:\n"
        '    def _safe_run(self, name, func) -> "CollectorResult":\n'
        "        ...\n"
    )
    assert _safe_run_return_annotation(flipped, "WatchLoop", "_safe_run") == "CollectorResult", (
        "Mutation check broken: a `-> CollectorResult` annotation (string "
        "forward-ref) must satisfy the contract"
    )
