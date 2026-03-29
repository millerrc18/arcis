# ADR-004: Phase 1 Regime Control Uses Traffic Light

**Date:** 2026-03-28
**Status:** Active
**Context:** Halcyon Lab needed regime awareness early, but the first implementation had to resist overfitting and stay explainable during Bootcamp. More advanced HMM-style detection remained attractive, but not as a first production step.
**Decision:** Phase 1 uses the Traffic Light regime overlay for position sizing and risk posture. More complex statistical regime models are deferred to later phases.
**Consequences:** Regime handling stays simple, observable, and easy to audit while the live sample is still small. The roadmap still leaves room for jump-model and HMM upgrades after the system has enough real outcomes to support them.
**Research:** `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`, `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`
