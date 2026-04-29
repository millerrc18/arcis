# Pre-registration addendum 1 — LLM-scoring methodology + PIT discipline

_Author: PM, with operator-stated preferences from PR #853 review (2026-04-29). Amends `docs/research/pre-registration-stage1.md`. **Cut BEFORE Stage 1 walk-forward begins** — pre-reg §5.3 forbids amendments after results are visible. This addendum is binding once committed to main._

## Why this addendum exists

Sprint 1.C option C ("wire LLM-scoring into backtester first, then build deterministic-ranker shadow") landed after the original pre-reg was committed (2026-04-28). Wiring the LLM into the backtester adds methodology decisions the original pre-reg didn't cover:

- Which model version is the backtest measuring?
- How is parse-failure handled in the corpus?
- Which prompt-context sources are PIT-clean enough for historical decision points?
- What about sources that are NOT PIT-clean — accept stale, drop, or build PIT history?

The Sprint 1.C Phase 2 PIT audit (`docs/research/llm-prompt-pit-audit.md`, PR #853) classified all 11 prompt sections. The Phase 1 attribution work (#846, #847, #848, #850 — PRs #849, #851, #852, #863) added the canonical-action validator and the parse_failed flag column. This addendum locks the methodology decisions arising from both before Phase 4 corpus generation begins.

Original pre-reg sections remain binding except where this addendum explicitly revises them.

---

## §A1. LLM-scoring methodology (NEW commitment — extends original §1)

The original pre-reg §1 ("Hypothesis") is operator-authored and committed verbatim. It implicitly assumes LLM-scoring is part of the system under test but does not lock down implementation. This section makes the implementation binding.

### A1.1 — Model version: **`arcis:v1.0.0`** ✓ committed

The single LLM model used to generate scores across the entire walk-forward window. Per pre-reg §5.3, re-running with different `arcis:` model versions until one passes is forbidden. This addendum makes that explicit at the corpus-generation level: **the corpus is generated once, per a single model version. Re-generating against a different model version requires a new pre-registration.**

The bootcamp archive used `halcyon-v1.0.0` for 2026-04-06 → 2026-04-10 then transitioned to `arcis:v1.0.0` from 2026-04-13 onward (per #848 postmortem). Stage 1 corpus uses **`arcis:v1.0.0` only** — pre-`arcis:v1.0.0` historical decision points must NOT be in the corpus until they are re-scored under `arcis:v1.0.0`.

### A1.2 — Sampling: **deterministic** ✓ committed

`temperature=0`, no top_p sampling. Cached LLM responses are byte-for-byte reproducible from `(model, prompt)` pairs; corpus regeneration must produce identical outputs given identical prompts. Operator-side note: any sampling drift from llama.cpp / Ollama backend updates between corpus generation and Stage 1 execution requires a corpus rebuild, NOT a Stage 1 reinterpretation.

### A1.3 — Prompt format: **`_build_feature_prompt` 11-section layout, frozen at v0.32.0** ✓ committed

The runtime prompt assembly path at `src/llm/packet_writer.py:_build_feature_prompt` is the binding format. Section ordering, section headers, and per-field formatting are part of the inference distribution and may not be changed mid-corpus.

If a section's data source is PIT-broken (per §A2 below) AND the operator-elected mitigation is "drop the section from backtest prompts," that section is REPLACED by an empty/placeholder string at the same character offset; it is NOT removed entirely. This preserves the model's prompt-positional priors. The placeholder text and the dropped sections are documented in the corpus manifest.

### A1.4 — Parse-failure semantics: **parse_failed=1 rows excluded from primary metric** ✓ committed

Per #850 (PR #863), parse-failure conviction=5 fallback rows are tagged `parse_failed=1` on `attribution_trades`. The Stage 1 primary-metric computation excludes these rows from the success-criteria evaluation:

- `parse_failed=1` rows do NOT contribute to the §4.1 excess Sharpe
- `parse_failed=1` rows do NOT contribute to the §4.4 sample-size minimum
- `parse_failed=1` rows ARE reported separately in the Stage 1 results document as a "parse-failure rate" diagnostic
- A parse-failure rate >5% on the OOS sample is a §7 "does NOT count as success" trigger — a high parse-failure rate indicates LLM-pipeline contamination and requires investigation before claiming a primary-metric pass

### A1.5 — "Taken" semantic: **rec_id present + conviction not parser-default + parse_failed=0** ✓ committed

For corpus rows entering the §4 primary metric:
- `llm_action = 'taken'` (per #846 canonical-action validator)
- `parse_failed = 0` (per §A1.4 above)
- `rec_id IS NOT NULL` (a recommendation was actually logged)

Rows with `llm_action='conviction_none'` or `llm_action='rejected'` enter the deterministic-ranker shadow comparator (per original §6 secondary diagnostic) but NOT the primary metric.

### A1.6 — Deterministic-ranker shadow scoping: **same prompt minus LLM step** ✓ committed

The §6 secondary diagnostic ("deterministic-ranker shadow portfolio in parallel") runs the IDENTICAL feature pipeline + ranker selection minus the `enhance_packet_with_llm` call. Both portfolios see the same candidates; the shadow takes whatever the ranker selected with no LLM filtering. If primary minus shadow > 0, the LLM is adding selection alpha. If shadow > primary, the LLM is value-destructive at the selection level.

Both portfolios use the same `parse_failed=0` row filter for fair comparison.

---

## §A2. Prompt-context PIT compliance (NEW commitment — extends original §2)

Per `docs/research/llm-prompt-pit-audit.md` (PR #853), 5 of 11 prompt sections are PIT-broken in the current code path. This section locks the binding policy for each.

### A2.1 — Pre-Stage-1 fixes required (MUST land before corpus generation):

| Section | Tracker | Fix description |
|---|---|---|
| 4 — Fundamentals | #856 | Add `as_of` parameter; sort entries by `filed` (filing date) not `end` (period-end); filter `filed <= as_of` |
| 5 — Insiders | #857 | Add `as_of`; pass `[as_of - lookback_days, as_of]` to Finnhub `from`/`to`; cache key includes `as_of` |
| 6 — News | #854 | Route `enrich_features` to `fetch_historical_news(as_of_date=...)` (already implemented; just not wired) |
| 7 — Macro | #855 | Add `as_of`; pass `observation_end=as_of` to FRED `_fetch_series` |
| 10 — Earnings Signals | #859 | Replace `date('now')` literals + `datetime.now(ET)` with `as_of` parameter |
| 11 — Cross-Asset | #855 (bundled) | Same shape as Section 7; same fix lands jointly |

**Stage 1 walk-forward MUST NOT begin until all 6 trackers above are closed.** Phase 4 corpus generation (Sprint 1.C Phase 4 / #96) consumes these fixes.

### A2.2 — Accepted PIT impurities (operator policy decisions):

**Section 3 — GICS Sector classifications (#861 doc):** Accepted as **stale**. The PIT membership table (`data/reference/sp100_history.json`) tracks ticker membership but not historical sector classifications. Building PIT sector history is real data-engineering work for marginal accuracy gain. Known reclassifications (META 2018, BRK.B legacy, PCLN/BKNG 2014) are documented in the corpus manifest as known impurities. Sector-banded subgroup analysis (§6(c)) accepts this caveat; sector misattribution for early-history corp-action descendants is a known and bounded error.

**Section 9 — Earnings calendar PIT (#860):** Accepted as **best-effort**. The `earnings_calendar` and `analyst_estimates` SQLite tables are not yet audited for write-time-PIT discipline (whether earnings dates are immutable once written, whether revisions are timestamped vs overwritten). #860 tracks the audit. Until #860 closes, Section 9 in the corpus uses the table as-is; if the audit later finds PIT violations, Stage 1 results may need to be qualified accordingly. **This is a documented limitation and does NOT block corpus generation** (the alternative — gating Stage 1 on the audit — was rejected because the audit may take days and Section 9 is a low-information section in the prompt).

**Section 8 — Options Flow (audit unresolved):** Replaced with **placeholder text** in the backtest prompts. Per audit, the data source is unconfirmed and likely yfinance-options-current-only (no historical chain available). Per §A1.3, the section is replaced with a constant "Options data not available for this decision point" string at the same character offset. The model has been trained to handle missing-section graceful degradation. This is documented in the corpus manifest as a "section-omitted" decision.

**Section 1 — yfinance auto-adjust caveat (operator decision):** OHLCV from yfinance is auto-adjusted (split + dividend retroactively applied to all historical bars). For a strict PIT backtest, "what would I have seen on date T" is the *unadjusted* close. Stage 1 accepts auto-adjusted prices because (a) returns are unaffected — the relevant input is `pct_change`, which is invariant to the adjustment, and (b) re-implementing unadjusted-price backtest infrastructure is out of scope. **This is documented as a deliberate methodology choice, not an oversight.**

### A2.3 — PIT-clean already (NO action required):

- **Section 1 — Technical Data** (gated on yfinance OHLCV per §A2.2 caveat)
- **Section 2 — Market Regime** (composes from PIT-clean OHLCV)

---

## §A3. Corpus generation contract (NEW — companion to Phase 4 / #96)

Phase 4 (`#96` LLM-scoring corpus + backtester wiring) MUST produce a corpus satisfying these properties for Stage 1 results to be admissible:

### A3.1 — Per-decision artifact requirements ✓ committed

For every walk-forward decision point, the corpus row contains:

- `as_of` (ISO-8601) — the trade decision date
- `ticker`
- `model_version` (`arcis:v1.0.0`)
- `prompt_sha256` — hash of the assembled 11-section prompt
- `response` — raw LLM response string
- `llm_action` (canonical: taken / rejected / parse_failed / conviction_none — per #846)
- `llm_conviction` (1-10 INTEGER — per packet_writer.py clamp)
- `parse_failed` (0/1 — per #850 / PR #863)
- `parser_strategy_succeeded` (which of the 6 conviction-parsing strategies fired, or NULL if all failed)
- `prompt_section_omitted` (JSON array of section numbers replaced with placeholder per §A2.2)
- `enrichment_pit_warnings` (JSON array of any source that returned a PIT-warning during fetch — coverage limit, fallback default, etc.)

### A3.2 — Reproducibility receipts ✓ committed

The corpus is SHA-pinned. Corpus generation outputs a manifest containing:

- Corpus generation date
- Code SHA at generation time
- Total decision points generated
- Per-section PIT status (clean / fixed / accepted-stale / placeholder / TBD)
- Parse-failure rate
- Coverage limit hits per section
- Stage 1 admissibility verdict (PASS / FAIL with reason)

If the corpus's manifest reports any FAIL condition, Stage 1 backtest is blocked until the underlying issue is fixed and the corpus regenerated.

### A3.3 — Re-generation policy ✓ committed

The corpus is generated ONCE for Stage 1. Regeneration triggers a new pre-registration (or addendum) and a new corpus manifest. Specifically forbidden:

- Regenerating with a different model version (per pre-reg §5.3 + §A1.1)
- Regenerating after seeing intermediate Stage 1 results (per pre-reg §5.3)
- Regenerating to "fix" prompt format mid-test
- Selectively re-generating individual decision points

Permitted:
- Regenerating after a confirmed bug in PIT plumbing — but the entire pre-registered protocol is re-run from scratch on the new corpus, not blended.
- Regenerating after a deterministic-output drift (sampling backend update) — full corpus rebuilt, no comparison against the prior corpus's intermediate results.

---

## §A4. Revision to original §3.3 — Stage 1 OOS window

The original pre-reg §3.3 commits to "From 2023-09 onward through end of coverage" with 8 folds × ~4 months each.

**This addendum confirms the original §3.3 is unchanged.** The PR #853 PIT audit raised a concern that Sections 5+6 Finnhub coverage limits might gate Stage 1 to ~2022 onward, but the original pre-reg already starts at 2023-09 — within Finnhub free-tier coverage for both insiders (~2-3yr) and news (~2-5yr).

Edge case: insider data for the earliest test fold (2023-09) is at the edge of Finnhub's free-tier retention. If corpus generation reports >5% missing insider data for the earliest fold, the operator decides at corpus-build time whether to (a) accept the gap as documented in the manifest, or (b) advance the Stage 1 start date by one fold (to 2024-01 onward, 7 folds instead of 8).

If (b) is elected, the change is documented in addendum-2 BEFORE backtest execution, never as a post-result revision.

---

## §A5. Status of original sections (no change)

These sections of the original pre-reg are unchanged by this addendum:

- **§1 Hypothesis** — operator-authored, binding as committed
- **§2 Universe & data** (universe range, PIT lookup, out-of-coverage handling)
- **§3.1, §3.2, §3.4, §3.5** (walk-forward style + fold count + embargo + underpowered-fold reporting)
- **§4 Success criteria** (excess Sharpe ≥ 0.5, t ≥ 2.0, MinTRL, drawdown ≤ 15%, gate combination)
- **§5 Failure criteria** (hard fail / soft fail / forbidden actions — including the bound against re-running with different model versions)
- **§6 Subgroup analyses** (4 subgroups + secondary deterministic-ranker shadow — exploratory)
- **§7 What does NOT count as success** (5 anti-success diagnostic checks)
- **§8 Statistical methodology** (no multiple-testing correction; promotion gate via `src/methods/promotion_gate.py`)
- **§9 Pre-commit verification** (operator-confirmed)

This addendum is additive to the original pre-reg, not a replacement.

---

## §A6. Pre-commit verification for this addendum

- [x] All §A1.x decisions reflect operator's PR #853 review preferences
- [x] §A2 PIT-fix list matches the audit's "must-fix" classification
- [x] §A2.2 accepted-stale exceptions match operator's stated leans (sectors → accept, options → omit, yfinance auto-adjust → document)
- [x] §A3 corpus contract is a binding commitment for Phase 4 / #96
- [x] §A4 confirms original §3.3 OOS window unchanged (2023-09 onward, 8 folds)
- [x] No methodology weakening — every decision is at-or-stricter than the original pre-reg's spirit
- [x] Pre-reg §5.3 satisfied: this amendment is committed BEFORE Stage 1 results are visible

This addendum is binding once committed to `main`. Subsequent amendments require their own dated addendum file (addendum-2, addendum-3, etc.) and a new commit with rationale. **Stage 1 walk-forward MUST NOT begin until §A2.1 PIT fixes are landed.**

---

## Reference

- Original pre-reg: `docs/research/pre-registration-stage1.md`
- PIT audit findings: `docs/research/llm-prompt-pit-audit.md`
- Coverage-drop postmortem: `audits/attribution-coverage-drop-postmortem-2026-04-29.md`
- PIT follow-ups: GitHub issues #854, #855, #856, #857, #858, #859, #860, #861
- Attribution discipline closures: PRs #849, #851, #852, #863
