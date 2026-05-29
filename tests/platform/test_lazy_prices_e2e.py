"""E2E regression test: Lazy Prices must produce trades on the production DB.

Pinned after 2026-04-17 hotfix — this test fails loudly if the n_trades=0
regression reappears. Skip if production DB is absent (for CI / fresh
checkouts without the EDGAR backfill run).

Root causes fixed by hotfix v0.24.0-alpha2.1:
1. H1 (sections_json → full_text fallback): edgar_collector backfill populates
   full_text but not sections_json. cosine_similarity_yoy() now parses
   sections from full_text when sections_json is NULL.
2. H2 (universe alias): spec.universe.tickers = "sp100" (string) was rejected
   by _query_event_rows() which expected a list. _resolve_universe() now
   handles the "sp100" alias.
3. H4 (combinator bug): _evaluate_event_signal() was hardcoded to AND logic;
   spec has combinator: any (OR). Fixed to read the combinator parameter.

The date range must match the actual DB. The production DB (ARCIS_DB_PATH or
<repo_root>/ai_research_desk.sqlite3) contains filings from 2024 onward;
prior-year pairs first appear in 2025 (2024 prior-year data available).
"""
import sqlite3
from pathlib import Path

import pytest

from src.config import DB_PATH


def _db_has_prior_year_pairs(db_path: str) -> bool:
    """Check if DB has at least one filing with a prior-year same-form match
    and non-NULL full_text on both sides (minimum data needed for cosine)."""
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute("""
            SELECT COUNT(*) FROM edgar_filings f1
            JOIN edgar_filings f2 ON
                f2.ticker = f1.ticker AND
                f2.form_type = f1.form_type AND
                f2.filing_date < f1.filing_date AND
                f2.filing_date >= date(f1.filing_date, '-400 days') AND
                f2.filing_date <= date(f1.filing_date, '-300 days')
            WHERE f1.form_type IN ('10-K', '10-Q')
            AND LENGTH(f1.full_text) > 1000
            AND LENGTH(f2.full_text) > 1000
        """).fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _db_date_range(db_path: str) -> tuple[str, str]:
    """Return (min_date, max_date) for 10-K/10-Q filings in the DB."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT MIN(filing_date), MAX(filing_date) FROM edgar_filings "
            "WHERE form_type IN ('10-K', '10-Q')"
        ).fetchone()
        conn.close()
        return row[0] or "2020-01-01", row[1] or "2024-12-31"
    except Exception:
        return "2020-01-01", "2024-12-31"


@pytest.mark.skipif(
    not Path(DB_PATH).exists(),
    reason="optional-dep: production DB absent — requires "
           "scripts/backfill_edgar_fulltext.py to populate the EDGAR fulltext fixture",
)
@pytest.mark.skipif(
    Path(DB_PATH).exists() and not _db_has_prior_year_pairs(DB_PATH),
    reason="optional-dep: production DB lacks prior-year pairs — needs >=2 years of "
           "filings data (run scripts/backfill_edgar_fulltext.py to populate)",
)
def test_lazy_prices_produces_trades_on_real_data():
    """Lazy Prices backtest must produce at least 1 trade on the production DB.

    Uses the actual DB date range (not hardcoded 2020-2024) so the test
    remains valid as the DB grows. Floor: 1 trade (not 50) because the
    production DB may have limited history; the key assertion is n_trades > 0.
    When the DB reaches ≥3 years of history, the floor should be raised to >=50.
    """
    from src.platform.backtest_engine import BacktestConfig, run_backtest
    from src.platform.strategy_spec import load_spec

    spec = load_spec("lazy_prices_v1")
    # Use the actual DB date range rather than a hardcoded window
    start_date, end_date = _db_date_range(DB_PATH)
    cfg = BacktestConfig(
        strategy=spec,
        start_date=start_date,
        end_date=end_date,
    )
    result = run_backtest(cfg)
    assert result.metrics["n_trades"] >= 1, (
        f"expected >=1 trade over {start_date}..{end_date}, "
        f"got {result.metrics['n_trades']}. "
        "Likely regression: sections_json key mismatch, filter bug, "
        "combinator bug, or prior-year lookup failure."
    )
    assert result.metrics["sharpe"] is not None
    assert result.metrics["max_drawdown_pct"] is not None
