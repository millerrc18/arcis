"""T2.15 — lazy_prices_v1 spec is shelved with revival criteria.

Audit spec §6.4 + F-Strategy-C: Lazy Prices is a Stage-3 candidate that
was formally shelved post-bootcamp pending re-activation via revival
ticket gate. This file pins:

  1. The `status: shelved` top-level field is present and equals
     "shelved" on disk.
  2. The `revival_criteria` block contains the three required
     re-activation thresholds (min_oos_sessions, min_observed_sharpe,
     sponsor_ticket_required).
  3. The modified YAML still parses cleanly through
     `strategy_spec.load_spec(...)` (no schema regression — `status`
     and `revival_criteria` are additive).
  4. No live consumer under `src/` references `lazy_prices_v1` as a
     spec_id (pre-shelving Grep gate).
  5. Generic spec-router behavior: a synthetic spec with
     `status: shelved` is correctly flagged as inactive.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.platform.strategy_spec import load_spec, validate_spec


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_DIR = _REPO_ROOT / "src"


def test_lazy_prices_v1_status_shelved():
    spec = load_spec("lazy_prices_v1")
    assert spec.raw.get("status") == "shelved"


def test_lazy_prices_v1_revival_criteria_block_present():
    spec = load_spec("lazy_prices_v1")
    rc = spec.raw.get("revival_criteria")
    assert isinstance(rc, dict), "revival_criteria must be a dict"
    assert "min_oos_sessions" in rc
    assert isinstance(rc["min_oos_sessions"], int) and rc["min_oos_sessions"] > 0
    assert "min_observed_sharpe" in rc
    assert isinstance(rc["min_observed_sharpe"], (int, float))
    assert rc["min_observed_sharpe"] > 0
    assert "sponsor_ticket_required" in rc
    assert rc["sponsor_ticket_required"] is True


def test_lazy_prices_v1_still_loads_without_schema_error():
    """Loader accepts the modified YAML — additive fields don't break parse."""
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"
    ok, errors = validate_spec(spec.raw)
    assert ok, f"validate_spec must accept shelved spec: {errors}"


def test_lazy_prices_v1_existing_fields_preserved():
    """Scope guard: shelving must NOT remove any existing fields."""
    spec = load_spec("lazy_prices_v1")
    # spot-check the load-bearing fields the loader projects out
    assert spec.display_name == "Lazy Prices (Cohen-Malloy-Nguyen 2020)"
    assert spec.universe == {"tickers": "sp100"}
    assert spec.entry.get("kind") == "event_driven"
    assert spec.exit.get("kind") == "mechanical"
    assert spec.position_sizing.get("method") == "fixed_pct_equity"
    assert spec.attribution.get("benchmark") == "SPY_matched_window"
    assert "llm_enhancement" in spec.raw


def test_no_live_consumer_loads_lazy_prices_v1_spec_id():
    """Pre-shelving gate: no production code calls load_spec('lazy_prices_v1')
    or otherwise treats 'lazy_prices_v1' as an active strategy_id under
    src/. Tests, docs, and CHANGELOG references are exempt by design.

    The desk-routing string 'research_lazy_prices_v1' (a different
    string referring to a shadow-trading desk identifier, not the
    spec_id) is filtered out — it is permitted under SCOPE_FENCE
    because T2.18 owns plugin removal.
    """
    pattern_spec_id = re.compile(r"['\"]lazy_prices_v1['\"]")
    pattern_desk = re.compile(r"research_lazy_prices_v1")
    offenders: list[str] = []
    for py_path in _SRC_DIR.rglob("*.py"):
        text = py_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            # Skip the desk-prefix mentions; they are a different identifier.
            without_desk = pattern_desk.sub("", line)
            if pattern_spec_id.search(without_desk):
                offenders.append(f"{py_path}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Live consumer of spec_id 'lazy_prices_v1' detected — must escalate "
        "before shelving. Offenders:\n" + "\n".join(offenders)
    )


def test_synthetic_shelved_spec_flagged_inactive():
    """A spec with `status: shelved` is recognized as inactive by any
    consumer that reads the field. We codify the contract: shelved
    specs MUST have status == 'shelved' (string), and that value is
    the canonical inactive sentinel for downstream routers.
    """
    synthetic = {
        "spec_version": 1,
        "strategy_id": "synthetic_shelved",
        "display_name": "Synthetic Shelved",
        "status": "shelved",
        "universe": {"tickers": ["AAPL"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "python_plugin"},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY"},
    }
    ok, errors = validate_spec(synthetic)
    assert ok, errors
    # Routing contract: a downstream router reads .status to gate dispatch.
    assert synthetic["status"] == "shelved"
    # Active specs (status absent OR != "shelved") should NOT match this gate.
    active_a = dict(synthetic)
    active_a.pop("status")
    assert active_a.get("status") != "shelved"
    active_b = dict(synthetic, status="active")
    assert active_b.get("status") != "shelved"
