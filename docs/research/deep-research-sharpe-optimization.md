# Deep Research: Trade Lifecycle Optimization for Sharpe Ratio Maximization

## System Context

I operate **Arcis**, an autonomous AI-powered equity trading system targeting S&P 100 stocks using a pullback-in-uptrend strategy with mechanical bracket orders. The system is in Phase 1 validation with 23 closed trades showing:

- **Win rate:** 65.2% (15W / 8L)
- **Sharpe ratio:** 0.585 (annualized from per-trade returns, √150 trades/year)
- **Profit factor:** 3.72
- **Avg winner:** +3.6% | **Avg loser:** -1.8%
- **Avg hold period:** 3.5 days | **Max:** ~8 days (7-day timeout)
- **Max drawdown:** 5.34% (cumulative P&L peak-to-trough)
- **Targets hit:** 56.5% (T1 at ~2% gain) | **Stops hit:** 8.7% | **Reconciled/stale exits:** 34.8%
- **Concurrent positions:** Up to 15 | **Position sizing:** Equal-weight ~$6,600 per position on $100K shadow equity
- **Entry window:** 10:00–11:30 AM ET
- **Bracket parameters:** Fixed 2% target (T1), 4% target (T2), 3% stop, 7-day timeout
- **Universe:** S&P 100 (102 tickers), highly liquid, negligible market impact

**Current Sharpe is 0.585. The IB live trading gate requires >1.0. Institutional threshold is ≥1.5. I need to understand every lever available to move from 0.585 → 1.5+ without changing the core strategy (pullback-in-uptrend on large-cap equities).**

The system uses a deterministic ranker to score pullback setups, then an LLM (Qwen3 8B fine-tuned) to generate trade commentary and conviction scores. Execution is fully mechanical — bracket orders submitted at entry with no human intervention until exit.

---

## SECTION 1: EXIT STRATEGY OPTIMIZATION

This is the highest-priority research area. The current system uses fixed bracket orders (2% target, 3% stop, 7-day timeout) with no adaptation to the specific trade's characteristics. The data shows winners overshoot the target (avg winner +3.6% vs 2% T1), suggesting we're leaving alpha on the table, while 34.8% of trades exit via "reconciled_stale" (forced closure after timeout), suggesting the timeout mechanism is too blunt.

### 1.1 — Trailing Stop Mechanisms for Short-Duration Equity Trades

I need an exhaustive academic and practitioner review of trailing stop methodologies applicable to 2-15 day equity swing trades on large-cap stocks:

- **Chandelier exits** (Chuck LeBeau): ATR-based trailing from the highest high since entry. What ATR multiplier is optimal for 3-8 day holds on large-cap stocks? How does performance compare to fixed stops across different volatility regimes? Provide the exact formula and cite any backtesting results on S&P 100 or S&P 500 constituents.

- **Volatility-adjusted trailing stops**: Wilder's ATR trailing stop, Keltner Channel exits, Bollinger Band %B exits. For each, provide the formula, the academic evidence for or against, optimal lookback periods for swing trading, and any published Sharpe ratio comparisons vs fixed stops.

- **Parabolic SAR as exit signal**: Is Parabolic SAR useful for swing trade exits? What acceleration factor / max acceleration parameters work for 3-8 day holds? Cite Wilder's original work and any modern empirical validation.

- **Time-decay exits**: The concept of tightening the stop as the trade ages — e.g., move stop to breakeven after day 3, trail by 1 ATR after day 5, force exit at day 7. Is there academic support for time-based stop tightening? What is the optimal schedule for a strategy with 3.5-day average hold?

- **Glabadanidis (2015)** and any other academic papers specifically studying trailing stop optimization on equity portfolios. What were the key findings? Did trailing stops improve Sharpe ratio compared to fixed exits? What were the optimal parameters?

- **The "stop too tight" problem**: Research showing that tighter stops reduce average loss but increase loss frequency (more stopped out trades that would have recovered). What is the optimal stop distance for S&P 100 stocks with 1.5-3% daily ATR? Is there a universal relationship between ATR and optimal stop distance?

### 1.2 — Partial Profit-Taking and Scale-Out Strategies

- **Sell-half-at-T1, trail-the-rest**: What does the academic and practitioner literature say about partial exits? Does selling 50% at T1 and trailing the remainder improve risk-adjusted returns? Provide any backtesting evidence with effect sizes and Sharpe comparisons.

- **Three-tier exits**: 33% at T1, 33% at T2, 33% trailed. Is there evidence this outperforms all-at-T1 or all-trailed approaches? What are the transaction cost implications for ~$6,600 positions?

- **Keller and Keuning (2015)** or similar papers on optimal profit-taking thresholds. How should T1 and T2 be set relative to ATR? Is there a universal ratio (e.g., T1 = 1.5 ATR, T2 = 3 ATR, Stop = 1 ATR)?

- **The asymmetric payoff design**: How do you engineer a positive-skew return distribution through exit design? Academic work on "cutting losses short, letting profits run" — is there rigorous evidence that this actually improves Sharpe, or does it primarily improve Sortino/Calmar?

### 1.3 — ATR-Based Dynamic Bracket Sizing

The current system uses fixed percentage brackets regardless of the stock's actual volatility. AAPL with 1.2% daily ATR gets the same 2%/3% brackets as CAT with 2.8% ATR.

- **Optimal bracket sizing as a function of ATR**: What does the literature say about sizing stops and targets as ATR multiples? Provide specific ATR multiplier recommendations for large-cap equities with 2-8 day holding periods. Include research from both academic sources and practitioners (Turtle Trading rules, Van Tharp's work, Kaufman's adaptive methods).

- **Regime-conditional ATR multipliers**: Should brackets widen in high-VIX environments and tighten in low-VIX? My stress test data shows 0% win rate in crisis scenarios with fixed brackets. How should bracket parameters adapt to VIX regimes? Provide specific multiplier tables if available in the literature.

- **The ATR lookback period question**: 14-day ATR is standard. Is this optimal for 3-8 day swing trades? Would shorter (5-day, 7-day) ATR be more responsive? Any research comparing ATR lookback periods and their effect on exit quality?

### 1.4 — Exit Timing and Intraday Considerations

- **End-of-day vs intraday exits**: Does it matter whether stops are checked intrabar or only at close? For daily bracket orders, intraday wicks can trigger stops that would have recovered by close. Research on "close-only" stops vs "intrabar" stops for swing trades. What's the empirical difference in Sharpe?

- **The first-hour stop problem**: Stocks gap overnight, and the opening 30 minutes often has exaggerated moves that recover. Is there evidence for delaying stop-loss evaluation until after 10:00 AM? Or using wider intraday stops in the first hour?

- **Exit day-of-week effects**: Is there evidence that exits on specific days (e.g., Friday afternoon) have systematically different outcomes? Should the system avoid entering new positions on Thursday/Friday to avoid weekend risk on fresh trades?

---

## SECTION 2: ENTRY QUALITY SCORING AND TRADE SELECTION

The system currently enters every trade that the ranker qualifies and the LLM approves. There is no secondary quality filter that distinguishes "strong pullback setups" from "marginal pullback setups." I need to understand which entry-time features predict trade success.

### 2.1 — Feature Importance for Pullback Trade Success

- **Cross-sectional momentum factors** (Jegadeesh & Titman 1993, 2001): Which momentum features most strongly predict short-term (1-2 week) mean reversion success? Prior 1-month return? 3-month vs 1-month spread? 52-week high proximity? Provide specific factors with effect sizes and t-statistics from the original papers and the most cited replications.

- **RSI as entry quality signal**: Connors RSI, 2-period RSI, standard 14-period RSI. Which RSI variant most reliably identifies "exhausted pullbacks" that reverse within 3-8 days? What RSI threshold separates high-quality from low-quality pullback entries on large-cap stocks? Cite Connors, Alvarez, and Radtke's work on short-term RSI strategies.

- **Volume patterns at entry**: Is declining volume during the pullback (dry-up pattern) predictive of reversal? What about relative volume (current vs 20-day avg)? On-Balance Volume divergence? Cite Granville, Wyckoff volume analysis, and any modern empirical work on volume confirmation for mean-reversion entries.

- **Pullback depth and quality**: What pullback depth (measured as % from recent high) optimizes win rate for large-cap equities? Is a 3% pullback better than 5%? Is there a "too deep" threshold where pullbacks become trend reversals? Academic work on mean-reversion depth thresholds.

- **Market microstructure signals at entry**: Bid-ask spread widening, unusual options activity, dark pool prints, institutional order flow imbalance. Which of these are accessible to a retail trader via Alpaca/IB and have empirical support for predicting 3-8 day reversals? Focus on signals available without Level 3 market data or expensive alternative data.

- **Sector and correlation context**: Does the pullback being sector-wide (all tech stocks pulling back) vs idiosyncratic (one stock pulling back while sector is flat) affect win rates? Research on sector rotation momentum, industry momentum spillovers (Moskowitz & Grinblatt 1999), and cross-sectional pullback dispersion.

### 2.2 — Composite Entry Quality Scores

- **Multi-factor scoring models**: How should multiple entry features be combined into a single quality score? Linear combination with learned weights? Logistic regression? Decision tree? What does the literature say about combining technical signals for short-term trading? Cite any papers that build composite entry scores for swing trading.

- **Feature orthogonality**: Which commonly used technical indicators are actually measuring the same thing (e.g., RSI and stochastic are highly correlated)? What is the minimum set of orthogonal features that captures maximum predictive information for pullback reversal? Research on technical indicator redundancy and principal component analysis of common indicators.

- **Conviction-weighted entry**: If the composite entry quality score is reliable, should position size scale with score? Half-Kelly sizing based on edge estimate? Or binary (take/don't take) with fixed size? What does the academic optimal position sizing literature recommend for strategies with 50-200 trades/year and 55-70% win rates?

### 2.3 — The Selectivity vs Volume Tradeoff

- **How many trades should a pullback system take?** If I tighten entry criteria to improve win rate from 65% to 75%, I'll take fewer trades. What is the Sharpe-optimal number of trades per year for a single-strategy swing system? Is there an analytical solution relating win rate, avg win/loss ratio, trade frequency, and Sharpe?

- **The Sharpe ratio decomposition**: Sharpe = (mean × √N) / std, where N is trades/year. Improving mean by reducing trade count can decrease √N. What's the crossover point? Provide the mathematical framework for optimizing the trade-frequency/win-rate tradeoff.

- **Research on optimal trade selection rates**: What fraction of "qualified" setups should a system actually trade? Is there evidence from systematic trading literature on optimal selection rates (e.g., top 10% of scored setups vs top 50%)?

---

## SECTION 3: DRAWDOWN CONTROL AND ADAPTIVE EXPOSURE

The system currently has no mechanism to reduce exposure during portfolio-level adversity. All 15 positions run simultaneously with equal weight regardless of portfolio performance, position correlation, or market conditions.

### 3.1 — Portfolio Heat and Dynamic Position Count

- **Van Tharp's portfolio heat concept**: Total portfolio risk = sum of individual position risks. If each position risks 2% (stop distance), 15 positions = 30% portfolio heat. What does the literature say about optimal portfolio heat for swing trading? What maximum portfolio heat preserves drawdown limits while maintaining return potential?

- **Dynamic position count based on portfolio state**: Research on reducing position count (e.g., 15 → 10 → 5) when the portfolio is in drawdown. What triggers should be used? Cumulative P&L below X%? N consecutive losses? Correlation spike? Provide specific frameworks with backtested evidence.

- **The "portfolio lockdown" concept**: Is there evidence for completely halting new entries when drawdown exceeds a threshold (e.g., >8%), and resuming only after recovery to a higher level (e.g., -4%)? How does this compare to gradual position count reduction?

### 3.2 — Correlation and Concentration Risk

- **Intra-portfolio correlation management**: With 15 concurrent positions in S&P 100 stocks, correlation is inherently high (most move with SPY). What does the literature say about optimal correlation management for concentrated equity portfolios? Should the system limit sector exposure (e.g., max 3 positions in Technology)?

- **Beta-adjusted position sizing**: Instead of equal-weight, should positions be sized inversely to their beta? A 0.8-beta utility stock gets a larger allocation than a 1.5-beta tech stock to equalize risk contribution. Research on risk parity at the position level for equity portfolios. Cite Roncalli (2013) and related work.

- **Pair correlation monitoring**: If 8 of 15 positions are in correlated pullbacks (e.g., entire market sold off), the portfolio is effectively a 2-3 position bet on market recovery. What correlation threshold should trigger position reduction? How should the system measure and respond to realized correlation spikes?

### 3.3 — Regime-Adaptive Exposure Sizing

- **VIX-based exposure scaling**: Research on reducing total exposure when VIX exceeds certain thresholds. What VIX levels correspond to optimal exposure reduction? Linear scaling (exposure = max(0.3, 1 - VIX/50))? Step function (full exposure <20, 50% at 20-30, 25% at 30+)? Provide specific VIX-exposure mappings with historical validation.

- **Market breadth filters**: Percentage of S&P 100 above 50-day MA, advance-decline line, new highs vs new lows. Which breadth indicators are most useful for timing exposure changes? What thresholds signal "reduce exposure" vs "increase exposure"?

- **Keller's Vigilant Asset Allocation** and related adaptive allocation frameworks. How applicable are these to a single-strategy equity system? Can the protection mechanism (shifting to cash when momentum signals deteriorate) be adapted for position count management?

- **Turbulence index (Kritzman & Li 2010)**: Mahalanobis distance measuring how unusual current market conditions are relative to history. Is this a practical real-time signal for exposure reduction? How is it computed, and what threshold triggers defensive positioning?

### 3.4 — Maximum Adverse Excursion (MAE) Analysis

- **John Swagerman / John Ehlers MAE framework**: Using the maximum adverse excursion (largest intraday drawdown) of winning trades to calibrate stop placement. If 95% of eventual winners never draw down more than X%, set the stop at X%. Provide the methodology, the math, and examples of MAE-based stop calibration from the literature.

- **MAE/MFE analysis for position management**: Maximum Favorable Excursion tells you how much winners run before reversing. If MFE data shows 80% of winners peak at +4% before pulling back to close at +2.5%, a trailing stop at peak-1.5% captures more profit. How should MAE and MFE distributions inform exit rules?

- **Conditional MAE**: Does MAE distribution differ based on entry quality? Do higher-scored entries have shallower MAE (tighter stops viable)? This would enable score-dependent bracket sizing — tighter stops on high-conviction entries, wider on marginal ones.

---

## SECTION 4: INNOVATIONS AND UNEXPLORED EDGES

I'm looking for ideas that go beyond textbook approaches. What are the cutting-edge or underexplored techniques that could give a small systematic trader a structural advantage?

### 4.1 — Machine Learning for Dynamic Exit Optimization

- **Reinforcement learning for exit timing**: Research on training RL agents (DQN, PPO, SAC) to optimize trade exit decisions. Has anyone demonstrated RL-based exits outperforming rule-based exits on equity swing trades? Cite specific papers with Sharpe comparisons. What state space and reward function design works for this problem?

- **Survival analysis for trade duration**: Modeling trade outcomes as a survival problem — what is the hazard rate of a trade "dying" (hitting stop) as a function of time, entry features, and market conditions? Cox proportional hazards model applied to trade exits. Has anyone published this approach for systematic trading?

- **Bayesian online learning for bracket adaptation**: Starting with prior bracket parameters and updating them in real-time based on incoming trade outcomes. Thompson sampling or Bayesian optimization over bracket parameters. Research on online parameter optimization for trading systems.

### 4.2 — Microstructure Signals for Entry Timing

- **VPIN (Volume-Synchronized Probability of Informed Trading)**: Easley, López de Prado, and O'Hara's flow toxicity metric. Is it useful as an entry timing signal for large-cap pullback trades? Can it differentiate "informed selling" (avoid) from "noise selling" (enter)? Provide the computation method and empirical results.

- **Kyle's Lambda (price impact coefficient)**: Daily estimation of market maker adverse selection. Research on using Lambda changes as contrarian signals — increasing Lambda during a pullback may indicate temporary liquidity withdrawal rather than fundamental revaluation. Any published results on large-cap equities?

- **Options-implied signals for entry timing**: Put/call ratio, skew, term structure. Research on using options market data to time equity entries. Does elevated put skew during a pullback predict faster recovery (too much fear) or continued decline (informed hedging)?

### 4.3 — Portfolio Construction Innovations

- **Risk budgeting with conditional drawdown**: Instead of equal-weight, allocate a fixed "drawdown budget" to each position and size accordingly. Positions with tighter stops (lower max loss) get larger allocations. Research on Conditional Value-at-Risk (CVaR) based position sizing for equity portfolios.

- **Cross-sectional signal stacking**: If 5 stocks all show pullback setups on the same day, is it better to take all 5 (diversification) or just the top 1-2 (concentration in highest-quality)? Research on optimal number of concurrent mean-reversion positions and the diversification-quality tradeoff.

- **Dynamic hedging with index options**: At what portfolio size does buying SPY puts as tail-risk protection become cost-effective? What delta and tenor optimize the protection/cost ratio? Research on protective put strategies for concentrated equity portfolios, with specific cost analysis for $100K-$500K portfolio sizes.

---

## OUTPUT FORMAT

For each topic above, provide:

1. **The definitive academic citation(s)** with author, year, journal, and key finding with effect size
2. **The specific formula or algorithm** (not just a description — the actual math)
3. **Optimal parameters** for S&P 100 stocks with 3-8 day holding periods, if available in the literature
4. **Sharpe ratio impact** — estimated or measured improvement from each technique
5. **Implementation complexity** — can this be built in a weekend sprint or does it require months of infrastructure?
6. **Interaction effects** — how does this technique interact with the others? Do trailing stops and dynamic position sizing compound, or does one subsume the other?

Prioritize findings that are:
- **Empirically validated** on liquid US equities (not just forex, futures, or crypto)
- **Applicable at small scale** ($100K-$500K, no market impact)
- **Mechanically implementable** (no discretionary judgment required)
- **Novel or underutilized** — edges that most retail and small systematic traders miss

I am specifically NOT interested in:
- General portfolio theory (Markowitz, CAPM) without actionable trading rules
- High-frequency techniques requiring co-location or sub-second execution
- Strategies that require leverage >2x
- Options strategies beyond simple protective puts (the options desk is Phase 3)
- Cryptocurrency or forex applications
