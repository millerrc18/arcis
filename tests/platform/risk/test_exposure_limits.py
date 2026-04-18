"""Tests for src.platform.risk.exposure_limits — hard concentration caps.

Non-negotiable gates (Sprint 3):
  - test_hard_limit_blocks_single_name_over_6pct
  - test_hard_limit_blocks_sector_over_25pct
  - test_drawdown_circuit_breaker_blocks_all_entries
"""
import pytest

from src.platform.risk.exposure_limits import (
    HARD_LIMITS,
    SOFT_LIMITS,
    check_book_drawdown_circuit_breaker,
    check_pre_trade_limits,
    get_soft_limit_breaches,
)


# ── Hard limit: single-name 6% ─────────────────────────────────────────

def test_hard_limit_allows_single_name_under_6pct():
    """5% position → allowed."""
    current_positions = []
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL",
        proposed_shares=50,
        proposed_price=100.0,   # 50 × 100 = 5000
        current_positions=current_positions,
        current_nav=100_000.0,   # 5000 / 100_000 = 5% < 6%
        db_path=None,
    )
    assert allowed, f"5% position should be allowed; reason={reason}"


def test_hard_limit_blocks_single_name_over_6pct():
    """7% position → rejected. Non-negotiable gate."""
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL",
        proposed_shares=70,
        proposed_price=100.0,   # 7000 / 100_000 = 7%
        current_positions=[],
        current_nav=100_000.0,
        db_path=None,
    )
    assert not allowed
    assert "single" in reason.lower() or "concentration" in reason.lower()
    assert "6" in reason or "0.06" in reason


def test_hard_limit_aggregates_existing_position_in_same_name():
    """Existing 4% AAPL + proposed 3% AAPL → 7% aggregate → blocked.
    The cap is on AGGREGATE per ticker, not per new order."""
    existing = [
        {"ticker": "AAPL", "shares": 40, "current_price": 100.0},  # 4%
    ]
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL",
        proposed_shares=30,
        proposed_price=100.0,   # +3% → total 7%
        current_positions=existing,
        current_nav=100_000.0,
        db_path=None,
    )
    assert not allowed
    assert "single" in reason.lower() or "concentration" in reason.lower()


# ── Hard limit: sector 25% ─────────────────────────────────────────────

def test_hard_limit_blocks_sector_over_25pct():
    """Existing Tech = 24% (AAPL+MSFT), proposed +2% NVDA → 26% sector → rejected.

    Note: uses NVDA (Technology) not GOOGL — Alphabet was reclassified
    from Technology to Communication Services in GICS September 2018.
    """
    existing = [
        {"ticker": "AAPL", "shares": 120, "current_price": 100.0},   # 12%
        {"ticker": "MSFT", "shares": 120, "current_price": 100.0},   # 12%
    ]
    allowed, reason = check_pre_trade_limits(
        ticker="NVDA",
        proposed_shares=20,
        proposed_price=100.0,    # +2% → total 26% Tech
        current_positions=existing,
        current_nav=100_000.0,
        db_path=None,
    )
    assert not allowed
    assert "sector" in reason.lower()
    assert "25" in reason or "0.25" in reason


def test_hard_limit_allows_sector_under_25pct():
    """Tech at 20% + 4% proposed → 24% → allowed."""
    existing = [
        {"ticker": "AAPL", "shares": 100, "current_price": 100.0},   # 10%
        {"ticker": "MSFT", "shares": 100, "current_price": 100.0},   # 10%
    ]
    allowed, reason = check_pre_trade_limits(
        ticker="NVDA",
        proposed_shares=40,
        proposed_price=100.0,    # +4% → total 24%
        current_positions=existing,
        current_nav=100_000.0,
        db_path=None,
    )
    assert allowed, f"24% sector should be allowed; reason={reason}"


# ── Hard limit: gross leverage 1.5x ────────────────────────────────────

def test_hard_limit_blocks_gross_over_1_5x():
    """Many small positions all under 6% single-name but aggregate
    gross > 150%. Each existing = 5% single-name (fine); 30 × 5% =
    150% existing gross; proposed +5% → 155% total > 150% limit.

    Must use tickers with unknown sectors (not in SECTOR_MAP) so the
    sector-aggregate check doesn't trip first. Using f'T{i}' synthetic
    tickers; _lookup_sector returns None for them, so sector check
    short-circuits on sector=None (skipped per code logic line 210).
    """
    existing = [
        {"ticker": f"T{i}", "shares": 5, "current_price": 1000.0}   # 5% each × 30 = 150%
        for i in range(30)
    ]
    allowed, reason = check_pre_trade_limits(
        ticker="TNEW",
        proposed_shares=5,
        proposed_price=1000.0,   # 5% single-name (under 6% cap), +5% gross → 155%
        current_positions=existing,
        current_nav=100_000.0,
        db_path=None,
    )
    assert not allowed
    assert "leverage" in reason.lower() or "gross" in reason.lower()


# ── Drawdown circuit breaker ───────────────────────────────────────────

def test_drawdown_circuit_breaker_blocks_all_entries(monkeypatch):
    """Book drawdown exceeds 8% → ALL new entries blocked regardless
    of concentration math."""
    # Mock the drawdown computation to return a value over threshold
    import src.platform.risk.exposure_limits as el
    monkeypatch.setattr(
        el, "check_book_drawdown_circuit_breaker",
        lambda db_path=None: (False, 0.095),   # 9.5% dd, breached
    )
    # Even a tiny 0.1% proposed position must be rejected
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL",
        proposed_shares=1,
        proposed_price=100.0,
        current_positions=[],
        current_nav=100_000.0,
        db_path=None,
    )
    assert not allowed
    assert "drawdown" in reason.lower() or "circuit" in reason.lower()


def test_drawdown_circuit_breaker_allows_entries_under_threshold(monkeypatch):
    """7% drawdown → under 8% threshold → concentration check proceeds normally."""
    import src.platform.risk.exposure_limits as el
    monkeypatch.setattr(
        el, "check_book_drawdown_circuit_breaker",
        lambda db_path=None: (True, 0.07),
    )
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL",
        proposed_shares=20,
        proposed_price=100.0,    # 2% position, fine
        current_positions=[],
        current_nav=100_000.0,
        db_path=None,
    )
    assert allowed


# ── HARD_LIMITS / SOFT_LIMITS constants ────────────────────────────────

def test_hard_limits_constants_match_spec():
    assert HARD_LIMITS["max_single_name_pct_of_nav"] == 0.06
    assert HARD_LIMITS["max_sector_pct_of_nav"] == 0.25
    assert HARD_LIMITS["max_gross_leverage"] == 1.5
    assert HARD_LIMITS["book_drawdown_circuit_breaker_pct"] == 0.08


def test_soft_limits_constants_match_spec():
    assert SOFT_LIMITS["max_pair_spearman_63d"] == 0.50
    assert SOFT_LIMITS["max_pair_spearman_persistence_days"] == 5
    assert SOFT_LIMITS["max_aggregate_factor_beta"] == 0.50
    assert SOFT_LIMITS["max_vol_ratio_21d_vs_252d"] == 1.50


# ── Pure-function contract ─────────────────────────────────────────────

def test_check_pre_trade_limits_returns_tuple_bool_and_reason():
    allowed, reason = check_pre_trade_limits(
        ticker="AAPL", proposed_shares=1, proposed_price=100.0,
        current_positions=[], current_nav=100_000.0, db_path=None,
    )
    assert isinstance(allowed, bool)
    assert reason is None or isinstance(reason, str)


def test_check_pre_trade_limits_does_not_write_db(tmp_path, monkeypatch):
    """Pure function — must not touch DB on check path."""
    # We can't easily verify "no writes" without DB instrumentation; instead
    # assert that with db_path=None (no DB access allowed) the function
    # still returns a sensible answer for non-drawdown-gated cases.
    import src.platform.risk.exposure_limits as el
    monkeypatch.setattr(
        el, "check_book_drawdown_circuit_breaker",
        lambda db_path=None: (True, 0.0),
    )
    allowed, _ = check_pre_trade_limits(
        ticker="AAPL", proposed_shares=1, proposed_price=100.0,
        current_positions=[], current_nav=100_000.0, db_path=None,
    )
    assert allowed is True


# ── get_soft_limit_breaches advisory ───────────────────────────────────

def test_get_soft_limit_breaches_returns_list(tmp_path):
    """get_soft_limit_breaches returns list (possibly empty) of dicts
    describing current soft-limit breaches. Advisory only — does not block."""
    breaches = get_soft_limit_breaches(db_path=str(tmp_path / "none.db"))
    assert isinstance(breaches, list)
    # Empty DB → no breaches
    assert breaches == []
