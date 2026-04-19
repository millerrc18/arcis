# Training Data v1-Citation Audit — Pass 1 Evaluation

**Sprint:** Training Data v1-Citation Audit + Dashboard Integration
**Branch:** `feat/training-data-v1-audit` (off `main` at `cf45cf6`)
**Target tag:** v0.26.0
**Pass 1 author:** Claude Code (Opus 4.7, 1M context)
**Pass 1 date:** 2026-04-19
**Status:** No operator gate — proceeding directly to Pass 2 after commit, per operator bypass directive.

---

## 1. Why this sprint, briefly

The operator's #1 competitive edge is training-data quality. An attribution bug in the v1-era outcome-labeling pipeline caused some `shadow_trades` to carry narrative explanations that contradict the eventually-fixed (v2) outcome. Any training example built on those v1 narratives teaches the model a story that never happened — textbook label noise.

Three independent contamination vectors need surfacing:
- **Pass A — v1-attribution contradicts narrative:** the example's `output_text` describes a trade outcome in terms that the v1 bug generated and v2 later overturned.
- **Pass B — format drift:** structural integrity of the prompt/completion text (section markers, schema fields) degraded over time as the generator evolved.
- **Pass C — TF-IDF leakage:** an n-gram in the prompt predicts the label too well — a classic test-set leak pattern even if not v1-attributable.

Never delete, only quarantine. Operator remains in control of the corpus.

---

## 2. R1–R8 satisfaction map

| # | Requirement | Feasibility | Notes / design |
|---|---|---|---|
| **R1** | Never delete training examples; only flag `quarantined=1` + `quarantine_reason` | ✅ Clean | UPDATE-only. All three passes emit row-level reason codes from the taxonomy in §3. |
| **R2** | Three independent passes, runnable in isolation via `--pass A\|B\|C` | ✅ Clean | Each pass is a function with its own input/output contract. The CLI wrapper composes 1–3 of them; the library exposes each individually. |
| **R3** | Fixed taxonomy of quarantine reasons — no free-form strings | ✅ Clean | Enum-ish: `v1_attribution_contradicts_narrative`, `format_drift_missing_section`, `format_drift_deprecated_marker`, `format_drift_malformed`, `leakage_ngram_suspect`. Enforced in code via a Python `Literal` + test. |
| **R4** | 5-section audit report (executive / A / B / C / clean corpus) | ✅ Clean | Renderer builds a fixed-template markdown; missing any section = test failure. |
| **R5** | Reversible (rerun = identical results; operator can un-quarantine via SQL) | ✅ Clean | Deterministic seeds for Pass C TF-IDF split; Pass A/B are pure functions of data state. Rerun is idempotent. |
| **R6** | Do not modify `src/training/data_loader.py` filter behavior | ✅ Clean | Pass 2 confirms loader's current filter; if it doesn't skip `quarantined=1`, we file a follow-up issue — do not fix in this sprint. |
| **R7** | Register as Action via `@register_action` — appears on `/diagnostics` + `/api/system/index` | ✅ Clean | Pattern precedent is Sprint 1B's `audit_registration.py`. The decorator sits on the same kickoff function the command-handler calls. |
| **R8** | Reuse `diagnostic_runs` — do NOT create parallel `audit_runs` | ✅ Clean | `diagnostic_type` is an unconstrained TEXT column (§4.4); `'training_audit'` is simply a new valid value. Registry column description updates from `'regime'\|'forensic'` to `'regime'\|'forensic'\|'training_audit'`. |

**Bottom line:** all eight requirements satisfy cleanly on existing infrastructure. Primary risk lives in the input data, not the plumbing.

---

## 3. Quarantine-reason taxonomy (R3 lock-in)

The full fixed vocabulary — extend only in a future sprint with explicit rationale:

| Code | Pass | Meaning |
|---|---|---|
| `v1_attribution_contradicts_narrative` | A | Linked to a trade where v1 said outcome-X and v2 said outcome-Y; narrative cites outcome-X. |
| `v1_attribution_linked_outcome_neutral_preserved` | A | Linked to a v1-affected trade, but narrative describes pattern/setup only — no outcome claim. **Not** a quarantine reason; tracked for reporting. |
| `format_drift_missing_section` | B | Required section header (e.g. `=== ACTUAL OUTCOME ===`) missing. |
| `format_drift_deprecated_marker` | B | Contains a section or field we removed in a later schema version. |
| `format_drift_malformed` | B | Structural parse failure — truncated, unclosed field, etc. |
| `leakage_ngram_suspect` | C | Example is in the high-suspicion bucket (its n-gram overlap with the classifier's top discriminative features is ≥ threshold). **Report-only in v1;** Pass C does not quarantine unless operator explicitly opts in via `--pass-c-quarantine`. |

Pass A + Pass B quarantine by default. Pass C reports, does not quarantine — leakage remediation is its own sprint (per sprint prompt: "don't gate merge on Pass C").

---

## 4. Identified risks (live-DB findings, ranked by severity)

### 4.1 `shadow_trades.ranker_only_outcome_v1` DOES NOT EXIST [MATERIAL]

**Problem:** The sprint prompt's Pass A design assumes a column `ranker_only_outcome_v1` in `shadow_trades` marks v1-affected trades. Inspection of the live DB (`C:/arcis/data/ai_research_desk.sqlite3`, 1.0 GB) confirms no such column exists. No columns contain the substrings `ranker`, `outcome_v1`, `v2`, `attribution`, `fixed`.

**Impact if ignored:** Pass A fires on zero rows; all "v1-affected" contamination goes undetected.

**Resolution (Pass 2 must confirm):** three candidate v1-cohort definitions, ranked:

- **Candidate 1 — Date cutoff:** v1 attribution bug existed prior to the v2 fix (commit TBD in Pass 2 git archaeology). Every `shadow_trades.entry_timestamp < v2_fix_date` is v1-era. Simplest; robust to schema drift.
- **Candidate 2 — `source` discriminator on the training example:** `historical_backfill` (700 rows) and some `manual_claude_code` (703 rows) were the v1-era sources. `blinded_win`/`blinded_loss` and outcome templates are post-fix. Pass 2 must verify the git-log timing of when each source was added.
- **Candidate 3 — Text-pattern fallback in `output_text`:** regex for `"ranker-only"`, `"v1 attribution"`, numeric patterns that only v1 produced. Per sprint prompt: "If absent, document text-pattern matching fallback."

Pass 2 locks one. Default in Pass 1: Candidate 1 (date cutoff) with Candidate 3 (text-pattern) as a belt-and-suspenders secondary check.

### 4.2 Training examples are PLAIN TEXT, not XML [MATERIAL]

**Problem:** The sprint prompt's Pass B spec reads "detects missing required XML tags" and "detects deprecated tags from older format versions." Inspection of 3 sample `input_text` bodies (example_ids `f3ea7f32…`, `fc69e55a…`, `7f49dfea…`) shows **no XML** — the format uses plain labels (`Ticker:`, `Current Price:`, `Pullback Depth:`) plus banner section markers (`=== ACTUAL OUTCOME ===`).

**Impact if ignored:** Pass B's "XML tag" detection matches nothing; quarantine-rate for Pass B = 0%.

**Resolution:** Pass B detects **plain-text schema drift**:
- Required labels missing (`Ticker:`, `Current Price:`, `Trend State:`, …).
- Required section markers missing (`=== ACTUAL OUTCOME ===`).
- Extra/deprecated labels (TBD in Pass 2 — grep for labels that appear in <5% of rows).
- Malformed structure — body truncated, missing newlines, non-UTF-8 bytes.

No XML parser needed; regex/split-based validator is sufficient.

### 4.3 `training_examples` has no `quarantined` or `quarantine_reason` column [BLOCKER, RESOLVABLE]

**Problem:** Live DB inspection: `PRAGMA table_info(training_examples)` returns 30 columns, none named `quarantined` or `quarantine_reason`. The registry at `src/schema/registry.py:421-461` confirms — these columns are not declared.

**Impact if ignored:** Cannot execute any pass; there's nowhere to write the flag.

**Resolution:** Commit 3 adds both columns to the registry `TableDef`, runs `validate-schema --fix` (additive migration, zero-risk), then `render_migrate.py` to propagate to Postgres.

### 4.4 `diagnostic_type` enum widening [LOW — documentation only]

**Problem:** Sprint prompt talks of extending an enum. Live DB inspection: `diagnostic_type` is stored as `TEXT` with no `CHECK` constraint. The registry column's `description` string says `'regime' | 'forensic'` but that's metadata, not DDL.

**Impact if ignored:** Nothing technical breaks — the column happily accepts `'training_audit'`. But the description lies.

**Resolution:** Update the `ColumnDef` description in `registry.py:1481-1482` to `'regime' | 'forensic' | 'training_audit'`. No DDL change; `validate-schema` passes unchanged.

### 4.5 `training_examples.recommendation_id` is a single-trade link [LOW]

**Problem:** Sprint prompt edge case #2 says "Example linked to 3 trades, 1 affected by v1 bug." Live schema shows `recommendation_id TEXT` — a single scalar, not a JSON array. The sprint's `linked_trade_ids` column does not exist in this codebase.

**Impact if ignored:** Edge case #2 never fires — every example is linked to 0 or 1 trade.

**Resolution:** Pass A's linkage loop iterates `[row.recommendation_id]` when present. Text-pattern matching runs additionally on all examples regardless. Edge-case #2 is not achievable on this corpus; we document it as not-applicable rather than design dead code for it.

### 4.6 `model_version` and `regime_label` are fully NULL [LOW]

**Problem:** Live DB: `SELECT model_version, COUNT(*) FROM training_examples GROUP BY model_version` returns 1 row: `(None, 1782)`. Same for `regime_label`. These cannot discriminate v1-era rows.

**Impact if ignored:** Can't use these as v1 signals. (See §4.1 resolution — we use date + source instead.)

### 4.7 Text-pattern brittleness [LOW, ACCEPTED]

**Problem:** Pass A's text-pattern fallback relies on substring matching in natural-language narratives. False positives possible ("the v1 approach" meaning something unrelated).

**Mitigation:** Decision in §5 — prefer false-positive. Operator can un-quarantine individual examples via SQL. Reversible by design.

### 4.8 Command handler timing [LOW]

**Problem:** The training audit could take 3–5 minutes (Pass C TF-IDF fit on 1,782 examples + bootstrap). `dashboard_runner.timeout_s=900` (15 min) is ample. Serial executor still blocks other queued commands during the run — accepted per Sprint 1A design.

---

## 5. Decisions YOU (Claude Code) make, with written rationale

Per sprint prompt §Pass-1: "Decisions YOU make with written rationale." No operator gate — logged in this doc for Ralph Loop auditability.

| # | Decision | Chosen | Rationale |
|---|---|---|---|
| **D1** | Format-drift strictness (sprint default: moderate) | **moderate** | Strict would flag legitimate variations in early `manual_claude_code` examples that were manually curated and are not actually broken — we'd destroy real signal. Lenient would miss genuine drift like missing `=== ACTUAL OUTCOME ===` headers. Moderate: flag truly-missing required sections, don't flag cosmetic whitespace differences. |
| **D2** | False-positive vs false-negative (sprint default: prefer FP) | **prefer false-positive** | Quarantine is reversible via SQL; un-training on contaminated data is not. An FP costs ~1 training example; an FN poisons the ranker's loss surface permanently. Asymmetric cost → asymmetric threshold. |
| **D3** | Which passes run by default (sprint default: all three) | **A + B + C, all three** | Full audit is the default operator experience. CLI flag `--pass A` etc. narrows when the operator needs a subset (e.g. debugging Pass C behavior). Pass C still runs by default because it's report-only — it can't quarantine unless `--pass-c-quarantine` is set. |
| **D4** | v1-cohort definition (new decision from §4.1) | **Date cutoff primary + text-pattern secondary** | Both are additive — an example is v1-era if EITHER its linked trade entered before the v1→v2 fix date OR its narrative contains a v1-attribution text marker. Belt-and-suspenders; Pass 2 will confirm the exact fix-date by git archaeology. |
| **D5** | Pass B format — XML vs plain-text schema (new decision from §4.2) | **Plain-text schema** | The actual corpus format. XML detection would be dead code. Checker targets section markers + required field labels + parse structure. |
| **D6** | Pass C leakage threshold (gate at what accuracy?) | **Report-only; no default quarantine** | Per sprint prompt "don't gate merge on Pass C leakage finding (report only)." Provide `--pass-c-quarantine-threshold 0.XX` as an opt-in CLI flag, default off. |
| **D7** | Kickoff button description length | **2–3 sentences, ~40 words** | Matches the regime and forensic button prose. |
| **D8** | Run naming | **UUID via `uuid4()`** | Matches Sprint 1A pattern. UI truncates to 8 chars for display. |
| **D9** | Pass C random seed | **`random_state=42`** | Reproducibility (R5) requires a fixed seed. 42 is the repo's convention (used in `simulation_engine.py`). |
| **D10** | CLI default DB path | **`src.config.DB_PATH`** | Same convention as every other script in this repo. |

---

## 6. Non-goals (explicit)

- **Not a retrain.** Quarantining marks data; it does not re-fit the model. The next scheduled retrain consumes the clean subset.
- **Not a loader fix.** Per R6, if `src/training/data_loader.py` doesn't filter `quarantined=1`, that's a follow-up issue, not this sprint.
- **Not a leakage remediation.** Pass C reports; it does not fix the underlying feature-engineering issue (that's a separate sprint).
- **Not a multi-tenant audit.** Single-operator assumption; no per-user quarantine state.
- **Not a quarantine-regeneration loop.** Regenerating quarantined examples with fixed outputs is a v0.26.x follow-up.
- **Not a CSV export.** Inline report viewer only; CSV export is a follow-up.

---

## 7. Proposed file map (Pass 3 preview)

### Create
- `src/training/audit/__init__.py` — module entry; `run_training_audit` is the decorated kickoff
- `src/training/audit/core.py` — orchestrator; composes Passes A/B/C
- `src/training/audit/pass_a_citation.py` — v1-attribution contradicts narrative
- `src/training/audit/pass_b_format.py` — plain-text schema drift
- `src/training/audit/pass_c_leakage.py` — TF-IDF leakage classifier
- `src/training/audit/report.py` — 5-section markdown + summary JSON
- `src/training/audit/taxonomy.py` — Literal of quarantine reason codes + allowlist function
- `src/training/audit/registration.py` — `@register_action` decorator application
- `scripts/audits/training_data_v1_audit.py` — CLI wrapper (≤120 lines)
- `tests/training/test_pass_a.py` — ≥4 tests
- `tests/training/test_pass_b.py` — ≥2 tests
- `tests/training/test_pass_c.py` — ≥2 tests
- `tests/training/test_audit_integration.py` — ≥4 tests (registration, handler, API, reproducibility)

### Modify
- `src/schema/registry.py` — add `quarantined` + `quarantine_reason` columns to `training_examples`; update `diagnostic_runs.diagnostic_type` description
- `src/commands/diagnostic_handlers.py` — add `handle_run_training_audit`
- `src/commands/executor.py` — register new command name `'run-training-audit'`
- `src/api/cloud_routes/diagnostics.py` — add `/training-audit` POST + dedup branch
- `src/platform/capability_registry/bootstrap.py` — import the new registration module
- `frontend/src/components/DiagnosticKickoffButtons.jsx` — third button
- `frontend/src/components/DiagnosticRunTable.jsx` — recognize `training_audit` type
- `frontend/src/api.js` — `triggerTrainingAudit`
- `docs/MASTER.md` — training_examples quarantine documentation
- `CHANGELOG.md` — v0.26.0 entry

All files stay under 400 lines; all functions under 60 lines (CLAUDE.md guardrails).

---

## 8. Dry-run sanity checks Claude Code will self-apply (from sprint prompt, unchanged)

- **Quarantine rate > 40%** → STOP, flag operator.
- **Quarantine rate < 1% when Pass A should find v1-affected trades** → STOP, logic broken.
- **Pass C leakage accuracy** — report only, never gate.
- **Distribution across reasons** — should span multiple taxonomy codes, not 100% concentrated.
- **All four OK** → proceed to write-mode commit 13.

This self-audit is CC discipline; operator does not gate.

---

## 9. Revision based on Pass 2 findings

Two Pass 1 decisions were revised after Pass 2 research (full rationale in `training_data_v1_audit_research_findings.md` §12):

- **D4 v1-cohort definition:** was "date cutoff + text pattern"; revised to **`attribution_trades` JOIN where `ranker_only_outcome_v1 != ranker_only_outcome`**. Reason: `training_examples.trade_date` is 100% NULL in production DB; direct column `ranker_only_outcome_v1` exists in `attribution_trades` (not `shadow_trades` as the sprint prompt assumed).
- **D5 Pass B format target:** was "plain-text schema on input_text only"; revised to **XML-tag drift on `output_text` (primary) + plain-text label drift on `input_text` (secondary)**. Reason: `output_text` is XML-tagged (`<why_now>`, `<analysis>` at 95% prevalence). Ignoring XML loses the main signal.

**Revealed constraint:** Pass A's reachable quarantine cohort in the current DB is **6 rows max** (12 examples join `attribution_trades`; 6 diverged). Sprint still earns merit via Pass B + Pass C corpus-wide checks; the architecture remains sound for future runs as more trades get linked.

---

**Pass 1 complete. Proceeding directly to Pass 2 research (no operator gate).**
