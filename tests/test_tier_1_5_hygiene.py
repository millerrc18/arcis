"""Regression guards for Tier 1.5 hygiene fixes.

Each test prevents a hygiene regression from re-emerging. Tier 1.5 covers
documentation accuracy (CLAUDE.md test count), operator-safety defaults
(cleanup script --dry-run), UI conditional rendering, packet-builder
defensive defaults, route-layer connect_db migration, and helper test
coverage.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLAUDE.md test-count baseline must reflect the current sweep size
# ---------------------------------------------------------------------------


def test_claude_md_test_count_baseline_is_current():
    """CLAUDE.md publishes a "Test count must not drop" baseline used as a
    rule-of-thumb for code review. When the actual sweep grows past the
    baseline, the number must be bumped — otherwise the rule loses bite
    (a PR could halve the test count and still satisfy "above baseline").

    This test asserts the baseline is at least the prior known sweep
    (2897 from PR #639). It does NOT auto-detect because the goal is
    "operator notices and bumps consciously" — auto-detection would
    silently follow regressions down."""
    claude_md = _read("CLAUDE.md")
    match = re.search(r"minimum of (\d+) tests", claude_md)
    assert match, "CLAUDE.md must declare a 'minimum of N tests' baseline"
    declared = int(match.group(1))
    assert declared >= 2897, (
        f"CLAUDE.md baseline ({declared}) is below the 2026-04-24 sweep size "
        f"of 2897 (PR #639). Bump the number in CLAUDE.md."
    )


# ---------------------------------------------------------------------------
# Destructive cleanup scripts must default to dry-run (require --apply)
# ---------------------------------------------------------------------------


def test_clean_training_data_requires_explicit_apply_flag():
    """scripts/clean_training_data.py UPDATEs training_examples.output_text
    in-place. Without a --dry-run/--apply gate, an accidental run could
    mass-overwrite the corpus. The script must:
      - parse argparse with --apply (or --dry-run that defaults True)
      - print a "Re-run with --apply" hint when in dry-run
      - not call conn.commit() unless --apply was passed
    """
    src = _read("scripts/clean_training_data.py")
    assert "argparse" in src, "clean_training_data.py must use argparse"
    assert "--apply" in src or "--dry-run" in src, (
        "clean_training_data.py must accept --apply (or --dry-run) so accidental "
        "runs do not mass-overwrite training_examples.output_text"
    )
    # When --apply is absent, conn.commit() must be guarded
    assert "args.apply" in src or "dry_run" in src.lower(), (
        "clean_training_data.py must check the apply/dry-run flag before "
        "calling conn.commit() — otherwise the gate is cosmetic"
    )


# ---------------------------------------------------------------------------
# #621 — packets/template.py must refuse to build on price <= 0
# ---------------------------------------------------------------------------


def test_build_packet_from_features_returns_none_on_zero_price():
    """#621 — 390 risk-rejection rows in 4/21–4/23 traced to upstream
    feature pipeline returning current_price=0 for ~14 specific tickers.
    System burned ~110 min/day of LLM compute on packets that could
    never fund. The packet builder must refuse early so the wasted
    compute path is gone."""
    from src.packets.template import build_packet_from_features

    features_no_price = {
        "current_price": 0.0,
        "atr_14": 1.0,
        "trend_state": "uptrend",
        "_score": 80,
    }
    config = {"risk": {"starting_capital": 100000}, "risk_governor": {}}
    result = build_packet_from_features("ZERO", features_no_price, config)
    assert result is None, (
        "build_packet_from_features must return None when current_price<=0 "
        "(#621). Returning a TradePacket with allocation=0 wastes downstream "
        "LLM + governor compute on a packet that cannot fund."
    )


def test_build_packet_from_features_returns_none_on_missing_price():
    """Defensive: missing current_price (treated as 0.0 by .get default)
    is functionally identical to price=0 for funding purposes."""
    from src.packets.template import build_packet_from_features

    config = {"risk": {"starting_capital": 100000}, "risk_governor": {}}
    result = build_packet_from_features("MISSING", {"_score": 80}, config)
    assert result is None


def test_build_packet_from_features_succeeds_with_normal_price(monkeypatch):
    """Sanity: a valid price still builds a packet (no over-restriction)."""
    from src.packets import template as tpl

    # The function calls get_effective_risk_pct which reads config — stub it.
    monkeypatch.setattr(
        "src.risk.governor.get_effective_risk_pct",
        lambda cfg: (0.005, "static"),
    )
    features = {
        "current_price": 100.0,
        "atr_14": 2.0,
        "trend_state": "uptrend",
        "_score": 80,
    }
    config = {"risk": {"starting_capital": 100000}, "risk_governor": {}}
    pkt = tpl.build_packet_from_features("AAPL", features, config)
    assert pkt is not None
    assert pkt.position_sizing.allocation_dollars > 0


# ---------------------------------------------------------------------------
# #478 — route DB reads must use connect_db (busy_timeout=30s)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "src/api/routes/council.py",
        "src/api/routes/health.py",
        "src/api/routes/ib_status.py",
        "src/api/routes/live.py",
        "src/api/routes/logs.py",
        "src/api/routes/notes.py",
        "src/api/routes/system.py",
    ],
)
def test_route_uses_connect_db_helper(path):
    """#478 — route DB reads must use connect_db so the busy_timeout=30s
    applies consistently. Without it, a route that fires during external-
    tool DB inspection (MS Access, DB Browser) gets immediate 'database
    is locked' instead of waiting for the lock to release.
    """
    src = _read(path)
    body_only = re.sub(r"^import sqlite3\b.*$", "", src, flags=re.MULTILINE)
    matches = re.findall(r"\bsqlite3\.connect\b", body_only)
    assert not matches, (
        f"{path} contains {len(matches)} raw sqlite3.connect call(s); "
        f"use connect_db() from src.utils.db instead (#478)"
    )
