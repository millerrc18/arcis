"""Regression-locking tests for Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY.

Authority: operator Q6=A decision (2026-04-26) during PR #690 review. Each
test pins a deliberate methodology decision; reverting the source change
must reintroduce the test failure.

Fixes covered:
  - Fix 1 (CPCV-EMBARGO-ZERO): the auto-shrink loop never decrements embargo
    to 0; CPCV vote auto-FAILs with structured `reason` when the series can't
    support a leakage-safe (k>=2, embargo>=1) configuration.
  - Fix 2 (BOOTSTRAP-RESAMPLES): `_run_bootstrap` calls block_bootstrap_ci
    with n_resamples=10000 (the documented production default), not 1000.
  - Fix 3 (WHITE-RC-ZERO-BASELINE): when n_trials==1 and no candidate_pool is
    supplied, White RC abstains (vote `passed=None`) instead of pairing
    against an artificial zeros baseline.
  - Fix 4 (MC-PERM-DIRECTIONS): when no `directions` are supplied, MC
    permutation abstains (vote `passed=None`) instead of inferring direction
    labels from the sign of returns.

Gate-threshold-with-abstentions semantics: operator chose strict (4-of-5
stays rigid; abstentions count as not-pass).

Network discipline: tests do not call FRED. The CPCV/bootstrap/PSR paths
are pure (no I/O), so we can run them freely. White RC and MC perm are
exercised through their abstention paths or with synthetic candidate
pools / explicit directions.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np
import pytest

from src.methods.cpcv import EmbargoZeroError, _apply_embargo
from src.methods.promotion_gate import (
    _run_bootstrap,
    _run_cpcv,
    _run_mc_perm,
    _run_white_rc,
    promotion_gate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RNG = np.random.default_rng(1234)


def _good_returns(n: int = 500, seed: int = 1234) -> np.ndarray:
    """Strong-edge returns; mean ~+0.006, std ~0.01."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n) * 0.01 + 0.006


def _bad_returns(n: int = 500, seed: int = 1234) -> np.ndarray:
    """Negative-edge returns."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n) * 0.01 - 0.006


def _vote(name: str, passed: bool | None, value: float | None = 0.03,
          threshold: float = 0.05) -> dict:
    """Helper for constructing canned vote dicts in mocked-runner tests."""
    return {"name": name, "passed": passed, "value": value, "threshold": threshold}


# ---------------------------------------------------------------------------
# Fix 1: CPCV-EMBARGO-ZERO — auto-FAIL when leakage-safe config impossible
# ---------------------------------------------------------------------------

class TestCpcvEmbargoZero:
    """Operator Q6=A: never silently disable leakage protection."""

    def test_apply_embargo_raises_when_train_idx_wiped(self):
        """`_apply_embargo` raises EmbargoZeroError when embargo eats every
        train index (the unit-level guard rail at the cpcv module surface)."""
        # 3 train indices, 1 test index, embargo=5 — every train falls within
        # 5 of the test index → empty result → must raise.
        train_idx = np.array([1, 2, 3], dtype=int)
        test_idx = np.array([5], dtype=int)
        with pytest.raises(EmbargoZeroError, match="leakage-safe|consumed every"):
            _apply_embargo(train_idx, test_idx, embargo=5)

    def test_apply_embargo_passes_when_some_indices_remain(self):
        """`_apply_embargo` returns a non-empty array when at least some
        train indices survive the embargo."""
        train_idx = np.array([100, 200, 300], dtype=int)
        test_idx = np.array([0], dtype=int)
        out = _apply_embargo(train_idx, test_idx, embargo=5)
        # None of [100, 200, 300] fall within 5 of test_idx=0 → all survive
        assert len(out) == 3
        assert set(out.tolist()) == {100, 200, 300}

    def test_cpcv_auto_fails_on_embargo_zero(self):
        """Small series + auto-shrink lands at infeasible config → CPCV
        vote returns `passed=False` with structured reason."""
        # 5 observations is well below k=2 * (embargo=1 + 1) = 4 minimum
        # at the strictest auto-shrink terminal config. Use n=3 to force
        # the feasibility check to fail.
        tiny = np.array([0.01, 0.02, -0.01], dtype=float)
        vote = _run_cpcv(tiny, alpha=0.05)
        assert vote["name"] == "cpcv"
        assert vote["passed"] is False, (
            f"expected auto-FAIL on tiny series; got {vote!r}"
        )
        assert vote["value"] is None
        assert "details" in vote
        assert vote["details"]["reason"] == "insufficient_data_for_leakage_safe_cpcv"
        assert "n_obs" in vote["details"]
        assert "k" in vote["details"]
        assert "min_required" in vote["details"]
        assert vote["details"]["n_obs"] == 3

    def test_cpcv_passes_when_series_supports_leakage_safe_config(self):
        """Sanity: a well-sized series still produces a normal CPCV vote
        (no auto-FAIL regression)."""
        returns = _good_returns(500)
        vote = _run_cpcv(returns, alpha=0.05)
        assert vote["passed"] is True
        assert vote["value"] is not None
        # Should NOT carry a `details["reason"]` — that only fires on auto-FAIL
        assert "details" not in vote or "reason" not in vote.get("details", {})

    def test_cpcv_auto_shrink_never_decrements_to_zero(self):
        """Verifies the auto-shrink loop guard: even with a series at the
        boundary (n=4), the loop must NOT produce embargo=0; the feasibility
        check then catches the overshoot and returns auto-FAIL."""
        # 4 observations: k=5 cannot fit, k=4 cannot, k=3 needs n>=6, k=2
        # needs n>=4 with embargo=1 → exactly fits!  So n=4 should pass
        # feasibility (k=2, embargo=1) — but n=3 should NOT.
        n3 = np.array([0.01, -0.02, 0.005], dtype=float)
        vote_n3 = _run_cpcv(n3, alpha=0.05)
        assert vote_n3["passed"] is False, (
            f"n=3 cannot support k=2 embargo=1 (need 4); got {vote_n3!r}"
        )

    def test_cpcv_logs_warning_with_canonical_marker(self, caplog):
        """[PROMOTION_GATE_CPCV_EMBARGO_ZERO] warning fires on auto-FAIL."""
        caplog.set_level(logging.WARNING, logger="src.methods.promotion_gate")
        tiny = np.array([0.01, 0.02, -0.01], dtype=float)
        _run_cpcv(tiny, alpha=0.05)
        msgs = [r.getMessage() for r in caplog.records
                if "[PROMOTION_GATE_CPCV_EMBARGO_ZERO]" in r.getMessage()]
        assert msgs, (
            "expected [PROMOTION_GATE_CPCV_EMBARGO_ZERO] warning; got "
            f"{[r.getMessage() for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# Fix 2: BOOTSTRAP-RESAMPLES — use 10000 (documented production default)
# ---------------------------------------------------------------------------

class TestBootstrapResamples:
    """Operator Q6=A: pin to the documented production default."""

    def test_bootstrap_uses_10000_resamples(self):
        """`_run_bootstrap` calls `block_bootstrap_ci` with n_resamples=10000."""
        returns = _good_returns(60)
        with patch(
            "src.methods.promotion_gate.block_bootstrap_ci",
            return_value=(0.05, 0.15),
        ) as mock_bb:
            _run_bootstrap(returns, alpha=0.05)
        assert mock_bb.call_count == 1
        kwargs = mock_bb.call_args.kwargs
        assert kwargs.get("n_resamples") == 10000, (
            f"expected n_resamples=10000 (production default per "
            f"docs/methodology-toolkit.md:56); got {kwargs.get('n_resamples')}. "
            "The prior 1000 was 1/10 of the documented resolution."
        )


# ---------------------------------------------------------------------------
# Fix 3: WHITE-RC-ZERO-BASELINE — abstain when no candidate_pool
# ---------------------------------------------------------------------------

class TestWhiteRcAbstention:
    """Operator Q6=A: skip White RC when single-strategy + no pool."""

    def test_white_rc_abstains_when_no_candidate_pool(self):
        """n_trials=1 + candidate_pool=None → vote returns passed=None
        with structured reason."""
        returns = _good_returns(60)
        vote = _run_white_rc(returns, alpha=0.05, n_trials=1, candidate_pool=None)
        assert vote["name"] == "white_rc"
        assert vote["passed"] is None, (
            f"expected abstention (passed=None) with n_trials=1 and no pool; "
            f"got {vote!r}"
        )
        assert vote["value"] is None
        assert "details" in vote
        assert vote["details"]["reason"] == "white_rc_requires_candidate_pool"
        assert vote["details"]["n_trials"] == 1

    def test_white_rc_runs_when_candidate_pool_supplied(self):
        """When a real candidate_pool is supplied, the test runs and
        produces a real p-value (no abstention)."""
        returns = _good_returns(60)
        rng = np.random.default_rng(99)
        # 2 competing strategies; cross-sectionally similar to returns
        pool = rng.normal(0.005, 0.01, size=(60, 2))
        vote = _run_white_rc(
            returns, alpha=0.05, n_trials=3, candidate_pool=pool,
        )
        assert vote["passed"] is not None, "expected real vote with pool"
        assert isinstance(vote["value"], float)
        assert 0.0 <= vote["value"] <= 1.0

    def test_white_rc_pool_length_mismatch_raises(self):
        """candidate_pool with wrong T raises ValueError."""
        returns = _good_returns(60)
        bad_pool = np.zeros((30, 2))  # T=30, but returns has T=60
        with pytest.raises(ValueError, match="must equal"):
            _run_white_rc(
                returns, alpha=0.05, n_trials=3, candidate_pool=bad_pool,
            )


# ---------------------------------------------------------------------------
# Fix 4: MC-PERM-DIRECTIONS — abstain when no directions supplied
# ---------------------------------------------------------------------------

class TestMcPermAbstention:
    """Operator Q6=A: skip MC perm when no real direction labels."""

    def test_mc_perm_abstains_when_directions_missing(self):
        """No `directions` parameter → vote returns passed=None with
        structured reason."""
        returns = _good_returns(60)
        vote = _run_mc_perm(returns, alpha=0.05, directions=None)
        assert vote["name"] == "mc_perm"
        assert vote["passed"] is None, (
            f"expected abstention (passed=None) without directions; got {vote!r}"
        )
        assert vote["value"] is None
        assert "details" in vote
        assert vote["details"]["reason"] == "mc_permutation_requires_real_directions"

    def test_mc_perm_runs_when_directions_supplied(self):
        """When real directions are supplied, the test runs and produces a
        real p-value."""
        returns = _good_returns(60)
        rng = np.random.default_rng(7)
        directions = rng.choice([1, -1], size=60).tolist()
        vote = _run_mc_perm(returns, alpha=0.05, directions=directions)
        assert vote["passed"] is not None, "expected real vote with directions"
        assert isinstance(vote["value"], float)
        assert 0.0 <= vote["value"] <= 1.0

    def test_mc_perm_directions_length_mismatch_raises(self):
        """directions with wrong length raises ValueError."""
        returns = _good_returns(60)
        with pytest.raises(ValueError, match="must equal"):
            _run_mc_perm(returns, alpha=0.05, directions=[1, -1, 1])


# ---------------------------------------------------------------------------
# Gate-decision-with-abstentions semantics — strict 4-of-5
# ---------------------------------------------------------------------------

class TestGateDecisionWithAbstentions:
    """Operator Q6=A operator-chose-strict: 4-of-5 stays rigid; abstentions
    count as not-pass."""

    def test_gate_decision_with_abstentions(self):
        """3 voted-pass + 2 abstain → strict 4-of-5 → reject."""
        # Mock the 5 runners: cpcv, bootstrap, mc_perm, psr/dsr, white_rc
        # 3 pass (cpcv, bootstrap, psr_dsr); 2 abstain (mc_perm, white_rc)
        with (
            patch("src.methods.promotion_gate._run_cpcv",
                  return_value=_vote("cpcv", True)),
            patch("src.methods.promotion_gate._run_bootstrap",
                  return_value=_vote("block_bootstrap", True)),
            patch("src.methods.promotion_gate._run_mc_perm",
                  return_value=_vote("mc_perm", None, value=None)),
            patch("src.methods.promotion_gate._run_psr",
                  return_value=_vote("psr_dsr", True)),
            patch("src.methods.promotion_gate._run_white_rc",
                  return_value=_vote("white_rc", None, value=None)),
            patch("src.methods.promotion_gate.mintrl", return_value=10),
        ):
            result = promotion_gate(_good_returns(500).tolist(), n_trials=1)
        assert result["decision"] == "reject", (
            f"3 passed + 2 abstain must FAIL strict 4-of-5; got {result!r}"
        )
        assert result["details"]["n_pass"] == 3
        assert result["details"]["n_abstentions"] == 2
        assert result["details"]["n_fail"] == 0

    def test_gate_promotes_with_4_pass_and_1_abstain(self):
        """4 voted-pass + 1 abstain → meets strict 4-of-5 → promote."""
        with (
            patch("src.methods.promotion_gate._run_cpcv",
                  return_value=_vote("cpcv", True)),
            patch("src.methods.promotion_gate._run_bootstrap",
                  return_value=_vote("block_bootstrap", True)),
            patch("src.methods.promotion_gate._run_mc_perm",
                  return_value=_vote("mc_perm", True, value=0.02)),
            patch("src.methods.promotion_gate._run_psr",
                  return_value=_vote("psr_dsr", True)),
            patch("src.methods.promotion_gate._run_white_rc",
                  return_value=_vote("white_rc", None, value=None)),
            patch("src.methods.promotion_gate.mintrl", return_value=10),
        ):
            result = promotion_gate(_good_returns(500).tolist(), n_trials=1)
        assert result["decision"] == "promote", (
            f"4 passed + 1 abstain must meet strict 4-of-5; got {result!r}"
        )
        assert result["details"]["n_pass"] == 4
        assert result["details"]["n_abstentions"] == 1
        assert result["details"]["n_fail"] == 0

    def test_gate_inverse_hard_block_skipped_when_mc_perm_abstains(self):
        """Abstention (passed=None, value=None) must NOT trigger
        inverse-hard-block detection — that detector requires a real p-value."""
        with (
            patch("src.methods.promotion_gate._run_cpcv",
                  return_value=_vote("cpcv", True)),
            patch("src.methods.promotion_gate._run_bootstrap",
                  return_value=_vote("block_bootstrap", True)),
            patch("src.methods.promotion_gate._run_mc_perm",
                  return_value=_vote("mc_perm", None, value=None)),
            patch("src.methods.promotion_gate._run_psr",
                  return_value=_vote("psr_dsr", True)),
            patch("src.methods.promotion_gate._run_white_rc",
                  return_value=_vote("white_rc", True)),
            patch("src.methods.promotion_gate.mintrl", return_value=10),
        ):
            # Use a strongly negative-mean series — would trip inverse-hard-block
            # IF MC perm had a real p-value >= 0.95.  With abstention, must not.
            result = promotion_gate(_bad_returns(500).tolist(), n_trials=1)
        # 4 pass + 1 abstain = strict 4-of-5 met → promote (not reject from
        # inverse-hard-block, which is the regression-locker).
        assert result["details"]["inverse_hard_block"] is False, (
            "inverse_hard_block must be False when MC perm abstains "
            f"(value=None); got {result!r}"
        )
        # Vote tally: 4 pass + 1 abstain → promote
        assert result["decision"] == "promote"

    def test_gate_details_carries_n_pass_n_fail_n_abstentions(self):
        """Top-level `details` dict carries n_pass / n_fail / n_abstentions
        counters for operator/dashboard introspection."""
        with (
            patch("src.methods.promotion_gate._run_cpcv",
                  return_value=_vote("cpcv", True)),
            patch("src.methods.promotion_gate._run_bootstrap",
                  return_value=_vote("block_bootstrap", False, value=0.10)),
            patch("src.methods.promotion_gate._run_mc_perm",
                  return_value=_vote("mc_perm", None, value=None)),
            patch("src.methods.promotion_gate._run_psr",
                  return_value=_vote("psr_dsr", True)),
            patch("src.methods.promotion_gate._run_white_rc",
                  return_value=_vote("white_rc", None, value=None)),
            patch("src.methods.promotion_gate.mintrl", return_value=10),
        ):
            result = promotion_gate(_good_returns(500).tolist(), n_trials=1)
        d = result["details"]
        assert d["n_pass"] == 2
        assert d["n_fail"] == 1
        assert d["n_abstentions"] == 2

    def test_real_gate_run_with_n_trials_1_no_directions_no_pool(self):
        """End-to-end smoke: with the production default invocation
        (n_trials=1, no directions, no candidate_pool), the gate runs without
        error, MC perm and White RC abstain, and the decision is `reject`
        (since at most 3 votes can pass under strict 4-of-5 with 2
        abstentions). No FRED I/O — `dates` not supplied."""
        returns = _good_returns(60).tolist()
        result = promotion_gate(returns, n_trials=1)
        assert result["votes"]["mc_perm"] is None, (
            "mc_perm must abstain in default invocation"
        )
        assert result["votes"]["white_rc"] is None, (
            "white_rc must abstain in default invocation"
        )
        assert result["details"]["n_abstentions"] == 2
        assert result["decision"] == "reject"
        # Per-method details preserved
        assert "details" in result["details"]["mc_perm"]
        assert (
            result["details"]["mc_perm"]["details"]["reason"]
            == "mc_permutation_requires_real_directions"
        )
        assert "details" in result["details"]["white_rc"]
        assert (
            result["details"]["white_rc"]["details"]["reason"]
            == "white_rc_requires_candidate_pool"
        )

    def test_real_gate_run_with_directions_and_pool_clears_abstentions(self):
        """When `directions` and `candidate_pool` are supplied, MC perm and
        White RC produce real votes — no abstentions."""
        rng = np.random.default_rng(12345)
        returns = rng.normal(0.005, 0.01, size=60)
        directions = rng.choice([1, -1], size=60).tolist()
        pool = rng.normal(0.0, 0.01, size=(60, 2))
        result = promotion_gate(
            returns.tolist(), n_trials=3,
            directions=directions, candidate_pool=pool,
        )
        assert result["votes"]["mc_perm"] is not None
        assert result["votes"]["white_rc"] is not None
        assert result["details"]["n_abstentions"] == 0
