from src.universe.sp100 import get_sp100_universe


def test_returns_list():
    universe = get_sp100_universe()
    assert isinstance(universe, list)


def test_count_in_range():
    universe = get_sp100_universe()
    assert 95 <= len(universe) <= 105, f"Expected 95-105 tickers, got {len(universe)}"


def test_common_tickers_present():
    universe = get_sp100_universe()
    for ticker in ["AAPL", "MSFT", "GOOGL", "JPM", "AMZN", "META", "BRK.B"]:
        assert ticker in universe, f"{ticker} missing from universe"


def test_no_duplicates():
    universe = get_sp100_universe()
    assert len(universe) == len(set(universe)), "Duplicate tickers found"


def test_alphabetically_sorted():
    universe = get_sp100_universe()
    assert universe == sorted(universe), "Universe is not alphabetically sorted"
