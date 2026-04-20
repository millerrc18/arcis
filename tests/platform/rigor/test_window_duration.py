"""Window-duration sub-state tests (#538, v0.25.4 Part B).

Adds an INCONCLUSIVE_WINDOW_DURATION sub-state so operators can
distinguish "strategy didn't signal" (INCONCLUSIVE_DATA) from "the
window itself was too short" (the new sub-state).

Pass 1 chose Option 1 (sub-state) over Option 2 (new walkforward_windows
table). Threshold = 365 days. Precedence: INCONCLUSIVE_DURATION beats
INCONCLUSIVE_DATA at both per-window classification and run-level
reducer.

Tests in TDD order:

  Reducer (walkforward_outcome.reduce_outcome):
    1. Two windows flagged INCONCLUSIVE_DURATION → run-level INCONCLUSIVE
       with reason "duration_inconclusive".
    2. INCONCLUSIVE_DURATION takes precedence over INCONCLUSIVE_DATA
       at run level (both at threshold → duration wins).
    3. INCONCLUSIVE_DURATION takes precedence over INCONCLUSIVE_POWER
       at run level (both at threshold → duration wins).
    4. One INCONCLUSIVE_DURATION (below threshold of 2) does NOT flip
       overall — falls through to existing logic.
    5. OutcomeResult has n_windows_inconclusive_duration field with
       correct count.

  Power state classifier (walkforward_power.count_power_states):
    6. Short window (<365d) gets WINDOW_INCONCLUSIVE_DURATION even when
       trade count is high enough.
    7. Long window (≥365d) keeps the existing classification (PASS /
       FAIL / INCONCLUSIVE_POWER / INCONCLUSIVE_DATA).
    8. Short window with insufficient trades is flagged DURATION, not
       DATA — duration takes precedence per-window.
    9. Threshold boundary: 273-day window flagged, 365-day window not.

  Config (walkforward_config.WalkForwardConfig):
   10. Default min_window_duration_days is 365.
   11. Field round-trips through as_json_dict().

  v0.25.3 retrofit:
   12. DEFAULT_WINDOWS yields Window 4 as INCONCLUSIVE_DURATION, run-level
       stays INCONCLUSIVE/coverage_inconclusive (only 1 short window;
       inconclusive_window_threshold = 2).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from src.platform.rigor.walkforward_config import (
    DEFAULT_WINDOWS,
    WalkForwardConfig,
    WalkForwardWindow,
)


# ---------------------------------------------------------------------------
# Reducer tests — walkforward_outcome.reduce_outcome
# ---------------------------------------------------------------------------

KW = dict(
    pooled_sharpe_min=0.5,
    max_drawdown_cap_pct=0.20,
    min_vix_tiers=2,
    windows_passing_criterion_2=4,
    inconclusive_window_threshold=2,
)


def test_two_inconclusive_duration_gives_inconclusive_duration():
    from src.platform.rigor.walkforward_outcome import (
        STATE_INCONCLUSIVE,
        WINDOW_INCONCLUSIVE_DURATION,
        WINDOW_PASS,
        reduce_outcome,
    )

    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS, 2: WINDOW_PASS,
        3: WINDOW_INCONCLUSIVE_DURATION, 4: WINDOW_INCONCLUSIVE_DURATION,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "duration_inconclusive"
    assert out.n_windows_inconclusive_duration == 2


def test_inconclusive_duration_takes_precedence_over_data():
    from src.platform.rigor.walkforward_outcome import (
        STATE_INCONCLUSIVE,
        WINDOW_INCONCLUSIVE_DATA,
        WINDOW_INCONCLUSIVE_DURATION,
        WINDOW_PASS,
        reduce_outcome,
    )

    states = {
        0: WINDOW_INCONCLUSIVE_DURATION, 1: WINDOW_INCONCLUSIVE_DURATION,
        2: WINDOW_INCONCLUSIVE_DATA, 3: WINDOW_INCONCLUSIVE_DATA,
        4: WINDOW_PASS,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "duration_inconclusive"


def test_inconclusive_duration_takes_precedence_over_power():
    from src.platform.rigor.walkforward_outcome import (
        STATE_INCONCLUSIVE,
        WINDOW_INCONCLUSIVE_DURATION,
        WINDOW_INCONCLUSIVE_POWER,
        WINDOW_PASS,
        reduce_outcome,
    )

    states = {
        0: WINDOW_INCONCLUSIVE_DURATION, 1: WINDOW_INCONCLUSIVE_DURATION,
        2: WINDOW_INCONCLUSIVE_POWER, 3: WINDOW_INCONCLUSIVE_POWER,
        4: WINDOW_PASS,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "duration_inconclusive"


def test_one_inconclusive_duration_falls_through_to_existing_logic():
    """Threshold is 2: a single short window doesn't flip the run state.
    Falls through to whatever the rest of the windows say (PASS here)."""
    from src.platform.rigor.walkforward_outcome import (
        STATE_PASS,
        WINDOW_INCONCLUSIVE_DURATION,
        WINDOW_PASS,
        reduce_outcome,
    )

    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS, 2: WINDOW_PASS,
        3: WINDOW_PASS, 4: WINDOW_INCONCLUSIVE_DURATION,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    # 4 PASS satisfies criterion_2_windows; 1 duration < threshold; falls
    # through to PASS (overall).
    assert out.outcome_state == STATE_PASS
    assert out.n_windows_inconclusive_duration == 1


def test_outcome_result_has_n_windows_inconclusive_duration_field():
    """Counter field must be present on OutcomeResult, populated in every
    reducer return path."""
    from src.platform.rigor.walkforward_outcome import (
        WINDOW_PASS,
        reduce_outcome,
    )

    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert hasattr(out, "n_windows_inconclusive_duration")
    assert out.n_windows_inconclusive_duration == 0


# ---------------------------------------------------------------------------
# Power state classifier tests — walkforward_power.count_power_states
# ---------------------------------------------------------------------------

@dataclass
class _FakePower:
    window_index: int
    passes_power_gate: bool = True
    passes_sharpe_gate: bool = True


def _w(test_start: str, test_end: str) -> WalkForwardWindow:
    """Convenience factory: build a window with sentinel IS dates that
    won't fail validation. Real callers always set IS dates strictly
    before test_start; we use a fixed 2-year flank ending one day before
    test_start."""
    from datetime import date, timedelta

    test_s = date.fromisoformat(test_start)
    train_end = (test_s - timedelta(days=1)).isoformat()
    train_start = (test_s.replace(year=test_s.year - 2)).isoformat()
    return WalkForwardWindow(
        train_start=train_start, train_end=train_end,
        test_start=test_start, test_end=test_end,
    )


def test_count_power_states_flags_short_window_as_inconclusive_duration():
    """A 273-day window with plenty of trades + power → INCONCLUSIVE_DURATION."""
    from src.platform.rigor.walkforward_power import count_power_states

    powers = [_FakePower(window_index=0)]
    windows = [_w("2024-01-01", "2024-09-30")]  # 273 days
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[20], windows=windows,
        min_window_duration_days=365,
    )
    assert states[0] == "INCONCLUSIVE_DURATION"


def test_count_power_states_long_window_keeps_existing_state():
    """A 455-day window classifies via existing logic."""
    from src.platform.rigor.walkforward_power import count_power_states

    powers = [_FakePower(window_index=0,
                         passes_power_gate=True, passes_sharpe_gate=True)]
    windows = [_w("2019-01-01", "2020-03-31")]  # 455 days
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[20], windows=windows,
        min_window_duration_days=365,
    )
    assert states[0] == "PASS"


def test_count_power_states_short_window_overrides_data_signal():
    """Short window + insufficient trades: state = DURATION not DATA."""
    from src.platform.rigor.walkforward_power import count_power_states

    powers = [_FakePower(window_index=0)]
    windows = [_w("2024-01-01", "2024-09-30")]  # 273 days, short
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[3], windows=windows,  # also too few trades
        min_window_duration_days=365,
    )
    assert states[0] == "INCONCLUSIVE_DURATION"


def test_count_power_states_threshold_at_365_classifies_273_as_short():
    """Boundary test: 273 days < 365 → DURATION."""
    from src.platform.rigor.walkforward_power import count_power_states

    powers = [_FakePower(window_index=0)]
    windows = [_w("2024-01-01", "2024-09-30")]  # 273 days
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[20], windows=windows,
        min_window_duration_days=365,
    )
    assert states[0] == "INCONCLUSIVE_DURATION"


def test_count_power_states_threshold_at_365_passes_365_day_window():
    """Boundary test: exactly 365 days → NOT short (≥ threshold)."""
    from src.platform.rigor.walkforward_power import count_power_states

    powers = [_FakePower(window_index=0)]
    # 2023-01-01 → 2024-01-01 = 365 days
    windows = [_w("2023-01-01", "2024-01-01")]
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[20], windows=windows,
        min_window_duration_days=365,
    )
    assert states[0] == "PASS"


# ---------------------------------------------------------------------------
# Config tests — walkforward_config
# ---------------------------------------------------------------------------

def test_walkforward_config_has_min_window_duration_days_default_365():
    cfg = WalkForwardConfig(strategy_id="x")
    assert cfg.min_window_duration_days == 365


def test_walkforward_config_min_window_duration_days_round_trips():
    cfg = WalkForwardConfig(strategy_id="x", min_window_duration_days=270)
    j = cfg.as_json_dict()
    assert j["min_window_duration_days"] == 270


# ---------------------------------------------------------------------------
# Runner integration — persistence + retrofit
# ---------------------------------------------------------------------------

def test_runner_persists_n_windows_inconclusive_duration(tmp_path):
    """End-to-end: persist a result whose outcome carries duration count.
    walkforward_results row must surface the new counter."""
    from src.platform.rigor.walkforward_metrics import WindowMetrics
    from src.platform.rigor.walkforward_outcome import OutcomeResult
    from src.platform.rigor.walkforward_power import PowerResult
    from src.platform.rigor.walkforward_runner import (
        WalkForwardRunResult, persist_run_result,
    )
    from src.schema.sqlite import create_all_tables

    db_path = str(tmp_path / "wf.sqlite3")
    create_all_tables(db_path)

    metrics = WindowMetrics(
        window_index=0, n_trades=0, mean_pnl_pct=0.0, std_pnl_pct=0.0,
        sharpe=0.0, max_drawdown_pct=0.0, parametric_se=1.0,
        bootstrap_se=1.0, heavy_tail_flag=False, vix_tiers_represented=set(),
    )
    power = PowerResult(
        window_index=0, observed_sharpe=0.0, mde=float("inf"),
        effective_n=0, se_used=1.0, heavy_tail_flag=False,
        passes_power_gate=False, passes_sharpe_gate=False,
    )
    outcome = OutcomeResult(
        outcome_state="INCONCLUSIVE", reason="duration_inconclusive",
        n_windows_pass=0, n_windows_fail=0,
        n_windows_inconclusive_power=0, n_windows_inconclusive_data=0,
        n_windows_inconclusive_duration=2,
    )
    config = WalkForwardConfig(strategy_id="test_dur")
    result = WalkForwardRunResult(
        run_id="run-dur", strategy_id="test_dur", spec_hash="abc",
        code_git_sha=None, outcome=outcome, pooled_sharpe=0.0,
        pooled_mde=float("inf"), heavy_tail_window_count=0,
        window_metrics=[metrics], window_power=[power],
        window_states={0: "INCONCLUSIVE_DURATION"}, vix_tier_coverage=0,
        effective_universe_size=100, config=config,
    )
    persist_run_result(
        result=result, strategy_spec_raw={"derived_from": None},
        oos_trades_per_window=[[]], db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT outcome_state, reason, n_windows_inconclusive_duration "
        "FROM walkforward_results WHERE run_id = ?", ("run-dur",),
    ).fetchone()
    conn.close()
    assert row[0] == "INCONCLUSIVE"
    assert row[1] == "duration_inconclusive"
    assert row[2] == 2


def test_v0_25_3_window_4_retrofit_via_count_power_states():
    """Retrofit verification: the v0.25.3 DEFAULT_WINDOWS produces Window 4
    (273 days) as INCONCLUSIVE_DURATION, while Windows 0-3 keep their
    existing semantics. Run-level stays INCONCLUSIVE/coverage_inconclusive
    because only 1 short window < threshold of 2."""
    from src.platform.rigor.walkforward_outcome import (
        STATE_INCONCLUSIVE,
        reduce_outcome,
    )
    from src.platform.rigor.walkforward_power import count_power_states

    # All 5 v0.25.3 windows had n_trades < 10 (1, 4, 4, 4, 7 from the
    # validation doc). With sufficient trades + low Sharpe they'd be FAIL,
    # but this fixture mirrors the actual v0.25.3 trade counts so the
    # data signal would normally fire on all 5.
    powers = [
        _FakePower(window_index=i, passes_power_gate=False,
                   passes_sharpe_gate=False)
        for i in range(5)
    ]
    windows = list(DEFAULT_WINDOWS)  # 4 long + 1 short (Window 4)
    states = count_power_states(
        powers, min_trades_per_window=10,
        n_trades_per_window=[4, 7, 4, 4, 1], windows=windows,
        min_window_duration_days=365,
    )
    # Window 4 flips to DURATION instead of DATA
    assert states[4] == "INCONCLUSIVE_DURATION"
    # Windows 0-3 stay DATA (each has < 10 trades)
    for i in range(4):
        assert states[i] == "INCONCLUSIVE_DATA"

    # Run-level: 4 DATA + 1 DURATION → DATA wins by threshold (≥2 DATA)
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.0] * 5,
        pooled_sharpe=0.0, distinct_vix_tiers=0,
        pooled_sharpe_min=0.5, max_drawdown_cap_pct=0.20,
        min_vix_tiers=2, windows_passing_criterion_2=4,
        inconclusive_window_threshold=2,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "coverage_inconclusive"
    assert out.n_windows_inconclusive_data == 4
    assert out.n_windows_inconclusive_duration == 1
