"""S03 T3: Second moments of forward returns by horizon.

Clean-room measurement for preregistration power calibration. Computes
ONLY unconditional second moments — no conditioning on any real signal.

For horizons h in {1, 2, 5, 10, 15} sessions:
  - forward-return dispersion (cross-sectional std) for:
      raw returns, market-adjusted (minus SPY), beta-adjusted (252-session rolling beta)
  - pooled within-date residual correlation (beta-adjusted residuals)
  - by-year within-date residual correlation
  - per-stock lag-1 autocorrelation of 1-session returns (median, IQR)

Also: news-bearing share of stock-days and article-count distribution
(from the metadata-only news panel).

Absolute anti-contamination rules:
  - Never load config/incumbent_v1.yaml.
  - No statistic conditional on incumbent qualification, ranker score,
    text score, or any real signal. Only unconditional moments.

Output: <data_root>/s03/second_moments.json (aggregate statistics only)
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd

_FORBIDDEN_CONFIG = "incumbent_v1.yaml"
HORIZONS = [1, 2, 5, 10, 15]
BETA_WINDOW = 252


def _check_forbidden(config_dir: str) -> None:
    """Fail if incumbent access is explicitly enabled.

    This guard prevents accidental contamination: S03 measurement scripts
    must not condition on the incumbent definition. It does not (and cannot)
    prevent deliberate file access; the guarantee rests on code review
    (no open() of the incumbent path in these scripts, verified by
    tests/test_s03_cleanroom.py) plus this runtime check.
    Uses explicit raise, not assert, so it survives python -O.
    """
    if os.environ.get("ARCIS_ALLOW_INCUMBENT"):
        raise RuntimeError(
            "S03 scripts must not run with incumbent access enabled"
        )
    # Reference the forbidden path so reviewers can see what is guarded.
    _ = os.path.join(config_dir, _FORBIDDEN_CONFIG)


def load_panel(data_root: str) -> pd.DataFrame:
    """Load all per-symbol bars into one long DataFrame (date, symbol, close)."""
    bars_dir = os.path.join(data_root, "raw", "bars")
    frames = []
    for fname in sorted(os.listdir(bars_dir)):
        if not fname.endswith(".parquet"):
            continue
        symbol = fname[:-len(".parquet")]
        df = pd.read_parquet(os.path.join(bars_dir, fname), columns=["t", "c"])
        df = df.rename(columns={"t": "date", "c": "close"})
        df["symbol"] = symbol
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    return panel.sort_values(["symbol", "date"]).reset_index(drop=True)


def compute_log_returns(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["log_ret"] = np.log(panel["close"]).groupby(panel["symbol"]).diff()
    return panel


def rolling_betas(panel: pd.DataFrame, market: pd.Series) -> pd.Series:
    """252-session rolling beta of each stock vs SPY log returns.

    Returns a Series aligned to panel index.
    """
    betas = pd.Series(np.nan, index=panel.index)
    for _symbol, grp in panel.groupby("symbol"):
        idx = grp.index
        r = grp["log_ret"].values
        m = market.reindex(grp["date"]).values
        b = np.full(len(grp), np.nan)
        # rolling covariance / variance over BETA_WINDOW sessions
        for t in range(BETA_WINDOW, len(grp)):
            rw = r[t - BETA_WINDOW : t]
            mw = m[t - BETA_WINDOW : t]
            mask = np.isfinite(rw) & np.isfinite(mw)
            if mask.sum() < BETA_WINDOW // 2:
                continue
            cov = np.cov(rw[mask], mw[mask])[0, 1]
            var = np.var(mw[mask])
            b[t] = cov / var if var > 0 else np.nan
        betas.loc[idx] = b
    return betas


def forward_returns(panel: pd.DataFrame, h: int) -> pd.Series:
    """h-session forward log return, aligned to the formation date."""
    logp = np.log(panel["close"])
    fwd = logp.groupby(panel["symbol"]).shift(-h) - logp
    return fwd


def _prepare_panel(data_root: str) -> tuple[pd.DataFrame, dict]:
    """Load panel, compute log returns, rolling betas, lag-1 autocorr."""
    print("Loading panel...", flush=True)
    panel = load_panel(data_root)
    panel = compute_log_returns(panel)
    print(f"  {len(panel):,} rows, {panel['symbol'].nunique()} symbols", flush=True)
    spy = panel[panel["symbol"] == "SPY"].set_index("date")["log_ret"]
    panel["mkt_ret"] = panel["date"].map(spy)
    print("Computing rolling betas...", flush=True)
    panel["beta"] = rolling_betas(panel, spy)
    panel["resid"] = panel["log_ret"] - panel["beta"] * panel["mkt_ret"]
    print("Lag-1 autocorrelation...", flush=True)
    ac1 = (
        panel.groupby("symbol")["log_ret"]
        .apply(lambda s: s.autocorr(lag=1))
        .dropna()
    )
    ac_stats = {
        "median": float(ac1.median()),
        "q25": float(ac1.quantile(0.25)),
        "q75": float(ac1.quantile(0.75)),
        "n_stocks": int(len(ac1)),
    }
    return panel, ac_stats


def _dispersion_stats(series: pd.Series, panel: pd.DataFrame) -> dict:
    """Cross-sectional dispersion per date, then time-series average."""
    valid = series.dropna()
    disp_by_date = valid.groupby(panel.loc[valid.index, "date"]).std()
    return {
        "xs_dispersion_mean": float(disp_by_date.mean()),
        "xs_dispersion_std": float(disp_by_date.std()),
        "n_dates": int(disp_by_date.count()),
    }


def _pairwise_corr(
    resid_pivot: pd.DataFrame,
    rng: np.random.Generator,
    n_pairs: int,
    min_overlap: int,
) -> list[float]:
    """Average pairwise time-series correlation over random stock pairs."""
    symbols_list = list(resid_pivot.columns)
    corrs = []
    for _ in range(n_pairs):
        s1, s2 = rng.choice(symbols_list, size=2, replace=False)
        x = resid_pivot[s1].dropna()
        y = resid_pivot[s2].dropna()
        common = x.index.intersection(y.index)
        if len(common) < min_overlap:
            continue
        c = float(np.corrcoef(x.loc[common], y.loc[common])[0, 1])
        if np.isfinite(c):
            corrs.append(c)
    return corrs


def _horizon_cell(panel: pd.DataFrame, h: int) -> dict:
    """Second moments for one horizon: dispersions + residual correlation."""
    print(f"Horizon {h}...", flush=True)
    panel[f"fwd{h}"] = forward_returns(panel, h)
    spy_close = panel[panel["symbol"] == "SPY"].set_index("date")["close"]
    spy_fwd = np.log(spy_close.shift(-h)) - np.log(spy_close)
    panel[f"mkt_fwd{h}"] = panel["date"].map(spy_fwd)
    fwd = panel[f"fwd{h}"]
    mkt_adj = fwd - panel[f"mkt_fwd{h}"]
    beta_adj = fwd - panel["beta"] * panel[f"mkt_fwd{h}"]
    cell: dict = {}
    for name, series in [
        ("raw", fwd),
        ("market_adjusted", mkt_adj),
        ("beta_adjusted", beta_adj),
    ]:
        cell[name] = _dispersion_stats(series, panel)
    resid_fwd = beta_adj.dropna()
    resid_pivot = pd.DataFrame({
        "symbol": panel.loc[resid_fwd.index, "symbol"].values,
        "date": panel.loc[resid_fwd.index, "date"].values,
        "r": resid_fwd.values,
    }).pivot_table(index="date", columns="symbol", values="r")
    rng = np.random.default_rng(303)
    pair_corrs = _pairwise_corr(resid_pivot, rng, 2000, 30)
    by_year: dict[int, list[float]] = {}
    for yr in sorted(set(pd.Timestamp(d).year for d in resid_pivot.index)):
        yr_dates = [d for d in resid_pivot.index if pd.Timestamp(d).year == yr]
        if len(yr_dates) < 30:
            continue
        yr_corrs = _pairwise_corr(resid_pivot.loc[yr_dates], rng, 200, 20)
        if yr_corrs:
            by_year[yr] = yr_corrs
    cell["residual_corr"] = {
        "method": "average pairwise time-series correlation (2000 random pairs)",
        "pooled_mean": float(np.mean(pair_corrs)) if pair_corrs else float("nan"),
        "pooled_std": float(np.std(pair_corrs)) if pair_corrs else float("nan"),
        "n_pairs": int(len(pair_corrs)),
        "by_year": {str(y): float(np.mean(v)) for y, v in sorted(by_year.items())},
    }
    return cell


def _news_share(data_root: str, panel: pd.DataFrame) -> dict:
    """News-bearing share of stock-days.

    Methodology (reproducible):
    1. Convert article created_at to America/New_York (US equity timezone).
    2. Bucket by NY calendar date.
    3. A stock-day is "news-bearing" if >=1 article maps to that NY date
       AND that date is a trading day for the symbol in the bars panel.
    4. Share = news-bearing stock-days / total stock-days in window.
    """
    print("News metadata...", flush=True)
    news_path = os.path.join(data_root, "raw", "news_metadata")
    news = pd.read_parquet(os.path.join(news_path, "news_metadata.parquet"))
    # Use manifest window, not data min (data may have stray rows)
    with open(os.path.join(news_path, "manifest.json")) as f:
        manifest = json.load(f)
    window_start = manifest["start"]  # e.g., "2025-10-04"
    window_end = manifest["end"]
    news["created_ny"] = pd.to_datetime(
        news["earliest_created_at"], utc=True
    ).dt.tz_convert("America/New_York")
    news["ny_date"] = news["created_ny"].dt.date.astype(str)
    # Filter to manifest window
    news = news[(news["ny_date"] >= window_start) & (news["ny_date"] <= window_end)]
    news_days = set(zip(news["symbol"], news["ny_date"], strict=True))
    panel_ny_date = panel["date"].dt.tz_convert("America/New_York").dt.date.astype(str)
    bars_window = panel[
        (panel_ny_date >= window_start) & (panel_ny_date <= window_end)
    ]
    all_days = set(
        zip(bars_window["symbol"], panel_ny_date[bars_window.index], strict=True)
    )
    bearing = len(news_days & all_days)
    total = len(all_days)
    counts = news.groupby(["symbol", "ny_date"])["article_count"].sum()
    return {
        "window_start": window_start,
        "window_end": window_end,
        "methodology": (
            "created_at converted to America/New_York; bucketed by NY date; "
            "intersected with trading days from bars panel; "
            "window from manifest (not data min)"
        ),
        "news_bearing_share": float(bearing / total) if total else float("nan"),
        "news_bearing_stock_days": int(bearing),
        "total_stock_days": int(total),
        "article_count_per_stock_day": {
            "mean": float(counts.mean()),
            "median": float(counts.median()),
            "q90": float(counts.quantile(0.90)),
            "max": int(counts.max()),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S03 T3 second moments")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()
    _check_forbidden(args.config_dir)
    out_dir = os.path.join(args.data_root, "s03")
    os.makedirs(out_dir, exist_ok=True)
    panel, ac_stats = _prepare_panel(args.data_root)
    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "n_symbols": int(panel["symbol"].nunique()),
        "n_rows": int(len(panel)),
        "date_min": str(panel["date"].min().date()),
        "date_max": str(panel["date"].max().date()),
        "horizons": HORIZONS,
        "beta_window": BETA_WINDOW,
        "by_horizon": {},
        "lag1_autocorr_1d": ac_stats,
    }
    for h in HORIZONS:
        results["by_horizon"][str(h)] = _horizon_cell(panel, h)
    results["news"] = _news_share(args.data_root, panel)
    out_path = os.path.join(out_dir, "second_moments.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}", flush=True)

    # Print summary
    for h in HORIZONS:
        c = results["by_horizon"][str(h)]
        print(f"h={h}: raw_disp={c['raw']['xs_dispersion_mean']:.4f} "
              f"mkt_adj={c['market_adjusted']['xs_dispersion_mean']:.4f} "
              f"beta_adj={c['beta_adjusted']['xs_dispersion_mean']:.4f} "
              f"resid_corr={c['residual_corr']['pooled_mean']:.4f}")
    print(f"lag1 autocorr median: {results['lag1_autocorr_1d']['median']:.4f}")
    print(f"news-bearing share: {results['news']['news_bearing_share']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
