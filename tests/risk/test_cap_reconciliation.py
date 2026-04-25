"""T1.04 — Cap reconciliation across 4 namespaces.

The effective open-position cap must be the MIN of the present caps from:
  1. risk.max_open_positions
  2. risk_governor.max_open_positions
  3. live_trading.max_open_positions
  4. bootcamp.max_positions

If none are present, fall back to default 10. Both
``RiskGovernor.__init__`` and ``shadow_trading.executor._governor_cap``
must read through the same helper so all governor surfaces agree.

Pre-T1.04 divergence: ``RiskGovernor.__init__`` read only
``risk_governor.max_open_positions``; ``executor._governor_cap`` read
only ``bootcamp.*`` then min(``risk.max_open_positions``,
``shadow_trading.max_positions``); ``live_trading.max_open_positions``
was completely ignored. This caused live trading to silently exceed
the live cap when bootcamp was on.
"""
from __future__ import annotations

import itertools

import pytest


# All 16 combinations of presence (True/False) for the 4 cap namespaces.
NAMESPACES = (
    "risk",            # risk.max_open_positions
    "risk_governor",   # risk_governor.max_open_positions
    "live_trading",    # live_trading.max_open_positions
    "bootcamp",        # bootcamp.max_positions
)


def _build_config(present: dict[str, int | None]) -> dict:
    """Build a synthetic config with caps only where the dict has int values."""
    cfg: dict = {}
    if present.get("risk") is not None:
        cfg["risk"] = {"max_open_positions": present["risk"]}
    if present.get("risk_governor") is not None:
        cfg["risk_governor"] = {"max_open_positions": present["risk_governor"]}
    if present.get("live_trading") is not None:
        cfg["live_trading"] = {"max_open_positions": present["live_trading"]}
    if present.get("bootcamp") is not None:
        cfg["bootcamp"] = {"max_positions": present["bootcamp"]}
    return cfg


@pytest.mark.parametrize("mask", list(itertools.product([False, True], repeat=4)))
def test_effective_position_cap_min_of_present(mask):
    """For all 16 masks, helper returns min of present caps (or 10 if none)."""
    from src.risk.governor import effective_position_cap

    # Distinct values per namespace so min selection is unambiguous.
    distinct_values = {"risk": 5, "risk_governor": 50, "live_trading": 7, "bootcamp": 20}
    present: dict[str, int | None] = {}
    for ns, is_present in zip(NAMESPACES, mask):
        present[ns] = distinct_values[ns] if is_present else None

    cfg = _build_config(present)
    result = effective_position_cap(cfg)

    present_values = [v for v in present.values() if v is not None]
    expected = min(present_values) if present_values else 10
    assert result == expected, (
        f"mask={mask} present={present} cfg={cfg} expected={expected} got={result}"
    )


def test_effective_position_cap_all_four_present_returns_min():
    from src.risk.governor import effective_position_cap

    cfg = {
        "risk": {"max_open_positions": 5},
        "risk_governor": {"max_open_positions": 50},
        "live_trading": {"max_open_positions": 7},
        "bootcamp": {"max_positions": 20},
    }
    assert effective_position_cap(cfg) == 5


def test_effective_position_cap_only_one_present_returns_that_value():
    from src.risk.governor import effective_position_cap

    cfg = {"live_trading": {"max_open_positions": 3}}
    assert effective_position_cap(cfg) == 3


def test_effective_position_cap_none_present_returns_default_10():
    from src.risk.governor import effective_position_cap

    assert effective_position_cap({}) == 10


def test_effective_position_cap_ignores_non_positive_and_non_int():
    """Zero, negative, None, and non-int caps must be ignored, not crash."""
    from src.risk.governor import effective_position_cap

    cfg = {
        "risk": {"max_open_positions": 0},          # invalid -> ignored
        "risk_governor": {"max_open_positions": -1},  # invalid -> ignored
        "live_trading": {"max_open_positions": "foo"},  # invalid -> ignored
        "bootcamp": {"max_positions": 8},            # valid
    }
    assert effective_position_cap(cfg) == 8


def test_effective_position_cap_all_invalid_falls_back_to_default():
    from src.risk.governor import effective_position_cap

    cfg = {
        "risk": {"max_open_positions": 0},
        "risk_governor": {"max_open_positions": None},
        "live_trading": {"max_open_positions": -5},
        "bootcamp": {"max_positions": "x"},
    }
    assert effective_position_cap(cfg) == 10


def test_governor_init_uses_effective_cap():
    """RiskGovernor.__init__ must populate max_open_positions via the helper.

    Pre-T1.04 it read only risk_governor.max_open_positions, ignoring the
    other 3 namespaces.
    """
    from src.risk.governor import RiskGovernor

    cfg = {
        "risk": {"max_open_positions": 4},        # tightest -> wins
        "risk_governor": {"max_open_positions": 50},
        "live_trading": {"max_open_positions": 7},
        "bootcamp": {"max_positions": 20},
    }
    gov = RiskGovernor(cfg)
    assert gov.max_open_positions == 4


def test_governor_cap_and_init_agree_on_identical_config():
    """Both consumers (RiskGovernor.__init__, executor._governor_cap)
    must yield the same effective cap on the same config."""
    from src.risk.governor import RiskGovernor
    from src.shadow_trading.executor import _governor_cap

    cfg = {
        "risk": {"max_open_positions": 6},
        "risk_governor": {"max_open_positions": 50},
        "live_trading": {"max_open_positions": 4},  # tightest
        "bootcamp": {"max_positions": 20},
    }
    gov = RiskGovernor(cfg)
    assert gov.max_open_positions == _governor_cap(cfg) == 4


def test_governor_cap_returns_min_not_larger():
    """Negative regression: divergent caps must collapse to the smallest,
    never the bootcamp value when other namespaces are tighter."""
    from src.shadow_trading.executor import _governor_cap

    cfg = {
        "risk": {"max_open_positions": 5},
        "risk_governor": {"max_open_positions": 50},
        "live_trading": {"max_open_positions": 7},
        "bootcamp": {"enabled": True, "max_positions": 20},
    }
    # Even with bootcamp.enabled=True, the min-rule picks risk=5 not 20.
    assert _governor_cap(cfg) == 5


def test_governor_cap_falls_back_to_default_on_empty_config():
    from src.shadow_trading.executor import _governor_cap

    assert _governor_cap({}) == 10


def test_effective_position_cap_logs_at_startup(caplog):
    """RiskGovernor.__init__ must log the effective cap on construction."""
    import logging

    from src.risk.governor import RiskGovernor

    cfg = {
        "risk": {"max_open_positions": 6},
        "risk_governor": {"max_open_positions": 50},
        "live_trading": {"max_open_positions": 4},
        "bootcamp": {"max_positions": 20},
    }
    with caplog.at_level(logging.INFO, logger="src.risk.governor"):
        RiskGovernor(cfg)
    msg = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "4" in msg, f"effective cap value should appear in startup log; got: {msg}"
    # Some indicator that this is the effective/reconciled cap log line
    assert ("effective" in msg.lower() or "cap" in msg.lower()), (
        f"startup log should reference effective cap; got: {msg}"
    )
