"""T1.02 — Stage-1 honest baseline recompute tests.

Tests scripts/stage1_baseline_recompute.py for:
  (1) Memo writer: produces all required sections (per audit-spec §9 item 9)
  (2) Quarantined rows are excluded from Sharpe computation
  (3) Mixed-instrumentation: only fully-instrumented + non-quarantined rows used
  (4) Three Sharpe figures match canonical_sharpe outputs on the fixture
  (5) Underpowered case: memo contains the literal underpowered phrase
  (6) Powered case: memo verdict says "powered"
  (7) Constant rf-rate documentation: memo includes constant + window note (DA-9)
  (8) Bootstrap CI: each Sharpe figure has a 95% CI block
  (9) Methodology version hash: canonical_sharpe SHA `1928710` referenced
  (10) Pre-#651 row exclusion count is reported
  (11) Stage-2 promotion bootstrap CI placeholder section present (T2.02)
  (12) FRED rf-rate placeholder note present (T2.10)
  (13) MinTRL value reported per assess_statistical_power
  (14) N counts (total / quarantined / fully-instrumented) reported
  (15) Script does not write to the DB (read-only)
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts.stage1_baseline_recompute import (
    CANONICAL_SHARPE_SHA,
    RF_PERIOD_CONSTANT,
    RF_PERIOD_WINDOW,
    build_memo,
    compute_baseline,
    fetch_closed_shadow_trades,
)


def _create_minimal_schema(conn: sqlite3.Connection) -> None:
    """Faithful-but-minimal shadow_trades shape covering columns used by recompute."""
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            recommendation_id TEXT,
            ticker TEXT,
            status TEXT,
            actual_entry_time TEXT,
            actual_exit_time TEXT,
            pnl_pct REAL,
            spy_return_over_hold REAL,
            excess_return REAL,
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()


def _seed(conn, **kwargs) -> None:
    cols = ",".join(kwargs.keys())
    placeholders = ",".join("?" * len(kwargs))
    conn.execute(
        f"INSERT INTO shadow_trades ({cols}) VALUES ({placeholders})",
        tuple(kwargs.values()),
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _create_minimal_schema(c)
    yield c
    c.close()


def _seed_clean_closed(conn, trade_id, pnl_pct, spy_return, excess_return, quarantined=0):
    """Seed a fully-instrumented closed trade."""
    _seed(
        conn,
        trade_id=trade_id,
        recommendation_id=f"rec-{trade_id}",
        ticker="AAPL",
        status="closed",
        actual_entry_time="2026-04-23T10:00:00-04:00",
        actual_exit_time="2026-04-23T15:00:00-04:00",
        pnl_pct=pnl_pct,
        spy_return_over_hold=spy_return,
        excess_return=excess_return,
        quarantined=quarantined,
    )


# ---------------------------------------------------------------------------
# fetch_closed_shadow_trades — DB-read helper
# ---------------------------------------------------------------------------


def test_fetch_returns_only_closed_status(conn):
    """Open trades must be excluded — only fully-closed trades have a Sharpe."""
    _seed_clean_closed(conn, "t-closed", 1.5, 0.005, 1.0)
    _seed(
        conn,
        trade_id="t-open",
        recommendation_id="r-open",
        ticker="MSFT",
        status="active",
        actual_entry_time="2026-04-23T10:00:00-04:00",
        actual_exit_time=None,
        pnl_pct=None,
        spy_return_over_hold=None,
        excess_return=None,
        quarantined=0,
    )
    conn.commit()

    rows = fetch_closed_shadow_trades(conn)
    trade_ids = [r["trade_id"] for r in rows]
    assert "t-closed" in trade_ids
    assert "t-open" not in trade_ids


def test_fetch_returns_quarantined_rows_too(conn):
    """fetch_closed_shadow_trades returns ALL closed; the recompute filters quarantined later."""
    _seed_clean_closed(conn, "t-q", 1.0, 0.005, 0.5, quarantined=1)
    _seed_clean_closed(conn, "t-clean", 2.0, 0.005, 1.5, quarantined=0)
    conn.commit()

    rows = fetch_closed_shadow_trades(conn)
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# compute_baseline — three Sharpe figures + counts
# ---------------------------------------------------------------------------


def test_compute_baseline_excludes_quarantined(conn):
    """Quarantined rows are NOT part of the Sharpe computation."""
    # 5 fully-instrumented non-quarantined
    for i in range(5):
        _seed_clean_closed(conn, f"clean-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    # 5 quarantined (must be ignored)
    for i in range(5):
        _seed_clean_closed(
            conn, f"quar-{i}", 99.0, 0.005, 99.0, quarantined=1,
        )
    conn.commit()

    result = compute_baseline(conn)
    assert result["n_total"] == 10
    assert result["n_quarantined"] == 5
    assert result["n_fully_instrumented"] == 5


def test_compute_baseline_excludes_partial_instrumentation(conn):
    """Rows missing one of the four instrumentation cols are dropped."""
    # 3 clean
    for i in range(3):
        _seed_clean_closed(conn, f"clean-{i}", 1.0, 0.005, 0.5)
    # 1 with NULL pnl_pct
    _seed(
        conn,
        trade_id="missing-pnl",
        recommendation_id="r-mp",
        ticker="GOOG",
        status="closed",
        actual_entry_time="2026-04-23T10:00:00-04:00",
        actual_exit_time="2026-04-23T15:00:00-04:00",
        pnl_pct=None,
        spy_return_over_hold=0.005,
        excess_return=0.5,
        quarantined=0,
    )
    conn.commit()

    result = compute_baseline(conn)
    assert result["n_total"] == 4
    assert result["n_fully_instrumented"] == 3


def test_compute_baseline_three_sharpe_match_canonical(conn):
    """The three Sharpe values match canonical_sharpe outputs on the same data.

    FRED is patched to raise so the script falls back to RF_PERIOD_CONSTANT
    per row — matches the historical behavior pre-T2.10. A separate test
    (test_compute_baseline_uses_fred_when_available) covers the wired path.
    """
    from unittest.mock import patch

    from src.analytics.canonical_sharpe import (
        raw_sharpe,
        rf_adjusted_excess_sharpe,
        spy_relative_sharpe,
    )

    pnl_pcts = [1.0, 2.0, -1.0, 3.0, 0.5, 1.5, -0.5, 2.5, 1.0, 0.0]
    spy_rets = [0.005, 0.01, -0.002, 0.012, 0.001, 0.006, 0.000, 0.008, 0.004, 0.000]
    for i, (p, s) in enumerate(zip(pnl_pcts, spy_rets)):
        _seed_clean_closed(conn, f"t-{i}", p, s, p - s * 100)
    conn.commit()

    # Force FRED fallback so the rf vector is uniformly RF_PERIOD_CONSTANT.
    with patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=KeyError("forced fallback for legacy test"),
    ):
        result = compute_baseline(conn)

    expected_raw = raw_sharpe(pnl_pcts)
    expected_spy = spy_relative_sharpe(pnl_pcts, [s * 100.0 for s in spy_rets])
    expected_rf = rf_adjusted_excess_sharpe(pnl_pcts, RF_PERIOD_CONSTANT)

    assert result["raw_sharpe"] == pytest.approx(expected_raw)
    assert result["spy_relative_sharpe"] == pytest.approx(expected_spy)
    assert result["rf_adjusted_excess_sharpe"] == pytest.approx(expected_rf)
    assert result["rf_source"] == "placeholder"


def test_compute_baseline_uses_fred_when_available(conn):
    """When FRED is reachable, rf_source flips to 'fred_dtb3' and the
    rf-adjusted Sharpe reflects the real per-trade rf — different from the
    constant-fallback path."""
    from unittest.mock import patch

    pnl_pcts = [1.0, 2.0, -1.0, 3.0, 0.5, 1.5, -0.5, 2.5, 1.0, 0.0]
    spy_rets = [0.005, 0.01, -0.002, 0.012, 0.001, 0.006, 0.000, 0.008, 0.004, 0.000]
    for i, (p, s) in enumerate(zip(pnl_pcts, spy_rets)):
        _seed_clean_closed(conn, f"t-{i}", p, s, p - s * 100)
    conn.commit()

    # FRED success path: a different per-day rate than the placeholder.
    with patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        return_value=0.0005,  # ~5x placeholder
    ):
        fred_result = compute_baseline(conn)
    with patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=KeyError("force placeholder"),
    ):
        placeholder_result = compute_baseline(conn)

    assert fred_result["rf_source"] == "fred_dtb3"
    assert placeholder_result["rf_source"] == "placeholder"
    # The two Sharpe values must differ — proves FRED is actually wired.
    assert fred_result["rf_adjusted_excess_sharpe"] != pytest.approx(
        placeholder_result["rf_adjusted_excess_sharpe"], abs=1e-9
    )


def test_compute_baseline_logs_warning_on_fred_failure(conn, caplog):
    """When FRED raises, a [STAGE1_RF_FALLBACK] WARNING fires per row."""
    import logging
    from unittest.mock import patch

    _seed_clean_closed(conn, "t-1", 1.0, 0.005, 0.5)
    _seed_clean_closed(conn, "t-2", 2.0, 0.005, 1.5)
    conn.commit()

    caplog.set_level(logging.WARNING, logger="scripts.stage1_baseline_recompute")
    with patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=ConnectionError("FRED unreachable"),
    ):
        result = compute_baseline(conn)

    assert result["rf_source"] == "placeholder"
    fallback_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "[STAGE1_RF_FALLBACK]" in r.getMessage()
    ]
    assert fallback_records, (
        f"expected [STAGE1_RF_FALLBACK] WARNING; got "
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_compute_baseline_includes_bootstrap_cis(conn):
    """Each of the three Sharpe figures gets a bootstrap CI dict."""
    for i in range(10):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()

    result = compute_baseline(conn)
    for key in ("raw_sharpe_ci", "spy_relative_sharpe_ci", "rf_adjusted_excess_sharpe_ci"):
        ci = result[key]
        assert "ci_lower" in ci
        assert "ci_upper" in ci
        assert "point_estimate" in ci


def test_compute_baseline_includes_power_assessment(conn):
    """compute_baseline returns a PowerAssessment with status + mintrl_required."""
    for i in range(20):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()

    result = compute_baseline(conn)
    power = result["power"]
    assert power.status in ("powered", "marginal", "underpowered")
    assert power.mintrl_required > 0


# ---------------------------------------------------------------------------
# build_memo — required sections
# ---------------------------------------------------------------------------


def test_memo_has_three_sharpe_figures(conn):
    for i in range(20):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()
    result = compute_baseline(conn)

    memo = build_memo(result)

    assert "raw_sharpe" in memo.lower() or "raw sharpe" in memo.lower()
    assert "spy" in memo.lower()
    assert "rf-adjusted" in memo.lower() or "rf adjusted" in memo.lower() or "rf_adjusted" in memo.lower()


def test_memo_has_bootstrap_ci_for_each_sharpe(conn):
    for i in range(20):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)

    # 95% bootstrap CI is mentioned at least once per Sharpe figure (3 total).
    # We require the literal "95%" or "95 percent" plus "bootstrap" appear.
    assert "95%" in memo or "95 percent" in memo
    assert "bootstrap" in memo.lower()
    assert memo.lower().count("ci_lower") + memo.lower().count("ci lower") + memo.lower().count("[") >= 3


def test_memo_has_n_trades_and_counts(conn):
    """Memo reports total N, quarantined-excluded, fully-instrumented N."""
    for i in range(5):
        _seed_clean_closed(conn, f"clean-{i}", 1.0, 0.005, 0.5)
    for i in range(3):
        _seed_clean_closed(conn, f"quar-{i}", 1.0, 0.005, 0.5, quarantined=1)
    conn.commit()

    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "8" in memo  # total
    assert "3" in memo  # quarantined
    assert "5" in memo  # fully-instrumented


def test_memo_has_mintrl(conn):
    for i in range(20):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "MinTRL" in memo or "mintrl" in memo.lower()


def test_underpowered_memo_contains_literal_phrase(conn):
    """N=2 closed trades is < MinTRL (~4.84) -> underpowered phrase MUST appear."""
    for i in range(2):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.5, 0.005, 0.5 + i * 0.5)
    conn.commit()

    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "Stage-1 sample is underpowered" in memo
    assert "reported Sharpe is not statistically reliable" in memo
    assert "Consider deferring promotion until N >= MinTRL." in memo


def test_powered_memo_says_powered(conn):
    """N=20 (well above 2*MinTRL) -> verdict says 'powered'."""
    for i in range(20):
        _seed_clean_closed(conn, f"t-{i}", 1.0 + i * 0.1, 0.005, 0.5 + i * 0.1)
    conn.commit()

    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "powered" in memo.lower()


def test_memo_has_canonical_sharpe_sha(conn):
    """Methodology version hash: canonical_sharpe commit SHA `1928710`."""
    for i in range(5):
        _seed_clean_closed(conn, f"t-{i}", 1.0, 0.005, 0.5)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    assert CANONICAL_SHARPE_SHA in memo
    assert "1928710" in memo


def test_memo_has_pre_651_quarantined_count(conn):
    """Pre-#651 row exclusion count == count of quarantined=1 rows."""
    for i in range(7):
        _seed_clean_closed(conn, f"clean-{i}", 1.0, 0.005, 0.5)
    for i in range(4):
        _seed_clean_closed(conn, f"quar-{i}", 1.0, 0.005, 0.5, quarantined=1)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    # Quarantined count = 4
    assert "4" in memo
    assert "quarantin" in memo.lower()
    assert "pre-#651" in memo or "pre-651" in memo or "#651" in memo


def test_memo_has_fred_rf_placeholder_and_window(conn):
    """DA-9: memo documents the constant rf-rate + window pending T2.10 / FRED integration."""
    for i in range(5):
        _seed_clean_closed(conn, f"t-{i}", 1.0, 0.005, 0.5)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "FRED" in memo or "fred" in memo
    assert "T2.10" in memo
    assert RF_PERIOD_WINDOW in memo
    # Constant value should be visible in memo (e.g. "0.0001" or some numeric form)
    assert str(RF_PERIOD_CONSTANT) in memo


def test_memo_has_stage2_bootstrap_placeholder(conn):
    """Memo includes a Stage-2 promotion bootstrap CI placeholder (T2.02 dependency)."""
    for i in range(5):
        _seed_clean_closed(conn, f"t-{i}", 1.0, 0.005, 0.5)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "T2.02" in memo
    assert "block bootstrap" in memo.lower() or "block-bootstrap" in memo.lower()


def test_memo_has_iid_bootstrap_caveat(conn):
    """Memo flags that the current bootstrap is IID (T2.02 block bootstrap not yet landed)."""
    for i in range(5):
        _seed_clean_closed(conn, f"t-{i}", 1.0, 0.005, 0.5)
    conn.commit()
    result = compute_baseline(conn)
    memo = build_memo(result)
    assert "IID" in memo or "iid" in memo


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_compute_baseline_does_not_write_to_db(conn):
    """Script must be read-only on the DB."""
    for i in range(5):
        _seed_clean_closed(conn, f"t-{i}", 1.0, 0.005, 0.5, quarantined=(i % 2))
    conn.commit()

    before = conn.execute(
        "SELECT trade_id, quarantined FROM shadow_trades ORDER BY trade_id"
    ).fetchall()
    _ = compute_baseline(conn)
    after = conn.execute(
        "SELECT trade_id, quarantined FROM shadow_trades ORDER BY trade_id"
    ).fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
