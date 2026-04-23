# Complexity Calibration

Worked examples for consistent complexity scoring.

## Scoring Recap

| Signal                    | Weight |
|---------------------------|--------|
| topical_breadth           | 0.30   |
| authoritative_disagreement| 0.25   |
| source_type_diversity     | 0.15   |
| query_residual            | 0.15   |
| temporal_spread           | 0.15   |

## Depth-Adjusted Thresholds

| Depth    | Role        | Threshold |
|----------|-------------|-----------|
| 0        | Director    | 0.3       |
| 1        | Lead        | 0.5       |
| 2        | Specialist  | 0.7       |
| 3+       | Deep        | 0.9       |

Rigor modifiers applied to threshold before comparison:

| Rigor Mode  | Modifier |
|-------------|----------|
| shallow     | +0.2     |
| moderate    | 0        |
| deep        | -0.1     |
| exhaustive  | -0.2     |

## Research Director Examples

### LOW (0.2) — "What is the current price of titanium Ti-6Al-4V bar stock?"

Trial search returns consistent pricing data from a single domain (metals suppliers). No meaningful disagreement, no cross-domain complexity, no unresolved residual.

| Signal                    | Score |
|---------------------------|-------|
| topical_breadth           | 0.1   |
| authoritative_disagreement| 0.1   |
| source_type_diversity     | 0.2   |
| query_residual            | 0.1   |
| temporal_spread           | 0.2   |

**Weighted score: 0.13**
**Decision: no_decomposition**
Assessment: single-Lead mode or Director handles directly.

```json
{
  "complexity_assessment": {
    "score": 0.13,
    "signals": {
      "topical_breadth": 0.1,
      "authoritative_disagreement": 0.1,
      "source_type_diversity": 0.2,
      "query_residual": 0.1,
      "temporal_spread": 0.2
    },
    "threshold": 0.3,
    "decision": "no_decomposition",
    "rationale": "Consistent pricing data from a single domain; no sub-topic branching required."
  }
}
```

---

### MODERATE (0.52) — "How does additive manufacturing compare to traditional machining for aerospace titanium?"

Trial search surfaces multiple sub-topics: cost, material properties, certification pathways, design freedom. Some expert disagreement on cost crossover points. Mix of trade publications, standards bodies, and academic sources.

| Signal                    | Score |
|---------------------------|-------|
| topical_breadth           | 0.7   |
| authoritative_disagreement| 0.4   |
| source_type_diversity     | 0.5   |
| query_residual            | 0.4   |
| temporal_spread           | 0.5   |

**Weighted score: 0.52**
**Decision: selective_decompose**
Assessment: 2 domains (manufacturing process; certification & cost).

```json
{
  "complexity_assessment": {
    "score": 0.52,
    "signals": {
      "topical_breadth": 0.7,
      "authoritative_disagreement": 0.4,
      "source_type_diversity": 0.5,
      "query_residual": 0.4,
      "temporal_spread": 0.5
    },
    "threshold": 0.3,
    "decision": "selective_decompose",
    "rationale": "Multiple sub-topics with some source disagreement warrant splitting into 2 domain leads."
  }
}
```

---

### HIGH (0.82) — "Analyze feasibility of replacing Al-Li with CFRP in next-gen narrow-body primary structure"

Trial search immediately branches into materials science, structural analysis, manufacturing processes, airworthiness certification, supply chain maturity, lifecycle cost, and environmental impact. Significant expert disagreement across industry and academia. Requires standards, OEM white papers, academic journals, and supplier data. Multi-decade technology evolution.

| Signal                    | Score |
|---------------------------|-------|
| topical_breadth           | 0.9   |
| authoritative_disagreement| 0.8   |
| source_type_diversity     | 0.8   |
| query_residual            | 0.8   |
| temporal_spread           | 0.7   |

**Weighted score: 0.82**
**Decision: full_decompose**
Assessment: 4-5 domains (materials; structures; manufacturing; certification; cost/supply chain).

```json
{
  "complexity_assessment": {
    "score": 0.82,
    "signals": {
      "topical_breadth": 0.9,
      "authoritative_disagreement": 0.8,
      "source_type_diversity": 0.8,
      "query_residual": 0.8,
      "temporal_spread": 0.7
    },
    "threshold": 0.3,
    "decision": "full_decompose",
    "rationale": "Highly multi-domain with significant expert disagreement; requires 4-5 parallel domain leads."
  }
}
```

---

## Domain Lead Examples

### LOW (0.25) — "FSW process parameters for 2195-T8"

Well-documented in NASA technical reports and ASM handbooks. Parameters (tool rpm, traverse rate, pin geometry) are established with narrow variance across sources. No meaningful disagreement.

| Signal                    | Score |
|---------------------------|-------|
| topical_breadth           | 0.2   |
| authoritative_disagreement| 0.2   |
| source_type_diversity     | 0.3   |
| query_residual            | 0.2   |
| temporal_spread           | 0.3   |

**Weighted score: 0.23**
**Decision: no_decomposition**
Handle directly; Specialist delegation not warranted.

```json
{
  "complexity_assessment": {
    "score": 0.23,
    "signals": {
      "topical_breadth": 0.2,
      "authoritative_disagreement": 0.2,
      "source_type_diversity": 0.3,
      "query_residual": 0.2,
      "temporal_spread": 0.3
    },
    "threshold": 0.5,
    "decision": "no_decomposition",
    "rationale": "Well-established parameters in authoritative sources; Lead handles directly."
  }
}
```

---

### HIGH (0.72) — "Al-Li metallurgy under FSW"

Active research area with competing theories on precipitate dissolution, HAZ softening mechanisms, and optimal post-weld heat treatment. Results vary by alloy generation (2090, 2195, 2099). Multiple research groups with contradictory findings. Residual questions on microstructural evolution remain open.

| Signal                    | Score |
|---------------------------|-------|
| topical_breadth           | 0.6   |
| authoritative_disagreement| 0.8   |
| source_type_diversity     | 0.6   |
| query_residual            | 0.8   |
| temporal_spread           | 0.6   |

**Weighted score: 0.70**
**Decision: selective_decompose**
Delegate to Specialist for microstructural mechanisms sub-topic.

```json
{
  "complexity_assessment": {
    "score": 0.70,
    "signals": {
      "topical_breadth": 0.6,
      "authoritative_disagreement": 0.8,
      "source_type_diversity": 0.6,
      "query_residual": 0.8,
      "temporal_spread": 0.6
    },
    "threshold": 0.5,
    "decision": "selective_decompose",
    "rationale": "Competing theories and open residual questions warrant delegating microstructural sub-topic to Specialist."
  }
}
```

---

## Decision Guide

After computing the weighted score, compare against the depth-adjusted threshold (with rigor modifier applied):

| Condition                              | Action                   |
|----------------------------------------|--------------------------|
| score < threshold                      | Handle directly          |
| score >= threshold (marginally)        | Selective decomposition  |
| score >> threshold (>0.2 above)        | Full decomposition       |

When in doubt, prefer handling directly — delegation carries overhead and coordination cost that only pays off when complexity genuinely warrants it.
