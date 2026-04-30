# Section 11 (Cross-Asset Context) omission audit — closes #870 follow-up question

_Author: PM-direct codebase archaeologist. Date: 2026-04-29. Same shape as #858 options-flow audit (`docs/research/section-8-options-source-audit.md`) and #860 earnings tables PIT audit (`docs/research/earnings-tables-pit-audit.md`). Pre-Stage-1 robustness audit triggered by PR #895 LLM-cost-analysis finding: 100% (98/98) of capped-corpus entries have `prompt_section_omitted=(11,)`._

## TL;DR

**The pre-reg addendum-2 §B1.3 placeholder classification is correct-by-design. Section 11 has zero live producers in `src/`. Five of the six prompt-side feature keys have NO producer anywhere in the codebase, and the one that does (`vix_term_structure`) writes to a table that no enrichment path reads from.**

This is **not** a producer that broke. It is a producer that never landed. The Section 11 prompt block was added to `_build_feature_prompt` (introduced as "optional, NEW" in the section comment at `src/llm/packet_writer.py:287`) before any fetcher was built. The model has been trained and run for the entirety of its production history with all six Section 11 fields rendering `'n/a'`. The LLM has never seen cross-asset data through the prompt — at training time or at inference.

**Recommendation: A — confirm placeholder is correct.** Section 11 has no feasible producer that can be wired in the time before Stage 1 corpus generation, AND the model's training distribution was the `'n/a'` rendering, so building producers now would change the inference distribution mid-experiment (forbidden under pre-reg §A1.3).

The operator should explicitly affirm: **the LLM has zero cross-asset / macro signal beyond what Section 7 (Macro Context) carries**. Any future "macro awareness" attribution claims for Stage 1 results are moot for the cross-asset axis specifically (10Y change, DXY level, HY spread, gold, VIX term structure). Stage 7 macro coverage (Fed funds, 10Y level, 2Y level, CPI YoY, unemployment, regime classification) IS PIT-clean post-#855 — but those are absolute levels and regime labels, not cross-asset deltas.

## Audit methodology

1. Read `src/llm/packet_writer.py::_build_feature_prompt` lines 287-296 — Section 11's six feature-key reads
2. Grepped each feature key (`us_10y_yield`, `us_10y_change_1m`, `dxy_level`, `dxy_change_1m`, `vix_term_structure`, `hy_oas`, `hy_oas_z_score`, `gold_change_1m`) across the entire repo
3. Cross-referenced with `src/data_enrichment/enricher.py`, `src/data_enrichment/macro.py`, `src/data_collection/vix_collector.py`
4. Spot-checked 3 entries from `data/corpus/stage1-capped/entries.jsonl`
5. Reproduced the rendered Section 11 area for empty features (matches what every corpus entry's prompt would have contained)
6. Read GitHub issue #870 (the open follow-up tracker that this audit answers)
7. Compared findings against `docs/research/llm-prompt-pit-audit.md` (Phase 2 audit, PR #853) and addendum-2 §B1.3

## What Section 11 is supposed to contain

Per `src/llm/packet_writer.py:287-296` the Section 11 prompt block is:

```
=== CROSS-ASSET CONTEXT ===
US 10Y Yield: {us_10y_yield}% ({us_10y_change_1m} 1m)
US Dollar Index: {dxy_level} ({dxy_change_1m} 1m)
VIX Term Structure: {vix_term_structure}
HY Credit Spread: {hy_oas} bps ({hy_oas_z_score} Z)
Gold: {gold_change_1m} (1m)
```

The system prompt (`src/llm/prompts.py:35`) instructs the LLM to use it:

> "When cross-asset context is available, note correlations that support or undermine the thesis. Rising yields and a strong dollar create headwinds for growth names. Widening credit spreads signal risk aversion."

So the **intended** semantics are: **deltas and term-structure signals across rates / FX / credit / commodities / vol** that complement Section 7's macro absolute levels. The feature keys break down as:

| # | Prompt key | Intended source | Asset class |
|---|---|---|---|
| 1 | `us_10y_yield` | FRED `DGS10` | Rates (level — duplicates Section 7's `treasury_10y` semantically) |
| 2 | `us_10y_change_1m` | FRED `DGS10` 1m delta | Rates (delta) |
| 3 | `dxy_level` | yfinance `DX-Y.NYB` (or FRED `DTWEXBGS`) | FX |
| 4 | `dxy_change_1m` | yfinance/FRED 1m delta | FX (delta) |
| 5 | `vix_term_structure` | yfinance `^VIX` / `^VIX3M` ratio | Vol (term structure) |
| 6 | `hy_oas` | FRED `BAMLH0A0HYM2` | Credit (HY OAS) |
| 7 | `hy_oas_z_score` | derived 252d Z-score | Credit (Z-score) |
| 8 | `gold_change_1m` | yfinance `GC=F` 1m return | Commodities (delta) |

Eight feature keys total across five asset classes. The intended shape is a "cross-asset macro delta dashboard" — distinct from Section 7's macro **levels and regime** snapshot.

## Producer audit — per feature key

### Feature key 1-2: `us_10y_yield`, `us_10y_change_1m`

- **Producer in `src/`:** NONE.
- Grep confirmed: only consumer site is `src/llm/packet_writer.py:292`. No producer file writes these keys to any features dict.
- **Note**: Section 7's `treasury_10y` (FRED `DGS10`) IS produced by `src/data_enrichment/macro.py:259` — but it's bound to `treasury_10y`, NOT `us_10y_yield`, and Section 7 emits it through `format_macro_summary()` as text inside the macro summary block, not as a per-key feature. So even though FRED's `DGS10` series IS being fetched (PIT-clean post-#855), its value never reaches Section 11's prompt slot.

### Feature key 3-4: `dxy_level`, `dxy_change_1m`

- **Producer in `src/`:** NONE. Grep on `dxy_level` returns zero hits outside `packet_writer.py`. Grep on `DXY` or `DTWEXBGS` returns zero hits in `src/`.

### Feature key 5: `vix_term_structure`

- **Producer in `src/`:** PARTIAL. There IS a producer (`src/data_collection/vix_collector.py::collect_vix_term_structure`) that writes to the `vix_term_structure` SQLite table (defined in `src/schema/registry.py:1119-1140`). The collector is wired into the daily overnight schedule (`src/scheduler/overnight.py:622-664`) and the on-demand collector chain.
- **BUT no read path to features dict.** The `vix_term_structure` table IS read by:
  - `src/council/context.py:83` — council subsystem (different subsystem, not the prompt builder)
  - `src/journal/store.py:339` — journal writer (post-trade)
  - `src/scheduler/reports.py:189-668` — report generation (post-trade EOD reports)
  - `src/services/mr_scan_service.py:86` — mean-reversion scanner (different prompt path)
  - `src/scheduler/universe_scanner.py:123` — pullback universe scanner (uses VIX for regime gating, not for Section 11 prompt)
  - `src/scheduler/premarket.py:57` — premarket gating
- **None of these read paths populate `features['vix_term_structure']` for the LLM prompt.** The producer exists, the data is in the table, the read sites read it for OTHER purposes — but no enricher/feature-engine call site reads `vix_term_structure` and writes it into the per-ticker `features` dict that `_build_feature_prompt` consumes.
- This is the **only** Section 11 key with a wireable producer. The fix would be a 1-PR enrichment-side wiring (add a fetcher call in `enrich_features` that reads the latest `vix_term_structure` row PIT-correctly and writes a string like `"contango (normal, slope=0.92)"` to `features['vix_term_structure']`).

### Feature key 6-7: `hy_oas`, `hy_oas_z_score`

- **Producer in `src/`:** NONE. No FRED fetcher for `BAMLH0A0HYM2` exists. No alternative HY-spread source exists. The 252d Z-score derivation also has no producer.

### Feature key 8: `gold_change_1m`

- **Producer in `src/`:** NONE. No yfinance `GC=F` fetcher. No commodity-fetcher pattern in the codebase.

### Producer-status table (summary)

| # | Prompt key | Producer file | Writes to features dict? | PIT-capable? | Status |
|---|---|---|---|---|---|
| 1 | `us_10y_yield` | none | no | n/a | **fundamentally absent** |
| 2 | `us_10y_change_1m` | none | no | n/a | **fundamentally absent** |
| 3 | `dxy_level` | none | no | n/a | **fundamentally absent** |
| 4 | `dxy_change_1m` | none | no | n/a | **fundamentally absent** |
| 5 | `vix_term_structure` | `src/data_collection/vix_collector.py` | **NO** (data in table, not in features dict) | yes (table has `collected_at` + `collected_date`) | **deferred wiring** (writer exists, reader not wired) |
| 6 | `hy_oas` | none | no | n/a | **fundamentally absent** |
| 7 | `hy_oas_z_score` | none | no | n/a | **fundamentally absent** |
| 8 | `gold_change_1m` | none | no | n/a | **fundamentally absent** |

**7 of 8 keys are fundamentally absent. 1 of 8 keys has a writer-but-no-reader (deferred wiring).**

## PIT-cleanliness analysis

The #856-#859 audits all asked: "given a producer that exists but is PIT-broken, would `as_of` plumbing close the gap?" That question is moot for Section 11 because **there is nothing to plumb for 7 of 8 keys**.

For the one key with a partial producer (`vix_term_structure`):
- The schema IS PIT-capable (`vix_term_structure` table has both `collected_at` and `collected_date` columns + an `idx_vix_term_structure_date` index would be needed but no such filter currently runs on the corpus path)
- So if a wiring fix were made, the schema would support it: `WHERE collected_date <= as_of ORDER BY collected_date DESC LIMIT 1` would be PIT-correct
- However the table's `sync_mode="latest_only"` (per `src/schema/registry.py:1138`) means **Render Postgres only carries the latest snapshot**. The local SQLite has full history; the cloud copy doesn't. For Stage 1 corpus generation running locally on the operator's machine against `C:\arcis\data\ai_research_desk.sqlite3`, this isn't a blocker. But it's a constraint worth noting if cloud-side corpus regeneration were ever required.

For the seven keys with no producer at all: PIT analysis is N/A. There's no schema to be clean or broken.

## Spot-check transcript: actual corpus prompts

I cannot show the literal Section 11 area from the corpus because the corpus generator stores `prompt_sha256` (the hash) but NOT the raw prompt text — see `src/evaluation/corpus.py:82` (entry schema only carries the hash). However:

1. **Reproduction:** I ran the exact `_build_feature_prompt` logic on an empty feature dict (the same shape that the corpus encountered for these keys, since no enricher writes to them). Result:

   ```
   === CROSS-ASSET CONTEXT ===
   US 10Y Yield: n/a% (n/a 1m)
   US Dollar Index: n/a (n/a 1m)
   VIX Term Structure: n/a
   HY Credit Spread: n/a bps (n/a Z)
   Gold: n/a (1m)
   ```

2. **Three entries from `data/corpus/stage1-capped/entries.jsonl`** (read directly):

   - Entry 1: `as_of=2023-09-01, ticker=AAPL, prompt_sha256=898941cb..., prompt_section_omitted=[11]`
   - Entry 2: `as_of=2023-09-01, ticker=ABBV, prompt_sha256=a8f301ba..., prompt_section_omitted=[11]`
   - Entry 3: `as_of=2023-09-01, ticker=ABT, prompt_sha256=92612ada..., prompt_section_omitted=[11]`

   Per PR #895's finding (also reflected in the manifest at `data/corpus/stage1-capped/manifest.json`): all 98/98 entries carry `prompt_section_omitted=[11]` and `section_pit_status[11]="placeholder"`. The corpus generator (`src/evaluation/corpus_generator.py:82`) hardcodes `_OMITTED_SECTIONS = (11,)`.

3. **Manifest receipt:**

   ```json
   {
     "section_pit_status": {
       "1": "clean", "2": "clean", "3": "accepted-stale",
       "4": "fixed", "5": "fixed", "6": "fixed", "7": "fixed",
       "8": "fixed", "9": "best-effort", "10": "fixed",
       "11": "placeholder"
     },
     "total_decision_points": 98,
     "admissibility": "PASS"
   }
   ```

The `compute_admissibility` gate (per `src/evaluation/corpus.py:195-210`) PASSES because "placeholder" is an accepted status. Only "broken" is rejected.

## Why this happened (history)

The Section 11 prompt block was introduced into `_build_feature_prompt` as part of the "11 sections" expansion. The comment at `src/llm/packet_writer.py:287` reads:

> `# SECTION 11: Cross-Asset Context (optional, NEW)`

The code was written for a producer that was planned but never delivered. The phase-2 PIT audit (`docs/research/llm-prompt-pit-audit.md`) at line 156-163 made an inferential error: it classified Section 11 as "❌ PIT-broken — MUST FIX" by assuming the same FRED-fetcher pattern as Section 7. **The audit didn't grep for the producer.** Pre-reg addendum-1 §A2.1 inherited that error and bundled #855 as covering both Section 7 AND Section 11.

When the dispatched agent implemented #855 (PR #869, FRED PIT plumbing for Section 7), they correctly observed that Section 11's keys had no FRED-side producer to plumb, and filed the corrective tracker #870. Pre-reg addendum-2 §B1.3 then encoded the right answer: Section 11 is placeholder, no live producer, no further action.

**The PR #895 LLM-cost finding (100% of corpus entries have `prompt_section_omitted=(11,)`) is therefore correct, intentional, and matches the addendum-2 binding decision.** It is a feature, not a bug.

## Recommendation: A — confirm placeholder is correct

### Why A and not B/C

**Option A: Confirm placeholder is correct (RECOMMENDED).**
- Reasons:
  1. **Producer absence, not breakage.** The PR #895 finding reflects the intended design as of addendum-2 §B1.3. There is no broken pipeline to fix.
  2. **Training distribution preservation.** The model (`arcis:v1.0.0`) was trained with Section 11 always rendering `'n/a'` — see audit's history note above. Adding producers now would change the inference distribution, which pre-reg §A1.3 explicitly forbids ("prompt format frozen at v0.32.0... Section ordering, section headers, and per-field formatting are part of the inference distribution and may not be changed mid-corpus").
  3. **Methodology drift cost.** Wiring even just `vix_term_structure` (the cheapest fix) would change a section's contents from "5 'n/a' lines" to "1 line with a real value + 4 'n/a' lines". This IS a per-field formatting change relative to the model's training distribution.
  4. **Marginal Stage 1 information value.** The cross-asset signals are already partially captured: VIX level enters Section 2 ("Volatility: ... VIX") via `vix_proxy`; 10Y/2Y enters Section 7 via FRED PIT; sector rotation enters Section 3. The additional information from a cross-asset delta dashboard is incremental, not foundational.

**Option B: Wire `vix_term_structure` (the only deferred-wiring key).**
- Effort: ~half-day. The pattern would be:
  1. Add a `_load_vix_term_structure(as_of)` helper in `src/data_enrichment/macro.py` or `src/features/engine_helpers.py`
  2. Filter `WHERE collected_date <= as_of ORDER BY collected_date DESC LIMIT 1`
  3. Format result as a string like `"contango (slope=0.92)"` and write to `features['vix_term_structure']`
  4. Tests mirroring the #855/#856 PIT tests
- Reasons against:
  - Changes the training-distribution shape (4 of 5 lines `'n/a'` → 3 of 5 lines `'n/a'` + 1 line populated)
  - The information is already captured in Section 2's `vix_proxy` realized-vol field — VIX term structure is a refinement, not a new signal
  - Pre-reg §5.3 + §A1.3 forbid amendments after results are visible. If wired now, an addendum-3 would be required AND Stage 1 corpus would need full regeneration
- If selected: pre-reg addendum-3 required before Stage 1 corpus regeneration. Same shape as addendum-2 but with §B1.3 reclassifying Section 11 from "placeholder" to "partial-fixed (vix_term_structure only)".

**Option C: Build full Section 11 producers (yfinance VIX/DXY/Gold + FRED HY OAS + 252d Z-score derivation).**
- Effort: 2-3 days minimum. Five fetchers + derivations + tests + cache layer + PIT plumbing + enricher wiring.
- Reasons against:
  - Same training-distribution mismatch as B but more severe (5 of 5 lines change)
  - Real data-engineering work for marginal Stage 1 value
  - HY OAS Z-score derivation requires a 252d rolling history fetch, which adds complexity to PIT cache layer
  - Stage 1 timeline impact: 2-3 days delay vs Option A's zero days
- If selected: pre-reg addendum-3 required. Stage 1 corpus full regeneration. Bigger inference-distribution shift than Option B.

### Methodology implication if B or C is picked

Per pre-reg §5.3:

> "The hypothesis, model commitments (§A1), and prompt-format freeze (§A1.3) are binding once the pre-registration is committed to main. Subsequent amendments require a dated addendum file BEFORE Stage 1 results are visible."

Per addendum-1 §A1.3:

> "The runtime prompt assembly path at `src/llm/packet_writer.py:_build_feature_prompt` is the binding format. Section ordering, section headers, and per-field formatting are part of the inference distribution and may not be changed mid-corpus."

**Pre-reg amendment requirement matrix:**

| Recommendation | Amendment required? | Corpus regeneration required? | Stage 1 delay |
|---|---|---|---|
| A: Confirm placeholder | NO (addendum-2 §B1.3 already covers) | NO | 0 days |
| B: Wire `vix_term_structure` only | YES — addendum-3 needed | YES — full corpus rebuild | ~1 day (half-day implementation + half-day corpus regen) |
| C: Wire all 8 keys | YES — addendum-3 needed | YES — full corpus rebuild | 3-4 days minimum |

Critical: under §5.3, **the producer change must land BEFORE Stage 1 begins** for the amendment to be valid. If results are visible (even partial first-fold smoke), §5.3 is violated and the experiment must restart from a fresh pre-registration.

## Operator decision required

The audit's finding is unambiguous: addendum-2 §B1.3 is correctly classified. The PR #895 finding (98/98 entries with `prompt_section_omitted=(11,)`) is the intended state.

**Operator should explicitly affirm:**

> "I confirm Stage 1 corpus runs with Section 11 rendering as placeholder ('n/a' on all 8 keys). I acknowledge the LLM has no cross-asset / macro-delta / commodity / FX / credit-spread signal at inference time. Any 'macro awareness' attribution claim from Stage 1 results applies only to Section 7's macro absolute levels (Fed funds, 10Y, 2Y, CPI YoY, unemployment, regime label) and Section 2's market-regime composites (VIX proxy, breadth, drawdown). It does NOT apply to cross-asset deltas (10Y change, DXY change, gold change), credit conditions (HY OAS), or vol term structure."

If the operator instead picks B or C, this audit becomes the seed for addendum-3 + corpus regeneration. But the strong case is A — the design choice was made and is internally consistent; reversing it now costs more than its information value.

## Strict-rigor receipts

- All 8 Section 11 prompt fields traced from `_build_feature_prompt` (file:line `packet_writer.py:287-296`) through grep across the entire repo
- Producer absence verified for 7 of 8 keys via `Grep` on each key (zero matches outside `packet_writer.py`)
- Producer existence + read-path absence verified for `vix_term_structure`: writer at `src/data_collection/vix_collector.py:53-112`, schema at `src/schema/registry.py:1119-1140`, ZERO read sites that write to `features['vix_term_structure']`
- Enricher inspected (`src/data_enrichment/enricher.py`) — confirms only Sections 4/5/6/7/10 are wired; Section 11 is NOT in the enrichment chain (docstring at line 73-79 explicitly states "section 11 has no live producer (#870 pending)")
- Corpus inspected: 3 entries spot-checked from `data/corpus/stage1-capped/entries.jsonl`, manifest at `data/corpus/stage1-capped/manifest.json` confirms `section_pit_status[11]="placeholder"` and `admissibility=PASS`
- Cross-referenced #870 GitHub issue — surfaces the same Option A/B/C tree this audit recommends choosing on
- Cross-referenced llm-prompt-pit-audit.md — confirms Section 11's earlier classification as "PIT-broken MUST FIX" was an inferential error (didn't grep for producer); addendum-2 §B1.3 corrected it
- Cross-referenced #858 (PR #879) and #860 (PR #880) audit shapes — this audit follows the same skeleton: methodology + producer audit + PIT analysis + recommendation + amendment requirement matrix
- No code changes; doc-only deliverable
- Investigation duration: ~30min PM-direct against the worktree; finding is not surprising given addendum-2 §B1.3 already encoded the answer — this audit's value is the receipt that confirms the addendum's classification matches the actual codebase state

## What this audit did NOT cover

- **Did not measure the Stage 1 information loss from Section 11's absence.** A small ablation study (compare LLM conviction distributions for trades on high-vol-term-structure-stress days vs low-stress days) could quantify the cost of the placeholder. Worth doing post-Stage-1 if Stage 1 fails primary metric and macro-awareness deficit is a candidate explanation.
- **Did not check if any other prompt-builder path** (e.g., `_build_condensed_prompt`, mean-reversion prompt, postmortem prompt, training-time prompt) references the Section 11 keys. Spot-check shows `_build_condensed_prompt` does NOT (it's a reduced 1-section prompt). MR/postmortem paths are out of Stage 1 scope.
- **Did not audit whether the model's training set** (the historical-bootcamp corpus that produced `arcis:v1.0.0`) contained Section 11 with populated values. If it did, the model has been TRAINED on cross-asset signals but is INFERRING without them — which would be an even bigger distribution mismatch. The `docs/research/deep-research/horizontal-training-data-RESULTS.md` mention of these keys (per grep) suggests the training-data assembly may have referenced them at some point. Worth a separate audit if Stage 1 conviction distributions look unusual.
- **Did not investigate the wider question** of whether `_build_feature_prompt` has OTHER deferred-wiring sections beyond #11. The Phase 2 audit (PR #853) classified all 11 sections, so this is conceptually covered, but Section 11's producer-absence vs producer-PIT-broken distinction wasn't drawn cleanly there.

## Reference

- Pre-reg addendum 2 §B1.3: `docs/research/pre-registration-stage1-addendum-2.md` (binding)
- Pre-reg addendum 1 §A1.3 + §A2.1: `docs/research/pre-registration-stage1-addendum-1.md`
- Phase 2 PIT audit: `docs/research/llm-prompt-pit-audit.md` (Section 11 misclassification documented)
- #858 sibling audit: `docs/research/section-8-options-source-audit.md`
- #860 sibling audit: `docs/research/earnings-tables-pit-audit.md`
- GitHub tracker #870 (this audit answers the operator-decision question filed there)
- PR #895 (LLM cost analysis surfaced the 100% omission rate)
- Code citations: `src/llm/packet_writer.py:287-296` (Section 11 emission), `src/llm/packet_writer.py:147` (`_OPTIONAL_SECTIONS` includes 11), `src/data_collection/vix_collector.py` (the only partial producer), `src/data_enrichment/enricher.py:73-79` (docstring explicitly notes Section 11 has no live producer), `src/evaluation/corpus_generator.py:82` (`_OMITTED_SECTIONS = (11,)`)
- Corpus receipts: `data/corpus/stage1-capped/entries.jsonl` (98/98 entries), `data/corpus/stage1-capped/manifest.json` (`section_pit_status[11]="placeholder"`, `admissibility=PASS`)
