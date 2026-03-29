# ADR-002: Strategy 3 Is Evolved PEAD

**Date:** 2026-03-28
**Status:** Active
**Context:** The large-cap beat/miss version of PEAD has decayed too far to justify a naive implementation, but the earnings-information stack is still powerful when modeled more richly. We needed to decide whether PEAD belonged in the roadmap and, if so, in what form.
**Decision:** Strategy #3 will be evolved PEAD: a composite earnings-information system using surprise magnitude, concordance, revisions, and related context. It is not the classic single-signal drift trade.
**Consequences:** Phase 3 work now targets a higher-quality earnings desk with fewer but more defensible trades. The same research also justifies reusing PEAD signals as enrichment features for the live pullback strategy before the standalone adapter launches.
**Research:** `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`, `docs/research/Scaling_Halcyon_Lab_From_One_Strategy_to_a_Multidesk_Fund.md`
