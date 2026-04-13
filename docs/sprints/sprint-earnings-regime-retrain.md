# Implementation Spec: Earnings Filter + Regime Classifier + Retraining Cadence

**Date:** April 13, 2026
**Research Sources:**
- `docs/research/earnings-event-handling-pullback-strategy.md`
- `docs/research/regime-classifier-fix-3-regimes.md`
- `docs/research/optimal-retraining-cadence-lora.md`

**Strategy Decisions:** #33, #34, #35
**Ralph-looped:** 3 passes

---

## Strategy Decision #33: Earnings Exclusion Zone

**Rule:** Do not enter positions within 7 calendar days of earnings. Force-exit open positions 2 calendar days before earnings. 2-business-day cooldown after earnings.

**Rationale:** Median mega-cap earnings gaps (2-4%) routinely breach 2x ATR stops. No broker guarantees fill quality during gaps. PEAD is dead for large caps (Martineau 2022, Subrahmanyam 2025). The 7-day zone costs ~11% of the opportunity set — acceptable for eliminating the strategy's largest unmanageable tail risk.

## Strategy Decision #34: Monthly Retraining Cadence

**Rule:** Retrain monthly from original Qwen3-8B base (full reset), not weekly. Minimum 20 new examples accumulated before triggering. 6-week mandatory ceiling. Canary perplexity >8% for 2 consecutive weeks = forced retrain. Maintain FP16 master copy of merged model at all times.

**Rationale:** 5-10 weekly examples = 0.3-0.6% corpus increment, below noise floor. Monthly full reset eliminates NF4 quantization error accumulation and intruder dimensions. Same 1-hour GPU cost, dramatically better signal-to-noise.

## Strategy Decision #35: 3-Regime Classifier (Bull / Cautious / Bear)

**Rule:** Replace the current 7-label classifier with a 3-regime priority-ordered decision list. "Cautious" is the default (catch-all). Add VIX/VIX3M ratio. 5-day debounce. Kill "range" and "unknown".

**Rationale:** Current classifier leaves 75% of trading days as "unknown" due to conjunctive AND-chaining with no default. The "range" regime encodes a logical impossibility (VIX < 20 AND SPY 5-15% drawdown have r = -0.79). Academic consensus (Hamilton 1989, Ang & Bekaert 2002) supports 2-3 regimes for equity trading. Statistical Jump Models are the upgrade path.

---

## Sprint 1: Earnings Filter (CRITICAL — live risk)

> **Branch:** `feat/earnings-filter`
> **Priority:** CRITICAL — 3 open positions with no earnings protection
> **CC time:** 4-6 hours

### Task 1: Earnings proximity check in ranker

**File:** `src/ranking/ranker.py`

Before scoring any ticker in `rank_universe()`, query earnings_calendar for the next earnings date. If within 7 calendar days, mark the ticker as `earnings_blocked=True` and exclude from packet-worthy candidates. The ticker can still appear on the watchlist (useful for monitoring) but cannot generate a trade signal.

```python
def _check_earnings_proximity(ticker: str, db_path: str, days: int = 7) -> bool:
    """Return True if ticker has earnings within N calendar days."""
    from datetime import date, timedelta
    import sqlite3
    today = date.today()
    cutoff = (today + timedelta(days=days)).isoformat()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT earnings_date FROM earnings_calendar "
            "WHERE ticker = ? AND earnings_date >= ? AND earnings_date <= ? "
            "ORDER BY earnings_date LIMIT 1",
            (ticker, today.isoformat(), cutoff),
        ).fetchone()
    return row is not None
```

Add to `_score_ticker()` as early return: if earnings_blocked, return score with `qualification="earnings_blocked"`.

### Task 2: Force-exit for open positions approaching earnings

**File:** `src/shadow_trading/executor.py`

In `check_and_manage_open_trades()`, after the MFE/MAE update block and before the timeout check, add an earnings proximity audit:

```python
# Earnings force-exit: unconditional exit 2 calendar days before earnings
from datetime import date, timedelta
today = date.today()
cutoff = (today + timedelta(days=2)).isoformat()
with sqlite3.connect(db_path) as conn:
    earnings_row = conn.execute(
        "SELECT earnings_date FROM earnings_calendar "
        "WHERE ticker = ? AND earnings_date >= ? AND earnings_date <= ? "
        "ORDER BY earnings_date LIMIT 1",
        (ticker, today.isoformat(), cutoff),
    ).fetchone()
if earnings_row:
    logger.warning("[EXECUTOR] Force-exit %s: earnings on %s (within 2 days)",
                   ticker, earnings_row[0])
    # Trigger close with exit_reason = "earnings_protection"
    ...
```

Add `"earnings_protection"` as a valid exit_reason.

### Task 3: Post-earnings cooldown

**File:** `src/ranking/ranker.py`

In the same earnings check from Task 1, also check if the most recent past earnings date was within 2 business days. If so, block entry.

```python
# Also check recent past earnings (2 business day cooldown)
recent_cutoff = (today - timedelta(days=4)).isoformat()  # 4 calendar ≈ 2 business
recent = conn.execute(
    "SELECT earnings_date FROM earnings_calendar "
    "WHERE ticker = ? AND earnings_date >= ? AND earnings_date < ? "
    "ORDER BY earnings_date DESC LIMIT 1",
    (ticker, recent_cutoff, today.isoformat()),
).fetchone()
if recent:
    return True  # still in cooldown
```

### Task 4: Earnings calendar freshness check

**File:** `src/scheduler/watch.py` or `src/startup_checks.py`

Add a startup check: if earnings_calendar has no data within the next 30 days, log a WARNING. The overnight data collection should refresh the calendar daily via Finnhub. If the calendar is stale (>3 days old), the earnings filter is blind and should log this clearly.

### Task 5: Dashboard visibility

**File:** `frontend/src/pages/ShadowLedger.jsx` (or merged ledger)

On open position cards, show an earnings proximity indicator:
- 🟢 No earnings within 14 days
- 🟡 Earnings within 7-14 days (entering watchlist only territory)
- 🔴 Earnings within 7 days (would not have entered) or within 2 days (force-exit pending)

### Task 6: Tests

- Test: ticker with earnings in 3 days → blocked from entry
- Test: ticker with earnings in 10 days → allowed
- Test: open position with earnings tomorrow → force-exit triggered
- Test: ticker that reported yesterday → cooldown blocks entry
- Test: ticker that reported 3 business days ago → allowed
- Test: empty earnings_calendar → no blocking (fail-open, not fail-closed)

### Task 7: Update config and docs

Add to `settings.example.yaml`:
```yaml
earnings_filter:
  enabled: true
  entry_exclusion_days: 7      # calendar days before earnings
  force_exit_days: 2           # calendar days before earnings
  cooldown_business_days: 2    # business days after earnings
```

Update MASTER.md with SD#33. Update CHANGELOG.

---

## Sprint 2: Regime Classifier Fix

> **Branch:** `feat/regime-classifier-v2`
> **Priority:** HIGH — 75% of trades have unknown regime
> **CC time:** 3-4 hours

### Task 1: Rewrite classify_regime() as priority-ordered decision list

**File:** `src/features/regime.py`

Replace the current conjunctive classifier with a 3-regime priority-ordered system. Add VIX/VIX3M ratio as a feature.

```python
def classify_regime_v2(
    vix: float,
    spy_vs_200ma: float,
    breadth: float,
    vix_vix3m_ratio: float = 0.95,
) -> str:
    """3-regime priority-ordered classifier. No unknowns possible.

    Strategy Decision #35. Research: regime-classifier-fix-3-regimes.md
    """
    # Priority 1: Crisis / high-vol override
    if vix > 30 or vix_vix3m_ratio > 1.05:
        return "bear"

    # Priority 2: Structural bear
    if spy_vs_200ma < -0.03 and breadth < 45:
        return "bear"

    # Priority 3: Strong bull
    if spy_vs_200ma > 0.02 and breadth > 55 and vix < 22:
        return "bull"

    # Default: cautious (range-bound, mixed signals, transitions)
    return "cautious"
```

Keep the old function as `classify_regime_v1()` for comparison during validation.

### Task 2: Add 5-day debounce

**File:** `src/features/regime.py`

Add a `RegimeDebouncer` class that prevents regime changes for 5 days:

```python
class RegimeDebouncer:
    def __init__(self, min_hold_days: int = 5):
        self.current_regime = "bull"
        self.days_in_regime = 0
        self.min_hold_days = min_hold_days

    def update(self, raw_regime: str) -> str:
        if raw_regime != self.current_regime:
            if self.days_in_regime >= self.min_hold_days:
                self.current_regime = raw_regime
                self.days_in_regime = 1
            else:
                self.days_in_regime += 1
        else:
            self.days_in_regime += 1
        return self.current_regime
```

Persist debouncer state in traffic_light_state table or a new regime_state table.

### Task 3: Add VIX/VIX3M ratio to feature pipeline

**File:** `src/features/engine.py` or `src/data_collection/vix_collector.py`

The VIX term structure data is already collected (vix_term_structure table, 17 entries). Extract the VIX/VIX3M ratio from this data and pass it to the classifier. If VIX3M is unavailable, default to 0.95 (contango assumption).

### Task 4: Update REGIME_THRESHOLDS in ranker

**File:** `src/ranking/ranker.py`

Replace the 7-regime threshold map with 3 regimes:

```python
REGIME_THRESHOLDS = {
    "bull": {"packet_worthy": 40, "position_pct": 1.0},
    "cautious": {"packet_worthy": 55, "position_pct": 0.5},
    "bear": {"packet_worthy": 999, "position_pct": 0.0},  # no trades
}
```

### Task 5: Backfill regime on existing trades

Run a one-time backfill: apply the new classifier to all existing trades and update their `market_regime` field. This fixes the 43/57 "unknown" trades in the CTO report.

### Task 6: Hysteresis thresholds

Add asymmetric entry/exit thresholds to prevent flickering at boundaries:
- Enter bull: SPY > 2% above 200MA. Exit bull: SPY < 5% below 200MA.
- Enter bear: breadth < 45. Exit bear: breadth > 55.
- VIX crisis: enter at > 30, exit at < 24.

### Task 7: Tests

- Test: VIX 35 → bear regardless of other inputs
- Test: VIX/VIX3M 1.10 → bear (backwardation override)
- Test: SPY +5% above 200MA, breadth 65%, VIX 15 → bull
- Test: SPY -1%, breadth 50%, VIX 18 → cautious (default)
- Test: debouncer holds regime for 5 days despite raw signal change
- Test: no "unknown" in any output
- Test: hysteresis — bull doesn't flip to cautious on 1-day breadth dip

### Task 8: Update docs

Update MASTER.md with SD#35. Update CHANGELOG. Update the simulation engine to use the new classifier for regime labeling.

---

## Sprint 3: Retraining Cadence Configuration

> **Branch:** `fix/retrain-cadence`
> **Priority:** HIGH — auto-retrain fired incorrectly tonight
> **CC time:** 2-3 hours

### Task 1: Disable auto-retrain in watch loop

**File:** `src/scheduler/watch.py` or `src/training/trainer.py`

The auto-retrain triggered tonight because 1,782 new examples exceeded the 50-example threshold. Fix:
- Change the threshold from 50 to 500 new examples
- Add a config flag `training.auto_retrain.enabled: false` (default false)
- Add a config flag `training.auto_retrain.min_new_examples: 500`
- When disabled, log "Training skipped: auto_retrain disabled" instead of attempting to train

### Task 2: Fix PYTHONUTF8 for training

**File:** `training_data/train.py`

Add at the very top of the file (before any imports):
```python
import os
os.environ["PYTHONUTF8"] = "1"
```

This fixes the TRL gptoss.jinja UnicodeDecodeError on Windows.

### Task 3: Fix pnl_dollars type cast in model_monitor

**File:** `src/evaluation/model_monitor.py` line 48

```python
# Before:
wins = [p for p in pnl_dollars if p > 0]
# After:
wins = [float(p) for p in pnl_dollars if p is not None and float(p or 0) > 0]
losses = [float(p) for p in pnl_dollars if p is not None and float(p or 0) <= 0]
```

### Task 4: Add canary perplexity evaluation

**File:** `src/training/canary.py` (new or existing)

Create a function that evaluates the current model's perplexity on the canary set and logs the result. Schedule it for Wednesday evaluation in the watch loop:

```python
def evaluate_canary_perplexity(canary_path: str, model_name: str) -> float:
    """Compute average perplexity on the canary holdout set."""
    # Load canary examples
    # Run inference, compute cross-entropy loss
    # Return average perplexity
    ...
```

Store results in a new `canary_evaluations` table:
- date, model_version, avg_perplexity, baseline_perplexity, pct_change, triggered_retrain

### Task 5: Add retraining decision flowchart to config

**File:** `config/settings.example.yaml`

```yaml
training:
  auto_retrain:
    enabled: false
    min_new_examples: 500
  cadence:
    schedule: "monthly"           # monthly | triggered | disabled
    max_weeks_between_resets: 6
    canary_perplexity_threshold: 0.08  # 8% increase = trigger
    canary_persistence_weeks: 2        # must persist 2 weeks
    fp16_master_path: "training_data/merged_hf/"
```

### Task 6: Tests

- Test: auto-retrain disabled → training not triggered regardless of example count
- Test: auto-retrain enabled, 100 new examples → training not triggered (below 500)
- Test: auto-retrain enabled, 600 new examples → training triggered
- Test: pnl_dollars as string "123.45" → float comparison works
- Test: pnl_dollars as None → skipped without error

### Task 7: Update docs

Update MASTER.md with SD#34. Update CHANGELOG. Add the Saturday decision flowchart from the research doc to `docs/operations/`.

---

## Ralph Loop Findings

### Pass 1:
**Earnings filter fail-open vs fail-closed:** Task 6 specifies that empty earnings_calendar should NOT block trades (fail-open). This is correct — if the calendar isn't populated, we'd rather trade without earnings protection than shut down the entire system. But this means a stale earnings calendar is a silent failure. Task 4 (freshness check) is the mitigation — it surfaces the problem as a WARNING so Ryan can fix the data pipeline. Added explicit test case for this.

### Pass 2:
**Regime classifier and earnings filter interact.** If the regime is "bear" (no trades), the earnings filter is irrelevant. But if regime is "cautious" (half sizing), earnings proximity should still block entries — a half-sized position through earnings is still a gap risk. The earnings filter must run BEFORE regime-based sizing, not after. This is naturally handled if the earnings check is in the ranker (Task 1) since the ranker runs before the executor applies regime sizing. No code change needed, but the sprint prompt should clarify the execution order.

### Pass 3:
**The VIX/VIX3M ratio data source needs verification.** Task 3 of Sprint 2 assumes the vix_term_structure table contains VIX3M. Need to verify: does the current VIX data collector fetch VIX3M, or just the VIX spot level + futures curve? If VIX3M isn't available, the ratio defaults to 0.95 (contango assumption), which means the backwardation override (>1.05) never fires — effectively disabling one of the three crisis detectors. The sprint should include a subtask: verify vix_term_structure schema and add VIX3M collection if missing.

Also caught: **the force-exit in Task 2 of Sprint 1 needs to handle IB bracket orders.** Forcing an exit means canceling the existing bracket (stop + target) and placing a market sell. For IB trades, this requires calling `ib_broker.cancel_order()` on the child orders before placing the exit. For Alpaca trades, the existing `close_shadow_trade` path handles this. The sprint prompt should specify both broker paths.

Also: **the debouncer state needs to persist across watch loop restarts.** If the system restarts, the debouncer resets to "bull" with 0 days, potentially allowing an immediate regime change. Store `current_regime` and `days_in_regime` in the traffic_light_state table. The sprint should specify this.
