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
    forbidden = os.path.join(config_dir, _FORBIDDEN_CONFIG)
    assert not os.environ.get("ARCIS_ALLOW_INCUMBENT"), (
        "S03 scripts must not run with incumbent access enabled"
    )
    _ = forbidden


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


def main() -> int:
    parser = argparse.ArgumentParser(description="S03 T3 second moments")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    _check_forbidden(args.config_dir)

    out_dir = os.path.join(args.data_root, "s03")
    os.makedirs(out_dir, exist_ok=True)

    print("Loading panel...", flush=True)
    panel = load_panel(args.data_root)
    panel = compute_log_returns(panel)
    print(f"  {len(panel):,} rows, {panel['symbol'].nunique()} symbols", flush=True)

    # Market (SPY) series indexed by date
    spy = panel[panel["symbol"] == "SPY"].set_index("date")["log_ret"]
    panel["mkt_ret"] = panel["date"].map(spy)

    print("Computing rolling betas...", flush=True)
    panel["beta"] = rolling_betas(panel, spy)
    panel["resid"] = panel["log_ret"] - panel["beta"] * panel["mkt_ret"]

    # Per-stock lag-1 autocorrelation of 1-session log returns (unconditional)
    print("Lag-1 autocorrelation...", flush=True)
    ac1 = (
        panel.groupby("symbol")["log_ret"]
        .apply(lambda s: s.autocorr(lag=1))
        .dropna()
    )

    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "n_symbols": int(panel["symbol"].nunique()),
        "n_rows": int(len(panel)),
        "date_min": str(panel["date"].min().date()),
        "date_max": str(panel["date"].max().date()),
        "horizons": HORIZONS,
        "beta_window": BETA_WINDOW,
        "by_horizon": {},
        "lag1_autocorr_1d": {
            "median": float(ac1.median()),
            "q25": float(ac1.quantile(0.25)),
            "q75": float(ac1.quantile(0.75)),
            "n_stocks": int(len(ac1)),
        },
    }

    for h in HORIZONS:
        print(f"Horizon {h}...", flush=True)
        panel[f"fwd{h}"] = forward_returns(panel, h)
        # market forward return: shift SPY closes by h sessions on SPY's own
        # calendar, then align to each stock-date via the date map
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
            # cross-sectional dispersion per date, then time-series average
            valid = series.dropna()
            disp_by_date = valid.groupby(panel.loc[valid.index, "date"]).std()
            cell[name] = {
                "xs_dispersion_mean": float(disp_by_date.mean()),
                "xs_dispersion_std": float(disp_by_date.std()),
                "n_dates": int(disp_by_date.count()),
            }

        # within-date residual correlation of beta-adjusted forward returns.
        # With one observation per stock per date, the mean pairwise product
        # of cross-sectionally standardized residuals estimates the mean
        # pairwise correlation. Sample up to 60 dates for tractability.
        resid_fwd = beta_adj.dropna()
        date_groups = resid_fwd.groupby(panel.loc[resid_fwd.index, "date"])
        rng = np.random.default_rng(303)
        all_dates = np.array(sorted(date_groups.groups.keys()))
        sample_dates = rng.choice(
            all_dates, size=min(60, len(all_dates)), replace=False
        )
        corrs = []
        by_year: dict[int, list[float]] = {}
        for d in sample_dates:
            vals = date_groups.get_group(d).values.astype(float)
            vals = vals[np.isfinite(vals)]
            if len(vals) < 10:
                continue
            z = (vals - vals.mean()) / vals.std()
            # mean pairwise product of standardized residuals
            n = len(z)
            # use random pairs to avoid O(n^2)
            pairs = rng.integers(0, n, size=(2000, 2))
            pairs = pairs[pairs[:, 0] != pairs[:, 1]]
            if len(pairs) == 0:
                continue
            mc = float(np.mean(z[pairs[:, 0]] * z[pairs[:, 1]]))
            corrs.append(mc)
            yr = int(pd.Timestamp(d).year)
            by_year.setdefault(yr, []).append(mc)

        cell["residual_corr"] = {
            "pooled_mean": float(np.mean(corrs)) if corrs else float("nan"),
            "pooled_std": float(np.std(corrs)) if corrs else float("nan"),
            "n_sampled_dates": int(len(corrs)),
            "by_year": {
                str(y): float(np.mean(v)) for y, v in sorted(by_year.items())
            },
        }
        results["by_horizon"][str(h)] = cell

    # News-bearing share (metadata only)
    print("News metadata...", flush=True)
    news = pd.read_parquet(
        os.path.join(args.data_root, "raw", "news_metadata", "news_metadata.parquet")
    )
    news["date"] = pd.to_datetime(news["date"], utc=True)
    # stock-days in the news window with at least one article
    news_days = set(zip(news["symbol"], news["date"].dt.date.astype(str), strict=True))
    # all stock-days in the same window from bars
    n_start = pd.Timestamp(news["date"].min())
    bars_window = panel[panel["date"] >= n_start]
    all_days = set(
        zip(bars_window["symbol"], bars_window["date"].dt.date.astype(str), strict=True)
    )
    bearing = len(news_days & all_days)
    total = len(all_days)
    counts = news.groupby(["symbol", "date"])["article_count"].sum()
    results["news"] = {
        "window_start": str(n_start.date()),
        "window_end": str(pd.Timestamp(news['date'].max()).date()),
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
