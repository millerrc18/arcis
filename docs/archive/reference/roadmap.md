# Arcis Roadmap

**Last Updated:** 2026-03-30

Arcis is still in Bootcamp mode: one live pullback strategy, full shadow execution, continuous enrichment, council governance, and a guarded training loop. The roadmap below consolidates the confirmed weekend decisions from the March 28-29, 2026 research pass into a single operating plan.

## Phase 1: Bootcamp (Current)

### Deployed and Running
- Pullback-in-strong-trend strategy on the S&P 100.
- Alpaca bracket execution with fail-closed safety checks.
- Traffic Light regime overlay and event-calendar risk scoring.
- PEAD enrichment features, earnings proximity handling, and implementation shortfall tracking.
- Council v2 with vote-first sessions, calibration logs, and value tracking.
- Self-blinded training pipeline with ingestion gates, leakage checks, and holdout evaluation.
- Cloud dashboard with live ledger, health, council, notes, docs, and validation views.
- Arcis brand system: Palette H, Inter display typography, persisted dark/light theme toggle, and dashboard API stubs for Build Score plus current Traffic Light state.

### Remaining Before the 50-Trade Gate
- Reach 50 closed Bootcamp trades with enough regime diversity to support a real gate decision.
- Continue collecting bracket-health, implementation shortfall, and council calibration data.
- Keep data quality compliance above 90% for training ingestion batches.
- Verify that the pullback edge survives the shorter 7-day timeout and event-risk overlays.

## Phase 2: After the 50-Trade Gate

### Strategy Expansion
- Launch Strategy #2 as short-term mean reversion, not breakout.
- Expand the universe toward the filtered ~325-stock set once process stability holds.
- Add PEAD signals as pullback enrichment from day one of Phase 2.
- Keep breakout logic inside the pullback adapter as a feature, not a second strategy.

### Model and Risk Upgrades
- Keep the Traffic Light overlay as the Phase 1 regime layer; evaluate statistical jump models and HMM-style upgrades after the gate.
- Introduce volatility-adaptive sizing at the portfolio level only after the gate, without abandoning simple hard guardrails.
- Add conviction calibration once enough real outcomes exist to fit it responsibly.
- Continue equal-weight / 1-N style risk budgeting until the strategy history is long enough to justify optimization.

### Research and Infrastructure Targets
- Evaluate Batch API usage for overnight generation and scoring.
- Upgrade the training stack toward Unsloth + newer TRL support before Dr. GRPO activation.
- Build MFE/MAE and holding-period analysis once the sample is large enough to trust it.
- Add stronger numerical verification and FinBERT-style earnings NLP only when the base workflow is stable.

## Phase 3+: Scale

### Strategy #3 and Multi-Strategy Architecture
- Launch Strategy #3 as evolved PEAD: a composite earnings-information system, not simple beat/miss drift.
- Keep Strategy #2 and Strategy #3 in separate adapters because their signal sources are genuinely different.
- Maintain a 4-6 strategy target for the solo-founder phase rather than chasing raw breadth too early.

### Capital and Platform Scaling
- Stay on equal-weight / inverse-vol style allocation until trade histories are long enough for higher-order optimization.
- Move to stronger hardware and multi-LoRA serving only when adapter count and weekend retrain time justify it.
- Treat portfolio correlation control as a first-class requirement once multiple desks are running.

### Business Path
- Use the Bootcamp and Micro Live phases to build the operating record needed for outside capital.
- Treat fund formation, legal setup, and tax optimization as staged later work rather than a current-phase build priority.

## Confirmed Decisions

| Date | Decision | Status | Rationale |
|---|---|---|---|
| 2026-03-28 | Strategy #2 will be short-term mean reversion. | Active | Research showed it offered the best diversification against the live pullback desk. |
| 2026-03-28 | Strategy #3 will be evolved PEAD, not classic beat/miss drift. | Active | Large-cap earnings drift now needs a composite information model to stay useful. |
| 2026-03-28 | PEAD signals will also be used as pullback enrichment features. | Active | Earnings context improves the live strategy before Strategy #3 exists. |
| 2026-03-28 | RL refinement path is SFT -> Dr. GRPO. | Active | Dr. GRPO is the practical TRL-supported choice from the research pass. |
| 2026-03-28 | DPO is skipped for this stack. | Active | Financial-reasoning research did not justify its added complexity here. |
| 2026-03-28 | Breakout remains a pullback feature, not a standalone desk. | Active | Correlation with pullback was too high to justify a separate strategy slot. |
| 2026-03-28 | Traditional PEAD is not good enough for large-cap deployment. | Active | The standalone beat/miss formulation decayed too far to trust by itself. |
| 2026-03-28 | Phase 1 regime control is Traffic Light; advanced HMM-style work is deferred. | Active | The simple overlay is harder to overfit and already useful for sizing. |
| 2026-03-28 | Council governance uses vote-first sessions with conditional Round 2. | Active | Majority voting captures most of the value without mandatory debate overhead. |
| 2026-03-29 | Pullback timeout is shortened to 7 trading days. | Active | Research showed most pullback edge appears early and decays fast. |
| 2026-03-29 | Event-calendar risk becomes a 0-10 additive overlay with sizing consequences. | Active | Earnings, FOMC, CPI, NFP, OpEx, and month-end effects materially change entry risk. |
| 2026-03-29 | XML commentary gets an optional GBNF-constrained generation path. | Active | Grammar enforcement is the cleanest path to higher XML compliance without hard template fallback. |
| 2026-03-29 | Phase 2 sizing should be volatility-adaptive, not optimizer-heavy. | Active | Better sizing is useful earlier than full portfolio optimization. |
| 2026-03-29 | Risk budgeting stays equal-weight / 1-N until roughly 200 trades. | Active | The sample is too small for stable optimizer-driven allocations before then. |
| 2026-03-29 | Fund-formation and tax-structure work is tabled until a real track record exists. | Tabled | The research supported waiting for 12-24 months of results before spending attention there. |
| 2026-03-29 | SEC EDGAR `companyfacts.zip` is the preferred free fundamentals backbone. | Active | It improves scale and consistency for fundamentals without adding vendor cost. |

## Tabled / Deferred

- Full fund-formation execution and trader-tax optimization: deferred until the system has a 12-24 month operating record and the startup budget is justified.
- Advanced regime detection (jump models, HMM ensembles): deferred until Phase 2 or Phase 3, after the simple Traffic Light overlay has enough operating data.
- Batch API, FinBERT earnings NLP, and multi-LoRA serving: deferred until the single-strategy production path is stable and the sample size justifies more complexity.
- Full portfolio optimization: deferred until multiple desks and longer histories exist; equal-weight and inverse-vol rules are intentionally favored early.
- Prompt caching for council sessions: researched but not enabled because the current agent system prompts do not share a sufficiently large reusable prefix.
