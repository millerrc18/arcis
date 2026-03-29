# Halcyon Lab should expand to ~350 stocks immediately

**The S&P 100 is demonstrably too narrow.** Academic evidence from 2020–2026 is unambiguous: pooled cross-sectional ML models trained on broader stock universes outperform narrower ones by wide margins, and Halcyon's self-blinding architecture amplifies this advantage. The optimal universe for an 8B-parameter pullback model at sub-$1M AUM is **~300–350 stocks** — the S&P 500 filtered to >$100M average daily volume. This triples training data accumulation speed, improves generalization, and costs only ~$400/month more in infrastructure. Single-sector focus would be a strategic mistake at this stage, but sector *conditioning* (feeding sector as an input feature) is a free lunch that should be implemented immediately. A LoRA-adapter architecture for sector specialization becomes the right move at Phase 2, once the broader base model proves its edge.

---

## The academic case for broader training is overwhelming

Every major financial ML paper from the past six years trains on the broadest feasible cross-section — and the one study that explicitly tested narrowing found it degraded performance. **Gu, Kelly, and Xiu (2020)**, the most-cited paper in financial ML (~2,000 citations), trained neural networks on the entire cross-section of US stocks and generated **1.76% monthly alpha** on a value-weighted portfolio. They explicitly warned against filtering to the S&P 500 or smaller universes, noting it would be "clearly problematic to exclude" important stocks. Their deeper networks (NN3) benefited most from the full universe — more complex models extract more value from broader data.

**Cao and You (2024)**, winner of the Graham & Dodd Award, provided the most direct test of universe narrowing. Their pooled cross-sectional ML models beat firm-specific approaches by **6.7–9.9% in forecast accuracy** across 134,154 firm-year observations. When they estimated models on subsamples by industry, firm size, or analyst coverage, performance consistently worsened. Their conclusion was unequivocal: subsample estimation "leads to worse performance due to the smaller training sample." This finding directly answers whether Halcyon should narrow to a single sector — no.

The anonymization research validates Halcyon's self-blinding approach and simultaneously argues for breadth. **Kim, Muhn, and Nikolaev (2024)** at Chicago Booth showed that GPT-4 analyzing anonymized financial statements — stripped of company names, dates, and industry context — matched a specialized neural network at **~60% directional accuracy** and outperformed human analysts. The model couldn't identify which companies it analyzed, proving it learned generalizable financial patterns rather than ticker-specific memory. For Halcyon, this means the self-blinding pipeline is learning *strategy-level* pullback patterns, and these patterns benefit from seeing more diverse contexts (more tickers), not deeper repetition of the same tickers.

International evidence reinforces the point. Cakici et al. (2023) found across **46 countries** that ML performance scaled directly with the number of listed firms in the training universe. Tobek and Hronec (2021) showed US-trained patterns predicted international returns, confirming that cross-sectional patterns are universal rather than market-specific. The bias-variance tradeoff resolves cleanly: neural networks accommodate heterogeneous patterns through nonlinear interactions, effectively learning sector-specific rules *within* a pooled model.

---

## Why exactly 300–350 stocks, not 500 or 1,000

The optimal universe balances four constraints: training data diversity, liquidity, infrastructure cost, and signal quality. At Halcyon's current scale, these constraints converge on **S&P 500 membership filtered to >$100M average daily dollar volume**, which yields approximately **300–350 stocks**.

**Training data acceleration is the decisive factor.** At ~5 pullback signals per stock per year with a 50% trade rate, the math is stark:

| Universe | Trades/month | Months to 200 trades | Months to 500 trades |
|----------|-------------|---------------------|---------------------|
| S&P 100 (~100 stocks) | 20–25 | 8–10 | 20–25 |
| Filtered S&P 500 (~325 stocks) | 65–80 | 2.5–3 | 6–8 |
| Full S&P 500 (~500 stocks) | 100–125 | 1.5–2 | 4–5 |

At 100 stocks, reaching the **200-trade threshold** for institutional-grade statistical confidence (per López de Prado) takes 8–10 months. At 325 stocks, it takes under 3 months. This acceleration compounds: faster feedback loops mean faster model iteration, earlier detection of regime changes, and quicker accumulation of the proprietary labeled dataset that constitutes Halcyon's data moat.

The liquidity constraint is non-binding. At $10K maximum position size, Halcyon needs only **$1M daily volume** per stock (the standard 1% ADV rule). The least liquid S&P 500 stock trades ~$13M/day. Even S&P MidCap 400 stocks (ranks 501–900) trade $7.5M+/day. A $10K order on the smallest S&P 500 name represents **0.08% of daily volume** — invisible to the market. The S&P 100 constraint was never about liquidity; it was about simplicity. That simplicity now costs alpha.

Going beyond 350 to the full S&P 500 adds diminishing returns. Stocks ranked #350–500 have sparser news coverage, weaker analyst sentiment data, and **3–5x lower daily volume** than the median S&P 500 name. The enrichment pipeline degrades for these names: news providers return 1–3 articles/day versus 5–20 for larger stocks. The incremental 150 stocks add ~35% more training data but introduce measurably noisier signals. The Russell 1000 (~1,000 stocks) pushes further into mid-caps where fundamental enrichment quality drops materially and the backtesting compute burden doubles again.

**Infrastructure cost scales modestly.** Moving from S&P 100 to ~325 stocks increases monthly operating costs from roughly **$350–750 to $550–1,350** — dominated by data APIs and news/sentiment feeds, not LLM compute. Daily LLM scanning of 325 stocks costs under $10/month with GPT-4o mini or is essentially free with a self-hosted 8B model on a single GPU. The real cost is backtesting: a full 5-year backtest at 325 stocks requires ~400,000 inference calls, costing ~$60 with GPT-4o mini or ~$10 on self-hosted hardware.

---

## Sector conditioning is a free lunch; single-sector focus is not

Pullback patterns have both a universal component and a sector-specific component, and the evidence clearly favors capturing both within a single model rather than building separate sector models.

The universal component is dominant. **Ehsani and Linnainmaa** showed that momentum "is not a distinct risk factor" but rather "aggregates the autocorrelations found in all other factors." Factor momentum — the universal signal — generated **6.4% annualized returns** with a t-statistic of 5.55. This means the core pullback pattern (price drops toward a rising moving average in a strong trend, then resumes) shares a common statistical structure across sectors.

But sector-specific effects are real and exploitable. **Energy pullbacks** resolve faster due to commodity-driven mean reversion, with natural gas showing mean-reversion rates of **2.0–4.0 annually** (half of any deviation corrected in 60–125 trading days). **Healthcare/biotech pullbacks** face binary event risk from FDA catalysts and trial results that violate standard mean-reversion assumptions entirely. **Technology momentum** is stronger at short horizons but "more prone to overvaluation" (Bakshi and Chen, 2005), making pullbacks potentially deeper and slower to resolve. These differences are large enough to matter — sector rotation strategies exploiting them achieve **Sharpe ratios of 0.60–1.16** in backtests.

The practical recommendation is straightforward: **include GICS sector as an input feature** to the model (a one-hot encoding or learned embedding), not as a universe filter. This lets the 8B model learn conditional patterns ("pullback in Energy at 50-day MA → faster resolution than same setup in Tech") without sacrificing the training data volume that comes from cross-sectional pooling. Gu, Kelly, and Xiu (2020) included 74 industry dummies in their feature set and found them among the important predictors — the model implicitly learned sector-specific dynamics within the pooled framework.

**Single-sector focus would be a mistake now for three reasons.** First, it cuts training data by 70–90%, pushing the time-to-statistical-significance from months to years. Second, it concentrates drawdown risk — tech fell ~33% in 2022; a tech-only system would have had no diversification buffer. Third, Halcyon's self-blinding approach explicitly strips sector identity to learn structural patterns. Restricting the universe to one sector undermines the core design philosophy.

---

## The LoRA adapter roadmap for Phase 2

The academic literature on LoRA adapters has matured dramatically, and a **base model + sector-specific LoRA adapter** architecture is now production-ready. FinLlama (Imperial College/MIT) demonstrated that a LoRA-tuned Llama 2 7B — the same parameter class as Halcyon's Qwen3 8B — outperformed FinBERT on financial sentiment with only **4.2M trainable parameters** (0.06% of total) and ~$15 in compute cost. TT-LoRA MoE (ACM SC'24) showed that independent domain experts with a frozen-expert router achieve comparable performance to full fine-tuning using just **0.3% of adapter parameters**, with zero catastrophic forgetting.

The architecture for Halcyon's Phase 2 would work as follows: train the base Qwen3 8B model on self-blinded cross-sectional data across all ~325 stocks (Phase 1, current work). Then create lightweight LoRA adapters (~100MB each) for 3–4 major sector groupings — Technology, Healthcare, Energy/Materials, Financials. Each adapter costs **$15–50 to train** and can be swapped at inference with zero additional latency when merged into base weights. A small router network selects the appropriate adapter based on input features.

This approach resolves the specialization-vs-breadth tension: the base model captures universal pullback dynamics from broad cross-sectional data, while sector adapters inject domain-specific conditioning (biotech binary event awareness, energy mean-reversion speed, tech momentum characteristics). The MoA framework (ACL 2024) tested exactly this pattern across Finance, Medicine, and general domains and confirmed that **per-domain LoRA experts outperform a single mixed-data LoRA**.

The trigger for Phase 2 should be clear evidence that sector conditioning improves out-of-sample performance — testable by comparing the base model's pullback predictions stratified by sector. If Healthcare pullbacks systematically have different resolution rates than Tech pullbacks in the base model's residuals, a Healthcare LoRA adapter will capture that signal.

---

## What every major quant fund tells us about breadth

Renaissance Technologies holds **~3,200 positions** across its portfolio, making 150,000–300,000 trades daily. AQR applies factor screens across thousands of stocks globally. WorldQuant's BRAIN platform defines standard universes of TOP500 to TOP3000. Not a single major systematic fund restricts itself to 100 stocks. The entire quant model is predicated on breadth — small edges across thousands of instruments compounding into large returns.

The relevant comparison for Halcyon isn't Renaissance's 3,200-stock universe (that requires billions in infrastructure), but rather the **community standard from Quantopian and WorldQuant: 500–1,500 liquid stocks**. Quantopian's Q500US — the top 500 most liquid US stocks by 200-day average dollar volume, capped at 30% per sector — was the minimum required universe for funded strategies. WorldQuant's 101 Formulaic Alphas paper explicitly used the **"2,000 most liquid U.S. stocks"** as its working universe. Small quant funds ($10M–$100M) typically trade 200–1,500 stocks filtered by liquidity.

At Halcyon's current AUM ($100K–$500K), the constraint isn't liquidity, infrastructure, or data cost. It's training data velocity. The S&P 100 generates pullback signals at roughly one-third the rate of a 325-stock universe. Every month at 100 stocks is three months of potential learning left on the table.

---

## The implementation roadmap

**Phase 1 (Months 0–3): Expand to ~325 stocks.** Adopt the S&P 500 membership filtered to >$100M average daily dollar volume, rebalanced monthly with index reconstitution. Add GICS sector as an input feature. Upgrade data API to a professional tier (Polygon.io at $199/month covers all US equities with flat-rate pricing). Budget ~$800–1,200/month total infrastructure. Begin accumulating cross-sectional training data at 3x the current rate.

**Phase 2 (Months 6–12): Evaluate and deploy LoRA sector adapters.** After accumulating 500+ labeled trade outcomes across the broader universe, analyze residuals by sector. If sector-specific patterns emerge (differential pullback resolution rates), train the first 2–3 LoRA adapters at ~$15–50 each. Implement a lightweight router. This is the cheapest possible experiment — if it doesn't improve out-of-sample performance, discard it with minimal sunk cost.

**Phase 3 (Months 12–24): Consider Russell 1000 expansion.** If the model demonstrates robust alpha at 325 stocks and AUM grows past $1M, expand to ~500–700 stocks including upper mid-caps. This doubles the training data rate again and opens capacity for larger allocations. The LoRA adapter framework scales naturally.

**What not to do:** Don't narrow to a single sector, don't jump directly to Russell 1000, and don't build separate models per sector. The academic evidence, industry practice, and Halcyon's own self-blinding methodology all point in the same direction: **train one model on the broadest feasible liquid universe, condition on sector, and specialize via lightweight adapters only when the data supports it.**

---

## Five free lunches and the quantified tradeoffs

Several findings represent clear wins with minimal downside:

- **Adding sector as an input feature** costs nothing and lets the model learn conditional patterns. Gu, Kelly, and Xiu found industry dummies among the top predictors in their pooled model.
- **Dynamic universe with liquidity filter** (rather than static S&P 100 membership) avoids survivorship bias in backtesting and adapts to changing market conditions. Wang et al. (2014) found that survivorship bias literally reversed factor results.
- **Self-blinding validates on broader data.** Halcyon's anonymized approach produces the same anti-memorization benefits that Kim et al. (2024) demonstrated — but these benefits increase with universe breadth, because more diverse contexts make it harder for the model to "cheat" by recognizing individual stocks from their feature patterns.
- **Examples-per-pattern matters more than examples-per-ticker.** For a self-blinded pullback model, having 3 examples each across 300 tickers is strictly better than 30 examples each across 30 tickers. The model learns "pullback dynamics," not "AAPL dynamics."
- **The expansion is reversible.** If broader training degrades performance (unlikely given the literature, but possible), Halcyon can filter back to S&P 100 constituents at inference time while retaining the richer training data.

The quantified tradeoff of expanding from S&P 100 to ~325 stocks: training data accumulation increases by **~225%**, per-ticker depth decreases by **~69%**, monthly infrastructure cost increases by **~$400–600**, daily pipeline runtime increases from ~10 minutes to ~20 minutes, and time-to-statistical-significance drops from **8–10 months to 2.5–3 months**. Given that Halcyon's self-blinding approach makes per-ticker depth irrelevant by design, this tradeoff is decisively favorable.

## Conclusion

The S&P 100 was a reasonable starting point, but the evidence now clearly supports expansion. Halcyon's self-blinding architecture is *uniquely well-suited* to broader cross-sectional training — it forces the model to learn structural pullback patterns rather than ticker-specific behavior, and those patterns improve with more diverse training contexts. The 325-stock filtered S&P 500 universe hits the sweet spot: broad enough for robust ML training and rapid data accumulation, liquid enough for zero-impact execution at current AUM, and narrow enough for manageable infrastructure costs. The LoRA adapter framework provides a clear, low-cost path to sector specialization once the base model proves its edge. The single most important insight from this research is that **breadth and specialization are not tradeoffs — they're sequential phases** of the same optimal strategy.