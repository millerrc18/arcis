# Sprint: Research-Informed Feature Build + Reliability Completion

> **Context for CC:** Six deep research documents have been synthesized confirming the following system decisions:
> - **Strategy #2** = Mean Reversion (Phase 2, ρ=−0.35, Connors RSI(2), 65-75% WR)
> - **Strategy #3** = Evolved PEAD (Phase 3, composite earnings information system)
> - **RL method** = Dr. GRPO (`loss_type="dr_grpo"` in TRL GRPOTrainer), NOT REINFORCE++ (not in TRL), skip DPO entirely
> - **Regime detection** = Traffic Light (Phase 1 MVP), HMM upgrade (Phase 2-3)
> - **Council** = Vote-first protocol, structured JSON, parameter control within hard guardrails
> - **PEAD signals** as enrichment features for pullback adapter (Phase 2)
>
> The reliability sprint (`proto/upbeat-edison`) fixed 3 criticals, wired 4 orphan modules, connected 12 Telegram notifications, and eliminated 44+ silent exceptions. This sprint addresses what was missed AND adds the research-informed features.
>
> **Read these files FIRST before writing any code:**
> - `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`
> - `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`
> - `docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md`
> - `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md`
> - `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`
> - `docs/research/REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md`
> - `docs/research/Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md`
> - `docs/roadmap-additions-2026-03-28.md`
>
> **Run `python -m pytest tests/ -x -q` before starting. All tests must pass before and after each Part.**

---

## PART 0: Complete Remaining Reliability Fixes

These items were missed in the first reliability sprint.

### 0A. Wire `src/evaluation/hshs.py` into production

The HSHS (Halcyon System Health Score) module exists with tests but is never called by production code. Wire it into:

1. **Health Score dashboard page** — create or update the API endpoint `/api/health/score` that calls `compute_hshs()` and returns the 5-dimension scores + composite. The frontend Health page should display this.
2. **Weekly CTO report** — call `compute_hshs()` at the end of the CTO report generation and append the HSHS summary.
3. **Daily council input** — pass the current HSHS score to the council as part of the shared context so agents are aware of system health.

### 0B. Consolidate `src/scheduler/overnight.py`

`watch.py` implements overnight logic inline. `overnight.py` exists separately but is only imported by scripts. Pick ONE:
- **Option A (recommended):** Move overnight-specific logic from `watch.py` into `overnight.py` as clean functions. Import and call from `watch.py`. Delete the duplicated inline code.
- **Option B:** Delete `overnight.py` entirely and keep the inline implementation in `watch.py`.

Whichever you choose: remove the dead code path so there's exactly one implementation.

### 0C. Fix `notify_retrain_report` placeholder values

In `src/scheduler/watch.py`, the `notify_retrain_report` call passes placeholder values:
```python
new_this_week=counts.get("total", 0)  # WRONG — should be delta from last week
```
Fix: query the count of training examples created in the last 7 days and pass that as `new_this_week`. Also compute `new_paper` (examples from paper trades this week) and `prev_examples` (total minus new).

### 0D. Separate live trade monitoring from paper (Issue 1D)

In `src/shadow_trading/executor.py`, live trade exits currently depend on the paper trade monitoring loop. Add an independent monitoring path for live trades that fires even if paper trading is disabled:
```python
# After checking paper trades, also independently check live trades
live_trades = get_open_shadow_trades(db_path, source="live")
for trade in live_trades:
    # Same exit logic but independent of paper state
```

### 0E. Update CHANGELOG.md

Add entries for BOTH sprints:
1. The reliability sprint (criticals fixed, orphans wired, notifications connected, silent exceptions eliminated)
2. This feature sprint (everything below)

### 0F. Update docs/architecture.md

Reflect all changes from both sprints: new modules wired, deleted modules (broker.py), new tables, new API endpoints, updated pipeline flow.

---

## PART 1: Traffic Light Regime System

**Research source:** `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`

### 1A. Create `src/features/traffic_light.py`

Three indicators, each scored Green(2) / Yellow(1) / Red(0):

| Indicator | Green (2) | Yellow (1) | Red (0) |
|---|---|---|---|
| VIX level | <20 | 20-30 | >30 |
| S&P 500 vs 200-day MA | Above by >3% | Within 3% | Below |
| HY credit spread z-score (vs 1yr MA) | <0.5σ | 0.5-1.5σ | >1.5σ |

Total score 0-6. Mapping to position sizing multiplier:
- Score 5-6: multiplier = 1.0 (full sizing)
- Score 3-4: multiplier = 0.5 (half sizing)
- Score 0-2: multiplier = 0.1 (minimal/cash)

**Persistence filter:** Require 5+ consecutive days at the new level before changing the multiplier. This prevents whipsaw.

For credit spreads: use FRED series `BAMLH0A0HYM2` (ICE BofA US High Yield OAS). Check `macro_snapshots` table first (already collected nightly by macro_collector). If not available, fetch from FRED API.

```python
def compute_traffic_light(spy_data: pd.DataFrame, vix: float, 
                          credit_spread: float, credit_spread_1y_avg: float,
                          credit_spread_1y_std: float) -> dict:
    """Returns: {
        "vix_signal": "green"|"yellow"|"red",
        "vix_score": 0|1|2,
        "trend_signal": "green"|"yellow"|"red", 
        "trend_score": 0|1|2,
        "credit_signal": "green"|"yellow"|"red",
        "credit_score": 0|1|2,
        "total_score": 0-6,
        "sizing_multiplier": 0.1|0.5|1.0,
        "regime_label": "risk_on"|"caution"|"risk_off",
        "persistence_days": int,
        "changed": bool
    }"""
```

### 1B. Wire Traffic Light into scan pipeline

In `src/services/scan_service.py` → `run_scan()`:
1. Compute Traffic Light score after features are computed
2. Apply `sizing_multiplier` to the risk governor's position sizing (pass as parameter)
3. Log to `scan_metrics` table (new columns: `traffic_light_score INT`, `traffic_light_multiplier REAL`)
4. Include in Telegram scan notification
5. Include in pre-market brief
6. Pass to council as input data

### 1C. Wire into risk governor

In `src/risk/governor.py`, accept an optional `traffic_light_multiplier` parameter in `check_trade()`. Apply it to the base position size BEFORE all other checks. This is a hard override.

### 1D. Dashboard widget

Add a Traffic Light indicator to the Dashboard page — 3 colored circles (one per indicator) with the total score and current multiplier. Small, always-visible component. Show persistence days and whether a change is pending.

### 1E. Tests

- Test each indicator independently at boundary values
- Test persistence filter (score changes after exactly 5 days, not before)
- Test multiplier mapping
- Test integration with risk governor
- Test with missing data (credit spread not available — should default to Yellow)

---

## PART 2: AI Council Redesign — Vote-First Protocol

**Research source:** `docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md`

### 2A. Rewrite agent definitions in `src/council/agents.py`

Replace current 5 agents with research-defined analytical lenses:

| Agent | Framework | Core Question |
|---|---|---|
| **Tactical Operator** | Market microstructure, regime, order flow | What does current data tell us about next 1-5 days? |
| **Strategic Architect** | Portfolio theory, Kelly, phase gates | How should we allocate capital and attention? |
| **Red Team / Risk Sentinel** | Adversarial analysis, pre-mortem | What are we missing and what kills us? |
| **Innovation Engine** | R&D pipeline, ML experiments | What can we build that we couldn't before? |
| **Macro Navigator** | Macro-financial, regulatory | How is the world changing around us? |

Each agent's system prompt must include:
- Specific analytical framework (not just a persona label)
- Core question for this session type (daily/weekly/monthly)
- Evaluation criteria they apply
- Explicit instruction to produce **structured JSON output** (not prose)

Each agent's `gather_*_data()` function must pull REAL data from the database — not placeholder values.

### 2B. Rewrite protocol to vote-first

In `src/council/protocol.py`:

**Round 1 (always runs):** All 5 agents independently assess. Each produces structured JSON:
```json
{
  "direction": "bullish"|"neutral"|"bearish",
  "confidence": 0.0-1.0,
  "position_sizing_recommendation": 0.25-1.5,
  "cash_reserve_recommendation_pct": 10-50,
  "scan_aggressiveness": "conservative"|"normal"|"aggressive",
  "sector_tilts": {"prefer": ["Industrials", "Energy"], "avoid": ["Tech"]},
  "key_reasoning": "one paragraph maximum",
  "key_risk": "one sentence",
  "falsifiable_prediction": "SPY will close above 540 by April 5"
}
```

**Aggregation:** Confidence-weighted voting:
```
Score = Σ(vote × confidence × domain_weight) / Σ(confidence × domain_weight)
```
Where vote = +1 (bullish), 0 (neutral), -1 (bearish).

Domain weights (pre-set):
- Tactical Operator: 1.2 on daily, 0.8 on weekly
- Strategic Architect: 0.8 on daily, 1.3 on weekly
- Red Team: 1.0 always
- Innovation Engine: 0.6 on daily, 1.0 on monthly
- Macro Navigator: 0.9 on daily, 1.2 on weekly

**Decision thresholds:**
- Score > 0.6: full conviction
- Score 0.3-0.6: reduced size
- Score -0.3-0.3: no action
- Score < -0.3: opposite-direction signal (reduce exposure)

**Round 2 (conditional):** Only if <3/5 consensus on direction. Agents see Round 1 outputs. Track whether any agent flips — flag as potential sycophancy.

**Round 3 removed from daily sessions.** Keep available for weekly/monthly strategic sessions only.

### 2C. Structured session output

Add `result_json TEXT` column to `council_sessions` table. Store the complete JSON:
```json
{
  "session_meta": {"id": "...", "type": "daily", "cost_usd": 0.48, "duration_seconds": 45},
  "market_regime": {"classification": "TRANSITION", "traffic_light_score": 4, "vix": 25.3},
  "council_vote": {
    "aggregated_score": 0.42,
    "direction": "neutral",
    "vote_distribution": {"bullish": 2, "neutral": 1, "bearish": 2},
    "consensus_type": "3-2",
    "round2_triggered": true,
    "sycophancy_flag": false
  },
  "parameter_adjustments": {
    "position_sizing_multiplier": {"previous": 1.0, "new": 0.75, "within_bounds": true},
    "cash_reserve_target_pct": {"previous": 15, "new": 25, "within_bounds": true}
  },
  "dissent_record": [
    {"agent": "Red Team", "position": "bearish", "summary": "Credit spreads widening...", "falsifiable_trigger": "HY OAS > 400bps by April 10"}
  ],
  "calibration_tracking": [
    {"prediction": "SPY closes above 540 by April 5", "confidence": 0.65, "verification_date": "2026-04-05", "outcome": null}
  ]
}
```

### 2D. Parameter auto-application

After daily council, if all parameter adjustments are within bounds AND rate limiters pass:
- Apply `position_sizing_multiplier` to next scan's risk governor
- Apply `cash_reserve_target_pct` to buying power check
- Apply `scan_aggressiveness` to ranking thresholds
- Apply `sector_tilts` to sector preference scoring

**Hard controls (NEVER council-adjustable):** Max position 5%, portfolio DD halt -10%, daily loss -3%, max leverage 1.0x, VIX >40 automatic 50% reduction, kill switch.

**Rate limiters (hardcoded):**
- Max ±25% change per day on any single parameter
- Max ±50% cumulative weekly change
- If confidence <60% consensus: all params default to most conservative preset

### 2E. Calibration tracking table

```sql
CREATE TABLE IF NOT EXISTS council_calibrations (
    calibration_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT,
    prediction TEXT NOT NULL,
    prediction_confidence REAL NOT NULL,
    verification_date TEXT NOT NULL,
    actual_outcome TEXT,
    correct INTEGER,
    created_at TEXT NOT NULL
);
```

Daily job in watch loop: check calibrations whose `verification_date` has passed and `actual_outcome` is null. For SPY direction predictions, auto-verify against SPY close.

### 2F. Council dashboard update

Update `frontend/src/pages/Council.jsx`:
- 5 agent cards showing direction, confidence, key reasoning (color-coded: green=bullish, red=bearish, gray=neutral)
- Dissent highlighted with different border color
- Parameter adjustments as before/after table
- Consensus badge (5-0 unanimous, 4-1 strong, 3-2 split)
- Calibration scorecard (rolling 30-day accuracy per agent)
- Session cost displayed

### 2G. Tests

- Test vote aggregation with various vote distributions
- Test Round 2 trigger condition (<3/5 consensus)
- Test parameter rate limiters (±25% daily, ±50% weekly)
- Test sycophancy flag detection
- Test calibration auto-verification
- Test JSON schema validation of agent outputs

---

## PART 3: Implementation Shortfall Tracking

**Research source:** `docs/research/Complete_Research_Agenda__Validation_to_Scale_v2.md`

### 3A. Add columns to shadow_trades

```sql
ALTER TABLE shadow_trades ADD COLUMN signal_price REAL;
ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL;
```

`signal_price` = mid-price at the moment the scan identified the ticker as packet-worthy (before LLM, before order).

### 3B. Capture signal price in scan pipeline

In `src/services/scan_service.py`, when a candidate is identified as packet-worthy, record the current price from the features dict as `signal_price`. Pass through to `open_shadow_trade()`.

### 3C. Compute IS on fill

In `src/shadow_trading/executor.py`, after receiving the Alpaca fill:
```python
if signal_price and fill_price:
    is_bps = ((fill_price - signal_price) / signal_price) * 10000
    # Store in shadow_trades
```

If rolling 20-trade average IS exceeds 10 bps, fire a Telegram alert.

### 3D. Limit orders at the ask

For S&P 100 stocks during regular hours, use limit orders at the current ask price instead of market orders. Add config option:
```yaml
execution:
  order_type: "limit_at_ask"  # or "market"
  limit_timeout_seconds: 300  # cancel unfilled limit after 5 min
```

If the limit order doesn't fill within 5 minutes, cancel it and log as "missed opportunity" — do NOT convert to market order.

### 3E. Tests

- Test IS computation with known signal/fill prices
- Test limit order placement via mock Alpaca
- Test Telegram alert on rolling average threshold
- Test config option switching between market and limit

---

## PART 4: PEAD Enrichment Features for Pullback Adapter

**Research source:** `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`

These are NOT a separate strategy — they're additional enrichment features added to the pullback strategy's input prompt to improve trade quality near earnings events.

### 4A. Create `src/data_enrichment/earnings_signals.py`

Compute the following for each ticker during enrichment:

1. **Earnings surprise magnitude:** from Finnhub `company_earnings()` — `actual - estimate`. Normalize by stock price to get surprise as percentage.
2. **Revenue-EPS concordance:** did both revenue AND EPS beat/miss? Concordant surprises (both beat or both miss) produce stronger drift than mixed.
3. **Analyst revision velocity:** rate of estimate changes in the 30 days pre-earnings. Fast upward revisions + subsequent beat = strongest signal.
4. **Recommendation inconsistency:** surprise direction vs consensus analyst rating. A positive surprise on a "Sell"-rated stock is 2.5-4.5× stronger signal (McCarthy 2025).
5. **Earnings proximity:** days to next earnings announcement (already partially computed — ensure it's in the enrichment output).

```python
def compute_earnings_signals(ticker: str, db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Returns: {
        "earnings_proximity_days": int|None,
        "last_surprise_pct": float|None,
        "last_revenue_eps_concordant": bool|None,
        "analyst_revision_velocity_30d": float|None,  # positive = upward revisions
        "recommendation_inconsistency": bool|None,  # surprise opposite to consensus
        "earnings_signal_strength": "strong"|"moderate"|"weak"|"none"
    }"""
```

### 4B. Add to enrichment pipeline

In `src/data_enrichment/enricher.py`, call `compute_earnings_signals()` for each ticker and merge into the enriched features dict.

### 4C. Add to LLM prompt template

In the enrichment prompt template, add a new section:
```
EARNINGS CONTEXT for {TICKER} as of {DATE}:
- Days to next earnings: {N} ({DATE})
- Last earnings surprise: {+/-X%} ({beat/miss} on {DATE})
- Revenue-EPS concordance: {concordant/mixed}
- Analyst revision trend (30d): {rising/falling/stable}
- Recommendation vs surprise: {consistent/inconsistent}
- Earnings signal strength: {strong/moderate/weak/none}
```

Include this section ONLY if earnings proximity ≤ 30 days or last earnings was ≤ 10 days ago. Otherwise omit (keeps the prompt shorter for non-earnings-adjacent trades).

### 4D. Tests

- Test earnings signal computation with mock Finnhub data
- Test concordance logic (both beat, both miss, mixed)
- Test revision velocity with time series of estimates
- Test recommendation inconsistency detection
- Test prompt template conditional inclusion (within 30 days vs not)

---

## PART 5: Validation Dashboard Page

CC built `src/evaluation/system_validator.py` (943 lines, 50+ checks) in the reliability sprint. Now build the frontend.

### 5A. Verify API endpoint exists

Check that `/api/system/validation` is registered and returns the validator's JSON output. If not, add:
```python
@app.get("/api/system/validation")
async def get_validation():
    from src.evaluation.system_validator import run_full_validation
    result = run_full_validation()
    return result
```

Cache the result for 5 minutes (validations are expensive).

### 5B. Create `frontend/src/pages/Validation.jsx`

CC created this file in the reliability sprint. Verify it:
- Shows summary bar: X passed / Y warnings / Z failed with overall status badge
- Category cards (8 categories): database, trading, training, API, collectors, notifications, scheduler, LLM
- Each card expandable to show individual checks with pass/warn/fail icons
- "Run Validation" button triggers fresh check
- Last validation timestamp
- Auto-runs on page load

### 5C. Add to navigation

Ensure Validation page is in `frontend/src/App.jsx` routes and `frontend/src/components/Layout.jsx` navigation.

### 5D. Daily auto-run with Telegram

In watch.py, after 4:30 PM daily validation:
- If all pass: no notification
- If warnings: summary notification
- If any failures: detailed notification listing each failure

Store results in `validation_results` table (verify CC created this).

---

## PART 6: HSHS Dashboard Page

### 6A. Create or update Health Score section

The Health page should display the 5-dimension HSHS score:
- **Performance** (P): Sharpe, max drawdown
- **Model Quality** (M): rubric score, calibration, decay rate
- **Data Asset** (D): proprietary %, volume, freshness, dimensions
- **Flywheel Velocity** (F): cycle time, growth rate
- **Competitive Defensibility** (C): time-to-replicate, integration depth

Display as a radar chart (5 axes) with the composite geometric mean score.

Show phase-dependent weights:
- Current phase (months 1-6): Data=0.35, Model=0.25, Performance=0.10

### 6B. API endpoint

```python
@app.get("/api/health/hshs")
async def get_hshs():
    from src.evaluation.hshs import compute_hshs
    return compute_hshs()
```

---

## PART 7: Documentation & Roadmap Updates (MANDATORY)

### 7A. CHANGELOG.md

Add entries for:
1. Reliability sprint (already merged): criticals fixed, orphans wired, notifications connected
2. This feature sprint: Traffic Light, Council redesign, IS tracking, PEAD enrichment, Validation page, HSHS page

### 7B. docs/architecture.md

Update to reflect:
- Traffic Light module and its integration points
- Council redesign (vote-first protocol, structured JSON, parameter control)
- Implementation Shortfall columns and limit order system
- PEAD enrichment module
- Validation page and validator
- HSHS dashboard
- All deleted modules (broker.py)
- All new tables/columns

### 7C. AGENTS.md

Update ALL counts. Run verification commands:
```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "LOC:" && find src -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "API routes:" && grep -c "@app\.\|@router\." src/api/cloud_app.py src/api/routes/*.py 2>/dev/null
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md | wc -l
```

### 7D. Roadmap documents

Update `docs/roadmap.md` and `docs/roadmap-complete.md`:
- Strategy #2 = Mean Reversion (not breakout, not PEAD)
- Strategy #3 = Evolved PEAD (composite earnings info system)
- RL method = Dr. GRPO (not REINFORCE++, not standard GRPO)
- PEAD enrichment features added to Phase 2 roadmap
- Traffic Light regime system built (Phase 1)

### 7E. Research docs on dashboard

Add ALL new research documents to the docs list in `src/api/routes/docs.py` and `src/data_collection/docs_collector.py`:
- Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md
- PEAD_for_SP100__The_Drift_Evolved.md
- Strategy_2_Selection__Mean_Reversion_Wins.md
- REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md
- Complete_Research_Agenda__Validation_to_Scale_v2.md
- Quantitative_Regime_Detection_for_Halcyon_Lab.md

Total research docs should now be 35+.

---

## Execution Order

**Phase A — Remaining reliability (do first):**
1. 0A: Wire hshs.py
2. 0B: Consolidate overnight.py
3. 0C: Fix retrain report values
4. 0D: Separate live trade monitoring

**Phase B — Core features:**
5. 1A-1C: Traffic Light system (feature, scan, governor)
6. 2A-2D: Council redesign (agents, protocol, output, params)
7. 3A-3D: Implementation Shortfall tracking

**Phase C — Enrichment and dashboard:**
8. 4A-4C: PEAD enrichment features
9. 5A-5D: Validation dashboard (verify/complete CC's work)
10. 6A-6B: HSHS dashboard

**Phase D — Documentation (MANDATORY):**
11. 2E-2F: Council calibration + dashboard
12. All Part 7: CHANGELOG, architecture.md, AGENTS.md, roadmap, docs list

---

## Acceptance Criteria

### Reliability (Part 0):
- [ ] hshs.py called by at least 3 production code paths
- [ ] overnight.py: exactly ONE implementation exists (not two)
- [ ] notify_retrain_report shows accurate week-over-week delta
- [ ] Live trade monitoring fires independently of paper trade state

### Traffic Light (Part 1):
- [ ] `traffic_light.py` computes score from VIX, 200-DMA, credit spreads
- [ ] 5-day persistence filter prevents whipsaw
- [ ] Multiplier applied in risk governor BEFORE position sizing
- [ ] Score logged to scan_metrics, shown in Telegram + dashboard

### Council (Part 2):
- [ ] 5 new agent definitions with distinct analytical frameworks
- [ ] Round 1 always runs, Round 2 only on <3/5 consensus
- [ ] Structured JSON stored in council_sessions.result_json
- [ ] Parameter adjustments auto-apply within bounds with rate limiters
- [ ] Calibration table tracks predictions with auto-verification
- [ ] Dashboard shows vote cards, dissent, param changes, scorecard
- [ ] Session cost stays ≤$0.50 for daily

### Implementation Shortfall (Part 3):
- [ ] signal_price captured at scan time for every packet-worthy ticker
- [ ] IS computed in bps on every fill
- [ ] Telegram alert if rolling 20-trade IS avg >10 bps
- [ ] Limit-at-ask orders default for paper and live

### PEAD Enrichment (Part 4):
- [ ] 5 earnings signals computed for every ticker during enrichment
- [ ] Signals included in LLM prompt ONLY when earnings-adjacent (≤30 days)
- [ ] Tests verify all signal computations

### Dashboard (Parts 5-6):
- [ ] Validation page shows 50+ checks across 8 categories
- [ ] HSHS page shows 5-dimension radar chart with composite score
- [ ] Both pages accessible from navigation

### Documentation (Part 7):
- [ ] CHANGELOG reflects both sprints
- [ ] architecture.md reflects all new modules, tables, endpoints
- [ ] AGENTS.md counts match code reality (verified by commands)
- [ ] Roadmap docs reflect confirmed strategy decisions
- [ ] All 6 new research docs in dashboard docs list
- [ ] All tests pass, `npm run build` succeeds

---

## Sprint Documentation Checklist

> **This section is MANDATORY. Do not skip any Tier 1 items.**

### Tier 1 (every sprint — MANDATORY):
- [ ] AGENTS.md — all counts verified against code
- [ ] CHANGELOG.md — sprint entry added
- [ ] docs/architecture.md — all new modules/tables/endpoints documented
- [ ] README.md — updated if major features changed

### Tier 2 (when applicable):
- [ ] docs/cli-reference.md — any new CLI commands
- [ ] docs/telegram-commands.md — any new notification types
- [ ] config/settings.example.yaml — any new config keys (execution.order_type, execution.limit_timeout_seconds)
- [ ] frontend/src/api.js — any new API endpoints
- [ ] render.yaml — any new env vars
- [ ] docs/roadmap.md — strategy/phase decisions updated
- [ ] scripts/render_migrate.py — any new Postgres tables/columns

### Verification (run at end):
```bash
find src -name "*.py" ! -path "*__pycache__*" | wc -l
find src -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```
