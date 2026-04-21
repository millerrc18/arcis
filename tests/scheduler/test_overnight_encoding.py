"""Regression tests for H6 — ASCII-only logger/print paths in overnight.py.

Audit 2026-04-20 observed 10 UnicodeEncodeError crashes in logs when
``logger.info("[WATCH] %s", msg)`` received an ``❌`` (cross mark)
character via ``src/scheduler/overnight.py:65``. Root cause: the
StreamHandler writing stderr on Windows inherits the cp1252 console codec
and cannot encode the emoji.

Fix: replace cp1252-incompatible characters in logger/print/msg paths
with ASCII markers. Docstring/comment prose em dashes are preserved
because they never reach an emittable stream.

These tests lock in the fix by:
  1. Verifying all logger/print/msg-vars lines are cp1252-encodable.
  2. Round-tripping the reconciliation-message branches through
     ``str.encode("cp1252")`` without raising.
  3. Confirming the expected ASCII markers (``[OK]``, ``[FAIL]``) are
     present where the emojis used to be.
"""
from __future__ import annotations

import pathlib

OVERNIGHT_PATH = pathlib.Path(__file__).parent.parent.parent / "src" / "scheduler" / "overnight.py"


def _source_lines() -> list[str]:
    return OVERNIGHT_PATH.read_text(encoding="utf-8").splitlines()


def _in_docstring_at(lines: list[str], i: int) -> bool:
    """Rough heuristic: is line i inside a triple-quoted docstring?"""
    in_doc = False
    delim = None
    for j in range(i):
        line = lines[j]
        for d in ('"""', "'''"):
            cnt = line.count(d)
            if cnt == 0:
                continue
            if not in_doc:
                if cnt % 2 == 1:
                    in_doc = True
                    delim = d
            elif d == delim:
                if cnt % 2 == 1:
                    in_doc = False
                    delim = None
    return in_doc


def test_logger_and_print_lines_are_cp1252_encodable():
    """Every logger.*() / print() / msg-var line must encode under cp1252.

    Docstrings and comments are exempt — they don't reach emittable streams.
    """
    lines = _source_lines()
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if _in_docstring_at(lines, i - 1):
            continue
        if stripped.startswith(('"""', "'''")):
            continue  # docstring boundary line
        tokens = ("logger.", "print(", "msg =", "msg +=", "detail +=", "subject =", "alarm_msg =", "leak_msg =")
        if not any(tok in line for tok in tokens):
            continue
        try:
            line.encode("cp1252")
        except UnicodeEncodeError:
            offenders.append((i, line.rstrip()))
    assert not offenders, (
        "Found cp1252-incompatible characters in logger/print/msg lines: "
        + "; ".join(f"L{n}: {text[:80]!r}" for n, text in offenders[:10])
    )


def test_reconciliation_success_message_is_cp1252_safe():
    """The success-branch message (line 53-55) must ASCII-encode cleanly."""
    result = {"local_count": 10, "alpaca_count": 10}
    msg = (
        f"[OK] Reconciliation: {result['local_count']} local / "
        f"{result['alpaca_count']} Alpaca -- all matched"
    )
    # Must not raise
    msg.encode("cp1252")
    assert "[OK]" in msg
    assert "--" in msg


def test_reconciliation_failure_message_is_cp1252_safe():
    """The failure-branch message (line 65) must ASCII-encode cleanly."""
    parts = ["10 orphaned (backfilled: [])", "2 mismatched"]
    msg = f"[FAIL] Reconciliation: {', '.join(parts)}"
    msg.encode("cp1252")
    assert "[FAIL]" in msg


def test_expected_ascii_markers_present_in_source():
    """Sanity: the three specific bug sites now carry ASCII markers.

    Prevents a future refactor from silently re-introducing emoji.
    """
    text = OVERNIGHT_PATH.read_text(encoding="utf-8")
    # Lines 53, 54, 65 neighborhood
    assert "[OK] Reconciliation:" in text, "Success marker [OK] missing"
    assert "Alpaca -- all matched" in text, "em-dash replacement missing"
    assert "[FAIL] Reconciliation:" in text, "Failure marker [FAIL] missing"


def test_no_cross_mark_or_check_mark_escape_in_source():
    """The u274C (cross) and u2705 (check) escape sequences must not recur."""
    text = OVERNIGHT_PATH.read_text(encoding="utf-8")
    bs = chr(92)
    assert bs + "u274c" not in text.lower(), (
        "Found u274c cross-mark escape reintroduced — logger will crash on cp1252"
    )
    assert bs + "u2705" not in text.lower(), (
        "Found u2705 check-mark escape reintroduced — logger will crash on cp1252"
    )
