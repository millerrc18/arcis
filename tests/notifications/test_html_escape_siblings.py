"""T13 D4: HTML-escape sibling tests for notify_regime_alert + notify_streak_alert.

Tests:
1. test_notify_regime_alert_escapes_regime_old_and_regime_new
2. test_notify_streak_alert_escapes_status_and_tickers
3. test_sibling_search_no_unescaped_fstrings_in_notify_funcs
4. test_source_tag_column_written_under_pytest
5. test_send_single_is_null_router_under_pytest
"""

import ast
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Test 1 — notify_regime_alert escapes regime_old and regime_new
# ---------------------------------------------------------------------------

def test_notify_regime_alert_escapes_regime_old_and_regime_new():
    """regime_old and regime_new must be HTML-escaped before being placed in the message."""
    from src.notifications.telegram import notify_regime_alert

    captured = {}

    def _stub_send(msg, parse_mode="HTML"):
        captured["msg"] = msg
        return True

    with patch("src.notifications.telegram.send_telegram", side_effect=_stub_send):
        notify_regime_alert(
            vix_now=25.0,
            vix_prev=18.0,
            threshold_crossed=20.0,
            regime_old="<script>alert('xss')</script>",
            regime_new="<b>HACKED</b>",
            qual_old=60,
            qual_new=50,
            sizing_old=100,
            sizing_new=75,
        )

    msg = captured["msg"]
    assert "&lt;script&gt;" in msg, f"Expected &lt;script&gt; in msg, got: {msg}"
    assert "<script>" not in msg, f"Raw <script> must not appear in msg: {msg}"
    assert "&lt;b&gt;HACKED&lt;/b&gt;" in msg, f"Expected escaped <b>HACKED</b> in msg, got: {msg}"


# ---------------------------------------------------------------------------
# Test 2 — notify_streak_alert escapes status and tickers
# ---------------------------------------------------------------------------

def test_notify_streak_alert_escapes_status_and_tickers():
    """risk_governor_status and ticker strings must be HTML-escaped in the message."""
    from src.notifications.telegram import notify_streak_alert

    captured = {}

    def _stub_send(msg, parse_mode="HTML"):
        captured["msg"] = msg
        return True

    with patch("src.notifications.telegram.send_telegram", side_effect=_stub_send):
        notify_streak_alert(
            streak_length=3,
            recent_trades=[("EVIL<>TICKER", 1.0), ("NORM", -2.0)],
            max_drawdown_pct=-5.0,
            risk_governor_status="<b>HACKED</b>",
            historical_max_streak=7,
        )

    msg = captured["msg"]
    assert "&lt;" in msg, f"Expected HTML entity &lt; in msg, got: {msg}"
    assert "<b>HACKED</b>" not in msg, f"Raw <b>HACKED</b> must not appear in msg: {msg}"
    assert "&lt;b&gt;HACKED&lt;/b&gt;" in msg, f"Expected escaped status in msg, got: {msg}"
    assert "EVIL&lt;&gt;TICKER" in msg, f"Expected escaped ticker in msg, got: {msg}"


# ---------------------------------------------------------------------------
# Test 3 — AST sibling-search structural guardrail
# ---------------------------------------------------------------------------

def _load_notify_func_ast_nodes(telegram_path: Path) -> dict:
    """Parse telegram.py and return {func_name: ast.FunctionDef} for every notify_* function."""
    source = telegram_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("notify_"):
            funcs[node.name] = node
    return funcs


def _get_fstring_interpolations(func_node: ast.FunctionDef) -> list:
    """Return list of (lineno, expr_ast) for every FormattedValue in the function's f-strings."""
    hits = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    hits.append((value.lineno if hasattr(value, "lineno") else 0, value.value))
    return hits


def _is_html_escape_call(expr: ast.expr) -> bool:
    """Return True if expr is a Call to _html_escape (possibly with slicing)."""
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Name) and func.id == "_html_escape":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "_html_escape":
            return True
    return False


def _is_format_only_numeric(expr: ast.expr) -> bool:
    """Return True if the expr is used with a purely-numeric format spec (:.Nf, :.Nd, :+.Nf, etc).

    We check the parent FormattedValue's format_spec — but since we receive the
    expr itself, we rely on callers to pass the FormattedValue and check
    the format_spec if present.
    """
    return False


def _is_numeric_literal_or_call(expr: ast.expr) -> bool:
    """Return True for constants (int/float) or numeric method calls (e.g. float(...))."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)):
        return True
    return False


def _is_format_numeric_fv(fv: ast.FormattedValue) -> bool:
    """Return True if the FormattedValue has a numeric format spec like :.Nf, :d, :+.Nf etc.

    Numeric format specs imply the value is a number and cannot contain HTML.
    Examples: .1f, +.2f, .0%, d, :,  etc.
    """
    import re
    if fv.format_spec is None:
        return False
    if not isinstance(fv.format_spec, ast.JoinedStr):
        return False
    spec_parts = fv.format_spec.values
    if not spec_parts:
        return False
    # Collect all constant parts of the format spec string
    spec = "".join(
        p.value for p in spec_parts if isinstance(p, ast.Constant) and isinstance(p.value, str)
    )
    # Numeric format specs end in d, f, F, e, E, g, G, x, X, o, b, or %
    # They may have prefix characters like +, -, space, 0, comma, #
    if re.search(r'[dfeEgGxXob%]$', spec):
        return True
    return False


def _collect_numeric_param_names(func_node: ast.FunctionDef) -> set:
    """Return set of parameter names annotated as int or float in the function signature."""
    numeric_names = set()
    for arg in func_node.args.args:
        ann = arg.annotation
        if ann is None:
            continue
        if isinstance(ann, ast.Name) and ann.id in ("int", "float"):
            numeric_names.add(arg.arg)
        # Handle Optional[int], Optional[float], int | None, float | None
        if isinstance(ann, ast.Subscript):
            if isinstance(ann.slice, ast.Name) and ann.slice.id in ("int", "float"):
                numeric_names.add(arg.arg)
        if isinstance(ann, ast.BinOp):
            for side in (ann.left, ann.right):
                if isinstance(side, ast.Name) and side.id in ("int", "float"):
                    numeric_names.add(arg.arg)
    return numeric_names


def _is_numeric_param_name(expr: ast.expr, numeric_names: set) -> bool:
    """Return True if expr is a Name whose parameter is annotated as int or float."""
    if isinstance(expr, ast.Name) and expr.id in numeric_names:
        return True
    return False


def _is_string_literal_or_ifexp_of_literals(expr: ast.expr) -> bool:
    """Return True if expr is a string constant or a conditional (IfExp) whose
    body and orelse are both string constants (e.g. 'Tighter' if cond else 'Looser').

    These cannot contain HTML injection.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return True
    if isinstance(expr, ast.IfExp):
        if (isinstance(expr.body, ast.Constant) and isinstance(expr.body.value, str)
                and isinstance(expr.orelse, ast.Constant) and isinstance(expr.orelse.value, str)):
            return True
    return False


def test_sibling_search_no_unescaped_fstrings_in_notify_funcs():
    """AST guardrail: every f-string interpolation in notify_regime_alert and
    notify_streak_alert must be wrapped in _html_escape() or be demonstrably safe
    (numeric type annotation, numeric format spec, string literal, or allowlisted
    pre-escaped local variable).

    Scope: these are the two functions patched in T13 D4 (#93, #94). The test
    ensures no future edit to these functions can introduce an unescaped string
    interpolation without this test failing.

    Other notify_* functions are in a different security posture (already tested
    elsewhere, pre-existing code not in this PR's scope) and are audited via
    the sibling-search receipt in the PR body rather than mechanically here.
    """
    # T11 (PR-C): notify_regime_alert + notify_streak_alert moved to
    # telegram_delivery.py when the delivery layer was extracted from
    # telegram.py. Scan the module where they now live so this guardrail
    # stays non-vacuous (it must still iterate the notify_* funcs and catch
    # an unescaped f-string interpolation in their new location).
    delivery_path = (
        Path(__file__).parent.parent.parent
        / "src" / "notifications" / "telegram_delivery.py"
    )
    assert delivery_path.exists(), f"telegram_delivery.py not found at {delivery_path}"

    source = delivery_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Only check the two functions patched in this PR
    target_functions = {"notify_regime_alert", "notify_streak_alert"}

    # Allowlist: local variables that are pre-escaped (built from _html_escape calls).
    # key = func_name, value = set of variable names that are safe.
    # recent_str in notify_streak_alert is built as:
    #   ", ".join(f"{_html_escape(t)} {p:+.1f}%" for t, p in recent_trades[:5])
    # so its content is already escaped — interpolating it without wrapping is safe.
    pre_escaped_locals: dict[str, set] = {
        "notify_streak_alert": {"recent_str"},
    }

    violations = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in target_functions):
            continue
        func_name = node.name
        numeric_params = _collect_numeric_param_names(node)
        safe_locals = pre_escaped_locals.get(func_name, set())
        for fstr_node in ast.walk(node):
            if not isinstance(fstr_node, ast.JoinedStr):
                continue
            for value in fstr_node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue
                fv = value
                expr = fv.value
                # (a) wrapped in _html_escape
                if _is_html_escape_call(expr):
                    continue
                # (b) numeric format spec (:.1f, :d, etc.)
                if _is_format_numeric_fv(fv):
                    continue
                # (c) integer/float constant
                if _is_numeric_literal_or_call(expr):
                    continue
                # (d) parameter annotated as int or float
                if _is_numeric_param_name(expr, numeric_params):
                    continue
                # (e) string literal or ternary of string literals (safe, no HTML)
                if _is_string_literal_or_ifexp_of_literals(expr):
                    continue
                # (f) explicitly allowlisted pre-escaped local variable
                if isinstance(expr, ast.Name) and expr.id in safe_locals:
                    continue
                # Everything else is a violation in these two functions
                lineno = getattr(fv, "lineno", 0)
                violations.append(
                    f"{func_name}:{lineno} — {ast.dump(expr)[:120]}"
                )

    assert violations == [], (
        f"Found {len(violations)} unescaped f-string interpolation(s) in "
        f"{target_functions}:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test 4 — source_tag column written under pytest
# ---------------------------------------------------------------------------

def test_source_tag_column_written_under_pytest():
    """ARCIS_NOTIFICATION_SOURCE env var is set to 'pytest:<worktree>' by the conftest fixture."""
    source = os.environ.get("ARCIS_NOTIFICATION_SOURCE", "")
    assert source.startswith("pytest:"), (
        f"Expected ARCIS_NOTIFICATION_SOURCE to start with 'pytest:', got: {source!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — _send_single is null_router under pytest
# ---------------------------------------------------------------------------

def test_send_single_is_null_router_under_pytest():
    """After the conftest isolation fixture runs, _send_single must be the null router stub."""
    import src.notifications.telegram as tg
    assert tg._send_single.__name__ == "_null_router", (
        f"Expected _send_single.__name__ == '_null_router', got: {tg._send_single.__name__!r}. "
        f"The conftest autouse fixture must monkeypatch _send_single to prevent real Telegram calls."
    )
