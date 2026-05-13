"""Sprint 5 Wave C7a.3 / T19 — RECENT ATTRIBUTION packet section tests.

Covers:
1. 30d window read with setup_class match populates recent_setup_win_rate
   (closed attribution_trades only).
2. similar-ticker sector join populates recent_similar_pnl_30d via the
   recommendations.sector_context lookup.
3. No-recent-trades fallback renders the empty-state message.

These tests bypass network/Ollama — they exercise the enricher DB reader
against synthetic SQLite fixtures, then drive _build_feature_prompt directly.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.data_enrichment.enricher import enrich_recent_attribution
from src.llm.packet_writer import _build_feature_prompt
from tests.conftest import init_test_db


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _insert_recommendation(
    conn: sqlite3.Connection,
    rec_id: str,
    ticker: str,
    created_at: str,
    setup_type: str | None = None,
    sector_context: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO recommendations (recommendation_id, created_at, ticker, "
        "setup_type, sector_context) VALUES (?, ?, ?, ?, ?)",
        (rec_id, created_at, ticker, setup_type, sector_context),
    )


def _insert_attribution(
    conn: sqlite3.Connection,
    attr_id: str,
    rec_id: str | None,
    ticker: str,
    pnl_pct: float | None,
    created_at: str,
    outcome: str | None = "target_hit",
) -> None:
    conn.execute(
        "INSERT INTO attribution_trades (attribution_id, recommendation_id, ticker, "
        "llm_portfolio_pnl_pct, llm_portfolio_outcome, created_at) VALUES "
        "(?, ?, ?, ?, ?, ?)",
        (attr_id, rec_id, ticker, pnl_pct, outcome, created_at),
    )


@pytest.fixture
def attribution_db(tmp_path):
    db = str(tmp_path / "attribution_test.sqlite3")
    init_test_db(db, ["attribution_trades", "recommendations"])
    now = datetime.now(timezone.utc)
    recent_iso = _iso(now - timedelta(days=5))
    older_iso = _iso(now - timedelta(days=45))  # outside 30d window

    with sqlite3.connect(db) as conn:
        # 3 recent setup-class=pullback trades for AAPL (Technology):
        # 2 wins (positive pnl) + 1 loss (negative pnl).
        _insert_recommendation(conn, "rec-1", "AAPL", recent_iso, "pullback", "Technology")
        _insert_recommendation(conn, "rec-2", "AAPL", recent_iso, "pullback", "Technology")
        _insert_recommendation(conn, "rec-3", "AAPL", recent_iso, "pullback", "Technology")
        _insert_attribution(conn, "attr-1", "rec-1", "AAPL", 2.5, recent_iso)
        _insert_attribution(conn, "attr-2", "rec-2", "AAPL", 1.8, recent_iso)
        _insert_attribution(conn, "attr-3", "rec-3", "AAPL", -1.2, recent_iso)

        # 1 recent pullback trade for MSFT (Technology) — similar-sector match.
        _insert_recommendation(conn, "rec-4", "MSFT", recent_iso, "pullback", "Technology")
        _insert_attribution(conn, "attr-4", "rec-4", "MSFT", 3.0, recent_iso)

        # 1 recent pullback trade for XOM (Energy) — different sector, no match.
        _insert_recommendation(conn, "rec-5", "XOM", recent_iso, "pullback", "Energy")
        _insert_attribution(conn, "attr-5", "rec-5", "XOM", 0.5, recent_iso)

        # 1 OLD trade (>30d) — should be excluded from window.
        _insert_recommendation(conn, "rec-old", "AAPL", older_iso, "pullback", "Technology")
        _insert_attribution(conn, "attr-old", "rec-old", "AAPL", 5.0, older_iso)

        # 1 unresolved (open) trade — no llm_portfolio_pnl_pct, should be excluded.
        _insert_recommendation(conn, "rec-open", "AAPL", recent_iso, "pullback", "Technology")
        _insert_attribution(conn, "attr-open", "rec-open", "AAPL", None, recent_iso, outcome=None)

        conn.commit()
    return db


class TestEnrichRecentAttribution:
    def test_30d_window_setup_class_populates_win_rate(self, attribution_db):
        """30d window read filtered by setup_class populates recent_setup_win_rate."""
        feat = {"setup_class": "pullback", "sector": "Technology"}
        enrich_recent_attribution(feat, "AAPL", db_path=attribution_db)
        # 5 closed pullback trades in window (3 AAPL + 1 MSFT + 1 XOM); 4 wins / 5 = 0.8
        # AAPL wins: 2.5, 1.8 (2 wins); AAPL loss: -1.2; MSFT win: 3.0; XOM win: 0.5
        assert feat.get("recent_setup_win_rate") == pytest.approx(4 / 5)

    def test_similar_ticker_sector_join_populates_similar_pnl(self, attribution_db):
        """Sector-match join populates recent_similar_pnl_30d (excluding self-ticker)."""
        feat = {"setup_class": "pullback", "sector": "Technology"}
        enrich_recent_attribution(feat, "AAPL", db_path=attribution_db)
        # Ticker-specific: AAPL trades only (3): (2.5 + 1.8 + -1.2) / 3 ≈ 1.0333
        assert feat.get("recent_ticker_pnl") == pytest.approx((2.5 + 1.8 - 1.2) / 3)
        # Similar-sector (Technology, excluding AAPL): only MSFT (3.0) — XOM is Energy.
        assert feat.get("recent_similar_pnl_30d") == pytest.approx(3.0)

    def test_no_recent_trades_fallback(self, tmp_path):
        """No attribution trades in window → empty-state message rendered."""
        db = str(tmp_path / "empty_attribution.sqlite3")
        init_test_db(db, ["attribution_trades", "recommendations"])
        feat = {"setup_class": "pullback", "sector": "Technology"}
        enrich_recent_attribution(feat, "AAPL", db_path=db)
        prompt = _build_feature_prompt(feat, "AAPL")
        assert "=== RECENT ATTRIBUTION ===" in prompt
        assert "No attribution trades in window" in prompt
