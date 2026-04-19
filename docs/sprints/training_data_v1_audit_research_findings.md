# Training Data v1-Citation Audit — Pass 2 Research Findings

**Sprint:** Training Data v1-Citation Audit + Dashboard Integration
**Branch:** `feat/training-data-v1-audit`
**Pass 2 author:** Claude Code (Opus 4.7, 1M context)
**Pass 2 date:** 2026-04-19
**Status:** No operator gate — proceeding directly to implementation.

Pass 2 verifies Pass 1 hypotheses against the live codebase + production DB, and closes open questions. Several Pass 1 decisions are **revised** below based on findings.

---

## 1. Schema inspection — `training_examples` live vs. registry

Ran `PRAGMA table_info(training_examples)` on `C:/arcis/data/ai_research_desk.sqlite3` (993 MB, mtime 2026-04-18 23:30).

Columns present (30 total):
```
example_id TEXT               created_at TEXT
ticker TEXT                   recommendation_id TEXT
trade_date TEXT               feature_snapshot TEXT
input_text TEXT               regime_label TEXT
output_text TEXT              trade_outcome TEXT
quality_score TEXT            instruction TEXT
curriculum_stage TEXT         difficulty TEXT
outcome TEXT                  quality_score_auto TEXT
source TEXT                   outcome_type TEXT
model_version TEXT            regime TEXT
temporal_honesty REAL         evidence_integration REAL
risk_specificity REAL         uncertainty_calibration REAL
structural_compliance REAL    analytical_depth REAL
source_coverage REAL          actionability REAL
composite_score REAL          updated_at TEXT
```

**Missing (confirmed):** `quarantined`, `quarantine_reason`. Commit 3 adds both via the registry.

**Counts:**
- Total rows: **1,782** (matches sprint spec target exactly).
- `recommendation_id` populated: only **112** rows (6.3%). The rest have NULL.
- `model_version`, `regime_label`: **100% NULL**. Cannot use these as v1 discriminators.
- `trade_date`: **100% NULL**. Cannot use as v1 cutoff discriminator on `training_examples`.

**Source distribution (13 sources):**
```
manual_claude_code:         703
historical_backfill:        700
blinded_win:                217
blinded_loss:                84
outcome_template_primary_timeout:   21
outcome_template_contrastive_timeout: 21
outcome_template_*_win:       24 (8 each in 3 buckets)
outcome_template_*_loss:       9 (3 each in 3 buckets)
synthetic_claude:            3
```

**REVISION from Pass 1 §4.1 decision D4:** Pass 1 planned to use `trade_date` as a v1 cutoff. `trade_date` is 100% NULL on training_examples, so this plan does not work. Revised plan uses the linked `attribution_trades` row's `ranker_only_outcome_v1 != ranker_only_outcome` divergence as the ground truth for "v1-affected." See §3.

---

## 2. Output format — it IS XML (Pass 1 §4.2 was wrong)

Pass 1 inspected only `input_text` (plain-text feature snapshot) and concluded outputs are plain-text. Pass 2 inspected `output_text` directly:

- `<why_now>` appears in **1,707 / 1,782 (95%)** of rows.
- `<analysis>` appears in **1,707 / 1,782 (95%)** of rows.
- `<metadata>` appears in 200/200 of the sampled rows (~95% projected).
- `<risk_management>`, `<execution_plan>`, `<monitoring>`: **0% prevalence** — not currently used. If any rows carry them, that is deprecated-marker drift.
- `input_text` remains plain-text (feature snapshot). This is input to the model; the model's output is XML-tagged.

**REVISION from Pass 1 §4.2 decision D5:** Pass B targets XML-tag drift on `output_text`, not plain-text section-marker drift on `input_text`. The plain-text schema check can still apply to `input_text` as a second-tier check, but the primary Pass B signal is XML integrity on `output_text`.

### Pass B rule set (locked by Pass 2)

1. **Required XML tags missing in output_text** → `format_drift_missing_section`
   - Required: `<why_now>`, `</why_now>`, `<analysis>`, `</analysis>`
   - Rationale: 95% prevalence is canonical; the 5% without these are almost certainly drift or malformed.
2. **Unbalanced XML (open tag without close, or vice versa)** → `format_drift_malformed`
   - Regex-level check; do NOT try to parse as real XML (the content inside is natural language, not well-formed XML).
3. **Deprecated XML tags present** → `format_drift_deprecated_marker`
   - Deprecated: `<risk_management>`, `<execution_plan>`, `<monitoring>`
   - If any row contains these, it's an older format version; quarantine.
4. **Required input_text labels missing** → `format_drift_missing_section` (secondary tier)
   - Required labels: `Ticker:`, `Current Price:`, `Trend State:`, `=== ACTUAL OUTCOME ===`
   - Rationale: these appear consistently across sampled `input_text` bodies.

**Moderate strictness (per Pass 1 D1):** unbalanced tags from pathological edge cases (e.g. `<analysis/>` self-closing) are NOT flagged; only true unbalance.

---

## 3. v1 attribution — ground truth lives in `attribution_trades`, not `shadow_trades`

Pass 1 §4.1 noted `shadow_trades.ranker_only_outcome_v1` does not exist. Pass 2 located the real ground truth by grepping every table column for the substrings `ranker`, `attribution`, `v1`, `v2`, `fixed`, `corrected`.

**Finding:** `attribution_trades` table:
```
attribution_id TEXT          (2,370 total rows)
recommendation_id TEXT       (matches training_examples.recommendation_id)
ranker_only_outcome TEXT     — v2 (fixed) outcome
ranker_only_outcome_v1 TEXT  — v1 (buggy) outcome — present on 1,780 rows
ranker_only_pnl_pct TEXT
ranker_only_pnl_pct_v1 TEXT
resolution_version TEXT
pair_type TEXT
```

**v1 divergence:**
```sql
SELECT COUNT(*) FROM attribution_trades
 WHERE ranker_only_outcome_v1 IS NOT NULL
   AND ranker_only_outcome_v1 != ranker_only_outcome;
-- 1,287 trades have v1 outcome != v2 outcome (diverged)
```

**Join path `training_examples` → `attribution_trades`:**
- Via `attribution_id`: 0 matches (attribution_id is internal to attribution_trades)
- Via `recommendation_id`: **12 matches**

12 training examples are directly linked to attribution_trades rows. Of those 12:
- **6 point to diverged trades** (CSCO, MRK across three source variants each: `blinded_win`, `outcome_template_primary_timeout`, `outcome_template_contrastive_timeout`)
- **6 point to agreeing trades** (XOM — v1=loss, v2=loss)

**REVISION from Pass 1 §4.1 D4:** The sprint prompt's Pass A premise — that v1-attribution contamination spreads broadly through the corpus — is narrower than hoped in this database. Pass A via direct `recommendation_id` linkage will only ever quarantine at most 6 rows (the CSCO + MRK set).

**Why Pass A still earns its place in the sprint:** the 6 rows are real contamination (v1 said "loss," narrative may reflect that, v2 says "win"). Even 6 rows of corrupted training data is worth catching. Additionally, Pass A's architecture + tests establish the pattern for future runs once more trades get linked.

**Supplementary Pass A signal — outcome-source mismatch:** training_examples has `outcome_type` and `trade_outcome` columns. For the 6 diverged rows, the example's declared outcome (embedded in source name for `outcome_template_*` or implied by `blinded_win`/`blinded_loss`) may contradict v2 outcome. Specifically:

| example_id (8-char) | source | ticker | v1 | v2 | DIVERGED? |
|---|---|---|---|---|---|
| 08123d9a | `blinded_win` | CSCO | loss | win | ✅ narrative says "win", matches v2 |
| 71120ed0 | `outcome_template_primary_timeout` | CSCO | loss | win | ✅ template name says "timeout" — neither "win" nor "loss"; soft contradiction |
| f8d407e3 | `outcome_template_contrastive_timeout` | CSCO | loss | win | same as above |
| 9bb4eeaa | `blinded_win` | MRK | loss | win | ✅ name says "win", matches v2 |
| 5502f91d | `outcome_template_primary_timeout` | MRK | loss | win | same timeout ambiguity |
| 0ee31aee | `outcome_template_contrastive_timeout` | MRK | loss | win | same |

**Unexpected nuance:** the `blinded_win` examples are actually CONSISTENT with v2 (the fixed outcome). They're not contamination — they're correct post-fix data. What's contaminated is the subtle case where the **narrative** (`output_text`) mentions specifics that only the v1 outcome would have justified. Pass A must inspect `output_text` for narrative cues that contradict v2.

**Pass A locked algorithm:**
1. JOIN `training_examples te ON te.recommendation_id = at.recommendation_id` with `attribution_trades at WHERE at.ranker_only_outcome_v1 != at.ranker_only_outcome`.
2. For each joined row:
   - Parse `output_text` narrative for outcome-directional claims (win/loss signals: "successful", "profitable", "losing", "stopped out", "reversal", etc.).
   - If narrative direction matches v1 (buggy) outcome and contradicts v2 outcome → **quarantine** with `v1_attribution_contradicts_narrative`.
   - If narrative is outcome-neutral (describes pattern, not result) → **preserve** with informational log `v1_attribution_linked_outcome_neutral_preserved`. Do NOT quarantine.
3. Degraded mode (no recommendation_id): skip Pass A for that row; Pass B + C still apply.

**Outcome-direction signal lexicon (derived from output samples):**
- WIN signals: "successful", "profitable", "target hit", "reversal", "mean reversion", "bounce", "gain", "+%"
- LOSS signals: "failed", "breakdown", "stopped out", "continued decline", "rejected", "-%"
- NEUTRAL: pattern-only language, no outcome claim

---

## 4. Training pipeline filter — loader does NOT skip `quarantined=1`

Ran `grep -n "quarantined" src/training/` across all files:

| File:line | Context | Has filter? |
|---|---|---|
| `src/training/data_collector.py:175` | Collects NEW training examples from closed shadow_trades: `AND COALESCE(st.quarantined, 0) = 0` | ✅ (but this is about `shadow_trades.quarantined`, not `training_examples.quarantined`) |
| `src/training/versioning.py:313` | Same — excludes quarantined shadow_trades when building a training run | ✅ |
| `src/training/trainer.py:423` | Main training pipeline `SELECT ... FROM training_examples ORDER BY created_at ASC` | ❌ **no filter** |
| `src/training/trainer.py:472` | Same query pattern at later line | ❌ **no filter** |
| `src/training/validation.py:38` | Validator pull: `SELECT ... FROM training_examples ORDER BY created_at ASC` | ❌ **no filter** |
| `src/training/dpo_pipeline.py:53` | DPO pipeline: `SELECT ... FROM training_examples ...` | ❌ **no filter** |

**Finding:** The loader does NOT currently filter `training_examples.quarantined = 0`. Adding our column + quarantine flags will have no effect on the next training run until a follow-up PR adds the filter.

**Per R6:** Do NOT fix this in this sprint. File a follow-up issue titled *"chore(training): filter quarantined training_examples in trainer.py + validation.py + dpo_pipeline.py"*. Issue to be filed in PR description as a post-merge action.

---

## 5. Existing diagnostic handler patterns — pattern to mirror

Read `src/commands/diagnostic_handlers.py` (86 lines). Two existing handlers:
- `handle_run_regime_diagnostic(payload, config) -> dict`
- `handle_run_forensic_audit(payload, config) -> dict`

Both:
1. Extract `run_id` from payload; return `{"error": ...}` if missing.
2. Call `_prepare_output_paths(prefix, run_id)` to allocate `docs/diagnostics/{prefix}-{run_id}.md` + directory.
3. Invoke `src.diagnostics.dashboard_runner.run_diagnostic(...)` with:
   - `script_path` — path to the diagnostic CLI script
   - `script_args` — additional args (regime passes `--db`, `--exclude-quarantined`, `--bootstrap-n`; forensic passes none)
   - `report_parser` — a summary-extractor function
   - `report_path`, `plot_dir`, `db_path`

**`handle_run_training_audit` will mirror this exactly** with:
- `prefix = "training-audit"`
- `script_path = "scripts/audits/training_data_v1_audit.py"`
- `script_args = ["--db", db_path]` + optional `--pass A|B|C`, `--dry-run`
- `report_parser = parse_training_audit_report` (new function in summary_extractor.py)

**Command name:** `run-training-audit` (kebab-case matches existing `run-regime-diagnostic`, `run-forensic-audit`).

---

## 6. Existing dashboard button pattern — pattern to mirror

Read `frontend/src/components/DiagnosticKickoffButtons.jsx` (70 lines). Two-column grid:

```jsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
  <div className="border rounded p-4">
    <h3>Regime Diagnostic</h3>
    <p>description...</p>
    <button onClick={() => regimeMut.mutate(...)} disabled={regimeActive}>...</button>
  </div>
  <div className="border rounded p-4">
    <h3>Forensic Trade Audit</h3>...
  </div>
</div>
```

**Commit 10 changes:**
1. Grid columns `md:grid-cols-2` → `md:grid-cols-3`.
2. Third `<div>` with `<h3>Training Data Audit</h3>` + description + button.
3. `trainingActive = typeIsActive(runs, 'training_audit')`.
4. `trainingMut = useMutation({ mutationFn: () => api.triggerTrainingAudit(), ... })`.

Button description (~40 words, per D7):
> "Three-pass audit of 1,782 training examples: v1-attribution citation contamination, XML format drift, and TF-IDF leakage detection. Quarantines contaminated rows without deleting. Takes 3–5 minutes."

---

## 7. Capability registration approach

Pattern precedent: `src/diagnostics/__init__.py` holds `@register_action` for both `regime_diagnostic` and `forensic_trade_audit`. The registered function is a **registration anchor** — not the real kickoff. The kickoff happens when the command-executor dispatches `run-regime-diagnostic`.

**Decision — registration module location:** `src/training/audit/__init__.py` will hold the `@register_action` decorator. Add `"src.training.audit"` to `CAPABILITY_MODULES` in `src/platform/capability_registry/bootstrap.py`.

Why not `src/diagnostics/__init__.py`? The sprint prompt explicitly says the training audit's `category="audit"`. It conceptually belongs in `src.training`, and keeping it there preserves the existing diagnostics file's cohesion.

---

## 8. Summary-extractor contract

Read `src/diagnostics/summary_extractor.py`. Existing parser shape:

```python
def parse_regime_report(md: str) -> dict:
    body = _extract_exec_summary(md)
    summary = {}
    # extract fields via regex from ## Executive Summary
    return summary  # fields become diagnostic_runs.summary_json
```

**New function to add — `parse_training_audit_report(md: str) -> dict`:**

Extract from `## Executive Summary` section:
- `total_audited` — int
- `quarantined_by_reason` — dict (taxonomy code → count)
- `leakage_accuracy` — float (from Pass C)
- `clean_corpus_size` — int

If any field missing from markdown → fallback to `raw_executive_summary` + `parse_errors` list (same pattern as regime/forensic).

---

## 9. Existing leakage detector — reuse opportunity

Found `src/training/leakage_detector.py` — already implements `check_outcome_leakage()`:
- TF-IDF vectorizer + LogisticRegression
- Balanced accuracy with StratifiedKFold CV
- Masks ticker + company names to prevent that from registering as leakage
- Threshold: `balanced_accuracy > 0.65 = leaking`

**Reuse decision:** Pass C wraps `check_outcome_leakage()` rather than reinventing. Adds identification of **which examples** are most predictive (top `N` rows by classifier's decision-function score) so the report can list suspect examples. Same random seed (`random_state=42`, per Pass 1 D9).

**Corpus subset for Pass C:** only `blinded_win`, `blinded_loss`, `outcome_win`, `outcome_loss` sources (existing leakage_detector already filters to these; they're the only sources with ground-truth labels). This is the sprint's test cohort — 301 rows total (217 wins + 84 losses).

---

## 10. `react-markdown` already installed

Sprint 1A (v0.25.0) added `react-markdown` + `remark-gfm` per operator approval. Confirmed in `frontend/package.json`. No new frontend deps needed for this sprint. The training audit report renders through the same `DiagnosticRunDetail.jsx` component — free inheritance of markdown + plot rendering.

---

## 11. Dedup logic — same pattern as regime/forensic

Existing `src/api/cloud_routes/diagnostics.py` `_check_dedup(runtime, diagnostic_type)`:

```python
SELECT run_id, status FROM diagnostic_runs
 WHERE diagnostic_type = %s AND status IN ('queued','running')
ORDER BY created_at DESC LIMIT 1
```

On hit → 409 CONFLICT. We pass `diagnostic_type='training_audit'` to the same function.

---

## 12. Revisions to Pass 1 decisions

| # | Decision | Pass 1 choice | Pass 2 revision | Why |
|---|---|---|---|---|
| D4 | v1-cohort definition | Date cutoff + text-pattern | **`attribution_trades` v1!=v2 join** | `trade_date` is 100% NULL on `training_examples`; `attribution_trades` has the actual ground-truth column. |
| D5 | Pass B format target | Plain-text schema | **XML-tag schema on output_text** (+ plain-text on input_text as tier-2) | `output_text` is XML-tagged (95%); ignoring that loses the primary drift signal. |
| — | Pass A reachable cohort | Assumed hundreds | **Exactly 6 rows max** in current DB | 12 examples join attribution_trades; 6 diverged. Pass A still runs; sprint still earns merit from Pass B + Pass C. |

All other Pass 1 decisions (D1, D2, D3, D6–D10) stand unchanged.

---

## 13. Risk re-evaluation

| Pass 1 risk | Post-research status |
|---|---|
| 4.1 — `ranker_only_outcome_v1` missing | RESOLVED: column exists in `attribution_trades`. |
| 4.2 — plain-text vs XML | PARTIALLY RESOLVED: output IS XML; input IS plain-text. Pass B targets both. |
| 4.3 — no `quarantined`/`quarantine_reason` columns | UNCHANGED: commit 3 adds both. |
| 4.4 — diagnostic_type enum | UNCHANGED: column description update only. |
| 4.5 — single-trade link | UNCHANGED: edge case #2 is not achievable on this corpus. |
| 4.6 — `model_version` / `regime_label` NULL | UNCHANGED. |
| 4.7 — text-pattern brittleness | UNCHANGED: accepted; quarantine is reversible. |
| 4.8 — timing | UNCHANGED: 15 min timeout is ample for 1,782 rows. |

**New risk from Pass 2:**
- **Pass A tiny impact** (max 6 quarantines in current DB). Sprint prompt's sanity check "Pass A hit rate < 1% when Pass A found v1-affected trades exist → STOP" will NOT trigger falsely because the hit rate is on the JOINED set (6 rows), not the whole corpus (1,782). Document this nuance in commit 12 dry-run verifier.

---

## 14. Sanity-check formula — commit 12 self-audit

To avoid the false positive above, formalize the dry-run self-audit formulas:

```
v1_affected_join_rows = SELECT COUNT(*) FROM training_examples te
                        JOIN attribution_trades at USING (recommendation_id)
                        WHERE at.ranker_only_outcome_v1 != at.ranker_only_outcome

pass_a_quarantine_rate = (Pass-A quarantined count) / v1_affected_join_rows
# STOP if this is < 1% AND v1_affected_join_rows > 0

corpus_quarantine_rate = (total quarantined) / 1782
# STOP if this is > 40%

distribution_spread = number of distinct taxonomy codes with > 0 quarantines
# STOP if distribution_spread == 1 AND total quarantine count > 100
```

---

## 15. Open items for commit 3+

- Add `quarantined INTEGER DEFAULT 0` to `training_examples` TableDef.
- Add `quarantine_reason TEXT` to `training_examples` TableDef (nullable).
- Update `diagnostic_runs.diagnostic_type` column description.
- No sync_mode changes; existing `incremental` on `created_at` is correct.

All changes are additive and reversible (dropping our new columns is a no-op on any data that pre-existed).

---

**Pass 2 complete. Proceeding to Commit 3 (schema migration) with zero operator gate.**
