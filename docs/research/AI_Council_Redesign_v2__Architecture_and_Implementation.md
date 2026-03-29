# AI Council Redesign — Architecture Document
# Collaborative design between Ryan and Claude · March 28, 2026

> **Starting fresh.** The old council (5 agents, 3 mandatory rounds, prose output,
> no parameter control, no calibration) is being replaced entirely.
>
> Bounded by research: `docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md`
> Key finding: NeurIPS 2025 showed majority voting > multi-agent debate for factual tasks.
> Our adaptation: vote-first with conditional deliberation only when consensus fails.

---

## 1. AGENT DEFINITIONS

### Design principles
- Each agent is an **analytical lens**, not a persona
- Each has a **distinct framework** that produces genuinely different analysis
- Each queries **real data** from the database (no placeholder functions)
- Each outputs **structured JSON** (not prose — prose goes in key_reasoning field)
- 5 agents = odd number for clean majority votes

### The five agents

| Agent | Framework | Core Question | Data Sources |
|---|---|---|---|
| **Tactical Operator** | Market microstructure, regime detection, short-term price action | "What does the data say about the next 1-5 days?" | VIX + term structure, Traffic Light score, recent scan results, open position P&L, ATR, volume profiles |
| **Strategic Architect** | Portfolio theory, Kelly criterion, phase gates, resource allocation | "Are we on track, and how should we allocate?" | Phase gate progress (trade count vs 50-trade target), capital levels, HSHS score, strategy performance metrics, model version history |
| **Red Team** | Adversarial pre-mortem, tail risk, competitive threats | "What are we missing, and what kills us?" | Current drawdown, sector concentration, position correlation, alpha decay indicators, model health (fallback rate, quality scores), worst-case scenarios |
| **Innovation Engine** | R&D pipeline, ML experiments, technical feasibility | "What should we build or fix next?" | Training data trends (volume, quality scores, source mix), template fallback rate, feature importance drift, research digest summaries |
| **Macro Navigator** | Macro-financial, regulatory, structural | "How is the world changing around us?" | FRED macro data (34 series from macro_snapshots), regime history, sector rotation metrics, credit conditions, earnings calendar density |

### Output schema (every agent, every session)

```json
{
  "agent": "tactical_operator",
  "direction": "bullish",         // "bullish" | "neutral" | "bearish"
  "confidence": 0.72,             // 0.0 to 1.0 (continuous, NOT 1-10 integer)
  "parameters": {
    "position_sizing_multiplier": 0.85,   // 0.25 to 1.5
    "cash_reserve_target_pct": 20,        // 10 to 50
    "scan_aggressiveness": "normal"       // "conservative" | "normal" | "aggressive"
  },
  "sector_tilts": {
    "prefer": ["Industrials", "Energy"],
    "avoid": ["Technology"]
  },
  "key_reasoning": "VIX term structure in backwardation suggests...", // one paragraph max
  "key_risk": "Credit spreads widening toward 1.5σ threshold",       // one sentence
  "falsifiable_prediction": {
    "claim": "SPY closes above 540 by April 5",
    "confidence": 0.65,
    "verification_date": "2026-04-05"
  }
}
```

**DECIDED:** Portfolio level only for Phase 1. Ticker-level added Phase 2.

---

## 2. VOTE-FIRST PROTOCOL

### Flow

```
Round 1 (ALWAYS): All 5 agents assess independently
    ↓
Aggregate: Confidence-weighted vote with domain weights
    ↓
Consensus? (≥3/5 agree on direction)
    ├── YES → Apply parameters, log, done (1 round = ~$0.30)
    └── NO → Round 2: Agents see others' views, can update
              ↓
              Re-aggregate → Apply regardless (2 rounds = ~$0.50)
              Flag if any agent flipped (sycophancy detector)
```

### Aggregation formula

```
Score = Σ(vote_i × confidence_i × domain_weight_i) / Σ(confidence_i × domain_weight_i)
```

Where `vote = +1 (bullish), 0 (neutral), -1 (bearish)`.

### Domain weights by session type

| Agent | Daily | Weekly | Monthly |
|---|---|---|---|
| Tactical Operator | 1.2 | 0.8 | 0.6 |
| Strategic Architect | 0.8 | 1.3 | 1.5 |
| Red Team | 1.0 | 1.0 | 1.0 |
| Innovation Engine | 0.6 | 1.0 | 1.2 |
| Macro Navigator | 0.9 | 1.2 | 1.3 |

Rationale: Tactical gets more weight for short-term daily decisions. Strategic and 
Macro dominate longer-horizon weekly/monthly sessions. Red Team is always 1.0 — 
adversarial analysis is always equally important. Innovation is weighted lower daily 
(no R&D decisions needed) but higher monthly (strategic planning).

### Decision thresholds

| Aggregated Score | Interpretation | Action |
|---|---|---|
| > 0.5 | Strong bullish consensus | Full conviction, may increase sizing |
| 0.2 to 0.5 | Lean bullish | Normal sizing |
| -0.2 to 0.2 | Neutral / split | Default parameters, no adjustments |
| -0.5 to -0.2 | Lean bearish | Reduce exposure |
| < -0.5 | Strong bearish consensus | Significant reduction, raise cash |

**DECIDED:** Hardcoded. To change: edit `DECISION_THRESHOLDS` in `protocol.py`.

---

## 3. PARAMETER AUTO-APPLICATION

### Controllable parameters (council CAN adjust)

| Parameter | Range | Default | What It Does |
|---|---|---|---|
| `position_sizing_multiplier` | 0.25 - 1.5 | 1.0 | Scales all new position sizes |
| `cash_reserve_target_pct` | 10 - 50 | 15 | Target cash allocation |
| `scan_aggressiveness` | conservative/normal/aggressive | normal | Maps to ranking threshold adjustments |

### Hard controls (council CANNOT adjust — ever)

- Max position: 5% of equity
- Portfolio drawdown halt: -10%
- Daily loss halt: -3%
- Max leverage: 1.0x (no leverage)
- VIX > 40: automatic 50% reduction (Traffic Light handles this)
- Kill switch: manual override always available

### Rate limiters

| Constraint | Limit |
|---|---|
| Max daily change per parameter | ±25% of current value |
| Max weekly cumulative change | ±50% of baseline |
| Low-confidence override | If aggregated confidence < 0.4, all params stay at default |
| Emergency reset | If 3 consecutive sessions disagree on direction, reset all to defaults |

### Scan aggressiveness mapping

| Setting | Ranking min_score | Description |
|---|---|---|
| conservative | +10 above default | Fewer candidates, only strongest setups |
| normal | default | Standard threshold |
| aggressive | -10 below default | More candidates, weaker setups included |

---

## 4. VALUE TRACKING (the counterfactual)

This is how we measure whether the council creates or destroys value.

### Council parameter log table

```sql
CREATE TABLE IF NOT EXISTS council_parameter_log (
    log_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,      -- 'position_sizing_multiplier', etc.
    default_value REAL NOT NULL,       -- what system would use without council
    council_value REAL NOT NULL,       -- what council recommended
    applied_value REAL NOT NULL,       -- what was actually applied (after rate limiters)
    rate_limited INTEGER DEFAULT 0,    -- 1 if rate limiter clipped the recommendation
    attribution_start TEXT NOT NULL,   -- when this parameter became active
    attribution_end TEXT,              -- when next council session changed it
    trades_during_window INTEGER,      -- count of trades opened while this was active
    pnl_during_window REAL,           -- sum P&L of those trades
    counterfactual_pnl REAL,          -- estimated P&L if default sizing had been used
    value_added_dollars REAL,          -- pnl_during_window - counterfactual_pnl
    created_at TEXT NOT NULL
);
```

### How counterfactual P&L works

For `position_sizing_multiplier`:
- Actual: trade opened at $500 (because council set mult=0.5, default would be $1000)
- Trade returns +3%
- Actual P&L: $500 × 3% = $15
- Counterfactual P&L: $1000 × 3% = $30
- Value added: $15 - $30 = -$15 (council cost us $15 by sizing down)

BUT if the trade lost 3%:
- Actual P&L: -$15
- Counterfactual P&L: -$30
- Value added: +$15 (council saved us $15)

This is straightforward for sizing multiplier. For scan aggressiveness, 
we'd need to track "which trades would NOT have been taken at conservative 
threshold" — more complex but doable by logging the score at entry.

### Weekly attribution report

Every Saturday (before retrain), compute:
1. Total trades influenced by council adjustments
2. Actual P&L vs counterfactual P&L
3. Rolling 30-day council value-added
4. Per-parameter value attribution
5. Per-agent calibration accuracy (falsifiable predictions checked)

Include in CTO report and Telegram weekly summary.

**DECIDED:** Alert at 8 weeks negative, auto-tighten at 12 weeks, auto-restore after 4 weeks positive.

---

## 5. CALIBRATION TRACKING

### Falsifiable predictions

Every agent produces one falsifiable prediction per session. These are stored 
and auto-verified:

```sql
CREATE TABLE IF NOT EXISTS council_calibrations (
    calibration_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    claim TEXT NOT NULL,
    confidence REAL NOT NULL,
    verification_date TEXT NOT NULL,
    actual_outcome TEXT,              -- filled on verification
    correct INTEGER,                  -- 1 or 0
    created_at TEXT NOT NULL
);
```

### Auto-verification

For SPY direction predictions:
- Claim: "SPY closes above 540 by April 5"
- On April 5: check SPY close price, update `actual_outcome` and `correct`

For sector predictions:
- Claim: "Energy outperforms Technology over next 5 trading days"
- Compute sector returns, verify

For regime predictions:
- Claim: "VIX stays below 25 through April 10"
- Check daily VIX, verify

Complex claims (qualitative, multi-condition) get flagged for manual verification 
during Sunday ritual.

### Agent authority weighting

After 20+ verified predictions per agent, compute:
- ECE (Expected Calibration Error) per agent
- Accuracy by confidence bucket (low/medium/high)
- Agent whose predictions add most information

If an agent's calibration is consistently poor (ECE > 0.3 after 50 predictions), 
reduce its domain weight by 20%. If it improves, restore. This creates earned 
authority — agents that predict well get more influence.

---

## 6. SESSION STORAGE

### Structured session output

Add `result_json TEXT` column to `council_sessions`. Store the complete 
JSON for every session:

```json
{
  "session_meta": {
    "session_id": "uuid",
    "session_type": "daily",
    "cost_usd": 0.31,
    "rounds_completed": 1,
    "duration_seconds": 38
  },
  "market_context": {
    "traffic_light": {"score": 4, "multiplier": 0.5, "regime": "caution"},
    "vix": 25.3,
    "spy_vs_200dma_pct": 1.2,
    "hshs_score": 42.5
  },
  "votes": {
    "aggregated_score": 0.42,
    "direction": "bullish",
    "vote_distribution": {"bullish": 3, "neutral": 1, "bearish": 1},
    "consensus_reached": true,
    "round2_triggered": false,
    "sycophancy_flags": []
  },
  "parameter_adjustments": {
    "position_sizing_multiplier": {
      "previous": 1.0,
      "recommended": 0.85,
      "applied": 0.85,
      "rate_limited": false,
      "within_bounds": true
    },
    "cash_reserve_target_pct": {
      "previous": 15,
      "recommended": 20,
      "applied": 20,
      "rate_limited": false,
      "within_bounds": true
    },
    "scan_aggressiveness": {
      "previous": "normal",
      "recommended": "normal",
      "applied": "normal"
    }
  },
  "agent_assessments": [
    {
      "agent": "tactical_operator",
      "direction": "bullish",
      "confidence": 0.72,
      "key_reasoning": "...",
      "key_risk": "...",
      "falsifiable_prediction": {
        "claim": "...",
        "confidence": 0.65,
        "verification_date": "2026-04-05"
      }
    }
    // ... 4 more agents
  ],
  "dissent": [
    {
      "agent": "red_team",
      "direction": "bearish",
      "confidence": 0.68,
      "key_reasoning": "Credit spreads widening..."
    }
  ]
}
```

---

## 7. DASHBOARD DISPLAY

### Council page updates

Current Council.jsx (324 lines) shows session history and agent votes. Redesign:

1. **Current State Banner**: Traffic Light + council direction + active parameter adjustments
2. **Vote Visualization**: 5 agent cards, each with direction color (green/gray/red), confidence bar, one-line reasoning. Dissent highlighted with orange border.
3. **Consensus Badge**: "5-0 Unanimous" / "4-1 Strong" / "3-2 Split" / "No Consensus"
4. **Parameter Changes**: Before/after table for each adjusted parameter
5. **Value Attribution**: Rolling 30-day chart showing cumulative council value-added in dollars
6. **Calibration Scorecard**: Per-agent accuracy with confidence intervals
7. **Session History**: Expandable list of recent sessions with key metrics

---

## 8. IMPLEMENTATION PLAN

### Files to create:
- `src/council/agents.py` — complete rewrite (5 new agents + 5 data functions)
- `src/council/protocol.py` — complete rewrite (vote-first, aggregation, conditional R2)
- `src/council/engine.py` — significant modification (new session flow, JSON storage)
- `src/council/value_tracker.py` — NEW (counterfactual computation, attribution)

### Files to modify:
- `src/scheduler/watch.py` — update council session call, add value tracking job
- `src/api/cloud_app.py` — update council API endpoints for new JSON structure
- `frontend/src/pages/Council.jsx` — significant update for new display
- `frontend/src/api.js` — new API functions

### Database changes:
- ALTER council_sessions ADD COLUMN result_json TEXT
- CREATE TABLE council_parameter_log
- CREATE TABLE council_calibrations
- CREATE TABLE council_parameter_state (current active parameters)

### Tests:
- `tests/test_council_agents.py` — each agent produces valid JSON
- `tests/test_council_protocol.py` — aggregation, consensus detection, rate limiters
- `tests/test_council_value_tracker.py` — counterfactual computation, attribution
- `tests/test_council_calibration.py` — auto-verification logic

---

## DECISIONS (FINALIZED March 28, 2026)

1. **Agent ticker recommendations:** Portfolio/regime level only for Phase 1. Ticker-level recommendations added in Phase 2 when calibration data exists. **→ TODO on roadmap.**
2. **Score thresholds:** Hardcoded. Documented in this file with instructions for changing if needed. To modify: edit the `DECISION_THRESHOLDS` dict in `src/council/protocol.py` — the thresholds are co-located in a single constant, not scattered.
3. **Negative value response:** Alert after 8 weeks negative. Auto-tighten bounds (reduce max parameter adjustment from ±25% to ±10%) after 12 consecutive weeks negative. Auto-restore after 4 consecutive weeks positive.
4. **Per-agent value tracking:** YES from day 1. Track BOTH holistic council value-added AND per-agent attribution. Per-agent tracking uses the `agent_name` field in `council_parameter_log` — each parameter adjustment is attributed to the agent whose recommendation drove it (or "consensus" if aggregated).
5. **Session frequency:** Daily tactical + weekly strategic from launch. Monthly planning sessions added after 3 months of calibration data. On-demand "strategic" sessions can be triggered manually via CLI or Telegram with a custom question.

### On-Demand Strategic Sessions

The council can deliberate on any business-level question — hardware purchases, new desk proposals, scaling decisions, fund formation timing, hiring, etc. Trigger via:

```
python -m src.main council --type strategic --question "Should we buy the RTX 3090 now or wait until revenue starts?"
```

Or via Telegram:
```
/council Should we add a mean reversion desk now or wait for the 50-trade gate?
```

**How it works:** The custom question replaces the default "daily tactical briefing" user message. Each agent still receives its specialist data AND applies its analytical framework to the question. The vote-first protocol runs identically — direction becomes "proceed" (bullish) / "wait" (neutral) / "don't do this" (bearish).

**Agent lenses on business questions:**
- **Tactical Operator:** How does this affect current trading operations? Timeline impact?
- **Strategic Architect:** ROI analysis. Phase gate alignment. Resource allocation tradeoff.
- **Red Team:** What could go wrong? What are we not considering? Opportunity cost?
- **Innovation Engine:** Technical feasibility. What does this unlock or block? Build vs buy?
- **Macro Navigator:** External factors. Market timing. Regulatory implications.

**Stored identically** in council_sessions with `session_type = "strategic"` and `trigger_reason = "<the question>"`. Value tracking still applies if the decision involves parameter changes. Calibration tracking applies if agents make falsifiable predictions about the outcome.

**Cost:** Same as a daily session (~$0.30-0.50 per strategic question). No limit on frequency, but the rate limiter prevents parameter changes from accumulating faster than ±50%/week even across multiple sessions.
