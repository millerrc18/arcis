# ADR-006: Pullback Timeout Is Reduced to Seven Trading Days

**Date:** 2026-03-29
**Status:** Active
**Context:** The live pullback desk had been carrying a longer generic timeout even though the strategy's edge is concentrated early in the holding window. The research pass specifically revisited holding periods by strategy instead of treating them as one-size-fits-all.
**Decision:** The pullback strategy timeout is reduced from 15 trading days to 7 trading days. Holding periods become strategy-specific rather than globally shared.
**Consequences:** Capital recycles faster, stale positions are cut sooner, and the system matches the documented edge decay more closely. Future desks can now receive their own timeout rules instead of inheriting the pullback window by default.
**Research:** `docs/research/Optimal_Holding_Periods_for_Halcyon_Lab_Three_Equity_Strategies.md`
