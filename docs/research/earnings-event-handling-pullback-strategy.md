# Earnings events are pure gap risk for your pullback strategy — avoid them

**For a mechanical pullback-in-uptrend strategy on S&P 100 stocks with 2–8 day holds and 2× ATR bracket exits, earnings announcements represent unmanageable binary risk with no compensating return.** Post-earnings announcement drift is dead for mega-caps (confirmed through December 2024 data), meaning holding through earnings adds catastrophic gap exposure without directional edge. The recommended approach: implement a **7-calendar-day entry exclusion zone** and a **2-day forced-exit rule** for open positions approaching earnings. This sacrifices roughly 8% of the opportunity set on average — a small price for eliminating tail scenarios where a -15% overnight gap vaporizes months of accumulated gains.

The core tension is straightforward. Your strategy profits from mean-reversion in orderly markets. Earnings destroy orderly markets for individual stocks, creating overnight gaps of 3–20% that bypass any stop-loss. Since no US equity broker guarantees fill quality during gaps, and since PEAD offers no post-event drift to capture, earnings are asymmetrically dangerous to short-horizon mechanical systems.

---

## Mega-cap earnings gaps routinely exceed 2× ATR stops

Empirical data on S&P 100 earnings gap sizes paints a clear picture of the threat to bracket-order systems. The **median absolute earnings-day gap for mega-cap stocks is 2–4%**, while the **mean is 4–6%**, heavily skewed by outlier events. For high-volatility names like NVDA, TSLA, and META, the average absolute gap climbs to **6–10%**, with individual quarters producing moves of 15–25%.

The distribution matters more than the average for risk management. Roughly **60–70% of large-cap earnings announcements produce moves exceeding 2%**, which already threatens a typical 2× ATR stop on a $200 stock with 14-day ATR of $4 (stop at $8, or ~4%). About **25–40% of mega-cap earnings events gap more than 5%**, and **10–15% exceed 10%**. Exceptional moves — META's -26% in February 2022, NVDA's +24% in February 2023 — occur roughly once per year across the S&P 100 universe.

NVDA's last ten quarters illustrate the dispersion problem. Earnings-day absolute moves ranged from **0.53% to 24.36%**, with a mean of ~8.5% and median of ~7.9%. Even the "quiet" quarters produced moves of 2–6%, enough to breach most ATR-based stops. The options market consistently priced NVDA's expected earnings move at 7–9.5% (via straddle pricing), yet actual moves exceeded this in several quarters. For your 2× ATR bracket system, a stock with ATR of 3% would have a stop at 6% — well within the range of common mega-cap earnings gaps.

These gaps are getting larger in impact, though not uniformly in magnitude. **Index concentration has nearly doubled** — the top 10 S&P 500 stocks grew from ~19% of index weight in 2015 to ~41% by end of 2025. Goldman Sachs has noted rising dispersion between dominant companies, meaning individual mega-cap earnings reactions are becoming more idiosyncratic. Most S&P 100 mega-caps report after the close (AMC), meaning gaps materialize at the next day's open after repricing in thin after-hours liquidity with wider spreads.

---

## Stop-loss orders are structurally incapable of protecting against earnings gaps

The gap-through problem is not probabilistic — it is **deterministic**. When a stock gaps past your stop price at the open, the stop-market order converts to a market order and fills at the opening price. If your stop is at -4% and the stock opens at -12%, you absorb the full -12% loss. The stop provided zero protection.

Critical broker-specific behaviors compound this risk. **Interactive Brokers' default stop orders do not trigger outside regular trading hours** for US equities. A standard GTC stop will sit dormant while an after-hours earnings reaction drives the stock down 15%. Even with `outsideRTH=True` enabled, the stop converts to a market order in a thin after-hours market with wide spreads, potentially filling **worse** than the already-gapped price. **Alpaca only accepts limit orders during extended hours** — stop and stop-limit orders are not eligible for extended-hours execution, leaving positions completely unprotected during after-hours earnings announcements.

No major US equity broker — IB, Alpaca, Schwab, Fidelity, or Vanguard — guarantees fill quality on stop orders during gaps. IB's documentation explicitly states: *"A Stop order becomes marketable and is intended to fill — regardless of price — once the determined trigger price is pierced. It does not have a specific execution price and may execute significantly away from its Stop price."* Guaranteed stop-losses exist only through CFD/spread-betting brokers (IG Markets, CMC Markets) at a 0.3–1% premium, and are unavailable for direct US equity trading.

Stop-limit orders present an arguably worse alternative: they may **skip entirely** if the gap exceeds the limit price, leaving you fully exposed to continued downside with no exit execution at all. Academic research from Arratia and Dorador (2019, *Quantitative Finance*) found approximately **5% slippage from gap events** in models incorporating overnight gaps, with gap cost representing the dominant cost factor exceeding transaction costs. Most critically, SMB Training's study of S&P 500 gaps found that **large gaps (>5%) close within the same day only 9.6% of the time** — meaning earnings gaps are typically not recoverable intraday.

---

## The 7-day exclusion zone balances protection against opportunity cost

Academic and practitioner evidence converges on a **5–7 trading day pre-earnings exclusion window** as optimal for strategies with 2–8 day holding periods. This window captures the period when pre-earnings dynamics most diverge from normal price behavior, while minimizing the reduction in tradeable universe.

The pre-earnings period exhibits systematically different price dynamics that undermine pullback strategy assumptions. Frazzini and Lamont's landmark 2007 NBER study documented a robust pre-earnings announcement premium — stocks rise on average into earnings, driven by predictable increases in trading volume and individual investor buying. Kelly (2016, Notre Dame) found returns **11 basis points higher per day** in the 5 days before earnings for high-extrapolation stocks. Top-percentile past-winner stocks earn **1.58% cumulative market-adjusted returns** during the 5 trading days preceding announcements. This upward bias means a pullback occurring within this window may be fighting a systematic drift rather than exhibiting normal mean-reversion behavior.

Implied volatility follows a predictable lifecycle: gradual rise starting 2–3 weeks out, acceleration 5–7 days before earnings, a final 5–10 percentage point spike in the last 48 hours, then a **30–60% collapse** (the "IV crush") post-announcement. This volatility ramp inflates realized price swings in the pre-earnings window, increasing the probability of premature stop-loss triggers even before the announcement itself.

So and Wang (2014) documented a **six-fold increase in short-term return reversals** during earnings windows — the LOW-HIGH reversal strategy yielded 1.45% over 3 days during earnings windows versus 0.22% during non-earnings periods. While this suggests enhanced mean-reversion opportunity, the magnitude of potential adverse moves makes the risk-reward calculation unfavorable for a system without earnings-specific logic.

The opportunity cost of exclusion is manageable. With ~100 S&P 100 stocks each reporting 4 times annually and a 7-calendar-day exclusion zone, approximately **2,800 stock-days are excluded** from ~25,200 total (100 stocks × 252 trading days), roughly **11% on average**. However, earnings cluster heavily into 4–5 peak weeks per quarter. During these peak weeks, **25–40% of the S&P 100 universe** may simultaneously fall within the exclusion zone. Outside peak weeks, exclusion drops to 0–3%. This clustering is the primary cost — the strategy will have significantly fewer candidates during January/February, April/May, July/August, and October/November peak reporting periods.

---

## Pre-earnings pullbacks look like opportunities but carry hidden binary risk

Pullbacks occurring 3–7 days before earnings are fundamentally different from normal pullbacks, and your system cannot distinguish between them without explicit earnings calendar logic. The causes are structural: institutional hedging and position reduction before the binary event, elevated market-maker inventory risk demanding higher compensation for liquidity provision, and corporate insider trading blackout periods (78% of companies restrict insider trading starting 11+ days before quarter-end) removing a source of natural buying support.

The academic evidence is ambiguous on whether pre-earnings pullbacks are bullish or bearish. UCLA Anderson research by Friedman and Zeng (2010–2021 data) found that professional investors drive prices in the direction that **correctly predicts** the earnings surprise — "the pros know what to expect." If a stock is pulling back despite informed institutional buying, temporary retail selling may be creating an opportunity. However, in stocks with high retail trader concentration, pre-announcement price movement is a **poor predictor** of the actual surprise.

The practical problem for your system is stark. A pullback signal that fires 5 days before earnings looks identical to any other pullback signal in your current logic. But entering this trade means your 2–8 day holding period will almost certainly span the earnings announcement. Your 2× ATR bracket exit will then face a potential overnight gap of 5–15%, far exceeding the stop distance. The mean-reversion thesis that underlies the pullback entry becomes irrelevant when a binary information event can shift the stock's fair value by 10%+ in either direction overnight.

The safest approach supported by evidence: if you do trade pre-earnings pullbacks, **enter the pullback but exit via market-on-close (MOC) order 1–2 days before the announcement**. This captures the pre-earnings drift (worth ~30 bps/day for the strongest names) and mean-reversion recovery without bearing the announcement gap risk. MOC orders execute in the highest-liquidity period of the trading day (closing auction), ensuring minimal slippage.

---

## Post-earnings announcement drift is dead for S&P 100 stocks

The question of whether earnings events offer compensating return for their risk has been definitively resolved. Martineau's 2022 paper in *Critical Finance Review* demonstrated that **PEAD has been non-existent for large-cap stocks since 2006**, attributing the disappearance to decimalization (2001) and Regulation NMS (2005), which enabled faster arbitrage and more complete price discovery around announcements.

Subrahmanyam's 2025 working paper (SSRN 5930255) provides the definitive resolution to an apparent contradiction. Two recent papers — Dickerson, Julliard, and Mueller (forthcoming, *Journal of Financial Economics*) and Hirshleifer, Peng, and Wang (2025, *Review of Financial Studies*) — claimed PEAD remained significant. Subrahmanyam showed the contradiction is **entirely explained by microcap stocks**. Replicating the Dickerson et al. earnings drift factor from February 2001 to December 2024, the t-statistic drops from **2.18 (including all stocks) to 1.43 (excluding microcaps)** — well below statistical significance. Microcaps represent only ~3% of total market value but are numerous enough to drive aggregate statistical tests while being too illiquid to trade profitably.

Two nuances deserve mention. First, Kaczmarek and Zaremba (2025, *Finance Research Letters*) showed that machine learning models using 12 quarters of historical earnings data can "revive" PEAD, with gains **especially strong among large-cap stocks**. But this is not traditional PEAD — it requires sophisticated multi-quarter pattern recognition, not simple post-surprise drift. Second, Meursault et al. (2023, *JFQA*) found that text-based earnings surprise measures from NLP analysis of earnings calls produce drift **larger** than classic numeric PEAD, even in recent years. These signals require infrastructure far beyond a mechanical bracket-order system.

The earnings announcement premium — a distinct phenomenon where stocks earn abnormal returns during announcement months — shows mixed survival. Savor and Wilson (2016, *Journal of Finance*) found annualized abnormal returns of **9.9%** for announcing firms, interpreted as compensation for bearing systematic information risk. However, Heitz, Narayanamoorthy, and Zekhnini (2020) found this premium **disappeared in the US after ~2004** following disclosure regulation changes, though it may persist for the very largest stocks. For your system's purposes, the conclusion is clear: **holding S&P 100 stocks through earnings adds event risk with negligible to zero directional edge**.

---

## Implementation: a three-layer defense architecture

The earnings defense system should operate at three points in your strategy pipeline, ordered by priority.

**Layer 1 — Entry filter (ranker/screener level).** Before generating any pullback signal, exclude stocks with earnings within 7 calendar days. This is the primary defense and prevents the most dangerous scenario: entering a new position that will hold through an earnings announcement. Implementation requires a daily pre-market query against an earnings calendar API. Recommended data sources include Finnhub (60 free requests/minute, `/calendar/earnings` endpoint), Financial Modeling Prep (comprehensive, well-documented), or Alpha Vantage (`EARNINGS_CALENDAR` function, 25 free requests/day). For QuantConnect users, the `EODHDUpcomingEarnings` dataset integrates natively.

**Layer 2 — Position management (executor/risk governor level).** Run a daily audit of all open positions against the earnings calendar. If any position's next earnings date falls within **2 calendar days**, execute a forced exit at the next market open or via MOC order. This catches positions where an earnings date was updated or moved after entry. The rule is unconditional — exit regardless of current P&L. As one practitioner source articulates: *"Holding the position through the announcement transforms the trade from a systematic speculation on sentiment into a binary gamble on the news itself."*

**Layer 3 — Post-earnings cooldown.** After a stock reports earnings, impose a **2-trading-day cooldown** before allowing new entries. This allows the post-earnings price level to stabilize and the gap to be absorbed. Corporate insider trading policies provide a useful benchmark — 46% of companies allow insider trading to resume 2–3 trading days after earnings.

IV rank can serve as a **supplementary signal** but not a standalone replacement for the calendar-based filter. For stable S&P 100 names, IV rank rising above 50 outside of macro volatility events strongly correlates with an approaching earnings catalyst. The pattern is predictable: gradual rise 2–3 weeks out, acceleration at 5–7 days, peak in final 48 hours, then 30–60% collapse post-announcement. However, market-wide volatility spikes create false positives, and IV may not meaningfully rise until 5–7 days before earnings — providing inadequate lead time for a system needing 7+ days of advance warning. Use IV rank > 50 as a confirmation layer, not the primary filter.

The hybrid timing approach uses **calendar days for the pre-earnings exclusion** (because earnings can be reported on any calendar day, and Friday reports affect Monday opens) and **business days for the post-earnings cooldown** (because you want N trading sessions of actual price action before re-entering). The full protocol:

- **7 calendar days before earnings:** Block new entries for this ticker
- **2 calendar days before earnings:** Force-exit any open position in this ticker
- **Earnings day:** No action (ticker already cleared)
- **2 business days after earnings:** Allow ticker back into the universe

---

## Conclusion

The evidence overwhelmingly favors **calendar-based earnings avoidance** over adjustment or exploitation for your specific strategy architecture. Three findings drive this conclusion with particular force. First, median mega-cap earnings gaps of 2–4% and frequent gaps of 5–10% will reliably blow through 2× ATR stops, with no broker providing fill-quality guarantees — meaning your risk management framework is structurally defeated by earnings gaps. Second, PEAD's death for large caps (confirmed through 2024 data by Martineau and Subrahmanyam) eliminates any post-event directional edge that might compensate for gap risk. Third, the opportunity cost is modest — roughly 8–11% of the tradeable universe on average, concentrated in predictable peak weeks where the system can simply wait.

The one scenario worth monitoring: pre-earnings pullbacks in strong uptrends that can be entered and exited before the announcement, capturing the documented pre-earnings drift (~30 bps/day for top-decile stocks) and mean-reversion recovery. This is an optional enhancement requiring precise calendar logic and MOC exit execution 1–2 days before the report. It converts earnings proximity from pure risk into a time-bounded opportunity — but only if the exit discipline is absolute.

The implementation cost is minimal: a single API call daily to an earnings calendar service, a universe filter check, and a position audit. The protection is substantial: eliminating the strategy's single largest source of unmanageable tail risk.