# Training Data v1-Citation Audit

**Run at**: 2026-04-19T10:22:49.648195+00:00
**Dry-run**: True

## Executive Summary

- **Total audited**: 1782
- **Quarantined**: 76
- **Preserved outcome-neutral (v1-linked, pattern-only)**: 7
- **Clean corpus remaining**: 1706
- **Dry-run**: True
- **Pass C balanced accuracy**: 0.500 (majority baseline 0.721, threshold 0.65)

**Quarantined by reason:**

- `format_drift_missing_section`: 75
- `v1_attribution_contradicts_narrative`: 1

## Pass A — v1-Attribution Citation Contamination

Rows are examined only if their `recommendation_id` joins an
`attribution_trades` row where `ranker_only_outcome_v1 !=
`ranker_only_outcome` (the v1 bug corrected by v2).

- **Candidates with recommendation_id linkage**: 112
- **Diverged v1→v2 join cohort**: 9
- **Quarantined (narrative contradicts v2)**: 1 → `v1_attribution_contradicts_narrative`
- **Preserved (outcome-neutral narrative)**: 7 → `v1_attribution_linked_outcome_neutral_preserved` (info only)

## Pass B — Format Drift

Schema checks on each row:
- Output XML required tags: `<why_now>`, `<analysis>` (95% corpus prevalence)
- Output deprecated tags: `<risk_management>`, `<execution_plan>`, `<monitoring>`
- Input required labels: `Ticker:`, `Current Price:`, `Trend State:`

- **Rows checked**: 1782
- **Missing section / label**: 75 → `format_drift_missing_section`
- **Deprecated marker present**: 0 → `format_drift_deprecated_marker`
- **Malformed (open/close imbalance)**: 0 → `format_drift_malformed`

## Pass C — TF-IDF Leakage

- **Balanced accuracy (5-fold CV)**: 0.500
- **Majority baseline**: 0.721
- **Leakage threshold**: 0.65
- **Is leaking?**: NO
- **Labeled examples**: 301

No leakage signal above threshold; narrative text is not predicting outcome beyond class-imbalance baseline.

## Remaining Clean Corpus

- **Clean examples after audit**: 1706
- **Quarantined count**: 76
- **Clean / total ratio**: 0.957

The remaining clean corpus is the input for the next training run.
Quarantined rows are retained in the database and can be un-quarantined via SQL if the operator finds a false positive (reversibility — R5).

