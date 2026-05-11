"""Integration tests for the walk-forward runner (R1–R8 wired)."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest

from src.platform.rigor.walkforward_config import (
    DEFAULT_WINDOWS,
    WalkForwardConfig,
    WalkForwardWindow,
)
from src.platform.rigor.walkforward_firewall import R8ViolationError
from src.platform.rigor.walkforward_runner import (
    persist_run_result,
    process_window,
    run_walkforward,
)
from src.platform.rigor.walkforward_outcome import (
    STATE_FAIL, STATE_INCONCLUSIVE, STATE_PASS,
)
from src.schema.sqlite import create_all_tables


@dataclass
class FakeTrade:
    trade_id: str
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    excess_return: float | None = None
    exit_reason: str | None = "timeout"
    hold_days: int | None = 10
    vix_at_entry: float | None = 18.0
    shares: int | None = 100
    pnl_dollars: float | None = None


def _generate_trades(
    start: str, end: str, n: int, sharpe_target: float,
    seed: int = 0, vix: float = 18.0,
) -> list[FakeTrade]:
    """Generate synthetic trades spanning [start, end] with a target Sharpe."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    span = (e - s).days
    if span <= 1 or n < 1:
        return []
    rng = np.random.default_rng(seed)
    # Derive a mean/std from target Sharpe (daily basis; annualized ~15.87x)
    std = 0.02
    mean = (sharpe_target / (252 ** 0.5)) * std
    pnls = rng.normal(mean, std, size=n)
    trades = []
    for i, p in enumerate(pnls):
        entry = s + timedelta(days=int(span * i / max(n, 1)))
        exit_ = entry + timedelta(days=5)
        if exit_ > e:
            exit_ = e
        entry_price = 100.0 * (1.0 + rng.normal(0, 0.01))
        exit_price = entry_price * (1.0 + float(p))
        trades.append(FakeTrade(
            trade_id=f"t{seed}_{i}",
            ticker="AAPL",
            entry_date=entry.isoformat(),
            exit_date=exit_.isoformat(),
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=float(p),
            vix_at_entry=vix,
        ))
    return trades


def _minimal_spec(derived_from=None):
    spec = {"strategy_id": "wf_test", "derived_from": derived_from}
    return spec


def test_runner_rejects_missing_derived_from():
    cfg = WalkForwardConfig(strategy_id="wf_test")
    with pytest.raises(R8ViolationError, match="derived_from"):
        run_walkforward(
            strategy_spec_raw={"strategy_id": "wf_test"},  # no derived_from!
            config=cfg, window_trades={},
        )


def test_runner_raises_on_source_date_overlap():
    cfg = WalkForwardConfig(strategy_id="wf_test")
    spec = _minimal_spec({
        "source_type": "forensic_audit_ruleset",
        "source_run_id": "forensic_a",
        "source_date_range": {"start": "2020-01-01", "end": "2020-12-31"},
    })
    with pytest.raises(R8ViolationError, match="overlaps"):
        run_walkforward(
            strategy_spec_raw=spec, config=cfg, window_trades={},
        )


def test_runner_accepts_null_derived_from():
    """Null derived_from is allowed (organic / literature-derived). Runs
    without raising; outcome depends on the data supplied."""
    cfg = WalkForwardConfig(strategy_id="wf_test", windows=[
        WalkForwardWindow("2017-01-01", "2018-12-31", "2019-01-01", "2020-03-31"),
    ])
    spec = _minimal_spec(None)
    result = run_walkforward(
        strategy_spec_raw=spec, config=cfg,
        window_trades={0: {"is": [], "oos": []}},
    )
    # Empty OOS + single window: n_incdata=1, below threshold of 2, so
    # overall outcome falls through to criterion 2 (4 of 5 must pass) — FAIL.
    assert result.outcome.outcome_state == STATE_FAIL
    # Smoke-test that runner ran through R8 checks without raising.
    assert result.spec_hash


def test_runner_process_window_purges_and_embargoes():
    """Process a single window with IS straddler + OOS embargo candidate."""
    cfg = WalkForwardConfig(strategy_id="x")
    window = WalkForwardWindow(
        "2019-01-01", "2019-12-31", "2020-01-01", "2020-12-31",
    )
    is_trades = [
        FakeTrade(  # straddles boundary — should be purged
            trade_id="a", ticker="AAPL",
            entry_date="2019-12-20", exit_date="2020-01-10",
            entry_price=100.0, exit_price=101.0, pnl_pct=0.01,
        ),
        FakeTrade(  # entirely IS
            trade_id="b", ticker="AAPL",
            entry_date="2019-06-01", exit_date="2019-06-10",
            entry_price=100.0, exit_price=102.0, pnl_pct=0.02,
        ),
    ]
    oos_trades = [
        FakeTrade(  # within embargo
            trade_id="c", ticker="AAPL",
            entry_date="2020-01-02", exit_date="2020-01-10",
            entry_price=100.0, exit_price=101.0, pnl_pct=0.01,
        ),
        FakeTrade(  # past embargo
            trade_id="d", ticker="AAPL",
            entry_date="2020-02-01", exit_date="2020-02-10",
            entry_price=100.0, exit_price=103.0, pnl_pct=0.03,
        ),
    ]
    metrics, power, oos_costed = process_window(
        window_index=0, window=window,
        is_trades_raw=is_trades, oos_trades_raw=oos_trades,
        config=cfg, max_hold_days=21,
    )
    # Only the non-embargoed OOS trade contributes to metrics
    assert metrics.n_trades == 1


def test_runner_synthetic_inconclusive_path():
    """All windows N=5 → INCONCLUSIVE_DATA → overall INCONCLUSIVE."""
    cfg = WalkForwardConfig(strategy_id="wf_test")
    spec = _minimal_spec(None)
    window_trades = {}
    for i, w in enumerate(cfg.windows):
        oos = _generate_trades(
            w.test_start, w.test_end, n=5,
            sharpe_target=0.5, seed=i,
        )
        window_trades[i] = {"is": [], "oos": oos}
    result = run_walkforward(
        strategy_spec_raw=spec, config=cfg, window_trades=window_trades,
    )
    assert result.outcome.outcome_state == STATE_INCONCLUSIVE
    assert result.outcome.reason == "coverage_inconclusive"


def test_runner_synthetic_fail_path_drawdown():
    """Plenty of data in windows 1-4, one with DD > 20%, all past power gate.

    The MDE gate (R6 criterion 2) is genuinely demanding at per-trade
    granularity and synthetic N. For this test we raise mde_max so the
    synthetic windows pass the power gate and the criterion 4 drawdown
    check fires as intended. Production runs use mde_max=0.3 where
    the underpowering case is caught by INCONCLUSIVE_POWER."""
    cfg = WalkForwardConfig(strategy_id="wf_test", mde_max=100.0)
    spec = _minimal_spec(None)
    window_trades = {}
    for i, w in enumerate(cfg.windows):
        if i == 0:
            oos = [FakeTrade(
                trade_id=f"c{j}", ticker="AAPL",
                entry_date="2019-06-15", exit_date="2019-06-20",
                entry_price=100.0, exit_price=50.0, pnl_pct=-0.5,
                vix_at_entry=15.0,
            ) for j in range(15)]
        else:
            oos = _generate_trades(
                w.test_start, w.test_end, n=50,
                sharpe_target=1.0, seed=i, vix=10.0 if i % 2 else 30.0,
            )
        window_trades[i] = {"is": [], "oos": oos}
    result = run_walkforward(
        strategy_spec_raw=spec, config=cfg, window_trades=window_trades,
    )
    assert result.outcome.outcome_state == STATE_FAIL


def test_runner_persists_outcome_state_to_db(tmp_path):
    """End-to-end: runner + persist + round-trip the outcome_state."""
    db = tmp_path / "runner.sqlite3"
    create_all_tables(str(db))
    cfg = WalkForwardConfig(strategy_id="wf_test", windows=[
        WalkForwardWindow("2017-01-01", "2018-12-31", "2019-01-01", "2020-03-31"),
    ])
    spec = _minimal_spec(None)
    window_trades = {0: {"is": [], "oos": _generate_trades(
        "2019-01-01", "2020-03-31", n=20, sharpe_target=0.5,
    )}}
    result = run_walkforward(
        strategy_spec_raw=spec, config=cfg, window_trades=window_trades,
    )
    persist_run_result(
        result=result, strategy_spec_raw=spec,
        oos_trades_per_window=[window_trades[0]["oos"]], db_path=str(db),
    )
    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT outcome_state, reason FROM walkforward_results "
        "WHERE run_id = ?",
        (result.run_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] in {STATE_PASS, STATE_FAIL, STATE_INCONCLUSIVE}
    # The reason field must not be NULL or empty
    assert row[1]


def test_runner_deterministic_under_same_seed():
    """Two runs with the same spec + config + synthetic trades must produce
    the same outcome_state and the same pooled_sharpe to a tolerance (R5)."""
    cfg = WalkForwardConfig(strategy_id="wf_test")
    spec = _minimal_spec(None)
    window_trades = {}
    for i, w in enumerate(cfg.windows):
        window_trades[i] = {"is": [], "oos": _generate_trades(
            w.test_start, w.test_end, n=30, sharpe_target=0.5, seed=i,
        )}
    r1 = run_walkforward(
        strategy_spec_raw=spec, config=cfg, window_trades=window_trades,
    )
    r2 = run_walkforward(
        strategy_spec_raw=spec, config=cfg, window_trades=window_trades,
    )
    assert r1.outcome.outcome_state == r2.outcome.outcome_state
    assert r1.outcome.reason == r2.outcome.reason
    assert abs(r1.pooled_sharpe - r2.pooled_sharpe) < 1e-9
    assert r1.spec_hash == r2.spec_hash


def test_runner_three_outcome_states_all_reachable():
    """Build three synthetic inputs and verify the runner produces PASS,
    FAIL, and INCONCLUSIVE for each. This is the propagation audit for R6.
    Production mde_max=0.3 is genuinely hard to clear with 30-50 per-trade
    synthetic windows, so the FAIL and PASS cases raise mde_max so the
    criterion-2 power gate does not unintentionally divert to
    INCONCLUSIVE_POWER."""
    spec = _minimal_spec(None)

    # INCONCLUSIVE: all windows N=5 → INCONCLUSIVE_DATA across the board.
    # Override min_window_duration_days=0 so the v0.25.4 (#538) duration
    # gate doesn't intercept the v0.25.3 default 273-day Window 4 — this
    # test exercises the data/power/sharpe paths only; the duration path
    # is covered by tests/platform/rigor/test_window_duration.py.
    cfg_default = WalkForwardConfig(
        strategy_id="wf_test", min_window_duration_days=0,
    )
    incon_trades = {
        i: {"is": [], "oos": _generate_trades(w.test_start, w.test_end, 5, 0.5, i)}
        for i, w in enumerate(cfg_default.windows)
    }
    r = run_walkforward(spec, cfg_default, incon_trades)
    assert r.outcome.outcome_state == STATE_INCONCLUSIVE

    # FAIL: big drawdown in window 0, good elsewhere. Power gate relaxed.
    cfg_relaxed = WalkForwardConfig(
        strategy_id="wf_test", mde_max=100.0, min_window_duration_days=0,
    )
    fail_trades = {}
    for i, w in enumerate(cfg_relaxed.windows):
        if i == 0:
            fail_trades[i] = {"is": [], "oos": [FakeTrade(
                trade_id=f"x{j}", ticker="AAPL",
                entry_date="2019-06-15", exit_date="2019-06-20",
                entry_price=100.0, exit_price=50.0, pnl_pct=-0.5,
                vix_at_entry=15.0,
            ) for j in range(15)]}
        else:
            fail_trades[i] = {"is": [], "oos": _generate_trades(
                w.test_start, w.test_end, 30, 1.0, seed=i,
                vix=10.0 if i % 2 == 0 else 30.0,
            )}
    r = run_walkforward(spec, cfg_relaxed, fail_trades)
    assert r.outcome.outcome_state == STATE_FAIL

    # PASS: strong Sharpe in all windows, mixed VIX, small DD.
    cfg_pass = WalkForwardConfig(
        strategy_id="wf_test", mde_max=100.0, pooled_sharpe_min=0.1,
        min_window_duration_days=0,
    )
    pass_trades = {
        i: {"is": [], "oos": _generate_trades(
            w.test_start, w.test_end, n=40, sharpe_target=2.0, seed=i + 100,
            vix=10.0 if i % 2 == 0 else 30.0,
        )}
        for i, w in enumerate(cfg_pass.windows)
    }
    r = run_walkforward(spec, cfg_pass, pass_trades)
    assert r.outcome.outcome_state == STATE_PASS


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 1 T1.15 — persist_run_result engine_aware_upsert dual-engine
# ---------------------------------------------------------------------------
#
# Test strategy (per T1.15 brief):
#   * walkforward_results AND walkforward_trades both classified
#     `in_place_update` per T0.12 audit §5.7 + §5.8. Both are written by
#     persist_run_result() in src/platform/rigor/walkforward_runner.py — the
#     parent-then-child INSERT pattern via `run_id` is NOT declared as a
#     registry ForeignKey (audit §6.2), so the dispatch behavior is uniform
#     across engines: replace-on-PK without cascade.
#   * Parametrized across [sqlite, postgres] like
#     tests/evaluation/test_build_score.py — PG path skips cleanly when
#     TEST_DATABASE_URL / DATABASE_URL is not a postgres:// URL.
#   * Each test exercises the engine_aware_upsert helper directly with
#     deterministic PKs so the REPLACE conflict path actually fires; on the
#     second insert with same PK, non-target columns must be updated.

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


def _build_sqlite_ddl_runner(table_name):
    """Return SQLite CREATE TABLE SQL for one of the audited tables."""
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    cols = []
    for c in td.columns:
        nn = "" if c.nullable else " NOT NULL"
        cols.append(f"{c.name} {c.type}{nn}")
    pk = td.primary_key if isinstance(td.primary_key, list) else [td.primary_key]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")
    body = ",\n    ".join(cols)
    return f"CREATE TABLE {table_name} (\n    {body}\n);"


def _build_pg_ddl_runner(table_name):
    """Return Postgres CREATE TABLE SQL for one of the audited tables."""
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


@pytest.fixture
def sqlite_conn_runner():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn_runner():
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set."""
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    yield wrapper
    try:
        wrapper.rollback()
    except Exception:
        pass
    wrapper.close()


def _setup_walkforward_table(conn, table_name):
    """Drop+recreate `table_name` on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(_build_pg_ddl_runner(table_name))
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl_runner(table_name))
        conn.commit()


def _get_runner_conn(request):
    """Return the conn fixture matching the parametrized engine."""
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn_runner")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn_runner")
    raise ValueError(f"unknown engine: {engine}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine_runner(request):
    return _get_runner_conn(request)


def _count_rows_runner(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


def _walkforward_results_row(run_id, outcome_state="PASS", pooled_sharpe=1.5,
                              reason="ok"):
    """Construct a minimal walkforward_results row dict."""
    return {
        "run_id": run_id,
        "strategy_id": "wf_t1.15",
        "spec_hash": "deadbeef",
        "code_git_sha": None,
        "random_seed": 42,
        "config_json": "{}",
        "outcome_state": outcome_state,
        "reason": reason,
        "pooled_sharpe": pooled_sharpe,
        "pooled_mde": 0.3,
        "heavy_tail_flag": 0,
        "heavy_tail_window_count": 0,
        "n_windows": 5,
        "n_windows_pass": 4,
        "n_windows_fail": 1,
        "n_windows_inconclusive_data": 0,
        "n_windows_inconclusive_power": 0,
        "n_windows_inconclusive_duration": 0,
        "derived_from_source_type": None,
        "derived_from_source_run_id": None,
        "effective_universe_size": 100,
        "max_drawdown_pct": -5.5,
        "vix_tier_coverage": 3,
        "created_at": "2026-05-11T10:00:00",
    }


def _walkforward_trades_row(trade_id, run_id, pnl_pct=0.01, vix_tier="MID"):
    """Construct a minimal walkforward_trades row dict."""
    return {
        "trade_id": trade_id,
        "run_id": run_id,
        "window_index": 0,
        "is_in_is_window": 0,
        "ticker": "AAPL",
        "entry_date": "2020-01-15",
        "exit_date": "2020-01-25",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl_pct": pnl_pct,
        "excess_return": 0.005,
        "exit_reason": "timeout",
        "hold_days": 10,
        "vix_at_entry": 18.0,
        "vix_tier": vix_tier,
        "purged": 0,
        "embargoed": 0,
        "quarantined": 0,
        "sharpe_observed": 0.5,
        "bootstrap_se": 0.1,
        "mde_value": 0.3,
    }


class TestWalkforwardResultsEngineAwareUpsert:
    """T1.15: walkforward_results.engine_aware_upsert dual-engine coverage."""

    def test_first_insert_lands_row(self, conn_engine_runner):
        """T1.15 #1: first insert against walkforward_results lands the row."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_runner
        _setup_walkforward_table(conn, "walkforward_results")

        row = _walkforward_results_row("fixed-run-1", outcome_state="PASS")
        engine_aware_upsert(conn, "walkforward_results", row, action="replace")
        conn.commit()

        assert _count_rows_runner(conn, "walkforward_results") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walkforward_results WHERE run_id=?", ("fixed-run-1",)
        )
        fetched = cur.fetchone()
        assert fetched["outcome_state"] == "PASS"
        assert fetched["pooled_sharpe"] == 1.5

    def test_replace_updates_existing_row(self, conn_engine_runner):
        """T1.15 #2: re-upserting same run_id UPDATES non-target columns."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_runner
        _setup_walkforward_table(conn, "walkforward_results")

        row1 = _walkforward_results_row(
            "fixed-run-2", outcome_state="INCONCLUSIVE", pooled_sharpe=0.5,
            reason="coverage_inconclusive",
        )
        engine_aware_upsert(conn, "walkforward_results", row1, action="replace")

        # Second persist with same run_id but updated outcome (re-rerun)
        row2 = _walkforward_results_row(
            "fixed-run-2", outcome_state="PASS", pooled_sharpe=2.1,
            reason="ok",
        )
        engine_aware_upsert(conn, "walkforward_results", row2, action="replace")
        conn.commit()

        assert _count_rows_runner(conn, "walkforward_results") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walkforward_results WHERE run_id=?", ("fixed-run-2",)
        )
        fetched = cur.fetchone()
        assert fetched["outcome_state"] == "PASS"
        assert fetched["pooled_sharpe"] == 2.1
        assert fetched["reason"] == "ok"


class TestWalkforwardTradesEngineAwareUpsert:
    """T1.15: walkforward_trades.engine_aware_upsert dual-engine coverage."""

    def test_first_insert_lands_row(self, conn_engine_runner):
        """T1.15 #3: first insert against walkforward_trades lands the row."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_runner
        _setup_walkforward_table(conn, "walkforward_trades")

        row = _walkforward_trades_row("fixed-trade-1", "fixed-run-1",
                                       pnl_pct=0.025)
        engine_aware_upsert(conn, "walkforward_trades", row, action="replace")
        conn.commit()

        assert _count_rows_runner(conn, "walkforward_trades") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walkforward_trades WHERE trade_id=?",
            ("fixed-trade-1",),
        )
        fetched = cur.fetchone()
        assert fetched["pnl_pct"] == 0.025
        assert fetched["ticker"] == "AAPL"

    def test_replace_updates_existing_row(self, conn_engine_runner):
        """T1.15 #4: re-upserting same trade_id UPDATES non-target columns."""
        from src.utils.db import engine_aware_upsert

        conn = conn_engine_runner
        _setup_walkforward_table(conn, "walkforward_trades")

        row1 = _walkforward_trades_row("fixed-trade-2", "fixed-run-1",
                                        pnl_pct=0.01, vix_tier="LOW")
        engine_aware_upsert(conn, "walkforward_trades", row1, action="replace")

        # Re-persist same trade_id with updated pnl + vix_tier
        row2 = _walkforward_trades_row("fixed-trade-2", "fixed-run-1",
                                        pnl_pct=0.05, vix_tier="HIGH")
        engine_aware_upsert(conn, "walkforward_trades", row2, action="replace")
        conn.commit()

        assert _count_rows_runner(conn, "walkforward_trades") == 1
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM walkforward_trades WHERE trade_id=?",
            ("fixed-trade-2",),
        )
        fetched = cur.fetchone()
        assert fetched["pnl_pct"] == 0.05
        assert fetched["vix_tier"] == "HIGH"


def test_persist_run_result_no_literal_insert_or_replace_in_source():
    """T1.15 lock-in: walkforward_runner.py must not contain `INSERT OR REPLACE`."""
    from pathlib import Path

    runner_path = (
        Path(__file__).resolve().parents[3]
        / "src" / "platform" / "rigor" / "walkforward_runner.py"
    )
    source = runner_path.read_text(encoding="utf-8")
    assert "INSERT OR REPLACE" not in source, (
        "src/platform/rigor/walkforward_runner.py must not contain literal "
        "`INSERT OR REPLACE` after T1.15 migration; use "
        "engine_aware_upsert(action='replace') via src.utils.db instead."
    )
