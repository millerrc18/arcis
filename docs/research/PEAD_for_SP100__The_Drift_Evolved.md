# PEAD for S&P 100: the drift isn't dead, it evolved

**Traditional earnings-surprise drift has vanished from mega-cap stocks, but ML-enhanced and information-package variants remain exploitable with Sharpe ratios of 0.63–1.2.** The apparent contradiction between Martineau (2022) declaring PEAD dead and Kaczmarek & Zaremba (2025) reviving it resolves cleanly: single-quarter SUE-based drift disappeared for non-microcaps around 2006, but multi-quarter earnings pattern recognition and text-based surprise signals capture overlooked information that markets still underprocess. For Halcyon Lab, this means building a composite PEAD system that combines 12-quarter elastic net scoring, revenue-EPS concordance, analyst revision velocity, and earnings call NLP — not a simple beat/miss trigger.

---

## The contradiction resolved: two different PEADs

Three landmark papers define the current state of earnings drift. **Martineau (2022, Critical Finance Review)** examined price formation around earnings through ~2020 and found that for large stocks, PEAD has been non-existent since approximately 2006. Decimalization (2001) and Reg NMS (2005) enabled electronic arbitrage that eliminated the friction sustaining drift in liquid names. Both analyst-forecast-based and time-series surprise measures show the drift spread is statistically and economically indistinguishable from zero for the top quintile by market cap.

**Subrahmanyam (2025, SSRN)** confirmed this using data through December 2024. Replicating the earnings drift factor from Dickerson, Julliard & Mueller (2025, JFE forthcoming), the t-statistic with all stocks is 2.18 but drops to **1.43 (insignificant) when excluding microcaps**. Two recent papers claiming PEAD lives — Dickerson et al. (2025) and Hirshleifer, Peng & Wang (2025, RFS) — are contaminated by microcaps that represent ~3% of market value but are numerous enough to drive statistical results.

**Kaczmarek & Zaremba (2025, Finance Research Letters)** then showed that elastic net regression on 12 quarters of historical SUE nearly doubles Sharpe ratios from 0.34 to **0.63**, with **0.4% monthly alpha** surviving Fama-French 5-factor + momentum controls. Crucially, these gains are **strongest among large-cap stocks** — precisely where single-quarter SUE is priced in immediately but older earnings patterns remain overlooked. The model dynamically reweights historical quarters; recent-quarter SUE receives less weight in large-caps (already priced) while distant quarters receive more (overlooked trajectory information).

A parallel finding from **Meursault, Liang, Routledge & Scanlon (2023, JFQA)** shows that text-based surprise (SUE.txt), constructed via elastic net on earnings call word counts, generates **8.01% drift over 63 trading days** — far larger than classic PEAD in the same period. Simple tone-based analysis (Loughran-McDonald sentiment) produces only 1.11–2.87% drift, confirming that SUE.txt captures something richer than mere sentiment.

The resolution is conceptually clean. **"PEAD on the EPS number" is dead for S&P 100 stocks. "PEAD on the information package" — historical earnings trajectories, text signals, revenue concordance, and guidance revisions — remains alive.** The market efficiently processes the headline surprise within minutes but systematically underprocesses complex, multi-dimensional earnings information.

### Quantitative summary of exploitability

| Strategy variant | Works in S&P 100? | Sharpe / alpha | Evidence quality |
|---|---|---|---|
| Traditional 1-quarter SUE | **No** — dead since ~2006 | ≈ 0 for large-caps | Very strong (Martineau 2022, Subrahmanyam 2025) |
| 12-quarter elastic net SUE | **Yes** — strongest in large-caps | Sharpe 0.63, alpha 0.4%/mo | Strong (Kaczmarek & Zaremba 2025) |
| Text-based SUE.txt (earnings call NLP) | **Likely yes** | ~8% drift/63 days | Strong (Meursault et al. 2023, JFQA) |
| CNN visual earnings patterns | **Partially** | 3.6% spread/63 days | Moderate (Garfinkel, Hribar & Hsiao 2024) |
| Multi-signal composite (recommended) | **Yes** | Sharpe 0.9–1.3 est. | Supported by multiple papers |
| Revenue surprise alone | **Weak for large-caps** | Not significant at 6-mo horizon | Negative for large-caps (Jegadeesh & Livnat 2006) |

---

## Signal construction specification

### Core signal: 12-quarter elastic net SUE

The primary PEAD signal uses analyst-forecast-based SUE across 12 quarterly lags. The formula for current-quarter SUE is:

```
SUE_t = (EPS_actual - EPS_consensus) / σ(forecast_errors over prior 8 quarters)
```

For S&P 100 stocks with 20–30+ covering analysts, analyst-based consensus is far superior to time-series models. Livnat & Mendenhall (2006) showed analyst-forecast SUE generates significantly larger drift. **Finnhub's `company_earnings()` endpoint provides actual vs. estimate with pre-computed surprise for S&P 100 stocks**, adequate for implementation given high analyst coverage convergence across data sources. The key limitation is lack of historical consensus snapshots and individual analyst timestamps — critical for backtesting but not for live trading.

The elastic net model trains on features `[SUE_t-1, SUE_t-2, ..., SUE_t-12]` to predict next-quarter post-earnings return. Kaczmarek & Zaremba found that two decades ago, the latest surprise dominated model weights. Over time, older lags gained importance as fresh earnings news gets priced in faster. This temporal shift is precisely why the approach works best in large-caps.

```python
from sklearn.linear_model import ElasticNet

def build_sue_features(ticker: str, current_quarter: str, n_lags: int = 12) -> dict:
    features = {}
    for lag in range(1, n_lags + 1):
        q = quarter_offset(current_quarter, -lag)
        features[f'sue_lag_{lag}'] = get_historical_sue(ticker, q)
    return features

# Train quarterly with walk-forward: 12Q training, 1Q test, step 1Q
model = ElasticNet(alpha=0.1, l1_ratio=0.5)  # Tune via time-series CV
```

### Revenue-EPS concordance amplifier

Revenue surprises are more persistent than expense surprises. When EPS and revenue beat in the same direction (concordance), the earnings surprise likely reflects sustainable revenue growth rather than one-time expense management. Jegadeesh & Livnat (2006) found concordant signals predict future earnings confirmations, with the concordant hedge portfolio earning ~0.25% additional quarterly return. **A one-standard-deviation increase in revenue surprise associates with 9.1% higher announcement-window price reaction versus only 1.3% for GAAP EPS**, underscoring revenue's informational superiority.

```python
def concordance_score(eps_sue: float, revenue_sus: float) -> float:
    if np.sign(eps_sue) == np.sign(revenue_sus):  # Concordant
        return abs(eps_sue) * 1.3  # Amplify
    return abs(eps_sue) * 0.5  # Dampen — discordance reduces confidence
```

### Analyst revision velocity (days 1–5 post-earnings)

This is among the strongest confirming signals. Zhang (2008) showed **26–53% of analysts revise forecasts within 2 trading days** after earnings. When analysts are slow to revise, more of the price adjustment occurs in the drift window rather than the event window. Stocks where analysts lag have **larger drift opportunities**. Poll Finnhub's `company_eps_estimates()` at T+1, T+3, and T+5 versus T-1 to measure revision magnitude, direction, and speed.

### Earnings call NLP via Ollama

The PEAD.txt methodology from Meursault et al. (2023) demonstrates that ML-based text surprise from earnings call transcripts generates drift of 8.01% even when classic PEAD approaches zero. For Halcyon Lab, deploy **FinBERT** (fits within RTX 3060's 12GB VRAM) on the Q&A section of earnings call transcripts, computing a sentiment surprise relative to the company's prior 8-quarter tone baseline. The Q&A section is more informative than prepared remarks because analysts probe weaknesses. Finnhub Premium provides transcripts via `transcripts()` and `transcripts_list()`.

Price et al. (2012) confirmed that conference call linguistic tone is a significant return predictor that **dominates earnings surprises over 60 trading days**. However, companies increasingly "sugar-coat" — context-aware models like FinBERT significantly outperform dictionary methods (Loughran-McDonald) but the signal has weakened as management teams adapt language.

### Additional confirming features

**Volume surge**: Earnings-day volume relative to 20-day average. Garfinkel & Sokobin (2006) showed higher abnormal volume correlates with opinion divergence. Paradoxically, very high day-0 volume can indicate faster price discovery (less drift), but sustained elevated volume in days 2–5 suggests continued market processing (more drift). Track both ratios.

**Pre-announcement run-up**: Kelly et al. found pre-earnings run-ups positively predict announcement returns but **negatively predict post-earnings drift**. A large run-up that isn't confirmed by the actual surprise increases reversal risk. If confirmed, drift may be partially exhausted. Use as a contra-indicator or dampening factor.

**Options IV crush ratio**: Compare actual move to ATM straddle-implied expected move. If `actual_move / implied_move > 1.0`, the market underpriced the information content, predicting stronger subsequent drift.

### Recommended feature tiers for the ML scoring model

**Tier 1 (core)**: SUE (analyst-based), 12 SUE lags, revenue SUS, EPS-revenue concordance, 3-day Earnings Announcement Return (EAR). **Tier 2 (confirming)**: Analyst revision velocity (1–5 day), volume ratio, post-earnings volume persistence, pre-announcement return, forecast dispersion. **Tier 3 (cross-sectional)**: Institutional ownership percentage, short interest ratio, sector earnings momentum, earnings call sentiment, individual ticker drift history. Deploy an ensemble of ElasticNet (for SUE lag features) plus LightGBM/XGBoost with GPU acceleration (for the full heterogeneous feature set) — this combination balances interpretability with non-linear interaction capture.

---

## Entry, exit, and position sizing mechanics

### Entry timing: day+1 open plus 15 minutes

Academic evidence converges on entering the session after the announcement rather than attempting same-day capture. Grégoire & Martineau (2021) showed that for large stocks, **80–90% of the price adjustment happens within minutes** of the announcement through quote adjustments in the after-hours market. For after-hours earnings (~70% of S&P 100 reports), entering at next-day open plus 15 minutes lets the opening auction settle. For before-open earnings (~25%), wait 30 minutes into regular session. Martineau (2021) found that since 2011, the only suggestive evidence of PEAD is for the **2-to-5-day horizon** — entering day+1 captures this window while avoiding overnight gap noise.

On Alpaca, extended hours support **limit orders only** with `extended_hours=True`. Bracket orders are not available during extended hours. The recommended pattern: submit an OPG (market-on-open) order via `TimeInForce.OPG` for next-day entry, then immediately submit a separate bracket modification once filled during regular hours. For the rare during-market-hours report (~5% of S&P 100), react within minutes using a limit order.

```python
# Primary entry: next-day open
def submit_pead_entry(symbol: str, qty: int, side: OrderSide):
    return client.submit_order(MarketOrderRequest(
        symbol=symbol, qty=qty, side=side,
        time_in_force=TimeInForce.OPG  # Market on Open
    ))
```

### Exit strategy: triple-barrier method

Implement López de Prado's triple-barrier approach optimized for PEAD's drift characteristics. The **upper barrier** (take-profit) sits at 3× ATR(14) above entry. The **lower barrier** (stop-loss) sits at 2× ATR(14) below entry, yielding a 1.5:1 reward-to-risk ratio. The **vertical barrier** (time exit) triggers at 10 trading days, when FMP research shows the drift curve plateaus for large-caps.

Stop-loss placement materially affects PEAD profitability because earnings drift has a fundamentally different thesis than pullback trades. Zhang, Cai & Keasey (2014) showed that incorporating realistic transaction costs can eliminate PEAD alpha for broad portfolios, but for S&P 100 specifically, round-trip costs are modest (~16 bps including 5 bps slippage, 3 bps market impact, and regulatory fees on Alpaca's commission-free platform). The **2× ATR stop is critical** — tighter stops get whipsawed by post-earnings volatility noise, destroying the strategy's edge.

Alpaca does not natively support time-based exits. Implement via FastAPI scheduled task running at 3:55 PM ET each trading day, closing any PEAD position that has exceeded its holding period. Trailing stops are also not supported as bracket legs — use TradingStream websocket to monitor fills and programmatically submit trailing stops after the entry fills.

### Position sizing: quarter-Kelly with hard caps

Estimated PEAD win rate for S&P 100 modern markets is **52–55%** with an average win/loss ratio of approximately 1.2–1.5:1. Full Kelly fraction calculates to roughly 20%, but estimation error makes full Kelly dangerous. Apply **quarter-Kelly (~5% per position)** with a hard cap at 5% of portfolio per trade, 1% of equity risked per trade (entry-to-stop distance), maximum 4 concurrent PEAD positions, and maximum 15% sector exposure. During peak earnings season (late January, April, July, October), the system may have 4 PEAD trades and 5 pullback trades simultaneously.

McCarthy (2025, SSRN) found that PEAD is **2.5–4.5× stronger when surprises are inconsistent with prior analyst recommendations** — a positive surprise on a "Sell"-rated stock generates 5.8–7.4% 90-day abnormal return versus only 1–2% for "Buy"-rated stocks. Since most S&P 100 stocks carry "Buy" consensus, this filter dramatically reduces the number of qualifying trades but substantially increases per-trade alpha. Adjust position sizing upward (to half-Kelly) for recommendation-inconsistent surprises.

---

## PEAD asymmetry: the short side is theoretically stronger but practically constrained

Multiple 2024 papers document significant asymmetry. Zhang, Gregoriou & Wu (2024, IRFA) found stocks with **bad news exhibit stronger drift than good news** across the FTSE 350. Fink, Palan & Theissen (2024, JFQA) confirmed experimentally: prices dropped 2.10 units on negative announcement then drifted down another 7.88 units, versus jumping 3.96 and drifting up only 3.80 for positive surprises. Klein & Klein (2024, IRFA) explain the mechanism: crowding is more likely after positive earnings because barriers to going long are lower than short-selling, so the **long side of PEAD gets crowded out faster**, leaving the short side theoretically more exploitable.

However, for S&P 100 implementation, practical constraints limit short-side exploitation. While short-selling constraints are minimal for mega-caps (high borrow availability), the asymmetric risk profile of shorts (unlimited downside) and the general upward market drift over 5–10 day holding periods create headwinds. **Recommendation: implement both sides but weight long signals 60/40 versus short signals**, and require higher composite scores (stronger conviction) for short entries.

---

## ML model architecture for RTX 3060

### XGBoost PEAD scorer (primary model)

Deploy XGBoost with GPU acceleration (`tree_method='gpu_hist'`) for real-time scoring. The model predicts whether cumulative abnormal return over 10 days will exceed 2%, trained on the full feature set spanning all three tiers. Retrain quarterly using walk-forward validation with an 8-quarter training window and 1-quarter test window.

Ye & Schuller (2020) demonstrated that XGBoost with genetic algorithm optimization on Russell 1000 stocks captures non-linear, time-varying relationships that regression misses — drift direction depends on **different factors for different sectors and quarters**. The model trains on ~1,600 earnings events per year (S&P 100 × 4 quarters × ~4 years of training data = ~1,600 events per training window).

```python
pead_model_params = {
    'objective': 'binary:logistic',
    'tree_method': 'gpu_hist',
    'gpu_id': 0,
    'max_depth': 6,
    'learning_rate': 0.05,
    'n_estimators': 500,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'eval_metric': 'auc',
    'early_stopping_rounds': 50
}
```

### ElasticNet SUE-lag model (complementary)

Run separately on only the 12 SUE lag features, producing a drift probability that feeds into the XGBoost model as a meta-feature. This two-stage architecture preserves the interpretability of the Kaczmarek & Zaremba approach while leveraging XGBoost's ability to capture interactions with confirming signals.

### FinBERT sentiment model (NLP component)

FinBERT runs comfortably within 12GB VRAM for inference. Process the Q&A section of earnings call transcripts at sentence level, aggregate into a company-quarter sentiment score, then compute sentiment surprise versus the 8-quarter rolling mean. This sentiment surprise feeds as a feature into both the XGBoost scorer and the LoRA-adapted LLM commentary generator.

---

## LoRA fine-tuning specification for PEAD analysis

### Training data generation: self-blinded historical examples

Each S&P 100 earnings event produces one training example. With ~100 companies × 4 quarters, expect **~400 examples per year**. The self-blinding protocol is critical — the model must analyze setups without knowing outcomes:

- Replace ticker with anonymous ID (`STOCK_2024Q3_047`)
- Replace dates with relative labels (`Period T`, `T-1`, `T-4`)
- Include ONLY data available at signal generation time (T+1 after earnings)
- Training target is the analytical reasoning, NOT the subsequent return

Kim et al. (arXiv 2407.17866) validated that anonymized, standardized financial presentations enable LLMs to outperform human analysts at predicting earnings direction changes, confirming the self-blinding approach works.

### QLoRA configuration for RTX 3060

Use Mistral 7B or Llama 3.1 8B quantized to 4-bit via QLoRA. The base model loads in ~3.4–4GB, leaving ~8GB for gradients and activations with `batch_size=1` and `gradient_accumulation_steps=8`. Training 400 examples takes approximately 2–4 hours. LoRA rank 16, alpha 16, targeting attention projection layers (`q_proj`, `k_proj`, `v_proj`, `o_proj`). Retrain semi-annually with 200 new examples plus 200 from the prior period.

### PEAD prompt template

```
<|system|> You are a quantitative trading analyst specializing in post-earnings 
drift analysis. Evaluate this setup for a 5-10 day directional trade.

<|user|>
## Earnings Report — [ANONYMIZED_ID]
- Sector: {sector} | Market Cap Quintile: {1-5}
- EPS: ${actual} vs ${estimate} consensus ({surprise_pct}% surprise, SUE: {sue})
- Revenue: ${rev_actual} vs ${rev_est} ({rev_surprise_pct}% surprise)
- EPS-Revenue Concordance: {concordant|discordant}
- 12Q SUE History: [{sue_lag_1}, ..., {sue_lag_12}]
- ElasticNet drift probability: {en_score}
- Analyst Revision Velocity (T+1 to T+3): {revision_pct}%
- Recommendation Consistency: {consistent|inconsistent} with {consensus_rating}
- Earnings Call Sentiment Surprise: {sentiment_z_score} σ
- Gap: {gap_pct}% | Volume Ratio: {vol_ratio}x | Pre-10d Return: {pre_return}%
- RSI(14): {rsi} | Price vs 200-SMA: {pct_above_200sma}%

Provide: (1) Signal strength, (2) Action (LONG/SHORT/SKIP), (3) Holding period,
(4) Key risks, (5) Confidence (1-10).
```

---

## Integration architecture with pullback strategy

### Strategy Registry with unified risk governor

Each strategy operates as an independent module that registers with a central orchestrator. The orchestrator collects signals from both strategies, then passes them through a shared Risk Governor that enforces portfolio-level constraints while respecting strategy-specific sub-limits.

**A stock can qualify for both pullback and PEAD simultaneously.** This confluence signal represents a stock in a pullback-in-uptrend that also just reported a positive surprise — a strong setup where both fundamental and technical signals align. Tag these as `confluence` and allow up to 1.5× normal position size. Prevent duplicate positions: if a PEAD signal fires on a stock already in a pullback trade, either upgrade the existing position's targets or add to the position up to the concentration limit.

### Capital allocation: half-Kelly with ERC floor

Calculate Kelly fraction for each strategy independently using trailing 6-month returns, apply half-Kelly, then cap total allocation at 100%. Use Equal Risk Contribution as a floor so each strategy receives at minimum `capital / n_strategies`. Target allocation: **PEAD 30–40%** (higher per-trade Sharpe but event-driven concentration risk) and **pullback 60–70%** (more consistent, lower tail risk). Monitor 20-day rolling correlation between strategy daily P&Ls — if correlation exceeds 0.7, reduce the smaller strategy's allocation by 25%.

### Risk governor parameters

Portfolio-level limits: maximum 15% drawdown trigger, maximum 8 concurrent positions, maximum 50% single-sector exposure. PEAD sub-limits: maximum 4 concurrent trades, maximum 2% risk per trade, no more than 2 in the same sector. Pullback sub-limits: maximum 5 concurrent trades, maximum 1.5% risk per trade. Cross-strategy: VIX above 25 reduces PEAD sizes by 25%; VIX above 30 halts new PEAD entries entirely. During FOMC days, CPI releases, and NFP days, skip new PEAD entries — macro events overwhelm individual stock drift signals.

---

## Backtesting methodology

### Walk-forward design

Use a 12-quarter (3-year) training window, 1-quarter test window, rolling forward by 1 quarter. This ensures the model always trains on data ending before the test period. Each training window contains approximately 1,200 earnings events (100 stocks × 12 quarters, minus delistings and additions). Minimum 200 events per evaluation window for statistical reliability, and minimum 8 earnings cycles per individual stock before including it in training.

### Survivorship bias mitigation

Using today's S&P 100 constituents to backtest history is a **major survivorship bias** that can overstate annual returns by 1–4% and underestimate drawdowns by ~14 percentage points. The system must use **point-in-time index composition** — tracking which stocks were actually in the index at each historical date. CRSP or Compustat historical index membership is the gold standard. For a practical approach, maintain a `sp100_membership` SQLite table logging additions and deletions with effective dates.

### Point-in-time earnings dates

Many databases retroactively "correct" earnings announcement dates (restatements, adjusted timing). Use Finnhub's `company_earnings()` historical data cross-referenced with the original 8-K filing date from SEC EDGAR. Store the announcement date as detected at the time in the `earnings_actuals` table, never overwriting with corrections. This prevents the insidious look-ahead bias of using "corrected" dates that weren't known at signal generation time.

### Transaction cost model

```python
COST_MODEL = {
    "commission": 0.0,                # Alpaca commission-free
    "sec_fee_per_dollar": 0.0000278,  # ~$27.80 per $1M
    "taf_fee_per_share": 0.000166,    # FINRA TAF
    "slippage_bps": 5,                # S&P 100 stocks, liquid
    "market_impact_bps": 3,           # Positions < $100K
    "total_round_trip_bps": 16        # Conservative aggregate
}
```

---

## Known failure modes and mitigations

**Priced-in surprise** is the most common trap. When the options market implies a move that exceeds the actual move (actual/implied ratio < 1.0), the "surprise" was already anticipated. Pre-earnings options trading actually corrects stock market underreaction, reducing subsequent drift. **Mitigation**: Filter for actual move exceeding 80% of implied move before entering.

**Guidance overrides surprise** — even strong EPS beats fail if forward guidance disappoints. FMP research confirms that "strong earnings beats can lead to price declines if forward guidance disappoints." **Mitigation**: Require no guidance cut as a filter, and weight revenue concordance heavily (revenue beats with guidance raises are the strongest signal).

**Recommendation-consistent surprises** generate minimal drift in S&P 100. McCarthy (2025) showed PEAD is 2.5–4.5× stronger when inconsistent with prior analyst ratings, but most mega-caps carry "Buy" consensus. **Mitigation**: Score recommendation inconsistency explicitly and upsize positions for inconsistent surprises. Accept that most S&P 100 earnings events will not qualify, generating approximately 15–30 tradeable signals per quarter rather than 100.

**Declining earnings persistence** (Kettell, McInnis & Zhao 2022) means SUE autocorrelation has weakened — firms no longer stay in extreme SUE deciles as reliably. This degrades all SUE-based approaches including ML variants. **Mitigation**: The 12-quarter elastic net partially addresses this by capturing trajectory changes, but monitor out-of-sample model accuracy quarterly and be prepared to reduce position sizes if the model's AUC drops below 0.55.

**AI/NLP disruption**: CFA Institute (2025) notes that generative AI tools are accelerating information processing of earnings calls. As LLM-based earnings analysis proliferates, text-based PEAD may compress. **Mitigation**: Retrain NLP models semi-annually to capture evolving language patterns, and monitor whether sentiment surprise predictive power is decaying.

---

## SQLite schema for the complete PEAD pipeline

```sql
CREATE TABLE earnings_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, report_date DATE NOT NULL,
    report_time TEXT,  -- 'bmo', 'amc', 'dmh'
    fiscal_quarter TEXT, eps_estimate REAL, revenue_estimate REAL,
    n_analysts INTEGER, source TEXT DEFAULT 'finnhub',
    UNIQUE(symbol, report_date)
);

CREATE TABLE earnings_actuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, report_date DATE NOT NULL,
    actual_eps REAL, estimate_eps REAL, eps_surprise_pct REAL,
    actual_revenue REAL, estimate_revenue REAL, revenue_surprise_pct REAL,
    sue_score REAL, concordance_score REAL,
    gap_pct REAL, day1_volume_ratio REAL, day1_return_pct REAL,
    UNIQUE(symbol, report_date)
);

CREATE TABLE pead_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, signal_date DATE NOT NULL,
    earnings_actual_id INTEGER REFERENCES earnings_actuals(id),
    direction TEXT NOT NULL,  -- 'LONG' | 'SHORT'
    elastic_net_score REAL, xgboost_score REAL,
    llm_score REAL, llm_commentary TEXT,
    composite_score REAL, signal_strength TEXT,
    entry_price REAL, target_price REAL, stop_price REAL,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE pead_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES pead_signals(id),
    symbol TEXT NOT NULL, direction TEXT NOT NULL,
    entry_date DATE, entry_price REAL, qty INTEGER,
    risk_amount_usd REAL, alpaca_order_id TEXT,
    take_profit_price REAL, stop_loss_price REAL,
    exit_date DATE, exit_price REAL, exit_reason TEXT,
    pnl_usd REAL, pnl_pct REAL, holding_days INTEGER,
    status TEXT DEFAULT 'open'
);

CREATE TABLE drift_tracking (
    symbol TEXT NOT NULL, earnings_date DATE NOT NULL,
    day_offset INTEGER NOT NULL,
    cumulative_abnormal_return REAL, daily_return REAL,
    UNIQUE(symbol, earnings_date, day_offset)
);

CREATE TABLE strategy_daily_returns (
    date DATE NOT NULL, strategy TEXT NOT NULL,
    daily_return REAL, n_positions INTEGER,
    UNIQUE(date, strategy)
);
```

---

## If all else fails: best alternatives preserving key properties

If live trading confirms PEAD is truly unworkable for S&P 100, three alternatives preserve the attractive properties of near-zero pullback correlation, same universe, and same holding period.

**Post-earnings IV crush (Sharpe 0.6–0.9, correlation ~0.0 with pullback)** exploits the systematic overpricing of options before earnings. The variance risk premium accounts for 30–70% of a stock's annual movement. Selling iron condors on S&P 100 stocks — which have the most liquid options and penny-wide spreads — captures this premium with a 55–65% win rate. This strategy is completely orthogonal to pullback momentum signals. Requires Alpaca's options trading capability.

**Earnings streak momentum (Sharpe 0.7–1.0, correlation ~0.3 with pullback)** exploits the gambler's fallacy. Loh & Warachka (2012, Management Science) showed investors significantly underreact to streak continuation. When a surprise extends a positive streak (e.g., 4th consecutive beat), PEAD is "strong and significant"; when it breaks a streak, drift is "negligible." The elastic net multi-quarter model from Kaczmarek & Zaremba captures this same pattern.

**Multi-signal composite scoring (Sharpe 0.9–1.3 estimated, correlation ~0.2 with pullback)** combines all signals — EPS surprise, revenue concordance, EAR, analyst revision velocity, NLP tone, earnings quality, recommendation inconsistency — into a single score. Brandt et al. showed combined EAR + SUE generates ~12.5% annual abnormal returns versus 7.55% for EAR alone. This is the recommended primary approach regardless of pure PEAD viability, because it degrades gracefully: even if individual signals weaken, the composite retains predictive power through signal diversity.

## Conclusion

The implementation path for Halcyon Lab is not classical PEAD — it is a **composite earnings information processing system** that happens to exploit the same underlying phenomenon (market underreaction to complex earnings information) through modern ML methods. The single most important design decision is building the 12-quarter elastic net SUE model, which Kaczmarek & Zaremba specifically showed works best in large-caps. Layer NLP sentiment surprise via FinBERT on Ollama, revenue concordance filtering, and analyst revision velocity as confirming signals. Enter day+1 at open plus 15 minutes, exit via triple-barrier at 10 trading days, and size at quarter-Kelly with 4 concurrent position maximum. Expect roughly **15–30 qualifying trades per quarter** (not 100) given the stringent filtering required for mega-cap stocks, with an estimated Sharpe of 0.6–0.9 after transaction costs — modest but meaningfully additive to the pullback strategy given near-zero correlation. Monitor quarterly for signal decay, and maintain the IV crush alternative as a ready fallback if the composite model's out-of-sample AUC degrades below 0.55.