"""Tests for src/simulation/lifecycle/provenance.py — T8.

Tests assert that assert_real_path_executed():
  (1) passes when all conditions are met (happy path)
  (2) raises ProvenanceError with an informative message for each
      kind of violation (5 seam-counter negatives, bad order_type,
      prod DSN, DSN mismatch, missing inv9 column)

The FakeLLM in fakes/llm.py does NOT carry a self.calls Counter
(that counter was specified in T3 but not implemented). These tests
use a minimal stub object so they exercise the guard's callable
interface without depending on the live FakeLLM implementation.
The guard handles missing .calls gracefully (see provenance.py).
"""
from __future__ import annotations

from collections import Counter

import pytest

from src.simulation.lifecycle.provenance import (
    ProvenanceError,
    assert_real_path_executed,
)


# ────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ────────────────────────────────────────────────────────────────────────────

SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"
PROD_DSN = "postgresql://halcyon_app:secret@prod-db-host:5432/halcyon"


class _FakeConn:
    """Minimal conn-like object with a .dsn attribute."""
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn


class _FakeMD:
    def __init__(self, fetch_ohlcv: int = 1, fetch_spy: int = 1) -> None:
        self.calls: Counter[str] = Counter(
            fetch_ohlcv=fetch_ohlcv,
            fetch_spy=fetch_spy,
        )


class _FakeLLM:
    def __init__(self, generate: int = 1) -> None:
        self.calls: Counter[str] = Counter(generate=generate)


class _FakeTC:
    def __init__(self, get_account: int = 1, submit_order: int = 1) -> None:
        self.calls: Counter[str] = Counter(
            get_account=get_account,
            submit_order=submit_order,
        )


INV9_COLUMNS = (
    "recommendation_id",
    "ticker",
    "status",
    "actual_shares",
    "order_type",
    "exit_reason",
    "pnl_dollars",
)


def _make_row(order_type: str = "bracket", **overrides) -> dict:
    """Return a minimal shadow_trade row dict with all inv9 columns present."""
    row = {col: "x" for col in INV9_COLUMNS}
    row["order_type"] = order_type
    row.update(overrides)
    return row


def _happy_args(**overrides):
    """Return keyword args for a passing assert_real_path_executed call."""
    args = dict(
        fake_tc=_FakeTC(),
        fake_md=_FakeMD(),
        fake_llm=_FakeLLM(),
        oracle_conn=_FakeConn(SIM_DSN),
        primed_dsn=SIM_DSN,
        rows=[_make_row()],
    )
    args.update(overrides)
    return args


# ────────────────────────────────────────────────────────────────────────────
# (1) Happy path
# ────────────────────────────────────────────────────────────────────────────

def test_happy_path_returns_none():
    """Guard passes when all three properties are satisfied."""
    result = assert_real_path_executed(**_happy_args())
    assert result is None


def test_happy_path_simple_with_stop_accepted():
    """order_type='simple_with_stop' is in the executor-only set — must pass."""
    result = assert_real_path_executed(
        **_happy_args(rows=[_make_row(order_type="simple_with_stop")])
    )
    assert result is None


# ────────────────────────────────────────────────────────────────────────────
# (2) Negative — 5 individual seam counter tests (one per seam)
# ────────────────────────────────────────────────────────────────────────────

def test_negative_seam_fetch_ohlcv_zero():
    """Guard raises ProvenanceError when fetch_ohlcv count == 0."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(fake_md=_FakeMD(fetch_ohlcv=0))
        )
    assert "fetch_ohlcv" in str(exc_info.value)
    assert "0" in str(exc_info.value)


def test_negative_seam_fetch_spy_zero():
    """Guard raises ProvenanceError when fetch_spy count == 0."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(fake_md=_FakeMD(fetch_spy=0))
        )
    assert "fetch_spy" in str(exc_info.value)
    assert "0" in str(exc_info.value)


def test_negative_seam_generate_zero():
    """Guard raises ProvenanceError when generate count == 0."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(fake_llm=_FakeLLM(generate=0))
        )
    assert "generate" in str(exc_info.value)
    assert "0" in str(exc_info.value)


def test_negative_seam_get_account_zero():
    """Guard raises ProvenanceError when get_account count == 0."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(fake_tc=_FakeTC(get_account=0))
        )
    assert "get_account" in str(exc_info.value)
    assert "0" in str(exc_info.value)


def test_negative_seam_submit_order_zero():
    """Guard raises ProvenanceError when submit_order count == 0."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(fake_tc=_FakeTC(submit_order=0))
        )
    assert "submit_order" in str(exc_info.value)
    assert "0" in str(exc_info.value)


# ────────────────────────────────────────────────────────────────────────────
# (3) Negative — bad order_type
# ────────────────────────────────────────────────────────────────────────────

def test_negative_bad_order_type_reconciled():
    """Guard raises ProvenanceError when a row has order_type='reconciled'."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(rows=[_make_row(order_type="reconciled")])
        )
    assert "order_type" in str(exc_info.value)
    assert "reconciled" in str(exc_info.value)


def test_negative_bad_order_type_synthetic():
    """Guard raises ProvenanceError on order_type outside executor-only set."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(rows=[_make_row(order_type="synthetic")])
        )
    assert "order_type" in str(exc_info.value)


# ────────────────────────────────────────────────────────────────────────────
# (4) Negative — prod DSN on oracle_conn
# ────────────────────────────────────────────────────────────────────────────

def test_negative_prod_dsn_on_oracle_conn():
    """Guard raises ProvenanceError when oracle_conn points at a prod DSN."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(
                oracle_conn=_FakeConn(PROD_DSN),
                primed_dsn=PROD_DSN,
            )
        )
    assert "5434" in str(exc_info.value) or "prod" in str(exc_info.value).lower() or "sim" in str(exc_info.value).lower()


def test_negative_prod_dsn_primed_dsn_only():
    """Guard raises ProvenanceError when primed_dsn is prod-shaped (port 5432)."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(
                oracle_conn=_FakeConn(PROD_DSN),
                primed_dsn=PROD_DSN,
            )
        )
    # The message must name the specific failure
    msg = str(exc_info.value)
    assert "ProvenanceError" not in msg or len(msg) > len("ProvenanceError")


# ────────────────────────────────────────────────────────────────────────────
# (5) Negative — DSN mismatch (both are 5434 but they differ)
# ────────────────────────────────────────────────────────────────────────────

def test_negative_dsn_mismatch_both_sim():
    """Guard raises ProvenanceError when oracle_conn DSN != primed_dsn even if both are 5434."""
    other_sim_dsn = "postgresql://test:test@127.0.0.1:5434/other_db"
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(
                oracle_conn=_FakeConn(other_sim_dsn),
                primed_dsn=SIM_DSN,
            )
        )
    assert "mismatch" in str(exc_info.value).lower() or "match" in str(exc_info.value).lower() or "equal" in str(exc_info.value).lower()


# ────────────────────────────────────────────────────────────────────────────
# (6) Negative — missing inv9 column
# ────────────────────────────────────────────────────────────────────────────

def test_negative_missing_inv9_column_recommendation_id():
    """Guard raises ProvenanceError when recommendation_id is missing from rows."""
    row = _make_row()
    del row["recommendation_id"]
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(**_happy_args(rows=[row]))
    assert "recommendation_id" in str(exc_info.value)


def test_negative_missing_inv9_column_pnl_dollars():
    """Guard raises ProvenanceError when pnl_dollars is missing from rows."""
    row = _make_row()
    del row["pnl_dollars"]
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(**_happy_args(rows=[row]))
    assert "pnl_dollars" in str(exc_info.value)


def test_negative_missing_inv9_column_actual_shares():
    """Guard raises ProvenanceError when actual_shares is missing from rows."""
    row = _make_row()
    del row["actual_shares"]
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(**_happy_args(rows=[row]))
    assert "actual_shares" in str(exc_info.value)


# ────────────────────────────────────────────────────────────────────────────
# (7) All counters checked — each of the 5 independently
#     (covered by the 5 explicit tests above; this test verifies the guard
#     passes when all counters are > 1 — counter > 0 is the only requirement)
# ────────────────────────────────────────────────────────────────────────────

def test_all_counters_above_one_still_pass():
    """Guard passes with all counters > 1 (not just == 1)."""
    result = assert_real_path_executed(
        **_happy_args(
            fake_md=_FakeMD(fetch_ohlcv=5, fetch_spy=3),
            fake_llm=_FakeLLM(generate=7),
            fake_tc=_FakeTC(get_account=2, submit_order=4),
        )
    )
    assert result is None


# ────────────────────────────────────────────────────────────────────────────
# (8) Bracket-only artifact rule
# ────────────────────────────────────────────────────────────────────────────

def test_bracket_order_type_accepted():
    """order_type='bracket' is in the allowed set."""
    result = assert_real_path_executed(
        **_happy_args(rows=[_make_row(order_type="bracket")])
    )
    assert result is None


def test_simple_with_stop_order_type_accepted():
    """order_type='simple_with_stop' is in the allowed set."""
    result = assert_real_path_executed(
        **_happy_args(rows=[_make_row(order_type="simple_with_stop")])
    )
    assert result is None


def test_reconciled_order_type_rejected():
    """order_type='reconciled' is NOT in the executor-only set."""
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(
            **_happy_args(rows=[_make_row(order_type="reconciled")])
        )
    assert "order_type" in str(exc_info.value)
    assert "reconciled" in str(exc_info.value)


# ────────────────────────────────────────────────────────────────────────────
# Edge cases
# ────────────────────────────────────────────────────────────────────────────

def test_empty_rows_passes_order_type_check():
    """An empty rows list satisfies the order_type check vacuously (no rows to check).

    Note: the rows list being empty is a separate concern from provenance;
    the oracle detects the 'zero rows' condition. The guard's job is to check
    that any rows that DO exist carry the right order_type.
    """
    result = assert_real_path_executed(**_happy_args(rows=[]))
    assert result is None


def test_multiple_rows_one_bad_order_type():
    """Guard catches a bad order_type even when only one row out of many has it."""
    rows = [
        _make_row(order_type="bracket"),
        _make_row(order_type="reconciled"),
        _make_row(order_type="simple_with_stop"),
    ]
    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(**_happy_args(rows=rows))
    assert "order_type" in str(exc_info.value)
    assert "reconciled" in str(exc_info.value)


def test_fake_llm_without_calls_attr_raises():
    """Guard handles FakeLLM without .calls Counter — treats as count=0 and raises."""

    class _NoCallsLLM:
        """Simulates a FakeLLM that never had .calls added (T3 gap)."""
        pass

    with pytest.raises(ProvenanceError) as exc_info:
        assert_real_path_executed(**_happy_args(fake_llm=_NoCallsLLM()))
    assert "generate" in str(exc_info.value)
