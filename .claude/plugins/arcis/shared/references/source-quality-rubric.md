# Source Quality Rubric

This document defines how ARCIS agents compute and report the `source_quality` score (0.0–1.0) for each source in the `evidence[]` array. The score is a composite of five weighted factors. It maps to the `quality_rating` (1–5) used when calling the `register_source` MCP tool.

---

## 1. Composite Score

The composite score is a weighted average of up to five factors. If a factor cannot be assessed for a given source (e.g., citation count is unavailable for a government report), exclude that factor and redistribute its weight proportionally among the remaining factors.

| Factor | Weight |
|--------|--------|
| Domain tier | 0.30 |
| Citation impact | 0.25 |
| Recency | 0.20 |
| Author credibility | 0.15 |
| Venue tier | 0.10 |

**Formula:**

```
source_quality = sum(factor_score_i * weight_i) / sum(weight_i for assessed factors)
```

Round to two decimal places. Report 0.00 for sources where no factor could be assessed (treat as a quality concern in `issues[]`).

---

## 2. Domain Tier

Domain tier reflects the institutional standing and peer-review status of the source type.

| Tier Label | Score | Examples |
|------------|-------|---------|
| Authoritative | 1.0 | Peer-reviewed journals (Nature, AIAA Journal, Journal of Materials Science), government publications (MIL-HDBK, FAA ACs, NIST reports), international standards (ISO, ASTM, SAE AMS) |
| Expert | 0.8 | Conference proceedings (AIAA SciTech, SAE AeroTech), working papers from recognized research institutions, pre-publication drafts by credentialed authors with institutional affiliation |
| Professional | 0.6 | Reputable trade news (Aviation Week, Flight Global, Defense News), analyst reports from established firms (Gartner, Frost & Sullivan, Oliver Wyman), industry association publications |
| Community | 0.4 | Stack Overflow accepted answers, established technical blogs with identified expert authors, Wikipedia articles with strong citation sections |
| General | 0.2 | Open forums, Reddit threads, personal blogs without institutional affiliation, press releases without independent corroboration |

---

## 3. Citation Impact Scoring

Citation impact measures how widely a source has been cited within its field. Use citation counts from Google Scholar, Semantic Scholar, or CrossRef where available.

| Percentile in Field | Score |
|---------------------|-------|
| Top 10% | 1.0 |
| Top 25% (but not top 10%) | 0.8 |
| Top 50% (but not top 25%) | 0.6 |
| Bottom 50% | 0.4 |
| Not applicable (no citation data available) | Exclude factor |

For government publications, standards documents, and regulatory guidance, citation impact is often inapplicable. Exclude the factor and redistribute weight.

---

## 4. Recency Scoring

Recency measures how current the source is. Use the publication date, not the access date. For living documents (standards under active revision), use the most recent revision date.

| Age | Score |
|-----|-------|
| Less than 1 year old | 1.0 |
| 1–3 years old | 0.8 |
| 3–5 years old | 0.6 |
| 5–10 years old | 0.4 |
| More than 10 years old | 0.2 |
| Foundational or seminal work (any age) | 0.8 override |

**Foundational override:** Sources that are widely recognized as foundational references in their domain (e.g., original ASTM B265 titanium sheet standard, original FAA Advisory Circular establishing a certification methodology) receive a floor of 0.8 regardless of age, because their authority is not diminished by time. Agents must justify invoking this override in the `relevant_excerpt` or `issues[]` if the source is more than 10 years old.

---

## 5. Author Credibility

Author credibility assesses the standing of the individual(s) or organization responsible for the content.

| Author Type | Score |
|------------|-------|
| Domain expert with named institutional affiliation (university, national lab, government agency) | 1.0 |
| Published researcher (named, with verifiable publication history in the field) | 0.8 |
| Industry practitioner (named, with verifiable professional role relevant to the topic) | 0.6 |
| Journalist or analyst (named, covering the relevant beat at a credible outlet) | 0.4 |
| Anonymous or pseudonymous | 0.2 |

For organizational sources (e.g., a report published by Boeing, Lockheed, or RAND), assess the organization's credibility as the "author" using the same scale.

---

## 6. Venue Tier

Venue tier reflects the prestige and selectivity of the publication or platform.

| Venue Type | Score |
|------------|-------|
| Top-tier peer-reviewed journal in the field (Nature, Science, top IEEE/AIAA journals) | 1.0 |
| Respected peer-reviewed journal or major established conference | 0.8 |
| Workshop, symposium, or regional conference proceedings | 0.6 |
| Preprint server (arXiv, SSRN, ESSOAr) without peer review | 0.4 |
| Self-published or platform-published (Medium, Substack, personal website) | 0.2 |

For non-academic sources (news, government, standards), venue tier often overlaps with domain tier. In these cases, exclude venue tier and redistribute its weight.

---

## 7. MCP register_source Mapping

When calling the `register_source` MCP tool, map the composite score to the `quality_rating` integer as follows:

| Composite Score | quality_rating |
|----------------|---------------|
| 0.80–1.00 | 5 |
| 0.60–0.79 | 4 |
| 0.40–0.59 | 3 |
| 0.20–0.39 | 2 |
| 0.00–0.19 | 1 |

Always register sources at the time of reading, not after analysis is complete. Register every source that was successfully read, including sources whose evidence was ultimately not used — they form the audit trail of the research effort.

---

## 8. Grouping in Reports

When presenting sources in a report's bibliography or evidence section, group them by quality tier to give readers immediate orientation on evidentiary strength:

| Group Label | Score Range |
|------------|-------------|
| Authoritative | 0.80–1.00 |
| Expert | 0.60–0.79 |
| Professional | 0.40–0.59 |
| Other | Below 0.40 |

Sources in the "Other" group should not be cited as primary support for high-confidence findings. If an Other-tier source is used, it must be clearly labeled and the finding's confidence must reflect the source quality limitation.
