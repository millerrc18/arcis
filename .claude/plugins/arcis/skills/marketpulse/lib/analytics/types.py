"""Analytics result dataclasses and helpers for MarketPulse."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ._base import AnalyticsResult

# ---------------------------------------------------------------------------
# Summary types
# ---------------------------------------------------------------------------


@dataclass
class DailySummary(AnalyticsResult):
    ticker: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    bar_count: int
    daily_return: float  # (close - open) / open
    intraday_range: float  # (high - low) / open


@dataclass
class DailySummaryResult(AnalyticsResult):
    summaries: list[DailySummary]
    ticker_count: int
    date_count: int


@dataclass
class Mover(AnalyticsResult):
    ticker: str
    return_pct: float
    volume: float
    close: float


@dataclass
class BiggestMoversResult(AnalyticsResult):
    gainers: list[Mover]
    losers: list[Mover]
    date: str
    n: int


@dataclass
class VolumeStats(AnalyticsResult):
    ticker: str
    total_volume: float
    avg_volume: float
    max_volume: float
    volume_std: float


@dataclass
class VolumeAnalysisResult(AnalyticsResult):
    stats: list[VolumeStats]
    date_range: str


# ---------------------------------------------------------------------------
# Volatility types
# ---------------------------------------------------------------------------


@dataclass
class TickerVolatility(AnalyticsResult):
    ticker: str
    annualized_vol: float
    daily_vol: float
    num_periods: int


@dataclass
class RealizedVolatilityResult(AnalyticsResult):
    volatilities: list[TickerVolatility]
    window: str


@dataclass
class IntradayVolBucket(AnalyticsResult):
    hour: int
    minute: int
    avg_vol: float
    bar_count: int


@dataclass
class IntradayVolProfileResult(AnalyticsResult):
    ticker: str
    buckets: list[IntradayVolBucket]


@dataclass
class VolSurfacePoint(AnalyticsResult):
    ticker: str
    window_days: int
    annualized_vol: float


@dataclass
class VolSurfaceResult(AnalyticsResult):
    points: list[VolSurfacePoint]
    windows: list[int]


@dataclass
class GarmanKlassResult(AnalyticsResult):
    ticker: str
    gk_vol: float
    annualized_gk_vol: float
    num_bars: int


# ---------------------------------------------------------------------------
# Correlation types
# ---------------------------------------------------------------------------


@dataclass
class PairCorrelation(AnalyticsResult):
    ticker_a: str
    ticker_b: str
    correlation: float


@dataclass
class PairwiseCorrelationResult(AnalyticsResult):
    pairs: list[PairCorrelation]
    tickers: list[str]
    matrix: list[list[float]]


@dataclass
class SectorCorrelationPair(AnalyticsResult):
    sector_a: str
    sector_b: str
    correlation: float


@dataclass
class SectorCorrelationResult(AnalyticsResult):
    pairs: list[SectorCorrelationPair]
    sectors: list[str]
    matrix: list[list[float]]


@dataclass
class RollingCorrelationPoint(AnalyticsResult):
    timestamp: str
    correlation: float


@dataclass
class RollingCorrelationResult(AnalyticsResult):
    ticker_a: str
    ticker_b: str
    window: int
    points: list[RollingCorrelationPoint]


# ---------------------------------------------------------------------------
# Pattern types
# ---------------------------------------------------------------------------


@dataclass
class IntradayBucket(AnalyticsResult):
    hour: int
    minute: int
    avg_return: float
    avg_volume: float
    bar_count: int


@dataclass
class IntradayPatternsResult(AnalyticsResult):
    ticker: str
    buckets: list[IntradayBucket]


@dataclass
class DayOfWeekStats(AnalyticsResult):
    day_name: str
    day_number: int
    avg_return: float
    avg_volume: float
    sample_count: int
    t_stat: float | None
    p_value: float | None


@dataclass
class DayOfWeekResult(AnalyticsResult):
    ticker: str
    days: list[DayOfWeekStats]


@dataclass
class MonthStats(AnalyticsResult):
    month: int
    month_name: str
    avg_return: float
    avg_volume: float
    sample_count: int


@dataclass
class MonthlySeasonalityResult(AnalyticsResult):
    ticker: str
    months: list[MonthStats]


# ---------------------------------------------------------------------------
# Sector types
# ---------------------------------------------------------------------------


@dataclass
class SectorPerformance(AnalyticsResult):
    sector: str
    avg_return: float
    total_volume: float
    ticker_count: int


@dataclass
class SectorRotationResult(AnalyticsResult):
    sectors: list[SectorPerformance]
    period: str


@dataclass
class SectorHeatmapCell(AnalyticsResult):
    sector: str
    date: str
    avg_return: float


@dataclass
class SectorHeatmapResult(AnalyticsResult):
    cells: list[SectorHeatmapCell]
    sectors: list[str]
    dates: list[str]


@dataclass
class RelativeStrengthTicker(AnalyticsResult):
    ticker: str
    rs_ratio: float
    ticker_return: float
    benchmark_return: float


@dataclass
class RelativeStrengthResult(AnalyticsResult):
    tickers: list[RelativeStrengthTicker]
    benchmark: str


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


@dataclass
class VolumeSpike(AnalyticsResult):
    ticker: str
    timestamp: str
    volume: float
    avg_volume: float
    spike_ratio: float


@dataclass
class VolumeSpikeResult(AnalyticsResult):
    spikes: list[VolumeSpike]
    threshold: float


@dataclass
class PriceGap(AnalyticsResult):
    ticker: str
    date: str
    prev_close: float
    open_price: float
    gap_pct: float
    direction: str


@dataclass
class PriceGapResult(AnalyticsResult):
    gaps: list[PriceGap]
    threshold: float


@dataclass
class Anomaly(AnalyticsResult):
    ticker: str
    timestamp: str
    metric: str
    value: float
    z_score: float


@dataclass
class AnomalyDetectionResult(AnalyticsResult):
    anomalies: list[Anomaly]
    z_threshold: float


@dataclass
class EventImpactResult(AnalyticsResult):
    ticker: str
    event_date: str
    pre_window_days: int
    post_window_days: int
    pre_avg_return: float
    post_avg_return: float
    pre_avg_volume: float
    post_avg_volume: float
    return_change: float
    volume_change: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_sector_map(*index_names: str) -> dict[str, str]:
    """Build a ticker -> GICS sector mapping from index JSON seed files.

    If *index_names* is empty, loads all available indices by reading JSON
    files directly.  When names are given, uses ``IndexManager`` to resolve
    them (supports short names like ``"SP500"``).
    """
    indices_dir = Path(__file__).resolve().parent.parent.parent / "indices"
    sector_map: dict[str, str] = {}

    if index_names:
        from ..indices import IndexManager

        mgr = IndexManager()
        for name in index_names:
            try:
                idx = mgr.get_index(name)
                for c in idx.constituents:
                    if c.get("sector"):
                        sector_map[c["ticker"]] = c["sector"]
            except Exception:
                pass
    else:
        for path in indices_dir.glob("*.json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for c in data.get("constituents", []):
                if c.get("sector"):
                    sector_map[c["ticker"]] = c["sector"]

    return sector_map
