# Completeness Reporting

This document defines how agents self-assess and report the `completeness` field in the Agent Findings Output schema.

---

## 1. Completeness Score (0.0–1.0)

Completeness is an **independent self-assessment** by each agent relative to its own assigned mandate. It is not computed by aggregating child Specialist scores and is not a measure of source quality or confidence.

### Formula

```
completeness = (confidence-weighted sub-questions answered) / (total sub-questions generated)
```

Each agent begins by decomposing its mandate into sub-questions. After research, it counts how many sub-questions received an answer and applies a confidence-based credit:

| Confidence Level | Credit Weight |
|-----------------|---------------|
| HIGH or VERY HIGH | 1.0 (full credit) |
| MODERATE | 0.8x |
| LOW | 0.5x |
| VERY LOW | 0.2x |

Tool failures that prevent answering a sub-question reduce the numerator but are independently recorded in the `issues[]` array. A sub-question answered at VERY LOW confidence counts only 0.2 toward the numerator — it is not the same as a well-supported answer.

### Example

An agent generates 10 sub-questions. Results:
- 4 answered at HIGH confidence → 4.0 credit
- 2 answered at MODERATE confidence → 1.6 credit
- 1 answered at LOW confidence → 0.5 credit
- 3 unanswered (tool failures, no sources found) → 0.0 credit

Completeness = (4.0 + 1.6 + 0.5) / 10 = **0.61**

---

## 2. Completeness Scale

| Score | Interpretation |
|-------|----------------|
| 0.0 | Catastrophic failure — agent could not conduct meaningful research |
| 0.1–0.3 | Significant gaps — results are fragmentary; Coverage Failure section required in report |
| 0.4–0.6 | Meaningful with known gaps — useful findings exist but substantial questions remain open |
| 0.7–0.8 | Solid with minor gaps — most sub-questions answered; remaining gaps are documented |
| 0.9–1.0 | Comprehensive — mandate is thoroughly covered; residual gaps are negligible or out of scope |

When completeness falls below 0.4, the agent must include a **Coverage Failure** section in its output narrative describing what was attempted, what failed, and what questions remain open. This section is propagated into the final report.

---

## 3. Distinguishing "Found Nothing" vs. "Could Not Investigate"

These two states look identical in `key_findings` (an empty or near-empty array) but have opposite meanings. Completeness disambiguates them:

**High completeness + empty key_findings = "Looked hard; evidence does not exist."**

- Example: completeness 0.8, zero key findings for "titanium supply disruption in Q1 2026"
- Interpretation: The agent executed thorough queries, read credible sources, and found no evidence of the phenomenon
- Rendered in report as: a **positive finding** ("No evidence found despite thorough investigation")
- This is informative — absence of evidence after rigorous search is itself evidence

**Low completeness + empty key_findings = "Barely looked."**

- Example: completeness 0.1, zero key findings for the same mandate
- Interpretation: Research was interrupted — tool failures, token pressure, or scope issues prevented investigation
- Rendered in report as: a **gap or failure**, not a finding
- Consumers should not interpret this as "no evidence exists"

Agents must be honest about which state applies. If tool failures limited investigation, completeness must reflect that.

---

## 4. Issues Array

The `issues[]` array records problems encountered during research. It is separate from completeness — issues are the cause; completeness is the effect.

| Category | Example Strings |
|----------|----------------|
| Tool failure | `"search_web returned empty results for query: 'AS9100D clause 8.4 subcontractor flow-down'"` |
| Tool failure | `"read_url timed out on https://example.gov/report.pdf after 30s"` |
| Source access | `"Source behind paywall; abstract only retrieved: https://doi.org/10.1016/..."` |
| Source access | `"PDF extraction failed — scanned image document, no OCR available"` |
| Token pressure | `"Truncated Specialist report to fit context; full specialist_reports nested output omitted"` |
| Token pressure | `"Stopped after 8 of 12 planned queries due to approaching token limit"` |
| Quality concern | `"Primary source for claim X is a single industry press release; no independent corroboration found"` |
| Quality concern | `"Source date is 2019; topic may have changed significantly since publication"` |
| Scope limitation | `"Mandate included classified program details; open-source investigation is necessarily incomplete"` |
| Scope limitation | `"Sub-question requires domain expertise in fluid dynamics; agent flagged for specialist escalation"` |

### Rules

1. **Every tool failure must appear in `issues[]`.** Failures not recorded in issues are invisible to downstream consumers and cannot be addressed.

2. **Issues do not automatically reduce completeness.** A tool failure on a minor sub-question may not materially reduce completeness. A tool failure blocking the central sub-question may reduce it dramatically. The agent exercises judgment.

3. **Issues propagate upward.** Domain Leads must include notable Specialist issues in their own `issues[]` array — particularly tool failures that affected coverage, quality concerns that affect confidence, and any scope limitations the Orchestrator should know about. Routine low-severity issues need not be re-surfaced.
