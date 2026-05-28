"""Load-bearing coverage-matrix contract test (#115 T14 — DD-08 + DD-16 + DA-MAJ-4).

Enforces the email aggregator routing surface as a regression guard:

  1. ``EVENT_TO_TIER`` in ``src.notifications.email_digest`` matches the
     spec-declared event→tier mapping (Section 7.1) exactly — no drift,
     no extras, no missing keys.
  2. Every ``send_email(...)`` call site in ``src/`` is justified — either
     it lives in the aggregator's own ``_dispatch_tier`` or it is listed in
     ``BYPASS_ALLOWLIST`` with an explicit rationale (DD-13 CLI carve-out,
     DD-14 telegram-fail escalation, DD-20 hold-over, DD-30 ImportError
     fallback).
  3. ``CARVE_OUT_TYPES`` includes the two spec-mandated carve-outs.
  4. Every constant-literal ``enqueue_for_email_digest(event_type='X', ...)``
     emit-site in ``src/`` references an event_type registered in
     ``EVENT_TO_TIER`` (no orphan emits).

Implementation note (DA-MAJ-4 platform fix): AST-based, NOT
subprocess(grep). The original DA-MAJ-4 review caught that ``grep`` is a
GNU coreutil unavailable on Windows by default, which would have made
this regression guard a no-op on the operator's primary dev box.
``ast.parse`` ships with the Python stdlib and is platform-independent.

Allowlist granularity is ``(file_path, function_name)`` tuples — DA-MAJ-4
noted that file-level allowlists are too coarse (a new offender added to
an allowlisted file would slip through silently).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# ── Spec contracts (load-bearing — match Section 7.1 of the design doc) ─────

EXPECTED_EVENT_TO_TIER: dict[str, str] = {
    'audit_critical':            'preopen',
    'audit_alert':               'postclose',
    'audit_red_assessment':      'postclose',
    'morning_watchlist':         'preopen',
    'action_packet':             'postclose',
    'eod_recap_email':           'postclose',
    'premarket_content':         'preopen',
    'midday_content':            'postclose',
    'eod_content':               'postclose',
    'evening_content':           'postclose',
    'weekly_digest_content':     'weekly',
    'saturday_training_report':  'weekly',
    'saturday_cto_report':       'weekly',
    'research_synthesis_email':  'weekly',
}


# (file_path_posix, function_name) → rationale. function_name=None means
# "any module-level send_email call site". File paths use forward slashes
# so the contract is identical on Windows + POSIX.
BYPASS_ALLOWLIST: dict[tuple[str, str | None], str] = {
    # ── DD-13 CLI carve-outs (operator-invoked immediate send) ──
    # Phase 5 PR-C T13: cmd_send_test_email moved to commands_ops.py and
    # cmd_cto_report to commands_training.py during the category split.
    ('src/cli/commands_ops.py', 'cmd_send_test_email'):
        'CLI carve-out (DD-13) — `arcis send-test-email` operator command',
    ('src/cli/commands_training.py', 'cmd_cto_report'):
        'CLI carve-out (DD-13) — `arcis cto-report --email` operator command',

    # ── DD-14 escalated-telegram-fail carve-out ──
    ('src/notifications/telegram.py', '_do_dispatch_escalated'):
        'TG-fail escalation carve-out (DD-14) — immediate email when telegram channel is down',

    # ── Implementation + re-export (these are not "callers", they ARE the symbol) ──
    ('src/email/notifier.py', 'send_email'):
        'implementation — defines the send_email function itself',
    ('src/email/__init__.py', None):
        're-export — `from src.email.notifier import send_email`',

    # ── Aggregator's own dispatcher ──
    ('src/notifications/email_digest.py', '_dispatch_tier'):
        'aggregator (DD-29) — the email_digest module dispatching a rendered tier digest',

    # ── DD-30 ImportError-fallback sites (firehose mode when email_digest module fails to load) ──
    ('src/evaluation/auditor.py', 'check_escalation'):
        'DD-30 ImportError fallback + DD-01 CRITICAL hybrid immediate send (check_escalation)',
    ('src/scheduler/overnight.py', '_route_email_via_digest'):
        'DD-30 ImportError fallback + DD-20 shadow/time_aligned dual-write (overnight router)',
    ('src/scheduler/watch.py', '_route_email_via_digest'):
        'DD-30 ImportError fallback + DD-20 shadow/time_aligned dual-write (watch router)',
    ('src/scheduler/reports.py', '_route_morning_watchlist_email'):
        'DD-30 ImportError fallback + DD-20 shadow/time_aligned dual-write (reports router)',
    ('src/services/watchlist_service.py', '_route_email_or_enqueue'):
        'DD-30 ImportError fallback + DD-13 via_cli direct-send (watchlist service router)',
    ('src/services/recap_service.py', '_route_email_or_enqueue'):
        'DD-30 ImportError fallback + DD-13 via_cli direct-send (recap service router)',
    ('src/services/scan_service.py', '_route_packet_email'):
        'DD-30 ImportError fallback + DD-13 via_cli direct-send (scan service router)',

    # ── DD-13 via_cli passthrough (operator-invoked immediate send via run_morning_watchlist) ──
    ('src/scheduler/reports.py', 'run_morning_watchlist'):
        'via_cli direct-send passthrough (DD-13) — operator-invoked morning watchlist',

    # ── DD-20 legacy 4-slot digest_builder hold-over (suppressed by mode) ──
    ('src/scheduler/watch.py', '_check_legacy_digest_schedule'):
        'DD-20 legacy digest_builder hold-over — fires only when hold-over mode permits',
}


# ── AST helpers ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / 'src'


def _resolve_callee(node: ast.AST) -> str | None:
    """Return the callable's local name for ast.Name / ast.Attribute, else None.

    Examples:
        ast.Name('send_email')                       → 'send_email'
        ast.Attribute(value=ast.Name('mod'), attr='send_email') → 'send_email'
        ast.Call(...)                                → None  (chained call)
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _SendEmailCallFinder(ast.NodeVisitor):
    """Collects every send_email(...) call site with its enclosing function.

    Tracks (Async)FunctionDef stack so nested defs report the *innermost*
    function name. Calls outside any function are reported with name=None.
    """

    def __init__(self, file_path_posix: str) -> None:
        self.file_path_posix = file_path_posix
        self._fn_stack: list[str] = []
        self.calls: list[tuple[str, str | None, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if _resolve_callee(node.func) == 'send_email':
            fn = self._fn_stack[-1] if self._fn_stack else None
            self.calls.append((self.file_path_posix, fn, node.lineno))
        self.generic_visit(node)


class _EnqueueEventTypeFinder(ast.NodeVisitor):
    """Collects every constant-literal event_type passed to enqueue_for_email_digest."""

    def __init__(self, file_path_posix: str) -> None:
        self.file_path_posix = file_path_posix
        self.events: list[tuple[str, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _resolve_callee(node.func) == 'enqueue_for_email_digest':
            event_type: str | None = None
            # Positional: enqueue_for_email_digest('audit_critical', ...)
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    event_type = first.value
            # Kwarg form: enqueue_for_email_digest(event_type='audit_critical', ...)
            for kw in node.keywords:
                if kw.arg == 'event_type' and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        event_type = kw.value.value
            if event_type is not None:
                self.events.append((self.file_path_posix, node.lineno, event_type))
        self.generic_visit(node)


def _iter_src_py_files() -> list[Path]:
    return sorted(p for p in _SRC_ROOT.rglob('*.py'))


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError:
        return None


def _posix_rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


# ── Tests ───────────────────────────────────────────────────────────────────

def test_coverage_matrix_complete() -> None:
    """``EVENT_TO_TIER`` keys + values match the spec exactly (Section 7.1)."""
    from src.notifications import email_digest

    actual = email_digest.EVENT_TO_TIER
    actual_keys = set(actual)
    expected_keys = set(EXPECTED_EVENT_TO_TIER)

    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    mismatched = {
        k: (actual[k], EXPECTED_EVENT_TO_TIER[k])
        for k in actual_keys & expected_keys
        if actual[k] != EXPECTED_EVENT_TO_TIER[k]
    }

    msg_parts: list[str] = []
    if missing:
        msg_parts.append(f'MISSING from EVENT_TO_TIER: {sorted(missing)}')
    if extra:
        msg_parts.append(f'EXTRA in EVENT_TO_TIER (not in spec): {sorted(extra)}')
    if mismatched:
        details = ', '.join(
            f'{k!r}: actual={a!r} expected={e!r}'
            for k, (a, e) in sorted(mismatched.items())
        )
        msg_parts.append(f'TIER VALUE MISMATCH: {details}')

    assert not msg_parts, (
        'EVENT_TO_TIER drift from spec Section 7.1:\n  '
        + '\n  '.join(msg_parts)
    )


def test_coverage_matrix_no_extra_entries_in_event_to_tier() -> None:
    """Symmetric guard — production EVENT_TO_TIER MUST NOT contain entries
    absent from the spec-declared expected map.

    Redundant with test_coverage_matrix_complete's `extra` branch, but a
    standalone assertion gives a clearer failure surface when only the
    extras-direction drift occurs (e.g., a developer adding a new event
    without updating the spec + this test).
    """
    from src.notifications import email_digest

    extras = set(email_digest.EVENT_TO_TIER) - set(EXPECTED_EVENT_TO_TIER)
    assert not extras, (
        'EVENT_TO_TIER contains event_types not declared in the spec '
        f'(Section 7.1): {sorted(extras)}. Either remove the entry or '
        'update EXPECTED_EVENT_TO_TIER + Section 7.1.'
    )


def test_carve_outs_listed() -> None:
    """``CARVE_OUT_TYPES`` contains the two spec-mandated carve-outs (DD-01, DD-14)."""
    from src.notifications import email_digest

    co = email_digest.CARVE_OUT_TYPES
    assert 'audit_critical' in co, (
        "CARVE_OUT_TYPES missing 'audit_critical' (DD-01 hybrid carve-out)"
    )
    assert 'escalated_telegram_fail' in co, (
        "CARVE_OUT_TYPES missing 'escalated_telegram_fail' (DD-14 carve-out)"
    )


def test_no_orphan_send_email_call_sites() -> None:
    """Every send_email(...) call site in src/ MUST be in BYPASS_ALLOWLIST.

    AST-based (NOT subprocess(grep) per DA-MAJ-4 platform fix). Walks every
    .py file under src/, finds every ast.Call whose callee resolves to
    'send_email' (ast.Name or ast.Attribute), and asserts the
    (file, enclosing_function) pair has an explicit allowlist entry.
    """
    offenders: list[tuple[str, str | None, int]] = []
    for path in _iter_src_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = _posix_rel(path)
        finder = _SendEmailCallFinder(rel)
        finder.visit(tree)
        for call in finder.calls:
            file_path, fn_name, lineno = call
            key = (file_path, fn_name)
            if key in BYPASS_ALLOWLIST:
                continue
            offenders.append(call)

    if offenders:
        formatted = '\n  '.join(
            f'{f}:{ln}  (enclosing function: {fn!r})'
            for f, fn, ln in offenders
        )
        pytest.fail(
            f'Found {len(offenders)} unauthorized send_email(...) call site(s) '
            'outside BYPASS_ALLOWLIST. Each call site MUST route through '
            'enqueue_for_email_digest() or be explicitly justified in the '
            'BYPASS_ALLOWLIST with a rationale:\n  ' + formatted
        )


def test_event_types_emitted_match_registered() -> None:
    """Every constant-literal event_type emitted via enqueue_for_email_digest
    MUST be registered in EVENT_TO_TIER.

    Catches the orphan-emit class of bugs where a caller passes
    e.g. ``enqueue_for_email_digest('newly_added_event', ...)`` but the
    aggregator's routing dict was never updated — flush_tier would then
    skip the row silently because no tier owns it.

    Handles both positional and kwarg forms:
        enqueue_for_email_digest('audit_critical', ...)        # positional
        enqueue_for_email_digest(event_type='audit_critical', ...)  # kwarg

    Variable-passed event_types (e.g. routing helpers that forward a
    parameter) are not detectable via static AST — they're covered by
    the upstream callers' tests.
    """
    from src.notifications import email_digest

    registered = set(email_digest.EVENT_TO_TIER)
    orphans: list[tuple[str, int, str]] = []
    for path in _iter_src_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = _posix_rel(path)
        finder = _EnqueueEventTypeFinder(rel)
        finder.visit(tree)
        for site in finder.events:
            _, _, event_type = site
            if event_type not in registered:
                orphans.append(site)

    if orphans:
        formatted = '\n  '.join(
            f'{f}:{ln}  enqueue_for_email_digest(event_type={ev!r}, ...) '
            '— not in EVENT_TO_TIER'
            for f, ln, ev in orphans
        )
        pytest.fail(
            f'Found {len(orphans)} orphan enqueue_for_email_digest emit '
            'site(s) referencing event_types not registered in '
            'EVENT_TO_TIER:\n  ' + formatted
        )
