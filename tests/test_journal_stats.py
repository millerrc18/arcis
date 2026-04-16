"""Tests for src/journal/stats.py — trade-stats windows.

Covers:
- empty DB -> all windows have count=0, None stats (no crash)
- window boundaries (today vs. yesterday vs. 7d vs. 30d)
- excess_sharpe only computed when >=10 closed trades in window
- quarantined trades excluded
- open trades excluded
- win rate math
- NULL pnl/excess fields handled gracefully
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.journal.stats import compute_all_window_stats, compute_window_stats

ET = ZoneInfo("America/New_York")


def _init_schema(db_path: str) -> None:
    """Create the minimal shadow_trades columns the stats helper reads."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY, ticker TEXT, status TEXT,
            pnl_pct REAL, pnl_dollars REAL, excess_return REAL,
            actual_exit_time TEXT, quarantined INTEGER
        );
    """)
    conn.commit()
    conn.close()


def _seed(db_path: str, trade_id: str, days_ago: float, pnl_pct: float,
          pnl_dollars: float = 100.0, excess_return: float | None = None,
          status: str = "closed_target", quarantined: int = 0) -> None:
    exit_time = (datetime.now(ET) - timedelta(days=days_ago)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, "AAPL", status, pnl_pct, pnl_dollars, excess_return,
         exit_time, quarantined),
    )
    conn.commit()
    conn.close()


def test_empty_db_returns_zero_counts(tmp_path):
    db = str(tmp_path / "empty.db")
    _init_schema(db)
    stats = compute_all_window_stats(db)
    for window in ("today", "7d", "30d", "all_time"):
        assert stats[window]["count"] == 0
        assert stats[window]["win_rate"] is None
        assert stats[window]["avg_pnl_pct"] is None


def test_open_trades_excluded(tmp_path):
    db = str(tmp_path / "open.db")
    _init_schema(db)
    _seed(db, "t-closed", days_ago=0, pnl_pct=3.0)
    _seed(db, "t-open",   days_ago=0, pnl_pct=2.0, status="open")
    stats = compute_all_window_stats(db)
    # Only the closed trade counts
    assert stats["today"]["count"] == 1
    assert stats["all_time"]["count"] == 1


def test_quarantined_trades_excluded(tmp_path):
    db = str(tmp_path / "q.db")
    _init_schema(db)
    _seed(db, "t-clean", days_ago=1, pnl_pct=5.0, excess_return=1.0)
    _seed(db, "t-quar",  days_ago=1, pnl_pct=-99.0, quarantined=1)
    stats = compute_all_window_stats(db)
    # Only the non-quarantined trade counts toward stats
    assert stats["all_time"]["count"] == 1
    assert stats["all_time"]["avg_pnl_pct"] == pytest.approx(5.0)


def test_today_vs_7d_vs_30d_windows(tmp_path):
    db = str(tmp_path / "windows.db")
    _init_schema(db)
    # Today
    _seed(db, "today-a", days_ago=0.1, pnl_pct=2.0)
    # 4 days ago — in 7d, 30d, all_time
    _seed(db, "recent",  days_ago=4,   pnl_pct=3.0)
    # 15 days ago — in 30d, all_time (not 7d)
    _seed(db, "older",   days_ago=15,  pnl_pct=-1.0)
    # 60 days ago — only in all_time
    _seed(db, "ancient", days_ago=60,  pnl_pct=10.0)

    stats = compute_all_window_stats(db)
    assert stats["today"]["count"] == 1
    assert stats["7d"]["count"] == 2  # today + recent
    assert stats["30d"]["count"] == 3
    assert stats["all_time"]["count"] == 4


def test_win_rate_math(tmp_path):
    db = str(tmp_path / "wr.db")
    _init_schema(db)
    # 3 wins, 1 loss
    for i, pct in enumerate([1.0, 2.0, 3.0, -4.0]):
        _seed(db, f"t-{i}", days_ago=0.1, pnl_pct=pct)
    stats = compute_all_window_stats(db)
    assert stats["today"]["wins"] == 3
    assert stats["today"]["losses"] == 1
    assert stats["today"]["win_rate"] == pytest.approx(0.75)


def test_excess_sharpe_requires_min_10_trades(tmp_path):
    db = str(tmp_path / "sharpe.db")
    _init_schema(db)
    # 9 trades with excess_return — Sharpe should be None
    for i in range(9):
        _seed(db, f"t-{i}", days_ago=0.5, pnl_pct=1.0, excess_return=0.5)
    assert compute_all_window_stats(db)["today"]["excess_sharpe"] is None
    # Add a 10th — Sharpe should now compute
    _seed(db, "t-9", days_ago=0.5, pnl_pct=1.0, excess_return=0.5)
    stats = compute_all_window_stats(db)
    # Every excess_return is identical (0.5) so stdev=0 -> None
    assert stats["today"]["excess_sharpe"] is None
    # Replace one to make stdev non-zero
    conn = sqlite3.connect(db)
    conn.execute("UPDATE shadow_trades SET excess_return = 1.5 WHERE trade_id = 't-9'")
    conn.commit(); conn.close()
    stats = compute_all_window_stats(db)
    assert stats["today"]["excess_sharpe"] is not None


def test_null_excess_return_handled(tmp_path):
    db = str(tmp_path / "null.db")
    _init_schema(db)
    _seed(db, "t-null-excess", days_ago=1, pnl_pct=2.0, excess_return=None)
    stats = compute_all_window_stats(db)
    assert stats["all_time"]["count"] == 1
    assert stats["all_time"]["avg_excess_return"] is None
    assert stats["all_time"]["avg_pnl_pct"] == pytest.approx(2.0)


# ── notify_trading_stats_update formatting (no-send smoke tests) ─────


def test_notify_trading_stats_update_silent_on_empty(monkeypatch):
    """All-zero counts -> no send (return True)."""
    from src.notifications import telegram as tg
    sent: list[str] = []
    monkeypatch.setattr(tg, "send_telegram", lambda msg, **_: sent.append(msg) or True)
    monkeypatch.setattr(tg, "is_telegram_enabled", lambda: True)
    empty = {w: {"count": 0} for w in ("today", "7d", "30d", "all_time")}
    assert tg.notify_trading_stats_update(empty) is True
    assert sent == []


def test_notify_trading_stats_update_renders_all_windows(monkeypatch):
    from src.notifications import telegram as tg
    sent: list[str] = []
    monkeypatch.setattr(tg, "send_telegram", lambda msg, **_: sent.append(msg) or True)
    monkeypatch.setattr(tg, "is_telegram_enabled", lambda: True)
    stats = {
        "today": {"count": 2, "wins": 1, "losses": 1, "win_rate": 0.5,
                  "avg_pnl_pct": 1.0, "total_pnl_dollars": 50.0,
                  "avg_excess_return": None, "excess_sharpe": None},
        "7d": {"count": 10, "wins": 7, "losses": 3, "win_rate": 0.7,
               "avg_pnl_pct": 2.3, "total_pnl_dollars": 420.0,
               "avg_excess_return": 0.8, "excess_sharpe": 1.1},
        "30d": {"count": 40, "wins": 22, "losses": 18, "win_rate": 0.55,
                "avg_pnl_pct": 1.4, "total_pnl_dollars": 1600.0,
                "avg_excess_return": 0.3, "excess_sharpe": 0.9},
        "all_time": {"count": 85, "wins": 44, "losses": 41, "win_rate": 0.52,
                     "avg_pnl_pct": 1.0, "total_pnl_dollars": 2100.0,
                     "avg_excess_return": 0.2, "excess_sharpe": 0.5},
    }
    tg.notify_trading_stats_update(stats, label="midday")
    assert len(sent) == 1
    body = sent[0]
    # Label renders uppercased
    assert "MIDDAY" in body
    # Every window appears
    for name in ("Today", "7d", "30d", "All-time"):
        assert name in body
    # Excess Sharpe rendered where ≥10 trades
    assert "ex-Sharpe 1.10" in body or "ex-Sharpe 1.1" in body
    # Zero-count windows don't show excess; non-zero ones do
    assert "excess +0.80%" in body or "excess +0.8" in body
