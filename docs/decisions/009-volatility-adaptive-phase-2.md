# ADR-009: Phase 2 Uses Volatility-Adaptive Sizing

**Date:** 2026-03-29
**Status:** Active
**Context:** The next phase needs better sizing discipline, but not the false precision of a full optimizer while trade counts are still low. The research favored robust volatility-aware controls over fragile forecast-heavy allocation.
**Decision:** Phase 2 sizing upgrades will be volatility-adaptive rather than optimizer-driven. The system will improve sizing first and postpone more complex portfolio optimization until histories are longer.
**Consequences:** Risk posture improves without pretending the sample supports heavy optimization. This also keeps the operational model explainable for Bootcamp-to-Phase-2 transition reviews.
**Research:** `docs/research/Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md`, `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`
