# ADR-010: Risk Budgeting Stays Equal-Weight Early

**Date:** 2026-03-29
**Status:** Active
**Context:** Multi-strategy allocation rules become fragile quickly when trade histories are short. The research pass strongly warned against over-optimizing portfolio weights before enough real data exists.
**Decision:** Halcyon Lab uses equal-weight / 1-N style risk budgeting until roughly 200 trades or equivalent evidence exists to justify more complex allocation. Optimizers stay out of the critical path before then.
**Consequences:** Early capital allocation remains intentionally simple, robust, and easy to defend. When more advanced allocation eventually arrives, it will do so on top of a much healthier evidence base.
**Research:** `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`, `docs/research/Halcyon_Lab_Scaling_Plan_Through_2026.md`
