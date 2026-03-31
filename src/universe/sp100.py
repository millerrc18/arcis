"""S&P 100 (OEX) constituent universe.

Called by: api.routes.actions, cli.commands, data_collection.options_collector, evaluation.backtester, features.earnings, llm.validator, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.bootstrap, training.historical_data, training.leakage_detector
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_regime.py, tests/test_universe.py

Last verified: 2025-03-24
Source: S&P Dow Jones Indices / public OEX constituent lists.
Refresh periodically — constituents change with index rebalances.
"""

# yfinance uses hyphens for share classes (BRK-B), not dots (BRK.B)
YFINANCE_TICKER_MAP = {
    "BRK.B": "BRK-B",
}


def to_yfinance_ticker(ticker: str) -> str:
    """Map a canonical ticker to its yfinance-compatible form."""
    return YFINANCE_TICKER_MAP.get(ticker, ticker)


def from_yfinance_ticker(ticker: str) -> str:
    """Map a yfinance ticker back to its canonical form."""
    reverse = {v: k for k, v in YFINANCE_TICKER_MAP.items()}
    return reverse.get(ticker, ticker)


def get_sp100_universe() -> list[str]:
    """Return the current S&P 100 constituent ticker list, alphabetically sorted."""
    return [
        "AAPL",
        "ABBV",
        "ABT",
        "ACN",
        "ADBE",
        "AIG",
        "AMD",
        "AMGN",
        "AMT",
        "AMZN",
        "AVGO",
        "AXP",
        "BA",
        "BAC",
        "BK",
        "BKNG",
        "BLK",
        "BMY",
        "BRK.B",
        "C",
        "CAT",
        "CHTR",
        "CL",
        "CMCSA",
        "COF",
        "COP",
        "COST",
        "CRM",
        "CSCO",
        "CVS",
        "CVX",
        "DE",
        "DHR",
        "DIS",
        "DUK",
        "EMR",
        "ETN",
        "EXC",
        "F",
        "FDX",
        "GD",
        "GE",
        "GILD",
        "GM",
        "GOOG",
        "GOOGL",
        "GS",
        "HD",
        "HON",
        "IBM",
        "INTC",
        "INTU",
        "JNJ",
        "JPM",
        "KHC",
        "KO",
        "LIN",
        "LLY",
        "LMT",
        "LOW",
        "MA",
        "MCD",
        "MDLZ",
        "MDT",
        "MET",
        "META",
        "MMM",
        "MO",
        "MRK",
        "MS",
        "MSFT",
        "NEE",
        "NFLX",
        "NKE",
        "NOW",
        "NVDA",
        "ORCL",
        "PEP",
        "PFE",
        "PG",
        "PM",
        "PYPL",
        "QCOM",
        "RTX",
        "SBUX",
        "SCHW",
        "SO",
        "SPG",
        "T",
        "TGT",
        "TMO",
        "TMUS",
        "TXN",
        "UNH",
        "UNP",
        "UPS",
        "USB",
        "V",
        "VZ",
        "WFC",
        "WMT",
        "XOM",
    ]
