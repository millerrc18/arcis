# Pre-registration addendum 2 — §A2.2 revisions from #858 + #860 audits

_Author: PM. Date: 2026-04-29. Amends `docs/research/pre-registration-stage1.md` and `docs/research/pre-registration-stage1-addendum-1.md`. **Cut BEFORE Stage 1 walk-forward begins** per §5.3 binding constraint. This addendum is binding once committed to main._

## Why this addendum exists

Pre-Stage-1 robustness audits #858 (Section 8 options) and #860 (Section 9 earnings tables) surfaced findings that contradict addendum-1 §A2.2's classifications. Per §5.3, methodology revisions must land via dated addendum **before** Stage 1 results are visible. This addendum encodes the operator-decided revisions.

Operator decisions (locked 2026-04-29 evening):
- **#858 Section 8**: Option A — fix the loader (add `as_of` plumbing + complete SELECT + iv_skew_25d alias). Implementation in flight.
- **#860 Section 9 / earnings tables**: Option B — repopulate `earnings_calendar` table + accept the UPSERT-overwrite as PIT-best-effort.

## §B1 — Revisions to addendum-1 §A2.2 ("Accepted PIT impurities")

### §B1.1 — Section 8 (Options Flow): RECLASSIFIED from "placeholder" to "fixed via #858 fix PR"

Addendum-1 §A2.2 stated: _"Section 8 — Options Flow (audit unresolved): Replaced with placeholder text in the backtest prompts."_

**Revised**: Section 8 has a live producer (`src/data_collection/options_metrics.py` writing to the `options_metrics` table — schema is PIT-capable with `collected_at` + `collected_date` columns). The runtime loader was PIT-broken AND had a field-name mismatch silently breaking `iv_skew_25d` AND dropped 2 of the 6 schema columns from its SELECT. Per audit #858 (PR #879), the placeholder treatment was wrong.

**Locked decision**: Option A — fix `src/features/engine_helpers.py::_load_options_metrics` to:
1. Accept `as_of` parameter (mirroring the Phase 2 PIT plumbing pattern from #855-#859)
2. Filter `WHERE collected_date <= as_of` BEFORE selecting per-ticker latest
3. Complete the SELECT (add `iv_percentile` + `atm_iv_30d` columns)
4. Alias `iv_skew` → `iv_skew_25d` to match the prompt's expected key
5. Plumb `as_of` through `compute_all_features` to the corpus generator's caller chain

**Implementation status**: Fix is in flight as of this addendum's writing. Once the fix PR merges, Section 8 reclassifies to "fixed" status in the corpus manifest's `section_pit_status` (addendum-1 §A3.2). The corpus generator's `prompt_section_omitted` should NOT include 8 — Section 8 is rendered with PIT-clean data, not omitted.

**Stage 1 admissibility implication**: Phase 4 corpus generation MUST NOT begin until the #858 fix PR lands. Running corpus generation against the broken loader silently leaks future options data (3 of 6 prompt fields populated runtime-only) into historical decision points.

### §B1.2 — Section 9 (Earnings Calendar): RECLASSIFIED from "best-effort" to "best-effort with operator action item"

Addendum-1 §A2.2 stated: _"Section 9 — Earnings calendar PIT (#860): Accepted as best-effort... if the audit later finds PIT violations, Stage 1 results may need to be qualified accordingly."_

**Revised** (per audit #860 / PR #880):
- `analyst_estimates` is **PIT-correct** for cross-day revisions (`INSERT OR IGNORE` on `UNIQUE(ticker, date, source)`). The `as_of` filter from #859 (PR #868) is real for Stage 1's end-of-day decision cadence. Intra-day revisions are silently dropped — acceptable per §A4 OOS window semantics.
- `earnings_calendar` is **PIT-broken** (writer uses `INSERT ... ON CONFLICT(ticker, earnings_date) DO UPDATE SET collected_at=excluded.collected_at` — UPSERT that overwrites collected_at on every re-collection). Plus the table is currently EMPTY (0 rows in production DB).

**Locked decision**: Option B — operator repopulates `earnings_calendar` before Stage 1 corpus generation, AND accepts the UPSERT-overwrite as PIT-best-effort with these documented limitations:
- "Days to Next Earnings" reflects the LATEST fetch's view, not the as-of-date's view
- An earnings date that was rescheduled won't preserve its original announcement timing in the table
- For Stage 1's daily-fetch cadence, this is bounded: each (ticker, earnings_date) row's collected_at is at most ~24h stale relative to the as_of date

**Operator action item**: Run the populator before Stage 1 corpus generation:
```bash
python scripts/fetch_earnings_calendar.py
```
Or whichever wrapper is on the overnight scheduler. Verify with:
```sql
SELECT COUNT(*) FROM earnings_calendar;
-- Should be > 0; current state is 0
```

**Schema gap (separate concern, not blocking Stage 1)**: `earnings_calendar`'s writer uses `ON CONFLICT(ticker, earnings_date)` but the schema doesn't declare a `UNIQUE` index on that pair. Silent fallback to plain INSERT on duplicate-key would create duplicate rows. Filed as follow-up tracker (separate PR).

**Stage 1 admissibility implication**: Phase 4 corpus generation can run with `earnings_calendar` populated post-Option-B. The corpus's `section_pit_status` for Section 9 is recorded as `"best-effort"` (per addendum-1 §A3.2), and Stage 1 results are qualified accordingly: "Days to Next Earnings" is reliable for daily-cadence backtest decisions but not for intraday revisions.

### §B1.3 — Section 11 (Cross-Asset): UNCHANGED

Addendum-1 §A2.2 stated Section 11 had no live producer. This was based on the #855 macro PIT fix's investigation. The #858 audit confirmed that the cross-asset features (`us_10y_yield`, `dxy_level`, `hy_oas`, etc.) have no producer in `src/` and always render `n/a` in production.

**Locked decision**: No change. Section 11 remains placeholder per addendum-1 §A1.3 + §A2.2. The `prompt_section_omitted=(11,)` annotation in the corpus manifest stays correct. Filed as follow-up tracker #870 for any future "wire cross-asset producers" sprint — not blocking Stage 1.

## §B2 — Pre-Stage-1 admissibility checklist (binding)

Before Phase 4 corpus generation begins, all of the following MUST be true:

| # | Item | Verification |
|---|---|---|
| 1 | #858 Option A fix landed in main | `git log main` shows the merge commit; `_load_options_metrics` accepts `as_of` |
| 2 | `earnings_calendar` table populated | `SELECT COUNT(*) FROM earnings_calendar` returns > 0 |
| 3 | #856-#859 Phase 2 PIT bundle merged | Already done as of 2026-04-29 |
| 4 | Pre-reg §A1 model commitments still binding | `arcis:v1.0.0`, temperature=0, prompt format frozen at v0.32.0 |
| 5 | Corpus generator imports the fixed loader | Phase 4 dependency chain re-tested after #858 lands |
| 6 | `parse_failure_rate <= 0.05` enforced by `compute_admissibility` | Already enforced per addendum-1 §A1.4 |
| 7 | All `section_pit_status` values are clean / fixed / placeholder / accepted-stale / best-effort (no 'broken') | `compute_admissibility` rejects 'broken' per addendum-1 §A2.1 |
| 8 | Smoke run (`--dry-run --max-decisions 100`) passes end-to-end | Operator-runnable validation |
| 9 | First-fold smoke (`--folds 1`) produces a clean trade list | Operator-runnable validation |

## §B3 — Status of original sections (unchanged)

Pre-reg §1-9 + addendum-1 §A1, §A3, §A4, §A5, §A6 are unchanged by this addendum. Specifically:

- §A1 LLM-scoring methodology binding (§A1.1-§A1.6) — unchanged
- §A2.1 must-fix tracker list — already closed (Phase 2 bundle)
- §A3 corpus contract — unchanged
- §A4 OOS window 2023-09-01 onward × 8 folds — unchanged
- §5.3 forbidden actions list — unchanged

## §B4 — Pre-commit verification for this addendum

- [x] Encodes operator decisions (2026-04-29): #858 Option A, #860 Option B
- [x] §B1 revisions match the source audits (PR #879 + PR #880)
- [x] §B2 admissibility checklist captures all binding gates before Phase 4 corpus generation
- [x] No methodology weakening — §B2 is at-or-stricter than addendum-1's spirit
- [x] Pre-reg §5.3 satisfied: cut BEFORE Stage 1 results are visible
- [x] Section 11 explicitly preserved unchanged (operator-confirmed in earlier exchange)

This addendum is binding once committed to `main`. Subsequent amendments require their own dated addendum file (addendum-3, etc.). **Stage 1 walk-forward MUST NOT begin until §B2 admissibility checklist is satisfied.**

## Reference

- Original pre-reg: `docs/research/pre-registration-stage1.md`
- Addendum 1: `docs/research/pre-registration-stage1-addendum-1.md`
- #858 audit: `docs/research/section-8-options-source-audit.md` (PR #879)
- #860 audit: `docs/research/earnings-tables-pit-audit.md` (PR #880)
- #858 Option A fix: in flight (PR # to be filled once landed; tracked via task #100)
- Operator decisions logged in chat: 2026-04-29 evening, "858: A // 860: B"
