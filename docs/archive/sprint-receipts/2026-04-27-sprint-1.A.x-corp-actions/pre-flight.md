# Sprint 1.A.x — Pre-flight: SP100 Corporate Actions Enumeration (#803)

**Status:** OPERATOR DECISION REQUIRED on the candidate-event list before Developer dispatch.

**Author:** PM-direct (Planner agents have hit the 6-turn cap on three research-heavy preflights today; #53 tracks the skill bump). Sources cross-referenced: existing `_CURATED_CHANGES` in `scripts/build_sp100_history.py:61-89`, PR #802 + #813 review verifications by operator, and standard public-knowledge corporate-action databases.

**Base branch:** `sprint/1.A.x-corp-actions/base` @ `790bb36`.

## Recap of existing `_CURATED_CHANGES`

15 entries, all `add/remove` events, 2015-03-20 → 2025-03-24:

```
2015-03-20: +CMCSA -ACE          2017-03-20: +AVGO -TWX
2015-09-18: +PYPL -EBAY          2017-06-19: +LOW
2016-03-18: -BKR                 2018-06-18: +NFLX -TWX  ← TWX twice (#805)
2016-09-06: +CHTR                2019-06-03: +SBUX -GE
                                  2020-12-21: +TSLA -OXY
2021-03-22: +NVDA -WBA           2023-09-18: +ABNB -ATVI
2022-03-21: +DXCM -EMRG          2024-03-18: +SMCI
                                  2024-06-24: -KHC
2025-03-24: +PLTR -EXC
```

**No rename/merger/spinoff entries.** This is the gap #803 fixes.

## Candidate corporate-action events to add (operator review required)

### Tier A — operator-verified in PR #802 / #813 reviews (HIGH confidence)

| date | type | from | to | source | notes |
|---|---|---|---|---|---|
| 2018-02-27 | rename | PCLN | BKNG | Priceline Group → Booking Holdings | Operator-verified. Most-cited example. |
| 2015-07-06 | merger | KRFT | KHC | Kraft + Heinz merger forming Kraft Heinz Co. | Operator-verified. Functionally a rename of the surviving entity (KRFT pre-merger). |
| 2020-04-03 | merger | [UTX, RTN] | RTX | UTC + Raytheon Co. merger forming Raytheon Technologies | Operator-verified. Note the [UTX, RTN] pair: pre-merger snapshots should have BOTH as separate SP100 members; post-merger only RTX. |
| 2016-09-07 | removal-via-acquisition | EMC | (none) | EMC Corp acquired by Dell Technologies | Operator-verified. EMC was SP100 until delisted on this date. Dell remained private until 2018 IPO (DELL added to SP500 only). |
| 2017-06-13 | removal-via-acquisition | YHOO | (none) | Yahoo! Inc. core acquired by Verizon; remaining Altaba spun off | Operator-verified. YHOO was SP100 until delisted. |

### Tier B — high-likelihood from public record (HIGH confidence, verify before commit)

| date | type | from | to | source | notes |
|---|---|---|---|---|---|
| 2022-06-09 | rename | FB | META | Facebook → Meta Platforms | Ticker change announced 2021-10-28, executed 2022-06-09. FB was SP100 throughout. |
| 2019-04-02 | split (DWDP→DOW+DD) | DWDP | [DOW, DD] | DowDuPont split | DWDP existed 2017-08 to 2019-04. Less critical for backtest correctness if DOW or DD aren't separately tracked in SP100; verify SP100 membership of DWDP. |
| 2019-11-20 | removal-via-acquisition | CELG | (none) | Celgene acquired by Bristol Myers Squibb | Verify SP100 membership of CELG pre-2019. |
| 2020-04-01 | removal-via-acquisition | S | (none) | Sprint acquired by T-Mobile US | Verify SP100 membership. May or may not have been SP100. |

### Tier C — possible but lower-confidence (needs verification)

| date | type | from | to | source | notes |
|---|---|---|---|---|---|
| 2022-10-28 | removal-via-private-takeover | TWTR | (none) | Twitter taken private by Musk | Likely SP500, SP100 less certain. Skip if not SP100. |
| 2024-XX | misc | various | various | Other 2024 SP100 changes | Existing curated list has only one 2024 add (SMCI) + one removal (KHC). Verify completeness. |
| 2018-XX | misc | various | various | TWX-twice issue (#805) — 2017-03-20 says "+AVGO -TWX" and 2018-06-18 says "+NFLX -TWX". One of those is wrong. | The 2018-06-18 entry is more likely correct (post-AT&T acquisition close 2018-06-15 → TWX delisted 2018-06-15). The 2017-03-20 entry's `removed: TWX` should likely be empty (AVGO was added without paired removal). |

## Reverse-application logic specification

For each event type, when `build_history_table()` walks BACKWARDS from today:

### `rename`
- For all snapshots BEFORE `event.date`: replace `event.to` ticker with `event.from` ticker
- Snapshot count unchanged

### `merger` (multi-from → single-to)
- For all snapshots BEFORE `event.date`: replace `event.to` ticker with the **list** `event.from` (e.g., RTX → both UTX and RTN)
- Snapshot count temporarily increases by `len(from) - 1` for each merger backwards-applied
- The 100-ticker invariant becomes 100 + N for each unwound merger; the validator's tolerance band must allow this

### `spinoff` (single-from → multi-to)
- Inverse of merger. For all snapshots BEFORE `event.date`: replace the **list** `event.to` with `event.from` (single ticker)
- Snapshot count temporarily decreases by `len(to) - 1`

### `removal-via-acquisition`
- For all snapshots BEFORE `event.date`: insert `event.from` ticker (since it was historically present, just not in today's list because it got delisted)
- Snapshot count temporarily increases by 1 for each unwound removal

### Order matters
Walk backwards through ALL events sorted by `date` DESC. Apply each event's reverse-application to all snapshots whose date is `< event.date`. Existing add/remove events use the same backwards-walk pattern; the type-tagged events extend it.

## Validator spot-checks (closes #804 in this PR)

Add to `_validate_table()`:

```python
HISTORICAL_TICKER_CHECKS = [
    # Tier A — operator-verified
    ("2015-03-19", "PCLN", True),    ("2015-03-19", "BKNG", False),
    ("2018-06-18", "BKNG", True),
    ("2015-03-19", "KRFT", True),    ("2015-03-19", "KHC", False),
    ("2015-09-30", "KHC", True),
    ("2015-09-18", "UTX", True),     ("2015-09-18", "RTN", True),    ("2015-09-18", "RTX", False),
    ("2020-12-21", "RTX", True),     ("2020-12-21", "UTX", False),   ("2020-12-21", "RTN", False),
    ("2015-03-19", "EMC", True),     ("2025-03-24", "EMC", False),
    ("2015-03-19", "YHOO", True),    ("2025-03-24", "YHOO", False),
    # Tier B — pending operator approval
    ("2018-06-18", "FB", True),      ("2025-03-24", "FB", False),
    ("2025-03-24", "META", True),
]
```

Each entry: `(snapshot_date, ticker, expected_present)`. Validator iterates and `assert (ticker in snapshot) == expected_present`.

## Coverage check after fix

After regenerating `data/reference/sp100_history.json`:
- `pit.get_data_range()` should still return `(2015-03-19, 2026-04-27)` — date range unchanged
- `pit.get_sp100_at("2015-06-01")` should include PCLN, KRFT (or KHC depending on date relative to 2015-07-06), UTX, RTN, EMC, YHOO — NOT BKNG, KHC-pre-merger, RTX
- `pit.get_all_historical_tickers()` should include the union: PCLN ∪ BKNG, KRFT ∪ KHC, UTX ∪ RTN ∪ RTX, EMC, YHOO, FB ∪ META

## Operator decisions required (BLOCKERS for Developer dispatch)

### Decision 1: Which tier(s) to include in this PR?

- **(a) Tier A only** (5 events, all operator-verified): conservative, ships fast, leaves Tier B for follow-up. Resolves the most-cited gaps (PCLN, KRFT, UTX/RTN, EMC, YHOO).
- **(b) Tier A + B** (~9 events): adds FB→META, possibly DWDP split, CELG removal, S removal. Bigger scope but more thorough.
- **(c) Tier A + B + C** (~12 events): research-heavy; some Tier C items may not even be SP100 (TWTR uncertain, 2024 misc undefined). Probably overscoped for one PR.

**PM recommendation: (a) Tier A only.** Ships #803 fast, gets walk-forward unblocked ASAP. Tier B can land as a follow-up PR after Sprint 1.B kicks off, since Tier B's impact (FB, CELG, S) is mostly post-2018 — less urgent than the Tier A pre-2018 coverage.

### Decision 2: TWX-removed-twice cleanup (#805)?

The existing `_CURATED_CHANGES` has TWX removed at both `2017-03-20` (with `+AVGO`) and `2018-06-18` (with `+NFLX`). One is wrong. Per public record:
- TWX was acquired by AT&T closed 2018-06-14; delisted 2018-06-15
- The 2017-03-20 entry should have `removed: ""` (AVGO was added without paired removal — index size drift is acceptable)

**PM recommendation: fix this in the same PR (5-line change).** Keeps the curated list clean and resolves #805.

### Decision 3: 2022-03-21 `removed: EMRG` — typo?

`{"date": "2022-03-21", "added": "DXCM", "removed": "EMRG"}` — "EMRG" is not a real ticker symbol. Likely a typo for **EMR** (Emerson Electric) or possibly **ERTS** (Electronic Arts, but that's EA now). EMR seems most plausible for a 2022-03 SP100 removal context.

**PM recommendation: investigate during implementation; fix or document. ~10 min of research.**

## Recommended task graph (pending Decision 1)

If Decision 1 = (a) Tier A only:

1. **T1** — Pre-flight committed (PM-direct, ready now). Operator approval of Tier A list closes the gate.
2. **T2** — Schema extension + reverse-application logic (`scripts/build_sp100_history.py`). 5 Tier A events + the type-tagged schema. Includes #805 TWX fix and EMRG investigation if Decision 2/3 = yes.
3. **T3** — Validator spot-checks + regenerate `data/reference/sp100_history.json`. Verify all assertions pass.
4. **T4** — Tests for new logic (synthetic-fixture rename, merger, removal-via-acquisition + integration test against regenerated JSON).
5. **T5** — Docs: scraper docstring update, PR #802 caveat → resolved.

T2 → T3 → T4 sequential (each depends on the previous). T5 parallel with T4.

If Decision 1 = (b) or (c): split T2 into T2a/T2b for Tier A vs Tier B events, parallel batches.

## Strict-rigor receipts (so far)

- ✅ Spec committed as deliverable 0 (PR #806 rule) — `sprint/1.A.x-corp-actions/base` @ `790bb36`
- ✅ Pre-flight committed as deliverable 1 (this file, pending operator gate review)
- 🚫 No skip / xfail / weakening (will apply during implementation)
- 📝 Pre-existing failures from canon doc — to be referenced by Integrator

## Operator action

Read Tier A / B / C tables. Pick a/b/c for Decision 1. Confirm/override Decisions 2 and 3. PM dispatches Developer wave once decisions are settled.
