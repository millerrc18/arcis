"""Tests for attribution resolver OHLCV data-shape handling (SD#41 D2 fix).

Covers the MultiIndex-column defect that made simulate_mechanical_outcome
return 'loss' at stop_price on day 1 for every resolved trade
(audit: docs/research/attribution-resolver-audit.md).
"""

import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from src.attribution.logger import (
    resolve_pending_outcomes,
    simulate_mechanical_outcome,
)


def _flat_columns_frame():
    """Pre-yfinance-multiindex shape: flat string columns."""
    return pd.DataFrame(
        {
            "Open":   [100, 101, 102, 103, 104],
            "High":   [102, 103, 105, 104, 105],
            "Low":    [99, 100, 101, 102, 103],
            "Close":  [101, 102, 104, 103, 104.5],
            "Volume": [1000] * 5,
        },
        index=pd.date_range("2026-01-01", periods=5),
    )


def _multiindex_frame(ticker: str = "AAPL"):
    """Current yfinance shape for single-ticker downloads."""
    df = _flat_columns_frame()
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


# ── Simulator is pure-logic: flat columns yield the right outcome ─────


def test_simulator_handles_flat_column_ohlcv():
    """Simulator produces the right outcome given correctly-shaped bars."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    # Entry 100, stop 95, target 105 — target hit on day 3 (High=105)
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=95, target_price=105,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "win"
    assert exit_price == 105
    assert days == 3


def test_simulator_returns_timeout_when_neither_breached():
    """No stop and no target hit -> timeout at last close."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=80, target_price=120,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "timeout"
    assert exit_price == pytest.approx(104.5)
    assert days == 5


def test_simulator_returns_loss_when_stop_hit_first():
    """Low <= stop should trip the stop-first branch."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=99.5, target_price=110,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "loss"
    assert exit_price == 99.5
    assert days == 1


# ── The D2-specific bug prevention ────────────────────────────────────


def _seed_pending(db_path: str, attribution_id: str = "test-1", ticker: str = "AAPL"):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL
        );
    """)
    conn.execute(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (attribution_id, ticker, "2026-01-01T10:00:00-05:00",
         100.0, 95.0, 105.0, "pending", None),
    )
    conn.commit()
    conn.close()


def test_resolve_pending_flattens_multiindex_before_simulating(tmp_path):
    """Regression: yfinance MultiIndex columns must not slip through unflattened.

    Before the D2 fix, bar.get("Low") returned the default 0 because the
    DataFrame had tuple-keyed columns. Every trade exited at stop on day 1.
    The _flat_columns_frame has High=105 on day 3, so a correctly-flattened
    MultiIndex frame should produce ('win', 105, 3).
    """
    db = str(tmp_path / "resolver.db")
    _seed_pending(db)

    with patch("yfinance.download", return_value=_multiindex_frame("AAPL")):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    conn.close()
    # ('loss', -5.0) is the bug signature — must not appear here.
    assert row[0] == "win", (
        f"Got {row}; if it's ('loss', -5.0) the MultiIndex flatten regressed."
    )
    assert row[1] == pytest.approx(5.0)


def test_resolve_pending_handles_empty_yfinance_response(tmp_path):
    """Empty DataFrame -> row stays 'pending', no crash, no partial update."""
    db = str(tmp_path / "resolver.db")
    _seed_pending(db, attribution_id="empty-1", ticker="DELISTED")

    with patch("yfinance.download", return_value=pd.DataFrame()):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 0
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    conn.close()
    assert row[0] == "pending", (
        "Empty yfinance response must leave the row as 'pending' for retry."
    )
    assert row[1] is None


def test_resolve_pending_flat_frame_also_works(tmp_path):
    """Backwards compat: if upstream ever returns flat columns, we must still resolve."""
    db = str(tmp_path / "resolver.db")
    _seed_pending(db, attribution_id="flat-1")

    with patch("yfinance.download", return_value=_flat_columns_frame()):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome FROM attribution_trades"
    ).fetchone()
    conn.close()
    assert row[0] == "win"


# ── Hotfix regressions — bugs 1/2/3 from the reresolve rollout ────────


def test_resolve_one_row_handles_zero_entry_price(tmp_path):
    """Hotfix bug 3 — ranker_only_entry=0.0 must not ZeroDivisionError.

    A handful of early-pipeline rows have entry=0. Pre-fix, the pnl math
    divided by entry and raised ZeroDivisionError, which the except clause
    swallowed and silently dropped the row. The guard now returns False
    cleanly so the loop continues.
    """
    db = str(tmp_path / "resolver.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL
        );
    """)
    conn.execute(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("zero-entry-1", "AAPL", "2026-01-01T10:00:00-05:00",
         0.0, 0.0, 0.0, "pending", None),
    )
    conn.commit()
    conn.close()

    # Even with valid yfinance data, the zero-entry guard short-circuits
    # before the fetch and leaves the row pending.
    with patch("yfinance.download", return_value=_flat_columns_frame()):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 0, "Zero-entry row must not be counted as resolved"
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    conn.close()
    assert row[0] == "pending"
    assert row[1] is None


def test_simulate_mechanical_outcome_handles_zero_entry_price():
    """Hotfix bug 3 (sibling) — simulator must not crash on zero/None entry either."""
    ohlcv = [{"Low": 10, "High": 20, "Close": 15}]

    # Zero entry: guard triggers, returns harmless timeout tuple.
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=0.0, stop_price=9.0, target_price=21.0,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "timeout"
    assert exit_price == 0.0
    assert days == 0

    # None entry must not raise either.
    outcome, _, _ = simulate_mechanical_outcome(
        entry_price=None, stop_price=9.0, target_price=21.0,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "timeout"


def _seed_mixed_resolution_versions(db_path: str):
    """Seed attribution_trades with a realistic mix for hotfix bug-1/bug-2 tests:

    - row-A: resolved row with resolution_version=NULL — bug 1 back-tags as v1.
    - row-B: already-tagged v1 with an ELAPSED window — bug 2 keeps it reset-eligible.
    - row-C: already-tagged v1 with a FUTURE window — bug 2 must skip it.
    - row-D: already v2_fixed — untouched.
    """
    from datetime import datetime, timedelta
    today = datetime.now().date()
    past_scan = (today - timedelta(days=20)).isoformat() + "T10:00:00"
    recent_scan = (today - timedelta(days=2)).isoformat() + "T10:00:00"  # future window

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL,
          resolution_version TEXT,
          ranker_only_outcome_v1 TEXT, ranker_only_pnl_pct_v1 TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("row-A-null-v1", "AAPL", past_scan,
             100.0, 95.0, 105.0, "loss", -5.0, None, None, None),
            ("row-B-past", "MSFT", past_scan,
             100.0, 95.0, 105.0, "loss", -5.0, "v1_multiindex_bug", None, None),
            ("row-C-future", "TSLA", recent_scan,
             100.0, 95.0, 105.0, "loss", -5.0, "v1_multiindex_bug", None, None),
            ("row-D-v2", "GOOG", past_scan,
             100.0, 95.0, 105.0, "win", 5.0, "v2_fixed",
             "loss", "-5.0"),
        ],
    )
    conn.commit()
    conn.close()


def test_reresolve_tags_null_resolution_version_as_v1(tmp_path, monkeypatch):
    """Hotfix bug 1 — the pre-tag step finds NULL-resolution rows and marks them v1."""
    import scripts.reresolve_attribution as rr
    db = str(tmp_path / "resolver.db")
    _seed_mixed_resolution_versions(db)
    monkeypatch.setattr(rr, "DB_PATH", db)
    # No-op out the actual re-resolve so the test focuses on the pre-tag step.
    monkeypatch.setattr(rr, "resolve_pending_outcomes", lambda *a, **kw: 0)

    result = rr.reresolve(dry_run=True)

    # Bug 1 fix: row-A (NULL → v1) counted in pre_tagged.
    assert result["pre_tagged"] == 1, f"Expected 1 back-tag, got {result}"
    conn = sqlite3.connect(db)
    rv = dict(conn.execute(
        "SELECT attribution_id, resolution_version FROM attribution_trades"
    ).fetchall())
    conn.close()
    assert rv["row-A-null-v1"] == "v1_multiindex_bug"
    assert rv["row-B-past"] == "v1_multiindex_bug"
    assert rv["row-C-future"] == "v1_multiindex_bug"
    assert rv["row-D-v2"] == "v2_fixed"  # untouched


def test_reresolve_skips_future_window_rows(tmp_path, monkeypatch):
    """Hotfix bug 2 — rows whose scan+8d window hasn't elapsed must NOT be reset."""
    import scripts.reresolve_attribution as rr
    db = str(tmp_path / "resolver.db")
    _seed_mixed_resolution_versions(db)
    monkeypatch.setattr(rr, "DB_PATH", db)
    monkeypatch.setattr(rr, "resolve_pending_outcomes", lambda *a, **kw: 0)

    result = rr.reresolve(dry_run=False)

    # Elapsed-window rows reset: row-A (just back-tagged) + row-B = 2.
    # row-C (future window) must NOT be reset.
    assert result["reset"] == 2, (
        f"Expected 2 elapsed-window resets (A + B), got {result}"
    )
    conn = sqlite3.connect(db)
    outcomes = dict(conn.execute(
        "SELECT attribution_id, ranker_only_outcome FROM attribution_trades"
    ).fetchall())
    conn.close()
    # Row C (future window) keeps its original 'loss' outcome.
    assert outcomes["row-C-future"] == "loss"
    # Rows A and B got reset to 'pending' (resolve patched as no-op).
    assert outcomes["row-A-null-v1"] == "pending"
    assert outcomes["row-B-past"] == "pending"


def test_resolve_pending_outcomes_skips_future_window_rows(tmp_path):
    """4th-bug fix: `resolve_pending_outcomes` must not select rows whose
    7-day outcome window is still in the future. yfinance has no data yet,
    and each attempt just logs a spurious `YFPricesMissingError` warning.

    Regression seeds 3 rows:
      - old-resolvable (scan 30 days ago)  -> selected
      - fresh-future   (scan today)        -> skipped
      - boundary-edge  (scan exactly 8d ago, window ends today) -> selected
    and asserts that the resolver's SELECT filter matches only the 2
    elapsed-window rows. No yfinance calls are made (mocked empty) so the
    test is a pure SQL-filter check.
    """
    from datetime import datetime, timedelta
    from src.attribution.logger import resolve_pending_outcomes

    db = str(tmp_path / "future_window.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL
        );
    """)
    today = datetime.now().date()
    seeds = [
        ("old-resolvable", (today - timedelta(days=30)).isoformat() + "T10:00:00"),
        ("fresh-future",   today.isoformat() + "T10:00:00"),
        ("boundary-edge",  (today - timedelta(days=8)).isoformat() + "T10:00:00"),
    ]
    for attr_id, ts in seeds:
        conn.execute(
            "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (attr_id, "AAPL", ts, 100.0, 95.0, 105.0, "pending", None),
        )
    conn.commit()
    conn.close()

    # Mock yfinance to return empty so _resolve_one_row is a no-op per row.
    # The test only cares WHICH rows get passed to _resolve_one_row.
    seen_ids: list[str] = []

    def fake_resolve_one_row(conn_inner, row):
        seen_ids.append(row["attribution_id"])
        return False  # not resolved — leave pending

    with patch("src.attribution.logger._resolve_one_row",
               side_effect=fake_resolve_one_row):
        resolve_pending_outcomes(db_path=db)

    assert "fresh-future" not in seen_ids, (
        "resolve_pending_outcomes must skip rows whose scan_timestamp + 8 days "
        "is still in the future (yfinance has no data yet)."
    )
    assert "old-resolvable" in seen_ids
    assert "boundary-edge" in seen_ids
