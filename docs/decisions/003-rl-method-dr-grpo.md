# ADR-003: RL Refinement Uses Dr. GRPO

**Date:** 2026-03-28
**Status:** Active
**Context:** The reinforcement-learning stage needed a method that was both research-supported and realistically available in the Arcis training stack. Pure GRPO looked weak on small prompt datasets, while the most attractive academic variants were not all production-ready.
**Decision:** The post-SFT RL path is Dr. GRPO through TRL, not baseline GRPO and not DPO. DPO remains out of scope for this stack.
**Consequences:** The RL stage stays compatible with the existing training infrastructure while still incorporating the strongest practical upgrade from the research pass. This also keeps the pipeline simpler until live outcome volume is high enough to justify the RL step.
**Research:** `docs/research/REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md`, `docs/research/GRPO_for_Financial_LLMs_on_Consumer_Hardware__Practical_Implementation_and_Reward_Design.md`
