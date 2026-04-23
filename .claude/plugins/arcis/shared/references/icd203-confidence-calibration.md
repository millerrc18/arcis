# ICD 203 Confidence Calibration

Based on Intelligence Community Directive 203 (Analytic Standards), adapted for open-source research. ICD 203 requires that every analytic judgment carry an explicit confidence level so consumers can distinguish well-supported conclusions from speculative ones. ARCIS applies this standard to all agent findings.

---

## 1. Five-Level Scale

| Level | Label | When to Use |
|-------|-------|-------------|
| 5 | Very High | Extensive, diverse sources; findings independently replicated across multiple authoritative venues; no credible contradicting evidence; expert consensus is clear and current |
| 4 | High | Multiple authoritative sources in agreement; alternative explanations considered and assessed as less plausible; key assumptions are explicit and well-supported |
| 3 | Moderate | Several credible sources available; key assumptions have not been independently tested; some contradicting evidence exists but has been assessed as less reliable; reasonable inference |
| 2 | Low | Limited sources; questionable source reliability or currency; significant assumptions required to reach the conclusion; credible alternative explanations have not been ruled out |
| 1 | Very Low | Fragmentary information; single unverified source; substantial inferential leap required; conclusion is speculative; consumer should treat as a hypothesis only |

---

## 2. Calibration Examples

The following examples use aerospace and engineering research scenarios to illustrate each confidence level in practice.

### Very High

> "Grade 5 titanium (Ti-6Al-4V) exhibits a fatigue limit of approximately 550 MPa at 10^7 cycles under rotating bending conditions at room temperature."

Rating: **Very High** — This is a foundational material property documented in MIL-HDBK-5J, ASM Handbook Vol. 2, multiple peer-reviewed fatigue studies, and reproduced in Gulfstream structural design references. The data has been independently replicated across hundreds of test programs over decades. No credible source disputes this value within the stated test conditions.

### High

> "The FAA's AATF (Advanced Air Mobility Pathfinder) program issued a means of compliance for Urban Air Mobility type certification under 14 CFR Part 23 Amendment 64 in Q3 2024."

Rating: **High** — Sourced from the FAA's official AATF program page, corroborated by three industry trade publications (Aviation Week, Flight Global, AIN), and consistent with the FAA's stated regulatory roadmap. Key assumption: the publications accurately reported the issuance date. Alternative explanation (delayed issuance) was checked against the FAA docket and found unsupported.

### Moderate

> "Adoption of model-based definition (MBD) practices among Tier 2 aerospace suppliers has reached approximately 40–55% of organizations as of 2025."

Rating: **Moderate** — Two industry surveys (AeroDef Manufacturing 2024, SME State of MBD 2025) report figures in this range. However, survey methodologies differ, response rates are not disclosed, and "adoption" is defined inconsistently across studies. Key assumption: survey respondents are representative of Tier 2 suppliers broadly. Independent replication is absent; the range reflects genuine uncertainty.

### Low

> "A major Western titanium sponge producer suspended operations in Q1 2026, creating a near-term supply shortfall for aerospace-grade titanium."

Rating: **Low** — Found in a single industry newsletter citing an unnamed source. No corroboration from producer IR filings, LME titanium spot price data, or trade publications with direct sourcing. The newsletter has a track record of early but occasionally inaccurate supply chain reporting. Significant alternative explanation: the disruption may be a temporary maintenance shutdown, not a suspension.

### Very Low

> "A U.S. prime contractor is developing a titanium additive manufacturing process that would eliminate dependence on Russian sponge imports within 18 months."

Rating: **Very Low** — Sourced from a single social media post attributed to a conference attendee. No corporate announcement, patent filing, or trade press corroboration exists. The claim requires significant inferential leaps about manufacturing scalability and supply chain economics. This should be treated as a lead for further investigation, not a finding.

---

## 3. Confidence Propagation Rules

These rules govern how confidence levels move through the agent hierarchy.

1. **Confidence can only be elevated by a higher-tier agent adding independent evidence.** A Domain Lead may raise a Specialist's finding from Moderate to High, but only if the Lead itself retrieves and documents new corroborating evidence in the `evidence[]` array. Elevation without new evidence is not permitted.

2. **Confidence can be lowered by any agent at any tier.** A Lead that identifies a methodological flaw in a Specialist's evidence may lower the confidence of an inherited finding. The Lead must document the reason in its `reasoning` field.

3. **Confidence cannot be elevated without new evidence in the `evidence[]` array.** If a Lead elevates a finding, the elevating agent's name and the additional evidence it found must be traceable in the schema. "I agree with the Specialist" is not grounds for elevation.

4. **Sonnet Specialists are capped at Moderate.** Domain Specialists running on claude-sonnet may assign at most Moderate confidence to any finding, regardless of how strong the evidence appears. This cap accounts for model limitations in source credibility assessment and complex inferential chains. Only Domain Leads (claude-opus or equivalent) may assign High or Very High.

5. **A Domain Lead that elevates a Specialist finding to High or Very High must document the additional evidence.** The Lead's `key_findings[].evidence[]` array must contain at least one entry that was not present in the Specialist's output. The Lead's `reasoning` field must explicitly reference this new evidence and explain why it warrants the elevation.

---

## 4. Usage in Reports

- **Every claim carries a confidence label.** No finding may appear in a report without an explicit ICD 203 confidence level. This applies to key findings, synthesis conclusions, and emergent patterns from the Cross-Domain Analyst.

- **The executive summary states overall confidence with justification.** The overall confidence for the research question is the lowest confidence of the findings most central to the answer, not an average. The justification explains which finding(s) are the binding constraint.

- **Every report includes a Confidence Key table.** Include the following table in the report appendix or legend so consumers unfamiliar with ICD 203 understand the scale:

  | Label | Meaning |
  |-------|---------|
  | Very High | Extensive corroboration; expert consensus |
  | High | Multiple authoritative sources; alternatives assessed |
  | Moderate | Several credible sources; key assumptions untested |
  | Low | Limited or questionable sources; alternatives not ruled out |
  | Very Low | Fragmentary; speculative; treat as hypothesis |

- **Reduced confidence is proportional to failed coverage.** When the Failure Manifest records failed agents, the overall confidence must be reduced to reflect the missing coverage. A research question that lost coverage of a central domain cannot report High confidence even if the surviving domains produced strong findings.
