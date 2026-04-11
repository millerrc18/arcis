# LLM Authority Boundaries: Where the Model Earns Responsibility and Where It Never Should

**Date:** April 11, 2026
**Source:** Claude Deep Research analysis, cross-referenced with FINSABER (KDD 2026), TradeTrap (2024), Trading-R1 (2025), TradingAgents (AAAI 2025), FinCon (NeurIPS 2024)
**Status:** INCORPORATED — informs Strategy Decisions #26+

---

## Key Finding: FINSABER

FINSABER (Li et al., Oxford, KDD 2026) systematically dismantled claimed LLM trading alpha. Even GPT-4-class models fail at timing decisions across 20 years and 100+ symbols — previously claimed Sharpe ratios degraded from 1.44 to -1.247 under bias-mitigated backtests. LLMs are "overly conservative in bull markets and overly aggressive in bear markets." Model scaling does not help.

**Implication for Arcis:** The LLM's value is in analysis and enrichment, not signal generation. Our edge comes from the pullback-in-uptrend setup and ATR brackets. The LLM makes better commentary, not better trades. This validates our existing architecture.

**Critical nuance:** FINSABER tested timing-based strategies (buy/hold/sell). It did NOT test LLMs as signal enrichment layers atop mechanical strategies — which is our architecture. Whether our hybrid approach preserves alpha remains the existential question (Strategy Decision #17 — alpha attribution experiment).

---

## Permanent Exclusions (Anti-Recommendations)

These are permanent architectural constraints, not temporary limitations:

1. **LLM must never control execution parameters.** No stop adjustments, no trailing stop activation, no stop removal. TradeTrap showed single perturbations cascade into extreme concentration.

2. **Position sizing must remain mechanical.** Chopra & Ziemba: mean return estimation errors are 20× more impactful than covariance errors. LLM numerical hallucination rate is 10–20% (FAITH Framework, 2025). Fixed-fractional with ATR scaling is robust by design.

3. **Risk governor cannot accept LLM inputs.** China's 2016 circuit breaker (abolished in 4 days) demonstrates that poorly calibrated adaptive thresholds cause more harm than fixed ones.

4. **No self-improvement loop without external anchors.** Self-Rewarded Training causes "sudden performance collapse" where outputs degenerate into fixed answers. Every training improvement must validate against backtest P&L, market data, or human review.

5. **Conviction must never become a hard gate.** PolySwarm (2026): helpful LLMs exhibit systematic overconfidence. Hard gating introduces unquantifiable opportunity cost. Soft weighting (±15% of base sizing) is the maximum authority, and only after 300+ trades with confirmed calibration.

---

## Expansion Tiers

### Tier 1 — Now (0–50 trades)
- Training data curation and self-improvement (highest priority — what the backfill sprint delivers)
- EOD reconciliation auditing (LLM explains discrepancies, never auto-corrects)
- Enhanced trade commentary (already deployed)

### Tier 2 — 50–100 trades
- Market regime narrative enrichment (LLM adds qualitative texture to deterministic Traffic Light)
- FinBERT news event flagging (informational only, never auto-executes)
- Isolation Forest anomaly detection on CPU (LLM explains, doesn't decide)

### Tier 3 — 100–200 trades
- Conviction as soft multiplier on position size (±15%, only if Brier score confirms calibration)
- Mechanical thesis invalidation rules pre-specified at entry
- Walk-forward comparison of regime-adaptive allocation

### Tier 4 — 200+ trades
- Mechanical ATR-trailing stops (NOT LLM-driven) via walk-forward analysis
- Regime-based strategy allocation if jump-model detection confirms improvement
- **Still excluded:** LLM-driven exits, LLM-driven sizing, LLM override of risk governor

---

## Statistical Reality: 18 Trades

- 30 trades: CLT minimum
- 100–200: preliminary retail validation
- 200–500 across regimes: institutional standard (López de Prado)
- 1,000+: isotonic calibration of confidence scores

At 18 trades, win rate 95% CI spans 36–81%. Kelly sizing with p=0.60 vs p=0.36 produces 3–5× different position sizes. Every expansion must accumulate evidence, not act on conclusions that don't exist.

---

## Hardware Roadmap

- **RTX 3060 12GB (current):** Qwen3-8B Q4_K_M (~5GB model + ~5GB KV) + FinBERT (250MB) + Isolation Forest on CPU. ~20–42 tok/s.
- **RTX 3090 24GB (target):** Qwen3-14B Q4_K_M (~9GB + 14GB remaining). 2.5× faster generation (936 vs 360 GB/s bandwidth). Used: $700–900.
- **Qwen3-30B-A3B MoE:** 73 tok/s on 3090 (only 3B active per token). Worth benchmarking against dense 14B after v2.0.0 training is validated — not before.

---

## Strategy Decisions Informed

| # | Decision | Source |
|---|----------|--------|
| #18 | Mechanical brackets through 200 trades | Reinforced by FINSABER, Kaminski & Lo |
| #17 | Alpha attribution experiment is existential | Gap in FINSABER — tests timing, not enrichment |
| NEW | Conviction soft multiplier only after 300+ trades with Brier calibration | PolySwarm overconfidence finding |
| NEW | Isolation Forest + LLM explanation > LLM-only anomaly detection | 97.69% accuracy, 89% false alert reduction |
| NEW | No self-training without external anchors | Self-Rewarded Training collapse finding |
