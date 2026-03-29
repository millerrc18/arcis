# AI-powered options trading: from first principles to production

**Credit spreads and iron condors are the optimal starting strategies for Halcyon Lab's $500–$5K options system, with the LLM serving as a "volatility analyst" while rules-based logic handles trade construction and execution.** This architecture is strongly supported by academic literature from 2020–2026 showing that ML models add genuine value in volatility surface prediction and earnings analysis, but that strike selection and position management belong to deterministic systems. The most important immediate action is not building the options trading system — it's collecting options data today and feeding options-derived signals into the existing equity pullback strategy. Every day of IV surface data you collect compounds in value, and options flow signals can enhance equity returns within weeks rather than months.

---

## Part 1: The academic evidence points to volatility surfaces, not price prediction

The most active and productive area of ML-options research since 2020 is **volatility surface prediction**, not directional options trading. Kelly, Kuznetsov, Malamud, and Xu (2023) used CNN image-recognition techniques on IV surfaces to predict the cross-section of stock returns, finding that **predictive information from IV surfaces is essentially uncorrelated with existing option-implied characteristics** and delivers higher Sharpe ratios — with performance increasing in ensemble size. Bloch and Böök (2021) demonstrated that ConvLSTM models systematically outperform naive approaches for long-term IV surface forecasts, confirming that surface dynamics are dominated by trend and mean reversion and are therefore predictable.

The second major research strand is **deep hedging via reinforcement learning**. Cao, Chen, Hull, and Poulos (2021) showed that RL agents consistently outperform Black-Scholes delta hedging in frictional environments, particularly at transaction costs of 1–3%. This finding has been replicated across 17+ studies (Pickard & Lawryshyn, 2023), with DDPG emerging as the dominant algorithm for continuous action spaces.

The most directly relevant paper for Halcyon's S&P 100 universe is Tan, Roberts, and Zohren (2024), "Deep Learning for Options Trading: An End-to-End Approach" from ICAIF '24. Their end-to-end deep learning system for S&P 100 options demonstrated significant improvements in risk-adjusted performance, with a critical finding: **mean-reversion strategies significantly outperformed momentum strategies**, and models that accurately predict returns do not necessarily guarantee superior strategy performance. This confirms the need to evaluate strategies on risk-adjusted P&L, not prediction accuracy alone.

Several things have been debunked or shown to be fragile. Momentum-based options strategies are generally unprofitable. Simple neural networks underperform Black-Scholes during turbulent market regimes. Static risk measures in RL hedging produce optimistic bias. Overfitting risk is real and severe with limited options data — any backtest showing a Sharpe above 3.0 should be treated with deep suspicion.

The neural network pricing literature shows that **ANN models reduce mean absolute error by 64% versus Black-Scholes** for mid-priced options (De Souza Santos & Ferreira, 2024), and a BSANN hybrid provides the most accurate estimation across 8 pricing models tested. However, neural nets underperform Black-Scholes during turbulent periods — making regime awareness essential rather than optional.

## Three strategies match Halcyon's constraints exactly

For a $500–$5,000 account operated by a solo developer with an existing equity pullback system and fund aspirations, three strategies rise to the top after evaluating all candidates across capital requirements, complexity, risk profile, LLM value-add, and academic evidence.

**Bull put credit spreads should be the primary strategy.** They are the natural options expression of the pullback strategy's directional signals. A $5-wide spread requires only $500 maximum risk per contract, making them viable from day one. The LLM adds genuine value in timing entries (IV rank assessment, regime context, earnings avoidance), while strike selection follows mechanical rules (16–20 delta short strikes, spread width based on account risk budget). Win rates of 70–80% are typical when selling at elevated IV percentile, and the defined-risk nature prevents catastrophic losses. At $2,000 capital, you can safely manage 2–3 simultaneous positions with $150–250 risk each.

**Iron condors on SPY/QQQ fill the gap when the pullback strategy is inactive.** Range-bound markets — where the equity system finds no setups — are precisely when iron condors generate theta income. Target 30–45 DTE, 16–20 delta short strikes, $5-wide wings. Expected return runs 20–50% on risk per trade with 70–85% win rates. The LLM assesses whether range-bound conditions are likely to persist and identifies risks to the range. At $5,000 capital, iron condors with $300–$700 risk per position become comfortable.

**Calendar spreads and Poor Man's Covered Calls (PMCC) provide the third leg.** A PMCC — buying a deep ITM LEAPS call and selling near-term OTM calls against it — requires only $400–800 per position on sub-$50 stocks. This exploits term structure (selling expensive near-term vol, owning cheaper long-term vol) and works well in low-vol environments when iron condors offer thin premiums. The LLM's term structure analysis directly informs entry timing.

Strategies eliminated for this capital level include covered calls and cash-secured puts (require $3,000–$30,000 for 100 shares of quality stocks), the wheel strategy (same capital problem plus 100% concentration risk), volatility arbitrage and dispersion trading (institutional capital and infrastructure requirements of $100K+), and naked options of any kind (unlimited risk is incompatible with small accounts and fund obligations).

### How each strategy complements the equity pullback system

The strategies map cleanly to market regimes. During strong trends with pullbacks, the equity system is active and bull put spreads confirm entries — when the pullback model signals a buy, simultaneously selling an OTM bull put spread collects premium if the stock bounces as predicted while providing a defined-risk alternative. During strong trends without pullbacks, the equity system waits while iron condors generate theta income on range-bound sectors. During regime transitions, protective puts hedge equity positions — the LLM detects uncertainty (Fed meetings, weakening trends) and recommends cheap OTM puts as tail insurance. During range-bound markets, the equity system is fully inactive while iron condors and calendar spreads provide the entire income stream. During earnings season, the LLM identifies mispriced IV for selective straddle/strangle plays.

### Capital scaling path

The realistic progression runs: **$500** → one credit spread at a time → **$2,500** → 2–3 simultaneous credit spreads → **$5,000** → add iron condors and PMCC → **$10,000** → full multi-strategy portfolio → **$25,000+** → overcome PDT restrictions, run diversified strategy suite. Below $1,000, the math barely works for defined-risk spreads; the minimum viable options trading account for credit spreads is realistically **$2,000**. At $500–$1,000, paper trade the system while growing capital through the equity strategy.

## The LLM's highest-value role is volatility analyst, not trade constructor

Kim, Muhn, and Nikolaev (2024) from Chicago Booth demonstrated that **GPT-4 outperforms median financial analysts in predicting earnings direction** from anonymized financial statements, achieving ~60.4% accuracy — on par with specifically trained ANN models. More importantly, combining ANN and GPT text outputs pushed accuracy to 63.2%, higher than either alone. This complementarity finding directly validates the "LLM as volatility analyst" architecture.

The recommended architecture separates responsibilities cleanly. The LLM layer handles strategic posture: bullish/bearish/neutral on volatility, regime identification, earnings event assessment, IV mispricing narrative, and risk scenario analysis. It answers the "what" and "why" — the trade thesis and market context. The rules-based layer handles trade construction: strike selection, spread width, position sizing, Greeks management, stop-loss triggers, and rolling decisions. It answers the "how" — exact parameters and execution.

This separation is validated by the "New Quant" survey (arXiv 2510.05533), reviewing 84+ papers, which found that language signals add value around identifiable events and narrative changes, with earnings call analysis mattering most at announcement and in following days. The survey explicitly recommends that "the portfolio should separate signal generation from allocation and risk, and should include materiality filters, confidence gating, and exposure controls."

Where the LLM adds genuine value, ranked by evidence strength: **Earnings event analysis** (very high — parsing 10-K, conference calls, guidance for volatility positioning) sits at the top. **Regime context for vol positioning** (high — "this environment resembles Q4 2018") and **cross-asset signal synthesis** (high — combining macro, sector, and individual stock signals) follow. **Trade thesis generation** is a native LLM strength. Where the LLM should not be trusted: strike/expiration selection (pure quant is better), delta hedging decisions (RL dominates), and any calculation requiring numerical precision.

### Training data pipeline for multidimensional options outcomes

Options outcomes create a unique training challenge: a trade can be right on direction but wrong on timing (expires worthless before the move happens), right on volatility but wrong on direction (straddle wins but spread loses), or right on thesis but wrong on magnitude (move too small for premium paid). The recommended quality rubric scores five dimensions independently: **directional thesis** (25% weight, scored against realized price change), **volatility assessment** (25%, IV rank identification and vol regime classification), **strategy selection** (20%, was the recommended strategy appropriate given realized outcome), **timing and catalyst identification** (15%, did identified catalysts occur), and **risk calibration** (15%, were position sizing and stop levels appropriate). Crucially, score process quality separately from outcome quality — a well-reasoned analysis that loses money due to a tail event should still score well on process dimensions.

## Passive data collection architecture: start free, scale deliberately

The data pipeline should begin immediately with zero cost and scale as the system matures. The core principle: **every day of IV surface data you collect is irreplaceable** — you cannot buy back the specific snapshots of your target universe that you missed.

### What to collect and how often

End-of-day snapshots are the minimum viable starting point and sufficient for 90% of strategy research on swing-trade timescales. For each of the S&P 100's ~200,000 option contracts (100 underlyings × 20 expirations × 50 strikes × 2 call/put), capture: bid, ask, mark, volume, open interest, implied volatility, delta, gamma, theta, vega, underlying price, days to expiration, and in-the-money flag. Add one midday snapshot to capture overnight gap effects and intraday IV mean reversion — this doubles data volume for minimal incremental effort.

Supplement with VIX term structure (VIX, VIX3M, VIX9D — free from CBOE), underlying OHLCV for realized volatility calculations, and derived unusual activity flags (volume/OI ratio > 2.0 at specific strikes).

### Phased data source progression

**Months 1–3 ($0/month):** Build a Python scraper using `yfinance` for daily EOD options chains on S&P 100, supplemented by Polygon.io's free tier (5 API calls/minute, 2-year history). Store in SQLite using partitioned databases (one .db file per month). Expected storage: **~3 GB for 3 months** uncompressed. This phase validates the pipeline and schema before spending money.

**Months 4–6 ($29/month):** Upgrade to Polygon.io Starter for unlimited API calls with Greeks and IV. Add the midday snapshot. Begin SVI curve fitting per expiration slice and store the 5 parameters alongside raw data. Expected cumulative storage: ~8 GB.

**Months 7–12 ($79–99/month):** Either Polygon.io Developer ($79/mo) for raw data depth or ORATS ($99/mo) for pre-computed analytics, smoothed IV surfaces, 100+ proprietary indicators, and backtesting with data back to 2007. Migrate to PostgreSQL + TimescaleDB for concurrent read/write access and native time-series compression. Expected cumulative storage: ~20–25 GB before compression, ~5 GB compressed.

**When ready to backtest ($2,000 one-time):** Purchase ORATS historical data (2-minute snapshots from 2015-present) or use Databento pay-per-use batch downloads for deep historical backfills.

**Total annual steady-state cost: $948–$1,188/year** — well within the starting capital budget, with most spending deferred until the pipeline proves reliable.

### Storage: SQLite works for now, TimescaleDB is the target

SQLite handles EOD collection up to ~50 GB without trouble and is already in the Halcyon stack. The single-writer lock becomes problematic when concurrent collection and querying are needed, but for the first 6 months of EOD snapshots this is a non-issue. TimescaleDB (a PostgreSQL extension) is the ideal target: hypertables auto-partition by time, compression achieves **90%+ reduction** (12 GB → ~1.2 GB), and `time_bucket()` provides native time-series aggregations. Migration from SQLite is straightforward — export CSV, import to hypertable. The migration should happen around month 6 when data exceeds 10 GB or concurrent access becomes necessary.

### IV surface representation: store both raw and parametric

Store the raw grid (bid/ask/mid IV by strike × expiry — ~48 MB/day) alongside fitted SVI parameters (5 parameters per expiration slice — ~80 KB/day). Raw data is irreplaceable; fitted parameters enable fast querying and feature extraction. Start with SVI (Gatheral, 2004) — parsimonious, fast calibration, fits single-expiry smile well. Graduate to SSVI for cross-maturity consistency once comfortable. The extractable features that matter most for trading: **skew steepening/flattening** (bearish/bullish sentiment shift), **term structure inversion** (market expects imminent move), **IV-RV spread** (volatility risk premium magnitude), and **ATM IV term structure slope** (shape changes signal market stress).

### Backtesting requires brutal realism about options-specific pitfalls

The single most dangerous pitfall is **bid-ask spread assumptions**. Using mid-price for entry and exit dramatically overstates profitability. For S&P 100 ATM options, spreads run $0.01–$0.05 (penny pilot), but OTM options can have $0.10–$1.00+ spreads that widen further during selloffs — exactly when you need to close. Use a "realistic fill" model: assume you fill 25–40% from mid toward the unfavorable side. ORATS recommends rejecting any backtest trade where bid-ask/strike exceeds 1%.

Liquidity filters must be enforced: only backtest on contracts with >100 OI and >50 daily volume. The "picking up nickels" problem is real — short premium strategies show smooth equity curves with 80–90% win rates in backtests, then catastrophic losses in tail events. The 2018 Volmageddon event caused 50–90% drawdowns in short-vol strategies; the 2020 COVID crash saw SPY fall 34% in 23 trading days. **Always include 2008, 2020, and 2022 in backtest periods.** Pin risk near expiration is another silent killer: a short option ATM at expiration creates assignment uncertainty that can produce losses 100x the premium received. Close all positions within $0.25 of strike by 3 PM on expiration day.

## Feature engineering: five features deliver most of the value

The volatility risk premium (VRP) — the spread between implied and realized volatility — is the **single most well-documented predictive feature** in options. It averages ~4 volatility points for the S&P 500 since 1990, rising to >6.5 points post-2020. Bollerslev, Tauchen, and Zhou (2009) showed the variance risk premium predicts future equity returns, and AQR research confirms a Sharpe ratio of ~1.0 on the short-vol component. Calculation is trivial: ATM 30-day IV minus 20-day trailing realized volatility.

**IV percentile** (the percentage of days over the past 252 trading days when IV was lower than today's level) is preferred over IV rank because it's robust to single-day spikes. Above 70% signals an expensive premium environment favoring selling; below 30% signals cheap options favoring buying. **IV skew** (25-delta put IV minus 25-delta call IV) captures directional sentiment and tail risk pricing — steepening put skew signals institutional hedging demand. **Earnings implied move** (ATM straddle price / stock price) compared to historical actual earnings moves identifies mispriced event risk. **Put/call volume ratio** serves as a sentiment confirmation filter.

These five features — VRP, IV percentile, IV skew, earnings implied move, and put/call ratio — are all computationally trivial on the RTX 3060 and have moderate-to-strong academic predictive evidence. Gamma exposure (GEX) and max pain theory are second-tier features to add once the system is stable; GEX requires full intraday options chain data that adds cost and complexity, and max pain is primarily useful only during expiration week.

### Greeks must serve two masters through architectural separation

The system must cleanly separate Greeks used for **trade decisions** (feature Greeks) from Greeks used for **position management** (portfolio Greeks). The trade decision module uses per-position Greeks as features: delta expresses directional view, gamma-to-theta ratio measures trade quality, vega informs positions based on IV forecast. The risk governor module monitors aggregate portfolio Greeks: total portfolio delta (directional exposure), portfolio vega (sensitivity to vol shifts), portfolio theta (daily decay P&L), and portfolio gamma (how fast exposure changes). The cardinal rule: **the risk governor overrides trade decisions, never the reverse.**

## The equity risk governor needs 7 new checks for options

The existing 8-check equity risk governor provides a solid foundation, but options' non-linear payoffs, time decay, assignment risk, and margin dynamics require substantial expansion. Of the original 8 checks, emergency halt and duplicate prevention translate directly. Daily loss limits need modification to account for unrealized Greeks-based P&L and theta decay. Position size limits need complete redesign because "X% of capital" ignores non-linear payoff profiles. The volatility circuit breaker needs reconceptualization — in options, volatility is the primary trading variable, not merely a risk filter.

### 15-check options risk governor

The expanded risk governor operates in three tiers. **Tier 1 (hard stops)** includes the emergency halt, daily loss limit at **-3% of account value** (including unrealized Greeks-based P&L), margin safety rejecting any trade pushing utilization above 50% of account, and maximum loss verification ensuring no single trade's theoretical max loss exceeds the position risk budget. **Tier 2 (portfolio limits)** enforces portfolio delta below 30% of account value in SPY-equivalent terms, portfolio vega below 2–3% of account per 1-point IV move, portfolio theta income below 0.5% of account daily (preventing over-leveraged theta strategies), and portfolio gamma awareness tracking whether the portfolio amplifies or dampens moves. **Tier 3 (position-level checks)** manages individual position sizing at 2–5% of account, maximum simultaneous positions (1 at $500, 2–3 at $2K, 3–5 at $5K), liquidity verification requiring minimum 100 OI and bid-ask spread below 15% of mid-price, sector concentration below 30%, expiration management with mandatory close or roll at 7 DTE for short options, and volatility regime awareness adjusting all limits based on VIX level (reduce short premium position limits by 50% when VIX is below 15; shift to defensive mode with 50% normal position sizes when VIX exceeds 35).

### Position sizing and risk of ruin at small account sizes

The Kelly criterion adapted for credit spreads with a typical 70% win rate and 1:2 risk/reward yields a full Kelly fraction of ~10%. **Half Kelly (5% per trade) captures 75% of optimal growth with 50% less drawdown** and is the recommended maximum for accounts above $2,000. Quarter Kelly (2.5%) is appropriate for $500–$2,000 accounts. The position sizing formula: `max_contracts = floor(account_value × kelly_fraction / max_loss_per_contract)`, where max_loss_per_contract = (spread_width × 100) - (credit_received × 100).

Risk of ruin is the existential threat at small account sizes. At $2,000 risking 5% ($100) per trade, 10 consecutive max losses produce a 50% drawdown requiring 100% gain to recover. Monte Carlo simulations show that at 5% risk per trade with 70% win rate, there's a **~25% probability of reaching a 30% drawdown** — unacceptable for a fund model. At 3% risk, this drops to ~8%. At 2%, below 3%. The recommendation: cap risk per trade at 3–5% maximum loss basis, and at small account sizes err toward the lower end. Iron condors deserve extra caution — their 70–80% win rate masks fat tail losses that arrive in clusters during vol regime shifts.

## Architecture: shared database, separate modules, switchable LoRA adapters

The optimal architecture for a solo developer is **shared database and dashboard with separate strategy modules** (Option A from the evaluation). This reuses existing FastAPI, React, and Alpaca infrastructure while keeping equity and options logic in separate Python packages. Estimated 40–60% less new code versus building a separate system. Risk isolation is achieved through separate database tables and per-strategy risk limits rather than physical system separation.

The code structure extends naturally:

```
halcyon/
  strategies/
    equity/         # existing pullback-in-trend
    options/        # new options strategies
  core/
    data_pipeline.py
    risk_manager.py  # shared risk governor with strategy-specific checks
    alpaca_client.py # handles both equity & options orders
  dashboard/         # React 18 — add options tab
```

### Single Qwen3 8B with switchable LoRA adapters solves the model problem

Running two separate models simultaneously on the RTX 3060's 12GB VRAM is not feasible — two Q4_K_M models would consume ~10–11GB, leaving nothing for KV caches. The solution is a **single base Qwen3 8B (Q4_K_M quantization, ~5GB VRAM)** with switchable LoRA adapters. Each adapter is tiny (10–50MB) and loads in milliseconds. Train separate equity and options adapters, keeping the base model frozen. This prevents catastrophic forgetting — research (arXiv 2401.05605) shows LoRA doesn't fully prevent forgetting during sequential fine-tuning, but the adapter isolation pattern (never merging adapters) preserves base model knowledge. The remaining ~7GB VRAM supports 4K–8K context windows at ~40 tokens/second, sufficient for non-latency-critical trading decisions.

### Alpaca supports options including paper trading

Alpaca provides full multi-leg options support (Level 3: spreads, straddles, iron condors), commission-free options for retail, paper trading with options enabled by default, real-time and historical options data with Greeks and IV, and up to 1,000 API calls/minute. The key limitation: **no bracket orders for options** — exit management must be built into the FastAPI backend as a position monitoring daemon. Alpaca does not support index options (SPX, VIX) — only US equity and ETF options. For eventual SPX/XSP trading (desirable for tax advantages), Interactive Brokers is the gold standard alternative.

### Exit management replaces bracket orders

Since Alpaca lacks bracket orders for options, the system needs a programmatic exit management framework running as a background process. For credit spreads: close at 50–80% of max credit captured (profit target), close at 2–3x initial credit (stop loss), close at 7–14 DTE regardless of P&L (time exit), close when short strike delta exceeds 0.40 (delta stop), and close when earnings or FOMC fall within 5 days (event exit). For iron condors: close both sides at 50% total credit, close the threatened side when price approaches a short strike, and close the full position below 7 DTE. For directional plays: close at 50–100% gain on debit (take profits quickly due to theta decay), close at 50% loss (preserve capital), and close when the equity model reverses its directional signal.

## Tax optimization strongly favors index options

Section 1256 contracts receive **60/40 tax treatment** — 60% taxed as long-term capital gains (max 20%) and 40% as short-term (max 37%), regardless of holding period. This produces a blended effective rate of ~26.8% versus up to 37% for equity options taxed entirely at short-term rates. On $100K profit, this saves approximately **$10,200**. Section 1256 applies to SPX, XSP (Mini-SPX), NDX, RUT, and VIX options — but critically, **not** to ETF options (SPY, QQQ, IWM) even though they track the same indices.

XSP (Mini-SPX, 1/10th notional of SPX) is particularly suited for small accounts — same 60/40 tax treatment but requiring less capital per contract. Additional 1256 benefits include mandatory mark-to-market (simpler year-end reporting via Form 6781), 3-year loss carryback (unique to 1256 — the only remaining carryback opportunity), and general exemption from wash sale rules. The strategic implication: as capital grows, **migrate from equity options (SPY) to index options (XSP/SPX)** for both tax efficiency and European-style exercise (no early assignment risk). Do not elect Section 475(f) mark-to-market for Trader Tax Status if primarily trading index options — it converts all gains to ordinary income, destroying the 60/40 benefit.

For fund structure, start with a **single-member LLC** trading personal capital. Convert to multi-member LLC when accepting outside investors. State RIA registration is required below $100M AUM when managing others' money. Fund launch costs run $40,000–$70,000 (legal documents, compliance, administration) — defer this until you have a proven track record.

## Five innovation opportunities nobody is pursuing well

**First, LLM reasoning combined with systematic options execution is genuinely novel.** Current platforms offer either rule-based automation without reasoning (Option Alpha, TastyTrade's mechanical approach) or AI signal generation without options-specific execution (Trade Ideas, Tickeron). Halcyon's combination — Qwen3 8B reasoning about market context and volatility regime feeding structured strategy selection into systematic execution with rule-based exit management — does not exist in the market today.

**Second, using options market data as signals for equity trading before building options trading.** This is the highest-value near-term project. Rising IV rank on a stock where the equity model sees a pullback-in-strong-trend setup confirms the setup — smart money is positioning for a move. Steepening put skew signals institutional hedging demand (bearish), while flattening skew or emerging call skew signals bullish positioning. Unusual options activity (volume >3x open interest at specific strikes) often precedes significant equity moves. Implementation takes 6–8 weeks and immediately enhances the existing equity system at zero additional cost using Alpaca's included options data.

**Third, earnings transcript analysis cross-referenced with options positioning.** The LLM parses conference calls and 10-K filings for sentiment and forward guidance, then cross-references with current IV, skew, and open interest to identify mispriced earnings risk. This extends Kim et al.'s finding that LLMs predict earnings direction better than analysts into the options domain specifically.

**Fourth, regime-aware volatility trading via LLM historical analogy.** The LLM identifies which historical environment the current market most resembles ("this resembles Q4 2018 — elevated vol with mean reversion likely") and maps that to optimal volatility strategy ("sell premium with wide wings and tight profit targets"). This goes beyond VIX-level heuristics into reasoning about why the regime is what it is.

**Fifth, the competitive landscape has clear gaps.** Unusual Whales provides excellent flow data and even offers an MCP server for AI integration ($35–48/month). Option Alpha provides no-code automation but no Python API or LLM integration. TastyTrade offers a proven mechanical methodology (45 DTE entry, 50% profit target, 21 DTE exit) but no AI reasoning layer. QuantConnect's LEAN engine supports options backtesting but lacks LLM integration. No platform combines all three elements — natural language reasoning, quantitative feature engineering, and systematic options execution.

## Realistic timeline: 12–18 months from research to first live trade

**Phase 1 — Passive data collection and options-as-equity-signal (Months 1–3):** Start collecting daily EOD options chain snapshots via yfinance. Build IV percentile, skew, and flow metrics for S&P 100. Feed options-derived features into the existing equity model as additional inputs. Open Interactive Brokers account for eventual index options access. Begin reading Natenberg's "Option Volatility & Pricing." Cost: $0/month.

**Phase 2 — Education and strategy research (Months 3–6):** Complete core reading (Natenberg, then Sinclair's "Volatility Trading" and "Positional Option Trading"). Upgrade data pipeline to Polygon.io Starter ($29/month). Begin SVI curve fitting and VRP calculations. Paper trade simple credit spreads on Alpaca. Identify 2–3 candidate strategies for backtesting. Cost: $29/month.

**Phase 3 — Feature engineering and backtesting (Months 6–9):** Build options backtesting framework with realistic bid-ask spread assumptions and transaction costs. Purchase ORATS historical data or Databento backfill ($2,000). Migrate to TimescaleDB. Backtest across 2007–present including all major stress periods. Walk-forward out-of-sample validation. Target metrics: Sharpe 1.0–2.0, max drawdown below 20%, profit factor 1.5–2.0. Cost: $79–99/month + $2,000 one-time.

**Phase 4 — Model training and paper trading (Months 9–12):** Train options LoRA adapter for Qwen3 8B using multidimensional rubric scoring. Build structured JSON output pipeline. Implement 15-check risk governor. Paper trade via Alpaca with live market data for minimum 3 months. Go/no-go criteria: paper results within 70% of backtest performance, no unexpected large drawdowns, system handles edge cases (earnings, ex-div, market halts).

**Phase 5 — Live with small capital (Months 12–15+):** Start with $1,000–$2,000 and 1 contract at a time. Use XSP if index options are accessible via IBKR. Scale slowly — double position size only after 2 months of positive performance. Hard stop: if drawdown exceeds 20%, halt trading and review.

At 10–15 hours/week (realistic for a solo developer maintaining the equity system), **12–18 months from start to first live options trade** is the honest timeline. Rushing is the number one cause of failure in systematic options trading.

## Five mistakes that destroy AI options traders and how to prevent them architecturally

**Overfitting** is prevented by enforcing out-of-sample testing in the pipeline, limiting model parameters, using walk-forward analysis, and flagging any strategy with Sharpe above 3.0 for mandatory review. **Underestimating assignment, pin risk, and liquidity** is prevented by preferring European-style index options (XSP/SPX), building liquidity checks into entry criteria, and closing positions before expiration rather than holding to expiry. **Ignoring transaction costs** is prevented by including realistic costs in all backtests ($0.50–$1.00 per contract plus 5–20% of bid-ask spread as slippage) and rejecting strategies where costs exceed 20% of premium collected. **Selling naked premium without tail protection** is prevented by the architectural constraint of only using defined-risk strategies (spreads, not naked positions) and backtesting through 2008, 2020, and 2022. **Over-relying on Black-Scholes assumptions** is prevented by using implied volatility from market prices rather than model-derived "fair values" and building regime detection into the system rather than treating it as an afterthought.

## Start these five things today

**First, begin collecting EOD options chain snapshots for S&P 100 today.** Write a cron job running a yfinance scraper storing all strikes within ±30% of spot, all expirations ≤6 months, both calls and puts, in SQLite. This data cannot be acquired retroactively and compounds in value every day.

**Second, log VIX term structure daily** — VIX, VIX3M, VIX9D, and if possible VIX futures curve. Free from CBOE. Takes 5 minutes to set up.

**Third, build options-derived signals for the existing equity model.** IV percentile, put/call volume ratio, and skew slope for S&P 100 underlyings can be computed from the data you're already collecting and fed into the equity pullback model within weeks.

**Fourth, order Natenberg's "Option Volatility & Pricing"** and begin the 24-week education sequence (Natenberg → Sinclair "Volatility Trading" → Sinclair "Positional Option Trading" → Passarelli). Also download Colin Bennett's "Trading Volatility" (free PDF) for institutional-grade volatility concepts.

**Fifth, enable Alpaca paper trading for options** and start manually entering simple credit spread paper trades to build execution intuition. Track every trade with entry rationale, Greeks at entry, planned adjustments, actual outcome, and lessons learned. The goal is developing physical familiarity with options mechanics before the system trades autonomously.

## Conclusion

The path from Halcyon Lab's equity pullback system to a production options trading capability is long but well-defined. The academic literature strongly supports ML approaches to volatility surface prediction and premium selling strategies at small account sizes. The "LLM as volatility analyst" architecture — where Qwen3 8B provides strategic reasoning while deterministic rules handle trade construction — represents a genuine innovation that no existing platform offers. Credit spreads are the natural starting strategy, iron condors fill the gap during range-bound markets, and calendar spreads provide a third income stream.

The critical insight is sequencing: **options data collection and options-as-equity-signal should start immediately, months before any options trade is placed.** The data compounds, the equity system improves, and the developer builds volatility intuition organically. The tax advantages of index options (XSP/SPX) via Section 1256's 60/40 treatment are substantial enough to influence broker and strategy selection from the beginning. And the 15-check risk governor, with its portfolio Greeks limits, margin monitoring, and regime awareness, must be non-negotiable architecture — not an afterthought — because at $2,000–$5,000 starting capital, the margin between survival and account destruction is measured in position-sizing discipline.