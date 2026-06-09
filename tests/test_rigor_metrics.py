"""Tests for src.console.rigor_metrics (F5 — PBO matrix builder + envelope).

PBO via CSCV is meaningless on a single configuration. These tests pin the
HONEST contract: a real N-config (>=2) x T-period (>=8) matrix yields a PBO in
[0, 1]; anything thinner degrades to state='insufficient_configs' with value
None — NEVER a fabricated PBO. They also verify that the S chosen for the
underlying pbo() call is always even/>=2/<=n_periods so pbo()'s own guards
never raise out of build_pbo_envelope.

The DB is mocked at the src.console.rigor_metrics.connect_db seam — no live
DB rows are required, so the matrix-building logic is exercised
deterministically and the honesty paths are reachable.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest

from src.console import rigor_metrics


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Returns canned rows keyed by a substring of the SQL it is asked to run.

    `responses` is a list of (sql_substring, rows) pairs; the first whose
    substring is found in the executed SQL wins. Unmatched queries return [].
    """

    def __init__(self, responses):
        self._responses = responses

    def execute(self, sql, params=None):
        for needle, rows in self._responses:
            if needle in sql:
                return _FakeCursor(rows)
        return _FakeCursor([])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_conn(responses):
    """Patch the connect_db seam to hand back a _FakeConn with `responses`."""

    @contextmanager
    def _cm():
        with patch.object(
            rigor_metrics, "connect_db", return_value=_FakeConn(responses)
        ):
            yield

    return _cm()


def _trade_rows(config_to_returns):
    """Build backtest_trades-shaped rows: (result_id, pnl_pct, exit_date).

    `config_to_returns` maps a config id -> list of per-trade pnl_pct floats.
    exit_date is a monotonic sequence so any ORDER BY exit_date is stable.
    """
    rows = []
    for cfg, returns in config_to_returns.items():
        for i, r in enumerate(returns):
            rows.append(
                {
                    "result_id": cfg,
                    "pnl_pct": r,
                    "exit_date": f"2026-01-{i + 1:02d}",
                }
            )
    return rows


# ---------------------------------------------------------------------------
# (1) Happy path: >=2 configs x >=8 aligned periods -> matrix + state='ok'
# ---------------------------------------------------------------------------


class TestBuildConfigReturnsMatrixHappy:
    def test_two_configs_eight_periods_builds_matrix(self):
        rng = np.random.default_rng(0)
        cfgs = {
            "cfg_a": list(rng.standard_normal(10)),
            "cfg_b": list(rng.standard_normal(10)),
        }
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            matrix, meta = rigor_metrics.build_config_returns_matrix()
        assert matrix is not None
        # Common length is 10; N configs is 2.
        assert matrix.shape == (10, 2)
        assert matrix.dtype == float
        assert meta["n_configs"] == 2
        assert meta["n_periods"] == 10

    def test_unequal_lengths_truncate_to_common_min(self):
        cfgs = {
            "cfg_a": [0.01] * 12,
            "cfg_b": [0.02] * 9,
        }
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            matrix, meta = rigor_metrics.build_config_returns_matrix()
        assert matrix is not None
        # min(12, 9) == 9 rows; 2 columns.
        assert matrix.shape == (9, 2)
        assert meta["n_periods"] == 9
        assert meta["n_configs"] == 2


class TestBuildPboEnvelopeHappy:
    def test_state_ok_value_in_unit_interval(self):
        rng = np.random.default_rng(42)
        cfgs = {
            f"cfg_{j}": list(rng.standard_normal(40)) for j in range(6)
        }
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            env = rigor_metrics.build_pbo_envelope()
        assert env["state"] == "ok"
        assert env["value"] is not None
        assert 0.0 <= env["value"] <= 1.0
        assert env["cohort"] == "rigor"
        assert env["unit"] == "probability"
        assert env["n"] == 6
        assert set(env.keys()) == {
            "value", "n", "as_of", "cohort", "unit", "state"
        }

    def test_value_rounded_to_four_dp(self):
        rng = np.random.default_rng(3)
        cfgs = {f"cfg_{j}": list(rng.standard_normal(30)) for j in range(4)}
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            env = rigor_metrics.build_pbo_envelope()
        assert env["state"] == "ok"
        # round(x, 4): at most 4 decimal places.
        assert env["value"] == round(env["value"], 4)


# ---------------------------------------------------------------------------
# (2) HONESTY: single config OR <8 periods -> None / insufficient_configs.
#     Verify-by-mutation: these would FAIL if a fabricated PBO were returned.
# ---------------------------------------------------------------------------


class TestHonestyDegradation:
    def test_single_config_degrades(self):
        cfgs = {"cfg_only": [0.01] * 20}
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            matrix, meta = rigor_metrics.build_config_returns_matrix()
            env = rigor_metrics.build_pbo_envelope()
        assert matrix is None
        assert meta["n_configs"] == 1
        assert env["state"] == "insufficient_configs"
        # NEVER a fabricated PBO on one config.
        assert env["value"] is None
        assert env["n"] == 1
        assert env["n"] == meta["n_configs"]

    def test_zero_configs_degrades(self):
        # Mirrors the REAL DB today: backtest_trades empty -> 0 configs.
        with _patch_conn([("backtest_trades", [])]):
            matrix, meta = rigor_metrics.build_config_returns_matrix()
            env = rigor_metrics.build_pbo_envelope()
        assert matrix is None
        assert meta["n_configs"] == 0
        assert env["state"] == "insufficient_configs"
        assert env["value"] is None
        assert env["n"] == 0

    def test_two_configs_too_few_periods_degrades(self):
        # 2 configs but only 5 aligned periods (< T_min=8) -> degrade.
        cfgs = {"cfg_a": [0.01] * 5, "cfg_b": [0.02] * 5}
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            matrix, meta = rigor_metrics.build_config_returns_matrix()
            env = rigor_metrics.build_pbo_envelope()
        assert matrix is None
        assert meta["n_periods"] == 5
        assert env["state"] == "insufficient_configs"
        assert env["value"] is None

    def test_envelope_value_is_never_a_number_on_insufficient(self):
        # Verify-by-mutation guard: assert the type is None, not float, so a
        # stub that returned e.g. 0.0 or 0.5 would fail this test.
        cfgs = {"cfg_only": [0.05] * 50}
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            env = rigor_metrics.build_pbo_envelope()
        assert env["value"] is None
        assert not isinstance(env["value"], float)


# ---------------------------------------------------------------------------
# (3) S-clamping: pbo()'s guards (S even, >=2, and S<=usable T) must NEVER
#     raise out of build_pbo_envelope, regardless of n_periods.
# ---------------------------------------------------------------------------


class TestSClamping:
    @pytest.mark.parametrize("t", [8, 9, 10, 11, 14, 17, 33])
    def test_pbo_guards_never_raise_across_T(self, t):
        rng = np.random.default_rng(t)
        cfgs = {f"cfg_{j}": list(rng.standard_normal(t)) for j in range(4)}
        rows = _trade_rows(cfgs)
        with _patch_conn([("backtest_trades", rows)]):
            # Must not raise — S must be clamped to an even int in [2, t].
            env = rigor_metrics.build_pbo_envelope()
        assert env["state"] == "ok"
        assert 0.0 <= env["value"] <= 1.0

    def test_chosen_S_is_even_and_within_bounds(self):
        # T=8 (minimum). The chosen S must be even, >=2, <= 8 so pbo() runs.
        rng = np.random.default_rng(1)
        cfgs = {f"cfg_{j}": list(rng.standard_normal(8)) for j in range(3)}
        rows = _trade_rows(cfgs)
        captured = {}
        real_pbo = rigor_metrics.pbo

        def _spy(matrix, S):
            captured["S"] = S
            return real_pbo(matrix, S=S)

        with _patch_conn([("backtest_trades", rows)]):
            with patch.object(rigor_metrics, "pbo", side_effect=_spy):
                env = rigor_metrics.build_pbo_envelope()
        assert env["state"] == "ok"
        assert captured["S"] % 2 == 0
        assert 2 <= captured["S"] <= 8
