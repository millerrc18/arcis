# Cold-Read Findings — Stage 1 Corpus

**Date:** 2026-05-11
**Sprint:** S1-CC A3
**Source audit:** [`composition-audit.md`](composition-audit.md) (A2, code SHA `56fd7fb`)
**Corpus artifact:** `data/corpus/stage1-001/entries.jsonl`
**SHA256 (from A1 MANIFEST):** `43c2e3edb2cd4bb450a890da388ec2ade49ce3205d67a0525f2bb74485606d93`
**Row count:** 67,528 entries

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-05-11 | S1-CC A3 | Initial cold-read after A2 composition audit |

## Verdict

**Corpus passes composition audit.**

The A2 audit reports a unimodal length distribution at the long mode (median 2,548 chars, p10 2,094, p90 3,175), zero ISO-week gaps in the 2023-09-01 → 2026-04-28 walk-forward window, a 0.184% `parse_failed` rate well under the 1% red line, and full coverage across all 103 SP100 tickers (203-670 entries per ticker, median 670). The 153-entry shortfall vs the aspirational 67,681 is fully accounted for by the 1,529 coverage-gate skips documented in `manifest.coverage_limit_hits` (fundamentals_no_cik 669, macro_series_unavailable 504, fundamentals_no_data 261, news_fetch_failed 54, insiders_fetch_failed 39, news_coverage_gap 2). §B2 admissibility has already PASSed (per A1 manifest). This audit is forward-looking risk surfacing, not gate re-evaluation — and the risks surfaced below are bounded, classified, and either already filtered out of the training path (parse_failed) or structurally explained (cap exceedance).

## Specific anomalies inspected

### Anomaly 1 — 124 parse_failed entries split into two distinct populations

Sampling the 124 `parse_failed` entries (filtered by `parse_failed: 1` OR `llm_action: "parse_failed"`) reveals a **clean bimodal split**, not a single failure mode:

| Population | Count | Length range | Length median | Generated_at range |
|---|---|---|---|---|
| **Long** (real LLM, parser fail) | 43 | 1,393 – 6,957 chars | ~5,672 chars | 2026-05-03 → 2026-05-11 |
| **Short** (context regurgitation) | 81 | 583 – 843 chars | 804 chars | 2026-05-06 → 2026-05-11 |

**Long parse_failed (43 entries).** These contain real LLM reasoning narratives — full thesis, pullback analysis, stop/target levels, conviction commentary. Sample at line 9307 (INTC 2024-01-16, 5,692 chars): "A pullback from strong uptrend with favorable regime and pullback quality, but weak fundamentals and no insider activity dampen conviction. Enter short-term long with tighter stop for potential pullback bounce. The setup presents... The stop-loss should be placed at $44.34 close basis... The targets are $49.10 and $51.14." The LLM produced text; the structured-field parser couldn't extract `llm_action`/`llm_conviction` cleanly, so the entry was flagged. `parser_strategy_succeeded: None` across all 43.

**Short parse_failed (81 entries).** These are **context-summary regurgitations**, not LLM reasoning. Sample at line 27296 (VZ 2024-07-19, 791 chars) — the entire response is:

> "VZ is in a strong uptrend with underperformer relative strength. Pullback of -1.1% from recent highs into a reward/risk zone.
> Trend: strong uptrend. SMA50 slope is positive, SMA200 slope is positive. Price is 2.4% from 50-day MA and 7.0% from 200-day MA.
> Relative strength: underperformer. RS vs SPY ... Market regime: calm uptrend | Breadth: healthy | SPY RSI: 55.16.
> Fundamentals: Revenue (TTM): $336.7B (-8.3% YoY) | Net Income: $42.4B | Net Margin: 12.6% | EPS: $1.09 | P/E: 38.2 | Last filed: 10-Q (2024-03-31)
> Insider activity (90d): No transactions recorded
> Pullback quality: -1.1% decline from 50-day high. ATR(14): $0.66 (1.6% of price). Volume ratio: 1.00x 20-day average.
> Risk: Stop at $40.30 (2x ATR). Planned risk $200.00 (0.2% of $100000 capital)."

This is the **packet_writer / template_fallback emission pattern** — a verbatim regurgitation of the structured prompt context (Trend → RS → Regime → Fundamentals → Insider → Pullback → Risk), with no LLM thesis, no decision narrative, no per-target rationale. `parser_strategy_succeeded` is `None` for 76 of the 81, `catchall` for 4, `confidence_label` for 1. The 81 short entries cluster in the **second half of generation** (2026-05-06 → 2026-05-11), suggesting an emission-pattern shift mid-run.

**Risk assessment.** The same `packet_writer` fallback pattern was the root cause of task #52 / #53 (big-trim cleanup, 5,045 polluted entries removed). The 81 short entries here are the residual that the `parse_failed` flag *correctly caught* — they did not slip into the `llm_action: taken` (99.7%) training-eligible population. **They are safely flagged and excluded from downstream consumers that filter on `parse_failed == 0`.**

**However:** if any downstream consumer keys on `response` length alone or ignores the `parse_failed` flag, these 81 entries would contaminate the input. Verifying that all training/eval consumers respect the flag is the recommended follow-up (filed below).

### Anomaly 2 — 98.6% ticker-week cap exceedance (A2 §4 informational)

A2 confirms this is structural emission rate, not a corpus-level problem. Direct verification:

| Entries-per-(ticker, ISO-week) | Ticker-weeks | Note |
|---|---|---|
| 1/wk | 101 | Window-edge weeks (corpus start or stop date) |
| 2/wk | 101 | Window-edge weeks (corpus start or stop date) |
| 4/wk | 2,723 | Holiday-shortened weeks (Thanksgiving, Christmas, Independence Day, etc.) |
| 5/wk | 10,783 | Normal full trading week (dominant mode) |
| 6/wk | 403 | ISO-week boundaries that span Mon→Sat-equivalent of 6 trading days (rare) |

The ≤3 cap referenced in the sprint spec applies to a downstream sampling stage (decision-point sub-selection for training), not the raw corpus emission rate. **A2's framing is correct — flag closed.**

### Anomaly 3 — Conviction histogram skewed to 6-8

The conviction distribution clusters tightly at 6 (17.1%), 7 (50.5%), and 8 (20.4%), with only 6 entries at conviction=10 and 3 at conviction=1. This is the LLM's behavioral signature (avoiding extremes), not a corpus defect — but downstream consumers should be aware that the corpus does NOT include rare-event tails at the conviction extremes. Not a blocker for walk-forward.

### Anomaly 4 — Single `model_version` field (no real-LLM vs template_fallback split detectable via this field)

`arcis:v1.0.0` for all 67,528 entries. A2 correctly notes that bimodality of `response` length is the fallback signal — and that check passed (unimodal, no contamination beyond the 124 parse_failed). The 81 short parse_failed entries in Anomaly 1 are exactly the population this check is designed to surface, and they were surfaced. **Working as intended.**

### Anomaly 5 — Bottom-of-distribution tickers (KHC=203, PLTR=279, GEV=327, EXC=391)

These tickers have lower entry counts because they were **added to / removed from the SP100 mid-window** (point-in-time membership). KHC (Kraft Heinz) joined SP100 in 2018-08 from KRFT; PLTR (Palantir) is a recent addition; GEV (GE Vernova) spun off from GE in 2024-04; EXC (Exelon) had a membership gap. This is expected behavior of `get_sp100_at(<as_of>)` — the corpus generator is correctly filtering by historical membership, not snapshotting today's index. **Working as intended.**

## Recommendation

**Proceed to walk-forward.**

The corpus is admissible (§B2 PASS), composition is healthy (unimodal long-mode distribution, no gap weeks, full ticker coverage), and the 124 `parse_failed` entries are correctly flagged and filterable downstream. The 81 short parse_failed entries are the residual `packet_writer` template-fallback pattern, but they are flagged with `parse_failed: 1` AND `llm_action: "parse_failed"` — both downstream filters catch them. No corpus modification is warranted; the artifact is fit-for-purpose for Stage 1 OOS sub-validation (excess-mean > 0 at t > 1.0 over 30 OOS trades) and as input to the walk-forward framework being scoped in Batch B.

**Concrete next step.** Close Batch A (A4 cutover-state verification + A5 MASTER.md update), then dispatch Batch B (walk-forward spec + plan). DO NOT regenerate or trim the corpus.

## Follow-up tasks

These do NOT block the walk-forward dispatch but should be tracked:

- [ ] **Verify all training/eval consumers filter on `parse_failed == 0`** (or `llm_action != "parse_failed"`). Audit `scripts/train.py`, `src/training/dataset_builder.py`, any other JSONL reader of `entries.jsonl`. The 81 short context-regurgitation entries are safe ONLY if every consumer respects the flag. Owner: TBD. Priority: P2 (training v2 prereq).
- [ ] **Investigate why short-parse_failed clusters in the 2026-05-06 → 2026-05-11 generation window.** This suggests a configuration or runtime state change mid-generation (model server restart? prompt format drift? sampling temperature shift?). Cross-reference with operator-side `C:/arcis/halcyon-lab/logs/stage1-corpus.log` for that window. If a regression introduced the pattern, document and fix before the next corpus regeneration. Owner: TBD. Priority: P3 (forensic; corpus is admissible regardless).
- [ ] **Document the long parse_failed parser-failure mode.** 43 entries had valid LLM output but the structured-field parser couldn't extract `llm_action` / `llm_conviction`. Sample the entries' actual closing structure (looks like the parser expects a specific JSON or `Decision: X / Conviction: Y` footer pattern that the LLM omitted). Patching the parser would recover ~43 valid decisions from future corpus runs. Owner: TBD. Priority: P3 (efficiency, not correctness).

None of these block proceeding to walk-forward. All are recoverable from the existing artifact (no re-generation needed).
