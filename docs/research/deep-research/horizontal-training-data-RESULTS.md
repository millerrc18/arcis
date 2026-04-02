# Maximizing signal density for LLM-based S&P 100 swing trading

**The honest answer to "what else should I add?" is less than you expect — and that's the edge.** For S&P 100 mega-caps at 2–15 day horizons, the academic evidence supports only **7–8 truly orthogonal signal dimensions**, not the 12–15 the combinatorial fusion thesis might suggest. Most documented anomalies — PEAD, short interest, retail sentiment, congressional trading, analyst dispersion — are either dead, negligible, or fully arbitraged for trillion-dollar stocks with 30+ analyst coverage. Your current 7-section stack already captures ~5 of the 8 independent dimensions. The highest-value additions are **3 free enrichments** (credit spreads via FRED, cross-asset prices via yfinance, calendar/event risk) and **1 paid addition** (real-time options flow via Unusual Whales). This brings you to 11 sections — near the 12-section hard cap imposed by your 300–1,000 token budget — with genuinely orthogonal coverage that rivals systems spending 10x more on data.

The moat isn't in raw dimension count. It's in having the *right* dimensions, compressed to maximum information density, with the model trained to reason across their interactions. Trading-R1 achieved Sharpe 2.72 with only 5 broad data categories. Your 11-section architecture, combined with modified random source subsetting and QLoRA at rank 32, should exceed that signal diversity while fitting comfortably in your token and VRAM budgets.

---

## The mega-cap penalty changes everything about signal selection

The single most important finding from this research is that **S&P 100 stocks exist in a fundamentally different information regime** than the broader equity universe where most anomalies are documented. McLean and Pontiff (2016) showed anomalies decline **58% post-publication**, but the decay is *greatest* for low-idiosyncratic-risk stocks — exactly S&P 100 constituents. Gordon, Schneider, and Strauss (2025) found only **3 of 13 anomaly themes survive in modern data**: low-risk, momentum, and quality. Everything else — size, value, accruals, investment, seasonality — shows insignificant alpha post-2005.

This creates a Grossman-Stiglitz (1980) equilibrium problem specific to your universe. For stocks where information acquisition costs approach zero (universal analyst coverage, real-time news, massive data infrastructure), any signal computable from public data converges toward zero alpha. Martineau (2022) demonstrated this directly: **PEAD is completely dead for large-cap stocks since 2006**, with prices fully adjusting on announcement day. Subrahmanyam's 2025 working paper confirmed that removing microcap stocks (bottom 20th percentile NYSE market cap) drops PEAD's t-statistic from 2.18 to 1.43 — well below significance.

The implication for your system is stark: **most signals that "work" in academic papers don't work for your universe**. Cookson et al. (2024, JFE) found social media sentiment exhibits strong reversal and its informativeness deteriorated post-2021. For mega-caps specifically, social media posts have **no significant effect on abnormal returns** (Keasey 2025). Da, Engelberg, and Gao (2011) explicitly noted their Google Trends effect is "most pronounced among small stocks." Cohen and Frazzini's (2008) customer-supplier momentum has lost statistical significance in recent samples and is driven by small suppliers lagging large customers — the wrong direction for S&P 100 trading. Diether, Malloy, and Scherbina (2002) found analyst dispersion effects are "most pronounced in small stocks" and the effect has been learned away.

This doesn't invalidate the combinatorial fusion thesis — but it means you need to be ruthlessly selective about *which* dimensions to fuse. Adding noise dimensions (Google Trends, Reddit sentiment, FTD data) to mega-cap training examples actively degrades signal quality by teaching the model spurious correlations.

---

## The 8 orthogonal signal dimensions that actually matter

Based on factor model research (Fama-French 5-factor, q-factor, Stambaugh-Yuan mispricing factors) and empirical correlation analysis, the maximum number of genuinely independent signal dimensions for S&P 100 stocks at 2–15 day horizons is approximately **8**. Here is the orthogonality matrix showing estimated pairwise correlations among viable dimensions:

| Dimension | MOM | REV | VOL | IV | ERev | Sent | Macro | XAst |
|-----------|-----|-----|-----|-----|------|------|-------|------|
| **1. Momentum/Trend** | 1.0 | | | | | | | |
| **2. Mean-Reversion** | −0.65 | 1.0 | | | | | | |
| **3. Volume/Liquidity** | 0.10 | 0.15 | 1.0 | | | | | |
| **4. Options-Implied** | 0.05 | 0.10 | 0.20 | 1.0 | | | | |
| **5. Earnings Revisions** | 0.35 | −0.05 | 0.10 | 0.15 | 1.0 | | | |
| **6. News/Sentiment** | 0.30 | −0.20 | 0.15 | 0.10 | 0.20 | 1.0 | | |
| **7. Macro Regime** | 0.05 | 0.10 | 0.10 | 0.20 | 0.05 | 0.15 | 1.0 | |
| **8. Cross-Asset** | 0.05 | 0.10 | 0.05 | 0.15 | 0.00 | 0.10 | 0.40 | 1.0 |

Dimensions 1 and 2 (momentum and mean-reversion) are strongly anti-correlated but operate at different timescales — reversal dominates at less than 5 days, momentum at more than 5 days — making them complementary for your 2–15 day window. The highest off-diagonal correlation is Macro-to-Cross-Asset at 0.40, which still provides substantial independent information (DXY divergences, copper/gold ratio shifts are not fully captured by VIX or credit spreads alone).

**Four dimensions were explicitly dropped as redundant or non-viable**: short interest (subsumed by options-implied information; Muravyev et al. 2021 showed IV spreads reflect borrow fees; negligible for easy-to-borrow mega-caps), retail attention (subsumed by news/sentiment; ρ ≈ 0.45), supply chain/network effects (monthly frequency, post-discovery decay), and credit conditions (subsumed into macro regime; ρ ≈ 0.50 with rates/VIX). Calendar/seasonality effects operate as a **conditional modifier** rather than an independent signal dimension, warranting inclusion as a lightweight enrichment section rather than a full dimension.

---

## Complete signal taxonomy with evidence assessment

The following table covers every plausible signal dimension organized by viability for S&P 100 stocks at 2–15 day horizons. Effect sizes reflect mega-cap estimates where available, not full-universe figures.

| Signal | Academic Evidence | Effect Size (Mega-Cap) | Temporal Res. | 2–15 Day Viability | Post-Pub Decay | Verdict |
|--------|------------------|----------------------|---------------|---------------------|----------------|---------|
| **Earnings revision momentum** | Chan, Jegadeesh & Lakonishok (1996, JF); Novy-Marx (2015) | Significant even in largest quintile; ~22%/yr gross in large-cap samples | Weekly (analyst updates) | **Strong** | Low — persists | ✅ Add |
| **Short-term reversal** | Jegadeesh (1990); Lehmann (1990) | ~50–100 bps/month for large caps | Daily | **Strong** for <5d | Moderate | ✅ Already captured (RSI/pullback depth) |
| **Medium-term momentum** | Jegadeesh & Titman (1993); Asness et al. (2013) | Survives across all sizes | Daily-Monthly | **Moderate** at 5–15d | Low | ✅ Already captured (trend/EMA) |
| **Options put-call volume** | Pan & Poteshman (2006, RFS) | ~40 bps next-day, >1% next-week | Daily | **Moderate** — weaker for mega-caps | Moderate | ✅ Add (Unusual Whales) |
| **IV spread/skew** | Cremers & Weinbaum (2010, JFQA) | ~51 bps/week L/S; attenuated for mega-caps | Daily | **Moderate** | Moderate-High | ✅ Add with options flow |
| **VIX term structure** | Konstantinidi & Skiadopoulos (2019) | Backwardation → significant positive equity returns | Daily | **Strong** as regime filter | Low | ✅ Add (free via FRED) |
| **Credit spreads** | Gilchrist & Zakrajšek (2012, AER) | 100 bps increase → >1.25pp GDP deceleration | Daily | **Strong** as regime filter | Low | ✅ Add (free via FRED) |
| **Cross-asset regime** | Asness, Moskowitz & Pedersen (2013, JFE) | Pervasive momentum across asset classes | Daily | **Moderate** (index-level) | Low | ✅ Add (free via yfinance) |
| **News/event sentiment** | Tetlock (2007, JF); Cookson et al. (2024, JFE) | Persistence of negative sentiment creates pullback opps | Intra-daily | **Moderate** for event timing | Moderate | ✅ Already captured (Finnhub) |
| **Calendar events** | Lucca & Moench (2015, JF) — FOMC drift now dead; TOM weakened | Pre-FOMC drift: disappeared. TOM: ~0.47% historically | Event-driven | **Weak-Moderate** as filter | High (FOMC) | ⚠️ Add as lightweight enrichment |
| **Volume anomalies** | Gervais, Kaniel & Mingelgrin (2001, JF) | Significant for 20-day horizons | Daily | **Moderate** | Moderate | ✅ Already captured |
| **Fundamentals/valuation** | Fama-French; Novy-Marx (2013) | Quality/profitability persist; simple B/M weakened | Quarterly | **Context only** — too slow | Mixed | ✅ Already captured (EDGAR) |
| **Insider trading** | Cohen et al. (NBER) — opportunistic vs. routine | 82 bps/mo for opportunistic buys (value-weighted) | Monthly filings | **Weak** for mega-caps | Moderate | ⚠️ Keep but downweight |
| **Short interest** | Rapach, Ringgenberg & Zhou (2016) | Significant for 30 days; negligible for mega-caps | Bimonthly | **Near zero** for S&P 100 | N/A | ❌ Skip |
| **Google Trends** | Da, Engelberg & Gao (2011, JF) | Concentrated in small caps with low coverage | Weekly | **Near zero** for mega-caps | High | ❌ Skip |
| **Social media sentiment** | Cookson et al. (2024, JFE) | Deteriorated post-2021; no effect on mega-caps | Real-time | **Near zero** for mega-caps | N/A | ❌ Skip |
| **PEAD** | Martineau (2022, CFR) | Dead since 2006 for large caps | Quarterly events | **Zero** | Complete | ❌ Skip |
| **Congressional trading** | Belmont et al. (2022, JPubE) | No stock-picking alpha post-STOCK Act | 45-day delay | **Zero** — delay + no signal | Complete | ❌ Skip |
| **Analyst dispersion** | Diether et al. (2002, JF) | Concentrated in small stocks; learned away | Monthly | **Weak** for mega-caps | High | ❌ Skip |
| **Customer-supplier momentum** | Cohen & Frazzini (2008, JF) | Lost significance post-discovery | Monthly | **Non-viable** | High | ❌ Skip |
| **FTD data** | Practitioner literature only | Near zero for liquid mega-caps | Bimonthly | **Zero** | N/A | ❌ Skip |

---

## Free tier additions: 3 quick wins worth building

Your current free stack is strong. The highest-value additions are all enrichments to existing infrastructure — no new API registrations required. Ranked by expected marginal value:

**1. Credit market spreads via FRED (add to existing Macro section)**. Add 6–8 FRED series you already have API access to: BAMLH0A0HYM2 (HY OAS), BAMLC0A0CM (IG OAS), BAMLC0A4CBBB (BBB OAS), T10Y2Y (2s10s spread). Credit leads equity by days to weeks — HY OAS below 4% signals risk-on, above 5% signals risk-off. Gilchrist and Zakrajšek (2012) demonstrated the excess bond premium is a statistically significant predictor of economic activity. This requires approximately **10 additional FRED API calls per day**, trivially within your existing 120/min allocation. Implementation effort is trivial — extend your existing FRED pipeline with new series IDs. Token cost: ~25 tokens as compressed attributes within your existing `<macro>` section.

**2. Cross-asset prices via yfinance (new section)**. Add ~15–20 tickers to your existing yfinance pipeline: DX-Y.NYB (DXY dollar index), GC=F (gold), HG=F (copper), CL=F (crude), BTC-USD, plus sector ETFs (XLK, XLF, XLE, XLU, XLV). The **gold-to-copper ratio** is a well-documented economic health indicator. DXY strength directly impacts S&P 100 multinationals' translated earnings. Sector ETF relative strength reveals rotation patterns. These signals are genuinely orthogonal to your existing stock-specific data — they capture the macro/cross-asset dimension from market prices rather than economic releases. Implementation is trivial: extend existing yfinance calls. Token cost: ~30 tokens for a new `<intermarket>` section.

**3. VIX term structure via yfinance + FRED (enhance existing Market Regime section)**. Fetch ^VIX, ^VIX3M (or VIX3M from FRED as VIXCLS/VIX3MCLS), ^VVIX, ^SKEW via yfinance. Compute the VIX9D/VIX3M slope — **contango vs. backwardation**. Konstantinidi and Skiadopoulos (2019) found VIX backwardation significantly predicts positive equity returns at weekly horizons. VVIX (volatility of volatility) captures regime uncertainty. SKEW captures tail risk pricing. Token cost: ~20 tokens added to your existing market regime section. Implementation is trivial.

**4. Calendar/event risk indicators (new lightweight section)**. Hard-code 2026 FOMC dates (8 meetings), compute days-to-next-FOMC, flag monthly options expiration (3rd Friday), flag turn-of-month windows (day −1 to day +3), and compute earnings density (% of S&P 100 reporting this week from your existing FMP/Finnhub earnings calendar). While the pre-FOMC drift anomaly is dead post-publication, FOMC meetings still create **elevated volatility regimes** that affect pullback-in-uptrend setups. Token cost: ~20 tokens. Implementation is trivial — static calendar plus simple date math.

**5. Individual stock options metrics via yfinance (enrich Options section)**. Your existing yfinance installation can fetch options chains via `ticker.option_chain()`. Compute per-stock **put/call open interest ratio**, at-the-money IV level, and 25-delta skew for the nearest monthly expiration. Pan and Poteshman (2006) documented 40 bps next-day and >1% next-week returns from options-implied directional signals. While attenuated for mega-caps, this provides a free complement to Unusual Whales' real-time flow data (you get the structural positioning; UW gives you the flow). Implementation effort is moderate — parsing 100 stocks × multiple expirations.

**Secondary free sources (lower priority)**. CFTC COT data via the `cot_reports` Python package provides weekly institutional positioning in S&P 500 futures — a contrarian signal at extremes but with weak academic support and weekly frequency that limits 2–15 day utility. Wikipedia pageview API (no auth required, generous rate limits) provides attention spikes that complement news but are redundant with sentiment signals. FINRA short interest via their API requires OAuth registration but provides bimonthly data that is largely noise for mega-caps. FinBERT (HuggingFace: ProsusAI/finbert) could quantify sentiment on your existing Finnhub news and EDGAR filing text, but adds processing complexity for moderate gain.

---

## Paid tier: Unusual Whales is the right first purchase

The planned **Unusual Whales subscription (~$50/month)** is the single highest-value paid addition for your system. Real-time options flow data — sweeps, dark pool prints, unusual activity — provides the options-implied signal dimension that no free source can replicate. For a pullback-in-uptrend strategy, the combination of "institutional call sweeps during a healthy pullback" is precisely the kind of multi-signal confirmation that justifies the LLM fusion approach.

Beyond Unusual Whales, the paid landscape offers diminishing returns within your $150/month budget. Here is the ranked assessment:

**Quiver Quantitative API ($10/month)** adds government contract flows and lobbying data — genuinely alternative dimensions. However, the academic evidence for congressional trading alpha post-STOCK Act is weak (Belmont et al. 2022 found no stock-picking prowess), and the 45-day reporting delay makes this nearly useless for 2–15 day trading. At $10/month the bar is low, but the signal may be pure noise for mega-caps. Consider it only after exhausting free additions.

**Polygon.io Starter ($29/month)** replaces yfinance with a reliable, high-throughput API. This is an infrastructure upgrade rather than a signal addition — it provides the same OHLCV data with better uptime and rate limits. Worth considering if yfinance reliability becomes a bottleneck during live trading, but it adds zero new signal dimensions.

**Fintel Trader ($25/month)** or **ORTEX Advanced ($79/month annual)** provide short interest data. However, the anti-recommendation evidence is strong: S&P 100 stocks have massive float, minimal borrow costs, and short interest ratios near decade lows. Short squeeze dynamics simply don't apply to trillion-dollar companies. The academic evidence (Rapach, Ringgenberg & Zhou 2016) shows short interest negatively predicts returns at 30-day horizons, but the signal is concentrated in smaller, illiquid stocks. For your specific universe, this is likely noise.

**Recommended $150/month allocation**: Unusual Whales at ~$50 for options flow, leaving $100 as reserve for scaling or testing Polygon.io ($29) when transitioning to live trading. Do not add Fintel, ORTEX, Koyfin, or Tiingo — they either duplicate existing free sources or provide signals that don't work for mega-caps.

---

## Aspirational tier ($150–500/month) for proven profitability

If the system demonstrates consistent profitability and scales to $50K+ AUM, three additions would provide genuine signal uplift.

**Polygon.io Options Developer ($79/month)** unlocks historical options data with Greeks, IV surfaces, and open interest across all strikes and expirations. This enables building proprietary IV surface models — tracking how the volatility smile shifts during pullbacks, whether skew normalizes before reversals, and whether term structure changes predict resolution direction. No free source provides historical Greeks at scale. Combined with Unusual Whales' real-time flow, this creates a comprehensive options-informed signal layer.

**ORTEX Advanced at annual pricing ($79/month)** becomes more justifiable at higher AUM, providing **daily** short interest estimates (vs. FINRA's bimonthly) and cost-to-borrow data. While short interest alone is weak for mega-caps, the *rate of change* in short interest during a pullback could distinguish healthy retracements from genuine distribution. The daily granularity aligns with your holding period.

**Refinitiv Workspace stripped-down tier (~$300/month)** is the threshold where institutional-grade data becomes accessible. The unique value is Reuters exclusive news wire (ahead of free news aggregators by minutes to hours) and comprehensive analyst revision tracking with timestamps. For a system that needs to verify no-lookahead-bias compliance, having timestamped analyst revisions from the primary source is valuable. However, **70% of this data can be approximated** by FMP + Finnhub + Polygon at ~$160/month combined.

---

## What to explicitly skip and why

The following popular data sources would hurt training quality or add noise for your specific use case:

**Google Trends / pytrends**: Da, Engelberg, and Gao (2011) explicitly noted their attention effect is "most pronounced among small stocks." S&P 100 companies already have saturated media coverage — a Google Trends spike for Apple adds zero marginal information beyond what Finnhub news headlines already capture. Engineering effort is moderate (rate limiting, CAPTCHA management), signal is near-zero. The official Google Trends API launched in alpha in July 2025 doesn't change the fundamental problem that retail search behavior doesn't move trillion-dollar stocks.

**Reddit/StockTwits sentiment**: Warkulat and Pelster (2024) found WSB attention predicts retail net buying but is associated with *negative profits*. For mega-caps, retail sentiment cannot generate sufficient order flow to move prices. Adding this data teaches your model to weight noise.

**Short interest (FINRA free or Fintel paid)**: Bimonthly data with 10-day delay means the information is always stale relative to your 2–15 day holding period. For S&P 100 stocks with billions of shares outstanding, short interest ratios are consistently low and short squeeze dynamics are essentially non-existent.

**Congressional trading data**: Belmont et al. (2022, Journal of Public Economics) found stocks bought by House Members *underperformed* by 26 bps over 6 months post-STOCK Act. The 45-day filing delay makes this useless even if the signal existed. Politicians predict small company returns better than large — exactly the wrong profile for your universe.

**Fails-to-deliver data**: FTDs are a settlement issue for illiquid, hard-to-borrow stocks. S&P 100 stocks have deep, liquid markets with robust clearing. FTD data for mega-caps is consistently near zero.

**Multiple redundant technical indicators**: RSI, Stochastic Oscillator, and Williams %R all measure short-term mean-reversion — they are the same signal expressed three ways. Including all three inflates the apparent importance of overbought/oversold conditions and causes overfitting. **Choose one per concept**: RSI-14 for mean-reversion, ADX for trend strength, OBV for volume confirmation.

**Supply chain/network effects**: Cohen and Frazzini's (2008) customer-supplier momentum has lost statistical significance in recent samples. The monthly frequency and S&P 100 stocks being the *customers* (not the lagging suppliers) make this non-actionable.

**Tick/order book data**: Processing TB/day of microstructure data for signals that decay within minutes is engineering insanity for a 2–15 day strategy. Zero marginal value at your holding period.

---

## Updated training example architecture with 11 sections

Given the evidence, the optimal structure expands from your current 7 sections to **11 sections organized in 3 tiers**, consuming approximately **350–500 tokens** in telegraphic XML-attribute format. This fits comfortably within your 300–1,000 token budget while leaving headroom for the output thesis.

```xml
<input>
  <!-- TIER 1: ALWAYS PRESENT (~200 tokens) -->
  <ctx ticker="AAPL" date="2026-03-15" hold="2-15d"/>

  <price close="172.50" chg1d="-2.1%" chg5d="-4.8%" chg20d="+3.2%"
        hi52w="198.23" lo52w="155.01" atr14="3.42" vol_ratio="1.4"/>

  <trend ema9="174.1" ema21="176.3" ema50="170.2" ema200="165.8"
        regime="UPTREND" pullback="38.2%_fib" adx="32"/>

  <momentum rsi14="38" macd="-1.2" macd_hist="-0.4"
           rel_str_spy="+4.2%_20d" obv_trend="RISING"/>

  <regime vix="18.5" vix_slope="+0.28/mo" vvix="95" skew="135"
         spy_trend="UP" breadth="POSITIVE" sector_rs="+1.2"/>

  <!-- TIER 2: HIGH-PRIORITY CONDITIONAL (~120 tokens, 80-90% inclusion) -->
  <fundamentals pe_fwd="24.1" rev_growth="8.2%" eps_surprise="+4.2%"
               next_earn="42d" est_revisions="+3_30d" guidance="RAISED"/>

  <macro hy_oas="385bp" hy_chg_1w="+22bp" fed_rate="5.25%"
        yield_2s10s="+45bp" dxy="104.2" dxy_trend="UP"/>

  <sentiment news_3d="-0.3" news_vol="HIGH" insider_net="-2.1M"
            analyst_consensus="BUY" upgrades_30d="3"/>

  <!-- TIER 3: ENHANCEMENT (~80 tokens, 40-60% inclusion) -->
  <options iv_rank="45" pc_oi="0.85" skew_25d="-4.2"
          sweep_bias="BULLISH" unusual="CALLS_HEAVY"/>

  <intermarket gold_copper="530" crude_chg="-1.2%"
              peer_avg_chg="-1.8%" btc_chg="-3.0%"/>

  <calendar fomc_days="3" opex_days="8" earn_density="22%"
           month_effect="POSITIVE" tom_window="YES"/>
</input>
```

This architecture reflects several critical design decisions. **Telegraphic XML-attribute format** saves approximately 60% of tokens versus natural language descriptions — `rsi14="38"` tokenizes in ~4–5 tokens versus "The 14-period RSI is at 38, indicating oversold conditions" at 15–20 tokens. Qwen3 handles XML parsing well given its code/structured-data pretraining. The model's task becomes **synthesis and decision rather than extraction**, which is more tractable for a fine-tuned 8B model.

**Tier 1 sections are always present** because the LIMA (Zhou et al. 2023) "Superficial Alignment Hypothesis" implies your fine-tuning teaches format and decision logic, not financial knowledge. Consistent Tier 1 exposure ensures the model reliably learns signal interrelationships. **Tier 2 sections appear in 80–90% of examples**, excluded only when data is genuinely unavailable. **Tier 3 sections appear in 40–60% of examples**, creating the natural variation that Trading-R1's random subsetting approach provides.

The `<regime>` section merges your current Market Regime and adds VIX term structure data (slope, VVIX, SKEW) — capturing the full volatility surface dimension in a single section. The `<macro>` section now includes credit spreads (HY OAS) and DXY alongside FRED data, consolidating the macro-regime and credit-conditions dimensions. The `<fundamentals>` section adds **earnings revision tracking** (`est_revisions="+3_30d"` meaning 3 net upward revisions in 30 days) — the strongest fundamental signal for large-caps at intermediate horizons per Novy-Marx (2015).

---

## Modified random subsetting beats Trading-R1's full approach

Trading-R1 created 20 variations per date-ticker by randomly including/excluding entire data source categories from their 20–30K token examples. For your 350–500 token compressed inputs, the full Trading-R1 approach is both unnecessary and counterproductive. Their redundancy allowed random removal without information loss. Your telegraphic format has no redundancy to spare.

**Adopt a tiered subsetting strategy instead**: keep all 5 Tier 1 sections in every example (non-negotiable), randomly include 2–3 of the 3 Tier 2 sections (probability 0.85 each), and randomly include 0–2 of the 3 Tier 3 sections (probability 0.45 each). This generates **5–8 meaningful variations per date-ticker** rather than Trading-R1's 20, which is appropriate given your smaller combinatorial space. The benefits are preserved: data augmentation (critical when your base dataset may be 5–20K examples for 100 stocks), robustness to real-world data incompleteness (API failures during live trading), and regularization against overfitting to feature co-occurrence patterns.

One key modification: **when a Tier 3 section is excluded, include a null marker** (`<options available="NO"/>`) rather than simply omitting the tag. This teaches the model to explicitly reason about missing information rather than silently ignoring absent sections. Trading-R1's approach of silent omission works at 20–30K tokens where the model barely notices a missing category. At 350–500 tokens, the model should know what it doesn't know.

For QLoRA hyperparameters, start with **rank 32, alpha 64** targeting all linear layers. Lightning AI's extensive experiments confirmed alpha = 2× rank as the validated sweet spot. Higher feature density does not require higher rank — LoRA rank controls behavioral adaptation capacity, not input dimensionality. On RTX 3060 12GB with gradient checkpointing and bf16, this fits comfortably at batch_size=1 with gradient accumulation. After upgrading to RTX 3090, you can explore rank 64 or enable a GRPO reinforcement learning stage following Trading-R1's three-stage pipeline. Use **Unsloth** for 2x speedup and ~50% memory reduction through kernel optimizations.

---

## Implementation roadmap aligned with your phase gates

**Phase 1 expansion (now → 50-trade paper trading gate, ~2 weeks effort)**

Week 1 delivers three free quick wins requiring zero new API registrations. Add credit spreads (6 FRED series: BAMLH0A0HYM2, BAMLC0A0CM, T10Y2Y, BAMLC0A4CBBB) to your existing FRED pipeline — approximately 30 minutes of work. Add VIX term structure (^VIX, ^VIX3M, ^VVIX, ^SKEW via yfinance) to your Market Regime section — approximately 30 minutes. Add cross-asset prices (DX-Y.NYB, GC=F, HG=F, CL=F, BTC-USD, 5 sector ETFs via yfinance) as a new `<intermarket>` section — approximately 1 hour. Add calendar event features (hard-code FOMC dates, compute days-to-event features) as a new `<calendar>` section — approximately 1 hour. Total: **~3 hours of engineering** to go from 7 sections to 11 sections.

Week 2 implements the modified random subsetting augmentation pipeline. For each date-ticker in your training data, generate 5–8 variations with different Tier 2/3 inclusion patterns. Regenerate training examples using Claude Haiku 4.5 with the expanded 11-section input template. This expands your ~13 trade examples into ~65–104 training variations.

**Phase 2 (50-trade gate passed → live trading activation, ~1 month)**

Subscribe to Unusual Whales (~$50/month) and build the options flow pipeline. Add the `<options>` section with IV rank, put/call OI ratios, sweep bias, and unusual activity flags. Begin building your proprietary earnings revision momentum dataset by tracking FMP/Finnhub analyst estimate changes daily — this accumulates into a valuable time series for the `est_revisions` feature in your `<fundamentals>` section. Consider adding individual stock options metrics via yfinance (IV, skew, P/C OI) as a free complement to Unusual Whales flow data.

**Phase 3 (live trading profitable → scaling to $50K+ AUM)**

Evaluate Polygon.io Options Developer ($79/month) for historical IV surface data to improve options-informed signals. Consider ORTEX Advanced ($79/month annual) if daily short interest rate-of-change during pullbacks shows signal in your backtesting. At this scale, the $160–210/month total data spend is justified if the system generates even 5 bps additional alpha per trade across 25 monthly trades on $50K deployed.

**What NOT to build at any phase**: Google Trends scraping pipeline, Reddit/StockTwits sentiment analysis, congressional trading tracker, FTD data parser, Wikipedia pageview monitor, tick data infrastructure. The combined engineering effort for these would exceed 40 hours, and the expected marginal signal for S&P 100 stocks is near zero.

---

## Conclusion: density beats dimensionality

The research reveals a counterintuitive insight: **maximizing horizontal feature density for S&P 100 mega-caps means adding fewer dimensions than you'd expect, but making each one count**. The binding constraint isn't "what data exists" but "what data retains predictive power after publication, after arbitrage, and after filtering to the most efficiently priced securities in the world."

Your system's edge comes from three sources that compound. First, **the right 8 orthogonal dimensions** — momentum/reversal, volume, options-implied, earnings revisions, news/sentiment, macro regime (with credit and VIX term structure), cross-asset, and calendar effects — cover the viable signal space for S&P 100 at 2–15 day horizons. Adding a 9th noise dimension hurts more than helps. Second, **aggressive compression** into 350–500 token telegraphic XML creates information density that Trading-R1's 20–30K token natural-language approach cannot match per token — your model processes pre-extracted features rather than raw text, making its task synthesis rather than extraction. Third, **modified random subsetting** with tiered inclusion creates the training diversity that LIMA principles demand, while maintaining consistent core signal exposure.

The most underappreciated finding is that **earnings revision momentum is the highest-value signal you're not yet tracking**. It's the one fundamental signal that works for large-caps at intermediate horizons, with academic support from multiple independent studies. Building a proprietary revision tracker using your existing FMP/Finnhub estimate data requires moderate engineering effort but adds a genuinely orthogonal dimension with documented effect sizes that survive in modern, liquid markets. Prioritize this over any flashier alternative data source.