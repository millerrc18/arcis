"""W21 P1-NEW-1 + P1-NEW-2 regression-locks for exit_reason vocab.

Two new controlled-vocabulary terms added in v0.36.17:

- `position_already_closed` (P1-NEW-2): Alpaca returns 'position already
  closed at broker' when an exit fires on a position that's gone.
  Pre-fix, `coerce_exit_reason` silently mapped this to 'unknown',
  losing the specific broker signal.

- `duplicate_orphan_backfill` (P1-NEW-1): used when cleaning up
  duplicate shadow_trades created by the reconciler's orphan-backfill
  race with the premature-exit-revert path.

Both should also appear in:
- `EXCLUDED_FROM_OUTCOME_STATS` (no real broker fill on our side)
- `src/evaluation/cto_report._UNMEASURABLE_EXIT_REASONS` (audit filter)
- `src/evaluation/model_monitor._UNMEASURABLE_EXIT_REASONS` (canary stats)
"""

import os


_EXIT_REASON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "shadow_trading", "exit_reason.py",
)
_CTO_REPORT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "evaluation", "cto_report.py",
)
_MODEL_MONITOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "evaluation", "model_monitor.py",
)


def test_position_already_closed_in_controlled_vocab():
    """`position_already_closed` must be in CONTROLLED_VOCAB."""
    from src.shadow_trading.exit_reason import CONTROLLED_VOCAB
    assert "position_already_closed" in CONTROLLED_VOCAB, (
        "W21 P1-NEW-2: 'position_already_closed' must be in CONTROLLED_VOCAB "
        "so coerce_exit_reason() preserves it instead of mapping to 'unknown'."
    )


def test_duplicate_orphan_backfill_in_controlled_vocab():
    """`duplicate_orphan_backfill` must be in CONTROLLED_VOCAB."""
    from src.shadow_trading.exit_reason import CONTROLLED_VOCAB
    assert "duplicate_orphan_backfill" in CONTROLLED_VOCAB, (
        "W21 P1-NEW-1: 'duplicate_orphan_backfill' must be in CONTROLLED_VOCAB "
        "so cleanup ops can use it without coerce_exit_reason mapping to 'unknown'."
    )


def test_both_new_terms_excluded_from_outcome_stats():
    """Both new vocab terms represent synthetic closures and must NOT contribute to outcome stats."""
    from src.shadow_trading.exit_reason import EXCLUDED_FROM_OUTCOME_STATS
    assert "position_already_closed" in EXCLUDED_FROM_OUTCOME_STATS, (
        "W21 P1-NEW-2: 'position_already_closed' has no broker fill on our "
        "side; must be excluded from win-rate/profit-factor aggregations."
    )
    assert "duplicate_orphan_backfill" in EXCLUDED_FROM_OUTCOME_STATS, (
        "W21 P1-NEW-1: 'duplicate_orphan_backfill' is a synthetic close; "
        "must be excluded from outcome stats."
    )


def test_both_new_terms_in_cto_report_unmeasurable():
    """Both new terms must be in `cto_report._UNMEASURABLE_EXIT_REASONS`."""
    with open(_CTO_REPORT_PATH, encoding="utf-8") as f:
        source = f.read()
    # Find the _UNMEASURABLE_EXIT_REASONS block
    idx = source.find("_UNMEASURABLE_EXIT_REASONS = frozenset")
    assert idx > 0, "_UNMEASURABLE_EXIT_REASONS not found in cto_report.py"
    # Slice the frozenset block (should be within 1000 chars)
    block = source[idx:idx + 1000]
    end_idx = block.find("})")
    assert end_idx > 0
    block = block[:end_idx]
    assert '"position_already_closed"' in block, (
        "cto_report._UNMEASURABLE_EXIT_REASONS must include 'position_already_closed'"
    )
    assert '"duplicate_orphan_backfill"' in block, (
        "cto_report._UNMEASURABLE_EXIT_REASONS must include 'duplicate_orphan_backfill'"
    )


def test_both_new_terms_in_model_monitor_unmeasurable():
    """Both new terms must be in `model_monitor._UNMEASURABLE_EXIT_REASONS`."""
    with open(_MODEL_MONITOR_PATH, encoding="utf-8") as f:
        source = f.read()
    idx = source.find("_UNMEASURABLE_EXIT_REASONS = frozenset")
    assert idx > 0, "_UNMEASURABLE_EXIT_REASONS not found in model_monitor.py"
    block = source[idx:idx + 1000]
    end_idx = block.find("})")
    assert end_idx > 0
    block = block[:end_idx]
    assert '"position_already_closed"' in block
    assert '"duplicate_orphan_backfill"' in block


def test_coerce_preserves_new_vocab_terms():
    """coerce_exit_reason() returns the same value (not 'unknown') for the new terms."""
    from src.shadow_trading.exit_reason import coerce_exit_reason
    assert coerce_exit_reason("position_already_closed", ticker="TEST") == "position_already_closed"
    assert coerce_exit_reason("duplicate_orphan_backfill", ticker="TEST") == "duplicate_orphan_backfill"
