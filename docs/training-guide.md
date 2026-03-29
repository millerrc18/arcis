# Halcyon Lab — Training Guide

## Core Principle

Training data quality is our #1 competitive advantage. Every example in the dataset teaches the model what great equity analysis looks like. Bad examples teach bad habits.

## Training Data Sources

1. **Self-Blinded Historical Backfill** — Claude generates commentary from real market features WITHOUT seeing the trade outcome (2-stage pipeline: blinded generation → quality enhancement)
2. **Live Outcomes** — Shadow trade results converted to training examples via the self-blinding pipeline
3. **Contrastive Pairs** — Similar inputs with opposite outcomes, teaching the model to identify subtle distinguishing factors

## Self-Blinding Pipeline (Critical Architecture)

The most important design choice in the training pipeline: Claude NEVER sees whether a trade won or lost when generating training commentary.

**Stage 1 (Blinded):** Claude receives only the features (technical, fundamental, news, macro) and generates analysis. No outcome, no P&L, no exit information.

**Stage 2 (Enhancement):** Claude receives Stage 1's output plus the original features and improves the quality. Still no outcome.

**Why:** If the model sees outcomes during training data generation, it learns to reverse-engineer language that predicts wins/losses rather than learning genuine analytical reasoning. The self-blinding pipeline forces the training data to contain process-quality reasoning, not outcome-contaminated language.

**Validation:** The outcome leakage detector (balanced accuracy TF-IDF classifier) verifies the pipeline is clean. Current result: 60.2% balanced accuracy = MARGINAL (feature-level signal, not leakage). Raw accuracy is 8.9% BELOW the majority baseline — the classifier performs worse than always guessing "win."

## The 7-Section Multi-Source Input Format

Every training example input contains 7+ sections (same format as live inference):

```
=== TECHNICAL DATA ===
Ticker, price, trend state, moving averages, RSI, ATR, volume ratio...

=== MARKET REGIME ===
SPY trend, volatility, breadth, drawdown, regime label...

=== SECTOR CONTEXT ===
Sector, relative strength rank, sector average score...

=== FUNDAMENTAL SNAPSHOT ===
Revenue, margins, PE, growth rates from SEC EDGAR...

=== INSIDER ACTIVITY ===
Buys vs sells, net value, sentiment, notable transactions...

=== RECENT NEWS ===
Headlines, sentiment classification, article count...

=== MACRO CONTEXT ===
Fed Funds rate, yield curve, unemployment, CPI, GDP...

=== TRADE PARAMETERS ===
Score, entry, stop, targets, position size, event risk...

=== ACTUAL OUTCOME === (training only)
Exit reason, P&L, duration, MFE, MAE...
```

## Three-Stage Curriculum

### Stage 1: Structure (lr=3e-4)
All easy examples + clean medium examples. Teaches the model the output format and basic analysis patterns. Easy = single clear factor (high score + clean win, or low score + clean loss).

### Stage 2: Evidence (lr=2e-4)
Medium and hard examples with multiple data sources available. Teaches multi-source synthesis — how to weave fundamentals, insiders, and news into technical analysis.

### Stage 3: Decision (lr=1e-4)
Hard examples with conflicting signals, losing trades with risk flags, and contrastive pairs. Teaches nuanced decision-making under uncertainty.

## Difficulty Classification

- **Easy**: Score ≥ 90 + clean_win, OR score ≤ 50 + clean_loss
- **Hard**: 2+ conflicting signals (bullish technicals + insider selling, high score + bad regime, earnings-adjacent, choppy MFE/MAE, positive score + negative news)
- **Medium**: Everything else

## Quality Scoring (LLM-as-Judge)

Each example is scored on 6 dimensions (1-5 each):

1. **Thesis Clarity** — Is the core trade idea stated clearly?
2. **Evidence Quality** — Are claims grounded in specific input data?
3. **Risk Assessment** — Are risks identified and proportional?
4. **Technical Accuracy** — Are indicators referenced correctly?
5. **Calibration** — Does confidence match setup quality and outcome?
6. **Actionability** — Are entry, exit, and sizing addressed?

Examples scoring below 3.0 overall are excluded from training.

## Contrastive Pairs

Two trades that looked similar at entry (same sector, similar score, similar regime) but had opposite outcomes. The winning commentary is confident. The losing commentary includes the subtle risk factor that distinguished it.

## DPO Preference Pairs

For each training input:
1. Generate 4-6 alternative outputs via the current fine-tuned model (temperature 0.9)
2. Score all alternatives with LLM-as-judge
3. Pair the highest-scored with the lowest-scored
4. Store if quality delta ≥ 1.0

DPO training runs after SFT if ≥ 100 pairs exist.

## Holdout Validation

- 15% of examples (chronologically latest) are held out
- 5-day temporal gap between training and holdout sets
- After training, model generates outputs for holdout inputs
- LLM-as-judge scores model outputs vs gold standard
- Quality gap > 0.3 triggers regression warning

## A/B Shadow Evaluation

New models enter "evaluation" status and run in shadow alongside the active model on live scan inputs. After 20+ evaluations, if the new model wins ≥ 60% of comparisons, it's eligible for promotion.

## The Feedback Flywheel

```
Live Scan → Trade Recommendation → Shadow Execution → Outcome
    ↓                                                    ↓
Training Example ← Quality Filter ← LLM-as-Judge ← Outcome + Features
    ↓
Fine-tune → Better Model → Better Recommendations → Better Outcomes
```

## Cost Estimates

- **Backfill (1000 examples)**: ~$2-4 (Claude Haiku)
- **Quality Scoring (1000 examples)**: ~$1-2 (Claude Haiku)
- **DPO Generation (100 pairs)**: ~$2-3 (Ollama free + Claude Haiku scoring)
- **Fine-tuning**: Free (local GPU)
