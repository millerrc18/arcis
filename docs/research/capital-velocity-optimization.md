# Capital Velocity Optimization: Design Spec

**Date:** April 12, 2026
**Author:** Claude (Opus 4.6), Ralph-looped 3x
**Status:** Spec only — implementation gated on 50-trade milestone
**Strategy Decision:** #32 (pending — number reserved)

---

## Problem Statement

With $100K paper capital and a 5-position max, capital is the binding constraint. Each day a position is open is a day that capital can't be deployed to a new setup. Two systems with identical per-trade edge but different average hold periods produce dramatically different returns:

| Metric | 7-day avg hold | 4-day avg hold | Delta |
|--------|---------------|---------------|-------|
| Trades per quarter | ~36 | ~63 | +75% |
| Annual Sharpe scaling | sqrt(144) = 12x | sqrt(252) = 15.9x | +32% |
| Capital turns per year | ~28x | ~49x | +75% |

The question is not WHETHER velocity matters (it does — Scaling Levers research confirmed `sqrt(N)` Sharpe scaling as the highest-impact operational lever). The question is HOW to increase velocity without sacrificing per-trade edge.

---

## Principle: Select Faster, Don't Exit Faster

**Anti-pattern (dangerous):** Tighten stops or reduce timeouts to force faster exits. This systematically cuts winners short while holding losers to the stop. The result is negative selection bias — reduced per-trade expectancy that outweighs the velocity gain.

**Correct pattern:** When multiple candidates compete for limited capital slots, prefer the setup most likely to resolve quickly. The exit mechanics remain unchanged (mechanical brackets, 8-day timeout, ATR-based stops). The velocity optimization happens at ENTRY SELECTION, not exit management.

---

## Architecture: 3 Components

### Component 1: Time-to-MFE Logging (Build Now)

Track the **day on which each trade reaches its maximum favorable excursion**. This is the single most important velocity datapoint — it tells you how long you need to hold to capture the trade's best outcome.

**Schema addition** — `shadow_trades`:
```python
ColumnDef("time_to_mfe_days", "INTEGER",
          description="Days from entry to maximum favorable excursion. "
          "Updated on every monitoring cycle. Final value set at close."),
ColumnDef("mfe_timestamp", "TEXT",
          description="Timestamp when MFE was last updated (peak P&L moment)."),
```

**Executor change** — in `check_and_manage_open_trades()`, where MFE is updated (~line 932):
```python
# Existing MFE update
if price_move > mfe:
    mfe = price_move
    # NEW: track when MFE peaked
    mfe_timestamp = datetime.now(ET).isoformat()

# In the update dict (~line 951):
update_fields = {
    "max_favorable_excursion": mfe,
    "max_adverse_excursion": mae,
    "time_to_mfe_days": (datetime.now(ET) - entry_dt).days if mfe == price_move else trade.get("time_to_mfe_days"),
    "mfe_timestamp": mfe_timestamp if mfe == price_move else trade.get("mfe_timestamp"),
}
```

**Why log now with 18 trades:** Every trade from now on builds the dataset. By the time you hit 50 trades, you'll have 32+ datapoints with `time_to_mfe_days` populated. That's enough for the hold period analysis.

### Component 2: Hold Period Analysis (Trigger at 50 Trades)

At 50 closed trades, compute the velocity profile:

```python
def analyze_hold_periods(db_path: str) -> dict:
    """Compute velocity metrics from closed trade history."""
    trades = query_closed_trades(db_path)  # quarantine-filtered

    # Core distributions
    hold_days = [t["duration_days"] for t in trades]
    mfe_days = [t["time_to_mfe_days"] for t in trades if t["time_to_mfe_days"]]

    winners = [t for t in trades if t["pnl_dollars"] > 0]
    losers = [t for t in trades if t["pnl_dollars"] <= 0]

    return {
        # Hold period
        "median_hold_all": median(hold_days),
        "median_hold_winners": median([t["duration_days"] for t in winners]),
        "median_hold_losers": median([t["duration_days"] for t in losers]),

        # Time to MFE (the key velocity metric)
        "median_time_to_mfe": median(mfe_days),
        "pct_mfe_by_day_3": len([d for d in mfe_days if d <= 3]) / len(mfe_days),
        "pct_mfe_by_day_5": len([d for d in mfe_days if d <= 5]) / len(mfe_days),

        # MFE capture efficiency
        "avg_mfe_capture_pct": mean([
            t["pnl_pct"] / t["max_favorable_excursion"] * 100
            for t in winners if t["max_favorable_excursion"] > 0
        ]),

        # Velocity-adjusted edge
        "edge_per_day_winners": mean([
            t["pnl_pct"] / max(t["duration_days"], 1)
            for t in winners
        ]),
        "edge_per_day_all": mean([
            t["pnl_pct"] / max(t["duration_days"], 1)
            for t in trades
        ]),

        # Decision inputs
        "recommended_timeout": _recommend_timeout(mfe_days, hold_days),
    }


def _recommend_timeout(mfe_days, hold_days) -> int:
    """Recommend optimal timeout based on MFE distribution.

    Rule: timeout = day by which 90% of MFE values have been reached.
    If 90% of trades hit their peak by day 5, there's no reason to
    hold past day 6-7 (adding 1-2 days buffer for exit execution).
    """
    if not mfe_days:
        return 8  # current default
    sorted_mfe = sorted(mfe_days)
    p90_idx = int(len(sorted_mfe) * 0.9)
    p90_day = sorted_mfe[p90_idx]
    return min(p90_day + 2, 8)  # buffer, but never exceed current timeout
```

**Decision matrix at 50 trades:**

| MFE Profile | Action | Rationale |
|-------------|--------|-----------|
| 90% MFE by day 3 | Reduce timeout to 5 | Capital freed 3 days earlier, only 10% upside lost |
| 90% MFE by day 5 | Reduce timeout to 7 | Modest improvement, low risk |
| 90% MFE by day 7 | Keep timeout at 8 | Current setting is already optimal |
| Bimodal (some day 2, some day 7) | Don't change timeout, investigate why | Two different trade populations — may need separate strategies |

### Component 3: Velocity-Aware Ranking (Trigger at 100+ Trades)

Only after sufficient data confirms which setup features predict faster resolution. Add a velocity score to the ranker that tiebreaks candidates competing for the same capital slot.

**Velocity predictors (hypothesis — validate with data):**

| Feature | Hypothesis | Why |
|---------|-----------|-----|
| ATR % of price (low) | Lower daily volatility → more orderly trend → faster target hit | Choppy stocks take longer to resolve |
| Pullback depth (moderate, -4% to -6%) | Not too shallow (no momentum), not too deep (trend damaged) | Sweet spot pullbacks resolve fastest |
| Volume ratio on setup day (>1.0x) | Institutional participation signals conviction | Smart money dips get bought faster |
| Distance to SMA20 (-1% to -3%) | Near natural support → bounce happens sooner | Far from support → more drifting before reversal |
| Regime (bull > recovery > bear) | Supportive backdrop accelerates trend resumption | Bear market pullbacks take longer to resolve |
| Days since 50-day high (<10) | Recent high → less ground to recover | Deep pullbacks from distant highs are slow |

**Implementation (NOT YET — wait for data):**

```python
def _velocity_score(features: dict, velocity_model: dict) -> float:
    """Score expected resolution speed. 0-15 points added to ranker.

    Only active when velocity_model has been fit from 100+ closed trades.
    Before that, returns 0 (no velocity influence on ranking).
    """
    if not velocity_model.get("calibrated"):
        return 0.0

    score = 0.0
    atr_pct = features.get("atr_pct_price", 0)
    pullback = features.get("pullback_depth_pct", 0)
    vol_ratio = features.get("volume_ratio_20d", 1.0)
    dist_sma20 = features.get("dist_to_sma20_pct", 0)

    # Each factor contributes 0-3 points based on empirical buckets
    # Buckets are set from the velocity_model (fitted at 100 trades)
    for factor, value in [
        ("atr_pct", atr_pct),
        ("pullback_depth", pullback),
        ("volume_ratio", vol_ratio),
        ("dist_sma20", dist_sma20),
    ]:
        buckets = velocity_model.get(f"{factor}_buckets", [])
        for bucket in buckets:
            if bucket["min"] <= value <= bucket["max"]:
                score += bucket["velocity_points"]
                break

    return min(score, 15)  # Cap at 15 points (out of 100 total score)
```

**Weight: 15 points max** out of 100 total ranker score. Velocity is a tiebreaker, not a primary signal. A high-velocity setup with weak technicals should NOT beat a strong setup with average velocity.

---

## What Changes When

| Milestone | Component | Action |
|-----------|-----------|--------|
| **Now (18 trades)** | time_to_mfe logging | Add columns + update logic. Zero risk, pure data collection. |
| **50 trades** | Hold period analysis | Run analysis, decide on timeout adjustment. One-time decision. |
| **100 trades** | Velocity model fitting | Fit velocity buckets from empirical data. Determine which features predict fast resolution. |
| **100 trades** | Velocity-aware ranking | Add velocity_score to ranker with 15-point max weight. Enable via config flag. |
| **200 trades** | Validate velocity | A/B compare: did velocity-ranked trades actually resolve faster? Does portfolio Sharpe improve? |

---

## What This Does NOT Change

- **Exit mechanics:** stops, targets, and timeout remain purely mechanical (Strategy Decision #18)
- **Position sizing:** equal weight, ATR-based, risk governor controlled
- **LLM role:** the LLM does not influence velocity scoring (FINSABER — no timing decisions)
- **Risk governor:** all 8 hard limits unchanged
- **Bracket structure:** 2.0x ATR stop, 2.0x ATR target, GTC

---

## Dashboard Integration

Add to the **Strategy page** (or a new "Velocity" tab):

1. **Hold period histogram** — distribution of duration_days for closed trades (winners vs losers overlaid)
2. **Time-to-MFE scatter** — x: trade number, y: days to MFE. Shows whether the system is getting faster over time.
3. **MFE capture efficiency** — what % of MFE does each trade capture at exit? (100% = exited at the peak, 50% = gave back half)
4. **Capital utilization timeline** — how many of 5 position slots are occupied each day? Shows idle capital.
5. **Velocity score vs actual resolution** — once velocity ranking is active, scatter plot of predicted vs actual hold days

---

## Ralph Loop Findings

### Pass 1:
The velocity score weight (15 points) was initially set to 20. Reduced to 15 because at 20 points, a mediocre setup (score 65) with perfect velocity features could outscore a strong setup (score 80) with average velocity. The velocity signal should break ties between 78 and 82, not override the difference between 65 and 80. The ranker's existing components sum to ~100 max (trend 30 + RS 25 + pullback 25 + SMA20 10 + volume 15 + options ±3 + regime adj). Adding 15 velocity points means the theoretical max becomes ~115, which is fine — the cap at 100 in `_score_ticker` would need to increase to 115 or the velocity points would need to reduce other weights proportionally. Recommend the latter: at 100+ trades, reduce volume weight from 15 to 10 and add 5 velocity points, keeping the total at 100.

### Pass 2:
The `time_to_mfe_days` logic had a subtle bug in my initial design. When MFE updates (new high), the code would SET `time_to_mfe_days` to the current day count. But it should only update when MFE INCREASES — if MFE stays flat (trade going sideways or adverse), the timestamp should NOT update. Fixed: the conditional `if mfe == price_move` captures this correctly — it only triggers when a new high water mark is set.

### Pass 3:
The `_recommend_timeout` function was using P90 of MFE days directly as the timeout. But MFE day != exit day. A trade might hit MFE on day 3 but you don't know it's MFE until the trade closes (could go higher on day 4). The timeout should be P90 of MFE + buffer (2 days), not P90 exact. Also added a floor: never recommend a timeout below the current value's P90 — only tighten, never loosen beyond the current 8-day setting. This prevents the recommendation from suggesting 12-day timeouts if a few outlier trades had late MFE peaks.

---

## Implementation Sprint

**Estimated CC time:** 2-3 hours (Component 1 only — logging)

Component 1 is the only piece to build now. Components 2 and 3 are gated on trade count milestones and should be separate sprints when the data is available.

```
Add time_to_mfe tracking to shadow_trades:
1. Schema: add time_to_mfe_days (INTEGER) and mfe_timestamp (TEXT) columns
2. Executor: in check_and_manage_open_trades MFE update block (~line 932),
   record the day count and timestamp when MFE increases
3. Journal: set final time_to_mfe_days at trade close
4. Dashboard: add hold period histogram and time-to-MFE scatter to Strategy page
5. Tests: verify time_to_mfe updates correctly on new highs, doesn't update on flat/declining
```
