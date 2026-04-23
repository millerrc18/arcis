# Findings Schema — Inter-Skill API Contract

This document defines the JSON schema for all structured outputs exchanged between ARCIS skills. Every agent (Specialist, Domain Lead, Cross-Domain Analyst) produces output conforming to one of these schemas. The schema is the contract — downstream consumers must not assume fields beyond what is documented here.

---

## 1. Agent Findings Output

Produced by: Domain Specialists and Domain Leads.

```json
{
  "domain": "string — the research domain this agent covered (e.g., 'Materials Science', 'Regulatory')",
  "mandate": "string — the specific research question or sub-question assigned to this agent",
  "depth_level": "integer — 0 = top-level Lead, 1 = first-tier Specialist, 2 = second-tier, 3+ = deeper recursion",
  "self_researched": "boolean — true if this agent personally ran queries/tools; false if purely synthesis",
  "completeness": "number (0.0–1.0) — independent self-assessment relative to this agent's own mandate; see completeness-reporting.md",
  "issues": [
    "string — description of a problem encountered during research (tool failure, access error, scope limit, etc.)"
  ],

  "complexity_assessment": {
    "overall_score": "number (0.0–1.0) — weighted composite of signal scores below",
    "signals": {
      "topical_breadth": "number (0.0–1.0) — how many distinct sub-topics the mandate spans; weight 0.30",
      "authoritative_disagreement": "number (0.0–1.0) — degree of conflict among credible sources; weight 0.25",
      "source_type_diversity": "number (0.0–1.0) — variety of source types required (academic, regulatory, industry, news); weight 0.15",
      "query_residual": "number (0.0–1.0) — fraction of sub-questions left unanswered after initial research pass; weight 0.15",
      "temporal_spread": "number (0.0–1.0) — how much the topic changes over time (static vs. rapidly evolving); weight 0.15"
    },
    "decision": "string enum — one of: no_decomposition | selective_decompose | full_decompose",
    "sub_topics_delegated": "integer — number of sub-topics handed off to child Specialists",
    "sub_topics_handled_directly": "integer — number of sub-topics this agent researched directly"
  },

  "key_findings": [
    {
      "claim": "string — a single discrete, falsifiable finding statement",
      "confidence": "string enum (ICD 203) — one of: Very Low | Low | Moderate | High | Very High",
      "self_researched": "boolean — true if this agent gathered the evidence; false if inherited from a child Specialist",
      "evidence": [
        {
          "source_url": "string — canonical URL of the source",
          "source_title": "string — human-readable title of the source",
          "source_quality": "number (0.0–1.0) — composite score from source-quality-rubric.md",
          "source_read_success": "boolean — true if the agent successfully read content from this source",
          "relevant_excerpt": "string — verbatim or closely paraphrased passage supporting the claim"
        }
      ],
      "contradicting_evidence": [
        {
          "source_url": "string — URL of the contradicting source",
          "source_title": "string — title of the contradicting source",
          "source_quality": "number (0.0–1.0) — quality score of the contradicting source",
          "relevant_excerpt": "string — passage that contradicts or complicates the claim",
          "why_overridden": "string — agent's reasoning for why the primary evidence is preferred despite this contradiction"
        }
      ],
      "implications": "string — what this finding means for the broader research mandate"
    }
  ],

  "evidence_digest": [
    {
      "claim": "string — compact restatement of the finding (one sentence max)",
      "source": "string — source URL",
      "confidence": "string enum (ICD 203) — one of: Very Low | Low | Moderate | High | Very High",
      "specialist_depth": "integer — depth_level of the agent that produced this finding"
    }
  ],

  "specialist_reports": [
    "object — recursive: same Agent Findings Output schema, nested. Each child Specialist's full output is embedded here."
  ],

  "synthesis": {
    "conclusion": "string — the agent's integrated conclusion across all key findings",
    "confidence": "string enum (ICD 203) — one of: Very Low | Low | Moderate | High | Very High",
    "key_points": [
      "string — bullet-form summary points drawn from key_findings"
    ],
    "reasoning": "string — explanation of how the agent weighed evidence, resolved contradictions, and reached the conclusion"
  },

  "summary": "string — 3-to-5 sentence triage summary suitable for rapid review by the Orchestrator or Domain Lead. Covers: what was found, confidence level, major gaps, and any flags for cross-domain attention.",

  "gaps_remaining": [
    "string — description of a sub-question or evidence gap that this agent could not fill"
  ],

  "cross_domain_hooks": [
    {
      "hook_id": "string — unique identifier for this hook (e.g., 'MAT-001', 'REG-003')",
      "topic": "string — the specific finding or signal that may be relevant across domains",
      "direction": "string enum — one of: supports | contradicts | extends",
      "target_domains": [
        "string — domain name(s) that should be aware of this hook"
      ],
      "description": "string — explanation of why this finding matters to the target domains"
    }
  ]
}
```

---

## 2. Cross-Domain Analyst Output

Produced by: the Cross-Domain Analyst skill after ingesting all Domain Lead outputs.

```json
{
  "contradictions": [
    {
      "domain_a": "string — name of the first domain",
      "domain_b": "string — name of the second domain",
      "claim_a": "string — the finding from domain_a",
      "claim_b": "string — the finding from domain_b that conflicts with claim_a",
      "root_cause": "string — analyst's explanation of why these claims conflict (scope mismatch, data vintage, definitional difference, genuine disagreement, etc.)",
      "severity": "string enum — one of: high | medium | low"
    }
  ],

  "connections": [
    {
      "domains": [
        "string — list of two or more domain names involved in this connection"
      ],
      "pattern": "string — description of the cross-domain pattern or relationship",
      "evidence_from_each_domain": {
        "domain_name": "string — the specific evidence or finding from that domain supporting the connection"
      },
      "strength": "string enum — one of: strong | moderate | tentative"
    }
  ],

  "emergent_patterns": [
    {
      "pattern": "string — description of a pattern that only becomes visible when multiple domains are considered together",
      "contributing_domains": [
        "string — domain names whose findings contribute to this pattern"
      ],
      "confidence": "string enum (ICD 203) — one of: Very Low | Low | Moderate | High | Very High",
      "implications": "string — what this emergent pattern means for the overall research question"
    }
  ],

  "inter_domain_gaps": [
    {
      "gap_description": "string — description of a question that falls between domains and was not answered by any single Domain Lead",
      "relevant_domains": [
        "string — domains that partially touch this gap"
      ],
      "impact_on_conclusions": "string — how this gap affects confidence in or completeness of the overall answer"
    }
  ],

  "overall_coherence_assessment": "string — narrative assessment of how well the domain findings fit together, where they reinforce each other, and where they create unresolved tension",

  "recommended_report_structure": "string enum — one of: dialectical | convergent | landscape. dialectical = organize around contradictions; convergent = organize around reinforcing themes; landscape = organize as parallel domain summaries with connective tissue"
}
```

---

## 3. Failure Manifest

Produced by: the Orchestrator when one or more agents fail to return valid output. Appended to the final report so consumers understand coverage gaps.

```json
{
  "failed_agents": [
    {
      "agent": "string — the role/name of the agent that failed (e.g., 'Domain Specialist: Regulatory')",
      "domain": "string — the domain the agent was covering",
      "mandate": "string — the research question the agent was assigned",
      "failure_mode": "string enum — one of: timeout | token_limit | tool_failure | malformed_output",
      "partial_output": "object | null — whatever partial structured output the agent produced before failing, or null if nothing was recovered"
    }
  ]
}
```

---

## 4. Usage Notes

### Confidence Cap — Sonnet Specialists

Domain Specialists running on claude-sonnet are capped at **Moderate** confidence regardless of evidence quality. Only Domain Leads (claude-opus or higher) may assign High or Very High confidence, and only after reviewing and independently corroborating the Specialist's evidence. See `shared/references/icd203-confidence-calibration.md` for propagation rules.

### Completeness — Independent Self-Assessment

The `completeness` field is each agent's **own assessment** of how thoroughly it covered its assigned mandate. It is NOT computed by averaging child Specialist scores. A Lead with three fully successful Specialists (completeness 0.9 each) may still self-report completeness 0.5 if the Lead's own synthesis sub-questions were not answered. See `shared/schemas/completeness-reporting.md` for the full methodology.

### Evidence Digest — Compact Tuples for Cross-Domain Analyst

The `evidence_digest` array is a flattened, compact representation of all key findings — one tuple per finding. Its purpose is to give the Cross-Domain Analyst a high-bandwidth view of all evidence across domains without requiring it to parse nested `specialist_reports`. Leads are responsible for populating this array by rolling up their own findings and their Specialists' findings.

### Cross-Domain Hooks — Signals for Inter-Domain Connections

The `cross_domain_hooks` array is populated by any agent (Specialist or Lead) that notices a finding with potential relevance beyond its own domain. The Cross-Domain Analyst consumes these hooks as structured signals before running its own pattern analysis. Agents should err toward over-reporting hooks — false positives are filtered by the Cross-Domain Analyst, but missed hooks cannot be recovered.

### Specialist Reports — Recursive Nesting

The `specialist_reports` array contains the full Agent Findings Output of each child Specialist, embedded verbatim. This enables complete audit trails: every claim can be traced back through nested `specialist_reports` to the raw evidence and source that originated it. The Orchestrator should not prune this nesting — report consumers may need to inspect any depth.
