"""Tests for point-in-time S&P 100 resolver (R3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.schema.sqlite import create_all_tables
from src.platform.rigor.walkforward_universe import (
    HistoricalConstituentsError,
    load_constituents_from_csv,
    populate_constituents_table,
    resolve_universe_as_of,
    resolve_universe_size,
)

_CSV_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "reference" / "sp100_historical.csv"
)


@pytest.fixture
def populated_db(tmp_path):
    db = tmp_path / "wf_universe.sqlite3"
    create_all_tables(str(db))
    populate_constituents_table(str(db), _CSV_PATH)
    return str(db)


def test_csv_file_exists():
    assert _CSV_PATH.exists(), f"missing historical S&P 100 CSV at {_CSV_PATH}"


def test_csv_loader_returns_rows():
    rows = load_constituents_from_csv(_CSV_PATH)
    assert len(rows) >= 100, "expected >= 100 historical membership rows"


def test_csv_loader_raises_on_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    with pytest.raises(HistoricalConstituentsError, match="not found"):
        load_constituents_from_csv(missing)


def test_csv_loader_raises_on_bad_header(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("wrong,header\nAAPL,2020-01-01\n")
    with pytest.raises(HistoricalConstituentsError, match="header mismatch"):
        load_constituents_from_csv(bad)


def test_populate_is_idempotent(tmp_path):
    db = tmp_path / "wf_univ.sqlite3"
    create_all_tables(str(db))
    n1 = populate_constituents_table(str(db), _CSV_PATH)
    n2 = populate_constituents_table(str(db), _CSV_PATH)
    assert n1 == n2


def test_resolver_rejects_non_iso_date(populated_db):
    with pytest.raises(ValueError, match="ISO"):
        resolve_universe_as_of("not-a-date", populated_db)


def test_resolver_returns_nonempty_in_2020(populated_db):
    universe = resolve_universe_as_of("2020-01-15", populated_db)
    assert "AAPL" in universe
    assert "MSFT" in universe
    assert len(universe) >= 80


def test_resolver_excludes_post_removal(populated_db):
    """WBA was removed 2022-09-19 → 2023-01-01 universe should NOT contain WBA."""
    u_after = resolve_universe_as_of("2023-01-01", populated_db)
    assert "WBA" not in u_after
    # But before the removal it should be present.
    u_before = resolve_universe_as_of("2022-01-01", populated_db)
    assert "WBA" in u_before


def test_resolver_tsla_added_june_2020(populated_db):
    """TSLA added 2020-06-22 — must be absent on 2020-06-21, present on 2020-06-22."""
    u_pre = resolve_universe_as_of("2020-06-21", populated_db)
    u_post = resolve_universe_as_of("2020-06-22", populated_db)
    assert "TSLA" not in u_pre
    assert "TSLA" in u_post


def test_resolver_meta_rename_from_fb(populated_db):
    """FB renamed to META effective 2022-06-09. Before → FB in universe, META absent.
    After → META in universe, FB absent."""
    u_pre = resolve_universe_as_of("2022-06-08", populated_db)
    u_post = resolve_universe_as_of("2022-06-10", populated_db)
    assert "FB" in u_pre
    assert "META" not in u_pre
    assert "META" in u_post
    assert "FB" not in u_post


def test_resolver_utx_rtn_merger_into_rtx(populated_db):
    """2020-04-02: UTX and RTN separate members. 2020-04-03: merged to RTX."""
    u_pre = resolve_universe_as_of("2020-04-02", populated_db)
    u_post = resolve_universe_as_of("2020-04-03", populated_db)
    assert "UTX" in u_pre
    assert "RTN" in u_pre
    assert "RTX" not in u_pre
    assert "UTX" not in u_post
    assert "RTN" not in u_post
    assert "RTX" in u_post


def test_resolve_universe_size_matches_list_length(populated_db):
    count = resolve_universe_size("2021-06-01", populated_db)
    universe = resolve_universe_as_of("2021-06-01", populated_db)
    assert count == len(universe)


def test_resolver_empty_db_returns_empty(tmp_path):
    db = tmp_path / "empty.sqlite3"
    create_all_tables(str(db))
    assert resolve_universe_as_of("2022-01-01", str(db)) == []


def test_resolver_deduplicates_reentries(tmp_path):
    """A ticker with two add-events (removed then re-added) must appear once."""
    db = tmp_path / "readd.sqlite3"
    create_all_tables(str(db))
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO sp100_historical_constituents "
        "(ticker, added_date, removed_date) VALUES (?, ?, ?)",
        ("TEST", "2018-01-01", "2019-01-01"),
    )
    conn.execute(
        "INSERT INTO sp100_historical_constituents "
        "(ticker, added_date, removed_date) VALUES (?, ?, ?)",
        ("TEST", "2021-01-01", None),
    )
    conn.commit()
    conn.close()
    u = resolve_universe_as_of("2022-01-01", str(db))
    assert u.count("TEST") == 1
