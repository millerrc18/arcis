# Optimal holding periods for Halcyon Lab's three equity strategies

**The single most important finding: your pullback and PEAD strategies are likely holding too long, while your mean reversion window is roughly correct.** Across academic literature and practitioner backtests, large-cap pullback alpha concentrates in days 1–5 (capturing ~80–85% of total edge), RSI(2) mean reversion completes in 3–5 trading days, and traditional PEAD is effectively dead for S&P 100 stocks since 2006—though ML-enhanced composite signals can revive it with a 5–10 day window. The evidence strongly supports strategy-specific timeouts, tightening stops as edge decays, and MFE/MAE-driven parameter calibration once Halcyon accumulates 100+ closed trades per strategy.

---

## The pullback alpha decay curve peaks by day 5

The most consequential data point for your pullback-in-uptrend strategy comes from Cesar Alvarez's multi-year research: **after 6 bars, the average pullback trade becomes a loser.** This is not a gradual decline—it functions more as a cliff than a slope. Jeff Swanson's 30-year SPX backtest (1983–2013) confirms the shape: days 1–5 show steep, rapid P&L accumulation, days 5–14 show decelerating growth, and beyond day 14, cumulative P&L actually declines.

The synthesized alpha capture curve for S&P 100/large-cap pullback-in-uptrend entries:

| Trading Day | Cumulative Alpha Captured | Marginal Alpha Quality | Estimated Win Rate |
|:-----------:|:------------------------:|:---------------------:|:-----------------:|
| Day 1 | ~25–30% | Highest | 55–60% |
| Day 2 | ~45–55% | Very high | 60–65% |
| Day 3 | ~60–70% | Moderate | 65–75% |
| Day 5 | **~80–85%** | Declining | 70–82% |
| Day 7 | ~90–95% | Near-zero | Declining |
| Day 10 | ~95–100% | Zero or negative | Declining further |
| Day 15 | ≤100% (negative after costs) | Negative after opportunity cost | N/A |

**Your current 15-day hard timeout is too generous.** The evidence points to an optimal window of **5–10 days** for pullback trades on highly liquid large-caps. Connors & Alvarez's original research found that a 5-period moving average exit (averaging ~3 day holds) produced an **82–83% win rate** on the S&P 500 with a profit factor of 2.97. Extending to a 10-period MA exit captured more total profit but at lower efficiency—profit factor dropped to 2.74.

The most striking finding from Alvarez's systematic testing of exit methods was that the **"first up close" exit**—exiting at next open after the first day price closes higher than the prior day's close—produced the best risk-adjusted statistics of any exit tested. This implies the actionable alpha concentrates in the initial snapback, often days 1–2. Per-trade alpha is smaller, but dramatically shorter holds unlock far more capital turnover.

**Recommendation: reduce pullback timeout from 15 to 8 days.** Use a dynamic primary exit (close above 5-day SMA or first up close) with the 8-day timeout as a safety net. This captures >90% of available alpha while freeing capital 40–50% faster.

---

## RSI(2) mean reversion completes in 3–5 days for large-caps

Larry Connors' original RSI(2) strategy in *Short Term Trading Strategies That Work* (2008) specified: RSI(2) closes below 5 with price above the 200-day MA → buy on the close → **exit when price closes above the 5-period SMA**. On the S&P 500 from 1995–2007, this produced **83.6% win rate, 49 trades, and an average hold of 3 trading days**. The cumulative RSI variant (exit when RSI(2) crosses above 65) averaged 3.7 days with an **88% win rate**.

Modern backtesting confirms these durations hold. Quantified Strategies tested RSI(2) < 10 with their proprietary "QS Exit" (close > yesterday's high) on SPY and found an **average hold of 4.8 days** with higher risk-adjusted returns than RSI-based exits. The Concretum Group's massive study of **114,189 trades** across all historical S&P 500 constituents using RSI(2) < 5 with a 5-day time stop produced a mean return of **45 basis points per trade** and a 64% hit ratio.

The critical pattern across all sources: **trades not reverting by day 8–10 are almost certainly losers.** The Systematic Algo Trader found that "nearly every trade that went longer than 8 days was a loss." Alvarez's N-day exit study showed average trades turn negative after day 6.

For the RSI(2) < 5 versus < 10 threshold question, the evidence is nuanced. RSI(2) < 5 produces **higher per-trade returns** but fewer signals. RSI(2) < 10 generates more trades and better portfolio-level results due to higher capital utilization. Quantitativo's analysis on Nasdaq-100 stocks found that post-2010, RSI thresholds of 15–20 actually performed comparably to tighter thresholds, suggesting the optimal threshold may have shifted as markets became more efficient.

**Your planned 1–5 day hold is correct.** The optimal configuration for S&P 100 RSI(2) mean reversion:

- **Primary exit**: Close above 5-day SMA (Connors original) or close > yesterday's high (QS Exit)
- **Time stop**: 5 days as default, extend to 7 days maximum for RSI(2) < 5 entries
- **Hard stop**: Avoid tight price stops entirely—Connors' extensive testing concluded "stops hurt mean reversion performance." Use a catastrophic stop at **3.0x ATR** or 5% maximum as a tail-risk safety net only
- **Expected average hold**: 3–4 days
- **Expected win rate**: 65–75% on individual S&P 100 stocks (lower than index-level backtests due to idiosyncratic noise)

---

## Traditional PEAD is dead for mega-caps, but composite signals revive it

This is perhaps the most strategically important finding for Halcyon's PEAD strategy. **Martineau (2022) in *Critical Finance Review* demonstrated that post-earnings announcement drift has been non-existent for non-microcap stocks since 2006.** Prices began fully reflecting simple earnings surprises on the announcement date itself, driven by decimalization, Reg NMS, and faster algorithmic price discovery. Subrahmanyam (2025) confirmed this: when excluding microcaps, the PEAD t-statistic drops to **1.43—statistically insignificant**.

However, Kaczmarek & Zaremba (2025) in *Finance Research Letters* demonstrated that ML-enhanced PEAD strategies can revive the anomaly specifically for large-caps. Their approach uses elastic net models on **12 quarters of historical SUE data**, and critically, the **gains are strongest among large-cap stocks** where recent surprise is quickly priced but older earnings patterns remain overlooked. Sharpe ratios nearly doubled versus single-quarter SUE models. Similarly, PEAD.txt (Meursault et al., 2023, *Journal of Financial and Quantitative Analysis*) showed text-analysis-based earnings surprise measures produce **8.01% annual drift** over 252 days—suggesting markets still underprocess unstructured information.

For your "evolved PEAD" composite signal, the drift curve for large-caps concentrates heavily in early days. Historical Bernard & Thomas (1989) data showed the first 5 days captured **~20% of the 60-day drift** for large firms. In modern markets with faster information processing, this concentration has only intensified. Practitioner analysis identifies **day 9 as the plateau point** where the drift effect has largely exhausted.

The asymmetry between positive and negative surprises matters: research documents that **positive surprise drift is stronger** than negative surprise effects for large-caps, though negative surprises produce faster initial price adjustment.

**Recommendation: reduce PEAD time barrier from 10 to 7 trading days.** Your current 10-day triple barrier is reasonable but slightly long for S&P 100 mega-caps. A 7-day vertical barrier captures the vast majority of composite-signal drift while reducing dead-capital exposure. Consider asymmetric timeouts: **5 days for negative surprise shorts, 7–8 days for positive surprise longs.** Adjust the take-profit from 3x ATR to 2x ATR for mega-caps—the drift magnitude is smaller than historical estimates suggest.

---

## Strategy-specific timeouts and adaptive stop tightening

The evidence overwhelmingly supports differentiated timeout parameters. Each strategy exploits a different market inefficiency with a distinct temporal profile:

| Strategy | Recommended Timeout | Primary Exit | Initial Stop | Stop at Timeout |
|:---------|:------------------:|:------------:|:------------:|:---------------:|
| Pullback-in-uptrend | **8 days** | Close > 5-day SMA | 2.0x ATR | 1.5x ATR |
| RSI(2) mean reversion | **5 days** | Close > 5-day SMA or first up close | 3.0x ATR (catastrophic only) | Exit at market |
| Evolved PEAD | **7 days** | Take-profit at 2x ATR | 2.0x ATR | 1.25x ATR |

**On time-weighted stop tightening**, the concept is theoretically sound but requires careful calibration. Your proposed schedule of 2.0x ATR → 1.5x by day 5 → 1.0x by day 10 has one critical flaw: **1.0x ATR places the stop inside normal daily noise for S&P 100 stocks.** Typical S&P 100 daily ATR ranges from 1.2–2.5% of price (Charles Schwab data, March 2025). A 1.0x ATR stop will frequently trigger on routine intraday fluctuations, especially around gap openings.

The modified schedule should be: **2.0x ATR at entry → 1.5x ATR by day 5 → 1.25x ATR at timeout.** Never tighten below 1.25x ATR for large-cap equities. For the pullback strategy specifically, Arthur Hill's backtests on SPY/QQQ found that a Chandelier Exit with parameters (22,1)—the tighter variant—**consistently outperformed the wider (22,2) setting**, with 83% win rates and the best CAR/MDD ratios.

**Moving stops to breakeven is generally counterproductive.** Multiple practitioners document that markets commonly test recent entry areas before continuing in the intended direction. Premature breakeven moves place stops exactly where natural pullbacks cluster. If you implement breakeven adjustment, wait until the trade has moved at least **1.5R** in your favor, and move only 50% of the position to breakeven.

For **mean reversion specifically, the evidence is clear: avoid tightening stops at all.** Connors, Curtis Faith, and academic research converge on the finding that stop-losses systematically hurt mean reversion performance. The CFA Institute (Xiong, 2026) documented that tight stops "systematically remove investors during precisely the early volatile stage, not because the underlying signal is invalid, but because short-term price fluctuations exceed arbitrarily tight thresholds." For RSI(2) trades, use only the time stop—exit at day 5 regardless of position, or exit on strength signal, whichever comes first.

**Opportunity cost is the underappreciated driver.** With 13 scans per day producing 5–15 candidates, Halcyon generates more signals than it can execute with 8 position slots. Every day a stale position occupies a slot, a fresh high-probability signal goes unexploited. A rough estimate: each day a non-performing trade holds a slot, **5–10 basis points of potential alpha is forfeited** from the missed redeployment opportunity.

---

## Using MFE/MAE to empirically calibrate parameters

Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE), introduced by John Sweeney in *Maximum Adverse Excursion* (Wiley, 1997), provide the empirical framework for moving beyond theoretical recommendations to data-driven parameter optimization.

**For each closed trade**, compute MAE (entry price minus lowest low during hold, for longs) and MFE (highest high minus entry price). Express both in **R-multiples** (risk units = initial stop distance) for cross-strategy comparability. The critical visualization is a scatter plot of MAE versus final P&L, with winners and losers color-coded. Winning trades should cluster near zero MAE; the MAE level that **70–80% of winners never exceed** becomes your empirical stop-loss candidate.

The **MFE time profile**—a scatter plot of time-from-entry-to-MFE-peak versus MFE magnitude—directly determines optimal holding period. If 80% of winners reach peak MFE within 5 days, your time stop should be set at 7–8 days to capture stragglers while limiting dead-money exposure.

Different strategy types produce distinct MFE/MAE signatures. Mean reversion trades show **high MAE relative to MFE** (price moves further against before reverting) with fast MFE peaks (1–3 days). Momentum/PEAD trades show lower MAE relative to MFE with longer time-to-peak. This structural difference is precisely why strategy-specific parameters are essential.

**Halcyon's sample size assessment**: With ~50 closed trades across three strategies, you have approximately ~17 trades per strategy. This is **insufficient for per-strategy calibration** (minimum 30 trades required for preliminary analysis, 100+ for reliable optimization). However, you can immediately begin:

- Logging MFE, MAE, and time-to-MFE for all trades (open and closed)
- Running aggregate scatter plots across all strategies to identify gross misconfigurations
- Using paper trades with a **10–20% slippage penalty on MAE** to supplement the sample
- Targeting 100 closed trades per strategy before making definitive parameter changes
- Using Monte Carlo simulation on current samples to estimate confidence intervals

---

## Position sizing should reflect capital velocity, not just per-trade risk

Your 1% risk per trade with 8 concurrent positions is well-calibrated for $100K capital, producing maximum portfolio heat of **8%—conservative and appropriate for an early-stage system.** The key insight on holding period interaction: per-trade risk should remain constant (1%), but **shorter-hold strategies generate higher annualized returns through capital turnover**.

The mathematics are straightforward. Sharpe ratio scales with **√(number of independent bets).** A 3-day mean reversion strategy generating 60 trades per year with 0.1 per-trade Sharpe produces an annualized Sharpe of 0.1 × √60 ≈ **0.77.** A 10-day PEAD strategy generating 20 trades per year with 0.15 per-trade Sharpe yields 0.15 × √20 ≈ **0.67.** The mean reversion strategy is more capital-efficient despite lower per-trade edge.

For multi-strategy allocation, use **annualized-volatility-based risk parity**: weight each strategy proportional to the inverse of its annualized P&L volatility, so each contributes equally to portfolio risk. Rebalance quarterly. In practice, this means your faster-turning RSI(2) strategy should receive somewhat more capital allocation than its per-trade statistics alone would suggest, because the same capital produces more total opportunity.

Apply **quarter-Kelly** (25% of the Kelly-optimal fraction) as a sanity check once you have 100+ trades per strategy with reliable win rates and payoff ratios. For a strategy with 70% win rate and 1.5:1 reward-to-risk: Kelly% = 0.70 − (0.30/1.5) = 50%; quarter-Kelly = **12.5%** per trade. Your 1% risk constraint is well below this, providing substantial safety margin while the system matures.

---

## Concrete parameter recommendations for Halcyon Lab

Based on the full weight of academic and practitioner evidence, here are specific, implementable parameters for each strategy:

**Pullback-in-uptrend**: Change hold window from 2–15 days to **2–8 days**. Use close above 5-day SMA as primary exit. Set initial stop at 2.0x ATR, tightening to 1.5x ATR by day 5. If the trade hasn't moved 50% toward target by day 4, consider early exit. Expected alpha capture at day 8: >95%.

**RSI(2) mean reversion**: Maintain planned 1–5 day window. Use "exit on strength" (close above 5-day SMA or close > yesterday's high) as primary exit, with 5-day hard timeout. Do not use tight ATR-based stops—use only a catastrophic stop at 3.0x ATR. For RSI(2) < 5 entries, extend timeout to 7 days. Expected average hold: 3–4 days. Expected win rate: 65–75%.

**Evolved PEAD**: Reduce from 10-day to **7-day triple barrier**. Lower take-profit from 3x ATR to 2x ATR for mega-caps (drift magnitude is modest). Keep stop at 2.0x ATR. Consider asymmetric timeouts: 5 days for short positions, 7 days for longs. Monitor whether the composite signal genuinely produces drift beyond day 5—if MFE time profile shows peak at day 3–4, further reduce the window.

**Immediate action items**: Begin MFE/MAE logging for all trades. Run aggregate scatter plots at 50 closed trades. Implement strategy-specific timeouts as outlined. Backtest tighter pullback timeouts on historical data before deploying live. The evidence is clear that holding periods shorter than current parameters will improve capital efficiency without sacrificing meaningful alpha.