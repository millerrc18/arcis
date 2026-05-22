"""Tests for the GOVERNOR_GATES oracle tuple in src.risk.governor.

GOVERNOR_GATES is the definition list consumed by the capability registry's
gate DECISIONs (Convention C). It must equal the strategy-gate ``"name"``
strings emitted by ``check_trade``, in declaration order, with no
framework checks (``input_surface``/``governor_disabled``).
"""
from __future__ import annotations

from src.risk.governor import GOVERNOR_GATES

_EXPECTED = (
    "traffic_light",
    "event_risk",
    "deterministic_audit",
    "emergency_halt",
    "daily_loss",
    "position_size",
    "max_positions",
    "sector_concentration",
    "correlation",
    "volatility_halt",
    "duplicate",
)


def test_governor_gates_is_an_eleven_tuple():
    assert isinstance(GOVERNOR_GATES, tuple)
    assert len(GOVERNOR_GATES) == 11


def test_governor_gates_matches_emitted_names_in_order():
    assert GOVERNOR_GATES == _EXPECTED


def test_governor_gates_has_no_duplicates():
    assert len(set(GOVERNOR_GATES)) == len(GOVERNOR_GATES)


def test_governor_gates_excludes_framework_checks():
    assert "input_surface" not in GOVERNOR_GATES
    assert "governor_disabled" not in GOVERNOR_GATES
