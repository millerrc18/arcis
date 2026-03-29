# The Halcyon Framework v2.1: Compute, Value, Moat, and Multi-Strategy Architecture

> **Updated March 29, 2026** — Incorporates the March 28-29, 2026 research pass, including multi-strategy scaling, council redesign, event-risk handling, data-quality gates, and the remaining operating-compendium decisions.

---

## Changes from v1

| Area | v1 | v2 (updated) |
|---|---|---|
| Strategy count | Single strategy assumed | 4-6 uncorrelated strategies at steady state, 8 max across 3 desks |
| RL method | GRPO planned | **REINFORCE++** (GRPO overfits on small prompt datasets) |
| PEFT method | QLoRA | **QDoRA** (`use_dora=True` — 8% VRAM savings, no quality loss) |
| Adapter architecture | Single adapter | Per-strategy LoRA adapters; shared when >70% feature overlap |
| Council | Decorative sentiment label | Vote-first deliberation with structured JSON output and parameter control |
| Regime detection | Implicit via VIX | **Traffic Light system** (VIX + 200-DMA + credit spread z-score) |
| Moat thesis | Data asset is the moat | Refined: **signal→context→outcome mapping** is the moat, not raw data |
| Strategy 2 | Breakout | **PEAD (post-earnings drift)** — ρ ≈ 0.05 vs pullback (breakout was ρ ≈ 0.55) |
| Capital allocation | Not specified | Equal-weight → inverse-vol risk parity → correlation-aware + BL overlay |
| Hardware path | RTX 3060 → 3090 | RTX 3060 (5 strategies) → RTX 3090 (10-12) → Dual 3090 NVLink (20) |
| Execution tracking | Not specified | Implementation Shortfall logging from day 1 |
| Statistical validation | Not specified | PSR/MinTRL/DSR framework with Triple Penance Rule |

---

## Changes from v2 to v2.1

| Area | v2 | v2.1 addition |
|---|---|---|
| Data infrastructure | SQLite + sync path implied | SQLite remains the core local store for 10-20 years of solo operation; Render stays the low-cost cloud mirror for dashboard use. |
| Operating budget | Infra path discussed abstractly | Render baseline stays in the low-cost solo range (~$13/mo class) until multi-desk scale forces a bigger footprint. |
| Model serving hygiene | Daily cadence covered broadly | Ollama daily restart plus morning warm-up is now a formal operating rule, not an incidental implementation detail. |
| Statistical gating | PSR/MinTRL/DSR defined | MinBTL-style evidence discipline and pre-commitment rules are treated as operating constraints before scaling capital. |
| Risk budgeting | Equal-weight discussed for early phases | 1/N style allocation is explicitly locked in until roughly 200 trades, even if more advanced sizing research exists. |
| Fundamental data source | EDGAR discussed generally | SEC `companyfacts.zip` is the preferred free fundamentals backbone for scale and consistency. |
| Feature maintenance | Feature importance noted | Section-ablation / feature-importance review is now a lightweight recurring maintenance ritual (~35 minutes per month). |
| Business path | Fund formation future-facing | Fund formation remains tabled until a 12-24 month track record and roughly $50K-$75K of setup readiness are justified. |

---

## 1. Compute Architecture (unchanged core, new multi-strategy scaling)

### Single-strategy targets (unchanged)

**75% sustained GPU utilization** — inference ≤30%, training ≤45%, slack ≥25%. Kingman's formula, Toyota production system, and Google SRE methodology all converge on this number. Weekly Saturday retraining, not nightly. Emergency retrain only on >5% drift.

### Multi-strategy compute scaling (NEW)

Training pipeline — not inference — is the binding constraint for strategy count.

| Hardware | Training Budget | Max Strategies (Weekend) | Max Strategies (Inference) |
|---|---|---|---|
| RTX 3060 12GB (QDoRA) | 2-4 hrs/strategy | 5 | 8+ |
| RTX 3090 24GB (LoRA) | 1-2 hrs/strategy | 10-12 | 50+ |
| Dual 3090 NVLink | 1-2 hrs × 2 parallel | 20 | 100+ |

At 15+ strategies on a single 3090, weekend retraining becomes infeasible. Mitigations: cloud-burst training (Lambda Labs A10G ~$0.75/hr), incremental retraining (only retrain strategies with new data), staggered schedules (half each weekend).

### Multi-adapter serving

For swing trading (2-15 day holds), processing 325 stocks × 10 strategies = 3,250 inference requests takes ~15-25 minutes on RTX 3090 with INT4 + vLLM continuous batching. Inference is never the bottleneck.

Serving architecture progression:
- **Phase 1-2 (RTX 3060):** Ollama, hot-swapping adapters sequentially. 5 strategies at ~25-35 tok/s.
- **Phase 3-4 (RTX 3090):** vLLM with `--enable-lora --max-loras 16`. Qwen3-14B INT4 as base model upgrade.
- **Phase 5-6 (Dual 3090):** Tensor parallelism (TP=2) with NVLink. ~50% throughput improvement over PCIe-only.

Each LoRA adapter is ~34MB at rank 32. 10 adapters = 340MB total — trivial.

---

## 2. Training Pipeline (updated)

### PEFT method: QDoRA (updated from QLoRA)

DoRA (Liu et al., ICML 2024) decomposes weights into magnitude and direction, applying LoRA only to direction. ~8% VRAM savings, no quality loss. Implementation: `use_dora=True` in Unsloth. Comprehensive evaluation (arXiv:2512.23165) found DoRA surpasses full fine-tuning at 46.6% vs 44.9% average accuracy.

### RL stage: Dr. GRPO (updated from GRPO → REINFORCE++ → Dr. GRPO)

REINFORCE++ (Hu 2025) is theoretically superior to GRPO for small datasets but is **NOT available in TRL**. The practical solution: TRL's `GRPOTrainer` with `loss_type="dr_grpo"` — Dr. GRPO (Lan 2025) removes GRPO's question-level difficulty bias through length and difficulty normalization. This is a one-parameter change from standard GRPO.

**Skip DPO entirely** — Fin-o1 found DPO produces inconsistent results in financial reasoning. Pipeline: SFT → Dr. GRPO (at 100+ closed trades).

Composite reward function (from REINFORCE++ research):
- Volatility-normalized P&L: 40%
- Quality rubric score: 25%
- Calibration accuracy (conviction vs outcome): 20%
- Risk management quality (MAE/ATR): 15%

### LoRA adapter decision boundary (NEW)

| Condition | Recommendation |
|---|---|
| >70% feature overlap, same asset class, same frequency | Shared adapter (e.g., pullback + breakout) |
| Same asset class, different signal source | Separate adapters (e.g., pullback vs PEAD) |
| Different asset class or data modality | Definitely separate (e.g., equity vs options) |

FinLoRA benchmark: vanilla LoRA at rank 8 achieved highest overall score (74.74, +37.69% over base). Rank 16 is the conservative sweet spot for complex reasoning. Higher ranks (32-64) justified only for multi-factor analysis.

### Cross-strategy transfer learning (NEW)

Recommended pipeline: (1) pre-train a "financial base" LoRA on combined data from all strategies to capture shared market representations, then (2) fine-tune strategy-specific adapters from this shared base. Related strategies sharing >70% feature overlap benefit from joint pre-training. Feature overlap between equity strategies is ~30-50% shared (regime, sector, VIX, breadth) and ~50-70% unique (strategy-specific signals).

---

## 3. Multi-Strategy Scaling Framework (NEW section)

### Portfolio Sharpe mathematics

For N strategies each with Sharpe S and average pairwise correlation ρ:

**SR_portfolio = S × √N / √(1 + (N−1) × ρ)**

With individual SR = 0.6 and ρ = 0.15:
- 2 strategies: SR ≈ 0.79 (+32%)
- 4 strategies: SR ≈ 0.99 (+65%)
- 8 strategies: SR ≈ 1.17 (+95%)
- Beyond 10: marginal improvement <3% per strategy added

**Sweet spot for solo founder: 4-6 genuinely uncorrelated strategies, targeting combined SR ~1.0-1.2.**

### Strategy selection by correlation (CONFIRMED by deep research, March 28)

The equity swing desk strategy sequence, confirmed by 6 deep research documents:

| # | Strategy | Correlation with Pullback | Phase | Evidence |
|---|---|---|---|---|
| 1 | **Pullback-in-uptrend** | — | Phase 1 (LIVE) | Behavioral foundation (underreaction). Decaying but durable. |
| 2 | **Short-term mean reversion** | ρ ≈ **−0.35** | Phase 2 | Connors RSI(2) 65-75% WR. Enhanced Sharpe 0.7-1.0. Regime insurance. Decisively best #2 per research. |
| 3 | **Evolved PEAD** (composite earnings info) | ρ ≈ **0.2** | Phase 3 | NOT traditional beat/miss. 12-quarter elastic net + NLP + revenue concordance + analyst revision velocity + recommendation inconsistency. Sharpe 0.6-0.9. ~15-30 trades/quarter. |

**PEAD signals as pullback enrichment (Phase 2):** In addition to evolved PEAD as a standalone Strategy #3, key earnings signals (surprise magnitude, revenue concordance, analyst revision velocity, recommendation inconsistency) will be added as enrichment features for the pullback adapter in Phase 2. These improve pullback trades near earnings events without requiring a separate strategy.

**Critical correction (confirmed):** Breakout (ρ ≈ 0.55 with pullback) should NOT be a separate strategy. Incorporate breakout signals as features within the pullback adapter.

**Adding a second uncorrelated strategy reduces portfolio variance by ~50%. Expanding from 100 to 325 stocks with the same strategy reduces variance by only ~1.6%.** (Strategy #2 Selection research)

### Options desk: 2 strategies, not 6-8 (NEW)

Credit spreads, iron condors, covered calls, and short straddles all harvest the same Volatility Risk Premium. They are the same trade in different costumes. The genuinely independent risk premia:

| Strategy | Phase | Allocation | Independence |
|---|---|---|---|
| Systematic VRP harvesting | Phase 3-4 | ~70% of desk | Core short-vol trade |
| Vol term structure / calendar | Phase 4 | ~30% of desk | Partially independent from VRP level |
| Dispersion (optional) | Phase 6 | If justified | Operationally complex |

**Warning:** Short-vol and equity pullback share crisis vulnerability (ρ ≈ 0.3-0.4 during crises). Options desk does NOT fully diversify the equity desk.

### Capital allocation progression (NEW)

| Phase | Method | Rationale |
|---|---|---|
| 1-2 (2-3 strategies) | Equal weight + per-strategy vol targeting at 10% annualized | Optimization is actively harmful with <200 trades |
| 3-4 (4-6 strategies) | Inverse-volatility risk parity with drawdown floor | Requires only variance estimates, not return forecasts |
| 5-6 (7-12 strategies) | Two-level hierarchy: inter-desk equal risk + intra-desk correlation-aware + BL overlay | Full framework once track records are long enough |

DeMiguel, Garlappi, and Uppal (2009): across 14 optimization models and 7 datasets, none consistently beat equal-weight. With 25 assets, mean-variance needs 3,000 months of data to outperform 1/N.

Quarter-Kelly as hard upper bound. Half-Kelly captures 75% of optimal growth with 50% volatility. Full Kelly is never appropriate with estimation uncertainty this high.

### Correlation monitoring (NEW)

**Weekly:** Update EWMA correlations (half-life 60-90 trading days) across all strategy pairs.
**Monthly:** Full factor decomposition. Monitor PC1 — if it explains >50% of total strategy return variance, diversification is compromised.
**Quarterly:** Stress-test with constructed correlation matrices: normal, mild stress (+0.2), severe (+0.5), armageddon (all ρ = 0.8).

Alert thresholds:
- Yellow: 90-day rolling correlation exceeds 2σ above historical mean
- Orange: 60-day correlation exceeds 0.5 for designed-uncorrelated strategies
- Red: 30-day correlation exceeds 0.7 concurrent with portfolio DD >5%

---

## 4. Regime Detection (NEW section)

### Traffic Light system (minimum viable, Phase 1)

Three indicators chosen for low overfitting risk and complementary information:

| Indicator | Green (2) | Yellow (1) | Red (0) |
|---|---|---|---|
| VIX level | <20 | 20-30 | >30 |
| S&P 500 vs 200-DMA | Above | Within 3% | Below |
| HY credit spread z-score (vs 1yr MA) | <0.5σ | 0.5-1.5σ | >1.5σ |

Total score 0-6. At 5-6: full position sizing. At 3-4: 50%. At 0-2: minimal/cash.

This system has only 3 inputs (nearly impossible to overfit), is rules-based (no parameter estimation), captures volatility, trend, and credit information independently.

**Regime-aware position sizing is more robust than regime-aware strategy selection for Phase 1-2.** Position sizing adjusts one parameter gradually, is less prone to overfitting, and works even when detection is noisy.

### Advanced path (Phase 2-3)

HMM-based detection using Hamilton's framework. Statistical Jump Models (Shu et al., 2024) offer better stability. Wasserstein HMM approach (2025) achieved Sharpe 2.18 vs 1.18 buy-and-hold.

---

## 5. AI Council as Governance Infrastructure (NEW section)

### Architecture: Vote-first, debate-if-needed

NeurIPS 2025 finding: majority voting accounts for most performance gains attributed to multi-agent debate. The council's value comes from ensembling five independent analytical lenses, not from agents persuading each other.

Protocol: Get 5 independent Round 1 assessments → aggregate via confidence-weighted voting → only proceed to Round 2 if <3/5 consensus.

### Five agents as analytical lenses

| Agent | Framework | Time Horizon | Core Question |
|---|---|---|---|
| Tactical Operator | Market microstructure, regime, order flow | Hours-weeks | What does current data tell us about next 1-5 days? |
| Strategic Architect | Portfolio theory, Kelly, phase gates | 1-5 years | How should we allocate capital and attention? |
| Red Team / Risk Sentinel | Adversarial analysis, pre-mortem | Present-3 years | What are we missing and what kills us? |
| Innovation Engine | R&D pipeline, ML experiment design | 3-18 months | What can we build that we couldn't before? |
| Macro Navigator | Macro-financial, regulatory, market structure | 2-5 years | How is the world changing? |

### Parameter control: soft biases within hard guardrails

**Hard controls (never council-adjustable):** Max single position 5%, portfolio DD halt -10%, daily loss limit -3%, max leverage 1.0x, VIX >40 automatic 50% reduction, human kill switch.

**Soft controls (council-adjustable within bounds):** Position sizing multiplier (0.25x-1.5x), cash reserve (10-50%), scan aggressiveness, sector tilts (±20%), stop-loss multiplier (1.5-3.0x ATR).

Rate limiters: max ±25% change/day on any parameter, max ±50% cumulative weekly.

### Council earns authority

Phase 1: paper-only influence, tight bounds. As calibration scorecard accumulates over 90+ days, bounds widen. Self-correcting: influence proportional to proven track record.

### Process power as moat

Every session's structured output — reasoning chains, dissent records, parameter adjustments, outcomes — becomes proprietary training data compounding over time. This is the institutional memory that becomes progressively harder to replicate.

---

## 6. Statistical Validation Framework (NEW section)

### PSR/MinTRL/DSR

- **Probabilistic Sharpe Ratio (PSR):** Probability that observed Sharpe exceeds benchmark, accounting for non-normal returns
- **Minimum Track Record Length (MinTRL):** For SR=1.0, normally distributed: ~68 trades. For SR=0.5: ~270+ trades
- **Deflated Sharpe Ratio (DSR):** Corrects for multiple testing bias. **Critical requirement:** record ALL backtest trials from day one

### Triple Penance Rule

Recovery from maximum drawdown takes ~3× the formation period. 20% DD over 2 months → ~6 months to recover. Define drawdown tolerance before scaling, not during.

### Execution measurement

Implementation Shortfall = decision price − actual fill price. Log from day 1. If IS exceeds 10% of gross alpha, investigate. Switch from market orders to limit orders at the ask (saves 0.5-2 bps, adds no risk on liquid names).

---

## 7. Five Dimensions of System Value (updated from v1)

### HSHS formula (unchanged)

**HSHS = (P^w₁ × M^w₂ × D^w₃ × F^w₄ × C^w₅) ^ (1/(w₁+w₂+w₃+w₄+w₅))**

### Updated dimension definitions

**P (Performance):** Add portfolio-level Sharpe (not just per-strategy), correlation stability metric, Implementation Shortfall tracking.

**M (Model Quality):** Add per-adapter quality scores, MoLE routing accuracy (when applicable), REINFORCE++ reward signal quality.

**D (Data Advantage):** Refined thesis — the moat is not raw data but the accumulated **signal→context→outcome mapping** across diverse market conditions. Track: total labeled trade outcomes, regime coverage (how many distinct regimes experienced), "near miss" data (rejected setups logged), council reasoning chains as proprietary data.

**F (Flywheel Velocity):** Add council session frequency and quality score, multi-strategy feedback cycles (each strategy's flywheel reinforces the others through shared regime/macro features).

**C (Competitive Defensibility):** Add process power from council (institutional memory compounding), time-to-replicate per strategy (separate from overall system TTR), Moat Scorecard (monthly: out-of-sample Sharpe trend, IC of features, Brier score, alpha decay rate per signal).

### Phase-dependent weights (updated)

| Dimension | Months 1-6 | Months 7-18 | Months 18+ |
|---|---|---|---|
| Performance (w₁) | 0.10 | 0.20 | 0.30 |
| Model Quality (w₂) | 0.25 | 0.20 | 0.15 |
| Data Advantage (w₃) | **0.35** | **0.25** | 0.20 |
| Flywheel Velocity (w₄) | 0.15 | 0.20 | 0.10 |
| Defensibility (w₅) | 0.15 | 0.15 | **0.25** |

(Unchanged from v1 — the phase structure remains correct)

---

## 8. Competitive Landscape (NEW section)

### The crowding reality

Pullback-in-uptrend on S&P 100 is among the most competed strategy-universe combinations. QuantConnect has 300,000+ registered users, Freqtrade has 39,900 GitHub stars. But the pipeline attrition is severe: ~30-40% complete a backtest, 3-5% deploy live, 0.1-0.5% sustain profitable live trading beyond 2 years.

McLean and Pontiff (2016): published return predictors show 26% lower out-of-sample returns and 58% lower post-publication. The additional 32% is directly from publication-informed trading.

**However:** Momentum (the closest academic cousin to pullback) remained significant across 30 years post-publication (Jegadeesh & Titman 2023), likely because it's driven by deep behavioral biases, not simple mispricing.

### The Grossman-Stiglitz floor

If markets were perfectly efficient, no one would incur information costs, causing prices to become uninformative. There is always a floor to alpha — set by the cost of building and maintaining the AI systems. The question is whether Halcyon's costs fall below this floor. At all planned phases ($100-$500K), positions represent <0.001% of daily volume. Market impact is zero.

### AI-resistant alpha sources

As more AI agents trade pullbacks, pullbacks become shallower and briefer. The edge shifts to:
1. Identifying pullbacks algorithms won't buy (catalyst/fundamental triggers)
2. Regime detection (knowing when pullbacks are genuine vs noise)
3. Better position sizing and risk management (may now contain more alpha than signal generation)
4. Expanding to less-competed universes (mid-caps have higher idiosyncratic risk and more anomaly persistence)

**"AI as market infrastructure" (table stakes) rather than "AI as alpha generator" (edge) is the accurate framing for 2026-2030.** Build for a world where everyone has AI. The edge comes from proprietary data, regime awareness, and execution quality.

---

## 9. Phase-Gated Timeline (updated)

| Phase | Timeline | Strategies | Hardware | SR Target | Gate |
|---|---|---|---|---|---|
| 1 | Months 0-6 | 1 (pullback) | RTX 3060 | Validate | 100+ trades, t-stat >1.5 |
| 2 | Months 6-18 | 2 (+ mean reversion) + PEAD enrichment features | RTX 3060 | 0.79+ | PSR >90%, 2 regimes |
| 3 | Months 12-24 | 4 (+ evolved PEAD, + VRP) | RTX 3090 | 1.0-1.2 | Each strategy 100+ trades |
| 4 | Months 24-36 | 5-6 (+ term structure) | RTX 3090 | 1.2+ | Investor-ready track record |
| 5 | Months 36-48 | 7-8 (+ trend-following, pairs) | Dual 3090 | 1.2-1.5 | Institutional infrastructure |
| 6 | Months 48-60 | 8 (optimize, don't add) | Dual 3090 | 1.2-1.5 | Fund formation ready |

**Most important gate is not hardware but track record:** no strategy goes live until 100+ trades with t-stat >1.5 across ≥2 market regimes.

**Phase 4 by December 2026 probability: 25-35%**, gated by needing ~500 closed trades. Only achievable by launching Strategy 2 (PEAD) by August 2026.

---

## 10. Conclusion: The Updated Operating Playbook

The v2 framework adds three strategic layers to the v1 foundation:

1. **Multi-strategy architecture** with correlation-driven strategy selection, per-strategy LoRA adapters, and phase-gated scaling from 1 to 8 strategies.

2. **AI Council as governance infrastructure** — not decorative but structurally integrated into risk management through parameter control within hard guardrails, earning authority through demonstrated accuracy.

3. **Statistical rigor** via PSR/MinTRL/DSR frameworks, Triple Penance Rule, and Implementation Shortfall tracking that define exactly when evidence is trustworthy and scaling is justified.

The core v1 principle remains: **the data asset — not the model, not the returns — is the most valuable component.** The v2 refinement: the moat is specifically the accumulated mapping of signal→context→outcome across diverse market conditions, compounded by the council's institutional memory. Every trade, every council session, every regime experienced builds an asset no competitor can buy.
