"""S03 power simulation library: date-block bootstrap with synthetic effects.

Clean-room measurement for preregistration power calibration. All effects
are SYNTHETIC and randomly assigned. No statistic is conditional on any
real signal.

Used by tools/run_power_sims.py.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from scipy import stats

_FORBIDDEN_CONFIG = "incumbent_v1.yaml"
BLOCK_LEN = 20


def check_forbidden(config_dir: str) -> None:
    """Fail if incumbent access is explicitly enabled.

    Uses explicit raise, not assert, so it survives python -O.
    The guarantee rests on code review (no open() of the incumbent path,
    verified by tests/test_s03_cleanroom.py) plus this runtime check.
    """
    if os.environ.get("ARCIS_ALLOW_INCUMBENT"):
        raise RuntimeError(
            "S03 scripts must not run with incumbent access enabled"
        )
    _ = os.path.join(config_dir, _FORBIDDEN_CONFIG)


def load_beta_adjusted_returns(data_root: str, h: int) -> pd.DataFrame:
    """Load panel and compute beta-adjusted h-session forward returns.

    Returns DataFrame with columns: date, symbol, ret (beta-adjusted fwd).
    Beta uses 252-session rolling window vs SPY.
    """
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
    panel["date"] = pd.to_datetime(panel["date"], utc=True)
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    panel["log_ret"] = np.log(panel["close"]).groupby(panel["symbol"]).diff()
    spy = panel[panel["symbol"] == "SPY"].set_index("date")["log_ret"]
    panel["beta"] = _rolling_betas(panel, spy)
    logp = np.log(panel["close"])
    panel["fwd"] = logp.groupby(panel["symbol"]).shift(-h) - logp
    spy_close = panel[panel["symbol"] == "SPY"].set_index("date")["close"]
    spy_fwd = (np.log(spy_close.shift(-h)) - np.log(spy_close)).rename("spy_fwd")
    panel["spy_fwd"] = panel["date"].map(spy_fwd)
    panel["ret"] = panel["fwd"] - panel["beta"] * panel["spy_fwd"]
    return panel[["date", "symbol", "ret"]].dropna().reset_index(drop=True)


def _rolling_betas(panel: pd.DataFrame, spy: pd.Series) -> pd.Series:
    """252-session rolling beta vs SPY, vectorized per symbol.

    Uses the 252 sessions *prior* to day t (excludes t), consistent with
    tools/measure_second_moments.py.
    """
    betas = pd.Series(np.nan, index=panel.index)
    for _symbol, grp in panel.groupby("symbol"):
        idx = grp.index.values
        rs = pd.Series(grp["log_ret"].values, index=idx)
        ms = pd.Series(spy.reindex(grp["date"]).values, index=idx)
        # shift by 1 to exclude day t, then rolling 252
        cov = rs.shift(1).rolling(252).cov(ms.shift(1))
        var = ms.shift(1).rolling(252).var()
        betas.loc[idx] = (cov / var).values
    return betas


def _prep_panel_arrays(rets: pd.DataFrame) -> dict:
    """Pre-compute numpy arrays and date->rows mapping for fast bootstrap."""
    y = rets["ret"].values.astype(float)
    dates = np.array(sorted(rets["date"].unique()))
    date_to_idx = {d: i for i, d in enumerate(dates)}
    date_idx = rets["date"].map(date_to_idx).values.astype(np.int64)
    # rows per date (as numpy arrays)
    rows_by_date = {}
    for d, grp in rets.groupby("date", sort=False):
        rows_by_date[d] = grp.index.values.astype(np.int64)
    symbols = rets["symbol"].values
    # symbol -> 0..S-1 for bincount
    uniq_syms = np.array(sorted(set(symbols)))
    sym_to_idx = {s: i for i, s in enumerate(uniq_syms)}
    sym_idx_full = np.array([sym_to_idx[s] for s in symbols], dtype=np.int64)
    return {
        "y": y,
        "dates": dates,
        "date_idx": date_idx,
        "rows_by_date": rows_by_date,
        "symbols": symbols,
        "sym_idx_full": sym_idx_full,
        "n_dates": len(dates),
    }


def _bootstrap_indices(
    prep: dict, n_months: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Sample 20-session blocks; return (row_indices, block_date_ids)."""
    n_dates_needed = n_months * 21
    n_blocks = int(np.ceil(n_dates_needed / BLOCK_LEN))
    max_start = prep["n_dates"] - BLOCK_LEN
    starts = rng.integers(0, max_start + 1, size=n_blocks)
    dates = prep["dates"]
    rows_by_date = prep["rows_by_date"]
    # Collect exactly n_dates_needed dates' worth of rows
    row_chunks = []
    block_ids = []
    count = 0
    for _bi, s in enumerate(starts):
        for d in dates[s : s + BLOCK_LEN]:
            if count >= n_dates_needed:
                break
            rows = rows_by_date[d]
            row_chunks.append(rows)
            block_ids.append(np.full(len(rows), count, dtype=np.int64))
            count += 1
        if count >= n_dates_needed:
            break
    rows = np.concatenate(row_chunks)
    bdate = np.concatenate(block_ids)
    return rows, bdate


def _demean_by_group(x: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Subtract group means (numpy, faster than pandas groupby)."""
    # g must be 0..G-1 integers
    sums = np.bincount(g, weights=x)
    counts = np.bincount(g)
    means = sums / np.maximum(counts, 1)
    return x - means[g]


def estimate_bq_fast(
    y: np.ndarray, q: np.ndarray, bdate: np.ndarray
) -> tuple[float, float]:
    """Date-demeaned OLS with date-clustered SE (numpy)."""
    y_dm = _demean_by_group(y, bdate)
    q_dm = _demean_by_group(q, bdate)
    denom = float((q_dm ** 2).sum())
    if denom == 0:
        return 0.0, np.inf
    b_hat = float((q_dm * y_dm).sum() / denom)
    e = y_dm - b_hat * q_dm
    qe = q_dm * e
    # clustered meat: sum over dates of (sum qe)^2
    s = np.bincount(bdate, weights=qe)
    meat = float((s ** 2).sum())
    se = np.sqrt(meat) / denom if denom > 0 else np.inf
    return b_hat, se


def estimate_b_text_fast(
    y: np.ndarray,
    s: np.ndarray,
    bdate: np.ndarray,
    sym_idx: np.ndarray,
) -> tuple[float, float]:
    """Two-way (stock + date) demeaned OLS, numpy version.

    Returns (b_hat, se_two_way_clustered via Cameron-Gelbach-Miller).
    """
    # Two-way demean: x - x_d - x_s + x_bar; compute means directly
    # date means
    d_sums = np.bincount(bdate, weights=y)
    d_counts = np.bincount(bdate)
    d_means = d_sums / np.maximum(d_counts, 1)
    # symbol means (sym_idx must be 0..S-1)
    s_sums = np.bincount(sym_idx, weights=y)
    s_counts = np.bincount(sym_idx)
    s_means = s_sums / np.maximum(s_counts, 1)
    y_bar = y.mean()
    y_dm = y - d_means[bdate] - s_means[sym_idx] + y_bar
    # same for s
    sd_sums = np.bincount(bdate, weights=s)
    sd_means = sd_sums / np.maximum(d_counts, 1)
    ss_sums = np.bincount(sym_idx, weights=s)
    ss_means = ss_sums / np.maximum(s_counts, 1)
    s_bar = s.mean()
    s_dm = s - sd_means[bdate] - ss_means[sym_idx] + s_bar
    denom = float((s_dm ** 2).sum())
    if denom == 0:
        return 0.0, np.inf
    b_hat = float((s_dm * y_dm).sum() / denom)
    e = y_dm - b_hat * s_dm
    se_prod = s_dm * e
    # CGM: V = V_date + V_stock - V_white
    v_date = float((np.bincount(bdate, weights=se_prod) ** 2).sum() / denom ** 2)
    v_stock = float((np.bincount(sym_idx, weights=se_prod) ** 2).sum() / denom ** 2)
    v_white = float((se_prod ** 2).sum() / denom ** 2)
    v = v_date + v_stock - v_white
    return b_hat, np.sqrt(max(v, 0.0))


def estimate_b_text(boot: pd.DataFrame, score: np.ndarray) -> tuple[float, float]:
    """Estimate b via two-way (stock + date) demeaned OLS.

    Returns (b_hat, se_two_way_clustered via Cameron-Gelbach-Miller).
    Legacy pandas version; prefer estimate_b_text_fast for simulations.
    """
    df = pd.DataFrame({
        "y": boot["ret"].values.astype(float),
        "s": score.astype(float),
        "d": boot["block_date"].values,
        "sym": boot["symbol"].values,
    })
    y_dm = (df["y"] - df.groupby("d")["y"].transform("mean")
            - df.groupby("sym")["y"].transform("mean") + df["y"].mean())
    s_dm = (df["s"] - df.groupby("d")["s"].transform("mean")
            - df.groupby("sym")["s"].transform("mean") + df["s"].mean())
    denom = float((s_dm ** 2).sum())
    if denom == 0:
        return 0.0, np.inf
    b_hat = float((s_dm * y_dm).sum() / denom)
    e = y_dm - b_hat * s_dm
    df["se_prod"] = (s_dm * e).values

    def cluster_var(col: str) -> float:
        scores = df.groupby(col)["se_prod"].sum()
        return float((scores ** 2).sum() / denom ** 2)

    v = cluster_var("d") + cluster_var("sym") - float(
        (df["se_prod"] ** 2).sum() / denom ** 2
    )
    return b_hat, np.sqrt(max(v, 0.0))


def interpolate_mde(grid: np.ndarray, power: np.ndarray, target: float = 0.80) -> float:
    """Linear interpolation of the effect where power hits target."""
    idx = np.where(power >= target)[0]
    if len(idx) == 0:
        return float("nan")
    i = idx[0]
    if i == 0:
        return float(grid[0])
    x0, x1 = grid[i - 1], grid[i]
    p0, p1 = power[i - 1], power[i]
    if p1 == p0:
        return float(x1)
    return float(x0 + (target - p0) * (x1 - x0) / (p1 - p0))


def power_se(power: float, n_reps: int) -> float:
    """Binomial standard error of a power estimate."""
    return float(np.sqrt(power * (1 - power) / n_reps))


def simulate_family_a(
    rets: pd.DataFrame,
    q_rate: float,
    n_months: int,
    seed: int,
    n_reps: int,
    grid: np.ndarray,
) -> dict:
    """Power curve for Family A (§2.1) at one (q_rate, window) cell.

    Model: label = b_Q·Qualified + ε, date FE, SE clustered by date.
    One-sided α=2.5%. Linearity: b_hat(delta) = b_hat_0 + delta exactly,
    SE independent of delta, so we simulate once and evaluate the grid.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    z_crit = stats.norm.ppf(0.975)
    prep = _prep_panel_arrays(rets)
    b0 = np.zeros(n_reps)
    se = np.zeros(n_reps)
    for rep in range(n_reps):
        rows, bdate = _bootstrap_indices(prep, n_months, rng)
        y = prep["y"][rows]
        qual = (rng.random(len(rows)) < q_rate).astype(float)
        b0[rep], se[rep] = estimate_bq_fast(y, qual, bdate)
    valid = (se > 0) & np.isfinite(se) & np.isfinite(b0)
    power = np.array([
        float(np.mean((b0[valid] + d) / se[valid] > z_crit)) for d in grid
    ])
    se_power = np.array([power_se(p, valid.sum()) for p in power])
    mde = interpolate_mde(grid, power)
    return {
        "q_rate": q_rate,
        "window_months": n_months,
        "seed": seed,
        "n_reps": n_reps,
        "block_len": BLOCK_LEN,
        "alpha_one_sided": 0.025,
        "effect_grid": [float(x) for x in grid],
        "power": [float(x) for x in power],
        "power_se": [float(x) for x in se_power],
        "mde_80": float(mde),
        "power_at_25bp": float(np.interp(0.0025, grid, power)),
    }


def simulate_family_b(
    rets: pd.DataFrame,
    n_months: int,
    seed: int,
    n_reps: int,
    grid: np.ndarray,
    news_share: float,
) -> dict:
    """Power curve for Family B (§3.2) at one window.

    Holm with 2 co-primary hypotheses at family α=2.5%: test at 1.25%.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    z_crit = stats.norm.ppf(1 - 0.0125)
    prep = _prep_panel_arrays(rets)
    b0 = np.zeros(n_reps)
    se = np.zeros(n_reps)
    for rep in range(n_reps):
        rows, bdate = _bootstrap_indices(prep, n_months, rng)
        y = prep["y"][rows]
        sym_idx = prep["sym_idx_full"][rows]
        n = len(rows)
        news = rng.random(n) < news_share
        f = np.zeros(n)
        f[news] = rng.standard_normal(news.sum())
        b0[rep], se[rep] = estimate_b_text_fast(y, f, bdate, sym_idx)
    valid = (se > 0) & np.isfinite(se) & np.isfinite(b0)
    power = np.array([
        float(np.mean((b0[valid] + d) / se[valid] > z_crit)) for d in grid
    ])
    se_power = np.array([power_se(p, valid.sum()) for p in power])
    return {
        "window_months": n_months,
        "news_share": news_share,
        "seed": seed,
        "n_reps": n_reps,
        "block_len": BLOCK_LEN,
        "holm_family_alpha": 0.025,
        "per_test_alpha": 0.0125,
        "effect_grid": [float(x) for x in grid],
        "power": [float(x) for x in power],
        "power_se": [float(x) for x in se_power],
        "mde_80": float(interpolate_mde(grid, power)),
    }
