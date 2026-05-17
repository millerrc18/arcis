"""Regression-lock tests for v0.36.12 residual hotfix.

Three classes of bug surfaced after v0.36.11 (watch-loop hardening):

1. `scripts/collect_1min_bars.py` used raw `INSERT OR REPLACE`. Sibling-miss
   from the v0.36.11 `scripts/stress_test.py` migration. PG syntax error
   crashed the overnight 1-min-bars pull 17 times in a row.

2. `src/data_collection/macro_collector.py` shared one PG connection across
   31 FRED series with try/except continue. One IntegrityError on
   FEDFUNDS poisoned the transaction and every subsequent fetch failed with
   "current transaction is aborted, commands ignored until end of
   transaction block" — 22+ silently-dropped series per overnight run.

3. `src/data_collection/short_interest_collector.py` retried Finnhub's
   403-Forbidden response 102 times per overnight cycle and threshold-failed
   the whole collection task on what is really an API-entitlement gap.

These tests pin the fixes — they fail loudly if the anti-pattern returns.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. collect_1min_bars sibling fix
# ---------------------------------------------------------------------------


def test_collect_1min_bars_uses_engine_aware_upsert_not_raw_insert_or_replace():
    """v0.36.12 R1: regression-lock against the v0.36.11 sibling miss.

    The hardening migrated `scripts/stress_test.py` off raw
    `INSERT OR REPLACE` but missed `scripts/collect_1min_bars.py:127`.
    PG cutover failed it with `syntax error at or near "OR"`. The fix
    routes through `engine_aware_upsert` so SQLite and PG both work.
    """
    source = (REPO_ROOT / "scripts" / "collect_1min_bars.py").read_text(
        encoding="utf-8"
    )
    # Pin against the SQL form `INSERT OR REPLACE INTO ...` — explanatory
    # docstring mentions of the bare phrase are fine.
    sql_form_matches = re.findall(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+\w+", source, flags=re.IGNORECASE
    )
    assert not sql_form_matches, (
        "scripts/collect_1min_bars.py must use engine_aware_upsert; "
        "raw INSERT OR REPLACE INTO was the v0.36.12 R1 root cause."
    )
    # And the engine-agnostic helper is wired in.
    assert "engine_aware_upsert" in source, (
        "scripts/collect_1min_bars.py must import engine_aware_upsert "
        "for the PG-routed overnight pull to succeed."
    )


def test_minute_bars_classified_in_replace_semantics_audit():
    """v0.36.12 R1: `minute_bars` must be audited before `action='replace'`.

    `engine_aware_upsert(action='replace', table='minute_bars')` raises
    `ValueError` if `_REPLACE_SEMANTICS` doesn't include the table. This
    enforces the T0.12 audit discipline.
    """
    from src.utils.db import _REPLACE_SEMANTICS
    assert "minute_bars" in _REPLACE_SEMANTICS
    assert _REPLACE_SEMANTICS["minute_bars"] == "in_place_update"


# ---------------------------------------------------------------------------
# 2. macro_collector PG transaction-abort cascade fix
# ---------------------------------------------------------------------------


def test_macro_collector_no_raw_insert_into_macro_snapshots():
    """v0.36.12 R2: must route writes through engine_aware_upsert.

    The pre-fix raw INSERT relied on the bare-except logging the
    IntegrityError and continuing — which left PG's transaction
    poisoned and silently dropped 22+ downstream series. The fix
    uses `engine_aware_upsert(action='ignore')` so PG handles dedup
    natively via ON CONFLICT DO NOTHING.
    """
    source = (
        REPO_ROOT / "src" / "data_collection" / "macro_collector.py"
    ).read_text(encoding="utf-8")
    # Match raw "INSERT INTO macro_snapshots" — the previous pattern.
    raw_inserts = re.findall(
        r"conn\.execute\(\s*['\"]+\s*INSERT\s+INTO\s+macro_snapshots",
        source,
        flags=re.IGNORECASE,
    )
    assert not raw_inserts, (
        "macro_collector.py must use engine_aware_upsert(action='ignore') for "
        "macro_snapshots writes — raw INSERT was the v0.36.12 R2 root cause."
    )
    assert "engine_aware_upsert" in source


def test_macro_collector_handles_db_error_with_rollback():
    """v0.36.12 R2: defensive rollback on DB error to clear poisoned tx.

    The fix MUST include `except DBError` with `conn.rollback()` so the
    shared-connection loop survives any integrity error from any future
    code path (belt-and-suspenders alongside the upsert dedup).
    """
    source = (
        REPO_ROOT / "src" / "data_collection" / "macro_collector.py"
    ).read_text(encoding="utf-8")
    assert "except DBError" in source, (
        "macro_collector must catch DBError to handle PG IntegrityError "
        "without poisoning the connection."
    )
    assert "conn.rollback()" in source, (
        "macro_collector must rollback the PG transaction in the DBError "
        "handler — without it the loop cascades into 'current transaction "
        "is aborted' for every remaining series."
    )


# ---------------------------------------------------------------------------
# 3. short_interest_collector 403 early-exit fix
# ---------------------------------------------------------------------------


def test_short_interest_collector_early_exits_on_403_entitlement():
    """v0.36.12 R3: early-exit on first 403 instead of retrying 102 tickers.

    Finnhub's `/stock/short-interest` endpoint returns 403 across every
    ticker when the API plan no longer entitles the feature. The pre-fix
    retried + log-spammed across all 102 S&P tickers and threshold-failed
    the overnight cycle. The fix breaks the loop on the first 403 and
    reports a single 'entitlement gap' warning.
    """
    source = (
        REPO_ROOT / "src" / "data_collection" / "short_interest_collector.py"
    ).read_text(encoding="utf-8")
    # The fix introduces a sentinel string or HTTP-status check that breaks
    # the loop on 403. We pin a textual marker for the entitlement branch.
    assert "403" in source, (
        "short_interest_collector must explicitly detect HTTP 403 to "
        "early-exit on entitlement gaps."
    )
    assert "entitlement" in source.lower() or "entitled" in source.lower(), (
        "short_interest_collector must log the 403 cause as an "
        "entitlement gap so the overnight cycle reports it as a "
        "structured skip rather than a generic threshold failure."
    )
