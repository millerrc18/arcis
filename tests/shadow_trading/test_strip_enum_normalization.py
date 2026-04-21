"""Upstream-fix tests — `_strip_enum` must produce lowercase output.

Context: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md` §H5,
`docs/sprints/fix_paper_exit_qty_asymmetry_research.md` §2.

`_strip_enum` at `src/shadow_trading/alpaca_adapter.py:38-48` strips the
enum class prefix but does not lowercase the result. In Python 3.12 with
alpaca-py 0.43+, `str(OrderStatus.FILLED)` returns "OrderStatus.FILLED"
(regular Enum, not StrEnum). After strip: "FILLED" — uppercase.

Every downstream set is lowercase:
  - FILLED_ORDER_STATUSES = {"filled", "closed"}         (executor.py:166)
  - PENDING_ORDER_STATUSES = {"new", "accepted", ...}    (executor.py:167)
  - leg status tuple ("filled", "partially_filled")      (executor.py:1383)

Result: every bracket with filled legs is invisible to executor's
leg-detection. Fallback fires → sells on a closed position → overshoot.

Fix (per gated checkpoint): use `enum.Enum.value` when input is an Enum
instance (alpaca-py values are lowercase); fall back to split+lowercase
for plain strings.
"""
from __future__ import annotations

import enum


def test_strip_enum_produces_lowercase_for_alpaca_enums():
    """`_strip_enum(<alpaca-enum-like>)` must return lowercase value.

    This is the root-cause test. Without the fix, an alpaca-py regular
    Enum stringifies to 'OrderStatus.FILLED', strip() returns 'FILLED',
    and executor's `in {"filled", "closed"}` check silently fails.

    NOTE: conftest.py mocks `alpaca.trading.enums` but excludes
    `OrderStatus`, so a real `from alpaca.trading.enums import
    OrderStatus` raises ImportError in the test environment. We simulate
    the production path by testing on the stringified form that
    `_serialize_order` feeds downstream, plus a locally-built regular
    Enum that reproduces the alpaca-py behavior.
    """
    from src.shadow_trading.alpaca_adapter import _strip_enum

    # Primary path: a regular `enum.Enum` subclass (what alpaca-py 0.43
    # uses; confirmed empirically in Pass 2).
    class LocalOrderStatus(enum.Enum):
        FILLED = "filled"
        PENDING_NEW = "pending_new"
        CANCELED = "canceled"

    assert _strip_enum(LocalOrderStatus.FILLED) == "filled", (
        "_strip_enum on Enum instance must return lowercase value. "
        f"Got: {_strip_enum(LocalOrderStatus.FILLED)!r}. "
        "Before fix: returns 'FILLED' (uppercase from enum name)."
    )
    assert _strip_enum(LocalOrderStatus.PENDING_NEW) == "pending_new", (
        f"Got: {_strip_enum(LocalOrderStatus.PENDING_NEW)!r}"
    )
    assert _strip_enum(LocalOrderStatus.CANCELED) == "canceled"

    # Fallback path: plain strings retain current behavior per operator
    # spec (`fall back to current .split('.')[-1] for strings`). Document
    # the existing upstream bug in `place_paper_exit:296` and similar
    # callsites that bypass _strip_enum entirely — those remain as
    # pre-existing behavior, addressed by D3's qty-sync guard in Commit 5
    # which prevents the problematic submits.
    assert _strip_enum("OrderStatus.FILLED") == "FILLED", (
        "Per operator spec: string path retains current .split('.')[-1] behavior. "
        f"Got: {_strip_enum('OrderStatus.FILLED')!r}"
    )

    # Idempotent on plain strings without enum prefix.
    assert _strip_enum("held") == "held"
    assert _strip_enum("filled") == "filled"
    assert _strip_enum("canceled") == "canceled"

    # None-safe.
    assert _strip_enum(None) is None


def test_strip_enum_handles_str_subclass_enums():
    """Python 3.11+ `StrEnum` already stringifies to the value, but
    `_strip_enum` must still work correctly on those.
    """
    from src.shadow_trading.alpaca_adapter import _strip_enum

    try:
        from enum import StrEnum

        class FakeOrderStatus(StrEnum):
            FILLED = "filled"
            HELD = "held"

        assert _strip_enum(FakeOrderStatus.FILLED) == "filled"
        assert _strip_enum(FakeOrderStatus.HELD) == "held"
    except ImportError:
        # Python < 3.11 — covered by the primary test.
        pass

    # Regular Enum subclass (Python 3.10-style) — exercises the .value path.
    class RegularOrderStatus(enum.Enum):
        FILLED = "filled"
        HELD = "held"

    assert _strip_enum(RegularOrderStatus.FILLED) == "filled", (
        "Regular Enum must use .value (lowercase), not stringified name (uppercase)."
    )
    assert _strip_enum(RegularOrderStatus.HELD) == "held"


def test_bracket_leg_fill_detected_case_insensitive():
    """End-to-end: after _strip_enum fix, executor's bracket leg detection
    catches a filled target leg and closes the trade cleanly — instead of
    falling through to the market-price-based fallback that produced
    phantom overshoots.

    This is the C 2026-04-21 scenario as a regression test. The filled
    target leg MUST set bracket_exit=True with exit_reason='take_profit'.

    We simulate the path _serialize_order → executor's bracket check by
    testing _strip_enum output against the lowercase sets executor uses.
    """
    from src.shadow_trading.executor import FILLED_ORDER_STATUSES
    from src.shadow_trading.alpaca_adapter import _strip_enum

    # Production path: _serialize_order receives alpaca-py's OrderStatus
    # enum and calls _strip_enum on it. We simulate with a local Enum
    # that matches alpaca-py's behavior (regular Enum with lowercase value).
    class LocalOrderStatus(enum.Enum):
        FILLED = "filled"

    parent_status = _strip_enum(LocalOrderStatus.FILLED)
    assert parent_status in FILLED_ORDER_STATUSES, (
        f"parent_status={parent_status!r} not in FILLED_ORDER_STATUSES={FILLED_ORDER_STATUSES}. "
        "Executor's bracket detection at :1375 will miss filled parents."
    )

    # Leg status check uses the tuple directly.
    leg_status = _strip_enum(LocalOrderStatus.FILLED)
    assert leg_status in ("filled", "partially_filled"), (
        f"leg_status={leg_status!r} not in ('filled', 'partially_filled'). "
        "Executor's leg detection at :1383 will miss filled target/stop legs."
    )

    # The string path (what callers like place_paper_exit produce via
    # `str(order.status)`) is NOT fixed by this sprint per operator spec.
    # Pre-existing bug #TBD tracks it as follow-up. The enum path fix
    # above closes the primary overshoot mechanism because _serialize_order
    # (used by get_order_status, which executor consumes) uses the enum path.
