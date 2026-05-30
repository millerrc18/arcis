# Sprint: Stage 1 Corpus Closeout + Walk-Forward Framework Scoping

**Date:** 2026-05-11
**Status:** Queued — fires after Sprint 5 Phase 1 PR opens
**Operator-dispatched.** Tracking as PM task #80 (Batch A) + #81 (Batch B).

**Context.** Stage 1 corpus generation completed 2026-05-11 with §B2 admissibility passing. Final state: `data/corpus/stage1-001/entries.jsonl` at target row count (**67,528 entries** per `manifest.json:total_decision_points` — original aspirational target was 67,681; the 153-entry shortfall is from 1,529 coverage-gap skips: fundamentals_no_cik 669, macro_series_unavailable 504, fundamentals_no_data 261, news_fetch_failed 54, insiders_fetch_failed 39, news_coverage_gap 2 — expected attrition). Stage 1 OOS sub-validation (excess-mean > 0 at t > 1.0 over 30 OOS trades) is the next gate; walk-forward validation framework is the next blocker before any Stage 2 (excess Sharpe ≥ 0.5 over 150 OOS trades + ≥4-of-5 promotion gate) work. Per MASTER.md SD#43.

**Sprint hierarchy.**
- This is a 2-batch sprint with strict scope fences.
- Batch A is corpus closeout (artifact preservation + analysis + audit).
- Batch B is walk-forward framework SPEC only — no implementation.
- DO NOT write strategy specs in this sprint. The walk-forward framework precedes any new strategy work per existing operator guardrail.
- DO NOT dispatch training. v2 retrain is gated on walk-forward shipping, not on corpus completion.

**Pre-flight.** Read MASTER.md first. Then read:
- `docs/audits/2026-05-11-stage1-completion/` (already exists — this file is in it)
- `data/corpus/stage1-001/entries.jsonl` first 10 + last 10 + middle 10 rows
- `docs/audits/2026-04-27/stage1_baseline_memo.md` (baseline reference)

---

## Batch A — Corpus Closeout (5 tasks, sequential)

### A1. Pin the artifact immutably
- Compute `sha256sum data/corpus/stage1-001/entries.jsonl > data/corpus/stage1-001/MANIFEST.sha256`
- Also capture: row count (**67,528** confirmed from manifest.json — re-verify with `wc -l`), first/last timestamps in the file, model_version distribution, file size in bytes.
- Write `data/corpus/stage1-001/MANIFEST.md` with the SHA256, counts (**67,528**), and the §B2 admissibility result reference.
- Commit + push. This is provenance — future training runs reference this artifact by SHA.

### A2. Corpus composition audit
Write `scripts/audit_stage1_corpus.py` (≤200 lines, single-purpose). Produces a single Markdown report at `docs/audits/2026-05-11-stage1-completion/composition-audit.md` covering:
- Total entry count vs spec target (**67,528 actual** vs 67,681 aspirational)
- Decision distribution: WIN / LOSS / TIMEOUT / PASS percentages vs target (40 / 25 / 5 / 15 + 75 anchors per existing spec). Report deltas.
- Length distribution: character count histogram (10-bin), median, p10, p90. Flag bimodal patterns (template-fallback signal).
- Per-ticker entry count distribution: max per-ticker, max per-ticker-per-calendar-week, count of ticker-weeks exceeding the ≤3 cap.
- Date coverage: histogram by week, gap detection (any week with zero entries flagged).
- model_version distribution (real LLM vs template_fallback split). Use the 750-800 char vs 2400-3000 char discriminator if model_version field is uniform.

The script must use only stdlib + numpy (already in requirements). No new dependencies.

### A3. Cold-read findings
After A2, READ THE REPORT and write `docs/audits/2026-05-11-stage1-completion/cold-read.md` with operator-facing findings:
- "Corpus passes / marginal / fails composition audit" — one-line top-of-doc verdict
- Specific anomalies found (entries that look wrong on inspection)
- Recommendation: proceed to walk-forward / fix-and-resample / abort-and-rethink

DO NOT modify the corpus in this sprint. If anomalies surface, file them as follow-up tasks. The §B2 pass means the corpus is admissible; this audit is forward-looking risk surfacing, not gate re-evaluation.

### A4. Cutover-state corpus verification
Confirm `data/corpus/stage1-001/` is on the SQLite side, not the migration target. Specifically:
- Verify the directory is outside the DB unification path (should be JSONL files only, no SQLite tables)
- If any corpus metadata IS in `arcis.sqlite3` (e.g., a `corpus_runs` registry table), confirm it survives the PR #1047 + #1048 cutover sequence
- Document the answer in `docs/audits/2026-05-11-stage1-completion/cutover-impact.md` (≤50 lines)

### A5. MASTER.md update
- Section 2 (volatile state): update corpus generation status to "COMPLETE 2026-05-11; §B2 admissibility PASS; **67,528 entries**; SHA: <pin from A1>"
- Update "On the horizon" section: move walk-forward framework from "highest priority unshipped" to "active spec in progress" if Batch B dispatches
- CHANGELOG entry under [Unreleased]: "Stage 1 corpus generation complete (**67,528 entries**, §B2 admissibility PASS, manifest pinned)"
- Run `scripts/verify_docs.py` to confirm no drift.

---

## Batch B — Walk-Forward Framework Spec (3 tasks, parallel-eligible after B1)

### B1. Literature + prior-art review
Read in order:
- `docs/methodology-toolkit.md` (especially the §Shelf entries — Walk-forward, CPCV, block_bootstrap, PSR/DSR sections)
- `src/methods/promotion_gate.py` `_decide` (vote keys cpcv / block_bootstrap / mc_perm / psr_dsr / white_rc — verified shape from PR #971 v5)
- `src/platform/promotion.py:_evaluate_walkforward_gate` (if it exists; otherwise find the closest existing reference)
- Per the operator's research corpus: `Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining.md` for retrain cadence context

Write `docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md` summarizing:
- What walk-forward variants are already implemented vs shelf-only
- How walk-forward composes with the methodology-toolkit gate (4-of-5 voter)
- Existing parameters / config keys / sentinels that the new framework MUST honor (no greenfield reinvention)
- Open methodological questions the operator must decide (window length, train/OOS split, refit cadence, statistical gates per window, acceptance criteria across windows)

### B2. Spec draft (no implementation)
Write `docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md`. This is a spec doc following the operator's existing convention (Revision History → Overview → Architecture → Data Model → API & Module Surface → Error Handling → Testing Strategy → Operational Notes → File Inventory → Known Considerations → Design Decisions Table).

Hard requirements:
- 10-12 design decisions captured in a §Design Decisions Table
- Decision Choice A vs Choice B framing for any high-stakes call (window length, refit cadence, aggregation across windows, what counts as "PASS")
- Composition with existing promotion_gate explicitly documented (does walk-forward feed votes into _decide? Or is it a separate gate that AND-composes with the toolkit gate? Per PR #971 D5/D6 patterns)
- An explicit DO-NOT-DO section: what walk-forward does NOT cover (e.g., does not replace MC perm; does not bypass Stage 2 OOS criteria)
- Falsifiability triggers per PR #940 spec discipline (§5.4 style — what observation would change the spec)

Length target: 250-400 lines. NO design_decisions.json companion file in this sprint — that comes in the impl sprint.

### B3. Plan draft (also no implementation)
Write `docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md`. Standard format per existing operator convention (`## Execution order`, `## Notes`, `## Tasks` with T1, T2... numbered, each with Description + Test Strategy + Scope Fence).

Hard requirements:
- 8-12 tasks
- Each task ≤60 lines of code per src/ file (per CC sprint discipline)
- Each task has explicit Scope Fence (per #957 pattern)
- Batch grouping with parallelism notation (B1 / B2 / B3 / ...)
- Sentinel decision: does walk-forward have its own feature flag (WALKFORWARD_GATE_ENABLED) defaulting true / false? Document the rationale.

---

## Sprint discipline (every task)

- Branch per task (worktree-isolated per existing operator convention)
- No src/ file >400 lines, no function >60 lines (existing repo rule)
- Tests required for any new src/ code (Batch B is docs-only, exempt)
- Each commit prompt ends with: update MASTER.md if applicable + CHANGELOG entry + `scripts/verify_docs.py`
- Documentation: every spec file commits with a Revision History block dated 2026-05-11
- After A5 closes: open follow-up PR with all Batch A artifacts. After B3 closes: open follow-up PR with Batch B artifacts. These are separate PRs — Batch A is operationally complete on its own; Batch B is the bridge to the next sprint.

## Out of scope (DO NOT do in this sprint)

- Any src/ code changes for walk-forward implementation
- Strategy #2 spec work (Connors RSI(2) investigation per existing #511 stays separate)
- v2 training dispatch (gated on walk-forward implementation, not spec)
- New cutover work (#1047 / #1048 stay in queue)
- Any change to bootcamp settings (still active per MASTER.md SD#43)

## Acceptance criteria

This sprint is COMPLETE when:
- `MANIFEST.sha256` + `MANIFEST.md` committed for Stage 1 corpus
- Composition audit report exists and verdict is documented
- Cold-read findings written, no corpus modifications made
- Walk-forward spec-v1 + plan-v1 exist as docs/audits/ artifacts
- MASTER.md reflects post-Stage-1 state
- CHANGELOG entry under [Unreleased]
- Both PRs (Batch A + Batch B) open with reviewer-crosscheck blocks per operator convention

Operator review gates merge — no auto-merge.

---

## PM notes (count correction history)

- **Initial spec dispatch (2026-05-11)** quoted "67,681 entries" — the original aspirational target.
- **Operator correction (2026-05-11)** confirmed the final count from `data/corpus/stage1-001/manifest.json:total_decision_points`: **67,528**.
- The 153-entry shortfall from aspirational is the natural coverage-gap attrition (1,529 decision points hit coverage limits across 6 categories) and does NOT affect §B2 admissibility (PASS).
- All references in this spec now use the corrected 67,528 figure.
