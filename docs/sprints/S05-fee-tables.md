# S05-fee-tables — Complete historical SEC/TAF fee schedules + deferred S05 items

Branch: `feat/s05-fee-tables`. Follow-up to S05 (PR #7, merged at `2f0b986`).

## Goal

Replace the cost model's dated fee snapshots with complete, primary-source-verified
historical schedules for SEC Section 31 fees and FINRA TAF, and close out the
deferred S05 items that don't belong in S06. The paper lane must not cross
2027-01-01 on the current snapshots (cost functions intentionally raise past
2026-12-31); this sprint removes that cliff for all historical dates.

## CEO decisions feeding this sprint (2026-10-05)

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
3. Encode the full TAF schedule (8 rate/cap periods) with exact effective
   dates + source citations, including the Q4-2026 $0 holiday
   (2026-10-01–2026-12-31). Boundary-date known-answer tests.
4. Restructure `research/costs.py`: move tables to a new
   `research/fee_schedules.py` data module (400-line file limit).
   Make the SEC-charge-date vs TAF-trade-date distinction explicit in the
   API (`as_of` = trade date, optional `charge_date`).
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

## Acceptance

- Every historical date the backtest/simulator can touch returns a verified
  fee or raises; no silent zeros, no invented caps.
- 2027+ behavior: raise with a clear message until the 2027 schedules are
  verified (a new dated decision, not silent carry-forward).
- Frozen `config/incumbent_v1.yaml` untouched (hash verified in checks).

## Results (2026-10-06)

- Research: 33 SEC periods + 8 TAF periods reconstructed from primary
  sources; notes at `~/workspace/research_notes/sec-taf-fee-schedules-20261006-0046/`
  (outside the repo). Key corrections: TAF was not $0 in 2012–2023
  ($0.000119/share, $5.95 cap); no $0 TAF period in 2003; Q4-2026 $0 holiday
  confirmed (FR Doc. 2026-19392); 2027+ fail-closed for both fees.
- Date conventions: SEC = charge date (≈ settlement); TAF = trade date.
  `total_trade_cost` takes `as_of` (trade date) + optional `charge_date`.
- `UnresolvedFeeError` moved to `fee_schedules.py` (re-exported import in
  tests updated); `costs.py` delegates to the new module.
- Tests: 239 passing (was 235); new boundary-date, holiday, historical-rate,
  and charge-date tests.

## Out of scope

- Step 5 simulator / walk-forward harness (S06).
- Step P paper lane + the 3-account execution experiment design.
- Trend/RS classifier definitions (deferred).
- CAT fee schedule (still zero per R06 until a verified schedule exists).
