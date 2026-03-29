# Designing the Halcyon Lab AI Council: A 5-Agent Strategic Brain for Autonomous Quant Trading

> Deep research report — Multi-agent deliberation, council architecture, parameter adjustment, failure modes, scaling, and competitive moats

## Key Finding

The council should function as a confidence-weighted voting system with domain-specific believability scores, not a discussion forum. NeurIPS 2025: majority voting accounts for most performance gains attributed to multi-agent debate. The council's value comes from ensembling five independent analytical lenses, not from agents persuading each other.

Three structural changes needed:
1. Force quantitative outputs with specific decision boundaries
2. Track whether recommendations actually change behavior vs defaulting same call every session
3. Implement calibration scorecard comparing stated confidence to actual outcomes

## The Five Agents: Maximizing Cognitive Diversity

Hong & Page diversity prediction theorem (2004, PNAS): **Collective Error = Average Individual Error − Prediction Diversity.** Group accuracy improves through reducing individual errors AND increasing prediction diversity.

2024 study testing 162 personas across 6 LLM families: most personas had no significant effect on accuracy. Expert personas actually damaged accuracy on factual benchmarks (68.0% vs 71.6% baseline). However, personas combined with **different analytical frameworks, different data emphasis, and different evaluation criteria** do create meaningful diversity.

Tetlock's superforecasting: teams using "dragonfly eye" approach (each lens captures different view) produce extraordinary combined acuity. Nemeth (2001): **authentic dissent from genuinely different analysis outperforms devil's advocacy (assigned contrarianism).**

### Agent 1 — TACTICAL OPERATOR (market microstructure lens)
- Framework: Quantitative/technical analysis — regime detection, volatility surfaces, momentum/mean-reversion, order flow
- Method: Bottom-up from market data to position sizing and risk limits
- Time horizon: Hours to weeks
- Core question: "What does current price action, volatility, and microstructure tell us about next 1-5 trading days?"
- Evaluation criteria: Sharpe ratio, max drawdown, signal-to-noise ratio
- Reasons exclusively from data patterns, never narratives or macro stories
- Inputs: VIX level/percentile, ATR readings, credit spread data, overnight moves

### Agent 2 — STRATEGIC ARCHITECT (capital allocation lens)
- Framework: Portfolio theory, Kelly criterion, phase-gate methodology, resource allocation under uncertainty
- Method: Top-down from business objectives to roadmap and milestones
- Time horizon: 1-5 years
- Core question: "How should we allocate finite capital and attention, and what should we explicitly not do?"
- Evaluation criteria: Expected value, optionality, reversibility, opportunity cost
- Thinks in decision trees and scenario plans, considers second-order effects and path dependencies

### Agent 3 — RED TEAM / RISK SENTINEL (pre-mortem lens)
- Framework: Adversarial analysis, pre-mortem methodology (Klein 1998), competitive game theory, tail risk assessment
- Method: Inversion — "What would have to be true for this to fail?"
- Time horizon: Present to 3 years
- Core question: "What are we missing, and what kills us?"
- Evaluation criteria: Probability of ruin, competitive vulnerability, model fragility, regulatory exposure
- NOT a devil's advocate with fixed contrarian stance — uses structural stress-testing methodology
- When evidence is strong, should agree, with explicit documentation of evaluated-and-dismissed risks

### Agent 4 — INNOVATION ENGINE (technology possibility lens)
- Framework: R&D pipeline analysis, ML experiment design, information theory, technical feasibility
- Method: Bottom-up from technical capabilities to what's newly possible
- Time horizon: 3-18 months (R&D cycles)
- Core question: "What can we build that we couldn't before, and what's the expected effect size?"
- Evaluation criteria: Information ratio improvement, computational efficiency, backtest alpha, tech debt

### Agent 5 — MACRO NAVIGATOR (regime and ecosystem lens)
- Framework: Macro-financial analysis, regulatory landscape, market structure evolution, network effects
- Method: Outside-in from macro environment to strategy implications
- Time horizon: 2-5 years
- Core question: "How is the world changing in ways that create or destroy our opportunities?"
- Evaluation criteria: Scenario robustness, adaptive capacity, regulatory compliance, ecosystem positioning

### Why This Composition Works
Five agents span five distinct time horizons, five different "what matters most" criteria, mix of bottom-up and top-down reasoning. AceMAD paper (arXiv:2603.06801): configuring agents with different cognitive approaches achieved **74% improvement over standard multi-agent debate** by breaking the "Martingale Curse."

## Council Cadence: What to Deliberate and When

### Daily Council (~$0.50, 5 minutes, pre-market)
1. Market regime classification (VIX percentile, overnight moves, credit spread shifts)
2. Risk dashboard review (P&L, drawdown, margin, positions near stops)
3. Risk posture recommendation (position sizing 0.5x–1.5x, cash reserve, sector tilts)
4. Tactical opportunities and threats (earnings, Fed speakers, economic data)
5. Council vote with confidence scores (Modified Delphi, 1-10 confidence, dissent flagged)

### Weekly Council (~$1.50–2.00, 15-20 minutes, Sunday evening)
- Strategy performance review (win rate, Sharpe, drawdown trajectory)
- Signal quality assessment — which signals performed, which degraded
- Regime evolution analysis
- Sector and factor rotation recommendations
- Scan aggressiveness calibration
- Infrastructure and operations issues
- Forward calendar for coming week

### Monthly Council (~$3.00, 30 minutes, first weekend)
- Full performance attribution
- Strategy evolution — add, retire, or modify strategies?
- Capital allocation rebalancing
- Risk parameter audit
- Technology and infrastructure roadmap
- Business development planning

### Quarterly Council (~$6.00, 60 minutes)
- Phase transition assessment
- Competitive landscape analysis
- Risk framework evolution
- Scaling plan with AUM targets
- Mirrors Bridgewater, AQR, Two Sigma quarterly reviews

**Total: ~$20-25/month**

## Parameter Adjustment: Soft Biases Within Hard Guardrails

2025 Nature Scientific Reports: ML framework with regime-switching risk budgeting achieved Sharpe 1.38 (55% improvement over risk parity). During March 2020 crisis, proactively reduced equity exposure from 52% to 38% two weeks before trough. VIX-adaptive Kelly criterion research: hybrid strategies contained max DD below 11%.

### Hard Controls (NEVER council-adjustable)
- Maximum single position: 5% of equity
- Portfolio drawdown halt: -10% (all new positions stopped, orderly wind-down)
- Daily loss limit: -3% (trading paused)
- Maximum leverage: 1.0x Phase 1
- VIX >40: automatic 50% position reduction
- Human kill switch always available

### Soft Controls (council-adjustable within bounds)

| Parameter | Range | Frequency | Mechanism |
|---|---|---|---|
| Position sizing multiplier | 0.25x – 1.5x | Daily | VIX regime × council confidence |
| Cash reserve target | 10% – 50% | Daily | Regime + drawdown state |
| Scan aggressiveness | Conservative / Normal / Aggressive | Daily | Signal quality + regime |
| Sector preference weights | ±20% from neutral | Weekly | Factor and rotation analysis |
| Stop-loss multiplier | 1.5x – 3.0x ATR | Weekly | Volatility regime |
| Max portfolio beta | 0.3 – 1.2 | Weekly | Regime assessment |
| Strategy allocation weights | ±15% between strategies | Monthly | Performance attribution |

### Rate Limiters
- Max parameter change per day: ±25% on any single parameter
- Max cumulative weekly change: ±50%
- No parameter can move >2σ from 30-day mean in single session

### Confidence → Aggressiveness Mapping
- <60% consensus: all soft parameters default to most conservative preset
- Average confidence <4/10: minimum risk parameters auto-apply
- Rolling 30-day accuracy tracker adjusts council influence weight — degrading accuracy auto-reduces parameter shift range

### Phase 1 Implementation
- Council adjustments apply only to paper trading initially
- Auto-apply within tight bounds
- 3-6 month track record before influencing live trading
- Phase 2: gradually widen bounds based on accuracy
- Phase 3: per-strategy parameters + cross-strategy correlation monitoring

## Interpreting Contested vs Unanimous Sessions

### Condorcet Jury Theorem
If each voter independently correct with p > 0.5, majority-correct probability → 1 as group grows. With 5 agents at p=0.7: majority-correct ~83.7%. At p=0.8: ~94.2%.

**Critical violation: all 5 agents on Claude Sonnet share training data, RLHF alignment, and systematic biases.** NeurIPS 2024: when agents share a "common misconception," debate converges to incorrect majority — "tyranny of the majority."

### 5-0 Unanimous
Requires reasoning diversity audit before execution. Compute reasoning diversity score — how different are justifications?

If each agent arrives via genuinely different analytical path: very high-confidence signal, execute with full conviction.

If all cite same evidence/reasoning, or conclusion matches "conventional wisdom," or all confidence >90%: likely reflects model training consensus. Trigger shared-misconception audit — prompt fresh agent to find strongest counterargument. If plausible: downgrade to moderate confidence.

### 4-1 Split
Per Nemeth: even a wrong lone dissenter stimulates better thinking. Protocol:
1. Identify which agent dissented and whether aligned with their framework
2. Assess if dissenter identifies specific, falsifiable risk majority hasn't addressed
3. Apply domain-specific believability weighting
4. Default: execute majority but implement dissenter's top risk mitigation. Reduce size ~20% vs 5-0. Set "dissent trigger" condition for re-evaluation.

### 3-2 Split (Most Information-Rich)
Never auto-execute. Map coalition structure. Apply confidence-weighted aggregation:

**Score = Σ(agent_vote × agent_confidence × domain_weight) / Σ(agent_confidence × domain_weight)**

If weighted result near 50%: genuinely uncertain.

Default: hedged version of majority at ~50% size, implement minority hedges, shortened review cycle. **Ruin-prevention override: if minority includes Agent 3 (Red Team) and identifies ruin-level risk >10% probability, veto regardless of majority.**

Decision thresholds:
- Score > 0.8 → execute with full conviction
- 0.6–0.8 → execute with reduced size and hedges
- 0.4–0.6 → no action, preserve optionality
- < 0.4 → opposite-direction signal worth investigating

### Track Round 2 Behavior
Healthy: agents update based on new information. Sycophantic: agents switch without citing new reasoning — flag and discount. Persistent dissent after seeing majority reasoning: increase that agent's weight (Tetlock finding).

## The Human's Role: Centaur Moderator

Kasparov's 2005 freestyle chess: "Weak human + machine + better process was superior to strong computer alone." MIT meta-analysis: human+AI beats humans alone but did not outperform best AI alone in general. Adding human when AI outperforms typically pulls performance down.

**Implication: don't review every council output. Use confidence-based routing — escalate only low-confidence or high-disagreement decisions.**

Kahneman's Noise framework: human should provide input as structured data (not holistic judgments), input before seeing council output (avoid anchoring), focus on being input to algorithm rather than final judge on routine decisions.

### Four-Phase Interaction
1. **Phase 0 — Human primes council** (~2 min pre-deliberation): Set context, constraints, risk parameters. Inject proprietary info model can't access.
2. **Phase 1 — Independent agent assessment** (Delphi Round 1): All 5 independently assess. No human visibility — prevents anchoring.
3. **Phase 2 — Dashboard checkpoint** (~1 min): Agreement matrix, confidence distribution, flagged anomalies. Route: if agreement ≥4/5 and confidence >0.7 → auto-proceed. If disagreement ≥3/5 → founder reviews, can inject corrections.
4. **Phase 3 — Deliberation** (Delphi Round 2): With human injections visible as "Moderator Note." Founder doesn't see intermediate deliberation.
5. **Phase 4 — Final synthesis**: Council recommendation + confidence + dissents + risk flags. Routine decisions within bounds → auto-execute. Novel/high-stakes/low-confidence → founder Go/No-Go. Every override logged.

## Eight Failure Modes

### FM-1: Correlated Errors from Model Monoculture
2025 study across 350+ LLMs: models agree 60% of the time when both err. With all 5 on Claude Sonnet: maximum monoculture. Detection: track agreement rate specifically when council is later proven wrong. Mitigation: genuinely different information subsets, temperature variation (0.3 analytical, 0.7 exploratory), consider mixing model families as system matures.

### FM-2: Sycophantic Convergence
CONSENSAGENT (ACL 2025): "agents reinforce each other's responses instead of critically engaging." Agents show sycophancy in Round 1 and progressively become less willing to defend correct positions. Detection: correct-to-incorrect flip rate, entropy of opinion over rounds. Mitigation: lock Round 1, require explicit "what would change my mind" statements, "correctness payoff" prompts.

### FM-3: The Martingale Curse
**NeurIPS 2025 spotlight: multi-agent debate induces a martingale over belief trajectories — expected belief remains unchanged over rounds. Most gains attributed to debate actually stem from majority voting.** Multiple rounds can decrease performance.

Implementation: **Vote-First, Debate-If-Needed protocol.** Get 5 independent assessments, aggregate via majority vote. Only deliberate if significant disagreement (<3/5). Track whether deliberation changes majority-vote outcome, and whether changes are better or worse. Build empirical scorecard over first 90 days.

### FM-4: Confabulation in Data-Sparse Domains
Council may generate plausible-sounding but fabricated market analyses. Detection: compare factual claims against ground-truth data feeds, require "according-to" citations. **Never trade on qualitative LLM analysis alone — require quantitative data confirmation.**

### FM-5: Confident but Meaningless Output (Current Problem)
Detection: information entropy (low variance across sessions = decorative), actionability score (% of sessions with different action than default), specificity tracking. Mitigation: structured quantitative outputs, flag if >80% sessions produce same directional call.

### FM-6: LLM Calibration Failures
GPT-4 AUROC for distinguishing own correct vs incorrect: 62.7% — barely above random. LLMs overconfident when verbalizing confidence. Mitigation: use **behavioral confidence** (agreement among agents) rather than **stated confidence** (what agents claim). Apply post-hoc calibration.

### FM-7: Position Bias from Conversation Order
LLMs overemphasize beginning and end of context. First agent's response anchors subsequent agents. Mitigation: randomize agent order every round. Parallel/simultaneous presentation when possible.

### FM-8: Cascading Error Amplification
Google DeepMind: unstructured multi-agent networks amplify errors up to 17.2× vs single-agent. Detection: when final answer wrong, check if Round 1 majority was also wrong (monoculture) or error emerged during deliberation (cascade). Mitigation: preserve Round 1 as baseline, compare to final, flag divergences.

## Scaling: Solo Founder to Multi-Desk Fund

### Phase 1: Solo ($100K–$1M) — No Registration
- 5 agents report to founder
- Council = investment committee equivalent
- Paper-trading-only influence → live after demonstrated accuracy
- Focus: 12-24 month auditable track record

### Phase 2: First External Capital ($1M–$10M) — ERA
- Delaware LP + LLC GP
- Exempt Reporting Adviser (Form ADV Part 1)
- Private Fund Adviser Exemption (up to $150M AUM)
- Outsource CCO ($2-5K/month), fund admin, auditor
- AI-native fund breaks even at $5-20M vs traditional $100-200M

### Phase 3: Institutional ($10M–$50M)
- Formalize investment committee (AI memos, partner review)
- Separate risk from portfolio management
- First employee (operations/compliance)
- 2-3 person advisory board

### Phase 4: Multi-Desk ($50M–$150M)
- SEC registration approaching $100M mandatory
- Each desk gets own council instance
- Central risk management council oversees all pods
- Full-time CCO mandatory

### Phase 5: Institutional Fund ($150M+)
- Quarterly Form PF filing
- Multiple pods with independent councils
- Master risk council across pods
- Operating Board of Directors

**Critical: 5-agent council architecture stays constant at every phase. What changes is how many instances, what parameters they control, and governance around them. This is the pod replication model.**

## Building Competitive Moats

Renaissance Technologies: 66% annual gross (39% net) for 34+ years without losing year. Moat is interlocking system: capacity discipline (capped ~$10B), process power (50,000 cores, 30+ years continuous refinement), cornered resources (400 employees, 12-year median tenure), compounding knowledge.

Jim Simons: "Visibility invites competition… Our only defense is to keep a low profile."

### Hamilton Helmer's 7 Powers for Halcyon
Immediately accessible:
- **Counter-positioning**: AI-native architecture incumbents can't replicate without disruption
- **Cornered resources**: Founder's unique domain + AI knowledge; trained council can't be hired away

Over 2-5 years:
- **Process power**: Compounding institutional knowledge in reasoning chains, trade outcomes, refined heuristics

### What Agent 3 Should Track Weekly
1. **Knowledge compounding**: new signals, new features, accuracy trends (30/60/90-day rolling)
2. **Data flywheel velocity**: total labeled outcomes, execution cost improvement, feature importance drift, unique regimes documented
3. **Competitive landscape**: new arXiv papers, competitor performance, alt data vendor developments, regulatory changes
4. **Time-to-replicate estimate**: if competitor started today with unlimited resources, how many months to replicate? This number should increase over time.

## Structured JSON Output Schema

```json
{
  "session_meta": {
    "session_id": "HLC-2026-03-28-daily",
    "timestamp_utc": "2026-03-28T12:30:00Z",
    "session_type": "daily",
    "api_cost_usd": 0.48,
    "completion_time_seconds": 287
  },
  "market_regime": {
    "classification": "elevated",
    "vix_current": 22.4,
    "vix_percentile_52w": 71,
    "credit_spread_direction": "widening",
    "regime_confidence": 0.78
  },
  "council_vote": {
    "aggregated_score": 0.62,
    "aggregated_direction": "cautious_long",
    "vote_distribution": {
      "tactical_operator": {"direction": "neutral", "confidence": 0.65, "domain_weight": 1.2},
      "strategic_architect": {"direction": "long", "confidence": 0.72, "domain_weight": 0.8},
      "red_team": {"direction": "neutral", "confidence": 0.80, "domain_weight": 1.0},
      "innovation_engine": {"direction": "long", "confidence": 0.55, "domain_weight": 0.6},
      "macro_navigator": {"direction": "long", "confidence": 0.70, "domain_weight": 0.9}
    },
    "consensus_type": "4-1_split",
    "reasoning_diversity_score": 0.73,
    "sycophancy_flag": false
  },
  "parameter_adjustments": {
    "position_sizing_multiplier": {"value": 0.85, "previous": 1.0, "change_pct": -15},
    "cash_reserve_target_pct": {"value": 25, "previous": 20, "change_pct": 25},
    "scan_aggressiveness": {"value": "conservative", "previous": "normal"},
    "sector_tilts": {"prefer": ["utilities", "healthcare"], "avoid": ["tech_growth"]},
    "all_within_bounds": true,
    "rate_limit_check": "passed"
  },
  "dissent_record": {
    "dissenting_agent": "tactical_operator",
    "dissent_summary": "VIX term structure inversion suggests near-term vol expansion",
    "dissent_falsifiable_trigger": "VIX term structure returns to contango within 3 sessions",
    "dissent_mitigation_applied": "position_sizing_reduced_15pct"
  },
  "action_items": [
    {"action": "reduce_position_sizing", "parameter": "multiplier", "value": 0.85, "auto_applied": true},
    {"action": "increase_cash_reserve", "parameter": "target_pct", "value": 25, "auto_applied": true},
    {"action": "human_review_requested", "reason": "elevated_regime_with_dissent", "priority": "medium"}
  ],
  "quality_metrics": {
    "round1_majority_preserved": true,
    "deliberation_changed_outcome": false,
    "specificity_score": 0.82,
    "actionability_score": 0.90,
    "claim_verification_rate": 1.0
  },
  "calibration_tracking": {
    "prediction": "SPY range-bound within 1% for next 3 sessions",
    "prediction_confidence": 0.68,
    "verification_date": "2026-04-01",
    "outcome": null
  }
}
```

Weekly extends with `strategy_performance`, `signal_quality_assessment`, `moat_health_metrics`, `infrastructure_status`. Monthly adds `performance_attribution`, `strategy_evolution_recommendations`, `phase_gate_assessment`.

## Conclusion: Three Design Principles

1. **Vote first, debate only when needed.** NeurIPS martingale finding: primary value is ensembling five independent lenses. Round 1 independent assessments are the most valuable output. Reserve Round 2 for <3/5 consensus.

2. **Council earns authority through demonstrated accuracy.** Phase 1: paper-only with tight bounds. As calibration data accumulates over 90+ days, bounds widen. Self-correcting: influence proportional to proven track record.

3. **Process power is the ultimate moat.** Every session's structured output — reasoning chains, dissent records, parameter adjustments, outcomes — becomes proprietary training data compounding over time. The council builds institutional memory from Day 1 that becomes progressively harder to replicate.
