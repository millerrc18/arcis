"""S03 T4: Power simulations via date-block bootstrap with synthetic effects.

Clean-room measurement for preregistration power calibration. All effects
are SYNTHETIC and randomly assigned. No statistic is conditional on any
real signal.

Two simulation families:

**Family A (§2.1, Q1 forward information test).**
Model: label = δ_t + b_Q·Qualified + ε, date FE, SE clustered by date.
The label is the h-session forward return (h=10, closest to the 8.5-session
average hold in R01). We simulate:
  - Date-block bootstrap: resample 20-session blocks of dates with
    replacement to form 12-month and 24-month windows.
  - Randomly assign q% of stock-days as Qualified (synthetic).
  - Add synthetic effect δ to Qualified stock-days.
  - Estimate b_Q via date-demeaned OLS; test one-sided at α=2.5%.
  - Power = P(reject | δ). MDE = δ where power = 80%.
Qualification rates: 0.5%, 1%, 2%, 5%, 10%, and 17.5% (S02 planning rate,
midpoint of the 15–20% range in docs/research/old-platform-inventory.md).

**Family B (§3.2, Q2/Q3 text information test).**
Model: r = α_i + δ_t + b·(N·F) + ε, stock and date FE.
The outcome is the one-day beta-adjusted forward return. We simulate:
  - Randomly assign 8% of stock-days as news-bearing (measured share).
  - Assign synthetic scores F ~ N(0,1) to news-bearing stock-days.
  - Add synthetic effect δ·F to the return.
  - Estimate b via two-way-demeaned OLS; test one-sided with Holm
    correction for the two co-primary hypotheses (Q2, Q3) at family α=2.5%.
    For power we simulate one coefficient; Holm with 2 tests at 2.5%
    family α rejects the smaller p-value at 1.25% (conservative: we use
    the Holm-adjusted threshold for a single test).
  - Power = P(reject | δ). MDE = δ where power = 80%.

Design parameters (all recorded):
  - Block length: 20 sessions.
  - Replications: 2,000 per cell.
  - Seeds: fixed, recorded in output (base seed 304 + cell index).
  - Returns: beta-adjusted forward returns from the T3 panel. For Family A
    we use h=10; for Family B we use h=1.

Anti-contamination:
  - Never load config/incumbent_v1.yaml.
  - Synthetic qualification/scores only, randomly assigned.
  - No return conditional on any real signal.

Output: <data_root>/s03/power_results.json (aggregate statistics only).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy import stats

_FORBIDDEN_CONFIG = "incumbent_v1.yaml"
BLOCK_LEN = 20
N_REPS = 2000
BASE_SEED = 304

# Family A: §2.1 qualification rates (fractions)
Q_RATES_A = [0.005, 0.01, 0.02, 0.05, 0.10, 0.175]
# Family A: window lengths in months
WINDOWS_A = [12, 24]
# Family B: news-bearing share (measured in T3)
NEWS_SHARE_B = 0.08
# Family B: window (efficacy is judged once, at 24 months)
WINDOWS_B = [24]

# Effect grids (in return units, i.e., fractions; 0.0025 = 25 bp)
# Family A: label is 10-session forward return; grid around 25bp
GRID_A = np.array([0.0005, 0.001, 0.002, 0.0025, 0.003, 0.005, 0.0075, 0.01])
# Family B: outcome is 1-day beta-adjusted return; grid in bp
GRID_B = np.array([0.0001, 0.0002, 0.0003, 0.0005, 0.0008, 0.001, 0.0015, 0.002])


def _check_forbidden(config_dir: str) -> None:
    forbidden = os.path.join(config_dir, _FORBIDDEN_CONFIG)
    assert not os.environ.get("ARCIS_ALLOW_INCUMBENT"), (
        "S03 scripts must not run with incumbent access enabled"
    )
    _ = forbidden


def load_beta_adjusted_returns(data_root: str, h: int) -> pd.DataFrame:
    """Load panel and compute beta-adjusted h-session forward returns.

    Returns DataFrame with columns: date, symbol, ret (beta-adjusted fwd).
    Beta uses 252-session rolling window vs SPY (same as T3).
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

    # log returns
    panel["log_ret"] = np.log(panel["close"]).groupby(panel["symbol"]).diff()

    # SPY market series
    spy = panel[panel["symbol"] == "SPY"].set_index("date")["log_ret"]

    # 252-session rolling betas (vectorized per symbol)
    panel["beta"] = np.nan
    for _symbol, grp in panel.groupby("symbol"):
        idx = grp.index.values
        r = grp["log_ret"].values
        m = spy.reindex(grp["date"]).values
        # rolling cov/var via pandas for speed
        rs = pd.Series(r, index=idx)
        ms = pd.Series(m, index=idx)
        cov = rs.rolling(252).cov(ms)
        var = ms.rolling(252).var()
        beta = (cov / var).values
        panel.loc[idx, "beta"] = beta

    # h-session forward log returns
    logp = np.log(panel["close"])
    panel["fwd"] = logp.groupby(panel["symbol"]).shift(-h) - logp

    # SPY h-session forward return aligned by date
    spy_close = panel[panel["symbol"] == "SPY"].set_index("date")["close"]
    spy_fwd = (np.log(spy_close.shift(-h)) - np.log(spy_close)).rename("spy_fwd")
    panel["spy_fwd"] = panel["date"].map(spy_fwd)

    # beta-adjusted forward return
    panel["ret"] = panel["fwd"] - panel["beta"] * panel["spy_fwd"]

    out = panel[["date", "symbol", "ret"]].dropna().reset_index(drop=True)
    return out


def date_block_bootstrap(
    rets: pd.DataFrame, n_months: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Resample 20-session blocks of dates with replacement.

    n_months: 12 or 24. Assumes ~21 sessions/month.
    Returns a DataFrame with the resampled (date, symbol, ret).
    """
    dates = np.array(sorted(rets["date"].unique()))
    n_dates_needed = n_months * 21
    n_blocks = int(np.ceil(n_dates_needed / BLOCK_LEN))

    # all possible block start positions
    max_start = len(dates) - BLOCK_LEN
    starts = rng.integers(0, max_start + 1, size=n_blocks)

    sampled_dates = []
    for s in starts:
        sampled_dates.extend(dates[s : s + BLOCK_LEN])
    sampled_dates = sampled_dates[:n_dates_needed]

    # map to returns: for each sampled date, take all stock rets on that date
    # (dates may repeat; treat each occurrence as a separate block position)
    # Build by concatenating per-date frames
    by_date = {d: grp for d, grp in rets.groupby("date")}
    chunks = [by_date[d] for d in sampled_dates]
    boot = pd.concat(chunks, ignore_index=True)
    # assign a sequential block-date index for the date FE
    boot["block_date"] = np.repeat(np.arange(len(sampled_dates)),
                                    [len(c) for c in chunks])
    return boot


def estimate_bq(boot: pd.DataFrame, qualified: np.ndarray) -> tuple[float, float]:
    """Estimate b_Q via date-demeaned OLS.

    boot: DataFrame with ret, block_date.
    qualified: boolean array, same length, synthetic qualification.
    Returns (b_hat, se_clustered_by_date).
    """
    y = boot["ret"].values.astype(float)
    q = qualified.astype(float)
    d = boot["block_date"].values

    # date-demean y and q
    df = pd.DataFrame({"y": y, "q": q, "d": d})
    y_dm = df["y"] - df.groupby("d")["y"].transform("mean")
    q_dm = df["q"] - df.groupby("d")["q"].transform("mean")

    # OLS: b = (q_dm' y_dm) / (q_dm' q_dm)
    denom = float((q_dm ** 2).sum())
    if denom == 0:
        return 0.0, np.inf
    b_hat = float((q_dm * y_dm).sum() / denom)

    # clustered SE by date: meat = sum_d (q_dm_d' e_d)^2
    e = y_dm - b_hat * q_dm
    df["e"] = e.values
    df["qe"] = (q_dm * e).values
    score_by_date = df.groupby("d")["qe"].sum()
    meat = float((score_by_date ** 2).sum())
    se = np.sqrt(meat) / denom if denom > 0 else np.inf
    return b_hat, se


def simulate_family_a(
    rets: pd.DataFrame, q_rate: float, n_months: int, seed: int
) -> dict:
    """Power curve for Family A (§2.1) at one (q_rate, window) cell.

    Optimization: b_hat(delta) = b_hat_0 + delta exactly, and residuals (hence
    SE) do not depend on delta. So we simulate b_hat_0 and SE once per rep,
    then evaluate the rejection rule across the delta grid analytically.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    n_reps = N_REPS
    # one-sided α=2.5% critical value (normal)
    z_crit = stats.norm.ppf(0.975)

    # Collect (b0, se) across reps
    b0_list = []
    se_list = []
    for _rep in range(n_reps):
        boot = date_block_bootstrap(rets, n_months, rng)
        n = len(boot)
        # synthetic qualification: q_rate of stock-days, randomly assigned
        qual = rng.random(n) < q_rate
        b_hat_0, se = estimate_bq(boot, qual)
        b0_list.append(b_hat_0)
        se_list.append(se)

    b0 = np.array(b0_list)
    se = np.array(se_list)
    valid = (se > 0) & np.isfinite(se) & np.isfinite(b0)

    # Power at each delta: P((b0 + delta)/se > z_crit)
    power = []
    for delta in GRID_A:
        z = (b0[valid] + delta) / se[valid]
        power.append(float(np.mean(z > z_crit)))
    power = np.array(power)

    # MDE: interpolate delta where power = 0.80
    mde = float(_interpolate_mde(GRID_A, power, target=0.80))
    return {
        "q_rate": q_rate,
        "window_months": n_months,
        "seed": seed,
        "n_reps": n_reps,
        "block_len": BLOCK_LEN,
        "alpha_one_sided": 0.025,
        "effect_grid": [float(x) for x in GRID_A],
        "power": [float(x) for x in power],
        "mde_80": mde,
        "power_at_25bp": float(np.interp(0.0025, GRID_A, power)),
    }


def _interpolate_mde(grid: np.ndarray, power: np.ndarray, target: float = 0.80) -> float:
    """Linear interpolation of the effect where power hits target."""
    # find first grid point where power >= target
    idx = np.where(power >= target)[0]
    if len(idx) == 0:
        return float("nan")  # MDE above grid
    i = idx[0]
    if i == 0:
        return float(grid[0])
    # linear interpolation between grid[i-1] and grid[i]
    x0, x1 = grid[i - 1], grid[i]
    p0, p1 = power[i - 1], power[i]
    if p1 == p0:
        return float(x1)
    return float(x0 + (target - p0) * (x1 - x0) / (p1 - p0))


def estimate_b_text(boot: pd.DataFrame, score: np.ndarray) -> tuple[float, float]:
    """Estimate b via two-way (stock + date) demeaned OLS.

    boot: DataFrame with ret, block_date, symbol.
    score: synthetic N·F score array.
    Returns (b_hat, se_two_way_clustered).
    """
    df = pd.DataFrame({
        "y": boot["ret"].values.astype(float),
        "s": score.astype(float),
        "d": boot["block_date"].values,
        "sym": boot["symbol"].values,
    })
    # two-way demean: y - y_d - y_sym + y_overall (same for s)
    y_d = df.groupby("d")["y"].transform("mean")
    y_s = df.groupby("sym")["y"].transform("mean")
    y_bar = df["y"].mean()
    s_d = df.groupby("d")["s"].transform("mean")
    s_s = df.groupby("sym")["s"].transform("mean")
    s_bar = df["s"].mean()
    y_dm = df["y"] - y_d - y_s + y_bar
    s_dm = df["s"] - s_d - s_s + s_bar

    denom = float((s_dm ** 2).sum())
    if denom == 0:
        return 0.0, np.inf
    b_hat = float((s_dm * y_dm).sum() / denom)

    # two-way clustered SE (Cameron-Gelbach-Miller): V = V_date + V_stock - V_white
    e = y_dm - b_hat * s_dm
    df["e"] = e.values
    df["se_prod"] = (s_dm * e).values

    def cluster_var(group_col: str) -> float:
        scores = df.groupby(group_col)["se_prod"].sum()
        return float((scores ** 2).sum() / denom ** 2)

    v_date = cluster_var("d")
    v_stock = cluster_var("sym")
    v_white = float((df["se_prod"] ** 2).sum() / denom ** 2)
    v = v_date + v_stock - v_white
    se = np.sqrt(max(v, 0.0))
    return b_hat, se


def simulate_family_b(
    rets: pd.DataFrame, n_months: int, seed: int
) -> dict:
    """Power curve for Family B (§3.2) at one window.

    Holm with 2 co-primary hypotheses at family α=2.5%: the more significant
    of the two is tested at α/2 = 1.25%. We simulate a single coefficient
    and use the 1.25% threshold (conservative for the Holm procedure).

    Optimization: same linearity as Family A — b_hat(delta) = b_hat_0 + delta,
    SE independent of delta.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    n_reps = N_REPS
    # Holm-adjusted one-sided threshold for the smaller p-value: α/2 = 1.25%
    z_crit = stats.norm.ppf(1 - 0.0125)

    b0_list = []
    se_list = []
    for _rep in range(n_reps):
        boot = date_block_bootstrap(rets, n_months, rng)
        n = len(boot)
        # synthetic news-bearing: 8% of stock-days
        news = rng.random(n) < NEWS_SHARE_B
        # synthetic scores F ~ N(0,1) on news-bearing days
        f = np.zeros(n)
        f[news] = rng.standard_normal(news.sum())
        b_hat_0, se = estimate_b_text(boot, f)
        b0_list.append(b_hat_0)
        se_list.append(se)

    b0 = np.array(b0_list)
    se = np.array(se_list)
    valid = (se > 0) & np.isfinite(se) & np.isfinite(b0)

    power = []
    for delta in GRID_B:
        z = (b0[valid] + delta) / se[valid]
        power.append(float(np.mean(z > z_crit)))
    power = np.array(power)

    mde = float(_interpolate_mde(GRID_B, power, target=0.80))
    return {
        "window_months": n_months,
        "news_share": NEWS_SHARE_B,
        "seed": seed,
        "n_reps": n_reps,
        "block_len": BLOCK_LEN,
        "holm_family_alpha": 0.025,
        "per_test_alpha": 0.0125,
        "effect_grid": [float(x) for x in GRID_B],
        "power": [float(x) for x in power],
        "mde_80": mde,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S03 T4 power simulations")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--quick", action="store_true",
                        help="smoke test: 20 reps, 1 cell")
    args = parser.parse_args()

    _check_forbidden(args.config_dir)

    global N_REPS
    if args.quick:
        N_REPS = 20

    out_dir = os.path.join(args.data_root, "s03")
    os.makedirs(out_dir, exist_ok=True)

    print("Loading beta-adjusted returns (h=10)...", flush=True)
    rets_10 = load_beta_adjusted_returns(args.data_root, h=10)
    print(f"  {len(rets_10):,} rows", flush=True)
    print("Loading beta-adjusted returns (h=1)...", flush=True)
    rets_1 = load_beta_adjusted_returns(args.data_root, h=1)
    print(f"  {len(rets_1):,} rows", flush=True)

    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_seed": BASE_SEED,
        "block_len": BLOCK_LEN,
        "n_reps_per_cell": N_REPS,
        "family_a": [],
        "family_b": [],
        "notes": [
            "All effects synthetic and randomly assigned.",
            "Family A outcome: 10-session beta-adjusted forward return "
            "(closest to 8.5-session average hold, R01).",
            "Family B outcome: 1-day beta-adjusted forward return.",
            "Unbracketed forward returns overstate dispersion vs bracketed "
            "labels (MDE biased up); current-constituent survivorship "
            "understates dispersion (MDE biased down). Neither bias is "
            "called conservative.",
        ],
    }

    cell_idx = 0
    # Family A
    for n_months in WINDOWS_A:
        for q in Q_RATES_A:
            if args.quick and cell_idx > 0:
                continue
            seed = BASE_SEED + cell_idx
            print(f"Family A: {n_months}mo, q={q:.3f}, seed={seed}...", flush=True)
            cell = simulate_family_a(rets_10, q, n_months, seed)
            results["family_a"].append(cell)
            print(f"  MDE80={cell['mde_80']*1e4:.1f}bp, "
                  f"power@25bp={cell['power_at_25bp']:.2f}", flush=True)
            cell_idx += 1

    # Family B
    for n_months in WINDOWS_B:
        if args.quick and cell_idx > 1:
            continue
        seed = BASE_SEED + 100 + cell_idx
        print(f"Family B: {n_months}mo, seed={seed}...", flush=True)
        cell = simulate_family_b(rets_1, n_months, seed)
        results["family_b"].append(cell)
        print(f"  MDE80={cell['mde_80']*1e4:.1f}bp", flush=True)
        cell_idx += 1

    out_path = os.path.join(out_dir, "power_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
