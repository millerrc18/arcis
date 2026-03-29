# Scaling Halcyon Lab from One Strategy to a Multidesk Fund

> Deep research report — Multi-strategy architecture, LoRA adapter decisions, capital allocation, and phase-gated timeline

## Key Finding

The optimal path for a solo-founder AI quant fund is 6–8 genuinely independent strategies across 2–3 desks over 5 years, not the 12–15 that seem tempting. With realistic inter-strategy correlations of ~0.15, moving from 1 to 4 uncorrelated strategies roughly doubles portfolio Sharpe ratio, but strategies 5 through 10 add only ~15% more.

## Portfolio Sharpe Formula

SR_portfolio = S × √N / √(1 + (N−1) × ρ)

With individual strategy SR = 0.6 and ρ = 0.15: 2 strategies yield SR ≈ 0.79, 4 strategies yield SR ≈ 0.99, 8 strategies yield SR ≈ 1.17. Sweet spot: 4–6 genuinely uncorrelated strategies at steady state, targeting combined portfolio Sharpe of ~1.0–1.2.

## How Multi-Strategy Funds Organize

Pod shops (Millennium, Citadel, Balyasny) run 100+ autonomous pods of 5–7 people. Integrated quant funds (Renaissance, Two Sigma, Man AHL) treat the entire fund as one collaborative system. A solo founder is structurally one pod — the integrated model is the only viable template.

DE Shaw's research: Monte Carlo simulation of 10 uncorrelated strategies produces net Sharpe of 1.44, roughly 3× individual strategy Sharpe of ~0.48. Running those same 10 as independent standalone funds yields only 1.26 — netting benefit alone worth 157 bps/year.

CAIA 2021 survey: quality of operations (84%), research process (82%), and investment infrastructure (78%) rank far above raw strategy count in allocator selection. AIMA 2024: two-thirds of allocators invest in sub-$100M AUM funds, half consider <1 year track record — provided operational infrastructure is institutional-grade.

## Equity Swing Desk: Three Strategies in Specific Order

Of eight candidate equity swing strategies, only three provide genuinely independent return streams:

### Strategy #2: PEAD (Post-Earnings Announcement Drift)
- Correlation with pullback: ρ ≈ 0.05
- Bernard and Thomas (1989) — "granddaddy of underreaction events"
- ML-enhanced PEAD achieves Sharpe 0.63–0.76 (Kaczmarek & Zaremba 2025)
- Same universe, same holding window, fundamentally different signal source
- Works across regimes (driver is information flow, not market direction)
- Expected combined SR improvement: +30–40%

### Strategy #3: Short-Term Mean Reversion
- Correlation with pullback: ρ ≈ −0.15
- Works precisely when pullback fails (volatile, choppy, bear markets)
- Jegadeesh (1990) academic foundation
- 1–5 day reversals generate frequent trades for rapid validation

### Strategy #4 (optional): Pairs Trading / Statistical Arbitrage
- Gatev, Goetzmann, Rouwenhorst (2006): profitability increases in poor markets
- ML-based pair selection: Sharpe 0.81–2.69 (Sarmento & Horta 2023)
- Requires short-selling — add only after first three strategies profitable

### Critical: Breakout is NOT a Separate Strategy
- Pullback-breakout correlation: ρ ≈ 0.55 (near-zero diversification)
- Incorporate breakout signals as features within the pullback adapter
- Adding breakout as #2 instead of PEAD is the single most common architectural mistake

### Regime-Conditional Coverage
- Pullback: dominates bull/trending, collapses in bear
- PEAD: consistent across all regimes
- Mean reversion: peaks in high-volatility and bear markets
- Together: every regime covered, estimated combined SR 1.1–1.3

### Track Record Gate
- 100+ trades spanning ≥2 market regimes per strategy (Bailey & López de Prado 2014, DSR)
- At 2–15 day holds: ~1–2 years live/paper trading per strategy
- t-statistic must exceed 2.0

## Options Desk: Two Strategies, Not Eight

Six of eight planned options strategies harvest the same factor: Volatility Risk Premium (VRP). Put-call parity means covered call = cash-secured short put. Iron condor = two credit spreads.

Bakshi and Kapadia (2003) proved VRP exists. Dörries et al. (2021) tested seven VRP strategies 1996–2021: equal-exposure strategies show minimal variation — confirming they capture the same risk premium.

### Genuinely Independent Options Premia
1. **VRP (Volatility Risk Premium)**: Core trade, SR ~0.3–0.8 with left-tail risk
2. **Term Structure Premium**: Calendar/diagonal spreads, partially independent from VRP
3. **Correlation Risk Premium (CRP)**: Dispersion trading — 18% premium (Driessen et al. 2009), but returns went negative post-2000, operationally complex

### Recommended Options Desk
- Strategy #5: Systematic VRP harvesting (70% of desk capital) — delta-hedged strangles with ML-driven regime timing
- Strategy #6: Term-structure/calendar strategy (30%)
- Dispersion trading: Phase 6+ only

### Critical Risk: Short-vol and equity pullback share crisis vulnerability
In 2020 and 2022, VRP and equity-momentum strategies drew down simultaneously. Treat combined equity+options portfolio as ρ ≈ 0.3–0.4 during crises for risk budgeting.

## LoRA Adapter Decision Boundary

**Rule: Strategies sharing >70% of input features, same asset class, and same data frequency → shared adapter. Different asset classes or data modalities → separate adapters.**

| Strategy Pair | Decision | Rationale |
|---|---|---|
| Pullback + Breakout | Shared adapter | Same OHLCV data, overlapping features. LoRA Soups (2024): concatenated datasets +32% accuracy |
| Pullback + PEAD | Separate adapters | Different signal source (price vs earnings). Connect via MoLE gating |
| Equity + Options | Definitely separate | Different data modalities. TradExpert confirms negative transfer |
| VRP + Term Structure | Separate adapters | Different vol surface dimensions. Share preprocessing pipeline |

FinLoRA benchmark (Wang et al., 2025): vanilla LoRA rank 8 achieved highest overall score (74.74, +37.69% over base). Rank 16 sweet spot for complex reasoning. Higher ranks (32-64) only for multi-factor analysis.

Serving: vLLM with Punica SGMV kernels adds only ~2ms per token overhead. S-LoRA: thousands of concurrent adapters on single GPU with up to 30× throughput improvement. At 6–8 strategies, adapter count is never the bottleneck (~34 MB per adapter at rank 32).

## Capital Allocation Progression

### Phase 1–2 (2–3 strategies): Equal Weight
- Per-strategy volatility targeting at 10% annualized
- Quarter-Kelly as hard upper bound
- Thorp (2006): double Kelly = zero growth; half-Kelly = 75% of maximum growth

### Phase 3–4 (4–6 strategies): Inverse-Volatility Risk Parity
- Scale allocation inversely proportional to trailing volatility
- Drawdown floor: when any strategy DD exceeds 2× historical max, reduce 30% (not to zero)
- Yang and Zhong (2012): drawdown-responsive allocation achieves 3× higher Calmar (0.56 vs 0.16)

### Phase 5–6 (7–12 strategies): Two-Level Hierarchy
- Inter-desk: equal risk budgets, reviewed quarterly
- Intra-desk: correlation-aware risk parity with Ledoit-Wolf shrinkage
- Black-Litterman overlay using regime favorability as "views"

### Rebalancing: Weekly for vol targeting, monthly for capital allocation, quarterly for framework review. No-trade bands ±5%.

### Critical Error to Avoid
Chopra and Ziemba (1993): errors in mean return estimates are 100× more damaging than variance errors. Never optimize on estimated returns until 3+ years live data per strategy.

## Correlation Monitoring

Strategy correlations spike during crises — Yale/OFR research: hedge fund correlations nearly double from 0.15 to 0.27 during crises.

With 50–200 trades per strategy, sample correlations are dangerously noisy. Correlation of 0.3 from 100 observations has 95% CI of [0.1, 0.5].

### Monitoring Framework
- **Weekly**: EWMA correlations (half-life 60-90 days) across all strategy pairs
- **Monthly**: Factor decomposition against market beta, VIX, credit spreads, rates. Monitor PC1 — if >50% of total variance, diversification is compromised
- **Quarterly**: Stress-test with constructed correlation matrices (normal, mild +0.2, severe +0.5, armageddon all=0.8)

### Alert Thresholds
- Yellow: 90-day rolling correlation >2σ above historical mean
- Orange: 60-day correlation >0.5 for designed-uncorrelated strategies
- Red: 30-day correlation >0.7 concurrent with portfolio DD >5%

## Training Pipeline Scaling

Storage for LoRA adapters is trivial — 10 strategies at rank 32 = 340 MB. Binding constraint is training compute time.

### Weekly Retrain Feasibility
| Hardware | Time/Strategy | Max Strategies (Weekend) |
|---|---|---|
| RTX 3060 12GB (QLoRA) | 2–4 hours | 5 strategies |
| RTX 3090 24GB (LoRA) | 1–2 hours | 10–12 strategies |
| Dual 3090 (parallel) | 1–2 hours × 2 | 20 strategies |

Minimum training data: 1,000–2,000 labeled examples per strategy at rank 16-32, 3-4 epochs.

Cross-strategy transfer learning: pre-train "financial base" LoRA on combined data, then fine-tune strategy-specific adapters from shared base. ~30–50% features shared across equity strategies.

## GPU Inference for Swing Trading

325 stocks × 10 strategies = 3,250 inference requests takes ~15–25 minutes on RTX 3090 with INT4 + vLLM. Even 50 strategies × 325 stocks: under 3 hours.

### Serving Architecture by Phase
- **RTX 3060 (Phase 1–2)**: Qwen3-8B INT4 (~4.6 GB), hot-swap adapters, 5 strategies at 25-35 tok/s
- **RTX 3090 (Phase 3–4)**: Qwen3-8B or 14B INT4, vLLM with --enable-lora --max-loras 16
- **Dual 3090 NVLink (Phase 5–6)**: Tensor parallelism TP=2, ~50% throughput over PCIe-only

Decision criterion for 8B vs 14B: stick with 8B while tasks are narrow classification/scoring; move to 14B when strategies require complex multi-factor reasoning.

## Concrete Strategy Map

### Desk 1: Equity Swing (4 strategies at maturity)

| # | Strategy | Phase | Own Adapter? | Min Data | LoRA Rank | Hardware |
|---|---|---|---|---|---|---|
| 1 | Pullback-in-uptrend | Phase 1 | Yes | 1,000+ | r=16 | RTX 3060 |
| 2 | PEAD (earnings drift) | Phase 2 | Yes (different signal) | 1,500+ | r=16 | RTX 3060 |
| 3 | Short-term mean reversion | Phase 3 | Yes (negative corr) | 1,000+ | r=16 | RTX 3090 |
| 4 | Pairs trading / stat arb | Phase 5 | Yes (market-neutral) | 2,000+ | r=32 | RTX 3090 |

### Desk 2: Options Volatility (2–3 strategies at maturity)

| # | Strategy | Phase | Own Adapter? | Min Data | LoRA Rank | Hardware |
|---|---|---|---|---|---|---|
| 5 | Systematic VRP harvesting | Phase 3–4 | Yes | 2,000+ (10+ yr options data) | r=32 | RTX 3090 |
| 6 | Vol term structure / calendar | Phase 4 | Yes | 1,500+ | r=32 | RTX 3090 |
| 7 | Dispersion / correlation (optional) | Phase 6 | Yes | 2,000+ | r=32 | Dual 3090 |

### Desk 3: Equity Momentum (1–2 strategies)

| # | Strategy | Phase | Own Adapter? | Min Data | LoRA Rank | Hardware |
|---|---|---|---|---|---|---|
| 8 | Risk-managed trend-following | Phase 5 | Yes | 2,000+ | r=16 | Dual 3090 |

Use Barroso & Santa-Clara (2015) risk-managed momentum (SR ~0.97) rather than raw momentum (SR ~0.53).

## Phase-by-Phase Timeline

### Phase 1 (Months 0–6): Foundation
- 1 strategy, RTX 3060, 1 LoRA r=16, 100% allocation vol-targeted at 10%
- Goal: 100+ trades, prove system works live

### Phase 2 (Months 6–18): First Diversification
- 2 strategies (add PEAD), RTX 3060, 2 LoRAs
- Gate: Pullback 100+ trades with t-stat > 1.5
- Expected SR improvement: +30–40%

### Phase 3 (Months 12–24): Bear Insurance + Options Launch
- 4 strategies (add mean reversion + VRP), upgrade to RTX 3090
- Inverse-vol risk parity with drawdown floor
- Universe: S&P 100 → ~325 stocks
- Expected SR: ~1.0–1.2

### Phase 4 (Months 24–36): Options Buildout
- 5–6 strategies, RTX 3090
- Two-level hierarchy allocation
- Full correlation monitoring framework

### Phase 5 (Months 36–48): Momentum + Scale
- 7–8 strategies, dual RTX 3090 NVLink or RTX 4090
- MoLE gating within equity adapter group
- Full correlation-aware risk parity + Black-Litterman

### Phase 6 (Months 48–60): Optimization
- 8 strategies, refine don't add
- Target SR: ~1.2–1.5
- Institutional-grade infrastructure for outside capital

## Hardware Scaling

| Phase | GPU | VRAM | Max Strategies (Train) | Max (Inference) | Cost |
|---|---|---|---|---|---|
| 1–2 | 1× RTX 3060 | 12 GB | 5 | 8+ | $300 used |
| 3–4 | 1× RTX 3090 | 24 GB | 10–12 | 50+ | $800 used |
| 5–6 | 2× RTX 3090 + NVLink | 48 GB | 20 | 100+ | $1,700 total |
| Alt 5–6 | 1× RTX 4090 | 24 GB | 12–15 | 50+ | $1,600 new |

Note: RTX 4090 does NOT support NVLink. Dual 3090s offer 48 GB + NVLink vs 4090's 2× single-GPU compute without fast interconnect.

## Risk Factors

1. **Correlation convergence in crisis**: All strategies correlate simultaneously. Monitor PC1 weekly; if >50% of variance, reduce gross exposure 30%.
2. **LoRA overfitting to recent regimes**: Track OOS Sharpe on rolling 3-month holdout; if diverges from training Sharpe by >0.5, adapter is overfitting.
3. **Training time exceeding weekend window**: At 10+ strategies. Mitigation: cloud-burst (Lambda Labs A10G $0.75/hr), staggered retraining, incremental updates.
4. **Complexity death spiral**: If >30% of weekly time goes to operations vs research, complexity exceeds capacity.
5. **Options tail risk compounding equity drawdowns**: Compute conditional correlation using worst 10% of equity days. If >0.6, options desk not providing crisis diversification. Maintain small long-vol allocation.

## Conclusion

Genuine independence between strategies matters far more than count. Two truly uncorrelated strategies (ρ ≈ 0) provide more diversification than eight moderately correlated ones (ρ ≈ 0.3). Target 8 strategies across 3 desks at maturity. Most important phase gate is not hardware but track record: 100+ trades with t-stat > 1.5 across ≥2 regimes before any strategy goes live.
