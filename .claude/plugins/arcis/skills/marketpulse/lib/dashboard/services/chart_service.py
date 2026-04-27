"""Convert analytics results to Plotly-compatible JSON and template data.

All functions are stateless: they accept an analytics result or raw data
and return a plain dict suitable for ``json.dumps()`` or Jinja2 template
context.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from ...analytics.summary import (
    BiggestMoversResult,
    VolumeAnalysisResult,
)


def volume_distribution_chart(result: VolumeAnalysisResult) -> dict[str, list]:
    """Convert volume analysis to a mini bar chart data dict.

    Returns
    -------
    dict
        ``{"labels": ["AAPL", ...], "values": [123456, ...]}``
        sorted descending by volume.
    """
    pairs = [(s.ticker, s.total_volume) for s in result.stats]
    pairs.sort(key=lambda p: p[1], reverse=True)
    return {
        "labels": [p[0] for p in pairs],
        "values": [p[1] for p in pairs],
    }


def movers_to_template_data(result: BiggestMoversResult) -> dict[str, list[dict]]:
    """Convert biggest movers result to template-friendly dicts.

    Each mover dict includes ``ticker``, ``return_pct`` (float),
    ``return_display`` (formatted string like ``"+1.23%"``), and
    ``volume`` (float).

    Returns
    -------
    dict
        ``{"gainers": [...], "losers": [...]}``
    """
    def _fmt(mover) -> dict[str, Any]:
        sign = "+" if mover.return_pct >= 0 else ""
        return {
            "ticker": mover.ticker,
            "return_pct": mover.return_pct,
            "return_display": f"{sign}{mover.return_pct * 100:.2f}%",
            "volume": mover.volume,
            "close": mover.close,
        }

    return {
        "gainers": [_fmt(m) for m in result.gainers],
        "losers": [_fmt(m) for m in result.losers],
    }


def overview_stats(cache_status: dict) -> list[dict[str, str]]:
    """Build the 4 stat cards for the overview page.

    Parameters
    ----------
    cache_status:
        Dict from ``CacheManager.get_cache_status()`` (summary mode).
        Keys: ``total_tickers``, ``total_bars``, ``total_partitions``.

    Returns
    -------
    list[dict]
        Each dict has ``label`` and ``value`` keys.
    """
    total_bars = cache_status.get("total_bars", 0)

    if total_bars >= 1_000_000:
        bars_display = f"{total_bars / 1_000_000:.1f}M"
    elif total_bars >= 1_000:
        bars_display = f"{total_bars / 1_000:.1f}K"
    else:
        bars_display = f"{total_bars:,}"

    return [
        {"label": "Tickers Cached", "value": str(cache_status.get("total_tickers", 0))},
        {"label": "Total Bars", "value": bars_display},
        {"label": "Partitions", "value": str(cache_status.get("total_partitions", 0))},
        {"label": "Data Points", "value": f"{total_bars:,}"},
    ]


def candlestick_chart_data(df: pd.DataFrame, ticker: str) -> dict[str, list]:
    """Convert bar DataFrame to arrays for createCandlestick() JS helper."""
    tdf = df[df["ticker"] == ticker].sort_values("timestamp")
    return {
        "dates": [t.isoformat() if hasattr(t, "isoformat") else str(t) for t in tdf["timestamp"]],
        "open": tdf["open"].tolist(),
        "high": tdf["high"].tolist(),
        "low": tdf["low"].tolist(),
        "close": tdf["close"].tolist(),
        "volume": tdf["volume"].tolist(),
    }


def volatility_chart_data(result) -> list[dict]:
    """Convert VolSurfaceResult to multi-line series for createLineChart()."""
    by_ticker: dict[str, dict[int, float]] = defaultdict(dict)
    for pt in result.points:
        by_ticker[pt.ticker][pt.window_days] = pt.annualized_vol
    series = []
    for ticker, window_vols in sorted(by_ticker.items()):
        sorted_windows = sorted(window_vols.keys())
        series.append({
            "name": ticker,
            "x": [f"{w}d" for w in sorted_windows],
            "y": [window_vols[w] for w in sorted_windows],
        })
    return series


def correlation_heatmap_data(result) -> dict[str, list]:
    """Convert PairwiseCorrelationResult to createHeatmap() format."""
    return {
        "x": list(result.tickers),
        "y": list(result.tickers),
        "z": [list(row) for row in result.matrix],
    }


def pattern_chart_data(result, pattern_type: str) -> dict[str, list]:
    """Convert pattern results to createGroupedBar() format."""
    if pattern_type == "intraday":
        categories = [f"{b.hour:02d}:{b.minute:02d}" for b in result.buckets]
        return {
            "categories": categories,
            "series": [
                {"name": "Avg Return", "values": [b.avg_return for b in result.buckets]},
                {"name": "Avg Volume", "values": [b.avg_volume for b in result.buckets]},
            ],
        }
    elif pattern_type == "day_of_week":
        categories = [d.day_name for d in result.days]
        return {
            "categories": categories,
            "series": [
                {"name": "Avg Return", "values": [d.avg_return for d in result.days]},
                {"name": "Avg Volume", "values": [d.avg_volume for d in result.days]},
            ],
        }
    elif pattern_type == "monthly":
        categories = [m.month_name for m in result.months]
        return {
            "categories": categories,
            "series": [
                {"name": "Avg Return", "values": [m.avg_return for m in result.months]},
                {"name": "Avg Volume", "values": [m.avg_volume for m in result.months]},
            ],
        }
    return {"categories": [], "series": []}


def sector_rotation_chart_data(result) -> dict[str, list]:
    """Convert SectorRotationResult to horizontal bar data."""
    return {
        "labels": [s.sector for s in result.sectors],
        "values": [s.avg_return for s in result.sectors],
    }


def sector_heatmap_chart_data(result) -> dict[str, list]:
    """Convert SectorHeatmapResult to createHeatmap() format."""
    cell_map: dict[tuple[str, str], float] = {}
    for cell in result.cells:
        cell_map[(cell.sector, cell.date)] = cell.avg_return
    z = []
    for sector in result.sectors:
        row = [cell_map.get((sector, d), 0.0) for d in result.dates]
        z.append(row)
    return {
        "x": list(result.dates),
        "y": list(result.sectors),
        "z": z,
    }


def events_table_data(result, event_type: str) -> list[dict]:
    """Convert event detection results to table row dicts."""
    rows = []
    if event_type == "volume_spikes":
        for s in result.spikes:
            rows.append({
                "ticker": s.ticker,
                "date": s.timestamp[:10] if len(s.timestamp) >= 10 else s.timestamp,
                "type": "Volume Spike",
                "magnitude": f"{s.spike_ratio:.1f}x avg",
                "detail": f"Vol: {s.volume:,.0f} vs avg {s.avg_volume:,.0f}",
            })
    elif event_type == "price_gaps":
        for g in result.gaps:
            rows.append({
                "ticker": g.ticker,
                "date": g.date,
                "type": f"Gap {g.direction.title()}",
                "magnitude": f"{g.gap_pct:+.2%}",
                "detail": f"Prev close: {g.prev_close:.2f} -> Open: {g.open_price:.2f}",
            })
    elif event_type == "anomalies":
        for a in result.anomalies:
            rows.append({
                "ticker": a.ticker,
                "date": a.timestamp[:10] if len(a.timestamp) >= 10 else a.timestamp,
                "type": f"Anomaly ({a.metric})",
                "magnitude": f"z={a.z_score:.1f}",
                "detail": f"Value: {a.value:.4f}",
            })
    return rows


def event_impact_chart_data(result) -> dict:
    """Convert EventImpactResult to a comparison data dict."""
    return {
        "ticker": result.ticker,
        "event_date": result.event_date,
        "pre_return": result.pre_avg_return,
        "post_return": result.post_avg_return,
        "pre_volume": result.pre_avg_volume,
        "post_volume": result.post_avg_volume,
        "return_change": result.return_change,
        "volume_change": result.volume_change,
    }
