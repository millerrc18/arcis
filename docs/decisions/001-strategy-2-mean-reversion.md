# ADR-001: Strategy 2 Is Mean Reversion

**Date:** 2026-03-28
**Status:** Active
**Context:** Arcis needed a second strategy that could diversify the live pullback desk instead of duplicating its risk. The research pass compared breakout, mean reversion, and earnings-driven alternatives through the lens of correlation, trade frequency, and implementation simplicity.
**Decision:** Strategy #2 will be short-term mean reversion rather than breakout. It will stay in a separate adapter and paper-trading lane when Phase 2 begins.
**Consequences:** Portfolio diversification improves sooner because mean reversion is meaningfully less correlated with the pullback desk. Breakout logic remains useful, but it is treated as a feature inside the pullback adapter instead of claiming its own desk slot.
**Research:** `docs/research/Strategy_2_Selection__Mean_Reversion_Wins.md`, `docs/research/Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md`
