# Sharpe Attribution Methodology

**Authority:** SD#41 REVISED — `SD-41-REVISED-diagnostic-first-plan.md`
**Implemented:** Sprint D1 (v0.19.0)
**Target consumers:** CTO report, `/api/shadow/sharpe-attribution`, Trade History dashboard panel

---

## The problem this solves

Every Sharpe calculation in Arcis prior to v0.19.0 answered the question "did this sequence of returns look smooth?" — not "did it beat the passive benchmark?" During a bull run, a long-only strategy with any reasonable win rate will show high Sharpe **even if it's just capturing SPY drift with extra steps.** Forensic analysis of the first 78 closed trades (see `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` §6) found per-trade Sharpe 3.38 but mean excess vs SPY of +0.039% at t = 0.098 — statistically indistinguishable from zero alpha.

Raw Sharpe was a trivially-passed gate. We need a metric that separates alpha from beta.

---

## Definitions

Let a closed trade have:
- `pnl_pct` — percent return from entry to exit (e.g. 3.5 means +3.5%)
- entry date `t_in` and exit date `t_out`
- SPY close-to-close return over the same date range, `r_SPY(t_in → t_out)` (fraction, e.g. 0.02 = +2%)

Per-trade excess:

```
excess_i = pnl_pct_i − (r_SPY_i × 100)
```

Both sides are in percent after the × 100.

Per-trade raw Sharpe (annualised at 150 trades/year as the conservative Phase-1 throughput assumption):

```
Sharpe_raw = mean(pnl_pct) / stdev(pnl_pct) × √150
```

Per-trade excess Sharpe:

```
Sharpe_excess = mean(excess) / stdev(excess) × √150
```

Standard-error of Sharpe (Lo 2002 approximation, IID assumption — good enough at N ≥ 30 and honest about the IID caveat):

```
SE(Sharpe) = √((1 + 0.5 × Sharpe²) / N)
```

95% confidence interval:

```
Sharpe ± 1.96 × SE
```

t-statistic for "excess mean = 0":

```
t = mean(excess) / (stdev(excess) / √N)
```

Interpretation buckets:

| `|t|`      | Verdict                              |
|-----------|--------------------------------------|
| `< 1.0`   | `alpha_not_demonstrated`             |
| `1.0–2.0` | `alpha_suggestive` / `negative_*`    |
| `≥ 2.0`   | `alpha_significant` / `negative_*`   |

---

## The IB live-trading gate (v0.19.0 redefinition)

Previously: raw Sharpe ≥ 1.0 over 60 paper trades. This gate was trivially passed by a bull-market long-only strategy — SPY itself would have cleared it during 2024–2026.

Current gate (binding): **excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 out-of-sample trades.**

- `Sharpe_excess ≥ 0.5` — a meaningful edge, not noise
- `t ≥ 2.0` — statistically distinguishable from zero alpha at 95% confidence
- `N ≥ 150 OOS` — enough power that the SE doesn't swamp the point estimate

All three conditions must hold simultaneously. Any one failing leaves IB cold-stored per SD#41.

---

## Data pipeline

```
Entry/exit timestamps          yfinance.download("SPY", start, end, auto_adjust=True)
(close_shadow_trade hook) ───► SPY close-to-close over matched range
                               (.squeeze() to collapse MultiIndex single-ticker)
                                         │
                                         ▼
                               spy_return_over_range()  →  fraction (e.g. 0.037)
                                         │
                                         ▼
             pnl_pct ─────► excess_return(pnl_pct, r_SPY)  →  percent
                                         │
                                         ▼
                    UPDATE shadow_trades SET
                        spy_return_over_hold = <fraction>,
                        excess_return        = <percent>,
                        realized_sector      = <GICS>
                    WHERE trade_id = ?
```

**Fail-open contract:** yfinance errors, empty-response DataFrames, and ISO-8601 parse failures all resolve to `None`. None propagates through `excess_return()` (still `None`). `close_shadow_trade` writes the three fields anyway (all `None`), so the column state stays consistent — downstream aggregation uses `COUNT(excess_return IS NOT NULL)` as the denominator, not the full trade count.

**Never** block trade finalization on SPY availability. A missing attribution is preferable to a stuck open position.

---

## API consumption

`GET /api/shadow/sharpe-attribution` returns:

```json
{
  "n_trades": 85,
  "trades_with_spy_data": 85,
  "trades_missing_spy_data": 0,
  "raw_sharpe": 2.41,
  "raw_sharpe_ci_low": 1.85,
  "raw_sharpe_ci_high": 2.98,
  "excess_sharpe": 0.12,
  "excess_sharpe_ci_low": -0.41,
  "excess_sharpe_ci_high": 0.65,
  "excess_t_stat": 0.23,
  "mean_excess_pct": 0.04,
  "hit_rate_vs_spy": 51.8,
  "interpretation": "alpha_not_demonstrated"
}
```

Quarantined rows are filtered; sharpe-attribution reflects only the analytics-eligible cohort.

---

## Limitations (honest)

1. **Per-trade SPY return is NOT buy-and-hold SPY.** We match the holding period, not the position sizing or concurrency. Aggregating 85 per-trade excesses into a Sharpe is a close approximation of alpha, not a strict hedge-neutral alpha.
2. **N = 85 is underpowered for the IB gate.** The gate requires 150 OOS trades; at 85 total and ~20 weeks of activity, 150 OOS ≈ 25–30 more weeks. That's the whole point — the gate used to be passable in 2 weeks of bull-run paper trading; now it isn't.
3. **SE formula assumes IID.** Real trade returns have regime-dependent serial correlation. The CI is a lower bound on uncertainty, not an upper bound. At high Sharpe in a short sample, trust the t-stat over the point estimate.
4. **GICS sector from manual CSV.** Temporary until Sprint D3 fixes the sector_context classifier. Four-week shelf life on the lookup.
