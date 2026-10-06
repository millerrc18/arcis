# S06-fee-tables — Complete historical SEC/TAF fee schedules + deferred S05 items

Branch: `feat/s05-fee-tables` (opened as S05; renamed S06 per review — see Deviations). Follow-up to S05 (PR #7, merged at `2f0b986`).

Status: complete 2026-10-06; PR #10 open, awaiting Claude Code re-review after corrections.

## Goal

Replace the cost model's dated fee snapshots with complete, primary-source-verified
historical schedules for SEC Section 31 fees and FINRA TAF, and close out the
deferred S05 items. The paper lane must not cross 2027-01-01 on the current
snapshots (cost functions intentionally raise past 2026-12-31); this sprint
removes that cliff for all historical dates.

## CEO decisions feeding this sprint (2026-10-05)

- **D-026:** Absolute Set A sector-RS bands on weighted_excess vs SPY (pp):
  ≥ +5 → 25, 0 to +5 → 15, −5 to 0 → 5, < −5 → 0. This is not a change to a
  preregistered value (the frozen YAML pins only score values [25,15,5,0],
  never the mapping rule); recorded as a PREREGISTRATION.md §5 dated
  amendment, with no trial-ledger row (final).
- **D-027:** Pin pullback lookback = 60 sessions; sector-RS windows = 21/63/126
  sessions. The frozen YAML never specified these; this resolves ambiguity,
  not a prereg change.
- **D-028:** Adopt the Sprint F doc §1.4 legacy band-boundary operators
  (line-cited to `src/ranking/ranker.py`): pullback `-3.0 → 25`, `-8.0 → 25`
  (first-match-wins), `dist_to_sma20 -1.0 → 10`, `volume_ratio 0.8 → 0`
  (strict `<`), `iv_rank 25 → 0` (strict `<`). Supersedes the S05 fail-closed
  boundary raises.
- **Trial ledger:** No row for D-026 (final). §5 amendment suffices.
- **Classifiers:** Deferred — resolve via the S02 legacy archive or explicit
  design later. Unknown trend/RS labels keep raising. (Existing classifier
  research with a candidate MA-stack mapping is preserved in the 2026-10-05
  daily note as evidence, not a decision.)
- **Three paper accounts:** Approved for execution A/B testing (same frozen
  selection; arms differ only in execution). Design lands in Step P, not here.

## Correction to the S05 record

S05's sprint doc claimed the YAML was "silent on -3.0 inclusivity." Wrong:
the Sprint F evaluation doc (`workspace/user/files/INCUMBENT__docs__sprints__sprint_F_evaluation.md`,
§1.4, line-cited to the legacy ranker) records the operators explicitly
(`volume_ratio_20d < 0.8`, `iv_rank < 25`, `[-12, -8)`, `[-8, -3]`,
`in [-5, -1]`). D-028 implements them. Lesson: check the recovery doc's
operator notation, not just the YAML ranges.

## Tasks (≤10 per SCOPE §6.5)

1. Recover the user-supplied SEC/TAF schedule report; independently verify
   every entry against primary sources (SEC fee advisories, FINRA notices).
2. Encode the full Section 31 schedule (33 rate periods) with exact
   effective dates + source citations. Boundary-date known-answer tests.
3. Encode the full TAF schedule (9 rate/cap periods) with exact effective
   dates + source citations, including the 2002–2003 corrections and the
   Q4-2026 $0 holiday (2026-10-01–2026-12-31). Boundary-date known-answer
   tests.
4. Restructure `research/costs.py`: move tables to a new
   `research/fee_schedules.py` data module (400-line file limit).
   Make the SEC-charge-date vs TAF-trade-date distinction explicit in the
   API (`as_of` = trade date; `charge_date` required for sells).
4b. Add formal SCOPE.md decision-table entries for D-027 and D-028, and
    record both in PREREGISTRATION.md §5 as dated post-tag amendments
    (underspecification resolutions, not prereg changes).
5. D-027: pinned session constants + `sector_weighted_excess` validation
   (`0 < s1 < s3 < s6`, equal-length series). Tests.
6. D-028: boundary operators in `strategy/scoring.py` + tests.
7. Align SCOPE D-026 wording ("not a change to a preregistered value") with
   the PREREGISTRATION §5 amendment entry.
8. Full checks (ruff, mypy, ledger, size, hygiene, pytest) green.
9. Push once, open PR, independent quality review, Claude Code review.
10. Merge only on explicit CEO approval.

## Deviations

- **Renamed S05 → S06.** This work was opened as a follow-up to S05 but is
  its own sprint; the branch (`feat/s05-fee-tables`) and PR (#10) keep the
  original name. Next sprint takes S07.
- **Claude Code REJECT (2026-10-05), corrected before merge.** Five
  corrections landed on top of the PR after review: (1) the 2002–2003 TAF
  rows — the $0.0001/$10 announcement was superseded retroactively, so the
  assessed 2002 rate was $0.00005/$5, with $0.0001/$10 only from 2003-09-01;
  (2) `total_trade_cost` now requires `charge_date` for sells instead of
  defaulting it to the trade date; (3) the pre-2000 SEC history was not
  reconstructed — the schedule starts at 2000-01-01 and raises before it;
  (4) the 2021 SEC citation now points at the FY2021 advisory; (5) the
  research-log and CHANGELOG corrections were restated accurately (the old
  code raised for 2012–2023, it never assumed $0; R06's actual error was the
  "2004-2011 was $0.000075" calendar-year claim). The re-audit covered
  21 of 42 rows directly against their cited URLs (all 9 TAF rows; 12 SEC
  rows spanning 2000–2026); the rest are machine-checked against the
  research report.
- **Test count.** 241 tests, all passing locally; 2 conditional tests skip
  where the research-extras pandas is absent.

## Acceptance

- Every historical date the backtest/simulator can touch returns a verified
  fee or raises; no silent zeros, no invented caps.
- 2027+ behavior: raise with a clear message until the 2027 schedules are
  verified (a new dated decision, not silent carry-forward).
- Open item for Step P: the 2026-12-31 SEC window end is a modeling choice,
  not a verified fact — the last row directly re-checked was dated
  2026-10-06, and the FY2026 $20.60 rate ends 60 days after FY2027
  appropriation enactment (unknown date). The paper lane must re-verify
  the SEC rate before trading December 2026 charge dates.
- Frozen `config/incumbent_v1.yaml` untouched (hash verified in checks).

## Results (2026-10-06)

- Research: 33 SEC periods (2000-01-01–2026-12-31) + 9 TAF periods
  (2002-10-01–2026-12-31) reconstructed from primary sources; notes at
  `~/workspace/research_notes/sec-taf-fee-schedules-20261006-0046/`
  (outside the repo). Corrections to R06: calendar-year TAF boundaries
  replaced with effective-date periods; the 2002–2003 TAF rows fixed
  (retroactive $0.00005/$5); pre-2000 SEC history out of scope; 2027+
  fail-closed for both fees.
- Date conventions: SEC = charge date (≈ settlement); TAF = trade date.
  `total_trade_cost` takes `as_of` (trade date) and requires `charge_date`
  for sells — a missing or pre-trade charge date is a caller `ValueError`;
  buys ignore it.
- `UnresolvedFeeError` moved to `fee_schedules.py` (re-exported import in
  tests updated); `costs.py` delegates to the new module.
- Tests: 241 total, all passing locally (2 conditional tests skip without the research-extras
  pandas); new boundary-date, holiday, historical-rate, and charge-date
  tests.

## Out of scope

- Step 5 simulator / walk-forward harness (S07).
- Step P paper lane + the 3-account execution experiment design.
- Trend/RS classifier definitions (deferred).
- CAT fee schedule (still zero per R06 until a verified schedule exists).
