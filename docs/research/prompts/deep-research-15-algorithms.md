# Deep Research: Arcis 15 Proprietary Algorithm Analysis — Gap Assessment, Iteration Paths, and Competitive Positioning

**Date:** 2026-04-05
**Output:** Save to `docs/research/` as a single comprehensive document
**Classification:** INTERNAL — contains proprietary algorithm details

---

## Research Objective

Analyze each of the 15 proprietary algorithms in the Arcis autonomous equity trading system. For EACH algorithm, determine:

1. **State of the art:** What does industry/academia consider best practice for this specific function? Cite papers with effect sizes where available.
2. **Our position:** Where does our implementation sit relative to state-of-the-art (ahead, behind, on par)? Be honest — we want to find gaps, not validate our choices.
3. **Evidence threshold:** What evidence (trade count, statistical test, market condition) would tell us to iterate vs stay put?
4. **Highest-leverage improvement:** What's the single best next step, and what's the expected effect size?
5. **Gap analysis:** Are we doing anything that has been proven suboptimal by research published after our implementation?
6. **Risk assessment:** What failure mode is most likely, and what would it look like in production?

---

## System Context

- **Strategy:** Pullback-in-uptrend setups on S&P 100 large-cap equities
- **Model:** Qwen3 8B fine-tuned (QLoRA), local inference via Ollama on RTX 3060 12GB
- **Current state:** 18 closed trades (12W/1L), Phase 1 bootcamp targeting 50 trades
- **Training data:** 979 scored examples, 62/38 curated-to-synthetic ratio
- **Capital:** $100K paper (Alpaca) + $100 live (Alpaca)
- **Operating cost:** ~$64/month (Render $14, Claude API ~$50)
- **Holding period:** 1-15 days (swing trading, not intraday)
- **Universe:** 103 S&P 100 tickers (expanding to ~325 in Phase 2)
- **Scan frequency:** Every 30 minutes during market hours (9:30 AM – 4:00 PM ET)

---

## The 15 Algorithms

### Algorithm #1: Traffic Light Regime System
**File:** `src/features/traffic_light.py` (134 lines)
**Function:** Market-level regime overlay that controls position sizing across ALL trades

**Current implementation:**
- Three indicators, each scored 0-2:
  1. **VIX Level:** <20 → 0 (green), 20-30 → 1 (yellow), >30 → 2 (red)
  2. **SPY vs 200-DMA:** >3% above → 0, within 3% → 1, below → 2
  3. **HY Credit Spread Z-score:** <0.5 → 0, 0.5-1.5 → 1, >1.5 → 2
- Total score 0-6 maps to: GREEN (0-2), YELLOW (3-4), RED (5-6)
- Sizing multipliers: GREEN=1.0, YELLOW=0.5, RED=0.1
- **Persistence filter:** Must see same state 5 consecutive readings before switching regime. This prevents whipsaw at regime boundaries.
- State stored in `traffic_light_state` table (singleton row)

**Key design decisions:**
- Equal weighting across all 3 indicators (each contributes 0-2 to the total)
- VIX thresholds chosen from research: VIX <20 is historically "normal," >30 is "crisis"
- HY credit spread uses Z-score rather than absolute level to adapt to changing rate environments
- 0.1 multiplier in RED (not 0.0) ensures we maintain minimal exposure for learning even in crisis
- Persistence filter of 5 readings at 30-min scan cadence = 2.5 hours minimum before regime change

**What I want to know:**
- Is equal weighting optimal, or should VIX dominate? Research on which indicator leads the others?
- Is our persistence filter too slow (2.5 hours) or too fast? What do institutional regime systems use?
- Should we add breadth indicators (advance/decline line, new highs/lows, % above 200-DMA)?
- Are there regime detection methods (HMM, Markov switching) that outperform simple threshold rules at our trade count?
- What's the false positive rate of our regime transitions? (switching to RED when the dip is buyable)

---

### Algorithm #2: Event Risk Score
**File:** `src/features/event_risk_score.py` (284 lines)
**Function:** Continuous 0-10 additive calendar risk score that adjusts position sizing near known events

**Current implementation:**
- Additive scoring system — multiple events compound risk:
  - **Earnings proximity:** 0 points (>5 days away), +2 (3-5 days), +4 (1-2 days), +6 (today/tomorrow)
  - **FOMC:** +2 (within 3 days), +4 (day of/before)
  - **NFP (first Friday):** +1 (within 2 days), +2 (day of)
  - **CPI release:** +1 (within 2 days), +2 (day of)
- Sizing multiplier: `max(floor, 1.0 - score * 0.1)` where floor is configurable (default 0.3)
- Block threshold: score ≥8 → block trade entirely
- Data sources: `earnings_calendar` table (from Finnhub), `data/reference/market_event_calendar.csv` (manual), FOMC dates
- Uses `_coerce_date()` helper because SQLite stores dates inconsistently

**Key design decisions:**
- Additive (not max) — stock near earnings AND FOMC gets score 8+ (blocked), not just max(6, 4) = 6
- Sizing floor ensures we never go to zero sizing (we want data from all market conditions)
- Earnings weighted highest because they cause the most stock-specific volatility

**What I want to know:**
- Is our earnings proximity weighting correct? Research on optimal holding period around earnings for swing trades?
- Should we differentiate between pre-market and post-market earnings announcements?
- Are there events we're missing? (Options expiration, index rebalancing, sector-specific events like OPEC for energy stocks)
- What's the empirical relationship between event score and trade outcome at our holding period (1-15 days)?
- Is additive the right aggregation, or does research suggest multiplicative or max?

---

### Algorithm #3: Setup Classifier
**File:** `src/features/setup_classifier.py` (316 lines)
**Function:** Classify each ticker's current setup into one of 6 types for strategy routing

**Current implementation:**
- 5 discriminative features:
  1. **ADX** (trend strength): >25 = trending, <20 = ranging. Computed from 14-day smoothed +DI/-DI
  2. **ATR/price ratio** (normalized volatility): Expressed as percentage for cross-stock comparison
  3. **Volume profile**: Declining on retracement = healthy pullback, expanding = breakout or capitulation
  4. **Price vs MAs**: Above 200MA pulling to 50MA = classic pullback, below both = breakdown
  5. **RSI context**: 30-50 in uptrend = pullback, <25 = extreme mean reversion candidate
- 6 output types: `pullback`, `breakout`, `momentum`, `mean_reversion`, `range_bound`, `breakdown`
- **Ordered rule evaluation** — rules checked from most restrictive to least:
  1. Breakdown (downtrend + ADX>25 + below 200MA + negative slope + RSI<35)
  2. Mean reversion (RSI<25 + above 200MA + volume declining)
  3. Pullback (uptrend + pulling to 50MA + volume declining)
  4. Breakout (ADX>25 + volume expanding + above both MAs + near 52-week high)
  5. Momentum (strong uptrend + RSI>60 + expanding volume)
  6. Range bound (default fallback)
- Returns confidence score 0.0-1.0 based on how many sub-conditions match
- Routes to desk: `equity_swing` (pullback, breakout), `equity_momentum` (momentum), `none` (breakdown, range_bound)

**Key design decisions:**
- Rule-based, not ML — intentional at <50 trades because ML classifiers need 500+ labeled examples
- Order matters: breakdown checked first to prevent dangerous misclassification of a crash as mean reversion
- Confidence used downstream by the ranker (low confidence = lower score)
- `mean_reversion` desk is active (Strategy #2, paper-trading now)

**What I want to know:**
- At what trade count should we transition from rules to ML? What classifier type (random forest, gradient boosting, neural)?
- Are our 5 features the right discriminators? Factor analysis on labeled setups?
- Is ADX the best trend strength indicator, or are alternatives (Vortex, Aroon, Supertrend) better for this application?
- What's our misclassification rate? Can we estimate from the 18 closed trades?
- Should the confidence score weight downstream decisions more than it currently does?

---

### Algorithm #4: Filing NLP + Delta
**File:** `src/features/filing_nlp.py` (143 lines)
**Function:** Extract sentiment and change signals from SEC 10-K/10-Q filings

**Current implementation:**
- **Loughran-McDonald dictionary sentiment**: ~60 negative words, ~30 positive words (core subsets of the full L-M dictionary). Counts occurrences per 1000 words. Returns `negative_pct`, `positive_pct`, `net_sentiment`.
- **17 cautionary phrase patterns**: Regex patterns detecting phrases like "going concern," "material weakness," "covenant violation," "liquidity constraints," "restated." Returns count and list of matches.
- **Filing-to-filing delta**: Compares current 10-K/10-Q sentiment scores against previous filing of same type. Delta polarity (improving vs deteriorating) is the key signal.
- **Tech-fundamental divergence** (`compute_tech_fundamental_divergence()`): Cross-references technical trend state against filing sentiment. Outputs: `convergence_bullish` (uptrend + improving fundamentals = highest conviction), `divergence_caution` (uptrend + deteriorating fundamentals = reduce sizing), `neutral`.

**Key design decisions:**
- Using L-M dictionary (not general-purpose sentiment) because financial language has inverted meanings ("liability" is neutral in finance, negative in general English)
- CPU-only, milliseconds per filing — no GPU needed, runs during overnight collection
- Delta is more important than absolute level — a company with high cautionary phrases that's IMPROVING is a better signal than one with low phrases that's DETERIORATING
- Core subset of L-M dictionary (not full) to reduce noise from low-frequency terms

**What I want to know:**
- Should we upgrade to FinBERT or similar transformer-based sentiment? What's the marginal accuracy gain vs computational cost?
- Is our L-M subset comprehensive enough? Are there critical words we're missing?
- What's the optimal lookback window for delta computation (1 filing vs 2-3 filings)?
- Does the tech-fundamental divergence signal actually predict returns? At what holding period?
- Should we incorporate management's tone in earnings calls (not just filings)? What data source?
- Any research on filing readability (Fog index, Flesch-Kincaid) as a signal for large-cap equities?

---

### Algorithm #5: Pullback Ranker
**File:** `src/ranking/ranker.py` (226 lines)
**Function:** Score every ticker 0-100 and classify as packet-worthy (≥40), watchlist (30-39), or not interesting (<30)

**Current implementation:**
- **Scoring weights (0-100 scale):**
  - Trend state: strong_uptrend=+30, uptrend=+20, neutral=+5, downtrend=0
  - Relative strength: strong_outperformer=+25, outperformer=+15
  - Pullback depth: -3% to -10%=+25 (sweet spot), -10% to -15%=+10
  - Distance to SMA20: -1% to -5%=+10 (pulling back toward support)
  - Volume contraction: ratio <0.8=+10 (declining volume on pullback = healthy)
  - Options sentiment: IV rank <25=+3, IV rank >75 + bearish flow=-3
  - Regime adjustment: -10 to +10 (from `_regime_adjustment()`)
- **Regime adjustment** sub-algorithm:
  - calm_uptrend + healthy breadth = +5
  - calm_uptrend + narrowing breadth = +2
  - volatile_uptrend = 0
  - transitional = -3
  - calm_downtrend = -5
  - volatile_downtrend = -10
  - SPY RSI >75 = -3 (overbought), SPY RSI <30 = +3 (oversold)
- **Adaptive thresholds:** In bearish regimes, packet_worthy threshold rises (harder to qualify) and position sizing drops

**Key design decisions:**
- Equal weight between trend (+30) and pullback depth (+25) — we want BOTH a strong uptrend AND a meaningful pullback
- The -3% to -10% sweet spot is based on O'Neil's CAN SLIM research and our own observation
- Volume contraction is critical — declining volume on a pullback means institutions aren't selling
- Regime adjustment can swing ±10 points — a borderline stock (score 35) in a bad regime drops to 25 (rejected)

**What I want to know:**
- Are our weights optimal? At 200 trades, should we use feature importance from closed trades to recalibrate?
- Is the -3% to -10% pullback sweet spot correct for S&P 100 large-caps, or is it different from mid/small-cap research?
- Should we add momentum features (rate of change, acceleration)?
- Is there a better scoring methodology (logistic regression, ensemble) that preserves interpretability?
- How does our ranker compare to published factor models (Fama-French, Carhart) for large-cap equity selection?
- Should relative strength be measured against sector (not just SPY)?

---

### Algorithm #6: Self-Blinding Training Pipeline
**File:** `src/training/data_collector.py` (215 lines)
**Function:** Generate training data from closed trades WITHOUT leaking outcome information to the model

**Current implementation:**
- **Temporal firewall:** Outcome data (win/loss, P&L, exit reason) is NEVER included in the prompt sent to the LLM for commentary generation. The model sees only the setup features that were available at entry time.
- **Outcome-conditioned templates:** After a trade closes, we create 3-5 training examples using templates that condition on outcome type (WIN, LOSS, TIMEOUT, PASS). The template shapes the ANALYSIS FOCUS (e.g., "explain what went right" vs "explain what the risks were") but doesn't reveal the outcome in the input.
- **Sanitization:** `_sanitize_feature_snapshot()` removes outcome-correlated fields (P&L, exit price, exit reason) from the feature dict BEFORE it's sent to the LLM. (Fixed in #277 — was previously sanitizing AFTER generation.)
- **Leakage detection:** TF-IDF balanced accuracy test. If a simple bag-of-words classifier can predict outcome from the training input at >55% accuracy, the pipeline is leaking.
- **Quality scoring:** 6-dimension rubric scores each generated example. Bottom 15% pruned. Golden ratio: 62% curated / 38% model-generated (He et al., 2025).

**Key design decisions:**
- Self-blinding is ARCHITECTURAL, not procedural — the code structure makes it impossible to accidentally pass outcome data
- We generate examples from both the LLM and from structured templates — the mix prevents mode collapse
- Quality scoring uses LLM-as-judge (Claude API) for rubric evaluation
- DPO pairs (preferred vs rejected outputs) are generated from contrastive templates

**What I want to know:**
- Is our leakage detector sensitive enough? Can TF-IDF catch subtle leakage (e.g., feature distributions that correlate with outcome)?
- Should we add causal inference tests (e.g., conditional independence tests between features and outcomes)?
- Is the 62/38 ratio still optimal, or has more recent research updated the golden ratio for financial domains?
- What's the state of the art for self-play / self-improvement training in financial LLMs?
- How does our approach compare to RL-based training (PPO, GRPO) which we plan to add at 100+ trades?
- Are there published benchmarks for financial commentary quality that we could use instead of our custom rubric?

---

### Algorithm #7: HSHS (Halcyon System Health Score)
**File:** `src/evaluation/hshs.py` (82 lines) + `src/evaluation/hshs_live.py` (343 lines)
**Function:** Single composite health score (0-100) for the entire system, measured across 5 dimensions

**Current implementation:**
- **5 dimensions, each scored 0-100:**
  1. **Performance:** Win rate, profit factor, Sharpe, max drawdown, expectancy
  2. **Model quality:** LLM success rate, conviction parse rate, template fallback rate
  3. **Data asset:** Training example count, quality score distribution, diversity (unique tickers)
  4. **Flywheel velocity:** Trades/week, examples generated/week, model retrains completed
  5. **Defensibility:** Training data uniqueness, proprietary signal count, model fine-tuning depth
- **Weighted geometric mean** (not arithmetic) — any dimension near zero collapses the total score
- **Phase-dependent weights:**
  - Early (months 1-6): data_asset=0.35, model=0.25, flywheel=0.20, performance=0.10, defensibility=0.10
  - Growth (months 7-18): all dimensions = 0.20 (equal weight)
  - Mature (18+): performance=0.30, defensibility=0.25, model=0.20, data=0.15, flywheel=0.10

**Key design decisions:**
- Geometric mean chosen because a system scoring 95 on 4 dimensions and 5 on reliability is NOT a healthy system — arithmetic mean would say 77/100, geometric mean says 30/100
- Phase weights reflect what matters most at each stage: early = build data, growth = balance everything, mature = performance matters most
- Each dimension floored at 1.0 (not 0.0) so a zero dimension doesn't collapse entire score to zero

**What I want to know:**
- Is our 5-dimension decomposition correct? Are we missing critical dimensions (e.g., infrastructure reliability, regulatory compliance)?
- Are our phase weight transitions at the right times?
- How do institutional fund managers measure "system health" — is there an industry standard we should align to?
- Should the defensibility dimension include competitive intelligence (monitoring other AI trading systems)?
- Is geometric mean the best aggregation, or are there alternatives (harmonic mean, power mean) that better capture our intent?

---

### Algorithm #8: Build Score
**File:** `src/evaluation/build_score.py` (440 lines)
**Function:** Daily composite KPI (0-100) for system development progress, with idle-day decay

**Current implementation:**
- **6 components combined via geometric mean:**
  1. **Gate velocity:** Weekly closed trade rate vs 1.92/week target (based on 50 trades / 26 weeks)
  2. **System health:** HSHS composite score (passthrough from Algorithm #7)
  3. **Data asset value:** Quality (40%) + diversity (35%) + freshness (25%)
  4. **Model quality:** 7-day rolling LLM success rate
  5. **Research velocity:** HSHS flywheel_velocity proxy
  6. **Reliability:** Scan success rate (60%) + uptime proxy (40%)
- **Idle-day decay:** -1 point per day with zero activity (no trades, no training examples, no scans)
- **Phase progress tracking:** Tracks % completion toward Phase 1 gate criteria

**What I want to know:**
- Is the idle-day decay the right mechanism? Should it be exponential rather than linear?
- At what point does the Build Score become less useful (after Phase 1)?
- Should we add a financial dimension (cost efficiency, ROI on compute)?

---

### Algorithm #9: CUSUM Change Detector
**File:** `src/evaluation/change_detector.py` (40+ lines)
**Function:** Detect when the trading strategy has undergone a regime shift (performance degradation or improvement)

**Current implementation:**
- **Symmetric CUSUM filter** from López de Prado, AFML Chapter 17
- Inputs: P&L percentage series from closed trades
- Threshold: 2.0 (higher = less sensitive, fewer false alarms)
- Drift: 0.0 (no expected drift — strategy should have positive expectancy)
- Detects both upward and downward regime changes
- Outputs: list of detected change points + current alarm status

**What I want to know:**
- Is CUSUM the best change detection method for trade P&L series? Alternatives: Bayesian online change detection, PELT algorithm, MOSUM?
- Is our threshold (2.0) calibrated correctly for our expected P&L distribution?
- At 18 trades, is CUSUM even statistically meaningful? What's the minimum sample size?
- Should we monitor additional streams beyond P&L (e.g., win rate rolling window, average holding period)?

---

### Algorithm #10: Canary Score
**File:** `src/strategy/canary.py` (40+ lines)
**Function:** Pure rules-based conviction (1-10) that runs alongside the LLM as a baseline comparison

**Current implementation:**
- Starts at 5 (neutral), adjusts based on feature thresholds:
  - Strong uptrend: +1, Downtrend: -1
  - Pullback depth 3-8%: +1, >12%: -1
  - Volume ratio <0.8: +1
  - RSI <40: +1
- Capped at 1-10
- Logged alongside LLM conviction for every trade
- If LLM template fallback rate exceeds 50%, canary is compared for degradation monitoring

**What I want to know:**
- Is this the right baseline? Should we use a more sophisticated non-ML baseline (e.g., linear factor model)?
- At what paired trade count (50? 100?) can we statistically determine if LLM adds value over canary?
- Should the canary score be used as an ensemble input (average with LLM conviction) rather than just a comparison?

---

### Algorithm #11: Council Aggregation + Value Tracker
**File:** `src/council/aggregation.py` (106 lines) + `src/council/value_tracker.py` (221 lines)
**Function:** 5-agent AI deliberation system with counterfactual performance attribution

**Current implementation:**
- **5 agents:** Tactical (short-term ops), Strategic (long-term plan), Red Team (devil's advocate), Innovation (new approaches), Macro (market regime)
- **Modified Delphi protocol:** Round 1 = independent blind votes, Round 2 = debate (if no consensus), Round 3 = final positions with confidence
- **Domain-weighted aggregation:** Each agent's vote weighted by domain relevance
- **Consensus → traffic light:** Direction + confidence → position sizing regime for the day
- **Value tracker:** Compares actual P&L under council-adjusted parameters vs counterfactual P&L under default parameters
  - Alert at 8 weeks net negative
  - Auto-tighten parameters at 12 weeks negative
  - Restore at 4 weeks positive
- Cost: ~$0.50/session via Claude Sonnet API, daily at 8:30 AM ET

**What I want to know:**
- Is 5 agents optimal? Research on optimal committee size for decision quality?
- Is the Delphi protocol the best deliberation format? Alternatives: prediction markets, adversarial debate, majority vote?
- Does the value tracker correctly attribute causation (not just correlation)? Council changes parameters, but other factors change too.
- Should the council be strategy-specific (different councils for pullback vs mean reversion)?
- Are there published results on LLM council deliberation for trading decisions?

---

### Algorithm #12: Quality Drift Detection
**File:** `src/training/quality_drift.py` (185 lines)
**Function:** Detect when model outputs are degrading in quality without explicit failure

**Current implementation:**
- **Stdlib-only metrics (no nltk or external NLP):**
  - Vocabulary diversity: unique word count / total word count
  - Repetition rate: n-gram repetition frequency
  - Mode collapse: entropy of output distribution
- All metrics computed from raw text, stored in `quality_drift_metrics` table
- Alerts before next retrain cycle if drift detected
- Catches training-induced degradation (model converging to repetitive outputs)

**What I want to know:**
- Are these three metrics sufficient to catch all forms of model degradation?
- Should we add semantic drift (embedding distance from a "golden set" of high-quality outputs)?
- What's the baseline drift rate for fine-tuned models retrained weekly?
- At what drift level should we halt retraining and rollback to previous model version?

---

### Algorithm #13: Macro Regime Classification
**File:** `src/data_enrichment/macro.py` (180+ lines)
**Function:** Classify the current economic environment for regime-aware trading adjustments

**Current implementation:**
- **4 input indicators:**
  1. **Fed stance:** FFR >4% = restrictive, 2-4% = neutral, <2% = accommodative
  2. **Yield curve:** 10Y-2Y spread: <0 = inverted, 0-0.5 = flat, 0.5-1.5 = normal, >1.5 = steep
  3. **Unemployment:** >5% flag (recession indicator)
  4. **CPI YoY:** >3% with restrictive Fed = late_cycle
- **Output classifications:** recession, early_cycle, mid_cycle, late_cycle
- Override rules: inverted yield curve → recession (regardless of other indicators)
- Data sourced from FRED API (nightly collection)

**What I want to know:**
- Is our 4-indicator set sufficient? Should we add ISM PMI, housing starts, credit conditions, consumer sentiment?
- Are our thresholds calibrated for the current rate environment? (FFR >4% = restrictive was true in 2023 but may not be in 2027)
- How does our regime classification compare to NBER recession dating?
- Should we use a probabilistic model (recession probability 0-100%) rather than categorical labels?
- What's the lead time of our indicators vs actual regime transitions?

---

### Algorithm #14: Tech-Fundamental Divergence
**File:** `src/features/filing_nlp.py` (143 lines, shared with Algorithm #4)
**Function:** Cross-reference technical price action against fundamental sentiment direction

**Current implementation:**
- **Inputs:** Technical trend state (from feature engine) + filing sentiment delta (from Algorithm #4)
- **Logic:**
  - Tech bullish + fundamentals improving = `convergence_bullish` (highest conviction)
  - Tech bullish + fundamentals deteriorating = `divergence_caution` (reduce sizing)
  - All other combinations = `neutral`
- Simple binary classification — doesn't quantify the degree of divergence

**What I want to know:**
- Should this be a continuous score rather than 3 categories?
- Does research support this signal for large-cap equities? Most divergence research is on small-caps.
- Should we add revenue trajectory, margin trends, and guidance sentiment from earnings calls?
- What's the predictive horizon? Does convergence/divergence predict 5-day returns, 15-day returns, or longer?

---

### Algorithm #15: IV Skew + IV Rank
**File:** `src/data_collection/options_metrics.py` (230+ lines)
**Function:** Extract options market sentiment signals for equity trading decisions

**Current implementation:**
- **IV Skew:** Approximate 25-delta skew computed from strikes at ~5% OTM. `skew = OTM_put_IV - OTM_call_IV`. Positive skew = market pricing downside risk.
- **IV Rank:** `(current_ATM_IV - 252d_low) / (252d_high - 252d_low) * 100`. Requires ≥20 days historical data.
- **IV Percentile:** % of days in past year with lower IV than current.
- **Integration with ranker:** IV rank <25 = +3 to score (cheap options = less fear), IV rank >75 + put/call ratio >1.2 = -3 (expensive + bearish flow = caution)

**Key design decisions:**
- Using 5% OTM as proxy for 25-delta (exact delta calculation requires Black-Scholes and is computationally expensive for 103 tickers nightly)
- Skew is computed from nearest-expiry chain only (30-day target)
- Options pipeline was broken (#256, fixed in v0.13.0) — metrics were not computing correctly

**What I want to know:**
- Is the 5% OTM proxy for 25-delta accurate enough? What's the error margin?
- Should we use the full volatility surface (multiple expirations) instead of just nearest-30-day?
- Does put/call ratio add information beyond IV skew for S&P 100 equities?
- Should we incorporate unusual activity detection (large block trades, sweep orders)?
- Unusual Whales subscription ($50/mo) is planned — what specific data points would be highest value?
- How should options signals weight against technical signals in the ranker? Currently ±3 points out of 100.

---

## Cross-Cutting Questions

1. **Interaction effects:** Which algorithms interact with each other in ways that could amplify errors? (e.g., if Traffic Light is wrong AND the ranker over-weights regime, the combined error is larger than either alone)

2. **Redundancy:** Are any of the 15 algorithms measuring the same thing? Could we consolidate without losing information?

3. **Priority ordering:** If we could only improve 3 of the 15 algorithms in the next 6 months, which 3 would have the highest impact on trading performance? Why?

4. **Missing algorithms:** Are there standard components of a systematic trading system that we're missing entirely? (e.g., transaction cost model, slippage estimation, portfolio optimization, correlation-based sizing)

5. **Competitive positioning:** How does our algorithmic stack compare to known systematic trading firms (Renaissance, Two Sigma, Citadel, AQR) at the same stage of development? What did they focus on at the 50-trade mark?

6. **Model dependency:** How much of our edge comes from the LLM vs the deterministic pipeline? If we replaced the LLM with a simple logistic regression on the same features, what would we lose?

---

## Output Format

For each of the 15 algorithms, provide:

```
## Algorithm #N: [Name]

### State of the Art
[What industry/academia considers best practice. Cite papers with effect sizes.]

### Our Position
[Ahead / Behind / On Par — with specific justification]

### Evidence Threshold
[What data point / trade count / test result would trigger a change]

### Highest-Leverage Improvement
[Single best next step with expected effect size]

### Gap Analysis
[Any published research that contradicts our approach]

### Risk Assessment
[Most likely failure mode and what it looks like in production]

### Recommendation
[STAY (current approach is optimal for our stage) / ITERATE (specific change) / REPLACE (fundamentally different approach)]
```

Conclude with a priority-ordered roadmap: which algorithms to improve first, second, third, and which to leave alone.
