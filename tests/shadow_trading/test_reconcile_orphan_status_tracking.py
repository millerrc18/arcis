"""W21 P1-NEW-1 regression-lock: orphan-check must consider exit_failed/exit_pending.

Background:
  On 2026-05-18 09:32 ET, ETN had a shadow_trade `90f28c15` briefly in
  `status='exit_failed'` between 09:31:17 (exit attempt collided with
  active bracket) and 09:32:16 (reconciler reverted premature exit). A
  reconciler scan at 09:32:09 didn't see `90f28c15` in tracked_map
  (because the pre-fix query filtered by `status='open'` only), marked
  ETN as orphan, and created duplicate shadow_trade `465b63ed`.

The fix in `src/shadow_trading/reconcile.py:reconcile_paper_trades()`
extends the tracked-status filter to include `exit_failed`,
`exit_pending`. This prevents the race-condition duplicate.

These are file-content regression-locks. Behavioral testing of the full
reconcile flow requires substantial fixture infrastructure (Alpaca mock
+ sqlite DB with multi-trade lifecycle) — that's appropriate scope for
a future refactor, not for a P1 hotfix.
"""

import os


_RECONCILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "shadow_trading", "reconcile.py",
)


def _load_source() -> str:
    with open(_RECONCILE_PATH, encoding="utf-8") as f:
        return f.read()


def test_orphan_check_includes_exit_failed_in_tracked_statuses():
    """The orphan-check tracked-statuses set MUST include exit_failed."""
    source = _load_source()
    # The fix uses `status IN ('open', 'exit_failed', 'exit_pending')`
    assert "status IN " in source, (
        "reconcile.py orphan-check tracked query must use IN clause for statuses"
    )
    assert "'exit_failed'" in source, (
        "reconcile.py orphan-check must include 'exit_failed' in tracked "
        "statuses (W21 P1-NEW-1). Without this, a trade briefly in "
        "exit_failed during the premature-exit-revert path becomes "
        "invisible to orphan detection and a duplicate row gets created."
    )
    assert "'exit_pending'" in source, (
        "reconcile.py orphan-check must also include 'exit_pending' for "
        "the same reason — exit_pending is the analogous pre-resolution "
        "state."
    )


def test_orphan_check_does_not_include_submission_uncertain():
    """The orphan-check must NOT include 'submission_uncertain' — that's
    a different code path (the submission_uncertain resolver), and
    including it would regress test_uncertain_trade_marked_failed_when_alpaca_has_no_position.
    """
    source = _load_source()
    # Locate the orphan-check tracked query. The SQL spans two adjacent
    # Python string literals due to line-wrapping, so we look for the
    # 'exit_failed' literal that's only in the orphan-check query
    # (verified via comment scoping in reconcile.py).
    idx = source.find("'exit_failed', 'exit_pending'")
    assert idx > 0, "orphan-check tracked query with new W21 statuses not found"
    # Look 200 chars before and after for the surrounding context
    window = source[max(0, idx - 100):idx + 200]
    assert "submission_uncertain" not in window, (
        "orphan-check status set must NOT include 'submission_uncertain' — "
        "that's handled by a separate resolver and inclusion here would "
        "regress test_uncertain_trade_marked_failed_when_alpaca_has_no_position."
    )
