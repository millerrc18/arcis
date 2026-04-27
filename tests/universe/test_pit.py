"""Tests for point-in-time universe and dividend-haircut functions."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from src.universe.pit import (
    UniverseDataMissing,
    get_all_historical_tickers,
    get_data_range,
    get_sp100_at,
    apply_dividend_haircut,
    load_sp100_membership_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MEMBERSHIP_TABLE = {
    "2023-06-01": ["AAPL", "MSFT", "GOOG"],
    "2024-01-01": ["AAPL", "MSFT", "GOOG", "NVDA"],
    "2024-07-01": ["AAPL", "MSFT", "NVDA"],          # GOOG removed
    "2025-01-01": ["AAPL", "MSFT", "NVDA", "META"],  # META added
}


# ---------------------------------------------------------------------------
# get_sp100_at tests
# ---------------------------------------------------------------------------

def test_get_sp100_at_exact_date(membership_table=MEMBERSHIP_TABLE):
    """Exact snapshot date returns exactly that snapshot."""
    result = get_sp100_at("2024-01-01", membership_table=membership_table)
    assert result == ["AAPL", "GOOG", "MSFT", "NVDA"]


def test_get_sp100_at_between_snapshots(membership_table=MEMBERSHIP_TABLE):
    """Date between two snapshots returns the most recent prior snapshot."""
    # 2024-03-15 is after 2024-01-01 and before 2024-07-01
    result = get_sp100_at("2024-03-15", membership_table=membership_table)
    assert result == ["AAPL", "GOOG", "MSFT", "NVDA"]


def test_get_sp100_at_addition_appears_after_join_date(membership_table=MEMBERSHIP_TABLE):
    """Ticker added in a later snapshot is absent before and present after."""
    before = get_sp100_at("2024-06-30", membership_table=membership_table)
    after = get_sp100_at("2024-07-01", membership_table=membership_table)
    assert "GOOG" in before
    assert "GOOG" not in after


def test_get_sp100_at_removal_drops_from_universe(membership_table=MEMBERSHIP_TABLE):
    """Ticker removed in a snapshot is absent on that date."""
    result = get_sp100_at("2025-01-01", membership_table=membership_table)
    assert "META" in result
    assert "GOOG" not in result


def test_get_sp100_at_empty_table():
    """Empty membership table returns empty list."""
    result = get_sp100_at("2024-01-01", membership_table={})
    assert result == []


def test_get_sp100_at_date_before_all_snapshots(membership_table=MEMBERSHIP_TABLE):
    """Date before the earliest snapshot returns empty list."""
    result = get_sp100_at("2020-01-01", membership_table=membership_table)
    assert result == []


def test_get_sp100_at_returns_sorted_list(membership_table=MEMBERSHIP_TABLE):
    """Returned list is alphabetically sorted."""
    result = get_sp100_at("2025-01-01", membership_table=membership_table)
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# apply_dividend_haircut tests
# ---------------------------------------------------------------------------

def test_apply_dividend_haircut_basic():
    """1% annual yield, 30-day period, 1% return -> ~0.9178% return."""
    # Inputs: all decimal fractions; period_days int
    # Expected: 0.01 - (0.01 * 30/365) = 0.01 - 0.000821... = 0.009178...
    result = apply_dividend_haircut(
        returns=0.01,
        dividend_yield_pct=0.01,
        period_days=30,
    )
    expected = 0.01 - (0.01 * 30 / 365)
    assert abs(result - expected) < 1e-10


def test_apply_dividend_haircut_zero_yield():
    """Zero dividend yield leaves return unchanged."""
    result = apply_dividend_haircut(
        returns=0.05,
        dividend_yield_pct=0.0,
        period_days=90,
    )
    assert result == pytest.approx(0.05)


def test_apply_dividend_haircut_full_year():
    """365-day period deducts the full annual yield."""
    result = apply_dividend_haircut(
        returns=0.10,
        dividend_yield_pct=0.02,
        period_days=365,
    )
    assert result == pytest.approx(0.10 - 0.02)


def test_apply_dividend_haircut_negative_return():
    """Haircut is applied even when return is negative."""
    result = apply_dividend_haircut(
        returns=-0.03,
        dividend_yield_pct=0.02,
        period_days=182,
    )
    expected = -0.03 - (0.02 * 182 / 365)
    assert result == pytest.approx(expected)


def test_apply_dividend_haircut_zero_period_days():
    """Zero-day period applies zero haircut."""
    result = apply_dividend_haircut(
        returns=0.05,
        dividend_yield_pct=0.03,
        period_days=0,
    )
    assert result == pytest.approx(0.05)


# Production-loader tests (Sprint 1.A.0)

@pytest.fixture
def _clear_pit_cache():
    from src.universe.pit import load_sp100_membership_table
    load_sp100_membership_table.cache_clear()
    yield
    load_sp100_membership_table.cache_clear()


def test_load_sp100_membership_table_smoke(tmp_path, monkeypatch, _clear_pit_cache):
    data = {'2024-01-01': ['AAPL', 'MSFT'], '2024-07-01': ['AAPL', 'MSFT', 'NVDA']}
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    first = load_sp100_membership_table()
    assert first == data

    second = load_sp100_membership_table()
    assert second is first


def test_load_sp100_membership_table_raises_when_file_missing(tmp_path, monkeypatch, _clear_pit_cache):
    missing = tmp_path / 'nonexistent.json'
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', missing)

    with pytest.raises(UniverseDataMissing, match='scripts/build_sp100_history.py'):
        load_sp100_membership_table()


def test_load_sp100_membership_table_caches_via_lru_cache(tmp_path, monkeypatch, _clear_pit_cache):
    data_v1 = {'2024-01-01': ['AAPL', 'MSFT']}
    data_v2 = {'2024-01-01': ['AAPL', 'MSFT'], '2024-07-01': ['NVDA']}
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data_v1), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    first = load_sp100_membership_table()
    assert first == data_v1

    p.write_text(json.dumps(data_v2), encoding='utf-8')
    cached = load_sp100_membership_table()
    assert cached == data_v1

    load_sp100_membership_table.cache_clear()
    refreshed = load_sp100_membership_table()
    assert refreshed == data_v2


def test_get_data_range_returns_iso_date_tuple(tmp_path, monkeypatch, _clear_pit_cache):
    data = {
        '2024-01-01': ['AAPL'],
        '2024-07-01': ['AAPL', 'MSFT'],
        '2025-01-01': ['AAPL', 'MSFT', 'NVDA'],
    }
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    earliest, latest = get_data_range()
    assert earliest == date(2024, 1, 1)
    assert latest == date(2025, 1, 1)
    assert isinstance(earliest, date)
    assert isinstance(latest, date)


def test_get_data_range_raises_when_file_missing(tmp_path, monkeypatch, _clear_pit_cache):
    missing = tmp_path / 'nonexistent.json'
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', missing)

    with pytest.raises(UniverseDataMissing):
        get_data_range()


def test_get_sp100_at_production_path_uses_loader_when_membership_table_is_None(
    tmp_path, monkeypatch, _clear_pit_cache
):
    data = {'2024-01-01': ['AAPL', 'MSFT'], '2024-07-01': ['AAPL', 'MSFT', 'NVDA']}
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    result = get_sp100_at('2024-06-15')
    assert result == sorted(data['2024-01-01'])


def test_get_sp100_at_raises_when_as_of_before_coverage(tmp_path, monkeypatch, _clear_pit_cache):
    data = {'2024-01-01': ['AAPL'], '2025-01-01': ['AAPL', 'MSFT']}
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    with pytest.raises(UniverseDataMissing, match='before earliest') as exc_info:
        get_sp100_at('2020-01-01')
    assert '2024-01-01' in str(exc_info.value)


def test_get_sp100_at_raises_when_as_of_after_coverage(tmp_path, monkeypatch, _clear_pit_cache):
    data = {'2024-01-01': ['AAPL'], '2025-01-01': ['AAPL', 'MSFT']}
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    with pytest.raises(UniverseDataMissing, match='after latest') as exc_info:
        get_sp100_at('2030-01-01')
    assert 'scripts/build_sp100_history.py' in str(exc_info.value)


def test_get_sp100_at_patch_compat_with_explicit_membership_table_does_not_call_loader(
    monkeypatch,
):
    mock_loader = MagicMock()
    monkeypatch.setattr('src.universe.pit.load_sp100_membership_table', mock_loader)

    result = get_sp100_at('2024-01-01', membership_table=MEMBERSHIP_TABLE)
    assert result == ['AAPL', 'GOOG', 'MSFT', 'NVDA']
    mock_loader.assert_not_called()


def test_get_sp100_at_explicit_empty_dict_still_returns_empty_list():
    result = get_sp100_at('2024-01-01', membership_table={})
    assert result == []


def test_get_sp100_at_out_of_range_does_not_raise_when_using_explicit_table():
    result = get_sp100_at('2030-01-01', membership_table=MEMBERSHIP_TABLE)
    assert result == sorted(MEMBERSHIP_TABLE['2025-01-01'])


# ---------------------------------------------------------------------------
# get_all_historical_tickers tests
# ---------------------------------------------------------------------------

@pytest.fixture
def _clear_all_historical_tickers_cache():
    from src.universe.pit import load_sp100_membership_table, get_all_historical_tickers
    load_sp100_membership_table.cache_clear()
    get_all_historical_tickers.cache_clear()
    yield
    load_sp100_membership_table.cache_clear()
    get_all_historical_tickers.cache_clear()


def test_get_all_historical_tickers_returns_sorted_union(tmp_path, monkeypatch, _clear_all_historical_tickers_cache):
    data = {
        '2023-01-01': ['AAPL', 'MSFT', 'GOOG'],
        '2024-01-01': ['AAPL', 'MSFT', 'NVDA'],
        '2025-01-01': ['AAPL', 'META', 'NVDA'],
    }
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    result = get_all_historical_tickers()
    assert result == ['AAPL', 'GOOG', 'META', 'MSFT', 'NVDA']


def test_get_all_historical_tickers_includes_tickers_from_every_snapshot(tmp_path, monkeypatch, _clear_all_historical_tickers_cache):
    data = {
        '2020-01-01': ['INTC', 'IBM'],
        '2022-01-01': ['AAPL', 'MSFT'],
        '2024-01-01': ['AAPL', 'NVDA'],
    }
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    result = get_all_historical_tickers()
    assert 'INTC' in result
    assert 'IBM' in result
    assert result == sorted(result)


def test_get_all_historical_tickers_raises_when_file_missing(tmp_path, monkeypatch, _clear_all_historical_tickers_cache):
    missing = tmp_path / 'nonexistent.json'
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', missing)

    with pytest.raises(UniverseDataMissing):
        get_all_historical_tickers()


def test_get_all_historical_tickers_caches_via_lru_cache(tmp_path, monkeypatch, _clear_all_historical_tickers_cache):
    data = {
        '2024-01-01': ['AAPL', 'MSFT'],
        '2024-07-01': ['AAPL', 'MSFT', 'NVDA'],
    }
    p = tmp_path / 'sp100_history.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr('src.universe.pit._SP100_HISTORY_PATH', p)

    first = get_all_historical_tickers()
    second = get_all_historical_tickers()
    assert first is second
