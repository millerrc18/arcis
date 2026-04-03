# Depth Levels Configuration

## Depth Comparison

| Setting | Direct Searchers | Lateral Searchers | Contrarian | Trace | Refine Loops | Council | Est. Time |
|---------|-----------------|-------------------|------------|-------|-------------|---------|-----------|
| `shallow` | 2 | 0 | 0 | No | 0 | No | ~1-2 min |
| `moderate` (default) | 2 | 1 | 1 | Yes | 1 | No | ~3-5 min |
| `deep` | 3 | 2 | 1 | Yes | 2 | Yes | ~8-12 min |
| `exhaustive` | 5 | 3 | 1 | Yes | 3 | Yes | ~15-20 min |

## Phase Activation by Depth

| Phase | Shallow | Moderate | Deep | Exhaustive |
|-------|---------|----------|------|------------|
| 0: CLASSIFY | Yes | Yes | Yes | Yes |
| 1: PLAN | Yes | Yes | Yes | Yes |
| 2: GATHER (direct) | 2 agents | 2 agents | 3 agents | 5 agents |
| 2: GATHER (lateral) | Skip | 1 agent | 2 agents | 3 agents |
| 2: GATHER (contrarian) | Skip | 1 agent | 1 agent | 1 agent |
| 2.5: TRACE | Skip | Yes | Yes | Yes |
| 3: SYNTHESIZE | Yes | Yes | Yes | Yes |
| 4: REFINE | Skip | 1 loop max | 2 loops max | 3 loops max |
| 5: DELIBERATE | Skip | Skip | Yes (5 agents) | Yes (5 agents) |
| 6: OUTPUT | Yes | Yes | Yes | Yes |

## Adaptive Stopping (Phase 4: REFINE)

Refinement loops stop early if ANY condition is met:
- **Novelty score** drops below 0.10 (new findings overlap with existing)
- **Source saturation** drops below 0.15 (>85% of sources already registered)
- **All critical gaps** from the synthesizer are resolved

## Model Tiering

| Role | Model | Rationale |
|------|-------|-----------|
| Orchestrator | opus | Coordination decisions need strongest reasoning |
| Planner | opus | Decomposition quality drives everything |
| Searchers (direct/lateral/contrarian) | sonnet | Speed matters; search is procedural |
| Tracer | sonnet | Citation following is procedural |
| Synthesizer | opus | Cross-referencing and dialectical reasoning |
| Refiner | sonnet | Gap-filling searches are targeted |
| Council (4 of 5) | sonnet | Lens-specific assessments |
| Council Arbiter | opus | Meta-reasoning and final synthesis |

## maxTurns by Agent

| Agent | maxTurns | Rationale |
|-------|----------|-----------|
| Planner | 3 | Decompose in 1-2 turns |
| Searcher | 8 | Multiple search + read cycles |
| Tracer | 10 | Citation following needs several hops |
| Synthesizer | 3 | Read files + produce output |
| Refiner | 8 | Search + read + integrate per gap |
| Council agents | 3 | Assessment from provided material |
