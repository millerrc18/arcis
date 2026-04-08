# Design Spec: Strategy Dashboard Page Enhancement

> **Page:** `frontend/src/pages/Strategy.jsx` (existing, 238 lines)
> **Backend:** `src/api/cloud_routes/analytics.py` line 631
> **Author:** Claude (CTO)
> **Status:** SPEC — ready for sprint prompt conversion
> **Estimated effort:** 4-6 hours CC time (backend + frontend)
> **Ralph Loop:** 3x (see bottom)

---

## Current State

The Strategy page (238 lines) already provides:
- Strategy KPI cards (side-by-side pullback vs MR)
- 12-metric comparison table
- Head-to-head bar chart (WR, avg P&L, avg hold)
- Exit reason pie chart per strategy
- SD#2 correlation warning banner

The backend `/api/strategy-comparison` returns per-strategy: closed, open,
win_rate, avg_pnl_pct, total_pnl_dollars, avg_winner_pct, avg_loser_pct,
profit_factor, sharpe, max_drawdown_dollars, avg_hold_days, avg_score,
expectancy, by_exit_reason, max_consecutive_losses.

---

## What's Missing

### Gap 1: No time-series view

The page shows aggregate metrics but no temporal dimension. You can't see:
- When trades happened relative to each other
- Whether a strategy is improving or degrading over time
- How strategies performed in different market periods

### Gap 2: No equity curve per strategy

The CTO Report has an aggregate equity curve, but there's no way to see
cumulative P&L separated by strategy. This is the single most important
chart for comparing strategy performance over time.

### Gap 3: No score band analysis per strategy

The CTO Report shows score bands (0-39, 60-79, 80-100) across all trades.
The Strategy page should show this per-strategy: does the 80-100 band
perform equally well for pullback and MR, or is the ranker miscalibrated
for one strategy?

### Gap 4: No drawdown profile per strategy

Max drawdown is shown as a single number. A drawdown chart (underwater
equity curve) per strategy reveals clustering, recovery speed, and whether
drawdowns overlap (correlation risk).

### Gap 5: No hold period distribution

Average hold days is a single number. A histogram shows whether the
distribution is normal, bimodal, or has a long tail — each implies
different bracket calibration strategies.

### Gap 6: No statistical significance

With 51 pullback trades and 0 MR trades, the comparison is academic now.
But once MR has data, the page should show whether performance differences
are statistically significant (Mann-Whitney U test) or just noise.

### Gap 7: No regime breakdown per strategy

How does each strategy perform in bull vs bear vs sideways? The regime
data exists in recommendations.market_regime but isn't surfaced here.

---

## Design: Backend Changes

### New endpoint: `/api/strategy-detail/<strategy_type>`

Returns detailed time-series and breakdown data for a single strategy.
Keeps the existing `/api/strategy-comparison` lightweight for the overview.

```python
@router.get("/api/strategy-detail/{strategy_type}")
def strategy_detail(strategy_type: str):
    """Detailed analytics for a single strategy."""
    return {
        # Trade-level time series (for equity curve + timeline)
        "trades": [
            {
                "ticker": "AAPL",
                "entry_date": "2026-03-15",
                "exit_date": "2026-03-22",
                "pnl_pct": 2.3,
                "pnl_dollars": 45.50,
                "exit_reason": "target_1_hit",
                "duration_days": 7,
                "score": 85,
                "regime": "bull_trending",
                "cumulative_pnl": 245.50,
            },
            # ...
        ],

        # Score band breakdown (for calibration analysis)
        "by_score_band": {
            "0-39": {"trades": 5, "wins": 3, "win_rate": 0.6, "avg_pnl": 0.15},
            "40-59": {"trades": 8, "wins": 5, "win_rate": 0.625, "avg_pnl": 0.42},
            "60-79": {"trades": 12, "wins": 9, "win_rate": 0.75, "avg_pnl": 0.68},
            "80-100": {"trades": 10, "wins": 10, "win_rate": 1.0, "avg_pnl": 2.48},
        },

        # Regime breakdown
        "by_regime": {
            "bull_trending": {"trades": 20, "win_rate": 0.85, "avg_pnl": 1.2},
            "sideways_chop": {"trades": 5, "win_rate": 0.4, "avg_pnl": -0.3},
            "unknown": {"trades": 26, "win_rate": 0.78, "avg_pnl": 0.6},
        },

        # Hold period distribution (for histogram)
        "hold_distribution": [
            {"days": 1, "count": 2},
            {"days": 2, "count": 5},
            # ... through max hold
        ],

        # Sector breakdown
        "by_sector": {
            "Technology": {"trades": 15, "win_rate": 0.8, "avg_pnl": 1.5},
            "Healthcare": {"trades": 8, "win_rate": 0.75, "avg_pnl": 0.9},
            # ...
        },

        # Rolling metrics (30-trade window)
        "rolling_metrics": [
            {"trade_num": 30, "rolling_wr": 0.73, "rolling_pf": 2.1, "rolling_sharpe": 0.35},
            {"trade_num": 31, "rolling_wr": 0.74, "rolling_pf": 2.2, "rolling_sharpe": 0.38},
            # ...
        ],

        # Drawdown series
        "drawdown_series": [
            {"trade_num": 1, "cumulative_pnl": 45.50, "drawdown_pct": 0},
            {"trade_num": 2, "cumulative_pnl": 90.20, "drawdown_pct": 0},
            {"trade_num": 3, "cumulative_pnl": 55.10, "drawdown_pct": -38.9},
            # ...
        ],
    }
```

### Enhancement to existing endpoint

Add to `/api/strategy-comparison`:
- `correlation`: Pearson correlation of daily returns between strategies (when both have data)
- `significance`: p-value from Mann-Whitney U test on P&L distributions
- `combined_equity_curve`: merged trade-by-trade cumulative P&L for each strategy

---

## Design: Frontend Changes

### Section 1: Overview (existing, minor updates)

Keep the existing KPI cards and comparison table. Add:
- **Statistical significance badge** next to the comparison table title: "Difference: Not significant (p=0.72)" or "Significant (p=0.03)"
- **Correlation display** in the SD#2 warning banner: "Measured ρ = X.XX" alongside the theoretical 0.35-0.50

### Section 2: Equity Curves (NEW)

Overlaid line chart showing cumulative P&L per strategy over time. 

```
[Pullback ——— blue line]    [MR ——— amber line]
Cumulative P&L ($) on Y-axis, trade number on X-axis
```

Component: `<StrategyEquityCurve strategies={data.combined_equity_curve} />`

Uses recharts `<LineChart>` with one `<Line>` per strategy. Tooltip shows
trade details on hover. Reference line at Y=0.

### Section 3: Score Band Comparison (NEW)

Side-by-side grouped bar chart showing win rate and avg P&L by score band
for each strategy. This answers: "Is the ranker equally predictive for
both strategies?"

```
Score Band  | Pullback WR | MR WR | Pullback Avg P&L | MR Avg P&L
0-39        | 78%         | --    | +0.27%           | --
60-79       | 65%         | --    | +0.67%           | --
80-100      | 100%        | --    | +2.48%           | --
```

Component: `<ScoreBandComparison strategies={detail data} />`

### Section 4: Hold Period Distribution (NEW)

Histogram per strategy showing trade count by hold days. Overlaid as
semi-transparent bars (blue for pullback, amber for MR).

This reveals whether brackets are calibrated correctly. If 69% of trades
cluster at the timeout boundary, the histogram will show a spike at
day 15 (or whatever the reconciliation interval is).

Component: `<HoldDistribution data={detail.hold_distribution} />`

### Section 5: Regime Performance (NEW)

Table showing strategy metrics broken down by market regime. Only show
regimes with 5+ trades (suppress noisy small samples).

```
Regime          | Pullback WR | Pullback PF | MR WR | MR PF
Bull trending   | 85%         | 3.2         | --    | --
Sideways chop   | 40%         | 0.8         | --    | --
High volatility | 60%         | 1.5         | --    | --
```

Highlight regimes where a strategy underperforms (WR < 50% or PF < 1.0)
in red. This directly informs the Traffic Light overlay calibration.

Component: `<RegimeBreakdown data={detail.by_regime} />`

### Section 6: Drawdown Profile (NEW)

Underwater equity chart (drawdown from peak) per strategy. Shows:
- Depth of drawdowns
- Recovery speed
- Whether strategy drawdowns overlap (correlation risk)

Component: `<DrawdownChart data={detail.drawdown_series} />`

### Section 7: Trade Timeline (NEW)

Horizontal scatter/bar chart showing individual trades on a time axis.
Each trade is a horizontal bar from entry to exit, colored by P&L
(green = win, red = loss, gray = breakeven). Height/row = strategy.

This gives a visual sense of trade density, overlap, and clustering.

Component: `<TradeTimeline trades={detail.trades} />`

### Section 8: Sector Breakdown (NEW)

Horizontal bar chart per strategy showing trade count and average P&L
by GICS sector. Identifies which sectors each strategy works best in.

Component: `<SectorBreakdown data={detail.by_sector} />`

### Section 9: Existing exit reason + SD#2 warning (keep)

No changes. Already well-implemented.

---

## Data Flow

```
User loads /strategy
  → GET /api/strategy-comparison (lightweight, existing)
    → Renders overview KPI cards, table, head-to-head chart
  → GET /api/strategy-detail/pullback (new, heavy)
    → Renders equity curve, score bands, hold dist, regime, drawdown, timeline, sectors
  → GET /api/strategy-detail/mean_reversion (new, heavy, deferred until MR has data)
    → Same components, overlaid where applicable
```

The detail endpoints are fetched with `refetchInterval: 300000` (5 min)
since they query trade history which changes infrequently.

---

## Implementation Notes

### Backend: src/api/cloud_routes/analytics.py

The strategy-detail endpoint queries shadow_trades joined with
recommendations (for score, regime, setup_type) and uses SECTOR_MAP
for sector classification. The rolling metrics computation uses a
sliding window over the trade list.

Key SQL:
```sql
SELECT st.ticker, st.pnl_dollars, st.pnl_pct, st.exit_reason,
       st.duration_days, st.actual_entry_time, st.actual_exit_time,
       r.priority_score, r.market_regime, r.setup_type
FROM shadow_trades st
LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id
WHERE st.status = 'closed' AND st.strategy_type = ?
ORDER BY st.actual_exit_time ASC
```

### Frontend: Strategy.jsx

Split into sub-components:
- `StrategyOverview.jsx` — existing KPI cards + table (refactored out)
- `StrategyEquityCurve.jsx` — overlaid line chart
- `StrategyScoreBands.jsx` — grouped bar chart
- `StrategyHoldDist.jsx` — histogram
- `StrategyRegime.jsx` — table with conditional coloring
- `StrategyDrawdown.jsx` — underwater chart
- `StrategyTimeline.jsx` — horizontal bar scatter
- `StrategySector.jsx` — horizontal bar chart

Main Strategy.jsx becomes a layout coordinator that fetches both endpoints
and passes data to child components.

### Graceful degradation

When a strategy has 0 trades (e.g., MR currently), the detail sections
should show "Awaiting first closed MR trade" placeholders, not errors.
The overview comparison still works with a single strategy — it just
shows one column.

---

## Tests

1. `test_strategy_detail_endpoint` — returns correct shape with trade data
2. `test_strategy_detail_empty` — returns empty arrays for strategy with 0 trades
3. `test_score_band_computation` — bins trades correctly into score ranges
4. `test_rolling_metrics` — 30-trade rolling window produces correct values
5. `test_drawdown_series` — peak tracking and DD computation are correct
6. `test_regime_breakdown` — groups by regime, suppresses <5 trade buckets
7. `test_hold_distribution` — counts trades per hold day correctly
8. `test_correlation_computation` — Pearson correlation matches manual calc
9. `test_significance_test` — Mann-Whitney U returns correct p-value

---

## Ralph Loop

### Iteration 1: Initial spec
- Designed 7 new sections + 1 new backend endpoint
- MISSED: Need graceful degradation for MR with 0 trades
- MISSED: The hold distribution should highlight the reconciliation
  timeout boundary (day 15) as a reference line — this is the key
  diagnostic for the 69% stale exit problem

### Iteration 2: Refinements
- Added graceful degradation section
- Added reference line in hold distribution at the timeout boundary
- Added correlation + significance to the comparison endpoint
- Reconsidered: TradeTimeline (Section 7) is complex to render and
  may not justify the effort for only 51 trades. DECISION: Keep it
  but mark as low-priority — implement after the more diagnostic
  sections (equity curve, score bands, hold dist, drawdown)
- Added sector breakdown — important because the CTO Report shows
  "unknown" sector for 18/51 trades, which suggests the sector
  enrichment might not be running for all trades
- Changed rolling_metrics to use a 20-trade window (not 30) since
  we only have 51 trades. At 30-trade window, we'd only get 21 data points.

### Iteration 3: Final review
- Verified all data joins are possible with existing schema: shadow_trades
  has recommendation_id which joins to recommendations for score, regime,
  setup_type. SECTOR_MAP provides static sector lookup by ticker.
- Confirmed: the regime field is on recommendations, not shadow_trades.
  The detail endpoint must join to get this. Currently the strategy-comparison
  endpoint doesn't join recommendations for regime — this is a gap.
- Added implementation note: the frontend split into sub-components is
  important because Strategy.jsx will grow from 238 to ~600-800 lines.
  Without splitting, it violates the 400-line file rule.
- Prioritized sections by diagnostic value:
  1. Equity curve (highest — shows trajectory)
  2. Score bands (high — validates ranker per-strategy)
  3. Hold distribution (high — diagnoses stale exit problem)
  4. Drawdown profile (medium — shows risk character)
  5. Regime breakdown (medium — informs Traffic Light)
  6. Sector breakdown (low — useful but not urgent)
  7. Trade timeline (low — visual, not diagnostic)
- Added rolling_metrics window as configurable (default 20, capped at
  min(20, n-5) to ensure at least 5 data points)
