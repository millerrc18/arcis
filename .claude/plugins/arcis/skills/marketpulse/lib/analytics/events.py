"""Event analytics -- volume spikes, price gaps, anomaly detection, event impact."""

from __future__ import annotations

import pandas as pd

from .types import (
    VolumeSpike,
    VolumeSpikeResult,
    PriceGap,
    PriceGapResult,
    Anomaly,
    AnomalyDetectionResult,
    EventImpactResult,
)


def volume_spikes(
    df: pd.DataFrame,
    threshold: float = 3.0,
    tickers: list[str] | None = None,
) -> VolumeSpikeResult:
    """Detect bars where volume exceeds a multiple of the 20-bar rolling average.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    threshold:
        A bar is flagged when ``volume > threshold * rolling_avg``.
    tickers:
        Optional list of tickers to include.  ``None`` means all.

    Returns
    -------
    VolumeSpikeResult
        List of :class:`VolumeSpike` instances for every flagged bar.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    spikes: list[VolumeSpike] = []

    for ticker, grp in work.groupby("ticker"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        rolling_avg = grp["volume"].rolling(window=20, min_periods=20).mean()

        for idx in range(len(grp)):
            avg = rolling_avg.iloc[idx]
            if pd.isna(avg):
                continue
            vol = grp["volume"].iloc[idx]
            if vol > threshold * avg:
                ts = grp["timestamp"].iloc[idx]
                ts_iso = (
                    ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                )
                spikes.append(
                    VolumeSpike(
                        ticker=str(ticker),
                        timestamp=ts_iso,
                        volume=float(vol),
                        avg_volume=float(avg),
                        spike_ratio=float(vol / avg),
                    )
                )

    return VolumeSpikeResult(spikes=spikes, threshold=threshold)


def price_gaps(
    df: pd.DataFrame,
    threshold: float = 0.01,
    tickers: list[str] | None = None,
) -> PriceGapResult:
    """Detect overnight price gaps between consecutive trading days.

    Parameters
    ----------
    df:
        Bar DataFrame.
    threshold:
        Minimum absolute gap percentage to report.
    tickers:
        Optional list of tickers to include.

    Returns
    -------
    PriceGapResult
        List of :class:`PriceGap` instances for each qualifying gap.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    work["date"] = pd.to_datetime(work["timestamp"]).dt.date.astype(str)

    gaps: list[PriceGap] = []

    for ticker, grp in work.groupby("ticker"):
        daily: list[dict] = []
        for date_str, day_grp in grp.groupby("date", sort=True):
            day_sorted = day_grp.sort_values("timestamp")
            daily.append(
                {
                    "date": str(date_str),
                    "open": float(day_sorted["open"].iloc[0]),
                    "close": float(day_sorted["close"].iloc[-1]),
                }
            )

        daily.sort(key=lambda d: d["date"])

        for i in range(1, len(daily)):
            prev_close = daily[i - 1]["close"]
            today_open = daily[i]["open"]
            if prev_close == 0:
                continue
            gap_pct = (today_open - prev_close) / prev_close
            if abs(gap_pct) > threshold:
                direction = "up" if gap_pct > 0 else "down"
                gaps.append(
                    PriceGap(
                        ticker=str(ticker),
                        date=daily[i]["date"],
                        prev_close=prev_close,
                        open_price=today_open,
                        gap_pct=float(gap_pct),
                        direction=direction,
                    )
                )

    return PriceGapResult(gaps=gaps, threshold=threshold)


def anomaly_detection(
    df: pd.DataFrame,
    z_threshold: float = 3.0,
    tickers: list[str] | None = None,
) -> AnomalyDetectionResult:
    """Flag bars with extreme returns or volume based on z-score analysis.

    For each ticker, computes bar-level returns and rolling 60-bar statistics.
    Bars whose return or volume z-score exceeds *z_threshold* are reported.

    Parameters
    ----------
    df:
        Bar DataFrame.
    z_threshold:
        Absolute z-score cutoff for flagging anomalies.
    tickers:
        Optional list of tickers to include.

    Returns
    -------
    AnomalyDetectionResult
        List of :class:`Anomaly` instances.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    anomalies: list[Anomaly] = []

    for ticker, grp in work.groupby("ticker"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)

        # Bar-level returns
        returns = grp["close"] / grp["close"].shift(1) - 1.0
        ret_mean = returns.rolling(window=60, min_periods=60).mean()
        ret_std = returns.rolling(window=60, min_periods=60).std(ddof=1)

        # Volume z-scores
        vol_mean = grp["volume"].rolling(window=60, min_periods=60).mean()
        vol_std = grp["volume"].rolling(window=60, min_periods=60).std(ddof=1)

        for idx in range(len(grp)):
            ts = grp["timestamp"].iloc[idx]
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            # Check return anomaly
            if not pd.isna(ret_mean.iloc[idx]) and not pd.isna(ret_std.iloc[idx]):
                std_val = ret_std.iloc[idx]
                if std_val > 0:
                    z = (returns.iloc[idx] - ret_mean.iloc[idx]) / std_val
                    if abs(z) > z_threshold:
                        anomalies.append(
                            Anomaly(
                                ticker=str(ticker),
                                timestamp=ts_iso,
                                metric="return",
                                value=float(returns.iloc[idx]),
                                z_score=float(z),
                            )
                        )

            # Check volume anomaly
            if not pd.isna(vol_mean.iloc[idx]) and not pd.isna(vol_std.iloc[idx]):
                std_val = vol_std.iloc[idx]
                if std_val > 0:
                    z = (grp["volume"].iloc[idx] - vol_mean.iloc[idx]) / std_val
                    if abs(z) > z_threshold:
                        anomalies.append(
                            Anomaly(
                                ticker=str(ticker),
                                timestamp=ts_iso,
                                metric="volume",
                                value=float(grp["volume"].iloc[idx]),
                                z_score=float(z),
                            )
                        )

    return AnomalyDetectionResult(anomalies=anomalies, z_threshold=z_threshold)


def event_impact(
    df: pd.DataFrame,
    ticker: str,
    event_date: str,
    pre_days: int = 5,
    post_days: int = 5,
) -> EventImpactResult:
    """Measure the impact of an event by comparing pre/post trading windows.

    Parameters
    ----------
    df:
        Bar DataFrame.
    ticker:
        Single ticker to analyse.
    event_date:
        Date string ``"YYYY-MM-DD"`` marking the event.
    pre_days:
        Number of trading days before the event to include.
    post_days:
        Number of trading days after the event to include.

    Returns
    -------
    EventImpactResult
        Avg daily return and volume for pre/post windows, plus deltas.
    """
    work = df[df["ticker"] == ticker].copy()
    work["date"] = pd.to_datetime(work["timestamp"]).dt.date.astype(str)

    # Build daily OHLCV
    daily_rows: list[dict] = []
    for date_str, grp in work.groupby("date", sort=True):
        grp_sorted = grp.sort_values("timestamp")
        first_open = float(grp_sorted["open"].iloc[0])
        last_close = float(grp_sorted["close"].iloc[-1])
        total_vol = float(grp_sorted["volume"].sum())
        daily_return = (
            (last_close - first_open) / first_open if first_open != 0 else 0.0
        )
        daily_rows.append(
            {
                "date": str(date_str),
                "open": first_open,
                "close": last_close,
                "volume": total_vol,
                "daily_return": daily_return,
            }
        )

    daily_rows.sort(key=lambda r: r["date"])

    # Find event index
    dates = [r["date"] for r in daily_rows]
    if event_date in dates:
        event_idx = dates.index(event_date)
    else:
        # Find nearest date after event_date
        event_idx = None
        for i, d in enumerate(dates):
            if d >= event_date:
                event_idx = i
                break
        if event_idx is None:
            event_idx = len(dates)

    pre_start = max(0, event_idx - pre_days)
    pre_window = daily_rows[pre_start:event_idx]

    post_start = event_idx + 1
    post_end = min(len(daily_rows), post_start + post_days)
    post_window = daily_rows[post_start:post_end]

    # Compute averages
    pre_avg_return = (
        sum(r["daily_return"] for r in pre_window) / len(pre_window)
        if pre_window
        else 0.0
    )
    post_avg_return = (
        sum(r["daily_return"] for r in post_window) / len(post_window)
        if post_window
        else 0.0
    )
    pre_avg_volume = (
        sum(r["volume"] for r in pre_window) / len(pre_window)
        if pre_window
        else 0.0
    )
    post_avg_volume = (
        sum(r["volume"] for r in post_window) / len(post_window)
        if post_window
        else 0.0
    )

    return_change = post_avg_return - pre_avg_return
    volume_change = (
        (post_avg_volume - pre_avg_volume) / pre_avg_volume
        if pre_avg_volume > 0
        else 0.0
    )

    return EventImpactResult(
        ticker=ticker,
        event_date=event_date,
        pre_window_days=len(pre_window),
        post_window_days=len(post_window),
        pre_avg_return=float(pre_avg_return),
        post_avg_return=float(post_avg_return),
        pre_avg_volume=float(pre_avg_volume),
        post_avg_volume=float(post_avg_volume),
        return_change=float(return_change),
        volume_change=float(volume_change),
    )
