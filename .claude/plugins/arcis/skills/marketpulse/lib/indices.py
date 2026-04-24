"""Index constituent management -- load, refresh, and create ticker lists."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .db import MarketPulseConfig, get_config

logger = logging.getLogger(__name__)

# Maps short_name -> Wikipedia scrape config
SCRAPE_CONFIGS: dict[str, dict] = {
    "SP100": {
        "url": "https://en.wikipedia.org/wiki/S%26P_100",
        "table_index": 0,
        "ticker_col": "Symbol",
        "name_col": "Name",
        "sector_col": "Sector",
    },
    "SP500": {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "table_index": 0,
        "ticker_col": "Symbol",
        "name_col": "Security",
        "sector_col": "GICS Sector",
    },
    "DOW30": {
        "url": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
        "table_match_col": "Exchange",
        "ticker_col": "Symbol",
        "name_col": "Company",
        "sector_col": "Sector",
    },
    "NDX100": {
        "url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "table_match_col": "Ticker",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "sector_col": "ICB Industry",
    },
}


@dataclass
class IndexInfo:
    """Summary info about an index or custom list."""
    short_name: str
    name: str
    description: str
    ticker_count: int
    last_updated: str
    source: str


@dataclass
class Index:
    """Full index data with constituents."""
    short_name: str
    name: str
    description: str
    source: str
    last_updated: str
    constituents: list[dict]

    @property
    def tickers(self) -> list[str]:
        return [c["ticker"] for c in self.constituents]


class IndexManager:
    """Manages index constituent files and custom ticker lists."""

    def __init__(self, config: MarketPulseConfig | None = None) -> None:
        self._config = config or get_config()
        self._indices_dir = Path(__file__).resolve().parent.parent / "indices"
        self._custom_dir = self._config.data_dir / "custom_lists"
        self._custom_dir.mkdir(parents=True, exist_ok=True)

    def get_index(self, name: str) -> Index:
        """Load an index by short name. Also checks custom lists."""
        name_upper = name.upper()
        path = self._index_path(name_upper)
        if path.exists():
            return self._load_index(path)
        custom_path = self._custom_path(name)
        if custom_path.exists():
            return self._load_index(custom_path)
        raise IndexNotFoundError(f"Index or custom list '{name}' not found.")

    def get_tickers(self, name: str) -> list[str]:
        """Return ticker list for an index or custom list."""
        return self.get_index(name).tickers

    def list_indices(self) -> list[IndexInfo]:
        """List all available indices and custom lists."""
        results: list[IndexInfo] = []
        for path in sorted(self._indices_dir.glob("*.json")):
            idx = self._load_index(path)
            results.append(IndexInfo(
                short_name=idx.short_name, name=idx.name,
                description=idx.description, ticker_count=len(idx.constituents),
                last_updated=idx.last_updated, source=idx.source,
            ))
        for path in sorted(self._custom_dir.glob("*.json")):
            idx = self._load_index(path)
            results.append(IndexInfo(
                short_name=idx.short_name, name=idx.name,
                description=idx.description, ticker_count=len(idx.constituents),
                last_updated=idx.last_updated, source="custom",
            ))
        return results

    def refresh_index(self, name: str) -> Index:
        """Re-scrape from Wikipedia. Only works for indices with a scrape config."""
        name_upper = name.upper()
        if name_upper not in SCRAPE_CONFIGS:
            raise ValueError(
                f"No scrape config for '{name_upper}'. "
                f"Supported: {', '.join(SCRAPE_CONFIGS.keys())}"
            )
        cfg = SCRAPE_CONFIGS[name_upper]
        constituents = self._scrape_wikipedia(cfg)
        path = self._index_path(name_upper)
        if path.exists():
            existing = self._load_index(path)
            index_data = {
                "name": existing.name, "short_name": existing.short_name,
                "description": existing.description, "source": "Wikipedia",
                "last_updated": date.today().isoformat(), "constituents": constituents,
            }
        else:
            index_data = {
                "name": name_upper, "short_name": name_upper,
                "description": "", "source": "Wikipedia",
                "last_updated": date.today().isoformat(), "constituents": constituents,
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        logger.info("Refreshed %s: %d tickers", name_upper, len(constituents))
        return self._load_index(path)

    def create_custom_list(self, name: str, tickers: list[str]) -> Index:
        """Create a named custom ticker list."""
        if not name or not name.strip():
            raise ValueError("Custom list name cannot be empty.")
        data = {
            "name": name, "short_name": name,
            "description": f"Custom ticker list: {name}",
            "source": "custom", "last_updated": date.today().isoformat(),
            "constituents": [{"ticker": t.upper(), "name": "", "sector": ""} for t in tickers],
        }
        path = self._custom_path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return self._load_index(path)

    def is_index(self, name: str) -> bool:
        """Check if a name refers to a known index or custom list."""
        return (
            self._index_path(name.upper()).exists()
            or self._custom_path(name).exists()
        )

    def _index_path(self, short_name: str) -> Path:
        mapping = {
            "SP100": "sp100.json", "SP500": "sp500.json",
            "DOW30": "dow30.json", "NDX100": "nasdaq100.json",
            "RUT2000": "russell2000.json",
        }
        filename = mapping.get(short_name.upper(), f"{short_name.lower()}.json")
        return self._indices_dir / filename

    def _custom_path(self, name: str) -> Path:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return self._custom_dir / f"{safe_name.lower()}.json"

    def _load_index(self, path: Path) -> Index:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return Index(
            short_name=data.get("short_name", path.stem),
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            source=data.get("source", "unknown"),
            last_updated=data.get("last_updated", ""),
            constituents=data.get("constituents", []),
        )

    @staticmethod
    def _scrape_wikipedia(cfg: dict) -> list[dict]:
        tables = pd.read_html(cfg["url"])
        if "table_index" in cfg:
            df = tables[cfg["table_index"]]
        elif "table_match_col" in cfg:
            df = None
            for t in tables:
                if cfg["table_match_col"] in t.columns:
                    df = t
                    break
            if df is None:
                raise RuntimeError(
                    f"Could not find table with column '{cfg['table_match_col']}' at {cfg['url']}"
                )
        else:
            df = tables[0]
        constituents = []
        for _, row in df.iterrows():
            ticker = str(row.get(cfg["ticker_col"], "")).strip()
            name = str(row.get(cfg["name_col"], "")).strip()
            sector = str(row.get(cfg["sector_col"], "")).strip()
            if ticker and ticker != "nan":
                constituents.append({
                    "ticker": ticker,
                    "name": name if name != "nan" else "",
                    "sector": sector if sector != "nan" else "",
                })
        return constituents


class IndexNotFoundError(Exception):
    """Raised when an index or custom list is not found."""
