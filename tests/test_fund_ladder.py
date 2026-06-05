"""Tests for the derived fund-ladder generator (Founder Console P3-T1).

Covers src.console.fund_ladder — the derive-from-source (design law #7) Phase
1->6 ladder. The ladder STRUCTURE (AUM targets + gate-metric keys) is the
machine-readable spec; the per-phase LIVE progress is COMPUTED from the metric
registry, NEVER hand-typed (the spec's anti-goal).

Design-law assertions enforced:
  law #7  — current-phase gate progress is derived from real sources
            (src.metrics.registry via the closed-trade cohort), never typed.
  fail-closed — a failing source degrades the affected gate to state='unknown'
            and the top-level to generation_ok=False + failed_sources=[...];
            it NEVER raises, never fabricates a number, never serves a silently
            stale snapshot.
  law #1/#2 — every gate value carries cohort + n + as_of + unit (the canonical
            envelope), so a number is never shown without its provenance.

These tests monkeypatch the trade SOURCE (_fetch_closed_trades) rather than
seeding SQLite, mirroring how get_now_gate consumes its source; this keeps the
ladder derivation deterministic and isolated from the journal store.
"""
from __future__ import annotations

import pytest

from src.console import fund_ladder as fl

# A small synthetic closed-trade cohort. excess Sharpe / t-stat need SPY-aligned
# returns and >=2 samples; we give a handful of positive-pnl trades so the
# computed gate values are REAL numbers (non-vacuous), not None.
_SEED_TRADES = [
    {
        "pnl_pct": 2.0,
        "spy_return_over_hold": 0.005,
        "actual_entry_time": "2026-01-02T14:30:00+00:00",
        "actual_exit_time": "2026-01-03T20:00:00+00:00",
    },
    {
        "pnl_pct": 1.5,
        "spy_return_over_hold": 0.004,
        "actual_entry_time": "2026-01-05T14:30:00+00:00",
        "actual_exit_time": "2026-01-06T20:00:00+00:00",
    },
    {
        "pnl_pct": -0.5,
        "spy_return_over_hold": 0.002,
        "actual_entry_time": "2026-01-07T14:30:00+00:00",
        "actual_exit_time": "2026-01-08T20:00:00+00:00",
    },
    {
        "pnl_pct": 3.0,
        "spy_return_over_hold": -0.001,
        "actual_entry_time": "2026-01-09T14:30:00+00:00",
        "actual_exit_time": "2026-01-10T20:00:00+00:00",
    },
]


@pytest.fixture
def seeded(monkeypatch):
    """Patch the trade source to a known cohort so progress is computed, real."""
    monkeypatch.setattr(fl, "_fetch_closed_trades", lambda: list(_SEED_TRADES))
    return _SEED_TRADES


# ── structural / envelope shape ───────────────────────────────────────────────


def test_ladder_constant_has_six_phases():
    """The machine-readable spec is the 6-phase structure (no progress counts)."""
    assert len(fl.PHASE_LADDER) == 6
    aum = [p["aum_target"] for p in fl.PHASE_LADDER]
    assert "$100" in aum[0]
    assert "$500K" in aum[5]
    # Each phase declares its gate-metric target keys (the structure), and those
    # keys are real registry/gate-target keys — never a hand-typed progress number.
    from src.console.gate_targets import GATE_TARGETS
    for phase in fl.PHASE_LADDER:
        assert phase["gate_metrics"], "each phase must declare gate-metric keys"
        for mid in phase["gate_metrics"]:
            assert mid in GATE_TARGETS


def test_envelope_top_level_keys(seeded):
    out = fl.generate_fund_ladder()
    assert set(out.keys()) == {
        "ladder", "current_phase", "generation_ok", "failed_sources",
        "source_sha", "as_of",
    }
    assert isinstance(out["ladder"], list)
    assert len(out["ladder"]) == 6
    assert isinstance(out["failed_sources"], list)


def test_each_ladder_entry_shape(seeded):
    out = fl.generate_fund_ladder()
    for entry in out["ladder"]:
        assert set(entry.keys()) == {
            "phase", "name", "aum_target", "status", "gates", "progress",
        }
        assert entry["status"] in {"complete", "active", "pending"}
        assert isinstance(entry["gates"], list)
        for gate in entry["gates"]:
            assert set(gate.keys()) == {
                "metric_id", "value", "target", "n", "as_of", "cohort",
                "unit", "state",
            }
            assert gate["state"] in {"ok", "no_data", "pending", "unknown"}


def test_phases_are_numbered_one_through_six(seeded):
    out = fl.generate_fund_ladder()
    assert [e["phase"] for e in out["ladder"]] == [1, 2, 3, 4, 5, 6]


# ── current-phase detection + derived (non-vacuous) progress ──────────────────


def test_current_phase_is_active_and_within_range(seeded):
    out = fl.generate_fund_ladder()
    cur = out["current_phase"]
    assert 1 <= cur <= 6
    active = [e for e in out["ladder"] if e["status"] == "active"]
    assert len(active) == 1
    assert active[0]["phase"] == cur


def test_current_phase_gates_carry_real_computed_values(seeded):
    """Non-vacuous: seeded trades -> the current phase has REAL gate numbers."""
    out = fl.generate_fund_ladder()
    cur_entry = next(e for e in out["ladder"] if e["phase"] == out["current_phase"])
    by_id = {g["metric_id"]: g for g in cur_entry["gates"]}

    # closed_trade_count must equal the seeded cohort size — a real derived count.
    ct = by_id["closed_trade_count"]
    assert ct["value"] == len(_SEED_TRADES)
    assert ct["state"] == "ok"
    assert ct["n"] == len(_SEED_TRADES)
    assert ct["target"] == 100

    # excess_sharpe_vs_spy is computed over the SPY-aligned cohort -> a real float.
    es = by_id["excess_sharpe_vs_spy"]
    assert es["state"] == "ok"
    assert isinstance(es["value"], float)
    assert es["n"] == len(_SEED_TRADES)


def test_current_phase_progress_is_a_real_fraction(seeded):
    out = fl.generate_fund_ladder()
    cur_entry = next(e for e in out["ladder"] if e["phase"] == out["current_phase"])
    assert isinstance(cur_entry["progress"], float)
    assert 0.0 <= cur_entry["progress"] <= 1.0


def test_gate_values_carry_provenance(seeded):
    """law #1/#2: every computed gate carries cohort + n + as_of + unit."""
    out = fl.generate_fund_ladder()
    cur_entry = next(e for e in out["ladder"] if e["phase"] == out["current_phase"])
    for gate in cur_entry["gates"]:
        if gate["state"] in {"ok", "no_data"}:
            assert gate["cohort"], "computed gate must name its cohort"
            assert gate["unit"], "computed gate must name its unit"
            assert "n" in gate
            assert "as_of" in gate


# ── pending-phase legitimacy (emptiness != zero) ──────────────────────────────


def test_pending_phases_are_pending_not_zero(seeded):
    """Phases beyond the current carry state='pending' + value=None (legitimate
    emptiness), distinct from a computed zero."""
    out = fl.generate_fund_ladder()
    cur = out["current_phase"]
    pending = [e for e in out["ladder"] if e["phase"] > cur]
    assert pending, "with a small cohort there must be later pending phases"
    for entry in pending:
        assert entry["status"] == "pending"
        assert entry["progress"] is None
        for gate in entry["gates"]:
            assert gate["state"] == "pending"
            assert gate["value"] is None  # NOT 0 — emptiness, not a measurement
            assert gate["target"] is not None  # the target is still shown


# ── source_sha ────────────────────────────────────────────────────────────────


def test_source_sha_non_empty(seeded):
    out = fl.generate_fund_ladder()
    assert isinstance(out["source_sha"], str)
    assert out["source_sha"]


# ── FAIL-CLOSED: a broken source degrades, never fabricates, never raises ──────


def test_fail_closed_when_trade_source_raises(monkeypatch):
    """The headline contract: if the trade source is unavailable the ladder is
    generation_ok=False, failed_sources is populated, the affected gates are
    state='unknown' (value=None), and NO exception escapes."""
    def _boom():
        raise RuntimeError("journal store unavailable")

    monkeypatch.setattr(fl, "_fetch_closed_trades", _boom)

    out = fl.generate_fund_ladder()  # must NOT raise

    assert out["generation_ok"] is False
    assert out["failed_sources"], "a failed source must be named"
    # The current-phase gates that depend on the trade source are 'unknown',
    # never a fabricated number.
    cur_entry = next(e for e in out["ladder"] if e["phase"] == out["current_phase"])
    assert cur_entry["gates"], "current phase still lists its gate keys"
    for gate in cur_entry["gates"]:
        assert gate["state"] == "unknown"
        assert gate["value"] is None
    # Still a complete 6-phase envelope (no silent truncation).
    assert len(out["ladder"]) == 6


def test_fail_closed_progress_is_none_not_fabricated(monkeypatch):
    monkeypatch.setattr(
        fl, "_fetch_closed_trades",
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
    )
    out = fl.generate_fund_ladder()
    cur_entry = next(e for e in out["ladder"] if e["phase"] == out["current_phase"])
    assert cur_entry["progress"] is None


def test_happy_path_generation_ok_true(seeded):
    out = fl.generate_fund_ladder()
    assert out["generation_ok"] is True
    assert out["failed_sources"] == []
